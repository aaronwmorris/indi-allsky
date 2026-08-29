import os
import sys
import locale
import io
import time
import math
import tempfile
import json
import psutil
import subprocess
from datetime import datetime
from collections import OrderedDict
from pathlib import Path
#import signal
import ctypes
import logging

import numpy
import cv2

import queue
from multiprocessing import Queue
from multiprocessing import Array

from .exceptions import TimeOutException
from .exceptions import TemperatureException
from .exceptions import CameraException
from .exceptions import BadImage

from .config import IndiAllSkyConfig

from . import camera as camera_module

from . import constants
from .utils import IndiAllSkyExposureUtils
from .capture_state import CameraCapabilities
from .capture_state import build_effective_capture_state
from .dark_validation import validate_dark_master_data
from .temperature import TEMPERATURE_SOURCE_AUTO
from .temperature import TEMPERATURE_SOURCE_CAMERA
from .temperature import TEMPERATURE_SOURCE_SCRIPT
from .temperature import configured_temperature_sources
from .temperature import resolve_temperature
from .temperature import usable_temperature

from .flask import create_app
from .flask import db
from .flask.miscDb import miscDb

#from .flask.models import TaskQueueState
#from .flask.models import TaskQueueQueue
from .flask.models import IndiAllSkyDbCameraTable
from .flask.models import IndiAllSkyDbDarkFrameTable
from .flask.models import IndiAllSkyDbBadPixelMapTable
#from .flask.models import IndiAllSkyDbTaskQueueTable

from sqlalchemy.orm.exc import NoResultFound


try:
    import rawpy  # not available in all cases
except ImportError:
    rawpy = None


app = create_app()

logger = logging.getLogger('indi_allsky')


class DarkCapturePlanChanged(RuntimeError):
    pass


def _falling_temperature_thresholds(
        start_temperature,
        target_temperature,
        temperature_delta,
):
    """Build finite-series thresholds without depending on the library builder."""
    if target_temperature is None:
        return ()
    try:
        start_temperature = float(start_temperature)
        target_temperature = float(target_temperature)
        temperature_delta = float(temperature_delta)
    except (TypeError, ValueError):
        return ()
    if (
            not math.isfinite(start_temperature)
            or not math.isfinite(target_temperature)
            or not math.isfinite(temperature_delta)
            or temperature_delta <= 0
            or start_temperature <= target_temperature
    ):
        return ()

    thresholds = []
    next_temperature = start_temperature - temperature_delta
    while next_temperature > target_temperature + 0.000001:
        thresholds.append(float(round(next_temperature, 3)))
        next_temperature -= temperature_delta
    thresholds.append(float(round(target_temperature, 3)))
    return tuple(thresholds)


