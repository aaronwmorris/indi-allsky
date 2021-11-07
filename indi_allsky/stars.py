import time
import tempfile
import shutil
from pathlib import Path
import cv2
import numpy

import multiprocessing

logger = multiprocessing.get_logger()


class IndiAllSkyStars(object):

    _detectionThreshold = 0.50
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
            lab = cv2.cvtColor(roi_data, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            sep_data = l


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

        #self.drawCircles(original_data, blobs)

        return blobs


    def drawCircles(self, original_data, blob_list):
        sep_data = original_data.copy()

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
                radius=5,
                color=(0, 0, 255),
                #thickness=cv2.FILLED,
                thickness=1,
            )


        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.jpg')
        f_tmpfile.close()

        tmpfile_name = Path(f_tmpfile.name)
        tmpfile_name.unlink()  # remove tempfile, will be reused below


        cv2.imwrite(str(tmpfile_name), sep_data, [cv2.IMWRITE_JPEG_QUALITY, self.config['IMAGE_FILE_COMPRESSION']['jpg']])

        sep_file = self.image_dir.joinpath('stars.jpg')

        shutil.copy2(f_tmpfile.name, str(sep_file))  # copy file in place
        sep_file.chmod(0o644)

        tmpfile_name.unlink()  # cleanup

