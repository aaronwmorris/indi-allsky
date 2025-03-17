#!/usr/bin/env python3

#import io
import cv2
import numpy
import tempfile
import time
from pathlib import Path
import logging

from multiprocessing import Process

logging.basicConfig(level=logging.INFO)
logger = logging


class ImageCompressTest(object):
    def main(self):
        image_worker = ImageWorker()
        image_worker.start()
        image_worker.join()


class ImageWorker(Process):

    ### 1k
    width  = 1920
    height = 1080

    ### 4k
    #width  = 3840
    #height = 2160

    jpg_factor_list = (100, 90, 80, 70)
    png_factor_list = (9, 8, 7, 6)


    def __init__(self):
        super(ImageWorker, self).__init__()

        self.name = 'ImageWorker000'

        logger.info('*** Generating random %d x %d image ***', self.width, self.height)

        bits = 16

        # random colors (16bit -> 8bit)
        random_rgb_full = numpy.random.randint(((2 ** bits) - 1), size=(self.height, self.width, 3), dtype=numpy.uint16)

        #div_factor = int((2 ** 16) / 255)
        #self.random_rgb = (random_rgb_full / div_factor).astype('uint8')

        # shifting is 5x faster than division
        shift_factor = bits - 8
        self.random_rgb = numpy.right_shift(random_rgb_full, shift_factor).astype(numpy.uint8)

        # grey
        #self.random_rgb = numpy.full([self.height, self.width, 3], 127, dtype=numpy.uint8)

        # black
        #self.random_rgb = numpy.zeros([self.height, self.width, 3], dtype=numpy.uint8)

        # load raw numpy data
        #with io.open('/tmp/indi_allsky_numpy.npy', 'r+b') as f_numpy:
        #    self.random_rgb = numpy.load(f_numpy)


    def run(self):
        #PNG
        logger.info('*** Running png compression tests ***')

        for png_factor in self.png_factor_list:
            logger.info('Testing png factor %d', png_factor)

            for x in range(3):
                png_tmp_file = tempfile.NamedTemporaryFile(suffix='.png', dir='/dev/shm', delete=False)
                png_tmp_file.close()

                png_tmp_file_p = Path(png_tmp_file.name)
                png_tmp_file_p.unlink()


                write_img_start = time.time()

                cv2.imwrite(str(png_tmp_file_p), self.random_rgb, [cv2.IMWRITE_PNG_COMPRESSION, png_factor])

                write_img_elapsed_s = time.time() - write_img_start
                logger.info('Pass %d - compressed in %0.4f s', x, write_img_elapsed_s)

                png_tmp_file_p.unlink()


        #JPG
        logger.info('*** Running jpeg compression tests ***')

        for jpg_factor in self.jpg_factor_list:
            logger.info('Testing factor %d', jpg_factor)

            for x in range(3):
                jpg_tmp_file = tempfile.NamedTemporaryFile(suffix='.jpg', dir='/dev/shm', delete=False)
                jpg_tmp_file.close()

                jpg_tmp_file_p = Path(jpg_tmp_file.name)
                jpg_tmp_file_p.unlink()

                write_img_start = time.time()

                cv2.imwrite(str(jpg_tmp_file_p), self.random_rgb, [cv2.IMWRITE_JPEG_QUALITY, jpg_factor])

                write_img_elapsed_s = time.time() - write_img_start
                logger.info('Pass %d - compressed in %0.4f s', x, write_img_elapsed_s)

                jpg_tmp_file_p.unlink()


if __name__ == "__main__":
    ct = ImageCompressTest()
    ct.main()

