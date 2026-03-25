import io
import shutil
from datetime import datetime
from collections import OrderedDict
import time
import tempfile
import json
import subprocess
import psutil
from pathlib import Path
import logging

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

from .indi import IndiClient
from .fake_indi import FakeIndiCcd
from .picamera2_client import Picamera2Client

from .. import constants

from ..exceptions import TimeOutException
from ..exceptions import BinModeException


logger = logging.getLogger('indi_allsky')



class IndiClientLibCameraGeneric(IndiClient):

    libcamera_exec = 'rpicam-still'

    _sensor_temp_metadata_key = 'SensorTemperature'
    _analogue_gain_metadata_key = 'AnalogueGain'
    _digital_gain_metadata_key = 'DigitalGain'
    _ccm_metadata_key = 'ColourCorrectionMatrix'
    _awb_gains_metadata_key = 'ColourGains'
    _black_level_metadata_key = 'SensorBlackLevels'


    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraGeneric, self).__init__(*args, **kwargs)

        self.libcamera_process = None  # kept for compat; unused with daemon

        self._temp_val = -273.15  # absolute zero  :-)

        self._ccm = None

        self._awb_gains = None

        self._black_level = 0

        self.active_exposure = False
        self.current_exposure_file_p = None
        self.current_metadata_file_p = None

        # Picamera2 daemon client — replaces rpicam-still subprocess
        self._picam2_client = Picamera2Client()

        memory_info = psutil.virtual_memory()
        self.memory_total_mb = memory_info[0] / 1024.0 / 1024.0


        self.ccd_device_name = 'CHANGEME'


        # pick correct executable (kept as fallback identifier)
        if shutil.which('rpicam-still'):
            self.ccd_driver_exec = 'rpicam-still'
        elif shutil.which('libcamera-still'):
            self.ccd_driver_exec = 'libcamera-still'
        else:
            self.ccd_driver_exec = 'picamera2-daemon'


        logger.info('libcamera backend: picamera2 daemon')


        # override in subclass
        self.camera_info = {
            'width'         : 0,
            'height'        : 0,
            'pixel'         : 0.0,
            'min_gain'      : 0.0,
            'max_gain'      : 0.0,
            'min_binning'   : 0,
            'max_binning'   : 0,
            'min_exposure'  : 0.0,
            'max_exposure'  : 0.0,
            'cfa'           : 'CHANGEME',
            'bit_depth'     : 0,
        }


        self._binmode_options = {
            1 : '',
        }


    @property
    def libcamera_bit_depth(self):
        return self.ccd_device.bit_depth

    @libcamera_bit_depth.setter
    def libcamera_bit_depth(self, new_libcamera_bit_depth):
        self.camera_info['bit_depth'] = int(new_libcamera_bit_depth)
        self.ccd_device.bit_depth = self.camera_info['bit_depth']


    def getCcdGain(self):
        return float(self.gain_av[constants.GAIN_CURRENT])


    def setCcdGain(self, new_gain_value):
        gain_f = float(round(new_gain_value, 2))  # limit gain to 2 decimals

        # Update shared gain value
        with self.gain_av.get_lock():
            self.gain_av[constants.GAIN_CURRENT] = gain_f

        self.gain = gain_f


    def setCcdBinning(self, bin_value):
        if not bin_value:
            # Assume default
            return


        # Update shared gin value
        with self.binning_av.get_lock():
            self.binning_av[constants.BINNING_CURRENT] = int(bin_value)


        self.binning = int(bin_value)


    def _getBinModeOptions(self, bin_value):
        try:
            option = self._binmode_options[int(bin_value)]
        except KeyError:
            raise BinModeException('Invalid bin mode for camera: {0:d}'.format(int(bin_value)))

        return option


    def setCcdExposure(self, exposure, gain, binning, sync=False, timeout=None, sqm_exposure=False):
        if self.active_exposure:
            return

        self.exposure = exposure
        self.sqm_exposure = sqm_exposure

        if self.night_av[constants.NIGHT_NIGHT]:
            image_type = self.config.get('LIBCAMERA', {}).get('IMAGE_FILE_TYPE', 'jpg')
        else:
            image_type = self.config.get('LIBCAMERA', {}).get('IMAGE_FILE_TYPE_DAY', 'jpg')

        if self.gain != float(round(gain, 2)):
            self.setCcdGain(gain)

        if self.binning != int(binning):
            self.setCcdBinning(binning)

        # Determine AWB setting
        is_night = bool(self.night_av[constants.NIGHT_NIGHT])
        if is_night:
            awb_enable = bool(self.config.get('LIBCAMERA', {}).get('AWB_ENABLE'))
        else:
            awb_enable = bool(self.config.get('LIBCAMERA', {}).get('AWB_ENABLE_DAY'))

        # Send controls to the picamera2 daemon
        self._picam2_client.set_controls(
            exposure=exposure,
            gain=float(self.gain_av[constants.GAIN_CURRENT]),
            awb=awb_enable,
        )

        logger.info(
            'Capturing via picamera2 daemon: %.4fs exposure, gain %.2f, bin %d, type %s',
            exposure, self.gain_av[constants.GAIN_CURRENT], binning, image_type,
        )

        self.exposureStartTime = time.time()
        self.active_exposure = True
        self._pending_image_type = image_type

        # Update shared exposure value
        with self.exposure_av.get_lock():
            self.exposure_av[constants.EXPOSURE_CURRENT] = float(exposure)

        if sync:
            capture_timeout = timeout if timeout else max(exposure * 3, 30)

            if image_type == 'dng':
                # DNG: daemon captures directly to file
                try:
                    dng_tmp = tempfile.NamedTemporaryFile(
                        mode='w', suffix='.dng', delete=False,
                    )
                    dng_tmp.close()
                    result = self._picam2_client.capture_dng(
                        dng_tmp.name, timeout=capture_timeout,
                    )
                    if not result.get('ok'):
                        logger.error('DNG capture failed: %s', result.get('error'))
                except Exception as e:
                    logger.error('DNG capture error: %s', str(e))

                self.current_exposure_file_p = Path(dng_tmp.name)
            else:
                # JPG/PNG: grab frame from daemon, encode locally
                try:
                    result = self._picam2_client.capture_still(
                        exposure=exposure,
                        gain=float(self.gain_av[constants.GAIN_CURRENT]),
                        timeout=capture_timeout,
                    )
                except Exception as e:
                    logger.error('Capture error: %s', str(e))
                    self.active_exposure = False
                    return

                if not result.get('ok'):
                    logger.error('Capture failed: %s', result.get('error'))
                    self.active_exposure = False
                    return

                # Load numpy frame and encode to image file
                frame_path = result.get('frame_path', '')
                self._last_daemon_metadata = result.get('metadata', {})

                try:
                    frame = np.load(frame_path)
                except Exception as e:
                    logger.error('Failed to load frame from %s: %s', frame_path, str(e))
                    self.active_exposure = False
                    return

                # Save as JPG or PNG
                image_tmp_f = tempfile.NamedTemporaryFile(
                    mode='w', suffix='.{0:s}'.format(image_type), delete=False,
                )
                image_tmp_f.close()
                self.current_exposure_file_p = Path(image_tmp_f.name)

                if cv2 is not None:
                    # Frame is RGB from picamera2, convert to BGR for cv2
                    bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    if image_type == 'jpg':
                        cv2.imwrite(str(self.current_exposure_file_p), bgr,
                                    [cv2.IMWRITE_JPEG_QUALITY, 95])
                    else:
                        cv2.imwrite(str(self.current_exposure_file_p), bgr)

            self.active_exposure = False
            self._processMetadata()
            self._queueImage()

        else:
            # Async mode: start capture in background thread
            import threading
            self._async_thread = threading.Thread(
                target=self._async_capture,
                args=(exposure, gain, image_type),
                daemon=True,
            )
            self._async_thread.start()


    def _async_capture(self, exposure, gain, image_type):
        """Background capture for async (non-sync) mode."""
        try:
            capture_timeout = max(exposure * 3, 30)
            result = self._picam2_client.capture_still(
                exposure=exposure, gain=gain, timeout=capture_timeout,
            )
            if not result.get('ok'):
                logger.error('Async capture failed: %s', result.get('error'))
                self.active_exposure = False
                return

            frame_path = result.get('frame_path', '')
            self._last_daemon_metadata = result.get('metadata', {})

            frame = np.load(frame_path)

            image_tmp_f = tempfile.NamedTemporaryFile(
                mode='w', suffix='.{0:s}'.format(image_type), delete=False,
            )
            image_tmp_f.close()
            self.current_exposure_file_p = Path(image_tmp_f.name)

            if cv2 is not None:
                bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                if image_type == 'jpg':
                    cv2.imwrite(str(self.current_exposure_file_p), bgr,
                                [cv2.IMWRITE_JPEG_QUALITY, 95])
                else:
                    cv2.imwrite(str(self.current_exposure_file_p), bgr)

            # Mark as ready for getCcdExposureStatus to pick up
            # active_exposure stays True until getCcdExposureStatus processes it
        except Exception:
            logger.exception('Async capture error')
            self.active_exposure = False


    def getCcdExposureStatus(self):
        # returns camera_ready, exposure_state

        if self.active_exposure:
            # Check if async capture thread is still running
            if hasattr(self, '_async_thread') and self._async_thread is not None:
                if self._async_thread.is_alive():
                    return False, 'BUSY'

            # Async capture finished — process the result
            self.active_exposure = False
            self._async_thread = None

            self._processMetadata()
            self._queueImage()

        return True, 'READY'


    def _processMetadata(self):
        """Extract ISP metadata from the picamera2 daemon response."""
        metadata_dict = getattr(self, '_last_daemon_metadata', {})

        ### Gain
        analogue_gain = float(metadata_dict.get(self._analogue_gain_metadata_key, 0.0))
        digital_gain = float(metadata_dict.get(self._digital_gain_metadata_key, 0.0))

        if analogue_gain:
            logger.info('libcamera reported gain: %0.2f/%0.2f', analogue_gain, digital_gain)

        ### Temperature
        temp = metadata_dict.get(self._sensor_temp_metadata_key)
        if temp is not None:
            self._temp_val = float(temp)

        ### Auto white balance
        is_night = bool(self.night_av[constants.NIGHT_NIGHT])
        if is_night:
            awb_enabled = self.config.get('LIBCAMERA', {}).get('AWB_ENABLE')
        else:
            awb_enabled = self.config.get('LIBCAMERA', {}).get('AWB_ENABLE_DAY')

        if awb_enabled:
            awb_gains = metadata_dict.get(self._awb_gains_metadata_key)
            if awb_gains and isinstance(awb_gains, (list, tuple)) and len(awb_gains) >= 2:
                self._awb_gains = [awb_gains[0], awb_gains[1]]
            else:
                self._awb_gains = None
        else:
            self._awb_gains = None

        ### Black Level
        black_level = metadata_dict.get(self._black_level_metadata_key)
        if black_level and isinstance(black_level, (list, tuple)) and len(black_level) > 0:
            self._black_level = black_level[0]
        else:
            self._black_level = None



    def abortCcdExposure(self):
        logger.warning('Aborting exposure')
        self.active_exposure = False

        try:
            if self.current_exposure_file_p:
                self.current_exposure_file_p.unlink()
        except FileNotFoundError:
            pass


    def _queueImage(self):
        exposure_elapsed_s = time.time() - self.exposureStartTime

        exp_date = datetime.now()

        ### process data in worker
        jobdata = {
            'filename'    : str(self.current_exposure_file_p),
            'exposure'    : self.exposure,
            'gain'        : self.gain,
            'binning'     : self.binning,
            'sqm_exposure': self.sqm_exposure,
            'exp_time'    : datetime.timestamp(exp_date),  # datetime objects are not json serializable
            'exp_elapsed' : exposure_elapsed_s,
            'camera_id'   : self.camera_id,
            'filename_t'  : self._filename_t,
            'libcamera_black_level' : self._black_level,
            'libcamera_awb_gains'   : self._awb_gains,
            #'libcamera_ccm'         : self._ccm,
        }

        self.image_q.put(jobdata)


    def _libCameraProcessRunning(self):
        # No longer uses subprocess — check async thread instead
        if hasattr(self, '_async_thread') and self._async_thread is not None:
            return self._async_thread.is_alive()
        return False


    def findCcd(self, *args, **kwargs):
        # Try to get live sensor info from daemon, fall back to subclass camera_info
        try:
            info = self._picam2_client.get_sensor_info()
            if info.get('ok'):
                if info.get('width'):
                    self.camera_info['width'] = info['width']
                if info.get('height'):
                    self.camera_info['height'] = info['height']
                if info.get('pixel'):
                    self.camera_info['pixel'] = info['pixel']
                if info.get('min_gain'):
                    self.camera_info['min_gain'] = info['min_gain']
                if info.get('max_gain'):
                    self.camera_info['max_gain'] = info['max_gain']
                if info.get('min_exposure'):
                    self.camera_info['min_exposure'] = info['min_exposure']
                if info.get('max_exposure'):
                    self.camera_info['max_exposure'] = info['max_exposure']
                if info.get('cfa'):
                    self.camera_info['cfa'] = info['cfa']
                logger.info('Camera info from daemon: %s', info.get('sensor_name', 'unknown'))
        except Exception as e:
            logger.warning('Could not get sensor info from daemon, using defaults: %s', str(e))

        new_ccd = FakeIndiCcd()
        new_ccd.device_name = self.ccd_device_name
        new_ccd.driver_exec = self.ccd_driver_exec

        new_ccd.width = self.camera_info['width']
        new_ccd.height = self.camera_info['height']
        new_ccd.pixel = self.camera_info['pixel']

        new_ccd.min_gain = self.camera_info['min_gain']
        new_ccd.max_gain = self.camera_info['max_gain']

        new_ccd.min_binning = self.camera_info['min_binning']
        new_ccd.max_binning = self.camera_info['max_binning']

        new_ccd.min_exposure = self.camera_info['min_exposure']
        new_ccd.max_exposure = self.camera_info['max_exposure']

        new_ccd.cfa = self.camera_info['cfa']
        new_ccd.bit_depth = self.camera_info['bit_depth']

        self.ccd_device = new_ccd

        return new_ccd


    def getCcdInfo(self):
        ccdinfo = dict()

        ccdinfo['CCD_EXPOSURE'] = dict()
        ccdinfo['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE'] = {
            'current' : None,
            'min'     : self.ccd_device.min_exposure,
            'max'     : self.ccd_device.max_exposure,
            'step'    : None,
            'format'  : None,
        }

        ccdinfo['CCD_INFO'] = dict()
        ccdinfo['CCD_INFO']['CCD_MAX_X'] = dict()
        ccdinfo['CCD_INFO']['CCD_MAX_Y'] = dict()
        ccdinfo['CCD_INFO']['CCD_PIXEL_SIZE'] = {
            'current' : self.ccd_device.pixel,
            'min'     : self.ccd_device.pixel,
            'max'     : self.ccd_device.pixel,
            'step'    : None,
            'format'  : None,
        }

        ccdinfo['CCD_INFO']['CCD_PIXEL_SIZE_X'] = {
            'current' : self.ccd_device.pixel,
            'min'     : self.ccd_device.pixel,
            'max'     : self.ccd_device.pixel,
            'step'    : None,
            'format'  : None,
        }

        ccdinfo['CCD_INFO']['CCD_PIXEL_SIZE_Y'] = {
            'current' : self.ccd_device.pixel,
            'min'     : self.ccd_device.pixel,
            'max'     : self.ccd_device.pixel,
            'step'    : None,
            'format'  : None,
        }

        ccdinfo['CCD_INFO']['CCD_BITSPERPIXEL'] = {
            'current' : self.ccd_device.bit_depth,
            'min'     : self.ccd_device.bit_depth,
            'max'     : self.ccd_device.bit_depth,
            'step'    : None,
            'format'  : None,
        }

        ccdinfo['CCD_CFA'] = dict()
        ccdinfo['CCD_CFA']['CFA_TYPE'] = {
            'text' : self.ccd_device.cfa,
        }

        ccdinfo['CCD_FRAME'] = dict()
        ccdinfo['CCD_FRAME']['X'] = dict()
        ccdinfo['CCD_FRAME']['Y'] = dict()

        ccdinfo['CCD_FRAME']['WIDTH'] = {
            'current' : self.ccd_device.width,
            'min'     : self.ccd_device.width,
            'max'     : self.ccd_device.width,
            'step'    : None,
            'format'  : None,
        }

        ccdinfo['CCD_FRAME']['HEIGHT'] = {
            'current' : self.ccd_device.height,
            'min'     : self.ccd_device.height,
            'max'     : self.ccd_device.height,
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
            'current' : self.ccd_device.min_gain,
            'min'     : self.ccd_device.min_gain,
            'max'     : self.ccd_device.max_gain,
            'step'    : None,
            'format'  : None,
        }

        ccdinfo['BINNING_INFO'] = {
            'current' : self.ccd_device.min_binning,
            'min'     : self.ccd_device.min_binning,
            'max'     : self.ccd_device.max_binning,
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


    def setCcdTemperature(self, *args, **kwargs):
        # not supported
        pass


    def setCcdScopeInfo(self, *args):
        # not supported
        pass


class IndiClientLibCameraImx477(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx477, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_imx477'

        self.camera_info = {
            'width'         : 4056,
            'height'        : 3040,
            'pixel'         : 1.55,
            'min_gain'      : 1.0,
            'max_gain'      : 22.26,
            'min_binning'   : 1,
            'max_binning'   : 4,
            'min_exposure'  : 0.000114,
            'max_exposure'  : 694.0,
            'cfa'           : 'BGGR',
            'bit_depth'     : 16,
        }

        self._binmode_options = {
            #1 : '--mode 4056:3040:12',
            1 : '',
            2 : '--mode 2028:1520:12',
            4 : '--mode 1332:990:10',  # cropped
        }


class IndiClientLibCameraImx378(IndiClientLibCameraGeneric):
    # this model is almost identical to the imx477

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx378, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_imx378'

        self.camera_info = {
            'width'         : 4056,
            'height'        : 3040,
            'pixel'         : 1.55,
            'min_gain'      : 1.0,
            'max_gain'      : 22.26,
            'min_binning'   : 1,
            'max_binning'   : 4,
            'min_exposure'  : 0.000114,
            'max_exposure'  : 694.0,
            'cfa'           : 'BGGR',
            'bit_depth'     : 16,
        }

        self._binmode_options = {
            #1 : '--mode 4056:3040:12',
            1 : '',
            2 : '--mode 2028:1520:12',
            4 : '--mode 1332:990:10',  # cropped
        }


class IndiClientLibCameraOv5647(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraOv5647, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_ov5647'

        self.camera_info = {
            'width'         : 2592,
            'height'        : 1944,
            'pixel'         : 1.4,
            'min_gain'      : 1.0,
            'max_gain'      : 16.0,
            'min_binning'   : 1,
            'max_binning'   : 1,
            'min_exposure'  : 0.0001,
            'max_exposure'  : 6.0,
            'cfa'           : 'BGGR',  # unverified
            'bit_depth'     : 16,
        }

        self._binmode_options = {
            1 : '',
        }


class IndiClientLibCameraImx219(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx219, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_imx219'

        self.camera_info = {
            'width'         : 3280,
            'height'        : 2464,
            'pixel'         : 1.12,
            'min_gain'      : 1.0,
            'max_gain'      : 16.0,
            'min_binning'   : 1,
            'max_binning'   : 2,
            'min_exposure'  : 0.0001,
            'max_exposure'  : 11.76,
            'cfa'           : 'BGGR',
            'bit_depth'     : 16,
        }

        self._binmode_options = {
            #1 : '--mode 3280:2464:10',
            1 : '',
            2 : '--mode 1640:1232:10',
        }


class IndiClientLibCameraImx519(IndiClientLibCameraGeneric):
    # this model is almost identical to the imx477

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx519, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_imx519'

        self.camera_info = {
            'width'         : 4656,
            'height'        : 3496,
            'pixel'         : 1.22,
            'min_gain'      : 1.0,
            'max_gain'      : 16.0,
            'min_binning'   : 1,
            'max_binning'   : 4,
            'min_exposure'  : 0.000592,
            'max_exposure'  : 200.0,
            'cfa'           : 'RGGB',
            'bit_depth'     : 16,
        }

        self._binmode_options = {
            #1 : '--mode 4656:3496:10',
            1 : '',
            2 : '--mode 2328:1748:10',
            #4 : '--mode 1920x1080:10',  # cropped
            4 : '--mode 1280:720:10',  # cropped
        }


class IndiClientLibCamera64mpHawkeye(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCamera64mpHawkeye, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_64mp_hawkeye'

        self.camera_info = {
            'width'         : 9152,
            'height'        : 6944,
            'pixel'         : 0.8,
            'min_gain'      : 1.0,
            'max_gain'      : 16.0,  # unverified
            'min_binning'   : 1,
            'max_binning'   : 1,
            'min_exposure'  : 0.0001,
            'max_exposure'  : 200.0,
            'cfa'           : 'RGGB',
            'bit_depth'     : 16,
        }

        self._binmode_options = {
            1 : '',
            #1 : '--mode 9152:6944',  # unverified
            #2 : '--mode 4624:3472',
            #4 : '--mode 2312:1736',
        }


class IndiClientLibCameraOv64a40OwlSight(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraOv64a40OwlSight, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_64mp_owlsight'

        self.camera_info = {
            'width'         : 9152,
            'height'        : 6944,
            'pixel'         : 1.008,
            'min_gain'      : 1.0,
            'max_gain'      : 16.0,
            'min_binning'   : 1,
            'max_binning'   : 4,
            'min_exposure'  : 0.000580,
            'max_exposure'  : 910.0,
            'cfa'           : 'RGGB',
            'bit_depth'     : 16,
        }

        self._binmode_options = {
            1 : '',
            #1 : '--mode 9152:6944:10',
            2 : '--mode 4624:3472:10',  # bin modes do not work well, exposure is not linear
            4 : '--mode 2312:1736:10',
        }


class IndiClientLibCameraImx708(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx708, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_imx708'

        self.camera_info = {
            'width'         : 4608,
            'height'        : 2592,
            'pixel'         : 1.4,
            'min_gain'      : 1.13,
            'max_gain'      : 16.0,
            'min_binning'   : 1,
            'max_binning'   : 4,
            'min_exposure'  : 0.000026,
            'max_exposure'  : 220.0,
            'cfa'           : 'BGGR',
            'bit_depth'     : 16,
        }

        self._binmode_options = {
            #1 : '--mode 4608:2592:10',
            1 : '',
            2 : '--mode 2304:1296:10',
            4 : '--mode 1536:864:10',  # cropped
        }


class IndiClientLibCameraImx296(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx296, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_imx296_gs'

        self.camera_info = {
            'width'         : 1456,
            'height'        : 1088,
            'pixel'         : 3.45,
            'min_gain'      : 1.0,
            'max_gain'      : 251.18,
            'min_binning'   : 1,
            'max_binning'   : 1,
            'min_exposure'  : 0.016562,
            'max_exposure'  : 15.5,
            'cfa'           : None,  # mono
            'bit_depth'     : 16,
        }

        self._binmode_options = {
            #1 : '--mode 1456:1088:10',
            1 : '',
            # no bin2
        }


class IndiClientLibCameraImx296Color(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx296Color, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_imx296_gs_color'

        self.camera_info = {
            'width'         : 1456,
            'height'        : 1088,
            'pixel'         : 3.45,
            'min_gain'      : 1.0,
            'max_gain'      : 16.0,  # verified
            'min_binning'   : 1,
            'max_binning'   : 1,
            'min_exposure'  : 0.0001,
            'max_exposure'  : 15.5,
            'cfa'           : 'RGGB',  # unverified
            'bit_depth'     : 16,
        }

        self._binmode_options = {
            #1 : '--mode 1456:1088:10',
            1 : '',
            # no bin2
        }


class IndiClientLibCameraImx290(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx290, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_imx290'

        self.camera_info = {
            'width'         : 1920,
            'height'        : 1080,
            'pixel'         : 2.9,
            'min_gain'      : 1.0,
            'max_gain'      : 29.51,  # unverified
            'min_binning'   : 1,
            'max_binning'   : 2,
            'min_exposure'  : 0.000014,
            'max_exposure'  : 115.0,
            'cfa'           : 'GRBG',
            'bit_depth'     : 16,
        }

        self._binmode_options = {
            #1 : '--mode 1920:1080:12',
            1 : '',
            2 : '--mode 1280:720:12',  # cropped
        }


class IndiClientLibCameraImx462(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx462, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_imx462'

        self.camera_info = {
            'width'         : 1920,
            'height'        : 1080,
            'pixel'         : 2.9,
            'min_gain'      : 1.0,
            'max_gain'      : 29.51,
            'min_binning'   : 1,
            'max_binning'   : 2,
            'min_exposure'  : 0.000014,
            'max_exposure'  : 115.0,
            'cfa'           : 'RGGB',
            'bit_depth'     : 16,
        }

        self._binmode_options = {
            #1 : '--mode 1920:1080:12',
            1 : '',
            2 : '--mode 1280:720:12',  # cropped
        }


class IndiClientLibCameraImx327(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx327, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_imx327'

        self.camera_info = {
            'width'         : 1920,
            'height'        : 1080,
            'pixel'         : 2.9,
            'min_gain'      : 1.0,
            'max_gain'      : 29.51,
            'min_binning'   : 1,
            'max_binning'   : 1,
            'min_exposure'  : 0.000014,
            'max_exposure'  : 115.0,
            'cfa'           : 'RGGB',
            'bit_depth'     : 16,
        }

        self._binmode_options = {
            #1 : '--mode 1920:1080:12',
            1 : '',
            #2 : '--mode 1280:720:12',  # cropped
        }


class IndiClientLibCameraImx298(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx298, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_imx298'

        self.camera_info = {
            'width'         : 4640,
            'height'        : 3472,
            'pixel'         : 1.12,
            'min_gain'      : 1.0,
            'max_gain'      : 16.0,  # unverified
            'min_binning'   : 1,
            'max_binning'   : 1,
            'min_exposure'  : 0.0001,
            'max_exposure'  : 200.0,
            'cfa'           : 'RGGB',  # unverified
            'bit_depth'     : 16,
        }

        self._binmode_options = {
            1 : '',
        }


class IndiClientLibCameraImx500(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx500, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_imx500_ai'

        self.camera_info = {
            'width'         : 4056,
            'height'        : 3040,
            'pixel'         : 1.55,
            'min_gain'      : 1.0,
            'max_gain'      : 22.0,  # verified
            'min_binning'   : 1,
            'max_binning'   : 1,
            'min_exposure'  : 0.0002,
            'max_exposure'  : 200.0,
            'cfa'           : 'RGGB',  # verified
            'bit_depth'     : 16,
        }

        self._binmode_options = {
            1 : '',
        }


class IndiClientLibCameraImx283(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx283, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_imx283'

        self.camera_info = {
            'width'         : 5472,
            'height'        : 3648,
            'pixel'         : 2.4,
            'min_gain'      : 1.0,
            'max_gain'      : 22.5,
            'min_binning'   : 1,
            'max_binning'   : 1,
            'min_exposure'  : 0.000058,
            'max_exposure'  : 129.0,
            'cfa'           : 'RGGB',  # verified
            'bit_depth'     : 16,
        }

        self._binmode_options = {
            1 : '',
        }


class IndiClientLibCameraImx678(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx678, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_imx678'

        self.camera_info = {
            'width'         : 3840,
            'height'        : 2160,
            'pixel'         : 2.0,
            'min_gain'      : 1.0,
            'max_gain'      : 32.0,  # unverified
            'min_binning'   : 1,
            'max_binning'   : 1,
            'min_exposure'  : 0.000032,
            'max_exposure'  : 200.0,
            'cfa'           : 'RGGB',  # verified
            'bit_depth'     : 16,
        }

        self._binmode_options = {
            1 : '',
        }


class IndiClientLibCameraImx335(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx335, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_imx335'

        self.camera_info = {
            'width'         : 2592,
            'height'        : 1944,
            'pixel'         : 2.0,
            'min_gain'      : 1.0,
            'max_gain'      : 1000.0,
            'min_binning'   : 1,
            'max_binning'   : 1,
            'min_exposure'  : 0.000007,
            'max_exposure'  : 1.0,
            'cfa'           : 'RGGB',
            'bit_depth'     : 16,
        }

        self._binmode_options = {
            1 : '',
        }

