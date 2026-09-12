"""Optional empirical correction after a reliable catalogue match.

Fit a small, smooth 2-D displacement field, not an image resampling operation.
Coordinates and displacements are measured in reference-circle radii. The
same polynomial and boundary taper are implemented in virtualsky-calibration.js.
"""
import hashlib
import json

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial import cKDTree, ConvexHull, QhullError

from .projection import predictAltAz, projectToPixels, cameraAltAz, RADIAL_MIN, RADIAL_MAX


TAPER = 0.15  # fade to the original mapping outside the supported rectangle
MIN_PAIRS = 60


def pipelineSignature(config):
    keys = ('IMAGE_ROTATE', 'IMAGE_ROTATE_ANGLE', 'IMAGE_ROTATE_KEEP_SIZE',
            'IMAGE_FLIP_H', 'IMAGE_FLIP_V', 'IMAGE_CROP_ROI',
            'IMAGE_CROP_IMAGE_CIRCLE', 'IMAGE_SCALE', 'IMAGE_BORDER',
            'LENS_IMAGE_CIRCLE', 'LENS_OFFSET_X', 'LENS_OFFSET_Y')
    return hashlib.sha256(json.dumps([config.get(k) for k in keys],
                                    sort_keys=True).encode()).hexdigest()


def _basis(xy):
    u, v = xy.T
    return np.column_stack([np.ones(len(u)), u, v, u*u, u*v, v*v,
                            u*u*u, u*u*v, u*v*v, v*v*v])


def displacement(xy, model):
    bounds = np.asarray(model['bounds'])
    outside = np.maximum(bounds[:2]-xy, xy-bounds[2:])
    t = np.clip(outside / TAPER, 0, 1)
    weight = np.prod(1-t*t*(3-2*t), axis=1)
    # The existing fisheye renderer uses the front hemisphere. Do not let a
    # polynomial extrapolate into unused corners outside that reference circle.
    t = np.clip((np.linalg.norm(xy, axis=1)-1) / TAPER, 0, 1)
    weight *= 1-t*t*(3-2*t)
    return (_basis(xy) @ np.asarray(model['coefficients'])) * weight[:, None]


def _mappingBounds(model):
    # Bound the displacement gradient, including the taper. A contraction
    # makes the inverse iteration reliable and excludes folding of the map.
    bounds = np.asarray(model['bounds'])
    u = np.linspace(bounds[0]-TAPER, bounds[2]+TAPER, 49)
    v = np.linspace(bounds[1]-TAPER, bounds[3]+TAPER, 49)
    xy = np.array(np.meshgrid(u, v)).reshape(2, -1).T
    delta = displacement(xy, model)
    jac = np.stack([(displacement(xy+step, model)-displacement(xy-step, model))/2e-5
                    for step in ([1e-5, 0], [0, 1e-5])], axis=-1)
    return np.max(np.linalg.norm(delta, axis=1)), np.max(np.linalg.norm(jac, axis=(1, 2)))


def _safeMapping(model):
    distance, gradient = _mappingBounds(model)
    return distance <= 0.06 and gradient < 0.45


def validateCalibration(model):
    """Reject malformed/unbounded saved or submitted models before rendering."""
    try:
        if not isinstance(model, dict) or type(model.get('version')) is not int or model['version'] not in (1, 2):
            return False
        for key, shape in [('coefficients', (10, 2)), ('bounds', (4,)),
                           ('geometry', (10 if model['version'] == 2 else 8,)),
                           ('image_size', (2,)), ('context', (3,))]:
            a = np.asarray(model[key])
            if (a.shape != shape or a.dtype.kind not in 'ifu' or not np.isfinite(a).all()
                    or any(isinstance(v, bool) for v in np.asarray(model[key], dtype=object).flat)):
                return False
        if model['version'] == 2 and (not RADIAL_MIN <= model['geometry'][8] <= RADIAL_MAX
                                      or model['geometry'][9] not in (0, 1)):
            return False
        bounds = np.array(model['bounds'])
        if (np.max(np.abs(model['coefficients'])) > 1 or np.max(np.abs(bounds)) > 3
                or np.any(bounds[2:]-bounds[:2] < 0.15)
                or not all(1 <= x <= 30000 for x in model['image_size'])):
            return False
        if not isinstance(model.get('pipeline'), str) or len(model['pipeline']) != 64:
            return False
        if not isinstance(model.get('camera_uuid'), str) or len(model['camera_uuid']) > 64:
            return False
        # Keep the schema bounded; diagnostics are generated as a short string.
        if set(model) != {'version', 'coefficients', 'bounds', 'geometry', 'image_size',
                          'context', 'pipeline', 'camera_uuid', 'summary'}:
            return False
        if not isinstance(model['summary'], str) or len(model['summary']) > 500:
            return False
        return bool(_safeMapping(model))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def _pairs(predicted, detected, radius):
    if len(predicted) < 2 or len(detected) < 2:
        return np.array([], dtype=int), np.array([], dtype=int)
    distance, index = cKDTree(detected).query(predicted, k=2)
    reverse = cKDTree(predicted).query(detected)[1]
    keep = ((distance[:, 0] < radius) & (distance[:, 0] < 0.5*distance[:, 1])
            & (reverse[index[:, 0]] == np.arange(len(predicted))))
    return np.flatnonzero(keep), index[keep, 0]


