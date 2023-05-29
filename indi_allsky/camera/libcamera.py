import io
from datetime import datetime
from collections import OrderedDict
import time
import tempfile
import json
import subprocess
import psutil
from pathlib import Path
import logging

from .indi import IndiClient
from .fake_indi import FakeIndiCcd

from ..exceptions import TimeOutException


logger = logging.getLogger('indi_allsky')



class IndiClientLibCameraGeneric(IndiClient):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraGeneric, self).__init__(*args, **kwargs)

        self.libcamera_process = None

        self._exposure = None

        self._camera_id = None

        self._ccd_gain = -1
        self._ccd_bin = 1

        self._temp_val = -273.15  # absolute zero  :-)
        self._sensor_temp_metadata_key = 'SensorTemperature'

        self._ccm = None
        self._ccm_metadata_key = 'ColourCorrectionMatrix'

        self._awb_gains = None
        self._awb_gains_metadata_key = 'ColourGains'

        self._black_level = 0
        self._black_level_metadata_key = 'SensorBlackLevels'

        self.active_exposure = False
        self.current_exposure_file_p = None
        self.current_metadata_file_p = None

        memory_info = psutil.virtual_memory()
        self.memory_total_mb = memory_info[0] / 1024.0 / 1024.0


        self.ccd_device_name = 'CHANGEME'
        self.ccd_driver_exec = 'libcamera-still'

        self.camera_info = {
            'width'         : 0,
            'height'        : 0,
            'pixel'         : 0.0,
            'min_gain'      : 0,
            'max_gain'      : 0,
            'min_exposure'  : 0.0,
            'max_exposure'  : 0.0,
            'cfa'           : 'CHANGEME',
            'bit_depth'     : 16,
        }


    @property
    def camera_id(self):
        return self._camera_id

    @camera_id.setter
    def camera_id(self, new_camera_id):
        self._camera_id = int(new_camera_id)


    def getCcdGain(self):
        return self._ccd_gain


    def setCcdGain(self, new_gain_value):
        self._ccd_gain = int(new_gain_value)

        # Update shared gain value
        with self.gain_v.get_lock():
            self.gain_v.value = int(new_gain_value)


    def setCcdBinning(self, new_bin_value):
        if type(new_bin_value) is int:
            new_bin_value = [new_bin_value, new_bin_value]
        elif type(new_bin_value) is str:
            new_bin_value = [int(new_bin_value), int(new_bin_value)]
        elif not new_bin_value:
            # Assume default
            return


        self._ccd_bin = int(new_bin_value[0])

        # Update shared gain value
        with self.bin_v.get_lock():
            self.bin_v.value = int(new_bin_value[0])


    def setCcdExposure(self, exposure, sync=False, timeout=None):
        if self.active_exposure:
            return

        image_type = self.config.get('LIBCAMERA', {}).get('IMAGE_FILE_TYPE', 'dng')

        if image_type == 'dng' and self.memory_total_mb <= 768:
            logger.warning('*** Capturing raw images (dng) with libcamera and less than 1gb of memory can result in out-of-memory errors ***')


        try:
            image_tmp_f = tempfile.NamedTemporaryFile(mode='w', suffix='.{0:s}'.format(image_type), delete=True)
            image_tmp_f.close()
            image_tmp_p = Path(image_tmp_f.name)

            metadata_tmp_f = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=True)
            metadata_tmp_f.close()
            metadata_tmp_p = Path(metadata_tmp_f.name)
        except OSError as e:
            logger.error('OSError: %s', str(e))
            return


        self.current_exposure_file_p = image_tmp_p
        self.current_metadata_file_p = metadata_tmp_p


        self._exposure = exposure

        exposure_us = int(exposure * 1000000)

        if image_type in ['dng']:
            cmd = [
                'libcamera-still',
                '--immediate',
                '--nopreview',
                '--raw',
                '--denoise', 'off',
                '--gain', '{0:d}'.format(self._ccd_gain),
                '--shutter', '{0:d}'.format(exposure_us),
                '--metadata', str(metadata_tmp_p),
                '--metadata-format', 'json',
            ]
        elif image_type in ['jpg', 'png']:
            #logger.warning('RAW frame mode disabled due to low memory resources')
            cmd = [
                'libcamera-still',
                '--immediate',
                '--nopreview',
                '--encoding', '{0:s}'.format(image_type),
                '--quality', '95',
                '--denoise', 'off',
                '--gain', '{0:d}'.format(self._ccd_gain),
                '--shutter', '{0:d}'.format(exposure_us),
                '--metadata', str(metadata_tmp_p),
                '--metadata-format', 'json',
            ]
        else:
            raise Exception('Invalid image type')



        if self.night_v.value:
            #  night

            # Auto white balance, AWB causes long exposure times at night
            if self.config.get('LIBCAMERA', {}).get('AWB_ENABLE'):
                awb = self.config.get('LIBCAMERA', {}).get('AWB', 'auto')
                cmd.extend(['--awb', awb])
            else:
                # awb enabled by default, the following disables
                cmd.extend(['--awbgains', '1,1'])


            # Add extra config options
            extra_options = self.config.get('LIBCAMERA', {}).get('EXTRA_OPTIONS')
            if extra_options:
                cmd.extend(extra_options.split(' '))

        else:
            # daytime

            # Auto white balance, AWB causes long exposure times at night
            if self.config.get('LIBCAMERA', {}).get('AWB_ENABLE_DAY'):
                awb = self.config.get('LIBCAMERA', {}).get('AWB_DAY', 'auto')
                cmd.extend(['--awb', awb])
            else:
                # awb enabled by default, the following disables
                cmd.extend(['--awbgains', '1,1'])


            # Add extra config options
            extra_options = self.config.get('LIBCAMERA', {}).get('EXTRA_OPTIONS_DAY')
            if extra_options:
                cmd.extend(extra_options.split(' '))



        # Finally add output file
        cmd.extend(['--output', str(image_tmp_p)])


        logger.info('image command: %s', ' '.join(cmd))


        self.exposureStartTime = time.time()

        self.libcamera_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        self.active_exposure = True

        if sync:
            try:
                self.libcamera_process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                logger.error('Exposure timeout')
                raise TimeOutException('Timeout waiting for exposure')


            if self.libcamera_process.returncode != 0:
                # log errors
                stdout = self.libcamera_process.stdout
                for line in stdout.readlines():
                    logger.error('libcamera-still error: %s', line)

                # not returning, just log the error

            self.active_exposure = False

            self._processMetadata()

            self._queueImage()


    def getCcdExposureStatus(self):
        # returns camera_ready, exposure_state
        if self._libCameraPidRunning():
            return False, 'BUSY'


        if self.active_exposure:
            # if we get here, that means the camera is finished with the exposure
            self.active_exposure = False


            if self.libcamera_process.returncode != 0:
                # log errors
                stdout = self.libcamera_process.stdout
                for line in stdout.readlines():
                    logger.error('libcamera-still error: %s', line)

                # not returning, just log the error


            self._processMetadata()

            self._queueImage()


        return True, 'READY'


    def _processMetadata(self):
        # read metadata to get sensor temperature
        if self.current_metadata_file_p:
            try:
                with io.open(self.current_metadata_file_p, 'r') as f_metadata:
                    metadata_dict = json.loads(f_metadata.read(), object_pairs_hook=OrderedDict)
            except FileNotFoundError as e:
                logger.error('Metadata file not found: %s', str(e))
                metadata_dict = dict()
            except PermissionError as e:
                logger.error('Permission erro: %s', str(e))
                metadata_dict = dict()
            except json.JSONDecodeError as e:
                logger.error('Error decoding json: %s', str(e))
                metadata_dict = dict()


        #logger.info('Metadata: %s', metadata_dict)


        try:
            self.current_metadata_file_p.unlink()
        except FileNotFoundError:
            pass


        ### Temperature
        try:
            self._temp_val = float(metadata_dict[self._sensor_temp_metadata_key])
        except KeyError:
            logger.error('libcamera sensor temperature key not found')
        except ValueError:
            logger.error('Unable to parse libcamera sensor temperature')


        ### Auto white balance
        # Only return these values when libcamera AWB is enabled
        if self.night_v.value:
            # night
            if self.config.get('LIBCAMERA', {}).get('AWB_ENABLE'):
                try:
                    awb_gains = metadata_dict[self._awb_gains_metadata_key]
                    self._awb_gains = [awb_gains[0], awb_gains[1]]
                except KeyError:
                    logger.error('libcamera sensor AWB key not found')
                    self._awb_gains = None
                except IndexError:
                    logger.error('Invalid color gain values')
                    self._awb_gains = None


                ### Color correction matrix
                #try:
                #    ccm = metadata_dict[self._ccm_metadata_key]
                #    self._ccm = [
                #        [ccm[8], ccm[7], ccm[6]],
                #        [ccm[5], ccm[4], ccm[3]],
                #        [ccm[2], ccm[1], ccm[0]],
                #    ]
                #except KeyError:
                #    logger.error('libcamera CCM key not found')
                #    self._ccm = None
                #except IndexError:
                #    logger.error('Invalid CCM values')
                #    self._ccm = None

        else:
            # day
            if self.config.get('LIBCAMERA', {}).get('AWB_ENABLE_DAY'):
                try:
                    awb_gains = metadata_dict[self._awb_gains_metadata_key]
                    self._awb_gains = [awb_gains[0], awb_gains[1]]
                except KeyError:
                    logger.error('libcamera sensor AWB key not found')
                    self._awb_gains = None
                except IndexError:
                    logger.error('Invalid color gain values')
                    self._awb_gains = None


                ### Color correction matrix
                #try:
                #    ccm = metadata_dict[self._ccm_metadata_key]
                #    self._ccm = [
                #        [ccm[8], ccm[7], ccm[6]],
                #        [ccm[5], ccm[4], ccm[3]],
                #        [ccm[2], ccm[1], ccm[0]],
                #    ]
                #except KeyError:
                #    logger.error('libcamera CCM key not found')
                #    self._ccm = None
                #except IndexError:
                #    logger.error('Invalid CCM values')
                #    self._ccm = None


        ### Black Level
        try:
            black_level = metadata_dict[self._black_level_metadata_key]
            self._black_level = black_level[0]  # Only going to use the first key for now
        except KeyError:
            logger.error('libcamera sensor black level key not found')
            self._black_level = None
        except IndexError:
            logger.error('Invalid black level values')
            self._black_level = None



    def abortCcdExposure(self):
        logger.warning('Aborting exposure')

        self.active_exposure = False

        for x in range(5):
            if self._libCameraPidRunning():
                self.libcamera_process.terminate()
                time.sleep(0.25)
            else:
                break

        else:
            self.libcamera_process.kill()


        try:
            self.current_exposure_file_p.unlink()
        except FileNotFoundError:
            pass


        try:
            self.current_metadata_file_p.unlink()
        except FileNotFoundError:
            pass


    def _queueImage(self):
        exposure_elapsed_s = time.time() - self.exposureStartTime

        exp_date = datetime.now()

        ### process data in worker
        jobdata = {
            'filename'    : str(self.current_exposure_file_p),
            'exposure'    : self._exposure,
            'exp_time'    : datetime.timestamp(exp_date),  # datetime objects are not json serializable
            'exp_elapsed' : exposure_elapsed_s,
            'camera_id'   : self.camera_id,
            'filename_t'  : self._filename_t,
            'libcamera_black_level' : self._black_level,
            'libcamera_awb_gains'   : self._awb_gains,
            #'libcamera_ccm'         : self._ccm,
        }

        self.image_q.put(jobdata)


    def _libCameraPidRunning(self):
        if not self.libcamera_process:
            return False

        # poll returns None when process is active, rc (normally 0) when finished
        poll = self.libcamera_process.poll()
        if isinstance(poll, type(None)):
            return True

        return False


    def findCcd(self, *args, **kwargs):
        new_ccd = FakeIndiCcd()
        new_ccd.device_name = self.ccd_device_name
        new_ccd.driver_exec = self.ccd_driver_exec

        new_ccd.width = self.camera_info['width']
        new_ccd.height = self.camera_info['height']
        new_ccd.pixel = self.camera_info['pixel']

        new_ccd.min_gain = self.camera_info['min_gain']
        new_ccd.max_gain = self.camera_info['max_gain']

        new_ccd.min_exposure = self.camera_info['min_exposure']
        new_ccd.max_exposure = self.camera_info['max_exposure']

        new_ccd.cfa = self.camera_info['cfa']
        new_ccd.bit_depth = self.camera_info['bit_depth']

        self._ccd_device = new_ccd

        return self._ccd_device


    def getCcdInfo(self):
        ccdinfo = dict()

        ccdinfo['CCD_EXPOSURE'] = dict()
        ccdinfo['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE'] = {
            'current' : None,
            'min'     : self._ccd_device.min_exposure,
            'max'     : self._ccd_device.max_exposure,
            'step'    : None,
            'format'  : None,
        }

        ccdinfo['CCD_INFO'] = dict()
        ccdinfo['CCD_INFO']['CCD_MAX_X'] = dict()
        ccdinfo['CCD_INFO']['CCD_MAX_Y'] = dict()
        ccdinfo['CCD_INFO']['CCD_PIXEL_SIZE'] = {
            'current' : self._ccd_device.pixel,
            'min'     : self._ccd_device.pixel,
            'max'     : self._ccd_device.pixel,
            'step'    : None,
            'format'  : None,
        }

        ccdinfo['CCD_INFO']['CCD_PIXEL_SIZE_X'] = {
            'current' : self._ccd_device.pixel,
            'min'     : self._ccd_device.pixel,
            'max'     : self._ccd_device.pixel,
            'step'    : None,
            'format'  : None,
        }

        ccdinfo['CCD_INFO']['CCD_PIXEL_SIZE_Y'] = {
            'current' : self._ccd_device.pixel,
            'min'     : self._ccd_device.pixel,
            'max'     : self._ccd_device.pixel,
            'step'    : None,
            'format'  : None,
        }

        ccdinfo['CCD_INFO']['CCD_BITSPERPIXEL'] = {
            'current' : self._ccd_device.bit_depth,
            'min'     : self._ccd_device.bit_depth,
            'max'     : self._ccd_device.bit_depth,
            'step'    : None,
            'format'  : None,
        }

        ccdinfo['CCD_CFA'] = dict()
        ccdinfo['CCD_CFA']['CFA_TYPE'] = {
            'text' : self._ccd_device.cfa,
        }

        ccdinfo['CCD_FRAME'] = dict()
        ccdinfo['CCD_FRAME']['X'] = dict()
        ccdinfo['CCD_FRAME']['Y'] = dict()

        ccdinfo['CCD_FRAME']['WIDTH'] = {
            'current' : self._ccd_device.width,
            'min'     : self._ccd_device.width,
            'max'     : self._ccd_device.width,
            'step'    : None,
            'format'  : None,
        }

        ccdinfo['CCD_FRAME']['HEIGHT'] = {
            'current' : self._ccd_device.height,
            'min'     : self._ccd_device.height,
            'max'     : self._ccd_device.height,
            'step'    : None,
            'format'  : None,
        }

        ccdinfo['CCD_FRAME_TYPE'] = {
            'FRAME_LIGHT' : 1,
            'FRAME_BIAS'  : 0,
            'FRAME_DARK'  : 0,
            'FRAME_FLAT'  : 0,
        }

        ccdinfo['GAIN_INFO'] = {
            'current' : self._ccd_device.min_gain,
            'min'     : self._ccd_device.min_gain,
            'max'     : self._ccd_device.max_gain,
            'step'    : None,
            'format'  : None,
        }

        return ccdinfo


    def enableCcdCooler(self):
        # not supported
        pass


    def disableCcdCooler(self):
        # not supported
        pass


    def getCcdTemperature(self):
        return self._temp_val


    def setCcdTemperature(self, new_temp):
        # not supported
        pass


