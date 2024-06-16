#!/usr/bin/env python3


from datetime import datetime
from datetime import timedelta
#from datetime import timezone
import math
import ephem
import logging


logging.basicConfig(level=logging.INFO)
logger = logging



LATITUDE  = 33.0
LONGITUDE = -84.0

LATITUDE  = 62.9
LONGITUDE = -160.0

SUN_ALT   = -6.0


class DayNightStop(object):
    def main(self):


        obs = ephem.Observer()
        sun = ephem.Sun()
        obs.lat = math.radians(LATITUDE)
        obs.lon = math.radians(LONGITUDE)


        now = datetime.now()
        #now -= timedelta(hours=11.5)
        #now -= timedelta(days=180)

        utc_offset = now.astimezone().utcoffset()
        now_utc = now - utc_offset


        obs.date = now_utc
        sun.compute(obs)
        now_sun_alt = math.degrees(sun.alt)
        night = now_sun_alt < SUN_ALT


        start_day = datetime.strptime(now.strftime('%Y%m%d'), '%Y%m%d')
        start_day_utc = start_day - utc_offset

        obs.date = start_day_utc
        sun.compute(obs)


        today_transit = obs.next_transit(sun).datetime()
        obs.date = today_transit
        sun.compute(obs)

        previous_antitransit = obs.previous_antitransit(sun).datetime()
        next_antitransit = obs.next_antitransit(sun).datetime()


        if now_utc < previous_antitransit:
            logger.warning('Pre-antimeridian')
            dayDate = (now - timedelta(days=1)).date()

            night_stop = today_transit

            if night:
                day_stop = next_antitransit
            else:
                day_stop = previous_antitransit
        elif now_utc < today_transit:
            logger.warning('Pre-meridian')

            if night:
                dayDate = (now - timedelta(days=1)).date()
            else:
                dayDate = now.date()

            night_stop = today_transit
            day_stop = next_antitransit
        else:
            logger.warning('Post-meridian')
            dayDate = now.date()

            next_transit = obs.next_transit(sun).datetime()

            night_stop = next_transit
            day_stop = next_antitransit



        obs.date = night_stop
        sun.compute(obs)
        end_night_alt = math.degrees(sun.alt)

        obs.date = day_stop
        sun.compute(obs)
        end_day_alt = math.degrees(sun.alt)


        logger.info('Latitude:        %0.1f', LATITUDE)
        logger.info('Longitude:       %0.1f', LONGITUDE)
        logger.info('Now:             %s, %0.1f', now, now_sun_alt)
        logger.info('Night:           %s', str(night))
        logger.info('Start Day:       %s', start_day)
        #logger.info('Start Day UTC:   %s', start_day_utc)
        logger.info('UTC Offset:      %s', utc_offset)
        logger.info('Current dayDate  %s', dayDate)
        logger.info('Today Transit:   %s', today_transit + utc_offset)
        logger.info('Night Hard Stop: %s, %0.1f', night_stop + utc_offset, end_night_alt)
        logger.info('Day Hard Stop:   %s, %0.1f', day_stop + utc_offset, end_day_alt)



if __name__ == "__main__":
    DayNightStop().main()

