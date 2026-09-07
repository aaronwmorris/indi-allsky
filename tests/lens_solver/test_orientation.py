import json

import cv2
import numpy
import pytest

from indi_allsky.lens_solver import IndiAllSkyLensSolver, predictAltAz, projectToPixels
from indi_allsky.lens_solver.orientation import recoverOrientation, pointingFromFit
from indi_allsky.lens_solver import solver as solver_mod
from tests.lens_solver.test_camera_tilt import reference_pixels, PARAMS, KEYS


def star_field(altitude, heading, latitude=46.51, timestamp=1770000000):
    catalog = IndiAllSkyLensSolver({}).loadCatalog()
    alt, az = predictAltAz(catalog, latitude, 8, timestamp)
    x, y, z = reference_pixels(alt, az, altitude, heading)
    keep = ((alt > numpy.radians(10)) & (z > 0)
            & (x > 5) & (x < 2023) & (y > 5) & (y < 1515))
    detections = numpy.column_stack([x[keep], y[keep], numpy.full(keep.sum(), 500)])
    return catalog, detections, alt[keep], az[keep]


def render_stars(image_file, detections):
    image = numpy.full((1520, 2028), 10, dtype=numpy.uint8)
    for x, y, _ in detections:
        cv2.circle(image, (int(round(x)), int(round(y))), 2, 220, -1)
    assert cv2.imwrite(str(image_file), cv2.GaussianBlur(image, (5, 5), 1.1))


@pytest.mark.parametrize('altitude,heading,scale,latitude,timestamp', [
    (54, 0, 1.2, 46.51, 1770000000),
    (20, 120, 0.8, 46.51, 1770000000),
    (0, 0, 1.0, 46.51, 1770000000),
    (88, 220, 1.0, 46.51, 1770000000),
    (54, 270, 1.4, -33.9, 1770014400),
])
def test_recovers_pointing_without_angle_hints(altitude, heading, scale, latitude, timestamp):
    catalog, detections, alt, az = star_field(altitude, heading, latitude, timestamp)
    # Neither pointing nor roll is supplied, and the lens guesses are imperfect.
    initial = numpy.array([0, 0, 0, PARAMS[3]*scale, 20, -100])
    result = recoverOrientation(detections, catalog, latitude, 8, timestamp, initial, 2028, 1520)
    assert result is not None
    assert result['success'] and not result['partial']
    assert result['params'][1:3].tolist() == [0, 0]
    # Check the whole mapping, including decomposition into the renderer's angles.
    x, y = projectToPixels(alt, az, result['params'], 2028, 1520,
        lens_altitude=result['lens_altitude'], pointing_azimuth=result['pointing_azimuth'])
    numpy.testing.assert_allclose(numpy.column_stack([x, y]), detections[:, :2], atol=0.1)


@pytest.mark.parametrize('altitude,heading', [(54, 0), (20, 120), (0, 0)])
def test_solve_recovers_pointing_from_image(tmp_path, altitude, heading):
    _, detections, alt, az = star_field(altitude, heading)
    image_file = tmp_path / 'unknown-pointing.png'
    render_stars(image_file, detections)
    initial = dict(zip(KEYS, [0, 0, 0, 2900, 20, -100]))
    result = IndiAllSkyLensSolver({}).solve(image_file, 46.51, 8, 1770000000, initial)
    assert result['success'], result
    assert not result['partial']
    assert result['quality']['stars_matched'] >= 40
    assert result['quality']['rms_px'] < 2
    values = result['values']
    assert abs(values['LENS_ALTITUDE']-altitude) < 0.5
    assert abs((values['POINTING_AZIMUTH']-heading+180) % 360-180) < 0.5
    assert values['LATITUDE_OFFSET'] == values['LONGITUDE_OFFSET'] == 0
    params = numpy.array([values[key] for key in KEYS])
    x, y = projectToPixels(alt, az, params, 2028, 1520,
        lens_altitude=values['LENS_ALTITUDE'], pointing_azimuth=values['POINTING_AZIMUTH'])
    assert numpy.max(numpy.hypot(x-detections[:, 0], y-detections[:, 1])) < 3
    json.dumps(result)


