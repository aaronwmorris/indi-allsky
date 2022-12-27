import os
import cv2
import numpy
import time
from pathlib import Path
import tempfile
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

        self._sqm_mask = self._preprocess_mask(mask)

        # this is a default image that is used in case all images are excluded
        self.placeholder_image = None
        self.placeholder_adu = 255


        self._timelapse_frame_count = 0
        self._timelapse_frame_list = list()


        if self.config['IMAGE_FOLDER']:
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()


        self.timelapse_tmpdir = tempfile.TemporaryDirectory(dir=self.image_dir, suffix='_startrail_timelapse')
        self.timelapse_tmpdir_p = Path(self.timelapse_tmpdir.name)


    def __del__(self):
        self.cleanup()


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

    @property
    def timelapse_frame_count(self):
        return self._timelapse_frame_count

    @timelapse_frame_count.setter
    def timelapse_frame_count(self, new_frame_count):
        return  # read only

    @property
    def timelapse_frame_list(self):
        return self._timelapse_frame_list

    @timelapse_frame_list.setter
    def timelapse_frame_list(self, new_frame_list):
        return  # read only


    def generate(self, outfile, file_list):
        # Exclude empty files
        file_list_nonzero = filter(lambda p: p.stat().st_size != 0, file_list)

        # Sort by timestamp
        file_list_ordered = sorted(file_list_nonzero, key=lambda p: p.stat().st_mtime)


        processing_start = time.time()

        for file_p in file_list_ordered:
            logger.info('Reading file: %s', file_p)
            image = cv2.imread(str(file_p), cv2.IMREAD_UNCHANGED)

            if isinstance(image, type(None)):
                logger.error('Unable to read %s', file_p)
                continue

            self.processImage(file_p, image)


        self.finalize(outfile)


        processing_elapsed_s = time.time() - processing_start
        logger.warning('Total star trail processing in %0.1f s', processing_elapsed_s)


    def processImage(self, file_p, image):
        image_processing_start = time.time()


        if isinstance(self.trail_image, type(None)):
            image_height, image_width = image.shape[:2]

            self.pixels_cutoff = (image_height * image_width) * (self._pixel_cutoff_threshold / 100)

            # base image is just a black image
            if len(image.shape) == 2:
                self.trail_image = numpy.zeros((image_height, image_width), dtype=numpy.uint8)
            else:
                self.trail_image = numpy.zeros((image_height, image_width, 3), dtype=numpy.uint8)


        if isinstance(self._sqm_mask, type(None)):
            self._generateSqmMask(image)


        # need grayscale image for mask generation
        if len(image.shape) == 2:
            image_gray = image.copy()
        else:
            image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


        m_avg = cv2.mean(image_gray, mask=self._sqm_mask)[0]


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


        # Star trail timelapse processing
        if self.config.get('STARTRAILS_TIMELAPSE', True):
            image_mtime = file_p.stat().st_mtime

            f_tmp_frame = tempfile.NamedTemporaryFile(dir=self.timelapse_tmpdir_p, suffix='.{0:s}'.format(self.config['IMAGE_FILE_TYPE']), delete=False)
            f_tmp_frame.close()

            f_tmp_frame_p = Path(f_tmp_frame.name)

            if self.config['IMAGE_FILE_TYPE'] in ('jpg', 'jpeg'):
                cv2.imwrite(str(f_tmp_frame_p), self.trail_image, [cv2.IMWRITE_JPEG_QUALITY, self.config['IMAGE_FILE_COMPRESSION']['jpg']])
            elif self.config['IMAGE_FILE_TYPE'] in ('png',):
                cv2.imwrite(str(f_tmp_frame_p), self.trail_image, [cv2.IMWRITE_PNG_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION']['png']])
            elif self.config['IMAGE_FILE_TYPE'] in ('tif', 'tiff'):
                cv2.imwrite(str(f_tmp_frame_p), self.trail_image, [cv2.IMWRITE_TIFF_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION']['tif']])
            else:
                raise Exception('Unknown file type: %s', self.config['IMAGE_FILE_TYPE'])

            # put original mtime on file
            os.utime(f_tmp_frame_p, times=(image_mtime, image_mtime))

            self._timelapse_frame_list.append(f_tmp_frame_p)
            self._timelapse_frame_count += 1


        self.image_processing_elapsed_s += time.time() - image_processing_start


    def finalize(self, outfile):
        outfile_p = Path(outfile)

        logger.warning('Star trails images processed in %0.1f s', self.image_processing_elapsed_s)
        logger.warning('Excluded %d images', self.excluded_images)


        if self.trail_count == 0:
            logger.warning('Not enough images found to build star trail, using placeholder image')
            self.trail_image = self.placeholder_image


        write_img_start = time.time()

        logger.warning('Creating star trail: %s', outfile_p)
        if self.config['IMAGE_FILE_TYPE'] in ('jpg', 'jpeg'):
            cv2.imwrite(str(outfile_p), self.trail_image, [cv2.IMWRITE_JPEG_QUALITY, self.config['IMAGE_FILE_COMPRESSION']['jpg']])
        elif self.config['IMAGE_FILE_TYPE'] in ('png',):
            cv2.imwrite(str(outfile_p), self.trail_image, [cv2.IMWRITE_PNG_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION']['png']])
        elif self.config['IMAGE_FILE_TYPE'] in ('tif', 'tiff'):
            cv2.imwrite(str(outfile_p), self.trail_image, [cv2.IMWRITE_TIFF_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION']['tif']])
        else:
            raise Exception('Unknown file type: %s', self.config['IMAGE_FILE_TYPE'])

        write_img_elapsed_s = time.time() - write_img_start
        logger.info('Image compressed in %0.4f s', write_img_elapsed_s)


        # set default permissions
        outfile_p.chmod(0o644)


    def cleanup(self):
        # cleanup the folder
        self.timelapse_tmpdir.cleanup()


    def _generateSqmMask(self, img):
        logger.info('Generating mask based on SQM_ROI')

        image_height, image_width = img.shape[:2]

        # create a black background
        mask = numpy.zeros((image_height, image_width), dtype=numpy.uint8)

        ### Not going to use the user defined SQM_ROI for now
        sqm_roi = self.config.get('SQM_ROI', [])

        try:
            x1 = int(sqm_roi[0] / self.bin_v.value)
            y1 = int(sqm_roi[1] / self.bin_v.value)
            x2 = int(sqm_roi[2] / self.bin_v.value)
            y2 = int(sqm_roi[3] / self.bin_v.value)
        except IndexError:
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

        self._sqm_mask = mask


    def _preprocess_mask(self, mask):
        # If the images were cropped and/or scaled, the mask must have the same
        # dimensions as the images

        if isinstance(mask, type(None)):
            return mask


        # crop mask
        if self.config.get('IMAGE_CROP_ROI'):
            mask = self.crop_mask(mask)


        # scale mask
        if self.config['IMAGE_SCALE'] and self.config['IMAGE_SCALE'] != 100:
            mask = self.scale_mask(mask)

        return mask


    def crop_mask(self, mask):
        # divide the coordinates by binning value
        x1 = int(self.config['IMAGE_CROP_ROI'][0] / self.bin_v.value)
        y1 = int(self.config['IMAGE_CROP_ROI'][1] / self.bin_v.value)
        x2 = int(self.config['IMAGE_CROP_ROI'][2] / self.bin_v.value)
        y2 = int(self.config['IMAGE_CROP_ROI'][3] / self.bin_v.value)


        cropped_mask = mask[
            y1:y2,
            x1:x2,
        ]

        new_height, new_width = cropped_mask.shape[:2]
        logger.info('New cropped mask size: %d x %d', new_width, new_height)

        return cropped_mask


    def scale_mask(self, mask):
        image_height, image_width = mask.shape[:2]

        logger.info('Scaling mask by %d%%', self.config['IMAGE_SCALE'])
        new_width = int(image_width * self.config['IMAGE_SCALE'] / 100.0)
        new_height = int(image_height * self.config['IMAGE_SCALE'] / 100.0)

        logger.info('New mask size: %d x %d', new_width, new_height)

        return cv2.resize(mask, (new_width, new_height), interpolation=cv2.INTER_AREA)

