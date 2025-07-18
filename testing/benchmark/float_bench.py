#!/usr/bin/env python3


import timeit
import logging


logging.basicConfig(level=logging.INFO)
logger = logging


class FloatBench(object):
    rounds = 50


    def main(self):
        setup_float16 = '''
import numpy

width  = 3840
height = 2160

random_rgb_full = numpy.random.randint(255, size=(height, width, 3), dtype=numpy.uint16)
alpha = (random_rgb_full / 255).astype(numpy.float16)
'''

        s_float16 = '''
random_rgb_full * alpha
'''

        setup_float32 = '''
import numpy

width  = 3840
height = 2160

random_rgb_full = numpy.random.randint(255, size=(height, width, 3), dtype=numpy.uint16)
alpha = (random_rgb_full / 255).astype(numpy.float32)
'''

        s_float32 = '''
random_rgb_full * alpha
'''

        setup_float64 = '''
import numpy

width  = 3840
height = 2160

random_rgb_full = numpy.random.randint(255, size=(height, width, 3), dtype=numpy.uint16)
alpha = (random_rgb_full / 255).astype(numpy.float64)
'''

        s_float64 = '''
random_rgb_full * alpha
'''


        setup_float128 = '''
import numpy

width  = 3840
height = 2160

random_rgb_full = numpy.random.randint(255, size=(height, width, 3), dtype=numpy.uint16)
alpha = (random_rgb_full / 255).astype(numpy.float128)
'''

        s_float128 = '''
random_rgb_full * alpha
'''


        setup_uint8 = '''
import numpy

width  = 3840
height = 2160

random_rgb_full = numpy.random.randint(255, size=(height, width, 3), dtype=numpy.uint16)
alpha = (random_rgb_full / 255).astype(numpy.uint8)
'''

        s_uint8 = '''
random_rgb_full * alpha
'''


        setup_uint16 = '''
import numpy

width  = 3840
height = 2160

random_rgb_full = numpy.random.randint(255, size=(height, width, 3), dtype=numpy.uint16)
alpha = (random_rgb_full / 255).astype(numpy.uint16)
'''

        s_uint16 = '''
random_rgb_full * alpha
'''


        setup_uint32 = '''
import numpy

width  = 3840
height = 2160

random_rgb_full = numpy.random.randint(255, size=(height, width, 3), dtype=numpy.uint16)
alpha = (random_rgb_full / 255).astype(numpy.uint32)
'''

        s_uint32 = '''
random_rgb_full * alpha
'''


        setup_uint64 = '''
import numpy

width  = 3840
height = 2160

random_rgb_full = numpy.random.randint(255, size=(height, width, 3), dtype=numpy.uint16)
alpha = (random_rgb_full / 255).astype(numpy.uint64)
'''

        s_uint64 = '''
random_rgb_full * alpha
'''


        setup_int8 = '''
import numpy

width  = 3840
height = 2160

random_rgb_full = numpy.random.randint(255, size=(height, width, 3), dtype=numpy.uint16)
alpha = (random_rgb_full / 255).astype(numpy.int8)
'''

        s_int8 = '''
random_rgb_full * alpha
'''


        setup_int16 = '''
import numpy

width  = 3840
height = 2160

random_rgb_full = numpy.random.randint(255, size=(height, width, 3), dtype=numpy.uint16)
alpha = (random_rgb_full / 255).astype(numpy.int16)
'''

        s_int16 = '''
random_rgb_full * alpha
'''


        setup_int32 = '''
import numpy

width  = 3840
height = 2160

random_rgb_full = numpy.random.randint(255, size=(height, width, 3), dtype=numpy.uint16)
alpha = (random_rgb_full / 255).astype(numpy.int32)
'''

        s_int32 = '''
random_rgb_full * alpha
'''


        setup_int64 = '''
import numpy

width  = 3840
height = 2160

random_rgb_full = numpy.random.randint(255, size=(height, width, 3), dtype=numpy.uint16)
alpha = (random_rgb_full / 255).astype(numpy.int64)
'''

        s_int64 = '''
random_rgb_full * alpha
'''



        t_float16 = timeit.timeit(stmt=s_float16, setup=setup_float16, number=self.rounds)
        logger.info('float16:  %0.3fms', t_float16 * 1000 / self.rounds)

        t_float32 = timeit.timeit(stmt=s_float32, setup=setup_float32, number=self.rounds)
        logger.info('float32:  %0.3fms', t_float32 * 1000 / self.rounds)

        t_float64 = timeit.timeit(stmt=s_float64, setup=setup_float64, number=self.rounds)
        logger.info('float64:  %0.3fms', t_float64 * 1000 / self.rounds)

        t_float128 = timeit.timeit(stmt=s_float128, setup=setup_float128, number=self.rounds)
        logger.info('float128: %0.3fms', t_float128 * 1000 / self.rounds)


        t_uint8 = timeit.timeit(stmt=s_uint8, setup=setup_uint8, number=self.rounds)
        logger.info('uint8: %0.3fms', t_uint8 * 1000 / self.rounds)

        t_uint16 = timeit.timeit(stmt=s_uint16, setup=setup_uint16, number=self.rounds)
        logger.info('uint16: %0.3fms', t_uint16 * 1000 / self.rounds)

        t_uint32 = timeit.timeit(stmt=s_uint32, setup=setup_uint32, number=self.rounds)
        logger.info('uint32: %0.3fms', t_uint32 * 1000 / self.rounds)

        t_uint64 = timeit.timeit(stmt=s_uint64, setup=setup_uint64, number=self.rounds)
        logger.info('uint64: %0.3fms', t_uint64 * 1000 / self.rounds)


        t_int8 = timeit.timeit(stmt=s_int8, setup=setup_int8, number=self.rounds)
        logger.info('int8: %0.3fms', t_int8 * 1000 / self.rounds)

        t_int16 = timeit.timeit(stmt=s_int16, setup=setup_int16, number=self.rounds)
        logger.info('int16: %0.3fms', t_int16 * 1000 / self.rounds)

        t_int32 = timeit.timeit(stmt=s_int32, setup=setup_int32, number=self.rounds)
        logger.info('int32: %0.3fms', t_int32 * 1000 / self.rounds)

        t_int64 = timeit.timeit(stmt=s_int64, setup=setup_int64, number=self.rounds)
        logger.info('int64: %0.3fms', t_int64 * 1000 / self.rounds)


if __name__ == "__main__":
    FloatBench().main()

