#!/usr/bin/env python3

import sys
import time
from pathlib import Path
from datetime import datetime
#from datetime import timedelta
import logging

sys.path.append(str(Path(__file__).parent.absolute().parent))

from indi_allsky.flask import create_app

# setup flask context for db access
app = create_app()
app.app_context().push()

from indi_allsky.flask.models import IndiAllSkyDbCameraTable
from indi_allsky.flask.models import IndiAllSkyDbImageTable
#from indi_allsky.flask.models import IndiAllSkyDbVideoTable

from sqlalchemy import func
from sqlalchemy import cast
from sqlalchemy.types import DateTime
from sqlalchemy.types import Boolean
#from sqlalchemy.types import Integer

from indi_allsky.flask import db

logging.basicConfig(level=logging.INFO)
logger = logging

#logger.warning('%s', ','.join(sys.path))


class SqlTester(object):

    def __init__(self):
        pass


    def main(self):
        camera_id = 1
        timespec = '20230821'

        d_dayDate = datetime.strptime(timespec, '%Y%m%d').date()
        night = True


        createDate_local = func.datetime(IndiAllSkyDbImageTable.createDate, 'localtime', type_=DateTime).label('createDate_local')

        #timelapse_files_entries = db.session.query(
        #    IndiAllSkyDbImageTable,
        #    createDate_local,
        #)\
        #    .join(IndiAllSkyDbImageTable.camera)\
        #    .filter(IndiAllSkyDbCameraTable.id == camera_id)\
        #    .filter(IndiAllSkyDbImageTable.dayDate == d_dayDate)\
        #    .filter(IndiAllSkyDbImageTable.night == night)\
        #    .order_by(IndiAllSkyDbImageTable.createDate.asc())

        timelapse_files_entries = IndiAllSkyDbImageTable.query\
            .add_columns(
                createDate_local,
                IndiAllSkyDbImageTable.id,
                IndiAllSkyDbImageTable.kpindex,
                IndiAllSkyDbImageTable.filename,
            )\
            .join(IndiAllSkyDbCameraTable)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .filter(IndiAllSkyDbImageTable.dayDate == d_dayDate)\
            .filter(cast(IndiAllSkyDbImageTable.data['night'], Boolean) == night)\
            .order_by(IndiAllSkyDbImageTable.createDate.asc())

        #    .filter(IndiAllSkyDbImageTable.night == night)\

        #now_minus_3h = datetime.now() - timedelta(hours=3)

        #createDate_s = func.strftime('%s', IndiAllSkyDbImageTable.createDate, type_=Integer)
        #image_lag_list = IndiAllSkyDbImageTable.query\
        #    .add_columns(
        #        IndiAllSkyDbImageTable.id,
        #        (createDate_s - func.lag(createDate_s).over(order_by=IndiAllSkyDbImageTable.createDate)).label('lag_diff'),
        #    )\
        #    .filter(IndiAllSkyDbImageTable.createDate > now_minus_3h)\
        #    .order_by(IndiAllSkyDbImageTable.createDate.desc())\
        #    .limit(50)


        start = time.time()

        logger.warning('Entries: %d', timelapse_files_entries.count())
        #logger.warning('Entries: %d', image_lag_list.count())

        elapsed_s = time.time() - start
        logger.info('SQL executed in %0.4f s', elapsed_s)


        sql = timelapse_files_entries.statement.compile(db.engine, compile_kwargs={ "literal_binds" : True })
        #logger.info('SQL: %s', timelapse_files_entries)
        logger.info('SQL: %s', sql)

        for i in timelapse_files_entries:
            #logger.info('attrs: %s', i.keys())
            logger.info('id: %d, kpindex: %s, image: %s', i.id, str(i.kpindex), i.filename)


if __name__ == "__main__":
    st = SqlTester()
    st.main()

