#!/usr/bin/env python3

import math
import ephem
from skyfield.api import load
from skyfield.api import wgs84
from skyfield import almanac
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import logging



LATITUDE  = 33.0
LONGITUDE = -84.0

#LATITUDE  = 75.0
#LONGITUDE = -160.0

ELEVATION = 300
PRESSURE  = 0  # 0 to disable refraction


logging.basicConfig(level=logging.INFO)
logger = logging


class SunAltMinMax(object):

    def main(self):
        logger.warning('Latitude:  %0.1f', LATITUDE)
        logger.warning('Longitude: %0.1f', LONGITUDE)

        utcnow = datetime.now(tz=timezone.utc)
        #utcnow = datetime.now(tz=timezone.utc) - timedelta(days=5)

        self.main_pyephem(utcnow)
        self.main_skyfield(utcnow)


    def main_pyephem(self, utcnow):
        obs = ephem.Observer()
        sun = ephem.Sun()
        obs.lat = math.radians(LATITUDE)
        obs.lon = math.radians(LONGITUDE)
        obs.elevation = ELEVATION
        obs.pressure = PRESSURE


        sun_solstice_1 = ephem.next_solstice(utcnow)
        sun_solstice_2 = ephem.next_solstice(sun_solstice_1.datetime() + timedelta(days=1))

        logger.warning('pyephem Now - %s', utcnow)
        self.calcMinMax_pyephem(utcnow, obs, sun)


        logger.warning('pyephem Solstice 1')
        self.calcMinMax_pyephem(sun_solstice_1.datetime(), obs, sun)


        logger.warning('pyephem Solstice 2')
        self.calcMinMax_pyephem(sun_solstice_2.datetime(), obs, sun)


    def calcMinMax_pyephem(self, d, obs, sun):
        obs.date = d - timedelta(hours=1)  # offset time for transit at solstice
        sun.compute(obs)

        sun_next_transit_m = obs.next_transit(sun)
        obs.date = sun_next_transit_m
        sun.compute(obs)
        logger.info('%s: Max %0.3f', sun_next_transit_m.datetime(), math.degrees(sun.alt))

        sun_next_transit_a = sun_next_transit_m.datetime() + timedelta(hours=12)  # close enough
        obs.date = sun_next_transit_a
        sun.compute(obs)
        logger.info('%s: Min %0.3f', sun_next_transit_a, math.degrees(sun.alt))


    def main_skyfield(self, utcnow):
        eph = load('de421.bsp')
        earth = eph['earth']
        sun = eph['sun']

        loc = wgs84.latlon(LATITUDE, LONGITUDE, elevation_m=ELEVATION)
        obs = earth + loc

        logger.warning('skyfield Now - %s', utcnow)
        self.calcMinMax_skyfield(utcnow, eph, loc, obs, sun)


        ts = load.timescale()
        t0 = ts.from_datetime(utcnow)
        t1 = ts.from_datetime(utcnow + timedelta(days=365))


        seasons_times, seasons_events = almanac.find_discrete(t0, t1, almanac.seasons(eph))

        logger.warning('skyfield Solstice 1')
        seasons_times_ss = seasons_times[seasons_events == almanac.SEASON_EVENTS.index('Summer Solstice')]
        self.calcMinMax_skyfield(seasons_times_ss[0].utc_datetime(), eph, loc, obs, sun)


        logger.warning('skyfield Solstice 2')
        seasons_times_ws = seasons_times[seasons_events == almanac.SEASON_EVENTS.index('Winter Solstice')]
        self.calcMinMax_skyfield(seasons_times_ws[0].utc_datetime(), eph, loc, obs, sun)


    def calcMinMax_skyfield(self, d, eph, loc, obs, sun):
        ts = load.timescale()
        t0 = ts.from_datetime(d)
        t1 = ts.from_datetime(d + timedelta(hours=24))


        sun_transit_f = almanac.meridian_transits(eph, sun, loc)
        sun_transit_times, sun_transit_events = almanac.find_discrete(t0, t1, sun_transit_f)


        sun_transit_times_m = sun_transit_times[sun_transit_events == almanac.MERIDIAN_TRANSITS.index('Meridian transit')]
        sun_alt_max, sun_az_max, sun_dist_max = obs.at(sun_transit_times_m[0]).observe(sun).apparent().altaz(pressure_mbar=PRESSURE)
        logger.info('%s: Max %0.3f', sun_transit_times_m[0].utc_datetime(), sun_alt_max.degrees)

        sun_transit_times_a = sun_transit_times[sun_transit_events == almanac.MERIDIAN_TRANSITS.index('Antimeridian transit')]
        sun_alt_min, sun_az_min, sun_dist_min = obs.at(sun_transit_times_a[0]).observe(sun).apparent().altaz(pressure_mbar=PRESSURE)
        logger.info('%s: Min %0.3f', sun_transit_times_a[0].utc_datetime(), sun_alt_min.degrees)


if __name__ == "__main__":
    SunAltMinMax().main()
