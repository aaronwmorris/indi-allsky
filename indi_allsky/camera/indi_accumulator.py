import time
import copy
import io
import math
from datetime import datetime
from pathlib import Path
import tempfile
from pprint import pformat  # noqa: F401
import numpy
import logging

import PyIndi

from .indi import IndiClient

from .. import constants

from ..exceptions import TimeOutException


logger = logging.getLogger('indi_allsky')



class IndiClientIndiAccumulator(IndiClient):

    def __init__(self, *args, **kwargs):
        super(IndiClientIndiAccumulator, self).__init__(*args, **kwargs)

        self._sub_exposure_max = self.config.get('ACCUM_CAMERA', {}).get('SUB_EXPOSURE_MAX', 1.0)
        self._even_exposures = self.config.get('ACCUM_CAMERA', {}).get('EVEN_EXPOSURES', True)
        self._clamp_16bit = self.config.get('ACCUM_CAMERA', {}).get('CLAMP_16BIT', False)


        self._total_sub_exposures = 0  # total number of expected sub exposures
        self._sub_exposure_base = 0.0  # current sub-exposure max

        self.exposure_remain = 0.0  # remaining exposure time
        self.current_sub_exposure_count = 0  # current count of sub exposures

        self.camera_ready = True
        self.exposure_state = 'READY'

        self.data = None
        self.header = None

        self.ccd_min_exp = None  # updated in getCcdInfo()


    @property
    def sub_exposure_max(self):
        return self._sub_exposure_max

    @property
    def sub_exposure_base(self):
        return self._sub_exposure_base

    @property
    def even_exposures(self):
        return self._even_exposures

    @property
    def total_sub_exposures(self):
        return self._total_sub_exposures

    @property
    def clamp_16bit(self):
        return self._clamp_16bit


    def setCcdExposure(self, exposure, sync=False, timeout=None):
        if not self.camera_ready:
            raise Exception('Camera is busy')

        if not timeout:
            timeout = self.timeout


        self._total_sub_exposures = math.ceil(exposure / self.sub_exposure_max)

        if self.even_exposures:
            # the sub exposure length should be even for all exposures
            self._sub_exposure_base = exposure / self.total_sub_exposures
        else:
            # any remainder of exposure will result in a short final sub-exposure
            self._sub_exposure_base = self.sub_exposure_max


        logger.info('Taking %d sub-exposures for accumulation, using %0.6f as the base exposure', self.total_sub_exposures, self.sub_exposure_base)

        self.data = None
        self.header = None
        self.current_sub_exposure_count = 0  # reset

        self.exposure = exposure
        self.gain = float(self.gain_av[constants.GAIN_CURRENT])
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
        exp_count = self.total_sub_exposures - self.current_sub_exposure_count

        if self.exposure_remain < self.ccd_min_exp:
            logger.warning('Last sub-exposure is below the minimum exposure (%0.6fs), increasing to minimum', self.exposure_remain)
            sub_exposure = self.ccd_min_exp + 0.00000001  # offset to deal with conversion issues
            self.exposure_remain = 0.0
        elif exp_count == 1:
            if self.even_exposures:
                logger.info('1 sub-exposures remain (%0.6fs)', self.exposure_remain)
                sub_exposure = self.sub_exposure_base
            else:
                logger.info('1 sub-exposures remain (%0.6fs)', self.exposure_remain)
                sub_exposure = self.exposure_remain

            self.exposure_remain = 0.0
        else:
            logger.info('%d sub-exposures remain (%0.6fs)', exp_count, self.exposure_remain)

            sub_exposure = self.sub_exposure_base
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


        if self.clamp_16bit:
            # pre-scale data to 16-bits
            self.data = numpy.clip(self.data, 0, 65535).astype(numpy.uint16)


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
        hdulist[0].header['SUBCOUNT'] = self.total_sub_exposures



        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.fit')

        try:
            hdulist.writeto(f_tmpfile)
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
            'gain'        : self.gain,
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

        self.current_sub_exposure_count += 1

        imgdata = blob.getblobdata()
        blobfile = io.BytesIO(imgdata)
        hdulist = fits.open(blobfile)


        if isinstance(self.data, type(None)):
            # cast to 32-bit
            self.data = hdulist[0].data.astype(numpy.uint32)
            #self.data = hdulist[0].data.astype(numpy.float32)

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

        # store for internal use
        self.ccd_min_exp = float(ccd_info['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['min'])

        return ccd_info

