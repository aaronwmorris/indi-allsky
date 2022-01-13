#import cv2
import numpy
import logging


logger = logging.getLogger('indi_allsky')


class IndiAllskySqm(object):

    mask_percentile = 99


    def __init__(self, config):
        self.config = config


    def calculate(self, img, exposure, gain):
        logger.info('Exposure: %0.6f, gain: %d', exposure, gain)
        roidata = self.getRoi(img)

        masked = self.maskStars(roidata)

        sqm_avg = numpy.mean(masked)
        logger.info('Raw SQM average: %0.2f', sqm_avg)

        # offset the sqm based on the exposure and gain
        weighted_sqm_avg = (((self.config['CCD_EXPOSURE_MAX'] - exposure) / 10) + 1) * (sqm_avg * (((self.config['CCD_CONFIG']['NIGHT']['GAIN'] - gain) / 10) + 1))

        logger.info('Weighted SQM average: %0.2f', weighted_sqm_avg)

        return weighted_sqm_avg



    def getRoi(self, img):
        image_height, image_width = img.shape[:2]

        sqm_roi = self.config.get('SQM_ROI', [])

        try:
            x1, y1, x2, y2 = sqm_roi
        except ValueError:
            logger.warning('Using central 20% ROI for SQM calculations')
            x1 = int((image_width / 2) - (image_width / 5))
            y1 = int((image_height / 2) - (image_height / 5))
            x2 = int((image_width / 2) + (image_width / 5))
            y2 = int((image_height / 2) + (image_height / 5))


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


    def getStarless(self, img):
        self.image_height, self.image_width = img.shape[:2]

        roidata = self.getRoi(img)

        no_stars = self.replaceStars(roidata)

        return no_stars



    def replaceStars(self, img):
        p = numpy.percentile(img, self.mask_percentile)

        masked = numpy.where[img < p, 0, img]

        return masked