def fitCorrection(predicted, detected, expected, radius):
    """Inputs use circle-radius units. Expected points sample usable sky.

    Catalogue indices select a fixed validation subset, never used for fitting
    or reacquiring training matches. Masks limit expected coverage, not merely
    the number of detections. No rim detection or square-sensor assumption.
    """
    ids, matches = _pairs(predicted, detected, radius)
    best = None
    reason = 'Too few reliable stars for distortion calibration.'
    for degree in (2, 3):
        count = 6 if degree == 2 else 10
        current_ids, current_matches = ids.copy(), matches.copy()
        for iteration in range(2):
            train = current_ids % 4 != 0
            check = ~train
            if len(current_ids) < MIN_PAIRS or check.sum() < 15 or train.sum() < 3*count:
                break
            source = predicted[current_ids]
            target = detected[current_matches]
            lo, hi = source.min(axis=0), source.max(axis=0)
            if np.any(hi-lo < 0.15):
                reason = 'Matched stars cover too narrow an area.'
                break
            try:
                hull = ConvexHull(source[train])
            except QhullError:
                reason = 'Matched stars cover too narrow an area.'
                break
            # Expand by a small match-scale margin, not to an assumed full circle.
            inside = np.all(expected @ hull.equations[:, :2].T
                            + hull.equations[:, 2] <= 0.05, axis=1)
            if len(expected) == 0 or inside.mean() < 0.75:
                reason = 'Stars do not cover enough of the unmasked sky; try a clearer image.'
                break
            design = _basis(source[train])[:, :count]
            if np.linalg.cond(design) > 1000:
                reason = 'The distortion fit is poorly constrained by these stars.'
                break
            target_delta = target[train]-source[train]
            fit = least_squares(lambda c: (design @ c.reshape(count, 2)-target_delta).ravel(),
                                np.zeros(count*2), loss='soft_l1', f_scale=0.001,
                                max_nfev=60)
            coeff = np.zeros((10, 2))
            coeff[:count] = fit.x.reshape(count, 2)
            model = dict(version=1, coefficients=coeff.tolist(), bounds=[*lo, *hi])
            if fit.success:
                # A useful fit can just exceed the limit where the boundary
                # taper fades it out. Reduce its strength, then validate that
                # actual correction; never relax the displacement/folding limits.
                distance, gradient = _mappingBounds(model)
                strength = min(1., 0.99*0.06/max(distance, 1e-12), 0.99*0.45/max(gradient, 1e-12))
                model['coefficients'] = (coeff*strength).tolist()
            if not fit.success or not _safeMapping(model):
                reason = 'The proposed correction is too large or unstable.'
                break
            before = np.linalg.norm(target[check]-source[check], axis=1)
            after = np.linalg.norm(target[check]-source[check]
                                   - displacement(source[check], model), axis=1)
            old_rms, new_rms = np.sqrt(np.mean(before**2)), np.sqrt(np.mean(after**2))
            # Judge the same unused stars before and after; do not improve the
            # score by dropping validation outliers or counting only fit stars.
            if (new_rms < 0.8*old_rms and old_rms-new_rms > 0.0003
                    and np.percentile(after, 90) <= np.percentile(before, 90)
                    and (best is None or new_rms < best[1]['after']*0.9)):
                best = model, dict(before=float(old_rms), after=float(new_rms),
                                   validation=int(check.sum()), matches=len(current_ids),
                                   coverage=float(inside.mean()))
            else:
                reason = 'Distortion correction did not improve independent validation enough.'
            if iteration == 0:
                # Expand training matches with the learned map. Keep the original
                # validation identities/targets fixed so their errors cannot select matches.
                new_ids, new_matches = _pairs(predicted+displacement(predicted, model), detected, radius)
                # Reserve the observed validation stars too: a changed nearest
                # neighbour must not recycle one as a training target.
                use = (new_ids % 4 != 0) & ~np.isin(new_matches, matches[ids % 4 == 0])
                current_ids = np.r_[new_ids[use], ids[ids % 4 == 0]]
                current_matches = np.r_[new_matches[use], matches[ids % 4 == 0]]
    return best, reason


def calibrate(detections, catalog, latitude, longitude, timestamp, params,
              width, height, altitude, heading, mask):
    center = np.array([width/2+params[4], height/2-params[5]])
    reference = params[3]/2

    def visiblePoints(alt, az):
        # Catalogue matches and coverage must use the same sensor/mask bounds.
        x, y = projectToPixels(alt, az, params, width, height,
                              lens_altitude=altitude, pointing_azimuth=heading)
        keep = (cameraAltAz(alt, az, altitude, heading)[0] > 0)
        keep &= (x >= 0) & (x < width) & (y >= 0) & (y < height)
        x, y = x[keep], y[keep]
        if mask is not None:
            keep = mask[y.astype(int), x.astype(int)] > 0
            x, y = x[keep], y[keep]
        return (np.column_stack([x, y])-center)/reference

    alt, az = predictAltAz(catalog, latitude+params[1], longitude+params[2], timestamp)
    keep = alt > np.radians(10)
    predicted = visiblePoints(alt[keep], az[keep])
    detected = (detections[:, :2]-center)/reference
    # Uniform directions provide a coverage target clipped to actual sensor/mask.
    alt, az = np.meshgrid(np.arcsin(np.linspace(np.sin(np.radians(10)), 1, 24)),
                          np.linspace(0, 2*np.pi, 72, endpoint=False))
    expected = visiblePoints(alt.ravel(), az.ravel())
    return fitCorrection(predicted, detected, expected, max(8/reference, 0.025))
