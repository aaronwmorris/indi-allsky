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

from indi_allsky.flask.models import IndiAllSkyDbImageTable
from indi_allsky.flask.models import IndiAllSkyDbVideoTable
from indi_allsky.flask.models import IndiAllSkyDbMiniVideoTable

from sqlalchemy.sql.expression import null as sa_null

from indi_allsky.flask import db

logging.basicConfig(level=logging.INFO)
logger = logging


class PopulateDates(object):

    def __init__(self):
        pass


    def main(self):
        images_query = db.session.query(
            IndiAllSkyDbImageTable
        )\
            .filter(IndiAllSkyDbImageTable.createDate_year == sa_null())

        videos_query = db.session.query(
            IndiAllSkyDbVideoTable
        )\
            .filter(IndiAllSkyDbVideoTable.dayDate_year == sa_null())

        mini_videos_query = db.session.query(
            IndiAllSkyDbMiniVideoTable
        )\
            .filter(IndiAllSkyDbMiniVideoTable.dayDate_year == sa_null())


        print('Image entries to fix: {0:d}'.format(images_query.count()))
        print('Timelapse entries to fix: {0:d}'.format(videos_query.count()))
        print('Mini Timelapse entries to fix: {0:d}'.format(mini_videos_query.count()))
        print()
        print('Running in 10 seconds... control-c to cancel')
        print()

        time.sleep(10.0)



        start = time.time()

        ### images
        logger.warning('Processing images...')
        for x, i in enumerate(images_query):
            if x % 500 == 0:
                logger.info('Processed %d', x)

            i.createDate_year   = i.createDate.year
            i.createDate_month  = i.createDate.month
            i.createDate_day    = i.createDate.day
            i.createDate_hour   = i.createDate.hour

            db.session.commit()


        ### videos
        logger.warning('Processing timelapses...')
        for x, v in enumerate(videos_query):
            if x % 50 == 0:
                logger.info('Processed %d', x)

            v.dayDate_year   = v.dayDate.year
            v.dayDate_month  = v.dayDate.month
            v.dayDate_day    = v.dayDate.day

            db.session.commit()


        ### mini videos
        logger.warning('Processing mini-timelapses...')
        for x, m in enumerate(mini_videos_query):
            if x % 50 == 0:
                logger.info('Processed %d', x)

            m.dayDate_year   = m.dayDate.year
            m.dayDate_month  = m.dayDate.month
            m.dayDate_day    = m.dayDate.day

            db.session.commit()


        elapsed_s = time.time() - start
        logger.info('Entries fixed in %0.4f s', elapsed_s)


if __name__ == "__main__":
    PopulateDates().main()

