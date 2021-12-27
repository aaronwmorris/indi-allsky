#!/usr/bin/env python3

import cv2
import numpy
#import math
import argparse
import logging
import time
#from datetime import datetime
from pathlib import Path
#from pprint import pformat


logging.basicConfig(level=logging.INFO)
logger = logging



class StartrailGenerator(object):

    def __init__(self, max_brightness):
        self.max_brightness = max_brightness

        self.trail_image = None

        self.background_image = None
        self.background_image_brightness = 255
        self.background_image_min_brightness = 10

        self.image_processing_elapsed_s = 0


    def main(self, outfile, inputdir):
        file_list = list()
        self.getFolderFilesByExt(inputdir, file_list)

        # Exclude empty files
        file_list_nonzero = filter(lambda p: p.stat().st_size != 0, file_list)

        # Sort by timestamp
        file_list_ordered = sorted(file_list_nonzero, key=lambda p: p.stat().st_mtime)


        processing_start = time.time()

        for filename in file_list_ordered:
            logger.info('Reading file: %s', filename)
            image = cv2.imread(str(filename), cv2.IMREAD_UNCHANGED)

            if isinstance(image, type(None)):
                logger.error('Unable to read %s', filename)
                continue

            self.processImage(image)


        self.finalize(outfile)


        logger.warning('Images processed in %0.1f s', self.image_processing_elapsed_s)


        processing_elapsed_s = time.time() - processing_start
        logger.warning('Total processing in %0.1f s', processing_elapsed_s)


    def processImage(self, image):

        image_processing_start = time.time()

        if isinstance(self.trail_image, type(None)):
            image_height, image_width = image.shape[:2]

            # base image is just a black image
            if len(image.shape) == 2:
                self.trail_image = numpy.zeros((image_height, image_width), dtype=numpy.uint8)
            else:
                self.trail_image = numpy.zeros((image_height, image_width, 3), dtype=numpy.uint8)


        # need grayscale image for mask generation
        if len(image.shape) == 2:
            image_gray = image.copy()
        else:
            image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        m_avg = cv2.mean(image_gray)[0]
        if m_avg > self.max_brightness:
            logger.warning(' Excluding image due to brightness: %0.2f', m_avg)
            return

        #logger.info(' Image brightness: %0.2f', m_avg)

        if m_avg < self.background_image_brightness and m_avg > self.background_image_min_brightness:
            # try to exclude images that are too dark
            logger.info('Found new background candidate: score %0.2f', m_avg)
            self.background_image_brightness = m_avg  # new low score
            self.background_image = image  # image with the lowest score will be the permanent background


        ret, mask = cv2.threshold(image_gray, 127, 255, cv2.THRESH_BINARY)
        mask_inv = cv2.bitwise_not(mask)


        # Now black-out the area of stars in the background
        bg_masked = cv2.bitwise_and(self.trail_image, self.trail_image, mask=mask_inv)

        # Take only stars of original image
        stars_masked = cv2.bitwise_and(image, image, mask=mask)

        # Put stars on background
        self.trail_image = cv2.add(bg_masked, stars_masked)

        self.image_processing_elapsed_s += time.time() - image_processing_start


    def finalize(self, outfile):
        # need grayscale image for mask generation
        if len(self.trail_image.shape) == 2:
            base_image_gray = self.trail_image.copy()
        else:
            base_image_gray = cv2.cvtColor(self.trail_image, cv2.COLOR_BGR2GRAY)


        ret, mask = cv2.threshold(base_image_gray, 10, 255, cv2.THRESH_BINARY)
        mask_inv = cv2.bitwise_not(mask)


        # Now black-out the area of stars in the background
        bg_masked = cv2.bitwise_and(self.background_image, self.background_image, mask=mask_inv)

        # Take only stars of original image
        stars_masked = cv2.bitwise_and(self.trail_image, self.trail_image, mask=mask)

        # Put stars on background
        final_image = cv2.add(bg_masked, stars_masked)


        logger.warning('Creating %s', outfile)
        cv2.imwrite(outfile, final_image, [cv2.IMWRITE_JPEG_QUALITY, 90])


    def getFolderFilesByExt(self, folder, file_list, extension_list=None):
        if not extension_list:
            extension_list = ['jpg']

        logger.info('Searching for image files in %s', folder)

        dot_extension_list = ['.{0:s}'.format(e) for e in extension_list]

        for item in Path(folder).iterdir():
            if item.is_file() and item.suffix in dot_extension_list:
                file_list.append(item)
            elif item.is_dir():
                self.getFolderFilesByExt(item, file_list, extension_list=extension_list)  # recursion


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'inputdir',
        help='Input directory',
        type=str,
    )
    argparser.add_argument(
        '--output',
        '-o',
        help='output',
        type=str,
        required=True,
    )
    argparser.add_argument(
        '--max_brightness',
        '-l',
        help='max brightness limit',
        type=int,
        default=50,
    )


    args = argparser.parse_args()

    kg = StartrailGenerator(args.max_brightness)
    kg.main(args.output, args.inputdir)

