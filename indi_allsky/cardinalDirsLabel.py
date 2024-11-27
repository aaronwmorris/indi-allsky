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


        border_top = self.config.get('IMAGE_BORDER', {}).get('TOP', 0)
        border_left = self.config.get('IMAGE_BORDER', {}).get('LEFT', 0)
        border_right = self.config.get('IMAGE_BORDER', {}).get('RIGHT', 0)
        border_bottom = self.config.get('IMAGE_BORDER', {}).get('BOTTOM', 0)

        self.x_offset = self.config.get('LENS_OFFSET_X', 0) + int((border_left - border_right) / 2)
        self.y_offset = self.config.get('LENS_OFFSET_Y', 0) - int((border_top - border_bottom) / 2)


        self.top_offset = self.config.get('CARDINAL_DIRS', {}).get('OFFSET_TOP', 15)
        self.left_offset = self.config.get('CARDINAL_DIRS', {}).get('OFFSET_LEFT', 15)
        self.right_offset = self.config.get('CARDINAL_DIRS', {}).get('OFFSET_RIGHT', 15)
        self.bottom_offset = self.config.get('CARDINAL_DIRS', {}).get('OFFSET_BOTTOM', 15)
        self.panorama_bottom_offset = self.config.get('FISH2PANO', {}).get('DIRS_OFFSET_BOTTOM', 50)

        self.panorama_rotate_angle = self.config.get('FISH2PANO', {}).get('ROTATE_ANGLE', 0)


        self._az = 0
        self._diameter = 0


        # most all sky lenses will flip the image horizontally and vertically
        self.az = self.config.get('LENS_AZIMUTH', 0) + 180

        self.diameter = self.config.get('CARDINAL_DIRS', {}).get('DIAMETER', 3000)


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


        if self.config.get('CARDINAL_DIRS', {}).get('OUTLINE_CIRCLE'):
            self.drawCircle(image)


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


        # quadrants
        q1_height = (height / 2) + self.y_offset
        q1_width = (width / 2) - self.x_offset
        switch_angle_q1 = 90 - math.degrees(math.atan(q1_height / q1_width))

        q2_height = (height / 2) - self.y_offset
        q2_width = (width / 2) - self.x_offset
        switch_angle_q2 = 90 - math.degrees(math.atan(q2_height / q2_width))

        q3_height = (height / 2) - self.y_offset
        q3_width = (width / 2) + self.x_offset
        switch_angle_q3 = 90 - math.degrees(math.atan(q3_height / q3_width))

        q4_height = (height / 2) + self.y_offset
        q4_width = (width / 2) + self.x_offset
        switch_angle_q4 = 90 - math.degrees(math.atan(q4_height / q4_width))

        #logger.info('Switch angle 1: %0.1f', switch_angle_q1)
        #logger.info('Switch angle 2: %0.1f', switch_angle_q2)
        #logger.info('Switch angle 3: %0.1f', switch_angle_q3)
        #logger.info('Switch angle 4: %0.1f', switch_angle_q4)


        if angle >= 0 and angle < switch_angle_q1:
            #logger.info('Top right')
            opp, adj = self.getCircleOppAdj(angle, switch_angle_q1, q1_height, q1_width)
            d_x = (width / 2) + self.x_offset + opp
            d_y = (height / 2) - self.y_offset - adj
        elif angle >= switch_angle_q1 and angle < 90:
            #logger.info('Right top')
            opp, adj = self.getCircleOppAdj(angle, switch_angle_q1, q1_height, q1_width)
            d_x = (width / 2) + self.x_offset + adj
            d_y = (height / 2) - self.y_offset - opp
        elif angle >= 90 and angle < (180 - switch_angle_q2):
            #logger.info('Right bottom')
            opp, adj = self.getCircleOppAdj(angle, switch_angle_q2, q2_height, q2_width)
            d_x = (width / 2) + self.x_offset + adj
            d_y = (height / 2) - self.y_offset + opp
        elif angle >= (180 - switch_angle_q2) and angle < 180:
            #logger.info('Bottom right')
            opp, adj = self.getCircleOppAdj(angle, switch_angle_q2, q2_height, q2_width)
            d_x = (width / 2) + self.x_offset + opp
            d_y = (height / 2) - self.y_offset + adj
        elif angle >= 180 and angle < (180 + switch_angle_q3):
            #logger.info('Bottom left')
            opp, adj = self.getCircleOppAdj(angle, switch_angle_q3, q3_height, q3_width)
            d_x = (width / 2) + self.x_offset - opp
            d_y = (height / 2) - self.y_offset + adj
        elif angle >= (180 + switch_angle_q3) and angle < 270:
            #logger.info('Left bottom')
            opp, adj = self.getCircleOppAdj(angle, switch_angle_q3, q3_height, q3_width)
            d_x = (width / 2) + self.x_offset - adj
            d_y = (height / 2) - self.y_offset + opp
        elif angle >= 270 and angle < (360 - switch_angle_q4):
            #logger.info('Left top')
            opp, adj = self.getCircleOppAdj(angle, switch_angle_q4, q4_height, q4_width)
            d_x = (width / 2) + self.x_offset - adj
            d_y = (height / 2) - self.y_offset - opp
        elif angle >= (360 - switch_angle_q4) and angle < 360:
            #logger.info('Top left')
            opp, adj = self.getCircleOppAdj(angle, switch_angle_q4, q4_height, q4_width)
            d_x = (width / 2) + self.x_offset - opp
            d_y = (height / 2) - self.y_offset - adj


        return int(d_x), int(d_y)


    def getCircleOppAdj(self, angle, switch_angle, q_height, q_width):
        angle_180_r = abs(angle) % 180
        if angle_180_r > 90:
            angle_90_r = 90 - (abs(angle) % 90)
        else:
            angle_90_r = abs(angle) % 90


        radius = self.diameter / 2
        hyp = radius

        if angle_90_r < switch_angle:
            c_angle = angle_90_r

            adj = math.cos(math.radians(c_angle)) * hyp

            if adj <= radius:
                opp = math.sin(math.radians(c_angle)) * hyp
            else:
                adj = radius
                opp = math.tan(math.radians(c_angle)) * adj
        else:
            c_angle = 90 - angle_90_r

            adj = math.cos(math.radians(c_angle)) * hyp

            if adj <= radius:
                opp = math.sin(math.radians(c_angle)) * hyp
            else:
                adj = radius
                opp = math.tan(math.radians(c_angle)) * adj


        #logger.info('Opposite: %d', int(opp))
        #logger.info('Adjacent: %d', int(adj))

        return opp, adj


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


    def drawCircle(self, image):
        height, width = image.shape[:2]

        color_bgr = list(self.config['CARDINAL_DIRS']['FONT_COLOR'])
        color_bgr.reverse()

        pt = (
            int(width / 2) + self.x_offset,
            int(height / 2) - self.y_offset,
        )

        # center dot
        cv2.circle(
            img=image,
            center=pt,
            radius=5,
            color=color_bgr,
            thickness=cv2.FILLED,
        )

        # image circle outline
        cv2.circle(
            img=image,
            center=pt,
            radius=int(self.diameter / 2),
            color=color_bgr,
            thickness=1,
        )


    def panorama_label(self, image):
        height, width = image.shape[:2]


        coord_dict = dict()

        # the starting position of the panorama is 90 degrees clockwise
        if self.NORTH_CHAR:
            coord_dict[self.NORTH_CHAR]  = self.findPanoramaCoordinate(image, self.az - 90)

        if self.EAST_CHAR:
            coord_dict[self.EAST_CHAR] = self.findPanoramaCoordinate(image, self.az)

        if self.WEST_CHAR:
            coord_dict[self.WEST_CHAR] = self.findPanoramaCoordinate(image, self.az + 180)

        if self.SOUTH_CHAR:
            coord_dict[self.SOUTH_CHAR]  = self.findPanoramaCoordinate(image, self.az + 90)


        #logger.info('Panorama coords: %s', str(coord_dict))


        image_label_system = self.config.get('IMAGE_LABEL_SYSTEM', 'pillow')

        if image_label_system == 'opencv':
            #return self.applyLabels_opencv(image, coord_dict)
            return self.panorama_label_opencv(image, coord_dict)
        else:
            # pillow is default
            return self.panorama_label_pillow(image, coord_dict)


    def findPanoramaCoordinate(self, image, dir_az):
        height, width = image.shape[:2]

        dir_az -= self.panorama_rotate_angle

        if dir_az >= 360:
            angle = dir_az - 360
        elif dir_az < 0:
            angle = dir_az + 360
        else:
            angle = dir_az


        x = int(angle / 360 * width)
        y = height - self.panorama_bottom_offset


        if self.config.get('FISH2PANO', {}).get('FLIP_H'):
            x = width - x


        return x, y


    def panorama_label_opencv(self, image, coord_dict):
        height, width = image.shape[:2]

        fontFace = getattr(cv2, self.config['TEXT_PROPERTIES']['FONT_FACE'])
        lineType = getattr(cv2, self.config['TEXT_PROPERTIES']['FONT_AA'])

        color_bgr = list(self.config['CARDINAL_DIRS']['FONT_COLOR'])
        color_bgr.reverse()

        logger.info('Applying cardinal directions to panorama')

        for k, v in coord_dict.items():
            x, y = v


            if x < self.left_offset:
                x = self.left_offset
            elif x > width - self.right_offset:
                x = width - self.right_offset


            if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
                cv2.putText(
                    img=image,
                    text=k,
                    org=(x, y),
                    fontFace=fontFace,
                    color=(0, 0, 0),
                    lineType=lineType,
                    fontScale=self.config.get('FISH2PANO', {}).get('OPENCV_FONT_SCALE', 0.8),
                    thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'] + 1,
                )  # black outline
            cv2.putText(
                img=image,
                text=k,
                org=(x, y),
                fontFace=fontFace,
                color=tuple(color_bgr),
                lineType=lineType,
                fontScale=self.config.get('FISH2PANO', {}).get('OPENCV_FONT_SCALE', 0.8),
                thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'],
            )

        return image


    def panorama_label_pillow(self, image, coord_dict):
        img_rgb = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        width, height  = img_rgb.size  # backwards from opencv


        if self.config['TEXT_PROPERTIES']['PIL_FONT_FILE'] == 'custom':
            pillow_font_file_p = Path(self.config['TEXT_PROPERTIES']['PIL_FONT_CUSTOM'])
        else:
            pillow_font_file_p = self.font_path.joinpath(self.config['TEXT_PROPERTIES']['PIL_FONT_FILE'])


        pillow_font_size = self.config.get('FISH2PANO', {}).get('PIL_FONT_SIZE', 30)

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

