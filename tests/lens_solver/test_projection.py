import numpy
from astropy.coordinates import AltAz, EarthLocation, ICRS
from astropy.time import Time
import astropy.units as u

from indi_allsky.lens_solver import predictAltAz, projectToPixels, SIN45


W, H = 1920, 1080
# params: [azimuth, lat_off, long_off, diameter, off_x, off_y]
P = numpy.array([30.0, 0.0, 0.0, 1000.0, 40.0, -20.0])
CX = W / 2.0 + 40.0    # 1000.0
CY = H / 2.0 + 20.0    # 560.0  (cy = H/2 - off_y, off_y = -20)

# 1e-5, not 1e-6: SIN45 is virtualsky.js's truncated literal, ~8.4e-7 error at r=500
RADIAL_TOLERANCE = 1e-5


def project_one(alt_deg, az_deg, mirror=False):
    x, y = projectToPixels(
        numpy.radians([alt_deg]), numpy.radians([az_deg]), P, W, H, mirror=mirror)
    return x[0], y[0]


def test_zenith_maps_to_projection_center():
    x, y = project_one(90.0, 123.0)   # az irrelevant at zenith
    assert abs(x - CX) < 1e-6
    assert abs(y - CY) < 1e-6


def test_horizon_at_camera_azimuth_maps_straight_up():
    # star at alt=0, az == AZIMUTH_ANGLE -> psi=0 -> r=D/2 straight up on canvas
    x, y = project_one(0.0, 30.0)
    assert abs(x - CX) < RADIAL_TOLERANCE
    assert abs(y - (CY - 500.0)) < RADIAL_TOLERANCE


def test_east_of_camera_azimuth_maps_left_default_chirality():
    # psi=+90deg: x = cx - r*sin(psi) = cx - 500
    x, y = project_one(0.0, 120.0)
    assert abs(x - (CX - 500.0)) < RADIAL_TOLERANCE
    assert abs(y - CY) < RADIAL_TOLERANCE


def test_mirror_flips_x_only():
    x, y = project_one(0.0, 120.0, mirror=True)
    assert abs(x - (CX + 500.0)) < RADIAL_TOLERANCE
    assert abs(y - CY) < RADIAL_TOLERANCE


def test_equisolid_radial_function():
    # alt=45 -> theta=45 -> r = 500*sin(22.5deg)/sin(45deg) = 270.598...
    x, y = project_one(45.0, 30.0)
    r = numpy.hypot(x - CX, y - CY)
    expected = 500.0 * numpy.sin(numpy.radians(22.5)) / SIN45
    assert abs(r - expected) < RADIAL_TOLERANCE


def test_polaris_altitude_tracks_latitude():
    # Polaris (RA 37.95, Dec 89.26, J2000): altitude ~ latitude +/- 0.74deg
    cat = numpy.array([[37.95, 89.26, 2.0]])
    alt, az = predictAltAz(cat, 45.0, -73.0, 1770000000)
    assert abs(numpy.degrees(alt[0]) - 45.0) < 1.0
    assert (numpy.degrees(az[0]) < 2.0) or (numpy.degrees(az[0]) > 358.0)


# the only anchors to reality in the suite -- independent of predictAltAz's own machinery
# well-known J2000 catalog positions, independent of lens_solver_stars.json on purpose
SIRIUS = (101.287, -16.716)
ARCTURUS = (213.915, 19.182)
CAPELLA = (79.172, 45.998)

SITE_NORTH = (40.1, -75.4)
SITE_SOUTH = (-33.0, 151.0)     # Sydney -- required southern-hemisphere site

T1_UNIX = 1770000000
T2_UNIX = T1_UNIX + 200 * 86400   # ~200 days later -- a distinct epoch/season

# max separation vs. an independently-coded hour-angle computation (part 1 below)
INDEPENDENT_REFERENCE_TOLERANCE_ARCSEC = 5.0

