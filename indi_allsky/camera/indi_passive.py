import time
from decimal import Decimal
import logging
#from pprint import pformat

from .indi import IndiClient

#from .. import constants

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


    def setCcdExposure(self, exposure, gain, binning, sync=False, timeout=None, sqm_exposure=False):
        self.exposureStartTime = time.time()


        if not isinstance(exposure, Decimal):
            exposure_d = Decimal('{0:0.6f}'.format(float(exposure)))
        else:
            exposure_d = exposure

        if not isinstance(gain, Decimal):
            gain_d = Decimal('{0:0.3f}'.format(float(gain)))
        else:
            gain_d = gain


        self.exposure = exposure_d
        self.sqm_exposure = sqm_exposure

        if self.gain != gain_d:
            self.setCcdGain(gain_d)

        if self.binning != int(binning):
            self.setCcdBinning(binning)

        ctl_ccd_exposure = self.get_control(self.ccd_device, 'CCD_EXPOSURE', 'number')

        self._ctl_ccd_exposure = ctl_ccd_exposure


        # Update shared exposure value
        self._expUtils.EXPOSURE_CURRENT = exposure_d


    def getCcdExposureStatus(self):
        camera_ready, exposure_state = self.ctl_ready(self._ctl_ccd_exposure)

        return camera_ready, exposure_state


    def abortCcdExposure(self):
        pass


    def setCcdGain(self, new_gain):
        if not isinstance(new_gain, Decimal):
            gain_d = Decimal('{0:0.3f}'.format(float(new_gain)))
        else:
            gain_d = new_gain

        # Update shared gain value
        self._expUtils.GAIN_CURRENT = gain_d

        self.gain = gain_d


    def setCcdBinning(self, bin_value):
        if not bin_value:
            # Assume default
            return

        # Update shared bin value
        self._expUtils.BINNING_CURRENT = bin_value

        self.binning = int(bin_value)

