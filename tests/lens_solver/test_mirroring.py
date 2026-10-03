from copy import deepcopy
from itertools import product

import cv2
import numpy as np
import pytest

from indi_allsky.lens_solver import (
    IndiAllSkyLensSolver, applySolvedValuesToConfig, parseSolverRequestValues,
    predictAltAz, projectToPixels,
)
from indi_allsky.lens_solver import solver as solver_mod


ORIENTATIONS = list(product((False, True), repeat=2))
PARAMS = np.array([37.5, 2.0, -1.5, 1700.0, 25.0, -12.0])
KEYS = ('AZIMUTH_ANGLE', 'LATITUDE_OFFSET', 'LONGITUDE_OFFSET',
        'IMAGE_CIRCLE_DIAMETER', 'OFFSET_X', 'OFFSET_Y')
VALUES = dict(zip(KEYS, PARAMS))
LAT, LON, TIME = 40.1, -75.4, 1770000000


@pytest.mark.parametrize('flip_h,flip_v', ORIENTATIONS)
def test_projection_reflects_after_rotation_about_offset_center(flip_h, flip_v):
    alt = np.radians([15, 40, 70, 90])
    az = np.radians([20, 150, 260, 355])
    x, y = projectToPixels(alt, az, PARAMS, 2100, 1900)
    mx, my = projectToPixels(alt, az, PARAMS, 2100, 1900, flip_h=flip_h, flip_v=flip_v)
    np.testing.assert_allclose(mx, 2*(1050+25)-x if flip_h else x)
    np.testing.assert_allclose(my, 2*(950+12)-y if flip_v else y)
    # Chirality probes are relative to the selected orientation.
    px, py = projectToPixels(alt, az, PARAMS, 2100, 1900, mirror=True,
                            flip_h=flip_h, flip_v=flip_v)
    np.testing.assert_allclose(px, 2*(1050+25)-mx)
    np.testing.assert_allclose(py, my)


