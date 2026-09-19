import cv2
import numpy as np
import pytest

from indi_allsky.lens_solver.calibration import (
    fitCorrection, displacement, validateCalibration, pipelineSignature)
from indi_allsky.lens_solver.detection import StarDetector
from indi_allsky.lens_solver.request import parseSolverRequestValues, applySolvedValuesToConfig
from tests.flask.test_virtualsky_requests import VALUES


def field(layout='circle'):
    rng = np.random.default_rng(3128)
    points = rng.uniform(-1, 1, (10000, 2))
    keep = np.linalg.norm(points, axis=1) < 0.95
    if layout == 'landscape':
        keep &= np.abs(points[:, 1]) < 0.55
    elif layout == 'portrait':
        keep &= np.abs(points[:, 0]) < 0.55
    elif layout == 'offset_crop':
        keep &= (points[:, 0] > -0.2) & (np.abs(points[:, 1]) < 0.65)
    expected = points[keep]
    source = expected[:350]
    u, v = source.T
    # Independent radial and asymmetric distortions, in circle-radius units.
    shift = source*(0.018*(u*u+v*v))[:, None]
    shift += np.column_stack([0.004*(3*u*u+v*v), 0.008*u*v])
    target = source+shift+rng.normal(0, 0.0004, source.shape)
    return source, target, expected[350:]


@pytest.mark.parametrize('layout', ['circle', 'landscape', 'portrait', 'offset_crop'])
def test_learned_mapping_improves_unused_stars(layout):
    source, target, expected = field(layout)
    result, reason = fitCorrection(source, target, expected, 0.025)
    assert result is not None, reason
    model, stats = result
    assert stats['validation'] >= 15
    assert stats['after'] < stats['before']*0.5
    # Validate the learned mapping against independent physical truth too.
    # A few wrong initial identities can keep the reported validation RMS high;
    # the implementation deliberately does not discard those validation errors.
    u, v = expected.T
    truth = expected*(0.018*(u*u+v*v))[:, None]
    truth += np.column_stack([0.004*(3*u*u+v*v), 0.008*u*v])
    assert np.sqrt(np.mean(np.sum((displacement(expected, model)-truth)**2, axis=1))) < 0.002


def test_central_patch_cannot_validate_full_sensor():
    source, target, expected = field()
    keep = np.linalg.norm(source, axis=1) < 0.6
    result, reason = fitCorrection(source[keep], target[keep], expected, 0.025)
    assert result is None
    assert 'cover' in reason


def test_correct_mapping_is_retained_when_no_improvement_is_needed():
    source, _, expected = field()
    result, _ = fitCorrection(source, source, expected, 0.025)
    assert result is None


@pytest.mark.parametrize('family,fov', [
    (family, fov) for family in ('equisolid', 'equidistant', 'stereographic', 'orthographic')
    for fov in (60, 120, 180)
] + [('rectilinear', fov) for fov in (30, 60, 90, 120)])
def test_lens_families_improve_unseen_stars_or_retain_original_mapping(family, fov):
    from tests.lens_solver.test_distortion_feasibility import cap, angles, curve

    theta, direction = angles(cap(fov, 5000, 91))
    radius = np.sin(theta/2)/np.sin(np.pi/4)
    actual_radius = curve(theta, family)
    # Absorb the best common scale into the initial equisolid alignment. The
    # optional correction must handle the residual, not assume a physical lens.
    actual_radius *= np.dot(radius, radius)/np.dot(radius, actual_radius)
    predicted = direction*radius[:, None]
    actual = direction*actual_radius[:, None]
    extent = np.sin(np.radians(fov/4))/np.sin(np.pi/4)
    keep = (np.abs(actual[:, 1]) < extent*.65) & (actual[:, 0] > -extent*.8)
    predicted, actual = predicted[keep], actual[keep]  # oblong, off-centre sensor
    result, reason = fitCorrection(predicted[:350], actual[:350], predicted[350:], .025)
    if (family == 'equidistant' or (family in ('stereographic', 'orthographic') and fov <= 120)
            or (family == 'rectilinear' and fov == 60)):
        assert result is not None, reason
    if result is None:
        assert reason  # strong mismatch or too little support must remain usable
        return
    model, _ = result
    before = np.linalg.norm(actual[350:]-predicted[350:], axis=1)
    after = np.linalg.norm(actual[350:]-predicted[350:]-displacement(predicted[350:], model), axis=1)
    assert np.sqrt(np.mean(after**2)) < np.sqrt(np.mean(before**2))*.8
    assert np.percentile(after, 90) <= np.percentile(before, 90)
    saved = saved_model()
    saved.update(model)
    assert validateCalibration(saved)


