#!/usr/bin/env python3
##################################################################
# This script applies the camera configuration and takes several #
# test exposures to validate the camera is working               #
##################################################################

import sys
from pathlib import Path
import argparse
import platform
import io
import time
import math
from decimal import Decimal
import psutil
import ctypes
import logging

import queue
from multiprocessing import Queue
from multiprocessing import Array
from sqlalchemy import or_
from sqlalchemy.orm.exc import NoResultFound


sys.path.append(str(Path(__file__).parent.absolute().parent))


from indi_allsky import constants
from indi_allsky.flask import create_app
from indi_allsky.config import IndiAllSkyConfig
from indi_allsky import camera as camera_module
from indi_allsky.utils import IndiAllSkyExposureUtils
from indi_allsky.version import __version__
from indi_allsky.version import __config_level__

from indi_allsky.flask.models import IndiAllSkyDbCameraTable

from indi_allsky.exceptions import TimeOutException
from indi_allsky.exceptions import CameraException


# setup flask context for db access
app = create_app()
app.app_context().push()


logger = logging.getLogger('indi_allsky')
logger.setLevel(logging.INFO)

LOG_FORMATTER_STREAM = logging.Formatter('[%(levelname)s]: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)
logger.addHandler(LOG_HANDLER_STREAM)


class CameraTest(object):

    def __init__(self):
        try:
            self._config_obj = IndiAllSkyConfig()
            #logger.info('Loaded config id: %d', self._config_obj.config_id)
        except NoResultFound:
            logger.error('No config file found, please import a config')
            sys.exit(1)

        self.config = self._config_obj.config

        self.indi_config = self.config.get('INDI_CONFIG_DEFAULTS', {})

        self.image_q = Queue()
        self.image_error_q = Queue()


        self.night = False
        self.moonmode = False

        # These shared values are to indicate when the camera is in night/moon modes
        self.night_av = Array('i', [
            -1,  # night, bogus initial value
            -1,  # moonmode, bogus initial value
        ])


        ### all values in microseconds
        self.exposure_av = Array(ctypes.c_int32, [
            -1,  # current exposure
            -1,  # next exposure
            -1,  # exposure delta
            -1,  # night minimum
            -1,  # day minimum
            -1,  # maximum
            -1,  # sqm
        ])


        ### milli-gain
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


        self.position_av = Array('f', [
            float(self.config['LOCATION_LATITUDE']),
            float(self.config['LOCATION_LONGITUDE']),
            float(self.config.get('LOCATION_ELEVATION', 300)),
            0.0,  # Ra
            0.0,  # Dec
        ])


        self._expUtils = IndiAllSkyExposureUtils(self.config, self.exposure_av, self.gain_av, self.binning_av)


        #self._camera_id = 0


    #@property
    #def camera_id(self):
    #    return self._camera_id

    #@camera_id.setter
    #def camera_id(self, new_camera_id):
    #    self._camera_id = int(new_camera_id)


    def main(self):
        self._startup()

        self._initialize()


        logger.warning('TESTING %0.6fs EXPOSURE WITH DAY SETTINGS', self._expUtils.EXPOSURE_MIN_DAY)
        self.night = False
        self.moonmode = False
        self.reconfigureCcd()

        self.takeExposure(self._expUtils.EXPOSURE_MIN_DAY, self._expUtils.GAIN_MAX_DAY, self._expUtils.BINNING_DAY)


        logger.warning('TESTING 1.0s EXPOSURE WITH NIGHT SETTINGS')
        self.night = True
        self.moonmode = False
        self.reconfigureCcd()

        self.takeExposure(1.0, self._expUtils.GAIN_MAX_NIGHT, self._expUtils.BINNING_NIGHT)


        logger.warning('TESTING 1.0s EXPOSURE WITH MOON MODE SETTINGS')
        self.night = True
        self.moonmode = True
        self.reconfigureCcd()

        self.takeExposure(1.0, self._expUtils.GAIN_MAX_MOONMODE, self._expUtils.BINNING_MOONMODE)


        logger.warning('TESTING 1.0s EXPOSURE WITH SQM SETTINGS')
        self.night = True
        self.moonmode = True
        self.reconfigureCcd()

        self.takeExposure(1.0, self._expUtils.GAIN_SQM, self._expUtils.BINNING_SQM)


    def takeExposure(self, exposure, gain, binning):
        frame_start_time = time.time()

        self.shoot(exposure, gain, binning, sync=False)


        while True:
            time.sleep(0.1)

            # not needed for indi
            # libcamera uses this to add image to queue
            camera_ready, exposure_state = self.indiclient.getCcdExposureStatus()

            try:
                i_dict = self.image_q.get(False)
                break  # end the loop
            except queue.Empty:
                pass


            now_time = time.time()
            if now_time - frame_start_time > 10:
                logger.error('Frame not received in 10 seconds')
                sys.exit(1)


        filename_p = Path(i_dict['filename'])
        if not filename_p.exists():
            logger.error('Frame not found: %s', filename_p)
            sys.exit(1)


        if filename_p.stat().st_size == 0:
            logger.error('Frame is empty: %s', filename_p)


        frame_end_time = time.time() - frame_start_time
        logger.info('%0.6fs second exposure received in %0.6fs', exposure, frame_end_time)

        filename_p.unlink()


    def shoot(self, exposure, gain, binning, sync=True, timeout=None):
        logger.info('Taking %0.6fs exposure (gain %0.3f / bin %d)', exposure, gain, binning)

        self.indiclient.setCcdExposure(exposure, gain, binning, sync=sync, timeout=timeout)


    def _startup(self):
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
            host = self.indiclient.getHost()
            port = self.indiclient.getPort()

            logger.error("No indiserver available at %s:%d", host, port)
            sys.exit(1)


        # give devices a chance to register
        time.sleep(5)

        try:
            self.indiclient.findCcd(camera_name=self.config.get('INDI_CAMERA_NAME'))
        except CameraException as e:
            logger.error('Camera error: !!! %s !!!', str(e).upper())

            time.sleep(60)
            raise


        logger.warning('Connecting to CCD device %s', self.indiclient.ccd_device.getDeviceName())
        self.indiclient.connectDevice(self.indiclient.ccd_device.getDeviceName())


        camera_name = self.indiclient.ccd_device.getDeviceName()

        try:
            # not catching MultipleResultsFound
            camera = IndiAllSkyDbCameraTable.query\
                .filter(
                    or_(
                        IndiAllSkyDbCameraTable.name == camera_name,
                        IndiAllSkyDbCameraTable.name_alt1 == camera_name,
                        IndiAllSkyDbCameraTable.name_alt2 == camera_name,
                    )
                )\
                .one()
        except NoResultFound:
            logger.error('Camera not found in database: %s', camera_name)
            sys.exit(1)


        # configuration needs to be performed before getting CCD_INFO
        self.indiclient.configureCcdDevice(self.indi_config)  # night config by default


        self.indiclient.camera_id = camera.id


        try:
            # Disable debugging
            self.indiclient.disableDebugCcd()
        except TimeOutException:
            logger.warning('Camera does not support debug')


        # set BLOB mode to BLOB_ALSO
        self.indiclient.updateCcdBlobMode()


        try:
            self.indiclient.setCcdFrameType('FRAME_LIGHT')  # default frame type is light
        except TimeOutException:
            # this is an optional step
            # occasionally the CCD_FRAME_TYPE property is not available during initialization
            logger.warning('Unable to set CCD_FRAME_TYPE to Light')


        try:
            self.indiclient.setCcdScopeInfo(camera.lensFocalLength, camera.lensFocalRatio)
        except TimeOutException:
            logger.warning('Unable to set SCOPE_INFO')


        # get CCD information
        ccd_info = self.indiclient.getCcdInfo()


        # set minimum exposure
        ccd_min_exp = Decimal('{0:0.6f}'.format(math.ceil(float(ccd_info['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['min']) * 1000000) / 1000000))
        ccd_max_exp = Decimal('{0:0.6f}'.format(math.floor(float(ccd_info['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['max']) * 1000000) / 1000000))


        #ccd_min_exp = float(ccd_info['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['min'])

        # Some CCD drivers will not accept their stated minimum exposure.
        # There might be some python -> C floating point conversion problem causing this.
        #ccd_min_exp += 0.00000001


        config_exposure_min_day = Decimal('{0:0.6f}'.format(math.ceil(float(self.config.get('CCD_EXPOSURE_MIN_DAY', 0.0) * 1000000) / 1000000)))
        #config_exposure_min = Decimal('{0:0.6f}'.format(math.ceil(float(self.config.get('CCD_EXPOSURE_MIN', 0.0) * 1000000) / 1000000)))
        config_exposure_max = Decimal('{0:0.6f}'.format(math.floor(float(self.config.get('CCD_EXPOSURE_MAX', 15.0) * 1000000) / 1000000)))
        config_sqm_exposure = Decimal('{0:0.6f}'.format(math.floor(float(self.config.get('CAMERA_SQM', {}).get('EXPOSURE', 10.0) * 1000000) / 1000000)))


        if not self.config.get('CCD_EXPOSURE_MIN_DAY'):
            self._expUtils.EXPOSURE_MIN_DAY = ccd_min_exp
        elif self.config.get('CCD_EXPOSURE_MIN_DAY') > ccd_min_exp:
            self._expUtils.EXPOSURE_MIN_DAY = config_exposure_min_day
        elif self.config.get('CCD_EXPOSURE_MIN_DAY') < ccd_min_exp:
            logger.warning(
                'Minimum exposure (day) %0.6f too low, increasing to %0.6f',
                config_exposure_min_day,
                ccd_min_exp,
            )
            self._expUtils.EXPOSURE_MIN_DAY = ccd_min_exp

        logger.info('Minimum CCD exposure: %0.6f (day)', self._expUtils.EXPOSURE_MIN_DAY)


        # set maximum exposure
        if config_exposure_max > ccd_max_exp:
            logger.warning(
                'Maximum exposure %0.6f too high, decreasing to %0.6f',
                config_exposure_max,
                ccd_max_exp,
            )

            maximum_exposure = ccd_max_exp

        else:
            maximum_exposure = config_exposure_max


        self._expUtils.EXPOSURE_MAX = maximum_exposure
        logger.info('Maximum CCD exposure: %0.6f', self._expUtils.EXPOSURE_MAX)


        # set SQM exposure
        if config_sqm_exposure < ccd_min_exp:
            logger.warning(
                'SQM exposure %0.6f too low, increasing to %0.6f',
                config_sqm_exposure,
                ccd_min_exp,
            )

            sqm_exposure = ccd_min_exp

        elif config_sqm_exposure > ccd_max_exp:
            logger.warning(
                'SQM exposure %0.6f too high, decreasing to %0.6f',
                config_sqm_exposure,
                ccd_max_exp,
            )

            sqm_exposure = ccd_max_exp

        else:
            sqm_exposure = config_sqm_exposure


        self._expUtils.EXPOSURE_SQM = sqm_exposure
        logger.info('SQM CCD exposure: %0.6f', self._expUtils.EXPOSURE_SQM)


        # Validate gain settings
        ccd_min_gain = Decimal('{0:0.3f}'.format(math.ceil(float(ccd_info['GAIN_INFO']['min']) * 1000) / 1000))  # round up the thousands spot
        ccd_max_gain = Decimal('{0:0.3f}'.format(math.floor(float(ccd_info['GAIN_INFO']['max']) * 1000) / 1000))  # round down

        config_night_gain = Decimal('{0:0.3f}'.format(math.floor(float(self.config['CCD_CONFIG']['NIGHT']['GAIN']) * 1000) / 1000))
        config_moonmode_gain = Decimal('{0:0.3f}'.format(math.floor(float(self.config['CCD_CONFIG']['MOONMODE']['GAIN']) * 1000) / 1000))
        config_day_gain = Decimal('{0:0.3f}'.format(math.ceil(float(self.config['CCD_CONFIG']['DAY']['GAIN']) * 1000) / 1000))
        config_sqm_gain = Decimal('{0:0.3f}'.format(math.floor(float(self.config.get('CAMERA_SQM', {}).get('GAIN', 10.0)) * 1000) / 1000))


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


        self._expUtils.GAIN_CURRENT = gain_day
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


    def reconfigureCcd(self):
        if self.night:
            self.indi_config = self.config['INDI_CONFIG_DEFAULTS']

            if self.moonmode:
                logger.warning('Change to night (moon mode)')
            else:
                logger.warning('Change to night (normal mode)')


            if self.config['CAMERA_INTERFACE'].startswith('libcamera'):
                libcamera_image_type = self.config.get('LIBCAMERA', {}).get('IMAGE_FILE_TYPE', 'jpg')
                if libcamera_image_type == 'dng':
                    self.indiclient.libcamera_bit_depth = 16
                else:
                    self.indiclient.libcamera_bit_depth = 8
        else:
            logger.warning('Change to day')

            if self.config.get('INDI_CONFIG_DAY', {}):
                self.indi_config = self.config['INDI_CONFIG_DAY']
            else:
                self.indi_config = self.config['INDI_CONFIG_DEFAULTS']


            if self.config['CAMERA_INTERFACE'].startswith('libcamera'):
                libcamera_image_type = self.config.get('LIBCAMERA', {}).get('IMAGE_FILE_TYPE_DAY', 'jpg')
                if libcamera_image_type == 'dng':
                    self.indiclient.libcamera_bit_depth = 16
                else:
                    self.indiclient.libcamera_bit_depth = 8


        # update CCD config
        self.indiclient.configureCcdDevice(self.indi_config)


        ### Update shared values
        with self.night_av.get_lock():
            self.night_av[constants.NIGHT_NIGHT] = int(self.night)
            self.night_av[constants.NIGHT_MOONMODE] = int(self.moonmode)


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()

    args = argparser.parse_args()


    ct = CameraTest()
    ct.main()
