#!/usr/bin/env python3

import ephem
import datetime
from dateutil import tz
import math
import logging

logging.basicConfig(level=logging.INFO)
logger = logging


LATITUDE = 33
LONGITUDE = -84
TIMEZONE = 'EST5EDT'
TIME_OFFSET = -5


local_tz = tz.gettz(TIMEZONE)

obs = ephem.Observer()
obs.lat = math.radians(LATITUDE)
obs.lon = math.radians(LONGITUDE)
obs.date = datetime.datetime.utcnow()  # ephem expects UTC dates

sun = ephem.Sun()
sun.compute(obs)


# Sun
sun_alt_deg = math.degrees(sun.alt)

sun_ha_rad = obs.sidereal_time() - sun.ra
sun_ha_deg = math.degrees(sun_ha_rad)


sun.compute(obs)
sun_rise_date = obs.next_rising(sun)
sun_set_date = obs.next_setting(sun)
obs.date = sun_rise_date
sun_rise_ha = math.degrees(obs.sidereal_time() - sun.ra)


logger.info('Sun alt: %0.1f', sun_alt_deg)
logger.info('Sun HA: %0.1f', sun_ha_deg)
logger.info('Sun rise: %s', ephem.Date(sun_rise_date + (ephem.hour * TIME_OFFSET)))
#logger.info('Sun rise: %s', sun_rise_date.datetime().astimezone(local_tz))
logger.info('Sun rise HA: %0.1f', sun_rise_ha)
logger.info('Sun set: %s', ephem.Date(sun_set_date + (ephem.hour * TIME_OFFSET)))


obs.horizon = math.radians(-18)
sun.compute(obs)
sun_dawn_date = obs.next_rising(sun)
sun_twilight_date = obs.next_setting(sun)

logger.info('Sun dawn: %s', ephem.Date(sun_dawn_date + (ephem.hour * TIME_OFFSET)))
logger.info('Sun twilight: %s', ephem.Date(sun_twilight_date + (ephem.hour * TIME_OFFSET)))

# Moon
obs.date = datetime.datetime.utcnow()  # ephem expects UTC dates
obs.horizon = math.radians(0)

moon = ephem.Moon()
moon.compute(obs)

moon_alt_deg = math.degrees(moon.alt)
logger.info('Moon alt: %0.1f', moon_alt_deg)
logger.info('Moon phase: %0.2f%%', moon.moon_phase * 100)
