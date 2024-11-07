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

    height = 200
    width = 200

    def __init__(self):
        moon_file = Path(__file__).parent.absolute().parent.joinpath('indi_allsky', 'flask', 'static', 'astropanel', 'img', 'moon.png')

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


        moon_quarter = int(sm_angle * 4.0 // math.tau)



        height, width = self.moon.shape[:2]


        mask = numpy.zeros([height, width, 3], dtype=numpy.uint8)

        mask = cv2.circle(
            mask,
            (int(height / 2), int(width / 2)),
            int(height / 2) - 15,
            (255, 255, 255),
            cv2.FILLED,
        )


        ### cover half the moon
        mask = cv2.ellipse(
            mask,
            (int(height / 2), int(width / 2)),
            (int(height / 2) - 15, int(width / 2) - 15),
            270,
            180,
            360,
            (75, 75, 75),
            cv2.FILLED,
            #cv2.LINE_AA,
        )


        ### crecent
        mask = cv2.ellipse(
            mask,
            (int(height / 2), int(width / 2)),
            (int(height / 2) - 15, 150),
            270,
            0,
            360,
            (75, 75, 75),
            cv2.FILLED,
            #cv2.LINE_AA,
        )

        mask = (mask / 255).astype(numpy.float16)

        moon_bgr = self.moon[:, :, :3]
        moon_alpha = self.moon[:, :, 3]

        moon = (moon_bgr * mask).astype(numpy.uint8)

        final_moon = numpy.dstack((moon, moon_alpha))

        cv2.imwrite('moon.png', final_moon, [cv2.IMWRITE_PNG_COMPRESSION, 9])


if __name__ == "__main__":
    MoonEllipse().main()
