#!/usr/bin/env python3


import timeit
import logging


logging.basicConfig(level=logging.INFO)
logger = logging


class DayCalcBench(object):
    rounds = 100

    def __init__(self):
        pass

    def main(self):
        setup_pyephem = '''
import math
from datetime import datetime
import ephem
'''

        s_pyephem = '''
now = datetime.now()
utc_offset = now.astimezone().utcoffset()

utcnow_notz = now - utc_offset

obs = ephem.Observer()
sun = ephem.Sun()
obs.lon = math.radians(33.0)
obs.lat = math.radians(-84.0)
obs.elevation = 300

# disable atmospheric refraction calcs
obs.pressure = 0

obs.date = utcnow_notz
sun.compute(obs)
night = math.degrees(sun.alt) < -6.0


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
'''


        setup_skyfield = '''
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from skyfield.api import load
from skyfield.api import wgs84
from skyfield import almanac
'''

        s_skyfield = '''
now = datetime.now()
utc_offset = now.astimezone().utcoffset()

utcnow_tz = (now - utc_offset).replace(tzinfo=timezone.utc)

eph = load('de421.bsp')
earth = eph['earth']
sun = eph['sun']
location = wgs84.latlon(33.0, -84.0)
observer = earth + location

ts = load.timescale()
t0 = ts.from_datetime(utcnow_tz)
t1 = ts.from_datetime(utcnow_tz + timedelta(hours=24))

sun_transit_f = almanac.meridian_transits(eph, sun, location)
sun_transit_times, sun_transit_events = almanac.find_discrete(t0, t1, sun_transit_f)
'''


        t_pyephem = timeit.timeit(stmt=s_pyephem, setup=setup_pyephem, number=self.rounds)
        logger.info('PyEphem calc: %0.3fms', t_pyephem * 1000 / self.rounds)

        t_skyfield = timeit.timeit(stmt=s_skyfield, setup=setup_skyfield, number=self.rounds)
        logger.info('Skyfield calc: %0.3fms', t_skyfield * 1000 / self.rounds)



if __name__ == "__main__":
    DayCalcBench().main()

