"""Recover pointing from rotation-invariant star triangles, then fit one rotation.

Triangle search is used when the normal calibration cannot establish a full
solution. The equisolid lens model and catalogue are reused; no astrometry index or
network service is needed. Latitude/longitude offsets are zero in this fit:
allowing them to vary as well would describe the same rotation twice.
"""
import itertools

import numpy
from scipy.optimize import least_squares
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from . import fitting
from .projection import SIN45, predictAltAz, cameraAltAz


PATTERN_STARS = 120
PATTERN_NEIGHBORS = 8
PATTERN_TOLERANCE = 0.02  # unit-sphere chord lengths, allowing imperfect lens guesses
SEED_RADIUS = 0.035
MAX_SEEDS = 8


def _triangles(rays):
    neighbors = cKDTree(rays).query(rays, k=min(PATTERN_NEIGHBORS+1, len(rays)))[1][:, 1:]
    triangles = numpy.array([(i, j, k) for i, row in enumerate(neighbors)
                             for j, k in itertools.combinations(row, 2)])
    if not len(triangles):
        return numpy.empty((0, 3)), numpy.empty((0, 3), dtype=int)
    triangles = numpy.unique(numpy.sort(triangles, axis=1), axis=0)
    vertices = rays[triangles]
    # Each edge is opposite its corresponding vertex. Sorting both gives a
    # rotation-independent signature and the correspondence for a matched pair.
    edges = numpy.linalg.norm(vertices[:, [1, 0, 0]]-vertices[:, [2, 2, 1]], axis=2)
    order = numpy.argsort(edges, axis=1)
    edges = numpy.take_along_axis(edges, order, axis=1)
    triangles = numpy.take_along_axis(triangles, order, axis=1)
    keep = ((edges[:, 0] > 0.03) & (edges[:, 2] < 1.0)
            & (edges[:, 0]+edges[:, 1]-edges[:, 2] > 0.01))
    return edges[keep], triangles[keep]


def _pixelRays(xy, diameter, center):
    # Invert the equisolid radius into unit rays; ignore pixels outside the
    # guessed front hemisphere. The normal fit will refine scale and centre.
    xy = (center-xy) * (2*SIN45/diameter)
    r2 = numpy.sum(xy**2, axis=1)
    keep = r2 < SIN45**2
    xy, r2 = xy[keep], r2[keep]
    return numpy.column_stack([2*xy*numpy.sqrt(1-r2)[:, None], 1-2*r2])


def _project(world, matrix, params, width, height):
    rays = world @ matrix.T
    factor = params[3]/(2*SIN45*numpy.sqrt(numpy.maximum(2*(1+rays[:, 2]), 1e-12)))
    xy = numpy.column_stack([width/2+params[4]-factor*rays[:, 0],
                             height/2-params[5]-factor*rays[:, 1]])
    return xy, rays[:, 2] > 0


def _orientationValues(matrix):
    # matrix maps geographic east/north/up onto camera east/north/axis.
    axis = matrix[2]
    altitude = numpy.degrees(numpy.arctan2(axis[2], numpy.hypot(*axis[:2])))
    heading = numpy.arctan2(axis[0], axis[1]) if numpy.hypot(*axis[:2]) > 1e-10 else 0.0
    # Tilt leaves the across-heading axis unchanged; its camera angle isolates roll.
    across = matrix @ numpy.array([numpy.cos(heading), -numpy.sin(heading), 0.0])
    roll = numpy.degrees(numpy.arctan2(across[1], across[0])+heading) % 360
    return altitude, numpy.degrees(heading) % 360, roll


def pointingFromFit(params, latitude, longitude, timestamp, lens_altitude, pointing_azimuth):
    """Express fitted sky offsets as camera pointing without changing the mapping."""
    # Three orthogonal celestial directions determine the rotation exactly.
    # This also reports small tilts found by the fast fit, without a blind search.
    basis = numpy.array([[0., 0.], [90., 0.], [0., 90.]])
    alt, az = predictAltAz(basis, latitude, longitude, timestamp)
    world = numpy.column_stack([numpy.cos(alt)*numpy.sin(az),
                                numpy.cos(alt)*numpy.cos(az), numpy.sin(alt)])
    alt, az = predictAltAz(basis, latitude+params[1], longitude+params[2], timestamp)
    alt, az = cameraAltAz(alt, az, lens_altitude, pointing_azimuth)
    az = az-numpy.radians(params[0])
    camera = numpy.column_stack([numpy.cos(alt)*numpy.sin(az),
                                 numpy.cos(alt)*numpy.cos(az), numpy.sin(alt)])
    return _orientationValues(camera.T @ world)


