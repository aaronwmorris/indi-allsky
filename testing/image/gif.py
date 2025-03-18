#!/usr/bin/env python3

import sys
import argparse
import logging
import imageio
import pygifsicle
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


    def main(self, outfile, inputfiles, optimize=False):
        logger.warning('Creating %s', outfile)
        with imageio.get_writer(outfile, mode='I', duration=self.duration) as writer:
            for filename in inputfiles:
                logger.info(' Reading %s', filename)
                image = imageio.imread(filename)

                if len(self.roi):
                    logger.info('  *** Extracting ROI ***')
                    data = image[
                        self.roi[1]:self.roi[3],
                        self.roi[0]:self.roi[2],
                    ]
                else:
                    data = image

                writer.append_data(data)

        if optimize:
            logger.info('Optimizing gif')
            pygifsicle.optimize(
                outfile,
            )


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
        help='duration [default: 0.25]',
        type=float,
        default=0.25,
        required=False,
    )
    argparser.add_argument(
        '--roi',
        '-r',
        help='roi [x1 y1 x2 y2]',
        type=int,
        default=[],
        nargs='*',
        required=False,
    )
    argparser.add_argument(
        '--optimize',
        '-O',
        dest='optimize',
        action='store_true',
        help='optimize gif',
    )
    argparser.add_argument(
        '--no-optimize',
        dest='optimize',
        action='store_true',
    )
    argparser.set_defaults(optimize=False)

    args = argparser.parse_args()

    gb = GifBuilder(duration=args.duration, roi=args.roi)
    gb.main(args.output, args.inputfiles, optimize=args.optimize)

