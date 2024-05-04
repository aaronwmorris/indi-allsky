#!/usr/bin/env python3

import sys
import time
from pathlib import Path
import signal
import logging

#from sqlalchemy.sql.expression import true as sa_true
from sqlalchemy.sql.expression import null as sa_null
from sqlalchemy.orm.exc import NoResultFound


sys.path.append(str(Path(__file__).parent.absolute().parent))

from indi_allsky.flask import create_app

# setup flask context for db access
app = create_app()
app.app_context().push()

#from indi_allsky.flask import db
from indi_allsky.config import IndiAllSkyConfig
from indi_allsky.flask.miscDb import miscDb

from indi_allsky.flask.models import IndiAllSkyDbImageTable
from indi_allsky.flask.models import IndiAllSkyDbKeogramTable
from indi_allsky.flask.models import IndiAllSkyDbStarTrailsTable
#from indi_allsky.flask.models import IndiAllSkyDbThumbnailTable

from indi_allsky import constants


logging.basicConfig(level=logging.INFO)
logger = logging


class CreateThumbnails(object):

    thumbnail_keogram_width = 1000
    thumbnail_startrail_width = 300

    def __init__(self):
        try:
            self._config_obj = IndiAllSkyConfig()
            #logger.info('Loaded config id: %d', self._config_obj.config_id)
        except NoResultFound:
            logger.error('No config file found, please import a config')
            sys.exit(1)

        self.config = self._config_obj.config

        self._miscDb = miscDb(self.config)

        self._shutdown = False


    def sigint_handler_main(self, signum, frame):
        logger.warning('Caught INT signal, shutting down')
        self._shutdown = True


    def main(self):

        keograms_nothumbnail = IndiAllSkyDbKeogramTable.query\
            .filter(IndiAllSkyDbKeogramTable.thumbnail_uuid == sa_null())\
            .order_by(IndiAllSkyDbKeogramTable.createDate.desc())

        startrails_nothumbnail = IndiAllSkyDbStarTrailsTable.query\
            .filter(IndiAllSkyDbStarTrailsTable.thumbnail_uuid == sa_null())\
            .order_by(IndiAllSkyDbStarTrailsTable.createDate.desc())

        images_nothumbnail = IndiAllSkyDbImageTable.query\
            .filter(IndiAllSkyDbImageTable.thumbnail_uuid == sa_null())\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())



        print('Keograms without thumbnails:   {0:d}'.format(keograms_nothumbnail.count()))
        print('Startrails without thumbnails: {0:d}'.format(startrails_nothumbnail.count()))
        print('Images without thumbnails:     {0:d}'.format(images_nothumbnail.count()))
        print()
        print('Running in 10 seconds... control-c to cancel')
        print()

        time.sleep(10.0)


        signal.signal(signal.SIGINT, self.sigint_handler_main)


        for keogram_entry in keograms_nothumbnail:
            logger.info('Creating keogram thumbnail for %d', keogram_entry.id)

            keogram_thumbnail_metadata = {
                'type'       : constants.THUMBNAIL,
                'origin'     : constants.KEOGRAM,
                'createDate' : keogram_entry.createDate.timestamp(),
                'night'      : keogram_entry.night,
                'camera_uuid': keogram_entry.camera.uuid,
            }

            self._miscDb.addThumbnail(
                keogram_entry,
                {'type' : constants.KEOGRAM},  # keogram metadata not fully populated
                keogram_entry.camera_id,
                keogram_thumbnail_metadata,
                new_width=self.thumbnail_keogram_width,
            )


            if self._shutdown:
                sys.exit(1)

        for startrail_entry in startrails_nothumbnail:
            logger.info('Creating startrail thumbnail for %d', startrail_entry.id)

            startrail_thumbnail_metadata = {
                'type'       : constants.THUMBNAIL,
                'origin'     : constants.STARTRAIL,
                'createDate' : startrail_entry.createDate.timestamp(),
                'night'      : startrail_entry.night,
                'camera_uuid': startrail_entry.camera.uuid,
            }

            self._miscDb.addThumbnail(
                startrail_entry,
                {'type' : constants.STARTRAIL},  # startrail metadata not fully populated
                startrail_entry.camera_id,
                startrail_thumbnail_metadata,
                new_width=self.thumbnail_startrail_width,
            )


            if self._shutdown:
                sys.exit(1)

        for image_entry in images_nothumbnail:
            logger.info('Creating image thumbnail for %d', image_entry.id)

            image_thumbnail_metadata = {
                'type'       : constants.THUMBNAIL,
                'origin'     : constants.IMAGE,
                'createDate' : image_entry.createDate.timestamp(),
                'night'      : image_entry.night,
                'camera_uuid': image_entry.camera.uuid,
            }

            self._miscDb.addThumbnail(
                image_entry,
                {'type' : constants.IMAGE},  # image metadata not fully populated
                image_entry.camera_id,
                image_thumbnail_metadata,
            )


            if self._shutdown:
                sys.exit(1)




if __name__ == "__main__":
    ct = CreateThumbnails()
    ct.main()
