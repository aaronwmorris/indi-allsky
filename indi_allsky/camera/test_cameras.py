import io
from datetime import datetime
import time
from pathlib import Path
import math
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
        self.current_exposure_file_p = None


        self._image = None

        self.active_exposure = False


        self._temp_val = -273.15  # absolute zero  :-)

        self.ccd_device = None
        self.ccd_device_name = 'OVERRIDE'
        self.ccd_driver_exec = 'OVERRIDE'


        # bogus info for now
        self.camera_info = {
            'width'         : 4056,
            'height'        : 3040,
            'pixel'         : 2.0,
            'min_gain'      : 0,
            'max_gain'      : 0,
            'min_exposure'  : 0.000032,
            'max_exposure'  : 60.0,
            'cfa'           : None,
            'bit_depth'     : 8,
        }


        self._indi_allsky_var_p = '/var/lib/indi-allsky'



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
        self.updateImage()


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


    def write_fit(self, exp_date):
        import numpy
        from astropy.io import fits


        data = self._image


        if len(data.shape) == 3:
            # swap axes for FITS
            data = numpy.swapaxes(data, 1, 0)
            data = numpy.swapaxes(data, 2, 0)


        # create a new fits container
        hdu = fits.PrimaryHDU(data)
        hdulist = fits.HDUList([hdu])

        hdu.update_header()  # populates BITPIX, NAXIS, etc


        hdulist[0].header['IMAGETYP'] = 'Light Frame'
        hdulist[0].header['INSTRUME'] = 'Test Camera'
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


class IndiClientTestCameraBubbles(IndiClientTestCameraBase):

    bubble_count = 1000
    bubble_speed = 100
    bubble_radius_min = 5
    bubble_radius_max = 100


    def __init__(self, *args, **kwargs):
        super(IndiClientTestCameraBubbles, self).__init__(*args, **kwargs)

        self.ccd_device = None
        self.ccd_device_name = 'Bubbles Test Camera'
        self.ccd_driver_exec = 'bubbles_test_camera'


        # bogus info for now
        #self.camera_info = {
        #    'width'         : 4056,
        #    'height'        : 3040,
        #    'pixel'         : 2.0,
        #    'min_gain'      : 0,
        #    'max_gain'      : 0,
        #    'min_exposure'  : 0.000032,
        #    'max_exposure'  : 60.0,
        #    'cfa'           : None,
        #    'bit_depth'     : 8,
        #}


        self._bubbles_list = []


    def updateImage(self):
        import numpy
        import cv2

        if not self._bubbles_list:
            # create new set of random bubbles
            for _ in range(self.bubble_count):
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


class IndiClientTestCameraStars(IndiClientTestCameraBase):
    # This is basically a flat-earth sky simulator :-)

    star_count = 150000
    star_color = (127, 127, 127)
    rotation_degrees = 1
    star_sizes = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 3]


    def __init__(self, *args, **kwargs):
        super(IndiClientTestCameraStars, self).__init__(*args, **kwargs)

        self.ccd_device = None
        self.ccd_device_name = 'Stars Test Camera'
        self.ccd_driver_exec = 'stars_test_camera'


        # bogus info for now
        #self.camera_info = {
        #    'width'         : 4056,
        #    'height'        : 3040,
        #    'pixel'         : 2.0,
        #    'min_gain'      : 0,
        #    'max_gain'      : 0,
        #    'min_exposure'  : 0.000032,
        #    'max_exposure'  : 60.0,
        #    'cfa'           : None,
        #    'bit_depth'     : 8,
        #}


        self._base_image = None
        self.base_image_width = self.camera_info['width'] * 3
        self.base_image_height = self.camera_info['height'] * 3

        self.xy_array = None


        self._stars_list = []


    def updateImage(self):
        import numpy
        import cv2
        #from scipy.indimage import rotate


        center_x = int(self.base_image_width / 2)
        center_y = int(self.base_image_height / 2)


        if not self._stars_list:
            self.xy_array = numpy.zeros([2, self.star_count], dtype=numpy.float32)

            # create new set of random stars
            for i in range(self.star_count):
                #r = random.randrange(255)
                #g = random.randrange(255)
                #b = random.randrange(255)

                radius = random.choice(self.star_sizes)

                x = random.randrange(self.base_image_width)
                y = random.randrange(self.base_image_height)
                self.xy_array[0][i] = x
                self.xy_array[1][i] = y
                #logger.info('XY: %d x %d', x, y)


                self._stars_list.append({
                    'radius' : radius,
                    #'color' : (r, g, b),
                })


        # create blank image
        self._base_image = numpy.zeros(
            [
                self.base_image_height,
                self.base_image_width,
                3
            ],
            dtype=numpy.uint8,
        )


        # test circle
        #cv2.circle(
        #    self._base_image,
        #    center=(int(self.base_image_width / 2), int(self.base_image_height / 2)),
        #    radius=int(self.base_image_height / 4),
        #    color=(64, 64, 64),
        #    thickness=3,
        #    lineType=cv2.LINE_AA,
        #)


        #rot_start = time.time()

        # calculate new coordinates based on rotation (vectorized)
        Ax = self.xy_array[0] - center_x
        Ay = self.xy_array[1] - center_y

        rot_radians = math.radians(self.rotation_degrees)
        self.xy_array[0] = (center_x + (math.cos(rot_radians) * Ax + math.sin(rot_radians) * Ay)).astype(numpy.float32)
        self.xy_array[1] = (center_y + ((math.sin(rot_radians) * -1) * Ax + math.cos(rot_radians) * Ay)).astype(numpy.float32)


        #rot_elapsed_s = time.time() - rot_start
        #logger.info('Star rotation in %0.4f s', rot_elapsed_s)


        # redraw the stars
        for i, star in enumerate(self._stars_list):
            center = (int(self.xy_array[0][i]), int(self.xy_array[1][i]))
            #logger.info('Center: %s', center)

            cv2.circle(
                self._base_image,
                center=center,
                radius=star['radius'],
                color=self.star_color,
                #color=star['color'],
                thickness=cv2.FILLED,
                lineType=cv2.LINE_AA,
            )



        #self._base_image = rotate(self._base_image, angle=self.rotation_degrees, reshape=False)


        # slice the image
        start_width = int(center_x - (self.camera_info['width'] / 2))  # center width
        start_height = int(center_y - (self.camera_info['height'] / 3))  # offset height

        #logger.info('Center: %d x %d - Start: %d x %d', center_x, center_y, start_width, start_height)

        self._image = self._base_image[
            start_height:start_height + self.camera_info['height'],
            start_width:start_width + self.camera_info['width'],
        ]

