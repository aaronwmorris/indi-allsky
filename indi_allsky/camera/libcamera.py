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

        self.width = 4056
        self.height = 3040
        self.pixel = 1.55

        self.min_gain = 1
        self.max_gain = 16

        self.min_exposure = 0.000032
        self.max_exposure = 200.0

        self.cfa = 'BGGR'
        self.bit_depth = 12


    def setCcdExposure(self, exposure, sync=False, timeout=None):
        if self._libCameraPidRunning():
            return False

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

        logger.info('image command: %s', cmd.join(' '))

        libcamera_subproc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        self.libcamera_pid = libcamera_subproc.pid


    def getCcdExposureStatus(self):
        # returns camera_ready, exposure_state
        if not self._libCameraPidRunning():
            return False, 'BUSY'

        return True, 'READY'


    def _libCameraPidRunning(self):
        if not self.libcamera_pid:
            return False

        if psutil.pid_exists(self.libcamera_pid):
            return True

        return False


    def findCcd(self):
        new_ccd = FakeIndiCcd()
        new_ccd.device_name = 'libcamera0'
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


