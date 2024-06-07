#!/usr/bin/env python3

import ephem
from skyfield.api import load
from skyfield.api import wgs84
from skyfield.api import EarthSatellite
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


        p_sun = ephem.Sun()
        p_moon = ephem.Moon()
        p_sun.compute(p_obs)
        p_moon.compute(p_obs)


        p_sun_alt_deg = math.degrees(p_sun.alt)
        logger.info('Sun alt: %0.1f', p_sun_alt_deg)


        moon_alt_deg = math.degrees(p_moon.alt)
        logger.info('Moon alt: %0.1f', moon_alt_deg)
        logger.info('Moon phase: %0.2f%%', p_moon.moon_phase * 100)


        # skyfield
        s_eph = load('de421.bsp')
        s_earth = s_eph['earth']
        s_sun = s_eph['sun']
        s_moon = s_eph['moon']

        s_location = wgs84.latlon(LATITUDE, LONGITUDE)
        s_observer = s_earth + s_location

        ts = load.timescale()
        t0 = ts.from_datetime(utcnow)

        s_sun_alt, s_sun_az, dist = s_observer.at(t0).observe(s_sun).apparent().altaz()

        logger.info('Sun alt: %0.1f', s_sun_alt.degrees)

        s_moon_alt, s_moon_az, dist = s_observer.at(t0).observe(s_moon).apparent().altaz()
        logger.info('Moon alt: %0.1f', s_moon_alt.degrees)

        e_at = s_earth.at(t0)
        s_m_earth = e_at.observe(s_moon)

        moon_percent = s_m_earth.fraction_illuminated(s_sun)
        logger.info('Moon phase: %0.2f%%', moon_percent * 100)


        ### Satellite ###
        # pyephem
        p_iss = ephem.readtle(*self.tle_data)
        p_iss.compute(p_obs)
        p_iss_next_pass = p_obs.next_pass(p_iss)

        logger.info('iss: altitude %4.1f, azimuth %5.1f', math.degrees(p_iss.alt), math.degrees(p_iss.az))
        logger.info(' next rise: {0:%Y-%m-%d %H:%M:%S} ({1:0.1f}h), max: {2:%Y-%m-%d %H:%M:%S}, set: {3:%Y-%m-%d %H:%M:%S} - duration {4:d}s - elev {5:0.1f}km'.format(
            ephem.localtime(p_iss_next_pass[0]),
            (p_iss_next_pass[0].datetime() - utcnow.replace(tzinfo=None)).total_seconds() / 3600,
            ephem.localtime(p_iss_next_pass[2]),
            ephem.localtime(p_iss_next_pass[4]),
            (ephem.localtime(p_iss_next_pass[4]) - ephem.localtime(p_iss_next_pass[0])).seconds,
            p_iss.elevation / 1000,
        ))


        # skyfield
        s_iss = EarthSatellite(self.tle_data[1], self.tle_data[2], self.tle_data[0], ts)

        s_iss_diff = s_iss - s_location
        s_iss_topocentric = s_iss_diff.at(t0)

        s_iss_alt, s_iss_az, s_iss_distance = s_iss_topocentric.altaz()
        logger.info('iss: altitude %4.1f, azimuth %5.1f', s_iss_alt.degrees, s_iss_az.degrees)

        s_iss_geocentric = s_iss.at(t0)
        #s_iss_lat, s_iss_lon = wgs84.latlon_of(s_iss_geocentric)
        s_iss_height = wgs84.height_of(s_iss_geocentric)
        #earth_radius_km = 6378.16

        t1 = ts.from_datetime(utcnow + timedelta(hours=24))
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


if __name__ == "__main__":
    svp().main()
