#!/usr/bin/env python3

import sys
import time
import argparse
from pathlib import Path
import signal
import logging

from sqlalchemy.orm.exc import NoResultFound

sys.path.append(str(Path(__file__).parent.absolute().parent))

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


logger = logging.getLogger('indi_allsky')
logger.setLevel(logging.INFO)

LOG_FORMATTER_STREAM = logging.Formatter('[%(levelname)s]: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)
logger.addHandler(LOG_HANDLER_STREAM)



class FlushImages(object):


    def __init__(self):
        self._camera_id = 1
        self._flush_images = True
        self._flush_videos = False

        self._shutdown = False


    @property
    def camera_id(self):
        return self._camera_id

    @camera_id.setter
    def camera_id(self, new_camera_id):
        self._camera_id = int(new_camera_id)

    @property
    def flush_images(self):
        return self._flush_images

    @flush_images.setter
    def flush_images(self, new_flush_images):
        self._flush_images = bool(new_flush_images)

    @property
    def flush_videos(self):
        return self._flush_videos

    @flush_videos.setter
    def flush_videos(self, new_flush_videos):
        self._flush_videos = bool(new_flush_videos)


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
        print('This script will delete image and/or video files in the indi-allsky database and filesystem')
        print()
        print('Camera ID:    {0:d} [{1:s}]'.format(self.camera_id, camera_entry.name))
        print('Flush Images: {0:s}  [images, fits, raw, panorama images]'.format(str(self.flush_images)))
        print('Flush Videos: {0:s}  [timelapses, keograms, startrails, panorama timelapses]'.format(str(self.flush_videos)))
        print()
        print('Running in 10 seconds... control-c to cancel')
        print()

        time.sleep(10.0)

        signal.signal(signal.SIGINT, self.sigint_handler_main)


        if self.flush_images:
            self.flushImages(self.camera_id)


        if self.flush_videos:
            self.flushTimelapses(self.camera_id)


    def flushImages(self, camera_id):
        ### Images
        image_query = IndiAllSkyDbImageTable.query\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .order_by(IndiAllSkyDbImageTable.createDate.asc())


        ### FITS Images
        fits_image_query = IndiAllSkyDbFitsImageTable.query\
            .join(IndiAllSkyDbFitsImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .order_by(IndiAllSkyDbFitsImageTable.createDate.asc())


        ### RAW Images
        raw_image_query = IndiAllSkyDbRawImageTable.query\
            .join(IndiAllSkyDbRawImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .order_by(IndiAllSkyDbRawImageTable.createDate.asc())


        ### Panorama Images
        panorama_image_query = IndiAllSkyDbPanoramaImageTable.query\
            .join(IndiAllSkyDbPanoramaImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .order_by(IndiAllSkyDbPanoramaImageTable.createDate.asc())


        image_count = image_query.count()
        fits_image_count = fits_image_query.count()
        raw_image_count = raw_image_query.count()
        panorama_image_count = panorama_image_query.count()

        file_count = image_count
        file_count += fits_image_count
        file_count += raw_image_count
        file_count += panorama_image_count


        ### Getting IDs first then deleting each file is faster than deleting all files with
        ### thumbnails with a single query.  Deleting associated thumbnails causes sqlalchemy
        ### to recache after every delete which cause a 1-5 second lag for each delete

        image_id_list = list()
        for entry in image_query:
            image_id_list.append(entry.id)

        fits_id_list = list()
        for entry in fits_image_query:
            fits_id_list.append(entry.id)

        raw_id_list = list()
        for entry in raw_image_query:
            raw_id_list.append(entry.id)

        panorama_image_id_list = list()
        for entry in panorama_image_query:
            panorama_image_id_list.append(entry.id)


        logger.warning('Flushing %d Images', image_count)
        time.sleep(3.0)
        self._deleteAssets(IndiAllSkyDbImageTable, image_id_list)

        logger.warning('Flushing %d FITS', fits_image_count)
        time.sleep(3.0)
        self._deleteAssets(IndiAllSkyDbFitsImageTable, fits_id_list)

        logger.warning('Flushing %d RAW', raw_image_count)
        time.sleep(3.0)
        self._deleteAssets(IndiAllSkyDbRawImageTable, raw_id_list)

        logger.warning('Flushing %d Panorama Images', panorama_image_count)
        time.sleep(3.0)
        self._deleteAssets(IndiAllSkyDbPanoramaImageTable, panorama_image_id_list)


        return file_count


    def flushTimelapses(self, camera_id):
        video_query = IndiAllSkyDbVideoTable.query\
            .join(IndiAllSkyDbVideoTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .order_by(IndiAllSkyDbVideoTable.createDate.asc())

        mini_video_query = IndiAllSkyDbMiniVideoTable.query\
            .join(IndiAllSkyDbMiniVideoTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .order_by(IndiAllSkyDbMiniVideoTable.createDate.asc())

        keogram_query = IndiAllSkyDbKeogramTable.query\
            .join(IndiAllSkyDbKeogramTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .order_by(IndiAllSkyDbKeogramTable.createDate.asc())

        startrail_query = IndiAllSkyDbStarTrailsTable.query\
            .join(IndiAllSkyDbStarTrailsTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .order_by(IndiAllSkyDbStarTrailsTable.createDate.asc())

        startrail_video_query = IndiAllSkyDbStarTrailsVideoTable.query\
            .join(IndiAllSkyDbStarTrailsVideoTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .order_by(IndiAllSkyDbStarTrailsVideoTable.createDate.asc())

        panorama_video_query = IndiAllSkyDbPanoramaVideoTable.query\
            .join(IndiAllSkyDbPanoramaVideoTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .order_by(IndiAllSkyDbPanoramaVideoTable.createDate.asc())

        video_count = video_query.count()
        mini_video_count = mini_video_query.count()
        keogram_count = keogram_query.count()
        startrail_count = startrail_query.count()
        startrail_video_count = startrail_video_query.count()
        panorama_video_count = panorama_video_query.count()


        file_count = video_count
        file_count += mini_video_count
        file_count += keogram_count
        file_count += startrail_count
        file_count += startrail_video_count
        file_count += panorama_video_count


        ### Getting IDs first then deleting each file is faster than deleting all files with
        ### thumbnails with a single query.  Deleting associated thumbnails causes sqlalchemy
        ### to recache after every delete which cause a 1-5 second lag for each delete

        video_id_list = list()
        for entry in video_query:
            video_id_list.append(entry.id)

        mini_video_id_list = list()
        for entry in mini_video_query:
            mini_video_id_list.append(entry.id)

        keogram_id_list = list()
        for entry in keogram_query:
            keogram_id_list.append(entry.id)

        startrail_image_id_list = list()
        for entry in startrail_query:
            startrail_image_id_list.append(entry.id)

        startrail_video_id_list = list()
        for entry in startrail_video_query:
            startrail_video_id_list.append(entry.id)

        panorama_video_id_list = list()
        for entry in panorama_video_query:
            panorama_video_id_list.append(entry.id)


        logger.warning('Flushing %d Timelapse videos', video_count)
        time.sleep(3.0)
        self._deleteAssets(IndiAllSkyDbVideoTable, video_id_list)

        logger.warning('Flushing %d Mini videos', mini_video_count)
        time.sleep(3.0)
        self._deleteAssets(IndiAllSkyDbMiniVideoTable, mini_video_id_list)

        logger.warning('Flushing %d Keograms', mini_video_count)
        time.sleep(3.0)
        self._deleteAssets(IndiAllSkyDbKeogramTable, keogram_id_list)

        logger.warning('Flushing %d Startrail images', startrail_count)
        time.sleep(3.0)
        self._deleteAssets(IndiAllSkyDbStarTrailsTable, startrail_image_id_list)

        logger.warning('Flushing %d Startrail videos', startrail_video_count)
        time.sleep(3.0)
        self._deleteAssets(IndiAllSkyDbStarTrailsVideoTable, startrail_video_id_list)

        logger.warning('Flushing %d Panorama videos', panorama_video_count)
        time.sleep(3.0)
        self._deleteAssets(IndiAllSkyDbPanoramaVideoTable, panorama_video_id_list)


        return file_count


    def _deleteAssets(self, table, entry_id_list):
        for x, entry_id in enumerate(entry_id_list):
            if self._shutdown:
                sys.exit(1)


            entry = table.query\
                .filter(table.id == entry_id)\
                .one()


            if x % 500 == 0:
                logger.info('Removed %d %s entries', x, entry.__class__.__name__)


            #logger.info('Removing %s entry: %s', entry.__class__.__name__, entry.filename)

            try:
                entry.deleteAsset()
            except OSError as e:
                logger.error('Cannot remove file: %s', str(e))
                continue

            db.session.delete(entry)
            db.session.commit()


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        '--camera_id',
        '-c',
        help='camera id',
        type=int,
        default=1
    )

    flush_images_group = argparser.add_mutually_exclusive_group(required=False)
    flush_images_group.add_argument(
        '--no-flush-images',
        help='disable flushing images',
        dest='flush_images',
        action='store_false',
    )
    flush_images_group.add_argument(
        '--flush-images',
        help='enable flushing images (default)',
        dest='flush_images',
        action='store_true',
    )
    flush_images_group.set_defaults(flush_images=True)

    flush_videos_group = argparser.add_mutually_exclusive_group(required=False)
    flush_videos_group.add_argument(
        '--no-flush-videos',
        help='disable flushing videos (default)',
        dest='flush_videos',
        action='store_false',
    )
    flush_videos_group.add_argument(
        '--flush-videos',
        help='enable flushing videos',
        dest='flush_videos',
        action='store_true',
    )
    flush_videos_group.set_defaults(flush_videos=False)



    args = argparser.parse_args()

    fi = FlushImages()

    fi.camera_id = args.camera_id
    fi.flush_images = args.flush_images
    fi.flush_videos = args.flush_videos

    fi.main()

