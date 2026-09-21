#!/usr/bin/env python3
#####################################
# Test all bayer patterns on file   #
#####################################

import sys
import argparse
from pathlib import Path
import cv2
import numpy
from astropy.io import fits
import logging
from pprint import pformat  # noqa: F401


logging.basicConfig(level=logging.INFO)
logger = logging


class DebayerAllTest(object):

    __cfa_bgr_map = {
        'GRBG' : cv2.COLOR_BAYER_GB2BGR,
        'RGGB' : cv2.COLOR_BAYER_BG2BGR,
        'BGGR' : cv2.COLOR_BAYER_RG2BGR,
        'GBRG' : cv2.COLOR_BAYER_GR2BGR,
    }


    def main(self, input_file):
        inputfile_p = Path(input_file)
        if not inputfile_p.exists():
            logger.error('%s does not exist', inputfile_p)
            sys.exit(1)

        if inputfile_p.suffix.lower() in ['.fit', '.fits']:
            # fits
            hdulist = fits.open(inputfile_p)
            data = hdulist[0].data

            image_bitpix = hdulist[0].header['BITPIX']

            logger.warning('FITS BAYERPAT: %s', hdulist[0].header.get('BAYERPAT'))

            #logger.info('HDU Header = %s', pformat(hdulist[0].header))
        else:
            # hopefully a png
            data = cv2.imread(str(inputfile_p), cv2.IMREAD_UNCHANGED)

            image_bitpix = 16  # assumption


        if isinstance(data, type(None)):
            logger.error('File is not valid image data: %s', inputfile_p)
            sys.exit(1)


        if len(data.shape) != 2:
            logger.error('Image is already debayered')
            sys.exit(1)


        #data = cv2.flip(data, 0)  # verticle flip
        #data = cv2.flip(data, 1)  # horizontal flip


        image_bit_depth = self._detectBitDepth(data)


        for pattern, debayer_algorithm in self.__cfa_bgr_map.items():
            data_bgr = cv2.cvtColor(data, debayer_algorithm)
            data_bgr_8 = self._convert_16bit_to_8bit(data_bgr, image_bitpix, image_bit_depth)

            outputfile_p = inputfile_p.parent / Path('{0:s}_{1:s}.jpg'.format(inputfile_p.stem, pattern))
            logger.warning('Generating %s', outputfile_p)
            cv2.imwrite(str(outputfile_p), data_bgr_8, [cv2.IMWRITE_JPEG_QUALITY, 90])


    def _convert_16bit_to_8bit(self, data, image_bitpix, image_bit_depth):
        if image_bitpix == 8:
            return

        logger.info('Resampling image from %d to 8 bits', image_bitpix)

        #div_factor = int((2 ** image_bit_depth) / 255)
        #return (data / div_factor).astype(numpy.uint8)

        # shifting is 5x faster than division
        shift_factor = image_bit_depth - 8
        return numpy.right_shift(data, shift_factor).astype(numpy.uint8)


    def _detectBitDepth(self, data):
        ### This will need some rework if cameras return signed int data
        max_val = numpy.amax(data)
        logger.info('Image max value: %d', int(max_val))


        if max_val > 16383:
            detected_bit_depth = 16
        elif max_val > 4095:
            detected_bit_depth = 14
        elif max_val > 1023:
            detected_bit_depth = 12
        elif max_val > 255:
            detected_bit_depth = 10
        else:
            detected_bit_depth = 8


        logger.info('Detected bit depth: %d', detected_bit_depth)

        return detected_bit_depth


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'input',
        help='Input file',
        type=str,
    )

    args = argparser.parse_args()


    d = DebayerAllTest()
    d.main(args.input)

