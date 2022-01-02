#!/usr/bin/env python3

import cv2
import numpy
import argparse
import logging
import time
from pathlib import Path
#from pprint import pformat


logging.basicConfig(level=logging.INFO)
logger = logging


class StarTrailGenerator(object):

    def __init__(self):
        self._max_brightness = 50
        self._mask_threshold = 190
        self._pixel_cutoff_threshold = 1.0

        self.trail_image = None
        self.trail_count = 0
        self.pixels_cutoff = None
        self.excluded_images = 0

        self.image_processing_elapsed_s = 0


    @property
    def max_brightness(self):
        return self._max_brightness

    @max_brightness.setter
    def max_brightness(self, new_max):
        self._max_brightness = new_max

    @property
    def mask_threshold(self):
        return self._mask_threshold

    @mask_threshold.setter
    def mask_threshold(self, new_thold):
        self._mask_threshold = new_thold

    @property
    def pixel_cutoff_threshold(self):
        return self._pixel_cutoff_threshold

    @pixel_cutoff_threshold.setter
    def pixel_cutoff_threshold(self, new_thold):
        self._pixel_cutoff_threshold = new_thold


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

            self.processImage(filename, image)


        try:
            self.finalize(outfile)
        except InsufficentData as e:
            logger.error('Error generating star trail: %s', str(e))


        processing_elapsed_s = time.time() - processing_start
        logger.warning('Total star trail processing in %0.1f s', processing_elapsed_s)


    def processImage(self, filename, image):
        image_processing_start = time.time()

        if isinstance(self.trail_image, type(None)):
            image_height, image_width = image.shape[:2]

            self.pixels_cutoff = (image_height * image_width) * (self._pixel_cutoff_threshold / 100)

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
        if m_avg > self._max_brightness:
            logger.warning(' Excluding image due to brightness: %0.2f', m_avg)
            self.excluded_images += 1
            return

        #logger.info(' Image brightness: %0.2f', m_avg)

        pixels_above_cutoff = (image_gray > self._mask_threshold).sum()
        if pixels_above_cutoff > self.pixels_cutoff:
            logger.warning(' Excluding image due to pixel cutoff: %d', pixels_above_cutoff)
            self.excluded_images += 1
            return

        self.trail_count += 1

        ### Here is the magic
        self.trail_image = cv2.max(self.trail_image, image)

        self.image_processing_elapsed_s += time.time() - image_processing_start


    def finalize(self, outfile):
        logger.warning('Star trails images processed in %0.1f s', self.image_processing_elapsed_s)
        logger.warning('Excluded %d images', self.excluded_images)


        if self.trail_count < 20:
            raise InsufficentData('Not enough images found to build star trail')


        logger.warning('Creating %s', outfile)
        cv2.imwrite(str(outfile), self.trail_image, [cv2.IMWRITE_JPEG_QUALITY, 90])


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


class InsufficentData(Exception):
    pass


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
    argparser.add_argument(
        '--mask_threshold',
        '-m',
        help='mask threshold',
        type=int,
        default=190,
    )
    argparser.add_argument(
        '--pixel_cutoff_threshold',
        '-p',
        help='pixel cutoff threshold percentage',
        type=float,
        default=1.0,
    )


    args = argparser.parse_args()

    sg = StarTrailGenerator()
    sg.max_brightness = args.max_brightness
    sg.mask_threshold = args.mask_threshold
    sg.pixel_cutoff_threshold = args.pixel_cutoff_threshold
    sg.main(args.output, args.inputdir)

