import math
from datetime import datetime
from datetime import timedelta
from decimal import Decimal
import logging

import ephem

from . import constants

logger = logging.getLogger('indi_allsky')


class IndiAllSkyExposureUtils(object):
    def __init__(self, config, exposure_av, gain_av):
        self.config = config

        self.exposure_av = exposure_av
        self.gain_av = gain_av



    ### Exposure


    @property
    def EXPOSURE_CURRENT(self):
        return Decimal('{0:0.6f}'.format(self.exposure_av[constants.EXPOSURE_CURRENT] / 1000000))

    @EXPOSURE_CURRENT.setter
    def EXPOSURE_CURRENT(self, new_exposure):
        with self.exposure_av.get_lock():
            self.exposure_av[constants.EXPOSURE_CURRENT] = int(float(new_exposure) * 1000000)


    @property
    def EXPOSURE_NEXT(self):
        return Decimal('{0:0.6f}'.format(self.exposure_av[constants.EXPOSURE_NEXT] / 1000000))

    @EXPOSURE_NEXT.setter
    def EXPOSURE_NEXT(self, new_exposure):
        with self.exposure_av.get_lock():
            self.exposure_av[constants.EXPOSURE_NEXT] = int(float(new_exposure) * 1000000)


    @property
    def EXPOSURE_DELTA(self):
        return Decimal('{0:0.6f}'.format(self.exposure_av[constants.EXPOSURE_DELTA] / 1000000))

    @EXPOSURE_DELTA.setter
    def EXPOSURE_DELTA(self, new_exposure):
        with self.exposure_av.get_lock():
            self.exposure_av[constants.EXPOSURE_DELTA] = int(float(new_exposure) * 1000000)


    @property
    def EXPOSURE_MIN_NIGHT(self):
        return Decimal('{0:0.6f}'.format(self.exposure_av[constants.EXPOSURE_MIN_NIGHT] / 1000000))

    @EXPOSURE_MIN_NIGHT.setter
    def EXPOSURE_MIN_NIGHT(self, new_exposure):
        with self.exposure_av.get_lock():
            self.exposure_av[constants.EXPOSURE_MIN_NIGHT] = int(float(new_exposure) * 1000000)


    @property
    def EXPOSURE_MIN_DAY(self):
        return Decimal('{0:0.6f}'.format(self.exposure_av[constants.EXPOSURE_MIN_DAY] / 1000000))

    @EXPOSURE_MIN_DAY.setter
    def EXPOSURE_MIN_DAY(self, new_exposure):
        with self.exposure_av.get_lock():
            self.exposure_av[constants.EXPOSURE_MIN_DAY] = int(float(new_exposure) * 1000000)


    @property
    def EXPOSURE_MAX(self):
        return Decimal('{0:0.6f}'.format(self.exposure_av[constants.EXPOSURE_MAX] / 1000000))

    @EXPOSURE_MAX.setter
    def EXPOSURE_MAX(self, new_exposure):
        with self.exposure_av.get_lock():
            self.exposure_av[constants.EXPOSURE_MAX] = int(float(new_exposure) * 1000000)


    @property
    def EXPOSURE_SQM(self):
        return Decimal('{0:0.6f}'.format(self.exposure_av[constants.EXPOSURE_SQM] / 1000000))

    @EXPOSURE_SQM.setter
    def EXPOSURE_SQM(self, new_exposure):
        with self.exposure_av.get_lock():
            self.exposure_av[constants.EXPOSURE_SQM] = int(float(new_exposure) * 1000000)


    ### Gain


    @property
    def GAIN_CURRENT(self):
        return Decimal('{0:0.3f}'.format(self.exposure_av[constants.GAIN_CURRENT] / 1000))

    @GAIN_CURRENT.setter
    def GAIN_CURRENT(self, new_gain):
        with self.gain_av.get_lock():
            self.gain_av[constants.GAIN_CURRENT] = int(float(new_gain) * 1000)


    @property
    def GAIN_NEXT(self):
        return Decimal('{0:0.3f}'.format(self.exposure_av[constants.GAIN_NEXT] / 1000))

    @GAIN_NEXT.setter
    def GAIN_NEXT(self, new_gain):
        with self.gain_av.get_lock():
            self.gain_av[constants.GAIN_NEXT] = int(float(new_gain) * 1000)


    @property
    def GAIN_DELTA(self):
        return Decimal('{0:0.3f}'.format(self.exposure_av[constants.GAIN_DELTA] / 1000))

    @GAIN_DELTA.setter
    def GAIN_DELTA(self, new_gain):
        with self.gain_av.get_lock():
            self.gain_av[constants.GAIN_DELTA] = int(float(new_gain) * 1000)


    @property
    def GAIN_MIN_DAY(self):
        return Decimal('{0:0.3f}'.format(self.exposure_av[constants.GAIN_MIN_DAY] / 1000))

    @GAIN_MIN_DAY.setter
    def GAIN_MIN_DAY(self, new_gain):
        with self.gain_av.get_lock():
            self.gain_av[constants.GAIN_MIN_DAY] = int(float(new_gain) * 1000)


    @property
    def GAIN_MAX_DAY(self):
        return Decimal('{0:0.3f}'.format(self.exposure_av[constants.GAIN_MAX_DAY] / 1000))

    @GAIN_MAX_DAY.setter
    def GAIN_MAX_DAY(self, new_gain):
        with self.gain_av.get_lock():
            self.gain_av[constants.GAIN_MAX_DAY] = int(float(new_gain) * 1000)


    @property
    def GAIN_MIN_NIGHT(self):
        return Decimal('{0:0.3f}'.format(self.exposure_av[constants.GAIN_MIN_NIGHT] / 1000))

    @GAIN_MIN_NIGHT.setter
    def GAIN_MIN_NIGHT(self, new_gain):
        with self.gain_av.get_lock():
            self.gain_av[constants.GAIN_MIN_NIGHT] = int(float(new_gain) * 1000)


    @property
    def GAIN_MAX_NIGHT(self):
        return Decimal('{0:0.3f}'.format(self.exposure_av[constants.GAIN_MAX_NIGHT] / 1000))

    @GAIN_MAX_NIGHT.setter
    def GAIN_MAX_NIGHT(self, new_gain):
        with self.gain_av.get_lock():
            self.gain_av[constants.GAIN_MAX_NIGHT] = int(float(new_gain) * 1000)


    @property
    def GAIN_MIN_MOONMODE(self):
        return Decimal('{0:0.3f}'.format(self.exposure_av[constants.GAIN_MIN_MOONMODE] / 1000))

    @GAIN_MIN_MOONMODE.setter
    def GAIN_MIN_MOONMODE(self, new_gain):
        with self.gain_av.get_lock():
            self.gain_av[constants.GAIN_MIN_MOONMODE] = int(float(new_gain) * 1000)


    @property
    def GAIN_MAX_MOONMODE(self):
        return Decimal('{0:0.3f}'.format(self.exposure_av[constants.GAIN_MAX_MOONMODE] / 1000))

    @GAIN_MAX_MOONMODE.setter
    def GAIN_MAX_MOONMODE(self, new_gain):
        with self.gain_av.get_lock():
            self.gain_av[constants.GAIN_MAX_MOONMODE] = int(float(new_gain) * 1000)


    @property
    def GAIN_SQM(self):
        return Decimal('{0:0.3f}'.format(self.exposure_av[constants.GAIN_SQM] / 1000))

    @GAIN_SQM.setter
    def GAIN_SQM(self, new_gain):
        with self.gain_av.get_lock():
            self.gain_av[constants.GAIN_SQM] = int(float(new_gain) * 1000)


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
        obs.lon = math.radians(self.position_av[constants.POSITION_LONGITUDE])
        obs.lat = math.radians(self.position_av[constants.POSITION_LATITUDE])
        obs.elevation = self.position_av[constants.POSITION_ELEVATION]

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
        obs.lon = math.radians(self.position_av[constants.POSITION_LONGITUDE])
        obs.lat = math.radians(self.position_av[constants.POSITION_LATITUDE])
        obs.elevation = self.position_av[constants.POSITION_ELEVATION]

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
