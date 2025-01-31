#!/usr/bin/env python3

import sys
import argparse
import time
from datetime import datetime
from datetime import timedelta
from pathlib import Path
import signal
import logging

from sqlalchemy.orm.exc import NoResultFound


sys.path.append(str(Path(__file__).parent.absolute().parent))


from indi_allsky.flask.models import IndiAllSkyDbImageTable
from indi_allsky.flask.models import IndiAllSkyDbVideoTable
from indi_allsky.flask.models import IndiAllSkyDbMiniVideoTable
from indi_allsky.flask.models import IndiAllSkyDbKeogramTable
from indi_allsky.flask.models import IndiAllSkyDbStarTrailsTable
from indi_allsky.flask.models import IndiAllSkyDbStarTrailsVideoTable
from indi_allsky.flask.models import IndiAllSkyDbFitsImageTable
from indi_allsky.flask.models import IndiAllSkyDbPanoramaImageTable
from indi_allsky.flask.models import IndiAllSkyDbPanoramaVideoTable
from indi_allsky.flask.models import IndiAllSkyDbRawImageTable

from indi_allsky.config import IndiAllSkyConfig

from indi_allsky.flask import db
from indi_allsky.flask import create_app


logger = logging.getLogger('indi_allsky')
logger.setLevel(logging.INFO)


# setup flask context for db access
app = create_app()
app.app_context().push()


LOG_FORMATTER_STREAM = logging.Formatter('[%(levelname)s]: %(message)s')

LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)

logger.handlers.clear()  # remove syslog
logger.addHandler(LOG_HANDLER_STREAM)



