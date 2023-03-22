import math
import cv2
import logging


logger = logging.getLogger('indi_allsky')


class IndiAllSkyDraw(object):
    def __init__(self, config, bin_v, mask=None):
        self.config = config
        self.bin_v = bin_v

        self._sqm_mask = mask


    def main(self, sep_data):
        if not self.config.get('DETECT_DRAW'):
            return sep_data

        image_height, image_width = sep_data.shape[:2]


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
                adu_x1 = int((image_width / 2) - (image_width / 3))
                adu_y1 = int((image_height / 2) - (image_height / 3))
                adu_x2 = int((image_width / 2) + (image_width / 3))
                adu_y2 = int((image_height / 2) + (image_height / 3))


            logger.info('Draw box around ADU_ROI')
            cv2.rectangle(
                img=sep_data,
                pt1=(adu_x1, adu_y1),
                pt2=(adu_x2, adu_y2),
                color=(128, 128, 128),
                thickness=1,
            )
        else:
            # apply mask to image
            sep_data = cv2.bitwise_and(sep_data, sep_data, mask=self._sqm_mask)


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
            sep_data,
            (m_x1, m_y1),
            (m_x2, m_y2),
            (64, 64, 64),
            3,
        )


        return sep_data

