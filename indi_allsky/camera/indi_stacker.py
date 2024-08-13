import time
import io
import math
from datetime import datetime
from pathlib import Path
import tempfile
import logging

import PyIndi

from .indi import IndiClient

from ..exceptions import TimeOutException


logger = logging.getLogger('indi_allsky')



class IndiClientIndiStacker(IndiClient):

    def __init__(self, *args, **kwargs):
        super(IndiClientIndiStacker, self).__init__(*args, **kwargs)

        self.max_sub_exposure = 1.0
        self.exposure_remain = 0.0
        self.sub_exposure_count = 0

        self.camera_ready = True
        self.exposure_state = 'READY'

        self.data = None
        self.header = None


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


    def _startNextExposure(self):
        if self.exposure_remain < self.max_sub_exposure:
            logger.info('1 sub-exposures remain (%0.6f)', self.exposure_remain)
            sub_exposure = self.exposure_remain
            self.exposure_remain = 0.0
        else:
            exp_count = math.ceil(self.exposure_remain / self.max_sub_exposure)
            logger.info('%d sub-exposures remain (%0.6f)', exp_count, self.exposure_remain)

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

        # repopulate headers
        for k, v in self.header.items():
            hdulist[0].header[k] = v

        hdulist[0].header['BITPIX'] = 32
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
            self.data = hdulist[0].data.astype(numpy.uint32)

            # copy headers for later
            self.header = hdulist[0].header

            return


        self.data = numpy.add(self.data, hdulist[0].data)

