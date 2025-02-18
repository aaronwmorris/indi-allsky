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


logger = logging.getLogger(__name__)
logger.setLevel(level=logging.INFO)

LOG_FORMATTER_STREAM = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s %(funcName)s() [%(lineno)d]: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)
logger.addHandler(LOG_HANDLER_STREAM)



@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA synchronous=OFF")
    cursor.close()


class YearKeogramTest(object):

    day_color = (130, 200, 220)
    dusk_color = (200, 100, 60)
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
        self.period_pixels = 5


    def main(self):
        now = datetime.now()
        start_time = now.timestamp()


        rows = self.generate_lightgraph_year()
        logger.info('Rows: %d', len(rows))
        self.build_db(rows)


        query_start_date = datetime.strptime(now.strftime('%Y0101_120000'), '%Y%m%d_%H%M%S')
        query_end_date = query_start_date + timedelta(days=self.query_days)
        #query_end_date = datetime.strptime((now + timedelta(hours=24)).strftime('%Y%m%d_120000'), '%Y%m%d_%H%M%S')
        #query_start_date = now - timedelta(days=self.query_days)


        query_start_ts = query_start_date.timestamp()
        query_end_ts = query_end_date.timestamp()

        total_days = math.ceil((query_end_ts - query_start_ts) / 86400)
        logger.info('Total days: %d', total_days)


        q = self.session.query(
            #TestTable.ts,
            func.max(TestTable.r1).label('r1_avg'),
            func.max(TestTable.b1).label('b1_avg'),
            func.max(TestTable.g1).label('g1_avg'),
            func.max(TestTable.r2).label('r2_avg'),
            func.max(TestTable.b2).label('b2_avg'),
            func.max(TestTable.g2).label('g2_avg'),
            func.max(TestTable.r3).label('r3_avg'),
            func.max(TestTable.b3).label('b3_avg'),
            func.max(TestTable.g3).label('g3_avg'),
            func.max(TestTable.r4).label('r4_avg'),
            func.max(TestTable.b4).label('b4_avg'),
            func.max(TestTable.g4).label('g4_avg'),
            func.max(TestTable.r5).label('r5_avg'),
            func.max(TestTable.b5).label('b5_avg'),
            func.max(TestTable.g5).label('g5_avg'),
            func.floor(TestTable.ts / self.alignment_seconds).label('interval'),
        )\
            .filter(TestTable.ts >= query_start_ts)\
            .filter(TestTable.ts < query_end_ts)\
            .group_by('interval')\
            .order_by(TestTable.ts.asc())


        query_start_offset = int(query_start_ts / self.alignment_seconds)
        logger.info('Query start offset: %d', query_start_offset)


        numpy_start = time.time()

        numpy_data = numpy.zeros(((self.periods_per_day * total_days) * self.period_pixels, 1, 3), dtype=numpy.uint8)
        logger.info(numpy_data.shape)
        logger.info('Rows: %d', q.count())

        for i, row in enumerate(q):
            second_offset = row.interval - query_start_offset
            day = int(second_offset / self.periods_per_day)
            index = second_offset + (day * (self.periods_per_day * (self.period_pixels - 1)))
            #logger.info('Row: %d, second_offset: %d, day: %d, index: %d', i, second_offset, day, index)

            try:
                numpy_data[index + (self.periods_per_day * 0)] = row.b1_avg, row.g1_avg, row.r1_avg
                numpy_data[index + (self.periods_per_day * 1)] = row.b2_avg, row.g2_avg, row.r2_avg
                numpy_data[index + (self.periods_per_day * 2)] = row.b3_avg, row.g3_avg, row.r3_avg
                numpy_data[index + (self.periods_per_day * 3)] = row.b4_avg, row.g4_avg, row.r4_avg
                numpy_data[index + (self.periods_per_day * 4)] = row.b5_avg, row.g5_avg, row.r5_avg
            except IndexError:
                logger.error('Row: %d', i)
                raise


        numpy_elapsed_s = time.time() - numpy_start
        logger.warning('Total numpy in %0.4f s', numpy_elapsed_s)

        #logger.info(numpy_data[0:3])

        keogram_data = numpy.reshape(numpy_data, ((total_days * self.period_pixels), self.periods_per_day, 3))

        logger.info(keogram_data.shape)
        #logger.info(keogram_data[0:3])


        keogram_height, keogram_width = keogram_data.shape[:2]
        #keogram_data = cv2.resize(keogram_data, (keogram_width, keogram_height * 3), interpolation=cv2.INTER_AREA)
        cv2.imwrite(Path(__file__).parent.joinpath('year.jpg'), keogram_data, [cv2.IMWRITE_JPEG_QUALITY, 90])

        total_elapsed_s = time.time() - start_time
        logger.warning('Total in %0.4f s', total_elapsed_s)


    def _getDbConn(self):
        #engine = create_engine('sqlite://', echo=False)  # In memory db
        engine = create_engine('sqlite:///{0:s}'.format(str(Path(__file__).parent.joinpath('year.sqlite'))), echo=False)
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
                #norm = (18 + sun_alt_deg) / 18  # alt is negative
                #color_1 = self.day_color
                #color_2 = self.night_color

                ### tranition through dusk color
                if sun_alt_deg <= -9:
                    norm = (18 + sun_alt_deg) / 9  # alt is negative
                    color_1 = self.dusk_color
                    color_2 = self.night_color
                else:
                    norm = (9 + sun_alt_deg) / 9  # alt is negative
                    color_1 = self.day_color
                    color_2 = self.dusk_color


                r, g, b = self.mapColor(norm, color_1, color_2)


            #logger.info('Red: %d, Green: %d, Blue: %d', r, g, b)
            lightgraph_list.append({
                'ts'  : int(current_date_utc.timestamp()),
                'r1'  : r,
                'g1'  : g,
                'b1'  : b,
                'r2'  : r,
                'g2'  : g,
                'b2'  : b,
                'r3'  : r,
                'g3'  : g,
                'b3'  : b,
                'r4'  : r,
                'g4'  : g,
                'b4'  : b,
                'r5'  : r,
                'g5'  : g,
                'b5'  : b,
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
    r4          = Column(Integer, nullable=False)
    g4          = Column(Integer, nullable=False)
    b4          = Column(Integer, nullable=False)
    r5          = Column(Integer, nullable=False)
    g5          = Column(Integer, nullable=False)
    b5          = Column(Integer, nullable=False)


if __name__ == '__main__':
    YearKeogramTest().main()
