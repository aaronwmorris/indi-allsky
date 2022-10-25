#!/usr/bin/env python3

import math
from datetime import datetime
from datetime import timedelta
import ephem
import logging

logging.basicConfig(level=logging.INFO)
logger = logging



LATITUDE  = 33
LONGITUDE = -84


obs = ephem.Observer()
obs.lon = math.radians(LONGITUDE)
obs.lat = math.radians(LATITUDE)


sun = ephem.Sun()
moon = ephem.Moon()


utcnow = datetime.utcnow() - timedelta(days=30)

for x in range(20000):
    utcnow = utcnow + timedelta(hours=2)

    obs.date = utcnow

    sun.compute(obs)
    moon.compute(obs)

    sun_alt = math.degrees(sun.alt)

    moon_phase = moon.moon_phase * 100.0

    # separation of 1-3 degrees means a possible eclipse
    sun_moon_sep = abs((ephem.separation(moon, sun) / (math.pi / 180)) - 180)

    if sun_moon_sep < 0.8:
        # Lunar

        if sun_alt > -6:
            # not night time
            continue

        logger.info('Lunar: %s, separation: %0.3f, phase %0.2f', utcnow, sun_moon_sep, moon_phase)
    elif sun_moon_sep > 179.5:
        # Solar

        if sun_alt < -6:
            # not day time
            continue

        logger.info('Solar: %s, separation: %0.3f, phase %0.2f', utcnow, sun_moon_sep, moon_phase)

