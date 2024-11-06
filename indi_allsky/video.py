import os
import time
import math
import json
import cv2
import numpy
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
import psutil
import tempfile
import signal
import traceback
import logging

import PIL
from PIL import Image

import ephem

from . import constants

from .timelapse import TimelapseGenerator
from .keogram import KeogramGenerator
from .starTrails import StarTrailGenerator
from .miscUpload import miscUpload
from .aurora import IndiAllskyAuroraUpdate
from .smoke import IndiAllskySmokeUpdate
from .satellite_download import IndiAllskyUpdateSatelliteData
from .maskProcessing import MaskProcessor

from .flask import create_app
from .flask import db
from .flask.miscDb import miscDb

from .flask.models import TaskQueueState
from .flask.models import TaskQueueQueue
from .flask.models import NotificationCategory

from .flask.models import IndiAllSkyDbCameraTable
from .flask.models import IndiAllSkyDbImageTable
from .flask.models import IndiAllSkyDbVideoTable
from .flask.models import IndiAllSkyDbMiniVideoTable
from .flask.models import IndiAllSkyDbKeogramTable
from .flask.models import IndiAllSkyDbStarTrailsTable
from .flask.models import IndiAllSkyDbStarTrailsVideoTable
from .flask.models import IndiAllSkyDbFitsImageTable
from .flask.models import IndiAllSkyDbPanoramaImageTable
from .flask.models import IndiAllSkyDbPanoramaVideoTable
from .flask.models import IndiAllSkyDbRawImageTable
from .flask.models import IndiAllSkyDbTaskQueueTable

from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import and_
from sqlalchemy.sql.expression import false as sa_false
from sqlalchemy.orm.exc import NoResultFound

from multiprocessing import Process
#from threading import Thread
import queue

from .exceptions import TimelapseException
from .exceptions import TimeOutException


app = create_app()

logger = logging.getLogger('indi_allsky')



