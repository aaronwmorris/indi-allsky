#!/usr/bin/env python3


import argparse
from pathlib import Path
import io
import json
import numpy as np
import cv2
import rawpy
import logging


### Produce DNG and jpeg
# rpicam-still --immediate --nopreview --camera 0 --raw --denoise off --gain 1 --shutter 500000 --metadata metadata.json --metadata-format json --awbgains 1,1   --tuning-file /usr/share/libcamera/ipa/rpi/pisp/imx477.json --output input.jpg


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


    def main(self, input_file, output_file, metadata_file):
        input_file_p = Path(input_file)
        output_file_p = Path(output_file)
        metadata_file_p = Path(metadata_file)

        if input_file_p.suffix in ('.dng', '.DNG'):
            logger.info('Read %s', input_file_p)
            raw = rawpy.imread(str(input_file_p))
            raw_data_16 = raw.raw_image


            max_bits = self.detectBitDepth(raw_data_16)
            logger.info('Bits: %d', max_bits)


            logger.info('Subtract offset: %d', BLACK_LEVEL)
            black_level_scaled = BLACK_LEVEL >> (16 - max_bits)
            raw_data_16 = cv2.subtract(raw_data_16, black_level_scaled)


            logger.info('Debayer: %s', CFA)
            debayer_algorithm = self.__cfa_bgr_map[CFA]
            bgr_data_16 = cv2.cvtColor(raw_data_16, debayer_algorithm)


            ### CCM
            with io.open(metadata_file_p, 'r') as f_metadata:
                libcamera_metadata = json.loads(f_metadata.read())  # noqa: F841

            #bgr_data_16 = self.apply_color_correction_matrix(bgr_data_16, max_bits, libcamera_metadata)

            bgr_data_16 = self.apply_gamma_correction(bgr_data_16, max_bits, gamma=1.5)


            logger.info('Downsample to 8 bits')
            shift_factor = max_bits - 8
            bgr_data_8 = np.right_shift(bgr_data_16, shift_factor).astype(np.uint8)

        else:
            bgr_data_8 = cv2.imread(input_file_p)


        ### remove green bias
        bgr_data_8 = self.scnr_average_neutral(bgr_data_8)


        logger.info('Write %s', output_file_p)
        cv2.imwrite(output_file_p, bgr_data_8)


    def detectBitDepth(self, data):
        max_val = np.amax(data)
        logger.info('Image max value: %d', int(max_val))

        if max_val > 16383:
            return 16
        elif max_val > 4095:
            return 14
        elif max_val > 1023:
            return 12
        elif max_val > 255:
            return 10
        else:
            return 8


    def scnr_average_neutral(self, data):
        ### https://www.pixinsight.com/doc/legacy/LE/21_noise_reduction/scnr/scnr.html
        logger.info('Applying SCNR average neutral')
        b, g, r = cv2.split(data)

        # casting to uint16 (for uint8 data) to fix the magenta cast caused by overflows
        m = np.add(r.astype(np.uint16), b.astype(np.uint16)) * 0.5
        g = np.minimum(g, m.astype(np.uint8))

        return cv2.merge((b, g, r))


    def apply_color_correction_matrix(self, data, max_bits, libcamera_metadata):
        logger.info('Applying CCM')
        ccm = libcamera_metadata['ColourCorrectionMatrix']
        numpy_ccm = [
            [ccm[8], ccm[7], ccm[6]],
            [ccm[5], ccm[4], ccm[3]],
            [ccm[2], ccm[1], ccm[0]],
        ]


        ccm_image = np.matmul(data, np.array(numpy_ccm).T)


        max_value = (2 ** max_bits) - 1
        ccm_image[ccm_image > max_value] = max_value  # clip high end
        ccm_image[ccm_image < 0] = 0  # clip low end

        return ccm_image.astype(np.uint16)


    def apply_gamma_correction(self, data, max_bits, gamma=1.0):
        logger.info('Apply gamma correction')
        if max_bits == 8:
            numpy_dtype = np.uint8
        else:
            numpy_dtype = np.uint16


        data_max = (2 ** max_bits) - 1

        range_array = np.arange(0, data_max + 1, dtype=np.float32)
        lut = (((range_array / data_max) ** (1.0 / gamma)) * data_max).astype(numpy_dtype)


        return lut.take(data, mode='raise')


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'input',
        help='Input file',
        type=str,
    )
    argparser.add_argument(
        '--output',
        '-o',
        help='Output file (default: output.jpg)',
        type=str,
        default='output.jpg',
    )
    argparser.add_argument(
        '--metadata',
        '-m',
        help='Metadata file (default: metadata.json)',
        type=str,
        default='metadata.json',
    )


    args = argparser.parse_args()

    DNG2JPEG().main(args.input, args.output, args.metadata)
