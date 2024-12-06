#!/usr/bin/env python3
###
### This script populates required data in the database for new functionality
### Safe to re-run and cancel at any time
###

import sys
import time
from pathlib import Path
#from datetime import datetime
#from datetime import timedelta
import signal
import logging

from sqlalchemy.sql.expression import null as sa_null

sys.path.append(str(Path(__file__).parent.absolute().parent))

from indi_allsky.flask.models import IndiAllSkyDbImageTable
from indi_allsky.flask.models import IndiAllSkyDbPanoramaImageTable
from indi_allsky.flask.models import IndiAllSkyDbFitsImageTable
from indi_allsky.flask.models import IndiAllSkyDbVideoTable
from indi_allsky.flask.models import IndiAllSkyDbMiniVideoTable

from indi_allsky.flask import create_app
from indi_allsky.flask import db


# setup flask context for db access
app = create_app()
app.app_context().push()


LOG_FORMATTER_STREAM = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)


logger = logging.getLogger('indi_allsky')
logger.handlers.clear()
logger.addHandler(LOG_HANDLER_STREAM)
logger.setLevel(logging.INFO)


class PopulateData(object):

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

        panorama_image_count = db.session.query(
            IndiAllSkyDbPanoramaImageTable
        )\
            .filter(IndiAllSkyDbPanoramaImageTable.createDate_year == sa_null())\
            .count()

        fits_image_count = db.session.query(
            IndiAllSkyDbFitsImageTable
        )\
            .filter(IndiAllSkyDbFitsImageTable.createDate_year == sa_null())\
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
        print('Panorama Image entries to fix: {0:d}'.format(panorama_image_count))
        print('FITS Image entries to fix: {0:d}'.format(fits_image_count))
        print('Timelapse entries to fix: {0:d}'.format(video_count))
        print('Mini Timelapse entries to fix: {0:d}'.format(mini_video_count))
        print()


        total_count = image_count
        total_count += panorama_image_count
        total_count += fits_image_count
        total_count += video_count
        total_count += mini_video_count

        if total_count == 0:
            print('No updates needed')
            sys.exit()


        print('This process may require 10-20 minutes in some cases')
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


        ### panorama images
        logger.warning('Processing panorama images...')
        while True:
            panorama_image_query = db.session.query(
                IndiAllSkyDbPanoramaImageTable
            )\
                .filter(IndiAllSkyDbPanoramaImageTable.createDate_year == sa_null())\
                .limit(500)


            p_count = panorama_image_query.count()
            if p_count == 0:
                break


            for p in panorama_image_query:
                p.createDate_year   = p.createDate.year
                p.createDate_month  = p.createDate.month
                p.createDate_day    = p.createDate.day
                p.createDate_hour   = p.createDate.hour

            db.session.commit()


            panorama_image_count -= p_count
            logger.info(' %d remaining...', panorama_image_count)


            if self._shutdown:
                sys.exit(1)


        ### FITS images
        logger.warning('Processing FITS images...')
        while True:
            fits_image_query = db.session.query(
                IndiAllSkyDbFitsImageTable
            )\
                .filter(IndiAllSkyDbFitsImageTable.createDate_year == sa_null())\
                .limit(500)


            f_count = fits_image_query.count()
            if p_count == 0:
                break


            for f in fits_image_query:
                f.createDate_year   = f.createDate.year
                f.createDate_month  = f.createDate.month
                f.createDate_day    = f.createDate.day
                f.createDate_hour   = f.createDate.hour

            db.session.commit()


            fits_image_count -= f_count
            logger.info(' %d remaining...', fits_image_count)


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
    PopulateData().main()

