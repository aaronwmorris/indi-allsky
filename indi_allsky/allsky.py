import platform
import sys
import os
import time
import io
import json
import re
import psutil
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime
from datetime import timedelta
from datetime import timezone
#from pprint import pformat
import math
import dbus
import signal
import logging

import ephem

import queue
from multiprocessing import Queue
from multiprocessing import Value

from .version import __version__
from .version import __config_level__

from .config import IndiAllSkyConfig

from . import camera as camera_module

from . import constants

from .image import ImageWorker
from .video import VideoWorker
from .uploader import FileUploader

from .exceptions import TimeOutException
from .exceptions import TemperatureException
from .exceptions import CameraException
from .exceptions import ConfigSaveException

from .flask import create_app
from .flask import db
from .flask.miscDb import miscDb

from .flask.models import TaskQueueQueue
from .flask.models import TaskQueueState
from .flask.models import NotificationCategory

from .flask.models import IndiAllSkyDbCameraTable
from .flask.models import IndiAllSkyDbImageTable
from .flask.models import IndiAllSkyDbDarkFrameTable
from .flask.models import IndiAllSkyDbBadPixelMapTable
from .flask.models import IndiAllSkyDbVideoTable
from .flask.models import IndiAllSkyDbKeogramTable
from .flask.models import IndiAllSkyDbStarTrailsTable
from .flask.models import IndiAllSkyDbStarTrailsVideoTable
from .flask.models import IndiAllSkyDbTaskQueueTable

from sqlalchemy import or_
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.exc import IntegrityError


app = create_app()

logger = logging.getLogger('indi_allsky')


