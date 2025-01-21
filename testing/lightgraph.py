#!/usr/bin/env python3

import math
from datetime import datetime
from datetime import timedelta
import time
import ephem
import numpy
import cv2
import logging


LATITUDE  = 73
LONGITUDE = -84



logging.basicConfig(level=logging.INFO)
logger = logging


class LightGraphGenerator(object):

    # no color should be black (0, 0, 0)
    graph_height = 50
    graph_border = 3
    text_area_height = 40
    now_size = 8
    light_color = (200, 200, 200)
    dark_color = (15, 15, 15)
    line_color = (15, 15, 200)
    border_color = (1, 1, 1)
    now_color = (15, 150, 200)

    font_face = cv2.FONT_HERSHEY_SIMPLEX
    font_color = (200, 200, 200)
    font_scale = 0.8
    font_thickness = 1
    line_type = cv2.LINE_AA


    def __init__(self):
        self.obs = ephem.Observer()
        self.obs.lon = math.radians(LONGITUDE)
        self.obs.lat = math.radians(LATITUDE)

        # disable atmospheric refraction calcs
        self.obs.pressure = 0

        self.sun = ephem.Sun()
        self.moon = ephem.Moon()


        self.utc_offset = None
        self.next_generate = None


    def main(self):
        #utcnow_notz = now - utc_offset
        lightgraph = self.generate()

        #logger.info(lightgraph.shape)
        graph_height, graph_width = lightgraph.shape[:2]


        now = datetime.now()
        noon = datetime.strptime(now.strftime('%Y%m%d12'), '%Y%m%d%H')

        now_offset = int((now - noon).seconds / 60) + self.graph_border
        #logger.info('Now offset: %d', now_offset)


        # draw now triangle
        now_tri = numpy.array([
            (now_offset - self.now_size, graph_height - ((self.graph_border + self.graph_height) - self.now_size)),
            (now_offset + self.now_size, graph_height - ((self.graph_border + self.graph_height) - self.now_size)),
            (now_offset, graph_height - (self.graph_border + self.graph_height)),
        ],
            dtype=numpy.int32,
        )
        #logger.info(now_tri)

        cv2.fillPoly(
            img=lightgraph,
            pts=[now_tri],
            color=self.now_color,
        )


        # create alpha channel, anything pixel that is full black (0, 0, 0) is transparent
        alpha = numpy.max(lightgraph, axis=2)
        alpha[alpha > 0] = 254
        lightgraph = numpy.dstack((lightgraph, alpha))


        cv2.imwrite('lightgraph.png', lightgraph, [cv2.IMWRITE_PNG_COMPRESSION, 9])


    def generate(self):
        generate_start = time.time()


        now = datetime.now()
        self.utc_offset = now.astimezone().utcoffset()

        noon = datetime.strptime(now.strftime('%Y%m%d12'), '%Y%m%d%H')
        self.next_generate = noon + timedelta(hours=24)

        noon_utc = noon - self.utc_offset


        lightgraph_list = list()
        for x in range(1440):
            self.obs.date = noon_utc + timedelta(minutes=x)
            self.sun.compute(self.obs)

            sun_alt_deg = math.degrees(self.sun.alt)

            if sun_alt_deg < -18:
                lightgraph_list.append(self.dark_color)
            elif sun_alt_deg > 0:
                lightgraph_list.append(self.light_color)
            else:
                norm = (18 + sun_alt_deg) / 18  # alt is negative
                lightgraph_list.append(self.mapColor(norm, self.light_color, self.dark_color))

        #logger.info(lightgraph_list)

        generate_elapsed_s = time.time() - generate_start
        logger.warning('Total lightgraph processing in %0.4f s', generate_elapsed_s)


        lightgraph = numpy.array([lightgraph_list], dtype=numpy.uint8)
        lightgraph = cv2.resize(
            lightgraph,
            (1440, self.graph_height),
            interpolation=cv2.INTER_AREA,
        )


        # draw hour ticks
        for x in range(1, 24):
            cv2.line(
                img=lightgraph,
                pt1=(60 * x, 0),
                pt2=(60 * x, self.graph_height),
                color=tuple(self.line_color),
                thickness=1,
                lineType=self.line_type,
            )


        # draw border
        lightgraph = cv2.copyMakeBorder(
            lightgraph,
            self.graph_border,
            self.graph_border,
            self.graph_border,
            self.graph_border,
            cv2.BORDER_CONSTANT,
            None,
            self.border_color,
        )


        # draw text area
        lightgraph = cv2.copyMakeBorder(
            lightgraph,
            self.text_area_height,
            0,
            0,
            0,
            cv2.BORDER_CONSTANT,
            None,
            (0, 0, 0)
        )


        self.label_opencv(lightgraph)


        return lightgraph


    def label_opencv(self, lightgraph):
        for x, hour in enumerate([13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]):
            cv2.putText(
                img=lightgraph,
                text=str(hour),
                org=((60 * (x + 1)) - 10, 35),
                fontFace=self.font_face,
                color=(1, 1, 1),  # not full black
                lineType=self.line_type,
                fontScale=self.font_scale,
                thickness=self.font_thickness + 1,
            )
            cv2.putText(
                img=lightgraph,
                text=str(hour),
                org=((60 * (x + 1)) - 10, 35),
                fontFace=self.font_face,
                color=self.font_color,
                lineType=self.line_type,
                fontScale=self.font_scale,
                thickness=self.font_thickness,
            )


    def mapColor(self, scale, color_high, color_low):
        return tuple(int(((x[0] - x[1]) * scale) + x[1]) for x in zip(color_high, color_low))


if __name__ == "__main__":
    LightGraphGenerator().main()
