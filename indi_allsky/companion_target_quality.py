"""Estimate local star visibility in a saved, astrometrically aligned exposure."""
from datetime import datetime, timezone
from functools import lru_cache
import math
from pathlib import Path

import cv2
import ephem
import numpy as np
from PIL import Image

from .companion_targets import projection_values
from .lens_solver.catalog import loadCatalog
from .lens_solver.projection import cameraAltAz, precessCatalog, predictAltAz, projectToPixels


FIELD_RADIUS = 12.0  # degrees around the target
MIN_ALTITUDE = 18.0
THUMBNAIL_SIZE = 1400


def _result(state, reason, matched=0, expected=0):
    return {'state': state, 'reason': reason, 'matched': int(matched), 'expected': int(expected)}


def _unit_vectors(alt, az):
    return np.column_stack((np.cos(alt)*np.cos(az), np.cos(alt)*np.sin(az), np.sin(alt)))


def _sky_positions(catalog, latitude, longitude, timestamp, precession, params, size):
    dated = precessCatalog(catalog, timestamp) if precession else catalog
    alt, az = predictAltAz(dated, latitude, longitude, timestamp)
    x, y = projectToPixels(alt, az, params[:7], *size,
                           lens_altitude=params[7], pointing_azimuth=params[8])
    lens_alt, _ = cameraAltAz(alt, az, params[7], params[8])
    visible = ((lens_alt > 0) & (x >= 0) & (x < size[0]) & (y >= 0) & (y < size[1]))
    return alt, _unit_vectors(alt, az), x, y, visible


def _lights(location, timestamp):
    observer = ephem.Observer()
    observer.lat, observer.lon = map(math.radians, location)
    observer.date = datetime.fromtimestamp(timestamp, timezone.utc).replace(tzinfo=None)
    observer.pressure = 0
    moon = ephem.Moon(observer)
    direction = _unit_vectors(moon.alt, moon.az)[0] if moon.alt > 0 else None
    return math.degrees(ephem.Sun(observer).alt), direction


@lru_cache(maxsize=4)
def _frame_stars(path, revision, size, latitude, longitude, stamp, precession, params, moon_vector):
    # The cached result contains catalogue measurements only, never full images.
    with Image.open(path) as image:
        if image.size != size:
            raise ValueError('Image dimensions do not match alignment.')
        image.draft('L', (THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        image.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE), getattr(Image, 'Resampling', Image).BILINEAR)
        gray = np.asarray(image.convert('L'))
    height, width = gray.shape
    # Project more stars than the solver fits. Here the geometry is fixed;
    # the same exposure determines which magnitudes this camera can see.
    stars = loadCatalog(mag_limit=5.5)
    alt, vectors, x, y, visible = _sky_positions(stars, latitude, longitude, stamp, precession, params, size)
    x = np.rint(x * width / size[0]).astype(int)
    y = np.rint(y * height / size[1]).astype(int)
    radius = max(2, min(7, round(params[3] * width / size[0] * 0.004)))
    shift = 3 * radius + 2
    margin = shift + radius + 2
    valid = (visible & (alt > np.radians(8)) & (x >= margin) & (x < width-margin)
             & (y >= margin) & (y < height-margin))
    if moon_vector is not None:
        valid &= np.dot(vectors, moon_vector) < math.cos(math.radians(16))
    x, y = x[valid], y[valid]

    # Smooth small noise spikes, then look for compact positive sources near the
    # predicted pixels. Offset apertures measure accidental matches on branches,
    # captions, dense star fields, bright cloud edges and noisy frames.
    smoothed = cv2.GaussianBlur(gray.astype(np.float32), (0, 0), 0.8)
    background = cv2.GaussianBlur(smoothed, (0, 0), 4.5)
    signal = smoothed - background
    noise = cv2.GaussianBlur(np.abs(signal), (0, 0), 6.)
    detected = (signal > np.maximum(3.5, 4.5 * noise)).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*radius + 1, 2*radius + 1))
    hits = cv2.dilate(detected, kernel)
    controls = (hits[y, x-shift] + hits[y, x+shift] + hits[y-shift, x] + hits[y+shift, x]) / 4.
    return vectors[valid], np.degrees(alt[valid]), stars[valid, 2], hits[y, x], controls, background[y, x]


def frame_star_evidence(path, model, *, max_sun_altitude=None):
    """Catalogue positions, matches and chance controls in this aligned photograph."""
    path = Path(path)
    stat = path.stat()
    lat, lon = model['location']
    values = model['values']
    stamp = model['observed_at']
    solar_altitude, moon = _lights((lat, lon), stamp)
    if max_sun_altitude is not None and solar_altitude > max_sun_altitude:
        return None
    return _frame_stars(str(path), (stat.st_mtime_ns, stat.st_size), tuple(model['image_size']),
                        lat + values['LATITUDE_OFFSET'], lon + values['LONGITUDE_OFFSET'], stamp,
                        values['PRECESSION'], projection_values(model), None if moon is None else tuple(moon))


