import io
from datetime import datetime
import time
import tempfile
import psutil
from pathlib import Path
import logging

from .indi import IndiClient
from .fake_indi import FakeIndiCcd

#from ..exceptions import TimeOutException

from threading import Thread


logger = logging.getLogger('indi_allsky')



class PycurlCameraWorker(Thread):
    def __init__(
        self,
        idx,
        config,
        dl_file,
    ):
        super(PycurlCameraWorker, self).__init__()

        self.name = 'PycurlCamera-{0:d}'.format(idx)

        self.config = config
        self.dl_file_p = Path(dl_file)

        self._timeout = 10


    def run(self):
        import pycurl

        client = pycurl.Curl()

        # deprecated: will be replaced by PROTOCOLS_STR
        client.setopt(pycurl.PROTOCOLS, pycurl.PROTO_HTTP | pycurl.PROTO_HTTPS | pycurl.PROTO_FILE)

        client.setopt(pycurl.CONNECTTIMEOUT, int(self._timeout))

        client.setopt(pycurl.HTTPHEADER, ['Accept: */*', 'Connection: Close'])

        client.setopt(pycurl.FOLLOWLOCATION, 1)

        client.setopt(pycurl.SSL_VERIFYPEER, False)  # trust verification
        client.setopt(pycurl.SSL_VERIFYHOST, False)  # host verfication

        username = self.config.get('PYCURL_CAMERA', {}).get('USERNAME')
        password = self.config.get('PYCURL_CAMERA', {}).get('PASSWORD')
        if username:
            client.setopt(pycurl.USERPWD, '{0:s}:{1:s}'.format(username, password))
            client.setopt(pycurl.HTTPAUTH, pycurl.HTTPAUTH_ANY)

        url = self.config.get('PYCURL_CAMERA', {}).get('URL', '')
        logger.info('Camera URL: %s', url)
        client.setopt(pycurl.URL, url)


        f_dl_file = io.open(str(self.dl_file_p), 'wb')
        client.setopt(pycurl.WRITEDATA, f_dl_file)


        try:
            client.perform()
        except pycurl.error as e:
            rc, msg = e.args

            if rc in [pycurl.E_LOGIN_DENIED]:
                logger.error('Authentication failed')
            elif rc in [pycurl.E_COULDNT_RESOLVE_HOST]:
                logger.error('Hostname resolution failed')
            elif rc in [pycurl.E_COULDNT_CONNECT]:
                logger.error('Connection failed')
            elif rc in [pycurl.E_OPERATION_TIMEDOUT]:
                logger.error('Connection timed out')
            elif rc in [pycurl.E_URL_MALFORMAT]:
                logger.error('Malformed URL')
            elif rc in [pycurl.E_UNSUPPORTED_PROTOCOL]:
                logger.error('Unsupported protocol')
            else:
                logger.error('pycurl error code: %d', rc)

            client.close()

            f_dl_file.close()
            self.dl_file_p.unlink()
            return


        http_error = client.getinfo(pycurl.RESPONSE_CODE)
        if http_error >= 400:
            logger.info('HTTP return code: %d', http_error)
            self.dl_file_p.unlink()


        f_dl_file.close()
        client.close()


