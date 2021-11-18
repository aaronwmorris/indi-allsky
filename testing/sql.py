#!/usr/bin/env python3

import sys
import time
from pathlib import Path
from datetime import datetime
import logging

sys.path.append(str(Path(__file__).parent.absolute().parent))

from indi_allsky.db import IndiAllSkyDb
from indi_allsky.db import IndiAllSkyDbCameraTable
from indi_allsky.db import IndiAllSkyDbImageTable
#from indi_allsky.db import IndiAllSkyDbVideoTable


CONFIG = {
    'DB_URI' : 'sqlite:////var/lib/indi-allsky/indi-allsky.sqlite',
}


logging.basicConfig(level=logging.INFO)
logger = logging

#logger.warning('%s', ','.join(sys.path))


class SqlTester(object):

    def __init__(self):
        self._db = IndiAllSkyDb(CONFIG)


    def main(self):
        camera_id = 1
        timespec = '20211107'

        d_dayDate = datetime.strptime(timespec, '%Y%m%d').date()
        night = True

        dbsession = self._db.session

        timelapse_files_entries = dbsession.query(IndiAllSkyDbImageTable)\
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

