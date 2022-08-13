import logging

from .fake_indi import FakeIndiClient
from .fake_indi import FakeIndiCcd


logger = logging.getLogger('indi_allsky')


class FakeIndiLibCamera(FakeIndiClient):

    def __init__(self, *args, **kwargs):
        super(FakeIndiLibCamera, self).__init__(*args, **kwargs)


    def setCcdExposure(self, exposure, sync=False, timeout=None):
        pass


    def getCcdExposureStatus(self):
        # returns camera_ready, exposure_state
        pass


    def findCcd(self):
        new_ccd = FakeIndiCcd()
        new_ccd.device_name = 'libcamera0'
        new_ccd.driver_exec = 'indi_fake_ccd'

        self._ccd_device = new_ccd

        return self._ccd_device


