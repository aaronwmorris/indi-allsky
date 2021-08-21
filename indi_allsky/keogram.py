import cv2
import numpy
import time
from pprint import pformat


import multiprocessing

logger = multiprocessing.get_logger()


class KeogramGenerator(object):
    def __init__(self, config, file_list):
        self.config = config
        self.file_list = file_list

        self._angle = int(self.config['KEOGRAM_ANGLE'])


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

            if type(image) is type(None):
                logger.error('Unable to read %s', filename)
                continue


            rotated_image = self.rotate(image)
            del image


            rot_height, rot_width = rotated_image.shape[:2]

            rotated_center_line = rotated_image[:, [int(rot_width/2)]]

            if type(keogram_data) is type(None):
                new_shape = rotated_center_line.shape
                logger.info('New Shape: %s', pformat(new_shape))

                new_dtype = rotated_center_line.dtype
                logger.info('New dtype: %s', new_dtype)

                keogram_data = numpy.empty(new_shape, dtype=new_dtype)

            keogram_data = numpy.append(keogram_data, rotated_center_line, 1)


        processing_elapsed_s = time.time() - processing_start
        logger.info('Images processed for keogram in %0.1f s', processing_elapsed_s)

        logger.warning('Creating keogram: %s', outfile)
        cv2.imwrite(str(outfile), keogram_data, [cv2.IMWRITE_JPEG_QUALITY, self.config['IMAGE_FILE_COMPRESSION'][self.config['IMAGE_FILE_TYPE']]])


    def rotate(self, image):
            height, width = image.shape[:2]
            center = (width/2, height/2)

            rot = cv2.getRotationMatrix2D(center, self._angle, 1.0)

            abs_cos = abs(rot[0,0])
            abs_sin = abs(rot[0,1])

            bound_w = int(height * abs_sin + width * abs_cos)
            bound_h = int(height * abs_cos + width * abs_sin)

            rot[0, 2] += bound_w/2 - center[0]
            rot[1, 2] += bound_h/2 - center[1]

            rotated = cv2.warpAffine(image, rot, (bound_w, bound_h))

            return rotated



