import time
from pathlib import Path
import cv2
import numpy
import logging


logger = logging.getLogger('indi_allsky')


class IndiAllSkyStars(object):

    _distanceThreshold = 10


    def __init__(self, config, bin_v, mask=None):
        self.config = config
        self.bin_v = bin_v

        self._sqm_mask = mask

        self._detectionThreshold = self.config.get('DETECT_STARS_THOLD', 0.6)

        if self.config['IMAGE_FOLDER']:
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()


        # start with a black image
        star_template = numpy.zeros([15, 15], dtype=numpy.uint8)

        # draw a white circle
        cv2.circle(
            img=star_template,
            center=(7, 7),
            radius=3,
            color=255,  # mono
            thickness=cv2.FILLED,
        )

        # blur circle to simulate a star
        self.star_template = cv2.blur(
            src=star_template,
            ksize=(2, 2),
        )

        self.star_template_w, self.star_template_h = self.star_template.shape[::-1]


    def detectObjects(self, original_data):
        if isinstance(self._sqm_mask, type(None)):
            # This only needs to be done once if a mask is not provided
            self._generateSqmMask(original_data)

        masked_img = cv2.bitwise_and(original_data, original_data, mask=self._sqm_mask)

        if len(original_data.shape) == 2:
            # gray scale or bayered
            grey_img = masked_img
        else:
            # assume color
            grey_img = cv2.cvtColor(masked_img, cv2.COLOR_BGR2GRAY)


        sep_start = time.time()


        result = cv2.matchTemplate(grey_img, self.star_template, cv2.TM_CCOEFF_NORMED)
        result_filter = numpy.where(result >= self._detectionThreshold)

        blobs = list()
        for pt in zip(*result_filter[::-1]):
            for blob in blobs:
                if (abs(pt[0] - blob[0]) < self._distanceThreshold) and (abs(pt[1] - blob[1]) < self._distanceThreshold):
                    break

            else:
                # if none of the points are under the distance threshold, then add it
                blobs.append(pt)


        sep_elapsed_s = time.time() - sep_start
        logger.info('Detected %d stars in %0.4f s', len(blobs), sep_elapsed_s)

        self._drawCircles(original_data, blobs)

        return blobs


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
            logger.warning('Using central ROI for star detection')
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

        self._sqm_mask = mask


    def _drawCircles(self, sep_data, blob_list):
        if not self.config.get('DETECT_DRAW'):
            return

        image_height, image_width = sep_data.shape[:2]

        color_bgr = list(self.config['TEXT_PROPERTIES']['FONT_COLOR'])
        color_bgr.reverse()

        logger.info('Draw circles around objects')
        for blob in blob_list:
            x, y = blob

            center = (
                int(x + (self.star_template_w / 2)) + 1,
                int(y + (self.star_template_h / 2)) + 1,
            )

            cv2.circle(
                img=sep_data,
                center=center,
                radius=6,
                color=tuple(color_bgr),
                #thickness=cv2.FILLED,
                thickness=1,
            )

