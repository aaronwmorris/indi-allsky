from datetime import datetime
import time
import tempfile
import subprocess
#import psutil
from pathlib import Path
import logging

from .fake_indi import FakeIndiClient
from .fake_indi import FakeIndiCcd


logger = logging.getLogger('indi_allsky')


class FakeIndiLibCameraImx477(FakeIndiClient):

    def __init__(self, *args, **kwargs):
        super(FakeIndiLibCameraImx477, self).__init__(*args, **kwargs)

        self.device_name = 'libcamera_imx477'
        self.driver_exec = 'indi_fake_ccd'

        self.libcamera_process = None

        self.active_exposure = False
        self.current_exposure_file_p = None

        self.camera_info = {
            'width'         : 4056,
            'height'        : 3040,
            'pixel'         : 1.55,
            'min_gain'      : 1,
            'max_gain'      : 16,
            'min_exposure'  : 0.001,
            'max_exposure'  : 200.0,
            'cfa'           : 'BGGR',
            'bit_depth'     : 12,
        }


    def setCcdExposure(self, exposure, sync=False, timeout=None):
        if self.active_exposure:
            return

        self._exposure = exposure

        image_tmp_f = tempfile.NamedTemporaryFile(mode='w', suffix='.dng', delete=False)
        image_tmp_p = Path(image_tmp_f.name)
        image_tmp_f.close()

        exposure_us = int(exposure * 1000000)

        cmd = [
            'libcamera-still',
            '--immediate',
            '--nopreview',
            '--raw',
            '--awbgains', '1.0,1.0,1.0',  # disable awb
            '--gain', '{0:d}'.format(self._ccd_gain),
            '--shutter', '{0:d}'.format(exposure_us),
            '--output', str(image_tmp_p),
        ]

        logger.info('image command: %s', ' '.join(cmd))


        self.exposureStartTime = time.time()

        self.libcamera_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        self.active_exposure = True
        self.current_exposure_file_p = image_tmp_p


    def getCcdExposureStatus(self):
        # returns camera_ready, exposure_state
        if self._libCameraPidRunning():
            return False, 'BUSY'


        if self.active_exposure:
            # if we get here, that means the camera is finished with the exposure
            self.active_exposure = False


            exposure_elapsed_s = time.time() - self.exposureStartTime


            exp_date = datetime.now()

            ### process data in worker
            jobdata = {
                'filename'    : str(self.current_exposure_file_p),
                'exposure'    : self._exposure,
                'exp_time'    : datetime.timestamp(exp_date),  # datetime objects are not json serializable
                'exp_elapsed' : exposure_elapsed_s,
                'camera_id'   : self.config['DB_CCD_ID'],
                'filename_t'  : self._filename_t,
            }

            self.image_q.put(jobdata)


        return True, 'READY'


    def _libCameraPidRunning(self):
        if not self.libcamera_process:
            return False

        # poll returns None when process is active, rc (normally 0) when finished
        poll = self.libcamera_process.poll()
        if isinstance(poll, type(None)):
            return True

        return False


    def findCcd(self):
        new_ccd = FakeIndiCcd()
        new_ccd.device_name = self.device_name
        new_ccd.driver_exec = self.driver_exec

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