class IndiAllSkyDarks(object):

    def __init__(self):
        # should be inherited by all of the sub-processes
        locale.setlocale(locale.LC_ALL, '')

        with app.app_context():
            try:
                self._config_obj = IndiAllSkyConfig()
            except NoResultFound:
                logger.error('No config file found, please import a config')
                sys.exit(1)

            self.config = self._config_obj.config

        self._daytime = True  # build daytime dark library

        self._gain_list = []
        self._exposure_list = []
        self._binning = 1
        self._count = 10
        self._temp_delta = 5.0
        self._temperature_target = None
        self._time_delta = 5

        self._hotpixel_adu_percent = 90

        self._reverse = True  # default high to low exposures
        self._capture_profile = 'auto'
        self._progress_file = None
        self._automation_manifest = {}
        self._progress_total_master_sets = 0
        self._progress_completed_master_sets = 0
        self._progress_completed_master_details = []
        self._progress_current_gain = None
        self._progress_current_exposure = None
        self._progress_current_binning = None
        self._progress_current_temperature = None
        self._progress_temperature_source = None
        self._progress_next_temperature = None
        self._progress_target_temperature = None
        self._progress_completed_temperature_sets = 0
        self._progress_temperature_set = None
        self._progress_planned_temperature_sets = None
        self._progress_temperature_set_started_utc = None
        self._progress_activated_master_files = 0

        # this is used to set a max value of data returned by the camera
        self._bitmax = 0

        self._flush_camera_id = 1

        self.image_q = Queue()
        self.indiclient = None

        self.camera_id = None
        self.camera_name = None
        self.camera_server = None
        self.ccd_info = None


        self.sensor_q = Queue()
        self.sensor_error_q = Queue()
        self.sensor_worker = None
        self.sensor_worker_idx = 0


        self.indi_config = self.config.get('INDI_CONFIG_DEFAULTS', {})

        ### all values in microseconds (0.000001 second)
        self.exposure_av = Array(ctypes.c_int32, [
            -1,  # current exposure - these must be -1 to indicate unset
            -1,  # next exposure
            -1,  # exposure delta
            -1,  # night minimum
            -1,  # day minimum
            -1,  # maximum
            -1,  # sqm
        ])


        ### unit 1/1000 gain (0.001 gain)
        self.gain_av = Array(ctypes.c_int32, [
            -1,  # current gain
            -1,  # next gain
            -1,  # gain delta
            -1,  # day minimum
            -1,  # day maximum
            -1,  # night minimum
            -1,  # night maximum
            -1,  # moon mode minimum
            -1,  # moon mode maximum
            -1,  # sqm
        ])


        self.binning_av = Array('i', [
            -1,  # current bin
            -1,  # next bin
            -1,  # day bin
            -1,  # night bin
            -1,  # moonmode bin
            -1,  # sqm
        ])


        self.sensors_temp_av = Array('f', [0.0 for x in range(60)])
        # NaN distinguishes an unread configured sensor from a legitimate 0°C
        # reading while the dark-capture sensor worker is starting.
        self.sensors_user_av = Array('f', [float('nan') for x in range(110)])


        # These shared values are to indicate when the camera is in night/moon modes
        self.night_av = Array('i', [
            -1,  # night, bogus initial value
            0,  # moonmode, never used
        ])


        # not used, but required
        self.position_av = Array('f', [
            float(self.config['LOCATION_LATITUDE']),
            float(self.config['LOCATION_LONGITUDE']),
            float(self.config.get('LOCATION_ELEVATION', 300)),
            0.0,  # Ra
            0.0,  # Dec
        ])


        # not used, but required
        self.astro_av = Array('f', [
            0.0,  # sun alt
            0.0,  # moon alt
            0.0,  # moon percent
        ])


        self._miscDb = miscDb(self.config)
        self._expUtils = IndiAllSkyExposureUtils(self.config, self.exposure_av, self.gain_av, self.binning_av)


        self._shutdown = False

        #signal.signal(signal.SIGINT, self.sigint_handler_main)


        if self.config['IMAGE_FOLDER']:
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()

        self.darks_dir = self.image_dir.joinpath('darks')
        self.darks_dir.mkdir(mode=0o755, parents=True, exist_ok=True)


    @property
    def count(self):
        return self._count

    @count.setter
    def count(self, new_count):
        #logger.info('Changing image count to %d', int(new_count))
        self._count = int(new_count)


    @property
    def gain_list(self):
        return self._gain_list

    @gain_list.setter
    def gain_list(self, new_list_str):
        if isinstance(new_list_str, type(None)):
            logger.warning('Using gain values from config')
            time.sleep(3.0)
            return

        try:
            gain_list = [float(round(x, 3)) for x in new_list_str]
        except ValueError:
            logger.error('Invalid gain list: %s', str(new_list_str))
            sys.exit(1)
        except TypeError:
            logger.error('Invalid gain list: %s', str(new_list_str))
            sys.exit(1)


        self._gain_list = sorted(gain_list, reverse=True)
        logger.warning('Using gain list: %s', ', '.join(['{0:0.3f}'.format(x) for x in self._gain_list]))


    @property
    def exposure_list(self):
        return self._exposure_list

    @exposure_list.setter
    def exposure_list(self, new_exposure_list):
        if new_exposure_list is None:
            self._exposure_list = []
            return

        try:
            exposures = [float(round(value, 6)) for value in new_exposure_list]
        except (TypeError, ValueError):
            raise ValueError('Invalid exposure list')
        if not exposures or any(value <= 0 for value in exposures):
            raise ValueError('Exposure values must be greater than zero')
        self._exposure_list = sorted(set(exposures), reverse=self.reverse)
        logger.warning(
            'Using exposure list: %s',
            ', '.join(['{0:g}'.format(value) for value in self._exposure_list]),
        )


    @property
    def binning(self):
        return self._binning

    @binning.setter
    def binning(self, new_binning):
        self._binning = int(new_binning)
        assert self._binning >= 1


    @property
    def temp_delta(self):
        return self._temp_delta

    @temp_delta.setter
    def temp_delta(self, new_temp_delta):
        self._temp_delta = float(abs(new_temp_delta))
        logger.warning('New Temp delta: %0.1f', self.temp_delta)


    @property
    def temperature_target(self):
        return self._temperature_target

    @temperature_target.setter
    def temperature_target(self, new_temperature_target):
        if new_temperature_target is None:
            self._temperature_target = None
            return
        temperature_target = float(new_temperature_target)
        if not math.isfinite(temperature_target):
            raise ValueError('Invalid target sensor temperature')
        if temperature_target < -100.0 or temperature_target > 100.0:
            raise ValueError('Target sensor temperature must be between -100 and 100°C')
        self._temperature_target = float(round(temperature_target, 3))
        logger.warning('Target sensor temperature: %0.1f', self._temperature_target)


    @property
    def time_delta(self):
        return self._time_delta

    @time_delta.setter
    def time_delta(self, new_time_delta):
        self._time_delta = int(abs(new_time_delta))
        logger.warning('New Time delta: %d', self.time_delta)


    @property
    def bitmax(self):
        return self._bitmax

    @bitmax.setter
    def bitmax(self, new_bitmax):
        self._bitmax = int(new_bitmax)
        assert self._bitmax in (0, 8, 10, 12, 14, 16)

        if self.bitmax > 0:
            logger.warning('New bitmax: %d', self.bitmax)


    @property
    def flush_camera_id(self):
        return self._flush_camera_id

    @flush_camera_id.setter
    def flush_camera_id(self, new_camera_id):
        self._flush_camera_id = int(new_camera_id)


    @property
    def hotpixel_adu_percent(self):
        return self._hotpixel_adu_percent

    @hotpixel_adu_percent.setter
    def hotpixel_adu_percent(self, new_hotpixel_adu_percent):
        self._hotpixel_adu_percent = int(new_hotpixel_adu_percent)


    @property
    def daytime(self):
        return self._daytime

    @daytime.setter
    def daytime(self, new_daytime):
        self._daytime = bool(new_daytime)


    @property
    def reverse(self):
        return self._reverse

    @reverse.setter
    def reverse(self, new_reverse):
        self._reverse = bool(new_reverse)

        if self._exposure_list:
            self._exposure_list = sorted(self._exposure_list, reverse=self._reverse)


    @property
    def capture_profile(self):
        return self._capture_profile

    @capture_profile.setter
    def capture_profile(self, new_capture_profile):
        capture_profile = str(new_capture_profile)
        if capture_profile not in ('auto', 'day', 'night'):
            raise ValueError('Invalid capture profile')
        self._capture_profile = capture_profile


    @property
    def progress_file(self):
        return self._progress_file

    @progress_file.setter
    def progress_file(self, new_progress_file):
        if not new_progress_file:
            self._progress_file = None
            return
        self._progress_file = Path(new_progress_file).resolve()


    @property
    def automation_manifest(self):
        return self._automation_manifest

    @automation_manifest.setter
    def automation_manifest(self, new_manifest):
        if not isinstance(new_manifest, dict):
            raise ValueError('Invalid automation manifest')
        self._automation_manifest = dict(new_manifest)


    def sigint_handler_main(self, signum, frame):
        logger.warning('Caught INT signal, shutting down')

        # set flag for program to stop processes
        self._shutdown = True
        if self.indiclient is not None:
            try:
                self.indiclient.abortCcdExposure()
            except Exception as error:
                logger.warning('Unable to abort the current camera exposure: %s', str(error))


    def _validate_automation_preflight(self, live_capabilities):
        manifest = self.automation_manifest
        if not manifest.get('automation'):
            return

        changes = []
        expected_name = str(manifest.get('expected_camera_name') or '')
        expected_driver = str(manifest.get('expected_camera_driver') or '')
        if expected_name and self.camera_name != expected_name:
            changes.append('camera identity')
        if expected_driver and self.camera_server != expected_driver:
            changes.append('camera driver')
        if (
                manifest.get('capability_signature')
                and live_capabilities.signature != manifest.get('capability_signature')
        ):
            changes.append('camera capabilities')
        live_capture_state = build_effective_capture_state(
            self.config,
            live_capabilities,
            exposure_max=manifest.get('exposure_max'),
            exposure_step=manifest.get('exposure_step', 5.0),
        )
        if (
                manifest.get('config_signature')
                and live_capture_state.config_signature != manifest.get('config_signature')
        ):
            changes.append('camera settings')

        if not changes:
            return

        self._publish_progress(
            'review_required',
            'Live {0:s} changed after the plan was prepared. Review the revised plan; no dark frames were taken.'.format(
                ', '.join(changes),
            ),
        )
        raise DarkCapturePlanChanged(', '.join(changes))


    def _initialize(self):
        camera_interface = getattr(camera_module, self.config.get('CAMERA_INTERFACE', 'indi'))


        # instantiate the client
        self.indiclient = camera_interface(
            self.config,
            self.image_q,
            self.position_av,
            self.exposure_av,
            self.gain_av,
            self.binning_av,
            self.night_av,
        )


        # set indi server localhost and port
        self.indiclient.setServer(self.config['INDI_SERVER'], self.config['INDI_PORT'])

        # connect to indi server
        logger.info("Connecting to indiserver")
        if not self.indiclient.connectServer():
            logger.error("No indiserver running on %s:%d - Try to run", self.indiclient.getHost(), self.indiclient.getPort())
            logger.error("  indiserver indi_simulator_telescope indi_simulator_ccd")
            sys.exit(1)

        # give devices a chance to register
        time.sleep(8)


        try:
            self.indiclient.findCcd(camera_name=self.config.get('INDI_CAMERA_NAME'))
        except CameraException as e:
            logger.error('Camera error: %s', str(e))
            sys.exit(1)


        if not self.indiclient.ccd_device:
            logger.error('No CCDs detected')
            time.sleep(1)
            sys.exit(1)


        logger.warning('Connecting to device %s', self.indiclient.ccd_device.getDeviceName())
        self.indiclient.connectDevice(self.indiclient.ccd_device.getDeviceName())

        # add driver name to config
        self.camera_name = self.indiclient.ccd_device.getDeviceName()
        self.camera_server = self.indiclient.ccd_device.getDriverExec()


        # Get Properties
        ccd_properties = self.indiclient.getCcdDeviceProperties()
        self.config['CCD_PROPERTIES'] = ccd_properties


        # get CCD information
        ccd_info = self.indiclient.getCcdInfo()
        self.ccd_info = ccd_info
        live_capabilities = CameraCapabilities.from_ccd_info(ccd_info)


        if self.config.get('CFA_PATTERN'):
            cfa_pattern = self.config['CFA_PATTERN']
        else:
            cfa_pattern = ccd_info['CCD_CFA']['CFA_TYPE'].get('text')


        ccd_min_exp = math.ceil(float(ccd_info['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['min']) * 1000000) / 1000000
        ccd_max_exp = math.floor(float(ccd_info['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['max']) * 1000000) / 1000000

        ccd_min_gain = math.ceil(float(ccd_info['GAIN_INFO']['min']) * 1000) / 1000  # round up the thousands spot
        ccd_max_gain = math.floor(float(ccd_info['GAIN_INFO']['max']) * 1000) / 1000  # round down

        ccd_min_binning = int(ccd_info['BINNING_INFO']['min'])
        ccd_max_binning = int(ccd_info['BINNING_INFO']['max'])


        # need to get camera info before adding to DB
        camera_metadata = {
            'type'        : constants.CAMERA,
            'name'        : self.camera_name,
            'driver'      : self.camera_server,

            'hidden'      : False,  # unhide camera

            'minExposure' : ccd_min_exp,
            'maxExposure' : ccd_max_exp,
            'minGain'     : ccd_min_gain,
            'maxGain'     : ccd_max_gain,
            'minBinning'  : ccd_min_binning,
            'maxBinning'  : ccd_max_binning,

            'width'       : int(ccd_info.get('CCD_FRAME', {}).get('WIDTH', {}).get('max')),
            'height'      : int(ccd_info.get('CCD_FRAME', {}).get('HEIGHT', {}).get('max')),
            'bits'        : int(ccd_info.get('CCD_INFO', {}).get('CCD_BITSPERPIXEL', {}).get('current')),
            'pixelSize'   : float(ccd_info.get('CCD_INFO', {}).get('CCD_PIXEL_SIZE', {}).get('current')),
            'cfa'         : constants.CFA_STR_MAP[cfa_pattern],

            'location'    : self.config['LOCATION_NAME'],
            'latitude'    : self.position_av[constants.POSITION_LATITUDE],
            'longitude'   : self.position_av[constants.POSITION_LONGITUDE],
            'elevation'   : int(self.position_av[constants.POSITION_ELEVATION]),

            'owner'           : self.config['OWNER'],
            'lensName'        : self.config['LENS_NAME'],
            'lensFocalLength' : self.config['LENS_FOCAL_LENGTH'],
            'lensFocalRatio'  : self.config['LENS_FOCAL_RATIO'],
            'lensImageCircle' : self.config['LENS_IMAGE_CIRCLE'],
            'lensOffsetX'     : self.config.get('LENS_OFFSET_X', 0),
            'lensOffsetY'     : self.config.get('LENS_OFFSET_Y', 0),

            'alt'             : self.config['LENS_ALTITUDE'],
            'az'              : self.config['LENS_AZIMUTH'],
            'nightSunAlt'     : self.config['NIGHT_SUN_ALT_DEG'],

            'data'            : {
                'camera_capabilities': live_capabilities.to_dict(),
            },
        }

        db_camera = self._miscDb.addCamera(camera_metadata)


        self.camera_id = db_camera.id
        self.indiclient.camera_id = db_camera.id

        self._validate_automation_preflight(live_capabilities)


        try:
            # Disable debugging
            self.indiclient.disableDebugCcd()
        except TimeOutException:
            logger.warning('Camera does not support debug')

        # set BLOB mode to BLOB_ALSO
        self.indiclient.updateCcdBlobMode()

        self.indiclient.configureCcdDevice(self.indi_config)  # night config by default


        try:
            self.indiclient.setCcdFrameType('FRAME_DARK')
        except TimeOutException:
            # this is an optional step
            # occasionally the CCD_FRAME_TYPE property is not available during initialization
            logger.warning('Unable to set CCD_FRAME_TYPE to Dark')


        # set SQM exposure
        config_sqm_exposure = math.floor(float(self.config.get('CAMERA_SQM', {}).get('EXPOSURE', 10.0) * 1000000)) / 1000000
        self._expUtils.EXPOSURE_SQM = config_sqm_exposure


        logger.info('SQM CCD exposure: %0.6f', self._expUtils.EXPOSURE_SQM)


        ### Validate gain settings
        # prevent python/C float conversion errors
        config_night_gain = math.floor(float(self.config['CCD_CONFIG']['NIGHT']['GAIN']) * 1000) / 1000
        config_moonmode_gain = math.floor(float(self.config['CCD_CONFIG']['MOONMODE']['GAIN']) * 1000) / 1000
        config_day_gain = math.ceil(float(self.config['CCD_CONFIG']['DAY']['GAIN']) * 1000) / 1000
        config_sqm_gain = math.floor(float(self.config.get('CAMERA_SQM', {}).get('GAIN', 10.0)) * 1000) / 1000


        if config_night_gain < ccd_min_gain:
            logger.error('CCD night gain below minimum, changing to %0.3f', ccd_min_gain)
            gain_night = ccd_min_gain
            time.sleep(3)
        elif config_night_gain > ccd_max_gain:
            logger.error('CCD night gain above maximum, changing to %0.3f', ccd_max_gain)
            gain_night = ccd_max_gain
            time.sleep(3)
        else:
            gain_night = config_night_gain


        if config_moonmode_gain < ccd_min_gain:
            logger.error('CCD moon mode gain below minimum, changing to %0.3f', ccd_min_gain)
            gain_moonmode = ccd_min_gain
            time.sleep(3)
        elif config_moonmode_gain > ccd_max_gain:
            logger.error('CCD moon mode gain above maximum, changing to %0.3f', ccd_max_gain)
            gain_moonmode = ccd_max_gain
            time.sleep(3)
        else:
            gain_moonmode = config_moonmode_gain


        if config_day_gain < ccd_min_gain:
            logger.error('CCD day gain below minimum, changing to %0.3f', ccd_min_gain)
            gain_day = ccd_min_gain
            time.sleep(3)
        elif config_day_gain > ccd_max_gain:
            logger.error('CCD day gain above maximum, changing to %0.3f', ccd_max_gain)
            gain_day = ccd_max_gain
            time.sleep(3)
        else:
            gain_day = config_day_gain


        if config_sqm_gain < ccd_min_gain:
            logger.error('CCD sqm gain below minimum, changing to %0.3f', ccd_min_gain)
            gain_sqm = ccd_min_gain
            time.sleep(3)
        elif config_sqm_gain > ccd_max_gain:
            logger.error('CCD sqm gain above maximum, changing to %0.3f', ccd_max_gain)
            gain_sqm = ccd_max_gain
            time.sleep(3)
        else:
            gain_sqm = config_sqm_gain


        self._expUtils.GAIN_CURRENT = gain_day  # just need a valid value
        self._expUtils.GAIN_NEXT = gain_day

        self._expUtils.GAIN_MAX_NIGHT = gain_night
        self._expUtils.GAIN_MAX_MOONMODE = gain_moonmode

        # day is always lowest gain
        self._expUtils.GAIN_MAX_DAY = gain_day
        self._expUtils.GAIN_MIN_DAY = gain_day

        self._expUtils.GAIN_MIN_NIGHT = gain_night
        self._expUtils.GAIN_MIN_MOONMODE = gain_moonmode

        self._expUtils.GAIN_SQM = gain_sqm


        logger.info('Minimum CCD gain: %0.3f (day)', self._expUtils.GAIN_MIN_DAY)
        logger.info('Maximum CCD gain: %0.3f (day)', self._expUtils.GAIN_MAX_DAY)
        logger.info('Minimum CCD gain: %0.3f (night)', self._expUtils.GAIN_MIN_NIGHT)
        logger.info('Maximum CCD gain: %0.3f (night)', self._expUtils.GAIN_MAX_NIGHT)
        logger.info('Minimum CCD gain: %0.3f (moonmode)', self._expUtils.GAIN_MIN_MOONMODE)
        logger.info('Maximum CCD gain: %0.3f (moonmode)', self._expUtils.GAIN_MAX_MOONMODE)
        logger.info('SQM CCD gain: %0.3f', self._expUtils.GAIN_SQM)


        # Validate binning settings
        ccd_min_binning = int(ccd_info['BINNING_INFO']['min'])
        ccd_max_binning = int(ccd_info['BINNING_INFO']['max'])


        if self.config['CCD_CONFIG']['NIGHT']['BINNING'] < ccd_min_binning:
            logger.error('CCD night binning below minimum, changing to %d', ccd_min_binning)
            binning_night = ccd_min_binning
            time.sleep(3)
        elif self.config['CCD_CONFIG']['NIGHT']['BINNING'] > ccd_max_binning:
            logger.error('CCD night binning above maximum, changing to %d', ccd_max_binning)
            binning_night = ccd_max_binning
            time.sleep(3)
        else:
            binning_night = int(self.config['CCD_CONFIG']['NIGHT']['BINNING'])


        if self.config['CCD_CONFIG']['MOONMODE']['BINNING'] < ccd_min_binning:
            logger.error('CCD moonmode binning below minimum, changing to %d', ccd_min_binning)
            binning_moonmode = ccd_min_binning
            time.sleep(3)
        elif self.config['CCD_CONFIG']['MOONMODE']['BINNING'] > ccd_max_binning:
            logger.error('CCD moonmode binning above maximum, changing to %d', ccd_max_binning)
            binning_moonmode = ccd_max_binning
            time.sleep(3)
        else:
            binning_moonmode = int(self.config['CCD_CONFIG']['MOONMODE']['BINNING'])


        if self.config['CCD_CONFIG']['DAY']['BINNING'] < ccd_min_binning:
            logger.error('CCD day binning below minimum, changing to %d', ccd_min_binning)
            binning_day = ccd_min_binning
            time.sleep(3)
        elif self.config['CCD_CONFIG']['DAY']['BINNING'] > ccd_max_binning:
            logger.error('CCD day binning above maximum, changing to %d', ccd_max_binning)
            binning_day = ccd_max_binning
            time.sleep(3)
        else:
            binning_day = int(self.config['CCD_CONFIG']['DAY']['BINNING'])


        if self.config.get('CAMERA_SQM', {}).get('BINNING', 1) < ccd_min_binning:
            logger.error('CCD sqm binning below minimum, changing to %d', ccd_min_binning)
            binning_sqm = ccd_min_binning
            time.sleep(3)
        elif self.config.get('CAMERA_SQM', {}).get('BINNING', 1) > ccd_max_binning:
            logger.error('CCD sqm binning above maximum, changing to %d', ccd_max_binning)
            binning_sqm = ccd_max_binning
            time.sleep(3)
        else:
            binning_sqm = int(self.config.get('CAMERA_SQM', {}).get('BINNING', 1))



        self._expUtils.BINNING_DAY = binning_day
        self._expUtils.BINNING_NIGHT = binning_night
        self._expUtils.BINNING_MOONMODE = binning_moonmode
        self._expUtils.BINNING_SQM = binning_sqm


        logger.info('CCD binning: %d (day)', self._expUtils.BINNING_DAY)
        logger.info('CCD binning: %d (night)', self._expUtils.BINNING_NIGHT)
        logger.info('CCD binning: %d (moonmode)', self._expUtils.BINNING_MOONMODE)
        logger.info('CCD binning: %d (SQM)', self._expUtils.BINNING_SQM)


    def shoot(self, exposure, gain, binning, sync=True, timeout=None):
        logger.info('Taking %0.6fs exposure (gain %0.3f / bin %d)', exposure, gain, binning)

        self.indiclient.setCcdExposure(exposure, gain, binning, sync=sync, timeout=timeout)


    def _wait_for_image(self, exposure):
        from astropy.io import fits

        i_dict = self.image_q.get(timeout=10)

        ### Not using DB task queue for image processing to reduce database I/O
        #task_id = i_dict['task_id']

        #try:
        #    task = IndiAllSkyDbTaskQueueTable.query\
        #        .filter(IndiAllSkyDbTaskQueueTable.id == task_id)\
        #        .filter(IndiAllSkyDbTaskQueueTable.state == TaskQueueState.QUEUED)\
        #        .filter(IndiAllSkyDbTaskQueueTable.queue == TaskQueueQueue.IMAGE)\
        #        .one()

        #except NoResultFound:
        #    logger.error('Task ID %d not found', task_id)
        #    raise


        # go ahead and set complete
        #task.setSuccess('Dark frame processed')

        #filename = Path(task.data['filename'])
        ###


        filename_p = Path(i_dict['filename'])

        if not filename_p.exists():
            #task.setFailed('Frame not found: {0:s}'.format(str(filename_p)))
            raise Exception('Frame not found {0:s}'.format(str(filename_p)))


        if filename_p.stat().st_size == 0:
            #task.setFailed('Frame is empty: {0:s}'.format(str(filename_p)))
            raise Exception('Frame is empty: {0:s}'.format(str(filename_p)))



        ### Open file
        if filename_p.suffix in ['.fit']:
            try:
                hdulist = fits.open(filename_p)
            except OSError as e:
                filename_p.unlink()
                raise BadImage(str(e)) from e
        elif filename_p.suffix in ['.jpg', '.jpeg']:
            ### OpenCV
            #data = cv2.imread(str(filename_p), cv2.IMREAD_UNCHANGED)

            #if isinstance(data, type(None)):
            #    raise BadImage('Bad jpeg image')

            #if len(data.shape) == 3:
            #    data = cv2.cvtColor(data, cv2.COLOR_BGR2RGB)  # opencv returns BGR


            ### pillow
            #import PIL
            #from PIL import Image

            #try:
            #    with Image.open(str(filename_p)) as img:
            #        data = numpy.array(img)  # pillow returns RGB
            #except PIL.UnidentifiedImageError:
            #    raise BadImage('Bad jpeg image')


            ### simplejpeg
            import simplejpeg

            try:
                with io.open(str(filename_p), 'rb') as f_img:
                    data = simplejpeg.decode_jpeg(f_img.read(), colorspace='RGB')
            except ValueError as e:
                filename_p.unlink()
                raise BadImage('Bad jpeg image - {0:s}'.format(str(e)))


            if len(data.shape) == 3:
                # swap axes for FITS
                data = numpy.swapaxes(data, 1, 0)
                data = numpy.swapaxes(data, 2, 0)


            # create a new fits container
            hdu = fits.PrimaryHDU(data)
            hdulist = fits.HDUList([hdu])

            hdu.update_header()  # populates BITPIX, NAXIS, etc

            hdulist[0].header['IMAGETYP'] = 'Dark Frame'
            hdulist[0].header['INSTRUME'] = 'jpeg'
            hdulist[0].header['EXPTIME'] = float(exposure)
            hdulist[0].header['XBINNING'] = self._expUtils.BINNING_CURRENT
            hdulist[0].header['YBINNING'] = self._expUtils.BINNING_CURRENT
            hdulist[0].header['GAIN'] = self._expUtils.GAIN_CURRENT
            hdulist[0].header['CCD-TEMP'] = self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP]
            #hdulist[0].header['BITPIX'] = 8
        elif filename_p.suffix in ['.png']:
            # PNGs may be 16-bit, use OpenCV
            data = cv2.imread(str(filename_p), cv2.IMREAD_UNCHANGED)

            if isinstance(data, type(None)):
                filename_p.unlink()
                raise BadImage('Bad png image')


            if len(data.shape) == 3:
                if data.shape[2] == 4:
                    # remove alpha channel
                    data = data[:, :, :3]

                data = cv2.cvtColor(data, cv2.COLOR_BGR2RGB)

                # swap axes for FITS
                data = numpy.swapaxes(data, 1, 0)
                data = numpy.swapaxes(data, 2, 0)


            # create a new fits container
            hdu = fits.PrimaryHDU(data)
            hdulist = fits.HDUList([hdu])

            hdu.update_header()  # populates BITPIX, NAXIS, etc

            hdulist[0].header['IMAGETYP'] = 'Dark Frame'
            hdulist[0].header['INSTRUME'] = 'png'
            hdulist[0].header['EXPTIME'] = float(exposure)
            hdulist[0].header['XBINNING'] = self._expUtils.BINNING_CURRENT
            hdulist[0].header['YBINNING'] = self._expUtils.BINNING_CURRENT
            hdulist[0].header['GAIN'] = self._expUtils.GAIN_CURRENT
            hdulist[0].header['CCD-TEMP'] = self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP]
            #hdulist[0].header['BITPIX'] = 8
        elif filename_p.suffix in ['.dng']:
            if not rawpy:
                filename_p.unlink()
                raise Exception('*** rawpy module not available ***')

            # DNG raw
            try:
                raw = rawpy.imread(str(filename_p))
            except rawpy._rawpy.LibRawIOError as e:
                filename_p.unlink()
                raise BadImage(str(e)) from e

            scidata_uncalibrated = raw.raw_image

            # create a new fits container for DNG data
            hdu = fits.PrimaryHDU(scidata_uncalibrated)
            hdulist = fits.HDUList([hdu])

            hdu.update_header()  # populates BITPIX, NAXIS, etc

            hdulist[0].header['IMAGETYP'] = 'Dark Frame'
            hdulist[0].header['INSTRUME'] = 'libcamera'
            hdulist[0].header['EXPTIME'] = float(exposure)
            hdulist[0].header['XBINNING'] = self._expUtils.BINNING_CURRENT
            hdulist[0].header['YBINNING'] = self._expUtils.BINNING_CURRENT
            hdulist[0].header['GAIN'] = self._expUtils.GAIN_CURRENT
            hdulist[0].header['CCD-TEMP'] = self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP]
            #hdulist[0].header['BITPIX'] = 16

            if self.config.get('CFA_PATTERN'):
                hdulist[0].header['BAYERPAT'] = self.config['CFA_PATTERN']
                hdulist[0].header['XBAYROFF'] = 0
                hdulist[0].header['YBAYROFF'] = 0
            elif self.ccd_info['CCD_CFA']['CFA_TYPE'].get('text'):
                hdulist[0].header['BAYERPAT'] = self.ccd_info['CCD_CFA']['CFA_TYPE']['text']
                hdulist[0].header['XBAYROFF'] = 0
                hdulist[0].header['YBAYROFF'] = 0

            #for h in hdulist[0].header.keys():
            #    logger.info('  Header: %s = %s', h, str(hdulist[0].header[h]))
        else:
            raise Exception('Unsupported dark frame source')


        filename_p.unlink()  # no longer need the original file


        return hdulist


    def average(self):
        self.checkAvailableSpace()

        # do *NOT* start workers inside of a flask context
        # doing so will cause TLS/SSL problems connecting to databases

        # sensor worker only need to stop the fan and dew heater
        self._startSensorWorker()
        try:
            with app.app_context():
                self._average()
        finally:
            self._cleanup_capture()


    def _average(self):
        self._initialize()
        self._pre_run_tasks()

        self._run(IndiAllSkyDarksAverage)


    def tempaverage(self):
        self.checkAvailableSpace()

        # do *NOT* start workers inside of a flask context
        # doing so will cause TLS/SSL problems connecting to databases

        # sensor worker only need to stop the fan and dew heater
        self._startSensorWorker()
        try:
            with app.app_context():
                self._tempaverage()
        finally:
            self._cleanup_capture()


    def _tempaverage(self):
        self._run_temperature_series(IndiAllSkyDarksAverage)


    def sigmaclip(self):
        self.checkAvailableSpace()

        # do *NOT* start workers inside of a flask context
        # doing so will cause TLS/SSL problems connecting to databases

        # sensor worker only need to stop the fan and dew heater
        self._startSensorWorker()
        try:
            with app.app_context():
                self._sigmaclip()
        finally:
            self._cleanup_capture()


    def _sigmaclip(self):
        self._initialize()
        self._pre_run_tasks()

        self._run(IndiAllSkyDarksSigmaClip)


    def _cleanup_capture(self):
        try:
            self._stopSensorWorker()
        except Exception as e:
            logger.error('Unable to stop dark-frame sensor worker: %s', str(e))

        if self.indiclient is None:
            return

        try:
            self.indiclient.disableCcdCooler()
        except Exception as e:
            logger.error('Unable to disable the CCD cooler: %s', str(e))

        try:
            self.indiclient.disconnectServer()
        except Exception as e:
            logger.error('Unable to disconnect the camera server: %s', str(e))


    def tempsigmaclip(self):
        self.checkAvailableSpace()

        # do *NOT* start workers inside of a flask context
        # doing so will cause TLS/SSL problems connecting to databases

        # sensor worker only need to stop the fan and dew heater
        self._startSensorWorker()
        try:
            with app.app_context():
                self._tempsigmaclip()
        finally:
            self._cleanup_capture()


    def _tempsigmaclip(self):
        self._run_temperature_series(IndiAllSkyDarksSigmaClip)


    def _run_temperature_series(self, stacking_class):
        # disable daytime darks processing when doing temperature calibrated frames
        self.daytime = False

        self._initialize()

        self._pre_run_tasks()

        current_temperature = self._read_temperature_series_value()
        logger.info('Camera temperature: %0.1f', current_temperature)
        manifest_target = self.automation_manifest.get('temperature_target')
        if manifest_target is not None:
            self.temperature_target = manifest_target
        target_temperature = self.temperature_target
        self._progress_target_temperature = target_temperature
        pending_thresholds = list(_falling_temperature_thresholds(
            current_temperature,
            target_temperature,
            self.temp_delta,
        ))
        self._progress_planned_temperature_sets = (
            None if target_temperature is None else 1 + len(pending_thresholds)
        )
        if target_temperature is None:
            next_temp_thold = current_temperature - self.temp_delta
        elif pending_thresholds:
            next_temp_thold = pending_thresholds[0]
        else:
            next_temp_thold = target_temperature
        temperature_set = 1

        while True:
            self._check_shutdown()
            self._progress_temperature_set = temperature_set
            if (
                    self._progress_planned_temperature_sets is not None
                    and temperature_set > self._progress_planned_temperature_sets
            ):
                self._progress_planned_temperature_sets = temperature_set
            self._progress_temperature_set_started_utc = datetime.now().astimezone().isoformat()
            self._progress_next_temperature = next_temp_thold
            if self.automation_manifest.get('temperature_series'):
                self._revalidate_temperature_series_plan()
                self._run_automation_temperature_set(stacking_class, temperature_set)
            else:
                self._run(stacking_class)
            self._progress_completed_temperature_sets = temperature_set
            captured_temperature = usable_temperature(
                self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP],
            )
            self._progress_current_temperature = captured_temperature
            if (
                    target_temperature is not None
                    and captured_temperature is not None
                    and captured_temperature <= target_temperature + 0.000001
            ):
                self._progress_next_temperature = None
                self._progress_planned_temperature_sets = temperature_set
                self._publish_progress(
                    'complete',
                    'Target sensor temperature {0:0.1f}°C reached after {1:d} temperature set(s).'.format(
                        target_temperature,
                        temperature_set,
                    ),
                )
                return
            self._progress_next_temperature = next_temp_thold
            self._publish_progress(
                'temperature_wait',
                'Temperature set {0:d} complete. Waiting for the camera to cool to {1:0.1f}°C.'.format(
                    temperature_set,
                    next_temp_thold,
                ),
            )

            while True:
                # This loop intentionally runs until the operator cancels.
                self._check_shutdown()
                current_temperature = self._read_temperature_series_value()

                logger.info(
                    'Next temperature threshold: %0.1f (current: %0.1f)',
                    next_temp_thold,
                    current_temperature,
                )

                if current_temperature <= next_temp_thold:
                    break

                self._publish_progress(
                    'temperature_wait',
                    'Waiting for {0:0.1f}°C; camera is {1:0.1f}°C.'.format(
                        next_temp_thold,
                        current_temperature,
                    ),
                )
                self._sleep_interruptibly(30.0)

            logger.warning(
                'Achieved next temperature threshold: %0.1f | %0.1f',
                next_temp_thold,
                self.temp_delta,
            )
            if target_temperature is None:
                next_temp_thold -= self.temp_delta
            elif current_temperature <= target_temperature + 0.000001:
                pending_thresholds = []
                next_temp_thold = target_temperature
            else:
                if pending_thresholds:
                    pending_thresholds.pop(0)
                next_temp_thold = (
                    pending_thresholds[0]
                    if pending_thresholds
                    else target_temperature
                )
            temperature_set += 1


    def _read_temperature_series_value(self):
        wait_for_sensor = bool(
            self.automation_manifest.get('automation')
            and self.automation_manifest.get('temperature_source', TEMPERATURE_SOURCE_AUTO)
            != TEMPERATURE_SOURCE_CAMERA
        )
        deadline = time.monotonic() + (30.0 if wait_for_sensor else 0.0)
        while True:
            self._pre_temperature_action()
            current_temperature = usable_temperature(self.getCcdTemperature())
            if current_temperature is not None:
                self._progress_current_temperature = current_temperature
                return current_temperature
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    'Temperature-series dark capture requires a usable selected temperature source'
                )
            self._check_shutdown()
            self._publish_progress(
                'temperature_wait',
                'Waiting for the selected temperature sensor to report a usable reading.',
            )
            time.sleep(1.0)


    def _revalidate_temperature_series_plan(self):
        with app.app_context():
            self.config = IndiAllSkyConfig().config
        live_ccd_info = self.indiclient.getCcdInfo()
        live_capabilities = CameraCapabilities.from_ccd_info(live_ccd_info)
        self._validate_automation_preflight(live_capabilities)


    def _sleep_interruptibly(self, seconds):
        deadline = time.monotonic() + float(seconds)
        while time.monotonic() < deadline:
            self._check_shutdown()
            time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))


    def _run_automation_temperature_set(self, stacking_class, temperature_set):
        from .dark_automation import STRATEGY_CUSTOM
        from .dark_automation import _activate_generation

        groups = self.automation_manifest.get('groups')
        if not isinstance(groups, list) or not groups:
            raise ValueError('Temperature-series automation requires at least one capture group')

        base_manifest = dict(self.automation_manifest)
        base_generation_id = str(base_manifest.get('generation_id') or '')
        generation_id = '{0:s}-temperature-{1:04d}'.format(
            base_generation_id,
            int(temperature_set),
        )
        total_master_sets = sum(int(group['target_count']) for group in groups)
        completed_offset = 0
        self._progress_total_master_sets = total_master_sets
        self._progress_completed_master_sets = 0

        for group_index, group in enumerate(groups, start=1):
            self._check_shutdown()
            group_manifest = dict(base_manifest)
            group_manifest.update({
                'generation_id': generation_id,
                'group_id': str(group['id']),
                'capture_profile': str(group['capture_profile']),
                'capture_period': str(group['capture_period']),
                'binning': int(group['binning']),
                'bit_depth': group.get('bit_depth'),
                'width': group.get('width'),
                'height': group.get('height'),
                'temperature': group.get('temperature'),
                'gains': list(group['gains']),
                'exposures': list(group['exposures']),
                'temperature_set': int(temperature_set),
            })
            self.automation_manifest = group_manifest
            self.capture_profile = str(group['capture_period'])
            self.binning = int(group['binning'])
            self.bitmax = int(group.get('bitmax') or 0)
            self.gain_list = list(group['gains'])
            self.exposure_list = list(group['exposures'])
            self._run_targeted(
                stacking_class,
                progress_offset=completed_offset,
                progress_total=total_master_sets,
                publish_complete=False,
            )
            completed_offset += int(group['target_count'])
            self._publish_progress(
                'capturing',
                'Completed temperature-set group {0:d} of {1:d}.'.format(
                    group_index,
                    len(groups),
                ),
            )

        self.automation_manifest = base_manifest
        activation_task = {
            'generation_id': generation_id,
            'camera_id': self.camera_id,
            'target_count': total_master_sets,
            'groups': groups,
            'strategy': STRATEGY_CUSTOM,
        }
        _activate_generation(
            db,
            (IndiAllSkyDbDarkFrameTable, IndiAllSkyDbBadPixelMapTable),
            activation_task,
        )
        self._progress_completed_master_sets = total_master_sets
        self._publish_progress(
            'temperature_set_complete',
            'Temperature set {0:d} was captured and activated safely.'.format(
                temperature_set,
            ),
        )


    def _pre_run_tasks(self):
        # Tasks that need to be run before the main program loop

        if self.camera_server in ['indi_rpicam']:
            # Raspberry PI HQ Camera requires an initial throw away exposure of over 6s
            # in order to take exposures longer than 7s
            logger.info('Taking throw away exposure for rpicam')
            self.shoot(7.0, self._expUtils.GAIN_MIN_DAY, 1, sync=True, timeout=20.0)


            i_dict = self.image_q.get(timeout=10)

            ### Not using DB task queue for image processing to reduce database I/O
            #task_id = i_dict['task_id']

            #try:
            #    task = IndiAllSkyDbTaskQueueTable.query\
            #        .filter(IndiAllSkyDbTaskQueueTable.id == task_id)\
            #        .filter(IndiAllSkyDbTaskQueueTable.state == TaskQueueState.QUEUED)\
            #        .filter(IndiAllSkyDbTaskQueueTable.queue == TaskQueueQueue.IMAGE)\
            #        .one()

            #except NoResultFound:
            #    logger.error('Task ID %d not found', task_id)
            #    raise


            ### go ahead and set complete
            #task.setSuccess('Throw away frame')

            #filename = Path(task.data['filename'])
            ###


            filename = Path(i_dict['filename'])

            if not filename.exists():
                #task.setFailed('Frame not found: {0:s}'.format(str(filename)))
                raise Exception('Frame not found {0:s}'.format(str(filename)))


            filename.unlink()  # no longer need the original file


    def _pre_shoot_reconfigure(self):
        if self.camera_server in ['indi_asi_ccd']:
            # There is a bug in the ASI120M* camera that causes exposures to fail on gain changes
            # The indi_asi_ccd server will switch the camera to 8-bit mode to try to correct
            if self.camera_name.startswith('ZWO CCD ASI120'):
                self.indiclient.configureCcdDevice(self.indi_config)
        elif self.camera_server in ['indi_asi_single_ccd']:
            if self.camera_name.startswith('ZWO ASI120'):
                self.indiclient.configureCcdDevice(self.indi_config)


    def _pre_temperature_action(self):
        if self.config['CAMERA_INTERFACE'].startswith('libcamera_') or self.config['CAMERA_INTERFACE'].startswith('mqtt_'):
            # libcamera only reports temperature changes when an exposure is taken
            logger.warning('TAKING THROW AWAY EXPOSURE TO UPDATE TEMPERATURE')
            self.shoot(0.1, self._expUtils.GAIN_MIN_DAY, 1, sync=True, timeout=10.0)
            i_dict = self.image_q.get(timeout=10)
            filename = Path(i_dict['filename'])

            try:
                filename.unlink()
            except FileNotFoundError:
                pass
        elif self.camera_server == 'indi_libcamera_ccd':
            # libcamera only reports temperature changes when an exposure is taken
            logger.warning('TAKING THROW AWAY EXPOSURE TO UPDATE TEMPERATURE')
            self.shoot(0.1, self._expUtils.GAIN_MIN_DAY, 1, sync=True, timeout=10.0)
            i_dict = self.image_q.get(timeout=10)
            filename = Path(i_dict['filename'])

            try:
                filename.unlink()
            except FileNotFoundError:
                pass
        elif 'indi_pylibcamera' in self.camera_server:  # SPECIAL CASE
            # libcamera only reports temperature changes when an exposure is taken
            logger.warning('TAKING THROW AWAY EXPOSURE TO UPDATE TEMPERATURE')
            self.shoot(0.1, self._expUtils.GAIN_MIN_DAY, 1, sync=True, timeout=10.0)
            i_dict = self.image_q.get(timeout=10)
            filename = Path(i_dict['filename'])

            try:
                filename.unlink()
            except FileNotFoundError:
                pass


    @staticmethod
    def _format_time(seconds):
        """Take an integer number of seconds and return a string in the format HH:MM:SS."""
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return "{:02}h:{:02}m:{:02}s".format(int(hours), int(minutes), int(seconds))


    def _estimate_runtime(self, remaining_exposures, remaining_configs, overhead_per_exposure):
        """Estimate the remaining runtime in seconds of the _run function."""

        # Initialize time to zero
        total_time = 0

        # Add the time for each exposure plus overhead.
        total_exposure_time = sum(remaining_exposures) * self.count + len(remaining_exposures) * overhead_per_exposure
        total_time += total_exposure_time * remaining_configs

        return total_time


    def _check_shutdown(self):
        if self._shutdown:
            raise KeyboardInterrupt()


    def _publish_progress(self, phase, message, current_frame=None):
        if self.progress_file is None:
            return

        progress_data = {
            'phase': phase,
            'message': str(message),
            'completed_master_sets': self._progress_completed_master_sets,
            'completed_master_details': list(self._progress_completed_master_details),
            'total_master_sets': self._progress_total_master_sets,
            'current_gain': self._progress_current_gain,
            'current_exposure': self._progress_current_exposure,
            'current_binning': self._progress_current_binning,
            'current_temperature': self._progress_current_temperature,
            'temperature_source': self._progress_temperature_source,
            'next_temperature': self._progress_next_temperature,
            'target_temperature': self._progress_target_temperature,
            'temperature_set': self._progress_temperature_set,
            'planned_temperature_sets': self._progress_planned_temperature_sets,
            'temperature_set_started_utc': self._progress_temperature_set_started_utc,
            'completed_temperature_sets': self._progress_completed_temperature_sets,
            'activated_master_files': self._progress_activated_master_files,
            'capture_profile': self.capture_profile,
            'current_frame': current_frame,
            'current_frame_count': self.count,
            'updated_utc': datetime.now().astimezone().isoformat(),
        }
        self.progress_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary_name = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode='w',
                    encoding='utf-8',
                    dir=self.progress_file.parent,
                    prefix='.dark-progress-',
                    suffix='.tmp',
                    delete=False,
            ) as temporary_file:
                temporary_name = temporary_file.name
                json.dump(progress_data, temporary_file, sort_keys=True)
            os.replace(temporary_name, self.progress_file)
        finally:
            if temporary_name:
                try:
                    Path(temporary_name).unlink()
                except FileNotFoundError:
                    pass


    def _configure_target_profile(self):
        daytime = self.capture_profile == 'day'
        with self.night_av.get_lock():
            self.night_av[constants.NIGHT_NIGHT] = 0 if daytime else 1
            self.night_av[constants.NIGHT_MOONMODE] = 0

        if daytime:
            if (
                    self.config['CAMERA_INTERFACE'].startswith('libcamera_')
                    or self.config['CAMERA_INTERFACE'].startswith('mqtt_')
            ) and self.config.get('LIBCAMERA', {}).get('AWB_ENABLE_DAY'):
                raise RuntimeError('Daytime AWB must be disabled before capturing daytime darks')

            cooling_enabled = self.config.get('CCD_COOLING_DAY')
            cooling_temperature = self.config.get('CCD_TEMP_DAY', 35.0)
            if self.config.get('INDI_CONFIG_DAY', {}):
                self.indi_config = self.config['INDI_CONFIG_DAY']
            else:
                self.indi_config = self.config['INDI_CONFIG_DEFAULTS']
            image_type = self.config.get('LIBCAMERA', {}).get('IMAGE_FILE_TYPE_DAY', 'jpg')
        else:
            if (
                    self.config['CAMERA_INTERFACE'].startswith('libcamera_')
                    or self.config['CAMERA_INTERFACE'].startswith('mqtt_')
            ) and self.config.get('LIBCAMERA', {}).get('AWB_ENABLE'):
                raise RuntimeError('Nighttime AWB must be disabled before capturing darks')

            cooling_enabled = self.config.get('CCD_COOLING')
            cooling_temperature = self.config.get('CCD_TEMP', 15.0)
            self.indi_config = self.config['INDI_CONFIG_DEFAULTS']
            image_type = self.config.get('LIBCAMERA', {}).get('IMAGE_FILE_TYPE', 'jpg')

        if self.config['CAMERA_INTERFACE'].startswith('libcamera_') or self.config['CAMERA_INTERFACE'].startswith('mqtt_'):
            self.indiclient.libcamera_bit_depth = 16 if image_type == 'dng' else 8

        self.indiclient.configureCcdDevice(self.indi_config)
        if cooling_enabled:
            self.indiclient.enableCcdCooler()
            logger.warning('****** WAITING UP TO 20 MINUTES FOR TARGET TEMPERATURE ******')
            self.indiclient.setCcdTemperature(cooling_temperature, sync=True, timeout=1200.0)
        else:
            self.indiclient.disableCcdCooler()
            logger.warning('****** IF THE CCD COOLER WAS ENABLED, WAITING FOR THE SENSOR TO SETTLE ******')
            time.sleep(8.0)


    def _run_targeted(
            self,
            stacking_class,
            progress_offset=0,
            progress_total=None,
            publish_complete=True,
    ):
        if not self.gain_list:
            raise ValueError('Targeted dark capture requires an explicit gain list')
        if not self.exposure_list:
            raise ValueError('Targeted dark capture requires an explicit exposure list')

        self._configure_target_profile()

        bpm_filename_t = 'bpm_ccd{0:d}_{1:d}bit_{2:d}s_gain{3:d}_bin{4:d}_{5:d}c_{6:s}.fit'
        dark_filename_t = 'dark_ccd{0:d}_{1:d}bit_{2:d}s_gain{3:d}_bin{4:d}_{5:d}c_{6:s}.fit'
        group_master_sets = len(self.gain_list) * len(self.exposure_list)
        self._progress_total_master_sets = (
            group_master_sets if progress_total is None else int(progress_total)
        )
        self._progress_completed_master_sets = int(progress_offset)
        self._progress_current_binning = self.binning
        self._publish_progress('capturing', 'Starting targeted dark capture.')

        for gain in self.gain_list:
            for exposure in self.exposure_list:
                self._check_shutdown()
                self._progress_current_gain = gain
                self._progress_current_exposure = exposure
                self._publish_progress(
                    'capturing',
                    'Capturing gain {0:g}, exposure {1:g}s.'.format(gain, exposure),
                    current_frame=0,
                )
                master_started = time.monotonic()
                activation = self._take_exposures(
                    exposure,
                    gain,
                    self.binning,
                    dark_filename_t,
                    bpm_filename_t,
                    stacking_class,
                )
                master_detail = activation.get('master_detail')
                if master_detail:
                    master_detail['duration_seconds'] = round(
                        max(0.0, time.monotonic() - master_started),
                        3,
                    )
                    self._progress_completed_master_details.append(dict(master_detail))
                self._progress_activated_master_files += int(activation['activated'])
                self._progress_completed_master_sets += 1
                self._publish_progress(
                    'capturing',
                    'Completed gain {0:g}, exposure {1:g}s.'.format(gain, exposure),
                )

        self._progress_current_gain = None
        self._progress_current_exposure = None
        self._progress_current_binning = None
        self._progress_current_temperature = None
        if publish_complete:
            self._publish_progress('complete', 'Targeted dark capture complete.')


    def _run(self, stacking_class):
        if self.capture_profile in ('day', 'night'):
            self._run_targeted(stacking_class)
            return

        dark_exposures_set = set()  # prevent duplicate exposures
        dark_exposures_set.add(1.0)  # 1s is the shortest exposure

        x = float(math.ceil(self.config['CCD_EXPOSURE_MAX']))
        while x > 1:
            dark_exposures_set.add(float(int(x)))
            x -= self.time_delta


        dark_exposures = sorted(dark_exposures_set)


        if self.reverse:
            dark_exposures.reverse()  # take longer exposures first


        logger.info('Exposures: %s', ', '.join([str(x) for x in dark_exposures]))


        bpm_filename_t = 'bpm_ccd{0:d}_{1:d}bit_{2:d}s_gain{3:d}_bin{4:d}_{5:d}c_{6:s}.fit'  # filename gain as int
        dark_filename_t = 'dark_ccd{0:d}_{1:d}bit_{2:d}s_gain{3:d}_bin{4:d}_{5:d}c_{6:s}.fit'
        # 0  = ccd id
        # 1  = bits
        # 2  = exposure (seconds)
        # 3  = gain
        # 4  = binning
        # 5  = temperature
        # 6  = date
        # 7  = extension


        night_darks_odict = OrderedDict()  # using OrderedDict as a pseudo-set, we only care about keys
        # keys are a tuple of (gain, binmode)


        if self.gain_list:
            # use CLI values for gain
            self.daytime = False

            for gain in self.gain_list:
                night_darks_odict.update(
                    {
                        (gain, self.binning) : None,
                    }
                )

        else:
            # use config values for gain
            # if NIGHT and MOONMODE have the same parameters, no need to double the work
            night_darks_odict.update(
                {
                    (self._expUtils.GAIN_MAX_NIGHT, self._expUtils.BINNING_NIGHT) : None,
                }
            )
            night_darks_odict.update(
                {
                    (self._expUtils.GAIN_MAX_MOONMODE, self._expUtils.BINNING_MOONMODE) : None,
                }
            )
            night_darks_odict.update(
                {
                    (self._expUtils.GAIN_SQM, self._expUtils.BINNING_SQM) : None,
                }
            )


        ### take darks
        remaining_configs = len(night_darks_odict.keys()) + 1  # include daytime
        overhead_per_exposure = 30.0  # seconds, initial estimate
        completed_exposures = 0


        if self.config['CAMERA_INTERFACE'].startswith('libcamera_') or self.config['CAMERA_INTERFACE'].startswith('mqtt_'):
            if self.config.get('LIBCAMERA', {}).get('AWB_ENABLE_DAY'):
                logger.warning('DAYTIME AWB IS ENABLED.  DISABLING DAYTIME DARKS')
                self.daytime = False


        # take day darks with cooling disabled
        if self.daytime:
            ### DAY
            with self.night_av.get_lock():
                self.night_av[constants.NIGHT_NIGHT] = 0
                self.night_av[constants.NIGHT_MOONMODE] = 0


            # take day darks with cooling enabled
            if self.config.get('CCD_COOLING_DAY'):
                ccd_temp = self.config.get('CCD_TEMP_DAY', 35.0)
                self.indiclient.enableCcdCooler()
                logger.warning('****** WAITING UP TO 20 MINUTES FOR TARGET TEMPERATURE ******')
                self.indiclient.setCcdTemperature(ccd_temp, sync=True, timeout=1200.0)
            else:
                self.indiclient.disableCcdCooler()
                logger.warning('****** IF THE CCD COOLER WAS ENABLED, YOU MAY CONSIDER STOPPING THIS UNTIL THE SENSOR HAS WARMED ******')
                time.sleep(8.0)


            if self.config['CAMERA_INTERFACE'].startswith('libcamera_') or self.config['CAMERA_INTERFACE'].startswith('mqtt_'):
                libcamera_image_type = self.config.get('LIBCAMERA', {}).get('IMAGE_FILE_TYPE_DAY', 'jpg')
                if libcamera_image_type == 'dng':
                    self.indiclient.libcamera_bit_depth = 16
                else:
                    self.indiclient.libcamera_bit_depth = 8


            # update CCD config
            if self.config.get('INDI_CONFIG_DAY', {}):
                self.indi_config = self.config['INDI_CONFIG_DAY']
            else:
                self.indi_config = self.config['INDI_CONFIG_DEFAULTS']

            self.indiclient.configureCcdDevice(self.indi_config)


            ### DAY DARKS ###
            day_params = (self._expUtils.GAIN_MAX_DAY, self._expUtils.BINNING_DAY)
            if day_params not in night_darks_odict.keys():
                total_exposures = len(dark_exposures) * remaining_configs
                estimated_time_left = self._estimate_runtime(dark_exposures, remaining_configs, overhead_per_exposure)
                logger.info(f"Processing {total_exposures} darks, {self.count} exposures each. Estimated time left: {self._format_time(int(estimated_time_left))}")


                # day will rarely exceed 1 second (with good cameras and proper conditions)
                for index, exposure in enumerate(dark_exposures):
                    # Create a temporary list of remaining exposures
                    remaining_exposures = dark_exposures[index + 1:]

                    start = time.time()
                    self._take_exposures(exposure, self._expUtils.GAIN_MAX_DAY, self._expUtils.BINNING_DAY, dark_filename_t, bpm_filename_t, stacking_class)
                    elapsed_s = time.time()
                    exposure_time = elapsed_s - start

                    completed_exposures += 1

                    # Calculate the overhead for this exposure
                    overhead_per_exposure = exposure_time - exposure * float(self.count)
                    estimated_time_left = self._estimate_runtime(remaining_exposures, remaining_configs, overhead_per_exposure)
                    logger.info(f"Exposure {completed_exposures}/{total_exposures} done. Estimated time left: {self._format_time(int(estimated_time_left))}")

                remaining_configs -= 1

            else:
                remaining_configs -= 1  # daytime parameters included in night configs

        else:
            logger.warning('Daytime dark processing is disabled')

            remaining_configs -= 1  # skip daytime

            time.sleep(8.0)



        ### NIGHT
        with self.night_av.get_lock():
            self.night_av[constants.NIGHT_NIGHT] = 1



        if self.config['CAMERA_INTERFACE'].startswith('libcamera_') or self.config['CAMERA_INTERFACE'].startswith('mqtt_'):
            if self.config.get('LIBCAMERA', {}).get('AWB_ENABLE'):
                logger.error('NIGHT AWB IS ENABLED.  CANCELING DARKS.')
                sys.exit(1)


            libcamera_image_type = self.config.get('LIBCAMERA', {}).get('IMAGE_FILE_TYPE', 'jpg')
            if libcamera_image_type == 'dng':
                self.indiclient.libcamera_bit_depth = 16
            else:
                self.indiclient.libcamera_bit_depth = 8


        # update CCD config
        self.indi_config = self.config['INDI_CONFIG_DEFAULTS']
        self.indiclient.configureCcdDevice(self.indi_config)


        total_exposures = len(dark_exposures) * remaining_configs
        estimated_time_left = self._estimate_runtime(dark_exposures, remaining_configs, overhead_per_exposure)
        logger.info(f"Processing {total_exposures} darks, {self.count} exposures each. Estimated time left: {self._format_time(int(estimated_time_left))}")


        # take night darks with cooling enabled
        if self.config.get('CCD_COOLING'):
            ccd_temp = self.config.get('CCD_TEMP', 15.0)
            self.indiclient.enableCcdCooler()
            logger.warning('****** WAITING UP TO 20 MINUTES FOR TARGET TEMPERATURE ******')
            self.indiclient.setCcdTemperature(ccd_temp, sync=True, timeout=1200.0)
        else:
            self.indiclient.disableCcdCooler()
            logger.warning('****** IF THE CCD COOLER WAS ENABLED, YOU MAY CONSIDER STOPPING THIS UNTIL THE SENSOR HAS WARMED ******')
            time.sleep(8.0)


        ### NIGHT DARKS ###
        for gain, binning in night_darks_odict.keys():
            for index, exposure in enumerate(dark_exposures):
                # Create a temporary list of remaining exposures
                remaining_exposures = dark_exposures[index + 1:]

                start = time.time()
                self._take_exposures(exposure, gain, binning, dark_filename_t, bpm_filename_t, stacking_class)
                elapsed_s = time.time()
                exposure_time = elapsed_s - start

                completed_exposures += 1

                # Calculate the overhead for this exposure
                overhead_per_exposure = exposure_time - exposure * float(self.count)
                estimated_time_left = self._estimate_runtime(remaining_exposures, remaining_configs, overhead_per_exposure)
                logger.info(f"Exposure {completed_exposures}/{total_exposures} done. Estimated time left: {self._format_time(int(estimated_time_left))}")

            remaining_configs -= 1


    def _take_exposures(self, exposure, gain, binning, dark_filename_t, bpm_filename_t, stacking_class):
        automation_capture = bool(self.automation_manifest.get('automation'))
        if automation_capture:
            tmp_fit_dir = tempfile.TemporaryDirectory(
                prefix='indi-allsky-dark-source-',
            )
        else:
            # Preserve the legacy CLI's ordinary private temp directory.  The
            # builder's interrupted-run cleanup must never claim this folder.
            tmp_fit_dir = tempfile.TemporaryDirectory()
        tmp_fit_dir_p = Path(tmp_fit_dir.name)

        logger.info('Temp folder: %s', tmp_fit_dir_p)

        image_bitpix = None

        i = 1
        while i <= self.count:
            self._check_shutdown()
            self._publish_progress(
                'capturing',
                'Capturing source frame {0:d} of {1:d} at gain {2:g}, exposure {3:g}s.'.format(
                    i,
                    self.count,
                    gain,
                    exposure,
                ),
                current_frame=i,
            )
            # sometimes image data is bad, take images until we reach the desired number
            logger.info(f"Starting image {i}/{self.count}.")
            start = time.time()

            self._pre_shoot_reconfigure()

            self.shoot(exposure, gain, binning, sync=True, timeout=180.0)  # flat 3 minute timeout

            frame_elapsed = time.time() - start
            frame_delta = frame_elapsed - exposure

            logger.info('Exposure received in %0.4fs (%+0.4fs)', frame_elapsed, frame_delta)

            if frame_delta < 0:
                logger.error('%0.1fs EXPOSURE RECEIVED IN %0.1fs.  POSSIBLE CAMERA PROBLEM.', exposure, frame_elapsed)


            try:
                hdulist = self._wait_for_image(exposure)
            except BadImage as e:
                logger.error('Bad Image: %s', str(e))
                continue


            hdulist[0].header['BUNIT'] = 'ADU'  # hack for ccdproc


            #logger.info('Shape: %s', str(hdulist[0].data.shape))
            if len(hdulist[0].data.shape) == 3:
                # RGB fits data
                image_height, image_width = hdulist[0].data.shape[-2:]
            else:
                # Mono data
                image_height, image_width = hdulist[0].data.shape[:2]

            image_bitpix = hdulist[0].header['BITPIX']


            with tempfile.NamedTemporaryFile(mode='w+b', dir=tmp_fit_dir_p, suffix='.fit', delete=False) as f_tmp_fit:
                hdulist.writeto(f_tmp_fit)


            #logger.info('FIT: %s', f_tmp_fit.name)

            m_avg = numpy.mean(hdulist[0].data)
            logger.info('Image average adu: %0.2f', m_avg)

            measured_temperature = self.getCcdTemperature()
            self._progress_current_temperature = usable_temperature(measured_temperature)
            logger.info('Camera temperature: %0.1f', measured_temperature)
            self._publish_progress(
                'capturing',
                'Captured source frame {0:d} of {1:d} at gain {2:g}, exposure {3:g}s.'.format(
                    i,
                    self.count,
                    gain,
                    exposure,
                ),
                current_frame=i,
            )

            i += 1  # increment


        self._check_shutdown()
        self._publish_progress(
            'stacking',
            'Building the master dark and bad pixel map for gain {0:g}, exposure {1:g}s.'.format(
                gain,
                exposure,
            ),
            current_frame=self.count,
        )

        # libcamera does not know the temperature until the first exposure is taken
        exp_date = datetime.now()
        date_str = exp_date.strftime('%Y%m%d_%H%M%S')
        dark_filename = dark_filename_t.format(
            self.camera_id,
            image_bitpix,
            int(exposure),
            int(self._expUtils.GAIN_CURRENT),  # filename gain as int
            int(self._expUtils.BINNING_CURRENT),
            int(self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP]),
            date_str,
        )
        bpm_filename = bpm_filename_t.format(
            self.camera_id,
            image_bitpix,
            int(exposure),
            int(self._expUtils.GAIN_CURRENT),  # filename gain as int
            int(self._expUtils.BINNING_CURRENT),
            int(self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP]),
            date_str,
        )
        if automation_capture:
            from .dark_automation import automation_master_filename

            dark_filename = automation_master_filename(dark_filename)
            bpm_filename = automation_master_filename(bpm_filename)

        full_dark_filename_p = self.darks_dir.joinpath(dark_filename)
        full_bpm_filename_p = self.darks_dir.joinpath(bpm_filename)


        s = stacking_class(self.config, self.exposure_av, self.gain_av, self.binning_av)
        s.bitmax = self.bitmax
        s.hotpixel_adu_percent = self.hotpixel_adu_percent


        # build dark before BPM
        dark_adu_avg, dark_hot_pixel_count = s.stack(tmp_fit_dir_p, full_dark_filename_p, exposure, image_bitpix)
        bpm_adu_avg, bpm_hot_pixel_count = s.buildBadPixelMap(tmp_fit_dir_p, full_bpm_filename_p, exposure, image_bitpix)


        bpm_metadata = {
            'type'       : constants.BPM_FRAME,
            'createDate' : exp_date.timestamp(),
            'bitdepth'   : image_bitpix,
            'exposure'   : exposure,
            'gain'       : self._expUtils.GAIN_CURRENT,
            'binmode'    : self._expUtils.BINNING_CURRENT,
            'temp'       : usable_temperature(
                self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP],
            ),
            'adu'        : bpm_adu_avg,
            'fileSize'   : full_bpm_filename_p.stat().st_size,
            'height'     : image_height,
            'width'      : image_width,
        }

        bpm_metadata['data'] = {
            'hot_pixels' : int(bpm_hot_pixel_count),
            'count'      : self.count,
            'method'     : str(s),
        }


        dark_metadata = {
            'type'       : constants.DARK_FRAME,
            'createDate' : exp_date.timestamp(),
            'bitdepth'   : image_bitpix,
            'exposure'   : exposure,
            'gain'       : self._expUtils.GAIN_CURRENT,
            'binmode'    : self._expUtils.BINNING_CURRENT,
            'temp'       : usable_temperature(
                self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP],
            ),
            'adu'        : dark_adu_avg,
            'fileSize'   : full_dark_filename_p.stat().st_size,
            'height'     : image_height,
            'width'      : image_width,
        }

        dark_metadata['data'] = {
            'count'      : self.count,
            'hot_pixels' : int(dark_hot_pixel_count),
            #'method'     : stacking_class.__name__,
            'method'     : str(s),
        }

        automation_data = self._automation_frame_data(
            exposure,
            gain,
            binning,
            image_bitpix,
            image_width,
            image_height,
        )
        if automation_data:
            bpm_metadata['data']['dark_automation'] = automation_data
            dark_metadata['data']['dark_automation'] = automation_data
            staged_active = not bool(self.automation_manifest.get('stage_inactive'))
            bpm_metadata['active'] = staged_active
            dark_metadata['active'] = staged_active


        activation = {'activated': 0, 'deactivated': 0}
        if not automation_data:
            # Keep the original CLI persistence path independent: BPM first,
            # one commit per entry, then the dark frame.  No builder rollback,
            # activation, or artifact deletion is involved.
            self._miscDb.addBadPixelMap(
                full_bpm_filename_p.relative_to(self.image_dir),
                self.camera_id,
                bpm_metadata,
            )
            self._miscDb.addDarkFrame(
                full_dark_filename_p.relative_to(self.image_dir),
                self.camera_id,
                dark_metadata,
            )
            tmp_fit_dir.cleanup()
            return activation

        try:
            self._check_shutdown()
            from .dark_automation import checkpoint_master_pair

            bpm_frame = self._miscDb.addBadPixelMap(
                full_bpm_filename_p.relative_to(self.image_dir),
                self.camera_id,
                bpm_metadata,
                commit=False,
                preserve_zero_temperature=True,
            )
            dark_frame = self._miscDb.addDarkFrame(
                full_dark_filename_p.relative_to(self.image_dir),
                self.camera_id,
                dark_metadata,
                commit=False,
                preserve_zero_temperature=True,
            )
            activation = checkpoint_master_pair(
                db,
                (IndiAllSkyDbDarkFrameTable, IndiAllSkyDbBadPixelMapTable),
                (dark_frame, bpm_frame),
                self.automation_manifest,
            )
            db.session.commit()
            activation['master_detail'] = {
                'capture_profile': str(self.capture_profile),
                'gain': float(dark_metadata['gain']),
                'exposure': float(dark_metadata['exposure']),
                'binning': int(dark_metadata['binmode']),
                'temperature': dark_metadata['temp'],
                'frame_count': int(self.count),
                'temperature_set': self.automation_manifest.get('temperature_set'),
                'completed_utc': datetime.now().astimezone().isoformat(),
            }
        except BaseException:
            db.session.rollback()
            for output_path in (full_dark_filename_p, full_bpm_filename_p):
                try:
                    output_path.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    logger.exception('Unable to discard incomplete dark artifact: %s', output_path)
            raise
        finally:
            tmp_fit_dir.cleanup()

        return activation


    def _automation_frame_data(
            self,
            exposure,
            gain,
            binning,
            bit_depth,
            width,
            height,
    ):
        manifest = self.automation_manifest
        if not manifest.get('automation'):
            return {}
        staged = bool(manifest.get('stage_inactive'))
        return {
            'task_id': manifest.get('task_id'),
            'generation_id': manifest.get('generation_id'),
            'group_id': manifest.get('group_id'),
            'config_signature': manifest.get('config_signature'),
            'plan_signature': manifest.get('plan_signature'),
            'capability_signature': manifest.get('capability_signature'),
            'strategy': manifest.get('strategy'),
            'quality': manifest.get('quality'),
            'method': manifest.get('method'),
            'frame_count': manifest.get('frame_count'),
            'capture_profile': manifest.get('capture_profile'),
            'capture_period': manifest.get('capture_period'),
            'temperature_range': manifest.get('temperature_range'),
            'temperature_delta': manifest.get('temperature_delta'),
            'temperature_set': manifest.get('temperature_set'),
            'temperature_source': manifest.get('temperature_source', TEMPERATURE_SOURCE_AUTO),
            'temperature_source_label': self._progress_temperature_source,
            'eligibility': {
                'state': 'staged' if staged else 'active',
                'reason': 'capture_staging' if staged else 'capture_completed',
                'source': 'automation',
            },
            'target': {
                'gain': float(gain),
                'exposure': float(exposure),
                'binning': int(binning),
                'bit_depth': int(bit_depth),
                'width': int(width),
                'height': int(height),
                'temperature': manifest.get('temperature'),
            },
        }


    def flush(self):
        with app.app_context():
            self._flush()


    def _flush(self):
        try:
            flush_camera = IndiAllSkyDbCameraTable.query\
                .filter(IndiAllSkyDbCameraTable.id == self.flush_camera_id)\
                .one()
        except NoResultFound:
            logger.error('Camera ID %d not found', self.flush_camera_id)
            sys.exit(1)


        badpixelmaps = IndiAllSkyDbBadPixelMapTable.query\
            .join(IndiAllSkyDbBadPixelMapTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == flush_camera.id)

        dark_frames = IndiAllSkyDbDarkFrameTable.query\
            .join(IndiAllSkyDbDarkFrameTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == flush_camera.id)


        logger.warning('Found %d bad pixel maps to flush', badpixelmaps.count())
        logger.warning('Found %d dark frames to flush', dark_frames.count())


        if badpixelmaps.count() == 0 and dark_frames.count() == 0:
            logger.error('No dark frames found for camera "%s"', flush_camera.name)
            sys.exit(1)


        logger.warning('Flushing camera "%s" darks in 10 seconds...', flush_camera.name)
        time.sleep(10.0)


        for bpm_entry in badpixelmaps:
            filename = Path(bpm_entry.getFilesystemPath())

            if filename.exists():
                logger.warning('Removing bad pixel map: %s', filename)
                filename.unlink()

            db.session.delete(bpm_entry)


        for dark_frame_entry in dark_frames:
            filename = Path(dark_frame_entry.getFilesystemPath())

            if filename.exists():
                logger.warning('Removing dark frame: %s', filename)
                filename.unlink()

            db.session.delete(dark_frame_entry)


        db.session.commit()


    def getCcdTemperature(self):
        camera_temp = self.indiclient.getCcdTemperature()
        selected_source = str(
            self.automation_manifest.get('temperature_source')
            or TEMPERATURE_SOURCE_AUTO
        )
        sensor_values = {}
        if self.automation_manifest.get('automation'):
            for source in configured_temperature_sources(self.config):
                if not source.slot:
                    continue
                try:
                    sensor_index = int(source.slot.rsplit('_', 1)[1])
                    sensor_values[source.slot] = self.sensors_user_av[sensor_index]
                except (IndexError, ValueError):
                    continue

        reading = resolve_temperature(
            self.config,
            camera_temperature=camera_temp,
            sensor_values=sensor_values,
            source=selected_source,
        )

        if (
                reading is None
                and selected_source in (TEMPERATURE_SOURCE_AUTO, TEMPERATURE_SOURCE_SCRIPT)
                and self.config.get('CCD_TEMP_SCRIPT')
        ):
            try:
                sensor_values[TEMPERATURE_SOURCE_SCRIPT] = self.getExternalTemperature(
                    self.config.get('CCD_TEMP_SCRIPT'),
                )
            except TemperatureException as e:
                logger.error('Exception querying external temperature: %s', str(e))
            reading = resolve_temperature(
                self.config,
                camera_temperature=camera_temp,
                sensor_values=sensor_values,
                source=selected_source,
            )

        if reading is None:
            temp_val_f = float(camera_temp)
            self._progress_temperature_source = None
        else:
            temp_val_f = reading.value
            self._progress_temperature_source = reading.source.label

        with self.sensors_temp_av.get_lock():
            self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP] = temp_val_f


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
            with io.open(str(tempjson_name_p), 'r', encoding='utf-8') as tempjson_name_f:
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


    def checkAvailableSpace(self):
        fs_list = psutil.disk_partitions(all=True)

        for fs in fs_list:
            if fs.mountpoint not in ('/tmp'):
                continue

            try:
                disk_usage = psutil.disk_usage(fs.mountpoint)
            except PermissionError as e:
                logger.error('PermissionError: %s', str(e))
                continue


            fs_free_mb = disk_usage.total / 1024.0 / 1024.0
            if fs_free_mb < 600:
                logger.warning('%s filesystem has less than 600MB of available space', fs.mountpoint)
                time.sleep(10)


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


        # disable gpio
        self.config['GENERIC_GPIO']['A_CLASSNAME'] = ''


        # turn off fan
        if self.config['FAN']['CLASSNAME']:
            logger.warning('Disabling FAN')

        self.config['FAN']['LEVEL_DEF'] = 0
        self.config['FAN']['THOLD_ENABLE'] = False


        # turn off dew heater
        # an inverted dew heater will be ACTIVE by default, initilize dew heater and then turn it off
        if self.config['DEW_HEATER']['CLASSNAME']:
            logger.warning('Disabling DEW HEATER')

        self.config['DEW_HEATER']['LEVEL_DEF'] = 0
        self.config['DEW_HEATER']['THOLD_ENABLE'] = False


        self.sensor_worker_idx += 1

        logger.info('Starting Sensor-%d worker', self.sensor_worker_idx)
        self.sensor_worker = SensorWorker(
            self.sensor_worker_idx,
            self.config,
            self.sensor_q,
            self.sensor_error_q,
            self.sensors_temp_av,
            self.sensors_user_av,
            self.night_av,
            self.astro_av,
        )
        self.sensor_worker.start()


    def _stopSensorWorker(self):
        if not self.sensor_worker:
            return

        if not self.sensor_worker.is_alive():
            return

        logger.info('Stopping Sensor worker')

        self.sensor_q.put({'stop' : True})
        self.sensor_worker.join()