def _classify(catalog, direction, altitude):
    vectors, altitudes, mags, hits, controls, background = catalog
    cosine = np.dot(vectors, direction)
    around = cosine >= math.cos(math.radians(FIELD_RADIUS))
    # Compare to the same image at similar airmass, outside the target area.
    reference = (cosine < math.cos(math.radians(FIELD_RADIUS + 4))) & (np.abs(altitudes - altitude) < 22)
    for limit in (5.5, 5., 4.5, 4., 3.5):
        comparison = reference & (mags <= limit)
        if comparison.sum() < 20:
            continue
        chance = controls[comparison].mean()
        if chance >= .35:
            continue
        # A faint unrelated star can land inside the match radius in crowded
        # parts of the Milky Way. Subtract the offset-aperture coincidence rate.
        efficiency = (hits[comparison].mean() - chance) / (1 - chance)
        if efficiency >= .60:
            break
    else:
        return _result('unknown', 'Too few reliable star matches elsewhere in this exposure.')

    local = around & (mags <= limit)
    count, found = local.sum(), hits[local].sum()
    if count < 6:
        return _result('unknown', 'Too few reference stars near this target.', found, count)
    local_chance = controls[local].mean()
    if local_chance >= .35:
        return _result('unknown', 'Too much structure or noise around the expected stars.', found, count)
    sky = np.median(background[local])
    if sky >= 220 or (sky <= 2 and found < 3):
        return _result('unknown', 'Target field is clipped, masked or too dark to measure.', found, count)
    fraction = max(0., (found / count - local_chance) / (1 - local_chance))
    if fraction >= max(.60, .80 * efficiency) and found >= 5:
        return _result('clear', 'Most expected stars are visible in the target field.', found, count)
    if fraction <= .25 * efficiency and count * efficiency >= 5:
        return _result('obscured', 'Few expected stars are visible compared with other fields at this altitude.',
                       found, count)
    reference_sky = np.median(background[comparison])
    if (found >= 2 and fraction < .75 * efficiency and count * efficiency - found >= 2.5
            and sky > max(reference_sky * 1.20, reference_sky + 4)):
        return _result('thin_cloud', 'Fewer stars and a brighter background than comparable sky in this frame.',
                       found, count)
    return _result('unknown', 'The local star count and background are inconclusive.', found, count)


def assess_targets(path, model, coordinates, *, night, exposure, gain):
    """One evidence-based estimate per J2000 target, for this exposure only.

    A same-image reference shares exposure, gain and image processing. A wholly
    starless frame supplies no baseline to distinguish clouds from equipment
    problems. A clear classification means visible stars, not a calibrated
    measurement of telescope transparency.
    """
    def unknown(reason):
        return [_result('unknown', reason) for _ in coordinates]

    if not coordinates:
        return []
    if not night:
        return unknown('Daytime exposure.')
    if not model or not model.get('location') or model.get('observed_at') is None:
        return unknown('A frame-specific star alignment is required.')
    if path is None:
        return unknown('The local exposure is unavailable.')
    if (exposure is None or gain is None or not math.isfinite(exposure)
            or exposure <= 0 or not math.isfinite(gain)):
        return unknown('Exposure or gain is unavailable.')

    try:
        size = tuple(model['image_size'])
        latitude, longitude = model['location']
        stamp = model['observed_at']
        sun_alt, moon = _lights((latitude, longitude), stamp)
        if sun_alt > -12:
            return unknown('The sky is too bright for a reliable star comparison during twilight.')
        params = projection_values(model)
        values = model['values']
        latitude += values['LATITUDE_OFFSET']
        longitude += values['LONGITUDE_OFFSET']
        precession = values['PRECESSION']
        alt, vectors, x, y, visible = _sky_positions(np.asarray(coordinates, dtype=float),
                                                     latitude, longitude, stamp, precession, params, size)
        margin = .025 * params[3]
        near_edge = (x < margin) | (y < margin) | (x >= size[0]-margin) | (y >= size[1]-margin)
        catalog = frame_star_evidence(path, model)
    except (OSError, ValueError, KeyError, TypeError, Image.DecompressionBombError, cv2.error):
        return unknown('The saved image or its frame geometry could not be read.')
    result = []
    for direction, altitude, in_image, edge in zip(vectors, np.degrees(alt), visible, near_edge):
        if not in_image or altitude <= 0:
            result.append(_result('unknown', 'Target is outside the visible sky in this frame.'))
        elif altitude < MIN_ALTITUDE:
            result.append(_result('unknown', 'Target is too close to the horizon.'))
        elif edge:
            result.append(_result('unknown', 'Target is too close to the edge of the image.'))
        elif moon is not None and np.dot(direction, moon) > math.cos(math.radians(18)):
            result.append(_result('unknown', 'Moon glare may affect the target field.'))
        else:
            result.append(_classify(catalog, direction, altitude))
    return result
