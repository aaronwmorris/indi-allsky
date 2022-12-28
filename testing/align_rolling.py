#!/usr/bin/env python3

import time
from pathlib import Path
import argparse
import cv2
import numpy
from astropy.io import fits
import astroalign
import logging


logging.basicConfig(level=logging.INFO)
logger = logging


class AlignRolling(object):
    def __init__(self, method, output_dir):
        self.method = method
        self.output_dir_p = Path(output_dir)

        self.transform = None

        self.stack_count = 10
        self.split_screen = True

        self.image_list = list()

        if not self.output_dir_p.is_dir():
            raise Exception('%s is not a folder', self.output_dir_p)


    def main(self, inputfiles):
        file_list = sorted([Path(x) for x in inputfiles], key=lambda p: p.stat().st_mtime)

        i = 0
        for fit in file_list:
            self.add(fit)

            if len(self.image_list) != self.stack_count:
                # fill up the list
                continue


            start = time.time()


            reference_hdulist = self.image_list[0]
            reg_list = [reference_hdulist[0].data]  # add reference to list

            ref_crop = self._crop(reference_hdulist[0].data)


            for hdulist in self.image_list[1:]:
                # detection_sigma default = 5
                # max_control_points default = 50
                # min_area default = 5

                reg_start = time.time()


                try:
                    ### Reusing the tranform does not appear to work
                    #if isinstance(self.transform, type(None)):
                    #    self.transform, (source_list, target_list) = astroalign.find_transform(
                    #        hdulist[0],
                    #        reference_hdulist[0],
                    #        detection_sigma=7,
                    #        max_control_points=100,
                    #        min_area=15,
                    #    )

                    ### Find transform using a crop of the image
                    hdu_crop = self._crop(hdulist[0].data)
                    self.transform, (source_list, target_list) = astroalign.find_transform(
                        hdu_crop,
                        ref_crop,
                        detection_sigma=5,
                        max_control_points=150,
                        min_area=15,
                    )


                    logger.info(
                        'Registration Matches: %d, Rotation: %0.6f, Translation: (%0.6f, %0.6f), Scale: %0.6f',
                        len(target_list),
                        self.transform.rotation,
                        self.transform.translation[0], self.transform.translation[1],
                        self.transform.scale,
                    )


                    ### Apply transform
                    reg_image, footprint = astroalign.apply_transform(
                        self.transform,
                        hdulist[0],
                        reference_hdulist[0],
                    )


                    ## Register full image
                    #reg_image, footprint = astroalign.register(
                    #    hdulist[0],
                    #    reference_hdulist[0],
                    #    detection_sigma=5,
                    #    max_control_points=150,
                    #    min_area=15,
                    #)
                except astroalign.MaxIterError as e:
                    logger.error('Error registering: %s', str(e))
                    continue

                reg_elapsed_s = time.time() - reg_start
                logger.info('Image registered in %0.4f s', reg_elapsed_s)


                reg_list.append(reg_image)



            stacker = ImageStacker()
            stacker_method = getattr(stacker, self.method)

            stacked_img = stacker_method(reg_list, numpy.uint16)

            elapsed_s = time.time() - start
            logger.info('Images aligned in %0.4f s', elapsed_s)


            if self.split_screen:
                stacked_img = self._splitscreen(reference_hdulist[0].data, stacked_img)


            stacked_bitdepth = self._detectBitDepth(stacked_img)
            stacked_img_8bit = self._convert_16bit_to_8bit(stacked_img, 16, stacked_bitdepth)


            out_file = self.output_dir_p.joinpath('{0:05d}.png'.format(i))
            #cv2.imwrite(str(out_file), stacked_img_8bit, [cv2.IMWRITE_JPEG_QUALITY, 90])
            cv2.imwrite(str(out_file), stacked_img_8bit, [cv2.IMWRITE_PNG_COMPRESSION, 9])

            i += 1



    def add(self, filename):
        filename_p = Path(filename)


        if len(self.image_list) == self.stack_count:
            self.image_list.pop()  # remove last element


        ### Open file
        hdulist = fits.open(filename_p)

        self.image_list.insert(0, hdulist)  # new image is first in list


    def _detectBitDepth(self, data):
        ### This will need some rework if cameras return signed int data
        max_val = numpy.amax(data)
        logger.info('Image max value: %d', int(max_val))

        # This method of detecting bit depth can cause the 16->8 bit conversion
        # to stretch too much.  This most commonly happens with very low gains
        # during the day when there are no hot pixels.  This can result in a
        # trippy effect
        if max_val > 32768:
            image_bit_depth = 16
        elif max_val > 16384:
            image_bit_depth = 15
        elif max_val > 8192:
            image_bit_depth = 14
        elif max_val > 4096:
            image_bit_depth = 13
        elif max_val > 2096:
            image_bit_depth = 12
        elif max_val > 1024:
            image_bit_depth = 11
        elif max_val > 512:
            image_bit_depth = 10
        elif max_val > 256:
            image_bit_depth = 9
        else:
            image_bit_depth = 8

        logger.info('Detected bit depth: %d', image_bit_depth)

        return image_bit_depth


    def _convert_16bit_to_8bit(self, data, image_bitpix, image_bit_depth):
        if image_bitpix == 8:
            return

        logger.info('Resampling image from %d to 8 bits', image_bitpix)

        div_factor = int((2 ** image_bit_depth) / 255)

        return (data / div_factor).astype(numpy.uint8)


    def _crop(self, image):
        image_height, image_width = image.shape[:2]

        x1 = int((image_width / 2) - (image_width / 3))
        y1 = int((image_height / 2) - (image_height / 3))
        x2 = int((image_width / 2) + (image_width / 3))
        y2 = int((image_height / 2) + (image_height / 3))


        return image[
            y1:y2,
            x1:x2,
        ]


    def splitscreen(self, left_data, right_data):
        image_height, image_width = left_data.shape[:2]


        half_width = int(image_width / 2)

        # left side
        left_mask = numpy.zeros((image_height, image_width), dtype=numpy.uint8)
        cv2.rectangle(
            img=left_mask,
            pt1=(0, 0),
            #pt2=(half_width, image_height),
            pt2=(half_width - 1, image_height),  # ensure a black line is down the center
            color=255,
            thickness=cv2.FILLED,
        )

        masked_left = cv2.bitwise_and(left_data, left_data, mask=left_mask)

        # right side
        right_mask = numpy.zeros((image_height, image_width), dtype=numpy.uint8)
        cv2.rectangle(
            img=right_mask,
            pt1=(half_width + 1, 0),
            pt2=(image_width, image_height),
            color=255,
            thickness=cv2.FILLED,
        )

        masked_right = cv2.bitwise_and(right_data, right_data, mask=right_mask)

        return numpy.maximum(masked_left, masked_right)


class ImageStacker(object):

    def mean(self, *args, **kwargs):
        # alias for average
        return self.average(*args, **kwargs)


    def average(self, stack_data, numpy_type):
        mean_image = numpy.mean(stack_data, axis=0)
        return numpy.floor(mean_image).astype(numpy_type)  # no floats


    def maximum(self, stack_data, numpy_type):
        image_max = stack_data[0]  # start with first image

        # compare with remaining images
        for i in stack_data[1:]:
            image_max = numpy.maximum(image_max, i)

        return image_max

    def minimum(self, stack_data, numpy_type):
        image_min = stack_data[0]  # start with first image

        # compare with remaining images
        for i in stack_data[1:]:
            image_min = numpy.minimum(image_min, i)

        return image_min


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
        '--output_dir',
        '-o',
        help='output directory',
        type=str,
        required=True,
    )
    argparser.add_argument(
        '--method',
        '-m',
        help='method',
        type=str,
        required=True,
        choices=(
            'average',
            'maximum',
            'minimum',
        )
    )


    args = argparser.parse_args()

    ar = AlignRolling(args.method, args.output_dir)
    ar.main(args.inputfiles)


