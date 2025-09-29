import time
import logging
#from pprint import pformat

from .indi import IndiClient

from .. import constants

#from ..flask import db
from ..flask import create_app

#from ..flask.models import TaskQueueQueue
#from ..flask.models import TaskQueueState
#from ..flask.models import IndiAllSkyDbTaskQueueTable

logger = logging.getLogger('indi_allsky')


app = create_app()


class IndiClientPassive(IndiClient):

    def __init__(self, *args, **kwargs):
        super(IndiClientPassive, self).__init__(*args, **kwargs)

        logger.info('creating an instance of IndiClient')


    def parkTelescope(self):
        pass

    def unparkTelescope(self):
        pass

    def setTelescopeParkPosition(self, *args):
        pass

    def disableDebug(self, *args):
        pass

    def disableDebugCcd(self):
        pass

    def saveCcdConfig(self):
        pass

    def resetCcdFrame(self):
        pass

    def setCcdFrameType(self, *args):
        pass

    def configureDevice(self, *args, **kwargs):
        pass

    def configureCcdDevice(self, *args, **kwargs):
        pass

    def configureTelescopeDevice(self, *args, **kwargs):
        pass

    def setTelescopeGps(self, *args):
        pass

    def configureGpsDevice(self, *args, **kwargs):
        pass

    def refreshGps(self):
        pass

    def enableCcdCooler(self):
        pass

    def disableCcdCooler(self):
        pass

    def setCcdTemperature(self, *args, **kwargs):
        pass

    def setCcdScopeInfo(self, *args):
        pass


    def setCcdExposure(self, exposure, gain, sync=False, timeout=None):
        self.exposureStartTime = time.time()

        self.exposure = exposure

        if self.gain != float(int(gain)):
            self.setCcdGain(gain)

        ctl_ccd_exposure = self.get_control(self.ccd_device, 'CCD_EXPOSURE', 'number')

        self._ctl_ccd_exposure = ctl_ccd_exposure


        # Update shared exposure value
        with self.exposure_av.get_lock():
            self.exposure_av[constants.EXPOSURE_CURRENT] = float(exposure)


    def getCcdExposureStatus(self):
        camera_ready, exposure_state = self.ctl_ready(self._ctl_ccd_exposure)

        return camera_ready, exposure_state


    def abortCcdExposure(self):
        pass


    def setCcdGain(self, gain_value):
        gain_f = float(round(gain_value), 2)

        # Update shared gain value
        with self.gain_av.get_lock():
            self.gain_av[constants.GAIN_CURRENT] = gain_f

        self.gain = gain_f


    def setCcdBinning(self, bin_value):
        if not bin_value:
            # Assume default
            return

        # Update shared bin value
        with self.bin_v.get_lock():
            self.bin_v.value = int(bin_value)

