"""Mirroring must survive the full tilted pipeline and saved corrections."""
from itertools import product

import numpy as np
import pytest

from indi_allsky.lens_solver import IndiAllSkyLensSolver, predictAltAz, projectToPixels
from indi_allsky.lens_solver.calibration import validateCalibration, calibrate, displacement
from indi_allsky.lens_solver.orientation import recoverOrientation
from indi_allsky.lens_solver.projection import precessCatalog
from indi_allsky.lens_solver.request import parseSolverRequestValues, applySolvedValuesToConfig
from tests.lens_solver.test_camera_tilt import PARAMS, KEYS, reference_pixels
from tests.lens_solver.test_orientation import render_stars
from tests.lens_solver.test_calibration import saved_model, VALUES


ORIENTATIONS = list(product((False, True), repeat=2))
CENTER = np.array([1021., 895.])
TIME = 1788731972


def mirrored_field(altitude, heading, flip_h, flip_v, radial=0):
    catalog = precessCatalog(IndiAllSkyLensSolver({}).loadCatalog(), TIME)
    alt, az = predictAltAz(catalog, 53, 11, TIME)
    x, y, z = reference_pixels(alt, az, altitude, heading)
    xy = CENTER+(np.column_stack([x, y])-CENTER)*np.maximum(1+z, 1e-12)[:, None]**(-radial)
    xy = CENTER+(xy-CENTER)*[-1 if flip_h else 1, -1 if flip_v else 1]
    keep = ((alt > np.radians(10)) & (z > 0) & (xy[:, 0] > 5)
            & (xy[:, 0] < 2023) & (xy[:, 1] > 5) & (xy[:, 1] < 1515))
    return catalog, np.column_stack([xy[keep], np.full(keep.sum(), 500)]), alt[keep], az[keep]


@pytest.mark.parametrize('flip_h,flip_v,radial',
    [(h, v, None) for h, v in ORIENTATIONS]+[(False, True, -0.5), (True, False, 0.5)])
def test_triangle_recovery_uses_selected_mirroring(flip_h, flip_v, radial):
    catalog, detected, alt, az = mirrored_field(54, 176, flip_h, flip_v, radial or 0)
    initial = np.array([0, 0, 0, 2900, 20, -100])
    result = recoverOrientation(detected, catalog, 53, 11, TIME, initial, 2028, 1520, radial,
                                flip_h=flip_h, flip_v=flip_v)
    assert result is not None
    assert abs(result['lens_altitude']-54) < 0.01
    assert abs(result['pointing_azimuth']-176) < 0.01
    xy = projectToPixels(alt, az, result['params'], 2028, 1520,
        lens_altitude=result['lens_altitude'], pointing_azimuth=result['pointing_azimuth'],
        flip_h=flip_h, flip_v=flip_v)
    np.testing.assert_allclose(np.column_stack(xy), detected[:, :2], atol=0.1)


