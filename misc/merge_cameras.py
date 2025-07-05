#!/usr/bin/env python3
#########################################################
# This script changes the camera foreign key associated #
# with all images and videos to a different camera      #
#########################################################

import sys
from pathlib import Path
import argparse
import time
import signal
import logging

from sqlalchemy import update
from sqlalchemy import bindparam
from sqlalchemy.orm.exc import NoResultFound


sys.path.insert(0, str(Path(__file__).parent.absolute().parent))


from indi_allsky.flask import create_app

# setup flask context for db access

app = create_app()
app.app_context().push()

from indi_allsky.flask import db
from indi_allsky.flask.models import IndiAllSkyDbCameraTable
from indi_allsky.flask.models import IndiAllSkyDbImageTable
from indi_allsky.flask.models import IndiAllSkyDbRawImageTable
from indi_allsky.flask.models import IndiAllSkyDbFitsImageTable
from indi_allsky.flask.models import IndiAllSkyDbVideoTable
from indi_allsky.flask.models import IndiAllSkyDbMiniVideoTable
from indi_allsky.flask.models import IndiAllSkyDbKeogramTable
from indi_allsky.flask.models import IndiAllSkyDbStarTrailsTable
from indi_allsky.flask.models import IndiAllSkyDbStarTrailsVideoTable
from indi_allsky.flask.models import IndiAllSkyDbPanoramaImageTable
from indi_allsky.flask.models import IndiAllSkyDbPanoramaVideoTable
from indi_allsky.flask.models import IndiAllSkyDbLongTermKeogramTable
from indi_allsky.flask.models import IndiAllSkyDbThumbnailTable




logger = logging.getLogger('indi_allsky')
logger.setLevel(logging.INFO)

LOG_FORMATTER_STREAM = logging.Formatter('[%(levelname)s]: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)
logger.addHandler(LOG_HANDLER_STREAM)



class MergeCameras(object):

    def __init__(self):
        self._new_camera_id = 0
        self._orig_camera_id = 0

        self._shutdown = False


    @property
    def new_camera_id(self):
        return self._new_camera_id

    @new_camera_id.setter
    def new_camera_id(self, new_camera_id):
        self._new_camera_id = int(new_camera_id)


    @property
    def orig_camera_id(self):
        return self._orig_camera_id

    @orig_camera_id.setter
    def orig_camera_id(self, new_camera_id):
        self._orig_camera_id = int(new_camera_id)


    def sigint_handler_main(self, signum, frame):
        logger.warning('Caught INT signal, shutting down')
        self._shutdown = True


    def main(self):
        try:
            new_camera_entry = IndiAllSkyDbCameraTable.query\
                .filter(IndiAllSkyDbCameraTable.id == self.new_camera_id)\
                .one()
        except NoResultFound:
            logger.error('Camera with ID %d not found', self.new_camera_id)
            sys.exit(1)

        try:
            orig_camera_entry = IndiAllSkyDbCameraTable.query\
                .filter(IndiAllSkyDbCameraTable.id == self.orig_camera_id)\
                .one()
        except NoResultFound:
            logger.error('Camera with ID %d not found', self.orig_camera_id)
            sys.exit(1)


        new_images = IndiAllSkyDbImageTable.query\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == new_camera_entry.id)

        orig_images = IndiAllSkyDbImageTable.query\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == orig_camera_entry.id)

        logger.warning('New camera: %d - %s, Images: %d', new_camera_entry.id, new_camera_entry.name, new_images.count())
        logger.warning('Original camera: %d - %s, Images: %d', orig_camera_entry.id, orig_camera_entry.name, orig_images.count())
        logger.info('Proceeding in 10 seconds (Control-c to cancel)')

        time.sleep(10)

        signal.signal(signal.SIGINT, self.sigint_handler_main)


        tables = (
            IndiAllSkyDbImageTable,
            IndiAllSkyDbRawImageTable,
            IndiAllSkyDbFitsImageTable,
            IndiAllSkyDbVideoTable,
            IndiAllSkyDbMiniVideoTable,
            IndiAllSkyDbKeogramTable,
            IndiAllSkyDbStarTrailsTable,
            IndiAllSkyDbStarTrailsVideoTable,
            IndiAllSkyDbPanoramaImageTable,
            IndiAllSkyDbPanoramaVideoTable,
            IndiAllSkyDbLongTermKeogramTable,
            IndiAllSkyDbThumbnailTable,
        )

        for table in tables:
            if self._shutdown:
                sys.exit(1)


            logger.info('Updating table entries')


            update_stmt = update(table)\
                .where(table.camera_id == bindparam('new_camera_id'))

            db.session.connection().execute(
                update_stmt, [
                    {
                        'new_camera_id' : new_camera_entry.id,
                        'camera_id'     : orig_camera_entry.id,
                    }
                ]
            )

            db.session.commit()



        # merge cameras
        if not orig_camera_entry.name_alt1:
            orig_camera_entry.name_alt1 = new_camera_entry.name
        elif not orig_camera_entry.name_alt2:
            orig_camera_entry.name_alt2 = new_camera_entry.name
        else:
            logger.error('No name slots available on original camera')
            sys.exit(1)


        new_camera_entry.name = 'Merged with {0:s} {1:d}'.format(orig_camera_entry.name, new_camera_entry.id)
        #new_camera_entry.hidden = True

        db.session.commit()


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        '--new_camera_id',
        '-n',
        help='new camera id',
        type=int,
        required=True,
    )
    argparser.add_argument(
        '--orig_camera_id',
        '-orig',
        help='original camera id',
        type=int,
        required=True,
    )

    args = argparser.parse_args()


    mc = MergeCameras()

    mc.new_camera_id = args.new_camera_id
    mc.orig_camera_id = args.orig_camera_id

    mc.main()

