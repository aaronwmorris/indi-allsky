"""Measure repeatable foreground silhouettes in star-aligned night photographs."""
from functools import lru_cache
import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .companion_target_quality import _lights, _sky_positions, frame_star_evidence
from .companion_targets import project_horizontal_pixels, projection_values, rotate_horizontal
from .lens_solver.catalog import loadCatalog


STEP = 0.25  # output bearings, degrees clockwise from north
_COARSE_STEP = 2
_RESOLUTION = 0.5  # internal sampling in altitude and azimuth
_ALT = np.arange(0., 90., _RESOLUTION)
_AZ = np.arange(0., 360., _RESOLUTION)
_BRANCH_ALT = np.arange(0., 90., .125)
_BRANCH_AZ = np.arange(0., 360., STEP)
_CHECK_AZ = np.arange(0., 360., 4.)


def _thumbnail_star_bearings(gray, model):
    """Check for actual bright catalogue stars on this small thumbnail."""
    latitude, longitude = model['location']
    values = model['values']
    alt, vectors, x, y, visible = _sky_positions(
        loadCatalog(mag_limit=4.), latitude + values['LATITUDE_OFFSET'], longitude + values['LONGITUDE_OFFSET'],
        model['observed_at'], values['PRECESSION'], projection_values(model), model['image_size'])
    width, height = model['image_size']
    x, y = np.rint(x * gray.shape[1] / width).astype(int), np.rint(y * gray.shape[0] / height).astype(int)
    use = (visible & (alt > np.radians(16.)) & (x >= 6) & (y >= 6)
           & (x < gray.shape[1] - 6) & (y < gray.shape[0] - 6))
    x, y, alt, vectors = x[use], y[use], alt[use], vectors[use]
    # Point-like excess above the local sky. Displaced controls reject noise,
    # frost texture and bright cloud edges accidentally overlapping catalogue stars.
    light = gray.astype(np.float32)
    signal = light - cv2.GaussianBlur(light, (0, 0), 2.)
    noise = cv2.GaussianBlur(np.abs(signal), (0, 0), 3.)
    peaks = cv2.dilate((signal > np.maximum(3., 4.*noise)).astype(np.uint8),
                       cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    controls = (peaks[y, x-5] + peaks[y, x+5] + peaks[y-5, x] + peaks[y+5, x]) * .25
    found = (peaks[y, x] != 0) & (controls <= .25)
    high = alt > np.radians(30.)
    if high.sum() < 16 or found[high].sum() < max(7, .30 * high.sum()):
        return np.array([])
    return np.degrees(np.arctan2(vectors[found, 1], vectors[found, 0])) % 360.


@lru_cache(maxsize=2)
def _thumbnail_rays(geometry, size):
    model = json.loads(geometry)
    width, height = model['image_size']
    x, y, valid = project_horizontal_pixels(model, np.arange(77.)[:, None], _CHECK_AZ[None, :])
    x, y = x * size[0] / width, y * size[1] / height
    valid &= (x >= 2) & (y >= 2) & (x < size[0] - 2) & (y < size[1] - 2)
    return x.astype('f'), y.astype('f'), valid


def horizon_signature(path, model):
    """JSON-compatible coarse night silhouette or None when the scene is not comparable."""
    try:
        if _lights(model['location'], model['observed_at'])[0] > -12.:
            return None
        with Image.open(path) as image:
            if image.size != tuple(model['image_size']):
                return None
            image.draft('L', (160, 160))  # JPEG decoder uses its 1/8 native scale when possible
            image.thumbnail((480, 480), getattr(Image, 'Resampling', Image).BILINEAR)
            gray = np.asarray(image.convert('L'))
        stars = _thumbnail_star_bearings(gray, model)
        if not len(stars):
            return None
        geometry = json.dumps({k: model[k] for k in ('values', 'location', 'image_size')}, sort_keys=True)
        x, y, valid = _thumbnail_rays(geometry, gray.shape[::-1])
    except (OSError, ValueError, KeyError, TypeError, OverflowError, Image.DecompressionBombError, cv2.error):
        return None
    polar = cv2.remap(cv2.medianBlur(gray, 3), x, y, cv2.INTER_LINEAR)
    # Normalize to the local upper sky, rather than comparing raw pixel values
    # from different exposures or responding to stars moving near the horizon.
    sky = np.median(polar[48:73], axis=0)
    dark = valid & (polar < .64 * sky)
    tiled = np.tile(dark.astype(np.uint8), (1, 3))
    _, labels = cv2.connectedComponents(tiled)
    n = len(_CHECK_AZ)
    first = np.argmax(valid, axis=0)
    cols = np.arange(n)
    seeds = np.unique(labels[first, cols+n])
    ground = np.isin(labels[:, n:2*n], seeds[seeds > 0]) & valid
    top = len(polar) - 1 - np.argmax(ground[::-1], axis=0)
    row = np.clip(top, 2, len(polar) - 5)
    below = np.median(polar[row + np.array([[-2], [-1], [0]]), cols], axis=0)
    above = np.median(polar[row + np.array([[1], [2], [3]]), cols], axis=0)
    gradients = np.diff(polar[row + np.arange(-1, 3)[:, None], cols].astype(float), axis=0)
    local_stars = (np.abs((_CHECK_AZ[:, None] - stars + 180.) % 360. - 180.) < 18.).any(axis=1)
    clear = (ground.any(axis=0) & (top == row) & (row >= first + 2)
             & valid[row+3, cols] & valid[48:73].all(axis=0) & (sky >= 8) & (sky <= 205)
             & (above - below >= np.maximum(4., .27*above)) & (gradients.max(axis=0) >= np.maximum(3., .14*above))
             & (above >= .65*sky)
             & (above < 2.4*sky + 5) & local_stars)
    if clear.sum() < 18:
        return None
    return {'version': 1, 'edges': [int(r + 1) if ok else None for r, ok in zip(row, clear)]}


def significant_horizon_change(reference, candidate):
    """True for a coherent shift, False for ordinary variation, None for insufficient evidence."""
    if not isinstance(reference, dict) or not isinstance(candidate, dict):
        return None
    if reference.get('version') != 1 or candidate.get('version') != 1:
        return None
    try:
        a, b = (np.asarray(s['edges'], dtype=float) for s in (reference, candidate))
    except (TypeError, KeyError, ValueError):
        return None
    if a.shape != _CHECK_AZ.shape or b.shape != a.shape:
        return None
    comparable = np.isfinite(a) & np.isfinite(b)
    if comparable.sum() < max(15, .45 * min(np.isfinite(a).sum(), np.isfinite(b).sum())):
        return None
    delta = b - a
    # Three of four neighbouring bearings must agree on a rise or fall of six
    # degrees. A stray limb, overlay or single clipped sector cannot trigger it.
    for shifted in (delta >= 6., delta <= -6.):
        if (sum(np.roll(shifted.astype(int), i) for i in range(4)) >= 3).any():
            return True
    return False


def _unwrap(gray, model):
    """Sample the photograph in physical azimuth/altitude, retaining the sensor crop."""
    width, height = model['image_size']
    x, y, valid = project_horizontal_pixels(model, _ALT[:, None], _AZ[None, :])
    x = x * gray.shape[1] / width
    y = y * gray.shape[0] / height
    valid = valid & (x >= 2) & (y >= 2) & (x < gray.shape[1] - 2) & (y < gray.shape[0] - 2)
    polar = cv2.remap(gray, x.astype('f'), y.astype('f'), cv2.INTER_LINEAR)
    return polar, valid


def _outline(polar, valid, star_az, star_alt, sky_level):
    """Highest dark silhouette attached to the lower image boundary at each bearing."""
    # Suppress stars, tiny caption strokes and pixel noise before tracing edges.
    light = cv2.medianBlur(polar, 3)
    dark = (valid & (light < 0.58 * sky_level)).astype(np.uint8)
    # Connect foliage across small gaps. Three copies preserve connected components
    # that straddle the north meridian. Pixels outside the image cannot seed land.
    cols = len(_AZ)
    extended = np.tile(dark, (1, 3))
    extended = cv2.morphologyEx(extended, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    extended &= np.tile(valid, (1, 3)).astype(np.uint8)
    _, labels = cv2.connectedComponents(extended)
    bottom = np.tile(np.argmax(valid, axis=0), 3)
    seeds = labels[bottom, np.arange(3 * cols)]
    grounded = np.isin(labels[:, cols:2*cols], np.unique(seeds[seeds != 0]))
    tops = np.where(grounded.any(axis=0), len(_ALT) - 1 - np.argmax(grounded[::-1], axis=0), -1)

    edges = np.full(360 // _COARSE_STEP, np.nan)
    floors = edges.copy()
    for index, az in enumerate(range(0, 360, _COARSE_STEP)):
        center = int(az / _RESOLUTION)
        band = np.arange(center - 2, center + 3) % cols
        if not valid[-1, band].all():  # no continuous view up to the zenith
            continue
        first = bottom[band].max()
        if first >= len(_ALT) - 10:
            continue
        top = int(np.sort(tops[band])[-2])  # require a feature on at least two rays
        # Ground immediately below the outline, followed by a clear step to sky.
        if top >= first and top + 8 < len(_ALT):
            below = np.percentile(light[max(first, top-4):top+1, band], 30)
            above = np.median(light[top+2:top+9, band])
            gradients = np.diff(light[max(first, top-3):top+5, band].astype(float), axis=0)
            sharp = np.max(np.percentile(gradients, 70, axis=1)) >= max(3., 0.13 * sky_level)
            if sharp and above >= max(below + 5, 0.67 * sky_level) and below < 0.65 * sky_level:
                edges[index] = _ALT[top] + _RESOLUTION

        # Even when the lower skyline is ambiguous, a trajectory high above it
        # can remain usable. Find uninterrupted sky extending toward the zenith,
        # then require a catalogue star in this band; never infer the horizon
        # from the image crop or promise visibility below this supporting star.
        column = np.median(light[:, band], axis=1)
        suspect = (column < 0.67 * sky_level) | (column > 3 * sky_level + 10)
        sustained = np.flatnonzero(suspect[:-2] & suspect[1:-1] & suspect[2:])
        clear_from = max(first, top + 2, int(sustained[-1]) + 4 if len(sustained) else 0)
        if clear_from < len(_ALT):
            nearby = (np.abs((star_az - az + 180) % 360 - 180) <= 4) & (star_alt >= _ALT[clear_from])
            if nearby.any():
                floors[index] = math.ceil(np.min(star_alt[nearby]))
    return edges, floors


@lru_cache(maxsize=1)
def _branch_map(geometry, size):
    """Nearest native-image pixels. Project in strips to bound peak memory on the Pi."""
    model = json.loads(geometry)
    width, height = model['image_size']
    indexes = np.full((len(_BRANCH_ALT), len(_BRANCH_AZ)), -1, dtype=np.int32)
    for start in range(0, len(_BRANCH_ALT), 48):
        rows = slice(start, start + 48)
        x, y, visible = project_horizontal_pixels(model, _BRANCH_ALT[rows, None], _BRANCH_AZ[None, :])
        ix = np.rint((x + .5) * size[0] / width - .5).astype(np.int32)
        iy = np.rint((y + .5) * size[1] / height - .5).astype(np.int32)
        visible &= (ix >= 2) & (iy >= 2) & (ix < size[0] - 2) & (iy < size[1] - 2)
        indexes[rows][visible] = (iy * size[0] + ix)[visible]
    return indexes


def _branch_tops(gray, indexes, sky_level):
    """Resolve dark, grounded limbs before resampling, including branches with sky beneath."""
    # A local dark ridge can persist where a thin branch only partially covers a
    # pixel. A global threshold alone would lose that branch against brighter sky.
    smooth = cv2.GaussianBlur(gray, (3, 3), .55)
    local = cv2.morphologyEx(smooth, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    ridge = (local - smooth >= max(6., .23 * sky_level)) & (smooth < .73 * local)
    dark = ((smooth < .58 * sky_level) | ridge).astype(np.uint8)
    # Bridge a single sampling gap along a limb, without filling open sky below it.
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    # Caption outlines and glare can look like dark ridges. Exclude the immediate
    # surroundings of bright ink and saturated lamps from candidate components.
    ink = (gray > min(240., max(64., 2.1 * sky_level))).astype(np.uint8)
    near_ink = cv2.dilate(ink, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    dark[near_ink != 0] = 0
    count, components = cv2.connectedComponents(dark)
    valid = indexes >= 0
    first = np.argmax(valid, axis=0)
    cols = np.arange(indexes.shape[1])
    seeds = np.unique(components.ravel()[indexes[first, cols][valid[first, cols]]])
    supported = np.zeros(count, dtype=bool)
    supported[seeds] = True
    supported[0] = False
    land = supported[components.ravel()[indexes]] & valid
    top = len(_BRANCH_ALT) - 1 - np.argmax(land[::-1], axis=0)
    base = np.clip(top, 0, len(_BRANCH_ALT) - 10)
    # Contrast immediately above the tip distinguishes a sharp foreground edge
    # from a gradual cloud/vignetting threshold or an edge at the sensor crop.
    light = smooth.ravel()[indexes]
    above = np.median(light[base + np.array([[3], [5], [8]]), cols], axis=0)
    below = np.minimum(light[base, cols], light[np.maximum(first, base-1), cols])
    reliable = (land.any(axis=0) & (base == top) & (top > first + 1) & valid[-1]
                & valid[base+8, cols] & (above >= .65 * sky_level) & (above < 3 * sky_level + 10)
                & (above - below.astype(float) >= max(6., .24 * sky_level)))
    return np.where(reliable, _BRANCH_ALT[base] + .125, np.nan)


@lru_cache(maxsize=16)
def _measure_frame(path, revision, model_json):
    """Cache the angular measurements, never archived image buffers."""
    model = json.loads(model_json)
    evidence = frame_star_evidence(path, model, max_sun_altitude=-12.)
    if evidence is None:
        return None
    vectors, alts, mags, hits, controls, backgrounds = evidence
    reference = (alts >= 30.) & (mags <= 5.)
    true_hits = (hits != 0) & (controls <= .25)
    usable = reference & true_hits
    if (usable.sum() < 25 or reference.sum() < 40 or
            float((hits[reference] - controls[reference]).mean()) < .40):
        return None  # indoor, overcast or an unreliable alignment
    sky_level = float(np.median(backgrounds[usable]))
    if not 10 <= sky_level <= 205:
        return None
    with Image.open(path) as image:
        if image.size != tuple(model['image_size']):
            return None
        image.draft('L', (1200, 1000))
        bilinear = getattr(Image, 'Resampling', Image).BILINEAR
        image.thumbnail((1920, 1920), bilinear)
        gray = np.asarray(image.convert('L'))
        image.thumbnail((1120, 1120), bilinear)
        polar, valid = _unwrap(np.asarray(image.convert('L')), model)
    stars = vectors[true_hits]
    az = np.arctan2(stars[:, 1], stars[:, 0])
    lat = np.radians(model['location'][0])
    values = model['values']
    sky_alt, sky_az = rotate_horizontal(np.radians(alts[true_hits]), az,
                                        lat + np.radians(values['LATITUDE_OFFSET']), lat,
                                        -np.radians(values['LONGITUDE_OFFSET']))
    edges, floors = _outline(polar, valid, np.degrees(sky_az) % 360, np.degrees(sky_alt), sky_level)
    geometry = json.dumps({k: model[k] for k in ('values', 'location', 'image_size')}, sort_keys=True)
    tips = _branch_tops(gray, _branch_map(geometry, gray.shape[::-1]), sky_level)
    return edges, floors, tips


def _upper_slopes(values):
    """Smallest periodic upper bound with at most 4° vertical change per degree of bearing."""
    ring = np.tile(values, 3)
    rise = np.arange(len(ring)) * (4. * STEP)
    left = np.maximum.accumulate(ring + rise) - rise
    right = (np.maximum.accumulate(ring[::-1] + rise) - rise)[::-1]
    return np.maximum(left, right)[len(values):2*len(values)]


def _estimated_envelope(heights, floors):
    """Continuous planning estimate around the station, separate from verified edges."""
    seen = np.flatnonzero(np.isfinite(heights))
    size = len(heights)
    # One tree on one side cannot describe a whole station. Require independent
    # bearings around the site, while allowing a wide sector to have no visible rim.
    if len(seen) < 3 or np.diff(np.r_[seen, seen[0] + size]).max() * STEP > 225.:
        return None
    if len(np.unique((seen * STEP // 45.).astype(int))) < 3:
        return None
    estimate = np.interp(np.arange(size), seen, heights[seen], period=size)
    # Join tips across notches up to three degrees wide. The slope bound keeps
    # narrow but repeatable branches while avoiding radial lines through open sky.
    width = 2 * round(1.5 / STEP) + 1
    padded = np.pad(estimate, width, mode='wrap')[None, :]
    closed = cv2.morphologyEx(padded, cv2.MORPH_CLOSE, np.ones((1, width), np.uint8))
    estimate = _upper_slopes(closed[0, width:-width])
    # Where terrain cannot be seen, a confirmed star is an upper bound. Spread
    # such a bound gently into its neighbouring bearings instead of creating a notch.
    constrained = ~np.isfinite(heights) & np.isfinite(floors)
    if constrained.any():
        ceiling = -_upper_slopes(np.where(constrained, -floors, -np.inf))
        # Star support spans a small band of bearings; a high branch repeatedly
        # seen on the adjacent ray is stronger evidence at the edge of that band.
        tips = _upper_slopes(np.where(np.isfinite(heights), heights, -np.inf))
        estimate = np.maximum(tips, np.minimum(estimate, ceiling))
    return np.round(np.clip(estimate, 0., 90.), 3).tolist()


def measure_horizon(frames):
    """Return the measured skyline and separately the lower limits of visible sky.

    One explicitly supplied image yields an initial planning estimate only. For
    repeatable terrain, supply two or three images from the same verified setup,
    taken at least two minutes apart within two hours.
    """
    measurements = []
    geometry = None
    stamps = []
    frames = tuple(frames)
    initial = len(frames) == 1
    for path, model in frames:
        try:
            key = (model['id'], tuple(model['image_size']), tuple(model['location']), projection_values(model))
            if geometry is not None and key != geometry:
                return None
            geometry = key
            stamp = model['observed_at']
            if not math.isfinite(stamp) or any(abs(stamp - other) < 120 for other in stamps):
                continue
            path = Path(path)
            stat = path.stat()
            essential = {k: model[k] for k in ('values', 'location', 'image_size', 'observed_at')}
            measurement = _measure_frame(str(path), (stat.st_mtime_ns, stat.st_size), json.dumps(essential, sort_keys=True))
            if measurement is not None:
                measurements.append(measurement)
                stamps.append(stamp)
            if len(measurements) == 3:
                break
        except (OSError, ValueError, KeyError, TypeError, Image.DecompressionBombError, cv2.error):
            continue
    if not measurements or (not initial and len(measurements) < 2) or max(stamps) - min(stamps) > 7200:
        return None

    broad, limits, tips = (np.stack(values) for values in zip(*measurements))
    broad = np.where(np.ptp(broad, axis=0) <= 2., broad.max(axis=0), np.nan)
    lower = limits.max(axis=0)
    # Interpolation requires evidence on both sides. A cropped or unverified ray
    # cannot acquire a physical horizon from just one neighbouring sector.
    pos = _BRANCH_AZ / _COARSE_STEP
    left = pos.astype(int)
    right = np.ceil(pos).astype(int) % len(broad)
    coarse = broad[left] + (pos - left) * (broad[right] - broad[left])
    floors = np.maximum(lower[left], lower[right])
    if initial:
        tip = tips[0]
        neighbors = np.fmax(np.roll(tip, 1), np.roll(tip, -1))
        # One isolated high pixel has no independent confirmation on the first
        # exposure. A continuous limb may still contribute to the planning curve.
        heights = np.fmax(coarse, np.where(neighbors >= tip - 3., tip, np.nan))
        envelope = _estimated_envelope(heights, floors)
        if envelope is None:
            return None
        return {'step_deg': STEP, 'altitudes': [None] * len(heights), 'image_floor': [None] * len(heights),
                'envelope': envelope, 'frames': 1, 'quality': 'estimated'}
    ordered = np.sort(np.where(np.isfinite(tips), tips, -np.inf), axis=0)
    highest, second = ordered[-1], ordered[-2]
    # A poorly exposed frame can lose twig tips. The highest edge must recur,
    # even if a third image sees only the lower part of the same silhouette.
    stable = np.isfinite(second) & (second >= highest - .875)
    # A single tall feature in an otherwise repeatable sector could be a cloud.
    # Do not place a physical line below that unresolved feature.
    heights = np.where(stable, highest, np.where(highest <= coarse + 1., coarse, np.nan))
    floors = np.where(np.isfinite(heights) | (floors < highest), np.nan, floors)
    if not (np.isfinite(heights).any() or np.isfinite(floors).any()):
        return None
    def nullable(values):
        return [float(v) if np.isfinite(v) else None for v in values]
    return {'step_deg': STEP, 'altitudes': nullable(heights), 'image_floor': nullable(floors),
            'envelope': _estimated_envelope(heights, floors), 'frames': len(measurements), 'quality': 'repeated'}
