import time
import logging
#from pprint import pformat

import PyIndi

from .indi import IndiClient

#from ..flask import db
from ..flask import create_app

#from ..flask.models import TaskQueueQueue
#from ..flask.models import TaskQueueState
#from ..flask.models import IndiAllSkyDbTaskQueueTable

logger = logging.getLogger('indi_allsky')


app = create_app()


class IndiClientPassive(IndiClient):

    __state_to_str_p = {
        PyIndi.IPS_IDLE  : 'IDLE',
        PyIndi.IPS_OK    : 'OK',
        PyIndi.IPS_BUSY  : 'BUSY',
        PyIndi.IPS_ALERT : 'ALERT',
    }


    def __init__(
        self,
        config,
        image_q,
        latitude_v,
        longitude_v,
        elevation_v,
        ra_v,
        dec_v,
        gain_v,
        bin_v,
        night_v,
    ):
        super(IndiClient, self).__init__()

        self.config = config
        self.image_q = image_q

        self.latitude_v = latitude_v
        self.longitude_v = longitude_v
        self.elevation_v = elevation_v

        self.ra_v = ra_v
        self.dec_v = dec_v

        self.gain_v = gain_v
        self.bin_v = bin_v

        self.night_v = night_v

        self._camera_id = None

        self._ccd_device = None
        self._ctl_ccd_exposure = None

        self._telescope_device = None
        self._gps_device = None

        self._filename_t = 'ccd{0:d}_{1:s}.{2:s}'

        self._timeout = 10.0
        self._exposure = 0.0

        self.exposureStartTime = None

        logger.info('creating an instance of IndiClient')

        pyindi_version = '.'.join((
            str(getattr(PyIndi, 'INDI_VERSION_MAJOR', -1)),
            str(getattr(PyIndi, 'INDI_VERSION_MINOR', -1)),
            str(getattr(PyIndi, 'INDI_VERSION_RELEASE', -1)),
        ))
        logger.info('PyIndi version: %s', pyindi_version)


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


    def setCcdExposure(self, exposure, sync=False, timeout=None):
        self.exposureStartTime = time.time()

        self._exposure = exposure

        ctl_ccd_exposure = self.get_control(self.ccd_device, 'CCD_EXPOSURE', 'number')

        self._ctl_ccd_exposure = ctl_ccd_exposure


    def getCcdExposureStatus(self):
        camera_ready, exposure_state = self.ctl_ready(self._ctl_ccd_exposure)

        return camera_ready, exposure_state


    def abortCcdExposure(self):
        pass


    def setCcdGain(self, gain_value):
        # Update shared gain value
        with self.gain_v.get_lock():
            self.gain_v.value = int(gain_value)


    def setCcdBinning(self, bin_value):
        if not bin_value:
            # Assume default
            return

        # Update shared gain value
        with self.bin_v.get_lock():
            self.bin_v.value = int(bin_value)

