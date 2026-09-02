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


# --- applySolvedValuesToConfig ----------------------------------------------

def test_apply_solved_values_to_config():
    config = {
        'LENS_ALTITUDE': 42.0,
        'LENS_IMAGE_CIRCLE': 999,
        'LENS_OFFSET_X': 111,
        'LENS_OFFSET_Y': 222,
        'UNRELATED_KEY': 'keep-me',
        'VIRTUALSKY': {'SOME_OTHER_KEY': 'keep-me-too'},
    }
    values = {
        'AZIMUTH_ANGLE': 37.5, 'LATITUDE_OFFSET': 2.0, 'LONGITUDE_OFFSET': -1.5,
        'IMAGE_CIRCLE_DIAMETER': 1700, 'OFFSET_X': 25, 'OFFSET_Y': -12,
    }
    virtualsky_ref = config['VIRTUALSKY']

    result = lens_solver.applySolvedValuesToConfig(config, values)

    assert result is config    # mutated and returned, never reassigned
    assert config['VIRTUALSKY'] is virtualsky_ref    # in-place, object identity preserved

    assert config['LENS_AZIMUTH'] == 37.5
    assert config['VIRTUALSKY']['LATITUDE_OFFSET'] == 2.0
    assert config['VIRTUALSKY']['LONGITUDE_OFFSET'] == -1.5
    assert config['VIRTUALSKY']['IMAGE_CIRCLE_DIAMETER'] == 1700
    assert config['VIRTUALSKY']['OFFSET_X'] == 25
    assert config['VIRTUALSKY']['OFFSET_Y'] == -12

    # never written
    assert config['LENS_ALTITUDE'] == 42.0
    assert config['LENS_IMAGE_CIRCLE'] == 999
    assert config['LENS_OFFSET_X'] == 111
    assert config['LENS_OFFSET_Y'] == 222
    # unrelated keys preserved
    assert config['UNRELATED_KEY'] == 'keep-me'
    assert config['VIRTUALSKY']['SOME_OTHER_KEY'] == 'keep-me-too'

    # exact changed-key set
    changed_top = {'LENS_AZIMUTH', 'VIRTUALSKY'}
    unchanged_top = set(config.keys()) - changed_top
    assert unchanged_top == {
        'LENS_ALTITUDE', 'LENS_IMAGE_CIRCLE', 'LENS_OFFSET_X', 'LENS_OFFSET_Y', 'UNRELATED_KEY'}
    changed_vs = {'LATITUDE_OFFSET', 'LONGITUDE_OFFSET', 'IMAGE_CIRCLE_DIAMETER', 'OFFSET_X', 'OFFSET_Y'}
    assert set(config['VIRTUALSKY'].keys()) - changed_vs == {'SOME_OTHER_KEY'}

    for key in ('IMAGE_CIRCLE_DIAMETER', 'OFFSET_X', 'OFFSET_Y'):
        assert type(config['VIRTUALSKY'][key]) is int
    assert type(config['LENS_AZIMUTH']) is float
    assert type(config['VIRTUALSKY']['LATITUDE_OFFSET']) is float


def test_apply_solved_values_to_config_creates_missing_virtualsky_section():
    config = {}
    values = {
        'AZIMUTH_ANGLE': 10.0, 'LATITUDE_OFFSET': 0.0, 'LONGITUDE_OFFSET': 0.0,
        'IMAGE_CIRCLE_DIAMETER': 1000, 'OFFSET_X': 0, 'OFFSET_Y': 0,
    }
    result = lens_solver.applySolvedValuesToConfig(config, values)
    assert result is config
    assert config['VIRTUALSKY']['IMAGE_CIRCLE_DIAMETER'] == 1000
