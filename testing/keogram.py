#!/usr/bin/env python3

import cv2
import numpy
import math
import argparse
import logging
import time
from pathlib import Path
from pprint import pformat


logging.basicConfig(level=logging.INFO)
logger = logging



class KeogramGenerator(object):
    def __init__(self):
        self._angle = 0

        self.original_width = None
        self.original_height = None

        self.rotated_width = None
        self.rotated_height = None


    @property
    def angle(self):
        return self._angle

    @angle.setter
    def angle(self, new_angle):
        self._angle = float(new_angle)



    def main(self, outfile, inputdir):
        file_list = list()
        self.getFolderFilesByExt(inputdir, file_list)

        # Exclude empty files
        file_list_nonzero = filter(lambda p: p.stat().st_size != 0, file_list)

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

            #logger.info('Data: %s', pformat(image))
            height, width = image.shape[:2]
            self.original_height = height
            self.original_width = width

            rotated_image = self.rotate(image)
            del image


            rot_height, rot_width = rotated_image.shape[:2]
            self.rotated_height = rot_height
            self.rotated_width = rot_width

            rotated_center_line = rotated_image[:, [int(rot_width / 2)]]
            #logger.info('Shape: %s', pformat(rotated_center_line.shape))
            #logger.info('Data: %s', pformat(rotated_center_line))
            #logger.info('Size: %s', pformat(rotated_center_line.size))


            if isinstance(keogram_data, type(None)):
                new_shape = rotated_center_line.shape
                logger.info('New Shape: %s', pformat(new_shape))

                new_dtype = rotated_center_line.dtype
                logger.info('New dtype: %s', new_dtype)

                keogram_data = numpy.empty(new_shape, dtype=new_dtype)

            keogram_data = numpy.append(keogram_data, rotated_center_line, 1)

            del rotated_image


        processing_elapsed_s = time.time() - processing_start
        logger.info('Images processed in %0.1f s', processing_elapsed_s)

        #logger.info('Data: %s', pformat(keogram_data))

        trimmed_keogram = self.trimEdges(keogram_data)

        logger.warning('Creating %s', outfile)
        cv2.imwrite(outfile, keogram_data, [cv2.IMWRITE_JPEG_QUALITY, 90])

        logger.warning('Creating trim_%s', outfile)
        cv2.imwrite('trim_{0:s}'.format(outfile), trimmed_keogram, [cv2.IMWRITE_JPEG_QUALITY, 90])


    def rotate(self, image):
            height, width = image.shape[:2]
            center = (width / 2, height / 2)

            rot = cv2.getRotationMatrix2D(center, self._angle, 1.0)
            #bbox = cv2.boundingRect2f((0, 0), image.size(), self._angle)

            #rot[0, 2] += bbox.width / 2.0 - image.cols / 2.0
            #rot[1, 2] += bbox.height / 2.0 - imagesrc.rows / 2.0

            abs_cos = abs(rot[0, 0])
            abs_sin = abs(rot[0, 1])

            bound_w = int(height * abs_sin + width * abs_cos)
            bound_h = int(height * abs_cos + width * abs_sin)

            rot[0, 2] += bound_w / 2 - center[0]
            rot[1, 2] += bound_h / 2 - center[1]

            #rotated = cv2.warpAffine(image, rot, bbox.size())
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
        '--angle',
        '-a',
        help='angle',
        type=int,
        default=45,
    )


    args = argparser.parse_args()

    kg = KeogramGenerator()
    kg.angle = args.angle
    kg.main(args.output, args.inputdir)