@pytest.mark.parametrize('altitude,heading,radial,flip_h,flip_v', [
    (54, 176, 0, True, False), (20, 120, 0.08, False, True),
    (88, 220, 0.08, True, True), (90, 0, 0, True, False),
])
@pytest.mark.parametrize('hint_v', [False, True])
def test_automatic_mirrored_tilt_and_curvature_from_image(tmp_path, altitude, heading, radial, flip_h, flip_v, hint_v):
    _, detected, alt, az = mirrored_field(altitude, heading, flip_h, flip_v, radial)
    path = tmp_path/'mirrored-tilt.png'
    render_stars(path, detected)
    original = path.read_bytes()
    initial = dict(zip(KEYS, [0, 0, 0, 2900, 20, -100]),
                   LENS_ALTITUDE=90, RADIAL_DISTORTION=0, PRECESSION=True,
                   FLIP_H=not (flip_h ^ flip_v ^ hint_v), FLIP_V=hint_v)
    result = IndiAllSkyLensSolver({}).solve(path, 53, 11, TIME, initial)
    assert result['success'] and not result['partial'], result
    v = result['values']
    assert v['FLIP_H'] is (flip_h ^ flip_v ^ hint_v) and v['FLIP_V'] is hint_v
    assert abs(v['LENS_ALTITUDE']-altitude) < 0.5
    if altitude < 89:
        assert abs((v['POINTING_AZIMUTH']-heading+180) % 360-180) < 2
    assert abs(v['RADIAL_DISTORTION']-radial) < 0.01
    flips = dict(flip_h=v['FLIP_H'], flip_v=v['FLIP_V'])
    params = np.array([v[k] for k in KEYS]+[v['RADIAL_DISTORTION']])
    xy = projectToPixels(alt, az, params, 2028, 1520,
        lens_altitude=v['LENS_ALTITUDE'], pointing_azimuth=v['POINTING_AZIMUTH'], **flips)
    assert np.max(np.linalg.norm(np.column_stack(xy)-detected[:, :2], axis=1)) < 4
    zx, zy = projectToPixels(np.pi/2, 0, params, 2028, 1520,
        lens_altitude=v['LENS_ALTITUDE'], pointing_azimuth=v['POINTING_AZIMUTH'], **flips)
    assert np.hypot(result['geometry']['zenith_x']-zx, result['geometry']['zenith_y']-zy) < 2
    parsed, error = parseSolverRequestValues(v, for_save=True)
    assert error is None
    config = applySolvedValuesToConfig({}, parsed)
    assert config['VIRTUALSKY']['FLIP_H'] is v['FLIP_H']
    assert config['VIRTUALSKY']['FLIP_V'] is v['FLIP_V']
    assert path.read_bytes() == original


@pytest.mark.parametrize('flip_h,flip_v', ORIENTATIONS)
def test_correction_fits_photo_coordinates_under_mirroring(flip_h, flip_v):
    catalog, detected, _, _ = mirrored_field(54, 176, flip_h, flip_v)
    source = (detected[:, :2]-CENTER)/(PARAMS[3]/2)
    shift = source*(0.025*np.sum(source**2, axis=1))[:, None]
    target = source+shift
    detected[:, :2] = CENTER+target*(PARAMS[3]/2)
    mask = np.full((1520, 2028), 255, np.uint8)
    mask[:, :150] = 0  # Photo boundary stays on the left for all orientations.
    original = mask.copy()
    correction, why = calibrate(detected, catalog, 53, 11, TIME, PARAMS, 2028, 1520,
                                54, 176, mask, flip_h=flip_h, flip_v=flip_v)
    assert correction is not None, why
    model, stats = correction
    assert stats['after'] < stats['before']*0.8
    assert np.mean(np.linalg.norm(target-source-displacement(source, model), axis=1)) < 0.005
    np.testing.assert_array_equal(mask, original)


@pytest.mark.parametrize('version', [1, 2])
@pytest.mark.parametrize('flip_h,flip_v', ORIENTATIONS)
def test_saved_correction_is_bound_to_orientation(version, flip_h, flip_v):
    model = saved_model(version)
    model['orientation'] = [flip_h, flip_v]
    payload = dict(VALUES, LENS_ALTITUDE=90, RADIAL_DISTORTION=0.08 if version == 2 else 0,
        PRECESSION=version == 2, CALIBRATION_ENABLED=True, CALIBRATION=model,
        FLIP_H=flip_h, FLIP_V=flip_v)
    assert validateCalibration(model)
    parsed, error = parseSolverRequestValues(payload, for_save=True)
    assert error is None
    assert applySolvedValuesToConfig({}, parsed)['VIRTUALSKY']['CALIBRATION'] == model
    for key in ('FLIP_H', 'FLIP_V'):
        changed = dict(payload, **{key: not payload[key]})
        assert 'Orientation changed' in parseSolverRequestValues(changed, for_save=True)[1]
    del model['orientation']
    assert validateCalibration(model)  # Legacy calibrations imply no flips.
    assert (parseSolverRequestValues(payload, for_save=True)[1] is None) is (not flip_h and not flip_v)


@pytest.mark.parametrize('orientation', [None, [], [False], [True]*3, [0, 1], ['true', False], {}])
def test_malformed_saved_orientation_is_refused(orientation):
    model = saved_model()
    model['orientation'] = orientation
    assert not validateCalibration(model)
