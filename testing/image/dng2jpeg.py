#!/usr/bin/env python3


import io
import json
import numpy as np
import cv2
import rawpy
import logging


DNG_FILE = 'input.dng'
MAX_BITS = 16  # some cameras return data in 10/12/14 bit space
BLACK_LEVEL = 4096
CFA = 'BGGR'  # IMX477 CFA


logging.basicConfig(level=logging.INFO)
logger = logging


class DNG2JPEG(object):

    __cfa_bgr_map = {
        'RGGB' : cv2.COLOR_BAYER_BG2BGR,
        'GRBG' : cv2.COLOR_BAYER_GB2BGR,
        'BGGR' : cv2.COLOR_BAYER_RG2BGR,
        'GBRG' : cv2.COLOR_BAYER_GR2BGR,
    }


    def main(self):
        ### start
        logger.info('Read %s', DNG_FILE)
        raw = rawpy.imread(DNG_FILE)
        raw_data_16 = raw.raw_image


        logger.info('Subtract offset: %d', BLACK_LEVEL)
        black_level_scaled = BLACK_LEVEL >> (16 - MAX_BITS)
        raw_data_16 = cv2.subtract(raw_data_16, black_level_scaled)


        logger.info('Debayer: %s', CFA)
        debayer_algorithm = self.__cfa_bgr_map[CFA]
        bgr_data_16 = cv2.cvtColor(raw_data_16, debayer_algorithm)


        ### CCM
        with io.open('metadata.json', 'r') as f_metadata:
            libcamera_metadata = json.loads(f_metadata.read())  # noqa: F841

        #bgr_data_16 = self.apply_color_correction_matrix(bgr_data_16, libcamera_metadata)


        logger.info('Downsample to 8 bits')
        shift_factor = MAX_BITS - 8
        bgr_data_8 = np.right_shift(bgr_data_16, shift_factor).astype(np.uint8)


        ### if you want to read a jpeg instead
        #bgr_data_8 = cv2.imread('input.jpg')


        ### remove green bias
        bgr_data_8 = self.scnr_average_neutral(bgr_data_8)


        logger.info('Write output.jpg')
        cv2.imwrite('output.jpg', bgr_data_8, [cv2.IMWRITE_JPEG_QUALITY, 90])


    def scnr_average_neutral(self, data):
        ### https://www.pixinsight.com/doc/legacy/LE/21_noise_reduction/scnr/scnr.html
        logger.info('Applying SCNR average neutral')
        b, g, r = cv2.split(data)

        # casting to uint16 (for uint8 data) to fix the magenta cast caused by overflows
        m = np.add(r.astype(np.uint16), b.astype(np.uint16)) * 0.5
        g = np.minimum(g, m.astype(np.uint8))

        return cv2.merge((b, g, r))


    def apply_color_correction_matrix(self, data, libcamera_metadata):
        logger.info('Applying CCM')
        ccm = libcamera_metadata['ColourCorrectionMatrix']
        numpy_ccm = [
            [ccm[8], ccm[7], ccm[6]],
            [ccm[5], ccm[4], ccm[3]],
            [ccm[2], ccm[1], ccm[0]],
        ]


        ccm_image = np.matmul(data, np.array(numpy_ccm).T)


        max_value = (2 ** MAX_BITS) - 1
        ccm_image[ccm_image > max_value] = max_value  # clip high end
        ccm_image[ccm_image < 0] = 0  # clip low end

        return ccm_image.astype(np.uint16)


if __name__ == "__main__":
    DNG2JPEG().main()