class IndiAllSky(object):

    periodic_tasks_offset = 180.0  # 3 minutes


    def __init__(self):
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

        self.indiclient = None

        self.latitude_v = Value('f', float(self.config['LOCATION_LATITUDE']))
        self.longitude_v = Value('f', float(self.config['LOCATION_LONGITUDE']))

        self.ra_v = Value('f', 0.0)
        self.dec_v = Value('f', 0.0)

        self.exposure_v = Value('f', -1.0)
        self.gain_v = Value('i', -1)  # value set in CCD config
        self.bin_v = Value('i', 1)  # set 1 for sane default
        self.sensortemp_v = Value('f', 0)
        self.night_v = Value('i', -1)  # bogus initial value
        self.night = None
        self.moonmode_v = Value('i', -1)  # bogus initial value
        self.moonmode = None

        self.camera_id = None
        self.camera_name = None
        self.camera_server = None

        self.focus_mode = self.config.get('FOCUS_MODE', False)  # focus mode takes images as fast as possible

        self.night_sun_radians = math.radians(self.config['NIGHT_SUN_ALT_DEG'])
        self.night_moonmode_radians = math.radians(self.config['NIGHT_MOONMODE_ALT_DEG'])

        self.image_q = Queue()
        self.image_error_q = Queue()
        self.image_worker = None
        self.image_worker_idx = 0

        self.video_q = Queue()
        self.video_error_q = Queue()
        self.video_worker = None
        self.video_worker_idx = 0

        self.upload_q = Queue()
        self.upload_worker_list = []
        self.upload_worker_idx = 0

        for x in range(self.config.get('UPLOAD_WORKERS', 1)):
            self.upload_worker_list.append({
                'worker'  : None,
                'error_q' : Queue(),
            })


        self.periodic_tasks_time = time.time() + self.periodic_tasks_offset


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
        logger.warning('Caught HUP signal, reconfiguring')

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


        self._miscDb.setState('CONFIG_ID', self._config_obj.config_id)


        # Update shared values
        self.night_sun_radians = math.radians(self.config['NIGHT_SUN_ALT_DEG'])
        self.night_moonmode_radians = math.radians(self.config['NIGHT_MOONMODE_ALT_DEG'])

        with self.latitude_v.get_lock():
            self.latitude_v.value = float(self.config['LOCATION_LATITUDE'])

        with self.longitude_v.get_lock():
            self.longitude_v.value = float(self.config['LOCATION_LONGITUDE'])


        # reconfigure if needed
        self.reconfigureCcd()

        # add driver name to config
        self.camera_name = self.indiclient.ccd_device.getDeviceName()
        self._miscDb.setState('CAMERA_NAME', self.camera_name)

        self.camera_server = self.indiclient.ccd_device.getDriverExec()
        self._miscDb.setState('CAMERA_SERVER', self.camera_server)


        ### Telescope config
        # park the telescope at zenith
        if self.indiclient.telescope_device:
            telescope_config = {
                'SWITCHES' : {},
                'PROPERTIES' : {
                    'GEOGRAPHIC_COORD' : {
                        'LAT' : self.latitude_v.value,
                        'LONG' : self.longitude_v.value,
                    },
                },
            }

            self.indiclient.configureTelescopeDevice(telescope_config)

            self.reparkTelescope()


        # configuration needs to be performed before getting CCD_INFO
        # which queries the exposure control
        self.indiclient.configureCcdDevice(self.config['INDI_CONFIG_DEFAULTS'])


        # Get Properties
        #ccd_properties = self.indiclient.getCcdDeviceProperties()


        # get CCD information
        ccd_info = self.indiclient.getCcdInfo()


        if self.config.get('CFA_PATTERN'):
            cfa_pattern = self.config['CFA_PATTERN']
        else:
            cfa_pattern = ccd_info['CCD_CFA']['CFA_TYPE'].get('text')


        # need to get camera info before adding to DB
        camera_metadata = {
            'name'        : self.camera_name,

            'minExposure' : float(ccd_info.get('CCD_EXPOSURE', {}).get('CCD_EXPOSURE_VALUE', {}).get('min')),
            'maxExposure' : float(ccd_info.get('CCD_EXPOSURE', {}).get('CCD_EXPOSURE_VALUE', {}).get('max')),
            'minGain'     : int(ccd_info.get('GAIN_INFO', {}).get('min')),
            'maxGain'     : int(ccd_info.get('GAIN_INFO', {}).get('max')),
            'width'       : int(ccd_info.get('CCD_FRAME', {}).get('WIDTH', {}).get('max')),
            'height'      : int(ccd_info.get('CCD_FRAME', {}).get('HEIGHT', {}).get('max')),
            'bits'        : int(ccd_info.get('CCD_INFO', {}).get('CCD_BITSPERPIXEL', {}).get('current')),
            'pixelSize'   : float(ccd_info.get('CCD_INFO', {}).get('CCD_PIXEL_SIZE', {}).get('current')),
            'cfa'         : constants.CFA_STR_MAP[cfa_pattern],

            'location'    : self.config['LOCATION_NAME'],
            'latitude'    : self.latitude_v.value,
            'longitude'   : self.longitude_v.value,

            'lensName'        : self.config['LENS_NAME'],
            'lensFocalLength' : self.config['LENS_FOCAL_LENGTH'],
            'lensFocalRatio'  : self.config['LENS_FOCAL_RATIO'],
            'alt'             : self.config['LENS_ALTITUDE'],
            'az'              : self.config['LENS_AZIMUTH'],
            'nightSunAlt'     : self.config['NIGHT_SUN_ALT_DEG'],
        }

        camera = self._miscDb.addCamera(camera_metadata)
        self.camera_id = camera.id

        self.indiclient.camera_id = camera.id

        self._miscDb.setState('DB_CAMERA_ID', camera.id)


        self._sync_camera(camera, camera_metadata)


        # Update focus mode
        self.focus_mode = self.config.get('FOCUS_MODE', False)

        # set minimum exposure
        ccd_min_exp = ccd_info['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['min']

        # Some CCD drivers will not accept their stated minimum exposure.
        # There might be some python -> C floating point conversion problem causing this.
        ccd_min_exp = ccd_min_exp + 0.00000001

        if not self.config.get('CCD_EXPOSURE_MIN'):
            logger.warning('Setting minimum to %0.8f', ccd_min_exp)
            self.config['CCD_EXPOSURE_MIN'] = ccd_min_exp
        elif self.config.get('CCD_EXPOSURE_MIN') < ccd_min_exp:
            logger.warning(
                'Minimum exposure %0.8f too low, increasing to %0.8f',
                self.config.get('CCD_EXPOSURE_MIN'),
                ccd_min_exp,
            )
            self.config['CCD_EXPOSURE_MIN'] = ccd_min_exp

        logger.info('Minimum CCD exposure: %0.8f', self.config['CCD_EXPOSURE_MIN'])


        # Validate gain settings
        ccd_min_gain = ccd_info['GAIN_INFO']['min']
        ccd_max_gain = ccd_info['GAIN_INFO']['max']

        if self.config['CCD_CONFIG']['NIGHT']['GAIN'] < ccd_min_gain:
            logger.error('CCD night gain below minimum, changing to %d', int(ccd_min_gain))
            self.config['CCD_CONFIG']['NIGHT']['GAIN'] = int(ccd_min_gain)
        elif self.config['CCD_CONFIG']['NIGHT']['GAIN'] > ccd_max_gain:
            logger.error('CCD night gain above maximum, changing to %d', int(ccd_max_gain))
            self.config['CCD_CONFIG']['NIGHT']['GAIN'] = int(ccd_max_gain)

        if self.config['CCD_CONFIG']['MOONMODE']['GAIN'] < ccd_min_gain:
            logger.error('CCD moon mode gain below minimum, changing to %d', int(ccd_min_gain))
            self.config['CCD_CONFIG']['MOONMODE']['GAIN'] = int(ccd_min_gain)
        elif self.config['CCD_CONFIG']['MOONMODE']['GAIN'] > ccd_max_gain:
            logger.error('CCD moon mode gain above maximum, changing to %d', int(ccd_max_gain))
            self.config['CCD_CONFIG']['MOONMODE']['GAIN'] = int(ccd_max_gain)

        if self.config['CCD_CONFIG']['DAY']['GAIN'] < ccd_min_gain:
            logger.error('CCD day gain below minimum, changing to %d', int(ccd_min_gain))
            self.config['CCD_CONFIG']['DAY']['GAIN'] = int(ccd_min_gain)
        elif self.config['CCD_CONFIG']['DAY']['GAIN'] > ccd_max_gain:
            logger.error('CCD day gain above maximum, changing to %d', int(ccd_max_gain))
            self.config['CCD_CONFIG']['DAY']['GAIN'] = int(ccd_max_gain)


        # set flag for program to restart processes
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

        self._miscDb.setState('PID', pid)
        self._miscDb.setState('PID_FILE', self.pid_file)


    def _initialize(self, connectOnly=False):
        logger.info('indi-allsky release: %s', str(__version__))
        logger.info('indi-allsky config level: %s', str(__config_level__))

        logger.info('Python version: %s', platform.python_version())
        logger.info('Platform: %s', platform.machine())

        logger.info('System CPUs: %d', psutil.cpu_count())

        memory_info = psutil.virtual_memory()
        memory_total_mb = int(memory_info[0] / 1024.0 / 1024.0)

        logger.info('System memory: %d MB', memory_total_mb)

        uptime_s = time.time() - psutil.boot_time()
        logger.info('System uptime: %ds', uptime_s)


        camera_interface = getattr(camera_module, self.config.get('CAMERA_INTERFACE', 'indi'))

        # instantiate the client
        self.indiclient = camera_interface(
            self.config,
            self.image_q,
            self.latitude_v,
            self.longitude_v,
            self.ra_v,
            self.dec_v,
            self.gain_v,
            self.bin_v,
        )

        # set indi server localhost and port
        self.indiclient.setServer(self.config['INDI_SERVER'], self.config['INDI_PORT'])

        # connect to indi server
        logger.info("Connecting to indiserver")
        if not self.indiclient.connectServer():
            host = self.indiclient.getHost()
            port = self.indiclient.getPort()

            logger.error("No indiserver available at %s:%d", host, port)

            self._miscDb.addNotification(
                NotificationCategory.GENERAL,
                'no_indiserver',
                'Unable to connect to indiserver at {0:s}:{1:d}'.format(host, port),
                expire=timedelta(hours=2),
            )

            sys.exit(1)

        # give devices a chance to register
        time.sleep(8)

        try:
            self.indiclient.findCcd(camera_name=self.config.get('INDI_CAMERA_NAME'))
        except CameraException as e:
            logger.error('Camera error: %s', str(e))

            self._miscDb.addNotification(
                NotificationCategory.CAMERA,
                'no_camera',
                'Camera was not detected.',
                expire=timedelta(hours=2),
            )

            time.sleep(1)
            sys.exit(1)


        self.indiclient.findTelescope(telescope_name='Telescope Simulator')
        self.indiclient.findGps()

        logger.warning('Connecting to CCD device %s', self.indiclient.ccd_device.getDeviceName())
        self.indiclient.connectDevice(self.indiclient.ccd_device.getDeviceName())

        if self.indiclient.telescope_device:
            logger.warning('Connecting to Telescope device %s', self.indiclient.telescope_device.getDeviceName())
            self.indiclient.connectDevice(self.indiclient.telescope_device.getDeviceName())

        if self.indiclient.gps_device:
            logger.warning('Connecting to GPS device %s', self.indiclient.gps_device.getDeviceName())
            self.indiclient.connectDevice(self.indiclient.gps_device.getDeviceName())


        if connectOnly:
            return


        # add driver name to config
        self.camera_name = self.indiclient.ccd_device.getDeviceName()
        self._miscDb.setState('CAMERA_NAME', self.camera_name)

        self.camera_server = self.indiclient.ccd_device.getDriverExec()
        self._miscDb.setState('CAMERA_SERVER', self.camera_server)


        ### GPS config
        if self.indiclient.gps_device:
            gps_config = {
                'PROPERTIES' : {
                    'GPS_REFRESH_PERIOD' : {
                        'PERIOD' : 293,  # prime number
                    },
                },
            }

            self.indiclient.configureGpsDevice(gps_config)
            self.indiclient.refreshGps()


            # GPSD simulation
            #sim_gps_config = {
            #    'SWITCHES' : {
            #        'SIMULATION' : {
            #            'on'  : ['ENABLE'],
            #            'off' : ['DISABLE'],
            #        },
            #    },
            #    'PROPERTIES' : {
            #        'SIM_GEOGRAPHIC_COORD' : {  # rio
            #            'SIM_LAT'  : -22,  # requires integers
            #            'SIM_LONG' : 317,
            #            'SIM_ELEV' : 7,
            #        },
            #    },
            #}

            #self.indiclient.configureGpsDevice(sim_gps_config)



        ### Telescope config
        # park the telescope at zenith and stop tracking
        if self.indiclient.telescope_device:
            telescope_config = {
                'SWITCHES' : {
                    'TELESCOPE_SLEW_RATE' : {
                        'on' : ['4x'],  # zoom zoom
                    },
                    'TELESCOPE_TRACK_STATE' : {
                        'on'  : ['TRACK_OFF'],
                        'off' : ['TRACK_ON'],
                    },
                },
                'PROPERTIES' : {
                    'GEOGRAPHIC_COORD' : {
                        'LAT' : self.latitude_v.value,
                        'LONG' : self.longitude_v.value,
                    },
                    'TELESCOPE_INFO' : {
                        'TELESCOPE_APERTURE' : 10,
                        'TELESCOPE_FOCAL_LENGTH' : 10,
                    },
                },
                'TEXT' : {
                    'SCOPE_CONFIG_NAME' : {
                        'SCOPE_CONFIG_NAME' : 'indi-allsky',
                    },
                },
            }

            self.indiclient.configureTelescopeDevice(telescope_config)

            self.reparkTelescope()



        if self.indiclient.telescope_device and self.indiclient.gps_device:
            # Set Telescope GPS
            self.indiclient.setTelescopeGps(self.indiclient.gps_device.getDeviceName())


        # configuration needs to be performed before getting CCD_INFO
        # which queries the exposure control
        self.indiclient.configureCcdDevice(self.config['INDI_CONFIG_DEFAULTS'])


        # Get Properties
        #ccd_properties = self.indiclient.getCcdDeviceProperties()


        # get CCD information
        ccd_info = self.indiclient.getCcdInfo()


        if self.config.get('CFA_PATTERN'):
            cfa_pattern = self.config['CFA_PATTERN']
        else:
            cfa_pattern = ccd_info['CCD_CFA']['CFA_TYPE'].get('text')


        # need to get camera info before adding to DB
        camera_metadata = {
            'name'        : self.camera_name,

            'minExposure' : float(ccd_info.get('CCD_EXPOSURE', {}).get('CCD_EXPOSURE_VALUE', {}).get('min')),
            'maxExposure' : float(ccd_info.get('CCD_EXPOSURE', {}).get('CCD_EXPOSURE_VALUE', {}).get('max')),
            'minGain'     : int(ccd_info.get('GAIN_INFO', {}).get('min')),
            'maxGain'     : int(ccd_info.get('GAIN_INFO', {}).get('max')),
            'width'       : int(ccd_info.get('CCD_FRAME', {}).get('WIDTH', {}).get('max')),
            'height'      : int(ccd_info.get('CCD_FRAME', {}).get('HEIGHT', {}).get('max')),
            'bits'        : int(ccd_info.get('CCD_INFO', {}).get('CCD_BITSPERPIXEL', {}).get('current')),
            'pixelSize'   : float(ccd_info.get('CCD_INFO', {}).get('CCD_PIXEL_SIZE', {}).get('current')),
            'cfa'         : constants.CFA_STR_MAP[cfa_pattern],

            'location'    : self.config['LOCATION_NAME'],
            'latitude'    : self.latitude_v.value,
            'longitude'   : self.longitude_v.value,

            'lensName'        : self.config['LENS_NAME'],
            'lensFocalLength' : self.config['LENS_FOCAL_LENGTH'],
            'lensFocalRatio'  : self.config['LENS_FOCAL_RATIO'],
            'alt'             : self.config['LENS_ALTITUDE'],
            'az'              : self.config['LENS_AZIMUTH'],
            'nightSunAlt'     : self.config['NIGHT_SUN_ALT_DEG'],
        }

        camera = self._miscDb.addCamera(camera_metadata)
        self.camera_id = camera.id

        self.indiclient.camera_id = camera.id

        self._miscDb.setState('DB_CAMERA_ID', camera.id)


        self._sync_camera(camera, camera_metadata)


        # Disable debugging
        self.indiclient.disableDebugCcd()


        # set BLOB mode to BLOB_ALSO
        self.indiclient.updateCcdBlobMode()


        try:
            self.indiclient.setCcdFrameType('FRAME_LIGHT')  # default frame type is light
        except TimeOutException:
            # this is an optional step
            # occasionally the CCD_FRAME_TYPE property is not available during initialization
            logger.warning('Unable to set CCD_FRAME_TYPE to Light')


        # save config to defaults (disabled)
        #self.indiclient.saveCcdConfig()


        # set minimum exposure
        ccd_min_exp = ccd_info['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['min']

        # Some CCD drivers will not accept their stated minimum exposure.
        # There might be some python -> C floating point conversion problem causing this.
        ccd_min_exp = ccd_min_exp + 0.00000001

        if not self.config.get('CCD_EXPOSURE_MIN'):
            self.config['CCD_EXPOSURE_MIN'] = ccd_min_exp
        elif self.config.get('CCD_EXPOSURE_MIN') < ccd_min_exp:
            logger.warning(
                'Minimum exposure %0.8f too low, increasing to %0.8f',
                self.config.get('CCD_EXPOSURE_MIN'),
                ccd_min_exp,
            )
            self.config['CCD_EXPOSURE_MIN'] = ccd_min_exp

        logger.info('Minimum CCD exposure: %0.8f', self.config['CCD_EXPOSURE_MIN'])


        # set default exposure
        #
        # Note:  I have tried setting a default exposure of 1.0s which works fine for night time, but
        #        during the day weird things can happen when the image sensor is completely oversaturated.
        #        Instead of an all white image, you can get intermediate pixel values which confuses the
        #        exposure detection algorithm
        if not self.config.get('CCD_EXPOSURE_DEF'):
            self.config['CCD_EXPOSURE_DEF'] = self.config['CCD_EXPOSURE_MIN']

        with self.exposure_v.get_lock():
            self.exposure_v.value = self.config['CCD_EXPOSURE_DEF']

        logger.info('Default CCD exposure: {0:0.8f}'.format(self.config['CCD_EXPOSURE_DEF']))


        # Validate gain settings
        ccd_min_gain = ccd_info['GAIN_INFO']['min']
        ccd_max_gain = ccd_info['GAIN_INFO']['max']

        if self.config['CCD_CONFIG']['NIGHT']['GAIN'] < ccd_min_gain:
            logger.error('CCD night gain below minimum, changing to %d', int(ccd_min_gain))
            self.config['CCD_CONFIG']['NIGHT']['GAIN'] = int(ccd_min_gain)
            time.sleep(3)
        elif self.config['CCD_CONFIG']['NIGHT']['GAIN'] > ccd_max_gain:
            logger.error('CCD night gain above maximum, changing to %d', int(ccd_max_gain))
            self.config['CCD_CONFIG']['NIGHT']['GAIN'] = int(ccd_max_gain)
            time.sleep(3)

        if self.config['CCD_CONFIG']['MOONMODE']['GAIN'] < ccd_min_gain:
            logger.error('CCD moon mode gain below minimum, changing to %d', int(ccd_min_gain))
            self.config['CCD_CONFIG']['MOONMODE']['GAIN'] = int(ccd_min_gain)
            time.sleep(3)
        elif self.config['CCD_CONFIG']['MOONMODE']['GAIN'] > ccd_max_gain:
            logger.error('CCD moon mode gain above maximum, changing to %d', int(ccd_max_gain))
            self.config['CCD_CONFIG']['MOONMODE']['GAIN'] = int(ccd_max_gain)
            time.sleep(3)

        if self.config['CCD_CONFIG']['DAY']['GAIN'] < ccd_min_gain:
            logger.error('CCD day gain below minimum, changing to %d', int(ccd_min_gain))
            self.config['CCD_CONFIG']['DAY']['GAIN'] = int(ccd_min_gain)
            time.sleep(3)
        elif self.config['CCD_CONFIG']['DAY']['GAIN'] > ccd_max_gain:
            logger.error('CCD day gain above maximum, changing to %d', int(ccd_max_gain))
            self.config['CCD_CONFIG']['DAY']['GAIN'] = int(ccd_max_gain)
            time.sleep(3)


    def _sync_camera(self, camera, camera_metadata):
        ### sync camera
        if not self.config.get('SYNCAPI', {}).get('ENABLE'):
            return


        camera_metadata['uuid'] = camera.uuid
        camera_metadata['type'] = constants.CAMERA

        # tell worker to upload file
        jobdata = {
            'action'      : constants.TRANSFER_SYNC_V1,
            'model'       : camera.__class__.__name__,
            'id'          : camera.id,
            'metadata'    : camera_metadata,
        }

        upload_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(upload_task)
        db.session.commit()

        self.upload_q.put({'task_id' : upload_task.id})


    def _startImageWorker(self):
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

        logger.info('Starting ImageWorker process %d', self.image_worker_idx)
        self.image_worker = ImageWorker(
            self.image_worker_idx,
            self.config,
            self.image_error_q,
            self.image_q,
            self.upload_q,
            self.latitude_v,
            self.longitude_v,
            self.ra_v,
            self.dec_v,
            self.exposure_v,
            self.gain_v,
            self.bin_v,
            self.sensortemp_v,
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
                    'WARNING: ImageWorker was restarted more than 10 times',
                    expire=timedelta(hours=2),
                )


    def _stopImageWorker(self, terminate=False):
        if not self.image_worker:
            return

        if not self.image_worker.is_alive():
            return

        if terminate:
            logger.info('Terminating ImageWorker process')
            self.image_worker.terminate()

        logger.info('Stopping ImageWorker process')

        self.image_q.put({'stop' : True})
        self.image_worker.join()


    def _startVideoWorker(self):
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

        logger.info('Starting VideoWorker process %d', self.video_worker_idx)
        self.video_worker = VideoWorker(
            self.video_worker_idx,
            self.config,
            self.video_error_q,
            self.video_q,
            self.upload_q,
            self.latitude_v,
            self.longitude_v,
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


    def _stopVideoWorker(self, terminate=False):
        if not self.video_worker:
            return

        if not self.video_worker.is_alive():
            return

        if terminate:
            logger.info('Terminating VideoWorker process')
            self.video_worker.terminate()

        logger.info('Stopping VideoWorker process')

        self.video_q.put({'stop' : True})
        self.video_worker.join()


    def _startFileUploadWorkers(self):
        for upload_worker_dict in self.upload_worker_list:
            self._fileUploadWorkerStart(upload_worker_dict)


    def _fileUploadWorkerStart(self, uw_dict):
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

        logger.info('Starting FileUploader process %d', self.upload_worker_idx)
        uw_dict['worker'] = FileUploader(
            self.upload_worker_idx,
            self.config,
            uw_dict['error_q'],
            self.upload_q,
        )

        uw_dict['worker'].start()


        if self.upload_worker_idx % 10 == 0:
            # notify if worker is restarted more than 10 times
            with app.app_context():
                self._miscDb.addNotification(
                    NotificationCategory.WORKER,
                    'FileUploader',
                    'WARNING: FileUploader was restarted more than 10 times',
                    expire=timedelta(hours=2),
                )


    def _stopFileUploadWorkers(self, terminate=False):
        active_worker_list = list()
        for upload_worker_dict in self.upload_worker_list:
            if not upload_worker_dict['worker']:
                continue

            if not upload_worker_dict['worker'].is_alive():
                continue

            active_worker_list.append(upload_worker_dict)

            # need to put the stops in the queue before waiting on workers to join
            self.upload_q.put({'stop' : True})


        for upload_worker_dict in active_worker_list:
            self._fileUploadWorkerStop(upload_worker_dict, terminate=terminate)


    def _fileUploadWorkerStop(self, uw_dict, terminate=False):
        if terminate:
            logger.info('Terminating FileUploadWorker process')
            uw_dict['worker'].terminate()

        logger.info('Stopping FileUploadWorker process')

        uw_dict['worker'].join()


    def _pre_run_tasks(self):
        # Tasks that need to be run before the main program loop
        now = time.time()

        self._systemHealthCheck()


        # Update watchdog
        self._miscDb.setState('WATCHDOG', int(now))


        if self.config.get('GPS_TIMESYNC'):
            self.validateGpsTime()


        if self.camera_server in ['indi_rpicam']:
            # Raspberry PI HQ Camera requires an initial throw away exposure of over 6s
            # in order to take exposures longer than 7s
            logger.info('Taking throw away exposure for rpicam')
            self.shoot(7.0, sync=True, timeout=20.0)


    def periodic_tasks(self):
        # Tasks that need to be run periodically
        now = time.time()

        if self.periodic_tasks_time > now:
            return

        # set next reconfigure time
        self.periodic_tasks_time = now + self.periodic_tasks_offset

        logger.warning('Periodic tasks triggered')


        # Update watchdog
        self._miscDb.setState('WATCHDOG', int(now))


        if self.config.get('GPS_TIMESYNC'):
            self.validateGpsTime()


        if self.camera_server in ['indi_asi_ccd']:
            # There is a bug in the ASI120M* camera that causes exposures to fail on gain changes
            # The indi_asi_ccd server will switch the camera to 8-bit mode to try to correct
            if self.camera_name.startswith('ZWO CCD ASI120'):
                self.indiclient.configureCcdDevice(self.config['INDI_CONFIG_DEFAULTS'])
        elif self.camera_server in ['indi_asi_single_ccd']:
            if self.camera_name.startswith('ZWO ASI120'):
                self.indiclient.configureCcdDevice(self.config['INDI_CONFIG_DEFAULTS'])


    def connectOnly(self):
        self._initialize(connectOnly=True)

        self.indiclient.disconnectServer()

        sys.exit()


    def run(self):
        with app.app_context():
            self.write_pid()

            self._expireOrphanedTasks()

            self._initialize()

            self._pre_run_tasks()


        next_frame_time = time.time()  # start immediately
        frame_start_time = time.time()
        waiting_for_frame = False

        camera_ready_time = time.time()
        camera_ready = False
        last_camera_ready = False
        exposure_state = 'unset'
        check_exposure_state = time.time() + 300  # check in 5 minutes


        ### main loop starts
        while True:
            loop_start_time = time.time()


            logger.info('Camera last ready: %0.1fs', loop_start_time - camera_ready_time)
            logger.info('Exposure state: %s', exposure_state)


            # do *NOT* start workers inside of a flask context
            # doing so will cause TLS/SSL problems connecting to databases

            # restart worker if it has failed
            self._startImageWorker()
            self._startVideoWorker()
            self._startFileUploadWorkers()


            self.detectNight()
            self.detectMoonMode()


            with app.app_context():
                ### Change between day and night
                if self.night_v.value != int(self.night):
                    if self.generate_timelapse_flag:
                        self._flushOldTasks()  # cleanup old tasks in DB
                        self._expireData(self.camera_id)  # cleanup old images and folders

                    if not self.night and self.generate_timelapse_flag:
                        ### Generate timelapse at end of night
                        yesterday_ref = datetime.now() - timedelta(days=1)
                        timespec = yesterday_ref.strftime('%Y%m%d')
                        self._generateNightTimelapse(timespec, self.camera_id)
                        self._generateNightKeogram(timespec, self.camera_id)
                        self._uploadAllskyEndOfNight(self.camera_id)
                        self._systemHealthCheck()

                    elif self.night and self.generate_timelapse_flag:
                        ### Generate timelapse at end of day
                        today_ref = datetime.now()
                        timespec = today_ref.strftime('%Y%m%d')
                        self._generateDayTimelapse(timespec, self.camera_id)
                        self._generateDayKeogram(timespec, self.camera_id)
                        self._systemHealthCheck()


                # this is to prevent expiring images at startup
                if self.night:
                    # always indicate timelapse generation at night
                    self.generate_timelapse_flag = True  # indicate images have been generated for timelapse
                elif self.config['DAYTIME_CAPTURE'] and self.config['DAYTIME_TIMELAPSE']:
                    # must be day time
                    self.generate_timelapse_flag = True  # indicate images have been generated for timelapse


                self.getSensorTemperature()
                self.getTelescopeRaDec()
                self.getGpsPosition()


                # Queue externally defined tasks
                self._queueManualTasks()


                if not self.night and not self.config['DAYTIME_CAPTURE']:
                    logger.info('Daytime capture is disabled')
                    self.generate_timelapse_flag = False

                    if self._shutdown:
                        logger.warning('Shutting down')
                        self._stopImageWorker(terminate=self._terminate)
                        self._stopVideoWorker(terminate=self._terminate)
                        self._stopFileUploadWorkers(terminate=self._terminate)

                        self.indiclient.disableCcdCooler()  # safety

                        self.indiclient.disconnectServer()


                        now = datetime.now()
                        self._miscDb.addNotification(
                            NotificationCategory.STATE,
                            'indi-allsky',
                            'indi-allsky was shutdown',
                            expire=timedelta(hours=1),
                        )


                        sys.exit()


                    if self._reload:
                        logger.warning('Restarting processes')
                        self._reload = False
                        self._stopImageWorker()
                        self._stopVideoWorker()
                        self._stopFileUploadWorkers()
                        # processes will start at the next loop


                    time.sleep(59)  # prime number
                    continue


                # check exposure state every 5 minutes
                if check_exposure_state < loop_start_time:
                    check_exposure_state = time.time() + 300  # next check in 5 minutes

                    camera_last_ready_s = int(loop_start_time - camera_ready_time)
                    if camera_last_ready_s > 300:
                        self._miscDb.addNotification(
                            NotificationCategory.CAMERA,
                            'last_ready',
                            'Camera last ready {0:d}s ago.  Camera might be hung.'.format(camera_last_ready_s),
                            expire=timedelta(minutes=60),
                        )


                # Loop to run for 11 seconds (prime number)
                loop_end = time.time() + 11

                while True:
                    time.sleep(0.05)

                    now = time.time()
                    if now >= loop_end:
                        break

                    last_camera_ready = camera_ready
                    camera_ready, exposure_state = self.indiclient.getCcdExposureStatus()

                    if not camera_ready:
                        continue

                    ###########################################
                    # Camera is ready, not taking an exposure #
                    ###########################################
                    if not last_camera_ready:
                        camera_ready_time = now


                    if waiting_for_frame:
                        frame_elapsed = now - frame_start_time

                        waiting_for_frame = False

                        logger.info('Exposure received in %0.4f s (%0.4f)', frame_elapsed, frame_elapsed - self.exposure_v.value)


                    ##########################################################################
                    # Here we know the camera is not busy and we are not waiting for a frame #
                    ##########################################################################

                    # shutdown here to ensure camera is not taking images
                    if self._shutdown:
                        logger.warning('Shutting down')
                        self._stopImageWorker(terminate=self._terminate)
                        self._stopVideoWorker(terminate=self._terminate)
                        self._stopFileUploadWorkers(terminate=self._terminate)

                        self.indiclient.disableCcdCooler()  # safety

                        self.indiclient.disconnectServer()


                        now = datetime.now()
                        self._miscDb.addNotification(
                            NotificationCategory.STATE,
                            'indi-allsky',
                            'indi-allsky was shutdown',
                            expire=timedelta(hours=1),
                        )

                        sys.exit()


                    # restart here to ensure camera is not taking images
                    if self._reload:
                        logger.warning('Restarting processes')
                        self._reload = False
                        self._stopImageWorker()
                        self._stopVideoWorker()
                        self._stopFileUploadWorkers()
                        # processes will start at the next loop


                    # reconfigure if needed
                    self.reconfigureCcd()

                    # these tasks run every ~5 minutes
                    self.periodic_tasks()


                    if now >= next_frame_time:
                        #######################
                        # Start next exposure #
                        #######################

                        total_elapsed = now - frame_start_time

                        frame_start_time = now

                        self.shoot(self.exposure_v.value, sync=False)
                        camera_ready = False
                        waiting_for_frame = True

                        if self.focus_mode:
                            # Start frame immediately in focus mode
                            logger.warning('*** FOCUS MODE ENABLED ***')
                            next_frame_time = now + self.config.get('FOCUS_DELAY', 4.0)
                        elif self.night:
                            next_frame_time = frame_start_time + self.config['EXPOSURE_PERIOD']
                        else:
                            next_frame_time = frame_start_time + self.config['EXPOSURE_PERIOD_DAY']

                        logger.info('Total time since last exposure %0.4f s', total_elapsed)


                loop_elapsed = now - loop_start_time
                logger.debug('Loop completed in %0.4f s', loop_elapsed)


    def getSensorTemperature(self):
        temp_val = self.indiclient.getCcdTemperature()


        # query external temperature if camera does not return temperature
        if temp_val < -100.0 and self.config.get('CCD_TEMP_SCRIPT'):
            try:
                ext_temp_val = self.getExternalTemperature(self.config.get('CCD_TEMP_SCRIPT'))
                temp_val = ext_temp_val
            except TemperatureException as e:
                logger.error('Exception querying external temperature: %s', str(e))


        temp_val_f = float(temp_val)

        with self.sensortemp_v.get_lock():
            self.sensortemp_v.value = temp_val_f


        return temp_val_f


    def getExternalTemperature(self, script_path):
        temp_script_p = Path(script_path)

        logger.info('Running external script for temperature: %s', temp_script_p)

        # need to be extra careful running in the main thread
        if not temp_script_p.exists():
            raise TemperatureException('Temperature script does not exist')

        if not temp_script_p.is_file():
            raise TemperatureException('Temperature script is not a file')

        if temp_script_p.stat().st_size == 0:
            raise TemperatureException('Temperature script is empty')

        if not os.access(str(temp_script_p), os.X_OK):
            raise TemperatureException('Temperature script is not executable')


        # generate a tempfile for the data
        f_tmp_tempjson = tempfile.NamedTemporaryFile(mode='w', delete=True, suffix='.json')
        f_tmp_tempjson.close()

        tempjson_name_p = Path(f_tmp_tempjson.name)


        cmd = [
            str(temp_script_p),
        ]


        # the file used for the json data is communicated via environment variable
        cmd_env = {
            'TEMP_JSON' : str(tempjson_name_p),
        }


        try:
            temp_process = subprocess.Popen(
                cmd,
                env=cmd_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            raise TemperatureException('Temperature script failed to execute')


        try:
            temp_process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            temp_process.kill()
            time.sleep(1.0)
            temp_process.poll()  # close out process
            raise TemperatureException('Temperature script timed out')


        if temp_process.returncode != 0:
            raise TemperatureException('Temperature script returned exited abnormally')


        try:
            with io.open(str(tempjson_name_p), 'r') as tempjson_name_f:
                temp_data = json.load(tempjson_name_f)

            tempjson_name_p.unlink()  # remove temp file
        except PermissionError as e:
            logger.error(str(e))
            raise TemperatureException(str(e))
        except json.JSONDecodeError as e:
            logger.error('Error decoding json: %s', str(e))
            raise TemperatureException(str(e))
        except FileNotFoundError as e:
            raise TemperatureException(str(e))


        try:
            temp_float = float(temp_data['temp'])
        except ValueError:
            raise TemperatureException('Temperature script returned a non-numerical value')
        except KeyError:
            raise TemperatureException('Temperature script returned incorrect data')


        return temp_float


    def getGpsPosition(self):
        if not self.indiclient.gps_device:
            return

        update_position = False

        gps_lat, gps_long, gps_elev = self.indiclient.getGpsPosition()

        if gps_long > 180.0:
            # put longitude in range of -180 to 180
            gps_long = gps_long - 360.0

        #logger.info('Lat: %0.2f, Long: %0.2f', self.latitude_v.value, self.longitude_v.value)

        # need 1/10 degree difference before updating location
        if abs(gps_lat - self.latitude_v.value) > 0.1:
            self.updateConfigLocation(gps_lat, gps_long)
            update_position = True
        elif abs(gps_long - self.longitude_v.value) > 0.1:
            self.updateConfigLocation(gps_lat, gps_long)
            update_position = True


        if update_position:
            # Update shared values
            with self.latitude_v.get_lock():
                self.latitude_v.value = gps_lat

            with self.longitude_v.get_lock():
                self.longitude_v.value = gps_long


            self.reparkTelescope()


        return gps_lat, gps_long, gps_elev


    def getTelescopeRaDec(self):
        if not self.indiclient.telescope_device:
            return

        ra, dec = self.indiclient.getTelescopeRaDec()

        # Update shared values
        with self.ra_v.get_lock():
            self.ra_v.value = ra

        with self.dec_v.get_lock():
            self.dec_v.value = dec


        return ra, dec


    def updateConfigLocation(self, gps_lat, gps_long):
        logger.warning('Updating indi-allsky config with new geographic location')

        self.config['LOCATION_LATITUDE'] = round(float(gps_lat), 3)
        self.config['LOCATION_LONGITUDE'] = round(float(gps_long), 3)


        # save new config
        try:
            self._config_obj.save('system', '*Auto* Location updated')
            logger.info('Wrote new config')
        except ConfigSaveException:
            return


    def reparkTelescope(self):
        if not self.indiclient.telescope_device:
            return

        self.indiclient.unparkTelescope()
        self.indiclient.setTelescopeParkPosition(0.0, self.latitude_v.value)
        self.indiclient.parkTelescope()


    def cameraReport(self):
        camera_interface = getattr(camera_module, self.config.get('CAMERA_INTERFACE', 'indi'))

        # instantiate the client
        self.indiclient = camera_interface(
            self.config,
            self.image_q,
            self.latitude_v,
            self.longitude_v,
            self.ra_v,
            self.dec_v,
            self.gain_v,
            self.bin_v,
        )

        # set indi server localhost and port
        self.indiclient.setServer(self.config['INDI_SERVER'], self.config['INDI_PORT'])

        # connect to indi server
        logger.info("Connecting to indiserver")
        if not self.indiclient.connectServer():
            logger.error("No indiserver running on %s:%d - Try to run", self.indiclient.getHost(), self.indiclient.getPort())
            logger.error("  indiserver indi_simulator_telescope indi_simulator_ccd")

            self._miscDb.addNotification(
                NotificationCategory.GENERAL,
                'no_indiserver',
                'WARNING: indiserver service is not active',
                expire=timedelta(hours=2),
            )

            sys.exit(1)

        # give devices a chance to register
        time.sleep(8)

        try:
            self.indiclient.findCcd(self.config.get('INDI_CAMERA_NAME'))
        except CameraException as e:
            logger.error('Camera error: %s', str(e))

            self._miscDb.addNotification(
                NotificationCategory.CAMERA,
                'no_camera',
                'Camera was not detected.',
                expire=timedelta(hours=2),
            )

            time.sleep(1)
            sys.exit(1)


        logger.warning('Connecting to device %s', self.indiclient.ccd_device.getDeviceName())
        self.indiclient.connectDevice(self.indiclient.ccd_device.getDeviceName())

        # Get Properties
        ccd_properties = self.indiclient.getCcdDeviceProperties()
        logger.info('Camera Properties: %s', json.dumps(ccd_properties, indent=4))

        # get CCD information
        ccd_info = self.indiclient.getCcdInfo()
        logger.info('Camera Info: %s', json.dumps(ccd_info, indent=4))

        self.indiclient.disconnectServer()



    def reconfigureCcd(self):

        if self.night_v.value != int(self.night):
            pass
        elif self.night and bool(self.moonmode_v.value) != bool(self.moonmode):
            pass
        else:
            # No need to reconfigure
            return


        if self.night:
            # cooling
            if self.config.get('CCD_COOLING'):
                ccd_temp = self.config.get('CCD_TEMP', 15.0)
                self.indiclient.enableCcdCooler()
                self.indiclient.setCcdTemperature(ccd_temp)


            if self.moonmode:
                logger.warning('Change to night (moon mode)')
                self.indiclient.setCcdGain(self.config['CCD_CONFIG']['MOONMODE']['GAIN'])
                self.indiclient.setCcdBinning(self.config['CCD_CONFIG']['MOONMODE']['BINNING'])
            else:
                logger.warning('Change to night (normal mode)')
                self.indiclient.setCcdGain(self.config['CCD_CONFIG']['NIGHT']['GAIN'])
                self.indiclient.setCcdBinning(self.config['CCD_CONFIG']['NIGHT']['BINNING'])
        else:
            logger.warning('Change to day')
            self.indiclient.disableCcdCooler()
            self.indiclient.setCcdGain(self.config['CCD_CONFIG']['DAY']['GAIN'])
            self.indiclient.setCcdBinning(self.config['CCD_CONFIG']['DAY']['BINNING'])



        # Update shared values
        with self.night_v.get_lock():
            self.night_v.value = int(self.night)

        with self.moonmode_v.get_lock():
            self.moonmode_v.value = int(self.moonmode)



    def detectNight(self):
        obs = ephem.Observer()
        obs.lon = math.radians(self.longitude_v.value)
        obs.lat = math.radians(self.latitude_v.value)
        obs.date = datetime.utcnow()  # ephem expects UTC dates

        sun = ephem.Sun()
        sun.compute(obs)

        logger.info('Sun altitude: %s', sun.alt)

        self.night = sun.alt < self.night_sun_radians  # boolean


    def detectMoonMode(self):
        # detectNight() should be run first
        obs = ephem.Observer()
        obs.lon = math.radians(self.longitude_v.value)
        obs.lat = math.radians(self.latitude_v.value)
        obs.date = datetime.utcnow()  # ephem expects UTC dates

        moon = ephem.Moon()
        moon.compute(obs)

        moon_phase = moon.moon_phase * 100.0

        logger.info('Moon altitude: %s, phase %0.1f%%', moon.alt, moon_phase)
        if self.night:
            if moon.alt >= self.night_moonmode_radians:
                if moon_phase >= self.config['NIGHT_MOONMODE_PHASE']:
                    logger.info('Moon Mode conditions detected')
                    self.moonmode = True
                    return

        self.moonmode = False


    def generateDayTimelapse(self, timespec='', camera_id=0):
        # run from command line
        self.config['TIMELAPSE_ENABLE'] = True

        with app.app_context():
            if camera_id == 0:
                try:
                    camera_id = self._miscDb.getCurrentCameraId()
                except NoResultFound:
                    logger.error('No camera found')
                    sys.exit(1)
            else:
                camera_id = int(camera_id)


            self._generateDayTimelapse(timespec, camera_id, task_state=TaskQueueState.MANUAL)


    def _generateDayTimelapse(self, timespec, camera_id, task_state=TaskQueueState.QUEUED):
        if not self.config.get('TIMELAPSE_ENABLE', True):
            logger.warning('Timelapse creation disabled')
            return


        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        img_day_folder = self.image_dir.joinpath('ccd_{0:s}'.format(camera.uuid), '{0:s}'.format(timespec), 'day')

        logger.warning('Generating day time timelapse for %s camera %d', timespec, camera.id)

        jobdata = {
            'action'      : 'generateVideo',
            'timespec'    : timespec,
            'img_folder'  : str(img_day_folder),
            'night'       : False,
            'camera_id'   : camera.id,
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=task_state,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.video_q.put({'task_id' : task.id})


    def generateNightTimelapse(self, timespec='', camera_id=0):
        # run from command line
        self.config['TIMELAPSE_ENABLE'] = True

        with app.app_context():
            if camera_id == 0:
                try:
                    camera_id = self._miscDb.getCurrentCameraId()
                except NoResultFound:
                    logger.error('No camera found')
                    sys.exit(1)
            else:
                camera_id = int(camera_id)


            self._generateNightTimelapse(timespec, camera_id, task_state=TaskQueueState.MANUAL)


    def _generateNightTimelapse(self, timespec, camera_id, task_state=TaskQueueState.QUEUED):
        if not self.config.get('TIMELAPSE_ENABLE', True):
            logger.warning('Timelapse creation disabled')
            return


        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        img_day_folder = self.image_dir.joinpath('ccd_{0:s}'.format(camera.uuid), '{0:s}'.format(timespec), 'night')

        logger.warning('Generating night time timelapse for %s camera %d', timespec, camera.id)

        jobdata = {
            'action'      : 'generateVideo',
            'timespec'    : timespec,
            'img_folder'  : str(img_day_folder),
            'night'       : True,
            'camera_id'   : camera.id,
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=task_state,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.video_q.put({'task_id' : task.id})


    def generateNightKeogram(self, timespec='', camera_id=0):
        # run from command line
        self.config['TIMELAPSE_ENABLE'] = True

        with app.app_context():
            if camera_id == 0:
                try:
                    camera_id = self._miscDb.getCurrentCameraId()
                except NoResultFound:
                    logger.error('No camera found')
                    sys.exit(1)
            else:
                camera_id = int(camera_id)


            self._generateNightKeogram(timespec, camera_id, task_state=TaskQueueState.MANUAL)


    def _generateNightKeogram(self, timespec, camera_id, task_state=TaskQueueState.QUEUED):
        if not self.config.get('TIMELAPSE_ENABLE', True):
            logger.warning('Timelapse creation disabled')
            return


        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        img_day_folder = self.image_dir.joinpath('ccd_{0:s}'.format(camera.uuid), '{0:s}'.format(timespec), 'night')

        logger.warning('Generating night time keogram for %s camera %d', timespec, camera.id)

        jobdata = {
            'action'      : 'generateKeogramStarTrails',
            'timespec'    : timespec,
            'img_folder'  : str(img_day_folder),
            'night'       : True,
            'camera_id'   : camera.id,
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=task_state,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.video_q.put({'task_id' : task.id})


    def generateDayKeogram(self, timespec='', camera_id=0):
        # run from command line
        self.config['TIMELAPSE_ENABLE'] = True

        with app.app_context():
            if camera_id == 0:
                try:
                    camera_id = self._miscDb.getCurrentCameraId()
                except NoResultFound:
                    logger.error('No camera found')
                    sys.exit(1)
            else:
                camera_id = int(camera_id)


            self._generateDayKeogram(timespec, camera_id, task_state=TaskQueueState.MANUAL)


    def _generateDayKeogram(self, timespec, camera_id, task_state=TaskQueueState.QUEUED):
        if not self.config.get('TIMELAPSE_ENABLE', True):
            logger.warning('Timelapse creation disabled')
            return


        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        img_day_folder = self.image_dir.joinpath('ccd_{0:s}'.format(camera.uuid), '{0:s}'.format(timespec), 'day')

        logger.warning('Generating day time keogram for %s camera %d', timespec, camera.id)

        jobdata = {
            'action'      : 'generateKeogramStarTrails',
            'timespec'    : timespec,
            'img_folder'  : str(img_day_folder),
            'night'       : False,
            'camera_id'   : camera.id,
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=task_state,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.video_q.put({'task_id' : task.id})


    def shoot(self, exposure, sync=True, timeout=None):
        logger.info('Taking %0.8f s exposure (gain %d)', exposure, self.gain_v.value)

        self.indiclient.setCcdExposure(exposure, sync=sync, timeout=timeout)


    def validateGpsTime(self):
        if not self.indiclient.gps_device:
            logger.error('No GPS device for time sync')
            return


        self.indiclient.refreshGps()
        gps_utc, gps_offset = self.indiclient.getGpsTime()


        if not gps_utc:
            logger.error('GPS did not return time data')
            return


        systemtime_utc = datetime.now().astimezone(tz=timezone.utc)
        logger.info('System time: %s', systemtime_utc)

        time_offset = systemtime_utc.timestamp() - gps_utc.timestamp()
        logger.info('GPS time offset: %ds', int(time_offset))


        # if there is a delta of more than 60 seconds, update system time
        if abs(time_offset) > 60:
            logger.warning('Setting system time to %s (UTC)', gps_utc)

            # This may not result in a perfect sync.  Due to delays in commands,
            # time can still be off by several seconds
            try:
                self.setTimeSystemd(gps_utc)
            except dbus.exceptions.DBusException as e:
                logger.error('DBus Error: %s', str(e))


    def setTimeSystemd(self, new_datetime_utc):
        epoch = new_datetime_utc.timestamp() + 5  # add 5 due to sleep below
        epoch_msec = epoch * 1000000

        system_bus = dbus.SystemBus()
        timedate1 = system_bus.get_object('org.freedesktop.timedate1', '/org/freedesktop/timedate1')
        manager = dbus.Interface(timedate1, 'org.freedesktop.timedate1')

        logger.warning('Disabling NTP time sync')
        manager.SetNTP(False, False)  # disable time sync
        time.sleep(5.0)  # give enough time for time sync to diable

        r2 = manager.SetTime(epoch_msec, False, False)

        return r2


    def expireData(self, camera_id=0):
        with app.app_context():
            if camera_id == 0:
                try:
                    camera_id = self._miscDb.getCurrentCameraId()
                except NoResultFound:
                    logger.error('No camera found')
                    sys.exit(1)
            else:
                camera_id = int(camera_id)


            self._expireData(camera_id, TaskQueueState.MANUAL)


    def _expireData(self, camera_id, task_state=TaskQueueState.QUEUED):

        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        # This will delete old images from the filesystem and DB
        jobdata = {
            'action'       : 'expireData',
            'img_folder'   : str(self.image_dir),
            'timespec'     : None,  # Not needed
            'night'        : None,  # Not needed
            'camera_id'    : camera.id,
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=task_state,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.video_q.put({'task_id' : task.id})


    def _uploadAllskyEndOfNight(self, camera_id, task_state=TaskQueueState.QUEUED):
        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        # This will delete old images from the filesystem and DB
        jobdata = {
            'action'       : 'uploadAllskyEndOfNight',
            'img_folder'   : str(self.image_dir),  # not needed
            'timespec'     : None,  # Not needed
            'night'        : True,
            'camera_id'    : camera.id,
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=task_state,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.video_q.put({'task_id' : task.id})


    def _systemHealthCheck(self, task_state=TaskQueueState.QUEUED):
        # This will delete old images from the filesystem and DB
        jobdata = {
            'action'       : 'systemHealthCheck',
            'img_folder'   : str(self.image_dir),  # not needed
            'timespec'     : None,  # Not needed
            'night'        : None,  # Not needed
            'camera_id'    : None,  # Not needed
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
            camera = self._miscDb.addCamera('Import camera', None)
            camera_id = camera.id


        file_list_darks = list()
        self._getFolderFilesByExt(self.image_dir.joinpath('darks'), file_list_darks, extension_list=['fit', 'fits'])


        ### Dark frames
        file_list_darkframes = filter(lambda p: 'dark' in p.name, file_list_darks)

        #/var/www/html/allsky/images/darks/dark_ccd1_8bit_6s_gain250_bin1_10c_20210826_020202.fit
        re_darkframe = re.compile(r'\/dark_ccd(?P<ccd_id_str>\d+)_(?P<bitdepth_str>\d+)bit_(?P<exposure_str>\d+)s_gain(?P<gain_str>\d+)_bin(?P<binmode_str>\d+)_(?P<ccdtemp_str>\-?\d+)c_(?P<createDate_str>[0-9_]+)\.[a-z]+$')

        darkframe_entries = list()
        for f in file_list_darkframes:
            #logger.info('Raw frame: %s', f)

            m = re.search(re_darkframe, str(f))
            if not m:
                logger.error('Regex did not match file: %s', f)
                continue


            #logger.info('CCD ID string: %s', m.group('ccd_id_str'))
            #logger.info('Exposure string: %s', m.group('exposure_str'))
            #logger.info('Bitdepth string: %s', m.group('bitdepth_str'))
            #logger.info('Gain string: %s', m.group('gain_str'))
            #logger.info('Binmode string: %s', m.group('binmode_str'))
            #logger.info('Ccd temp string: %s', m.group('ccdtemp_str'))

            ccd_id = int(m.group('ccd_id_str'))
            exposure = int(m.group('exposure_str'))
            bitdepth = int(m.group('bitdepth_str'))
            gain = int(m.group('gain_str'))
            binmode = int(m.group('binmode_str'))
            ccdtemp = float(m.group('ccdtemp_str'))


            d_createDate = datetime.fromtimestamp(f.stat().st_mtime)

            darkframe_dict = {
                'filename'   : str(f),
                'createDate' : d_createDate,
                'bitdepth'   : bitdepth,
                'exposure'   : exposure,
                'gain'       : gain,
                'binmode'    : binmode,
                'camera_id'  : ccd_id,
                'temp'       : ccdtemp,
            }

            darkframe_entries.append(darkframe_dict)


        try:
            db.session.bulk_insert_mappings(IndiAllSkyDbDarkFrameTable, darkframe_entries)
            db.session.commit()

            logger.warning('*** Dark frames inserted: %d ***', len(darkframe_entries))
        except IntegrityError as e:
            logger.warning('Integrity error: %s', str(e))
            db.session.rollback()


        file_list_videos = list()
        self._getFolderFilesByExt(self.image_dir, file_list_videos, extension_list=['mp4', 'webm'])


        ### Bad pixel maps
        file_list_bpm = filter(lambda p: 'bpm' in p.name, file_list_darks)

        #/var/www/html/allsky/images/darks/bpm_ccd1_8bit_6s_gain250_bin1_10c_20210826_020202.fit
        re_bpm = re.compile(r'\/bpm_ccd(?P<ccd_id_str>\d+)_(?P<bitdepth_str>\d+)bit_(?P<exposure_str>\d+)s_gain(?P<gain_str>\d+)_bin(?P<binmode_str>\d+)_(?P<ccdtemp_str>\-?\d+)c_(?P<createDate_str>[0-9_]+)\.[a-z]+$')

        bpm_entries = list()
        for f in file_list_bpm:
            #logger.info('Raw frame: %s', f)

            m = re.search(re_bpm, str(f))
            if not m:
                logger.error('Regex did not match file: %s', f)
                continue


            #logger.info('CCD ID string: %s', m.group('ccd_id_str'))
            #logger.info('Exposure string: %s', m.group('exposure_str'))
            #logger.info('Bitdepth string: %s', m.group('bitdepth_str'))
            #logger.info('Gain string: %s', m.group('gain_str'))
            #logger.info('Binmode string: %s', m.group('binmode_str'))
            #logger.info('Ccd temp string: %s', m.group('ccdtemp_str'))

            ccd_id = int(m.group('ccd_id_str'))
            exposure = int(m.group('exposure_str'))
            bitdepth = int(m.group('bitdepth_str'))
            gain = int(m.group('gain_str'))
            binmode = int(m.group('binmode_str'))
            ccdtemp = float(m.group('ccdtemp_str'))


            d_createDate = datetime.fromtimestamp(f.stat().st_mtime)

            bpm_dict = {
                'filename'   : str(f),
                'createDate' : d_createDate,
                'bitdepth'   : bitdepth,
                'exposure'   : exposure,
                'gain'       : gain,
                'binmode'    : binmode,
                'camera_id'  : ccd_id,
                'temp'       : ccdtemp,
            }

            bpm_entries.append(bpm_dict)


        try:
            db.session.bulk_insert_mappings(IndiAllSkyDbBadPixelMapTable, bpm_entries)
            db.session.commit()

            logger.warning('*** Bad pixel maps inserted: %d ***', len(bpm_entries))
        except IntegrityError as e:
            logger.warning('Integrity error: %s', str(e))
            db.session.rollback()



        ### Timelapse
        timelapse_videos_tl = filter(lambda p: 'timelapse' in p.name, file_list_videos)
        timelapse_videos = filter(lambda p: 'startrail' not in p.name, timelapse_videos_tl)  # exclude star trail timelapses

        #/var/www/html/allsky/images/20210915/allsky-timelapse_ccd1_20210915_night.mp4
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
                'filename'   : str(f),
                'createDate' : d_createDate,
                'dayDate'    : d_dayDate,
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



        ### find all imaegs
        file_list_images = list()
        self._getFolderFilesByExt(self.image_dir, file_list_images, extension_list=['jpg', 'jpeg', 'png', 'tif', 'tiff'])


        ### Keograms
        file_list_keograms = filter(lambda p: 'keogram' in p.name, file_list_images)

        #/var/www/html/allsky/images/20210915/allsky-keogram_ccd1_20210915_night.jpg
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
                'filename'   : str(f),
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

        #/var/www/html/allsky/images/20210915/allsky-startrail_ccd1_20210915_night.jpg
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
                'filename'   : str(f),
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

        #/var/www/html/allsky/images/20210915/allsky-startrail_timelapse_ccd1_20210915_night.mp4
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
                'filename'   : str(f),
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


        ### Images
        # Exclude keograms and star trails
        file_list_images_nok = filter(lambda p: 'keogram' not in p.name, file_list_images)
        file_list_images_nok_nost = filter(lambda p: 'startrail' not in p.name, file_list_images_nok)

        #/var/www/html/allsky/images/20210825/night/26_02/ccd1_20210826_020202.jpg
        re_image = re.compile(r'(?P<dayDate_str>\d{8})\/(?P<timeofday_str>[a-z]+)\/\d{2}_\d{2}\/ccd(?P<ccd_id_str>\d+)_(?P<createDate_str>[0-9_]+)\.[a-z]+$')

        image_entries = list()
        for f in file_list_images_nok_nost:
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
                'filename'   : str(f),
                'camera_id'  : camera_id,
                'createDate' : d_createDate,
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


    def _getFolderFilesByExt(self, folder, file_list, extension_list=None):
        if not extension_list:
            extension_list = [self.config['IMAGE_FILE_TYPE']]

        #logger.info('Searching for image files in %s', folder)

        dot_extension_list = ['.{0:s}'.format(e) for e in extension_list]

        for item in Path(folder).iterdir():
            if item.is_file() and item.suffix in dot_extension_list:
                file_list.append(item)
            elif item.is_dir():
                self.getFolderFilesByExt(item, file_list, extension_list=extension_list)  # recursion


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
        logger.info('Checking for manually submitted tasks')
        manual_tasks = IndiAllSkyDbTaskQueueTable.query\
            .filter(IndiAllSkyDbTaskQueueTable.state == TaskQueueState.MANUAL)\
            .filter(
                or_(
                    IndiAllSkyDbTaskQueueTable.queue == TaskQueueQueue.MAIN,
                    IndiAllSkyDbTaskQueueTable.queue == TaskQueueQueue.VIDEO,
                )
            )\
            .order_by(IndiAllSkyDbTaskQueueTable.createDate.asc())


        reload_received = False
        for task in manual_tasks:
            if task.queue == TaskQueueQueue.VIDEO:
                logger.info('Queuing manual task %d', task.id)
                task.setQueued()
                self.video_q.put({'task_id' : task.id})

            elif task.queue == TaskQueueQueue.MAIN:
                logger.info('Picked up MAIN task')

                action = task.data['action']

                if action == 'reload':
                    if reload_received:
                        logger.warning('Skipping duplicate reload signal')
                        task.setExpired()
                        continue

                    reload_received = True
                    os.kill(os.getpid(), signal.SIGHUP)
                    task.setSuccess('Reloaded indi-allsky process')
                else:
                    logger.error('Unknown action: %s', action)
                    task.setFailed()

            else:
                logger.error('Unmanaged queue %s', task.queue.name)
                task.setFailed()

