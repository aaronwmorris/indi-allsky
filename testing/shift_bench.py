#!/usr/bin/env python3


import timeit
import logging

#import cv2
#from PIL import Image


logging.basicConfig(level=logging.INFO)
logger = logging


class ShiftBench(object):
    rounds = 50


    def __init__(self):
        pass


    def main(self):

        setup_1 = '''
import numpy
random = numpy.random.randint(2 ** 16, size=(5000, 5000, 3), dtype=numpy.uint16)

bits = 16
div_factor = int((2 ** bits) / 255)
'''

        s1 = '''
(random / div_factor).astype(numpy.uint8)
'''

        setup_2 = '''
import numpy
random = numpy.random.randint(65535, size=(5000, 5000, 3), dtype=numpy.uint16)

bits = 16
shift_factor = bits - 8
'''

        s2 = '''
numpy.right_shift(random, shift_factor).astype(numpy.uint8)
'''


        t_1 = timeit.timeit(stmt=s1, setup=setup_1, number=self.rounds)
        logger.info('Numpy division: %0.3fms', t_1 * 1000 / self.rounds)

        t_2 = timeit.timeit(stmt=s2, setup=setup_2, number=self.rounds)
        logger.info('Numpy shift: %0.3fms', t_2 * 1000 / self.rounds)



if __name__ == "__main__":
    b = ShiftBench()
    b.main()

