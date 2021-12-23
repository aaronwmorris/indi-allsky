#!/usr/bin/env python3

import ephem
import datetime
import math
import logging

logging.basicConfig(level=logging.INFO)
logger = logging


obs = ephem.Observer()
obs.lon = '-84'
obs.lat = '33'
obs.date = datetime.datetime.utcnow()  # ephem expects UTC dates

sun = ephem.Sun()
sun.compute(obs)


# Sun
sun_alt_deg = math.degrees(sun.alt)

sun_ha_rad = obs.sidereal_time() - sun.ra
sun_ha_deg = math.degrees(sun_ha_rad)


sun_rise = obs.next_rising(sun)
sun_set = obs.next_setting(sun)
obs.date = sun_rise
sun.compute(obs)
sun_rise_ha = math.degrees(obs.sidereal_time() - sun.ra)


logger.info('Sun alt: %0.1f', sun_alt_deg)
logger.info('Sun HA: %0.1f', sun_ha_deg)
logger.info('Sun rise: %s', sun_rise)
logger.info('Sun rise HA: %0.1f', sun_rise_ha)
logger.info('Sun set: %s', sun_set)


# Moon
obs.date = datetime.datetime.utcnow()  # ephem expects UTC dates

moon = ephem.Moon()
moon.compute(obs)

moon_alt_deg = math.degrees(moon.alt)
logger.info('Moon alt: %0.1f', moon_alt_deg)
logger.info('Moon phase: %0.2f%%', moon.moon_phase * 100)
