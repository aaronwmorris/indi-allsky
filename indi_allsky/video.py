import os
import io
import time
import math
import json
import cv2
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
import tempfile
import fcntl
import errno
import traceback
import logging

import ephem

from .timelapse import TimelapseGenerator
from .keogram import KeogramGenerator
from .starTrails import StarTrailGenerator

from .flask import db
from .flask.miscDb import miscDb

from .flask.models import TaskQueueState
from .flask.models import TaskQueueQueue
from .flask.models import IndiAllSkyDbCameraTable
from .flask.models import IndiAllSkyDbImageTable
from .flask.models import IndiAllSkyDbVideoTable
from .flask.models import IndiAllSkyDbKeogramTable
from .flask.models import IndiAllSkyDbStarTrailsTable
from .flask.models import IndiAllSkyDbStarTrailsVideoTable
from .flask.models import IndiAllSkyDbFitsImageTable
from .flask.models import IndiAllSkyDbRawImageTable
from .flask.models import IndiAllSkyDbTaskQueueTable

from sqlalchemy.orm.exc import NoResultFound

from multiprocessing import Process
#from threading import Thread
import queue

logger = logging.getLogger('indi_allsky')



class VideoWorker(Process):

    video_lockfile = '/tmp/timelapse_video.lock'


    def __init__(self, idx, config, error_q, video_q, upload_q, bin_v):
        super(VideoWorker, self).__init__()

        #self.threadID = idx
        self.name = 'VideoWorker{0:03d}'.format(idx)

        os.nice(19)  # lower priority

        self.config = config
        self.error_q = error_q
        self.video_q = video_q
        self.upload_q = upload_q
        self.bin_v = bin_v

        self._miscDb = miscDb(self.config)

        self.f_lock = None

        self._detection_mask = self._load_detection_mask()


    def run(self):
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
            time.sleep(1.9)  # sleep every loop

            try:
                v_dict = self.video_q.get_nowait()
            except queue.Empty:
                continue

            if v_dict.get('stop'):
                return


            task_id = v_dict['task_id']


            try:
                task = IndiAllSkyDbTaskQueueTable.query\
                    .filter(IndiAllSkyDbTaskQueueTable.id == task_id)\
                    .filter(IndiAllSkyDbTaskQueueTable.state == TaskQueueState.QUEUED)\
                    .filter(IndiAllSkyDbTaskQueueTable.queue == TaskQueueQueue.VIDEO)\
                    .one()

            except NoResultFound:
                logger.error('Task ID %d not found', task_id)
                continue


            task.setRunning()


            try:
                self._getLock()  # get lock to prevent multiple videos from being concurrently generated
            except BlockingIOError as e:
                if e.errno == errno.EAGAIN:
                    logger.error('Failed to get exclusive lock: %s', str(e))
                    task.setFailed('Failed to get exclusive lock')
                    return


            timespec = task.data['timespec']
            img_folder = Path(task.data['img_folder'])
            timeofday = task.data['timeofday']
            camera_id = task.data['camera_id']
            video = task.data.get('video', True)
            keogram = task.data.get('keogram', True)
            #startrail = task.data.get('startrail', True)
            expireData = task.data.get('expireData', False)


            if not img_folder.exists():
                logger.error('Image folder does not exist: %s', img_folder)
                task.setFailed('Image folder does not exist: {0:s}'.format(str(img_folder)))
                continue


            if expireData:
                self.expireData(task, img_folder)


            self.uploadAllskyEndOfNight(timeofday)


            if video:
                task.setRunning()
                self.generateVideo(task, timespec, img_folder, timeofday, camera_id)


            if keogram:
                task.setRunning()
                self.generateKeogramStarTrails(task, timespec, img_folder, timeofday, camera_id)


            self._releaseLock()



    def generateVideo(self, task, timespec, img_folder, timeofday, camera_id):
        try:
            d_dayDate = datetime.strptime(timespec, '%Y%m%d').date()
        except ValueError:
            logger.error('Invalid time spec')
            task.setFailed('Invalid time spec')
            return


        if timeofday == 'night':
            night = True
        else:
            night = False


        video_file = img_folder.parent.joinpath('allsky-timelapse_ccd{0:d}_{1:s}_{2:s}.mp4'.format(camera_id, timespec, timeofday))

        if video_file.exists():
            logger.warning('Video is already generated: %s', video_file)
            task.setFailed('Video is already generated: {0:s}'.format(str(video_file)))
            return


        try:
            # delete old video entry if it exists
            video_entry = IndiAllSkyDbVideoTable.query\
                .filter(IndiAllSkyDbVideoTable.filename == str(video_file))\
                .one()

            logger.warning('Removing orphaned video db entry')
            db.session.delete(video_entry)
            db.session.commit()
        except NoResultFound:
            pass


        # find all files
        timelapse_files_entries = IndiAllSkyDbImageTable.query\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .filter(IndiAllSkyDbImageTable.dayDate == d_dayDate)\
            .filter(IndiAllSkyDbImageTable.night == night)\
            .order_by(IndiAllSkyDbImageTable.createDate.asc())


        logger.info('Found %d images for timelapse', timelapse_files_entries.count())

        timelapse_files = list()
        for entry in timelapse_files_entries:
            p_entry = Path(entry.getFilesystemPath())

            if not p_entry.exists():
                logger.error('File not found: %s', p_entry)
                continue

            if p_entry.stat().st_size == 0:
                continue

            timelapse_files.append(p_entry)


        # Create DB entry before creating file
        video_entry = self._miscDb.addVideo(
            video_file,
            camera_id,
            d_dayDate,
            timeofday,
        )


        tg = TimelapseGenerator(self.config)
        tg.generate(video_file, timelapse_files)


        task.setSuccess('Generated timelapse: {0:s}'.format(str(video_file)))

        ### Upload ###
        self.uploadVideo(video_file)

        self._miscDb.addUploadedFlag(video_entry)



    def uploadVideo(self, video_file):
        ### Upload video
        if not self.config.get('FILETRANSFER', {}).get('UPLOAD_VIDEO'):
            logger.warning('Video uploading disabled')
            return


        now = datetime.now()

        # Parameters for string formatting
        file_data_dict = {
            'timestamp'    : now,
            'ts'           : now,  # shortcut
        }


        # Replace parameters in names
        remote_dir = self.config['FILETRANSFER']['REMOTE_VIDEO_FOLDER'].format(**file_data_dict)


        remote_file_p = Path(remote_dir).joinpath(video_file.name)

        # tell worker to upload file
        jobdata = {
            'action'      : 'upload',
            'local_file'  : str(video_file),
            'remote_file' : str(remote_file_p),
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.upload_q.put({'task_id' : task.id})


    def generateKeogramStarTrails(self, task, timespec, img_folder, timeofday, camera_id):
        try:
            d_dayDate = datetime.strptime(timespec, '%Y%m%d').date()
        except ValueError:
            logger.error('Invalid time spec')
            task.setFailed('Invalid time spec')
            return


        if timeofday == 'night':
            night = True
        else:
            night = False



        keogram_file = img_folder.parent.joinpath('allsky-keogram_ccd{0:d}_{1:s}_{2:s}.{3:s}'.format(camera_id, timespec, timeofday, self.config['IMAGE_FILE_TYPE']))
        startrail_file = img_folder.parent.joinpath('allsky-startrail_ccd{0:d}_{1:s}_{2:s}.{3:s}'.format(camera_id, timespec, timeofday, self.config['IMAGE_FILE_TYPE']))
        startrail_video_file = img_folder.parent.joinpath('allsky-startrail_timelapse_ccd{0:d}_{1:s}_{2:s}.mp4'.format(camera_id, timespec, timeofday))

        if keogram_file.exists():
            logger.warning('Keogram is already generated: %s', keogram_file)
            task.setFailed('Keogram is already generated: {0:s}'.format(str(keogram_file)))
            return

        if startrail_file.exists():
            logger.warning('Star trail is already generated: %s', startrail_file)
            task.setFailed('Star trail is already generated: {0:s}'.format(str(startrail_file)))
            return

        if startrail_video_file.exists():
            logger.warning('Star trail timelapse is already generated: %s', startrail_video_file)
            task.setFailed('Star trail timelapse is already generated: {0:s}'.format(str(startrail_video_file)))
            return



        try:
            # delete old keogram entry if it exists
            keogram_entry = IndiAllSkyDbKeogramTable.query\
                .filter(IndiAllSkyDbKeogramTable.filename == str(keogram_file))\
                .one()

            logger.warning('Removing orphaned keogram db entry')
            db.session.delete(keogram_entry)
            db.session.commit()
        except NoResultFound:
            pass


        try:
            # delete old star trail entry if it exists
            startrail_entry = IndiAllSkyDbStarTrailsTable.query\
                .filter(IndiAllSkyDbStarTrailsTable.filename == str(startrail_file))\
                .one()

            logger.warning('Removing orphaned star trail db entry')
            db.session.delete(startrail_entry)
            db.session.commit()
        except NoResultFound:
            pass


        try:
            # delete old star trail video entry if it exists
            startrail_video_entry = IndiAllSkyDbStarTrailsVideoTable.query\
                .filter(IndiAllSkyDbStarTrailsVideoTable.filename == str(startrail_video_file))\
                .one()

            logger.warning('Removing orphaned star trail video db entry')
            db.session.delete(startrail_video_entry)
            db.session.commit()
        except NoResultFound:
            pass


        # find all files
        files_entries = IndiAllSkyDbImageTable.query\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .filter(IndiAllSkyDbImageTable.dayDate == d_dayDate)\
            .filter(IndiAllSkyDbImageTable.night == night)\
            .order_by(IndiAllSkyDbImageTable.createDate.asc())


        image_count = files_entries.count()
        logger.info('Found %d images for keogram/star trails', image_count)


        processing_start = time.time()

        kg = KeogramGenerator(self.config)
        kg.angle = self.config['KEOGRAM_ANGLE']
        kg.h_scale_factor = self.config['KEOGRAM_H_SCALE']
        kg.v_scale_factor = self.config['KEOGRAM_V_SCALE']



        # Add DB entries before creating files
        keogram_entry = self._miscDb.addKeogram(
            keogram_file,
            camera_id,
            d_dayDate,
            timeofday,
        )

        if night:
            startrail_entry = self._miscDb.addStarTrail(
                startrail_file,
                camera_id,
                d_dayDate,
                timeofday=timeofday,
            )


        stg = StarTrailGenerator(self.config, self.bin_v, mask=self._detection_mask)
        stg.max_brightness = self.config['STARTRAILS_MAX_ADU']
        stg.mask_threshold = self.config['STARTRAILS_MASK_THOLD']
        stg.pixel_cutoff_threshold = self.config['STARTRAILS_PIXEL_THOLD']


        # Files are presorted from the DB
        for i, entry in enumerate(files_entries):
            if i % 100 == 0:
                logger.info('Processed %d of %d images', i, image_count)

            p_entry = Path(entry.getFilesystemPath())

            if not p_entry.exists():
                logger.error('File not found: %s', p_entry)
                continue

            if p_entry.stat().st_size == 0:
                continue

            #logger.info('Reading file: %s', p_entry)
            image = cv2.imread(str(p_entry), cv2.IMREAD_UNCHANGED)

            if isinstance(image, type(None)):
                logger.error('Unable to read %s', p_entry)
                continue

            kg.processImage(p_entry, image)

            if night:
                stg.processImage(p_entry, image)


        kg.finalize(keogram_file)

        if night:
            stg.finalize(startrail_file)

            st_frame_count = stg.timelapse_frame_count
            if st_frame_count >= self.config.get('STARTRAILS_TIMELAPSE_MINFRAMES', 250):
                startrail_video_entry = self._miscDb.addStarTrailVideo(
                    startrail_video_file,
                    camera_id,
                    d_dayDate,
                    timeofday=timeofday,
                )

                st_tg = TimelapseGenerator(self.config)
                st_tg.generate(startrail_video_file, stg.timelapse_frame_list)
            else:
                logger.error('Not enough frames to generate star trails timelapse: %d', self.st_frame_count)


        processing_elapsed_s = time.time() - processing_start
        logger.warning('Total keogram/star trail processing in %0.1f s', processing_elapsed_s)


        if keogram_file.exists():
            self.uploadKeogram(keogram_file)
            self._miscDb.addUploadedFlag(keogram_entry)


        if night and startrail_file.exists():
            self.uploadStarTrail(startrail_file)
            self._miscDb.addUploadedFlag(startrail_entry)


        if night and startrail_video_file.exists():
            self.uploadStarTrailVideo(startrail_video_file)
            self._miscDb.addUploadedFlag(startrail_video_entry)


        task.setSuccess('Generated keogram and/or star trail')


    def uploadKeogram(self, keogram_file):
        ### Upload video
        if not self.config.get('FILETRANSFER', {}).get('UPLOAD_KEOGRAM'):
            logger.warning('Keogram uploading disabled')
            return


        now = datetime.now()

        # Parameters for string formatting
        file_data_dict = {
            'timestamp'    : now,
            'ts'           : now,  # shortcut
        }


        # Replace parameters in names
        remote_dir = self.config['FILETRANSFER']['REMOTE_KEOGRAM_FOLDER'].format(**file_data_dict)


        remote_file_p = Path(remote_dir).joinpath(keogram_file.name)


        # tell worker to upload file
        jobdata = {
            'action'      : 'upload',
            'local_file'  : str(keogram_file),
            'remote_file' : str(remote_file_p),
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.upload_q.put({'task_id' : task.id})


    def uploadStarTrail(self, startrail_file):
        if not self.config.get('FILETRANSFER', {}).get('UPLOAD_STARTRAIL'):
            logger.warning('Star trail uploading disabled')
            return


        now = datetime.now()

        # Parameters for string formatting
        file_data_dict = {
            'timestamp'    : now,
            'ts'           : now,  # shortcut
        }


        # Replace parameters in names
        remote_dir = self.config['FILETRANSFER']['REMOTE_STARTRAIL_FOLDER'].format(**file_data_dict)


        remote_file_p = Path(remote_dir).joinpath(startrail_file.name)


        # tell worker to upload file
        jobdata = {
            'action'      : 'upload',
            'local_file'  : str(startrail_file),
            'remote_file' : str(remote_file_p),
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.upload_q.put({'task_id' : task.id})


    def uploadStarTrailVideo(self, startrail_video_file):
        self.uploadVideo(startrail_video_file)


    def uploadAllskyEndOfNight(self, timeofday):
        if timeofday != 'night':
            # Only upload at end of night
            return

        if not self.config.get('FILETRANSFER', {}).get('UPLOAD_ENDOFNIGHT'):
            logger.warning('End of Night uploading disabled')
            return

        if not self.config.get('FILETRANSFER', {}).get('REMOTE_ENDOFNIGHT_FOLDER'):
            logger.error('End of Night folder not configured')
            return


        logger.info('Generating Allsky EndOfNight data.json')

        utcnow = datetime.utcnow()  # ephem expects UTC dates

        obs = ephem.Observer()
        obs.lon = math.radians(self.config['LOCATION_LONGITUDE'])
        obs.lat = math.radians(self.config['LOCATION_LATITUDE'])

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
        data_tempfile_f.flush()
        data_tempfile_f.close()

        data_json_p = Path(data_tempfile_f.name)



        now = datetime.now()

        # Parameters for string formatting
        file_data_dict = {
            'timestamp'    : now,
            'ts'           : now,  # shortcut
        }


        # Replace parameters in names
        remote_dir = self.config['FILETRANSFER']['REMOTE_ENDOFNIGHT_FOLDER'].format(**file_data_dict)

        remote_file_p = Path(remote_dir).joinpath('data.json')


        jobdata = {
            'action'         : 'upload',
            'local_file'     : str(data_json_p),
            'remote_file'    : str(remote_file_p),
            'remove_local'   : True,
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.upload_q.put({'task_id' : task.id})


    def expireData(self, task, img_folder):
        # Old image files need to be pruned
        cutoff_age_images = datetime.now() - timedelta(days=self.config['IMAGE_EXPIRE_DAYS'])
        cutoff_age_images_date = cutoff_age_images.date()  # cutoff date based on dayDate attribute, not createDate

        old_images = IndiAllSkyDbImageTable.query\
            .filter(IndiAllSkyDbImageTable.dayDate < cutoff_age_images_date)
        old_fits_images = IndiAllSkyDbFitsImageTable.query\
            .filter(IndiAllSkyDbFitsImageTable.dayDate < cutoff_age_images_date)
        old_raw_images = IndiAllSkyDbRawImageTable.query\
            .filter(IndiAllSkyDbRawImageTable.dayDate < cutoff_age_images_date)

        cutoff_age_timelapse = datetime.now() - timedelta(days=self.config.get('TIMELAPSE_EXPIRE_DAYS', 365))
        cutoff_age_timelapse_date = cutoff_age_timelapse.date()  # cutoff date based on dayDate attribute, not createDate

        old_videos = IndiAllSkyDbVideoTable.query\
            .filter(IndiAllSkyDbVideoTable.dayDate < cutoff_age_timelapse_date)
        old_keograms = IndiAllSkyDbKeogramTable.query\
            .filter(IndiAllSkyDbKeogramTable.dayDate < cutoff_age_timelapse_date)
        old_startrails = IndiAllSkyDbStarTrailsTable.query\
            .filter(IndiAllSkyDbStarTrailsTable.dayDate < cutoff_age_timelapse_date)


        # images
        logger.warning('Found %d expired images to delete', old_images.count())
        for file_entry in old_images:
            #logger.info('Removing old image: %s', file_entry.filename)

            file_p = Path(file_entry.getFilesystemPath())

            try:
                file_p.unlink()
            except OSError as e:
                logger.error('Cannot remove file: %s', str(e))
                continue
            except FileNotFoundError as e:
                logger.warning('File already removed: %s', str(e))


        old_images.delete()  # mass delete
        db.session.commit()


        # fits images
        logger.warning('Found %d expired FITS images to delete', old_fits_images.count())
        for file_entry in old_fits_images:
            #logger.info('Removing old image: %s', file_entry.filename)

            file_p = Path(file_entry.getFilesystemPath())

            try:
                file_p.unlink()
            except OSError as e:
                logger.error('Cannot remove file: %s', str(e))
                continue
            except FileNotFoundError as e:
                logger.warning('File already removed: %s', str(e))


        old_fits_images.delete()  # mass delete
        db.session.commit()


        # raw images
        logger.warning('Found %d expired RAW images to delete', old_raw_images.count())
        for file_entry in old_raw_images:
            #logger.info('Removing old image: %s', file_entry.filename)

            file_p = Path(file_entry.getFilesystemPath())

            try:
                file_p.unlink()
            except OSError as e:
                logger.error('Cannot remove file: %s', str(e))
                continue
            except FileNotFoundError as e:
                logger.warning('File already removed: %s', str(e))


        old_raw_images.delete()  # mass delete
        db.session.commit()


        # videos
        logger.warning('Found %d expired videos to delete', old_videos.count())
        for file_entry in old_videos:
            #logger.info('Removing old video: %s', file_entry.filename)

            file_p = Path(file_entry.getFilesystemPath())

            try:
                file_p.unlink()
            except OSError as e:
                logger.error('Cannot remove file: %s', str(e))
                continue
            except FileNotFoundError as e:
                logger.warning('File already removed: %s', str(e))


        old_videos.delete()  # mass delete
        db.session.commit()


        # keograms
        logger.warning('Found %d expired keograms to delete', old_keograms.count())
        for file_entry in old_keograms:
            #logger.info('Removing old keogram: %s', file_entry.filename)

            file_p = Path(file_entry.getFilesystemPath())

            try:
                file_p.unlink()
            except OSError as e:
                logger.error('Cannot remove file: %s', str(e))
                continue
            except FileNotFoundError as e:
                logger.warning('File already removed: %s', str(e))


        old_keograms.delete()  # mass delete
        db.session.commit()


        # star trails
        logger.warning('Found %d expired star trails to delete', old_startrails.count())
        for file_entry in old_startrails:
            #logger.info('Removing old star trails: %s', file_entry.filename)

            file_p = Path(file_entry.getFilesystemPath())

            try:
                file_p.unlink()
            except OSError as e:
                logger.error('Cannot remove file: %s', str(e))
                continue
            except FileNotFoundError as e:
                logger.warning('File already removed: %s', str(e))


        old_startrails.delete()  # mass delete
        db.session.commit()


        ### The following code will need to be pruned eventually since we are deleting based on DB entries
        # Old fits image files need to be pruned


        # ensure we do not delete images stored in DB
        cutoff_age_images_minus_1day = cutoff_age_images - timedelta(days=1)


        fits_file_list = list()
        self.getFolderFilesByExt(img_folder, fits_file_list, extension_list=['fit', 'fits'])

        old_fits_files_1 = filter(lambda p: p.stat().st_mtime < cutoff_age_images_minus_1day.timestamp(), fits_file_list)
        old_fits_files_nodarks = filter(lambda p: 'dark' not in p.name, old_fits_files_1)  # exclude darks
        old_fits_files_no_d_bpm = filter(lambda p: 'bpm' not in p.name, old_fits_files_nodarks)  # exclude bpms
        logger.warning('Found %d expired fits images to delete', len(list(old_fits_files_no_d_bpm)))
        for f in old_fits_files_no_d_bpm:
            logger.info('Removing old fits image: %s', f)

            try:
                f.unlink()
            except OSError as e:
                logger.error('Cannot remove file: %s', str(e))



        # Old export image files need to be pruned
        export_folder_p = Path(self.config['IMAGE_EXPORT_FOLDER'])

        export_file_list = list()
        self.getFolderFilesByExt(export_folder_p, export_file_list, extension_list=['jpg', 'jpeg', 'png', 'tif', 'tiff'])

        old_export_files = filter(lambda p: p.stat().st_mtime < cutoff_age_images_minus_1day.timestamp(), export_file_list)
        logger.warning('Found %d expired export images to delete', len(list(old_export_files)))
        for f in old_export_files:
            logger.info('Removing old export image: %s', f)

            try:
                f.unlink()
            except OSError as e:
                logger.error('Cannot remove file: %s', str(e))



        # Remove empty folders
        dir_list = list()
        self.getFolderFolders(img_folder, dir_list)
        self.getFolderFolders(export_folder_p, dir_list)

        empty_dirs = filter(lambda p: not any(p.iterdir()), dir_list)
        for d in empty_dirs:
            logger.info('Removing empty directory: %s', d)

            try:
                d.rmdir()
            except OSError as e:
                logger.error('Cannot remove folder: %s', str(e))
            except PermissionError as e:
                logger.error('Cannot remove folder: %s', str(e))

        task.setSuccess('Expired images')


    def getFolderFilesByExt(self, folder, file_list, extension_list=None):
        if not extension_list:
            extension_list = [self.config['IMAGE_FILE_TYPE']]

        #logger.info('Searching for image files in %s', folder)

        dot_extension_list = ['.{0:s}'.format(e) for e in extension_list]

        for item in Path(folder).iterdir():
            if item.is_file() and item.suffix in dot_extension_list:
                file_list.append(item)
            elif item.is_dir():
                self.getFolderFilesByExt(item, file_list, extension_list=extension_list)  # recursion


    def getFolderFolders(self, folder, dir_list):
        for item in Path(folder).iterdir():
            if item.is_dir():
                dir_list.append(item)
                self.getFolderFolders(item, dir_list)  # recursion


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


        return mask_data


    def _getLock(self):
        logger.info('Get exclusive lock to generate video')
        lock_p = Path(self.video_lockfile)

        if not lock_p.is_file():
            f_lock = io.open(str(lock_p), 'w+')
            f_lock.close()
            lock_p.chmod(0o644)

        self.f_lock = io.open(str(lock_p), 'w+')
        fcntl.flock(self.f_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)  # Exclusive, non-blocking lock


    def _releaseLock(self):
        logger.info('Release exclusive lock')
        fcntl.flock(self.f_lock, fcntl.LOCK_UN)
        self.f_lock.close()

