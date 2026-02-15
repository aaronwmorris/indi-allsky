#import math
import cv2
import logging


logger = logging.getLogger('indi_allsky')


class IndiAllSkyDraw(object):
    def __init__(self, config, mask=None):
        self.config = config

        self._sqm_mask_dict = mask

        self._draw_mask_dict = dict()
        for binning in self._sqm_mask_dict.keys():
            self._draw_mask_dict[binning] = None


    def main(self, data, binning):
        if not self.config.get('DETECT_DRAW'):
            return data


        image_height, image_width = data.shape[:2]


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


        if not isinstance(self._sqm_mask_dict[binning], type(None)):
            self._draw_mask_dict[binning] = self._sqm_mask_dict[binning]


        ### ADU & SQM ROI ###
        if isinstance(self._draw_mask_dict, type(None)):

            ### Draw ADU ROI if detection mask is not defined
            ###  Make sure the box calculation matches image.py
            logger.info('Draw box around ADU_ROI and SQM_ROI')


            adu_roi = self.config.get('ADU_ROI', [])

            try:
                adu_x1 = int(adu_roi[0] / binning)
                adu_y1 = int(adu_roi[1] / binning)
                adu_x2 = int(adu_roi[2] / binning)
                adu_y2 = int(adu_roi[3] / binning)
            except IndexError:
                adu_fov_div = self.config.get('ADU_FOV_DIV', 4)
                adu_x1 = int((image_width / 2) - (image_width / adu_fov_div))
                adu_y1 = int((image_height / 2) - (image_height / adu_fov_div))
                adu_x2 = int((image_width / 2) + (image_width / adu_fov_div))
                adu_y2 = int((image_height / 2) + (image_height / adu_fov_div))


            cv2.rectangle(
                img=data,
                pt1=(adu_x1, adu_y1),
                pt2=(adu_x2, adu_y2),
                color=(128, 64, 64),
                thickness=1,
            )


            sqm_roi = self.config.get('SQM_ROI', [])

            try:
                sqm_x1 = int(sqm_roi[0] / binning)
                sqm_y1 = int(sqm_roi[1] / binning)
                sqm_x2 = int(sqm_roi[2] / binning)
                sqm_y2 = int(sqm_roi[3] / binning)
            except IndexError:
                sqm_fov_div = self.config.get('SQM_FOV_DIV', 4)
                sqm_x1 = int((image_width / 2) - (image_width / sqm_fov_div))
                sqm_y1 = int((image_height / 2) - (image_height / sqm_fov_div))
                sqm_x2 = int((image_width / 2) + (image_width / sqm_fov_div))
                sqm_y2 = int((image_height / 2) + (image_height / sqm_fov_div))


            cv2.rectangle(
                img=data,
                pt1=(sqm_x1, sqm_y1),
                pt2=(sqm_x2, sqm_y2),
                color=(64, 64, 128),
                thickness=1,
            )

        else:
            # apply mask to image
            data = cv2.bitwise_and(data, data, mask=self._draw_mask_dict[binning])


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

