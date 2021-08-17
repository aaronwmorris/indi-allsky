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

moon = ephem.Moon()
moon.compute(obs)

logger.info('Moon phase: %0.2f%%', moon.moon_phase * 100)
moon_alt_deg = math.degrees(moon.alt)
logger.info('Moon alt: %0.1f', moon_alt_deg)