def test_useful_correction_is_attenuated_to_keep_boundary_taper_safe():
    source = np.array(np.meshgrid(np.linspace(-.9, .9, 13), np.linspace(-.9, .9, 13))).reshape(2, -1).T
    source = source[np.linalg.norm(source, axis=1) < .92]
    shift = np.array([.028, .038])
    result, reason = fitCorrection(source, source+shift, source, .08)
    assert result is not None, reason
    model, stats = result
    # The full translation exceeds the existing gradient limit at the taper.
    # Its reduced strength must still improve stars not used in the fit.
    center_shift = displacement(np.zeros((1, 2)), model)[0]
    assert 0 < np.linalg.norm(center_shift) < np.linalg.norm(shift)
    assert stats['after'] < stats['before']*.3
    saved = saved_model()
    saved.update(model)
    assert validateCalibration(saved)


@pytest.mark.parametrize('kind', ['few', 'line', 'noise'])
def test_unreliable_calibration_is_refused(kind):
    source, target, expected = field()
    if kind == 'few':
        source, target = source[:30], target[:30]
    elif kind == 'line':
        source[:, 1] = source[:, 0]
        target = source.copy()
    else:
        target = np.random.default_rng(12).uniform(-1, 1, target.shape)
    assert fitCorrection(source, target, expected, 0.025)[0] is None


def saved_model(version=1):
    source, target, expected = field()
    model, _ = fitCorrection(source, target, expected, 0.025)[0]
    model.update(geometry=[VALUES[k] for k in ('AZIMUTH_ANGLE', 'LATITUDE_OFFSET',
        'LONGITUDE_OFFSET', 'IMAGE_CIRCLE_DIAMETER', 'OFFSET_X', 'OFFSET_Y')]+[90, 123],
        image_size=[2028, 1520], context=[53, 11, 0], camera_uuid='test-camera',
        pipeline=pipelineSignature({}), summary='Validation: 80 unused stars.')
    if version == 2:
        model.update(version=2, geometry=model['geometry']+[0.08, 1])
    return model


@pytest.mark.parametrize('key,value', [('coefficients', [[float('nan'), 0]]*10),
    ('coefficients', [[True, False]]*10), ('coefficients', [[1, 1]]*10),
    ('bounds', [0, 0, 0, 0]), ('bounds', [-100, -100, 100, 100]),
    ('image_size', [0, 1]), ('geometry', [0]*7), ('version', 999),
    ('context', [None, 0, 0]), ('summary', '<x>'*1000)])
def test_invalid_models_are_rejected(key, value):
    model = saved_model()
    model[key] = value
    assert not validateCalibration(model)


def test_model_save_toggle_and_geometry_binding():
    model = saved_model()
    assert validateCalibration(model)
    payload = dict(VALUES, LENS_ALTITUDE=90, CALIBRATION_ENABLED=True, CALIBRATION=model)
    parsed, error = parseSolverRequestValues(payload, for_save=True)
    assert error is None
    config = applySolvedValuesToConfig({}, parsed)
    assert config['VIRTUALSKY']['CALIBRATION'] == model
    payload['CALIBRATION_ENABLED'] = False
    parsed, error = parseSolverRequestValues(payload, for_save=True)
    assert error is None
    applySolvedValuesToConfig(config, parsed)
    assert config['VIRTUALSKY']['CALIBRATION'] == model
    assert not config['VIRTUALSKY']['CALIBRATION_ENABLED']
    payload['OFFSET_X'] += 1
    assert parseSolverRequestValues(payload, for_save=True)[1]


