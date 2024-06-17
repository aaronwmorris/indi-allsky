from datetime import datetime
#from datetime import timedelta
from datetime import timezone
import math
import ephem
import logging

logger = logging.getLogger('indi_allsky')


class DayNightManager(object):

    def __init__(self, config, night_v, moonmode_v, dayDate_v, position_av):
        self.config = config

        self.night_v = night_v
        self.moonmode_v = moonmode_v
        self.dayDate_v = dayDate_v
        self.position_av = position_av

        self.night_sun_radians = math.radians(self.config['NIGHT_SUN_ALT_DEG'])
        self.night_moonmode_radians = math.radians(self.config['NIGHT_MOONMODE_ALT_DEG'])
        self.moonmode_phase = self.config['NIGHT_MOONMODE_PHASE']

        self.obs = ephem.Observer()
        self.obs.lon = math.radians(self.position_av[1])
        self.obs.lat = math.radians(self.position_av[0])
        self.obs.elevation = self.position_av[2]

        self.sun = ephem.Sun()
        self.moon = ephem.Moon()

        utcnow = datetime.now(tz=timezone.utc)  # ephem expects UTC dates
        self.obs.date = utcnow


    def update(self):
        utcnow = datetime.now(tz=timezone.utc)  # ephem expects UTC dates

        self.obs.date = utcnow
        self.sun.compute(self.obs)

        self.detectNight()
        self.detectMoonmode()


    def detectNight(self):
        logger.info('Sun altitude: %s', self.sun.alt)
        night = self.sun.alt < self.night_sun_radians  # boolean

        if night != bool(self.night_v.value):
            # switch between day/night
            with self.night_v.get_lock():
                self.night_v.value = int(night)

        return night


    def detectMoonMode(self):
        moonmode = False  # detected below

        if self.night_v.value:
            # night
            self.moon.compute(self.obs)
            moon_phase = self.moon.moon_phase * 100.0
            logger.info('Moon altitude: %s, phase %0.1f%%', self.moon.alt, moon_phase)

            if self.moon.alt >= self.night_moonmode_radians:
                if moon_phase >= self.moonmode_phase:
                    logger.info('Moon Mode conditions detected')
                    moonmode = True


            if moonmode != bool(self.moonmode_v.value):
                with self.moonmode_v.get_lock():
                    self.moonmode_v.value = int(moonmode)

        else:
            # day
            if self.moonmode_v.value:
                with self.moonmode_v.get_lock():
                    self.moonmode_v.value = 0


        return moonmode


    def updateDayDate(self):
        pass

