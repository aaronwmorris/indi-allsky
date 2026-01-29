
import math
from pathlib import Path
from datetime import datetime
import logging

import numpy

from sqlalchemy import func
from sqlalchemy import cast
from sqlalchemy.types import Integer

from .flask import db
from .flask import create_app

from .flask.models import IndiAllSkyDbCameraTable
from .flask.models import IndiAllSkyDbLongTermKeogramTable


app = create_app()

logger = logging.getLogger('indi_allsky')


class LongTermKeogramGenerator(object):

    # label settings
    line_thickness = 2


    def __init__(self, config):
        self.config = config


        self._camera_id = None
        self._days = None
        self._alignment_seconds = None
        self._offset_seconds = None
        self._period_pixels = None
        self._reverse = False
        self._label = False


        base_path  = Path(__file__).parent
        self.font_path  = base_path.joinpath('fonts')


    @property
    def camera_id(self):
        return self._camera_id

    @camera_id.setter
    def camera_id(self, new_camera_id):
        self._camera_id = int(new_camera_id)


    @property
    def days(self):
        return self._days

    @days.setter
    def days(self, new_days):
        self._days = int(new_days)


    @property
    def reverse(self):
        return self._reverse

    @reverse.setter
    def reverse(self, new_reverse):
        self._reverse = bool(new_reverse)


    @property
    def label(self):
        return self._label

    @label.setter
    def label(self, new_label):
        self._label = bool(new_label)


    @property
    def alignment_seconds(self):
        return self._alignment_seconds

    @alignment_seconds.setter
    def alignment_seconds(self, new_alignment_seconds):
        self._alignment_seconds = int(new_alignment_seconds)


    @property
    def offset_seconds(self):
        return self._offset_seconds

    @offset_seconds.setter
    def offset_seconds(self, new_offset_seconds):
        self._offset_seconds = int(new_offset_seconds)


    @property
    def period_pixels(self):
        return self._period_pixels

    @period_pixels.setter
    def period_pixels(self, new_period_pixels):
        self._period_pixels = int(new_period_pixels)
        assert self._period_pixels >= 1
        assert self._period_pixels <= 5


    def generate(self, query_start_date, query_end_date):
        periods_per_day = int(86400 / self.alignment_seconds)

        if self.days == 42:
            # special condition to show all available data
            first_entry = db.session.query(
                IndiAllSkyDbLongTermKeogramTable.ts,
            )\
                .join(IndiAllSkyDbCameraTable)\
                .filter(IndiAllSkyDbCameraTable.id == self.camera_id)\
                .order_by(IndiAllSkyDbLongTermKeogramTable.ts.asc())\
                .first()


            first_date = datetime.fromtimestamp(first_entry.ts)
            query_start_date = datetime.strptime(first_date.strftime('%Y%m%d_120000'), '%Y%m%d_%H%M%S')


        query_start_ts = query_start_date.timestamp() - self.offset_seconds  # subtract offset
        query_end_ts = query_end_date.timestamp() - self.offset_seconds


        total_days = math.ceil((query_end_ts - query_start_ts) / 86400)

        query_start_offset = int(query_start_ts / self.alignment_seconds)


        ltk_interval = cast(IndiAllSkyDbLongTermKeogramTable.ts / self.alignment_seconds, Integer).label('interval')  # cast is slightly faster than func.floor

        q = db.session.query(
            ltk_interval,
            func.avg(IndiAllSkyDbLongTermKeogramTable.r1).label('r1_avg'),
            func.avg(IndiAllSkyDbLongTermKeogramTable.b1).label('b1_avg'),
            func.avg(IndiAllSkyDbLongTermKeogramTable.g1).label('g1_avg'),
            func.avg(IndiAllSkyDbLongTermKeogramTable.r2).label('r2_avg'),
            func.avg(IndiAllSkyDbLongTermKeogramTable.b2).label('b2_avg'),
            func.avg(IndiAllSkyDbLongTermKeogramTable.g2).label('g2_avg'),
            func.avg(IndiAllSkyDbLongTermKeogramTable.r3).label('r3_avg'),
            func.avg(IndiAllSkyDbLongTermKeogramTable.b3).label('b3_avg'),
            func.avg(IndiAllSkyDbLongTermKeogramTable.g3).label('g3_avg'),
            func.avg(IndiAllSkyDbLongTermKeogramTable.r4).label('r4_avg'),
            func.avg(IndiAllSkyDbLongTermKeogramTable.b4).label('b4_avg'),
            func.avg(IndiAllSkyDbLongTermKeogramTable.g4).label('g4_avg'),
            func.avg(IndiAllSkyDbLongTermKeogramTable.r5).label('r5_avg'),
            func.avg(IndiAllSkyDbLongTermKeogramTable.b5).label('b5_avg'),
            func.avg(IndiAllSkyDbLongTermKeogramTable.g5).label('g5_avg'),
        )\
            .join(IndiAllSkyDbCameraTable)\
            .filter(IndiAllSkyDbCameraTable.id == self.camera_id)\
            .filter(IndiAllSkyDbLongTermKeogramTable.ts >= query_start_ts)\
            .filter(IndiAllSkyDbLongTermKeogramTable.ts < query_end_ts)\
            .group_by(ltk_interval)


        ### order is proably unnecessary
        #    .order_by(ltk_interval.asc())


        numpy_data = numpy.zeros(((periods_per_day * total_days) * self.period_pixels, 1, 3), dtype=numpy.uint8)
        #logger.info('Rows: %d', q.count())


        if app.config['SQLALCHEMY_DATABASE_URI'].startswith('mysql'):
            query_limit = 300000  # limit memory impact on database
        else:
            # assume sqlite
            query_limit = 300000


        last_day = -1
        day_list = list()


        i = 0
        while i % query_limit == 0:
            q_offset = q.limit(query_limit).offset(i)

            for row in q_offset:
                second_offset = row.interval - query_start_offset
                day = int(second_offset / periods_per_day)
                index = second_offset + (day * (periods_per_day * (self.period_pixels - 1)))


                if last_day != day:
                    row_date = datetime.fromtimestamp(row.interval * self.alignment_seconds).date()
                    day_list.append({
                        'month'     : row_date.month,
                        'date'      : row_date,
                    })

                    last_day = day


                if self.period_pixels == 5:
                    numpy_data[index + (periods_per_day * 4)] = row.b5_avg, row.g5_avg, row.r5_avg
                    numpy_data[index + (periods_per_day * 3)] = row.b4_avg, row.g4_avg, row.r4_avg
                    numpy_data[index + (periods_per_day * 2)] = row.b3_avg, row.g3_avg, row.r3_avg
                    numpy_data[index + (periods_per_day * 1)] = row.b2_avg, row.g2_avg, row.r2_avg

                elif self.period_pixels == 4:
                    numpy_data[index + (periods_per_day * 3)] = row.b4_avg, row.g4_avg, row.r4_avg
                    numpy_data[index + (periods_per_day * 2)] = row.b3_avg, row.g3_avg, row.r3_avg
                    numpy_data[index + (periods_per_day * 1)] = row.b2_avg, row.g2_avg, row.r2_avg

                elif self.period_pixels == 3:
                    numpy_data[index + (periods_per_day * 2)] = row.b3_avg, row.g3_avg, row.r3_avg
                    numpy_data[index + (periods_per_day * 1)] = row.b2_avg, row.g2_avg, row.r2_avg

                elif self.period_pixels == 2:
                    numpy_data[index + (periods_per_day * 1)] = row.b2_avg, row.g2_avg, row.r2_avg


                # always add 1 row
                numpy_data[index] = row.b1_avg, row.g1_avg, row.r1_avg

                i += 1


        keogram_data = numpy.reshape(numpy_data, ((total_days * self.period_pixels), periods_per_day, 3))
        #logger.info(keogram_data.shape)


        if not self.reverse:
            # newer data at top
            keogram_data = numpy.flip(keogram_data, axis=0)
            day_list.reverse()


        # sanity check
        keogram_data = numpy.clip(keogram_data, 0, 255)
        #keogram_data[keogram_data < 0] = 0
        #keogram_data[keogram_data > 255] = 255


        #app.logger.info('Days: %s', str(day_list))

        # apply time labels
        keogram_data = self.applyLabels(keogram_data, day_list)


        return keogram_data


    def applyLabels(self, keogram_data, day_list):
        if self.label:
            image_label_system = self.config.get('IMAGE_LABEL_SYSTEM', 'pillow')

            if image_label_system == 'opencv':
                keogram_data = self.applyLabels_opencv(keogram_data, day_list)
            else:
                # pillow is default
                keogram_data = self.applyLabels_pillow(keogram_data, day_list)
        else:
            #logger.warning('Keogram labels disabled')
            pass


        return keogram_data


    def applyLabels_opencv(self, keogram_data, day_list):
        import cv2

        keogram_height, keogram_width = keogram_data.shape[:2]

        fontFace = getattr(cv2, self.config['TEXT_PROPERTIES']['FONT_FACE'])
        lineType = getattr(cv2, self.config['TEXT_PROPERTIES']['FONT_AA'])

        color_bgr = list(self.config['TEXT_PROPERTIES']['FONT_COLOR'])
        color_bgr.reverse()


        last_month = day_list[0]['month']  # skip first month
        for i, day in enumerate(day_list):
            if day['month'] == last_month:
                continue

            last_month = day['month']


            y = i * self.period_pixels
            label = '{0:%B %Y}'.format(day_list[i - 1]['date'])  # previous month


            if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
                cv2.line(
                    img=keogram_data,
                    pt1=(0, y),
                    pt2=(int(keogram_width * 0.15), y),
                    color=(0, 0, 0),
                    lineType=lineType,
                    thickness=self.line_thickness + 1,
                )  # black outline

            cv2.line(
                img=keogram_data,
                pt1=(0, y),
                pt2=(int(keogram_width * 0.15), y),
                color=tuple(color_bgr),
                lineType=lineType,
                thickness=self.line_thickness,
            )


            if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
                cv2.putText(
                    img=keogram_data,
                    text=label,
                    org=(5, y - 10),
                    fontFace=fontFace,
                    color=(0, 0, 0),
                    lineType=lineType,
                    fontScale=self.config['TEXT_PROPERTIES']['FONT_SCALE'],
                    thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'] + 1,
                )  # black outline

            cv2.putText(
                img=keogram_data,
                text=label,
                org=(5, y - 10),
                fontFace=fontFace,
                color=tuple(color_bgr),
                lineType=lineType,
                fontScale=self.config['TEXT_PROPERTIES']['FONT_SCALE'],
                thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'],
            )


        return keogram_data


    def applyLabels_pillow(self, keogram_data, day_list):
        import cv2
        from PIL import Image
        from PIL import ImageFont
        from PIL import ImageDraw

        keogram_rgb = Image.fromarray(cv2.cvtColor(keogram_data, cv2.COLOR_BGR2RGB))
        keogram_width, keogram_height  = keogram_rgb.size  # backwards from opencv


        if self.config['TEXT_PROPERTIES']['PIL_FONT_FILE'] == 'custom':
            pillow_font_file_p = Path(self.config['TEXT_PROPERTIES']['PIL_FONT_CUSTOM'])
        else:
            pillow_font_file_p = self.font_path.joinpath(self.config['TEXT_PROPERTIES']['PIL_FONT_FILE'])


        pillow_font_size = self.config['TEXT_PROPERTIES']['PIL_FONT_SIZE']

        font = ImageFont.truetype(str(pillow_font_file_p), pillow_font_size)
        draw = ImageDraw.Draw(keogram_rgb)

        color_rgb = list(self.config['TEXT_PROPERTIES']['FONT_COLOR'])  # RGB for pillow


        if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
            # black outline
            stroke_width = 4
        else:
            stroke_width = 0


        last_month = day_list[0]['month']  # skip first month
        for i, day in enumerate(day_list):
            if day['month'] == last_month:
                continue

            last_month = day['month']


            y = i * self.period_pixels
            label = '{0:%B %Y}'.format(day_list[i - 1]['date'])  # previous month


            if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
                draw.line(
                    ((0, y), (int(keogram_width * 0.15), y)),
                    fill=(0, 0, 0),
                    width=self.line_thickness + 3,
                )
            draw.line(
                ((0, y), (int(keogram_width * 0.15), y)),
                fill=tuple(color_rgb),
                width=self.line_thickness + 1,
            )


            draw.text(
                (5, y - 5),
                label,
                fill=tuple(color_rgb),
                font=font,
                stroke_width=stroke_width,
                stroke_fill=(0, 0, 0),
                anchor='ld',  # left-descender
            )


        # convert back to numpy array
        return cv2.cvtColor(numpy.array(keogram_rgb), cv2.COLOR_RGB2BGR)

