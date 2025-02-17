#!/usr/bin/env python3

#import sys
import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
import math
import logging

import ephem

import numpy
import cv2

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import Column
from sqlalchemy import Integer
#from sqlalchemy import DateTime
from sqlalchemy.sql import func
#from sqlalchemy import cast


LATITUDE = 33
LONGITUDE = -85


logging.basicConfig(level=logging.INFO)
logger = logging



@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA synchronous=OFF")
    cursor.close()


class YearKeogramTest(object):

    day_color = (150, 150, 150)
    night_color = (30, 30, 30)


    def __init__(self):
        self.session = self._getDbConn()


        self.alignment_seconds = 60

        self.db_entry_seconds = 60
        #self.db_entry_seconds = 65  # testing


        self.query_days = 365
        #self.query_days = 400  # testing

        self.db_days = 365
        #self.db_days = 31  # testing


        self.periods_per_day = int(86400 / self.alignment_seconds)
        self.period_pixels = 3


    def main(self):
        now = datetime.now()
        start_time = now.timestamp()


        rows = self.generate_lightgraph_year()
        logger.info('Rows: %d', len(rows))
        self.build_db(rows)


        start_date = datetime.strptime(now.strftime('%Y0101_120000'), '%Y%m%d_%H%M%S')
        end_date = start_date + timedelta(days=self.query_days)

        start_ts_utc = start_date.astimezone(timezone.utc).timestamp()
        end_ts_utc = end_date.astimezone(timezone.utc).timestamp()

        start_offset = int(start_ts_utc / self.alignment_seconds)


        q = self.session.query(
            func.max(TestTable.r1).label('r1_avg'),
            func.max(TestTable.b1).label('b1_avg'),
            func.max(TestTable.g1).label('g1_avg'),
            func.max(TestTable.r2).label('r2_avg'),
            func.max(TestTable.b2).label('b2_avg'),
            func.max(TestTable.g2).label('g2_avg'),
            func.max(TestTable.r3).label('r3_avg'),
            func.max(TestTable.b3).label('b3_avg'),
            func.max(TestTable.g3).label('g3_avg'),
            func.floor(TestTable.ts / self.alignment_seconds).label('interval'),
        )\
            .filter(TestTable.ts >= start_ts_utc)\
            .filter(TestTable.ts < end_ts_utc)\
            .group_by('interval')\
            .order_by(TestTable.ts.asc())



        numpy_start = time.time()

        numpy_data = numpy.zeros(((self.periods_per_day * self.query_days) * self.period_pixels, 1, 3), dtype=numpy.uint8)
        logger.info(numpy_data.shape)
        logger.info('Rows: %d', q.count())

        try:
            for i, row in enumerate(q):
                second_offset = row.interval - start_offset
                day = int(second_offset / self.periods_per_day)
                index = second_offset + (day * (self.periods_per_day * (self.period_pixels - 1)))
                #logger.info('Row: %d, second_offset: %d, day: %d, index: %d', i, second_offset, day, index)

                numpy_data[index + (self.periods_per_day * 0)] = row.b1_avg, row.g1_avg, row.r1_avg
                numpy_data[index + (self.periods_per_day * 1)] = row.b2_avg, row.g2_avg, row.r2_avg
                numpy_data[index + (self.periods_per_day * 2)] = row.b3_avg, row.g3_avg, row.r3_avg

        except IndexError:
            logger.error('Row: %d', i)
            raise

        numpy_elapsed_s = time.time() - numpy_start
        logger.warning('Total numpy in %0.4f s', numpy_elapsed_s)

        #logger.info(numpy_data[0:3])

        keogram_data = numpy.reshape(numpy_data, ((self.query_days * self.period_pixels), self.periods_per_day, 3))

        logger.info(keogram_data.shape)
        #logger.info(keogram_data[0:3])


        keogram_height, keogram_width = keogram_data.shape[:2]
        #keogram_data = cv2.resize(keogram_data, (keogram_width, keogram_height * 3), interpolation=cv2.INTER_AREA)
        cv2.imwrite(Path(__file__).parent.joinpath('year.jpg'), keogram_data, [cv2.IMWRITE_JPEG_QUALITY, 90])

        total_elapsed_s = time.time() - start_time
        logger.warning('Total in %0.4f s', total_elapsed_s)


    def _getDbConn(self):
        engine = create_engine('sqlite://', echo=False)  # In memory db
        #engine = create_engine('sqlite:///{0:s}'.format(str(Path(__file__).parent.joinpath('year.sqlite'))), echo=False)
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)

        return Session()


    def build_db(self, rows):
        insert_start = time.time()

        self.session.bulk_insert_mappings(TestTable, rows)
        self.session.commit()

        insert_elapsed_s = time.time() - insert_start
        logger.warning('Insert processing in %0.4f s', insert_elapsed_s)



    def generate_lightgraph_year(self):
        generate_start = time.time()

        now = datetime.now()
        start_date = datetime.strptime(now.strftime('%Y0101_000000'), '%Y%m%d_%H%M%S')
        end_date = start_date + timedelta(days=self.db_days)


        start_date_utc = start_date.astimezone(timezone.utc)
        end_date_utc = end_date.astimezone(timezone.utc)


        logger.info('Start date: %s', start_date)
        logger.info('End date: %s', end_date)

        obs = ephem.Observer()
        obs.lon = math.radians(LONGITUDE)
        obs.lat = math.radians(LATITUDE)

        # disable atmospheric refraction calcs
        obs.pressure = 0

        sun = ephem.Sun()


        current_date_utc = start_date_utc

        lightgraph_list = list()
        while current_date_utc <= end_date_utc:
            obs.date = current_date_utc
            sun.compute(obs)

            sun_alt_deg = math.degrees(sun.alt)

            if sun_alt_deg < -18:
                r, g, b = self.night_color
            elif sun_alt_deg > 0:
                r, g, b = self.day_color
            else:
                norm = (18 + sun_alt_deg) / 18  # alt is negative
                color_1 = self.day_color
                color_2 = self.night_color

                r, g, b = self.mapColor(norm, color_1, color_2)


            #logger.info('Red: %d, Green: %d, Blue: %d', r, g, b)
            lightgraph_list.append({
                'ts' : current_date_utc.timestamp(),
                'r1'  : r,
                'g1'  : g,
                'b1'  : b,
                'r2'  : r,
                'g2'  : g,
                'b2'  : b,
                'r3'  : r,
                'g3'  : g,
                'b3'  : b,
            })


            current_date_utc += timedelta(seconds=self.db_entry_seconds)


        generate_elapsed_s = time.time() - generate_start
        logger.warning('Total lightgraph processing in %0.4f s', generate_elapsed_s)


        return lightgraph_list


    def mapColor(self, scale, color_high, color_low):
        return tuple(int(((x[0] - x[1]) * scale) + x[1]) for x in zip(color_high, color_low))


class Base(DeclarativeBase):
    pass


class TestTable(Base):
    __tablename__ = 'test'

    id          = Column(Integer, primary_key=True)
    ts          = Column(Integer, nullable=False, index=True)
    r1          = Column(Integer, nullable=False)
    g1          = Column(Integer, nullable=False)
    b1          = Column(Integer, nullable=False)
    r2          = Column(Integer, nullable=False)
    g2          = Column(Integer, nullable=False)
    b2          = Column(Integer, nullable=False)
    r3          = Column(Integer, nullable=False)
    g3          = Column(Integer, nullable=False)
    b3          = Column(Integer, nullable=False)


if __name__ == '__main__':
    YearKeogramTest().main()
