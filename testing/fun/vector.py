#!/usr/bin/env python3

import os
import cv2
import numpy
import argparse
import logging
import time
from pathlib import Path
from pprint import pformat


logging.basicConfig(level=logging.INFO)
logger = logging



class VectorGenerator(object):

    def __init__(self):
        pass


    def main(self, inputdir, outputdir):
        inputdir_p = Path(inputdir)
        outputdir_p = Path(outputdir)

        assert(inputdir_p.is_dir())
        assert(outputdir_p.is_dir())


        file_list = list()
        self.getFolderFilesByExt(inputdir_p, file_list)

        # Exclude empty files
        file_list_nonzero = filter(lambda p: p.stat().st_size != 0, file_list)

        # Sort by timestamp
        file_list_ordered = sorted(file_list_nonzero, key=lambda p: p.stat().st_mtime)



        processing_start = time.time()

        line_files = list()
        for i, filename in enumerate(file_list_ordered):
            mtime = filename.stat().st_mtime

            logger.info('Reading file: %s', filename)
            image = cv2.imread(str(filename), cv2.IMREAD_GRAYSCALE)

            if isinstance(image, type(None)):
                logger.error('Unable to read %s', filename)
                continue


            edge_img = cv2.Canny(
                image,
                threshold1=25,
                threshold2=100,
                edges=None,
                L2gradient=3,
            )

            #lines = cv2.HoughLinesP(
            #    dst,
            #    rho=1,
            #    theta=numpy.pi / 180,
            #    threshold=125,
            #    lines=None,
            #    minLineLength=20,
            #    maxLineGap=10,
            #)

            #if lines is not None:
            #    logger.warning(' Detected %d lines', len(lines))
            #    line_files.append(filename)
            #else:
            #    pass
            #    #logger.warning(' No lines')

            outfile = outputdir_p.joinpath('{0:05d}.jpg'.format(i))
            logger.info('Writing %s', outfile)
            cv2.imwrite(str(outfile), edge_img, [cv2.IMWRITE_JPEG_QUALITY, 90])

            os.utime(outfile, (mtime, mtime))


        processing_elapsed_s = time.time() - processing_start
        logger.info('Images processed in %0.1f s', processing_elapsed_s)

        logger.warning('Files with lines: %s', pformat(line_files))


        ffmpeg_cmd = [
            'ffmpeg',
            '-y',
            '-f', 'image2',
            '-r', '{0:d}'.format(25),
            '-i', '"{0:s}/%05d.jpg"'.format(str(outputdir_p)),
            '-vcodec', 'libx264',
            '-b:v', '2500k',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            'outfile.mp4'
        ]

        print()
        print('ffmpeg command:')
        print(' '.join(ffmpeg_cmd))
        print()


    def getFolderFilesByExt(self, folder, file_list, extension_list=None):
        if not extension_list:
            extension_list = ['jpg']

        logger.info('Searching for image files in %s', folder)

        dot_extension_list = ['.{0:s}'.format(e) for e in extension_list]

        for item in Path(folder).iterdir():
            if item.is_file() and item.suffix in dot_extension_list:
                file_list.append(item)
            elif item.is_dir():
                self.getFolderFilesByExt(item, file_list, extension_list=extension_list)  # recursion



if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'inputdir',
        help='Input directory',
        type=str,
    )
    argparser.add_argument(
        'outputdir',
        help='Output directory',
        type=str,
    )


    args = argparser.parse_args()

    vg = VectorGenerator()
    vg.main(args.inputdir, args.outputdir)

