import math
from datetime import datetime
from datetime import timedelta
import logging

import ephem

logger = logging.getLogger('indi_allsky')


class IndiAllSkyDateCalcs(object):

    def __init__(self, config, position_av):
        self.config = config

        self.position_av = position_av

        self.night_sun_radians = math.radians(self.config['NIGHT_SUN_ALT_DEG'])


    def calcDayDate(self, now):
        utc_offset = now.astimezone().utcoffset()

        utcnow_notz = now - utc_offset

        obs = ephem.Observer()
        sun = ephem.Sun()
        obs.lon = math.radians(self.position_av[1])
        obs.lat = math.radians(self.position_av[0])
        obs.elevation = self.position_av[2]

        # disable atmospheric refraction calcs
        obs.pressure = 0

        obs.date = utcnow_notz
        sun.compute(obs)
        night = sun.alt < self.night_sun_radians


        start_day = datetime.strptime(now.strftime('%Y%m%d'), '%Y%m%d')
        start_day_utc = start_day - utc_offset

        obs.date = start_day_utc
        sun.compute(obs)


        today_meridian = obs.next_transit(sun).datetime()
        obs.date = today_meridian
        sun.compute(obs)

        previous_antimeridian = obs.previous_antitransit(sun).datetime()
        next_antimeridian = obs.next_antitransit(sun).datetime()

        obs.date = next_antimeridian
        sun.compute(obs)


        if utcnow_notz < previous_antimeridian:
            #logger.warning('Pre-antimeridian')
            dayDate = (now - timedelta(days=1)).date()
        elif utcnow_notz < today_meridian:
            #logger.warning('Pre-meridian')

            if night:
                dayDate = (now - timedelta(days=1)).date()
            else:
                dayDate = now.date()
        elif utcnow_notz < next_antimeridian:
            #logger.warning('Post-meridian')
            dayDate = now.date()
        else:
            #logger.warning('Post-antimeridian')

            if night:
                dayDate = now.date()
            else:
                dayDate = (now + timedelta(days=1)).date()


        return dayDate


    def getDayDate(self):
        now = datetime.now()
        return self.calcDayDate(now)


    def getNextDayNightTransition(self):
        now = datetime.now()
        utc_offset = now.astimezone().utcoffset()
        utcnow_notz = now - utc_offset


        obs = ephem.Observer()
        sun = ephem.Sun()
        obs.lon = math.radians(self.position_av[1])
        obs.lat = math.radians(self.position_av[0])
        obs.elevation = self.position_av[2]

        # disable atmospheric refraction calcs
        obs.pressure = 0

        obs.date = utcnow_notz
        sun.compute(obs)
        night = sun.alt < self.night_sun_radians


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
            #logger.warning('Pre-antimeridian')
            night_stop = today_meridian

            if night:
                day_stop = next_antimeridian
            else:
                day_stop = previous_antimeridian
        elif utcnow_notz < today_meridian:
            #logger.warning('Pre-meridian')

            if night:
                night_stop = today_meridian
            else:
                night_stop = next_meridian

            day_stop = next_antimeridian
        elif utcnow_notz < next_antimeridian:
            #logger.warning('Post-meridian')
            night_stop = next_meridian

            if night:
                day_stop = next_antimeridian_2
            else:
                day_stop = next_antimeridian
        else:
            #logger.warning('Post-antimeridian')
            night_stop = next_meridian
            day_stop = next_antimeridian_2


        if night_stop < day_stop:
            next_stop = night_stop
        else:
            next_stop = day_stop


        return next_stop + utc_offset