@pytest.mark.parametrize('kind', ['mirror', 'noise', 'dense_noise', 'too_few', 'below_horizon'])
def test_recovery_refuses_unreliable_matches(kind):
    catalog, detections, _, _ = star_field(54, 0)
    initial = PARAMS.copy()
    if kind == 'mirror':
        detections[:, 0] = 2*(1014+PARAMS[4])-detections[:, 0]
    elif kind == 'too_few':
        detections = detections[:39]
    elif kind == 'below_horizon':
        _, detections, _, _ = star_field(-15, 90)
    else:
        initial[3:] = [700, 0, 0]  # binding minimum scale, most vulnerable to chance matches
        rng = numpy.random.default_rng(3127)
        count = 500 if kind == 'dense_noise' else 120
        detections = numpy.column_stack([rng.uniform(700, 1328, count),
                                         rng.uniform(410, 1110, count), numpy.full(count, 500)])
    assert recoverOrientation(detections, catalog, 46.51, 8, 1770000000,
                              initial, 2028, 1520) is None


@pytest.mark.parametrize('altitude', [90, 88])
def test_successful_zenith_fit_keeps_existing_fast_path(tmp_path, monkeypatch, altitude):
    def unexpected_recovery(*args):
        pytest.fail('A full zenith fit must not invoke pointing recovery')

    monkeypatch.setattr(solver_mod, 'recoverOrientation', unexpected_recovery)
    image_file = tmp_path / 'zenith.png'
    _, detections, _, _ = star_field(altitude, 220)
    render_stars(image_file, detections)
    initial = dict(zip(KEYS, [0, 0, 0, 2900, 20, -100]), LENS_ALTITUDE=90)
    result = IndiAllSkyLensSolver({}).solve(image_file, 46.51, 8, 1770000000, initial)
    assert result['success'] and not result['partial']
    assert abs(result['values']['LENS_ALTITUDE']-altitude) < 0.1
    assert result['values']['LATITUDE_OFFSET'] == result['values']['LONGITUDE_OFFSET'] == 0


@pytest.mark.parametrize('latitude,offsets', [(53, (-2.61, 0.01)), (-33.9, (7, -15)),
                                            (90, (0, 20)), (-90, (0, -20))])
@pytest.mark.parametrize('altitude,heading', [(None, 213), (90, 0), (87.4, 177), (54, 123), (0, 350)])
def test_pointing_from_offsets_preserves_mapping(latitude, offsets, altitude, heading):
    catalog = IndiAllSkyLensSolver({}).loadCatalog()
    params = PARAMS.copy()
    params[1:3] = offsets
    alt, az = predictAltAz(catalog, latitude+offsets[0], 11+offsets[1], 1788731972)
    expected = projectToPixels(alt, az, params, 2028, 1520,
                               lens_altitude=altitude, pointing_azimuth=heading)
    elevation, pointing, roll = pointingFromFit(params, latitude, 11, 1788731972, altitude, heading)
    params[:3] = [roll, 0, 0]
    alt, az = predictAltAz(catalog, latitude, 11, 1788731972)
    actual = projectToPixels(alt, az, params, 2028, 1520,
                             lens_altitude=elevation, pointing_azimuth=pointing)
    numpy.testing.assert_allclose(actual, expected, atol=1e-7, rtol=0)


def test_unsuccessful_recovery_preserves_partial_fit(tmp_path, monkeypatch):
    image_file = tmp_path / 'partial.png'
    assert cv2.imwrite(str(image_file), numpy.zeros((1520, 2028), dtype=numpy.uint8))
    solver = IndiAllSkyLensSolver({})
    _, detections, _, _ = star_field(54, 0)
    monkeypatch.setattr(solver, 'detectStars', lambda image: detections)
    monkeypatch.setattr(solver, 'fitParameters', lambda *args: dict(
        success=True, partial=True, params=PARAMS.copy(), stars_matched=45, rms_px=2,
        final_match_radius=6))
    monkeypatch.setattr(solver_mod, 'recoverOrientation', lambda *args: None)
    result = solver.solve(image_file, 46.51, 8, 1770000000, dict(zip(KEYS, PARAMS)))
    assert result['success'] and result['partial']
    assert set(result['values']) == set(KEYS)