class IndiAllSkyDarksProcessor(object):
    def __init__(self, config, exposure_av, gain_av, binning_av):
        self.config = config
        self.exposure_av = exposure_av
        self.gain_av = gain_av
        self.binning_av = binning_av

        self._expUtils = IndiAllSkyExposureUtils(self.config, self.exposure_av, self.gain_av, self.binning_av)

        self._hotpixel_adu_percent = 90

        self._bitmax = 0


    def __repr__(self):
        return NotImplementedError

    def __str__(self):
        return NotImplementedError


    @property
    def bitmax(self):
        return self._bitmax

    @bitmax.setter
    def bitmax(self, new_bitmax):
        self._bitmax = int(new_bitmax)


    @property
    def hotpixel_adu_percent(self):
        return self._hotpixel_adu_percent

    @hotpixel_adu_percent.setter
    def hotpixel_adu_percent(self, new_hotpixel_adu_percent):
        self._hotpixel_adu_percent = int(new_hotpixel_adu_percent)



    def buildBadPixelMap(self, tmp_fit_dir_p, filename_p, exposure, image_bitpix):
        from astropy.io import fits

        logger.info('Building bad pixel map for exposure %0.1fs, gain %0.3f, bin %d', exposure, self._expUtils.GAIN_CURRENT, self._expUtils.BINNING_CURRENT)

        if image_bitpix == 16:
            numpy_type = numpy.uint16
        elif image_bitpix == 8:
            numpy_type = numpy.uint8
        elif image_bitpix == -32:
            numpy_type = numpy.float32
        elif image_bitpix == 32:
            numpy_type = numpy.uint32
        else:
            raise Exception('Unknown bits per pixel')


        dark_data_list = list()
        hdulist = None
        for item in Path(tmp_fit_dir_p).iterdir():
            #logger.info('Found item: %s', item)
            if item.is_file() and item.suffix in ['.fit']:
                #logger.info('Found fit: %s', item)
                hdulist = fits.open(item)
                dark_data_list.append(hdulist[0].data)


        bpm = numpy.zeros(dark_data_list[0].shape, dtype=numpy_type)


        # take the max values of each pixel from each image
        for dark in dark_data_list:
            bpm = numpy.maximum(bpm, dark)


        max_val = numpy.amax(bpm)
        logger.info('Image max value: %0.1f', float(max_val))


        if self.bitmax:
            max_value = (2 ** self.bitmax) - 1
        else:
            if numpy_type in (numpy.float32, numpy.uint32):
                # assume 16bit max
                max_value = (2 ** 16) - 1
            else:
                max_value = (2 ** image_bitpix) - 1


        hot_pixel_thold = int(max_value * (self.hotpixel_adu_percent / 100.0))
        bpm[bpm < hot_pixel_thold] = 0  # filter all values less than max value

        bpm_adu_avg = numpy.mean(bpm)
        logger.info('Master BPM average adu: %0.2f', bpm_adu_avg)


        if len(bpm.shape) == 3:
            # RGB fits data
            hot_pixels = numpy.maximum.reduce([bpm[0], bpm[1], bpm[2]]) > 0
        else:
            # Mono data
            hot_pixels = bpm > 0


        hot_pixel_count = hot_pixels.sum()

        if hot_pixel_count > 50000:
            logger.warning('DETECTED MORE THAN 50000 BAD PIXELS (>%d/%d%% ADU) - MAKE SURE YOUR SENSOR IS COVERED', hot_pixel_thold, self.hotpixel_adu_percent)
        elif hot_pixel_count == 0:
            logger.warning('DETECTED 0 BAD PIXELS (>%d/%d%% ADU) - BITMAX MAY NEED TO BE REDUCED', hot_pixel_thold, self.hotpixel_adu_percent)
        else:
            logger.info('Detected %d bad pixels (>%d/%d%% ADU)', hot_pixel_count, hot_pixel_thold, self.hotpixel_adu_percent)


        hdulist[0].data = bpm

        # reuse the last fits file for the stacked data
        hdulist.writeto(filename_p)

        return bpm_adu_avg, hot_pixel_count


    def stack(self, tmp_fit_dir_p, filename_p, exposure, image_bitpix):
        raise Exception('Must be redefined in sub-class')


