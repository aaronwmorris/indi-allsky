import datetime
import time
import tempfile
import subprocess
import psutil
from pathlib import Path
import logging

from .fake_indi import FakeIndiClient
from .fake_indi import FakeIndiCcd


logger = logging.getLogger('indi_allsky')


class FakeIndiLibCameraImx477(FakeIndiClient):

    def __init__(self, *args, **kwargs):
        super(FakeIndiLibCameraImx477, self).__init__(*args, **kwargs)

        self.libcamera_pid = None

        self.device_name = 'libcamera_imx477'

        self.width = 4056
        self.height = 3040
        self.pixel = 1.55

        self.min_gain = 1
        self.max_gain = 16

        self.min_exposure = 0.000032
        self.max_exposure = 200.0

        self.cfa = 'BGGR'
        self.bit_depth = 12

        self.active_exposure = False
        self.current_exposure_file = None


    def setCcdExposure(self, exposure, sync=False, timeout=None):
        if self.active_exposure:
            return

        self._exposure = exposure

        self.exposureStartTime = time.time()

        image_tmp_f = tempfile.NamedTemporaryFile(mode='w', suffix='.dng', delete=False)
        image_tmp_p = Path(image_tmp_f.name)
        image_tmp_f.close()

        exposure_us = int(exposure * 1000000)

        cmd = [
            'libcamera-still',
            '--immediate',
            '--raw',
            '--awbgains', '1.0,1.0,1.0',
            '--gain', '{0:d}'.format(self._ccd_gain),
            '--shutter', '{0:d}'.format(exposure_us),
            '--output', str(image_tmp_p),
        ]

        logger.info('image command: %s', ' '.join(cmd))

        libcamera_subproc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.libcamera_pid = libcamera_subproc.pid

        self.active_exposure = True
        self.current_exposure_file = image_tmp_p


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
                'filename'    : self.current_exposure_file.name,
                'exposure'    : self._exposure,
                'exp_time'    : datetime.timestamp(exp_date),  # datetime objects are not json serializable
                'exp_elapsed' : exposure_elapsed_s,
                'camera_id'   : self.config['DB_CCD_ID'],
                'filename_t'  : self._filename_t,
            }

            self.image_q.put(jobdata)


        return True, 'READY'


    def _libCameraPidRunning(self):
        if not self.libcamera_pid:
            return False

        if psutil.pid_exists(self.libcamera_pid):
            return True

        return False


    def findCcd(self):
        new_ccd = FakeIndiCcd()
        new_ccd.device_name = self.device_name
        new_ccd.driver_exec = 'indi_fake_ccd'

        new_ccd.width = self.width
        new_ccd.height = self.height
        new_ccd.pixel = self.pixel

        new_ccd.min_gain = self.min_gain
        new_ccd.max_gain = self.max_gain

        new_ccd.min_exposure = self.min_exposure
        new_ccd.max_exposure = self.max_exposure

        new_ccd.cfa = self.cfa
        new_ccd.bit_depth = self.bit_depth

        self._ccd_device = new_ccd

        return self._ccd_device