class IndiClientPycurl(IndiClient):

    def __init__(self, *args, **kwargs):
        super(IndiClientPycurl, self).__init__(*args, **kwargs)

        self.pycurl_worker = None
        self.pycurl_worker_idx = 0

        self._exposure = None

        self._camera_id = None

        self._temp_val = -273.15  # absolute zero  :-)


        self.active_exposure = False
        self.current_exposure_file_p = None
        self.current_metadata_file_p = None

        memory_info = psutil.virtual_memory()
        self.memory_total_mb = memory_info[0] / 1024.0 / 1024.0


        self.ccd_device_name = 'pyCurl Camera'
        self.ccd_driver_exec = 'pycurl_camera'

        # bogus info for now
        self.camera_info = {
            'width'         : 1920,
            'height'        : 1080,
            'pixel'         : 2.0,
            'min_gain'      : 0,
            'max_gain'      : 0,
            'min_exposure'  : 0.000032,
            'max_exposure'  : 60.0,
            'cfa'           : None,
            'bit_depth'     : 8,
        }


    def getCcdGain(self):
        return self.gain_v.value


    def setCcdGain(self, new_gain_value):
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


        # Update shared gain value
        with self.bin_v.get_lock():
            self.bin_v.value = int(new_bin_value[0])


    def setCcdExposure(self, exposure, sync=False, timeout=None):
        if self.active_exposure:
            return


        file_type = self.config['PYCURL_CAMERA'].get('IMAGE_FILE_TYPE', 'jpg')


        try:
            image_tmp_f = tempfile.NamedTemporaryFile(mode='w', suffix='.{0:s}'.format(file_type), delete=True)
            image_tmp_f.close()
            image_tmp_p = Path(image_tmp_f.name)

        except OSError as e:
            logger.error('OSError: %s', str(e))
            return



        self.current_exposure_file_p = image_tmp_p


        self._exposure = exposure



        self.exposureStartTime = time.time()

        self.pycurl_worker_idx += 1
        self.pycurl_worker = PycurlCameraWorker(
            self.pycurl_worker_idx,
            self.config,
            image_tmp_p,
        )
        self.pycurl_worker.start()

        self.active_exposure = True

        if sync:
            self.pycurl_worker.join(timeout=30.0)

            self.active_exposure = False

            self._queueImage()


    def getCcdExposureStatus(self):
        # returns camera_ready, exposure_state
        if not self.pycurl_worker:
            return True, 'READY'


        if self.pycurl_worker.is_alive():
            return False, 'BUSY'


        if self.active_exposure:
            # if we get here, that means the camera is finished with the exposure
            self.active_exposure = False

            self._queueImage()


        return True, 'READY'


    def abortCcdExposure(self):
        logger.warning('Aborting exposure')

        self.pycurl_worker.join(timeout=15.0)

        self.active_exposure = False


        try:
            self.current_exposure_file_p.unlink()
        except FileNotFoundError:
            pass


    def _queueImage(self):
        exposure_elapsed_s = time.time() - self.exposureStartTime

        exp_date = datetime.now()

        ### process data in worker
        jobdata = {
            'filename'    : str(self.current_exposure_file_p),
            'exposure'    : self._exposure,
            'exp_time'    : datetime.timestamp(exp_date),  # datetime objects are not json serializable
            'exp_elapsed' : exposure_elapsed_s,
            'camera_id'   : self.camera_id,
            'filename_t'  : self._filename_t,
        }

        self.image_q.put(jobdata)


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

        self.ccd_device = new_ccd

        return new_ccd


    def getCcdInfo(self):
        ccdinfo = dict()

        ccdinfo['CCD_EXPOSURE'] = dict()
        ccdinfo['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE'] = {
            'current' : None,
            'min'     : self.ccd_device.min_exposure,
            'max'     : self.ccd_device.max_exposure,
            'step'    : None,
            'format'  : None,
        }

        ccdinfo['CCD_INFO'] = dict()
        ccdinfo['CCD_INFO']['CCD_MAX_X'] = dict()
        ccdinfo['CCD_INFO']['CCD_MAX_Y'] = dict()
        ccdinfo['CCD_INFO']['CCD_PIXEL_SIZE'] = {
            'current' : self.ccd_device.pixel,
            'min'     : self.ccd_device.pixel,
            'max'     : self.ccd_device.pixel,
            'step'    : None,
            'format'  : None,
        }

        ccdinfo['CCD_INFO']['CCD_PIXEL_SIZE_X'] = {
            'current' : self.ccd_device.pixel,
            'min'     : self.ccd_device.pixel,
            'max'     : self.ccd_device.pixel,
            'step'    : None,
            'format'  : None,
        }

        ccdinfo['CCD_INFO']['CCD_PIXEL_SIZE_Y'] = {
            'current' : self.ccd_device.pixel,
            'min'     : self.ccd_device.pixel,
            'max'     : self.ccd_device.pixel,
            'step'    : None,
            'format'  : None,
        }

        ccdinfo['CCD_INFO']['CCD_BITSPERPIXEL'] = {
            'current' : self.ccd_device.bit_depth,
            'min'     : self.ccd_device.bit_depth,
            'max'     : self.ccd_device.bit_depth,
            'step'    : None,
            'format'  : None,
        }

        ccdinfo['CCD_CFA'] = dict()
        ccdinfo['CCD_CFA']['CFA_TYPE'] = {
            'text' : self.ccd_device.cfa,
        }

        ccdinfo['CCD_FRAME'] = dict()
        ccdinfo['CCD_FRAME']['X'] = dict()
        ccdinfo['CCD_FRAME']['Y'] = dict()

        ccdinfo['CCD_FRAME']['WIDTH'] = {
            'current' : self.ccd_device.width,
            'min'     : self.ccd_device.width,
            'max'     : self.ccd_device.width,
            'step'    : None,
            'format'  : None,
        }

        ccdinfo['CCD_FRAME']['HEIGHT'] = {
            'current' : self.ccd_device.height,
            'min'     : self.ccd_device.height,
            'max'     : self.ccd_device.height,
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
            'current' : self.ccd_device.min_gain,
            'min'     : self.ccd_device.min_gain,
            'max'     : self.ccd_device.max_gain,
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
        return self._temp_val


    def setCcdTemperature(self, *args, **kwargs):
        # not supported
        pass


    def setCcdScopeInfo(self, *args):
        # not supported
        pass