def recoverOrientation(detections, catalog, latitude, longitude, timestamp, initial, width, height):
    if len(detections) < fitting.EFFECTIVE_MIN_MATCHED_STARS:
        return None
    alt, az = predictAltAz(catalog, latitude, longitude, timestamp)
    keep = alt > numpy.radians(fitting.MIN_STAR_ALT_DEG)
    alt, az = alt[keep], az[keep]
    world = numpy.column_stack([numpy.cos(alt)*numpy.sin(az),
                                 numpy.cos(alt)*numpy.cos(az), numpy.sin(alt)])
    if len(world) < fitting.EFFECTIVE_MIN_MATCHED_STARS:
        return None
    signatures, triangles = _triangles(world)
    if not len(signatures):
        return None
    pattern_tree = cKDTree(signatures)
    center = numpy.array([width/2+initial[4], height/2-initial[5]])
    seeds = []
    diameters = initial[3]*numpy.geomspace(fitting.RECOVERY_DIAMETER_MIN_MULT,
                                         fitting.RECOVERY_DIAMETER_MAX_MULT,
                                         fitting.RECOVERY_DIAMETER_STEPS)
    for diameter in diameters:
        if diameter < fitting.MIN_VIABLE_DIAMETER_PX:
            continue
        rays = _pixelRays(detections[:PATTERN_STARS, :2], diameter, center)
        if len(rays) < 10:
            continue
        observed, triples = _triangles(rays)
        if not len(observed):
            continue
        distances, matches = pattern_tree.query(observed, k=2, distance_upper_bound=PATTERN_TOLERANCE)
        rows, columns = numpy.nonzero(numpy.isfinite(distances))
        if not len(rows):
            continue
        sky = world[triangles[matches[rows, columns]]]
        camera = rays[triples[rows]]
        u, _, vt = numpy.linalg.svd(sky.transpose(0, 2, 1) @ camera)
        matrices = vt.transpose(0, 2, 1) @ u.transpose(0, 2, 1)
        # A physical camera rotation cannot reflect the sky.
        vt[:, 2] *= numpy.linalg.det(matrices)[:, None]
        matrices = vt.transpose(0, 2, 1) @ u.transpose(0, 2, 1)
        tree = cKDTree(rays)
        scores = []
        for start in range(0, len(matrices), 128):
            predicted = numpy.einsum('nj,bkj->bnk', world, matrices[start:start+128])
            distance, index = tree.query(predicted, distance_upper_bound=SEED_RADIUS)
            index = numpy.sort(index, axis=1)
            unique = numpy.sum((index[:, 1:] != index[:, :-1]) & (index[:, 1:] < len(rays)), axis=1)
            unique += index[:, 0] < len(rays)
            scores.extend(unique + numpy.sum(numpy.maximum(0, 1-distance/SEED_RADIUS), axis=1)/len(world))
        order = numpy.argsort(scores)[::-1]
        for _ in range(2):
            if not len(order) or scores[order[0]] < 10:
                break
            i = order[0]
            seeds.append((scores[i], matrices[i], diameter))
            # Keep distinct orientations, not two triangles from the same sky
            # match. Otherwise competing solutions never reach the ambiguity check.
            trace = numpy.einsum('nij,ij->n', matrices[order], matrices[i])
            order = order[trace < 1+2*numpy.cos(numpy.radians(5))]

    detections = fitting._truncateDetections(detections, *center, fitting.MAX_DETECTED_STARS)
    solutions = []
    for _, seed, diameter in sorted(seeds, key=lambda item: item[0], reverse=True)[:MAX_SEEDS]:
        params = numpy.array([0., 0., 0., diameter, initial[4], initial[5]])
        offset_bound = initial[3]*fitting.OFFSET_BOUND_FRACTION
        lower = [-0.4]*3 + [max(fitting.MIN_VIABLE_DIAMETER_PX, diameter*0.7),
                            initial[4]-offset_bound, initial[5]-offset_bound]
        upper = [0.4]*3 + [diameter*1.3, initial[4]+offset_bound, initial[5]+offset_bound]
        for fraction in (0.02, 0.01, 0.006, 0.004):
            matrix = Rotation.from_rotvec(params[:3]).as_matrix() @ seed
            xy, visible = _project(world, matrix, params, width, height)
            indices = numpy.flatnonzero(visible)
            radius = max(6., fraction*params[3])
            pred, detected = fitting._matchStars(detections, xy[indices], radius)
            if len(pred) < 10:
                break
            stars, target = world[indices[pred]], detections[detected, :2]

            def residuals(trial):
                rotation = Rotation.from_rotvec(trial[:3]).as_matrix() @ seed
                return (_project(stars, rotation, trial, width, height)[0]-target).ravel()

            params = least_squares(residuals, params, bounds=(lower, upper),
                loss=fitting.FIT_LOSS, f_scale=radius, x_scale=[0.1]*3+[diameter]*3,
                max_nfev=80).x

        matrix = Rotation.from_rotvec(params[:3]).as_matrix() @ seed
        xy, visible = _project(world, matrix, params, width, height)
        counts, rms, matched = [], float('inf'), numpy.empty((0, 2))
        gate = fitting._rmsGatePx(params[3])
        for radius in (max(6., 0.004*params[3]), gate):
            predicted = xy[visible]
            pred, detected = fitting._matchStars(detections, predicted, radius)
            counts.append(len(pred))
            if len(pred):
                matched = detections[detected, :2]
                rms = numpy.sqrt(numpy.mean(numpy.sum((predicted[pred]-matched)**2, axis=1)))
        altitude, heading, roll = _orientationValues(matrix)
        if altitude < -1e-8:
            continue  # preserve the camera configuration's 0..90 degree range
        altitude = max(0.0, altitude)  # round-off at a horizontal optical axis
        final = numpy.array([roll, 0., 0., *params[3:]])
        result = fitting._buildFitResult(final, min(counts), rms, gate, False)
        # A narrow streak cannot constrain the lens. Require spread in both
        # image directions, at least ten times the accepted positional error.
        if (result['success']
                and numpy.linalg.eigvalsh(numpy.cov(matched.T))[0] > (10*gate)**2):
            result.update(lens_altitude=altitude, pointing_azimuth=heading)
            solutions.append((result, matrix))
    if not solutions:
        return None
    solutions.sort(key=lambda item: (-item[0]['stars_matched'], item[0]['rms_px']))
    best, matrix = solutions[0]
    for other, rotation in solutions[1:]:
        if (other['stars_matched'] >= 0.9*best['stars_matched']
                and Rotation.from_matrix(rotation @ matrix.T).magnitude() > numpy.radians(5)):
            return None  # competing orientations: do not silently pick one
    return best
