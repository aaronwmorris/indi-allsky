#!/usr/bin/env python3

import sys
import argparse
import logging
import imageio
#from pprint import pformat

logging.basicConfig(level=logging.INFO)
logger = logging


class FfmpegBuilder(object):
    def __init__(self, fps=25, roi=[]):
        self.fps = fps
        self.roi = roi

        try:
            assert len(self.roi) == 4 or len(self.roi) == 0
        except AssertionError:
            logger.error('ROI must be 4 integers')
            sys.exit(1)


    def main(self, outfile, inputfiles, optimize=False):
        logger.warning('Creating %s', outfile)
        with imageio.get_writer(outfile, 
                                format='FFMPEG',
                                mode='I',
                                fps=self.fps,
                                codec='libx264',
                                pixelformat='yuv420p',
                                ) as writer:
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
        '--fps',
        '-f',
        help='fps',
        type=int,
        default=25,
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

    fb = FfmpegBuilder(fps=args.fps, roi=args.roi)
    fb.main(args.output, args.inputfiles)