@pytest.mark.parametrize('version', [1, 2])
def test_calibration_is_bound_to_lens_curve_and_catalogue_convention(version):
    model = saved_model(version)
    payload = dict(VALUES, LENS_ALTITUDE=90, CALIBRATION_ENABLED=True, CALIBRATION=model,
                   RADIAL_DISTORTION=0.08 if version == 2 else 0, PRECESSION=version == 2)
    assert validateCalibration(model)
    assert parseSolverRequestValues(payload, for_save=True)[1] is None
    for changed in (dict(RADIAL_DISTORTION=0.1), dict(PRECESSION=not payload['PRECESSION'])):
        values, error = parseSolverRequestValues(dict(payload, **changed), for_save=True)
        assert values is None and 'Alignment changed' in error
    model['geometry'] = model['geometry'][:8]  # v2 must declare both new conventions
    assert validateCalibration(model) is (version == 1)


@pytest.mark.parametrize('value', ['true', 'false', 0, 1, None, [], {}])
def test_calibration_flag_requires_json_boolean(value):
    assert parseSolverRequestValues(dict(VALUES, CALIBRATION_ENABLED=value), for_save=True)[1]


def test_taper_is_identity_far_outside_calibrated_region():
    model = saved_model()
    np.testing.assert_array_equal(displacement(np.array([[3, 0], [-3, 0], [0, 3]]), model), 0)


def test_roi_transform_uses_sensor_coordinates_binning_rotation_and_crop():
    detector = StarDetector({'SQM_ROI': [20, 10, 80, 50], 'IMAGE_ROTATE': 'ROTATE_90_CLOCKWISE',
                             'IMAGE_CROP_ROI': [0, 0, 60, 100]})
    detector.use_sky_hints = True
    detector.sensor_shape = (40, 60)  # unbinned 80 x 120 sensor
    detector.binning = 2
    detections = np.array([[20, 20, 100], [2, 20, 100], [20, 45, 100]])
    # Original ROI [10:40, 5:25] -> clockwise x=[15:35], y=[10:40], then crop.
    preferred = detector.preferredDetections(detections, (50, 30))
    np.testing.assert_array_equal(preferred, detections[:1])


@pytest.mark.parametrize('roi', [None, [], [1], [0, 0, -1, 2], [0, 0, 5000, 4000],
                               [0, 0, float('nan'), 20], [0, 0, True, 20]])
def test_invalid_roi_is_ignored(roi):
    detector = StarDetector({'SQM_ROI': roi})
    detector.sensor_shape = (100, 100)
    assert len(detector.preferredDetections(np.array([[50, 50, 100]]), (100, 100))) == 0


def test_detection_mask_excludes_lights_from_calibration_threshold(tmp_path):
    mask = np.zeros((200, 400), np.uint8)
    mask[:, :200] = 255
    path = tmp_path / 'mask.png'
    assert cv2.imwrite(str(path), mask)
    image = np.full(mask.shape, 15, np.uint8)
    for y in range(20, 200, 30):
        for x in range(20, 200, 30):
            cv2.circle(image, (x, y), 2, 35, -1)
    image[:, 200:] = np.random.default_rng(3).integers(0, 255, (200, 200), dtype=np.uint8)
    detector = StarDetector({'DETECT_MASK': str(path)})
    legacy = detector.detectStars(image)
    detector.use_sky_hints = True
    hinted = detector.detectStars(image)
    assert len(hinted) > len(legacy)
    assert np.all(hinted[:, 0] < 200)


@pytest.mark.parametrize('bright_outside', [True, False])
def test_masked_noise_retries_normal_threshold_without_removing_limit(monkeypatch, bright_outside):
    image = np.full((1000, 2000), 15, np.uint8)
    image[4:996:8, 4:996:8] = 30  # faint isolated noise in otherwise usable sky
    for y in range(40, 1000, 140):
        for x in range(40, 1000, 140):
            cv2.circle(image, (x, y), 1, 220, -1)
    if bright_outside:
        image[:, 1000:] = np.random.default_rng(3).integers(0, 255, (1000, 1000), dtype=np.uint8)
    mask = np.zeros(image.shape, np.uint8)
    mask[:, :1000] = 255
    detector = StarDetector({})
    detector.use_sky_hints = True
    monkeypatch.setattr(detector, 'buildExclusionMask', lambda shape: mask)
    counts = []
    components = cv2.connectedComponentsWithStats

    def count_components(*args, **kwargs):
        result = components(*args, **kwargs)
        counts.append(result[0])
        return result

    monkeypatch.setattr(cv2, 'connectedComponentsWithStats', count_components)
    detections = detector.detectStars(image)
    assert len(counts) == 2 and counts[0] > 5000
    assert detector.last_component_flood is not bright_outside
    if bright_outside:
        assert len(detections) == 49  # stars survive, noise and masked lights do not
        assert np.all(detections[:, 0] < 1000)
    else:
        assert counts[-1] > 5000 and len(detections) == 0