# min separation from astropy's fully precessed AltAz (part 2); catches an added-precession regression
PRECESSION_DIVERGENCE_FLOOR_DEG = 0.2

# (name, ra_deg, dec_deg, lat_deg, lon_deg, obstime_unix)
R5_CASES = [
    ('Sirius, north, T1', SIRIUS[0], SIRIUS[1], SITE_NORTH[0], SITE_NORTH[1], T1_UNIX),
    ('Sirius, south, T2', SIRIUS[0], SIRIUS[1], SITE_SOUTH[0], SITE_SOUTH[1], T2_UNIX),
    ('Arcturus, north, T2', ARCTURUS[0], ARCTURUS[1], SITE_NORTH[0], SITE_NORTH[1], T2_UNIX),
    ('Arcturus, south, T2', ARCTURUS[0], ARCTURUS[1], SITE_SOUTH[0], SITE_SOUTH[1], T2_UNIX),
    ('Capella, north, T1', CAPELLA[0], CAPELLA[1], SITE_NORTH[0], SITE_NORTH[1], T1_UNIX),
]


def _independent_hour_angle_alt_az(ra_deg, dec_deg, lat_deg, lon_deg, obstime_unix):
    """Low-precision GMST + spherical-trig alt/az, deliberately not sharing any code
    with indi_allsky.lens_solver. GMST: Meeus, "Astronomical Algorithms" eq. 12.4."""
    jd = obstime_unix / 86400.0 + 2440587.5     # unix epoch -> Julian Date
    days_since_j2000 = jd - 2451545.0
    centuries_since_j2000 = days_since_j2000 / 36525.0

    gmst_deg = (
        280.46061837
        + 360.98564736629 * days_since_j2000
        + 0.000387933 * centuries_since_j2000 ** 2
        - (centuries_since_j2000 ** 3) / 38710000.0
    ) % 360.0

    # LST = GMST + east longitude (east-positive convention)
    lst_deg = (gmst_deg + lon_deg) % 360.0
    ha = numpy.radians((lst_deg - ra_deg) % 360.0)

    dec = numpy.radians(dec_deg)
    lat = numpy.radians(lat_deg)

    sin_alt = numpy.sin(dec) * numpy.sin(lat) + numpy.cos(dec) * numpy.cos(lat) * numpy.cos(ha)
    alt_deg = numpy.degrees(numpy.arcsin(numpy.clip(sin_alt, -1.0, 1.0)))

    az_deg = numpy.degrees(numpy.arctan2(
        -numpy.cos(dec) * numpy.sin(ha),
        numpy.sin(dec) * numpy.cos(lat) - numpy.cos(dec) * numpy.sin(lat) * numpy.cos(ha),
    )) % 360.0

    return alt_deg, az_deg


def _circular_diff_deg(a_deg, b_deg):
    return abs(((a_deg - b_deg + 180.0) % 360.0) - 180.0)


def test_altaz_matches_independent_reference_no_precession():
    for name, ra, dec, lat, lon, t in R5_CASES:
        cat = numpy.array([[ra, dec, 0.0]])
        alt_rad, az_rad = predictAltAz(cat, lat, lon, t)
        model_alt = numpy.degrees(alt_rad[0])
        model_az = numpy.degrees(az_rad[0])

        ref_alt, ref_az = _independent_hour_angle_alt_az(ra, dec, lat, lon, t)
        alt_diff_arcsec = abs(model_alt - ref_alt) * 3600.0
        az_diff_arcsec = _circular_diff_deg(model_az, ref_az) * 3600.0
        assert alt_diff_arcsec < INDEPENDENT_REFERENCE_TOLERANCE_ARCSEC, name
        assert az_diff_arcsec < INDEPENDENT_REFERENCE_TOLERANCE_ARCSEC, name

        # Part 2: must differ by > 0.2deg from astropy's fully precessed/nutated AltAz
        location = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=0 * u.m)
        obstime = Time(float(t), format='unix', scale='utc')
        precessed = ICRS(ra=ra * u.deg, dec=dec * u.deg).transform_to(
            AltAz(obstime=obstime, location=location, pressure=0 * u.hPa))

        model_alt_rad = numpy.radians(model_alt)
        model_az_rad = numpy.radians(model_az)
        precessed_sep_rad = numpy.arccos(numpy.clip(
            numpy.sin(model_alt_rad) * numpy.sin(precessed.alt.radian)
            + numpy.cos(model_alt_rad) * numpy.cos(precessed.alt.radian)
            * numpy.cos(model_az_rad - precessed.az.radian),
            -1.0, 1.0))
        precessed_sep_deg = numpy.degrees(precessed_sep_rad)
        assert precessed_sep_deg > PRECESSION_DIVERGENCE_FLOOR_DEG, name


