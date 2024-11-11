#!/usr/bin/env python3


import timeit
import logging


logging.basicConfig(level=logging.INFO)
logger = logging


class FloatBench(object):
    rounds = 30


    def main(self):
        setup_1 = '''
import numpy

width  = 3840
height = 2160

random_rgb_full = numpy.random.randint(255, size=(height, width, 3), dtype=numpy.uint16)
alpha = (random_rgb_full / 255).astype(numpy.float16)
'''

        s_1 = '''
random_rgb_full * alpha
'''

        setup_2 = '''
import numpy

width  = 3840
height = 2160

random_rgb_full = numpy.random.randint(255, size=(height, width, 3), dtype=numpy.uint16)
alpha = (random_rgb_full / 255).astype(numpy.float32)
'''

        s_2 = '''
random_rgb_full * alpha
'''

        setup_3 = '''
import numpy

width  = 3840
height = 2160

random_rgb_full = numpy.random.randint(255, size=(height, width, 3), dtype=numpy.uint16)
alpha = (random_rgb_full / 255).astype(numpy.float64)
'''

        s_3 = '''
random_rgb_full * alpha
'''


        setup_4 = '''
import numpy

width  = 3840
height = 2160

random_rgb_full = numpy.random.randint(255, size=(height, width, 3), dtype=numpy.uint16)
alpha = (random_rgb_full / 255).astype(numpy.float128)
'''

        s_4 = '''
random_rgb_full * alpha
'''




        t_1 = timeit.timeit(stmt=s_1, setup=setup_1, number=self.rounds)
        logger.info('float16:  %0.3fms', t_1 * 1000 / self.rounds)

        t_2 = timeit.timeit(stmt=s_2, setup=setup_2, number=self.rounds)
        logger.info('float32:  %0.3fms', t_2 * 1000 / self.rounds)

        t_3 = timeit.timeit(stmt=s_3, setup=setup_3, number=self.rounds)
        logger.info('float64:  %0.3fms', t_3 * 1000 / self.rounds)

        t_4 = timeit.timeit(stmt=s_4, setup=setup_4, number=self.rounds)
        logger.info('float128: %0.3fms', t_4 * 1000 / self.rounds)


if __name__ == "__main__":
    FloatBench().main()

