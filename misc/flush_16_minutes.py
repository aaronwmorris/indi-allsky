#!/usr/bin/env python3
###########################################################
# This script will flush images taken in the last 16      #
# minutes in the database.  This will prevent the last    #
# exposure/gain/bin settings from being reused.           #
# THERE IS NO WAY TO RECOVER                              #
###########################################################

import sys
from pathlib import Path
import time
from datetime import datetime
from datetime import timedelta
import argparse
import signal
import logging

from sqlalchemy.orm.exc import NoResultFound


sys.path.insert(0, str(Path(__file__).parent.absolute().parent))


from indi_allsky.flask import create_app

# setup flask context for db access

app = create_app()
app.app_context().push()


from indi_allsky.flask import db
from indi_allsky.flask.models import IndiAllSkyDbCameraTable
from indi_allsky.flask.models import IndiAllSkyDbImageTable


logger = logging.getLogger('indi_allsky')
logger.setLevel(logging.INFO)

LOG_FORMATTER_STREAM = logging.Formatter('[%(levelname)s]: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)
logger.addHandler(LOG_HANDLER_STREAM)



class FlushImages16Minutes(object):

    flush_minutes = 16


    def __init__(self):
        self._camera_id = 1

        self._shutdown = False


    @property
    def camera_id(self):
        return self._camera_id

    @camera_id.setter
    def camera_id(self, new_camera_id):
        self._camera_id = int(new_camera_id)


    def sigint_handler_main(self, signum, frame):
        logger.warning('Caught INT signal, shutting down')
        self._shutdown = True


    def main(self):

        try:
            camera_entry = IndiAllSkyDbCameraTable.query\
                .filter(IndiAllSkyDbCameraTable.id == self.camera_id)\
                .one()
        except NoResultFound:
            logger.error('Camera with ID %d not found', self.camera_id)
            sys.exit(1)


        print()
        print()
        print('DANGER:  THIS ACTION IS NOT RECOVERABLE !!!')
        print()
        print('This script will delete 16 minutes of images from the database and filesystem')
        print()
        print('Camera ID:    {0:d} [{1:s}]'.format(self.camera_id, camera_entry.name))
        print()
        print('Running in 10 seconds... control-c to cancel')
        print()

        time.sleep(10.0)

        signal.signal(signal.SIGINT, self.sigint_handler_main)


        self.flushImages(self.camera_id)


    def flushImages(self, camera_id):
        ### Images
        now  = datetime.now()
        now_minus_x_minutes = now - timedelta(minutes=self.flush_minutes)

        image_query = IndiAllSkyDbImageTable.query\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .filter(IndiAllSkyDbImageTable.createDate >= now_minus_x_minutes)\
            .order_by(IndiAllSkyDbImageTable.createDate.asc())


        logger.warning('Found %d images to delete', image_query.count())

        time.sleep(10)


        asset_lists = [
            (image_query, IndiAllSkyDbImageTable),
        ]


        delete_count = 0
        for asset_list, asset_table in asset_lists:
            while True:
                id_list = [entry.id for entry in asset_list.limit(500)]

                if not id_list:
                    break

                delete_count += self._deleteAssets(asset_table, id_list)


        return delete_count


    def _deleteAssets(self, table, entry_id_list):
        delete_count = 0
        for entry_id in entry_id_list:
            entry = table.query\
                .filter(table.id == entry_id)\
                .one()

            logger.info('Removing old %s entry: %s', entry.__class__.__name__, entry.filename)

            try:
                entry.deleteAsset()
            except OSError as e:
                logger.error('Cannot remove file: %s', str(e))
                continue

            db.session.delete(entry)
            db.session.commit()

            delete_count += 1

            if self._shutdown:
                sys.exit(1)

        return delete_count


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        '--camera_id',
        '-c',
        help='camera id',
        type=int,
        default=1
    )


    args = argparser.parse_args()

    fi16 = FlushImages16Minutes()
    fi16.camera_id = args.camera_id

    fi16.main()

