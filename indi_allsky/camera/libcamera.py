from datetime import datetime
import time
import tempfile
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

        self._ccd_gain = -1
        self._ccd_bin = 1

        self.active_exposure = False
        self.current_exposure_file_p = None

        memory_info = psutil.virtual_memory()
        self.memory_total_mb = memory_info[0] / 1024.0 / 1024.0


        self.ccd_device_name = 'CHANGEME'
        self.ccd_driver_exec = 'indi_fake_ccd'

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


        self.telescope_device_name = 'CHANGEME'
        self.telescope_driver_exec = 'indi_fake_telescope'

        self.telescope_info = {
            'lat'           : self.latitude_v.value,
            'long'          : self.longitude_v.value,
        }


        self.gps_device_name = 'CHANGEME'
        self.gps_driver_exec = 'indi_fake_gps'

        self.gps_info = {
            'lat'           : self.latitude_v.value,
            'long'          : self.longitude_v.value,
        }


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
            image_tmp_p = Path(image_tmp_f.name)
            image_tmp_f.close()
        except OSError as e:
            logger.error('OSError: %s', str(e))
            return


        self.current_exposure_file_p = image_tmp_p


        self._exposure = exposure

        exposure_us = int(exposure * 1000000)

        if image_type in ['dng']:
            cmd = [
                'libcamera-still',
                '--immediate',
                '--nopreview',
                '--raw',
                '--denoise', 'off',
                '--awbgains', '1,1',  # disable awb
                '--gain', '{0:d}'.format(self._ccd_gain),
                '--shutter', '{0:d}'.format(exposure_us),
            ]
        elif image_type in ['jpg', 'png']:
            #logger.warning('RAW frame mode disabled due to low memory resources')
            cmd = [
                'libcamera-still',
                '--immediate',
                '--nopreview',
                '--encoding', '{0:s}'.format(image_type),
                '--quality', '100',
                '--denoise', 'off',
                '--awbgains', '1,1',  # disable awb
                '--gain', '{0:d}'.format(self._ccd_gain),
                '--shutter', '{0:d}'.format(exposure_us),
            ]
        else:
            raise Exception('Invalid image type')


        # Add extra config options
        extra_options = self.config.get('LIBCAMERA', {}).get('EXTRA_OPTIONS')
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

            self.active_exposure = False

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


            self._queueImage()


        return True, 'READY'


    def _queueImage(self):
        exposure_elapsed_s = time.time() - self.exposureStartTime

        exp_date = datetime.now()

        ### process data in worker
        jobdata = {
            'filename'    : str(self.current_exposure_file_p),
            'exposure'    : self._exposure,
            'exp_time'    : datetime.timestamp(exp_date),  # datetime objects are not json serializable
            'exp_elapsed' : exposure_elapsed_s,
            'camera_id'   : self.config['DB_CAMERA_ID'],
            'filename_t'  : self._filename_t,
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
        temp_val = -273.15  # absolute zero  :-)
        return temp_val


    def setCcdTemperature(self, *args):
        pass


class IndiClientLibCameraImx477(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx477, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'libcamera_imx477'
        self.ccd_driver_exec = 'indi_fake_ccd'

        self.camera_info = {
            'width'         : 4056,
            'height'        : 3040,
            'pixel'         : 1.55,
            'min_gain'      : 1,
            'max_gain'      : 16,
            'min_exposure'  : 0.001,
            'max_exposure'  : 200.0,
            'cfa'           : 'BGGR',
            'bit_depth'     : 16,
        }


        self.telescope_device_name = 'fake_telescope'
        self.telescope_driver_exec = 'indi_fake_telescope'

        self.gps_device_name = 'fake_gps'
        self.gps_driver_exec = 'indi_fake_gps'

