#!/usr/bin/env python3


import sys
import time
import argparse
from pathlib import Path
from astropy.io import fits
import numpy
import cv2
import logging


logging.basicConfig(level=logging.INFO)
logger = logging


class StretchTestMode1(object):

    def main(self, input_file, output_file):
        inputfile_p = Path(input_file)
        if not inputfile_p.exists():
            logger.error('%s does not exist', inputfile_p)
            sys.exit(1)

        outputfile_p = Path(output_file)
        if outputfile_p.exists():
            logger.error('%s file already exists', outputfile_p)
            sys.exit(1)


        hdulist = fits.open(inputfile_p)


        data = hdulist[0].data

        start = time.time()

        data = self._apply_gamma(data, 16, gamma=3.0)

        stretched = self._adjustImageLevels(data, 16, devs=3.0)

        #stretched = data


        elapsed_s = time.time() - start
        logger.info('Stretched in %0.4f s', elapsed_s)

        stretched_8 = self._convert_16bit_to_8bit(stretched, 16, 16)

        cv2.imwrite(str(outputfile_p), stretched_8, [cv2.IMWRITE_JPEG_QUALITY, 90])


    def _convert_16bit_to_8bit(self, data, image_bitpix, image_bit_depth):
        if image_bitpix == 8:
            return

        logger.info('Resampling image from %d to 8 bits', image_bitpix)

        #div_factor = int((2 ** image_bit_depth) / 255)
        #return (data / div_factor).astype(numpy.uint8)

        # shifting is 5x faster than division
        shift_factor = image_bit_depth - 8
        return numpy.right_shift(data, shift_factor).astype(numpy.uint8)


    def _apply_gamma(self, data, image_bit_depth, gamma=3.0):
        if not gamma:
            return data

        logger.info('Applying gamma correction')

        gamma_start = time.time()

        data_max = 2 ** image_bit_depth
        range_array = numpy.arange(0, data_max, dtype=numpy.float32)
        lut = (((range_array / data_max) ** (1 / float(gamma))) * data_max).astype(numpy.uint16)


        gamma_image = lut.take(data, mode='raise')

        gamma_elapsed_s = time.time() - gamma_start
        logger.info('Image gamma in %0.4f s', gamma_elapsed_s)

        return gamma_image


    def _adjustImageLevels(self, data, image_bit_depth, devs=3.0):
        mean, stddev = self._get_image_stddev(data)
        logger.info('Mean: %0.2f, StdDev: %0.2f', mean, stddev)


        levels_start = time.time()

        data_max = 2 ** image_bit_depth

        low = int(mean - (devs * stddev))

        lowPercent  = (low / data_max) * 100
        highPercent = 100.0

        lowIndex = int((lowPercent / 100) * data_max)
        highIndex = int((highPercent / 100) * data_max)


        range_array = numpy.arange(0, data_max, dtype=numpy.float32)

        #range_array[range_array <= lowIndex] = 0
        #range_array[range_array > highIndex] = data_max

        lut = (((range_array - lowIndex) * data_max) / (highIndex - lowIndex))  # floating point match, results in negative numbers

        lut[lut < 0] = 0
        lut[lut > data_max] = data_max

        lut = lut.astype(numpy.uint16)


        stretch_image = lut.take(data, mode='raise')

        levels_elapsed_s = time.time() - levels_start
        logger.info('Image levels in %0.4f s', levels_elapsed_s)

        return stretch_image


    def _get_image_stddev(self, data, mask=None):
        mean_std_start = time.time()

        if isinstance(mask, type(None)):
            image_height, image_width = data.shape[:2]

            x1 = int((image_width / 2) - (image_width / 4))
            y1 = int((image_height / 2) - (image_height / 4))
            x2 = int((image_width / 2) + (image_width / 4))
            y2 = int((image_height / 2) + (image_height / 4))

            roi = data[
                y1:y2,
                x1:x2,
            ]
        else:
            roi = cv2.bitwise_and(data, data, mask=mask)


        if len(roi.shape) == 2:
            # mono
            mean = numpy.mean(roi)
            stddev = numpy.std(roi)
        else:
            # color
            b, g, r = roi[:, :, 0], roi[:, :, 1], roi[:, :, 2]

            b_mean = numpy.mean(b)
            g_mean = numpy.mean(g)
            r_mean = numpy.mean(r)

            b_stddev = numpy.std(b)
            g_stddev = numpy.std(g)
            r_stddev = numpy.std(r)

            mean = (b_mean + g_mean + r_mean) / 3
            stddev = (b_stddev + g_stddev + r_stddev) / 3


        mean_std_elapsed_s = time.time() - mean_std_start
        logger.info('Mean and std dev in %0.4f s', mean_std_elapsed_s)

        return mean, stddev



if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'input',
        help='Input file',
        type=str,
    )
    argparser.add_argument(
        '--output',
        '-o',
        help='output file',
        type=str,
        required=True,
    )


    args = argparser.parse_args()


    st = StretchTestMode1()
    st.main(args.input, args.output)

