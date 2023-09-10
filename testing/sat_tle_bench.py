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
        setup_sat = '''
from datetime import datetime
import io
import math
import ephem

obs = ephem.city('Atlanta')

with io.open('/tmp/iss_27272897.txt', 'r') as f_tle:
    tle_data = f_tle.readlines()
'''

        s_sat = '''
iss = ephem.readtle(*tle_data)
obs.date = datetime.utcnow()
iss.compute(obs)
iss_next_pass = obs.next_pass(iss)
#math.degrees(iss.alt)
#math.degrees(iss.az)
#ephem.localtime(iss_next_pass[0])
#ephem.localtime(iss_next_pass[2])
#ephem.localtime(iss_next_pass[4])
'''


        t_sat = timeit.timeit(stmt=s_sat, setup=setup_sat, number=self.rounds)
        logger.info('Satellite calc: %0.3fms', t_sat * 1000 / self.rounds)



if __name__ == "__main__":
    ib = SatBench()
    ib.main()

