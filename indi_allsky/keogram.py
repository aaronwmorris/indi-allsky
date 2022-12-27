import cv2
import numpy
import math
import time
#import copy
from datetime import datetime
from pathlib import Path
import logging
from pprint import pformat


logger = logging.getLogger('indi_allsky')


class KeogramGenerator(object):

    # label settings
    line_thickness = 2
    line_length = 35


    def __init__(self, config):
        self.config = config

        self._angle = self.config['KEOGRAM_ANGLE']
        self._v_scale_factor = 100
        self._h_scale_factor = 100

        self.original_width = None
        self.original_height = None

        self.rotated_width = None
        self.rotated_height = None

        self.keogram_data = None

        self.timestamps_list = list()
        self.image_processing_elapsed_s = 0


    @property
    def angle(self):
        return self._angle

    @angle.setter
    def angle(self, new_angle):
        self._angle = new_angle


    @property
    def v_scale_factor(self):
        return self._v_scale_factor

    @v_scale_factor.setter
    def v_scale_factor(self, new_factor):
        self._v_scale_factor = int(new_factor)


    @property
    def h_scale_factor(self):
        return self._h_scale_factor

    @h_scale_factor.setter
    def h_scale_factor(self, new_factor):
        self._h_scale_factor = int(new_factor)


    def generate(self, outfile, file_list):
        # Exclude empty files
        file_list_nonzero = filter(lambda p: p.stat().st_size != 0, file_list)

        # Sort by timestamp
        file_list_ordered = sorted(file_list_nonzero, key=lambda p: p.stat().st_mtime)


        processing_start = time.time()

        for filename in file_list_ordered:
            logger.info('Reading file: %s', filename)
            image = cv2.imread(str(filename), cv2.IMREAD_UNCHANGED)

            if isinstance(image, type(None)):
                logger.error('Unable to read %s', filename)
                continue

            self.processImage(filename, image)


        self.finalize(outfile)

        processing_elapsed_s = time.time() - processing_start
        logger.warning('Total keogram processing in %0.1f s', processing_elapsed_s)


    def processImage(self, filename, image):
        image_processing_start = time.time()

        self.timestamps_list.append(filename.stat().st_mtime)

        height, width = image.shape[:2]
        self.original_height = height
        self.original_width = width


        rotated_image = self.rotate(image)
        del image


        rot_height, rot_width = rotated_image.shape[:2]
        self.rotated_height = rot_height
        self.rotated_width = rot_width

        rotated_center_line = rotated_image[:, [int(rot_width / 2)]]

        if isinstance(self.keogram_data, type(None)):
            new_shape = rotated_center_line.shape
            logger.info('New Shape: %s', pformat(new_shape))

            new_dtype = rotated_center_line.dtype
            logger.info('New dtype: %s', new_dtype)

            self.keogram_data = numpy.empty(new_shape, dtype=new_dtype)

        self.keogram_data = numpy.append(self.keogram_data, rotated_center_line, 1)

        self.image_processing_elapsed_s += time.time() - image_processing_start


    def finalize(self, outfile):
        outfile_p = Path(outfile)

        logger.info('Images processed for keogram in %0.1f s', self.image_processing_elapsed_s)

        # trim off the top and bottom bars
        keogram_trimmed = self.trimEdges(self.keogram_data)

        # scale horizontal size
        trimmed_height, trimmed_width = keogram_trimmed.shape[:2]
        new_width = int(trimmed_width * self._h_scale_factor / 100)
        new_height = int(trimmed_height * self._v_scale_factor / 100)
        keogram_resized = cv2.resize(keogram_trimmed, (new_width, new_height), interpolation=cv2.INTER_AREA)

        # apply time labels
        self.applyLabels(keogram_resized)


        write_img_start = time.time()

        logger.warning('Creating keogram: %s', outfile_p)
        if self.config['IMAGE_FILE_TYPE'] in ('jpg', 'jpeg'):
            cv2.imwrite(str(outfile_p), keogram_resized, [cv2.IMWRITE_JPEG_QUALITY, self.config['IMAGE_FILE_COMPRESSION']['jpg']])
        elif self.config['IMAGE_FILE_TYPE'] in ('png',):
            cv2.imwrite(str(outfile_p), keogram_resized, [cv2.IMWRITE_PNG_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION']['png']])
        elif self.config['IMAGE_FILE_TYPE'] in ('tif', 'tiff'):
            cv2.imwrite(str(outfile_p), keogram_resized, [cv2.IMWRITE_TIFF_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION']['tif']])
        else:
            raise Exception('Unknown file type: %s', self.config['IMAGE_FILE_TYPE'])

        write_img_elapsed_s = time.time() - write_img_start
        logger.info('Image compressed in %0.4f s', write_img_elapsed_s)


        # set default permissions
        outfile_p.chmod(0o644)


    def rotate(self, image):
        height, width = image.shape[:2]
        center = (width / 2, height / 2)

        rot = cv2.getRotationMatrix2D(center, self._angle, 1.0)

        abs_cos = abs(rot[0, 0])
        abs_sin = abs(rot[0, 1])

        bound_w = int(height * abs_sin + width * abs_cos)
        bound_h = int(height * abs_cos + width * abs_sin)

        rot[0, 2] += bound_w / 2 - center[0]
        rot[1, 2] += bound_h / 2 - center[1]

        rotated = cv2.warpAffine(image, rot, (bound_w, bound_h))

        return rotated


    def trimEdges(self, image):
        # if the rotation angle exceeds the diagonal angle of the original image, use the height as the hypotenuse
        switch_angle = 90 - math.degrees(math.atan(self.original_height / self.original_width))
        logger.info('Switch angle: %0.2f', switch_angle)


        angle_180_r = abs(self._angle) % 180
        if angle_180_r > 90:
            angle_90_r = 90 - (abs(self._angle) % 90)
        else:
            angle_90_r = abs(self._angle) % 90


        if angle_90_r < switch_angle:
            hyp_1 = self.original_width
            c_angle = angle_90_r
        else:
            hyp_1 = self.original_height
            c_angle = 90 - angle_90_r


        logger.info('Trim angle: %d', c_angle)

        height, width = image.shape[:2]
        logger.info('Keogram dimensions: %d x %d', width, height)
        logger.info('Original image dimensions: %d x %d', self.original_width, self.original_height)
        logger.info('Original rotated image dimensions: %d x %d', self.rotated_width, self.rotated_height)


        adj_1 = math.cos(math.radians(c_angle)) * hyp_1
        adj_2 = adj_1 - (self.rotated_width / 2)

        trim_height_pre = math.tan(math.radians(c_angle)) * adj_2

        # trim double the orb radius so they do not show up in the keograms
        trim_height = trim_height_pre + (self.config['ORB_PROPERTIES']['RADIUS'] * 2)

        trim_height_int = int(trim_height)
        logger.info('Trim height: %d', trim_height_int)


        x1 = 0
        y1 = trim_height_int
        x2 = width
        y2 = height - trim_height_int

        logger.info('Calculated trimmed area: (%d, %d) (%d, %d)', x1, y1, x2, y2)
        trimmed_image = image[
            y1:y2,
            x1:x2,
        ]

        trimmed_height, trimmed_width = trimmed_image.shape[:2]
        logger.info('New trimmed image: %d x %d', trimmed_width, trimmed_height)

        return trimmed_image


    def applyLabels(self, keogram):
        # Keogram labels enabled by default
        if not self.config.get('KEOGRAM_LABEL', True):
            logger.warning('Keogram labels disabled')
            return

        # Legacy setting, code to be removed
        if not self.config['TEXT_PROPERTIES'].get('FONT_FACE'):
            logger.warning('Image labels disabled')
            return

        height, width = keogram.shape[:2]

        # starting point
        last_time = datetime.fromtimestamp(self.timestamps_list[0])
        last_hour_str = last_time.strftime('%H')

        fontFace = getattr(cv2, self.config['TEXT_PROPERTIES']['FONT_FACE'])
        lineType = getattr(cv2, self.config['TEXT_PROPERTIES']['FONT_AA'])

        color_bgr = list(self.config['TEXT_PROPERTIES']['FONT_COLOR'])
        color_bgr.reverse()

        for i, u_ts in enumerate(self.timestamps_list):
            ts = datetime.fromtimestamp(u_ts)
            hour_str = ts.strftime('%H')

            if not hour_str != last_hour_str:
                continue

            last_hour_str = hour_str

            line_x = int(i * width / len(self.timestamps_list))

            line_start = (line_x, height)
            line_end = (line_x, height - self.line_length)


            if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
                cv2.line(
                    img=keogram,
                    pt1=line_start,
                    pt2=line_end,
                    color=(0, 0, 0),
                    thickness=self.line_thickness + 1,
                    lineType=lineType,
                )  # black outline
            cv2.line(
                img=keogram,
                pt1=line_start,
                pt2=line_end,
                color=tuple(color_bgr),
                thickness=self.line_thickness,
                lineType=lineType,
            )


            if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
                cv2.putText(
                    img=keogram,
                    text=hour_str,
                    org=(line_x + 5, height - 5),
                    fontFace=fontFace,
                    color=(0, 0, 0),
                    lineType=lineType,
                    fontScale=self.config['TEXT_PROPERTIES']['FONT_SCALE'],
                    thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'] + 1,
                )  # black outline
            cv2.putText(
                img=keogram,
                text=hour_str,
                org=(line_x + 5, height - 5),
                fontFace=fontFace,
                color=tuple(color_bgr),
                lineType=lineType,
                fontScale=self.config['TEXT_PROPERTIES']['FONT_SCALE'],
                thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'],
            )

