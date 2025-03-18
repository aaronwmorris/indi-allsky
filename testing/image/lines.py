#!/usr/bin/env python3

import cv2
import numpy
import argparse
import logging
import time
from pathlib import Path
from pprint import pformat


logging.basicConfig(level=logging.INFO)
logger = logging



class LineDetector(object):

    def __init__(self):
        pass


    def main(self, inputdir):
        file_list = list()
        self.getFolderFilesByExt(inputdir, file_list)

        # Exclude empty files
        file_list_nonzero = filter(lambda p: p.stat().st_size != 0, file_list)

        # Sort by timestamp
        file_list_ordered = sorted(file_list_nonzero, key=lambda p: p.stat().st_mtime)



        processing_start = time.time()

        line_files = list()
        for filename in file_list_ordered:
            logger.info('Reading file: %s', filename)
            image = cv2.imread(str(filename), cv2.IMREAD_GRAYSCALE)

            if isinstance(image, type(None)):
                logger.error('Unable to read %s', filename)
                continue


            #dst = cv2.Canny(image, 50, 200, None, 3)
            dst = cv2.Canny(
                image,
                threshold1=50,
                threshold2=200,
                edges=None,
                L2gradient=3,
            )

            #lines = cv2.HoughLines(
            #    dst,
            #    rho=1,
            #    theta=numpy.pi / 180,
            #    threshold=125,
            #    lines=None,
            #    srn=0,
            #    stn=0,
            #)

            lines = cv2.HoughLinesP(
                dst,
                rho=1,
                theta=numpy.pi / 180,
                threshold=125,
                lines=None,
                minLineLength=20,
                maxLineGap=10,
            )

            if lines is not None:
                logger.warning(' Detected %d lines', len(lines))
                line_files.append(filename)
            else:
                pass
                #logger.warning(' No lines')


        processing_elapsed_s = time.time() - processing_start
        logger.info('Images processed in %0.1f s', processing_elapsed_s)

        logger.warning('Files with lines: %s', pformat(line_files))



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

    args = argparser.parse_args()

    ld = LineDetector()
    ld.main(args.inputdir)

