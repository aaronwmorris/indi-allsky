#!/usr/bin/env python3

###
### Processes FITS files using the indi-allsky processing pipeline
###

import sys
import argparse
from pathlib import Path
from astropy.io import fits
import logging
from pprint import pformat  # noqa: F401


logging.basicConfig(level=logging.INFO)
logger = logging


class FitsHeaders(object):


    def main(self, input_file):
        input_file_p = Path(input_file)
        if not input_file_p.exists():
            logger.error('%s does not exist', input_file_p)
            sys.exit(1)


        if input_file_p.suffix != '.fit' and input_file_p.suffix != '.fits':
            logger.error('Please specify a FITS file')
            sys.exit(1)


        hdulist = fits.open(input_file_p)

        for k, v in hdulist[0].header.items():
            print('{0}: {1}'.format(k, v))


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'fits_file',
        help='FITS file',
        type=str,
    )

    args = argparser.parse_args()


    fh = FitsHeaders()
    fh.main(args.fits_file)

