#!/usr/bin/env python3


import timeit
import logging


logging.basicConfig(level=logging.INFO)
logger = logging


class SatBench(object):
    rounds = 500

    def __init__(self):
        pass

    def main(self):
        setup_pyephem = '''
from datetime import datetime
from datetime import timezone
import io
import math
import ephem

obs = ephem.Observer()
obs.lat = math.radians(33.0)
obs.lon = math.radians(-84.0)

# disable atmospheric refraction calcs
obs.pressure = 0

with io.open('/tmp/iss_27272897.txt', 'r') as f_tle:
    tle_data = f_tle.readlines()
'''

        s_pyephem = '''
iss = ephem.readtle(*tle_data)
obs.date = datetime.now(tz=timezone.utc)
iss.compute(obs)
iss_next_pass = obs.next_pass(iss)
#math.degrees(iss.alt)
#math.degrees(iss.az)
#ephem.localtime(iss_next_pass[0])
#ephem.localtime(iss_next_pass[2])
#ephem.localtime(iss_next_pass[4])
'''


        setup_skyfield = '''
import io
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from skyfield.api import load
from skyfield.api import wgs84
from skyfield.api import EarthSatellite

ts = load.timescale()

location = wgs84.latlon(33.0, -84.0)

with io.open('/tmp/iss_27272897.txt', 'r') as f_tle:
    tle_data = f_tle.readlines()
'''

        s_skyfield = '''
satellite = EarthSatellite(tle_data[1], tle_data[2], tle_data[0], ts)

now = datetime.now(tz=timezone.utc)
t0 = ts.from_datetime(now)
t1 = ts.from_datetime(now + timedelta(hours=24))

t, events = satellite.find_events(location, t0, t1, altitude_degrees=0.0)
'''


        t_pyephem = timeit.timeit(stmt=s_pyephem, setup=setup_pyephem, number=self.rounds)
        logger.info('PyEphem calc: %0.3fms', t_pyephem * 1000 / self.rounds)

        t_skyfield = timeit.timeit(stmt=s_skyfield, setup=setup_skyfield, number=self.rounds)
        logger.info('Skyfield calc: %0.3fms', t_skyfield * 1000 / self.rounds)



if __name__ == "__main__":
    ib = SatBench()
    ib.main()