@pytest.mark.parametrize('altitude,heading', [(90, 0), (54, 123)])
def test_solver_learns_from_rendered_catalogue(tmp_path, altitude, heading):
    from indi_allsky.lens_solver import IndiAllSkyLensSolver
    from tests.lens_solver.test_orientation import star_field, render_stars
    from tests.lens_solver.test_camera_tilt import PARAMS, KEYS

    _, detections, _, _ = star_field(altitude, heading)
    center = np.array([1014+PARAMS[4], 760-PARAMS[5]])
    q = (detections[:, :2]-center)/(PARAMS[3]/2)
    u, v = q.T
    shift = q*(0.025*(u*u+v*v))[:, None]
    shift += np.column_stack([0.006*(3*u*u+v*v), 0.012*u*v])
    detections[:, :2] += shift*(PARAMS[3]/2)
    path = tmp_path / 'distorted.png'
    render_stars(path, detections)
    initial = dict(zip(KEYS, PARAMS), CALIBRATION_ENABLED=True)
    result = IndiAllSkyLensSolver({}).solve(path, 46.51, 8, 1770000000, initial,
        lens_altitude=altitude, pointing_azimuth=heading)
    assert result['success'], result
    assert result['calibration'] is not None, result['message']
    assert validateCalibration(result['calibration'])
    assert result['calibration']['image_size'] == [2028, 1520]


@pytest.mark.parametrize('scale', [1, 3])
def test_learning_uses_solved_curvature_and_precessed_catalogue(tmp_path, monkeypatch, scale):
    from indi_allsky.lens_solver import solver as solver_mod
    from indi_allsky.lens_solver.projection import predictAltAz, precessCatalog
    from tests.lens_solver.test_camera_tilt import PARAMS, KEYS, reference_pixels
    from tests.lens_solver.test_orientation import render_stars

    solver = solver_mod.IndiAllSkyLensSolver({})
    timestamp = 1788731972
    catalogue = precessCatalog(solver.loadCatalog(), timestamp)
    alt, az = predictAltAz(catalogue, 53, 11, timestamp)
    x, y, z = reference_pixels(alt, az, 54, 176)
    center = np.array([1014+PARAMS[4], 760-PARAMS[5]])
    xy = center+(np.column_stack([x, y])-center)*np.maximum(1+z, 1e-12)[:, None]**(-0.08)
    keep = (alt > np.radians(10)) & (z > 0) & (xy[:, 0] > 5) & (xy[:, 0] < 2023) & (xy[:, 1] > 5) & (xy[:, 1] < 1515)
    path = tmp_path/'curved.png'
    render_stars(path, np.column_stack([xy[keep], np.ones(keep.sum())]))
    if scale != 1:
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        assert cv2.imwrite(str(path), cv2.resize(image, None, fx=scale, fy=scale))
    calls = []
    calibrate = solver_mod.calibrate

    def record(*args):
        calls.append(args)
        return calibrate(*args)

    monkeypatch.setattr(solver_mod, 'calibrate', record)
    initial = dict(zip(KEYS, PARAMS), LENS_ALTITUDE=90, PRECESSION=True,
                   RADIAL_DISTORTION=0, CALIBRATION_ENABLED=True)
    for key in KEYS[3:]:
        initial[key] *= scale
    result = solver.solve(path, 53, 11, timestamp, initial)
    assert result['success'], result
    assert len(calls) == 1
    args = calls[0]
    np.testing.assert_array_equal(args[1], catalogue)
    values = result['values']
    assert abs(values['RADIAL_DISTORTION']-0.08) < 0.01
    assert abs((values['POINTING_AZIMUTH']-176+180) % 360-180) < 2
    downscale = solver_mod._chooseDownscaleFactor(2028*scale, 1520*scale, initial['IMAGE_CIRCLE_DIAMETER'])
    expected = np.array([values[k] for k in KEYS]+[values['RADIAL_DISTORTION']])
    expected[3:6] /= downscale
    np.testing.assert_array_equal(args[5], expected)
    assert args[8:10] == (values['LENS_ALTITUDE'], values['POINTING_AZIMUTH'])
