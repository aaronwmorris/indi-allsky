#!/usr/bin/env python3


import timeit
#import time
import random
import cv2
import numpy
from pathlib import Path
import logging

#import cv2
#from PIL import Image


logging.basicConfig(level=logging.INFO)
logger = logging


class ImageBench(object):
    rounds = 50

    ### 1k
    width  = 1920
    height = 1080

    ### 4k
    #width  = 3840
    #height = 2160


    def __init__(self):
        self.f_tmp_name = Path('/dev/shm/image_bench.jpg')
        #self.f_tmp_name = Path('/dev/shm/image_bench.png')
        #self.f_tmp_name = Path('/dev/shm/image_bench.webp')

        # random
        #image_bgr = numpy.random.randint(255, size=(self.height, self.width, 3), dtype=numpy.uint8)

        # grey
        #image_bgr = numpy.full([self.height, self.width, 3], 127, dtype=numpy.uint8)

        # black
        #image_bgr = numpy.zeros([self.height, self.width, 3], dtype=numpy.uint8)


        # draw a bunch of random circles
        image_bgr = numpy.zeros([self.height, self.width, 3], dtype=numpy.uint8)
        for x in range(500):
            r = random.randrange(255)
            g = random.randrange(255)
            b = random.randrange(255)
            radius = random.randrange(5, 100)
            x = random.randrange(self.width)
            y = random.randrange(self.height)

            cv2.circle(
                image_bgr,
                center=(x, y),
                radius=radius,
                color=(r, g, b),
                thickness=cv2.FILLED,
                lineType=cv2.LINE_AA,
            )

        cv2.imwrite(str(self.f_tmp_name), image_bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
        #cv2.imwrite(str(self.f_tmp_name), image_bgr, [cv2.IMWRITE_PNG_COMPRESSION, 7])
        #cv2.imwrite(str(self.f_tmp_name), image_bgr, [cv2.IMWRITE_WEBP_QUALITY, 90])
        #cv2.imwrite(str(self.f_tmp_name), image_bgr, [cv2.IMWRITE_WEBP_QUALITY, 101])  # lossless


    def __del__(self):
        self.f_tmp_name.unlink()


    def main(self):
        setup_pillow_read = '''
from PIL import Image
import cv2
import numpy
'''

        s_pillow_read = '''
img = Image.open("/dev/shm/image_bench.jpg")
#img = Image.open("/dev/shm/image_bench.png")
#img = Image.open("/dev/shm/image_bench.webp")

img_n = numpy.array(img)
img_bgr = cv2.cvtColor(img_n, cv2.COLOR_RGB2BGR)
'''

        setup_pillow_write = '''
import io
from PIL import Image
import cv2
import numpy

img = Image.open("/dev/shm/image_bench.jpg")
#img = Image.open("/dev/shm/image_bench.png")
#img = Image.open("/dev/shm/image_bench.webp")

img_n = numpy.array(img)
img_bgr = cv2.cvtColor(img_n, cv2.COLOR_RGB2BGR)

# writing to /dev/null is faster
out = io.open("/dev/null", "wb")
#out = io.BytesIO()
'''

        s_pillow_write = '''
#out.seek(0)  # for buffer
img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
i = Image.fromarray(img_bgr)

i.save(out, format="JPEG", quality=90)
#i.save(out, format="PNG", compression=7)
#i.save(out, format="WEBP", quality=90, lossless=True)
'''

        setup_opencv_read = '''
import cv2
'''

        s_opencv_read = '''
cv2.imread("/dev/shm/image_bench.jpg", cv2.IMREAD_UNCHANGED)
#cv2.imread("/dev/shm/image_bench.png", cv2.IMREAD_UNCHANGED)
#cv2.imread("/dev/shm/image_bench.webp", cv2.IMREAD_UNCHANGED)
'''

        setup_opencv_write = '''
import cv2

img = cv2.imread("/dev/shm/image_bench.jpg", cv2.IMREAD_UNCHANGED)
#img = cv2.imread("/dev/shm/image_bench.png", cv2.IMREAD_UNCHANGED)
#img = cv2.imread("/dev/shm/image_bench.webp", cv2.IMREAD_UNCHANGED)
'''

        s_opencv_write = '''
cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
#cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 7])
#cv2.imencode(".webp", img, [cv2.IMWRITE_WEBP_QUALITY, 101])
'''


        setup_simplejpeg_read = '''
import io
import simplejpeg

with io.open("/dev/shm/image_bench.jpg", 'rb') as f_image:
    img = f_image.read()
'''

        s_simplejpeg_read = '''
simplejpeg.decode_jpeg(img, colorspace='BGR')
'''

        setup_simplejpeg_write = '''
import io
import simplejpeg

with io.open("/dev/shm/image_bench.jpg", 'rb') as f_image:
    img = simplejpeg.decode_jpeg(f_image.read(), colorspace='BGR')
'''

        s_simplejpeg_write = '''
simplejpeg.encode_jpeg(img, colorspace='BGR', quality=90)
'''



        t_pillow_read = timeit.timeit(stmt=s_pillow_read, setup=setup_pillow_read, number=self.rounds)
        logger.info('Pillow read: %0.3fms', t_pillow_read * 1000 / self.rounds)

        t_pillow_write = timeit.timeit(stmt=s_pillow_write, setup=setup_pillow_write, number=self.rounds)
        logger.info('Pillow write: %0.3fms', t_pillow_write * 1000 / self.rounds)

        t_opencv2_read = timeit.timeit(stmt=s_opencv_read, setup=setup_opencv_read, number=self.rounds)
        logger.info('OpenCV read: %0.3fms', t_opencv2_read * 1000 / self.rounds)

        t_opencv2_write = timeit.timeit(stmt=s_opencv_write, setup=setup_opencv_write, number=self.rounds)
        logger.info('OpenCV write: %0.3fms', t_opencv2_write * 1000 / self.rounds)

        t_simplejpeg_read = timeit.timeit(stmt=s_simplejpeg_read, setup=setup_simplejpeg_read, number=self.rounds)
        logger.info('simplejpeg read: %0.3fms', t_simplejpeg_read * 1000 / self.rounds)

        t_simplejpeg_write = timeit.timeit(stmt=s_simplejpeg_write, setup=setup_simplejpeg_write, number=self.rounds)
        logger.info('simplejpeg write: %0.3fms', t_simplejpeg_write * 1000 / self.rounds)


if __name__ == "__main__":
    ib = ImageBench()
    ib.main()

