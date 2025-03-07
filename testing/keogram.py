#!/usr/bin/env python3

import cv2
import numpy
import PIL
from PIL import Image
import math
import argparse
import logging
import time
from datetime import datetime
from pathlib import Path
from pprint import pformat


logging.basicConfig(level=logging.INFO)
logger = logging



class KeogramGenerator(object):

    # label settings
    font_face = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.8
    font_thickness = 1
    line_length = 35
    line_color = (200, 200, 200)
    line_thickness = 2
    line_type = cv2.LINE_AA


    def __init__(self):
        self._angle = 0

        self._h_scale_factor = 33

        self.original_width = None
        self.original_height = None

        self.rotated_width = None
        self.rotated_height = None

        # We do not know the array dimensions until the first image is rotated
        self.keogram_data = None
        self.keogram_final = None  # will contain final resized keogram

        self.timestamps_list = list()
        self.image_processing_elapsed_s = 0


    @property
    def angle(self):
        return self._angle

    @angle.setter
    def angle(self, new_angle):
        self._angle = float(new_angle)


    @property
    def h_scale_factor(self):
        return self._h_scale_factor

    @h_scale_factor.setter
    def h_scale_factor(self, new_factor):
        self._h_scale_factor = int(new_factor)



    def main(self, outfile, inputdir):
        file_list = list()
        self.getFolderFilesByExt(inputdir, file_list)

        # Exclude empty files
        file_list_nonzero = filter(lambda p: p.stat().st_size != 0, file_list)

        # Sort by timestamp
        file_list_ordered = sorted(file_list_nonzero, key=lambda p: p.stat().st_mtime)


        processing_start = time.time()

        for filename in file_list_ordered:
            logger.info('Reading file: %s', filename)

            image_ts = filename.stat().st_mtime

            try:
                with Image.open(str(filename)) as img:
                    image = cv2.cvtColor(numpy.array(img), cv2.COLOR_RGB2BGR)
            except PIL.UnidentifiedImageError:
                logger.error('Unable to read %s', filename)
                continue


            try:
                self.processImage(image, image_ts)
            except ValueError as e:
                logger.error('Error processing keogram image: %s', str(e))


        self.finalize(outfile)

        processing_elapsed_s = time.time() - processing_start
        logger.warning('Total keogram processing in %0.1f s', processing_elapsed_s)


    def processImage(self, image, timestamp):
        image_processing_start = time.time()

        self.timestamps_list.append(timestamp)

        #logger.info('Data: %s', pformat(image))
        height, width = image.shape[:2]


        rotated_image = self.rotate(image)


        rot_height, rot_width = rotated_image.shape[:2]
        self.rotated_height = rot_height
        self.rotated_width = rot_width

        rotated_center_line = rotated_image[:, [int(rot_width / 2)]]
        #logger.info('Shape: %s', pformat(rotated_center_line.shape))
        #logger.info('Data: %s', pformat(rotated_center_line))
        #logger.info('Size: %s', pformat(rotated_center_line.size))


        if isinstance(self.keogram_data, type(None)):
            # this only happens on the first image

            new_shape = rotated_center_line.shape
            logger.info('New Shape: %s', pformat(new_shape))

            new_dtype = rotated_center_line.dtype
            logger.info('New dtype: %s', new_dtype)

            self.keogram_data = numpy.empty(new_shape, dtype=new_dtype)


        # will raise ValueError on dimension mismatch
        self.keogram_data = numpy.append(self.keogram_data, rotated_center_line, 1)


        # set every image for reasons
        self.original_height = height
        self.original_width = width


        self.image_processing_elapsed_s += time.time() - image_processing_start


    def finalize(self, outfile):
        logger.warning('Keogram images processed in %0.1f s', self.image_processing_elapsed_s)

        # trim bars at top and bottom
        trimmed_keogram = self.trimEdges(self.keogram_data)

        # scale horizontal
        trimmed_height, trimmed_width = trimmed_keogram.shape[:2]
        new_width = trimmed_width
        new_height = int(trimmed_height * self.h_scale_factor / 100)
        self.keogram_final = cv2.resize(trimmed_keogram, (new_width, new_height), interpolation=cv2.INTER_AREA)


        # apply time labels
        self.applyLabels(self.keogram_final)


        logger.warning('Creating labeled_trim_resize_%s', outfile)

        keogram_final_rgb = Image.fromarray(cv2.cvtColor(self.keogram_final, cv2.COLOR_BGR2RGB))
        keogram_final_rgb.save(str(outfile), quality=90)


    def rotate(self, image):
        height, width = image.shape[:2]
        center_x = int(width / 2)
        center_y = int(height / 2)

        rot = cv2.getRotationMatrix2D((center_x, center_y), self.angle, 1.0)
        #bbox = cv2.boundingRect2f((0, 0), image.size(), self.angle)

        #rot[0, 2] += bbox.width / 2.0 - image.cols / 2.0
        #rot[1, 2] += bbox.height / 2.0 - imagesrc.rows / 2.0

        abs_cos = abs(rot[0, 0])
        abs_sin = abs(rot[0, 1])

        bound_w = int(height * abs_sin + width * abs_cos)
        bound_h = int(height * abs_cos + width * abs_sin)

        rot[0, 2] += bound_w / 2 - center_x
        rot[1, 2] += bound_h / 2 - center_y

        #rotated = cv2.warpAffine(image, rot, bbox.size())
        rotated = cv2.warpAffine(image, rot, (bound_w, bound_h))

        return rotated


    def trimEdges(self, keogram):
        # if the rotation angle exceeds the diagonal angle of the original image, use the height as the hypotenuse
        switch_angle = 90 - math.degrees(math.atan(self.original_height / self.original_width))
        logger.info('Switch angle: %0.2f', switch_angle)


        angle_180_r = abs(self.angle) % 180
        if angle_180_r > 90:
            angle_90_r = 90 - (abs(self.angle) % 90)
        else:
            angle_90_r = abs(self.angle) % 90


        if angle_90_r < switch_angle:
            hyp_1 = self.original_width
            c_angle = angle_90_r
        else:
            hyp_1 = self.original_height
            c_angle = 90 - angle_90_r


        logger.info('Trim angle: %d', c_angle)

        height, width = keogram.shape[:2]
        logger.info('Keogram dimensions: %d x %d', width, height)
        logger.info('Original keogram dimensions: %d x %d', self.original_width, self.original_height)
        logger.info('Original rotated keogram dimensions: %d x %d', self.rotated_width, self.rotated_height)


        adj_1 = math.cos(math.radians(c_angle)) * hyp_1
        adj_2 = adj_1 - (self.rotated_width / 2)

        trim_height = math.tan(math.radians(c_angle)) * adj_2

        trim_height_int = int(trim_height)
        logger.info('Trim height: %d', trim_height_int)


        x1 = 0
        y1 = trim_height_int
        x2 = width
        y2 = height - trim_height_int

        logger.info('Calculated trimmed area: (%d, %d) (%d, %d)', x1, y1, x2, y2)
        trimmed_keogram = keogram[
            y1:y2,
            x1:x2,
        ]

        trimmed_height, trimmed_width = trimmed_keogram.shape[:2]
        logger.info('New trimmed keogram: %d x %d', trimmed_width, trimmed_height)

        return trimmed_keogram


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


    def applyLabels(self, keogram):
        height, width = keogram.shape[:2]

        # starting point
        last_time = datetime.fromtimestamp(self.timestamps_list[0])
        last_hour_str = last_time.strftime('%H')

        for i, u_ts in enumerate(self.timestamps_list):
            ts = datetime.fromtimestamp(u_ts)
            hour_str = ts.strftime('%H')

            if not hour_str != last_hour_str:
                continue

            last_hour_str = hour_str

            line_x = int(i * width / len(self.timestamps_list))

            line_start = (line_x, height)
            line_end = (line_x, height - self.line_length)

            cv2.line(
                img=keogram,
                pt1=line_start,
                pt2=line_end,
                color=(0, 0, 0),
                thickness=self.line_thickness + 1,
                lineType=self.line_type,
            )
            cv2.line(
                img=keogram,
                pt1=line_start,
                pt2=line_end,
                color=self.line_color,
                thickness=self.line_thickness,
                lineType=self.line_type,
            )


            cv2.putText(
                img=keogram,
                text=hour_str,
                org=(line_x + 5, height - 5),
                fontFace=self.font_face,
                color=(0, 0, 0),
                lineType=self.line_type,
                fontScale=self.font_scale,
                thickness=self.font_thickness + 1,
            )
            cv2.putText(
                img=keogram,
                text=hour_str,
                org=(line_x + 5, height - 5),
                fontFace=self.font_face,
                color=self.line_color,
                lineType=self.line_type,
                fontScale=self.font_scale,
                thickness=self.font_thickness,
            )


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'inputdir',
        help='Input directory',
        type=str,
    )
    argparser.add_argument(
        '--output',
        '-o',
        help='output',
        type=str,
        required=True,
    )
    argparser.add_argument(
        '--angle',
        '-a',
        help='angle [default: 45]',
        type=int,
        default=45,
    )


    args = argparser.parse_args()

    kg = KeogramGenerator()
    kg.angle = args.angle
    kg.main(args.output, args.inputdir)

