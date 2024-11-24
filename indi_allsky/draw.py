import math
import cv2
import logging


logger = logging.getLogger('indi_allsky')


class IndiAllSkyDraw(object):
    def __init__(self, config, bin_v, mask=None):
        self.config = config
        self.bin_v = bin_v

        self._sqm_mask = mask


    def main(self, data):
        if not self.config.get('DETECT_DRAW'):
            return data


        image_height, image_width = data.shape[:2]


        self.drawText_opencv(data, 'MARK DETECTIONS ENABLED', (int(image_width / 3), 25), (200, 200, 200))


        ### ADU ROI ###
        if isinstance(self._sqm_mask, type(None)):
            ### Draw ADU ROI if detection mask is not defined
            ###  Make sure the box calculation matches image.py
            adu_roi = self.config.get('ADU_ROI', [])

            try:
                adu_x1 = int(adu_roi[0] / self.bin_v.value)
                adu_y1 = int(adu_roi[1] / self.bin_v.value)
                adu_x2 = int(adu_roi[2] / self.bin_v.value)
                adu_y2 = int(adu_roi[3] / self.bin_v.value)
            except IndexError:
                adu_fov_div = self.config.get('ADU_FOV_DIV', 4)
                adu_x1 = int((image_width / 2) - (image_width / adu_fov_div))
                adu_y1 = int((image_height / 2) - (image_height / adu_fov_div))
                adu_x2 = int((image_width / 2) + (image_width / adu_fov_div))
                adu_y2 = int((image_height / 2) + (image_height / adu_fov_div))


            logger.info('Draw box around ADU_ROI')
            cv2.rectangle(
                img=data,
                pt1=(adu_x1, adu_y1),
                pt2=(adu_x2, adu_y2),
                color=(128, 128, 128),
                thickness=1,
            )
        else:
            # apply mask to image
            data = cv2.bitwise_and(data, data, mask=self._sqm_mask)


        ### Keogram meridian ###
        logger.info('Draw keogram meridian')
        if abs(self.config['KEOGRAM_ANGLE']) == 90.0:
            # line is straight across
            m_x1 = 0
            m_y1 = int(image_height / 2)
            m_x2 = image_width
            m_y2 = m_y1
        else:
            opp_1 = math.tan(math.radians(self.config['KEOGRAM_ANGLE'])) * (image_height / 2)

            m_x1 = int(image_width / 2) + int(opp_1)
            m_y1 = 0
            m_x2 = int(image_width / 2) - int(opp_1)
            m_y2 = image_height


        cv2.line(
            data,
            (m_x1, m_y1),
            (m_x2, m_y2),
            (64, 64, 64),
            3,
        )


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

