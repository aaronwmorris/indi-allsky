
import math
from datetime import datetime
import logging

import numpy

from sqlalchemy import func

from .flask import db
from .flask import create_app

from .flask.models import IndiAllSkyDbCameraTable
from .flask.models import IndiAllSkyDbLongTermKeogramTable


app = create_app()

logger = logging.getLogger('indi_allsky')


class LongTermKeogramGenerator(object):
    def __init__(self):
        self._camera_id = None
        self._days = None
        self._alignment_seconds = None
        self._offset_seconds = None
        self._period_pixels = None
        self._reverse = False


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



        ltk_interval = func.floor(IndiAllSkyDbLongTermKeogramTable.ts / self.alignment_seconds).label('interval')

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

        ### order is unnecessary
        #    .order_by(ltk_interval.asc())


        numpy_data = numpy.zeros(((periods_per_day * total_days) * self.period_pixels, 1, 3), dtype=numpy.uint8)
        #logger.info('Rows: %d', q.count())


        if app.config['SQLALCHEMY_DATABASE_URI'].startswith('mysql'):
            query_limit = 300000  # limit memory impact on database
        else:
            # assume sqlite
            query_limit = 300000


        i = 0
        while i % query_limit == 0:
            q_offset = q.offset(i).limit(query_limit)

            for row in q_offset:
                second_offset = row.interval - query_start_offset
                day = int(second_offset / periods_per_day)
                index = second_offset + (day * (periods_per_day * (self.period_pixels - 1)))

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
            keogram_data = numpy.flip(keogram_data, axis=0)  # newer data at top


        # sanity check
        keogram_data = numpy.clip(keogram_data, 0, 255)
        #keogram_data[keogram_data < 0] = 0
        #keogram_data[keogram_data > 255] = 255


        return keogram_data
