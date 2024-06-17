#!/usr/bin/env python3


from datetime import datetime
from datetime import timedelta
#from datetime import timezone
import pytz
import math
import ephem
import logging


logging.basicConfig(level=logging.INFO)
logger = logging


### If the longitude changes, make sure the TZ is correct

#TZ        = 'America/New_York'
TZ        = 'America/Chicago'
LATITUDE  = 33.0
LONGITUDE = -85.0

#TZ        = 'America/Anchorage'
#LATITUDE  = 75.0
#LONGITUDE = -160.0

SUN_ALT   = -6.0


class DayNightStop(object):
    def main(self):

        #utcnow = datetime.now(tz=timezone.utc)
        utcnow = datetime.now(tz=pytz.timezone('UTC'))
        #utcnow -= timedelta(hours=20.5)
        #utcnow -= timedelta(days=180)


        now_tz = utcnow.astimezone(pytz.timezone(TZ))
        utc_offset = now_tz.utcoffset()
        now = now_tz.replace(tzinfo=None)
        utcnow_notz = now - utc_offset


        obs = ephem.Observer()
        sun = ephem.Sun()
        obs.lat = math.radians(LATITUDE)
        obs.lon = math.radians(LONGITUDE)
        obs.date = utcnow_notz


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


        if utcnow_notz < previous_antitransit:
            logger.warning('Pre-antimeridian')
            dayDate = (now - timedelta(days=1)).date()

            night_stop = today_transit

            if night:
                day_stop = next_antitransit
            else:
                day_stop = previous_antitransit
        elif utcnow_notz < today_transit:
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
        logger.info('Now:             %s, %0.1f', now.strftime('%Y-%m-%d %H:%M:%S'), now_sun_alt)
        logger.info('Timezone:        %s', TZ)
        logger.info('Night:           %s', str(night))
        logger.info('Start Day:       %s', start_day.strftime('%Y-%m-%d %H:%M:%S'))
        #logger.info('Start Day UTC:   %s', start_day_utc)
        logger.info('UTC Offset:      %s', utc_offset)
        logger.info('Current dayDate  %s', dayDate)
        logger.info('Today Transit:   %s', (today_transit + utc_offset).strftime('%Y-%m-%d %H:%M:%S'))
        logger.info('Night Hard Stop: %s, %0.1f', (night_stop + utc_offset).strftime('%Y-%m-%d %H:%M:%S'), end_night_alt)
        logger.info('Day Hard Stop:   %s, %0.1f', (day_stop + utc_offset).strftime('%Y-%m-%d %H:%M:%S'), end_day_alt)



if __name__ == "__main__":
    DayNightStop().main()

