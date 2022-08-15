import tempfile
import subprocess
import psutil
from pathlib import Path
import logging

from .fake_indi import FakeIndiClient
from .fake_indi import FakeIndiCcd


logger = logging.getLogger('indi_allsky')


class FakeIndiLibCamera(FakeIndiClient):

    def __init__(self, *args, **kwargs):
        super(FakeIndiLibCamera, self).__init__(*args, **kwargs)

        self.libcamera_pid = None

        self.max_gain = 16
        self.min_gain = 1


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

        self._ccd_device = new_ccd

        return self._ccd_device


