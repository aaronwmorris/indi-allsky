#import math
import numpy
import cv2
import logging


logger = logging.getLogger('indi_allsky')


class IndiAllSkyDraw(object):
    def __init__(self, config, mask=None):
        self.config = config

        self._sqm_mask_dict = mask

        self._draw_alpha_mask_dict = dict()
        for binning in self._sqm_mask_dict.keys():
            self._draw_alpha_mask_dict[binning] = None


    def main(self, data, binning):
        if not self.config.get('DETECT_DRAW'):
            return data


        image_height, image_width = data.shape[:2]


        if isinstance(self._draw_alpha_mask_dict[binning], type(None)):
            self._draw_alpha_mask_dict[binning] = self.generate_alpha_mask(data, binning)


        # apply mask to image
        data = (data * self._draw_alpha_mask_dict[binning]).astype(numpy.uint8)


        # flip image to draw text
        if self.config.get('IMAGE_FLIP_V'):
            data = cv2.flip(data, 0)

        if self.config.get('IMAGE_FLIP_H'):
            data = cv2.flip(data, 1)

        data = cv2.rotate(data, cv2.ROTATE_90_CLOCKWISE)


        self.drawText_opencv(data, 'MARK DETECTIONS ENABLED', (int((image_height / 2) - (image_height / 4)), 25), (200, 200, 200))


        # flip back to original
        data = cv2.rotate(data, cv2.ROTATE_90_COUNTERCLOCKWISE)

        if self.config.get('IMAGE_FLIP_V'):
            data = cv2.flip(data, 0)

        if self.config.get('IMAGE_FLIP_H'):
            data = cv2.flip(data, 1)


        ### Keogram meridian ###
        #logger.info('Draw keogram meridian')
        #if abs(self.config['KEOGRAM_ANGLE']) == 90.0:
        #    # line is straight across
        #    m_x1 = 0
        #    m_y1 = int(image_height / 2)
        #    m_x2 = image_width
        #    m_y2 = m_y1
        #else:
        #    opp_1 = math.tan(math.radians(self.config['KEOGRAM_ANGLE'])) * (image_height / 2)

        #    m_x1 = int(image_width / 2) + int(opp_1)
        #    m_y1 = 0
        #    m_x2 = int(image_width / 2) - int(opp_1)
        #    m_y2 = image_height


        #cv2.line(
        #    data,
        #    (m_x1, m_y1),
        #    (m_x2, m_y2),
        #    (64, 64, 64),
        #    3,
        #)


        return data


    def drawText_opencv(self, data, text, pt, color_bgr):
        fontFace = getattr(cv2, self.config['TEXT_PROPERTIES']['FONT_FACE'])
        lineType = getattr(cv2, self.config['TEXT_PROPERTIES']['FONT_AA'])

        if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
            cv2.putText(
                img=data,
                text=text,
                org=pt,
                fontFace=fontFace,
                color=(0, 0, 0),
                lineType=lineType,
                fontScale=self.config['TEXT_PROPERTIES']['FONT_SCALE'],
                thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'] + 1,
            )  # black outline
        cv2.putText(
            img=data,
            text=text,
            org=pt,
            fontFace=fontFace,
            color=tuple(color_bgr),
            lineType=lineType,
            fontScale=self.config['TEXT_PROPERTIES']['FONT_SCALE'],
            thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'],
        )


    def generate_alpha_mask(self, image, binning):
        alpha = (self._sqm_mask_dict[binning] / 255).astype(numpy.float32)

        # set excluded area to 75% opacity
        alpha[alpha == 0] = 0.75

        if len(image.shape) == 2:
            # mono
            return alpha

        # color
        return numpy.dstack((alpha, alpha, alpha))
