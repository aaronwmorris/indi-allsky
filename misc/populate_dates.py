#!/usr/bin/env python3

import sys
import time
from pathlib import Path
#from datetime import datetime
#from datetime import timedelta
import signal
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
        self._shutdown = False


    def sigint_handler_main(self, signum, frame):
        logger.warning('Caught INT signal, shutting down')
        self._shutdown = True


    def main(self):
        image_count = db.session.query(
            IndiAllSkyDbImageTable
        )\
            .filter(IndiAllSkyDbImageTable.createDate_year == sa_null())\
            .count()

        video_count = db.session.query(
            IndiAllSkyDbVideoTable
        )\
            .filter(IndiAllSkyDbVideoTable.dayDate_year == sa_null())\
            .count()

        mini_video_count = db.session.query(
            IndiAllSkyDbMiniVideoTable
        )\
            .filter(IndiAllSkyDbMiniVideoTable.dayDate_year == sa_null())\
            .count()


        print()
        print('Image entries to fix: {0:d}'.format(image_count))
        print('Timelapse entries to fix: {0:d}'.format(video_count))
        print('Mini Timelapse entries to fix: {0:d}'.format(mini_video_count))
        print()
        print('Running in 10 seconds... control-c to cancel')
        print()

        time.sleep(10.0)


        signal.signal(signal.SIGINT, self.sigint_handler_main)


        start = time.time()

        ### images
        logger.warning('Processing images...')
        while True:
            image_query = db.session.query(
                IndiAllSkyDbImageTable
            )\
                .filter(IndiAllSkyDbImageTable.createDate_year == sa_null())\
                .limit(500)


            i_count = image_query.count()
            if i_count == 0:
                break


            for i in image_query:
                i.createDate_year   = i.createDate.year
                i.createDate_month  = i.createDate.month
                i.createDate_day    = i.createDate.day
                i.createDate_hour   = i.createDate.hour

            db.session.commit()


            image_count -= i_count
            logger.info(' %d remaining...', image_count)


            if self._shutdown:
                sys.exit(1)


        ### videos
        logger.warning('Processing timelapses...')
        while True:
            video_query = db.session.query(
                IndiAllSkyDbVideoTable
            )\
                .filter(IndiAllSkyDbVideoTable.dayDate_year == sa_null())\
                .limit(500)


            v_count = video_query.count()
            if v_count == 0:
                break


            for v in video_query:
                v.dayDate_year   = v.dayDate.year
                v.dayDate_month  = v.dayDate.month
                v.dayDate_day    = v.dayDate.day

            db.session.commit()


            video_count -= v_count
            logger.info(' %d remaining...', video_count)


            if self._shutdown:
                sys.exit(1)


        ### mini videos
        logger.warning('Processing mini-timelapses...')
        while True:
            mini_video_query = db.session.query(
                IndiAllSkyDbMiniVideoTable
            )\
                .filter(IndiAllSkyDbMiniVideoTable.dayDate_year == sa_null())\
                .limit(500)


            m_count = mini_video_query.count()
            if m_count == 0:
                break


            for m in mini_video_query:
                m.dayDate_year   = m.dayDate.year
                m.dayDate_month  = m.dayDate.month
                m.dayDate_day    = m.dayDate.day

            db.session.commit()


            mini_video_count -= m_count
            logger.info(' %d remaining...', mini_video_count)


            if self._shutdown:
                sys.exit(1)


        elapsed_s = time.time() - start
        logger.info('Entries fixed in %0.4f s', elapsed_s)


if __name__ == "__main__":
    PopulateDates().main()

