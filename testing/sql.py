#!/usr/bin/env python3

import sys
import time
from pathlib import Path
from datetime import datetime
import logging

sys.path.append(str(Path(__file__).parent.absolute().parent))

import indi_allsky

# setup flask context for db access
app = indi_allsky.flask.create_app()
app.app_context().push()

from indi_allsky.flask.models import IndiAllSkyDbCameraTable
from indi_allsky.flask.models import IndiAllSkyDbImageTable
#from indi_allsky.flask.models import IndiAllSkyDbVideoTable

from indi_allsky.flask import db

logging.basicConfig(level=logging.INFO)
logger = logging

#logger.warning('%s', ','.join(sys.path))


class SqlTester(object):

    def __init__(self):
        pass


    def main(self):
        camera_id = 1
        timespec = '20220101'

        d_dayDate = datetime.strptime(timespec, '%Y%m%d').date()
        night = True

        timelapse_files_entries = db.session.query(IndiAllSkyDbImageTable)\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .filter(IndiAllSkyDbImageTable.dayDate == d_dayDate)\
            .filter(IndiAllSkyDbImageTable.night == night)\
            .order_by(IndiAllSkyDbImageTable.createDate.asc())


        start = time.time()

        logger.warning('Entries: %d', timelapse_files_entries.count())

        elapsed_s = time.time() - start
        logger.info('SQL executed in %0.4f s', elapsed_s)


        #logger.info('SQL: %s', timelapse_files_entries)


if __name__ == "__main__":
    st = SqlTester()
    st.main()

