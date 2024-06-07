#!/usr/bin/env python3

import ephem
from skyfield.api import load
from skyfield.api import wgs84
import math
from datetime import datetime
#from datetime import timedelta
from datetime import timezone
import logging

logging.basicConfig(level=logging.INFO)
logger = logging


LATITUDE = 33.0
LONGITUDE = -84.0




class svp(object):


    def main(self):
        utcnow = datetime.now(tz=timezone.utc)  # ephem expects UTC dates

        p_obs = ephem.Observer()
        p_obs.lat = math.radians(LATITUDE)
        p_obs.lon = math.radians(LONGITUDE)
        p_obs.date = utcnow


        p_sun = ephem.Sun()
        p_sun.compute(p_obs)


        p_sun_alt_deg = math.degrees(p_sun.alt)
        logger.info('Sun alt: %0.1f', p_sun_alt_deg)



        s_eph = load('de421.bsp')
        s_sun = s_eph['Sun']
        s_loc = wgs84.latlon(LATITUDE, LONGITUDE)
        s_observer = s_eph['Earth'] + s_loc

        ts = load.timescale()
        t = ts.from_datetime(utcnow)

        s_sun_alt, s_sun_az, dist = s_observer.at(t).observe(s_sun).apparent().altaz()

        logger.info('Sun alt: %0.1f', s_sun_alt.degrees)



if __name__ == "__main__":
    svp().main()
