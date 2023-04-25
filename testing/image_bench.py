#!/usr/bin/env python3


import timeit
#import time

#import cv2
#from PIL import Image

ROUNDS = 25


setup_pillow_read = '''
from PIL import Image
import cv2
import numpy
'''

s_pillow_read = '''
img = Image.open("blob_detection/test_transparent_clouds_plane.jpg")
img_n = numpy.array(img)
img_bgr = cv2.cvtColor(img_n, cv2.COLOR_RGB2BGR)
'''

setup_pillow_write = '''
import io
from PIL import Image
import cv2
import numpy

img = Image.open("blob_detection/test_transparent_clouds_plane.jpg")
img_n = numpy.array(img)
img_bgr = cv2.cvtColor(img_n, cv2.COLOR_RGB2BGR)

out = io.open("/dev/null", "wb")
'''

s_pillow_write = '''
img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
i = Image.fromarray(img_bgr)
i.save(out, format="JPEG", quality=90)
#i.save(out, format="PNG", compression=7)
'''

setup_opencv_read = '''
import cv2
'''

s_opencv_read = '''
cv2.imread("blob_detection/test_transparent_clouds_plane.jpg", cv2.IMREAD_UNCHANGED)
'''

setup_opencv_write = '''
import cv2
img = cv2.imread("blob_detection/test_transparent_clouds_plane.jpg", cv2.IMREAD_UNCHANGED)
'''

s_opencv_write = '''
cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
#cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 7])
'''


t_pillow_read = timeit.timeit(stmt=s_pillow_read, setup=setup_pillow_read, number=ROUNDS)
print('Pillow read: {0:0.3f}ms'.format(t_pillow_read * 1000 / ROUNDS))

t_pillow_write = timeit.timeit(stmt=s_pillow_write, setup=setup_pillow_write, number=ROUNDS)
print('Pillow write: {0:0.3f}ms'.format(t_pillow_write * 1000 / ROUNDS))

t_opencv2_read = timeit.timeit(stmt=s_opencv_read, setup=setup_opencv_read, number=ROUNDS)
print('OpenCV read: {0:0.3f}ms'.format(t_opencv2_read * 1000 / ROUNDS))

t_opencv2_write = timeit.timeit(stmt=s_opencv_write, setup=setup_opencv_write, number=ROUNDS)
print('OpenCV write: {0:0.3f}ms'.format(t_opencv2_write * 1000 / ROUNDS))


