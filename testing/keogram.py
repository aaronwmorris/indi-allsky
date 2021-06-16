#!/usr/bin/env python3

import cv2

filenames = (
    '20210613_234008.jpg',
    '20210613_234023.jpg',
    '20210613_234038.jpg',
    '20210613_234053.jpg',
    '20210613_234108.jpg',
    '20210613_234123.jpg',
    '20210613_234138.jpg',
    '20210613_234153.jpg',
)

ANGLE = 80

for filename in filenames:
    image = cv2.imread(filename, cv2.IMREAD_UNCHANGED)

    height, width = image.shape[:2]
    center = (width/2, height/2)

    rot = cv2.getRotationMatrix2D(center, ANGLE, 1.0)
    #bbox = cv2.boundingRect2f((0, 0), image.size(), ANGLE)

    #rot[0, 2] += bbox.width/2.0 - image.cols/2.0
    #rot[1, 2] += bbox.height/2.0 - imagesrc.rows/2.0

    abs_cos = abs(rot[0,0])
    abs_sin = abs(rot[0,1])

    bound_w = int(height * abs_sin + width * abs_cos)
    bound_h = int(height * abs_cos + width * abs_sin)

    rot[0, 2] += bound_w/2 - center[0]
    rot[1, 2] += bound_h/2 - center[1]

    #rotated = cv2.warpAffine(image, rot, bbox.size())
    rotated = cv2.warpAffine(image, rot, (bound_w, bound_h))

    cv2.imwrite('rot_{0:s}'.format(filename), rotated, [cv2.IMWRITE_JPEG_QUALITY, 90])

