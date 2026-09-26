import cv2
import numpy
import pytest

from indi_allsky.lens_solver import IndiAllSkyLensSolver, predictAltAz, projectToPixels
from indi_allsky.lens_solver.projection import cameraAltAz, SIN45
from indi_allsky.lens_solver.request import parseSolverRequestValues, applySolvedValuesToConfig


PARAMS = numpy.array([200.0, 0.0, 0.0, 2951.0, 7.0, -135.0])
KEYS = ['AZIMUTH_ANGLE', 'LATITUDE_OFFSET', 'LONGITUDE_OFFSET',
        'IMAGE_CIRCLE_DIAMETER', 'OFFSET_X', 'OFFSET_Y']


def reference_pixels(alt, az, altitude, heading, params=PARAMS):
    """Independent Cartesian/Rodrigues reference, not the production alt/az rotation."""
    altitude, heading = numpy.radians([altitude, heading])
    axis = numpy.array([numpy.cos(altitude)*numpy.sin(heading),
                        numpy.cos(altitude)*numpy.cos(heading), numpy.sin(altitude)])
    up = numpy.array([0., 0., 1.])
    v = numpy.cross(axis, up)
    skew = numpy.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    rotation = numpy.eye(3) + skew + skew @ skew / (1+numpy.dot(axis, up))
    rays = numpy.column_stack([numpy.cos(alt)*numpy.sin(az),
                               numpy.cos(alt)*numpy.cos(az), numpy.sin(alt)]) @ rotation.T
    east, north, z = rays.T
    radius = params[3]/2 * numpy.sqrt(numpy.maximum(0, (1-z)/2)) / SIN45
    horizontal = numpy.maximum(numpy.hypot(east, north), 1e-15)
    roll = numpy.radians(params[0])
    x = 2028/2 + params[4] - radius*(east*numpy.cos(roll)-north*numpy.sin(roll))/horizontal
    y = 1520/2 - params[5] - radius*(north*numpy.cos(roll)+east*numpy.sin(roll))/horizontal
    return x, y, z


@pytest.mark.parametrize('altitude', [None, 90.0])
@pytest.mark.parametrize('mirror', [False, True])
def test_zenith_projection_is_unchanged(altitude, mirror):
    alt = numpy.radians([-20, 0, 10, 45, 89, 90])
    az = numpy.radians([0, 40, 90, 180, 270, 359])
    camera_alt, camera_az = cameraAltAz(alt, az, altitude, 213)
    assert camera_alt is alt and camera_az is az
    actual = projectToPixels(alt, az, PARAMS, 2028, 1520, mirror=mirror,
                             lens_altitude=altitude, pointing_azimuth=213)
    r = PARAMS[3]/2 * numpy.sin((numpy.pi/2-alt)/2) / SIN45
    psi = az-numpy.radians(PARAMS[0])
    numpy.testing.assert_array_equal(actual[0], 1021 + (1 if mirror else -1)*r*numpy.sin(psi))
    numpy.testing.assert_array_equal(actual[1], 895-r*numpy.cos(psi))


@pytest.mark.parametrize('altitude,heading', [(54, 0), (20, 123), (0, 350)])
def test_tilt_matches_independent_rotation(altitude, heading):
    alt = numpy.radians([altitude, 10, 45, 75, 90])
    az = numpy.radians([heading, 20, 170, 270, 0])
    actual = projectToPixels(alt, az, PARAMS, 2028, 1520,
                             lens_altitude=altitude, pointing_azimuth=heading)
    expected = reference_pixels(alt, az, altitude, heading)
    numpy.testing.assert_allclose(actual, expected[:2], atol=2e-5, rtol=0)
    numpy.testing.assert_allclose([actual[0][0], actual[1][0]], [1021, 895], atol=1e-8)