class IndiClientLibCameraImx477(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx477, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_imx477'
        self.ccd_driver_exec = 'libcamera-still'

        self.camera_info = {
            'width'         : 4056,
            'height'        : 3040,
            'pixel'         : 1.55,
            'min_gain'      : 1,
            'max_gain'      : 22,  # verified
            'min_exposure'  : 0.0001,
            'max_exposure'  : 200.0,
            'cfa'           : 'BGGR',
            'bit_depth'     : 16,
        }


class IndiClientLibCameraImx378(IndiClientLibCameraGeneric):
    # this model is almost identical to the imx477

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx378, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_imx378'
        self.ccd_driver_exec = 'libcamera-still'

        self.camera_info = {
            'width'         : 4056,
            'height'        : 3040,
            'pixel'         : 1.55,
            'min_gain'      : 1,
            'max_gain'      : 22,  # verified
            'min_exposure'  : 0.0001,
            'max_exposure'  : 200.0,
            'cfa'           : 'BGGR',
            'bit_depth'     : 16,
        }


class IndiClientLibCameraImx219(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx219, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_imx219'
        self.ccd_driver_exec = 'libcamera-still'

        self.camera_info = {
            'width'         : 3280,
            'height'        : 2464,
            'pixel'         : 1.12,
            'min_gain'      : 1,
            'max_gain'      : 16,
            'min_exposure'  : 0.0001,
            'max_exposure'  : 200.0,
            'cfa'           : 'BGGR',
            'bit_depth'     : 16,
        }


class IndiClientLibCameraImx519(IndiClientLibCameraGeneric):
    # this model is almost identical to the imx477

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx519, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_imx519'
        self.ccd_driver_exec = 'libcamera-still'

        self.camera_info = {
            'width'         : 4656,
            'height'        : 3496,
            'pixel'         : 1.22,
            'min_gain'      : 1,
            'max_gain'      : 16,
            'min_exposure'  : 0.0001,
            'max_exposure'  : 200.0,
            'cfa'           : 'RGGB',
            'bit_depth'     : 16,
        }


class IndiClientLibCamera64mpHawkeye(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCamera64mpHawkeye, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_64mp_hawkeye'
        self.ccd_driver_exec = 'libcamera-still'

        self.camera_info = {
            'width'         : 9152,
            'height'        : 6944,
            'pixel'         : 0.8,
            'min_gain'      : 1,
            'max_gain'      : 16,  # unverified
            'min_exposure'  : 0.0001,
            'max_exposure'  : 200.0,
            'cfa'           : 'RGGB',
            'bit_depth'     : 16,
        }


class IndiClientLibCameraImx708(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx708, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_imx708'
        self.ccd_driver_exec = 'libcamera-still'

        self.camera_info = {
            'width'         : 4608,
            'height'        : 2592,
            'pixel'         : 1.4,
            'min_gain'      : 1,
            'max_gain'      : 16,  # unverified
            'min_exposure'  : 0.00003,
            'max_exposure'  : 112.0,
            'cfa'           : 'BGGR',  # untested
            'bit_depth'     : 16,
        }


class IndiClientLibCameraImx290(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx290, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_imx290'
        self.ccd_driver_exec = 'libcamera-still'

        self.camera_info = {
            'width'         : 1920,
            'height'        : 1080,
            'pixel'         : 2.9,
            'min_gain'      : 1,
            'max_gain'      : 16,  # unverified
            'min_exposure'  : 0.0001,
            'max_exposure'  : 200.0,
            'cfa'           : 'GRGB',
            'bit_depth'     : 16,
        }


class IndiClientLibCameraImx462(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx462, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_imx462'
        self.ccd_driver_exec = 'libcamera-still'

        self.camera_info = {
            'width'         : 1920,
            'height'        : 1080,
            'pixel'         : 2.9,
            'min_gain'      : 1,
            'max_gain'      : 16,  # unverified
            'min_exposure'  : 0.00003,
            'max_exposure'  : 200.0,
            'cfa'           : 'RGGB',
            'bit_depth'     : 16,
        }



