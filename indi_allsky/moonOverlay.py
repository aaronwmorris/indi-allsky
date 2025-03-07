#import time
import math
from pathlib import Path
import numpy
import cv2
import logging

logger = logging.getLogger('indi_allsky')


class IndiAllSkyMoonOverlay(object):

    full = (255, 255, 255)
    dark = (None, None, None)  # set later

    left_start = 180
    left_end = 360
    right_start = 0
    right_end = 180


    def __init__(self, config):
        self.config = config

        self.moon_file = Path(__file__).parent.joinpath('flask', 'static', 'astropanel', 'img', 'moon_rot.png')
        self.moon_orig = None


        self.scale = self.config.get('MOON_OVERLAY', {}).get('SCALE', 0.5)

        self.x = self.config.get('MOON_OVERLAY', {}).get('X', -500)
        self.y = self.config.get('MOON_OVERLAY', {}).get('Y', -200)

        self.flip_v = self.config.get('MOON_OVERLAY', {}).get('FLIP_V')
        self.flip_h = self.config.get('MOON_OVERLAY', {}).get('FLIP_H')

        self.dark_side_scale = self.config.get('MOON_OVERLAY', {}).get('DARK_SIDE_SCALE', 0.4)
        dark_ratio = int(self.dark_side_scale * 255)
        self.dark = (dark_ratio, dark_ratio, dark_ratio)


    def apply(self, image_data, moon_cycle_percent, moon_phase):
        if isinstance(self.moon_orig, type(None)):
            # moon data not loaded until it is needed
            self.moon_orig = cv2.imread(str(self.moon_file), cv2.IMREAD_UNCHANGED)


        #moon_overlay_start = time.time()

        moon = self.moon_orig.copy()


        ### Testing
        #moon_cycle_percent = 20
        #moon_phase = 44


        moon_height, moon_width = moon.shape[:2]
        moon_radius = int((moon_width / 2) - 15)  # ellipse_a
        #logger.info('Moon Radius: %d', moon_radius)


        moon_area = math.pi * (moon_radius ** 2)
        #logger.info('Moon area: %0.2f', moon_area)


        if moon_cycle_percent <= 25:
            start_scale = self.full
            half_start = self.left_start
            half_end = self.left_end
            half_scale = self.dark
            crecent_scale = self.dark

            ellipse_area = (moon_area * ((1 - (moon_phase / 100)) - 0.5)) * 2
            #logger.info('Ellipse area: %0.2f', ellipse_area)
            ellipse_b = int(ellipse_area / (math.pi * moon_radius))
        elif moon_cycle_percent <= 50:
            start_scale = self.dark
            half_start = self.right_start
            half_end = self.right_end
            half_scale = self.full
            crecent_scale = self.full

            ellipse_area = (moon_area * ((moon_phase / 100) - 0.5)) * 2
            #logger.info('Ellipse area: %0.2f', ellipse_area)
            ellipse_b = int(ellipse_area / (math.pi * moon_radius))
        elif moon_cycle_percent <= 75:
            start_scale = self.dark
            half_start = self.left_start
            half_end = self.left_end
            half_scale = self.full
            crecent_scale = self.full

            ellipse_area = (moon_area * ((moon_phase / 100) - 0.5)) * 2
            #logger.info('Ellipse area: %0.2f', ellipse_area)
            ellipse_b = int(ellipse_area / (math.pi * moon_radius))
        else:
            start_scale = self.full
            half_start = self.right_start
            half_end = self.right_end
            half_scale = self.dark
            crecent_scale = self.dark

            ellipse_area = (moon_area * ((1 - (moon_phase / 100)) - 0.5)) * 2
            #logger.info('Ellipse area: %0.2f', ellipse_area)
            ellipse_b = int(ellipse_area / (math.pi * moon_radius))


        #logger.info('Ellipse B: %d', ellipse_b)


        mask = numpy.zeros([moon_height, moon_width, 3], dtype=numpy.uint8)

        mask = cv2.circle(
            mask,
            (int(moon_height / 2), int(moon_width / 2)),
            moon_radius,
            start_scale,
            cv2.FILLED,
        )


        ### cover half the moon
        mask = cv2.ellipse(
            mask,
            (int(moon_height / 2), int(moon_width / 2)),
            (moon_radius, moon_radius),
            270,
            half_start,
            half_end,
            half_scale,
            cv2.FILLED,
        )


        ### crecent
        mask = cv2.ellipse(
            mask,
            (int(moon_height / 2), int(moon_width / 2)),
            (moon_radius, ellipse_b),
            270,
            0,
            360,
            crecent_scale,
            cv2.FILLED,
        )


        mask = (mask / 255).astype(numpy.float32)

        moon_bgr = moon[:, :, :3]
        moon_alpha = moon[:, :, 3]

        moon = (moon_bgr * mask).astype(numpy.uint8)

        moon = numpy.dstack((moon, moon_alpha))


        # scale image
        new_moon_width = int(moon_width * self.scale)
        new_moon_height = int(moon_height * self.scale)
        moon = cv2.resize(moon, (new_moon_width, new_moon_height), interpolation=cv2.INTER_AREA)


        if self.flip_v:
            moon = cv2.flip(moon, 0)

        if self.flip_h:
            moon = cv2.flip(moon, 1)


        image_height, image_width = image_data.shape[:2]

        # calculate coordinates
        if self.x < 0:
            x = image_width + self.x  # minus
        else:
            x = self.x

        if self.y < 0:
            y = image_height + self.y  # minus
        else:
            y = self.y


        # sanity check coordinates
        if x > image_width - new_moon_width:
            logger.error('Moon overlay X offset places moon outside image boundary')
            x = image_width - new_moon_width

        if y > image_height - new_moon_height:
            logger.error('Moon overlay Y offset places moon outside image boundary')
            y = image_height - new_moon_height



        # extract are where moon is to be applied
        image_crop = image_data[
            y:y + new_moon_height,
            x:x + new_moon_width,
        ]


        moon_bgr = moon[:, :, :3]
        moon_alpha = (moon[:, :, 3] / 255).astype(numpy.float32)


        # create alpha mask
        alpha_mask = numpy.dstack((
            moon_alpha,
            moon_alpha,
            moon_alpha,
        ))


        # apply alpha mask
        image_crop = (image_crop * (1 - alpha_mask) + moon_bgr * alpha_mask).astype(numpy.uint8)


        # add overlayed moon area back to image
        image_data[
            y:y + new_moon_height,
            x:x + new_moon_width,
        ] = image_crop


        #moon_overlay_elapsed_s = time.time() - moon_overlay_start
        #logger.warning('Moon Overlay processing in %0.4f s', moon_overlay_elapsed_s)

