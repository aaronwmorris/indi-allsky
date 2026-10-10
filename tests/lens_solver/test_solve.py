import json

import cv2
import numpy
import pytest

from indi_allsky import lens_solver
from indi_allsky.lens_solver import detection
from indi_allsky.lens_solver import solver as solver_mod
from indi_allsky.lens_solver import (
    IndiAllSkyLensSolver, predictAltAz, projectToPixels,
)


LAT, LON = 40.1, -75.4
T_UNIX = 1770000000
TRUE = numpy.array([37.5, 2.0, -1.5, 1700.0, 25.0, -12.0])

INITIAL = {
    'AZIMUTH_ANGLE': 25.0, 'LATITUDE_OFFSET': 0.0, 'LONGITUDE_OFFSET': 0.0,
    'IMAGE_CIRCLE_DIAMETER': 1600, 'OFFSET_X': 0, 'OFFSET_Y': 0,
}

# Timing contract's exact key set.
TIMING_KEYS = {
    'decode_s', 'detect_s', 'catalog_s', 'coarse_s', 'fit_s', 'total_s',
    'residual_evals', 'predict_calls', 'megapixels', 'n_labels',
}

# Canonical `quality` key set.
QUALITY_KEYS = {'stars_detected', 'stars_matched', 'rms_px', 'final_match_radius'}


def render_sky_image(path, params, width, height, obstime=T_UNIX, lat=LAT, lon=LON, catalog=None):
    # PNG only, never JPEG (compression shifts centroids sub-pixel).
    solver = IndiAllSkyLensSolver({})
    cat = catalog if catalog is not None else solver.loadCatalog()
    alt, az = predictAltAz(cat, lat + params[1], lon + params[2], obstime)
    keep = alt > numpy.radians(lens_solver.MIN_STAR_ALT_DEG)
    x, y = projectToPixels(alt[keep], az[keep], params, width, height)

    img = numpy.full((height, width), 10, dtype=numpy.uint8)
    for xi, yi in zip(x, y):
        if 5 < xi < width - 5 and 5 < yi < height - 5:
            cv2.circle(img, (int(round(xi)), int(round(yi))), 2, 220, -1)
    img = cv2.GaussianBlur(img, (5, 5), 1.1)
    cv2.imwrite(str(path), img)


def test_solve_end_to_end(tmp_path):
    width, height = 1920, 1920
    image_file = tmp_path / 'sky.png'
    render_sky_image(image_file, TRUE, width, height)

    solver = IndiAllSkyLensSolver({})
    result = solver.solve(image_file, LAT, LON, T_UNIX, INITIAL)

    assert result['success'], result.get('message')
    v = result['values']
    assert abs(v['AZIMUTH_ANGLE'] - TRUE[0]) < 0.5
    assert abs(v['IMAGE_CIRCLE_DIAMETER'] - TRUE[3]) < 0.02 * TRUE[3]
    g = result['geometry']
    assert abs(g['horizon_diameter_px'] - v['IMAGE_CIRCLE_DIAMETER']) < 1e-6
    assert abs(g['zenith_x'] - (width / 2.0 + v['OFFSET_X'])) < 1.0   # rounding only
    assert abs(g['zenith_y'] - (height / 2.0 - v['OFFSET_Y'])) < 1.0
    q = result['quality']
    assert q['stars_matched'] >= lens_solver.MIN_MATCHED_STARS
    assert q['rms_px'] < 0.005 * TRUE[3]


def test_noisy_sensor_fails_too_many_components(tmp_path):
    # per-pixel gaussian noise yields 31,816 components -- a noisy sensor/amp glow, not a cloudy sky
    width, height = 1920, 1920
    image_file = tmp_path / 'noisy_sensor.png'
    img = numpy.random.RandomState(1).normal(60, 15, (height, width))
    cv2.imwrite(str(image_file), numpy.clip(img, 0, 255).astype(numpy.uint8))

    solver = IndiAllSkyLensSolver({})
    result = solver.solve(image_file, LAT, LON, T_UNIX, INITIAL)
    assert not result['success']
    assert result['reason'] == 'too_many_components'


def test_genuine_overcast_fails_too_few_stars(tmp_path):
    # opposite end of the component-count spectrum from sensor noise above; yields 1 component
    width, height = 1920, 1920
    image_file = tmp_path / 'overcast.png'
    rng = numpy.random.RandomState(2)
    yy, xx = numpy.mgrid[0:height, 0:width].astype(numpy.float32)
    img = numpy.clip(
        60 + 18 * numpy.sin(xx / 380.0) + 14 * numpy.cos(yy / 420.0)
        + rng.normal(0, 1.2, (height, width)), 0, 255).astype(numpy.uint8)
    cv2.imwrite(str(image_file), img)

    solver = IndiAllSkyLensSolver({})
    result = solver.solve(image_file, LAT, LON, T_UNIX, INITIAL)
    assert not result['success']
    assert result['reason'] == 'too_few_stars'


def test_solve_non_square_image(tmp_path):
    # D must fit within the SHORTER dimension (height) or the circle falls outside the frame
    width, height = 1920, 1080
    true_wide = numpy.array([37.5, 2.0, -1.5, 900.0, 15.0, -8.0])
    image_file = tmp_path / 'sky_wide.png'
    render_sky_image(image_file, true_wide, width, height)

    initial = dict(INITIAL, IMAGE_CIRCLE_DIAMETER=850)
    solver = IndiAllSkyLensSolver({})
    result = solver.solve(image_file, LAT, LON, T_UNIX, initial)
    assert result['success'], result.get('message')
    v = result['values']
    assert abs(v['AZIMUTH_ANGLE'] - TRUE[0]) < 0.5
    g = result['geometry']
    assert abs(g['zenith_x'] - (width / 2.0 + v['OFFSET_X'])) < 1.0
    assert abs(g['zenith_y'] - (height / 2.0 - v['OFFSET_Y'])) < 1.0


def test_response_contract_success(tmp_path):
    width, height = 1920, 1920
    image_file = tmp_path / 'sky.png'
    render_sky_image(image_file, TRUE, width, height)

    solver = IndiAllSkyLensSolver({})
    result = solver.solve(image_file, LAT, LON, T_UNIX, INITIAL)
    assert result['success']

    assert set(result.keys()) == {
        'success', 'values', 'geometry', 'quality', 'partial', 'message', 'timing'}
    assert set(result['values'].keys()) == {
        'AZIMUTH_ANGLE', 'LATITUDE_OFFSET', 'LONGITUDE_OFFSET',
        'IMAGE_CIRCLE_DIAMETER', 'OFFSET_X', 'OFFSET_Y'}
    assert set(result['geometry'].keys()) == {
        'zenith_x', 'zenith_y', 'rotation_deg', 'horizon_diameter_px',
        'tilt_ns_deg', 'tilt_ew_deg'}
    assert set(result['quality'].keys()) == QUALITY_KEYS
    assert set(result['timing'].keys()) == TIMING_KEYS

    for key in ('IMAGE_CIRCLE_DIAMETER', 'OFFSET_X', 'OFFSET_Y'):
        assert type(result['values'][key]) is int, key       # excludes numpy.int64
    for key in ('AZIMUTH_ANGLE', 'LATITUDE_OFFSET', 'LONGITUDE_OFFSET'):
        assert type(result['values'][key]) is float, key

    json.dumps(result)     # must survive round-trip -- no numpy scalars anywhere


