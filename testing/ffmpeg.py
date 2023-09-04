#!/usr/bin/env python3

import sys
import argparse
import logging
import imageio
#from pprint import pformat

logging.basicConfig(level=logging.INFO)
logger = logging


class FfmpegBuilder(object):
    def __init__(self, fps=25, roi=[], bitrate=2500000):
        self.fps = fps
        self.roi = roi
        self.bitrate = bitrate
        #self.quality = quality

        try:
            assert len(self.roi) == 4 or len(self.roi) == 0
        except AssertionError:
            logger.error('ROI must be 4 integers')
            sys.exit(1)


    def main(self, outfile, inputfiles, optimize=False):
        logger.warning('Creating %s', outfile)
        with imageio.get_writer(
            outfile,
            format='FFMPEG',
            mode='I',
            #quality=self.quality,
            bitrate=self.bitrate,
            fps=self.fps,
            codec='libx264',
            pixelformat='yuv420p',
        ) as writer:
            for filename in inputfiles:
                logger.info(' Reading %s', filename)
                image = imageio.v3.imread(filename)

                if len(self.roi):
                    logger.info('  *** Extracting ROI ***')
                    data = image[
                        self.roi[1]:self.roi[3],
                        self.roi[0]:self.roi[2],
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
        help='fps [default: 25]',
        type=int,
        default=25,
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
        '--bitrate',
        '-b',
        help='bitrate [default: 2500000]',
        type=int,
        default=2500000,
    )
    #argparser.add_argument(
    #    '--quality',
    #    '-q',
    #    help='quality [0-10]',
    #    type=int,
    #    default=5,
    #)


    args = argparser.parse_args()

    fb = FfmpegBuilder(fps=args.fps, roi=args.roi, bitrate=args.bitrate)
    fb.main(args.output, args.inputfiles)

