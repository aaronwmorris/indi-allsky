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

TZ        = 'America/Chicago'
#TZ        = 'America/New_York'
LATITUDE  = 33.0
LONGITUDE = -84.0

#UTC_DT    = datetime(2024, 6, 21, 5, 20, 0, tzinfo=pytz.timezone('UTC'))  # summer solstice pre antimeridian
#UTC_DT    = datetime(2024, 6, 21, 10, 20, 0, tzinfo=pytz.timezone('UTC'))  # summer solstice pre meridian
#UTC_DT    = datetime(2024, 6, 21, 20, 20, 0, tzinfo=pytz.timezone('UTC'))  # summer solstice post meridian

#UTC_DT    = datetime(2024, 12, 21, 5, 20, 0, tzinfo=pytz.timezone('UTC'))  # winter solstice pre antimeridian
#UTC_DT    = datetime(2024, 12, 21, 10, 20, 0, tzinfo=pytz.timezone('UTC'))  # winter solstice pre meridian
#UTC_DT    = datetime(2024, 12, 21, 19, 0, 0, tzinfo=pytz.timezone('UTC'))  # winter solstice post meridian


#LATITUDE  = 75.0
#LONGITUDE = -70.0
#UTC_DT    = datetime(2024, 6, 21, 2, 50, 0, tzinfo=pytz.timezone('UTC'))  # summer solstice pre antimeridian  75 lat test


#TZ        = 'America/Anchorage'
#LATITUDE  = 75.0
#LONGITUDE = -160.0

### always day
#UTC_DT    = datetime(2024, 6, 20, 10, 0, 0, tzinfo=pytz.timezone('UTC'))  # summer solstice pre antimeridian
#UTC_DT    = datetime(2024, 6, 20, 18, 0, 0, tzinfo=pytz.timezone('UTC'))  # summer solstice pre meridian
#UTC_DT    = datetime(2024, 6, 21, 3, 0, 0, tzinfo=pytz.timezone('UTC'))  # summer solstice post meridian

### always night
#UTC_DT    = datetime(2024, 12, 21, 10, 0, 0, tzinfo=pytz.timezone('UTC'))  # winter solstice pre antimeridian
#UTC_DT    = datetime(2024, 12, 21, 18, 0, 0, tzinfo=pytz.timezone('UTC'))  # winter solstice pre meridian
#UTC_DT    = datetime(2024, 12, 22, 3, 0, 0, tzinfo=pytz.timezone('UTC'))  # winter solstice post meridian

UTC_DT     = datetime.now(tz=pytz.timezone('UTC'))

SUN_ALT   = -6.0


class DayNightStop(object):
    def main(self):

        utcnow = UTC_DT
        #utcnow -= timedelta(hours=5)
        #utcnow -= timedelta(hours=180)


        now_tz = utcnow.astimezone(pytz.timezone(TZ))
        utc_offset = now_tz.utcoffset()
        now = now_tz.replace(tzinfo=None)
        utcnow_notz = now - utc_offset


        obs = ephem.Observer()
        sun = ephem.Sun()
        obs.lat = math.radians(LATITUDE)
        obs.lon = math.radians(LONGITUDE)
        obs.date = utcnow_notz

        # disable atmospheric refraction calcs
        obs.pressure = 0

        sun.compute(obs)
        now_sun_alt = math.degrees(sun.alt)
        night = now_sun_alt < SUN_ALT


        start_day = datetime.strptime(now.strftime('%Y%m%d'), '%Y%m%d')
        start_day_utc = start_day - utc_offset

        obs.date = start_day_utc
        sun.compute(obs)


        today_meridian = obs.next_transit(sun).datetime()
        obs.date = today_meridian
        sun.compute(obs)

        next_meridian = obs.next_transit(sun).datetime()
        previous_antimeridian = obs.previous_antitransit(sun).datetime()
        next_antimeridian = obs.next_antitransit(sun).datetime()

        obs.date = next_antimeridian
        sun.compute(obs)
        next_antimeridian_2 = obs.next_antitransit(sun).datetime()


        if utcnow_notz < previous_antimeridian:
            logger.warning('Pre-antimeridian')
            dayDate = (now - timedelta(days=1)).date()

            night_stop = today_meridian

            if night:
                day_stop = next_antimeridian
            else:
                day_stop = previous_antimeridian
        elif utcnow_notz < today_meridian:
            logger.warning('Pre-meridian')

            if night:
                dayDate = (now - timedelta(days=1)).date()
                night_stop = today_meridian
            else:
                dayDate = now.date()
                night_stop = next_meridian

            day_stop = next_antimeridian
        elif utcnow_notz < next_antimeridian:
            logger.warning('Post-meridian')
            dayDate = now.date()

            night_stop = next_meridian

            if night:
                day_stop = next_antimeridian_2
            else:
                day_stop = next_antimeridian
        else:
            logger.warning('Post-antimeridian')

            night_stop = next_meridian

            if night:
                dayDate = now.date()
            else:
                dayDate = (now + timedelta(days=1)).date()

            day_stop = next_antimeridian_2



        obs.date = night_stop
        sun.compute(obs)
        end_night_alt = math.degrees(sun.alt)

        obs.date = day_stop
        sun.compute(obs)
        end_day_alt = math.degrees(sun.alt)


        if night_stop < day_stop:
            next_stop = night_stop
        else:
            next_stop = day_stop


        logger.info('Latitude:        %0.1f', LATITUDE)
        logger.info('Longitude:       %0.1f', LONGITUDE)
        logger.info('Now:             %s, %0.1f', now.strftime('%Y-%m-%d %H:%M:%S'), now_sun_alt)
        logger.info('Timezone:        %s', TZ)
        logger.info('Night:           %s', str(night))
        logger.info('Start Day:       %s', start_day.strftime('%Y-%m-%d %H:%M:%S'))
        #logger.info('Start Day UTC:   %s', start_day_utc)
        logger.info('UTC Offset:      %s', utc_offset)
        logger.info('Current dayDate  %s', dayDate)
        logger.info('Today Transit:   %s', (today_meridian + utc_offset).strftime('%Y-%m-%d %H:%M:%S'))
        logger.info('Night Hard Stop: %s, %0.1f', (night_stop + utc_offset).strftime('%Y-%m-%d %H:%M:%S'), end_night_alt)
        logger.info('Day Hard Stop:   %s, %0.1f', (day_stop + utc_offset).strftime('%Y-%m-%d %H:%M:%S'), end_day_alt)
        logger.info('Next Hard Stop:  %s', (next_stop + utc_offset).strftime('%Y-%m-%d %H:%M:%S'))



if __name__ == "__main__":
    DayNightStop().main()

