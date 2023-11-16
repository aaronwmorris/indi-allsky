import math
from pathlib import Path
import numpy
import cv2
from PIL import Image
from PIL import ImageFont
from PIL import ImageDraw
import logging

logger = logging.getLogger('indi_allsky')


class IndiAllskyCardinalDirsLabel(object):

    def __init__(self, config):
        self.config = config

        self.NORTH_CHAR = self.config.get('CARDINAL_DIRS', {}).get('CHAR_NORTH', 'N')
        self.EAST_CHAR  = self.config.get('CARDINAL_DIRS', {}).get('CHAR_EAST', 'E')
        self.WEST_CHAR  = self.config.get('CARDINAL_DIRS', {}).get('CHAR_WEST', 'W')
        self.SOUTH_CHAR = self.config.get('CARDINAL_DIRS', {}).get('CHAR_SOUTH', 'S')


        self.top_offset = self.config.get('CARDINAL_DIRS', {}).get('OFFSET_TOP', 3)
        self.left_offset = self.config.get('CARDINAL_DIRS', {}).get('OFFSET_LEFT', 5)
        self.right_offset = self.config.get('CARDINAL_DIRS', {}).get('OFFSET_RIGHT', 20)
        self.bottom_offset = self.config.get('CARDINAL_DIRS', {}).get('OFFSET_BOTTOM', 30)


        self._az = 0
        self._diameter = 0


        # most all sky lenses will flip the image horizontally and vertically
        self.az = self.config.get('LENS_AZIMUTH', 0) + 180

        self.diameter = self.config.get('CARDINAL_DIRS', {}).get('DIAMETER', 4000)


        if self.config['IMAGE_FLIP_V']:
            self.NORTH_CHAR, self.SOUTH_CHAR = self.SOUTH_CHAR, self.NORTH_CHAR

        if self.config.get('IMAGE_FLIP_H'):
            self.EAST_CHAR, self.WEST_CHAR = self.WEST_CHAR, self.EAST_CHAR


        # manual swap
        if self.config.get('CARDINAL_DIRS', {}).get('SWAP_NS'):
            self.NORTH_CHAR, self.SOUTH_CHAR = self.SOUTH_CHAR, self.NORTH_CHAR

        if self.config.get('CARDINAL_DIRS', {}).get('SWAP_EW'):
            self.EAST_CHAR, self.WEST_CHAR = self.WEST_CHAR, self.EAST_CHAR


        base_path  = Path(__file__).parent
        self.font_path  = base_path.joinpath('fonts')


    @property
    def az(self):
        return self._az

    @az.setter
    def az(self, new_az):
        self._az = float(new_az)


    @property
    def diameter(self):
        return self._diameter

    @diameter.setter
    def diameter(self, new_diameter):
        self._diameter = int(new_diameter)


    def main(self, image):

        coord_dict = dict()

        if self.NORTH_CHAR:
            coord_dict[self.NORTH_CHAR] = self.findDirectionCoordinate(image, self.az)

        if self.EAST_CHAR:
            coord_dict[self.EAST_CHAR]  = self.findDirectionCoordinate(image, self.az + 90)

        if self.WEST_CHAR:
            coord_dict[self.WEST_CHAR]  = self.findDirectionCoordinate(image, self.az - 90)

        if self.SOUTH_CHAR:
            coord_dict[self.SOUTH_CHAR] = self.findDirectionCoordinate(image, self.az + 180)


        image_label_system = self.config.get('IMAGE_LABEL_SYSTEM', 'pillow')

        if image_label_system == 'opencv':
            image = self.applyLabels_opencv(image, coord_dict)
        else:
            # pillow is default
            image = self.applyLabels_pillow(image, coord_dict)


        return image


    def findDirectionCoordinate(self, image, dir_az):
        height, width = image.shape[:2]

        if dir_az >= 360:
            angle = dir_az - 360
        elif dir_az < 0:
            angle = dir_az + 360
        else:
            angle = dir_az

        #logger.info('Finding direction angle for: %0.1f', angle)


        switch_angle = 90 - math.degrees(math.atan(height / width))
        #logger.info('Switch angle: %0.1f', switch_angle)


        angle_180_r = abs(angle) % 180
        if angle_180_r > 90:
            angle_90_r = 90 - (abs(angle) % 90)
        else:
            angle_90_r = abs(angle) % 90


        if angle_90_r < switch_angle:
            hyp = self.diameter / 2
            c_angle = angle_90_r
        else:
            hyp = self.diameter / 2
            c_angle = 90 - angle_90_r


        opp = math.sin(math.radians(c_angle)) * hyp
        #logger.info('Opposite: %d', int(opp))

        adj = math.cos(math.radians(c_angle)) * hyp
        #logger.info('Adjacent: %d', int(adj))


        if angle >= 0 and angle < switch_angle:
            #logger.info('Top right')
            d_x = (width / 2) + opp
            d_y = (height / 2) - adj
        elif angle >= switch_angle and angle < 90:
            #logger.info('Right top')
            d_x = (width / 2) + adj
            d_y = (height / 2) - opp
        elif angle >= 90 and angle < (180 - switch_angle):
            #logger.info('Right bottom')
            d_x = (width / 2) + adj
            d_y = (height / 2) + opp
        elif angle >= (180 - switch_angle) and angle < 180:
            #logger.info('Bottom right')
            d_x = (width / 2) + opp
            d_y = (height / 2) + adj
        elif angle >= 180 and angle < (180 + switch_angle):
            #logger.info('Bottom left')
            d_x = (width / 2) - opp
            d_y = (height / 2) + adj
        elif angle >= (180 + switch_angle) and angle < 270:
            #logger.info('Left bottom')
            d_x = (width / 2) - adj
            d_y = (height / 2) + opp
        elif angle >= 270 and angle < (360 - switch_angle):
            #logger.info('Left top')
            d_x = (width / 2) - adj
            d_y = (height / 2) - opp
        elif angle >= (360 - switch_angle) and angle < 360:
            #logger.info('Top left')
            d_x = (width / 2) - opp
            d_y = (height / 2) - adj


        return int(d_x), int(d_y)


    def applyLabels_opencv(self, image, coord_dict):
        height, width = image.shape[:2]

        # starting point
        fontFace = getattr(cv2, self.config['TEXT_PROPERTIES']['FONT_FACE'])
        lineType = getattr(cv2, self.config['TEXT_PROPERTIES']['FONT_AA'])

        color_bgr = list(self.config['CARDINAL_DIRS']['FONT_COLOR'])
        color_bgr.reverse()


        for k, v in coord_dict.items():
            x, y = v

            if x < self.left_offset:
                x = self.left_offset
            elif x > width - self.right_offset:
                x = width - self.right_offset

            if y < self.top_offset:
                y = self.top_offset
            elif y > height - self.bottom_offset:
                y = height - self.bottom_offset


            if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
                cv2.putText(
                    img=image,
                    text=k,
                    org=(x, y),
                    fontFace=fontFace,
                    color=(0, 0, 0),
                    lineType=lineType,
                    fontScale=self.config.get('CARDINAL_DIRS', {}).get('OPENCV_FONT_SCALE', 0.8),
                    thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'] + 1,
                )  # black outline
            cv2.putText(
                img=image,
                text=k,
                org=(x, y),
                fontFace=fontFace,
                color=tuple(color_bgr),
                lineType=lineType,
                fontScale=self.config.get('CARDINAL_DIRS', {}).get('OPENCV_FONT_SCALE', 0.8),
                thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'],
            )

        return image


    def applyLabels_pillow(self, image, coord_dict):
        img_rgb = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        width, height  = img_rgb.size  # backwards from opencv


        if self.config['TEXT_PROPERTIES']['PIL_FONT_FILE'] == 'custom':
            pillow_font_file_p = Path(self.config['TEXT_PROPERTIES']['PIL_FONT_CUSTOM'])
        else:
            pillow_font_file_p = self.font_path.joinpath(self.config['TEXT_PROPERTIES']['PIL_FONT_FILE'])


        pillow_font_size = self.config.get('CARDINAL_DIRS', {}).get('PIL_FONT_SIZE', 30)

        font = ImageFont.truetype(str(pillow_font_file_p), pillow_font_size)
        draw = ImageDraw.Draw(img_rgb)

        color_rgb = list(self.config['CARDINAL_DIRS']['FONT_COLOR'])  # RGB for pillow


        if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
            # black outline
            stroke_width = 4
        else:
            stroke_width = 0


        for k, v in coord_dict.items():
            x, y = v

            if x < self.left_offset:
                x = self.left_offset
            elif x > width - self.right_offset:
                x = width - self.right_offset

            if y < self.top_offset:
                y = self.top_offset
            elif y > height - self.bottom_offset:
                y = height - self.bottom_offset


            draw.text(
                (x, y),
                k,
                fill=tuple(color_rgb),
                font=font,
                stroke_width=stroke_width,
                stroke_fill=(0, 0, 0),
                anchor='mm',  # middle-middle
            )


        # convert back to numpy array
        return cv2.cvtColor(numpy.array(img_rgb), cv2.COLOR_RGB2BGR)
