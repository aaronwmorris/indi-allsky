import platform
import sys
import fcntl
#import errno
import os
import time
import io
import re
import psutil
from pathlib import Path
from datetime import datetime
from datetime import timedelta
#from pprint import pformat
import signal
import logging

import queue
from multiprocessing import Queue
from multiprocessing import Value
from multiprocessing import Array

from .version import __version__
from .version import __config_level__

from .config import IndiAllSkyConfig

from . import constants

from .exceptions import TimeOutException
from .exceptions import ConfigSaveException

from .flask import create_app
from .flask import db
from .flask.miscDb import miscDb

from .flask.models import TaskQueueQueue
from .flask.models import TaskQueueState
from .flask.models import NotificationCategory

from .flask.models import IndiAllSkyDbCameraTable
from .flask.models import IndiAllSkyDbImageTable
from .flask.models import IndiAllSkyDbVideoTable
from .flask.models import IndiAllSkyDbKeogramTable
from .flask.models import IndiAllSkyDbStarTrailsTable
from .flask.models import IndiAllSkyDbStarTrailsVideoTable
from .flask.models import IndiAllSkyDbPanoramaImageTable
from .flask.models import IndiAllSkyDbPanoramaVideoTable
from .flask.models import IndiAllSkyDbTaskQueueTable

from sqlalchemy import or_
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.expression import false as sa_false


app = create_app()

logger = logging.getLogger('indi_allsky')


