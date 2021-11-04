import time
import math
import tempfile
import shutil
from pathlib import Path
from skimage.feature import blob_dog
import cv2
import numpy

import multiprocessing

logger = multiprocessing.get_logger()


class IndiAllSkySep(object):

    def __init__(self, config):
        self.config = config

        self.x_offset = 0
        self.y_offset = 0

        if self.config['IMAGE_FOLDER']:
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()



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

        blobs = blob_dog(sep_data, max_sigma=5, min_sigma=1, threshold=.1, overlap=0.1)

        sep_elapsed_s = time.time() - sep_start
        logger.info('SEP processing in %0.4f s', sep_elapsed_s)

        logger.info('Found %d objects', len(blobs))

        #self.drawCircles(original_data, blobs)

        return blobs


    def drawCircles(self, original_data, blob_list):
        if numpy.any(blob_list):
            # Compute radii in the 3rd column
            blob_list[:, 2] = blob_list[:, 2] * math.sqrt(2)

        sep_data = original_data.copy()

        logger.info('Draw circles around objects')
        for blob in blob_list:
            y, x, r = blob
            cv2.circle(
                img=sep_data,
                center=(int(x) + self.x_offset, int(y) + self.y_offset),
                radius=int(r) + 4,
                color=(0, 0, 255),
                #thickness=cv2.FILLED,
                thickness=1,
            )


        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.jpg')
        f_tmpfile.close()

        tmpfile_name = Path(f_tmpfile.name)
        tmpfile_name.unlink()  # remove tempfile, will be reused below


        cv2.imwrite(str(tmpfile_name), sep_data, [cv2.IMWRITE_JPEG_QUALITY, self.config['IMAGE_FILE_COMPRESSION']['jpg']])

        sep_file = self.image_dir.joinpath('blobs.jpg')

        shutil.copy2(f_tmpfile.name, str(sep_file))  # copy file in place
        sep_file.chmod(0o644)

        tmpfile_name.unlink()  # cleanup

