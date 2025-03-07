####################################################################################
# Algorithms below were borrowed from PixInsight docs
# https://www.pixinsight.com/doc/legacy/LE/21_noise_reduction/scnr/scnr.html
####################################################################################

#import time
#from pathlib import Path
import cv2
import numpy
import logging


logger = logging.getLogger('indi_allsky')


class IndiAllskyScnr(object):

    def __init__(self, config):
        self.config = config

        self.amount = self.config.get('SCNR_AMOUNT', 0.50)  # not currently used


    def additive_mask(self, scidata):
        ### The function below returns an out of memory error, needs to be fixed

        if len(scidata.shape) == 2:
            # grayscale
            return scidata

        #logger.warning('Applying SCNR additive mask')


        image_height, image_width = scidata.shape[:2]
        b, g, r = cv2.split(scidata)

        #start = time.time()

        ones = numpy.ones([image_height, image_width])

        m = numpy.minimum(ones, numpy.sum(r + b))

        #g * (1 - self.amount) * (1 - m) + m * g
        g = numpy.multiply(g * (1 - self.amount), numpy.sum(numpy.subtract(ones, m), numpy.multiply(m, g)))  # oom

        #elapsed_s = time.time() - start
        #logger.info('SCNR additive mask in %0.4f s', elapsed_s)

        return cv2.merge((b, g, r))


    def average_neutral(self, scidata):
        if len(scidata.shape) == 2:
            # grayscale
            return scidata

        #logger.warning('Applying SCNR average neutral')


        b, g, r = cv2.split(scidata)

        #start = time.time()

        # casting to uint16 (for uint8 data) to fix the magenta cast caused by overflows
        m = numpy.add(r.astype(numpy.uint16), b.astype(numpy.uint16)) * 0.5
        g = numpy.minimum(g, m.astype(numpy.uint8))

        #elapsed_s = time.time() - start
        #logger.info('SCNR average neutral in %0.4f s', elapsed_s)

        return cv2.merge((b, g, r))


    def maximum_neutral(self, scidata):
        if len(scidata.shape) == 2:
            # grayscale
            return scidata

        #logger.warning('Applying SCNR maximum neutral')


        b, g, r = cv2.split(scidata)

        #start = time.time()

        m = numpy.maximum(r, b)
        g = numpy.minimum(g, m)

        #elapsed_s = time.time() - start
        #logger.info('SCNR maximum neutral in %0.4f s', elapsed_s)

        return cv2.merge((b, g, r))


