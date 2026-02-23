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

from .. import constants

#from ..exceptions import TimeOutException


logger = logging.getLogger('indi_allsky')


class IndiClientTestCameraBase(IndiClient):

    image_bit_depth = 16


    def __init__(self, *args, **kwargs):
        super(IndiClientTestCameraBase, self).__init__(*args, **kwargs)

        self.current_exposure_file_p = None


        self._image = None

        self.active_exposure = False


        self._temp_val = -273.15  # absolute zero  :-)

        self.ccd_device_name = 'OVERRIDE'
        self.ccd_driver_exec = 'OVERRIDE'


        self._width = self.config.get('TEST_CAMERA', {}).get('WIDTH', 4056)
        self._height = self.config.get('TEST_CAMERA', {}).get('HEIGHT', 3040)
        self._image_circle_diameter = self.config.get('TEST_CAMERA', {}).get('IMAGE_CIRCLE_DIAMETER', 3500)


        # bogus info for now
        self.camera_info = {
            'width'         : self.width,
            'height'        : self.height,
            'pixel'         : 2.0,
            'min_gain'      : 0.0,
            'max_gain'      : 0.0,
            'min_exposure'  : 0.000032,
            'max_exposure'  : 60.0,
            'min_binning'   : 1,
            'max_binning'   : 4,
            'cfa'           : None,
            'bit_depth'     : 16,
        }


        self._last_exposure_time = time.time()

        self._image_circle_alpha_mask_dict = dict()  # each key is binning mode


        varlib_folder = self.config.get('VARLIB_FOLDER', '/var/lib/indi-allsky')
        self.varlib_folder_p = Path(varlib_folder)


    @property
    def height(self):
        return self._height

    @property
    def width(self):
        return self._width

    @property
    def image_circle_diameter(self):
        return self._image_circle_diameter


    def getCcdGain(self):
        return float(self.gain_av[constants.GAIN_CURRENT])


    def setCcdGain(self, new_gain_value):
        gain_f = float(round(new_gain_value, 2))

        # Update shared gain value
        with self.gain_av.get_lock():
            self.gain_av[constants.GAIN_CURRENT] = gain_f

        self.gain = gain_f


    def setCcdBinning(self, bin_value):
        if not bin_value:
            # Assume default
            return


        # Update shared bin value
        with self.binning_av.get_lock():
            self.binning_av[constants.BINNING_CURRENT] = int(bin_value)


        self.binning = int(bin_value)


    def setCcdExposure(self, exposure, gain, binning, sync=False, timeout=None, sqm_exposure=False):
        if self.active_exposure:
            return


        self.exposure = exposure
        self.sqm_exposure = sqm_exposure


        if self.gain != float(round(gain, 2)):
            self.setCcdGain(gain)  # gain does not do anything

        if self.binning != int(binning):
            self.setCcdBinning(binning)  # binning does not do anything


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
        self.updateImage(self.binning)


        # update reference
        self._last_exposure_time = time.time()


        # Update shared exposure value
        with self.exposure_av.get_lock():
            self.exposure_av[constants.EXPOSURE_CURRENT] = float(exposure)


        if sync:
            time.sleep(self.exposure)

            self.active_exposure = False

            self._queueImage()


    def getCcdExposureStatus(self):
        if self.active_exposure:
            if time.time() - self.exposureStartTime < self.exposure:
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
            'exposure'    : self.exposure,
            'gain'        : self.gain,
            'binning'     : self.binning,
            'sqm_exposure': self.sqm_exposure,
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

        new_ccd.min_binning = self.camera_info['min_binning']
        new_ccd.max_binning = self.camera_info['max_binning']

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

        ccdinfo['BINNING_INFO'] = {
            'current' : self.ccd_device.min_binning,
            'min'     : self.ccd_device.min_binning,
            'max'     : self.ccd_device.max_binning,
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
        hdulist[0].header['EXPTIME'] = float(self.exposure)
        hdulist[0].header['XBINNING'] = 1
        hdulist[0].header['YBINNING'] = 1
        hdulist[0].header['GAIN'] = float(self.gain)
        hdulist[0].header['CCD-TEMP'] = self._temp_val
        #hdulist[0].header['SITELAT'] =
        #hdulist[0].header['SITELONG'] =
        #hdulist[0].header['RA'] =
        #hdulist[0].header['DEC'] =
        hdulist[0].header['DATE-OBS'] = exp_date.isoformat()
        #hdulist[0].header['BITPIX'] = 8


        with io.open(str(self.current_exposure_file_p), 'wb') as f_image:
            hdulist.writeto(f_image)


    def _generate_image_circle_mask(self, image, binning):
        import numpy
        import cv2

        image_height, image_width = image.shape[:2]

        max_value = (2 ** self.image_bit_depth) - 1

        opacity = 100
        background = int(max_value * (100 - opacity) / 100)

        channel_mask = numpy.full([image_height, image_width], background, dtype=numpy.uint16)

        center_x = int(image_width / 2)
        center_y = int(image_height / 2)
        radius = int((self.image_circle_diameter / binning) / 2)
        blur = 75


        # draw a white circle
        cv2.circle(
            img=channel_mask,
            center=(center_x, center_y),
            radius=radius,
            color=max_value,  # mono
            thickness=cv2.FILLED,
        )


        if blur:
            # blur circle
            channel_mask = cv2.blur(
                src=channel_mask,
                ksize=(blur, blur),
                borderType=cv2.BORDER_DEFAULT,
            )


        channel_alpha = (channel_mask / max_value).astype(numpy.float32)

        alpha_mask = numpy.dstack((channel_alpha, channel_alpha, channel_alpha))

        return alpha_mask


class IndiClientTestCameraBubbles(IndiClientTestCameraBase):

    bubble_speed = 100
    bubble_radius_min = 5
    bubble_radius_max = 100
    background_color = (24, 24, 24)


    def __init__(self, *args, **kwargs):
        super(IndiClientTestCameraBubbles, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'Bubbles Test Camera'
        self.ccd_driver_exec = 'test_bubbles'


        # bogus info for now
        #self.camera_info = {
        #    'width'         : self.width,
        #    'height'        : self.height,
        #    'pixel'         : 2.0,
        #    'min_gain'      : 0.0,
        #    'max_gain'      : 0.0,
        #    'min_exposure'  : 0.000032,
        #    'max_exposure'  : 60.0,
        #    'cfa'           : None,
        #    'bit_depth'     : 8,
        #}


        self.bubble_count = self.config.get('TEST_CAMERA', {}).get('BUBBLE_COUNT', 1000)

        self.bubbles_array = None

        self._bubbles_store_tmpl = 'test_bubbles_store_ccd{0:d}.npy'
        self._bubbles_store_p = None


    def disconnectServer(self, *args, **kwargs):
        import numpy

        if not isinstance(self._bubbles_store_p, type(None)):
            logger.info('Storing bubbles data')
            with io.open(str(self._bubbles_store_p), 'w+b') as f_numpy:
                numpy.save(f_numpy, self.bubbles_array)

        super(IndiClientTestCameraBubbles, self).disconnectServer(*args, **kwargs)


    def updateImage(self):
        import numpy
        import cv2


        if isinstance(self.bubbles_array, type(None)):
            # try to load data
            self._bubbles_store_p = self.varlib_folder_p.joinpath(self._bubbles_store_tmpl.format(self.camera_id))

            try:
                logger.info('Loading stored bubbles data')
                with io.open(str(self._bubbles_store_p), 'r+b') as f_numpy:
                    self.bubbles_array = numpy.load(f_numpy)

                if self.bubbles_array.shape[1] != self.bubble_count:
                    # if bubble count changes, create new array
                    self._bubbles_store_p.unlink()
                    self.bubbles_array = None
            except ValueError:
                logger.error('Invalid numpy data for bubbles')
                self._bubbles_store_p.unlink()
                self.bubbles_array = None
            except EOFError:
                logger.error('Invalid numpy data for bubbles')
                self._bubbles_store_p.unlink()
                self.bubbles_array = None
            except FileNotFoundError:
                pass


        if isinstance(self.bubbles_array, type(None)):
            # create new set of random bubbles
            self.bubbles_array = numpy.zeros([6, self.bubble_count], dtype=numpy.int16)  # x, y, radius, r, g, b


            max_value = (2 ** self.image_bit_depth) - 1

            for i in range(self.bubbles_array.shape[1]):
                r = random.randrange(max_value)
                g = random.randrange(max_value)
                b = random.randrange(max_value)

                radius = random.randrange(self.bubble_radius_min, self.bubble_radius_max)

                x = random.randrange(self.camera_info['width'])
                y = random.randrange(self.camera_info['height'] * 2)


                self.bubbles_array[0][i] = x
                self.bubbles_array[1][i] = y
                self.bubbles_array[2][i] = radius
                self.bubbles_array[3][i] = r
                self.bubbles_array[4][i] = g
                self.bubbles_array[5][i] = b


        # create blank image
        self._image = numpy.full(
            [
                self.camera_info['height'],
                self.camera_info['width'],
                3
            ],
            self.background_color,
            dtype=numpy.uint16,
        )


        for i in range(self.bubbles_array.shape[1]):
            # move bubbles up
            # indi-allsky normally flips the image by default, so the operations are backwards

            self.bubbles_array[1][i] += self.bubble_speed

            if self.bubbles_array[1][i] > (self.camera_info['height'] * 2):
                # move to top
                self.bubbles_array[1][i] = (self.bubble_radius_max * -1) + ((self.camera_info['height'] * 2) % self.bubble_speed)


            center = (round(self.bubbles_array[0][i]), round(self.bubbles_array[1][i]))
            radius = int(self.bubbles_array[2][i])
            color = (int(self.bubbles_array[3][i]), int(self.bubbles_array[4][i]), int(self.bubbles_array[5][i]))

            cv2.circle(
                self._image,
                center=center,
                radius=radius,
                color=color,
                thickness=cv2.FILLED,
                lineType=cv2.LINE_AA,
            )


        if self.image_circle_diameter:
            if isinstance(self._image_circle_alpha_mask, type(None)):
                self._image_circle_alpha_mask = self._generate_image_circle_mask(self._image)


            # simulate an image circle
            self._image = (self._image * self._image_circle_alpha_mask).astype(numpy.uint16)


class IndiClientTestCameraRotatingStars(IndiClientTestCameraBase):
    # This is basically a flat-earth sky simulator :-)

    star_sizes = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 3]
    background_color = (24, 24, 24)


    def __init__(self, *args, **kwargs):
        super(IndiClientTestCameraRotatingStars, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'Rotating Stars Test Camera'
        self.ccd_driver_exec = 'test_rotating_stars'


        # bogus info for now
        #self.camera_info = {
        #    'width'         : self.width,
        #    'height'        : self.height,
        #    'pixel'         : 2.0,
        #    'min_gain'      : 0.0,
        #    'max_gain'      : 0.0,
        #    'min_exposure'  : 0.000032,
        #    'max_exposure'  : 60.0,
        #    'cfa'           : None,
        #    'bit_depth'     : 8,
        #}


        self.star_count = self.config.get('TEST_CAMERA', {}).get('ROTATING_STAR_COUNT', 30000)
        self.rotation_factor = self.config.get('TEST_CAMERA', {}).get('ROTATING_STAR_FACTOR', 1.0)

        self.stars_array = None

        self._stars_store_tmpl = 'test_rotating_stars_store_ccd{0:d}.npy'
        self._stars_store_p = None


    def disconnectServer(self, *args, **kwargs):
        import numpy

        if not isinstance(self._stars_store_p, type(None)):
            logger.info('Storing stars test data')
            with io.open(str(self._stars_store_p), 'w+b') as f_numpy:
                numpy.save(f_numpy, self.stars_array.astype(numpy.float16))  # reduce precision to reduce space

        super(IndiClientTestCameraRotatingStars, self).disconnectServer(*args, **kwargs)


    def updateImage(self, binning):
        import numpy
        import cv2


        if isinstance(self.stars_array, type(None)):
            # try to load data
            self._stars_store_p = self.varlib_folder_p.joinpath(self._stars_store_tmpl.format(self.camera_id))


            try:
                logger.info('Loading stored stars data')
                with io.open(str(self._stars_store_p), 'r+b') as f_numpy:
                    self.stars_array = numpy.load(f_numpy).astype(numpy.float32)

                if self.stars_array.shape[1] != self.star_count:
                    # if star count changes, create new array
                    self._stars_store_p.unlink()
                    self.stars_array = None
            except ValueError:
                logger.error('Invalid numpy data for stars')
                self._stars_store_p.unlink()
                self.stars_array = None
            except EOFError:
                logger.error('Invalid numpy data for stars')
                self._stars_store_p.unlink()
                self.stars_array = None
            except FileNotFoundError:
                pass


        if isinstance(self.stars_array, type(None)):
            # create new set of random stars
            self.stars_array = numpy.zeros([6, self.star_count], dtype=numpy.float32)  # x, y, radius, r, g, b

            max_value = (2 ** self.image_bit_depth) - 1  # 16-bit RGB

            for i in range(self.stars_array.shape[1]):
                r = random.randrange(max_value)
                g = random.randrange(max_value)
                b = random.randrange(max_value)

                radius = random.choice(self.star_sizes)


                # stars will be drawn out of bounds in a higher binning mode
                x = random.randrange(self.camera_info['width'] * 3)
                y = random.randrange(self.camera_info['height'] * 3)


                self.stars_array[0][i] = x
                self.stars_array[1][i] = y
                self.stars_array[2][i] = radius
                self.stars_array[3][i] = r
                self.stars_array[4][i] = g
                self.stars_array[5][i] = b

                #logger.info('XY: %d x %d', x, y)


        base_image_width = int(self.camera_info['width'] / binning) * 3
        base_image_height = int(self.camera_info['height'] / binning) * 3


        # create blank image
        base_image = numpy.full(
            [
                base_image_height,
                base_image_width,
                3
            ],
            self.background_color,
            dtype=numpy.uint16,
        )


        center_x = int(base_image_width / 2)
        center_y = int(base_image_height / 2)


        #rot_start = time.time()


        # calculate new coordinates based on rotation (vectorized)
        Ax = self.stars_array[0] - center_x
        Ay = self.stars_array[1] - center_y

        rotation_degrees = (360.0 / 86400) * (time.time() - self._last_exposure_time)  # sidereal day
        #logger.info('Rotation: %0.3f - Factor: %0.1f', rotation_degrees, self.rotation_factor)

        rot_radians = math.radians(rotation_degrees * self.rotation_factor)


        self.stars_array[0] = (center_x + (math.cos(rot_radians) * Ax + math.sin(rot_radians) * Ay)).astype(numpy.float32)
        self.stars_array[1] = (center_y + ((math.sin(rot_radians) * -1) * Ax + math.cos(rot_radians) * Ay)).astype(numpy.float32)


        #rot_elapsed_s = time.time() - rot_start
        #logger.info('Star rotation in %0.4f s', rot_elapsed_s)


        # redraw the stars
        for i in range(self.stars_array.shape[1]):
            center = (round(self.stars_array[0][i]), round(self.stars_array[1][i]))
            radius = int(self.stars_array[2][i])
            color = (int(self.stars_array[3][i]), int(self.stars_array[4][i]), int(self.stars_array[5][i]))
            #logger.info('Center: %s', center)

            cv2.circle(
                base_image,
                center=center,
                radius=radius,
                color=color,
                thickness=cv2.FILLED,
                lineType=cv2.LINE_AA,
            )


        # slice the image
        start_width = int(center_x - (self.camera_info['width'] / 2))  # center width
        start_height = int(self.camera_info['height'] * .7)  # offset height

        #logger.info('Center: %d x %d - Start: %d x %d', center_x, center_y, start_width, start_height)

        self._image = base_image[
            start_height:start_height + int(self.camera_info['height'] / binning),
            start_width:start_width + int(self.camera_info['width'] / binning),
        ]


        if self.image_circle_diameter:
            if isinstance(self._image_circle_alpha_mask_dict.get(binning), type(None)):
                self._image_circle_alpha_mask_dict[binning] = self._generate_image_circle_mask(self._image, binning)


            # simulate an image circle
            self._image = (self._image * self._image_circle_alpha_mask_dict[binning]).astype(numpy.uint16)


