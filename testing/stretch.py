#!/usr/bin/env python3


import sys
import time
import argparse
from pathlib import Path
from astropy.io import fits
from astropy.visualization import MinMaxInterval
from astropy.visualization import HistEqStretch
#from astropy.visualization import SinhStretch
#from astropy.visualization import AsinhStretch
#from astropy.visualization import LinearStretch
#from astropy.visualization import LogStretch
#from astropy.visualization import SqrtStretch
import numpy
import cv2
import logging


logging.basicConfig(level=logging.INFO)
logger = logging


class StretchTest(object):

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


        start = time.time()


        interval = MinMaxInterval()
        normalized = interval(hdulist[0].data)

        stretch = HistEqStretch(data=normalized)
        #stretch = SinhStretch()
        #stretch = AsinhStretch()
        #stretch = LinearStretch()
        #stretch = LogStretch()
        #stretch = SqrtStretch()
        data_norm = stretch(normalized)
        #data_norm = stretch(hdulist[0].data)

        stretched = numpy.floor(hdulist[0].data * data_norm).astype(numpy.uint16)

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


    st = StretchTest()
    st.main(args.input, args.output)

