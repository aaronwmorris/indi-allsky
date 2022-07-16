import time
from pathlib import Path
import cv2
import numpy
import logging


logger = logging.getLogger('indi_allsky')


class IndiAllSkyStars(object):

    _detectionThreshold = 0.55
    _distanceThreshold = 10


    def __init__(self, config):
        self.config = config

        self.x_offset = 0
        self.y_offset = 0

        if self.config['IMAGE_FOLDER']:
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()


        # start with a black image
        template = numpy.zeros([15, 15], dtype=numpy.uint8)

        # draw a white circle
        cv2.circle(
            img=template,
            center=(7, 7),
            radius=3,
            color=(255, 255, 255),
            thickness=cv2.FILLED,
        )

        # blur circle to simulate a star
        self.star_template = cv2.blur(
            src=template,
            ksize=(2, 2),
        )

        self.star_template_w, self.star_template_h = self.star_template.shape[::-1]


    def detectObjects(self, original_data):
        image_height, image_width = original_data.shape[:2]

        sqm_roi = self.config.get('SQM_ROI', [])

        try:
            x1, y1, x2, y2 = sqm_roi
        except ValueError:
            logger.warning('Using central ROI for blob calculations')
            x1 = int((image_width / 2) - (image_width / 3))
            y1 = int((image_height / 2) - (image_height / 3))
            x2 = int((image_width / 2) + (image_width / 3))
            y2 = int((image_height / 2) + (image_height / 3))


        self.x_offset = x1
        self.y_offset = y1

        roi_data = original_data[
            y1:y2,
            x1:x2,
        ]


        if len(original_data.shape) == 2:
            # gray scale or bayered
            sep_data = roi_data
        else:
            # assume color
            sep_data = cv2.cvtColor(roi_data, cv2.COLOR_BGR2GRAY)


        sep_start = time.time()


        result = cv2.matchTemplate(sep_data, self.star_template, cv2.TM_CCOEFF_NORMED)
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
        logger.info('Star detection in %0.4f s', sep_elapsed_s)

        logger.info('Found %d objects', len(blobs))

        self._drawCircles(original_data, blobs, (x1, y1, x2, y2))

        return blobs


    def _drawCircles(self, sep_data, blob_list, box):
        if not self.config.get('DETECT_DRAW'):
            return

        ### Wait for line detection before drawing box
        #logger.info('Draw box around ROI')
        #cv2.rectangle(
        #    img=sep_data,
        #    pt1=(box[0], box[1]),
        #    pt2=(box[2], box[3]),
        #    color=(128, 128, 128),
        #    thickness=1,
        #)

        logger.info('Draw circles around objects')
        for blob in blob_list:
            x, y = blob

            center = (
                int(x + (self.star_template_w / 2)) + self.x_offset + 1,
                int(y + (self.star_template_h / 2)) + self.y_offset + 1,
            )

            cv2.circle(
                img=sep_data,
                center=center,
                radius=6,
                color=(192, 192, 192),
                #thickness=cv2.FILLED,
                thickness=1,
            )


