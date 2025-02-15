#!/usr/bin/env python3

import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone
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


ALIGNMENT = 60


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


    def main(self):
        now = datetime.now()
        start_time = now.timestamp()


        rows = self.generate_lightgraph_year()
        logger.info('Rows: %d', len(rows))
        self.build_db(rows)



        start_date = datetime.strptime(now.strftime('%Y0101_120000'), '%Y%m%d_%H%M%S')
        end_date = datetime.strptime(now.strftime('%Y1231_120000'), '%Y%m%d_%H%M%S')

        start_ts_utc = start_date.astimezone(timezone.utc).timestamp()
        end_ts_utc = end_date.astimezone(timezone.utc).timestamp()

        start_offset = int(start_ts_utc / ALIGNMENT)


        q = self.session.query(
            func.avg(TestTable.r).label('r_a'),
            func.avg(TestTable.b).label('b_a'),
            func.avg(TestTable.g).label('g_a'),
            func.floor(TestTable.ts / ALIGNMENT).label('interval'),
        )\
            .filter(TestTable.ts >= start_ts_utc)\
            .filter(TestTable.ts < end_ts_utc)\
            .group_by('interval')\
            .order_by(TestTable.ts.asc())



        numpy_start = time.time()

        numpy_data = numpy.zeros((int(86400 / ALIGNMENT) * 365, 1, 3), dtype=numpy.uint8)

        for x in q:
            #logger.info('Entry: %s, (%d, %d, %d)', x.interval - start_offset, x.r_a, x.b_a, x.g_a)
            numpy_data[x.interval - start_offset] = x.b_a, x.g_a, x.r_a

        numpy_elapsed_s = time.time() - numpy_start
        logger.warning('Total numpy in %0.4f s', numpy_elapsed_s)

        logger.info(numpy_data.shape)
        #logger.info(numpy_data[0:3])

        keogram_data = numpy.reshape(numpy_data, (365, int(86400 / ALIGNMENT), 3))

        logger.info(keogram_data.shape)
        #logger.info(keogram_data[0:3])


        keogram_height, keogram_width = keogram_data.shape[:2]
        keogram_data = cv2.resize(keogram_data, (keogram_width, keogram_height * 3), interpolation=cv2.INTER_AREA)
        cv2.imwrite('year.jpg', keogram_data, [cv2.IMWRITE_JPEG_QUALITY, 90])

        total_elapsed_s = time.time() - start_time
        logger.warning('Total in %0.4f s', total_elapsed_s)


    def _getDbConn(self):
        #engine = create_engine('sqlite:///foo.sqlite', echo=False)
        engine = create_engine('sqlite://', echo=False)  # In memory db
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
        end_date = datetime.strptime(now.strftime('%Y1231_235959'), '%Y%m%d_%H%M%S')
        #end_date = datetime.strptime(now.strftime('%Y0131_235959'), '%Y%m%d_%H%M%S')  # test

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
                'r'  : r,
                'g'  : g,
                'b'  : b,
            })


            current_date_utc += timedelta(seconds=60)
            #current_date_utc += timedelta(seconds=90)  # testing


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
    r           = Column(Integer, nullable=False)
    g           = Column(Integer, nullable=False)
    b           = Column(Integer, nullable=False)


if __name__ == '__main__':
    YearKeogramTest().main()
