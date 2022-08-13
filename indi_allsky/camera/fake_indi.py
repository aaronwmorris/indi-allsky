import logging

logger = logging.getLogger('indi_allsky')


class FakeIndiClient(object):

    def __init__(self, config, image_q, gain_v, bin_v, sensortemp_v):
        super(FakeIndiClient, self).__init__()

        self.config = config
        self.image_q = image_q
        self.gain_v = gain_v
        self.bin_v = bin_v
        self.sensortemp_v = sensortemp_v

        self._ccd_device = None
        self._ccd_gain = -1
        self._ccd_bin = 1
        self._ccd_frame_type = 'LIGHT'

        self._filename_t = 'ccd{0:d}_{1:s}.{2:s}'

        self._timeout = 65.0
        self._exposure = 0.0

        self.exposureStartTime = None

        logger.info('creating an instance of FakeIndiClient')



    @property
    def ccd_device(self):
        return self._ccd_device

    @ccd_device.setter
    def ccd_device(self, new_ccd_device):
        self._ccd_device = new_ccd_device


    @property
    def timeout(self):
        return self._timeout

    @timeout.setter
    def timeout(self, new_timeout):
        self._timeout = float(new_timeout)

    @property
    def exposure(self):
        return self._exposure

    @exposure.setter
    def exposure(self, new_exposure):
        self._exposure = float(new_exposure)

    @property
    def filename_t(self):
        return self._filename_t

    @filename_t.setter
    def filename_t(self, new_filename_t):
        self._filename_t = new_filename_t


    def setServer(self, *args, **kwargs):
        # does nothing
        pass


    def connectServer(self):
        # does nothing
        pass


    def getHost(self):
        return self.__class__.__name__


    def getPort(self):
        return 0


    def updateCcdBlobMode(self, *args, **kwargs):
        # does nothing
        pass


    def disableDebug(self, *args, **kwargs):
        # does nothing
        pass


    def resetCcdFrame(self, *args, **kwargs):
        # does nothing
        pass


    def setCcdFrameType(self, frame_type):
        self._ccd_frame_type = frame_type


    def getDeviceProperties(self, device):
        properties = dict()
        return properties


    def getCcdDeviceProperties(self):
        return self.getDeviceProperties(self._ccd_device)


    def getCcdInfo(self):
        ccdinfo = dict()
        return ccdinfo


    def findCcd(self):
        # override
        # create FakeIndiCcd object here
        pass


    def configureCcdDevice(self, *args, **kwargs):
        # does nothing
        pass


    def getCcdTemperature(self):
        temp_val = -273.15  # absolute zero  :-)
        return temp_val


    def setCcdExposure(self, exposure, sync=False, timeout=None):
        # override
        pass


    def getCcdExposureStatus(self):
        # override
        # returns camera_ready, exposure_state
        pass



    def getCcdGain(self):
        return self._ccd_gain


    def setCcdGain(self, gain_value):
        self._ccd_gain = int(gain_value)

        # Update shared gain value
        with self.gain_v.get_lock():
            self.gain_v.value = int(gain_value)


    def setCcdBinning(self, bin_value):
        self._ccd_bin = int(bin_value[0])

        # Update shared gain value
        with self.bin_v.get_lock():
            self.bin_v.value = int(bin_value[0])



class FakeIndiCcd(object):

    def __init__(self):
        super(FakeIndiCcd, self).__init__()

        # these should be set
        self._device_name = 'UNDEFINED'
        self._driver_exec = 'UNDEFINED'


    @property
    def device_name(self):
        return self._device_name

    @device_name.setter
    def device_name(self, new_device_name):
        self._device_name = new_device_name


    @property
    def driver_exec(self):
        return self._driver_exec

    @driver_exec.setter
    def driver_exec(self, new_driver_exec):
        self._driver_exec = new_driver_exec


    def getDeviceName(self):
        return self._device_name


    def getDriverExec(self):
        return self._driver_exec