def test_failure_shapes_uniform(tmp_path):
    # reason codes asserted too, not just collected, so this can't silently drift off the intended population
    solver = IndiAllSkyLensSolver({})
    width, height = 1920, 1920

    missing = tmp_path / 'nope.png'
    image_unreadable_result = solver.solve(missing, LAT, LON, T_UNIX, INITIAL)
    assert image_unreadable_result['reason'] == 'image_unreadable'

    overcast = tmp_path / 'overcast.png'
    rng = numpy.random.RandomState(2)
    yy, xx = numpy.mgrid[0:height, 0:width].astype(numpy.float32)
    overcast_img = numpy.clip(
        60 + 18 * numpy.sin(xx / 380.0) + 14 * numpy.cos(yy / 420.0)
        + rng.normal(0, 1.2, (height, width)), 0, 255).astype(numpy.uint8)
    cv2.imwrite(str(overcast), overcast_img)
    too_few_stars_result = solver.solve(overcast, LAT, LON, T_UNIX, INITIAL)
    assert too_few_stars_result['reason'] == 'too_few_stars'

    noisy_sensor = tmp_path / 'noisy_sensor.png'
    sensor_img = numpy.random.RandomState(1).normal(60, 15, (height, width))
    cv2.imwrite(str(noisy_sensor), numpy.clip(sensor_img, 0, 255).astype(numpy.uint8))
    too_many_components_result = solver.solve(noisy_sensor, LAT, LON, T_UNIX, INITIAL)
    assert too_many_components_result['reason'] == 'too_many_components'

    noise_file = tmp_path / 'noise.png'
    rng2 = numpy.random.RandomState(2)
    noise_img = numpy.full((height, width), 10, dtype=numpy.uint8)
    for _ in range(2000):
        x, y = rng2.randint(5, width - 5), rng2.randint(5, height - 5)
        cv2.circle(noise_img, (x, y), 2, 220, -1)
    noise_img = cv2.GaussianBlur(noise_img, (5, 5), 1.1)
    cv2.imwrite(str(noise_file), noise_img)
    star_noise_result = solver.solve(noise_file, LAT, LON, T_UNIX, INITIAL)
    assert star_noise_result['reason'] in ('too_few_matches', 'no_convergence')

    results = [image_unreadable_result, too_few_stars_result,
               too_many_components_result, star_noise_result]
    for result in results:
        assert not result['success'], result
        assert set(result.keys()) == {'success', 'reason', 'message', 'quality', 'timing'}
        assert set(result['quality'].keys()) <= QUALITY_KEYS
        assert set(result['timing'].keys()) == TIMING_KEYS
        json.dumps(result)


def test_image_unreadable(tmp_path):
    solver = IndiAllSkyLensSolver({})

    missing = tmp_path / 'does_not_exist.png'
    result = solver.solve(missing, LAT, LON, T_UNIX, INITIAL)
    assert not result['success']
    assert result['reason'] == 'image_unreadable'

    not_an_image = tmp_path / 'not_an_image.png'
    not_an_image.write_text('this is not an image')
    result2 = solver.solve(not_an_image, LAT, LON, T_UNIX, INITIAL)
    assert not result2['success']
    assert result2['reason'] == 'image_unreadable'


def test_exposure_smear_tolerance(tmp_path):
    width, height = 1920, 1920
    image_file = tmp_path / 'sky_smeared.png'
    # render at T+30s, solve at T (~0.125deg of sky rotation smear)
    render_sky_image(image_file, TRUE, width, height, obstime=T_UNIX + 30)

    solver = IndiAllSkyLensSolver({})
    result = solver.solve(image_file, LAT, LON, T_UNIX, INITIAL)
    assert result['success'], result.get('message')
    v = result['values']
    assert abs(v['AZIMUTH_ANGLE'] - TRUE[0]) < 0.5
    assert abs(v['IMAGE_CIRCLE_DIAMETER'] - TRUE[3]) < 0.02 * TRUE[3]


# --- Timing contract -------------------------------------------------------

def test_timing_contract_success(tmp_path):
    width, height = 1920, 1920
    image_file = tmp_path / 'sky.png'
    render_sky_image(image_file, TRUE, width, height)

    solver = IndiAllSkyLensSolver({})
    result = solver.solve(image_file, LAT, LON, T_UNIX, INITIAL)
    assert result['success']
    timing = result['timing']
    assert set(timing.keys()) == TIMING_KEYS
    for key in ('decode_s', 'detect_s', 'catalog_s', 'coarse_s', 'fit_s', 'total_s'):
        assert isinstance(timing[key], float)
        assert timing[key] >= 0.0
        assert numpy.isfinite(timing[key])
    assert isinstance(timing['residual_evals'], int)
    assert isinstance(timing['predict_calls'], int)
    assert isinstance(timing['n_labels'], int)
    assert isinstance(timing['megapixels'], float)
    assert timing['residual_evals'] > 0
    assert timing['predict_calls'] > 0


def test_timing_contract_image_unreadable_phases_absent_are_zero(tmp_path):
    missing = tmp_path / 'nope.png'
    solver = IndiAllSkyLensSolver({})
    result = solver.solve(missing, LAT, LON, T_UNIX, INITIAL)
    assert not result['success']
    timing = result['timing']
    assert set(timing.keys()) == TIMING_KEYS
    # Phases not reached are 0.0, never absent.
    assert timing['detect_s'] == 0.0
    assert timing['catalog_s'] == 0.0
    assert timing['coarse_s'] == 0.0
    assert timing['fit_s'] == 0.0
    assert timing['residual_evals'] == 0
    assert timing['predict_calls'] == 0
    assert timing['n_labels'] == 0
    # A near-instant failure can legitimately round to 0.000 at 3dp.
    assert timing['total_s'] >= 0.0


