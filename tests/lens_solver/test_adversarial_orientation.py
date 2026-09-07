import numpy
import pytest

from indi_allsky.lens_solver import IndiAllSkyLensSolver, predictAltAz, projectToPixels
from indi_allsky.lens_solver.orientation import recoverOrientation
from tests.lens_solver.test_orientation import star_field, render_stars, KEYS


@pytest.mark.parametrize('altitude', [90, 89.9999])
@pytest.mark.parametrize('supplied_altitude,heading', [(90, 0), (90, 123), (90, 360), (0, 270)])
def test_zenith_with_uninformative_or_wrong_pointing(tmp_path, altitude, supplied_altitude, heading):
    _, detections, _, _ = star_field(altitude, 123)
    path = tmp_path / 'zenith.png'
    render_stars(path, detections)
    initial = dict(zip(KEYS, [360, 0, 0, 2900, 20, -100]))
    result = IndiAllSkyLensSolver({}).solve(path, 46.51, 8, 1770000000, initial,
        lens_altitude=supplied_altitude, pointing_azimuth=heading)
    assert result['success'] and not result['partial'], result
    values = result['values']
    assert abs(values.get('LENS_ALTITUDE', supplied_altitude)-90) < 0.1
    assert abs(values['AZIMUTH_ANGLE']-200) < 0.1
    assert abs(values['IMAGE_CIRCLE_DIAMETER']-2951) < 3
    assert result['quality']['rms_px'] < 1
    # Heading has no physical meaning at zenith; never require it to equal 123.


@pytest.mark.parametrize('initial,expected_success', [
    ([360, 30, -30, 4100, 100, -200], True),
    ([0, 0, 0, 1771, 7, -135], True),
    ([0, 0, 0, 4131, 7, -135], True),
    ([0, 0, 0, 700, 7, -135], False),
    ([0, 0, 0, 20000, 7, -135], False),
    ([0, 0, 0, 2951, 10000, -10000], False),
])
def test_misleading_user_entries(tmp_path, monkeypatch, initial, expected_success):
    _, detections, alt, az = star_field(54, 123)
    path = tmp_path / 'sky.png'
    render_stars(path, detections)
    solver = IndiAllSkyLensSolver({})
    monkeypatch.setattr(solver, 'detectStars', lambda image: detections)
    result = solver.solve(path, 46.51, 8, 1770000000, dict(zip(KEYS, initial)))
    assert result['success'] == expected_success, result
    if expected_success:
        values = result['values']
        assert not result['partial']
        x, y = projectToPixels(alt, az, [values[k] for k in KEYS], 2028, 1520,
            lens_altitude=values['LENS_ALTITUDE'], pointing_azimuth=values['POINTING_AZIMUTH'])
        assert numpy.max(numpy.hypot(x-detections[:, 0], y-detections[:, 1])) < 2
    else:
        assert 'values' not in result


@pytest.mark.parametrize('altitude', [90, 54])
def test_noisy_incomplete_sky_with_outliers_still_has_correct_geometry(altitude):
    catalog, detections, alt, az = star_field(altitude, 123)
    truth = detections[:, :2].copy()
    rng = numpy.random.default_rng(42)
    detections = detections[::2].copy()  # half the stars lost to cloud
    detections[:, :2] += rng.normal(0, 2, detections[:, :2].shape)
    outliers = numpy.column_stack([rng.uniform(0, 2028, 60), rng.uniform(0, 1520, 60),
                                  numpy.full(60, 100)])
    result = recoverOrientation(numpy.vstack([detections, outliers]), catalog,
        46.51, 8, 1770000000, numpy.array([0, 0, 0, 2900, 20, -100]), 2028, 1520)
    assert result is not None
    x, y = projectToPixels(alt, az, result['params'], 2028, 1520,
        lens_altitude=result['lens_altitude'], pointing_azimuth=result['pointing_azimuth'])
    # Check held-out stars too. Allow individual edge errors up to 5 px, but
    # require the whole-map RMS to improve on the injected 2 px centroid noise.
    error = numpy.hypot(x-truth[:, 0], y-truth[:, 1])
    assert numpy.sqrt(numpy.mean(error**2)) < 2
    assert numpy.max(error) < 5


@pytest.mark.parametrize('seed', [0, 1, 2])
def test_two_equally_valid_star_maps_are_ambiguous(seed):
    solver = IndiAllSkyLensSolver({})
    catalog = solver.loadCatalog()
    alt, az = predictAltAz(catalog, 46.51, 8, 1770000000)
    keep = alt > numpy.radians(10)
    # Two complete skies with different rolls, interleaved at equal brightness.
    maps = [numpy.column_stack(projectToPixels(alt[keep], az[keep],
                [roll, 0, 0, 1700, 0, 0], 1920, 1920)) for roll in (20, 150)]
    detections = numpy.vstack(maps)
    numpy.random.default_rng(seed).shuffle(detections)
    detections = numpy.column_stack([detections, numpy.full(len(detections), 500)])
    result = recoverOrientation(detections, catalog, 46.51, 8, 1770000000,
                                numpy.array([300, 0, 0, 1700, 0, 0]), 1920, 1920)
    assert result is None


@pytest.mark.parametrize('kind', ['grid', 'ring', 'duplicates', 'cluster', 'few_stars_in_noise'])
def test_structured_false_stars_are_rejected(kind):
    catalog, stars, _, _ = star_field(54, 123)
    rng = numpy.random.default_rng(7)
    if kind == 'grid':
        x, y = numpy.meshgrid(numpy.linspace(300, 1600, 20), numpy.linspace(300, 1600, 20))
        xy = numpy.column_stack([x.ravel(), y.ravel()])
    elif kind == 'ring':
        angle = numpy.linspace(0, 2*numpy.pi, 500)
        xy = numpy.column_stack([960+750*numpy.sin(angle), 960+750*numpy.cos(angle)])
    elif kind == 'duplicates':
        xy = numpy.repeat(stars[:1, :2], 100, axis=0)
    elif kind == 'cluster':
        xy = rng.uniform(930, 990, (300, 2))
    else:
        xy = numpy.vstack([stars[:15, :2], rng.uniform(300, 1600, (400, 2))])
    detections = numpy.column_stack([xy, numpy.full(len(xy), 500)])
    assert recoverOrientation(detections, catalog, 46.51, 8, 1770000000,
        numpy.array([0, 0, 0, 1700, 0, 0]), 1920, 1920) is None
