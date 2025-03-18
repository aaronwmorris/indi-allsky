#!/usr/bin/env python3

import ephem
from skyfield.api import load
from skyfield.api import wgs84
from skyfield.api import EarthSatellite
from skyfield import almanac
import io
import math
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pprint import pformat  # noqa: F401
import logging

logging.basicConfig(level=logging.INFO)
logger = logging


LATITUDE = 33.0
LONGITUDE = -84.0

PRESSURE = 1010  # 0 disables refraction



class svp(object):

    def __init__(self):
        with io.open('/tmp/iss_27272897.txt', 'r') as f_tle:
            self.tle_data = f_tle.readlines()


    def main(self):
        utcnow = datetime.now(tz=timezone.utc)  # ephem expects UTC dates


        ### Sun ###
        # pyephem
        p_obs = ephem.Observer()
        p_obs.lat = math.radians(LATITUDE)
        p_obs.lon = math.radians(LONGITUDE)
        p_obs.date = utcnow
        p_obs.horizon = math.radians(0)
        p_obs.pressure = PRESSURE


        p_sun = ephem.Sun()
        p_moon = ephem.Moon()
        p_jupiter = ephem.Jupiter()
        p_sun.compute(p_obs)
        p_moon.compute(p_obs)
        p_jupiter.compute(p_obs)


        p_sun_alt_deg = math.degrees(p_sun.alt)
        logger.info('Sun alt: %0.1f', p_sun_alt_deg)

        p_sun_rise_date = p_obs.next_rising(p_sun)
        p_sun_set_date = p_obs.next_setting(p_sun)
        p_sun_next_transit = p_obs.next_transit(p_sun)

        logger.info('Sun rise: %s', p_sun_rise_date)
        logger.info('Sun set: %s', p_sun_set_date)
        logger.info('Sun Transit: %s', p_sun_next_transit)

        p_sun_ha_rad = p_obs.sidereal_time() - p_sun.ra
        p_sun_ha_deg = math.degrees(p_sun_ha_rad)
        logger.info('Sun HA: %0.1f', p_sun_ha_deg)

        p_moon_alt_deg = math.degrees(p_moon.alt)
        logger.info('Moon alt: %0.1f', p_moon_alt_deg)
        logger.info('Moon phase: %0.2f%%', p_moon.moon_phase * 100)

        p_jupiter_alt_deg = math.degrees(p_jupiter.alt)
        logger.info('Jupiter alt: %0.1f', p_jupiter_alt_deg)


        # skyfield
        s_eph = load('de421.bsp')
        s_earth = s_eph['earth']
        s_sun = s_eph['sun']
        s_moon = s_eph['moon']
        s_jup = s_eph['jupiter barycenter']

        s_location = wgs84.latlon(LATITUDE, LONGITUDE)
        s_observer = s_earth + s_location

        ts = load.timescale()
        t0 = ts.from_datetime(utcnow)
        t1 = ts.from_datetime(utcnow + timedelta(hours=24))

        s_sun_alt, s_sun_az, s_sun_dist = s_observer.at(t0).observe(s_sun).apparent().altaz(pressure_mbar=PRESSURE)
        logger.info('Sun alt: %0.1f', s_sun_alt.degrees)

        s_rise_twil_time, s_civil_twil_up = almanac.find_discrete(t0, t1, self.daylength(s_eph, s_location, 0.8333))
        logger.info('Sun time: %s', s_rise_twil_time[0].utc_datetime())
        logger.info('Sun time: %s', s_rise_twil_time[1].utc_datetime())


        s_sun_transit_f = almanac.meridian_transits(s_eph, s_sun, s_location)
        s_sun_transit_times, s_sun_transit_events = almanac.find_discrete(t0, t1, s_sun_transit_f)
        s_sun_transit_times = s_sun_transit_times[s_sun_transit_events == almanac.MERIDIAN_TRANSITS.index('Meridian transit')]  # Select transits instead of antitransits.
        logger.info('Sun Transit: %s', s_sun_transit_times[0].utc_datetime())

        s_sun_ha, s_sun_dec, s_sun_dist = s_observer.at(t0).observe(s_sun).apparent().hadec()
        logger.info('Sun HA: %0.1f', math.degrees(s_sun_ha.radians))

        s_moon_alt, s_moon_az, s_moon_dist = s_observer.at(t0).observe(s_moon).apparent().altaz(pressure_mbar=PRESSURE)
        logger.info('Moon alt: %0.1f', s_moon_alt.degrees)

        e_at = s_earth.at(t0)
        s_m_earth = e_at.observe(s_moon)

        moon_percent = s_m_earth.fraction_illuminated(s_sun)
        logger.info('Moon phase: %0.2f%%', moon_percent * 100)

        s_jup_alt, s_jup_az, s_jup_dist = s_observer.at(t0).observe(s_jup).apparent().altaz(pressure_mbar=PRESSURE)
        logger.info('Jupiter Alt: %0.1f', s_jup_alt.degrees)


        ### Satellite ###
        # pyephem
        p_iss = ephem.readtle(*self.tle_data)
        p_iss.compute(p_obs)
        p_iss_next_pass = p_obs.next_pass(p_iss)

        logger.info('iss: altitude %4.1f, azimuth %5.1f', math.degrees(p_iss.alt), math.degrees(p_iss.az))
        logger.info(' next rise: {0:%Y-%m-%d %H:%M:%S} ({1:0.1f}h), max: {2:%Y-%m-%d %H:%M:%S}, set: {3:%Y-%m-%d %H:%M:%S} - duration {4:d}s - elev {5:0.1f}km'.format(
            p_iss_next_pass[0].datetime(),
            (p_iss_next_pass[0].datetime() - utcnow.replace(tzinfo=None)).total_seconds() / 3600,
            p_iss_next_pass[2].datetime(),
            p_iss_next_pass[4].datetime(),
            (p_iss_next_pass[4].datetime() - p_iss_next_pass[0].datetime()).seconds,
            p_iss.elevation / 1000,
        ))


        # skyfield
        s_iss = EarthSatellite(self.tle_data[1], self.tle_data[2], self.tle_data[0], ts)

        s_iss_diff = s_iss - s_location
        s_iss_topocentric = s_iss_diff.at(t0)

        s_iss_alt, s_iss_az, s_iss_distance = s_iss_topocentric.altaz(pressure_mbar=PRESSURE)
        logger.info('iss: altitude %4.1f, azimuth %5.1f', s_iss_alt.degrees, s_iss_az.degrees)

        s_iss_geocentric = s_iss.at(t0)
        #s_iss_lat, s_iss_lon = wgs84.latlon_of(s_iss_geocentric)
        s_iss_height = wgs84.height_of(s_iss_geocentric)
        #earth_radius_km = 6378.16

        t_iss, iss_events = s_iss.find_events(s_location, t0, t1, altitude_degrees=0.0)
        s_iss_event_list = list(zip(t_iss.utc_datetime(), iss_events))
        #logger.info('%s', pformat(s_iss_event_list))
        logger.info(' next rise: {0:%Y-%m-%d %H:%M:%S} ({1:0.1f}h), max: {2:%Y-%m-%d %H:%M:%S}, set: {3:%Y-%m-%d %H:%M:%S} - duration {4:d}s - elev {5:0.1f}km'.format(
            s_iss_event_list[0][0],
            (s_iss_event_list[0][0] - utcnow).total_seconds() / 3600,
            s_iss_event_list[1][0],
            s_iss_event_list[2][0],
            (s_iss_event_list[2][0] - s_iss_event_list[0][0]).seconds,
            s_iss_height.km,
        ))


    def daylength(self, ephemeris, topos, degrees):
        """Build a function of time that returns the daylength.

        The function that this returns will expect a single argument that is a
        :class:`~skyfield.timelib.Time` and will return ``True`` if the sun is up
        or twilight has started, else ``False``.
        """
        from skyfield.nutationlib import iau2000b

        sun = ephemeris['sun']
        topos_at = (ephemeris['earth'] + topos).at

        def is_sun_up_at(t):
            """Return `True` if the sun has risen by time `t`."""
            t._nutation_angles = iau2000b(t.tt)
            return topos_at(t).observe(sun).apparent().altaz(pressure_mbar=PRESSURE)[0].degrees > -degrees

        is_sun_up_at.rough_period = 0.5  # twice a day
        return is_sun_up_at


if __name__ == "__main__":
    svp().main()
