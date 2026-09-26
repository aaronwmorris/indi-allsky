import numpy as np
import pytest
import erfa
from astropy.coordinates import AltAz, EarthLocation, SkyCoord
from astropy.time import Time
import astropy.units as u

from indi_allsky.lens_solver import IndiAllSkyLensSolver
from indi_allsky.lens_solver.projection import precessCatalog
from tests.lens_solver.test_camera_tilt import PARAMS, KEYS, reference_pixels
from tests.lens_solver.test_orientation import render_stars


@pytest.mark.parametrize('timestamp', [0, 946728000, 1788731972, 4102444800])
def test_precession_matches_independent_erfa_rotation(timestamp):
    catalog = np.array([[0, 90, 1], [359.99, -90, 2], [0, 0, 3], [180, 45, 4.]])
    original = catalog.copy()
    actual = precessCatalog(catalog, timestamp)
    ra, dec = np.radians(catalog[:, :2].T)
    xyz = np.column_stack([np.cos(dec)*np.cos(ra), np.cos(dec)*np.sin(ra), np.sin(dec)])
    time = Time(timestamp, format='unix')
    expected = xyz @ erfa.pmat76(time.jd1, time.jd2).T
    ra, dec = np.radians(actual[:, :2].T)
    observed = np.column_stack([np.cos(dec)*np.cos(ra), np.cos(dec)*np.sin(ra), np.sin(dec)])
    np.testing.assert_allclose(observed, expected, atol=1e-14, rtol=0)
    np.testing.assert_array_equal(actual[:, 2], catalog[:, 2])
    np.testing.assert_array_equal(catalog, original)


@pytest.mark.parametrize('hour', [0, 2, 4, 8, 12, 18])
@pytest.mark.parametrize('radial', [0, 0.06, -0.12])
@pytest.mark.parametrize('latitude,altitude,heading', [
    (53, 87.4, 176), (-33.9, 54, 270), (53, 90, 0), (53, 89.9, 359)])
def test_pointing_from_independent_observed_sky(tmp_path, hour, radial, latitude, altitude, heading):
    # Do not synthesize stars through the solver's own astronomical calculation.
    # Astropy includes precession, nutation and aberration independently.
    timestamp = 1788731972 + hour*3600
    solver = IndiAllSkyLensSolver({})
    catalog = solver.loadCatalog()
    stars = SkyCoord(ra=catalog[:, 0]*u.deg, dec=catalog[:, 1]*u.deg, frame='icrs')
    place = EarthLocation.from_geodetic(11*u.deg, latitude*u.deg, 0*u.m)
    observed = stars.transform_to(AltAz(obstime=Time(timestamp, format='unix'), location=place))
    x, y, z = reference_pixels(observed.alt.rad, observed.az.rad, altitude, heading)
    cx, cy = 2028/2+PARAMS[4], 1520/2-PARAMS[5]
    factor = np.maximum(1+z, 1e-12)**(-radial)
    x, y = cx+(x-cx)*factor, cy+(y-cy)*factor
    keep = ((observed.alt.deg > 10) & (z > 0) & (x > 5) & (x < 2023) & (y > 5) & (y < 1515))
    detections = np.column_stack([x[keep], y[keep], np.full(keep.sum(), 500)])
    image_file = tmp_path / 'independent-sky.png'
    render_stars(image_file, detections)
    seed_altitude = 90 if altitude >= 87 else altitude
    initial = dict(zip(KEYS, PARAMS), LENS_ALTITUDE=seed_altitude, PRECESSION=True, RADIAL_DISTORTION=0)
    result = solver.solve(image_file, latitude, 11, timestamp, initial,
                          lens_altitude=seed_altitude, pointing_azimuth=0 if seed_altitude == 90 else heading)
    assert result['success'] and not result['partial'], result
    values = result['values']
    assert values['PRECESSION'] is True
    assert abs(values['RADIAL_DISTORTION']-radial) < 0.005
    assert abs(values['LENS_ALTITUDE']-altitude) < 0.1
    # At zenith heading is undefined; tiny real nutation/aberration can rotate
    # its reported direction substantially while the camera axis stays put.
    if altitude < 89:
        assert abs((values['POINTING_AZIMUTH']-heading+180) % 360-180) < 1
    assert np.isfinite(values['POINTING_AZIMUTH'])
    assert result['quality']['rms_px'] < 1
