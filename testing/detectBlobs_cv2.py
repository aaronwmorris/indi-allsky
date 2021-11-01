#!/usr/bin/env python3

import argparse
import time
import logging
#import math
import tempfile
import shutil
from pathlib import Path
#from pprint import pformat
import cv2
import numpy


logging.basicConfig(level=logging.INFO)
logger = logging


class DetectBlob(object):

    def __init__(self):
        #self.x_offset = 0
        #self.y_offset = 0

        blob_params = cv2.SimpleBlobDetector_Params()
        blob_params.minThreshold = 50
        blob_params.maxThreshold = 250
        blob_params.filterByArea = True
        blob_params.minArea = 3
        blob_params.maxArea = 20
        blob_params.filterByCircularity = False
        blob_params.minCircularity = 0.5
        blob_params.filterByConvexity = False
        blob_params.filterByInertia = False
        blob_params.filterByColor = False

        self.detector = cv2.SimpleBlobDetector_create(blob_params)


    def detectObjects(self, image_file):
        logger.info('Opening image')
        original_data = cv2.imread(str(image_file), cv2.IMREAD_UNCHANGED)

        image_height, image_width = original_data.shape[:2]

        logger.warning('Using central ROI for blob calculations')
        x1 = int((image_width / 2) - (image_width / 3))
        y1 = int((image_height / 2) - (image_height / 3))
        x2 = int((image_width / 2) + (image_width / 3))
        y2 = int((image_height / 2) + (image_height / 3))

        #self.x_offset = x1
        #self.y_offset = y1

        roi_data = original_data[
            y1:y2,
            x1:x2,
        ]
        #roi_data = original_data


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

        keypoints = self.detector.detect(sep_data)

        sep_elapsed_s = time.time() - sep_start
        logger.info('SEP processing in %0.4f s', sep_elapsed_s)

        logger.info('Found %d objects', len(keypoints))

        self.drawCircles(roi_data, keypoints)

        return keypoints


    def drawCircles(self, original_data, keypoints):
        sep_data = original_data.copy()

        logger.info('Draw circles around objects')
        sep_image = cv2.drawKeypoints(
            image=sep_data,
            keypoints=keypoints,
            outImage=numpy.array([]),
            color=(0, 0, 255),
            flags=cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS,
        )

        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.jpg')
        f_tmpfile.close()

        tmpfile_name = Path(f_tmpfile.name)
        tmpfile_name.unlink()  # remove tempfile, will be reused below


        cv2.imwrite(str(tmpfile_name), sep_image, [cv2.IMWRITE_JPEG_QUALITY, 90])

        sep_file = Path('blobs_cv2.jpg')

        shutil.copy2(f_tmpfile.name, str(sep_file))  # copy file in place
        sep_file.chmod(0o644)



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