class ExpireImages(object):

    def __init__(self):
        try:
            self._config_obj = IndiAllSkyConfig()
            #logger.info('Loaded config id: %d', self._config_obj.config_id)
        except NoResultFound:
            logger.error('No config file found, please import a config')
            sys.exit(1)

        self.config = self._config_obj.config


        self._image_days = 30
        self._image_raw_days = 10
        self._image_fits_days = 10
        self._video_days = 365


        if self.config['IMAGE_FOLDER']:
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()


        self._shutdown = False


    @property
    def image_days(self):
        return self._image_days

    @image_days.setter
    def image_days(self, new_image_days):
        self._image_days = int(new_image_days)


    @property
    def image_raw_days(self):
        return self._image_raw_days

    @image_raw_days.setter
    def image_raw_days(self, new_image_raw_days):
        self._image_raw_days = int(new_image_raw_days)


    @property
    def image_fits_days(self):
        return self._image_fits_days

    @image_fits_days.setter
    def image_fits_days(self, new_image_fits_days):
        self._image_fits_days = int(new_image_fits_days)


    @property
    def video_days(self):
        return self._video_days

    @video_days.setter
    def video_days(self, new_video_days):
        self._video_days = int(new_video_days)


    def sigint_handler_main(self, signum, frame):
        logger.warning('Caught INT signal, shutting down')

        # set flag for program to stop processes
        self._shutdown = True



    def main(self):
        logger.info('Cutoff for images:       %d days', self.image_days)
        logger.info('Cutoff for raw images:   %d days', self.image_raw_days)
        logger.info('Cutoff for fits images:  %d days', self.image_fits_days)
        logger.info('Cutoff for videos:       %d days', self.video_days)

        time.sleep(5)


        now = datetime.now()

        # Old image files need to be pruned
        cutoff_age_images = now - timedelta(days=self.image_days)
        cutoff_age_images_date = cutoff_age_images.date()  # cutoff date based on dayDate attribute, not createDate

        old_images = IndiAllSkyDbImageTable.query\
            .filter(IndiAllSkyDbImageTable.dayDate < cutoff_age_images_date)\
            .order_by(IndiAllSkyDbImageTable.createDate.asc())
        old_panorama_images = IndiAllSkyDbPanoramaImageTable.query\
            .filter(IndiAllSkyDbPanoramaImageTable.dayDate < cutoff_age_images_date)\
            .order_by(IndiAllSkyDbPanoramaImageTable.createDate.asc())


        # raw
        cutoff_age_images_raw = now - timedelta(days=self.image_raw_days)
        cutoff_age_images_raw_date = cutoff_age_images_raw.date()  # cutoff date based on dayDate attribute, not createDate

        old_raw_images = IndiAllSkyDbRawImageTable.query\
            .filter(IndiAllSkyDbRawImageTable.dayDate < cutoff_age_images_raw_date)\
            .order_by(IndiAllSkyDbRawImageTable.createDate.asc())


        # fits
        cutoff_age_images_fits = now - timedelta(days=self.image_fits_days)
        cutoff_age_images_fits_date = cutoff_age_images_fits.date()  # cutoff date based on dayDate attribute, not createDate

        old_fits_images = IndiAllSkyDbFitsImageTable.query\
            .filter(IndiAllSkyDbFitsImageTable.dayDate < cutoff_age_images_fits_date)\
            .order_by(IndiAllSkyDbFitsImageTable.createDate.asc())


        # videos
        cutoff_age_timelapse = now - timedelta(days=self.video_days)
        cutoff_age_timelapse_date = cutoff_age_timelapse.date()  # cutoff date based on dayDate attribute, not createDate

        old_videos = IndiAllSkyDbVideoTable.query\
            .filter(IndiAllSkyDbVideoTable.dayDate < cutoff_age_timelapse_date)\
            .order_by(IndiAllSkyDbVideoTable.createDate.asc())
        old_mini_videos = IndiAllSkyDbMiniVideoTable.query\
            .filter(IndiAllSkyDbMiniVideoTable.dayDate < cutoff_age_timelapse_date)\
            .order_by(IndiAllSkyDbMiniVideoTable.createDate.asc())
        old_keograms = IndiAllSkyDbKeogramTable.query\
            .filter(IndiAllSkyDbKeogramTable.dayDate < cutoff_age_timelapse_date)\
            .order_by(IndiAllSkyDbKeogramTable.createDate.asc())
        old_startrails = IndiAllSkyDbStarTrailsTable.query\
            .filter(IndiAllSkyDbStarTrailsTable.dayDate < cutoff_age_timelapse_date)\
            .order_by(IndiAllSkyDbStarTrailsTable.createDate.asc())
        old_startrails_videos = IndiAllSkyDbStarTrailsVideoTable.query\
            .filter(IndiAllSkyDbStarTrailsVideoTable.dayDate < cutoff_age_timelapse_date)\
            .order_by(IndiAllSkyDbStarTrailsVideoTable.createDate.asc())
        old_panorama_videos = IndiAllSkyDbPanoramaVideoTable.query\
            .filter(IndiAllSkyDbPanoramaVideoTable.dayDate < cutoff_age_timelapse_date)\
            .order_by(IndiAllSkyDbPanoramaVideoTable.createDate.asc())


        logger.warning('Found %d expired images to delete', old_images.count())
        logger.warning('Found %d expired Panorama images to delete', old_panorama_images.count())
        logger.warning('Found %d expired FITS images to delete', old_fits_images.count())
        logger.warning('Found %d expired RAW images to delete', old_raw_images.count())
        logger.warning('Found %d expired videos to delete', old_videos.count())
        logger.warning('Found %d expired mini videos to delete', old_mini_videos.count())
        logger.warning('Found %d expired keograms to delete', old_keograms.count())
        logger.warning('Found %d expired star trails to delete', old_startrails.count())
        logger.warning('Found %d expired star trail videos to delete', old_startrails_videos.count())
        logger.warning('Found %d expired panorama videos to delete', old_panorama_videos.count())
        logger.info('Proceeding in 10 seconds')

        time.sleep(10)


        ### Getting IDs first then deleting each file is faster than deleting all files with
        ### thumbnails with a single query.  Deleting associated thumbnails causes sqlalchemy
        ### to recache after every delete which cause a 1-5 second lag for each delete


        # catch signals to perform cleaner shutdown
        signal.signal(signal.SIGINT, self.sigint_handler_main)



        logger.warning('Deleting...')


        asset_lists = [
            (old_images, IndiAllSkyDbImageTable),
            (old_panorama_images, IndiAllSkyDbPanoramaImageTable),
            (old_fits_images, IndiAllSkyDbFitsImageTable),
            (old_raw_images, IndiAllSkyDbRawImageTable),
            (old_videos, IndiAllSkyDbVideoTable),
            (old_mini_videos, IndiAllSkyDbMiniVideoTable),
            (old_keograms, IndiAllSkyDbKeogramTable),
            (old_startrails, IndiAllSkyDbStarTrailsTable),
            (old_startrails_videos, IndiAllSkyDbStarTrailsVideoTable),
            (old_panorama_videos, IndiAllSkyDbPanoramaVideoTable),
        ]


        delete_count = 0
        for asset_list, asset_table in asset_lists:
            while True:
                id_list = [entry.id for entry in asset_list.limit(500)]

                if not id_list:
                    break

                delete_count += self._deleteAssets(asset_table, id_list)


        # Remove empty folders
        dir_list = list()
        self._getFolderFolders(self.image_dir, dir_list)

        empty_dirs = filter(lambda p: not any(p.iterdir()), dir_list)
        for d in empty_dirs:
            logger.info('Removing empty directory: %s', d)

            try:
                d.rmdir()
            except OSError as e:
                logger.error('Cannot remove folder: %s', str(e))
            except PermissionError as e:
                logger.error('Cannot remove folder: %s', str(e))


        logger.warning('Deleted %d assets', delete_count)


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


    def _getFolderFolders(self, folder, dir_list):
        for item in Path(folder).iterdir():
            if item.is_dir():
                dir_list.append(item)
                self._getFolderFolders(item, dir_list)  # recursion



if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        '--days',
        '-d',
        help='Images older than days will be deleted',
        type=int,
        default=30,
    )
    argparser.add_argument(
        '--raw',
        '-r',
        help='RAW Images older than days will be deleted',
        type=int,
        default=10,
    )
    argparser.add_argument(
        '--fits',
        '-f',
        help='FITS Images older than days will be deleted',
        type=int,
        default=10,
    )
    argparser.add_argument(
        '--timelapse_days',
        '-t',
        help='Videos older than days will be deleted',
        type=int,
        default=365,
    )


    args = argparser.parse_args()


    ei = ExpireImages()
    ei.image_days = args.days
    ei.image_raw_days = args.raw
    ei.image_fits_days = args.fits
    ei.video_days = args.timelapse_days

    ei.main()