class IndiAllSkyDarksAverage(IndiAllSkyDarksProcessor):
    def __repr__(self):
        return 'Average Stacking'

    def __str__(self):
        return 'Average Stacking'


    def stack(self, tmp_fit_dir_p, filename_p, exposure, image_bitpix):
        from astropy.io import fits

        logger.info('Stacking dark frames for exposure %0.1fs, gain %0.3f, bin %d', exposure, self._expUtils.GAIN_CURRENT, self._expUtils.BINNING_CURRENT)

        if image_bitpix == 16:
            numpy_type = numpy.uint16
            cast_type = numpy.uint32
        elif image_bitpix == 8:
            numpy_type = numpy.uint8
            cast_type = numpy.uint16
        elif image_bitpix == -32:
            numpy_type = numpy.float32
            cast_type = numpy.float32
        elif image_bitpix == 32:
            numpy_type = numpy.uint32
            cast_type = numpy.float32
        else:
            raise Exception('Unknown bits per pixel')

        dark_data_list = list()
        hdulist = None
        for item in Path(tmp_fit_dir_p).iterdir():
            #logger.info('Found item: %s', item)
            if item.is_file() and item.suffix in ('.fit',):
                #logger.info('Found fit: %s', item)
                hdulist = fits.open(item)
                dark_data_list.append(hdulist[0].data.astype(cast_type))

        #logger.info('Dark images found: %d', len(dark_data_list))

        start = time.time()

        avg_data = (numpy.sum(dark_data_list, axis=0) / len(dark_data_list)).astype(numpy_type)
        #logger.info('Avg dims: %s', str(avg_data.shape))

        validate_dark_master_data(avg_data)

        elapsed_s = time.time() - start
        logger.info('Exposure average stacked in %0.4f s', elapsed_s)

        dark_adu_avg = numpy.mean(avg_data)
        logger.info('Master Dark average adu: %0.2f', dark_adu_avg)


        if self.bitmax:
            max_value = (2 ** self.bitmax) - 1
        else:
            if numpy_type in (numpy.float32, numpy.uint32):
                # assume 16bit max
                max_value = (2 ** self.bitmax) - 1
            else:
                max_value = (2 ** image_bitpix) - 1


        hot_pixel_thold = int(max_value * (30 / 100))

        if len(avg_data.shape) == 3:
            # RGB fits data
            hot_pixels = numpy.maximum.reduce([avg_data[0], avg_data[1], avg_data[2]]) > hot_pixel_thold
        else:
            # Mono data
            hot_pixels = avg_data > hot_pixel_thold

        hot_pixel_count = hot_pixels.sum()

        if hot_pixel_count > 50000:
            logger.warning('DETECTED MORE THAN 50000 HOT PIXELS (>%d/%d%% ADU) - MAKE SURE YOUR SENSOR IS COVERED', hot_pixel_thold, 30)
        elif hot_pixel_count == 0:
            logger.warning('DETECTED 0 HOT PIXELS (>%d/%d%% ADU)', hot_pixel_thold, 30)
        else:
            logger.info('Detected %d hot pixels (>%d/%d%% ADU)', hot_pixel_count, hot_pixel_thold, 30)

        hdulist[0].data = avg_data

        # reuse the last fits file for the stacked data
        hdulist.writeto(filename_p)

        return dark_adu_avg, hot_pixel_count