class IndiAllSky(object):

    periodic_tasks_offset = 300         # 5 minutes
    cleanup_tasks_offset = 43200        # 12 hours
    aurora_tasks_offset = 1800          # 30 minutes
    smoke_tasks_offset = 10800          # 3 hours
    sat_data_tasks_offset = 259200      # 3 days


    def __init__(self):
        self.name = 'Main'

        self.pid_lock = None

        with app.app_context():
            try:
                self._config_obj = IndiAllSkyConfig()
                #logger.info('Loaded config id: %d', self._config_obj.config_id)
            except NoResultFound:
                logger.error('No config file found, please import a config')
                sys.exit(1)

            self.config = self._config_obj.config


        self._miscDb = miscDb(self.config)


        if __config_level__ != self._config_obj.config_level:
            logger.error('indi-allsky version does not match config, please rerun setup.sh')

            with app.app_context():
                self._miscDb.addNotification(
                    NotificationCategory.STATE,
                    'config_version',
                    'WARNING: indi-allsky version does not match config, please rerun setup.sh',
                    expire=timedelta(hours=2),
                )

            sys.exit(1)


        with app.app_context():
            self._miscDb.setState('CONFIG_ID', self._config_obj.config_id)

        self._pid_file = Path('/var/lib/indi-allsky/indi-allsky.pid')


        self.periodic_tasks_time = time.time() + self.periodic_tasks_offset
        #self.periodic_tasks_time = time.time()  # testing
        self.cleanup_tasks_time = time.time()   # run asap
        self.aurora_tasks_time = time.time()    # run asap
        self.smoke_tasks_time = time.time()     # run asap
        self.sat_data_tasks_time = time.time()  # run asap


        self.position_av = Array('f', [
            float(self.config['LOCATION_LATITUDE']),
            float(self.config['LOCATION_LONGITUDE']),
            float(self.config.get('LOCATION_ELEVATION', 300)),
            0.0,  # Ra
            0.0,  # Dec
        ])


        ### temperature values in this array should always be in Celsius
        # 0 ccd temp
        # 1-9 reserved for future use
        # 10-29 system temperatures
        self.sensors_temp_av = Array('f', [0.0 for x in range(30)])

        # sensors (temp, humidity, wind, sqm, etc)
        # 0 ccd temp
        # 1 dew heater level
        # 2 dew point
        # 3 frost point
        # 4 fan level
        # 5 heat index
        # 6 wind direction in degrees
        # 7 sqm
        # 8-9 reserved for future use
        self.sensors_user_av = Array('f', [0.0 for x in range(30)])

        self.exposure_av = Array('f', [
            -1.0,  # current exposure - these must be -1.0 to indicate unset
            -1.0,  # night minimum
            -1.0,  # day minimum
            -1.0,  # maximum
        ])

        self.gain_v = Value('i', -1)  # value set in CCD config
        self.bin_v = Value('i', 1)  # set 1 for sane default


        # These shared values are to indicate when the camera is in night/moon modes
        self.night_v = Value('i', -1)  # bogus initial value
        self.moonmode_v = Value('i', -1)  # bogus initial value


        self.capture_q = Queue()
        self.capture_error_q = Queue()
        self.capture_worker = None
        self.capture_worker_idx = 0

        self.image_q = Queue()
        self.image_error_q = Queue()
        self.image_worker = None
        self.image_worker_idx = 0

        self.video_q = Queue()
        self.video_error_q = Queue()
        self.video_worker = None
        self.video_worker_idx = 0

        self.sensor_q = Queue()
        self.sensor_error_q = Queue()
        self.sensor_worker = None
        self.sensor_worker_idx = 0

        self.upload_q = Queue()
        self.upload_worker_list = []
        self.upload_worker_idx = 0

        for x in range(self.config.get('UPLOAD_WORKERS', 1)):
            self.upload_worker_list.append({
                'worker'  : None,
                'error_q' : Queue(),
            })


        if self.config['IMAGE_FOLDER']:
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()


        self.generate_timelapse_flag = False   # This is updated once images have been generated


        self._reload = False
        self._shutdown = False
        self._terminate = False

        signal.signal(signal.SIGALRM, self.sigalarm_handler_main)
        signal.signal(signal.SIGHUP, self.sighup_handler_main)
        signal.signal(signal.SIGTERM, self.sigterm_handler_main)
        signal.signal(signal.SIGINT, self.sigint_handler_main)



    @property
    def pid_file(self):
        return self._pid_file

    @pid_file.setter
    def pid_file(self, new_pid_file):
        self._pid_file = Path(new_pid_file)


    def sighup_handler_main(self, signum, frame):
        logger.warning('Caught HUP signal')

        self._reload = True


    def sigterm_handler_main(self, signum, frame):
        logger.warning('Caught TERM signal, shutting down')

        # set flag for program to stop processes
        self._shutdown = True
        self._terminate = True


    def sigint_handler_main(self, signum, frame):
        logger.warning('Caught INT signal, shutting down')

        # set flag for program to stop processes
        self._shutdown = True


    def sigalarm_handler_main(self, signum, frame):
        raise TimeOutException()


    def write_pid(self):
        pid = os.getpid()

        try:
            with io.open(str(self.pid_file), 'w') as pid_f:
                pid_f.write('{0:d}'.format(pid))
        except PermissionError as e:
            logger.error('Unable to write pid file: %s', str(e))
            sys.exit(1)


        self.pid_file.chmod(0o644)

        try:
            self.pid_lock = io.open(self.pid_file, 'w+')
            fcntl.flock(self.pid_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.error('Failed to get lock, indi-allsky may already be running')
            sys.exit(1)
        except PermissionError as e:
            logger.error('Failed to get lock: %s', e.strerror)
            sys.exit(1)


        self._miscDb.setState('PID', pid)
        self._miscDb.setState('PID_FILE', self.pid_file)


    def _startup(self):
        now = time.time()

        self._miscDb.setState('WATCHDOG', int(now))
        self._miscDb.setState('STATUS', constants.STATUS_STARTING)

        logger.info('indi-allsky release: %s', str(__version__))
        logger.info('indi-allsky config level: %s', str(__config_level__))

        logger.info('Python version: %s', platform.python_version())
        logger.info('Platform: %s', platform.machine())
        logger.info('System Type: %s', self._getSystemType())

        logger.info('System CPUs: %d', psutil.cpu_count())

        memory_info = psutil.virtual_memory()
        memory_total_mb = int(memory_info[0] / 1024.0 / 1024.0)

        logger.info('System memory: %d MB', memory_total_mb)

        uptime_s = time.time() - psutil.boot_time()
        logger.info('System uptime: %ds', uptime_s)

        #logger.info('Temp dir: %s', tempfile.gettempdir())


    def _getSystemType(self):
        # This is available for SBCs and systems using device trees
        model_p = Path('/proc/device-tree/model')

        try:
            if model_p.exists():
                with io.open(str(model_p), 'r') as f:
                    system_type = f.readline()  # only first line
            else:
                return 'Generic PC'
        except PermissionError as e:
            app.logger.error('Permission error: %s', str(e))
            return 'Unknown'


        system_type = system_type.strip()


        if not system_type:
            return 'Unknown'


        return str(system_type)


    def _startCaptureWorker(self):
        from .capture import CaptureWorker

        if self.capture_worker:
            if self.capture_worker.is_alive():
                return

            try:
                capture_error, capture_traceback = self.capture_error_q.get_nowait()
                for line in capture_traceback.split('\n'):
                    logger.error('Capture worker exception: %s', line)
            except queue.Empty:
                pass


        self.capture_worker_idx += 1

        logger.info('Starting Capture-%d worker', self.capture_worker_idx)
        self.capture_worker = CaptureWorker(
            self.capture_worker_idx,
            self.config,
            self.capture_error_q,
            self.capture_q,
            self.image_q,
            self.video_q,
            self.upload_q,
            self.position_av,
            self.exposure_av,
            self.gain_v,
            self.bin_v,
            self.sensors_temp_av,
            self.sensors_user_av,
            self.night_v,
            self.moonmode_v,
        )
        self.capture_worker.start()


    def _stopCaptureWorker(self):
        if not self.capture_worker:
            return

        if not self.capture_worker.is_alive():
            return

        if self._terminate:
            logger.info('Terminating Capture worker')
            self.capture_worker.terminate()

        logger.info('Stopping Capture worker')

        self.capture_q.put({'stop' : True})
        self.capture_worker.join()


    def _startImageWorker(self):
        from .image import ImageWorker

        if self.image_worker:
            if self.image_worker.is_alive():
                return

            try:
                image_error, image_traceback = self.image_error_q.get_nowait()
                for line in image_traceback.split('\n'):
                    logger.error('Image worker exception: %s', line)
            except queue.Empty:
                pass


        self.image_worker_idx += 1

        logger.info('Starting Image-%d worker', self.image_worker_idx)
        self.image_worker = ImageWorker(
            self.image_worker_idx,
            self.config,
            self.image_error_q,
            self.image_q,
            self.upload_q,
            self.position_av,
            self.exposure_av,
            self.gain_v,
            self.bin_v,
            self.sensors_temp_av,
            self.sensors_user_av,
            self.night_v,
            self.moonmode_v,
        )
        self.image_worker.start()


        if self.image_worker_idx % 10 == 0:
            # notify if worker is restarted more than 10 times
            with app.app_context():
                self._miscDb.addNotification(
                    NotificationCategory.WORKER,
                    'ImageWorker',
                    'WARNING: Image worker was restarted more than 10 times',
                    expire=timedelta(hours=2),
                )


    def _stopImageWorker(self):
        if not self.image_worker:
            return

        if not self.image_worker.is_alive():
            return

        if self._terminate:
            logger.info('Terminating Image worker')
            self.image_worker.terminate()

        logger.info('Stopping Image worker')

        self.image_q.put({'stop' : True})
        self.image_worker.join()


    def _startVideoWorker(self):
        from .video import VideoWorker

        if self.video_worker:
            if self.video_worker.is_alive():
                return


            try:
                video_error, video_traceback = self.video_error_q.get_nowait()
                for line in video_traceback.split('\n'):
                    logger.error('Video worker exception: %s', line)
            except queue.Empty:
                pass


        self.video_worker_idx += 1

        logger.info('Starting Video-%d worker', self.video_worker_idx)
        self.video_worker = VideoWorker(
            self.video_worker_idx,
            self.config,
            self.video_error_q,
            self.video_q,
            self.upload_q,
            self.bin_v,
        )
        self.video_worker.start()


        if self.video_worker_idx % 10 == 0:
            # notify if worker is restarted more than 10 times
            with app.app_context():
                self._miscDb.addNotification(
                    NotificationCategory.WORKER,
                    'VideoWorker',
                    'WARNING: VideoWorker was restarted more than 10 times',
                    expire=timedelta(hours=2),
                )


    def _stopVideoWorker(self):
        if not self.video_worker:
            return

        if not self.video_worker.is_alive():
            return

        if self._terminate:
            logger.info('Terminating Video worker')
            self.video_worker.terminate()

        logger.info('Stopping Video worker')

        self.video_q.put({'stop' : True})
        self.video_worker.join()


    def _startSensorWorker(self):
        from .sensor import SensorWorker

        if self.sensor_worker:
            if self.sensor_worker.is_alive():
                return


            try:
                sensor_error, sensor_traceback = self.sensor_error_q.get_nowait()
                for line in sensor_traceback.split('\n'):
                    logger.error('Sensor worker exception: %s', line)
            except queue.Empty:
                pass


        self.sensor_worker_idx += 1

        logger.info('Starting Sensor-%d worker', self.sensor_worker_idx)
        self.sensor_worker = SensorWorker(
            self.sensor_worker_idx,
            self.config,
            self.sensor_q,
            self.sensor_error_q,
            self.sensors_temp_av,
            self.sensors_user_av,
            self.night_v,
        )
        self.sensor_worker.start()


        if self.sensor_worker_idx % 10 == 0:
            # notify if worker is restarted more than 10 times
            with app.app_context():
                self._miscDb.addNotification(
                    NotificationCategory.WORKER,
                    'SensorWorker',
                    'WARNING: SensorWorker was restarted more than 10 times',
                    expire=timedelta(hours=2),
                )


    def _stopSensorWorker(self):
        if not self.sensor_worker:
            return

        if not self.sensor_worker.is_alive():
            return

        logger.info('Stopping Sensor worker')

        self.sensor_q.put({'stop' : True})
        self.sensor_worker.join()


    def _startFileUploadWorkers(self):
        for upload_worker_dict in self.upload_worker_list:
            self._fileUploadWorkerStart(upload_worker_dict)


    def _fileUploadWorkerStart(self, uw_dict):
        from .uploader import FileUploader

        if uw_dict['worker']:
            if uw_dict['worker'].is_alive():
                return


            try:
                upload_error, upload_traceback = uw_dict['error_q'].get_nowait()
                for line in upload_traceback.split('\n'):
                    logger.error('Upload worker exception: %s', line)
            except queue.Empty:
                pass


        self.upload_worker_idx += 1

        logger.info('Starting Upload-%d worker', self.upload_worker_idx)
        uw_dict['worker'] = FileUploader(
            self.upload_worker_idx,
            self.config,
            uw_dict['error_q'],
            self.upload_q,
        )

        uw_dict['worker'].start()


        if self.upload_worker_idx % 20 == 0:
            # notify if worker is restarted more than 20 times
            with app.app_context():
                self._miscDb.addNotification(
                    NotificationCategory.WORKER,
                    'FileUploader',
                    'WARNING: Upload worker was restarted more than 20 times',
                    expire=timedelta(hours=2),
                )


    def _stopFileUploadWorkers(self):
        active_worker_list = list()
        for upload_worker_dict in self.upload_worker_list:
            if not upload_worker_dict['worker']:
                continue

            if not upload_worker_dict['worker'].is_alive():
                continue

            #if self._terminate:
            #    logger.info('Terminating Upload worker')
            #    upload_worker_dict['worker'].terminate()

            active_worker_list.append(upload_worker_dict)

            # need to put the stops in the queue before waiting on workers to join
            #self.upload_q.put({'stop' : True})
            upload_worker_dict['worker'].stop()


        for upload_worker_dict in active_worker_list:
            self._fileUploadWorkerStop(upload_worker_dict)


    def _fileUploadWorkerStop(self, uw_dict):
        logger.info('Stopping Upload worker')

        uw_dict['worker'].join()


    def run(self):
        with app.app_context():
            self.write_pid()

            self._expireOrphanedTasks()

            self._startup()


        while True:
            if self._shutdown:
                with app.app_context():
                    self._miscDb.setState('STATUS', constants.STATUS_STOPPING)


                logger.warning('Shutting down')
                self._stopCaptureWorker()  # stop this first so image queue is cleared out
                self._stopImageWorker()
                self._stopVideoWorker()
                self._stopSensorWorker()
                self._stopFileUploadWorkers()


                with app.app_context():
                    self._miscDb.addNotification(
                        NotificationCategory.STATE,
                        'indi-allsky',
                        'indi-allsky was shutdown',
                        expire=timedelta(hours=1),
                    )

                    self._miscDb.setState('STATUS', constants.STATUS_STOPPED)


                if self.pid_lock:
                    fcntl.flock(self.pid_lock, fcntl.LOCK_UN)

                sys.exit()


            if self._reload:
                logger.warning('Restarting processes')
                self._reload = False
                self._stopCaptureWorker()  # stop this first so image queue is cleared out
                self._stopImageWorker()
                self._stopVideoWorker()
                self._stopSensorWorker()
                self._stopFileUploadWorkers()
                # processes will start at the next loop

                with app.app_context():
                    self.reload_handler()


            # do *NOT* start workers inside of a flask context
            # doing so will cause TLS/SSL problems connecting to databases

            # restart worker if it has failed
            self._startCaptureWorker()
            self._startImageWorker()
            self._startVideoWorker()
            self._startSensorWorker()
            self._startFileUploadWorkers()


            # Queue externally defined tasks
            with app.app_context():
                self._queueManualTasks()
                self._periodic_tasks()


            time.sleep(13)


    def reload_handler(self):
        logger.warning('Reconfiguring...')

        self._config_obj = IndiAllSkyConfig()

        # overwrite config
        self.config = self._config_obj.config


        if __config_level__ != self._config_obj.config_level:
            logger.error('indi-allsky version does not match config, please rerun setup.sh')

            self._miscDb.addNotification(
                NotificationCategory.STATE,
                'config_version',
                'WARNING: indi-allsky version does not match config, please rerun setup.sh',
                expire=timedelta(hours=2),
            )

            return


        # indicate newer config is loaded
        self._miscDb.setState('CONFIG_ID', self._config_obj.config_id)


    def _systemHealthCheck(self, task_state=TaskQueueState.QUEUED):
        # This will delete old images from the filesystem and DB
        jobdata = {
            'action' : 'systemHealthCheck',
            'kwargs' : {},
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=task_state,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.video_q.put({'task_id' : task.id})


    def dbImportImages(self):
        with app.app_context():
            self._dbImportImages()


    def _dbImportImages(self):
        try:
            IndiAllSkyDbCameraTable.query\
                .limit(1)\
                .one()

            logger.error('Imports may only be performed before the first camera is connected')
            sys.exit(1)

        except NoResultFound:
            # need to get camera info before adding to DB
            print('')
            print('')
            camera_name = input('Please enter the camera name: ')
            camera_metadata = {
                'type'        : constants.CAMERA,
                'name'        : camera_name.rstrip(),
                'driver'      : 'import',
                'latitude'    : 0.0,
                'longitude'   : 0.0,
                'elevation'   : 0,
                'alt'         : 0,
                'az'          : 0,
            }
            camera = self._miscDb.addCamera(camera_metadata)
            camera_id = camera.id


        file_list_videos = list()
        self._getFolderFilesByExt(self.image_dir, file_list_videos, extension_list=['mp4', 'webm'])


        ### Timelapse
        timelapse_videos_tl = filter(lambda p: 'timelapse' in p.name, file_list_videos)
        timelapse_videos = filter(lambda p: 'startrail' not in p.name, timelapse_videos_tl)  # exclude star trail timelapses

        # timelapse/20210915/allsky-timelapse_ccd1_20210915_night.mp4
        re_video = re.compile(r'(?P<dayDate_str>\d{8})\/.+timelapse_ccd(?P<ccd_id_str>\d+)_\d{8}_(?P<timeofday_str>[a-z]+)\.[a-z0-9]+$')

        video_entries = list()
        for f in timelapse_videos:
            #logger.info('Timelapse: %s', f)

            m = re.search(re_video, str(f))
            if not m:
                logger.error('Regex did not match file: %s', f)
                continue

            #logger.info('dayDate string: %s', m.group('dayDate_str'))
            #logger.info('Time of day string: %s', m.group('timeofday_str'))

            d_dayDate = datetime.strptime(m.group('dayDate_str'), '%Y%m%d').date()
            #logger.info('dayDate: %s', str(d_dayDate))

            if m.group('timeofday_str') == 'night':
                night = True
            else:
                night = False

            d_createDate = datetime.fromtimestamp(f.stat().st_mtime)

            video_dict = {
                'filename'   : str(f.relative_to(self.image_dir)),
                'success'    : True,
                'createDate' : d_createDate,
                'dayDate'    : d_dayDate,
                'dayDate_year'  : d_dayDate.year,
                'dayDate_month' : d_dayDate.month,
                'dayDate_day'   : d_dayDate.day,
                'night'      : night,
                'uploaded'   : False,
                'camera_id'  : camera_id,
            }

            video_entries.append(video_dict)


        try:
            db.session.bulk_insert_mappings(IndiAllSkyDbVideoTable, video_entries)
            db.session.commit()

            logger.warning('*** Timelapse videos inserted: %d ***', len(video_entries))
        except IntegrityError as e:
            logger.warning('Integrity error: %s', str(e))
            db.session.rollback()



        ### find all images
        file_list_images = list()
        self._getFolderFilesByExt(self.image_dir, file_list_images, extension_list=['jpg', 'jpeg', 'png', 'tif', 'tiff', 'webp'])


        ### Keograms
        file_list_keograms = filter(lambda p: 'keogram' in p.name, file_list_images)

        # timelapse/20210915/allsky-keogram_ccd1_20210915_night.jpg
        re_keogram = re.compile(r'(?P<dayDate_str>\d{8})\/.+keogram_ccd(?P<ccd_id_str>\d+)_\d{8}_(?P<timeofday_str>[a-z]+)\.[a-z]+$')

        keogram_entries = list()
        for f in file_list_keograms:
            #logger.info('Keogram: %s', f)

            m = re.search(re_keogram, str(f))
            if not m:
                logger.error('Regex did not match file: %s', f)
                continue

            #logger.info('dayDate string: %s', m.group('dayDate_str'))
            #logger.info('Time of day string: %s', m.group('timeofday_str'))

            d_dayDate = datetime.strptime(m.group('dayDate_str'), '%Y%m%d').date()
            #logger.info('dayDate: %s', str(d_dayDate))

            if m.group('timeofday_str') == 'night':
                night = True
            else:
                night = False

            d_createDate = datetime.fromtimestamp(f.stat().st_mtime)

            keogram_dict = {
                'filename'   : str(f.relative_to(self.image_dir)),
                'success'    : True,
                'createDate' : d_createDate,
                'dayDate'    : d_dayDate,
                'night'      : night,
                'uploaded'   : False,
                'camera_id'  : camera_id,
            }

            keogram_entries.append(keogram_dict)


        try:
            db.session.bulk_insert_mappings(IndiAllSkyDbKeogramTable, keogram_entries)
            db.session.commit()

            logger.warning('*** Keograms inserted: %d ***', len(keogram_entries))
        except IntegrityError as e:
            logger.warning('Integrity error: %s', str(e))
            db.session.rollback()


        ### Star trails
        file_list_startrail = filter(lambda p: 'startrail' in p.name, file_list_images)

        # timelapse/20210915/allsky-startrail_ccd1_20210915_night.jpg
        re_startrail = re.compile(r'(?P<dayDate_str>\d{8})\/.+startrail_ccd(?P<ccd_id_str>\d+)_\d{8}_(?P<timeofday_str>[a-z]+)\.[a-z]+$')

        startrail_entries = list()
        for f in file_list_startrail:
            #logger.info('Star trail: %s', f)

            m = re.search(re_startrail, str(f))
            if not m:
                logger.error('Regex did not match file: %s', f)
                continue

            #logger.info('dayDate string: %s', m.group('dayDate_str'))
            #logger.info('Time of day string: %s', m.group('timeofday_str'))

            d_dayDate = datetime.strptime(m.group('dayDate_str'), '%Y%m%d').date()
            #logger.info('dayDate: %s', str(d_dayDate))

            if m.group('timeofday_str') == 'night':
                night = True
            else:
                night = False

            d_createDate = datetime.fromtimestamp(f.stat().st_mtime)

            startrail_dict = {
                'filename'   : str(f.relative_to(self.image_dir)),
                'success'    : True,
                'createDate' : d_createDate,
                'dayDate'    : d_dayDate,
                'night'      : night,
                'uploaded'   : False,
                'camera_id'  : camera_id,
            }

            startrail_entries.append(startrail_dict)


        try:
            db.session.bulk_insert_mappings(IndiAllSkyDbStarTrailsTable, startrail_entries)
            db.session.commit()

            logger.warning('*** Star trails inserted: %d ***', len(startrail_entries))
        except IntegrityError as e:
            logger.warning('Integrity error: %s', str(e))
            db.session.rollback()


        ### Star trail Videos
        file_list_startrail_video_tl = filter(lambda p: 'timelapse' in p.name, file_list_videos)
        file_list_startrail_video = filter(lambda p: 'startrail' in p.name, file_list_startrail_video_tl)

        # timelapse/20210915/allsky-startrail_timelapse_ccd1_20210915_night.mp4
        re_startrail_video = re.compile(r'(?P<dayDate_str>\d{8})\/.+startrail_timelapse_ccd(?P<ccd_id_str>\d+)_\d{8}_(?P<timeofday_str>[a-z]+)\.[a-z0-9]+$')

        startrail_video_entries = list()
        for f in file_list_startrail_video:
            #logger.info('Star trail timelapse: %s', f)

            m = re.search(re_startrail_video, str(f))
            if not m:
                logger.error('Regex did not match file: %s', f)
                continue

            #logger.info('dayDate string: %s', m.group('dayDate_str'))
            #logger.info('Time of day string: %s', m.group('timeofday_str'))

            d_dayDate = datetime.strptime(m.group('dayDate_str'), '%Y%m%d').date()
            #logger.info('dayDate: %s', str(d_dayDate))

            if m.group('timeofday_str') == 'night':
                night = True
            else:
                night = False

            d_createDate = datetime.fromtimestamp(f.stat().st_mtime)

            startrail_video_dict = {
                'filename'   : str(f.relative_to(self.image_dir)),
                'success'    : True,
                'createDate' : d_createDate,
                'dayDate'    : d_dayDate,
                'night'      : night,
                'uploaded'   : False,
                'camera_id'  : camera_id,
            }

            startrail_video_entries.append(startrail_video_dict)


        try:
            db.session.bulk_insert_mappings(IndiAllSkyDbStarTrailsVideoTable, startrail_video_entries)
            db.session.commit()

            logger.warning('*** Star trail timelapses inserted: %d ***', len(startrail_video_entries))
        except IntegrityError as e:
            logger.warning('Integrity error: %s', str(e))
            db.session.rollback()


        ### Panorama Videos
        file_list_panorama_video_tl = filter(lambda p: 'timelapse' in p.name, file_list_videos)
        file_list_panorama_video = filter(lambda p: 'panorama' in p.name, file_list_panorama_video_tl)

        # timelapse/20210915/allsky-panorama_timelapse_ccd1_20210915_night.mp4
        re_panorama_video = re.compile(r'(?P<dayDate_str>\d{8})\/.+panorama_timelapse_ccd(?P<ccd_id_str>\d+)_\d{8}_(?P<timeofday_str>[a-z]+)\.[a-z0-9]+$')

        panorama_video_entries = list()
        for f in file_list_panorama_video:
            #logger.info('Panorama timelapse: %s', f)

            m = re.search(re_panorama_video, str(f))
            if not m:
                logger.error('Regex did not match file: %s', f)
                continue

            #logger.info('dayDate string: %s', m.group('dayDate_str'))
            #logger.info('Time of day string: %s', m.group('timeofday_str'))

            d_dayDate = datetime.strptime(m.group('dayDate_str'), '%Y%m%d').date()
            #logger.info('dayDate: %s', str(d_dayDate))

            if m.group('timeofday_str') == 'night':
                night = True
            else:
                night = False

            d_createDate = datetime.fromtimestamp(f.stat().st_mtime)

            panorama_video_dict = {
                'filename'   : str(f.relative_to(self.image_dir)),
                'success'    : True,
                'createDate' : d_createDate,
                'dayDate'    : d_dayDate,
                'night'      : night,
                'uploaded'   : False,
                'camera_id'  : camera_id,
            }

            panorama_video_entries.append(panorama_video_dict)


        try:
            db.session.bulk_insert_mappings(IndiAllSkyDbPanoramaVideoTable, panorama_video_entries)
            db.session.commit()

            logger.warning('*** Panorama timelapses inserted: %d ***', len(panorama_video_entries))
        except IntegrityError as e:
            logger.warning('Integrity error: %s', str(e))
            db.session.rollback()


        ### Images
        # Exclude keograms and star trails
        file_list_images_nok = filter(lambda p: 'keogram' not in p.name, file_list_images)
        file_list_images_nok_nost = filter(lambda p: 'startrail' not in p.name, file_list_images_nok)
        file_list_images_nok_nost_noraw = filter(lambda p: 'raw' not in p.name, file_list_images_nok_nost)
        file_list_images_nok_nost_noraw_nopan = filter(lambda p: 'panorama' not in p.name, file_list_images_nok_nost_noraw)
        file_list_images_nok_nost_noraw_nopan_nothumb = filter(lambda p: 'thumbnail' not in p.name, file_list_images_nok_nost_noraw_nopan)

        # exposures/20210825/night/26_02/ccd1_20210826_020202.jpg
        re_image = re.compile(r'(?P<dayDate_str>\d{8})\/(?P<timeofday_str>[a-z]+)\/\d{2}_\d{2}\/ccd(?P<ccd_id_str>\d+)_(?P<createDate_str>[0-9_]+)\.[a-z]+$')

        image_entries = list()
        for f in file_list_images_nok_nost_noraw_nopan_nothumb:
            #logger.info('Image: %s', f)

            m = re.search(re_image, str(f))
            if not m:
                logger.error('Regex did not match file: %s', f)
                continue

            #logger.info('dayDate string: %s', m.group('dayDate_str'))
            #logger.info('Time of day string: %s', m.group('timeofday_str'))
            #logger.info('createDate string: %s', m.group('createDate_str'))

            d_dayDate = datetime.strptime(m.group('dayDate_str'), '%Y%m%d').date()
            #logger.info('dayDate: %s', str(d_dayDate))

            if m.group('timeofday_str') == 'night':
                night = True
            else:
                night = False

            #d_createDate = datetime.strptime(m.group('createDate_str'), '%Y%m%d_%H%M%S')
            d_createDate = datetime.fromtimestamp(f.stat().st_mtime)
            #logger.info('createDate: %s', str(d_createDate))


            image_dict = {
                'filename'   : str(f.relative_to(self.image_dir)),
                'camera_id'  : camera_id,
                'createDate' : d_createDate,
                'createDate_year'   : d_createDate.year,
                'createDate_month'  : d_createDate.month,
                'createDate_day'    : d_createDate.day,
                'createDate_hour'   : d_createDate.hour,
                'dayDate'    : d_dayDate,
                'exposure'   : 0.0,
                'gain'       : -1,
                'binmode'    : 1,
                'night'      : night,
                'adu'        : 0.0,
                'stable'     : True,
                'moonmode'   : False,
                'adu_roi'    : False,
                'uploaded'   : False,
            }


            image_entries.append(image_dict)

        try:
            db.session.bulk_insert_mappings(IndiAllSkyDbImageTable, image_entries)
            db.session.commit()

            logger.warning('*** Images inserted: %d ***', len(image_entries))
        except IntegrityError as e:
            logger.warning('Integrity error: %s', str(e))
            db.session.rollback()


        ### Panorama images
        file_list_panorama_images = filter(lambda p: 'panoram' in p.name, file_list_images)

        # panoramas/20210825/night/26_02/panorama_ccd1_20210826_020202.jpg
        re_image = re.compile(r'(?P<dayDate_str>\d{8})\/(?P<timeofday_str>[a-z]+)\/\d{2}_\d{2}\/panorama_ccd(?P<ccd_id_str>\d+)_(?P<createDate_str>[0-9_]+)\.[a-z]+$')

        panorama_image_entries = list()
        for f in file_list_panorama_images:
            #logger.info('Image: %s', f)

            m = re.search(re_image, str(f))
            if not m:
                logger.error('Regex did not match file: %s', f)
                continue

            #logger.info('dayDate string: %s', m.group('dayDate_str'))
            #logger.info('Time of day string: %s', m.group('timeofday_str'))
            #logger.info('createDate string: %s', m.group('createDate_str'))

            d_dayDate = datetime.strptime(m.group('dayDate_str'), '%Y%m%d').date()
            #logger.info('dayDate: %s', str(d_dayDate))

            if m.group('timeofday_str') == 'night':
                night = True
            else:
                night = False

            #d_createDate = datetime.strptime(m.group('createDate_str'), '%Y%m%d_%H%M%S')
            d_createDate = datetime.fromtimestamp(f.stat().st_mtime)
            #logger.info('createDate: %s', str(d_createDate))


            panorama_image_dict = {
                'filename'   : str(f.relative_to(self.image_dir)),
                'camera_id'  : camera_id,
                'createDate' : d_createDate,
                'createDate_year'   : d_createDate.year,
                'createDate_month'  : d_createDate.month,
                'createDate_day'    : d_createDate.day,
                'createDate_hour'   : d_createDate.hour,
                'dayDate'    : d_dayDate,
                'exposure'   : 0.0,
                'gain'       : -1,
                'binmode'    : 1,
                'night'      : night,
                'uploaded'   : False,
            }


            panorama_image_entries.append(panorama_image_dict)

        try:
            db.session.bulk_insert_mappings(IndiAllSkyDbPanoramaImageTable, panorama_image_entries)
            db.session.commit()

            logger.warning('*** Panorama images inserted: %d ***', len(panorama_image_entries))
        except IntegrityError as e:
            logger.warning('Integrity error: %s', str(e))
            db.session.rollback()


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


    def _expireOrphanedTasks(self):
        orphaned_statuses = (
            TaskQueueState.MANUAL,
            TaskQueueState.QUEUED,
            TaskQueueState.RUNNING,
        )

        old_task_list = IndiAllSkyDbTaskQueueTable.query\
            .filter(IndiAllSkyDbTaskQueueTable.state.in_(orphaned_statuses))

        for task in old_task_list:
            logger.warning('Expiring orphaned task %d', task.id)
            task.state = TaskQueueState.EXPIRED

        db.session.commit()


    def _flushOldTasks(self):
        now_minus_3d = datetime.now() - timedelta(days=3)

        flush_old_tasks = IndiAllSkyDbTaskQueueTable.query\
            .filter(IndiAllSkyDbTaskQueueTable.createDate < now_minus_3d)

        logger.warning('Found %d expired tasks to delete', flush_old_tasks.count())
        flush_old_tasks.delete()
        db.session.commit()


    def _queueManualTasks(self):
        #logger.info('Checking for manually submitted tasks')
        manual_tasks = IndiAllSkyDbTaskQueueTable.query\
            .filter(IndiAllSkyDbTaskQueueTable.state == TaskQueueState.MANUAL)\
            .filter(
                or_(
                    IndiAllSkyDbTaskQueueTable.queue == TaskQueueQueue.MAIN,
                    IndiAllSkyDbTaskQueueTable.queue == TaskQueueQueue.VIDEO,
                    IndiAllSkyDbTaskQueueTable.queue == TaskQueueQueue.UPLOAD,
                )
            )\
            .order_by(
                IndiAllSkyDbTaskQueueTable.priority.asc(),  # lower value, higher priority
                IndiAllSkyDbTaskQueueTable.createDate.asc(),
            )


        reload_received = False
        pause_received = False

        for task in manual_tasks:
            if task.queue == TaskQueueQueue.VIDEO:
                logger.info('Queuing manual video task %d', task.id)
                task.setQueued()
                self.video_q.put({'task_id' : task.id})

            elif task.queue == TaskQueueQueue.UPLOAD:
                logger.info('Queuing manual upload task %d', task.id)
                task.setQueued()
                self.upload_q.put({'task_id' : task.id})

            elif task.queue == TaskQueueQueue.MAIN:
                logger.info('Picked up MAIN task')

                action = task.data['action']

                if action == 'reload':
                    if reload_received:
                        logger.warning('Skipping duplicate reload signal')
                        task.setExpired()
                        continue

                    logger.warning('Reload initiated')

                    reload_received = True
                    self._reload = True

                    task.setSuccess('Reloaded indi-allsky process')

                elif action == 'settime':
                    self.update_time_offset = task.data['time_offset']
                    logger.info('Set time offset: %ds', int(self.update_time_offset))

                    self.capture_q.put({
                        'settime' : int(self.update_time_offset),
                    })

                    task.setSuccess('Set time queued')

                elif action == 'setlocation':
                    logger.info('Set location initiated')

                    camera_id = task.data['camera_id']
                    latitude = task.data['latitude']
                    longitude = task.data['longitude']
                    elevation = task.data['elevation']

                    self.updateConfigLocation(latitude, longitude, elevation, camera_id)

                    task.setSuccess('Updated config location')

                elif action == 'setpaused':
                    if pause_received:
                        logger.warning('Skipping duplicate pause action')
                        task.setExpired()
                        continue

                    logger.info('Set paused/unpaused')

                    pause = task.data['pause']

                    self.updateConfigPaused(pause)

                    pause_received = True
                    self._reload = True

                    task.setSuccess('Updated paused status')

                else:
                    logger.error('Unknown action: %s', action)
                    task.setFailed()

            else:
                logger.error('Unmanaged queue %s', task.queue.name)
                task.setFailed()


    def _periodic_tasks(self):

        # Tasks that need to be run periodically
        now = time.time()

        if self.periodic_tasks_time > now:
            return

        # set next reconfigure time
        self.periodic_tasks_time = now + self.periodic_tasks_offset

        logger.warning('Periodic tasks triggered')


        # cleanup data
        if self.cleanup_tasks_time < now:
            self.cleanup_tasks_time = now + self.cleanup_tasks_offset

            self._flushOldTasks()
            self._systemHealthCheck()


        # aurora data update
        if self.aurora_tasks_time < now:
            self.aurora_tasks_time = now + self.aurora_tasks_offset

            logger.info('Creating aurora update task')
            self._updateAuroraData()


        # smoke data update
        if self.smoke_tasks_time < now:
            self.smoke_tasks_time = now + self.smoke_tasks_offset

            logger.info('Creating smoke update task')
            self._updateSmokeData()


        # satellite tle data update
        if self.sat_data_tasks_time < now:
            self.sat_data_tasks_time = now + self.smoke_tasks_offset

            logger.info('Creating satellite tle data update task')
            self._updateSatelliteTleData()


    def _updateAuroraData(self, task_state=TaskQueueState.QUEUED):

        active_cameras = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.hidden == sa_false())\
            .order_by(IndiAllSkyDbCameraTable.id.desc())


        for camera in active_cameras:
            jobdata = {
                'action' : 'updateAuroraData',
                'kwargs' : {
                    'camera_id' : camera.id,
                },
            }

            task = IndiAllSkyDbTaskQueueTable(
                queue=TaskQueueQueue.VIDEO,
                state=task_state,
                data=jobdata,
            )
            db.session.add(task)
            db.session.commit()

            self.video_q.put({'task_id' : task.id})


    def _updateSmokeData(self, task_state=TaskQueueState.QUEUED):

        active_cameras = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.hidden == sa_false())\
            .order_by(IndiAllSkyDbCameraTable.id.desc())


        for camera in active_cameras:
            jobdata = {
                'action' : 'updateSmokeData',
                'kwargs' : {
                    'camera_id' : camera.id,
                },
            }

            task = IndiAllSkyDbTaskQueueTable(
                queue=TaskQueueQueue.VIDEO,
                state=task_state,
                data=jobdata,
            )
            db.session.add(task)
            db.session.commit()

            self.video_q.put({'task_id' : task.id})


    def _updateSatelliteTleData(self, task_state=TaskQueueState.QUEUED):
        jobdata = {
            'action' : 'updateSatelliteTleData',
            'kwargs' : {},
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=task_state,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.video_q.put({'task_id' : task.id})


    def updateConfigLocation(self, latitude, longitude, elevation, camera_id):
        logger.warning('Updating indi-allsky config with new geographic location')

        self.config['LOCATION_LATITUDE'] = round(float(latitude), 4)
        self.config['LOCATION_LONGITUDE'] = round(float(longitude), 4)
        self.config['LOCATION_ELEVATION'] = int(elevation)


        # save new config
        try:
            self._config_obj.save('system', '*Auto* Location updated')
            logger.info('Wrote new config')
        except ConfigSaveException:
            return


        #logger.info('Updating camera %d location %0.2f, %0.2f', camera_id, self.config['LOCATION_LATITUDE'], self.config['LOCATION_LONGITUDE'])
        try:
            camera = IndiAllSkyDbCameraTable.query\
                .filter(IndiAllSkyDbCameraTable.id == camera_id)\
                .one()

            camera.latitude = float(self.config['LOCATION_LATITUDE'])
            camera.longitude = float(self.config['LOCATION_LONGITUDE'])
            camera.elevation = int(self.config['LOCATION_ELEVATION'])

            db.session.commit()

        except NoResultFound:
            logger.error('Camera ID %d not found', camera_id)


    def updateConfigPaused(self, pause):
        if pause:
            logger.warning('Pausing capture')
        else:
            logger.warning('Unpausing capture')

        self.config['CAPTURE_PAUSE'] = bool(pause)

        # save new config
        try:
            self._config_obj.save('system', '*Auto* Pause/Unpause Capture')
            logger.info('Wrote new config')
        except ConfigSaveException:
            return