@pytest.mark.parametrize('flip_h,flip_v', ORIENTATIONS)
@pytest.mark.parametrize('downscale', [False, True])
@pytest.mark.parametrize('orientation_hint', ['matching', 'wrong', 'missing'])
def test_solve_mirrored_photo_preserves_image_and_orientation(tmp_path, monkeypatch, flip_h, flip_v,
                                                            downscale, orientation_hint):
    width, height = 2100, 1900
    solver = IndiAllSkyLensSolver({})
    catalog = solver.loadCatalog()
    alt, az = predictAltAz(catalog, LAT+PARAMS[1], LON+PARAMS[2], TIME)
    visible = alt > np.radians(10)
    x, y = projectToPixels(alt[visible], az[visible], PARAMS, width, height)
    # Build the fixture independently of the new projection flags.
    if flip_h:
        x = 2*(width/2+PARAMS[4])-x
    if flip_v:
        y = 2*(height/2-PARAMS[5])-y
    image = np.full((height, width), 10, dtype=np.uint8)
    for xi, yi in zip(x, y):
        if 5 < xi < width-5 and 5 < yi < height-5:
            cv2.circle(image, (round(xi), round(yi)), 2, 220, -1)
    path = tmp_path / 'sky.png'
    assert cv2.imwrite(str(path), cv2.GaussianBlur(image, (3, 3), 0.6))
    original = path.read_bytes()
    if downscale:
        monkeypatch.setattr(solver_mod, 'MAX_SOLVE_PIXELS', width*height//3)
    initial = dict(zip(KEYS, [25, 0, 0, 1600, 20, -10]), FLIP_H=flip_h, FLIP_V=flip_v)
    if orientation_hint == 'wrong':
        initial['FLIP_H'] = not flip_h
    elif orientation_hint == 'missing':
        del initial['FLIP_H'], initial['FLIP_V']
    result = solver.solve(path, LAT, LON, TIME, initial)
    assert result['success'], result
    assert result['quality']['rms_px'] < 2
    expected_v = initial.get('FLIP_V', False)
    expected_h = flip_h ^ flip_v ^ expected_v
    assert result['values']['FLIP_H'] is result['geometry']['flip_h'] is expected_h
    assert result['values']['FLIP_V'] is result['geometry']['flip_v'] is expected_v
    angle = PARAMS[0] + (180 if flip_v != expected_v else 0)
    assert abs((result['values']['AZIMUTH_ANGLE']-angle+180) % 360-180) < 0.5
    for key, truth, tolerance in zip(KEYS[1:], PARAMS[1:], [1, 1, 17, 8, 8]):
        assert abs(result['values'][key]-truth) < tolerance, result
    values, error = parseSolverRequestValues(result['values'])
    assert error is None
    saved = applySolvedValuesToConfig({}, values)
    assert saved['VIRTUALSKY']['FLIP_H'] is expected_h
    assert saved['VIRTUALSKY']['FLIP_V'] is expected_v
    assert path.read_bytes() == original


@pytest.mark.parametrize('flip_h,flip_v', ORIENTATIONS)
def test_save_orientation_and_preserve_capture_settings(flip_h, flip_v):
    config = {'IMAGE_FLIP_H': True, 'IMAGE_FLIP_V': False, 'LENS_ALTITUDE': 55,
              'VIRTUALSKY': {'MAGNITUDE': 4, 'FLIP_H': not flip_h, 'FLIP_V': not flip_v}}
    values, error = parseSolverRequestValues(dict(VALUES, FLIP_H=flip_h, FLIP_V=flip_v))
    assert error is None
    applySolvedValuesToConfig(config, values)
    assert config['VIRTUALSKY']['FLIP_H'] is flip_h
    assert config['VIRTUALSKY']['FLIP_V'] is flip_v
    assert config['IMAGE_FLIP_H'] is True
    assert config['IMAGE_FLIP_V'] is False
    assert config['LENS_ALTITUDE'] == 55
    assert config['VIRTUALSKY']['MAGNITUDE'] == 4
    saved = deepcopy(config)
    # Old clients must not clear a saved orientation.
    legacy, error = parseSolverRequestValues(VALUES)
    assert error is None
    applySolvedValuesToConfig(config, legacy)
    assert config == saved


@pytest.mark.parametrize('key', ['FLIP_H', 'FLIP_V'])
@pytest.mark.parametrize('invalid', ['false', 'true', 0, 1, None, [], {}])
def test_orientation_requires_json_booleans(key, invalid):
    values, error = parseSolverRequestValues(dict(VALUES, **{key: invalid}))
    assert values is None
    assert key in error


def test_wrong_selected_chirality_recommends_overlay_flip():
    solver = IndiAllSkyLensSolver({})
    catalog = solver.loadCatalog()
    params = np.array([37.5, 0, 0, 1700, 0, 0])
    alt, az = predictAltAz(catalog, LAT, LON, TIME)
    visible = alt > np.radians(10)
    x, y = projectToPixels(alt[visible], az[visible], params, 1920, 1920)
    detections = np.column_stack([x, y, np.ones(len(x))*100])
    result = solver.fitParameters(detections, catalog, LAT, LON, TIME, params,
                                  1920, 1920, flip_h=True)
    assert result['reason'] == 'chirality_mismatch'
    assert 'Flip Overlay Horizontally' in result['message']
    assert 'Flip Overlay Vertically' in result['message']
    assert 'Config -> Image' not in result['message']


@pytest.mark.parametrize('flip_h,flip_v', ORIENTATIONS)
def test_vertical_camera_has_determinable_rotation_and_parity(flip_h, flip_v):
    solver = IndiAllSkyLensSolver({})
    catalog = solver.loadCatalog()
    params = np.array([137.5, 0, 0, 1700, 25, -12])
    alt, az = predictAltAz(catalog, LAT, LON, TIME)
    visible = alt > np.radians(10)
    x, y = projectToPixels(alt[visible], az[visible], params, 2100, 1900)
    if flip_h:
        x = 2*(1050+25)-x
    if flip_v:
        y = 2*(950+12)-y
    detections = np.column_stack([x, y, np.ones(len(x))*100])
    initial = params.copy()
    initial[0] = 0
    result = solver.fitParameters(detections, catalog, LAT, LON, TIME, initial,
                                  2100, 1900, auto_orientation=True)
    assert result['success'], result
    assert result['flip_h'] is (flip_h ^ flip_v)
    assert result['flip_v'] is False
    assert abs((result['params'][0]-params[0]-(180 if flip_v else 0)+180) % 360-180) < 0.01
    # Re-solving a saved representation must not alternate equivalent flips.
    again = solver.fitParameters(detections, catalog, LAT, LON, TIME, result['params'],
        2100, 1900, flip_h=result['flip_h'], flip_v=result['flip_v'], auto_orientation=True)
    assert again['success']
    assert again['flip_h'] == result['flip_h'] and again['flip_v'] == result['flip_v']
    np.testing.assert_allclose(again['params'], result['params'], atol=0.01)


def test_ambiguous_star_field_does_not_choose_a_mirror():
    solver = IndiAllSkyLensSolver({})
    catalog = solver.loadCatalog(mag_limit=3.5)
    params = np.array([37.5, 0, 0, 1700, 0, 0])
    alt, az = predictAltAz(catalog, LAT, LON, TIME)
    visible = alt > np.radians(10)
    x, y = projectToPixels(alt[visible], az[visible], params, 1920, 1920)
    # Two equally populated, reflected patterns provide conflicting evidence.
    detections = np.column_stack([np.r_[x, 1920-x], np.r_[y, y], np.ones(len(x)*2)*100])
    result = solver.fitParameters(detections, catalog, LAT, LON, TIME, params,
                                  1920, 1920, auto_orientation=True)
    assert not result['success'], result
    assert result['reason'] == 'orientation_ambiguous'
    assert 'flip_h' not in result and 'params' not in result


def test_sparse_field_does_not_gain_a_solution_by_trying_both_parities():
    solver = IndiAllSkyLensSolver({})
    catalog = solver.loadCatalog()
    detections = np.array([[300., 500., 100.], [800., 900., 100.]])
    result = solver.fitParameters(detections, catalog, LAT, LON, TIME, PARAMS,
                                  2100, 1900, auto_orientation=True)
    assert not result['success']
    assert 'flip_h' not in result and 'params' not in result


@pytest.mark.parametrize('flip_h,flip_v', ORIENTATIONS)
def test_detection_mask_stays_in_photo_coordinates(tmp_path, flip_h, flip_v):
    mask = np.full((80, 100), 255, dtype=np.uint8)
    mask[:25, :40] = 0
    path = tmp_path / 'mask.png'
    assert cv2.imwrite(str(path), mask)
    config = {'DETECT_MASK': str(path), 'IMAGE_FLIP_H': True,
              'VIRTUALSKY': {'FLIP_H': flip_h, 'FLIP_V': flip_v}}
    result = IndiAllSkyLensSolver(config).buildExclusionMask(mask.shape)
    np.testing.assert_array_equal(result, np.fliplr(mask))
