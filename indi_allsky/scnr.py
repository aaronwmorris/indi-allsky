import time
#from pathlib import Path
#import cv2
#import numpy
import logging


logger = logging.getLogger('indi_allsky')


class IndiAllskyScnr(object):

    def __init__(self, config):
        self.config = config

        self.amount = self.config.get('SCNR_AMOUNT', 0.50)


    def additive(self, scidata):
        if len(scidata.shape) == 2:
            return

        logger.warning('Applying SCNR additive function')

        image_height, image_width = scidata.shape[:2]

        start = time.time()

        for y in range(0, image_height):
            for x in range(0, image_width):
                b, g, r = scidata[y, x]

                m = min(1, r + b)

                g = g * (1 - self.amount) * (1 - m) + m * g

        elapsed_s = time.time() - start
        logger.info('SCNR additive in %0.4f s', elapsed_s)


        return

