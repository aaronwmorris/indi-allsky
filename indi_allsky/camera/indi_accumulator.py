import time
import copy
import io
import math
from datetime import datetime
from pathlib import Path
import tempfile
from pprint import pformat  # noqa: F401
import logging

import PyIndi

from .indi import IndiClient

from ..exceptions import TimeOutException


logger = logging.getLogger('indi_allsky')



class IndiClientIndiAccumulator(IndiClient):

    def __init__(self, *args, **kwargs):
        super(IndiClientIndiAccumulator, self).__init__(*args, **kwargs)

        self._max_sub_exposure = self.config.get('ACCUM_CAMERA', {}).get('SUB_EXPOSURE_MAX', 1.0)

        self.exposure_remain = 0.0
        self.sub_exposure_count = 0

        self.camera_ready = True
        self.exposure_state = 'READY'

        self.data = None
        self.header = None


    @property
    def max_sub_exposure(self):
        return self._max_sub_exposure


    def setCcdExposure(self, exposure, sync=False, timeout=None):
        if not timeout:
            timeout = self.timeout

        exp_count = math.ceil(exposure / self.max_sub_exposure)
        logger.info('Taking %d sub-exposures for stacking', exp_count)

        self.data = None
        self.header = None
        self.sub_exposure_count = 0

        self.exposure = exposure
        self.exposure_remain = float(exposure)


        self.exposureStartTime = time.time()

        self._startNextExposure()


        if sync:
            while True:
                camera_ready, exposure_state = self.getCcdExposureStatus()

                if camera_ready:
                    break

                time.sleep(0.1)


    def _startNextExposure(self):
        if self.exposure_remain < self.max_sub_exposure:
            logger.info('1 sub-exposures remain (%0.6fs)', self.exposure_remain)
            sub_exposure = self.exposure_remain
            self.exposure_remain = 0.0
        else:
            exp_count = math.ceil(self.exposure_remain / self.max_sub_exposure)
            logger.info('%d sub-exposures remain (%0.6fs)', exp_count, self.exposure_remain)

            sub_exposure = self.max_sub_exposure
            self.exposure_remain -= sub_exposure


        self.set_number(self.ccd_device, 'CCD_EXPOSURE', {'CCD_EXPOSURE_VALUE': sub_exposure}, sync=False, timeout=self.timeout)

        self.camera_ready = False
        self.exposure_state = 'BUSY'


    def getCcdExposureStatus(self):
        return self.camera_ready, self.exposure_state


    def abortCcdExposure(self):
        logger.warning('Aborting exposure')
        self.exposure_remain = 0.0
        self.camera_ready = True
        self.exposure_state = 'READY'


        try:
            ccd_abort = self.get_control(self.ccd_device, 'CCD_ABORT_EXPOSURE', 'switch', timeout=2.0)
        except TimeOutException:
            logger.warning("Abort not supported")
            return


        if ccd_abort.getPermission() == PyIndi.IP_RO:
            logger.warning("Abort control is read only")
            return


        ccd_abort[0].setState(PyIndi.ISS_ON)   # ABORT

        self.sendNewSwitch(ccd_abort)


    def processBlob(self, blob):
        from astropy.io import fits

        self._appendExposure(blob)

        if self.exposure_remain > 0.0:
            self._startNextExposure()
            return


        exposure_elapsed_s = time.time() - self.exposureStartTime

        # create a new fits container
        hdu = fits.PrimaryHDU(self.data)
        hdulist = fits.HDUList([hdu])

        hdu.update_header()
        #logger.info('Headers: %s', pformat(hdulist[0].header))

        # repopulate headers
        for k, v in self.header.items():
            if k in ('BITPIX', 'BZERO', 'BSCALE', 'EXPTIME', 'NAXIS', 'NAXIS1', 'NAXIS2', 'EXTEND'):
                continue

            hdulist[0].header[k] = v

        #hdulist[0].header['BITPIX'] = X  # automatically populated by hdu.update_header()
        hdulist[0].header['EXPTIME'] = self.exposure
        hdulist[0].header['SUBCOUNT'] = self.sub_exposure_count



        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.fit')

        try:
            hdulist.writeto(f_tmpfile)
            f_tmpfile.flush()
            f_tmpfile.close()
        except OSError as e:
            logger.error('OSError: %s', str(e))
            self.data = None
            self.header = None
            return


        tmpfile_p = Path(f_tmpfile.name)

        exp_date = datetime.now()

        ### process data in worker
        jobdata = {
            'filename'    : str(tmpfile_p),
            'exposure'    : self.exposure,
            'exp_time'    : datetime.timestamp(exp_date),  # datetime objects are not json serializable
            'exp_elapsed' : exposure_elapsed_s,
            'camera_id'   : self.camera_id,
            'filename_t'  : self._filename_t,
        }

        self.image_q.put(jobdata)


        self.camera_ready = True
        self.exposure_state = 'READY'

        self.data = None
        self.header = None


    def _appendExposure(self, blob):
        from astropy.io import fits
        import numpy

        self.sub_exposure_count += 1

        imgdata = blob.getblobdata()
        blobfile = io.BytesIO(imgdata)
        hdulist = fits.open(blobfile)


        if isinstance(self.data, type(None)):
            #self.data = hdulist[0].data.astype(numpy.float32)
            self.data = hdulist[0].data.astype(numpy.uint32)

            # copy headers for later
            self.header = copy.copy(hdulist[0].header)

            return


        self.data = numpy.add(self.data, hdulist[0].data)


    def getCcdInfo(self):
        ccd_info = super(IndiClientIndiAccumulator, self).getCcdInfo()

        ccd_max_exp = float(ccd_info['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['max'])

        # if the camera has a low max exposure, return a higher value for the accumulator
        if ccd_max_exp < 600:
            ccd_info['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['max'] = 600.0

        return ccd_info

