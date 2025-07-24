import io
from datetime import datetime
import time
from pathlib import Path
import random
import tempfile
import logging

from .indi import IndiClient
from .fake_indi import FakeIndiCcd

#from ..exceptions import TimeOutException


logger = logging.getLogger('indi_allsky')


class IndiClientTestCameraBase(IndiClient):
    def __init__(self, *args, **kwargs):
        super(IndiClientTestCameraBase, self).__init__(*args, **kwargs)

        self._camera_id = None


        self._exposure = None
        self.exposureStartTime = None


        self.active_exposure = False


        self._temp_val = -273.15  # absolute zero  :-)

        self.ccd_device = None
        self.ccd_device_name = 'OVERRIDE'
        self.ccd_driver_exec = 'OVERRIDE'


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


    def setCcdBinning(self, bin_value):
        if not bin_value:
            # Assume default
            return


        # Update shared gain value
        with self.bin_v.get_lock():
            self.bin_v.value = int(bin_value)


    def setCcdExposure(self, exposure, sync=False, timeout=None):
        pass


    def getCcdExposureStatus(self):
        pass


    def abortCcdExposure(self):
        pass


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


class IndiClientTestCameraBubbles(IndiClientTestCameraBase):

    bubble_speed = 100
    bubble_radius_min = 5
    bubble_radius_max = 100


    def __init__(self, *args, **kwargs):
        super(IndiClientTestCameraBubbles, self).__init__(*args, **kwargs)

        self.current_exposure_file_p = None

        self._bubbles_list = []
        self._image = None


        self.ccd_device = None
        self.ccd_device_name = 'Bubbles Test Camera'
        self.ccd_driver_exec = 'bubbles_test_camera'


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


    def setCcdExposure(self, exposure, sync=False, timeout=None):
        if self.active_exposure:
            return


        self._exposure = exposure

        self.active_exposure = True

        self.exposureStartTime = time.time()


        try:
            image_tmp_f = tempfile.NamedTemporaryFile(mode='w', suffix='.fit', delete=False)
            image_tmp_f.close()
            image_tmp_p = Path(image_tmp_f.name)

        except OSError as e:
            logger.error('OSError: %s', str(e))
            return

        self.current_exposure_file_p = image_tmp_p


        # update the synthetic image
        self.updateBubbles()


        if sync:
            self.active_exposure = False

            self._queueImage()


    def getCcdExposureStatus(self):
        if self.active_exposure:
            if time.time() - self.exposureStartTime < self._exposure:
                # wait until expected exposure finishes
                return False, 'BUSY'

            self.active_exposure = False

            self._queueImage()

            return True, 'READY'

        return True, 'READY'


    def abortCcdExposure(self):
        logger.warning('Aborting exposure')

        self.active_exposure = False


        try:
            self.current_exposure_file_p.unlink()
        except FileNotFoundError:
            pass


    def _queueImage(self):
        exposure_elapsed_s = time.time() - self.exposureStartTime

        exp_date = datetime.now()

        self.write_fit(exp_date)

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


    def updateBubbles(self):
        import numpy
        import cv2

        if not self._bubbles_list:
            # create new set of random bubbles
            for _ in range(300):
                r = random.randrange(255)
                g = random.randrange(255)
                b = random.randrange(255)
                radius = random.randrange(self.bubble_radius_min, self.bubble_radius_max)
                x = random.randrange(self.camera_info['width'])
                y = random.randrange(self.camera_info['height'] * 2)


                self._bubbles_list.append({
                    'x' : x,
                    'y' : y,
                    'radius' : radius,
                    'color' : (r, g, b),
                })


        #logger.info('Bubbles: %s', self._bubbles_list)


        # create blank image
        self._image = numpy.zeros(
            [
                self.camera_info['height'],
                self.camera_info['width'],
                3
            ],
            dtype=numpy.uint8,
        )


        for bubble in self._bubbles_list:
            # move bubbles up
            # indi-allsky normally flips the image by default, so the operations are backwards

            bubble['y'] += self.bubble_speed

            if bubble['y'] > (self.camera_info['height'] * 2):
                # move to top
                bubble['y'] = (self.bubble_radius_max * -1) + ((self.camera_info['height'] * 2) % self.bubble_speed)


            cv2.circle(
                self._image,
                center=(bubble['x'], bubble['y']),
                radius=bubble['radius'],
                color=bubble['color'],
                thickness=cv2.FILLED,
                lineType=cv2.LINE_AA,
            )


    def write_fit(self, exp_date):
        import numpy
        from astropy.io import fits


        data = self._image[
            0:self.camera_info['height'],
            0:self.camera_info['width'],
        ]


        if len(data.shape) == 3:
            # swap axes for FITS
            data = numpy.swapaxes(data, 1, 0)
            data = numpy.swapaxes(data, 2, 0)


        # create a new fits container
        hdu = fits.PrimaryHDU(data)
        hdulist = fits.HDUList([hdu])

        hdu.update_header()  # populates BITPIX, NAXIS, etc


        hdulist[0].header['IMAGETYP'] = 'Light Frame'
        hdulist[0].header['INSTRUME'] = 'Bubbles'
        hdulist[0].header['EXPTIME'] = float(self._exposure)
        hdulist[0].header['XBINNING'] = 1
        hdulist[0].header['YBINNING'] = 1
        hdulist[0].header['GAIN'] = float(self.gain_v.value)
        hdulist[0].header['CCD-TEMP'] = self._temp_val
        #hdulist[0].header['SITELAT'] =
        #hdulist[0].header['SITELONG'] =
        #hdulist[0].header['RA'] =
        #hdulist[0].header['DEC'] =
        hdulist[0].header['DATE-OBS'] = exp_date.isoformat()
        #hdulist[0].header['BITPIX'] = 8


        with io.open(str(self.current_exposure_file_p), 'wb') as f_image:
            hdulist.writeto(f_image)

