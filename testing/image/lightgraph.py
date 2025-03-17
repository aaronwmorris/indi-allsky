#!/usr/bin/env python3

import math
from datetime import datetime
from datetime import timedelta
from pathlib import Path
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
    graph_height = 30
    graph_border = 3
    top_border = 10
    text_area_height = 50
    now_marker_size = 8
    day_color = (150, 150, 150)
    dusk_color = (200, 100, 60)
    night_color = (30, 30, 30)
    hour_color = (100, 15, 15)
    border_color = (1, 1, 1)
    now_color = (120, 120, 200)

    opacity = 100
    hour_lines = True

    label = True
    font_face = cv2.FONT_HERSHEY_SIMPLEX
    font_color = (150, 150, 150)
    font_scale = 0.5
    font_thickness = 1
    line_type = cv2.LINE_AA


    def __init__(self):
        self.random_rgb = numpy.random.randint(200, size=(self.top_border + self.graph_height + self.text_area_height + (self.graph_border * 2), 1440 + (self.graph_border * 2), 3), dtype=numpy.uint8)

        self.lightgraph = None
        self.next_generate = 0  # generate immediately


    def main(self):
        now = time.time()

        if now > self.next_generate:
            self.lightgraph = self.generate()


        lightgraph = self.lightgraph.copy()


        #logger.info(lightgraph.shape)
        graph_height, graph_width = lightgraph.shape[:2]


        now = datetime.now()
        noon = datetime.strptime(now.strftime('%Y%m%d12'), '%Y%m%d%H')

        now_offset = int((now - noon).seconds / 60) + self.graph_border
        #logger.info('Now offset: %d', now_offset)


        now_color_bgr = list(self.now_color)
        now_color_bgr.reverse()

        # draw now triangle
        now_tri = numpy.array([
            (now_offset - self.now_marker_size, (self.top_border + self.graph_height + self.graph_border) - self.now_marker_size),
            (now_offset + self.now_marker_size, (self.top_border + self.graph_height + self.graph_border) - self.now_marker_size),
            (now_offset, self.top_border + self.graph_height + self.graph_border),
        ],
            dtype=numpy.int32,
        )
        #logger.info(now_tri)


        cv2.fillPoly(
            img=lightgraph,
            pts=[now_tri],
            color=tuple(now_color_bgr),
        )

        # outline
        cv2.polylines(
            img=lightgraph,
            pts=[now_tri],
            isClosed=True,
            color=(1, 1, 1),  # not full black
            thickness=1,
            lineType=self.line_type,
        )


        # create alpha channel, anything pixel that is full black (0, 0, 0) is transparent
        alpha = numpy.max(lightgraph, axis=2)
        alpha[alpha > 0] = int(255 * (self.opacity / 100))
        lightgraph = numpy.dstack((lightgraph, alpha))


        # separate layers
        lightgraph_bgr = lightgraph[:, :, :3]
        lightgraph_alpha = (lightgraph[:, :, 3] / 255).astype(numpy.float32)

        # create alpha mask
        alpha_mask = numpy.dstack((
            lightgraph_alpha,
            lightgraph_alpha,
            lightgraph_alpha,
        ))


        # apply alpha mask
        lightgraph_final = (self.random_rgb * (1 - alpha_mask) + lightgraph_bgr * alpha_mask).astype(numpy.uint8)


        if self.label:
            self.drawText_opencv(lightgraph_final)


        #cv2.imwrite(Path(__file__).parent.joinpath('lightgraph.png'), lightgraph_final, [cv2.IMWRITE_PNG_COMPRESSION, 9])
        cv2.imwrite(Path(__file__).parent.joinpath('lightgraph.jpg'), lightgraph_final, [cv2.IMWRITE_JPEG_QUALITY, 90])


    def generate(self):
        generate_start = time.time()


        now = datetime.now()
        utc_offset = now.astimezone().utcoffset()

        noon = datetime.strptime(now.strftime('%Y%m%d12'), '%Y%m%d%H')
        self.next_generate = (noon + timedelta(hours=24)).timestamp()

        noon_utc = noon - utc_offset


        obs = ephem.Observer()
        obs.lon = math.radians(LONGITUDE)
        obs.lat = math.radians(LATITUDE)

        # disable atmospheric refraction calcs
        obs.pressure = 0

        sun = ephem.Sun()

        day_color_bgr = list(self.day_color)
        day_color_bgr.reverse()
        dusk_color_bgr = list(self.dusk_color)
        dusk_color_bgr.reverse()
        night_color_bgr = list(self.night_color)
        night_color_bgr.reverse()

        lightgraph_list = list()
        for x in range(1440):
            obs.date = noon_utc + timedelta(minutes=x)
            sun.compute(obs)

            sun_alt_deg = math.degrees(sun.alt)

            if sun_alt_deg < -18:
                lightgraph_list.append(night_color_bgr)
            elif sun_alt_deg > 0:
                lightgraph_list.append(day_color_bgr)
            else:
                # tranition through dusk color
                if sun_alt_deg <= -9:
                    norm = (18 + sun_alt_deg) / 9  # alt is negative
                    color_1 = dusk_color_bgr
                    color_2 = night_color_bgr
                else:
                    norm = (9 + sun_alt_deg) / 9  # alt is negative
                    color_1 = day_color_bgr
                    color_2 = dusk_color_bgr

                lightgraph_list.append(self.mapColor(norm, color_1, color_2))

        #logger.info(lightgraph_list)

        generate_elapsed_s = time.time() - generate_start
        logger.warning('Total lightgraph processing in %0.4f s', generate_elapsed_s)


        lightgraph = numpy.array([lightgraph_list], dtype=numpy.uint8)
        lightgraph = cv2.resize(
            lightgraph,
            (1440, self.graph_height),
            interpolation=cv2.INTER_AREA,
        )


        hour_color_bgr = list(self.hour_color)
        hour_color_bgr.reverse()

        if self.hour_lines:
            # draw hour ticks
            for x in range(1, 24):
                cv2.line(
                    img=lightgraph,
                    pt1=(60 * x, 0),
                    pt2=(60 * x, self.graph_height),
                    color=tuple(hour_color_bgr),
                    thickness=1,
                    lineType=self.line_type,
                )


        border_color_bgr = list(self.border_color)
        border_color_bgr.reverse()

        # draw border
        lightgraph = cv2.copyMakeBorder(
            lightgraph,
            self.graph_border,
            self.graph_border,
            self.graph_border,
            self.graph_border,
            cv2.BORDER_CONSTANT,
            None,
            tuple(border_color_bgr),
        )


        # draw text area
        lightgraph = cv2.copyMakeBorder(
            lightgraph,
            self.top_border,
            self.text_area_height,
            0,
            0,
            cv2.BORDER_CONSTANT,
            None,
            (0, 0, 0)
        )


        return lightgraph


    def drawText_opencv(self, lightgraph):
        font_color_bgr = list(self.font_color)
        font_color_bgr.reverse()

        for x, hour in enumerate([13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]):
            cv2.putText(
                img=lightgraph,
                text=str(hour),
                org=((60 * (x + 1)) + self.graph_border - 7, self.top_border + self.graph_height + (self.graph_border * 2) + 20),
                fontFace=self.font_face,
                color=(1, 1, 1),  # not full black
                lineType=self.line_type,
                fontScale=self.font_scale,
                thickness=self.font_thickness + 1,
            )
            cv2.putText(
                img=lightgraph,
                text=str(hour),
                org=((60 * (x + 1)) + self.graph_border - 7, self.top_border + self.graph_height + (self.graph_border * 2) + 20),
                fontFace=self.font_face,
                color=tuple(font_color_bgr),
                lineType=self.line_type,
                fontScale=self.font_scale,
                thickness=self.font_thickness,
            )


    def mapColor(self, scale, color_high, color_low):
        return tuple(int(((x[0] - x[1]) * scale) + x[1]) for x in zip(color_high, color_low))


if __name__ == "__main__":
    LightGraphGenerator().main()
