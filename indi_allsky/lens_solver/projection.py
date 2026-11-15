import functools

import numpy
from astropy.time import Time
import astropy.units as u
from astropy.utils import iers

from ..fisheye import SIN45, cameraAltAz, projectToPixels


# never attempt IERS downloads on an offline allsky host, and accept an
# aged table rather than raise once "now" walks off its end -- the
# extrapolated UT1 error is milliseconds, far below arcminute-level fitting
iers.conf.auto_download = False
iers.conf.auto_max_age = None


RADIAL_MIN = -0.5  # monotonic on the front hemisphere, including orthographic
RADIAL_MAX = 1.0


def precessCatalog(catalog, obstime_unix):
    """J2000 -> mean equator/equinox of the image date (IAU 1976).

    Keep these angles in sync with VirtualSky.precessEquatorial. Applying
    precession before fitting prevents camera pointing from absorbing the
    changing orientation of the celestial reference frame.
    """
    t = (float(obstime_unix)/86400 + 2440587.5 - 2451545.0)/36525
    zeta, z, theta = numpy.radians(numpy.array([
        2306.2181*t + 0.30188*t*t + 0.017998*t*t*t,
        2306.2181*t + 1.09468*t*t + 0.018203*t*t*t,
        2004.3109*t - 0.42665*t*t - 0.041833*t*t*t]) / 3600)
    ra, dec = numpy.radians(catalog[:, :2].T)
    a = numpy.cos(dec)*numpy.sin(ra+zeta)
    b = numpy.cos(theta)*numpy.cos(dec)*numpy.cos(ra+zeta) - numpy.sin(theta)*numpy.sin(dec)
    c = numpy.sin(theta)*numpy.cos(dec)*numpy.cos(ra+zeta) + numpy.cos(theta)*numpy.sin(dec)
    result = numpy.array(catalog, dtype=float, copy=True)
    result[:, 0] = numpy.degrees(numpy.arctan2(a, b)+z) % 360
    result[:, 1] = numpy.degrees(numpy.arctan2(c, numpy.hypot(a, b)))
    return result


@functools.lru_cache(maxsize=8)
def _gmstRad(obstime_unix):
    # memoized: astropy must stay out of the fit hot loop; lst(t, lon)
    # == gmst(t) + radians(lon) to < 1e-7 arcsec
    return Time(float(obstime_unix), format='unix', scale='utc').sidereal_time(
        'mean', longitude=0.0 * u.deg).radian


def predictAltAz(catalog, latitude, longitude, obstime_unix):
    """Predict alt/az for catalog stars ([ra_deg, dec_deg, ...]).
    Replicates VirtualSky's horizon conversion, without refraction or
    aberration. New calibrations precess the catalog before calling this;
    legacy calibrations retain their uncorrected J2000 coordinates.
    Returns (alt_rad, az_rad), az from north increasing east.
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


# warm astropy's sidereal-time machinery at import (cold first call costs
# seconds, tens of seconds on a Pi); the timestamp is arbitrary
_gmstRad(1700000000.0)
