import numpy as np
import pytest
import cv2

from indi_allsky.lens_solver import IndiAllSkyLensSolver, predictAltAz, projectToPixels
from indi_allsky.lens_solver.request import parseSolverRequestValues, applySolvedValuesToConfig
from tests.lens_solver.test_camera_tilt import KEYS, PARAMS, reference_pixels
from tests.lens_solver.test_orientation import render_stars


@pytest.mark.parametrize('radial', [-0.5, -0.1, 0, 0.05, 1])
def test_radial_model_keeps_axis_rim_and_invertible_radii(radial):
    altitude = np.linspace(0, np.pi/2, 1001)
    p = [0, 0, 0, 1000, 0, 0, radial]
    x, y = projectToPixels(altitude, np.zeros_like(altitude), p, 1000, 1000)
    np.testing.assert_allclose(x, 500)
    np.testing.assert_allclose(y[[0, -1]], [0, 500], atol=1e-5)
    assert np.all(np.diff(y) > 0)


@pytest.mark.parametrize('radial', [-0.51, 1.01, None, True, float('nan'), float('inf'), 'bad'])
def test_invalid_lens_curve_is_never_saved(radial):
    values, error = parseSolverRequestValues(dict(zip(KEYS, PARAMS), RADIAL_DISTORTION=radial), for_save=True)
    assert values is None and error


def test_lens_curve_save_and_legacy_payload():
    config = {'VIRTUALSKY': {}}
    values = dict(zip(KEYS, PARAMS), RADIAL_DISTORTION=0.05)
    applySolvedValuesToConfig(config, values)
    assert config['VIRTUALSKY']['RADIAL_DISTORTION'] == 0.05
    del values['RADIAL_DISTORTION']
    applySolvedValuesToConfig(config, values)
    assert config['VIRTUALSKY']['RADIAL_DISTORTION'] == 0.05


@pytest.mark.parametrize('altitude,heading', [(87.4, 176), (54, 359), (0, 270), (90, 0)])
def test_noisy_curved_lens_without_pointing_hint(tmp_path, altitude, heading):
    solver = IndiAllSkyLensSolver({})
    timestamp = 1788731972
    catalog = solver.loadCatalog()
    alt, az = predictAltAz(catalog, 53, 11, timestamp)
    x, y, z = reference_pixels(alt, az, altitude, heading)
    cx, cy = 2028/2+PARAMS[4], 1520/2-PARAMS[5]
    factor = np.maximum(1+z, 1e-12)**(-0.08)
    x, y = cx+(x-cx)*factor, cy+(y-cy)*factor
    keep = (alt > np.radians(10)) & (z > 0) & (x > 5) & (x < 2023) & (y > 5) & (y < 1515)
    path = tmp_path/'noisy.png'
    render_stars(path, np.column_stack([x[keep], y[keep], np.ones(keep.sum())]))
    rng = np.random.default_rng(42)
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE).astype(float)
    image = np.clip(image+rng.normal(0, 3, image.shape), 0, 255).astype(np.uint8)
    image[rng.integers(0, 1520, 300), rng.integers(0, 2028, 300)] = 255
    assert cv2.imwrite(str(path), image)
    initial = dict(zip(KEYS, PARAMS), LENS_ALTITUDE=90, RADIAL_DISTORTION=0)
    result = solver.solve(path, 53, 11, timestamp, initial)
    assert result['success'], result
    v = result['values']
    # A horizontal camera has only a small, one-sided star field in this crop.
    # Retain the blind-solve elevation tolerance while requiring 2-degree heading.
    assert abs(v['LENS_ALTITUDE']-altitude) < 0.5, result
    if altitude < 89:
        assert abs((v['POINTING_AZIMUTH']-heading+180) % 360-180) < 2
    assert abs(v['RADIAL_DISTORTION']-0.08) < 0.01


@pytest.mark.parametrize('hour', [0, 4, 10, 18])
@pytest.mark.parametrize('model', ['equisolid', 'equidistant', 'stereographic', 'orthographic'])
@pytest.mark.parametrize('diameter', [1400, 2951])
def test_pointing_with_common_lens_projections(tmp_path, hour, model, diameter):
    # Independent native lens laws, including complete and sensor-clipped circles.
    timestamp = 1788731972+hour*3600
    solver = IndiAllSkyLensSolver({})
    catalog = solver.loadCatalog()
    alt, az = predictAltAz(catalog, 53, 11, timestamp)
    params = PARAMS.copy(); params[3] = diameter
    x, y, z = reference_pixels(alt, az, 87.4, 176, params)
    centre = np.array([2028/2+params[4], 1520/2-params[5]])
    delta = np.column_stack([x, y])-centre
    theta = np.arccos(np.clip(z, -1, 1))
    radius = {'equisolid': np.sqrt(2)*np.sin(theta/2),
              'equidistant': theta/(np.pi/2), 'stereographic': np.tan(theta/2),
              'orthographic': np.sin(theta)}[model]*diameter/2
    xy = centre+delta*(radius/np.maximum(np.linalg.norm(delta, axis=1), 1e-10))[:, None]
    keep = (alt > np.radians(10)) & (z > 0) & (xy[:, 0] > 5) & (xy[:, 0] < 2023) & (xy[:, 1] > 5) & (xy[:, 1] < 1515)
    path = tmp_path/'lens.png'
    render_stars(path, np.column_stack([xy[keep], np.ones(keep.sum())]))
    initial = dict(zip(KEYS, params), LENS_ALTITUDE=90, RADIAL_DISTORTION=0)
    result = solver.solve(path, 53, 11, timestamp, initial)
    assert result['success'], result
    v = result['values']
    assert abs((v['POINTING_AZIMUTH']-176+180) % 360-180) < 2, result
    assert abs(v['LENS_ALTITUDE']-87.4) < 0.15, result
