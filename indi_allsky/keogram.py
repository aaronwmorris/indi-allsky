import cv2
import numpy
import math
import time
from pprint import pformat


import multiprocessing

logger = multiprocessing.get_logger()


class KeogramGenerator(object):
    def __init__(self, config, file_list):
        self.config = config
        self.file_list = file_list

        self._angle = int(self.config['KEOGRAM_ANGLE'])

        self.original_width = None
        self.original_height = None

        self.rotated_width = None
        self.rotated_height = None


    @property
    def angle(self):
        return self._angle

    @angle.setter
    def angle(self, new_angle):
        self._angle = int(new_angle)


    def generate(self, outfile):
        # Exclude empty files
        file_list_nonzero = filter(lambda p: p.stat().st_size != 0, self.file_list)

        # Sort by timestamp
        file_list_ordered = sorted(file_list_nonzero, key=lambda p: p.stat().st_mtime)


        # We do not know the array dimensions until the first image is rotated
        keogram_data = None

        processing_start = time.time()

        for filename in file_list_ordered:
            logger.info('Reading file: %s', filename)
            image = cv2.imread(str(filename), cv2.IMREAD_UNCHANGED)

            if isinstance(image, type(None)):
                logger.error('Unable to read %s', filename)
                continue


            height, width = image.shape[:2]
            self.original_height = height
            self.original_width = width


            rotated_image = self.rotate(image)
            del image


            rot_height, rot_width = rotated_image.shape[:2]
            self.rotated_height = rot_height
            self.rotated_width = rot_width

            rotated_center_line = rotated_image[:, [int(rot_width / 2)]]

            if isinstance(keogram_data, type(None)):
                new_shape = rotated_center_line.shape
                logger.info('New Shape: %s', pformat(new_shape))

                new_dtype = rotated_center_line.dtype
                logger.info('New dtype: %s', new_dtype)

                keogram_data = numpy.empty(new_shape, dtype=new_dtype)

            keogram_data = numpy.append(keogram_data, rotated_center_line, 1)

            del rotated_image


        processing_elapsed_s = time.time() - processing_start
        logger.info('Images processed for keogram in %0.1f s', processing_elapsed_s)

        keogram_trimmed = self.trimEdges(keogram_data)

        logger.warning('Creating keogram: %s', outfile)
        cv2.imwrite(str(outfile), keogram_trimmed, [cv2.IMWRITE_JPEG_QUALITY, self.config['IMAGE_FILE_COMPRESSION'][self.config['IMAGE_FILE_TYPE']]])


    def rotate(self, image):
            height, width = image.shape[:2]
            center = (width / 2, height / 2)

            rot = cv2.getRotationMatrix2D(center, self._angle, 1.0)

            abs_cos = abs(rot[0, 0])
            abs_sin = abs(rot[0, 1])

            bound_w = int(height * abs_sin + width * abs_cos)
            bound_h = int(height * abs_cos + width * abs_sin)

            rot[0, 2] += bound_w / 2 - center[0]
            rot[1, 2] += bound_h / 2 - center[1]

            rotated = cv2.warpAffine(image, rot, (bound_w, bound_h))

            return rotated


    def trimEdges(self, image):
        # if the rotation angle exceeds the diagonal angle of the original image, use the height as the hypotenuse
        switch_angle = 90 - math.degrees(math.atan(self.original_height / self.original_width))
        logger.info('Switch angle: %0.2f', switch_angle)


        angle_180_r = abs(self._angle) % 180
        if angle_180_r > 90:
            angle_90_r = 90 - (abs(self._angle) % 90)
        else:
            angle_90_r = abs(self._angle) % 90


        if angle_90_r < switch_angle:
            hyp_1 = self.original_width
            c_angle = angle_90_r
        else:
            hyp_1 = self.original_height
            c_angle = 90 - angle_90_r


        logger.info('Trim angle: %d', c_angle)

        height, width = image.shape[:2]
        logger.info('Keogram dimensions: %d x %d', width, height)
        logger.info('Original image dimensions: %d x %d', self.original_width, self.original_height)
        logger.info('Original rotated image dimensions: %d x %d', self.rotated_width, self.rotated_height)


        adj_1 = math.cos(math.radians(c_angle)) * hyp_1
        adj_2 = int(adj_1 - (self.rotated_width / 2))

        trim_height = int(math.tan(math.radians(c_angle)) * adj_2)
        logger.info('Trim height: %d', trim_height)


        x1 = 0
        y1 = trim_height
        x2 = width
        y2 = height - trim_height

        logger.info('Calculated trimmed area: (%d, %d) (%d, %d)', x1, y1, x2, y2)
        trimmed_image = image[
            y1:y2,
            x1:x2,
        ]

        trimmed_height, trimmed_width = trimmed_image.shape[:2]
        logger.info('New trimmed image: %d x %d', trimmed_width, trimmed_height)

        return trimmed_image