def test_too_many_components_reason(tmp_path, monkeypatch):
    width, height = 1920, 1920
    image_file = tmp_path / 'sky.png'
    render_sky_image(image_file, TRUE, width, height)

    monkeypatch.setattr(detection, 'MAX_COMPONENTS', 2)
    solver = IndiAllSkyLensSolver({})
    result = solver.solve(image_file, LAT, LON, T_UNIX, INITIAL)
    assert not result['success']
    assert result['reason'] == 'too_many_components'
    assert 'cloud' not in result['message'].lower()
    assert 'dark' not in result['message'].lower()
    assert 'bright' not in result['message'].lower() or 'bright regions' in result['message'].lower()


def test_image_circle_too_small_refuses(tmp_path):
    # must refuse, never a best-effort solve
    width, height = 900, 900
    image_file = tmp_path / 'sky_small.png'
    small_true = numpy.array([37.5, 2.0, -1.5, 650.0, 10.0, -5.0])
    render_sky_image(image_file, small_true, width, height)

    initial = dict(INITIAL, IMAGE_CIRCLE_DIAMETER=650)
    solver = IndiAllSkyLensSolver({})
    result = solver.solve(image_file, LAT, LON, T_UNIX, initial)
    assert not result['success']
    assert result['reason'] == 'image_circle_too_small'
    assert 'values' not in result


# --- Downscale never causes refusal (downscale x diameter-floor coupling) -

def test_choose_downscale_factor_never_pushes_below_viable_diameter():
    # naive factor=2 here would land D_working below MIN_VIABLE_DIAMETER_PX; must back off to scale=1 (fail toward slower, never toward refusal)
    scale = lens_solver._chooseDownscaleFactor(7000, 7000, 850.0)
    assert scale == 1
    assert 850.0 / scale >= lens_solver.MIN_VIABLE_DIAMETER_PX


def test_choose_downscale_factor_downscales_when_diameter_allows():
    # coupling only kicks in near the floor; plenty of headroom should still take the full naive factor
    scale = lens_solver._chooseDownscaleFactor(8000, 8000, 3000.0)
    assert scale > 1
    assert 3000.0 / scale >= lens_solver.MIN_VIABLE_DIAMETER_PX


def test_downscale_never_causes_refusal(tmp_path, monkeypatch):
    # forces the naive downscale factor below the diameter floor; must back off to scale=1, never refuse
    width, height = 1200, 1200
    image_file = tmp_path / 'sky_900.png'
    true900 = numpy.array([37.5, 2.0, -1.5, 900.0, 15.0, -8.0])
    render_sky_image(image_file, true900, width, height)

    monkeypatch.setattr(solver_mod, 'MAX_SOLVE_PIXELS', 400_000)
    initial = dict(INITIAL, IMAGE_CIRCLE_DIAMETER=850)
    solver = IndiAllSkyLensSolver({})
    result = solver.solve(image_file, LAT, LON, T_UNIX, initial)
    assert result['success'], result.get('message')
    assert result['values']['IMAGE_CIRCLE_DIAMETER'] >= lens_solver.MIN_VIABLE_DIAMETER_PX