class VideoWorker(Process):

    thumbnail_keogram_width = 1000
    thumbnail_startrail_width = 300
    thumbnail_mini_timelapse_width = 300


    def __init__(
        self,
        idx,
        config,
        error_q,
        video_q,
        upload_q,
        bin_v,
    ):
        super(VideoWorker, self).__init__()

        self.name = 'Video-{0:d}'.format(idx)

        os.nice(19)  # lower priority

        self.config = config

        self.error_q = error_q
        self.video_q = video_q
        self.upload_q = upload_q

        self.bin_v = bin_v

        self._miscDb = miscDb(self.config)
        self._miscUpload = miscUpload(self.config, self.upload_q)

        self.f_lock = None

        self._detection_mask = self._load_detection_mask()


        if self.config.get('IMAGE_FOLDER'):
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()

        self._shutdown = False



    def sighup_handler_worker(self, signum, frame):
        logger.warning('Caught HUP signal')

        # set flag for program to stop processes
        self._shutdown = True


    def sigterm_handler_worker(self, signum, frame):
        logger.warning('Caught TERM signal')

        # set flag for program to stop processes
        self._shutdown = True


    def sigint_handler_worker(self, signum, frame):
        logger.warning('Caught INT signal')

        # set flag for program to stop processes
        self._shutdown = True


    def sigalarm_handler_worker(self, signum, frame):
        raise TimeOutException()



    def run(self):
        # setup signal handling after detaching from the main process
        signal.signal(signal.SIGHUP, self.sighup_handler_worker)
        signal.signal(signal.SIGTERM, self.sigterm_handler_worker)
        signal.signal(signal.SIGINT, self.sigint_handler_worker)
        signal.signal(signal.SIGALRM, self.sigalarm_handler_worker)


        ### use this as a method to log uncaught exceptions
        try:
            self.saferun()
        except Exception as e:
            tb = traceback.format_exc()
            self.error_q.put((str(e), tb))
            raise e


    def saferun(self):
        #raise Exception('Test exception handling in worker')

        while True:
            try:
                v_dict = self.video_q.get(timeout=61)  # prime number
            except queue.Empty:
                continue


            if v_dict.get('stop'):
                logger.warning('Goodbye')
                return

            if self._shutdown:
                logger.warning('Goodbye')
                return


            # new context for every task, reduces the effects of caching
            with app.app_context():
                self.processTask(v_dict)


    def processTask(self, v_dict):
        task_id = v_dict['task_id']

        try:
            task = IndiAllSkyDbTaskQueueTable.query\
                .filter(IndiAllSkyDbTaskQueueTable.id == task_id)\
                .filter(IndiAllSkyDbTaskQueueTable.state == TaskQueueState.QUEUED)\
                .filter(IndiAllSkyDbTaskQueueTable.queue == TaskQueueQueue.VIDEO)\
                .one()

        except NoResultFound:
            logger.error('Task ID %d not found', task_id)
            return


        task.setRunning()


        action = task.data['action']
        kwargs = task.data.get('kwargs', {})


        try:
            action_method = getattr(self, action)
        except AttributeError:
            logger.error('Unknown action: %s', action)
            return


        # perform the action
        action_method(task, **kwargs)


    def generateVideo(self, task, **kwargs):
        timespec = kwargs['timespec']
        night = bool(kwargs['night'])
        camera_id = kwargs['camera_id']

        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        task.setRunning()

        now = datetime.now()

        try:
            d_dayDate = datetime.strptime(timespec, '%Y%m%d').date()
        except ValueError:
            logger.error('Invalid time spec')
            task.setFailed('Invalid time spec')
            return


        if night:
            timeofday = 'night'
        else:
            timeofday = 'day'


        if self.config['FFMPEG_CODEC'] in ['libx264', 'h264_qsv']:
            video_format = 'mp4'
        elif self.config['FFMPEG_CODEC'] in ['libvpx']:
            video_format = 'webm'
        else:
            logger.error('Invalid codec in config, timelapse generation failed')
            task.setFailed('Invalid codec in config, timelapse generation failed')
            return


        vid_folder = self._getVideoFolder(d_dayDate, camera)

        video_file = vid_folder.joinpath(
            'allsky-timelapse_ccd{0:d}_{1:s}_{2:s}.{3:s}'.format(
                camera.id,
                timespec,
                timeofday,
                video_format,
            )
        )


        try:
            # delete old video entry if it exists
            old_video_entry = IndiAllSkyDbVideoTable.query\
                .filter(
                    and_(
                        IndiAllSkyDbVideoTable.dayDate == d_dayDate,
                        IndiAllSkyDbVideoTable.night == night,
                    )
                )\
                .one()


            if not self.config.get('TIMELAPSE_OVERWRITE'):
                logger.error('Timelapse already exists, overwrite not permitted')
                task.setFailed('Timelapse already exists, overwrite not permitted')
                return


            logger.warning('Removing old video db entry')

            old_video_entry.deleteAsset()

            db.session.delete(old_video_entry)
            db.session.commit()
        except NoResultFound:
            pass


        if video_file.exists():
            logger.warning('Removing orphaned video file: %s', video_file)
            video_file.unlink()


        # find all files
        timelapse_files_entries = IndiAllSkyDbImageTable.query\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera.id)\
            .filter(IndiAllSkyDbImageTable.dayDate == d_dayDate)\
            .filter(IndiAllSkyDbImageTable.night == night)\
            .filter(IndiAllSkyDbImageTable.exclude == sa_false())\
            .order_by(IndiAllSkyDbImageTable.createDate.asc())


        timelapse_files_entries_count = timelapse_files_entries.count()
        logger.info('Found %d images for timelapse', timelapse_files_entries_count)


        timelapse_data = IndiAllSkyDbImageTable.query\
            .add_columns(
                func.max(IndiAllSkyDbImageTable.kpindex).label('image_max_kpindex'),
                func.max(IndiAllSkyDbImageTable.ovation_max).label('image_max_ovation_max'),
                func.max(IndiAllSkyDbImageTable.smoke_rating).label('image_max_smoke_rating'),
                func.avg(IndiAllSkyDbImageTable.stars).label('image_avg_stars'),
                func.max(IndiAllSkyDbImageTable.moonphase).label('image_max_moonphase'),
                func.avg(IndiAllSkyDbImageTable.sqm).label('image_avg_sqm'),
            )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera.id)\
            .filter(IndiAllSkyDbImageTable.dayDate == d_dayDate)\
            .filter(IndiAllSkyDbImageTable.night == night)\
            .filter(IndiAllSkyDbImageTable.exclude == sa_false())\
            .first()


        # some of these values might be NULL which might cause other problems
        try:
            max_kpindex = float(timelapse_data.image_max_kpindex)
            max_ovation_max = int(timelapse_data.image_max_ovation_max)
            avg_stars = float(timelapse_data.image_avg_stars)
            max_moonphase = float(timelapse_data.image_max_moonphase)
            avg_sqm = float(timelapse_data.image_avg_sqm)
        except TypeError:
            max_kpindex = 0.0
            max_ovation_max = 0
            avg_stars = 0
            max_moonphase = -1.0
            avg_sqm = 0.0


        try:
            max_smoke_rating = int(timelapse_data.image_max_smoke_rating)
        except ValueError:
            max_smoke_rating = constants.SMOKE_RATING_NODATA
        except TypeError:
            max_smoke_rating = constants.SMOKE_RATING_NODATA


        logger.info('Max kpindex: %0.2f, ovation: %d, smoke rating: %s', max_kpindex, max_ovation_max, constants.SMOKE_RATING_MAP_STR[max_smoke_rating])


        timelapse_files = list()
        for entry in timelapse_files_entries:
            p_entry = Path(entry.getFilesystemPath())

            if not p_entry.exists():
                logger.error('File not found: %s', p_entry)
                continue

            if p_entry.stat().st_size == 0:
                continue

            timelapse_files.append(p_entry)


        timelapse_skip_frames = self.config.get('TIMELAPSE_SKIP_FRAMES', 4)

        video_metadata = {
            'type'          : constants.VIDEO,
            'createDate'    : now.timestamp(),
            'utc_offset'    : now.astimezone().utcoffset().total_seconds(),
            'dayDate'       : d_dayDate.strftime('%Y%m%d'),
            'night'         : night,
            'framerate'     : self.config['FFMPEG_FRAMERATE'],
            'frames'        : timelapse_files_entries_count - timelapse_skip_frames,
            'camera_uuid'   : camera.uuid,
        }

        video_metadata['data'] = {
            'max_kpindex'       : max_kpindex,
            'max_ovation_max'   : max_ovation_max,
            'max_smoke_rating'  : max_smoke_rating,
            'avg_stars'         : avg_stars,
            'max_moonphase'     : max_moonphase,
            'avg_sqm'           : avg_sqm,
        }

        # Create DB entry before creating file
        video_entry = self._miscDb.addVideo(
            video_file.relative_to(self.image_dir),
            camera.id,
            video_metadata,
        )


        try:
            # delete old video entry if it exists
            keogram_entry = IndiAllSkyDbKeogramTable.query\
                .filter(
                    and_(
                        IndiAllSkyDbKeogramTable.dayDate == d_dayDate,
                        IndiAllSkyDbKeogramTable.night == night,
                    )
                )\
                .one()

            keogram_filename = keogram_entry.getFilesystemPath()
        except NoResultFound:
            keogram_filename = None


        try:
            tg = TimelapseGenerator(
                self.config,
                skip_frames=timelapse_skip_frames,
                pre_processor_class=self.config.get('TIMELAPSE', {}).get('PRE_PROCESSOR', 'standard'),
            )

            tg.codec = self.config['FFMPEG_CODEC']
            tg.framerate = self.config['FFMPEG_FRAMERATE']
            tg.bitrate = self.config['FFMPEG_BITRATE']
            tg.vf_scale = self.config.get('FFMPEG_VFSCALE', '')
            tg.ffmpeg_extra_options = self.config.get('FFMPEG_EXTRA_OPTIONS', '')

            tg.pre_processor.keogram = keogram_filename

            tg.generate(video_file, timelapse_files)
        except TimelapseException:
            video_entry.success = False
            db.session.commit()

            self._miscDb.addNotification(
                NotificationCategory.MEDIA,
                'timelapse_video',
                'Timelapse video failed to generate',
                expire=timedelta(hours=12),
            )

            task.setFailed('Failed to generate timelapse: {0:s}'.format(str(video_file)))
            return


        task.setSuccess('Generated timelapse: {0:s}'.format(str(video_file)))

        ### Upload ###
        self._miscUpload.syncapi_video(video_entry, video_metadata)  # syncapi before s3
        self._miscUpload.s3_upload_video(video_entry, video_metadata)
        self._miscUpload.upload_video(video_entry)
        self._miscUpload.youtube_upload_video(video_entry, video_metadata)


    def generateMiniVideo(self, task, **kwargs):
        image_id = kwargs['image_id']
        camera_id = kwargs['camera_id']
        pre_seconds = int(kwargs['pre_seconds'])
        post_seconds = int(kwargs['post_seconds'])
        framerate = float(kwargs['framerate'])
        note = str(kwargs['note'])


        task.setRunning()


        now = datetime.now()

        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        image_entry = db.session.query(
            IndiAllSkyDbImageTable,
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .filter(IndiAllSkyDbImageTable.id == image_id)\
            .one()


        targetDate = image_entry.createDate
        startDate = image_entry.createDate - timedelta(seconds=pre_seconds)
        endDate = image_entry.createDate + timedelta(seconds=post_seconds)

        d_dayDate = image_entry.dayDate
        night = image_entry.night


        if image_entry.night:
            timeofday = 'night'
        else:
            timeofday = 'day'


        if self.config['FFMPEG_CODEC'] in ['libx264', 'h264_qsv']:
            video_format = 'mp4'
        elif self.config['FFMPEG_CODEC'] in ['libvpx']:
            video_format = 'webm'
        else:
            logger.error('Invalid codec in config, timelapse generation failed')
            task.setFailed('Invalid codec in config, timelapse generation failed')
            return


        vid_folder = self._getVideoFolder(d_dayDate, camera)

        video_file = vid_folder.joinpath(
            'allsky-minitimelapse_ccd{0:d}_{1:s}_{2:s}_{3:d}.{4:s}'.format(
                camera.id,
                d_dayDate.strftime('%Y%m%d'),
                timeofday,
                int(now.timestamp()),
                video_format,
            )
        )


        try:
            # delete old video entry if it exists
            old_mini_video_entry = IndiAllSkyDbVideoTable.query\
                .filter(
                    or_(
                        IndiAllSkyDbVideoTable.filename == str(video_file),
                        IndiAllSkyDbVideoTable.filename == str(video_file.relative_to(self.image_dir)),
                    )
                )\
                .one()


            if not self.config.get('TIMELAPSE_OVERWRITE'):
                logger.error('Mini Timelapse already exists, overwrite not permitted')
                task.setFailed('Mini Timelapse already exists, overwrite not permitted')
                return


            logger.warning('Removing old video db entry')

            old_mini_video_entry.deleteAsset()

            db.session.delete(old_mini_video_entry)
            db.session.commit()
        except NoResultFound:
            pass


        if video_file.exists():
            logger.warning('Removin orphaned Video file: %s', video_file)
            video_file.unlink()


        # find all files
        mini_timelapse_files_entries = IndiAllSkyDbImageTable.query\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera.id)\
            .filter(IndiAllSkyDbImageTable.createDate >= startDate)\
            .filter(IndiAllSkyDbImageTable.createDate <= endDate)\
            .filter(IndiAllSkyDbImageTable.exclude == sa_false())\
            .order_by(IndiAllSkyDbImageTable.createDate.asc())


        mini_timelapse_files_entries_count = mini_timelapse_files_entries.count()
        logger.info('Found %d images for mini timelapse', mini_timelapse_files_entries_count)


        timelapse_data = IndiAllSkyDbImageTable.query\
            .add_columns(
                func.max(IndiAllSkyDbImageTable.kpindex).label('image_max_kpindex'),
                func.max(IndiAllSkyDbImageTable.ovation_max).label('image_max_ovation_max'),
                func.max(IndiAllSkyDbImageTable.smoke_rating).label('image_max_smoke_rating'),
                func.avg(IndiAllSkyDbImageTable.stars).label('image_avg_stars'),
                func.max(IndiAllSkyDbImageTable.moonphase).label('image_max_moonphase'),
                func.avg(IndiAllSkyDbImageTable.sqm).label('image_avg_sqm'),
            )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera.id)\
            .filter(IndiAllSkyDbImageTable.createDate >= startDate)\
            .filter(IndiAllSkyDbImageTable.createDate <= endDate)\
            .filter(IndiAllSkyDbImageTable.exclude == sa_false())\
            .first()


        # some of these values might be NULL which might cause other problems
        try:
            max_kpindex = float(timelapse_data.image_max_kpindex)
            max_ovation_max = int(timelapse_data.image_max_ovation_max)
            avg_stars = float(timelapse_data.image_avg_stars)
            max_moonphase = float(timelapse_data.image_max_moonphase)
            avg_sqm = float(timelapse_data.image_avg_sqm)
        except TypeError:
            max_kpindex = 0.0
            max_ovation_max = 0
            avg_stars = 0
            max_moonphase = -1.0
            avg_sqm = 0.0


        try:
            max_smoke_rating = int(timelapse_data.image_max_smoke_rating)
        except ValueError:
            max_smoke_rating = constants.SMOKE_RATING_NODATA
        except TypeError:
            max_smoke_rating = constants.SMOKE_RATING_NODATA


        logger.info('Max kpindex: %0.2f, ovation: %d, smoke rating: %s', max_kpindex, max_ovation_max, constants.SMOKE_RATING_MAP_STR[max_smoke_rating])


        timelapse_files = list()
        for entry in mini_timelapse_files_entries:
            p_entry = Path(entry.getFilesystemPath())

            if not p_entry.exists():
                logger.error('File not found: %s', p_entry)
                continue

            if p_entry.stat().st_size == 0:
                continue

            timelapse_files.append(p_entry)


        mini_video_metadata = {
            'type'          : constants.MINI_VIDEO,
            'createDate'    : now.timestamp(),
            'utc_offset'    : now.astimezone().utcoffset().total_seconds(),
            'dayDate'       : d_dayDate.strftime('%Y%m%d'),
            'targetDate'    : targetDate.timestamp(),
            'startDate'     : startDate.timestamp(),
            'endDate'       : endDate.timestamp(),
            'night'         : night,
            'framerate'     : framerate,
            'frames'        : mini_timelapse_files_entries_count,
            'note'          : note,
            'camera_uuid'   : camera.uuid,
        }

        mini_video_metadata['data'] = {
            'max_kpindex'       : max_kpindex,
            'max_ovation_max'   : max_ovation_max,
            'max_smoke_rating'  : max_smoke_rating,
            'avg_stars'         : avg_stars,
            'max_moonphase'     : max_moonphase,
            'avg_sqm'           : avg_sqm,
        }

        # Create DB entry before creating file
        mini_video_entry = self._miscDb.addMiniVideo(
            video_file.relative_to(self.image_dir),
            camera.id,
            mini_video_metadata,
        )


        mini_video_thumbnail_metadata = {
            'type'       : constants.THUMBNAIL,
            'origin'     : constants.MINI_VIDEO,
            'createDate' : now.timestamp(),
            'dayDate'    : d_dayDate.strftime('%Y%m%d'),
            'utc_offset' : now.astimezone().utcoffset().total_seconds(),
            'night'      : night,
            'camera_uuid': camera.uuid,
        }


        mini_video_thumbnail_entry = self._miscDb.addThumbnail(
            mini_video_entry,
            mini_video_metadata,
            camera.id,
            mini_video_thumbnail_metadata,
            new_width=self.thumbnail_mini_timelapse_width,
            image_entry=image_entry,  # use target image for thumbnail
        )


        try:
            tg = TimelapseGenerator(
                self.config,
                skip_frames=0,
            )

            tg.codec = self.config['FFMPEG_CODEC']
            tg.framerate = framerate
            tg.bitrate = self.config['FFMPEG_BITRATE']
            tg.vf_scale = self.config.get('FFMPEG_VFSCALE', '')
            tg.ffmpeg_extra_options = self.config.get('FFMPEG_EXTRA_OPTIONS', '')

            tg.generate(video_file, timelapse_files)
        except TimelapseException:
            mini_video_entry.success = False
            db.session.commit()

            self._miscDb.addNotification(
                NotificationCategory.MEDIA,
                'mini_timelapse_video',
                'Mini timelapse video failed to generate',
                expire=timedelta(hours=12),
            )

            task.setFailed('Failed to generate mini timelapse: {0:s}'.format(str(video_file)))
            return


        task.setSuccess('Generated timelapse: {0:s}'.format(str(video_file)))

        ### Upload ###


        if mini_video_thumbnail_entry:
            self._miscUpload.syncapi_thumbnail(mini_video_thumbnail_entry, mini_video_thumbnail_metadata)  # syncapi before S3
            self._miscUpload.s3_upload_thumbnail(mini_video_thumbnail_entry, mini_video_thumbnail_metadata)


        self._miscUpload.syncapi_mini_video(mini_video_entry, mini_video_metadata)  # syncapi before s3
        self._miscUpload.s3_upload_mini_video(mini_video_entry, mini_video_metadata)
        self._miscUpload.upload_mini_video(mini_video_entry)
        self._miscUpload.youtube_upload_mini_video(mini_video_entry, mini_video_metadata)


    def generatePanoramaVideo(self, task, **kwargs):
        timespec = kwargs['timespec']
        night = bool(kwargs['night'])
        camera_id = kwargs['camera_id']

        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        task.setRunning()

        now = datetime.now()

        try:
            d_dayDate = datetime.strptime(timespec, '%Y%m%d').date()
        except ValueError:
            logger.error('Invalid time spec')
            task.setFailed('Invalid time spec')
            return


        if night:
            timeofday = 'night'
        else:
            timeofday = 'day'


        if self.config['FFMPEG_CODEC'] in ['libx264', 'h264_qsv']:
            video_format = 'mp4'
        elif self.config['FFMPEG_CODEC'] in ['libvpx']:
            video_format = 'webm'
        else:
            logger.error('Invalid codec in config, timelapse generation failed')
            task.setFailed('Invalid codec in config, timelapse generation failed')
            return


        vid_folder = self._getVideoFolder(d_dayDate, camera)

        video_file = vid_folder.joinpath(
            'allsky-panorama_timelapse_ccd{0:d}_{1:s}_{2:s}.{3:s}'.format(
                camera.id,
                timespec,
                timeofday,
                video_format,
            )
        )


        try:
            # delete old video entry if it exists
            old_panorama_video_entry = IndiAllSkyDbPanoramaVideoTable.query\
                .filter(
                    and_(
                        IndiAllSkyDbPanoramaVideoTable.dayDate == d_dayDate,
                        IndiAllSkyDbPanoramaVideoTable.night == night,
                    )
                )\
                .one()


            if not self.config.get('TIMELAPSE_OVERWRITE'):
                logger.error('Panorama Timelapse already exists, overwrite not permitted')
                task.setFailed('Panorama Timelapse already exists, overwrite not permitted')
                return


            logger.warning('Removing old panorama video db entry')

            old_panorama_video_entry.deleteAsset()

            db.session.delete(old_panorama_video_entry)
            db.session.commit()
        except NoResultFound:
            pass


        if video_file.exists():
            logger.warning('Removing orphaned panorama video file: %s', video_file)
            video_file.unlink()


        # find all files
        timelapse_files_entries = IndiAllSkyDbPanoramaImageTable.query\
            .join(IndiAllSkyDbPanoramaImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera.id)\
            .filter(IndiAllSkyDbPanoramaImageTable.dayDate == d_dayDate)\
            .filter(IndiAllSkyDbPanoramaImageTable.night == night)\
            .filter(IndiAllSkyDbPanoramaImageTable.exclude == sa_false())\
            .order_by(IndiAllSkyDbPanoramaImageTable.createDate.asc())


        timelapse_files_entries_count = timelapse_files_entries.count()
        logger.info('Found %d images for timelapse', timelapse_files_entries_count)


        timelapse_data = IndiAllSkyDbImageTable.query\
            .add_columns(
                func.max(IndiAllSkyDbImageTable.kpindex).label('image_max_kpindex'),
                func.max(IndiAllSkyDbImageTable.ovation_max).label('image_max_ovation_max'),
                func.max(IndiAllSkyDbImageTable.smoke_rating).label('image_max_smoke_rating'),
                func.avg(IndiAllSkyDbImageTable.stars).label('image_avg_stars'),
                func.max(IndiAllSkyDbImageTable.moonphase).label('image_max_moonphase'),
                func.avg(IndiAllSkyDbImageTable.sqm).label('image_avg_sqm'),
            )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera.id)\
            .filter(IndiAllSkyDbImageTable.dayDate == d_dayDate)\
            .filter(IndiAllSkyDbImageTable.night == night)\
            .filter(IndiAllSkyDbImageTable.exclude == sa_false())\
            .first()


        # some of these values might be NULL which might cause other problems
        try:
            max_kpindex = float(timelapse_data.image_max_kpindex)
            max_ovation_max = int(timelapse_data.image_max_ovation_max)
            avg_stars = float(timelapse_data.image_avg_stars)
            max_moonphase = float(timelapse_data.image_max_moonphase)
            avg_sqm = float(timelapse_data.image_avg_sqm)
        except TypeError:
            max_kpindex = 0.0
            max_ovation_max = 0
            avg_stars = 0
            max_moonphase = -1.0
            avg_sqm = 0.0


        try:
            max_smoke_rating = int(timelapse_data.image_max_smoke_rating)
        except ValueError:
            max_smoke_rating = constants.SMOKE_RATING_NODATA
        except TypeError:
            max_smoke_rating = constants.SMOKE_RATING_NODATA


        logger.info('Max kpindex: %0.2f, ovation: %d, smoke rating: %s', max_kpindex, max_ovation_max, constants.SMOKE_RATING_MAP_STR[max_smoke_rating])


        timelapse_files = list()
        for entry in timelapse_files_entries:
            p_entry = Path(entry.getFilesystemPath())

            if not p_entry.exists():
                logger.error('File not found: %s', p_entry)
                continue

            if p_entry.stat().st_size == 0:
                continue

            timelapse_files.append(p_entry)


        timelapse_skip_frames = self.config.get('TIMELAPSE_SKIP_FRAMES', 4)

        video_metadata = {
            'type'          : constants.PANORAMA_VIDEO,
            'createDate'    : now.timestamp(),
            'utc_offset'    : now.astimezone().utcoffset().total_seconds(),
            'dayDate'       : d_dayDate.strftime('%Y%m%d'),
            'night'         : night,
            'framerate'     : self.config['FFMPEG_FRAMERATE'],
            'frames'        : timelapse_files_entries_count - timelapse_skip_frames,
            'camera_uuid'   : camera.uuid,
        }

        video_metadata['data'] = {
            'max_kpindex'       : max_kpindex,
            'max_ovation_max'   : max_ovation_max,
            'max_smoke_rating'  : max_smoke_rating,
            'avg_stars'         : avg_stars,
            'max_moonphase'     : max_moonphase,
            'avg_sqm'           : avg_sqm,
        }


        # Create DB entry before creating file
        video_entry = self._miscDb.addPanoramaVideo(
            video_file.relative_to(self.image_dir),
            camera.id,
            video_metadata,
        )


        try:
            tg = TimelapseGenerator(
                self.config,
                skip_frames=timelapse_skip_frames,
            )

            tg.codec = self.config['FFMPEG_CODEC']
            tg.framerate = self.config['FFMPEG_FRAMERATE']
            tg.bitrate = self.config['FFMPEG_BITRATE']
            tg.vf_scale = self.config.get('FFMPEG_VFSCALE', '')
            tg.ffmpeg_extra_options = self.config.get('FFMPEG_EXTRA_OPTIONS', '')

            tg.generate(video_file, timelapse_files)
        except TimelapseException:
            video_entry.success = False
            db.session.commit()

            self._miscDb.addNotification(
                NotificationCategory.MEDIA,
                'timelapse_video',
                'Timelapse panorama video failed to generate',
                expire=timedelta(hours=12),
            )

            task.setFailed('Failed to generate timelapse: {0:s}'.format(str(video_file)))
            return


        task.setSuccess('Generated timelapse: {0:s}'.format(str(video_file)))

        ### Upload ###
        self._miscUpload.syncapi_panorama_video(video_entry, video_metadata)  # syncapi before S3
        self._miscUpload.s3_upload_panorama_video(video_entry, video_metadata)
        self._miscUpload.upload_panorama_video(video_entry)
        self._miscUpload.youtube_upload_panorama_video(video_entry, video_metadata)


    def generateKeogramStarTrails(self, task, **kwargs):
        timespec = kwargs['timespec']
        night = bool(kwargs['night'])
        camera_id = kwargs['camera_id']

        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        task.setRunning()

        now = datetime.now()

        try:
            d_dayDate = datetime.strptime(timespec, '%Y%m%d').date()
        except ValueError:
            logger.error('Invalid time spec')
            task.setFailed('Invalid time spec')
            return


        if night:
            timeofday = 'night'
        else:
            timeofday = 'day'


        if self.config['FFMPEG_CODEC'] in ['libx264', 'h264_qsv']:
            video_format = 'mp4'
        elif self.config['FFMPEG_CODEC'] in ['libvpx']:
            video_format = 'webm'
        else:
            logger.error('Invalid codec in config, timelapse generation failed')
            task.setFailed('Invalid codec in config, timelapse generation failed')
            return


        vid_folder = self._getVideoFolder(d_dayDate, camera)

        keogram_file = vid_folder.joinpath(
            'allsky-keogram_ccd{0:d}_{1:s}_{2:s}.{3:s}'.format(
                camera.id,
                timespec,
                timeofday,
                self.config['IMAGE_FILE_TYPE'],
            )
        )

        startrail_file = vid_folder.joinpath(
            'allsky-startrail_ccd{0:d}_{1:s}_{2:s}.{3:s}'.format(
                camera.id,
                timespec,
                timeofday,
                self.config['IMAGE_FILE_TYPE'],
            )
        )

        startrail_video_file = vid_folder.joinpath(
            'allsky-startrail_timelapse_ccd{0:d}_{1:s}_{2:s}.{3:s}'.format(
                camera.id,
                timespec,
                timeofday,
                video_format,
            )
        )


        try:
            # delete old keogram entry if it exists
            old_keogram_entry = IndiAllSkyDbKeogramTable.query\
                .filter(
                    and_(
                        IndiAllSkyDbKeogramTable.dayDate == d_dayDate,
                        IndiAllSkyDbKeogramTable.night == night,
                    )
                )\
                .one()


            if not self.config.get('TIMELAPSE_OVERWRITE'):
                logger.error('Keogram already exists, overwrite not permitted')
                task.setFailed('Keogram already exists, overwrite not permitted')
                return


            logger.warning('Removing old keogram db entry')

            old_keogram_entry.deleteAsset()

            db.session.delete(old_keogram_entry)
            db.session.commit()
        except NoResultFound:
            pass


        try:
            # delete old star trail entry if it exists
            old_startrail_entry = IndiAllSkyDbStarTrailsTable.query\
                .filter(
                    and_(
                        IndiAllSkyDbStarTrailsTable.dayDate == d_dayDate,
                        IndiAllSkyDbStarTrailsTable.night == night,
                    )
                )\
                .one()


            if not self.config.get('TIMELAPSE_OVERWRITE'):
                logger.error('Star trail already exists, overwrite not permitted')
                task.setFailed('Star trail already exists, overwrite not permitted')
                return


            logger.warning('Removing old star trail db entry')

            old_startrail_entry.deleteAsset()

            db.session.delete(old_startrail_entry)
            db.session.commit()
        except NoResultFound:
            pass


        try:
            # delete old star trail video entry if it exists
            old_startrail_video_entry = IndiAllSkyDbStarTrailsVideoTable.query\
                .filter(
                    and_(
                        IndiAllSkyDbStarTrailsVideoTable.dayDate == d_dayDate,
                        IndiAllSkyDbStarTrailsVideoTable.night == night,
                    )
                )\
                .one()


            if not self.config.get('TIMELAPSE_OVERWRITE'):
                logger.error('Star trail timelapse already exists, overwrite not permitted')
                task.setFailed('Star trail timelapse already exists, overwrite not permitted')
                return


            logger.warning('Removing old star trail video db entry')

            old_startrail_video_entry.deleteAsset()

            db.session.delete(old_startrail_video_entry)
            db.session.commit()
        except NoResultFound:
            pass


        if keogram_file.exists():
            logger.warning('Removing orphaned keogram file: %s', keogram_file)
            keogram_file.unlink()

        if startrail_file.exists():
            logger.warning('Removing orphanded Star trail file: %s', startrail_file)
            startrail_file.unlink()

        if startrail_video_file.exists():
            logger.warning('Removin orphaned Star trail timelapse file: %s', startrail_video_file)
            startrail_video_file.unlink()


        # find all files
        files_entries = IndiAllSkyDbImageTable.query\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera.id)\
            .filter(IndiAllSkyDbImageTable.dayDate == d_dayDate)\
            .filter(IndiAllSkyDbImageTable.night == night)\
            .filter(IndiAllSkyDbImageTable.exclude == sa_false())\
            .order_by(IndiAllSkyDbImageTable.createDate.asc())


        image_count = files_entries.count()
        logger.info('Found %d images for keogram/star trails', image_count)


        # some of these values might be NULL which might cause other problems
        image_data = IndiAllSkyDbImageTable.query\
            .add_columns(
                func.max(IndiAllSkyDbImageTable.kpindex).label('image_max_kpindex'),
                func.max(IndiAllSkyDbImageTable.ovation_max).label('image_max_ovation_max'),
                func.max(IndiAllSkyDbImageTable.smoke_rating).label('image_max_smoke_rating'),
                func.avg(IndiAllSkyDbImageTable.stars).label('image_avg_stars'),
                func.max(IndiAllSkyDbImageTable.moonphase).label('image_max_moonphase'),
                func.avg(IndiAllSkyDbImageTable.sqm).label('image_avg_sqm'),
            )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera.id)\
            .filter(IndiAllSkyDbImageTable.dayDate == d_dayDate)\
            .filter(IndiAllSkyDbImageTable.night == night)\
            .filter(IndiAllSkyDbImageTable.exclude == sa_false())\
            .first()


        # some of these values might be NULL which might cause other problems
        try:
            max_kpindex = float(image_data.image_max_kpindex)
            max_ovation_max = int(image_data.image_max_ovation_max)
            avg_stars = float(image_data.image_avg_stars)
            max_moonphase = float(image_data.image_max_moonphase)
            avg_sqm = float(image_data.image_avg_sqm)
        except TypeError:
            max_kpindex = 0.0
            max_ovation_max = 0
            avg_stars = 0
            max_moonphase = -1.0
            avg_sqm = 0.0


        try:
            max_smoke_rating = int(image_data.image_max_smoke_rating)
        except ValueError:
            max_smoke_rating = constants.SMOKE_RATING_NODATA
        except TypeError:
            max_smoke_rating = constants.SMOKE_RATING_NODATA


        logger.info('Max kpindex: %0.2f, ovation: %d, smoke rating: %s', max_kpindex, max_ovation_max, constants.SMOKE_RATING_MAP_STR[max_smoke_rating])


        timelapse_skip_frames = self.config.get('TIMELAPSE_SKIP_FRAMES', 4)


        processing_start = time.time()

        kg = KeogramGenerator(
            self.config,
            skip_frames=timelapse_skip_frames,
        )
        kg.angle = self.config['KEOGRAM_ANGLE']
        kg.h_scale_factor = self.config['KEOGRAM_H_SCALE']
        kg.v_scale_factor = self.config['KEOGRAM_V_SCALE']
        kg.crop_top = self.config.get('KEOGRAM_CROP_TOP', 0)
        kg.crop_bottom = self.config.get('KEOGRAM_CROP_BOTTOM', 0)


        keogram_metadata = {
            'type'       : constants.KEOGRAM,
            'createDate' : now.timestamp(),
            'utc_offset' : now.astimezone().utcoffset().total_seconds(),
            'dayDate'    : d_dayDate.strftime('%Y%m%d'),
            'night'      : night,
            'camera_uuid': camera.uuid,
            #'height'  # added later
            #'width'   # added later
            #'frames'  # added later
        }

        keogram_metadata['data'] = {
            'max_kpindex'       : max_kpindex,
            'max_ovation_max'   : max_ovation_max,
            'max_smoke_rating'  : max_smoke_rating,
            'avg_stars'         : avg_stars,
            'max_moonphase'     : max_moonphase,
            'avg_sqm'           : avg_sqm,
        }


        startrail_metadata = {
            'type'       : constants.STARTRAIL,
            'createDate' : now.timestamp(),
            'utc_offset' : now.astimezone().utcoffset().total_seconds(),
            'dayDate'    : d_dayDate.strftime('%Y%m%d'),
            'night'      : night,
            'camera_uuid': camera.uuid,
            #'height'  # added later
            #'width'   # added later
            #'frames'  # added later
        }

        startrail_metadata['data'] = {
            'max_kpindex'       : max_kpindex,
            'max_ovation_max'   : max_ovation_max,
            'max_smoke_rating'  : max_smoke_rating,
            'avg_stars'         : avg_stars,
            'max_moonphase'     : max_moonphase,
            'avg_sqm'           : avg_sqm,
        }


        startrail_video_metadata = {
            'type'       : constants.STARTRAIL_VIDEO,
            'createDate' : now.timestamp(),
            'utc_offset' : now.astimezone().utcoffset().total_seconds(),
            'dayDate'    : d_dayDate.strftime('%Y%m%d'),
            'night'      : night,
            'camera_uuid': camera.uuid,
            'framerate'  : self.config['FFMPEG_FRAMERATE'],
            #'frames'  # added later
        }

        startrail_video_metadata['data'] = {
            'max_kpindex'       : max_kpindex,
            'max_ovation_max'   : max_ovation_max,
            'max_smoke_rating'  : max_smoke_rating,
            'max_stars'         : avg_stars,
            'max_moonphase'     : max_moonphase,
            'max_sqm'           : avg_sqm,
        }


        # Add DB entries before creating files
        keogram_entry = self._miscDb.addKeogram(
            keogram_file.relative_to(self.image_dir),
            camera.id,
            keogram_metadata,
        )


        if night:
            startrail_entry = self._miscDb.addStarTrail(
                startrail_file.relative_to(self.image_dir),
                camera.id,
                startrail_metadata,
            )
        else:
            startrail_entry = None
            startrail_video_entry = None


        stg = StarTrailGenerator(
            self.config,
            self.bin_v,
            skip_frames=timelapse_skip_frames,
            mask=self._detection_mask,
        )
        stg.max_adu = self.config['STARTRAILS_MAX_ADU']
        stg.mask_threshold = self.config['STARTRAILS_MASK_THOLD']
        stg.pixel_cutoff_threshold = self.config['STARTRAILS_PIXEL_THOLD']
        stg.min_stars = self.config.get('STARTRAILS_MIN_STARS', 0)
        stg.latitude = camera.latitude
        stg.longitude = camera.longitude
        stg.sun_alt_threshold = self.config['STARTRAILS_SUN_ALT_THOLD']

        if self.config['STARTRAILS_MOONMODE_THOLD']:
            stg.moonmode_alt = self.config['NIGHT_MOONMODE_ALT_DEG']
            stg.moonmode_phase = self.config['NIGHT_MOONMODE_PHASE']
        else:
            stg.moon_alt_threshold = self.config['STARTRAILS_MOON_ALT_THOLD']
            stg.moon_phase_threshold = self.config['STARTRAILS_MOON_PHASE_THOLD']

        if self.config.get('STARTRAILS_USE_DB_DATA', True):
            logger.warning('Re-using image data for ADU and Star counts')
        else:
            logger.warning('Recalculating values for ADU and Star counts')


        # Files are presorted from the DB
        for i, entry in enumerate(files_entries):
            if i % 100 == 0:
                logger.info('Processed %d of %d images', i, image_count)

            image_file_p = Path(entry.getFilesystemPath())

            if not image_file_p.exists():
                logger.error('File not found: %s', image_file_p)
                continue

            if image_file_p.stat().st_size == 0:
                continue


            #logger.info('Reading file: %s', p_entry)
            if image_file_p.suffix in ('.png',):
                # opencv is faster than Pillow with PNG
                image_data = cv2.imread(str(image_file_p), cv2.IMREAD_COLOR)

                if isinstance(image_data, type(None)):
                    logger.error('Unable to read %s', image_file_p)
                    continue
            else:
                try:
                    with Image.open(str(image_file_p)) as img:
                        image_data = cv2.cvtColor(numpy.array(img), cv2.COLOR_RGB2BGR)
                except PIL.UnidentifiedImageError:
                    logger.error('Unable to read %s', image_file_p)
                    continue


            kg.processImage(image_file_p, image_data)

            if night:
                if self.config.get('STARTRAILS_USE_DB_DATA', True):
                    adu = entry.adu
                    star_count = entry.stars  # can be None
                else:
                    adu, star_count = None, None

                stg.processImage(image_file_p, image_data, adu=adu, star_count=star_count)


        kg.finalize(keogram_file, camera)


        # add height and width
        keogram_height, keogram_width = kg.shape[:2]
        keogram_metadata['height'] = keogram_height
        keogram_metadata['width'] = keogram_width
        keogram_metadata['frames'] = keogram_width  # one frame per line

        keogram_entry.height = keogram_height
        keogram_entry.width = keogram_width
        keogram_entry.frames = keogram_width  # one frame per line
        db.session.commit()


        keogram_thumbnail_metadata = {
            'type'       : constants.THUMBNAIL,
            'origin'     : constants.KEOGRAM,
            'createDate' : now.timestamp(),
            'dayDate'    : d_dayDate.strftime('%Y%m%d'),
            'utc_offset' : now.astimezone().utcoffset().total_seconds(),
            'night'      : night,
            'camera_uuid': camera.uuid,
        }

        keogram_thumbnail_entry = self._miscDb.addThumbnail(
            keogram_entry,
            keogram_metadata,
            camera.id,
            keogram_thumbnail_metadata,
            new_width=self.thumbnail_keogram_width,
        )


        if night:
            stg.finalize(startrail_file, camera)


            # add height and width
            st_height, st_width = stg.shape[:2]
            startrail_metadata['height'] = st_height
            startrail_metadata['width'] = st_width
            startrail_metadata['frames'] = stg.trail_count

            startrail_entry.height = st_height
            startrail_entry.width = st_width
            startrail_entry.frames = stg.trail_count
            db.session.commit()


            startrail_thumbnail_metadata = {
                'type'       : constants.THUMBNAIL,
                'origin'     : constants.STARTRAIL,
                'createDate' : now.timestamp(),
                'dayDate'    : d_dayDate.strftime('%Y%m%d'),
                'utc_offset' : now.astimezone().utcoffset().total_seconds(),
                'night'      : night,
                'camera_uuid': camera.uuid,
            }

            startrail_thumbnail_entry = self._miscDb.addThumbnail(
                startrail_entry,
                startrail_metadata,
                camera.id,
                startrail_thumbnail_metadata,
                new_width=self.thumbnail_startrail_width,
            )


            st_frame_count = stg.timelapse_frame_count
            if st_frame_count >= self.config.get('STARTRAILS_TIMELAPSE_MINFRAMES', 250):
                startrail_video_metadata['frames'] = st_frame_count  # add frame count

                startrail_video_entry = self._miscDb.addStarTrailVideo(
                    startrail_video_file.relative_to(self.image_dir),
                    camera.id,
                    startrail_video_metadata,
                )

                try:
                    st_tg = TimelapseGenerator(
                        self.config,
                        skip_frames=0,
                    )

                    st_tg.codec = self.config['FFMPEG_CODEC']
                    st_tg.framerate = self.config['FFMPEG_FRAMERATE']
                    st_tg.bitrate = self.config['FFMPEG_BITRATE']
                    st_tg.vf_scale = self.config.get('FFMPEG_VFSCALE', '')
                    st_tg.ffmpeg_extra_options = self.config.get('FFMPEG_EXTRA_OPTIONS', '')

                    st_tg.generate(startrail_video_file, stg.timelapse_frame_list)
                except TimelapseException:
                    logger.error('Failed to generate startrails timelapse')

                    startrail_video_entry.success = False
                    db.session.commit()

                    self._miscDb.addNotification(
                        NotificationCategory.MEDIA,
                        'startrail_video',
                        'Startrails timelapse video failed to generate',
                        expire=timedelta(hours=12),
                    )
            else:
                logger.error('Not enough frames to generate star trails timelapse: %d', st_frame_count)
                startrail_video_entry = None


        processing_elapsed_s = time.time() - processing_start
        logger.warning('Total keogram/star trail processing in %0.1f s', processing_elapsed_s)


        if keogram_entry:
            # upload thumbnail first
            if keogram_thumbnail_entry:
                self._miscUpload.syncapi_thumbnail(keogram_thumbnail_entry, keogram_thumbnail_metadata)  # syncapi before S3
                self._miscUpload.s3_upload_thumbnail(keogram_thumbnail_entry, keogram_thumbnail_metadata)


            if keogram_file.exists():
                self._miscUpload.s3_upload_keogram(keogram_entry, keogram_metadata)
                self._miscUpload.syncapi_keogram(keogram_entry, keogram_metadata)
                self._miscUpload.upload_keogram(keogram_entry)
            else:
                keogram_entry.success = False
                db.session.commit()


        if startrail_entry and night:
            # upload thumbnail first
            if startrail_thumbnail_entry:
                self._miscUpload.syncapi_thumbnail(startrail_thumbnail_entry, startrail_thumbnail_metadata)  # syncapi before S3
                self._miscUpload.s3_upload_thumbnail(startrail_thumbnail_entry, startrail_thumbnail_metadata)


            if startrail_file.exists():
                self._miscUpload.syncapi_startrail(startrail_entry, startrail_metadata)  # syncapi before S3
                self._miscUpload.s3_upload_startrail(startrail_entry, startrail_metadata)
                self._miscUpload.upload_startrail(startrail_entry)
            else:
                startrail_entry.success = False
                db.session.commit()


        if startrail_video_entry and night:
            if startrail_video_file.exists():
                self._miscUpload.syncapi_startrail_video(startrail_video_entry, startrail_video_metadata)  # syncapi before S3
                self._miscUpload.s3_upload_startrail_video(startrail_video_entry, startrail_video_metadata)
                self._miscUpload.upload_startrail_video(startrail_video_entry)
                self._miscUpload.youtube_upload_startrail_video(startrail_video_entry, startrail_video_metadata)
            else:
                # success flag set above
                pass


        task.setSuccess('Generated keogram and/or star trail')


    def uploadAllskyEndOfNight(self, task, **kwargs):
        night = bool(kwargs['night'])
        camera_id = kwargs['camera_id']

        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        task.setRunning()

        if not night:
            # Only upload at end of night
            return

        if not self.config.get('FILETRANSFER', {}).get('UPLOAD_ENDOFNIGHT'):
            logger.warning('End of Night uploading disabled')
            task.setFailed('End of Night uploading disabled')
            return

        if not self.config.get('FILETRANSFER', {}).get('REMOTE_ENDOFNIGHT_FOLDER'):
            logger.error('End of Night folder not configured')
            task.setFailed('End of Night folder not configured')
            return


        logger.info('Generating Allsky EndOfNight data.json')

        utcnow = datetime.now(tz=timezone.utc)  # ephem expects UTC dates

        obs = ephem.Observer()
        obs.lon = math.radians(camera.longitude)
        obs.lat = math.radians(camera.latitude)
        obs.elevation = camera.elevation

        # disable atmospheric refraction calcs
        obs.pressure = 0

        sun = ephem.Sun()

        obs.date = utcnow
        sun.compute(obs)


        try:
            if math.degrees(sun.alt) < 0:
                sun_civilDawn_date = obs.next_rising(sun, use_center=True).datetime()
            else:
                sun_civilDawn_date = obs.previous_rising(sun, use_center=True).datetime()
        except ephem.NeverUpError:
            # northern hemisphere
            sun_civilDawn_date = utcnow + timedelta(years=10)
        except ephem.AlwaysUpError:
            # southern hemisphere
            sun_civilDawn_date = utcnow - timedelta(days=1)


        try:
            sun_civilTwilight_date = obs.next_setting(sun, use_center=True).datetime()
        except ephem.AlwaysUpError:
            # northern hemisphere
            sun_civilTwilight_date = utcnow - timedelta(days=1)
        except ephem.NeverUpError:
            # southern hemisphere
            sun_civilTwilight_date = utcnow + timedelta(years=10)


        data = {
            'sunrise'            : sun_civilDawn_date.replace(tzinfo=timezone.utc).isoformat(),
            'sunset'             : sun_civilTwilight_date.replace(tzinfo=timezone.utc).isoformat(),
            'streamDaytime'      : bool(self.config['DAYTIME_CAPTURE']),
        }


        data_tempfile_f = tempfile.NamedTemporaryFile(mode='w', delete=False)

        json.dump(data, data_tempfile_f, indent=4)
        data_tempfile_f.close()

        data_json_p = Path(data_tempfile_f.name)



        now = datetime.now()

        # Parameters for string formatting
        file_data_dict = {
            'timestamp'    : now,
            'ts'           : now,  # shortcut
            'camera_uuid'  : camera.uuid,
        }


        # Replace parameters in names
        remote_dir = self.config['FILETRANSFER']['REMOTE_ENDOFNIGHT_FOLDER'].format(**file_data_dict)

        remote_file_p = Path(remote_dir).joinpath('data.json')


        jobdata = {
            'action'         : constants.TRANSFER_UPLOAD,
            'local_file'     : str(data_json_p),
            'remote_file'    : str(remote_file_p),
            'remove_local'   : True,
        }

        upload_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(upload_task)
        db.session.commit()

        self.upload_q.put({'task_id' : upload_task.id})

        task.setSuccess('Uploaded EndOfNight data')


    def systemHealthCheck(self, task, **kwargs):
        task.setRunning()


        disk_usage_warning = self.config.get('HEALTHCHECK', {}).get('DISK_USAGE', 90.0)
        swap_usage_warning = self.config.get('HEALTHCHECK', {}).get('SWAP_USAGE', 90.0)


        # check filesystems
        logger.info('Performing system health check')

        fs_list = psutil.disk_partitions(all=False)

        for fs in fs_list:

            skip = False
            for p in ('/snap', '/boot'):
                if fs.mountpoint.startswith(p + '/'):
                    skip = True
                    break
                elif fs.mountpoint == p:
                    skip = True
                    break

            if skip:
                continue


            try:
                disk_usage = psutil.disk_usage(fs.mountpoint)
            except PermissionError as e:
                logger.error('PermissionError: %s', str(e))
                continue

            if disk_usage.percent >= disk_usage_warning:
                self._miscDb.addNotification(
                    NotificationCategory.DISK,
                    fs.mountpoint,
                    'Filesystem {0:s} >={1:0.1f}% full'.format(fs.mountpoint, disk_usage_warning),
                    expire=timedelta(minutes=715),  # should run every ~12 hours
                )


        # check swap capacity
        swap_info = psutil.swap_memory()
        if swap_info.percent >= swap_usage_warning:
            self._miscDb.addNotification(
                NotificationCategory.MISC,
                'swap',
                'Swap memory >={0:0.1f}% full'.format(swap_usage_warning),
                expire=timedelta(minutes=715),  # should run every ~12 hours
            )

        task.setSuccess('Health check complete')


    def updateAuroraData(self, task, **kwargs):
        camera_id = kwargs['camera_id']

        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        task.setRunning()

        aurora = IndiAllskyAuroraUpdate(self.config)
        aurora.update(camera)

        task.setSuccess('Aurora data updated')


    def updateSmokeData(self, task, **kwargs):
        camera_id = kwargs['camera_id']

        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        task.setRunning()

        smoke = IndiAllskySmokeUpdate(self.config)
        smoke.update(camera)

        task.setSuccess('Smoke data updated')


    def updateSatelliteTleData(self, task, **kwargs):
        task.setRunning()

        satellite = IndiAllskyUpdateSatelliteData(self.config)
        satellite.update()

        task.setSuccess('Satellite data updated')


    def expireData(self, task, **kwargs):
        camera_id = kwargs['camera_id']

        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        task.setRunning()


        now = datetime.now()

        # Old image files need to be pruned
        cutoff_age_images = now - timedelta(days=self.config.get('IMAGE_EXPIRE_DAYS', 10))
        cutoff_age_images_date = cutoff_age_images.date()  # cutoff date based on dayDate attribute, not createDate

        old_images = IndiAllSkyDbImageTable.query\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera.id)\
            .filter(IndiAllSkyDbImageTable.dayDate < cutoff_age_images_date)\
            .order_by(IndiAllSkyDbImageTable.createDate.asc())
        old_panorama_images = IndiAllSkyDbPanoramaImageTable.query\
            .join(IndiAllSkyDbPanoramaImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera.id)\
            .filter(IndiAllSkyDbPanoramaImageTable.dayDate < cutoff_age_images_date)\
            .order_by(IndiAllSkyDbPanoramaImageTable.createDate.asc())

        # raw
        cutoff_age_images_raw = now - timedelta(days=self.config.get('IMAGE_RAW_EXPIRE_DAYS', 10))
        cutoff_age_images_raw_date = cutoff_age_images_raw.date()  # cutoff date based on dayDate attribute, not createDate

        old_raw_images = IndiAllSkyDbRawImageTable.query\
            .join(IndiAllSkyDbRawImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera.id)\
            .filter(IndiAllSkyDbRawImageTable.dayDate < cutoff_age_images_raw_date)\
            .order_by(IndiAllSkyDbRawImageTable.createDate.asc())


        # fits
        cutoff_age_images_fits = now - timedelta(days=self.config.get('IMAGE_FITS_EXPIRE_DAYS', 10))
        cutoff_age_images_fits_date = cutoff_age_images_fits.date()  # cutoff date based on dayDate attribute, not createDate

        old_fits_images = IndiAllSkyDbFitsImageTable.query\
            .join(IndiAllSkyDbFitsImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera.id)\
            .filter(IndiAllSkyDbFitsImageTable.dayDate < cutoff_age_images_fits_date)\
            .order_by(IndiAllSkyDbFitsImageTable.createDate.asc())


        # videos
        cutoff_age_timelapse = now - timedelta(days=self.config.get('TIMELAPSE_EXPIRE_DAYS', 365))
        cutoff_age_timelapse_date = cutoff_age_timelapse.date()  # cutoff date based on dayDate attribute, not createDate

        old_videos = IndiAllSkyDbVideoTable.query\
            .join(IndiAllSkyDbVideoTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera.id)\
            .filter(IndiAllSkyDbVideoTable.dayDate < cutoff_age_timelapse_date)\
            .order_by(IndiAllSkyDbVideoTable.createDate.asc())
        old_mini_videos = IndiAllSkyDbMiniVideoTable.query\
            .join(IndiAllSkyDbMiniVideoTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera.id)\
            .filter(IndiAllSkyDbMiniVideoTable.dayDate < cutoff_age_timelapse_date)\
            .order_by(IndiAllSkyDbMiniVideoTable.createDate.asc())
        old_keograms = IndiAllSkyDbKeogramTable.query\
            .join(IndiAllSkyDbKeogramTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera.id)\
            .filter(IndiAllSkyDbKeogramTable.dayDate < cutoff_age_timelapse_date)\
            .order_by(IndiAllSkyDbKeogramTable.createDate.asc())
        old_startrails = IndiAllSkyDbStarTrailsTable.query\
            .join(IndiAllSkyDbStarTrailsTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera.id)\
            .filter(IndiAllSkyDbStarTrailsTable.dayDate < cutoff_age_timelapse_date)\
            .order_by(IndiAllSkyDbStarTrailsTable.createDate.asc())
        old_startrails_videos = IndiAllSkyDbStarTrailsVideoTable.query\
            .join(IndiAllSkyDbStarTrailsVideoTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera.id)\
            .filter(IndiAllSkyDbStarTrailsVideoTable.dayDate < cutoff_age_timelapse_date)\
            .order_by(IndiAllSkyDbStarTrailsVideoTable.createDate.asc())
        old_panorama_videos = IndiAllSkyDbPanoramaVideoTable.query\
            .join(IndiAllSkyDbPanoramaVideoTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera.id)\
            .filter(IndiAllSkyDbPanoramaVideoTable.dayDate < cutoff_age_timelapse_date)\
            .order_by(IndiAllSkyDbPanoramaVideoTable.createDate.asc())


        ### Getting IDs first then deleting each file is faster than deleting all files with
        ### thumbnails with a single query.  Deleting associated thumbnails causes sqlalchemy
        ### to recache after every delete which cause a 1-5 second lag for each delete


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


        task.setSuccess('Expired {0:d} assets'.format(delete_count))


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

        return delete_count


    def _getVideoFolder(self, video_date, camera):
        day_ref = video_date

        video_folder = self.image_dir.joinpath(
            'ccd_{0:s}'.format(camera.uuid),
            'timelapse',
            '{0:s}'.format(day_ref.strftime('%Y%m%d')),
        )


        if not video_folder.exists():
            video_folder.mkdir(mode=0o755, parents=True)

        return video_folder


    def _getFolderFilesByExt(self, folder, file_list, extension_list=None):
        if not extension_list:
            extension_list = [self.config['IMAGE_FILE_TYPE']]

        #logger.info('Searching for image files in %s', folder)

        dot_extension_list = ['.{0:s}'.format(e) for e in extension_list]

        for item in Path(folder).iterdir():
            if item.is_file() and item.suffix in dot_extension_list:
                file_list.append(item)
            elif item.is_dir():
                self._getFolderFilesByExt(item, file_list, extension_list=extension_list)  # recursion


    def _getFolderFolders(self, folder, dir_list):
        for item in Path(folder).iterdir():
            if item.is_dir():
                dir_list.append(item)
                self._getFolderFolders(item, dir_list)  # recursion


    def _load_detection_mask(self):
        detect_mask = self.config.get('DETECT_MASK', '')

        if not detect_mask:
            logger.warning('No detection mask defined')
            return


        detect_mask_p = Path(detect_mask)

        try:
            if not detect_mask_p.exists():
                logger.error('%s does not exist', detect_mask_p)
                return


            if not detect_mask_p.is_file():
                logger.error('%s is not a file', detect_mask_p)
                return

        except PermissionError as e:
            logger.error(str(e))
            return

        mask_data = cv2.imread(str(detect_mask_p), cv2.IMREAD_GRAYSCALE)  # mono
        if isinstance(mask_data, type(None)):
            logger.error('%s is not a valid image', detect_mask_p)
            return

        ### any compression artifacts will be set to black
        #mask_data[mask_data < 255] = 0  # did not quite work


        mask_processor = MaskProcessor(
            self.config,
            self.bin_v,
        )


        # masks need to be rotated, flipped, cropped for post-processed images
        mask_processor.image = mask_data


        if self.config.get('IMAGE_ROTATE'):
            mask_processor.rotate_90()


        # rotation
        if self.config.get('IMAGE_ROTATE_ANGLE'):
            mask_processor.rotate_angle()


        # verticle flip
        if self.config.get('IMAGE_FLIP_V'):
            mask_processor.flip_v()


        # horizontal flip
        if self.config.get('IMAGE_FLIP_H'):
            mask_processor.flip_h()


        # crop
        if self.config.get('IMAGE_CROP_ROI'):
            mask_processor.crop_image()


        # scale
        if self.config['IMAGE_SCALE'] and self.config['IMAGE_SCALE'] != 100:
            mask_processor.scale_image()


        return mask_processor.image


