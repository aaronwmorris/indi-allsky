#!/usr/bin/env python3

import cv2
import numpy
import PIL
from PIL import Image
import argparse
import logging
import time
from pathlib import Path
from datetime import datetime
from datetime import timezone
import math
import ephem
#from pprint import pformat


logging.basicConfig(level=logging.INFO)
logger = logging


class StarTrailGenerator(object):

    _distanceThreshold = 10


    def __init__(self):
        self._max_adu = 65
        self._mask_threshold = 190
        self._pixel_cutoff_threshold = 1.0

        self._min_stars = 0
        self._detectionThreshold = 0.6

        self._latitude = 0.0
        self._longitude = 0.0
        self._sun_alt_threshold = -15.0
        self._moon_alt_threshold = 0.0
        self._moon_phase_threshold = 33.0

        self.original_height = None
        self.original_width = None

        self.trail_image = None
        self.pixels_cutoff = None
        self.excluded_images = {
            'adu'       : 0,
            'sun_alt'   : 0,
            'moon_mode' : 0,  # not in test
            'moon_alt'  : 0,
            'stars'     : 0,
            'pixels'    : 0,
        }


        self._trail_count = 0

        self.image_processing_elapsed_s = 0

        self._sqm_mask = None


        self.obs = ephem.Observer()
        self.sun = ephem.Sun()
        self.moon = ephem.Moon()


        # disable atmospheric refraction calcs
        self.obs.pressure = 0


        # start with a black image
        star_template = numpy.zeros([15, 15], dtype=numpy.uint8)

        # draw a white circle
        cv2.circle(
            img=star_template,
            center=(7, 7),
            radius=3,
            color=(255, 255, 255),
            thickness=cv2.FILLED,
        )

        # blur circle to simulate a star
        self.star_template = cv2.blur(
            src=star_template,
            ksize=(2, 2),
        )

        self.star_template_w, self.star_template_h = self.star_template.shape[::-1]



    @property
    def max_adu(self):
        return self._max_adu

    @max_adu.setter
    def max_adu(self, new_max_adu):
        self._max_adu = int(new_max_adu)

    @property
    def mask_threshold(self):
        return self._mask_threshold

    @mask_threshold.setter
    def mask_threshold(self, new_thold):
        self._mask_threshold = int(new_thold)

    @property
    def pixel_cutoff_threshold(self):
        return self._pixel_cutoff_threshold

    @pixel_cutoff_threshold.setter
    def pixel_cutoff_threshold(self, new_thold):
        self._pixel_cutoff_threshold = float(new_thold)

    @property
    def min_stars(self):
        return self._min_stars

    @min_stars.setter
    def min_stars(self, new_min_stars):
        self._min_stars = int(new_min_stars)

    @property
    def trail_count(self):
        return self._trail_count

    @property
    def latitude(self):
        return self._latitude

    @latitude.setter
    def latitude(self, new_latitude):
        self._latitude = float(new_latitude)
        self.obs.lat = math.radians(self._latitude)

    @property
    def longitude(self):
        return self._longitude

    @longitude.setter
    def longitude(self, new_longitude):
        self._longitude = float(new_longitude)
        self.obs.lon = math.radians(self._longitude)

    @property
    def sun_alt_threshold(self):
        return self._sun_alt_threshold

    @sun_alt_threshold.setter
    def sun_alt_threshold(self, new_sun_alt_threshold):
        self._sun_alt_threshold = float(new_sun_alt_threshold)

    @property
    def moon_alt_threshold(self):
        return self._moon_alt_threshold

    @moon_alt_threshold.setter
    def moon_alt_threshold(self, new_moon_alt_threshold):
        self._moon_alt_threshold = float(new_moon_alt_threshold)

    @property
    def moon_phase_threshold(self):
        return self._moon_phase_threshold

    @moon_phase_threshold.setter
    def moon_phase_threshold(self, new_moon_phase_threshold):
        self._moon_phase_threshold = float(new_moon_phase_threshold)



    def main(self, outfile, inputdir):
        logger.warning('Max ADU: %d', self.max_adu)
        logger.warning('Mask threshold: %d', self.mask_threshold)
        logger.warning('Mask threshold %%: %0.1f', self.pixel_cutoff_threshold)
        logger.warning('Min stars: %d', self.min_stars)
        logger.warning('Latitude configured for %0.1f', self.latitude)
        logger.warning('Longitude configured for %0.1f', self.longitude)
        logger.warning('Sun altitude threshold: %0.1f', self.sun_alt_threshold)
        logger.warning('Moon altitude threshold: %0.1f', self.moon_alt_threshold)
        logger.warning('Moon phase threshold: %0.1f', self.moon_phase_threshold)
        time.sleep(3)

        file_list = list()
        self.getFolderFilesByExt(inputdir, file_list)

        # Exclude empty files
        file_list_nonzero = filter(lambda p: p.stat().st_size != 0, file_list)

        # Sort by timestamp
        file_list_ordered = sorted(file_list_nonzero, key=lambda p: p.stat().st_mtime)


        processing_start = time.time()

        for filename_p in file_list_ordered:
            logger.info('Reading file: %s', filename_p)

            try:
                with Image.open(str(filename_p)) as img:
                    image = cv2.cvtColor(numpy.array(img), cv2.COLOR_RGB2BGR)
            except PIL.UnidentifiedImageError:
                logger.error('Unable to read %s', filename_p)
                continue


            self.processImage(filename_p, image)


        try:
            self.finalize(outfile)
        except InsufficentData as e:
            logger.error('Error generating star trail: %s', str(e))


        processing_elapsed_s = time.time() - processing_start
        logger.warning('Total star trail processing in %0.1f s', processing_elapsed_s)


    def processImage(self, file_p, image):
        image_processing_start = time.time()

        image_height, image_width = image.shape[:2]


        if isinstance(self.trail_image, type(None)):
            # this only happens on the first image

            self.original_height = image_height
            self.original_width = image_width

            self.pixels_cutoff = (image_height * image_width) * (self.pixel_cutoff_threshold / 100)

            # base image is just a black image
            if len(image.shape) == 2:
                self.trail_image = numpy.zeros((image_height, image_width), dtype=numpy.uint8)
            else:
                self.trail_image = numpy.zeros((image_height, image_width, 3), dtype=numpy.uint8)


        if image_height != self.original_height or image_width != self.original_width:
            logger.error('Image with dimension mismatch: %s', file_p)
            return


        if isinstance(self._sqm_mask, type(None)):
            self._generateSqmMask(image)


        # need grayscale image for mask generation
        if len(image.shape) == 2:
            image_gray = image.copy()
        else:
            image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


        mtime_datetime_utc = datetime.fromtimestamp(file_p.stat().st_mtime).astimezone(tz=timezone.utc)
        self.obs.date = mtime_datetime_utc


        self.sun.compute(self.obs)
        sun_alt = math.degrees(self.sun.alt)

        if sun_alt > self.sun_alt_threshold:
            logger.warning(' Excluding image due to sun altitude: %0.1f', sun_alt)
            self.excluded_images['sun_alt'] += 1
            return


        self.moon.compute(self.obs)
        moon_alt = math.degrees(self.moon.alt)
        moon_phase = self.moon.moon_phase * 100.0

        if moon_alt > self.moon_alt_threshold and moon_phase > self.moon_phase_threshold:
            logger.warning(' Excluding image due to moon altitude/phase: %0.1f/%0.1f%%', moon_alt, moon_phase)
            self.excluded_images['moon_alt'] += 1
            return


        m_avg = cv2.mean(image_gray, mask=self._sqm_mask)[0]
        if m_avg > self.max_adu:
            logger.warning(' Excluding image due to brightness: %0.2f', m_avg)
            self.excluded_images['adu'] += 1
            return


        #logger.info(' Image brightness: %0.2f', m_avg)

        pixels_above_cutoff = (image_gray > self.mask_threshold).sum()
        if pixels_above_cutoff > self.pixels_cutoff:
            logger.warning(' Excluding image due to pixel cutoff: %d', pixels_above_cutoff)
            self.excluded_images['pixels'] += 1
            return


        if self.min_stars > 0:
            star_count = len(self.detectObjects(image_gray))

            if star_count < self.min_stars:
                logger.warning(' Excluding image due to stars: %d', star_count)
                self.excluded_images['stars'] += 1
                return


        self._trail_count += 1

        ### Here is the magic
        self.trail_image = cv2.max(self.trail_image, image)

        self.image_processing_elapsed_s += time.time() - image_processing_start


    def finalize(self, outfile):
        logger.info('Star trails images processed in %0.1f s', self.image_processing_elapsed_s)
        logger.info(
            'Excluded %d images - adu: %d, sun alt: %d, moon mode: %d, moon alt: %d, stars: %d, pixels: %d',
            sum(self.excluded_images.values()),
            self.excluded_images['adu'],
            self.excluded_images['sun_alt'],
            self.excluded_images['moon_mode'],
            self.excluded_images['moon_alt'],
            self.excluded_images['stars'],
            self.excluded_images['pixels'],
        )


        if self.trail_count < 20:
            raise InsufficentData('Not enough images found to build star trail')


        logger.warning('Creating %s', outfile)
        trail_image_rgb = Image.fromarray(cv2.cvtColor(self.trail_image, cv2.COLOR_BGR2RGB))
        trail_image_rgb.save(str(outfile), quality=90)


    def detectObjects(self, original_data):
        masked_img = cv2.bitwise_and(original_data, original_data, mask=self._sqm_mask)

        if len(original_data.shape) == 2:
            # gray scale or bayered
            grey_img = masked_img
        else:
            # assume color
            grey_img = cv2.cvtColor(masked_img, cv2.COLOR_BGR2GRAY)


        #sep_start = time.time()


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


        #sep_elapsed_s = time.time() - sep_start
        #logger.info('Star detection in %0.4f s', sep_elapsed_s)

        logger.info('Found %d objects', len(blobs))

        return blobs


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


    def _generateSqmMask(self, img):
        logger.info('Generating mask based on SQM_ROI')

        image_height, image_width = img.shape[:2]

        # create a black background
        mask = numpy.zeros((image_height, image_width), dtype=numpy.uint8)

        logger.warning('Using central ROI for ADU mask')
        x1 = int((image_width / 2) - (image_width / 4))
        y1 = int((image_height / 2) - (image_height / 4))
        x2 = int((image_width / 2) + (image_width / 4))
        y2 = int((image_height / 2) + (image_height / 4))

        # The white area is what we keep
        cv2.rectangle(
            img=mask,
            pt1=(x1, y1),
            pt2=(x2, y2),
            color=(255),  # mono
            thickness=cv2.FILLED,
        )

        self._sqm_mask = mask


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
        '--max_adu',
        '-a',
        help='max brightness limit [default: 65]',
        type=int,
        default=65,
    )
    argparser.add_argument(
        '--min_stars',
        '-s',
        help='minimum stars [default: 0]',
        type=int,
        default=0,
    )
    argparser.add_argument(
        '--mask_threshold',
        '-m',
        help='mask threshold [default: 190]',
        type=int,
        default=190,
    )
    argparser.add_argument(
        '--pixel_cutoff_threshold',
        '-p',
        help='pixel cutoff threshold percentage [default: 1.0]',
        type=float,
        default=1.0,
    )
    argparser.add_argument(
        '--latitude',
        help='latitude',
        type=float,
        required=True,
    )
    argparser.add_argument(
        '--longitude',
        help='longitude',
        type=float,
        required=True,
    )
    argparser.add_argument(
        '--sun_alt_threshold',
        help='sun altitude threshold [default: -15.0]',
        type=float,
        default=-15.0,
    )
    argparser.add_argument(
        '--moon_alt_threshold',
        help='moon altitude threshold [default: 0.0]',
        type=float,
        default=0.0,
    )
    argparser.add_argument(
        '--moon_phase_threshold',
        help='moon phase threshold [default: 33.0]',
        type=float,
        default=33.0,
    )


    args = argparser.parse_args()

    sg = StarTrailGenerator()
    sg.max_adu = args.max_adu
    sg.min_stars = args.min_stars
    sg.mask_threshold = args.mask_threshold
    sg.pixel_cutoff_threshold = args.pixel_cutoff_threshold
    sg.latitude = args.latitude
    sg.longitude = args.longitude
    sg.sun_alt_threshold = args.sun_alt_threshold
    sg.moon_alt_threshold = args.moon_alt_threshold
    sg.moon_phase_threshold = args.moon_phase_threshold

    sg.main(args.output, args.inputdir)

