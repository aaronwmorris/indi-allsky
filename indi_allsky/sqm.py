#import cv2
import numpy

import multiprocessing

logger = multiprocessing.get_logger()


class IndiAllskySqm(object):

    mask_percentile = 99


    def __init__(self, config):
        self.config = config

        self.max_exposure = self.config['CCD_EXPOSURE_MAX']

        self.image_height = None
        self.image_width = None


    def calculate(self, img, exposure):
        self.image_height, self.image_width = img.shape[:2]

        roidata = self.getRoi(img)

        masked = self.maskStars(roidata)

        sqm_avg = numpy.mean(masked)
        logger.info('Raw SQM average: %0.2f', sqm_avg)

        if self.max_exposure == exposure:
            weighted_sqm_avg = sqm_avg
        else:
            # offset the sqm based on the exposure
            weighted_sqm_avg = ((self.max_exposure - exposure) + 1) * sqm_avg

        logger.info('Weighted SQM average: %0.2f', weighted_sqm_avg)

        return weighted_sqm_avg



    def getRoi(self, img):
        sqm_roi = self.config.get('SQM_ROI', [])

        try:
            x1, y1, x2, y2 = sqm_roi
        except ValueError:
            logger.warning('Using central 20% ROI for SQM calculations')
            x1 = int((self.image_width / 2) - (self.image_width / 5))
            y1 = int((self.image_height / 2) - (self.image_height / 5))
            x2 = int((self.image_width / 2) + (self.image_width / 5))
            y2 = int((self.image_height / 2) + (self.image_height / 5))


        roidata = img[
            y1:y2,
            x1:x2,
        ]

        return roidata


    def maskStars(self, img):
        p = numpy.percentile(img, self.mask_percentile)

        logger.info('SQM %d%% percentile: %d', self.mask_percentile, p)

        # find values less than mask percentile
        # assuming max values are saturated pixels due to stars
        masked = img[img < p]

        return masked

