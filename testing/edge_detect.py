#!/usr/bin/env python3

import sys
import cv2
import numpy
import argparse
import logging
import time
#from pathlib import Path
#from pprint import pformat


logging.basicConfig(level=logging.INFO)
logger = logging



class EdgeDetector(object):

    def __init__(self):
        pass


    def main(self, filename):

        img_gray = cv2.imread(str(filename), cv2.IMREAD_GRAYSCALE)

        if isinstance(img_gray, type(None)):
            logger.error('Unable to read %s', filename)
            sys.exit(1)

        #blur_gray = img_gray
        blur_gray = cv2.GaussianBlur(
            img_gray,
            (5, 5),
            0,
        )

        #lap_start = time.time()

        #lap_img = cv2.Laplacian(
        #    blur_gray,
        #    cv2.CV_8UC1,
        #    3,
        #)

        #lap_elapsed_s = time.time() - lap_start
        #logger.info('Laplacian processed in %0.1f s', lap_elapsed_s)


        canny_start = time.time()

        canny_img = cv2.Canny(
            blur_gray,
            15,
            50,
        )


        canny_elapsed_s = time.time() - canny_start
        logger.info('Canny processed in %0.1f s', canny_elapsed_s)


        #lines_lap = cv2.HoughLinesP(
        #    lap_img,
        #    rho=1,
        #    theta=numpy.pi / 180,
        #    threshold=125,
        #    lines=None,
        #    minLineLength=20,
        #    maxLineGap=10,
        #)

        #if lines_lap is not None:
        #    logger.warning(' Laplace detected %d lines', len(lines_lap))
        #else:
        #    pass
        #    logger.warning(' Laplace No lines')


        lines_canny = cv2.HoughLinesP(
            canny_img,
            rho=1,
            theta=numpy.pi / 180,
            threshold=125,
            lines=None,
            minLineLength=40,
            maxLineGap=20,
        )


        if lines_canny is None:
            logger.warning(' Canny No lines')
            sys.exit()


        logger.warning(' Canny detected %d lines', len(lines_canny))
        for line in lines_canny:
            for x1, y1, x2, y2 in line:
                cv2.line(
                    canny_img,
                    (x1, y1),
                    (x2, y2),
                    (255, 0, 0),
                    3,
                )


        cv2.imwrite('edge_canny.jpg', canny_img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        #cv2.imwrite('edge_laplacian.jpg', lap_img, [cv2.IMWRITE_JPEG_QUALITY, 90])



if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'filename',
        help='Input file',
        type=str,
    )

    args = argparser.parse_args()

    ed = EdgeDetector()
    ed.main(args.filename)

