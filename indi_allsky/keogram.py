import cv2
import numpy
#import PIL
from PIL import Image
from PIL import ImageFont
from PIL import ImageDraw
import math
import time
#import copy
from datetime import datetime
from datetime import timezone
from pathlib import Path
import logging
from pprint import pformat

from .exceptions import KeogramMismatchException


logger = logging.getLogger('indi_allsky')


class KeogramGenerator(object):

    # label settings
    line_thickness = 2
    line_length = 35


    def __init__(self, config, skip_frames=0):
        self.config = config
        self.skip_frames = skip_frames

        self.process_count = 0

        self._angle = self.config['KEOGRAM_ANGLE']
        self._v_scale_factor = 100
        self._h_scale_factor = 100

        self._crop_top = 0
        self._crop_bottom = 0


        border_top = self.config.get('IMAGE_BORDER', {}).get('TOP', 0)
        border_left = self.config.get('IMAGE_BORDER', {}).get('LEFT', 0)
        border_right = self.config.get('IMAGE_BORDER', {}).get('RIGHT', 0)
        border_bottom = self.config.get('IMAGE_BORDER', {}).get('BOTTOM', 0)

        self._x_offset = self.config.get('LENS_OFFSET_X', 0) + int((border_left - border_right) / 2)
        self._y_offset = self.config.get('LENS_OFFSET_Y', 0) - int((border_top - border_bottom) / 2)
        #logger.info('X Offset: %d, Y Offset: %d', self.x_offset, self.y_offset)

        self._label = True


        self.original_width = None
        self.original_height = None

        self.rotated_width = None
        self.rotated_height = None

        self._keogram_data = None
        self._keogram_final = None  # will contain final resized keogram

        self._timestamps = list()
        self.image_processing_elapsed_s = 0

        base_path  = Path(__file__).parent
        self.font_path  = base_path.joinpath('fonts')


    @property
    def angle(self):
        return self._angle

    @angle.setter
    def angle(self, new_angle):
        self._angle = float(new_angle)


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


    @property
    def x_offset(self):
        return self._x_offset

    @x_offset.setter
    def x_offset(self, new_offset):
        self._x_offset = int(new_offset)

    @property
    def y_offset(self):
        return self._y_offset

    @y_offset.setter
    def y_offset(self, new_offset):
        self._y_offset = int(new_offset)


    @property
    def crop_top(self):
        return self._crop_top

    @crop_top.setter
    def crop_top(self, new_crop):
        self._crop_top = int(new_crop)


    @property
    def crop_bottom(self):
        return self._crop_bottom

    @crop_bottom.setter
    def crop_bottom(self, new_crop):
        self._crop_bottom = int(new_crop)


    @property
    def timestamps(self):
        return self._timestamps

    @timestamps.setter
    def timestamps(self, new_timestamps):
        self._timestamps = list(new_timestamps)


    @property
    def keogram_data(self):
        return self._keogram_data

    @keogram_data.setter
    def keogram_data(self, new_data):
        self._keogram_data = new_data


    @property
    def keogram_final(self):
        return self._keogram_final

    @keogram_final.setter
    def keogram_final(self, new_keogram):
        self._keogram_final = new_keogram


    @property
    def label(self):
        return self._label

    @label.setter
    def label(self, new_label):
        self._label = bool(new_label)


    @property
    def shape(self):
        return self.keogram_final.shape


    def processImage(self, image, timestamp):
        self.process_count += 1

        if self.process_count <= self.skip_frames:
            return

        image_processing_start = time.time()

        self.timestamps.append(timestamp)

        image_height, image_width = image.shape[:2]
        #logger.info('Original: %d x %d', image_width, image_height)


        recenter_width = image_width + (abs(self.x_offset) * 2)
        recenter_height = image_height + (abs(self.y_offset) * 2)
        #logger.info('New: %d x %d', recenter_width, recenter_height)


        recenter_image = numpy.zeros([recenter_height, recenter_width, 3], dtype=numpy.uint8)
        recenter_image[
            int((recenter_height / 2) - (image_height / 2) + self.y_offset):int((recenter_height / 2) + (image_height / 2) + self.y_offset),
            int((recenter_width / 2) - (image_width / 2) - self.x_offset):int((recenter_width / 2) + (image_width / 2) - self.x_offset),
        ] = image  # recenter the image circle in the new image


        ### Draw a crosshair for reference
        #cv2.line(f_image, (int(final_width / 2), 0), (int(final_width / 2), final_height), (0, 0, 128), 3)
        #cv2.line(f_image, (0, int(final_height / 2)), (final_width, int(final_height / 2)), (0, 0, 128), 3)
        #cv2.imwrite('/tmp/keogram_test.jpg', f_image, [cv2.IMWRITE_JPEG_QUALITY, 90])
        #raise Exception()


        rotated_image = self.rotate(recenter_image)


        rot_height, rot_width = rotated_image.shape[:2]
        self.rotated_height = rot_height
        self.rotated_width = rot_width

        rotated_center_line = rotated_image[:, [int(rot_width / 2)]]


        if isinstance(self.keogram_data, type(None)):
            # this only happens on the first image

            new_shape = rotated_center_line.shape
            logger.info('New Shape: %s', pformat(new_shape))

            new_dtype = rotated_center_line.dtype
            logger.info('New dtype: %s', new_dtype)

            self.keogram_data = numpy.empty(new_shape, dtype=new_dtype)


        #if recenter_height != self.original_height or recenter_width != self.original_width:
        #    # all images have to match dimensions of the first image
        #    logger.error('Image with dimension mismatch: %s', filename)
        #    return

        # will raise ValueError if dimensions do not match
        try:
            self.keogram_data = numpy.append(self.keogram_data, rotated_center_line, 1)
        except ValueError as e:
            raise KeogramMismatchException from e


        # set every image for reasons
        self.original_height = recenter_height
        self.original_width = recenter_width


        self.image_processing_elapsed_s += time.time() - image_processing_start


    def finalize(self, outfile, camera):
        import piexif

        outfile_p = Path(outfile)

        logger.info('Images processed for keogram in %0.1f s', self.image_processing_elapsed_s)

        # trim off the top and bottom bars
        keogram_trimmed = self.trimEdges(self.keogram_data)
        trimmed_height, trimmed_width = keogram_trimmed.shape[:2]


        # crop keogram
        if self.crop_top:
            crop_top_px = int(trimmed_height * self.crop_top / 100)
            logger.warning('Cropping %d px from top of keogram', crop_top_px)
        else:
            crop_top_px = 0


        if self.crop_bottom:
            crop_bottom_px = int(trimmed_height * self.crop_bottom / 100)
            logger.warning('Cropping %d px from bottom of keogram', crop_bottom_px)
        else:
            crop_bottom_px = 0


        keogram_cropped = keogram_trimmed[
            crop_top_px:trimmed_height - crop_bottom_px,
            0:trimmed_width,  # keep width
        ]

        cropped_height, cropped_width = keogram_cropped.shape[:2]


        # scale horizontal size
        new_width = int(cropped_width * self.h_scale_factor / 100)
        new_height = int(cropped_height * self.v_scale_factor / 100)
        self.keogram_final = cv2.resize(keogram_cropped, (new_width, new_height), interpolation=cv2.INTER_AREA)


        # apply time labels
        self.keogram_final = self.applyLabels(self.keogram_final)


        ### EXIF tags ###
        exp_date_utc = datetime.now(tz=timezone.utc)

        zeroth_ifd = {
            piexif.ImageIFD.Model            : camera.name,
            piexif.ImageIFD.Software         : 'indi-allsky',
        }
        exif_ifd = {
            piexif.ExifIFD.DateTimeOriginal  : exp_date_utc.strftime('%Y:%m:%d %H:%M:%S'),
            piexif.ExifIFD.LensModel         : camera.lensName,
        }


        jpeg_exif_dict = {
            '0th'   : zeroth_ifd,
            'Exif'  : exif_ifd,
        }


        if not self.config.get('IMAGE_EXIF_PRIVACY'):
            if camera.owner:
                zeroth_ifd[piexif.ImageIFD.Copyright] = camera.owner


            long_deg, long_min, long_sec = self.decdeg2dms(camera.longitude)
            lat_deg, lat_min, lat_sec = self.decdeg2dms(camera.latitude)

            if long_deg < 0:
                long_ref = 'W'
            else:
                long_ref = 'E'

            if lat_deg < 0:
                lat_ref = 'S'
            else:
                lat_ref = 'N'

            gps_datestamp = exp_date_utc.strftime('%Y:%m:%d')
            gps_hour   = int(exp_date_utc.strftime('%H'))
            gps_minute = int(exp_date_utc.strftime('%M'))
            gps_second = int(exp_date_utc.strftime('%S'))

            gps_ifd = {
                piexif.GPSIFD.GPSVersionID       : (2, 2, 0, 0),
                piexif.GPSIFD.GPSDateStamp       : gps_datestamp,
                piexif.GPSIFD.GPSTimeStamp       : ((gps_hour, 1), (gps_minute, 1), (gps_second, 1)),
                piexif.GPSIFD.GPSLongitudeRef    : long_ref,
                piexif.GPSIFD.GPSLongitude       : ((int(abs(long_deg)), 1), (int(long_min), 1), (0, 1)),  # no seconds
                piexif.GPSIFD.GPSLatitudeRef     : lat_ref,
                piexif.GPSIFD.GPSLatitude        : ((int(abs(lat_deg)), 1), (int(lat_min), 1), (0, 1)),  # no seconds
            }

            jpeg_exif_dict['GPS'] = gps_ifd


        jpeg_exif = piexif.dump(jpeg_exif_dict)


        write_img_start = time.time()

        logger.warning('Creating keogram: %s', outfile_p)
        if self.config['IMAGE_FILE_TYPE'] in ('jpg', 'jpeg'):
            # opencv is faster but we have exif data
            img_rgb = Image.fromarray(cv2.cvtColor(self.keogram_final, cv2.COLOR_BGR2RGB))
            img_rgb.save(str(outfile_p), quality=self.config['IMAGE_FILE_COMPRESSION']['jpg'], exif=jpeg_exif)
        elif self.config['IMAGE_FILE_TYPE'] in ('png',):
            #img_rgb = Image.fromarray(cv2.cvtColor(self.keogram_final, cv2.COLOR_BGR2RGB))
            #img_rgb.save(str(outfile_p), compress_level=self.config['IMAGE_FILE_COMPRESSION']['png'])

            # opencv is faster than Pillow with PNG
            cv2.imwrite(str(outfile_p), self.keogram_final, [cv2.IMWRITE_PNG_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION']['png']])
        elif self.config['IMAGE_FILE_TYPE'] in ('webp',):
            img_rgb = Image.fromarray(cv2.cvtColor(self.keogram_final, cv2.COLOR_BGR2RGB))
            img_rgb.save(str(outfile_p), quality=90, lossless=False, exif=jpeg_exif)
        elif self.config['IMAGE_FILE_TYPE'] in ('tif', 'tiff'):
            img_rgb = Image.fromarray(cv2.cvtColor(self.keogram_final, cv2.COLOR_BGR2RGB))
            img_rgb.save(str(outfile_p), compression='tiff_lzw')
        else:
            raise Exception('Unknown file type: %s', self.config['IMAGE_FILE_TYPE'])

        write_img_elapsed_s = time.time() - write_img_start
        logger.info('Image compressed in %0.4f s', write_img_elapsed_s)


        # set default permissions
        outfile_p.chmod(0o644)


    def decdeg2dms(self, dd):
        is_positive = dd >= 0
        dd = abs(dd)
        minutes, seconds = divmod(dd * 3600, 60)
        degrees, minutes = divmod(minutes, 60)
        degrees = degrees if is_positive else -degrees
        return degrees, minutes, seconds


    def rotate(self, image):
        height, width = image.shape[:2]
        center_x = int(width / 2)
        center_y = int(height / 2)

        rot = cv2.getRotationMatrix2D((center_x, center_y), self.angle, 1.0)

        abs_cos = abs(rot[0, 0])
        abs_sin = abs(rot[0, 1])

        bound_w = int(height * abs_sin + width * abs_cos)
        bound_h = int(height * abs_cos + width * abs_sin)

        rot[0, 2] += bound_w / 2 - center_x
        rot[1, 2] += bound_h / 2 - center_y

        rotated = cv2.warpAffine(image, rot, (bound_w, bound_h))

        return rotated


    def trimEdges(self, keogram):
        # if the rotation angle exceeds the diagonal angle of the original image, use the height as the hypotenuse
        switch_angle = 90 - math.degrees(math.atan(self.original_height / self.original_width))
        #logger.info('Switch angle: %0.2f', switch_angle)


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


        #logger.info('Trim angle: %d', c_angle)

        height, width = keogram.shape[:2]
        #logger.info('Keogram dimensions: %d x %d', width, height)
        #logger.info('Original keogram dimensions: %d x %d', self.original_width, self.original_height)
        #logger.info('Original rotated keogram dimensions: %d x %d', self.rotated_width, self.rotated_height)


        adj_1 = math.cos(math.radians(c_angle)) * hyp_1
        adj_2 = adj_1 - (self.rotated_width / 2)

        trim_height_pre = math.tan(math.radians(c_angle)) * adj_2

        # trim double the orb radius so they do not show up in the keograms
        trim_height = trim_height_pre + (self.config['ORB_PROPERTIES']['RADIUS'] * 2)

        trim_height_int = int(trim_height)
        #logger.info('Trim height: %d', trim_height_int)


        x1 = 0
        y1 = trim_height_int
        x2 = width
        y2 = height - trim_height_int

        #logger.info('Calculated trimmed area: (%d, %d) (%d, %d)', x1, y1, x2, y2)
        trimmed_keogram = keogram[
            y1:y2,
            x1:x2,
        ]

        trimmed_height, trimmed_width = trimmed_keogram.shape[:2]
        #logger.info('New trimmed keogram: %d x %d', trimmed_width, trimmed_height)

        return trimmed_keogram


    def applyLabels(self, keogram):
        if self.label:
            # Keogram labels enabled by default
            image_label_system = self.config.get('IMAGE_LABEL_SYSTEM', 'pillow')

            if image_label_system == 'opencv':
                keogram = self.applyLabels_opencv(keogram)
            else:
                # pillow is default
                keogram = self.applyLabels_pillow(keogram)
        else:
            #logger.warning('Keogram labels disabled')
            pass


        return keogram


    def applyLabels_opencv(self, keogram):
        height, width = keogram.shape[:2]

        # starting point
        last_time = datetime.fromtimestamp(self.timestamps[0])
        last_hour_str = last_time.strftime('%H')

        fontFace = getattr(cv2, self.config['TEXT_PROPERTIES']['FONT_FACE'])
        lineType = getattr(cv2, self.config['TEXT_PROPERTIES']['FONT_AA'])

        color_bgr = list(self.config['TEXT_PROPERTIES']['FONT_COLOR'])
        color_bgr.reverse()

        for i, u_ts in enumerate(self.timestamps):
            ts = datetime.fromtimestamp(u_ts)
            hour_str = ts.strftime('%H')

            if not hour_str != last_hour_str:
                continue

            last_hour_str = hour_str

            line_x = int(i * width / len(self.timestamps))

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


        return keogram


    def applyLabels_pillow(self, keogram):
        img_rgb = Image.fromarray(cv2.cvtColor(keogram, cv2.COLOR_BGR2RGB))
        width, height  = img_rgb.size  # backwards from opencv


        if self.config['TEXT_PROPERTIES']['PIL_FONT_FILE'] == 'custom':
            pillow_font_file_p = Path(self.config['TEXT_PROPERTIES']['PIL_FONT_CUSTOM'])
        else:
            pillow_font_file_p = self.font_path.joinpath(self.config['TEXT_PROPERTIES']['PIL_FONT_FILE'])


        pillow_font_size = self.config['TEXT_PROPERTIES']['PIL_FONT_SIZE']

        font = ImageFont.truetype(str(pillow_font_file_p), pillow_font_size)
        draw = ImageDraw.Draw(img_rgb)

        color_rgb = list(self.config['TEXT_PROPERTIES']['FONT_COLOR'])  # RGB for pillow


        # starting point
        last_time = datetime.fromtimestamp(self.timestamps[0])
        last_hour_str = last_time.strftime('%H')


        if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
            # black outline
            stroke_width = 4
        else:
            stroke_width = 0


        for i, u_ts in enumerate(self.timestamps):
            ts = datetime.fromtimestamp(u_ts)
            hour_str = ts.strftime('%H')

            if not hour_str != last_hour_str:
                continue

            last_hour_str = hour_str

            line_x = int(i * width / len(self.timestamps))

            line_start = (line_x, height)
            line_end = (line_x, height - self.line_length)


            if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
                draw.line(
                    ((line_start[0] - 2), (line_start[1] - 2), line_end),
                    fill=(0, 0, 0),
                    width=self.line_thickness + 5,  # +4
                )
            draw.line(
                (line_start, line_end),
                fill=tuple(color_rgb),
                width=self.line_thickness + 1,
            )


            draw.text(
                (line_x + 5, height - 3),
                hour_str,
                fill=tuple(color_rgb),
                font=font,
                stroke_width=stroke_width,
                stroke_fill=(0, 0, 0),
                anchor='ld',  # left-descender
            )


        # convert back to numpy array
        return cv2.cvtColor(numpy.array(img_rgb), cv2.COLOR_RGB2BGR)
