import time
#from pathlib import Path
#import cv2
import numpy
import logging


logger = logging.getLogger('indi_allsky')


class IndiAllskyScnr(object):

    def __init__(self, config):
        self.config = config

        self.amount = self.config.get('SCNR_AMOUNT', 0.50)


    def additive_mask_function(self, p):
        b, g, r = p

        m = min(1, r + b)

        p[1] = g * (1 - self.amount) * (1 - m) + m * g

        return p


    def additive_mask(self, scidata):
        if len(scidata.shape) == 2:
            return scidata

        logger.warning('Applying SCNR additive_mask function')

        start = time.time()

        scnr_data = numpy.apply_along_axis(self.additive_mask_function, 2, scidata)

        elapsed_s = time.time() - start
        logger.info('SCNR additive mask in %0.4f s', elapsed_s)

        return scnr_data


    def average_neutral_function(self, p):
        b, g, r = p

        m = 0.5 * (r + b)

        p[1] = min(g, m)

        return p


    def average_neutral(self, scidata):
        if len(scidata.shape) == 2:
            return scidata

        logger.warning('Applying SCNR average_neutral')

        start = time.time()

        scnr_data = numpy.apply_along_axis(self.average_neutral_function, 2, scidata)

        elapsed_s = time.time() - start
        logger.info('SCNR average neutral in %0.4f s', elapsed_s)

        return scnr_data