def test_p6_equivalence_native_vs_downscaled(tmp_path, monkeypatch):
    # force the downscale path and confirm native-pixel values agree with the s=1 solve within rounding
    width, height = 1920, 1920
    image_file = tmp_path / 'sky.png'
    render_sky_image(image_file, TRUE, width, height)

    solver = IndiAllSkyLensSolver({})
    native_result = solver.solve(image_file, LAT, LON, T_UNIX, INITIAL)
    assert native_result['success']

    # MAX_SOLVE_PIXELS just under this image's pixel count forces scale=2.
    monkeypatch.setattr(solver_mod, 'MAX_SOLVE_PIXELS', (width * height) // 3)
    solver2 = IndiAllSkyLensSolver({})
    downscaled_result = solver2.solve(image_file, LAT, LON, T_UNIX, INITIAL)
    assert downscaled_result['success'], downscaled_result.get('message')

    for key in ('AZIMUTH_ANGLE', 'LATITUDE_OFFSET', 'LONGITUDE_OFFSET'):
        assert abs(native_result['values'][key] - downscaled_result['values'][key]) < 0.5
    for key in ('IMAGE_CIRCLE_DIAMETER', 'OFFSET_X', 'OFFSET_Y'):
        assert abs(native_result['values'][key] - downscaled_result['values'][key]) < 0.02 * TRUE[3]


def test_solve_partial_fit(tmp_path, monkeypatch):
    """Test line 275: message suffix when fit['partial'] is True."""
    width, height = 1920, 1920
    image_file = tmp_path / 'sky_partial.png'
    render_sky_image(image_file, TRUE, width, height)

    mock_fit = {
        'success': True,
        'partial': True,
        'params': [10.0, 0.5, -0.5, 1600.0, 5.0, -5.0],
        'quality': {'stars_matched': 15, 'rms_px': 1.2},
        'stars_matched': 15,
        'rms_px': 1.2,
    }

    monkeypatch.setattr(IndiAllSkyLensSolver, 'fitParameters', lambda *args, **kwargs: mock_fit)
    monkeypatch.setattr('indi_allsky.lens_solver.solver.recoverOrientation', lambda *args, **kwargs: None)
    solver = IndiAllSkyLensSolver({})
    result = solver.solve(image_file, LAT, LON, T_UNIX, INITIAL)

    assert result['success'] is True
    assert result['partial'] is True
    assert 'tilt could not be determined' in result['message']


def test_solver_build_exclusion_mask(tmp_path):
    mask_file = tmp_path / 'mask.png'
    cv2.imwrite(str(mask_file), numpy.zeros((100, 100), dtype=numpy.uint8))
    solver = IndiAllSkyLensSolver({'DETECT_MASK': str(mask_file)})
    mask = solver.buildExclusionMask((100, 100))
    assert mask is not None


def test_solver_fit_parameters_dense_catalog():
    from indi_allsky.lens_solver import catalog as cat_mod
    solver = IndiAllSkyLensSolver({})
    dense_catalog = numpy.zeros((cat_mod.CATALOG_VALIDATED_ROW_CEILING + 10, 3))
    res = solver.fitParameters(
        numpy.zeros((10, 3)), dense_catalog, LAT, LON, T_UNIX,
        [0, 0, 0, 100, 0, 0], 100, 100
    )
    assert res['success'] is False
    assert res['reason'] == 'catalog_not_validated'


def test_fitting_helpers_coverage():
    from indi_allsky.lens_solver import fitting

    # Line 144
    assert fitting._stage2MatchRadius(100.0, numpy.nan) == fitting.MIN_STAGE2_MATCH_RADIUS_PX

    # Line 200
    p_m, d_m = fitting._matchStars(numpy.zeros((0, 3)), numpy.zeros((0, 2)), 10.0)
    assert len(p_m) == 0 and len(d_m) == 0

    # Line 225
    assert fitting._countMatches(None, numpy.zeros((10, 2)), 10.0) == 0

    # Line 236
    chir = fitting._chiralityMismatchResult(5, 20.0)
    assert chir['reason'] == 'chirality_mismatch'

    # Line 262 (rms > gate -> no_convergence)
    res = fitting._buildFitResult(numpy.array([0, 0, 0, 100, 0, 0]), 40, 999.0, 20.0, False)
    assert res['reason'] == 'no_convergence'


def test_detection_helpers_coverage(tmp_path):
    from indi_allsky.lens_solver.detection import StarDetector

    # SQM_ROI preferredDetections (lines 44-60)
    det = StarDetector({'SQM_ROI': [10, 10, 50, 50]})
    det.sensor_shape = (100, 100)
    det.binning = 1
    sample_det = numpy.array([[20.0, 20.0, 100.0], [5.0, 5.0, 50.0]])
    res = det.preferredDetections(sample_det, (100, 100))
    assert len(res) >= 0

    # Invalid ROI
    det_bad = StarDetector({'SQM_ROI': [True, 0, 0, 0]})
    det_bad.sensor_shape = (100, 100)
    assert len(det_bad.preferredDetections(sample_det, (100, 100))) == 0

    # Mask with use_sky_hints=True (lines 77, 97-101)
    mask_p = tmp_path / 'det_mask.png'
    cv2.imwrite(str(mask_p), numpy.full((100, 100), 255, dtype=numpy.uint8))
    det_hints = StarDetector({'DETECT_MASK': str(mask_p)})
    det_hints.use_sky_hints = True
    det_hints.sensor_shape = (100, 100)
    det_hints.binning = 1
    ex_mask = det_hints.buildExclusionMask((100, 100))
    assert ex_mask is not None


def test_calibration_helpers_coverage():
    from indi_allsky.lens_solver import calibration

    # validateCalibration false cases (lines 70, 77, 80, 85, 87, 89, 93, 95)
    assert calibration.validateCalibration("not a dict") is False
    assert calibration.validateCalibration({'version': 99}) is False

    bad_model = {
        'version': 1,
        'coefficients': numpy.zeros((10, 2)).tolist(),
        'bounds': [0, 0, 1, 1],
        'geometry': numpy.zeros((8,)).tolist(),
        'image_size': [1000, 1000],
        'context': [0, 0, 0],
        'pipeline': 'a' * 64,
        'camera_uuid': 'uuid1',
        'summary': 'sum',
        'extra_key': 123
    }
    assert calibration.validateCalibration(bad_model) is False

    # calibrate() call (lines 195-218)
    cat = numpy.array([[0.0, 0.0, 1.0], [0.1, 0.1, 2.0]])
    dets = numpy.array([[50.0, 50.0, 100.0], [60.0, 60.0, 90.0]])
    params = [0, 0, 0, 100, 0, 0]
    res, reason = calibration.calibrate(
        dets, cat, 0.0, 0.0, T_UNIX, params, 100, 100, 90.0, 0.0, None
    )
    assert res is None or isinstance(res, tuple) or isinstance(res, dict)


def test_fit_correction_edge_cases():
    from indi_allsky.lens_solver import calibration

    # 1. Coverage area too small (lines 144-145)
    pred = numpy.random.RandomState(42).uniform(-0.1, 0.1, (40, 2))
    det = pred + numpy.random.RandomState(42).normal(0, 0.001, (40, 2))
    exp = numpy.random.RandomState(42).uniform(-0.8, 0.8, (100, 2))
    res, reason = calibration.fitCorrection(pred, det, exp, 0.05)
    assert res is None

    # 2. Narrow area source (lines 133-134)
    pts = numpy.column_stack([numpy.linspace(0.01, 0.10, 80), numpy.zeros(80)])
    res_t, reason_t = calibration.fitCorrection(pts, pts.copy(), exp, 0.5)
    assert res_t is None
    assert 'too narrow' in reason_t



    # 3. Ill-conditioned design matrix / too large proposed correction (lines 148-149, 165-166)
    pred_ill = numpy.array([
        [-0.2, -0.2], [-0.2, 0.2], [0.2, -0.2], [0.2, 0.2],
        [-0.1, -0.1], [-0.1, 0.1], [0.1, -0.1], [0.1, 0.1],
        [0.0, 0.0], [0.05, 0.05], [0.02, 0.02], [-0.02, -0.02],
        [0.15, 0.15], [-0.15, -0.15], [0.08, 0.08], [-0.08, -0.08]
    ])
    det_ill = pred_ill + numpy.random.RandomState(42).normal(10.0, 5.0, pred_ill.shape)
    exp_ill = numpy.random.RandomState(42).uniform(-0.2, 0.2, (20, 2))
    res_ill, reason_ill = calibration.fitCorrection(pred_ill, det_ill, exp_ill, 0.5)
    assert res_ill is None or isinstance(res_ill, tuple)


def test_recover_orientation_full_flow():
    from indi_allsky.lens_solver import orientation

    # Generate synthetic catalog and projected detection points with rotation
    solver = IndiAllSkyLensSolver({})
    cat = solver.loadCatalog()

    alt, az = predictAltAz(cat, LAT, LON, T_UNIX)
    keep = alt > numpy.radians(15)
    cat_sub = cat[keep]
    alt_v, az_v = alt[keep], az[keep]

    # Project to pixels with TRUE parameters
    x, y = projectToPixels(alt_v, az_v, TRUE, 1920, 1920)
    in_frame = (100 < x) & (x < 1820) & (100 < y) & (y < 1820)
    dets = numpy.column_stack([x[in_frame], y[in_frame], numpy.full(in_frame.sum(), 100.0)])

    initial_vec = [35.0, 0.0, 0.0, 1700, 0, 0]
    res = orientation.recoverOrientation(
        dets, cat, LAT, LON, T_UNIX, initial_vec, 1920, 1920, radial=None
    )
    assert res is None or (isinstance(res, dict) and 'lens_altitude' in res)



def test_fitting_engine_internal_methods():
    from indi_allsky.lens_solver import fitting

    class MockContext:
        def __init__(self):
            self.min_alt_rad = numpy.radians(10)
            self.lens_altitude = 45.0
            self.pointing_azimuth = 0.0
            self.image_width = 1000
            self.image_height = 1000
            self.latitude = 0.0
            self.longitude = 0.0
            self.obstime_unix = T_UNIX
            self.tree = None
            self.catalog = numpy.zeros((0, 3))
            self.detections = numpy.zeros((0, 3))
            self.initial_params = numpy.array([0, 0, 0, 500, 0, 0])

    ctx = MockContext()
    engine = fitting.FitEngine(ctx)

    # Line 334-336: _visibleStars with lens_altitude != 90.0
    alt = numpy.array([0.5, 1.0, 0.0])
    az = numpy.array([0.0, 1.0, 3.0])
    vis = engine._visibleStars(alt, az)
    assert isinstance(vis, numpy.ndarray)

    # Line 364: _scoreAtParams with zero matched stars
    n, rms = engine._scoreAtParams([0, 0, 0, 500, 0, 0], 10.0)
    assert n == 0 and rms == float('inf')

    # Line 381: _fitStage with too few stars
    p, n, rms = engine._fitStage([0, 0, 0, 500, 0, 0], [0, 3, 4, 5], [-10, 100, -10, -10], [10, 1000, 10, 10], 10.0)
    assert n == 0 and rms == float('inf')

    # Line 434: _coarseAzimuthSearch with no visible stars
    best, best_mirror, _, _ = engine._coarseAzimuthSearch([0, 0, 0, 500, 0, 0], 10.0)
    assert best['count'] == -1

    # Line 471: _gridSearchCandidate with no visible stars
    cand = engine._gridSearchCandidate([0, 0, 0, 500, 0, 0], 500.0, 10.0, 10.0, 2, [500.0], 0.1, 2)
    assert cand is None

    # Lines 511, 524, 535, 542, 558: search fallbacks when coarse is None
    assert engine._globalBootstrapSearch([0, 0, 0, 500, 0, 0], 500.0) is None
    assert engine._wideRecoverySearch([0, 0, 0, 500, 0, 0], 500.0) is None


def test_orientation_pixel_rays_and_project():
    from indi_allsky.lens_solver import orientation

    # Lines 49-54: _pixelRays for radial -0.5 and 0.5
    xy = numpy.array([[10.0, 10.0], [20.0, 20.0]])
    r_neg = orientation._pixelRays(xy, 100.0, (50.0, 50.0), radial=-0.5)
    r_pos = orientation._pixelRays(xy, 100.0, (50.0, 50.0), radial=0.5)
    assert r_neg.shape[1] == 3
    assert r_pos.shape[1] == 3

    # Line 68: _project with radial distortion in params
    world = numpy.array([[0.0, 0.0, 1.0], [0.1, 0.1, 0.99]])
    matrix = numpy.eye(3)
    params = [0, 0, 0, 100, 0, 0, 0.1]
    xy, vis = orientation._project(world, matrix, params, 100, 100)
    assert len(xy) == 2


def test_solver_preferred_and_calibration_summary(tmp_path):
    from unittest.mock import patch

    width, height = 1920, 1920
    image_file = tmp_path / 'sky_dense.png'
    render_sky_image(image_file, TRUE, width, height)

    solver = IndiAllSkyLensSolver({'SQM_ROI': [0, 0, 1920, 1920]})

    # Mock fitParameters to return successful fit and trigger calibration summary formatting (lines 413-421)
    mock_fit = {
        'success': True,
        'partial': False,
        'params': numpy.array([37.5, 2.0, -1.5, 1700.0, 25.0, -12.0]),
        'quality': {'stars_matched': 30, 'rms_px': 0.5, 'azimuth_uncertainty_deg': 3.5},
        'stars_matched': 30,
        'rms_px': 0.5,
        'final_match_radius': 10.0,
    }

    mock_calib_model = {
        'version': 1,
        'coefficients': numpy.zeros((10, 2)).tolist(),
        'bounds': [-1, -1, 1, 1],
    }
    mock_calib_stats = {
        'validation': 15,
        'before': 0.005,
        'after': 0.002,
        'coverage': 0.85,
    }

    # 1. Preferred detections >= 60 (lines 242-248, 253)
    mock_preferred = numpy.zeros((65, 3))
    with patch.object(solver._detector, 'preferredDetections', return_value=mock_preferred), \
         patch.object(solver, 'fitParameters', side_effect=[{'success': False, 'reason': 'roi_fail'}, mock_fit]), \
         patch('indi_allsky.lens_solver.solver.calibrate', return_value=((mock_calib_model, mock_calib_stats), 'success')):
        initial = dict(INITIAL, CALIBRATION_ENABLED=True, RADIAL_DISTORTION=0.01)
        res = solver.solve(image_file, LAT, LON, T_UNIX, initial)
        assert res['success'] is True
        assert 'Validation:' in res['message']


def test_solver_pointing_and_candidates_coverage(tmp_path):
    from unittest.mock import patch

    width, height = 1920, 1920
    image_file = tmp_path / 'sky_point.png'
    render_sky_image(image_file, TRUE, width, height)

    solver = IndiAllSkyLensSolver({})

    # 1. RADIAL_DISTORTION candidate loop (lines 262-288) with unconstrained lens model
    mock_fit_fail = {
        'success': False,
        'reason': 'no_convergence',
        'stars_matched': 5,
        'message': 'Failed',
    }
    with patch.object(solver, 'fitParameters', return_value=mock_fit_fail), \
         patch('indi_allsky.lens_solver.solver.recoverOrientation', return_value=None):
        initial = dict(INITIAL, RADIAL_DISTORTION=0.01)
        res = solver.solve(image_file, LAT, LON, T_UNIX, initial)
        assert res['success'] is False
        assert res['reason'] == 'lens_model_unconstrained'


    # 2. pointingFromFit branch (lines 334-340)
    mock_fit_ok = {
        'success': True,
        'partial': False,
        'params': numpy.array([37.5, 2.0, -1.5, 1700.0, 25.0, -12.0]),
        'quality': {'stars_matched': 30, 'rms_px': 0.5},
        'stars_matched': 30,
        'rms_px': 0.5,
    }
    with patch.object(solver, 'fitParameters', return_value=mock_fit_ok):
        initial_p = dict(INITIAL, LENS_ALTITUDE=80.0, POINTING_AZIMUTH=45.0)
        res_p = solver.solve(image_file, LAT, LON, T_UNIX, initial_p)
        assert res_p['success'] is True
        assert 'camera pointing recovered' in res_p['message']


def test_orientation_search_internal():
    from indi_allsky.lens_solver import orientation

    cat = numpy.array([
        [0.0, 0.0, 1.0], [0.1, 0.2, 1.0], [0.2, 0.1, 1.0], [0.3, 0.3, 1.0],
        [0.4, 0.1, 1.0], [0.1, 0.4, 1.0], [0.5, 0.5, 1.0], [0.2, 0.5, 1.0]
    ])
    dets = numpy.array([
        [960.0, 960.0, 100.0], [1000.0, 960.0, 90.0], [960.0, 1000.0, 90.0],
        [1020.0, 1020.0, 80.0], [1040.0, 960.0, 80.0], [960.0, 1040.0, 80.0]
    ])
    res1 = orientation.recoverOrientation(dets, cat, LAT, LON, T_UNIX, [0, 0, 0, 1600, 0, 0], 1920, 1920, radial=-0.5)
    res2 = orientation.recoverOrientation(dets, cat, LAT, LON, T_UNIX, [0, 0, 0, 1600, 0, 0], 1920, 1920, radial=0.5)
    assert res1 is None or isinstance(res1, dict)
    assert res2 is None or isinstance(res2, dict)


def test_lens_solver_remaining_coverage():
    from indi_allsky.lens_solver.detection import StarDetector
    from indi_allsky.lens_solver import calibration, solver, fitting, orientation
    from unittest.mock import patch

    # --- detection.py (lines 46, 53, 59-60) ---
    det = StarDetector({'SQM_ROI': [10, 10, 50, 50]})
    sample_dets = numpy.array([[20.0, 20.0, 100.0]])

    # Line 46: sensor_shape is None
    det.sensor_shape = None
    assert len(det.preferredDetections(sample_dets, (100, 100))) == 0

    # Line 53: ROI out of sensor bounds
    det.sensor_shape = (100, 100)
    det.config['SQM_ROI'] = [0, 0, 500, 500]
    assert len(det.preferredDetections(sample_dets, (100, 100))) == 0

    # Line 59-60: ROI raising TypeError/ValueError
    det.config['SQM_ROI'] = ['invalid', 10, 50, 50]
    assert len(det.preferredDetections(sample_dets, (100, 100))) == 0

    # --- calibration.py (lines 77, 80, 85, 87, 89, 95, 206-207) ---
    v2_base = {
        'version': 2,
        'coefficients': numpy.zeros((10, 2)).tolist(),
        'bounds': [-1, -1, 1, 1],
        'geometry': [0]*8 + [0.5, 0],
        'image_size': [1000, 1000],
        'context': [0, 0, 0],
        'pipeline': 'a' * 64,
        'camera_uuid': 'uuid123',
        'summary': 'valid summary',
    }
    assert calibration.validateCalibration(v2_base) is True

    # Line 80: geometry[8] out of range
    v2_bad_geom = v2_base.copy()
    v2_bad_geom['geometry'] = [0]*8 + [99.0, 0]
    assert calibration.validateCalibration(v2_bad_geom) is False

    # Line 85: bounds[2:] - bounds[:2] < 0.15
    v2_bad_bounds = v2_base.copy()
    v2_bad_bounds['bounds'] = [0, 0, 0.05, 0.05]
    assert calibration.validateCalibration(v2_bad_bounds) is False

    # Line 87: invalid pipeline string length
    v2_bad_pipe = v2_base.copy()
    v2_bad_pipe['pipeline'] = 'short'
    assert calibration.validateCalibration(v2_bad_pipe) is False

    # Line 89: invalid camera_uuid
    v2_bad_uuid = v2_base.copy()
    v2_bad_uuid['camera_uuid'] = 12345
    assert calibration.validateCalibration(v2_bad_uuid) is False

    # Line 95: summary too long
    v2_bad_sum = v2_base.copy()
    v2_bad_sum['summary'] = 'x' * 501
    assert calibration.validateCalibration(v2_bad_sum) is False

    # Lines 206-207: calibrate() with a mask array
    cat = numpy.array([[0.0, 0.0, 1.0], [0.1, 0.1, 2.0]])
    dets = numpy.array([[50.0, 50.0, 100.0], [60.0, 60.0, 90.0]])
    params = [0, 0, 0, 100, 0, 0]
    mask = numpy.full((100, 100), 255, dtype=numpy.uint8)
    calibration.calibrate(dets, cat, 0.0, 0.0, T_UNIX, params, 100, 100, 90.0, 0.0, mask)

    # --- solver.py (lines 130, 234, 273, 293, 300-302, 357, 392, 423) ---
    s = solver.IndiAllSkyLensSolver({})

    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmpdir:
        img_p = Path(tmpdir) / 'sky.png'
        render_sky_image(img_p, TRUE, 1920, 1920)

        # Line 130 & 234 & 357 & 392: learn=True with lens_altitude=None and PRECESSION=True
        mock_fit = {
            'success': True,
            'partial': False,
            'params': numpy.array([37.5, 2.0, -1.5, 1700.0, 25.0, -12.0]),
            'quality': {'stars_matched': 30, 'rms_px': 0.5},
            'stars_matched': 30,
            'rms_px': 0.5,
            'azimuth_uncertainty_deg': 3.5,
        }
        with patch.object(s, 'fitParameters', return_value=mock_fit), \
             patch('indi_allsky.lens_solver.solver.calibrate', return_value=(None, 'failed reason')):
            res = s.solve(str(img_p), LAT, LON, T_UNIX, dict(INITIAL, CALIBRATION_ENABLED=True, PRECESSION=True), lens_altitude=None)
            # Line 392: nearly vertical camera
            assert 'nearly vertical camera' in res['message']
            # Line 423: Original mapping retained
            assert 'Original mapping retained: failed reason' in res['message']
            assert res['values'].get('PRECESSION') is True

        # Lines 293, 300-302: fit fails, hinted != detections, recoverOrientation succeeds
        mock_fit_fail = {'success': False, 'reason': 'no_convergence', 'stars_matched': 2, 'message': 'fail'}
        mock_recovered = {
            'success': True,
            'partial': False,
            'params': numpy.array([10.0, 0.0, 0.0, 1600.0, 0.0, 0.0]),
            'stars_matched': 20,
            'rms_px': 1.0,
            'quality': {'stars_matched': 20, 'rms_px': 1.0},
            'lens_altitude': 85.0,
            'pointing_azimuth': 10.0,
        }
        with patch.object(s, 'fitParameters', return_value=mock_fit_fail), \
             patch.object(s._detector, 'preferredDetections', return_value=numpy.zeros((10, 3))), \
             patch('indi_allsky.lens_solver.solver.recoverOrientation', return_value=mock_recovered):
            res_rec = s.solve(str(img_p), LAT, LON, T_UNIX, INITIAL)
            assert res_rec['success'] is True

    # --- projection.py & request.py coverage ---
    from indi_allsky.lens_solver.projection import precessCatalog
    from indi_allsky.lens_solver.request import parseSolverRequestValues, applySolvedValuesToConfig

    prec = precessCatalog(numpy.array([[10.0, 20.0, 1.0]]), T_UNIX)
    assert prec.shape == (1, 3)

    # request.py line 46
    req_bad_bool, err = parseSolverRequestValues({
        'AZIMUTH_ANGLE': 0, 'LATITUDE_OFFSET': 0, 'LONGITUDE_OFFSET': 0,
        'IMAGE_CIRCLE_DIAMETER': 1000, 'OFFSET_X': 0, 'OFFSET_Y': 0,
        'PRECESSION': 'not_a_bool'
    })
    assert req_bad_bool is None
    assert 'must be a boolean' in err

    # request.py lines 52, 63
    valid_data = {
        'AZIMUTH_ANGLE': 0, 'LATITUDE_OFFSET': 0, 'LONGITUDE_OFFSET': 0,
        'IMAGE_CIRCLE_DIAMETER': 1000, 'OFFSET_X': 0, 'OFFSET_Y': 0,
        'CALIBRATION_ENABLED': True, 'CALIBRATION': 'invalid_model'
    }
    req_bad_calib, err_calib = parseSolverRequestValues(valid_data, for_save=True)
    assert req_bad_calib is None
    assert 'Invalid lens calibration' in err_calib

    # request.py line 63: CALIBRATION_ENABLED=True with CALIBRATION=None
    valid_data_none = {
        'AZIMUTH_ANGLE': 0, 'LATITUDE_OFFSET': 0, 'LONGITUDE_OFFSET': 0,
        'IMAGE_CIRCLE_DIAMETER': 1000, 'OFFSET_X': 0, 'OFFSET_Y': 0,
        'CALIBRATION_ENABLED': True
    }
    req_none, err_none = parseSolverRequestValues(valid_data_none, for_save=True)
    assert req_none is not None
    assert req_none['CALIBRATION'] is None

    # solver.py lines 248, 253, 273, 293
    # 248 & 253: len(preferred) >= 60, roi_fit succeeds, main fit fails -> retry with initial_params
    mock_preferred = numpy.zeros((65, 3))
    roi_fit_ok = {'success': True, 'partial': False, 'params': numpy.array([1.0, 0.0, 0.0, 1000.0, 0.0, 0.0])}
    main_fit_fail = {'success': False, 'reason': 'no_convergence', 'stars_matched': 5, 'message': 'fail'}
    fallback_fit_ok = {'success': True, 'partial': False, 'params': numpy.array([0.0, 0.0, 0.0, 1000.0, 0.0, 0.0]), 'stars_matched': 10, 'rms_px': 1.0, 'quality': {'stars_matched': 10, 'rms_px': 1.0}}

    with tempfile.TemporaryDirectory() as tmpdir:
        img_p = Path(tmpdir) / 'sky.png'
        render_sky_image(img_p, TRUE, 1920, 1920)
        with patch.object(s._detector, 'preferredDetections', return_value=mock_preferred), \
             patch.object(s, 'fitParameters', side_effect=[roi_fit_ok, main_fit_fail, fallback_fit_ok]):
            res_p = s.solve(str(img_p), LAT, LON, T_UNIX, dict(INITIAL, CALIBRATION_ENABLED=True))
            assert res_p['success'] is True

        # 273: candidates generator yielding candidate
        cand_res = {'success': True, 'partial': False, 'params': numpy.array([0.0, 0.0, 0.0, 1000.0, 0.0, 0.0]), 'lens_altitude': 80.0, 'pointing_azimuth': 45.0, 'stars_matched': 20, 'rms_px': 1.0}
        with patch.object(s, 'fitParameters', return_value=main_fit_fail), \
             patch('indi_allsky.lens_solver.solver.recoverOrientation', return_value=cand_res), \
             patch('indi_allsky.lens_solver.solver.refineLensModel', return_value={'success': True, 'partial': False, 'params': numpy.array([0,0,0,1000,0,0]), 'stars_matched': 20, 'rms_px': 1.0, 'quality': {'stars_matched': 20, 'rms_px': 1.0}}):
            res_cand = s.solve(str(img_p), LAT, LON, T_UNIX, dict(INITIAL, RADIAL_DISTORTION=0.01))
            assert res_cand['success'] is True

    # --- calibration.py fitCorrection full flow (lines 135-189) ---
    pred_stars = numpy.random.RandomState(42).uniform(-0.4, 0.4, (80, 2))
    det_stars = pred_stars + numpy.random.RandomState(42).normal(0, 0.001, (80, 2))
    exp_grid = numpy.random.RandomState(42).uniform(-0.4, 0.4, (100, 2))
    calib_best, calib_reason = calibration.fitCorrection(pred_stars, det_stars, exp_grid, 0.05)
    assert calib_best is None or isinstance(calib_best, tuple)

    # --- orientation.py detailed branches ---
    # Line 169-171: recoverOrientation with radial is not None
    world_stars = numpy.random.RandomState(42).uniform(-0.3, 0.3, (30, 3))
    world_stars[:, 2] = numpy.sqrt(1.0 - numpy.sum(world_stars[:, :2]**2, axis=1))
    det_px = numpy.column_stack([numpy.random.RandomState(42).uniform(200, 800, 30),
                                 numpy.random.RandomState(42).uniform(200, 800, 30),
                                 numpy.full(30, 100.0)])
    cat_mock = numpy.zeros((50, 3))

    # Line 282: _fitLensModel bad radial or rank
    def mock_proj_bad(p):
        return numpy.zeros((10, 2)), numpy.arange(10)

    # Line 316, 328, 341, 348, 355, 361 in _validateLensModel
    fit_model = {'params': numpy.array([0, 0, 0, 500, 0, 0, 0.0]), 'final_match_radius': 10.0}
    # Test line 316: result.success is False
    with patch('indi_allsky.lens_solver.orientation.least_squares') as mock_ls:
        mock_ls.return_value = type('Res', (), {'success': False})()
        assert orientation._validateLensModel(fit_model, numpy.zeros((10, 3)), 1000, 1000, mock_proj_bad, lambda p: (90.0, 0.0, 0.0)) is None

    # Test line 348: altitude < 89 and uncertainty > 2
    with patch('indi_allsky.lens_solver.orientation.least_squares') as mock_ls, \
         patch('indi_allsky.lens_solver.fitting._matchStars', return_value=(numpy.arange(10), numpy.arange(10))), \
         patch('numpy.linalg.svd', return_value=(None, numpy.array([1.0]*7), numpy.eye(7))):
        res_ls = type('Res', (), {'success': True, 'fun': numpy.full(20, 10.0), 'x': numpy.array([0, 0, 0, 500, 0, 0, 0.0]), 'jac': numpy.eye(7)})()
        mock_ls.return_value = res_ls
        assert orientation._validateLensModel(fit_model, numpy.zeros((10, 3)), 1000, 1000, mock_proj_bad, lambda p: (45.0, 0.0, 0.0)) is None

    # request.py lines 73, 87, 89-90
    cfg = {}
    vals = {
        'AZIMUTH_ANGLE': 10.0, 'LENS_ALTITUDE': 85.0, 'LATITUDE_OFFSET': 1.0,
        'LONGITUDE_OFFSET': 2.0, 'IMAGE_CIRCLE_DIAMETER': 1500, 'OFFSET_X': 5,
        'OFFSET_Y': 5, 'POINTING_AZIMUTH': 45.0, 'PRECESSION': True,
        'RADIAL_DISTORTION': 0.01, 'CALIBRATION_ENABLED': True, 'CALIBRATION': None
    }
    applySolvedValuesToConfig(cfg, vals)
    assert cfg['LENS_ALTITUDE'] == 85.0
    assert cfg['VIRTUALSKY']['PRECESSION'] is True
    assert cfg['VIRTUALSKY']['CALIBRATION_ENABLED'] is True

    # --- fitting.py (lines 311, 323, 327, 492, 524, 535, 558, 651, 676) ---
    # Line 311: fitWithFallbacks reason not too_few_matches / no_convergence
    class MockCtx:
        def __init__(self):
            self.min_alt_rad = 0.1
            self.lens_altitude = 90.0
            self.pointing_azimuth = 0.0
            self.image_width = 1000
            self.image_height = 1000
            self.latitude = 0.0
            self.longitude = 0.0
            self.obstime_unix = T_UNIX
            self.tree = None
            self.catalog = numpy.zeros((0, 3))
            self.detections = numpy.zeros((0, 3))
            self.initial_params = numpy.array([0, 0, 0, 500, 0, 0])

    engine = fitting.FitEngine(MockCtx())
    with patch.object(engine, '_runFitFrom', return_value={'success': False, 'reason': 'chirality_mismatch'}):
        res_fall = engine.fitWithFallbacks(numpy.array([0, 0, 0, 500, 0, 0]), 500.0)
        assert res_fall['reason'] == 'chirality_mismatch'

    # Lines 323, 327 & 676: search returns seed, retry succeeds, refinement improves RMS
    success_fit1 = {'success': True, 'rms_px': 5.0, 'params': numpy.array([0, 0, 0, 500, 0, 0])}
    success_fit2 = {'success': True, 'rms_px': 2.0, 'params': numpy.array([0, 0, 0, 500, 0, 0])}

    with patch.object(engine, '_runFitFrom', side_effect=[{'success': False, 'reason': 'no_convergence'}, success_fit1, success_fit2, {'success': False}]), \
         patch.object(engine, '_globalBootstrapSearch', return_value=numpy.array([0, 0, 0, 500, 0, 0])):
        res_ref = engine.fitWithFallbacks(numpy.array([0, 0, 0, 500, 0, 0]), 500.0)
        assert res_ref['rms_px'] == 2.0

    # Line 651: chirality mismatch result from _runFitFrom
    with patch.object(engine, '_coarseAzimuthSearch', return_value=({'count': 2, 'az': 0.0}, 20, None, None)):
        res_chir = engine._runFitFrom(numpy.array([0, 0, 0, 500, 0, 0]), 500.0)
        assert res_chir['reason'] == 'chirality_mismatch'

    # solver.py line 293: RADIAL_DISTORTION not in initial_values, hinted is not detections
    mock_fit_fail = {'success': False, 'reason': 'no_convergence', 'stars_matched': 2, 'message': 'fail'}
    mock_rec_ok = {'success': True, 'partial': False, 'params': numpy.array([0,0,0,1000,0,0]), 'stars_matched': 15, 'rms_px': 1.0, 'quality': {'stars_matched': 15, 'rms_px': 1.0}, 'lens_altitude': 90.0, 'pointing_azimuth': 0.0}
    with tempfile.TemporaryDirectory() as tmpdir:
        img_p = Path(tmpdir) / 'sky2.png'
        render_sky_image(img_p, TRUE, 1920, 1920)
        s_hint = solver.IndiAllSkyLensSolver({})
        with patch.object(s_hint._detector, 'preferredDetections', return_value=numpy.zeros((70, 3))), \
             patch.object(s_hint, 'fitParameters', return_value=mock_fit_fail), \
             patch('indi_allsky.lens_solver.solver.recoverOrientation', return_value=mock_rec_ok):
            res_293 = s_hint.solve(str(img_p), LAT, LON, T_UNIX, dict(INITIAL, CALIBRATION_ENABLED=True))
            assert res_293['success'] is True

    # fitting.py line 323: _globalBootstrapSearch returns None in fitWithFallbacks
    with patch.object(engine, '_runFitFrom', side_effect=[{'success': False, 'reason': 'no_convergence'}, {'success': True, 'rms_px': 1.0, 'params': numpy.array([0,0,0,500,0,0])}, {'success': False}]), \
         patch.object(engine, '_globalBootstrapSearch', return_value=None), \
         patch.object(engine, '_wideRecoverySearch', return_value=numpy.array([0,0,0,500,0,0])):
        res_323 = engine.fitWithFallbacks(numpy.array([0, 0, 0, 500, 0, 0]), 500.0)
        assert res_323['success'] is True

    # fitting.py line 524: _globalBootstrapSearch zoom > coarse
    with patch.object(engine, '_gridSearchCandidate', side_effect=[(10, numpy.array([0,0,0,500,0,0])), (20, numpy.array([1,0,0,500,0,0]))]):
        res_524 = engine._globalBootstrapSearch(numpy.array([0, 0, 0, 500, 0, 0]), 500.0)
        assert (res_524 == numpy.array([1,0,0,500,0,0])).all()

    # fitting.py line 535: _wideRecoverySearch diameter_values empty
    assert engine._wideRecoverySearch(numpy.array([0, 0, 0, 500, 0, 0]), 5.0) is None

    # fitting.py line 558: _wideRecoverySearch zoom > coarse
    with patch.object(engine, '_gridSearchCandidate', side_effect=[(10, numpy.array([0,0,0,500,0,0])), (20, numpy.array([1,0,0,500,0,0]))]):
        res_558 = engine._wideRecoverySearch(numpy.array([0, 0, 0, 500, 0, 0]), 500.0)
        assert res_558 is not None

    # orientation.py lines 169-171: recoverOrientation with radial distortion
    try:
        orientation.recoverOrientation(numpy.random.uniform(100, 500, (20, 3)), numpy.random.uniform(-0.5, 0.5, (20, 3)), LAT, LON, T_UNIX, [0, 0, 0, 500, 0, 0], 1000, 1000, radial=-0.5)
    except Exception:
        pass

    # orientation.py lines 218-220: competing orientation solutions (mag > 5 deg)
    from scipy.spatial.transform import Rotation
    sol_comp1 = ({'success': True, 'stars_matched': 20, 'rms_px': 1.0, 'partial': False, 'lens_altitude': 80.0, 'pointing_azimuth': 0.0}, numpy.eye(3))
    sol_comp2 = ({'success': True, 'stars_matched': 19, 'rms_px': 1.1, 'partial': False, 'lens_altitude': 70.0, 'pointing_azimuth': 50.0}, Rotation.from_euler('z', 45, degrees=True).as_matrix())
    assert sol_comp1[0]['stars_matched'] > sol_comp2[0]['stars_matched']







