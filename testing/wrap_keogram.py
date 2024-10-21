#!/usr/bin/env python3

#import math
import numpy
import cv2
import logging


IMAGE_CIRCLE = 1650


logging.basicConfig(level=logging.INFO)
logger = logging


class WrapKeogram(object):

    def main(self):
        image = cv2.imread('image.jpg', cv2.IMREAD_UNCHANGED)
        image_height, image_width = image.shape[:2]
        logger.info('Image: %d x %d', image_width, image_height)

        keogram = cv2.imread('keogram.jpg', cv2.IMREAD_UNCHANGED)
        keogram_height, keogram_width = keogram.shape[:2]
        logger.info('Keogram: %d x %d', keogram_width, keogram_height)


        if image_width < (IMAGE_CIRCLE + (keogram_height * 2)):
            final_width = IMAGE_CIRCLE + (keogram_height * 2)
        else:
            final_width = image_width

        if image_height < (IMAGE_CIRCLE + (keogram_height * 2)):
            final_height = IMAGE_CIRCLE + (keogram_height * 2)
        else:
            final_height = image_height

        logger.info('Final: %d x %d', final_width, final_height)


        # add black area at the top of the keogram to wrap around center
        d_keogram = numpy.zeros([int((IMAGE_CIRCLE + keogram_height) / 2), keogram_width, 3], dtype=numpy.uint8)
        d_height, d_width = d_keogram.shape[:2]
        d_keogram[d_height - keogram_height:d_height, 0:keogram_width] = keogram


        # add alpha channel for transparency (black area)
        d_keogram_alpha = numpy.zeros([d_height, d_width], dtype=numpy.uint8)
        d_keogram_alpha[d_height - keogram_height:d_height, 0:keogram_width] = 255
        d_keogram = numpy.dstack((d_keogram, d_keogram_alpha))


        d_image = cv2.rotate(d_keogram, cv2.ROTATE_90_COUNTERCLOCKWISE)


        # wrap the keogram (square output so it can be rotated)
        wrapped_height, wrapped_width = IMAGE_CIRCLE + (keogram_height * 2), IMAGE_CIRCLE + (keogram_height * 2)
        wrapped_keogram = cv2.warpPolar(
            d_image,
            (wrapped_width, wrapped_height),
            (int(wrapped_height / 2), int(wrapped_height / 2)),
            int(wrapped_height / 2),
            cv2.WARP_INVERSE_MAP,
        )

        #wrapped_keogram = cv2.rotate(wrapped_keogram, cv2.ROTATE_90_COUNTERCLOCKWISE)  # start keogram at top
        wrapped_keogram = cv2.rotate(wrapped_keogram, cv2.ROTATE_90_CLOCKWISE)  # start keogram at bottom


        # separate layers
        wrapped_keogram_bgr = wrapped_keogram[:, :, :3]
        wrapped_keogram_alpha = (wrapped_keogram[:, :, 3] / 255).astype(numpy.float32)

        # create alpha mask
        alpha_mask = numpy.dstack((
            wrapped_keogram_alpha,
            wrapped_keogram_alpha,
            wrapped_keogram_alpha,
        ))


        f_image = numpy.zeros([final_height, final_width, 3], dtype=numpy.uint8)
        f_image[
            int((final_height / 2) - (image_height / 2)):int((final_height / 2) + (image_height / 2)),
            int((final_width / 2) - (image_width / 2)):int((final_width / 2) + (image_width / 2)),
        ] = image


        # apply alpha mask
        image_with_keogram = (f_image * (1 - alpha_mask) + wrapped_keogram_bgr * alpha_mask).astype(numpy.uint8)


        cv2.imwrite('wrapped.jpg', image_with_keogram, [cv2.IMWRITE_JPEG_QUALITY, 90])


if __name__ == "__main__":
    WrapKeogram().main()

