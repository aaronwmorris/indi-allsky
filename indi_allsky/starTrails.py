import cv2
import numpy
import time
import logging

logger = logging.getLogger('indi_allsky')



class StarTrailGenerator(object):

    def __init__(self, config, bin_v, mask=None):
        self.config = config
        self.bin_v = bin_v

        self._max_brightness = 50
        self._mask_threshold = 190
        self._pixel_cutoff_threshold = 1.0

        self.trail_image = None
        self.trail_count = 0
        self.pixels_cutoff = None
        self.excluded_images = 0

        self.image_processing_elapsed_s = 0

        self._adu_mask = mask

        # this is a default image that is used in case all images are excluded
        self.placeholder_image = None
        self.placeholder_adu = 255


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

            self.pixels_cutoff = (image_height * image_width) * (self._pixel_cutoff_threshold / 100)

            # base image is just a black image
            if len(image.shape) == 2:
                self.trail_image = numpy.zeros((image_height, image_width), dtype=numpy.uint8)
            else:
                self.trail_image = numpy.zeros((image_height, image_width, 3), dtype=numpy.uint8)


        if isinstance(self._adu_mask, type(None)):
            self._generateAduMask(image)


        # need grayscale image for mask generation
        if len(image.shape) == 2:
            image_gray = image.copy()
        else:
            image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


        m_avg = cv2.mean(image_gray, mask=self._adu_mask)[0]


        if m_avg < self.placeholder_adu:
            # placeholder should be the image with the lowest calculated ADU
            self.placeholder_image = image
            self.placeholder_adu = m_avg


        if m_avg > self._max_brightness:
            #logger.warning(' Excluding image due to brightness: %0.2f', m_avg)
            self.excluded_images += 1
            return

        #logger.info(' Image brightness: %0.2f', m_avg)

        pixels_above_cutoff = (image_gray > self._mask_threshold).sum()
        if pixels_above_cutoff > self.pixels_cutoff:
            #logger.warning(' Excluding image due to pixel cutoff: %d', pixels_above_cutoff)
            self.excluded_images += 1
            return

        self.trail_count += 1

        ### Here is the magic
        self.trail_image = cv2.max(self.trail_image, image)

        self.image_processing_elapsed_s += time.time() - image_processing_start


    def finalize(self, outfile):
        logger.warning('Star trails images processed in %0.1f s', self.image_processing_elapsed_s)
        logger.warning('Excluded %d images', self.excluded_images)


        if self.trail_count == 0:
            logger.warning('Not enough images found to build star trail, using placeholder image')
            self.trail_image = self.placeholder_image


        write_img_start = time.time()

        logger.warning('Creating star trail: %s', outfile)
        if self.config['IMAGE_FILE_TYPE'] in ('jpg', 'jpeg'):
            cv2.imwrite(str(outfile), self.trail_image, [cv2.IMWRITE_JPEG_QUALITY, self.config['IMAGE_FILE_COMPRESSION']['jpg']])
        elif self.config['IMAGE_FILE_TYPE'] in ('png',):
            cv2.imwrite(str(outfile), self.trail_image, [cv2.IMWRITE_PNG_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION']['png']])
        elif self.config['IMAGE_FILE_TYPE'] in ('tif', 'tiff'):
            cv2.imwrite(str(outfile), self.trail_image, [cv2.IMWRITE_TIFF_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION']['tif']])
        else:
            raise Exception('Unknown file type: %s', self.config['IMAGE_FILE_TYPE'])

        write_img_elapsed_s = time.time() - write_img_start
        logger.info('Image compressed in %0.4f s', write_img_elapsed_s)


    def _generateAduMask(self, img):
        logger.info('Generating mask based on SQM_ROI')

        image_height, image_width = img.shape[:2]

        # create a black background
        mask = numpy.zeros((image_height, image_width), dtype=numpy.uint8)

        ### Not going to use the user defined ADU_ROI for now
        #adu_roi = self.config.get('ADU_ROI', [])

        #try:
        #    x1 = int(adu_roi[0] / self.bin_v.value)
        #    y1 = int(adu_roi[1] / self.bin_v.value)
        #    x2 = int(adu_roi[2] / self.bin_v.value)
        #    y2 = int(adu_roi[3] / self.bin_v.value)
        #except IndexError:

        logger.warning('Using central ROI for ADU mask')
        x1 = int((image_width / 2) - (image_width / 3))
        y1 = int((image_height / 2) - (image_height / 3))
        x2 = int((image_width / 2) + (image_width / 3))
        y2 = int((image_height / 2) + (image_height / 3))

        # The white area is what we keep
        cv2.rectangle(
            img=mask,
            pt1=(x1, y1),
            pt2=(x2, y2),
            color=(255),  # mono
            thickness=cv2.FILLED,
        )

        self._adu_mask = mask

