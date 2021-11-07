#!/usr/bin/env python3

import argparse
import time
import logging
import math
import tempfile
import shutil
from pathlib import Path
#from pprint import pformat
import cv2
import numpy


logging.basicConfig(level=logging.INFO)
logger = logging


class DetectBlob(object):

    _detectionThreshold = 0.50
    _distanceThreshold = 10

    def __init__(self):
        self.x_offset = 0
        self.y_offset = 0

        self.template = cv2.imread('resources/templateSM.jpg', cv2.IMREAD_GRAYSCALE)
        self.t_w, self.t_h = self.template.shape[::-1]


    def detectObjects(self, image_file):
        logger.info('Opening image')
        original_data = cv2.imread(str(image_file), cv2.IMREAD_UNCHANGED)

        image_height, image_width = original_data.shape[:2]

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
            logger.info('Extract luminance')
            #sep_data = cv2.cvtColor(original_data, cv2.COLOR_BGR2GRAY)
            lab = cv2.cvtColor(roi_data, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            sep_data = l.copy()

        #sep_data = cv2.equalizeHist(sep_data)

        sep_start = time.time()

        result = cv2.matchTemplate(sep_data, self.template, cv2.TM_CCOEFF_NORMED)
        result_filter = numpy.where(result >= self._detectionThreshold)

        blobs = list()
        for pt in zip(*result_filter[::-1]):
            for blob in blobs:
                d = math.sqrt(((pt[0] - blob[0]) ** 2) + ((pt[1] - blob[1]) ** 2))
                if d < self._distanceThreshold:
                    break

            else:
                # if none of the points are under the distance threshold, then add it
                blobs.append(pt)


        sep_elapsed_s = time.time() - sep_start
        logger.info('SEP processing in %0.4f s', sep_elapsed_s)


        logger.info('Found %d objects', len(blobs))

        self.drawCircles(original_data, blobs)

        return blobs


    def drawCircles(self, original_data, blob_list):
        sep_data = original_data.copy()

        t2_w = int(self.t_w / 2)
        t2_h = int(self.t_h / 2)

        logger.info('Draw circles around objects')
        for blob in blob_list:
            x, y = blob
            cv2.circle(
                img=sep_data,
                center=(int(x + 1) + t2_w + self.x_offset, int(y + 1) + t2_h + self.y_offset),
                radius=5,
                color=(0, 0, 255),
                #thickness=cv2.FILLED,
                thickness=1,
            )


        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.jpg')
        f_tmpfile.close()

        tmpfile_name = Path(f_tmpfile.name)
        tmpfile_name.unlink()  # remove tempfile, will be reused below


        cv2.imwrite(str(tmpfile_name), sep_data, [cv2.IMWRITE_JPEG_QUALITY, 90])

        sep_file = Path('blobs_ccoeff.jpg')

        shutil.copy2(f_tmpfile.name, str(sep_file))  # copy file in place
        sep_file.chmod(0o644)

        tmpfile_name.unlink()  # cleanup



if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'image',
        help='Image',
        type=str,
    )
    args = argparser.parse_args()

    db = DetectBlob()
    db.detectObjects(args.image)

