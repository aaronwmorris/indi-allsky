#!/usr/bin/env python3

import ephem
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import math
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging


LATITUDE = 33
LONGITUDE = -84

PRESSURE = 1010  # 0 disables refraction


utcnow = datetime.now(tz=timezone.utc)  # ephem expects UTC dates
#utcnow = datetime.now(tz=timezone.utc) + timedelta(days=10)

obs = ephem.Observer()
obs.lat = math.radians(LATITUDE)
obs.lon = math.radians(LONGITUDE)
obs.pressure = PRESSURE
obs.date = utcnow

logger.info('Latitude: %s', obs.lat.znorm)

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
logger.info('Sun rise: %s', ephem.localtime(sun_rise_date))
logger.info('Sun set: %s', ephem.localtime(sun_set_date))
logger.info('Sun Transit: %s', ephem.localtime(sun_next_transit))
logger.info('Sun rise HA: %0.1f', sun_rise_ha)


obs.horizon = math.radians(-18)
sun.compute(obs)
sun_dawn_date = obs.next_rising(sun)
sun_twilight_date = obs.next_setting(sun)

logger.info('Sun dawn: %s', ephem.localtime(sun_dawn_date))
logger.info('Sun twilight: %s', ephem.localtime(sun_twilight_date))

# Moon
obs.date = datetime.now(tz=timezone.utc)  # ephem expects UTC dates
obs.horizon = math.radians(0)

moon = ephem.Moon()
moon.compute(obs)

moon_alt_deg = math.degrees(moon.alt)
logger.info('Moon alt: %0.1f', moon_alt_deg)
logger.info('Moon phase: %0.2f%%', moon.moon_phase * 100)



obs.date = utcnow
sun.compute(obs)
moon.compute(obs)


#quarter
quarter_names = (
    'Waxing Crescent',
    'Waxing Gibbous',
    'Waning Gibbous',
    'Waning Crescent'
)
sun_lon = ephem.Ecliptic(sun).lon
moon_lon = ephem.Ecliptic(moon).lon

sm_angle = (moon_lon - sun_lon) % math.tau
#logger.info('Sun/Moon angle: %0.8f', sm_angle)
moon_quarter = int(sm_angle * 4.0 // math.tau)
#logger.info('Quarter: %0.8f', sm_angle * 4.0 / math.tau)
logger.info('Phase percent: %0.1f', (sm_angle / math.tau) * 100)
logger.info('Quarter: %d, %s', moon_quarter + 1, quarter_names[moon_quarter])



try:
    if math.degrees(sun.alt) < 0:
        logger.info('Sun below horizon')
        sun_civilDawn_date = obs.next_rising(sun, use_center=True).datetime()
    else:
        logger.info('Sun already above horizon')
        sun_civilDawn_date = obs.previous_rising(sun, use_center=True).datetime()
except ephem.NeverUpError:
    # northern hemisphere
    sun_civilDawn_date = utcnow + timedelta(years=10)
except ephem.AlwaysUpError:
    # southern hemisphere
    sun_civilDawn_date = utcnow - timedelta(days=1)


try:
    sun_civilTwilight_date = obs.next_setting(sun, use_center=True).datetime()
except ephem.AlwaysUpError:
    # northern hemisphere
    sun_civilTwilight_date = utcnow - timedelta(days=1)
except ephem.NeverUpError:
    # southern hemisphere
    sun_civilTwilight_date = utcnow + timedelta(years=10)


data = {
    'sunrise'            : sun_civilDawn_date.replace(tzinfo=timezone.utc).isoformat(),
    'sunset'             : sun_civilTwilight_date.replace(tzinfo=timezone.utc).isoformat(),
    'streamDaytime'      : False,
}


print(json.dumps(data, indent=4))