@pytest.mark.parametrize('altitude,heading,timestamp', [(54, 0, 1770000000), (20, 120, 1770014400)])
def test_solve_tilted_image_end_to_end(tmp_path, altitude, heading, timestamp):
    solver = IndiAllSkyLensSolver({})
    catalog = solver.loadCatalog()
    alt, az = predictAltAz(catalog, 46.51, 8, timestamp)
    x, y, z = reference_pixels(alt, az, altitude, heading)
    visible = (alt > numpy.radians(10)) & (z > 0)
    img = numpy.full((1520, 2028), 10, dtype=numpy.uint8)
    for xi, yi in zip(x[visible], y[visible]):
        if 5 < xi < 2023 and 5 < yi < 1515:
            cv2.circle(img, (int(round(xi)), int(round(yi))), 2, 220, -1)
    image_file = tmp_path / 'tilted.png'
    assert cv2.imwrite(str(image_file), cv2.GaussianBlur(img, (5, 5), 1.1))
    initial = dict(zip(KEYS, PARAMS))
    initial['AZIMUTH_ANGLE'] = 190
    result = solver.solve(image_file, 46.51, 8, timestamp, initial,
                          lens_altitude=altitude, pointing_azimuth=heading)
    assert result['success'], result
    assert result['quality']['stars_matched'] >= 40
    assert result['quality']['rms_px'] < 2
    assert abs(result['values']['AZIMUTH_ANGLE']-PARAMS[0]) < 0.5
    assert abs(result['values']['IMAGE_CIRCLE_DIAMETER']-PARAMS[3]) < 30
    geometry = result['geometry']
    assert geometry['lens_altitude_deg'] == altitude
    assert geometry['pointing_azimuth_deg'] == heading
    assert abs(geometry['axis_x']-(1014+result['values']['OFFSET_X'])) < 1
    assert numpy.hypot(geometry['zenith_x']-geometry['axis_x'],
                       geometry['zenith_y']-geometry['axis_y']) > 100


@pytest.mark.parametrize('mirror', [False, True])
def test_tilted_coarse_search_and_chirality(mirror):
    solver = IndiAllSkyLensSolver({})
    catalog = solver.loadCatalog()
    alt, az = predictAltAz(catalog, 46.51, 8, 1770000000)
    x, y, z = reference_pixels(alt, az, 54, 0)
    if mirror:
        x = 2*(1014+PARAMS[4])-x
    keep = (alt > numpy.radians(10)) & (z > 0) & (x > 5) & (x < 2023) & (y > 5) & (y < 1515)
    detections = numpy.column_stack([x[keep], y[keep], numpy.full(keep.sum(), 500)])
    initial = PARAMS.copy()
    initial[0] = 20  # opposite roll: the coarse search must keep pointing fixed
    result = solver.fitParameters(detections, catalog, 46.51, 8, 1770000000,
                                  initial, 2028, 1520, lens_altitude=54, pointing_azimuth=0)
    if mirror:
        assert not result['success']
        assert result['reason'] == 'chirality_mismatch'
    else:
        assert result['success'], result
        assert result['rms_px'] < 0.1


@pytest.mark.parametrize('key', ['LATITUDE_OFFSET', 'LONGITUDE_OFFSET'])
def test_manual_offsets_save_without_expanding_solver_limits(key):
    payload = dict(zip(KEYS, PARAMS), **{key: 43.49}, POINTING_AZIMUTH=123)
    assert parseSolverRequestValues(payload)[1] == f'{key} out of range'
    values, error = parseSolverRequestValues(payload, for_save=True)
    assert error is None
    config = {'LENS_ALTITUDE': 54, 'VIRTUALSKY': {'MAGNITUDE': 6}}
    applySolvedValuesToConfig(config, values)
    assert config['VIRTUALSKY'][key] == 43.49
    assert config['VIRTUALSKY']['POINTING_AZIMUTH'] == 123
    assert config['VIRTUALSKY']['MAGNITUDE'] == 6
    assert config['LENS_ALTITUDE'] == 54


@pytest.mark.parametrize('key', ['LATITUDE_OFFSET', 'LONGITUDE_OFFSET', 'POINTING_AZIMUTH'])
@pytest.mark.parametrize('value', [float('nan'), float('inf'), float('-inf'), 'invalid', None])
def test_manual_save_rejects_invalid_angles(key, value):
    payload = dict(zip(KEYS, PARAMS), **{key: value})
    assert parseSolverRequestValues(payload, for_save=True)[0] is None
