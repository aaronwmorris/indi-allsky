#!/usr/bin/env python3

# The theory behind timezones is the sun should be relatively near zenith at noon
# If there is significant (6+ hours) offset between noon and the suns next transit, the longitude is probably wrong


import math
from datetime import datetime
import ephem
import logging


LATITUDE  = 33
LONGITUDE = -85



logging.basicConfig(level=logging.INFO)
logger = logging


class EquinoxTest(object):

    def main(self):
        now = datetime.now()
        utc_offset = now.astimezone().utcoffset()


        noon = datetime.strptime(now.strftime('%Y%m%d12'), '%Y%m%d%H')
        midnight = datetime.strptime(now.strftime('%Y%m%d00'), '%Y%m%d%H')
        midnight_utc = midnight - utc_offset


        obs = ephem.Observer()
        obs.lon = math.radians(LONGITUDE)
        obs.lat = math.radians(LATITUDE)

        sun = ephem.Sun()

        obs.date = midnight_utc
        sun.compute(obs)


        next_sun_transit = obs.next_transit(sun)
        local_next_sun_transit = next_sun_transit.datetime() + utc_offset


        if noon > local_next_sun_transit:
            transit_noon_diff_hours = (noon - local_next_sun_transit).seconds / 3600
        else:
            transit_noon_diff_hours = (local_next_sun_transit - noon).seconds / 3600


        logger.info('Sun will transit: %s', str(local_next_sun_transit))
        logger.info('Noon: %s', str(noon))
        logger.info('Diff: %0.1f', transit_noon_diff_hours)


if __name__ == "__main__":
    EquinoxTest().main()
