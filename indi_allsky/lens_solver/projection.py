import functools

import numpy
from astropy.time import Time
import astropy.units as u
from astropy.utils import iers


# never attempt IERS downloads on an offline allsky host, and accept an
# aged table rather than raise once "now" walks off its end -- the
# extrapolated UT1 error is milliseconds, far below arcminute-level fitting
iers.conf.auto_download = False
iers.conf.auto_max_age = None


SIN45 = 0.70710678            # constant from virtualsky.js fisheye projection


@functools.lru_cache(maxsize=8)
def _gmstRad(obstime_unix):
    # memoized: astropy must stay out of the fit hot loop; lst(t, lon)
    # == gmst(t) + radians(lon) to < 1e-7 arcsec
    return Time(float(obstime_unix), format='unix', scale='utc').sidereal_time(
        'mean', longitude=0.0 * u.deg).radian


def predictAltAz(catalog, latitude, longitude, obstime_unix):
    """Predict alt/az for J2000 catalog stars ([ra_deg, dec_deg, ...]),
    replicating virtualsky.js's rendering: deliberately NO precession,
    refraction, or aberration -- the goal is matching what VirtualSky
    draws, not textbook astronomy. Returns (alt_rad, az_rad), az from
    north increasing east.
    """
    lst_rad = _gmstRad(obstime_unix) + numpy.radians(longitude)

    ra = numpy.radians(catalog[:, 0])
    dec = numpy.radians(catalog[:, 1])
    lat = numpy.radians(latitude)

    ha = lst_rad - ra

    sin_alt = (numpy.sin(dec) * numpy.sin(lat)
               + numpy.cos(dec) * numpy.cos(lat) * numpy.cos(ha))
    alt = numpy.arcsin(numpy.clip(sin_alt, -1.0, 1.0))

    az = numpy.arctan2(
        -numpy.cos(dec) * numpy.sin(ha),
        numpy.sin(dec) * numpy.cos(lat)
        - numpy.cos(dec) * numpy.sin(lat) * numpy.cos(ha))

    return alt, numpy.mod(az, 2.0 * numpy.pi)


def cameraAltAz(alt_rad, az_rad, lens_altitude=90.0, pointing_azimuth=0.0):
    """Rotate geographic alt/az (radians) into lens coordinates (radians).

    Lens altitude is degrees above the horizon; pointing azimuth is degrees
    east of north. Image roll is applied separately by projectToPixels.
    Keep this rotation in sync with VirtualSky.fisheyeAltAz in virtualsky.js.
    """
    # Preserve the exact legacy projection, including cameras without metadata.
    if lens_altitude is None or lens_altitude == 90.0:
        return alt_rad, az_rad
    tilt = numpy.radians(90.0 - lens_altitude)
    heading = numpy.radians(pointing_azimuth)
    across = numpy.cos(alt_rad) * numpy.sin(az_rad - heading)
    along = numpy.cos(alt_rad) * numpy.cos(az_rad - heading)
    up = numpy.sin(alt_rad)
    # Tilt in the along/up plane; the component across the heading is unchanged.
    forward = numpy.cos(tilt) * along - numpy.sin(tilt) * up
    axis = numpy.sin(tilt) * along + numpy.cos(tilt) * up
    return (numpy.arctan2(axis, numpy.hypot(across, forward)),
            heading + numpy.arctan2(across, forward))


def projectToPixels(alt_rad, az_rad, params, image_width, image_height, mirror=False,
                    lens_altitude=90.0, pointing_azimuth=0.0):
    """Project alt/az to pixels via VirtualSky's equisolid fisheye.
    params: [azimuth_deg, lat_off_deg, long_off_deg, diameter_px,
    offset_x_px, offset_y_px]; the lat/long offsets (1, 2) are applied by
    the caller before predictAltAz, not here.
    """
    alt_rad, az_rad = cameraAltAz(alt_rad, az_rad, lens_altitude, pointing_azimuth)
    azimuth_deg = params[0]
    diameter = params[3]
    offset_x = params[4]
    offset_y = params[5]

    cx = image_width / 2.0 + offset_x
    cy = image_height / 2.0 - offset_y

    theta = (numpy.pi / 2.0) - alt_rad
    r = (diameter / 2.0) * numpy.sin(theta / 2.0) / SIN45

    psi = az_rad - numpy.radians(azimuth_deg)

    sign = 1.0 if mirror else -1.0
    x = cx + sign * r * numpy.sin(psi)
    y = cy - r * numpy.cos(psi)

    return x, y


# warm astropy's sidereal-time machinery at import (cold first call costs
# seconds, tens of seconds on a Pi); the timestamp is arbitrary
_gmstRad(1700000000.0)
