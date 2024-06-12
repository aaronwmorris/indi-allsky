#!/usr/bin/env python3

import math
import ephem
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import logging



LATITUDE  = 33.0
LONGITUDE = -84.0
ELEVATION = 300

MINUTES = 15


logging.basicConfig(level=logging.INFO)
logger = logging


class SunAltMinMax(object):

    def main(self):
        logger.warning('Latitude:  %0.1f', LATITUDE)
        logger.warning('Longitude: %0.1f', LONGITUDE)

        obs = ephem.Observer()
        sun = ephem.Sun()
        obs.lat = math.radians(LATITUDE)
        obs.lon = math.radians(LONGITUDE)
        obs.elevation = ELEVATION

        utcnow = datetime.now(tz=timezone.utc)
        #utcnow = datetime.now(tz=timezone.utc) - timedelta(days=5)

        sun_solstice_1 = ephem.next_solstice(utcnow)
        sun_solstice_2 = ephem.next_solstice(sun_solstice_1.datetime() + timedelta(days=1))

        logger.warning('Now - %s', utcnow)
        self.calcMinMax(utcnow, obs, sun)

        logger.warning('Solstice 1')
        self.calcMinMax(sun_solstice_1.datetime(), obs, sun)

        logger.warning('Solstice 2')
        self.calcMinMax(sun_solstice_2.datetime(), obs, sun)


    def calcMinMax(self, d, obs, sun):
        obs.date = d - timedelta(hours=1)  # offset time for transit at solstice
        sun.compute(obs)

        sun_next_transit = obs.next_transit(sun)
        obs.date = sun_next_transit
        sun.compute(obs)
        logger.info('%s: Max %0.1f', sun_next_transit.datetime(), math.degrees(sun.alt))

        sun_next_antitransit = sun_next_transit.datetime() + timedelta(hours=12)
        obs.date = sun_next_antitransit
        sun.compute(obs)
        logger.info('%s: Min %0.1f', sun_next_antitransit, math.degrees(sun.alt))



if __name__ == "__main__":
    SunAltMinMax().main()
