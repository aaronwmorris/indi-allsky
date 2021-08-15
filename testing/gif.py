#!/usr/bin/env python3

import imageio
import argparse
import logging

logging.basicConfig(level=logging.INFO)
logger = logging


class GifBuilder(object):
    def __init__(self, duration=0.25):
        self.duration = float(duration)


    def main(self, outfile, inputfiles):
        logger.warning('Creating %s', outfile)
        with imageio.get_writer(outfile, mode='I', duration=self.duration) as writer:
            for filename in inputfiles:
                logger.info(' Reading %s', filename)
                image = imageio.imread(filename)
                writer.append_data(image)



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

    args = argparser.parse_args()

    gb = GifBuilder(duration=args.duration)
    gb.main(args.output, args.inputfiles)

