#!/usr/bin/env python3

from pathlib import Path
from datetime import datetime
from datetime import timezone
import math
import numpy
import cv2
import logging

import ephem

logging.basicConfig(level=logging.INFO)
logger = logging

LATITUDE = 33
LONGITUDE = -84


class MoonEllipse(object):

    full = (255, 255, 255)
    dark = (75, 75, 75)

    left_start = 180
    left_end = 360
    right_start = 0
    right_end = 180


    def __init__(self):
        moon_file = Path(__file__).parent.absolute().parent.joinpath('indi_allsky', 'flask', 'static', 'astropanel', 'img', 'moon_rot.png')

        self.moon = cv2.imread(str(moon_file), cv2.IMREAD_UNCHANGED)


    def main(self):
        utcnow = datetime.now(tz=timezone.utc)  # ephem expects UTC dates

        obs = ephem.Observer()
        obs.lon = math.radians(LONGITUDE)
        obs.lat = math.radians(LATITUDE)

        sun = ephem.Sun()
        moon = ephem.Moon()

        obs.date = utcnow
        sun.compute(obs)
        moon.compute(obs)


        sun_lon = ephem.Ecliptic(sun).lon
        moon_lon = ephem.Ecliptic(moon).lon
        sm_angle = (moon_lon - sun_lon) % math.tau


        #moon_quarter = int(sm_angle * 4.0 // math.tau)
        moon_cycle_percent = (sm_angle / math.tau) * 100
        logger.info('Moon cycle: %0.1f%%', moon_cycle_percent)


        height, width = self.moon.shape[:2]
        moon_radius = int((width / 2) - 15)


        ### Testing
        #moon_cycle_percent = 30

        if moon_cycle_percent <= 25:
            start_scale = self.full
            half_start = self.left_start
            half_end = self.left_end
            half_scale = self.dark
            crecent_scale = self.dark
            crecent_width = int(moon_radius - (moon_radius * (moon_cycle_percent / 25)))
        elif moon_cycle_percent <= 50:
            start_scale = self.dark
            half_start = self.right_start
            half_end = self.right_end
            half_scale = self.full
            crecent_scale = self.full
            crecent_width = int(moon_radius * ((moon_cycle_percent - 25) / 25))
        elif moon_cycle_percent <= 75:
            start_scale = self.dark
            half_start = self.left_start
            half_end = self.left_end
            half_scale = self.full
            crecent_scale = self.full
            crecent_width = int(moon_radius - (moon_radius * ((moon_cycle_percent - 50) / 25)))
        else:
            start_scale = self.full
            half_start = self.right_start
            half_end = self.right_end
            half_scale = self.dark
            crecent_scale = self.dark
            crecent_width = int(moon_radius * ((moon_cycle_percent - 75) / 25))



        mask = numpy.zeros([height, width, 3], dtype=numpy.uint8)

        mask = cv2.circle(
            mask,
            (int(height / 2), int(width / 2)),
            moon_radius,
            start_scale,
            cv2.FILLED,
        )


        ### cover half the moon
        mask = cv2.ellipse(
            mask,
            (int(height / 2), int(width / 2)),
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
            (int(height / 2), int(width / 2)),
            (moon_radius, crecent_width),
            270,
            0,
            360,
            crecent_scale,
            cv2.FILLED,
        )


        mask = (mask / 255).astype(numpy.float16)

        moon_bgr = self.moon[:, :, :3]
        moon_alpha = self.moon[:, :, 3]

        moon = (moon_bgr * mask).astype(numpy.uint8)

        final_moon = numpy.dstack((moon, moon_alpha))

        cv2.imwrite(str(Path(__file__).parent.joinpath('moon.png')), final_moon, [cv2.IMWRITE_PNG_COMPRESSION, 9])


if __name__ == "__main__":
    MoonEllipse().main()
