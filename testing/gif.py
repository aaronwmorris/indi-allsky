#!/usr/bin/env python3

import sys
import imageio
import argparse
import logging
#from pprint import pformat

logging.basicConfig(level=logging.INFO)
logger = logging


class GifBuilder(object):
    def __init__(self, duration=0.25, roi=[]):
        self.duration = float(duration)
        self.roi = roi

        try:
            assert len(self.roi) == 4 or len(self.roi) == 0
        except AssertionError:
            logger.error('ROI must be 4 integers')
            sys.exit(1)


    def main(self, outfile, inputfiles):
        logger.warning('Creating %s', outfile)
        with imageio.get_writer(outfile, mode='I', duration=self.duration) as writer:
            for filename in inputfiles:
                logger.info(' Reading %s', filename)
                image = imageio.imread(filename)

                if len(self.roi):
                    logger.info('  *** Extracting ROI ***')
                    data = image[
                        self.roi[1]:(self.roi[1] + self.roi[3]),
                        self.roi[0]:(self.roi[0] + self.roi[2]),
                    ]
                else:
                    data = image

                writer.append_data(data)



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
    argparser.add_argument(
        '--duration',
        '-d',
        help='duration',
        type=float,
        default=0.25,
        required=False,
    )
    argparser.add_argument(
        '--roi',
        '-r',
        help='roi',
        type=int,
        default=[],
        nargs='*',
        required=False,
    )

    args = argparser.parse_args()

    gb = GifBuilder(duration=args.duration, roi=args.roi)
    gb.main(args.output, args.inputfiles)

