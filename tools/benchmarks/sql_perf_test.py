#!/usr/bin/env python3

import sys
import time
from pathlib import Path
#from datetime import datetime
#from datetime import timedelta
import logging

sys.path.append(str(Path(__file__).parent.absolute().parent))

from indi_allsky.flask import create_app

# setup flask context for db access
app = create_app()
app.app_context().push()

from indi_allsky.flask.models import IndiAllSkyDbCameraTable
from indi_allsky.flask.models import IndiAllSkyDbImageTable
#from indi_allsky.flask.models import IndiAllSkyDbThumbnailTable
#from indi_allsky.flask.models import IndiAllSkyDbVideoTable

from sqlalchemy import extract
from sqlalchemy import and_
from indi_allsky.flask import db


LOG_FORMATTER_STREAM = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)


logger = logging.getLogger('indi_allsky')
logger.handlers.clear()
logger.addHandler(LOG_HANDLER_STREAM)
logger.setLevel(logging.INFO)


class SqlTester(object):

    def __init__(self):
        pass


    def main(self):
        camera_id = 1
        detections_count = 0

        year = 2024
        month = 7
        day = 28
        hour = 4


        createDate_Y = extract('year', IndiAllSkyDbImageTable.createDate).label('createDate_Y')
        createDate_m = extract('month', IndiAllSkyDbImageTable.createDate).label('createDate_m')
        createDate_d = extract('day', IndiAllSkyDbImageTable.createDate).label('createDate_d')
        createDate_H = extract('hour', IndiAllSkyDbImageTable.createDate).label('createDate_H')

        hours_query = db.session.query(
            createDate_Y,
            createDate_m,
            createDate_d,
            createDate_H,
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == camera_id,
                    IndiAllSkyDbImageTable.detections >= detections_count,
                    createDate_Y == year,
                    createDate_m == month,
                    createDate_d == day,
                )
        )\
            .distinct()\
            .order_by(createDate_H.desc())


        #    .join(IndiAllSkyDbThumbnailTable, IndiAllSkyDbImageTable.thumbnail_uuid == IndiAllSkyDbThumbnailTable.uuid)\


        #hours_query_group = db.session.query(
        #    createDate_Y,
        #    createDate_m,
        #    createDate_d,
        #    createDate_H,
        #)\
        #    .join(IndiAllSkyDbImageTable.camera)\
        #    .filter(
        #        and_(
        #            IndiAllSkyDbCameraTable.id == camera_id,
        #            IndiAllSkyDbImageTable.detections >= detections_count,
        #        )
        #)\
        #    .group_by(
        #        createDate_Y,
        #        createDate_m,
        #        createDate_d,
        #        createDate_H,
        #)\
        #    .distinct()\
        #    .order_by(
        #        createDate_Y.desc(),
        #        createDate_m.desc(),
        #        createDate_d.desc(),
        #        createDate_H.desc(),
        #)



        years_query_new = db.session.query(
            IndiAllSkyDbImageTable.createDate_year,
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == camera_id,
                    IndiAllSkyDbImageTable.detections >= detections_count,
                )
        ).distinct()\
            .order_by(IndiAllSkyDbImageTable.createDate_year.desc())



        months_query_new = db.session.query(
            IndiAllSkyDbImageTable.createDate_year,
            IndiAllSkyDbImageTable.createDate_month,
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == camera_id,
                    IndiAllSkyDbImageTable.detections >= detections_count,
                    IndiAllSkyDbImageTable.createDate_year == year,
                )
        ).distinct()\
            .order_by(IndiAllSkyDbImageTable.createDate_month.desc())


        days_query_new = db.session.query(
            IndiAllSkyDbImageTable.createDate_year,
            IndiAllSkyDbImageTable.createDate_month,
            IndiAllSkyDbImageTable.createDate_day,
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == camera_id,
                    IndiAllSkyDbImageTable.detections >= detections_count,
                    IndiAllSkyDbImageTable.createDate_year == year,
                    IndiAllSkyDbImageTable.createDate_month == month,
                )
        ).distinct()\
            .order_by(IndiAllSkyDbImageTable.createDate_day.desc())


        hours_query_new = db.session.query(
            IndiAllSkyDbImageTable.createDate_year,
            IndiAllSkyDbImageTable.createDate_month,
            IndiAllSkyDbImageTable.createDate_day,
            IndiAllSkyDbImageTable.createDate_hour,
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == camera_id,
                    IndiAllSkyDbImageTable.detections >= detections_count,
                    IndiAllSkyDbImageTable.createDate_year == year,
                    IndiAllSkyDbImageTable.createDate_month == month,
                    IndiAllSkyDbImageTable.createDate_day == day,
                )
        )\
            .distinct()\
            .order_by(IndiAllSkyDbImageTable.createDate_hour.desc())


        images_query_new = db.session.query(
            IndiAllSkyDbImageTable,
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == camera_id,
                    IndiAllSkyDbImageTable.detections >= detections_count,
                    IndiAllSkyDbImageTable.createDate_year == year,
                    IndiAllSkyDbImageTable.createDate_month == month,
                    IndiAllSkyDbImageTable.createDate_day == day,
                    IndiAllSkyDbImageTable.createDate_hour == hour,
                )
        ).order_by(IndiAllSkyDbImageTable.createDate.desc())


        YmdH_query_group_new = db.session.query(
            IndiAllSkyDbImageTable.createDate_year,
            IndiAllSkyDbImageTable.createDate_month,
            IndiAllSkyDbImageTable.createDate_day,
            IndiAllSkyDbImageTable.createDate_hour,
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == camera_id,
                    IndiAllSkyDbImageTable.detections >= detections_count,
                )
        )\
            .group_by(
                IndiAllSkyDbImageTable.createDate_year,
                IndiAllSkyDbImageTable.createDate_month,
                IndiAllSkyDbImageTable.createDate_day,
                IndiAllSkyDbImageTable.createDate_hour,
        )\
            .distinct()\
            .order_by(
                IndiAllSkyDbImageTable.createDate_year.desc(),
                IndiAllSkyDbImageTable.createDate_month.desc(),
                IndiAllSkyDbImageTable.createDate_day.desc(),
                IndiAllSkyDbImageTable.createDate_hour.desc(),
        )




        logger.info('Starting queries')

        start = time.time()
        logger.warning('Entries: %d', hours_query.count())
        elapsed_s = time.time() - start
        logger.info('Original SQL executed in %0.4f s', elapsed_s)

        #start_group = time.time()
        #logger.warning('Entries: %d', hours_query_group.count())
        #elapsed_s = time.time() - start_group
        #logger.info('Original group SQL executed in %0.4f s', elapsed_s)



        start_new = time.time()
        logger.warning('Entries: %d', years_query_new.count())
        elapsed_new = time.time() - start_new
        logger.info('New Years SQL executed in %0.4f s', elapsed_new)

        start_new = time.time()
        logger.warning('Entries: %d', months_query_new.count())
        elapsed_new = time.time() - start_new
        logger.info('New Months SQL executed in %0.4f s', elapsed_new)

        start_new = time.time()
        logger.warning('Entries: %d', days_query_new.count())
        elapsed_new = time.time() - start_new
        logger.info('New Days SQL executed in %0.4f s', elapsed_new)

        start_new = time.time()
        logger.warning('Entries: %d', hours_query_new.count())
        elapsed_new = time.time() - start_new
        logger.info('New Hours SQL executed in %0.4f s', elapsed_new)

        start_new = time.time()
        logger.warning('Entries: %d', images_query_new.count())
        elapsed_new = time.time() - start_new
        logger.info('New Images SQL executed in %0.4f s', elapsed_new)


        start_new = time.time()
        logger.warning('Entries: %d', YmdH_query_group_new.count())
        elapsed_new = time.time() - start_new
        logger.info('New group SQL executed in %0.4f s', elapsed_new)


        #for i in hours_query:
        #    #logger.info('attrs: %s', i.keys())
        #    logger.info('%d %d %d %d', i.createDate_Y, i.createDate_m, i.createDate_d, i.createDate_H)


if __name__ == "__main__":
    st = SqlTester()
    st.main()

