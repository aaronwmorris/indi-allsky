import cv2
import numpy
import time

import multiprocessing

logger = multiprocessing.get_logger()



class StarTrailGenerator(object):

    def __init__(self, config):
        self.config = config

        self._max_brightness = 50
        self._mask_threshold = 190

        self.trail_image = None

        self.background_image = None
        self.background_image_brightness = 255
        self.background_image_min_brightness = 10

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


    def generate(self, outfile, file_list):
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


        self.finalize(outfile)


        processing_elapsed_s = time.time() - processing_start
        logger.warning('Total star trail processing in %0.1f s', processing_elapsed_s)


    def processImage(self, filename, image):
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
        if m_avg > self._max_brightness:
            logger.warning(' Excluding image due to brightness: %0.2f', m_avg)
            return

        #logger.info(' Image brightness: %0.2f', m_avg)

        if m_avg < self.background_image_brightness and m_avg > self.background_image_min_brightness:
            # try to exclude images that are too dark
            logger.info('Found new background candidate: %s - score %0.2f', filename, m_avg)
            self.background_image_brightness = m_avg  # new low score
            self.background_image = image  # image with the lowest score will be the permanent background


        ret, mask = cv2.threshold(image_gray, self._mask_threshold, 255, cv2.THRESH_BINARY)
        mask_inv = cv2.bitwise_not(mask)


        # Now black-out the area of stars in the background
        bg_masked = cv2.bitwise_and(self.trail_image, self.trail_image, mask=mask_inv)

        # Take only stars of original image
        stars_masked = cv2.bitwise_and(image, image, mask=mask)

        # Put stars on background
        self.trail_image = cv2.add(bg_masked, stars_masked)

        self.image_processing_elapsed_s += time.time() - image_processing_start


    def finalize(self, outfile):
        logger.warning('Star trails images processed in %0.1f s', self.image_processing_elapsed_s)

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


        logger.warning('Creating star trail: %s', outfile)
        cv2.imwrite(str(outfile), final_image, [cv2.IMWRITE_JPEG_QUALITY, self.config['IMAGE_FILE_COMPRESSION'][self.config['IMAGE_FILE_TYPE']]])


