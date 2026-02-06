import math
import cv2
import numpy
import logging

from . import constants


logger = logging.getLogger('indi_allsky')


class IndiAllskySqm(object):

    def __init__(
        self,
        config,
        gain_av,
        bin_v,
        mask=None,
    ):
        self.config = config
        self.gain_av = gain_av
        self.bin_v = bin_v

        # both masks will be combined
        self._external_mask = mask
        self._sqm_mask = None


    def averageAdu(self, i_ref):
        fits_data = i_ref.hdulist[0].data

        #logger.info('Exposure: %0.6f, gain: %0.1f', exposure, gain)


        if len(fits_data.shape) == 2:
            # mono
            sqm_img = fits_data
        else:
            # color
            sqm_img = fits_data[1]  # green channel


        if isinstance(self._sqm_mask, type(None)):
            # This only needs to be done once if a mask is not provided
            self._generateSqmMask(sqm_img)


        return cv2.mean(src=sqm_img, mask=self._sqm_mask)[0]


    def jankySqm(self, i_ref):
        sqm_avg = self.averageAdu(i_ref)

        # offset the sqm based on the exposure and gain
        weighted_sqm_avg = (((self.config['CCD_EXPOSURE_MAX'] - i_ref.exposure) / 10) + 1) * (sqm_avg * (((float(self.gain_av[constants.GAIN_MAX_NIGHT]) - i_ref.gain) / 10) + 1))

        logger.info('Raw SQM: %0.2f, Weighted SQM: %0.2f', sqm_avg, weighted_sqm_avg)

        return weighted_sqm_avg


    def magnitudeSqm(self, i_ref):
        sqm_avg = self.averageAdu(i_ref)

        mag_sqm = 32.0 - (math.log10(sqm_avg) * 2.5)

        return mag_sqm


    def _generateSqmMask(self, img):
        logger.info('Generating mask based on SQM_ROI')

        image_height, image_width = img.shape[:2]

        # create a black background
        mask = numpy.zeros((image_height, image_width), dtype=numpy.uint8)

        sqm_roi = self.config.get('SQM_ROI', [])

        try:
            x1 = int(sqm_roi[0] / self.bin_v.value)
            y1 = int(sqm_roi[1] / self.bin_v.value)
            x2 = int(sqm_roi[2] / self.bin_v.value)
            y2 = int(sqm_roi[3] / self.bin_v.value)
        except IndexError:
            logger.warning('Using central ROI for SQM calculations')
            sqm_fov_div = self.config.get('SQM_FOV_DIV', 4)
            x1 = int((image_width / 2) - (image_width / sqm_fov_div))
            y1 = int((image_height / 2) - (image_height / sqm_fov_div))
            x2 = int((image_width / 2) + (image_width / sqm_fov_div))
            y2 = int((image_height / 2) + (image_height / sqm_fov_div))

        # The white area is what we keep
        cv2.rectangle(
            img=mask,
            pt1=(x1, y1),
            pt2=(x2, y2),
            color=255,  # mono
            thickness=cv2.FILLED,
        )


        # combine masks in case there is overlapping regions
        if not isinstance(self._external_mask, type(None)):
            self._sqm_mask = cv2.bitwise_and(mask, mask, mask=self._external_mask)
            return


        self._sqm_mask = mask