class IndiAllSkyDarksSigmaClip(IndiAllSkyDarksProcessor):
    def __repr__(self):
        return 'Sigma Clipping'

    def __str__(self):
        return 'Sigma Clipping'


    def stack(self, tmp_fit_dir_p, filename_p, exposure, image_bitpix):
        from astropy.io import fits
        from astropy.stats import mad_std
        import ccdproc

        logger.info('Stacking dark frames for exposure %0.1fs, gain %0.3f, bin %d', exposure, self._expUtils.GAIN_CURRENT, self._expUtils.BINNING_CURRENT)

        if image_bitpix == 16:
            numpy_type = numpy.uint16
        elif image_bitpix == 8:
            numpy_type = numpy.uint8
        elif image_bitpix == -32:
            numpy_type = numpy.float32
        elif image_bitpix == 32:
            numpy_type = numpy.uint32
        else:
            raise Exception('Unknown bits per pixel')

        dark_images = ccdproc.ImageFileCollection(tmp_fit_dir_p)
        #logger.info('Full dark count: %d', len(dark_images.files))

        # indi_pylibcamera reports slightly lower than the expected exposure values which cause the filter to exclude them
        #dark_images_filtered = dark_images.files_filtered(exptime=exposure, include_path=True)
        #logger.info('Filtered dark count: %d', len(dark_images_filtered))

        dark_images_files = [str(tmp_fit_dir_p.joinpath(x)) for x in dark_images.files]


        start = time.time()

        try:
            combined_dark = ccdproc.combine(
                dark_images_files,
                method='average',
                sigma_clip=True,
                sigma_clip_low_thresh=5,
                sigma_clip_high_thresh=5,
                sigma_clip_func=numpy.ma.median,
                signma_clip_dev_func=mad_std,
                dtype=numpy_type,
                mem_limit=350000000,
            )
        except ValueError as e:
            logger.error('ValueError: %s', str(e))
            logger.error('Performing sigma clipping stacking on RGB data is the most common cause of this error, use "average" instead')
            sys.exit(1)

        elapsed_s = time.time() - start
        logger.info('Exposure sigma clip stacked in %0.4f s', elapsed_s)


        combined_dark.meta['combined'] = True

        validate_dark_master_data(combined_dark[0].data)


        dark_adu_avg = numpy.mean(combined_dark[0].data)
        logger.info('Master Dark average adu: %0.2f', dark_adu_avg)


        combined_dark.write(filename_p)


        # counting hot pixels does not work on the data before being written to the file, I have no idea why
        # re-reading file to count hot pixels
        dark_from_file = fits.open(filename_p)


        if self.bitmax:
            max_value = (2 ** self.bitmax) - 1
        else:
            if numpy_type in (numpy.float32, numpy.uint32):
                # assume 16bit max
                max_value = (2 ** 16) - 1
            else:
                max_value = (2 ** image_bitpix) - 1


        hot_pixel_thold = int(max_value * (30 / 100))

        # Mono data
        hot_pixels = dark_from_file[0].data > hot_pixel_thold
        hot_pixel_count = hot_pixels.sum()  # this is not working correctly for some reason

        if hot_pixel_count > 50000:
            logger.warning('DETECTED MORE THAN 50000 HOT PIXELS (>%d/%d%% ADU) - MAKE SURE YOUR SENSOR IS COVERED', hot_pixel_thold, 30)
        elif hot_pixel_count == 0:
            logger.warning('DETECTED 0 HOT PIXELS (>%d/%d%% ADU)', hot_pixel_thold, 30)
        else:
            logger.info('Detected %d hot pixels (>%d/%d%% ADU)', hot_pixel_count, hot_pixel_thold, 30)


        return dark_adu_avg, hot_pixel_count

