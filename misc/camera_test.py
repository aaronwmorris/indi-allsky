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
import psutil
import logging

import queue
from multiprocessing import Queue
from multiprocessing import Value
from multiprocessing import Array
from sqlalchemy import or_
from sqlalchemy.orm.exc import NoResultFound


sys.path.append(str(Path(__file__).parent.absolute().parent))


from indi_allsky import constants
from indi_allsky.flask import create_app
from indi_allsky.config import IndiAllSkyConfig
from indi_allsky import camera as camera_module
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

        self.night_v = Value('i', -1)  # bogus initial value
        self.moonmode_v = Value('i', -1)  # bogus initial value


        self.exposure_av = Array('f', [
            -1.0,  # current exposure
            -1.0,  # next exposure
            -1.0,  # night minimum
            -1.0,  # day minimum
            -1.0,  # maximum
        ])


        self.gain_av = Array('f', [
            -1.0,  # current gain
            -1.0,  # next gain
            -1.0,  # day minimum
            -1.0,  # day maximum
            -1.0,  # night minimum
            -1.0,  # night maximum
            -1.0,  # moon mode minimum
            -1.0,  # moon mode maximum
        ])


        self.bin_v = Value('i', 1)  # set 1 for sane default


        self.position_av = Array('f', [
            float(self.config['LOCATION_LATITUDE']),
            float(self.config['LOCATION_LONGITUDE']),
            float(self.config.get('LOCATION_ELEVATION', 300)),
            0.0,  # Ra
            0.0,  # Dec
        ])


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


        logger.warning('TESTING 0.1s EXPOSURE WITH DAY SETTINGS')
        self.night = False
        self.moonmode = False
        self.reconfigureCcd()

        self.takeExposure(0.1)


        logger.warning('TESTING 1.0s EXPOSURE WITH NIGHT SETTINGS')
        self.night = True
        self.moonmode = False
        self.reconfigureCcd()

        self.takeExposure(1.0)


        logger.warning('TESTING 1.0s EXPOSURE WITH MOON MODE SETTINGS')
        self.night = True
        self.moonmode = True
        self.reconfigureCcd()

        self.takeExposure(1.0)


    def takeExposure(self, exposure):
        frame_start_time = time.time()

        self.shoot(exposure, sync=False)


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
        logger.info('%0.1fs second exposure received in %0.1fs', exposure, frame_end_time)

        filename_p.unlink()


    def shoot(self, exposure, sync=True, timeout=None):
        logger.info('Taking %0.8f s exposure (gain %0.1f)', exposure, self.gain_av[constants.GAIN_CURRENT])

        self.indiclient.setCcdExposure(exposure, sync=sync, timeout=timeout)


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
            self.bin_v,
            self.night_v,
            self.moonmode_v,
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


        # Validate gain settings
        ccd_min_gain = ccd_info['GAIN_INFO']['min']
        ccd_max_gain = ccd_info['GAIN_INFO']['max']


        if self.config['CCD_CONFIG']['NIGHT']['GAIN'] < ccd_min_gain:
            logger.error('CCD night gain below minimum, changing to %0.1f', float(ccd_min_gain))
            gain_night = float(ccd_min_gain)
            time.sleep(3)
        elif self.config['CCD_CONFIG']['NIGHT']['GAIN'] > ccd_max_gain:
            logger.error('CCD night gain above maximum, changing to %0.1f', float(ccd_max_gain))
            gain_night = float(ccd_max_gain)
            time.sleep(3)
        else:
            gain_night = float(self.config['CCD_CONFIG']['NIGHT']['GAIN'])


        if self.config['CCD_CONFIG']['MOONMODE']['GAIN'] < ccd_min_gain:
            logger.error('CCD moon mode gain below minimum, changing to %01.f', float(ccd_min_gain))
            gain_moonmode = float(ccd_min_gain)
            time.sleep(3)
        elif self.config['CCD_CONFIG']['MOONMODE']['GAIN'] > ccd_max_gain:
            logger.error('CCD moon mode gain above maximum, changing to %0.1f', float(ccd_max_gain))
            gain_moonmode = float(ccd_max_gain)
            time.sleep(3)
        else:
            gain_moonmode = float(self.config['CCD_CONFIG']['MOONMODE']['GAIN'])


        if self.config['CCD_CONFIG']['DAY']['GAIN'] < ccd_min_gain:
            logger.error('CCD day gain below minimum, changing to %0.1f', float(ccd_min_gain))
            gain_day = float(ccd_min_gain)
            time.sleep(3)
        elif self.config['CCD_CONFIG']['DAY']['GAIN'] > ccd_max_gain:
            logger.error('CCD day gain above maximum, changing to %0.1f', float(ccd_max_gain))
            gain_day = float(ccd_max_gain)
            time.sleep(3)
        else:
            gain_day = float(self.config['CCD_CONFIG']['DAY']['GAIN'])


        with self.gain_av.get_lock():
            self.gain_av[constants.GAIN_MIN] = gain_day
            self.gain_av[constants.GAIN_MAX_DAY] = gain_day
            self.gain_av[constants.GAIN_MAX_NIGHT] = gain_night
            self.gain_av[constants.GAIN_MAX_MOONMODE] = gain_moonmode


    def reconfigureCcd(self):
        if self.night:
            self.indi_config = self.config['INDI_CONFIG_DEFAULTS']

            if self.moonmode:
                logger.warning('Change to night (moon mode)')
                self.indiclient.setCcdGain(self.gain_av[constants.GAIN_MAX_MOONMODE])
                self.indiclient.setCcdBinning(self.config['CCD_CONFIG']['MOONMODE']['BINNING'])
            else:
                logger.warning('Change to night (normal mode)')
                self.indiclient.setCcdGain(self.gain_av[constants.GAIN_MAX_NIGHT])
                self.indiclient.setCcdBinning(self.config['CCD_CONFIG']['NIGHT']['BINNING'])


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

            self.indiclient.setCcdGain(self.gain_av[constants.GAIN_MAX_DAY])
            self.indiclient.setCcdBinning(self.config['CCD_CONFIG']['DAY']['BINNING'])


            if self.config['CAMERA_INTERFACE'].startswith('libcamera'):
                libcamera_image_type = self.config.get('LIBCAMERA', {}).get('IMAGE_FILE_TYPE_DAY', 'jpg')
                if libcamera_image_type == 'dng':
                    self.indiclient.libcamera_bit_depth = 16
                else:
                    self.indiclient.libcamera_bit_depth = 8


        # update CCD config
        self.indiclient.configureCcdDevice(self.indi_config)


        ### Update shared values
        with self.night_v.get_lock():
            self.night_v.value = int(self.night)

        with self.moonmode_v.get_lock():
            self.moonmode_v.value = int(self.moonmode)


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()

    args = argparser.parse_args()


    ct = CameraTest()
    ct.main()
