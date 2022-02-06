#!/usr/bin/env python3

import ephem
import datetime
from dateutil import tz
import math
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging


LATITUDE = 33
LONGITUDE = -84
TIMEZONE = 'EST5EDT'
TIME_OFFSET = -5


local_tz = tz.gettz(TIMEZONE)

utcnow = datetime.datetime.utcnow()  # ephem expects UTC dates

obs = ephem.Observer()
obs.lat = math.radians(LATITUDE)
obs.lon = math.radians(LONGITUDE)
obs.date = utcnow

sun = ephem.Sun()
sun.compute(obs)


# Sun
sun_alt_deg = math.degrees(sun.alt)

sun_ha_rad = obs.sidereal_time() - sun.ra
sun_ha_deg = math.degrees(sun_ha_rad)


sun.compute(obs)
sun_rise_date = obs.next_rising(sun)
sun_set_date = obs.next_setting(sun)
sun_next_transit = obs.next_transit(sun)
obs.date = sun_rise_date
sun_rise_ha = math.degrees(obs.sidereal_time() - sun.ra)


logger.info('Sun alt: %0.7f rad', sun.alt)
logger.info('Sun alt: %0.1f', sun_alt_deg)
logger.info('Sun HA: %0.1f', sun_ha_deg)
logger.info('Sun Transit: %s', sun_next_transit)
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



obs.date = utcnow
sun.compute(obs)


try:
    if math.degrees(sun.alt) < 0:
        logger.info('Sun below horizon')
        sun_civilDawn_date = obs.next_rising(sun, use_center=True).datetime()
    else:
        logger.info('Sun already above horizon')
        sun_civilDawn_date = obs.previous_rising(sun, use_center=True).datetime()
except ephem.NeverUpError:
    # northern hemisphere
    sun_civilDawn_date = utcnow + datetime.timedelta(years=10)
except ephem.AlwaysUpError:
    # southern hemisphere
    sun_civilDawn_date = utcnow - datetime.timedelta(days=1)


try:
    sun_civilTwilight_date = obs.next_setting(sun, use_center=True).datetime()
except ephem.AlwaysUpError:
    # northern hemisphere
    sun_civilTwilight_date = utcnow - datetime.timedelta(days=1)
except ephem.NeverUpError:
    # southern hemisphere
    sun_civilTwilight_date = utcnow + datetime.timedelta(years=10)


data = {
    'sunrise'            : sun_civilDawn_date.replace(tzinfo=datetime.timezone.utc).isoformat(),
    'sunset'             : sun_civilTwilight_date.replace(tzinfo=datetime.timezone.utc).isoformat(),
    'streamDaytime'      : False,
}


print(json.dumps(data, indent=4))

