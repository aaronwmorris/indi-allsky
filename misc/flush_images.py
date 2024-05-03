#!/usr/bin/env python3

import sys
import argparse
import time
from datetime import datetime
from datetime import timedelta
from pathlib import Path
import logging

from sqlalchemy.orm.exc import NoResultFound


sys.path.append(str(Path(__file__).parent.absolute().parent))


from indi_allsky.flask.models import IndiAllSkyDbImageTable
from indi_allsky.flask.models import IndiAllSkyDbVideoTable
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



class FlushImages(object):

    def __init__(self):
        try:
            self._config_obj = IndiAllSkyConfig()
            #logger.info('Loaded config id: %d', self._config_obj.config_id)
        except NoResultFound:
            logger.error('No config file found, please import a config')
            sys.exit(1)

        self.config = self._config_obj.config


        self._image_days = 30
        self._video_days = 365


        if self.config['IMAGE_FOLDER']:
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()


    @property
    def image_days(self):
        return self._image_days

    @image_days.setter
    def image_days(self, new_image_days):
        self._image_days = int(new_image_days)


    @property
    def video_days(self):
        return self._video_days

    @video_days.setter
    def video_days(self, new_video_days):
        self._video_days = int(new_video_days)


    def main(self):
        logger.info('Cutoff for images: %d days', self.image_days)
        logger.info('Cutoff for videos: %d days', self.video_days)

        time.sleep(5)


        # Old image files need to be pruned
        cutoff_age_images = datetime.now() - timedelta(days=self.image_days)
        cutoff_age_images_date = cutoff_age_images.date()  # cutoff date based on dayDate attribute, not createDate

        old_images = IndiAllSkyDbImageTable.query\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbImageTable.dayDate < cutoff_age_images_date)
        old_fits_images = IndiAllSkyDbFitsImageTable.query\
            .join(IndiAllSkyDbFitsImageTable.camera)\
            .filter(IndiAllSkyDbFitsImageTable.dayDate < cutoff_age_images_date)
        old_raw_images = IndiAllSkyDbRawImageTable.query\
            .join(IndiAllSkyDbRawImageTable.camera)\
            .filter(IndiAllSkyDbRawImageTable.dayDate < cutoff_age_images_date)
        old_panorama_images = IndiAllSkyDbPanoramaImageTable.query\
            .join(IndiAllSkyDbPanoramaImageTable.camera)\
            .filter(IndiAllSkyDbPanoramaImageTable.dayDate < cutoff_age_images_date)


        cutoff_age_timelapse = datetime.now() - timedelta(days=self.video_days)
        cutoff_age_timelapse_date = cutoff_age_timelapse.date()  # cutoff date based on dayDate attribute, not createDate

        old_videos = IndiAllSkyDbVideoTable.query\
            .join(IndiAllSkyDbVideoTable.camera)\
            .filter(IndiAllSkyDbVideoTable.dayDate < cutoff_age_timelapse_date)
        old_keograms = IndiAllSkyDbKeogramTable.query\
            .join(IndiAllSkyDbKeogramTable.camera)\
            .filter(IndiAllSkyDbKeogramTable.dayDate < cutoff_age_timelapse_date)
        old_startrails = IndiAllSkyDbStarTrailsTable.query\
            .join(IndiAllSkyDbStarTrailsTable.camera)\
            .filter(IndiAllSkyDbStarTrailsTable.dayDate < cutoff_age_timelapse_date)
        old_startrails_videos = IndiAllSkyDbStarTrailsVideoTable.query\
            .join(IndiAllSkyDbStarTrailsVideoTable.camera)\
            .filter(IndiAllSkyDbStarTrailsVideoTable.dayDate < cutoff_age_timelapse_date)
        old_panorama_videos = IndiAllSkyDbPanoramaVideoTable.query\
            .join(IndiAllSkyDbPanoramaVideoTable.camera)\
            .filter(IndiAllSkyDbPanoramaVideoTable.dayDate < cutoff_age_timelapse_date)


        logger.warning('Found %d expired images to delete', old_images.count())
        logger.warning('Found %d expired FITS images to delete', old_fits_images.count())
        logger.warning('Found %d expired RAW images to delete', old_raw_images.count())
        logger.warning('Found %d expired Panorama images to delete', old_panorama_images.count())
        logger.warning('Found %d expired videos to delete', old_videos.count())
        logger.warning('Found %d expired keograms to delete', old_keograms.count())
        logger.warning('Found %d expired star trails to delete', old_startrails.count())
        logger.warning('Found %d expired star trail videos to delete', old_startrails_videos.count())
        logger.warning('Found %d expired panorama videos to delete', old_panorama_videos.count())
        logger.info('Proceeding in 10 seconds')

        time.sleep(10)


        # images
        for file_entry in old_images:
            logger.info('Removing old image: %s', file_entry.filename)

            try:
                file_entry.deleteAsset()
            except OSError as e:
                logger.error('Cannot remove file: %s', str(e))
                continue

            db.session.delete(file_entry)


        db.session.commit()


        # fits images
        for file_entry in old_fits_images:
            logger.info('Removing old image: %s', file_entry.filename)

            try:
                file_entry.deleteAsset()
            except OSError as e:
                logger.error('Cannot remove file: %s', str(e))
                continue

            db.session.delete(file_entry)


        db.session.commit()


        # raw images
        for file_entry in old_raw_images:
            logger.info('Removing old image: %s', file_entry.filename)

            try:
                file_entry.deleteAsset()
            except OSError as e:
                logger.error('Cannot remove file: %s', str(e))
                continue

            db.session.delete(file_entry)


        db.session.commit()


        # panorama images
        for file_entry in old_panorama_images:
            logger.info('Removing old panorama: %s', file_entry.filename)

            try:
                file_entry.deleteAsset()
            except OSError as e:
                logger.error('Cannot remove file: %s', str(e))
                continue

            db.session.delete(file_entry)


        db.session.commit()


        # videos
        for file_entry in old_videos:
            logger.info('Removing old video: %s', file_entry.filename)

            try:
                file_entry.deleteAsset()
            except OSError as e:
                logger.error('Cannot remove file: %s', str(e))
                continue

            db.session.delete(file_entry)


        db.session.commit()


        # keograms
        for file_entry in old_keograms:
            logger.info('Removing old keogram: %s', file_entry.filename)

            try:
                file_entry.deleteAsset()
            except OSError as e:
                logger.error('Cannot remove file: %s', str(e))
                continue

            db.session.delete(file_entry)


        db.session.commit()


        # star trails
        for file_entry in old_startrails:
            logger.info('Removing old star trails: %s', file_entry.filename)

            try:
                file_entry.deleteAsset()
            except OSError as e:
                logger.error('Cannot remove file: %s', str(e))
                continue

            db.session.delete(file_entry)


        db.session.commit()


        # star trails video
        for file_entry in old_startrails_videos:
            logger.info('Removing old star trails video: %s', file_entry.filename)

            try:
                file_entry.deleteAsset()
            except OSError as e:
                logger.error('Cannot remove file: %s', str(e))
                continue

            db.session.delete(file_entry)


        db.session.commit()


        # panorama video
        for file_entry in old_panorama_videos:
            logger.info('Removing old panorama video: %s', file_entry.filename)

            try:
                file_entry.deleteAsset()
            except OSError as e:
                logger.error('Cannot remove file: %s', str(e))
                continue

            db.session.delete(file_entry)


        db.session.commit()


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
        '--timelapse_days',
        '-t',
        help='Videos older than days will be deleted',
        type=int,
        default=365,
    )


    args = argparser.parse_args()


    fi = FlushImages()
    fi.image_days = args.days
    fi.video_days = args.timelapse_days

    fi.main()