def _inverse_hour_angle_deg(alt_deg, az_deg, lat_deg, dec_deg):
    # recovers a signed HA from predictAltAz's (alt, az) for the sign-convention check below
    alt = numpy.radians(alt_deg)
    az = numpy.radians(az_deg)
    lat = numpy.radians(lat_deg)
    dec = numpy.radians(dec_deg)

    sin_ha = -numpy.sin(az) * numpy.cos(alt) / numpy.cos(dec)
    cos_ha = (numpy.sin(alt) - numpy.sin(lat) * numpy.sin(dec)) / (numpy.cos(lat) * numpy.cos(dec))
    return numpy.degrees(numpy.arctan2(sin_ha, cos_ha)) % 360.0


def test_longitude_sign_convention():
    # lon +75 vs -75 must give hour angles differing by exactly +150deg (east-positive), not -150
    ra, dec = SIRIUS
    lat = SITE_NORTH[0]
    cat = numpy.array([[ra, dec, 0.0]])

    alt_pos, az_pos = predictAltAz(cat, lat, 75.0, T1_UNIX)
    alt_neg, az_neg = predictAltAz(cat, lat, -75.0, T1_UNIX)

    ha_pos = _inverse_hour_angle_deg(
        numpy.degrees(alt_pos[0]), numpy.degrees(az_pos[0]), lat, dec)
    ha_neg = _inverse_hour_angle_deg(
        numpy.degrees(alt_neg[0]), numpy.degrees(az_neg[0]), lat, dec)

    signed_diff = ((ha_pos - ha_neg + 180.0) % 360.0) - 180.0
    assert abs(signed_diff - 150.0) < 1e-3


def test_projection_ignores_tilt_params():
    # params[1]/[2] (lat/long offset) are consumed by the caller; projectToPixels uses only 0, 3, 4, 5
    alt = numpy.radians([10.0, 45.0, 80.0])
    az = numpy.radians([30.0, 200.0, 350.0])
    baseline_x, baseline_y = projectToPixels(alt, az, P, W, H)

    for lat_off, long_off in [(15.0, 0.0), (-15.0, 0.0), (0.0, 15.0),
                              (0.0, -15.0), (15.0, -15.0), (-15.0, 15.0)]:
        trial = P.copy()
        trial[1] = lat_off
        trial[2] = long_off
        x, y = projectToPixels(alt, az, trial, W, H)
        assert numpy.array_equal(x, baseline_x)
        assert numpy.array_equal(y, baseline_y)


def test_below_horizon_finite_and_monotonic():
    # r must be finite, strictly increasing in theta, and r(alt=0) exactly D/2
    alts_deg = numpy.array([0.0, -5.0, -30.0, -89.0])
    az = numpy.radians(numpy.full_like(alts_deg, 30.0))
    x, y = projectToPixels(numpy.radians(alts_deg), az, P, W, H)
    r = numpy.hypot(x - CX, y - CY)

    assert numpy.all(numpy.isfinite(r))
    assert numpy.all(numpy.diff(r) > 0.0)
    assert abs(r[0] - 500.0) < RADIAL_TOLERANCE
