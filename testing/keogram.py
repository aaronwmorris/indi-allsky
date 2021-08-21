#!/usr/bin/env python3

import cv2
import numpy
import sys
import copy
import argparse
import logging
from pprint import pformat

ANGLE = 80


logging.basicConfig(level=logging.INFO)
logger = logging



class KeogramBuilder(object):
    def __init__(self):
        pass


    def main(self, outfile, inputfiles):
        # We do not know the array dimensions until the first image is rotated
        keogram_data = False

        for filename in inputfiles:
            logger.info('Reading file: %s', filename)
            image = cv2.imread(filename, cv2.IMREAD_UNCHANGED)
            #logger.info('Data: %s', pformat(image))

            rotated_image = self.rotate(image, ANGLE)
            del image


            rot_height, rot_width = rotated_image.shape[:2]

            rotated_center_line = rotated_image[:, [int(rot_width/2)]]
            #logger.info('Shape: %s', pformat(rotated_center_line.shape))
            #logger.info('Data: %s', pformat(rotated_center_line))
            #logger.info('Size: %s', pformat(rotated_center_line.size))


            if type(keogram_data) is bool:
                new_shape = rotated_center_line.shape
                logger.info('New Shape: %s', pformat(new_shape))

                new_dtype = rotated_center_line.dtype
                logger.info('New dtype: %s', new_dtype)

                keogram_data = numpy.empty(new_shape, dtype=new_dtype)

            keogram_data = numpy.append(keogram_data, rotated_center_line, 1)


        #logger.info('Data: %s', pformat(keogram_data))

        logger.warning('Creating %s', outfile)
        cv2.imwrite(outfile, keogram_data, [cv2.IMWRITE_JPEG_QUALITY, 90])


    def rotate(self, image, angle):
            height, width = image.shape[:2]
            center = (width/2, height/2)

            rot = cv2.getRotationMatrix2D(center, ANGLE, 1.0)
            #bbox = cv2.boundingRect2f((0, 0), image.size(), ANGLE)

            #rot[0, 2] += bbox.width/2.0 - image.cols/2.0
            #rot[1, 2] += bbox.height/2.0 - imagesrc.rows/2.0

            abs_cos = abs(rot[0,0])
            abs_sin = abs(rot[0,1])

            bound_w = int(height * abs_sin + width * abs_cos)
            bound_h = int(height * abs_cos + width * abs_sin)

            rot[0, 2] += bound_w/2 - center[0]
            rot[1, 2] += bound_h/2 - center[1]

            #rotated = cv2.warpAffine(image, rot, bbox.size())
            rotated = cv2.warpAffine(image, rot, (bound_w, bound_h))

            return rotated




if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'inputfiles',
        help='Input files',
        metavar='I',
        type=str,
        nargs='+'
    )
    argparser.add_argument(
        '--output',
        '-o',
        help='output',
        type=str,
        required=True,
    )

    args = argparser.parse_args()

    kb = KeogramBuilder()
    kb.main(args.output, args.inputfiles)

