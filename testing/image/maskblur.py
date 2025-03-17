#!/usr/bin/env python3

import cv2
import numpy
import sys
import argparse
import time
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging


class MaskBlur(object):
    def __init__(self):
        pass

    def main(self, image_file, mask_file):
        image_file_p = Path(image_file)
        mask_file_p = Path(mask_file)

        if not image_file_p.exists():
            logger.error('Image does not exist: %s', image_file_p)
            sys.exit(1)

        if not mask_file_p.exists():
            logger.error('Mask does not exist: %s', mask_file_p)
            sys.exit(1)

        image = cv2.imread(str(image_file_p), cv2.IMREAD_UNCHANGED)
        mask = cv2.imread(str(mask_file_p), cv2.IMREAD_GRAYSCALE)
        #mask = cv2.imread(str(mask_file_p), cv2.IMREAD_COLOR)


        ### set all compression artifacts to black
        #mask[mask < 255] = 0  # did not quite work


        start = time.time()

        #image_height, image_width = image.shape[:2]

        #mask = numpy.zeros((image_height, image_width), dtype=numpy.uint8)

        #x1 = int((image_width / 2) - (image_width / 4))
        #y1 = int((image_height / 2) - (image_height / 4))
        #x2 = int((image_width / 2) + (image_width / 4))
        #y2 = int((image_height / 2) + (image_height / 4))

        #cv2.rectangle(
        #    img=mask,
        #    pt1=(x1, y1),
        #    pt2=(x2, y2),
        #    color=(255),  # mono
        #    thickness=cv2.FILLED,
        #)

        blur_mask = cv2.blur(mask, (75, 75), cv2.BORDER_DEFAULT)

        color_mask = cv2.cvtColor(blur_mask, cv2.COLOR_GRAY2BGR)
        #color_mask = blur_mask

        gradient_mask = color_mask / 255


        masked_image = (image * gradient_mask).astype(numpy.uint8)
        #masked_image = cv2.multiply(image, gradient_mask)
        #masked_image = cv2.bitwise_and(image, image, mask=mask)


        elapsed_s = time.time() - start
        logger.warning('Time: %0.4fs', elapsed_s)


        cv2.imwrite('blur.jpg', masked_image, [cv2.IMWRITE_JPEG_QUALITY, 90])


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'image',
        help='Input image',
        type=str,
    )
    argparser.add_argument(
        'mask',
        help='Mask image',
        type=str,
    )

    args = argparser.parse_args()

    mb = MaskBlur()
    mb.main(args.image, args.mask)

