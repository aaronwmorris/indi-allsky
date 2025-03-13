import io
import re
from pathlib import Path
from datetime import datetime
#from datetime import timedelta
from datetime import timezone
import math
import time
import signal
import numpy
import cv2
import PIL
from PIL import Image
from PIL import ImageFont
from PIL import ImageDraw
from fractions import Fraction
from pprint import pformat  # noqa: F401
import logging

import ephem

from . import constants

from . import stretch
from .orb import IndiAllskyOrbGenerator
from .sqm import IndiAllskySqm
from .stars import IndiAllSkyStars
from .detectLines import IndiAllskyDetectLines
from .keogram import KeogramGenerator
from .draw import IndiAllSkyDraw
from .scnr import IndiAllskyScnr
from .stack import IndiAllskyStacker
from .cardinalDirsLabel import IndiAllskyCardinalDirsLabel
from .utils import IndiAllSkyDateCalcs
from .moonOverlay import IndiAllSkyMoonOverlay
from .lightgraphOverlay import IndiAllSkyLightgraphOverlay

from .flask.models import IndiAllSkyDbBadPixelMapTable
from .flask.models import IndiAllSkyDbDarkFrameTable
from .flask.models import IndiAllSkyDbTleDataTable

from sqlalchemy.sql.expression import true as sa_true

from .exceptions import TimeOutException
from .exceptions import CalibrationNotFound
from .exceptions import BadImage
from .exceptions import KeogramMismatchException


try:
    import rawpy  # not available in all cases
except ImportError:
    rawpy = None


logger = logging.getLogger('indi_allsky')


class ImageProcessor(object):

    dark_temperature_range = 5.0  # dark must be within this range

    registration_exposure_thresh = 5.0

    __cfa_bgr_map = {
        'RGGB' : cv2.COLOR_BAYER_BG2BGR,
        'GRBG' : cv2.COLOR_BAYER_GB2BGR,
        'BGGR' : cv2.COLOR_BAYER_RG2BGR,
        'GBRG' : cv2.COLOR_BAYER_GR2BGR,  # untested
    }

    __cfa_gray_map = {
        'RGGB' : cv2.COLOR_BAYER_BG2GRAY,
        'GRBG' : cv2.COLOR_BAYER_GB2GRAY,
        'BGGR' : cv2.COLOR_BAYER_RG2GRAY,
        'GBRG' : cv2.COLOR_BAYER_GR2GRAY,
    }


    satellite_dict = {
        'iss' : {
            'title' : 'ISS (ZARYA)',
            'group' : constants.SATELLITE_VISUAL,
        },
        'hst' : {
            'title' : 'HST',
            'group' : constants.SATELLITE_VISUAL,
        },
        'tiangong' : {
            'title' : 'CSS (TIANHE)',
            'group' : constants.SATELLITE_VISUAL,
        },
    }


    cardinal_directions = ('N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW', 'N')


    def __init__(
        self,
        config,
        position_av,
        gain_v,
        bin_v,
        sensors_temp_av,
        sensors_user_av,
        night_v,
        moonmode_v,
        astrometric_data,
    ):
        self.config = config

        self.position_av = position_av  # lat, long, elev, ra, dec

        self.gain_v = gain_v
        self.bin_v = bin_v
        self.sensors_temp_av = sensors_temp_av  # 0 ccd_temp
        self.sensors_user_av = sensors_user_av  # 0 ccd_temp
        self.night_v = night_v
        self.moonmode_v = moonmode_v

        self.astrometric_data = astrometric_data

        self._max_bit_depth = 8  # this will be scaled up (never down) as detected

        self._detection_mask = self._load_detection_mask()
        self._adu_mask = self._detection_mask  # reuse detection mask for ADU mask (if defined)

        self._image_circle_alpha_mask = None

        self._overlay = None
        self._alpha_mask = None

        self._gamma_lut = None

        self.focus_mode = self.config.get('FOCUS_MODE', False)

        self.stack_method = self.config.get('IMAGE_STACK_METHOD', 'average')
        self.stack_count = self.config.get('IMAGE_STACK_COUNT', 1)

        self._text_color_rgb = [0, 0, 0]
        self._text_xy = [0, 0]
        self._text_anchor_pillow = 'la'
        self._text_size_pillow = 0
        self._text_font_height = 0

        self._libcamera_raw = False

        # contains the current stacked image
        self._image = None

        # contains the raw image data, data will be newest to oldest
        self.image_list = [None]  # element will be removed on first image

        self._dateCalcs = IndiAllSkyDateCalcs(self.config, self.position_av)


        if self.config['IMAGE_STRETCH'].get('CLASSNAME'):
            stretch_class = getattr(stretch, self.config['IMAGE_STRETCH']['CLASSNAME'])
            self._stretch = stretch_class(self.config, self.bin_v, mask=self._detection_mask)
        else:
            self._stretch = None


        self._sqm = IndiAllskySqm(self.config, self.bin_v, mask=None)
        self._stars_detect = IndiAllSkyStars(self.config, self.bin_v, mask=self._detection_mask)
        self._lineDetect = IndiAllskyDetectLines(self.config, self.bin_v, mask=self._detection_mask)
        self._draw = IndiAllSkyDraw(self.config, self.bin_v, mask=self._detection_mask)
        self._ia_scnr = IndiAllskyScnr(self.config)
        self._cardinal_dirs_label = IndiAllskyCardinalDirsLabel(self.config)
        self._moon_overlay = IndiAllSkyMoonOverlay(self.config)
        self._lightgraph_overlay = IndiAllSkyLightgraphOverlay(self.config, self.position_av)

        self._orb = IndiAllskyOrbGenerator(self.config)
        self._orb.sun_alt_deg = self.config['NIGHT_SUN_ALT_DEG']
        self._orb.azimuth_offset = self.config['ORB_PROPERTIES'].get('AZ_OFFSET', 0.0)
        self._orb.retrograde = self.config['ORB_PROPERTIES'].get('RETROGRADE', False)
        self._orb.sun_color_rgb = self.config['ORB_PROPERTIES']['SUN_COLOR']
        self._orb.moon_color_rgb = self.config['ORB_PROPERTIES']['MOON_COLOR']

        self._stacker = IndiAllskyStacker(self.config, self.bin_v, mask=self._detection_mask)
        self._stacker.detection_sigma = self.config.get('IMAGE_ALIGN_DETECTSIGMA', 5)
        self._stacker.max_control_points = self.config.get('IMAGE_ALIGN_POINTS', 50)
        self._stacker.min_area = self.config.get('IMAGE_ALIGN_SOURCEMINAREA', 10)


        self._keogram_gen = KeogramGenerator(
            self.config,
        )
        self._keogram_gen.angle = self.config.get('KEOGRAM_ANGLE', 0)
        self._keogram_gen.h_scale_factor = self.config.get('KEOGRAM_H_SCALE', 100)
        self._keogram_gen.v_scale_factor = self.config.get('KEOGRAM_V_SCALE', 33)
        self._keogram_gen.crop_top = self.config.get('KEOGRAM_CROP_TOP', 0)
        self._keogram_gen.crop_bottom = self.config.get('KEOGRAM_CROP_BOTTOM', 0)
        self._keogram_gen.x_offset = 0  # reset
        self._keogram_gen.y_offset = 0  # reset


        base_path  = Path(__file__).parent
        self.font_path  = base_path.joinpath('fonts')

        self._keogram_store_p = Path('/var/lib/indi-allsky/realtime_keogram_store.npy')


    @property
    def image(self):
        return self._image

    @image.setter
    def image(self, new_image):
        self._image = new_image


    @property
    def shape(self):
        return self.image.shape

    @shape.setter
    def shape(self, *args):
        pass  # read only


    @property
    def max_bit_depth(self):
        return self._max_bit_depth

    @max_bit_depth.setter
    def max_bit_depth(self, new_max_bit_depth):
        self._max_bit_depth = int(new_max_bit_depth)


    @property
    def libcamera_raw(self):
        return self._libcamera_raw

    @libcamera_raw.setter
    def libcamera_raw(self, new_libcamera_raw):
        self._libcamera_raw = bool(new_libcamera_raw)


    @property
    def text_color_rgb(self):
        return self._text_color_rgb

    @text_color_rgb.setter
    def text_color_rgb(self, x):
        if len(x) != 3:
            logger.error('Color format error')
            return

        self._text_color_rgb = [int(x[0]), int(x[1]), int(x[2])]


    @property
    def text_color_bgr(self):
        return [self._text_color_rgb[2], self._text_color_rgb[1], self._text_color_rgb[0]]  # reversed

    @text_color_bgr.setter
    def text_color_bgr(self, x):
        if len(x) != 3:
            logger.error('Color format error')
            return

        self._text_color_rgb = [int(x[2]), int(x[1]), int(x[0])]  # reversed


    @property
    def text_xy(self):
        return self._text_xy

    @text_xy.setter
    def text_xy(self, xy):
        if len(xy) != 2:
            logger.error('Text coordinate error')
            return


        x = int(xy[0])
        y = int(xy[1])


        height, width = self.image.shape[:2]

        if x < 0:
            # negative X values would start from the right side
            x = width + x  # x is negative

        if y < 0:
            # negative Y values would start from the bottom
            y = height + y  # y is negative


        #logger.info('New XY: %d, %d', x, y)
        self._text_xy = [x, y]


    @property
    def text_anchor_pillow(self):
        return self._text_anchor_pillow

    @text_anchor_pillow.setter
    def text_anchor_pillow(self, new_anchor):
        self._text_anchor_pillow = str(new_anchor)


    @property
    def text_size_pillow(self):
        return self._text_size_pillow

    @text_size_pillow.setter
    def text_size_pillow(self, new_size):
        self._text_size_pillow = int(new_size)


    @property
    def text_font_height(self):
        return self._text_font_height

    @text_font_height.setter
    def text_font_height(self, new_height):
        self._text_font_height = int(new_height)


    @property
    def realtime_keogram_data(self):
        return self._keogram_gen.keogram_data

    @realtime_keogram_data.setter
    def realtime_keogram_data(self, new_data):
        self._keogram_gen.keogram_data = new_data


    @property
    def realtime_keogram_trimmed(self):
        return self._keogram_gen.trimEdges(self.realtime_keogram_data)


    def add(self, filename, exposure, exp_date, exp_elapsed, camera):
        from astropy.io import fits

        filename_p = Path(filename)


        # clear old data as soon as possible
        self.image = None


        if self.night_v.value and not self.moonmode_v.value:
            # just in case the array grows beyond the desired size
            while len(self.image_list) >= self.stack_count:
                self.image_list.pop()
        else:
            # disable stacking during daytime and moonmode
            self.image_list.clear()


        ### Open file
        if filename_p.suffix in ['.fit', '.fits']:
            try:
                hdulist = fits.open(filename_p)
            except OSError as e:
                raise BadImage(str(e)) from e

            #logger.info('Initial HDU Header = %s', pformat(hdulist[0].header))
            image_bitpix = hdulist[0].header['BITPIX']
            image_bayerpat = hdulist[0].header.get('BAYERPAT')

            # older versions of indi (<= 2.0.6) do not allow focal lengths lower than 10mm
            # so we are just going to set this manually
            aperture = camera.lensFocalLength / camera.lensFocalRatio
            hdulist[0].header['FOCALLEN'] = round(camera.lensFocalLength, 2)
            hdulist[0].header['APTDIA'] = round(aperture, 2)


            if isinstance(hdulist[0].header.get('EXPTIME'), type(None)):
                logger.warning('FITS exposure is not populated')
                hdulist[0].header['EXPTIME'] = float(exposure)

            # in case a driver does not populate this info (libcamera)
            if isinstance(hdulist[0].header.get('GAIN'), type(None)):
                logger.warning('FITS gain is not populated')
                hdulist[0].header['GAIN'] = float(self.gain_v.value)
        elif filename_p.suffix in ['.jpg', '.jpeg']:
            try:
                with Image.open(str(filename_p)) as img:
                    data = numpy.array(img)  # pillow returns RGB
            except PIL.UnidentifiedImageError:
                raise BadImage('Bad jpeg image')


            # swap axes for FITS
            data = numpy.swapaxes(data, 1, 0)
            data = numpy.swapaxes(data, 2, 0)


            image_bitpix = 8
            image_bayerpat = None

            # create a new fits container
            hdu = fits.PrimaryHDU(data)
            hdulist = fits.HDUList([hdu])

            hdu.update_header()  # populates BITPIX, NAXIS, etc

            hdulist[0].header['IMAGETYP'] = 'Light Frame'
            hdulist[0].header['INSTRUME'] = 'jpg'
            hdulist[0].header['EXPTIME'] = float(exposure)
            hdulist[0].header['XBINNING'] = 1
            hdulist[0].header['YBINNING'] = 1
            hdulist[0].header['GAIN'] = float(self.gain_v.value)
            hdulist[0].header['CCD-TEMP'] = self.sensors_temp_av[0]
            hdulist[0].header['SITELAT'] = self.position_av[0]
            hdulist[0].header['SITELONG'] = self.position_av[1]
            hdulist[0].header['RA'] = self.position_av[3]
            hdulist[0].header['DEC'] = self.position_av[4]
            hdulist[0].header['DATE-OBS'] = exp_date.isoformat()
            #hdulist[0].header['BITPIX'] = 8


            aperture = camera.lensFocalLength / camera.lensFocalRatio
            hdulist[0].header['FOCALLEN'] = round(camera.lensFocalLength, 2)
            hdulist[0].header['APTDIA'] = round(aperture, 2)


            if camera.owner:
                hdulist[0].header['ORIGIN'] = camera.owner

        elif filename_p.suffix in ['.png']:
            # PNGs may be 16-bit, use OpenCV
            data = cv2.imread(str(filename_p), cv2.IMREAD_UNCHANGED)  # opencv returns BGR

            if isinstance(data, type(None)):
                raise BadImage('Bad png image')


            if len(data.shape) == 3:
                if data.shape[2] == 4:
                    # remove alpha channel
                    data = data[:, :, :3]

                # swap axes for FITS
                data = cv2.cvtColor(data, cv2.COLOR_BGR2RGB)  # opencv returns BGR
                data = numpy.swapaxes(data, 1, 0)
                data = numpy.swapaxes(data, 2, 0)


            image_bitpix = 8
            image_bayerpat = None

            # create a new fits container
            hdu = fits.PrimaryHDU(data)
            hdulist = fits.HDUList([hdu])

            hdu.update_header()  # populates BITPIX, NAXIS, etc

            hdulist[0].header['IMAGETYP'] = 'Light Frame'
            hdulist[0].header['INSTRUME'] = 'png'
            hdulist[0].header['EXPTIME'] = float(exposure)
            hdulist[0].header['XBINNING'] = 1
            hdulist[0].header['YBINNING'] = 1
            hdulist[0].header['GAIN'] = float(self.gain_v.value)
            hdulist[0].header['CCD-TEMP'] = self.sensors_temp_av[0]
            hdulist[0].header['SITELAT'] = self.position_av[0]
            hdulist[0].header['SITELONG'] = self.position_av[1]
            hdulist[0].header['RA'] = self.position_av[3]
            hdulist[0].header['DEC'] = self.position_av[4]
            hdulist[0].header['DATE-OBS'] = exp_date.isoformat()
            #hdulist[0].header['BITPIX'] = 8


            aperture = camera.lensFocalLength / camera.lensFocalRatio
            hdulist[0].header['FOCALLEN'] = round(camera.lensFocalLength, 2)
            hdulist[0].header['APTDIA'] = round(aperture, 2)


            if camera.owner:
                hdulist[0].header['ORIGIN'] = camera.owner

        elif filename_p.suffix in ['.dng']:
            if not rawpy:
                raise Exception('*** rawpy module not available ***')

            # DNG raw
            try:
                raw = rawpy.imread(str(filename_p))
            except rawpy._rawpy.LibRawIOError as e:
                raise BadImage(str(e)) from e

            data = raw.raw_image

            ### testing
            #data = numpy.left_shift(data, 4)  # upscale to full 16-bits
            #data = data + 15  # increase max value

            # create a new fits container
            hdu = fits.PrimaryHDU(data)
            hdulist = fits.HDUList([hdu])

            hdu.update_header()  # populates BITPIX, NAXIS, etc

            hdulist[0].header['IMAGETYP'] = 'Light Frame'
            hdulist[0].header['INSTRUME'] = 'libcamera'
            hdulist[0].header['EXPTIME'] = float(exposure)
            hdulist[0].header['XBINNING'] = 1
            hdulist[0].header['YBINNING'] = 1
            hdulist[0].header['GAIN'] = float(self.gain_v.value)
            hdulist[0].header['CCD-TEMP'] = self.sensors_temp_av[0]
            hdulist[0].header['SITELAT'] = self.position_av[0]
            hdulist[0].header['SITELONG'] = self.position_av[1]
            hdulist[0].header['RA'] = self.position_av[3]
            hdulist[0].header['DEC'] = self.position_av[4]
            hdulist[0].header['DATE-OBS'] = exp_date.isoformat()
            #hdulist[0].header['BITPIX'] = 16


            aperture = camera.lensFocalLength / camera.lensFocalRatio
            hdulist[0].header['FOCALLEN'] = round(camera.lensFocalLength, 2)
            hdulist[0].header['APTDIA'] = round(aperture, 2)


            if camera.owner:
                hdulist[0].header['ORIGIN'] = camera.owner

            if self.config.get('CFA_PATTERN'):
                hdulist[0].header['BAYERPAT'] = self.config['CFA_PATTERN']
                hdulist[0].header['XBAYROFF'] = 0
                hdulist[0].header['YBAYROFF'] = 0
            elif camera.cfa:
                hdulist[0].header['BAYERPAT'] = constants.CFA_MAP_STR[camera.cfa]
                hdulist[0].header['XBAYROFF'] = 0
                hdulist[0].header['YBAYROFF'] = 0

            image_bitpix = hdulist[0].header['BITPIX']
            image_bayerpat = hdulist[0].header.get('BAYERPAT')


        # Override these
        hdulist[0].header['OBJECT'] = 'AllSky'
        hdulist[0].header['TELESCOP'] = 'indi-allsky'


        # Add headers from config
        fitsheaders = self.config.get('FITSHEADERS', [])
        for header in fitsheaders:
            try:
                k = str(header[0]).upper()
                v = str(header[1])
            except IndexError:
                logger.error('Invalid header information')
                continue

            if not k:
                # skipping empty values
                continue

            if not v:
                # skipping empty values
                continue

            hdulist[0].header[k] = v


        #logger.info('Final HDU Header = %s', pformat(hdulist[0].header))


        logger.info('Image bits: %d, cfa: %s', image_bitpix, str(image_bayerpat))


        dayDate = self._dateCalcs.calcDayDate(exp_date)


        if self.night_v.value:
            target_adu = self.config['TARGET_ADU']
        else:
            target_adu = self.config['TARGET_ADU_DAY']


        image_data = ImageData(
            self.config,
            hdulist,
            exposure,
            exp_date,
            exp_elapsed,
            dayDate,
            camera.id,
            camera.name,
            camera.uuid,
            str(camera.owner),
            str(camera.location),
            image_bitpix,
            image_bayerpat,
            target_adu,
        )


        detected_bit_depth = image_data.detected_bit_depth

        config_ccd_bit_depth = self.config.get('CCD_BIT_DEPTH', 0)
        if config_ccd_bit_depth:
            if detected_bit_depth != config_ccd_bit_depth:
                logger.warning('*** DETECTED BIT DEPTH (%d) IS DIFFERENT FROM CONFIGURED BIT DEPTH (%d) ***', detected_bit_depth, config_ccd_bit_depth)

            logger.info('Overriding bit depth to %d bits', config_ccd_bit_depth)
            self.max_bit_depth = config_ccd_bit_depth

        else:
            if detected_bit_depth > self.max_bit_depth:
                logger.warning('Updated default bit depth: %d', detected_bit_depth)
                self.max_bit_depth = detected_bit_depth


        # indi_pylibcamera specific stuff
        # read this before it is overriden with the customer FITSHEADERS below
        instrume_header = hdulist[0].header.get('INSTRUME', '')
        if instrume_header == 'indi_pylibcamera':
            # OFFSET_0, _1, _2, _3 are the SensorBlackLevels metadata from libcamera
            image_data.libcamera_black_level = int(hdulist[0].header.get('OFFSET_0', 0))


        # aurora and smoke data
        camera_data = camera.data
        if camera_data:
            image_data.kpindex = float(camera_data.get('KPINDEX_CURRENT', 0.0))
            image_data.ovation_max = int(camera_data.get('OVATION_MAX', 0))
            image_data.aurora_mag_bt = float(camera_data.get('AURORA_MAG_BT', 0.0))
            image_data.aurora_mag_gsm_bz = float(camera_data.get('AURORA_MAG_GSM_BZ', 0.0))
            image_data.aurora_plasma_density = float(camera_data.get('AURORA_PLASMA_DENSITY', 0.0))
            image_data.aurora_plasma_speed = float(camera_data.get('AURORA_PLASMA_SPEED', 0.0))
            image_data.aurora_plasma_temp = int(camera_data.get('AURORA_PLASMA_TEMP', 0))
            image_data.aurora_n_hemi_gw = int(camera_data.get('AURORA_N_HEMI_GW', 0))
            image_data.aurora_s_hemi_gw = int(camera_data.get('AURORA_S_HEMI_GW', 0))

            try:
                image_data.smoke_rating = int(camera_data.get('SMOKE_RATING', constants.SMOKE_RATING_NODATA))
            except ValueError:
                # fix legacy values (str) until updated
                pass
            except TypeError:
                # fix legacy values (str) until updated
                pass


        self.image_list.insert(0, image_data)  # new image is first in list

        return image_data


    def debayer(self):
        i_ref = self.getLatestImage()

        self._debayer(i_ref)


    def _debayer(self, i_ref):
        data = i_ref.hdulist[0].data

        if i_ref.image_bitpix in (8, 16):
            pass
        elif i_ref.image_bitpix == -32:  # float32
            logger.info('Scaling float32 data to uint16')

            ### cutoff lower range
            data[data < 0] = 0.0

            ### cutoff upper range
            data[data > 65535] = 65535.0

            ### cast to uint16 for pretty pictures
            data = data.astype(numpy.uint16)
            i_ref.hdulist[0].data = data

            i_ref.image_bitpix = 16
        elif i_ref.image_bitpix == 32:  # uint32
            logger.info('Scaling uint32 data to uint16')

            ### cutoff upper range
            data[data > 65535] = 65535

            ### cast to uint16 for pretty pictures
            data = data.astype(numpy.uint16)
            i_ref.hdulist[0].data = data

            i_ref.image_bitpix = 16
        else:
            raise Exception('Unsupported bit format: {0:d}'.format(i_ref.image_bitpix))


        if not len(data.shape) == 2:
            # data is already RGB(fits)
            data = numpy.swapaxes(data, 0, 2)
            data = numpy.swapaxes(data, 0, 1)

            i_ref.opencv_data = cv2.cvtColor(data, cv2.COLOR_RGB2BGR)
            return


        ### now we reach the debayer stage
        if self.config.get('CFA_PATTERN'):
            # override detected bayer pattern
            logger.warning('Overriding CFA pattern: %s', self.config['CFA_PATTERN'])
            image_bayerpat = self.config['CFA_PATTERN']
        else:
            image_bayerpat = i_ref.image_bayerpat


        if not image_bayerpat:
            # assume mono data
            logger.error('No bayer pattern detected')
            i_ref.opencv_data = data
            return


        if self.config.get('NIGHT_GRAYSCALE') and self.night_v.value:
            debayer_algorithm = self.__cfa_gray_map[image_bayerpat]
        elif self.config.get('DAYTIME_GRAYSCALE') and not self.night_v.value:
            debayer_algorithm = self.__cfa_gray_map[image_bayerpat]
        else:
            debayer_algorithm = self.__cfa_bgr_map[image_bayerpat]


        i_ref.opencv_data = cv2.cvtColor(data, debayer_algorithm)


    def getLatestImage(self):
        return self.image_list[0]


    def calibrate(self, libcamera_black_level=None):
        i_ref = self.getLatestImage()
        self._calibrate(i_ref, libcamera_black_level=libcamera_black_level)


    def _calibrate(self, i_ref, libcamera_black_level=None):
        # need this to be able to apply calibration frames to images other than the latest

        if not self.config.get('IMAGE_CALIBRATE_DARK', True):
            logger.warning('Dark frame calibration disabled')
            return


        if i_ref.calibrated:
            # already calibrated
            return


        try:
            calibrated_data = self._apply_calibration(i_ref.hdulist[0].data, i_ref.exposure, i_ref.camera_id, i_ref.image_bitpix)
            i_ref.hdulist[0].data = calibrated_data

            i_ref.calibrated = True
        except CalibrationNotFound:
            # only subtract dark level if dark frame is not found

            if self.libcamera_raw:
                if libcamera_black_level:
                    logger.info('Black level: %d', int(libcamera_black_level))
                    black_level_scaled = int(libcamera_black_level) >> (16 - self.max_bit_depth)

                    # use opencv to prevent underruns
                    i_ref.hdulist[0].data = cv2.subtract(i_ref.hdulist[0].data, black_level_scaled)

                    i_ref.calibrated = True


    def _apply_calibration(self, data, exposure, camera_id, image_bitpix):
        from astropy.io import fits

        if self.config.get('IMAGE_CALIBRATE_BPM'):
            # pick a bad pixel map that is closest to the exposure and temperature
            logger.info('Searching for bad pixel map: gain %d, exposure >= %0.1f, temp >= %0.1fc', self.gain_v.value, exposure, self.sensors_temp_av[0])
            bpm_entry = IndiAllSkyDbBadPixelMapTable.query\
                .filter(IndiAllSkyDbBadPixelMapTable.camera_id == camera_id)\
                .filter(IndiAllSkyDbBadPixelMapTable.active == sa_true())\
                .filter(IndiAllSkyDbBadPixelMapTable.bitdepth == image_bitpix)\
                .filter(IndiAllSkyDbBadPixelMapTable.binmode == self.bin_v.value)\
                .filter(IndiAllSkyDbBadPixelMapTable.gain >= self.gain_v.value)\
                .filter(IndiAllSkyDbBadPixelMapTable.exposure >= exposure)\
                .filter(IndiAllSkyDbBadPixelMapTable.temp >= self.sensors_temp_av[0])\
                .filter(IndiAllSkyDbBadPixelMapTable.temp <= (self.sensors_temp_av[0] + self.dark_temperature_range))\
                .order_by(
                    IndiAllSkyDbBadPixelMapTable.gain.asc(),
                    IndiAllSkyDbBadPixelMapTable.exposure.asc(),
                    IndiAllSkyDbBadPixelMapTable.temp.asc(),
                    IndiAllSkyDbBadPixelMapTable.createDate.desc(),
                )\
                .first()

            if not bpm_entry:
                #logger.warning('Temperature matched bad pixel map not found: %0.2fc', self.sensors_temp_av[0])

                # pick a bad pixel map that matches the exposure at the hightest temperature found
                bpm_entry = IndiAllSkyDbBadPixelMapTable.query\
                    .filter(IndiAllSkyDbBadPixelMapTable.camera_id == camera_id)\
                    .filter(IndiAllSkyDbBadPixelMapTable.active == sa_true())\
                    .filter(IndiAllSkyDbBadPixelMapTable.bitdepth == image_bitpix)\
                    .filter(IndiAllSkyDbBadPixelMapTable.binmode == self.bin_v.value)\
                    .filter(IndiAllSkyDbBadPixelMapTable.gain >= self.gain_v.value)\
                    .filter(IndiAllSkyDbBadPixelMapTable.exposure >= exposure)\
                    .order_by(
                        IndiAllSkyDbBadPixelMapTable.gain.asc(),
                        IndiAllSkyDbBadPixelMapTable.exposure.asc(),
                        IndiAllSkyDbBadPixelMapTable.temp.desc(),
                        IndiAllSkyDbBadPixelMapTable.createDate.desc(),
                    )\
                    .first()


                if not bpm_entry:
                    logger.warning(
                        'Bad Pixel Map not found: ccd%d %dbit %0.7fs gain %d bin %d %0.2fc',
                        camera_id,
                        image_bitpix,
                        float(exposure),
                        self.gain_v.value,
                        self.bin_v.value,
                        self.sensors_temp_av[0],
                    )
        else:
            bpm_entry = None


        # pick a dark frame that is closest to the exposure and temperature
        logger.info('Searching for dark frame: gain %d, exposure >= %0.1f, temp >= %0.1fc', self.gain_v.value, exposure, self.sensors_temp_av[0])
        dark_frame_entry = IndiAllSkyDbDarkFrameTable.query\
            .filter(IndiAllSkyDbDarkFrameTable.camera_id == camera_id)\
            .filter(IndiAllSkyDbDarkFrameTable.active == sa_true())\
            .filter(IndiAllSkyDbDarkFrameTable.bitdepth == image_bitpix)\
            .filter(IndiAllSkyDbDarkFrameTable.binmode == self.bin_v.value)\
            .filter(IndiAllSkyDbDarkFrameTable.gain >= self.gain_v.value)\
            .filter(IndiAllSkyDbDarkFrameTable.exposure >= exposure)\
            .filter(IndiAllSkyDbDarkFrameTable.temp >= self.sensors_temp_av[0])\
            .filter(IndiAllSkyDbDarkFrameTable.temp <= (self.sensors_temp_av[0] + self.dark_temperature_range))\
            .order_by(
                IndiAllSkyDbDarkFrameTable.gain.asc(),
                IndiAllSkyDbDarkFrameTable.exposure.asc(),
                IndiAllSkyDbDarkFrameTable.temp.asc(),
                IndiAllSkyDbDarkFrameTable.createDate.desc(),
            )\
            .first()

        if not dark_frame_entry:
            #logger.warning('Temperature matched dark not found: %0.2fc', self.sensors_temp_av[0])

            # pick a dark frame that matches the exposure at the hightest temperature found
            dark_frame_entry = IndiAllSkyDbDarkFrameTable.query\
                .filter(IndiAllSkyDbDarkFrameTable.camera_id == camera_id)\
                .filter(IndiAllSkyDbDarkFrameTable.active == sa_true())\
                .filter(IndiAllSkyDbDarkFrameTable.bitdepth == image_bitpix)\
                .filter(IndiAllSkyDbDarkFrameTable.binmode == self.bin_v.value)\
                .filter(IndiAllSkyDbDarkFrameTable.gain >= self.gain_v.value)\
                .filter(IndiAllSkyDbDarkFrameTable.exposure >= exposure)\
                .order_by(
                    IndiAllSkyDbDarkFrameTable.gain.asc(),
                    IndiAllSkyDbDarkFrameTable.exposure.asc(),
                    IndiAllSkyDbDarkFrameTable.temp.desc(),
                    IndiAllSkyDbDarkFrameTable.createDate.desc(),
                )\
                .first()


            if not dark_frame_entry:
                logger.warning(
                    'Dark not found: ccd%d %dbit %0.7fs gain %d bin %d %0.2fc',
                    camera_id,
                    image_bitpix,
                    float(exposure),
                    self.gain_v.value,
                    self.bin_v.value,
                    self.sensors_temp_av[0],
                )

                raise CalibrationNotFound('Dark not found')


        if bpm_entry:
            p_bpm = Path(bpm_entry.getFilesystemPath())
            if p_bpm.exists():
                logger.info('Matched bad pixel map: %s', p_bpm)
                with fits.open(p_bpm) as bpm_f:
                    bpm = bpm_f[0].data
            else:
                logger.error('Bad Pixel Map missing: %s', bpm_entry.filename)
                bpm = None
        else:
            bpm = None


        p_dark_frame = Path(dark_frame_entry.getFilesystemPath())
        if not p_dark_frame.exists():
            logger.error('Dark file missing: %s', dark_frame_entry.filename)
            raise CalibrationNotFound('Dark file missing: {0:s}'.format(dark_frame_entry.filename))


        logger.info('Matched dark: %s', p_dark_frame)

        with fits.open(p_dark_frame) as dark_f:
            dark = dark_f[0].data


        if not isinstance(bpm, type(None)):
            # merge bad pixel map and dark
            master_dark = numpy.maximum(bpm, dark)
        else:
            master_dark = dark


        if master_dark.shape != data.shape:
            image_height, image_width = data.shape[:2]  # there might be a 3rd dimension for RGB data
            dark_height, dark_width = master_dark.shape[:2]
            logger.error('Dark frame calibration dimensions mismatch - %dx%d vs %dx%d', image_width, image_height, dark_width, dark_height)
            raise CalibrationNotFound('Dark frame calibration dimension mismatch')


        if data.dtype.type == numpy.float32:
            ### cv2 does not support float32
            data_calibrated = numpy.subtract(data, master_dark)

            # cutoff values less than 0
            data_calibrated[data_calibrated < 0] = 0
        elif data.dtype.type == numpy.uint32:
            ### cv2 does not support uint32
            # cast to float so we can deal with negative numbers
            data_calibrated = numpy.subtract(data.astype(numpy.float32), master_dark)

            # cutoff values less than 0
            data_calibrated[data_calibrated < 0] = 0

            data_calibrated = data_calibrated.astype(numpy.uint32)
        else:
            data_calibrated = cv2.subtract(data, master_dark)

        return data_calibrated


    def calculate_8bit_adu(self):
        i_ref = self.getLatestImage()

        return self._calculate_8bit_adu(i_ref)


    def _calculate_8bit_adu(self, i_ref):
        if isinstance(self._adu_mask, type(None)):
            # This only needs to be done once if a mask is not provided
            self._generateAduMask(self.image)


        mask_dimensions = self._adu_mask.shape[:2]
        image_dimensions = self.image.shape[:2]

        if mask_dimensions != image_dimensions:
            # This is a canary message.  The cv2.mean() call will fail below, as well as many other functions later.
            logger.error('Detection mask dimensions do not match image')


        if len(self.image.shape) == 2:
            # mono
            adu = cv2.mean(src=self.image, mask=self._adu_mask)[0]
        else:
            data_mono = cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY)
            adu = cv2.mean(src=data_mono, mask=self._adu_mask)[0]


        if i_ref.image_bitpix == 8:
            # nothing to scale
            adu_8 = int(adu)
        elif i_ref.image_bitpix == 16:
            shift_factor = self.max_bit_depth - 8
            adu_8 = int(adu) >> shift_factor
        else:
            raise Exception('Unsupported bit depth')


        logger.info('ADU average: %0.1f (%d)', adu, adu_8)


        return adu_8


    def calculateSqm(self):
        i_ref = self.getLatestImage()

        if self.focus_mode:
            # disable processing in focus mode
            i_ref.sqm_value = 0
            return

        i_ref.sqm_value = self._sqm.calculate(i_ref.opencv_data, i_ref.exposure, self.gain_v.value)


    def stack(self):
        # self.image is first populated by this method
        i_ref = self.getLatestImage()


        if self.focus_mode:
            # disable processing in focus mode
            self.image = i_ref.opencv_data
            return


        stack_i_ref_list = list()
        for i in self.image_list:
            if isinstance(i, type(None)):
                continue

            stack_i_ref_list.append(i)


        stack_list_len = len(stack_i_ref_list)
        assert stack_list_len > 0  # canary

        if stack_list_len == 1:
            # no reason to stack a single image
            self.image = i_ref.opencv_data
            return


        image_bitpix = i_ref.image_bitpix


        if image_bitpix == 16:
            numpy_type = numpy.uint16
        elif image_bitpix == 8:
            numpy_type = numpy.uint8
        else:
            raise Exception('Unknown bits per pixel')


        if self.config.get('IMAGE_STACK_ALIGN') and i_ref.exposure > self.registration_exposure_thresh:
            # only perform registration once the exposure exceeds 5 seconds

            stack_i_ref_list = list(filter(lambda x: x.exposure > self.registration_exposure_thresh, stack_i_ref_list))


            # if the registration takes longer than the exposure period, kill it
            # 3 seconds is the assumed time it normally takes to process an image
            signal.alarm(int(self.config['EXPOSURE_PERIOD'] - 3))

            try:
                stack_data_list = self._stacker.register(stack_i_ref_list)
            except TimeOutException:
                # stack unaligned images
                logger.error('Registration exceeded the exposure period, cancel alignment')
                stack_data_list = [x.opencv_data for x in stack_i_ref_list]

            signal.alarm(0)
        else:
            # stack unaligned images
            stack_data_list = [x.opencv_data for x in stack_i_ref_list]


        stack_start = time.time()


        try:
            stacker_method = getattr(self._stacker, self.stack_method)
            self.image = stacker_method(stack_data_list, numpy_type)
        except AttributeError:
            logger.error('Unknown stacking method: %s', self.stack_method)
            self.image = i_ref.opencv_data
            return


        if self.config.get('IMAGE_STACK_SPLIT'):
            self.image = self.splitscreen(i_ref.opencv_data, self.image)


        stack_elapsed_s = time.time() - stack_start
        logger.info('Stacked %d images (%s) in %0.4f s', len(stack_data_list), self.stack_method, stack_elapsed_s)


    #def subtract_black_level(self, libcamera_black_level):
    #    # not used
    #    i_ref = self.getLatestImage()

    #    if i_ref['calibrated']:
    #        # do not subtract black level if dark frame calibrated
    #        return

    #    # for some reason the black levels are in a 16bit space even though the cameras only return 12 bit data
    #    black_level_depth = int(libcamera_black_level) >> (16 - self.max_bit_depth)

    #    self.image -= (black_level_depth - 10)  # offset slightly


    #def apply_awb_gains(self, libcamera_awb_gains):
    #    # not used
    #    dtype = self.image.dtype

    #    self.image[:, :, 2] = self.image[:, :, 2].astype(numpy.float32) * float(libcamera_awb_gains[0])  # red
    #    self.image[:, :, 0] = self.image[:, :, 0].astype(numpy.float32) * float(libcamera_awb_gains[1])  # blue

    #    self.image = self.image.astype(dtype)


    def apply_color_correction_matrix(self, libcamera_ccm):
        ccm_start = time.time()

        # do not convert to uint16 yet
        ccm_image = numpy.matmul(self.image, numpy.array(libcamera_ccm).T)


        max_value = (2 ** self.max_bit_depth) - 1

        ccm_image[ccm_image > max_value] = max_value  # clip high end
        ccm_image[ccm_image < 0] = 0  # clip low end


        self.image = ccm_image.astype(self.image.dtype)

        #ccm_m = numpy.array(ccm)

        #reshaped_image = self.image.reshape((-1, 3))
        #ccm_image = numpy.matmul(reshaped_image, ccm_m.T)
        #ccm_image[ccm_image > max_value] = max_value  # clip high end
        #ccm_image[ccm_image < 0] = 0  # clip low end

        #self.image = ccm_image.reshape(self.image.shape).astype(self.image.dtype)

        ccm_elapsed_s = time.time() - ccm_start
        logger.info('CCM in %0.4f s', ccm_elapsed_s)


    def convert_16bit_to_8bit(self):
        i_ref = self.getLatestImage()

        self._convert_16bit_to_8bit(i_ref.image_bitpix)


    def _convert_16bit_to_8bit(self, image_bitpix):
        if image_bitpix == 8:
            return

        #logger.info('Resampling image from %d to 8 bits', image_bitpix)

        # shifting is 5x faster than division
        shift_factor = self.max_bit_depth - 8
        self.image = numpy.right_shift(self.image, shift_factor).astype(numpy.uint8)


    def rotate_90(self):
        if not self.config.get('IMAGE_ROTATE'):
            return


        try:
            rotate_enum = getattr(cv2, self.config['IMAGE_ROTATE'])
        except AttributeError:
            logger.error('Unknown rotation option: %s', self.config['IMAGE_ROTATE'])
            return


        self._rotate_90(rotate_enum)
        return True


    def _rotate_90(self, rotate_enum):
        self.image = cv2.rotate(self.image, rotate_enum)


    def rotate_angle(self):
        angle = self.config.get('IMAGE_ROTATE_ANGLE')
        keep_size = self.config.get('IMAGE_ROTATE_KEEP_SIZE')
        #use_offset = self.config.get('IMAGE_ROTATE_WITH_OFFSET')

        if not angle:
            return


        self._rotate_angle(angle, keep_size=keep_size, use_offset=False)
        return True


    def _rotate_angle(self, angle, keep_size=False, use_offset=False):
        #rotate_start = time.time()

        height, width = self.image.shape[:2]
        center_x = int(width / 2)
        center_y = int(height / 2)


        # not sure what to do here (or if its in the right place)
        if use_offset:
            #x_offset = self.config.get('LENS_OFFSET_X', 0)
            #y_offset = self.config.get('LENS_OFFSET_Y', 0)
            pass
        else:
            pass


        # consider rotating at center offset
        rot = cv2.getRotationMatrix2D((center_x, center_y), int(angle), 1.0)


        if keep_size:
            bound_w = width
            bound_h = height
        else:
            # rotating will change the size of the resulting image
            abs_cos = abs(rot[0, 0])
            abs_sin = abs(rot[0, 1])

            bound_w = int(height * abs_sin + width * abs_cos)
            bound_h = int(height * abs_cos + width * abs_sin)


        rot[0, 2] += (bound_w / 2) - center_x
        rot[1, 2] += (bound_h / 2) - center_y


        self.image = cv2.warpAffine(self.image, rot, (bound_w, bound_h))

        rot_height, rot_width = self.image.shape[:2]
        mod_height = rot_height % 2
        mod_width = rot_width % 2

        if mod_height or mod_width:
            # width and height needs to be divisible by 2 for timelapse
            crop_height = rot_height - mod_height
            crop_width = rot_width - mod_width

            self.image = self.image[
                0:crop_height,
                0:crop_width,
            ]


        #processing_elapsed_s = time.time() - rotate_start
        #logger.warning('Rotation in %0.4f s', processing_elapsed_s)


    def _flip(self, data, cv2_axis):
        return cv2.flip(data, cv2_axis)


    def flip_v(self):
        if not self.config.get('IMAGE_FLIP_V'):
            return

        self.image = self._flip(self.image, 0)
        return True


    def flip_h(self):
        if not self.config.get('IMAGE_FLIP_H'):
            return

        self.image = self._flip(self.image, 1)
        return True


    def detectLines(self):
        i_ref = self.getLatestImage()

        if self.focus_mode:
            # disable processing in focus mode
            return

        i_ref.lines = self._lineDetect.detectLines(self.image)


    def detectStars(self):
        i_ref = self.getLatestImage()

        if self.focus_mode:
            # disable processing in focus mode
            return

        i_ref.stars = self._stars_detect.detectObjects(self.image)


    def drawDetections(self):
        if self.focus_mode:
            # disable processing in focus mode
            return

        self.image = self._draw.main(self.image)


    def crop_image(self):
        # divide the coordinates by binning value
        x1 = int(self.config['IMAGE_CROP_ROI'][0] / self.bin_v.value)
        y1 = int(self.config['IMAGE_CROP_ROI'][1] / self.bin_v.value)
        x2 = int(self.config['IMAGE_CROP_ROI'][2] / self.bin_v.value)
        y2 = int(self.config['IMAGE_CROP_ROI'][3] / self.bin_v.value)


        self.image = self.image[
            y1:y2,
            x1:x2,
        ]

        new_height, new_width = self.image.shape[:2]
        logger.info('New cropped size: %d x %d', new_width, new_height)


    def scnr(self):
        if self.focus_mode:
            # disable processing in focus mode
            return


        if self.config.get('USE_NIGHT_COLOR', True):
            algo = self.config.get('SCNR_ALGORITHM')
        else:
            if self.night_v.value:
                # night
                algo = self.config.get('SCNR_ALGORITHM')
            else:
                # day
                algo = self.config.get('SCNR_ALGORITHM_DAY')


        if not algo:
            return


        self._scnr(algo)
        return True


    def _scnr(self, algo):

        try:
            scnr_function = getattr(self._ia_scnr, algo)
            self.image = scnr_function(self.image)
        except AttributeError:
            logger.error('Unknown SCNR algorithm: %s', algo)


    def white_balance_manual_bgr(self):
        if self.focus_mode:
            # disable processing in focus mode
            return


        if len(self.image.shape) == 2:
            # mono
            return


        if self.config.get('USE_NIGHT_COLOR', True):
            WBB_FACTOR = float(self.config.get('WBB_FACTOR', 1.0))
            WBG_FACTOR = float(self.config.get('WBG_FACTOR', 1.0))
            WBR_FACTOR = float(self.config.get('WBR_FACTOR', 1.0))
        else:
            if self.night_v.value:
                # night
                WBB_FACTOR = float(self.config.get('WBB_FACTOR', 1.0))
                WBG_FACTOR = float(self.config.get('WBG_FACTOR', 1.0))
                WBR_FACTOR = float(self.config.get('WBR_FACTOR', 1.0))
            else:
                # day
                WBB_FACTOR = float(self.config.get('WBB_FACTOR_DAY', 1.0))
                WBG_FACTOR = float(self.config.get('WBG_FACTOR_DAY', 1.0))
                WBR_FACTOR = float(self.config.get('WBR_FACTOR_DAY', 1.0))


        if WBB_FACTOR == 1.0 and WBG_FACTOR == 1.0 and WBR_FACTOR == 1.0:
            # no action
            return


        self._white_balance_manual_bgr(WBB_FACTOR, WBG_FACTOR, WBR_FACTOR)
        return True


    def _white_balance_manual_bgr(self, WBB_FACTOR, WBG_FACTOR, WBR_FACTOR):
        b, g, r = cv2.split(self.image)

        logger.info('Applying manual color balance settings')
        if WBB_FACTOR == 1.0:
            wbb = b
        else:
            wbb = cv2.multiply(b, WBB_FACTOR)

        if WBG_FACTOR == 1.0:
            wbg = g
        else:
            wbg = cv2.multiply(g, WBG_FACTOR)

        if WBR_FACTOR == 1.0:
            wbr = r
        else:
            wbr = cv2.multiply(r, WBR_FACTOR)


        self.image = cv2.merge([wbb, wbg, wbr])


    #def white_balance_bgr_2(self):
    #    if len(self.image.shape) == 2:
    #        # mono
    #        return

    #    lab = cv2.cvtColor(self.image, cv2.COLOR_BGR2LAB)
    #    avg_a = numpy.average(lab[:, :, 1])
    #    avg_b = numpy.average(lab[:, :, 2])
    #    lab[:, :, 1] = lab[:, :, 1] - ((avg_a - 128) * (lab[:, :, 0] / 255.0) * 1.1)
    #    lab[:, :, 2] = lab[:, :, 2] - ((avg_b - 128) * (lab[:, :, 0] / 255.0) * 1.1)
    #    self.image = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


    #def median_blur(self):
    #    if self.focus_mode:
    #        # disable processing in focus mode
    #        return

    #    data_blur = cv2.medianBlur(self.image, ksize=3)
    #    self.image = data_blur


    #def fastDenoise(self):
    #    if self.focus_mode:
    #        # disable processing in focus mode
    #        return

    #    data_denoise = cv2.fastNlMeansDenoisingColored(
    #        self.image,
    #        None,
    #        h=3,
    #        hColor=3,
    #        templateWindowSize=7,
    #        searchWindowSize=21,
    #    )

    #    self.image = data_denoise


    def white_balance_auto_bgr(self):
        if self.focus_mode:
            # disable processing in focus mode
            return

        if len(self.image.shape) == 2:
            # mono
            return


        if self.config.get('USE_NIGHT_COLOR', True):
            auto_wb = self.config.get('AUTO_WB')
        else:
            if self.night_v.value:
                # night
                auto_wb = self.config.get('AUTO_WB')
            else:
                # day
                auto_wb = self.config.get('AUTO_WB_DAY')


        if not auto_wb:
            return


        self._white_balance_auto_bgr()
        return True


    def _white_balance_auto_bgr(self):
        ### This seems to work
        b, g, r = cv2.split(self.image)
        b_avg = cv2.mean(b)[0]
        g_avg = cv2.mean(g)[0]
        r_avg = cv2.mean(r)[0]

        # Find the gain of each channel
        k = (b_avg + g_avg + r_avg) / 3

        try:
            kb = k / b_avg
        except ZeroDivisionError:
            kb = k / 0.1

        try:
            kg = k / g_avg
        except ZeroDivisionError:
            kg = k / 0.1

        try:
            kr = k / r_avg
        except ZeroDivisionError:
            kr = k / 0.1

        b = cv2.addWeighted(src1=b, alpha=kb, src2=0, beta=0, gamma=0)
        g = cv2.addWeighted(src1=g, alpha=kg, src2=0, beta=0, gamma=0)
        r = cv2.addWeighted(src1=r, alpha=kr, src2=0, beta=0, gamma=0)

        self.image = cv2.merge([b, g, r])


    def saturation_adjust(self):
        if self.focus_mode:
            # disable processing in focus mode
            return


        if len(self.image.shape) == 2:
            # mono
            return


        if self.config.get('USE_NIGHT_COLOR', True):
            SATURATION_FACTOR = float(self.config.get('SATURATION_FACTOR', 1.0))
        else:
            if self.night_v.value:
                # night
                SATURATION_FACTOR = float(self.config.get('SATURATION_FACTOR', 1.0))
            else:
                # day
                SATURATION_FACTOR = float(self.config.get('SATURATION_FACTOR_DAY', 1.0))


        if SATURATION_FACTOR == 1.0:
            # no action
            return


        self._saturation_adjust(SATURATION_FACTOR)
        return True


    def _saturation_adjust(self, SATURATION_FACTOR):
        image_hsv = cv2.cvtColor(self.image, cv2.COLOR_BGR2HSV)

        sat = image_hsv[:, :, 1]

        logger.info('Applying saturation settings')
        image_hsv[:, :, 1] = cv2.multiply(sat, SATURATION_FACTOR)

        self.image = cv2.cvtColor(image_hsv, cv2.COLOR_HSV2BGR)


    def contrast_clahe(self):
        if self.focus_mode:
            # disable processing in focus mode
            return

        logger.info('Performing CLAHE contrast enhance')

        clip_limit = self.config.get('CLAHE_CLIPLIMIT', 3.0)
        grid_size = self.config.get('CLAHE_GRIDSIZE', 8)

        ### ohhhh, contrasty
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(grid_size, grid_size))

        if len(self.image.shape) == 2:
            # mono
            self.image = clahe.apply(self.image)
            return

        # color, apply to luminance
        lab = cv2.cvtColor(self.image, cv2.COLOR_BGR2LAB)

        lum = lab[:, :, 0]

        lab[:, :, 0] = clahe.apply(lum)

        self.image = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


    def contrast_clahe_16bit(self):
        if self.focus_mode:
            # disable processing in focus mode
            return

        logger.info('Performing 16-bit CLAHE contrast enhance')

        clip_limit = self.config.get('CLAHE_CLIPLIMIT', 3.0)
        grid_size = self.config.get('CLAHE_GRIDSIZE', 8)


        ### ohhhh, contrasty
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(grid_size, grid_size))


        if len(self.image.shape) == 2:
            # mono
            self.image = clahe.apply(self.image)
            return


        if self.max_bit_depth == 8:
            numpy_dtype = numpy.uint8
        else:
            numpy_dtype = numpy.uint16


        max_value = (2 ** self.max_bit_depth) - 1

        # float32 normalized values
        norm_image = (self.image / max_value).astype(numpy.float32)


        # color, apply to luminance
        # cvtColor() only accepts uint8 and normalized float32
        lab = cv2.cvtColor(norm_image, cv2.COLOR_BGR2LAB)

        # clahe only accepts uint8 and uint16
        # luminance is a float between 0-100, which needs to be remapped to a 16bit int
        cl_u16 = clahe.apply((lab[:, :, 0] * 655).astype(numpy_dtype))  # a little less than 65535 / 100

        # map luminance back to 0-100
        lab[:, :, 0] = (cl_u16 / 656).astype(numpy.float32)  # a little more than 655.35

        #logger.info('L min: %0.4f', numpy.min(lab[:, :, 0]))
        #logger.info('L max: %0.4f', numpy.max(lab[:, :, 0]))

        # convert back to uint8 or uint16
        self.image = (cv2.cvtColor(lab, cv2.COLOR_LAB2BGR) * max_value).astype(numpy_dtype)


    def apply_gamma_correction(self):
        if self.focus_mode:
            # disable processing in focus mode
            return


        if self.config.get('USE_NIGHT_COLOR', True):
            GAMMA_CORRECTION = float(self.config.get('GAMMA_CORRECTION', 1.0))
        else:
            if self.night_v.value:
                # night
                GAMMA_CORRECTION = float(self.config.get('GAMMA_CORRECTION', 1.0))
            else:
                # day
                GAMMA_CORRECTION = float(self.config.get('GAMMA_CORRECTION_DAY', 1.0))


        if GAMMA_CORRECTION == 1.0:
            # no action
            return


        self._apply_gamma_correction(GAMMA_CORRECTION)
        return True


    def _apply_gamma_correction(self, gamma):
        if isinstance(self._gamma_lut, type(None)):
            range_array = numpy.arange(0, 256, dtype=numpy.float32)
            self._gamma_lut = (((range_array / 255) ** (1.0 / gamma)) * 255).astype(numpy.uint8)


        self.image = self._gamma_lut.take(self.image, mode='raise')


    def colorize(self):
        if len(self.image.shape) == 3:
            # already color
            return

        self.image = cv2.cvtColor(self.image, cv2.COLOR_GRAY2BGR)


    def apply_image_circle_mask(self):
        if not self.config.get('IMAGE_CIRCLE_MASK', {}).get('ENABLE'):
            return

        if isinstance(self._image_circle_alpha_mask, type(None)):
            self._image_circle_alpha_mask = self._generate_image_circle_mask(self.image)


        #alpha_start = time.time()

        self.image = (self.image * self._image_circle_alpha_mask).astype(numpy.uint8)


        if self.config.get('IMAGE_CIRCLE_MASK', {}).get('OUTLINE'):
            image_height, image_width = self.image.shape[:2]

            center_x = int(image_width / 2) + self.config.get('LENS_OFFSET_X', 0)
            center_y = int(image_height / 2) - self.config.get('LENS_OFFSET_Y', 0)  # minus
            radius = int(self.config['IMAGE_CIRCLE_MASK']['DIAMETER'] / 2)

            cv2.circle(
                img=self.image,
                center=(center_x, center_y),
                radius=radius,
                color=(64, 64, 64),
                thickness=3,
            )


        #alpha_elapsed_s = time.time() - alpha_start
        #logger.info('Image circle mask in %0.4f s', alpha_elapsed_s)


    def apply_logo_overlay(self):
        logo_overlay = self.config.get('LOGO_OVERLAY', '')
        if not logo_overlay:
            return


        if isinstance(self._overlay, type(None)):
            self._overlay, self._alpha_mask = self._load_logo_overlay(self.image)

            if isinstance(self._overlay, bool):
                return

        elif isinstance(self._overlay, bool):
            logger.error('Logo overlay failed to load')
            return


        #alpha_start = time.time()

        self.image = (self.image * (1 - self._alpha_mask) + self._overlay * self._alpha_mask).astype(numpy.uint8)

        #alpha_elapsed_s = time.time() - alpha_start
        #logger.info('Alpha transparency in %0.4f s', alpha_elapsed_s)


    #def equalizeHistogram(self, data):
    #    if self.focus_mode:
    #        # disable processing in focus mode
    #        return

    #    if len(data.shape) == 2:
    #        # mono
    #        return cv2.equalizeHist(data)

    #    # color, apply to luminance
    #    lab = cv2.cvtColor(data, cv2.COLOR_BGR2LAB)

    #    l, a, b = cv2.split(lab)

    #    cl = cv2.equalizeHist(l)

    #    new_lab = cv2.merge((cl, a, b))

    #    return cv2.cvtColor(new_lab, cv2.COLOR_LAB2BGR)


    #def equalizeHistogramColor(self, data):
    #    if self.focus_mode:
    #        # disable processing in focus mode
    #        return

    #    if len(data.shape) == 2:
    #        # mono
    #        return data_bytes

    #    ycrcb_img = cv2.cvtColor(data, cv2.COLOR_BGR2YCrCb)
    #    ycrcb_img[:, :, 0] = cv2.equalizeHist(ycrcb_img[:, :, 0])
    #    return cv2.cvtColor(ycrcb_img, cv2.COLOR_YCrCb2BGR)


    def scale_image(self):
        if self.focus_mode:
            # disable processing in focus mode
            return


        scale = self.config.get('IMAGE_SCALE', 100)

        if scale == 100:
            return


        self._scale_image(scale)
        return True


    def _scale_image(self, scale):
        image_height, image_width = self.image.shape[:2]

        logger.info('Scaling image by %d%%', scale)
        new_height = int(image_height * scale / 100.0)
        new_width = int(image_width * scale / 100.0)

        # ensure size is divisible by 2
        new_height = new_height - (new_height % 2)
        new_width = new_width - (new_width % 2)

        logger.info('New size: %d x %d', new_width, new_height)

        self.image = cv2.resize(self.image, (new_width, new_height), interpolation=cv2.INTER_AREA)


    def splitscreen(self, original_data, new_data):
        # if flip horizontal is set, this data will swap sides later
        if self.config.get('IMAGE_FLIP_H'):
            left_data = new_data
            right_data = original_data
        else:
            left_data = original_data
            right_data = new_data


        image_height, image_width = left_data.shape[:2]

        half_width = int(image_width / 2)

        # left side
        left_mask = numpy.zeros((image_height, image_width), dtype=numpy.uint8)
        cv2.rectangle(
            img=left_mask,
            pt1=(0, 0),
            #pt2=(half_width, image_height),
            pt2=(half_width - 1, image_height),  # ensure a black line is down the center
            color=255,
            thickness=cv2.FILLED,
        )

        masked_left = cv2.bitwise_and(left_data, left_data, mask=left_mask)

        # right side
        right_mask = numpy.zeros((image_height, image_width), dtype=numpy.uint8)
        cv2.rectangle(
            img=right_mask,
            pt1=(half_width + 1, 0),
            pt2=(image_width, image_height),
            color=255,
            thickness=cv2.FILLED,
        )

        masked_right = cv2.bitwise_and(right_data, right_data, mask=right_mask)

        return numpy.maximum(masked_left, masked_right)


    def get_astrometric_data(self):
        utcnow = datetime.now(tz=timezone.utc)  # ephem expects UTC dates
        #utcnow = datetime.now(tz=timezone.utc) - timedelta(hours=13)  # testing

        obs = ephem.Observer()
        obs.lon = math.radians(self.position_av[1])
        obs.lat = math.radians(self.position_av[0])
        obs.elevation = self.position_av[2]


        # disable atmospheric refraction calcs
        obs.pressure = 0


        obs.date = utcnow

        self.astrometric_data['sidereal_time'] = str(obs.sidereal_time())


        sun = ephem.Sun()
        sun.compute(obs)
        self.astrometric_data['sun_alt'] = math.degrees(sun.alt)


        moon = ephem.Moon()
        moon.compute(obs)
        moon_alt = math.degrees(moon.alt)
        self.astrometric_data['moon_alt'] = moon_alt
        self.astrometric_data['moon_phase'] = moon.moon_phase * 100.0

        sun_lon = ephem.Ecliptic(sun).lon
        moon_lon = ephem.Ecliptic(moon).lon
        sm_angle = (moon_lon - sun_lon) % math.tau
        self.astrometric_data['moon_cycle'] = (sm_angle / math.tau) * 100

        if moon_alt >= 0:
            self.astrometric_data['moon_up'] = 'Yes'
        else:
            self.astrometric_data['moon_up'] = 'No'


        obs.date = utcnow  # reset
        sun.compute(obs)

        try:
            sun_next_rise = obs.next_rising(sun)
            self.astrometric_data['sun_next_rise'] = ephem.localtime(sun_next_rise).strftime('%H:%M')
            self.astrometric_data['sun_next_rise_h'] = (sun_next_rise.datetime() - utcnow.replace(tzinfo=None)).total_seconds() / 3600
        except ephem.NeverUpError:
            self.astrometric_data['sun_next_rise'] = '--:--'
            self.astrometric_data['sun_next_rise_h'] = 0.0
        except ephem.AlwaysUpError:
            self.astrometric_data['sun_next_rise'] = '--:--'
            self.astrometric_data['sun_next_rise_h'] = 0.0


        obs.date = utcnow  # reset
        sun.compute(obs)

        try:
            sun_next_set = obs.next_setting(sun)
            self.astrometric_data['sun_next_set'] = ephem.localtime(sun_next_set).strftime('%H:%M')
            self.astrometric_data['sun_next_set_h'] = (sun_next_set.datetime() - utcnow.replace(tzinfo=None)).total_seconds() / 3600
        except ephem.NeverUpError:
            self.astrometric_data['sun_next_set'] = '--:--'
            self.astrometric_data['sun_next_set_h'] = 0.0
        except ephem.AlwaysUpError:
            self.astrometric_data['sun_next_set'] = '--:--'
            self.astrometric_data['sun_next_set_h'] = 0.0


        obs.date = utcnow  # reset
        sun.compute(obs)

        try:
            obs.horizon = math.radians(-18.0)
            sun_next_astro_twilight_rise = obs.next_rising(sun)
            self.astrometric_data['sun_next_astro_twilight_rise'] = ephem.localtime(sun_next_astro_twilight_rise).strftime('%H:%M')
            self.astrometric_data['sun_next_astro_twilight_rise_h'] = (sun_next_astro_twilight_rise.datetime() - utcnow.replace(tzinfo=None)).total_seconds() / 3600
        except ephem.NeverUpError:
            self.astrometric_data['sun_next_astro_twilight_rise'] = '--:--'
            self.astrometric_data['sun_next_astro_twilight_rise_h'] = 0.0
        except ephem.AlwaysUpError:
            self.astrometric_data['sun_next_astro_twilight_rise'] = '--:--'
            self.astrometric_data['sun_next_astro_twilight_rise_h'] = 0.0


        obs.date = utcnow  # reset
        sun.compute(obs)

        try:
            obs.horizon = math.radians(-18.0)
            sun_next_astro_twilight_set = obs.next_setting(sun)
            self.astrometric_data['sun_next_astro_twilight_set'] = ephem.localtime(sun_next_astro_twilight_set).strftime('%H:%M')
            self.astrometric_data['sun_next_astro_twilight_set_h'] = (sun_next_astro_twilight_set.datetime() - utcnow.replace(tzinfo=None)).total_seconds() / 3600
        except ephem.NeverUpError:
            self.astrometric_data['sun_next_astro_twilight_set'] = '--:--'
            self.astrometric_data['sun_next_astro_twilight_set_h'] = 0.0
        except ephem.AlwaysUpError:
            self.astrometric_data['sun_next_astro_twilight_set'] = '--:--'
            self.astrometric_data['sun_next_astro_twilight_set_h'] = 0.0


        obs.horizon = math.radians(0.0)  # reset horizon
        obs.date = utcnow  # reset
        moon.compute(obs)

        try:
            moon_next_rise = obs.next_rising(moon)
            self.astrometric_data['moon_next_rise'] = ephem.localtime(moon_next_rise).strftime('%H:%M')
            self.astrometric_data['moon_next_rise_h'] = (moon_next_rise.datetime() - utcnow.replace(tzinfo=None)).total_seconds() / 3600
        except ephem.NeverUpError:
            self.astrometric_data['moon_next_rise'] = '--:--'
            self.astrometric_data['moon_next_rise_h'] = 0.0
        except ephem.AlwaysUpError:
            self.astrometric_data['moon_next_rise'] = '--:--'
            self.astrometric_data['moon_next_rise_h'] = 0.0


        obs.date = utcnow  # reset
        moon.compute(obs)

        try:
            moon_next_set = obs.next_setting(moon)
            self.astrometric_data['moon_next_set'] = ephem.localtime(moon_next_set).strftime('%H:%M')
            self.astrometric_data['moon_next_set_h'] = (moon_next_set.datetime() - utcnow.replace(tzinfo=None)).total_seconds() / 3600
        except ephem.NeverUpError:
            self.astrometric_data['moon_next_set'] = '--:--'
            self.astrometric_data['moon_next_set_h'] = 0.0
        except ephem.AlwaysUpError:
            self.astrometric_data['moon_next_set'] = '--:--'
            self.astrometric_data['moon_next_set_h'] = 0.0


        obs.date = utcnow  # reset

        mercury = ephem.Mercury()
        mercury.compute(obs)
        mercury_alt = math.degrees(mercury.alt)
        self.astrometric_data['mercury_alt'] = mercury_alt

        if mercury_alt >= 0:
            self.astrometric_data['mercury_up'] = 'Yes'
        else:
            self.astrometric_data['mercury_up'] = 'No'


        venus = ephem.Venus()
        venus.compute(obs)
        venus_alt = math.degrees(venus.alt)
        self.astrometric_data['venus_alt'] = venus_alt
        self.astrometric_data['venus_phase'] = venus.phase

        if venus_alt >= 0:
            self.astrometric_data['venus_up'] = 'Yes'
        else:
            self.astrometric_data['venus_up'] = 'No'


        mars = ephem.Mars()
        mars.compute(obs)
        mars_alt = math.degrees(mars.alt)
        self.astrometric_data['mars_alt'] = mars_alt

        if mars_alt >= 0:
            self.astrometric_data['mars_up'] = 'Yes'
        else:
            self.astrometric_data['mars_up'] = 'No'


        jupiter = ephem.Jupiter()
        jupiter.compute(obs)
        jupiter_alt = math.degrees(jupiter.alt)
        self.astrometric_data['jupiter_alt'] = jupiter_alt

        if jupiter_alt >= 0:
            self.astrometric_data['jupiter_up'] = 'Yes'
        else:
            self.astrometric_data['jupiter_up'] = 'No'


        saturn = ephem.Saturn()
        saturn.compute(obs)
        saturn_alt = math.degrees(saturn.alt)
        self.astrometric_data['saturn_alt'] = saturn_alt

        if saturn_alt >= 0:
            self.astrometric_data['saturn_up'] = 'Yes'
        else:
            self.astrometric_data['saturn_up'] = 'No'


        # separation of 1-3 degrees means a possible eclipse
        self.astrometric_data['sun_moon_sep'] = abs((ephem.separation(moon, sun) / (math.pi / 180)) - 180)


        # satellites
        satellite_data = self.populateSatelliteData()

        iss = satellite_data.get('iss')
        if iss:
            iss.compute(obs)

            iss_alt = math.degrees(iss.alt)
            self.astrometric_data['iss_alt'] = iss_alt

            if iss_alt >= 0:
                self.astrometric_data['iss_up'] = '{0:0.0f}°'.format(iss_alt)
            else:
                self.astrometric_data['iss_up'] = 'No'

            try:
                iss_next_pass = obs.next_pass(iss)
                self.astrometric_data['iss_next_h'] = (iss_next_pass[0].datetime() - utcnow.replace(tzinfo=None)).total_seconds() / 3600
                self.astrometric_data['iss_next_alt'] = math.degrees(iss_next_pass[3])
            except ValueError as e:
                logger.error('ISS next pass error: %s', str(e))
                self.astrometric_data['iss_next_h'] = 0.0
                self.astrometric_data['iss_next_alt'] = 0.0


        hst = satellite_data.get('hst')
        if hst:
            hst.compute(obs)

            hst_alt = math.degrees(hst.alt)
            self.astrometric_data['hst_alt'] = hst_alt

            if hst_alt >= 0:
                self.astrometric_data['hst_up'] = '{0:0.0f}°'.format(hst_alt)
            else:
                self.astrometric_data['hst_up'] = 'No'

            try:
                hst_next_pass = obs.next_pass(hst)
                self.astrometric_data['hst_next_h'] = (hst_next_pass[0].datetime() - utcnow.replace(tzinfo=None)).total_seconds() / 3600
                self.astrometric_data['hst_next_alt'] = math.degrees(hst_next_pass[3])
            except ValueError as e:
                logger.error('HST next pass error: %s', str(e))
                self.astrometric_data['hst_next_h'] = 0.0
                self.astrometric_data['hst_next_alt'] = 0.0


        tiangong = satellite_data.get('tiangong')
        if tiangong:
            tiangong.compute(obs)

            tiangong_alt = math.degrees(tiangong.alt)
            self.astrometric_data['tiangong_alt'] = tiangong_alt

            if tiangong_alt >= 0:
                self.astrometric_data['tiangong_up'] = '{0:0.0f}°'.format(tiangong_alt)
            else:
                self.astrometric_data['tiangong_up'] = 'No'

            try:
                tiangong_next_pass = obs.next_pass(tiangong)
                self.astrometric_data['tiangong_next_h'] = (tiangong_next_pass[0].datetime() - utcnow.replace(tzinfo=None)).total_seconds() / 3600
                self.astrometric_data['tiangong_next_alt'] = math.degrees(tiangong_next_pass[3])
            except ValueError as e:
                logger.error('TIANGONG next pass error: %s', str(e))
                self.astrometric_data['tiangong_next_h'] = 0.0
                self.astrometric_data['tiangong_next_alt'] = 0.0


    def populateSatelliteData(self):
        satellite_data = dict()

        for sat_key, sat_data in self.satellite_dict.items():
            # there may be multiple satellites of the same name, usually pieces of the same rocket
            sat_entry = IndiAllSkyDbTleDataTable.query\
                .filter(IndiAllSkyDbTleDataTable.group == sat_data['group'])\
                .filter(IndiAllSkyDbTleDataTable.title == sat_data['title'])\
                .order_by(IndiAllSkyDbTleDataTable.id.desc())\
                .first()


            if not sat_entry:
                logger.warning('Satellite data not found: %s', sat_data['title'])
                continue

            #logger.info('Found satellite data: %s', sat_name)

            try:
                sat = ephem.readtle(sat_entry.title, sat_entry.line1, sat_entry.line2)
            except ValueError as e:
                logger.error('Satellite TLE data error: %s', str(e))
                continue

            satellite_data[sat_key] = sat

        return satellite_data


    def get_image_label(self, i_ref, adsb_aircraft_list):
        image_label_tmpl = self.config.get('IMAGE_LABEL_TEMPLATE', '{timestamp:%Y%m%d %H:%M:%S}\nExposure {exposure:0.6f}\nGain {gain:d}\nTemp {temp:0.1f}{temp_unit:s}\nStars {stars:d}')


        if self.config.get('TEMP_DISPLAY') == 'f':
            temp_unit = 'F'
        elif self.config.get('TEMP_DISPLAY') == 'k':
            temp_unit = 'K'
        else:
            temp_unit = 'C'


        # calculate rational exposure ("1 1/4")
        exp_whole = int(i_ref.exposure)
        exp_remain = i_ref.exposure - exp_whole

        exp_remain_frac = Fraction(exp_remain).limit_denominator(max_denominator=31250)

        if exp_whole:
            if exp_remain:
                rational_exp = '{0:d} {1:d}/{2:d}'.format(exp_whole, exp_remain_frac.numerator, exp_remain_frac.denominator)
            else:
                rational_exp = '{0:d}'.format(exp_whole)
        else:
            rational_exp = '{0:d}/{1:d}'.format(exp_remain_frac.numerator, exp_remain_frac.denominator)



        label_data = {
            'timestamp'    : i_ref.exp_date,
            'ts'           : i_ref.exp_date,  # shortcut
            'exposure'     : i_ref.exposure,
            'day_date'     : i_ref.day_date,
            'rational_exp' : rational_exp,
            'gain'         : self.gain_v.value,
            'temp_unit'    : temp_unit,
            'sqm'          : i_ref.sqm_value,
            'stars'        : len(i_ref.stars),
            'detections'   : str(bool(len(i_ref.lines))),
            'owner'        : i_ref.owner,
            'location'     : i_ref.location,
            'kpindex'      : i_ref.kpindex,
            'ovation_max'  : i_ref.ovation_max,
            'aurora_mag_bt'    : i_ref.aurora_mag_bt,
            'aurora_mag_gsm_bz': i_ref.aurora_mag_gsm_bz,
            'aurora_plasma_density' : i_ref.aurora_plasma_density,
            'aurora_plasma_speed'   : i_ref.aurora_plasma_speed,
            'aurora_plasma_temp'    : i_ref.aurora_plasma_temp,
            'aurora_n_hemi_gw' : i_ref.aurora_n_hemi_gw,
            'aurora_s_hemi_gw' : i_ref.aurora_s_hemi_gw,
            'smoke_rating' : constants.SMOKE_RATING_MAP_STR[i_ref.smoke_rating],
            'sun_alt'      : self.astrometric_data['sun_alt'],
            'sun_next_rise'     : self.astrometric_data['sun_next_rise'],
            'sun_next_rise_h'   : self.astrometric_data['sun_next_rise_h'],
            'sun_next_set'      : self.astrometric_data['sun_next_set'],
            'sun_next_set_h'    : self.astrometric_data['sun_next_set_h'],
            'sun_next_astro_twilight_rise'   : self.astrometric_data['sun_next_astro_twilight_rise'],
            'sun_next_astro_twilight_rise_h' : self.astrometric_data['sun_next_astro_twilight_rise_h'],
            'sun_next_astro_twilight_set'    : self.astrometric_data['sun_next_astro_twilight_set'],
            'sun_next_astro_twilight_set_h'  : self.astrometric_data['sun_next_astro_twilight_set_h'],
            'moon_alt'     : self.astrometric_data['moon_alt'],
            'moon_phase'   : self.astrometric_data['moon_phase'],
            'moon_cycle'   : self.astrometric_data['moon_cycle'],
            'moon_up'      : self.astrometric_data['moon_up'],
            'moon_next_rise'    : self.astrometric_data['moon_next_rise'],
            'moon_next_rise_h'  : self.astrometric_data['moon_next_rise_h'],
            'moon_next_set'     : self.astrometric_data['moon_next_set'],
            'moon_next_set_h'   : self.astrometric_data['moon_next_set_h'],
            'sun_moon_sep' : self.astrometric_data['sun_moon_sep'],
            'mercury_alt'  : self.astrometric_data['mercury_alt'],
            'mercury_up'   : self.astrometric_data['mercury_up'],
            'venus_alt'    : self.astrometric_data['venus_alt'],
            'venus_phase'  : self.astrometric_data['venus_phase'],
            'venus_up'     : self.astrometric_data['venus_up'],
            'mars_alt'     : self.astrometric_data['mars_alt'],
            'mars_up'      : self.astrometric_data['mars_up'],
            'jupiter_alt'  : self.astrometric_data['jupiter_alt'],
            'jupiter_up'   : self.astrometric_data['jupiter_up'],
            'saturn_alt'   : self.astrometric_data['saturn_alt'],
            'saturn_up'    : self.astrometric_data['saturn_up'],
            'iss_alt'      : self.astrometric_data['iss_alt'],
            'iss_up'       : self.astrometric_data['iss_up'],
            'iss_next_h'   : self.astrometric_data['iss_next_h'],
            'iss_next_alt' : self.astrometric_data['iss_next_alt'],
            'hst_alt'      : self.astrometric_data['hst_alt'],
            'hst_up'       : self.astrometric_data['hst_up'],
            'hst_next_h'   : self.astrometric_data['hst_next_h'],
            'hst_next_alt' : self.astrometric_data['hst_next_alt'],
            'tiangong_alt'      : self.astrometric_data['tiangong_alt'],
            'tiangong_up'       : self.astrometric_data['tiangong_up'],
            'tiangong_next_h'   : self.astrometric_data['tiangong_next_h'],
            'tiangong_next_alt' : self.astrometric_data['tiangong_next_alt'],
            'latitude'     : self.position_av[0],
            'longitude'    : self.position_av[1],
            'elevation'    : int(self.position_av[2]),
            'sidereal_time'        : self.astrometric_data['sidereal_time'],
            'stretch_m1_gamma'     : self.config.get('IMAGE_STRETCH', {}).get('MODE1_GAMMA', 0.0),
            'stretch_m1_stddevs'   : self.config.get('IMAGE_STRETCH', {}).get('MODE1_STDDEVS', 0.0),
        }


        # stacking data
        if self.night_v.value and not self.moonmode_v.value:
            if self.config.get('IMAGE_STACK_COUNT', 1) > 1:
                label_data['stack_method'] = self.config.get('IMAGE_STACK_METHOD', 'average').capitalize()
                label_data['stack_count'] = self.config.get('IMAGE_STACK_COUNT', 1)
            else:
                label_data['stack_method'] = 'Off'
                label_data['stack_count'] = 0
        else:
            # stacking disabled during the day and moonmode
            label_data['stack_method'] = 'Off'
            label_data['stack_count'] = 0


        # stretching data
        if self.config.get('IMAGE_STRETCH', {}).get('CLASSNAME'):
            if self.night_v.value:
                # night
                label_data['stretch'] = 'On'

                if self.moonmode_v.value and not self.config.get('IMAGE_STRETCH', {}).get('MOONMODE'):
                    label_data['stretch'] = 'Off'
            else:
                # daytime
                if self.config.get('IMAGE_STRETCH', {}).get('DAYTIME'):
                    label_data['stretch'] = 'On'
                else:
                    label_data['stretch'] = 'Off'
        else:
            label_data['stretch'] = 'Off'


        for x, temp_c in enumerate(self.sensors_temp_av):
            temp_f = (temp_c * 9.0 / 5.0) + 32
            temp_k = temp_c + 273.15

            if self.config.get('TEMP_DISPLAY') == 'f':
                sensor_temp = temp_f
            elif self.config.get('TEMP_DISPLAY') == 'k':
                sensor_temp = temp_k
            else:
                sensor_temp = temp_c

            label_data['sensor_temp_{0:d}'.format(x)] = sensor_temp
            label_data['sensor_temp_{0:d}_f'.format(x)] = temp_f
            label_data['sensor_temp_{0:d}_c'.format(x)] = temp_c
            label_data['sensor_temp_{0:d}_k'.format(x)] = temp_k


        # 0 == ccd_temp
        label_data['temp'] = label_data['sensor_temp_0']


        for x, sensor_data in enumerate(self.sensors_user_av):
            label_data['sensor_user_{0:d}'.format(x)] = sensor_data


        # dew heater
        if self.sensors_user_av[1]:
            label_data['dew_heater_status'] = 'On'
        else:
            label_data['dew_heater_status'] = 'Off'

        # fan
        if self.sensors_user_av[4]:
            label_data['fan_status'] = 'On'
        else:
            label_data['fan_status'] = 'Off'


        # wind direction
        try:
            label_data['wind_dir'] = self.cardinal_directions[round(self.sensors_user_av[6] / (360 / (len(self.cardinal_directions) - 1)))]
        except IndexError:
            logger.error('Unable to calculate wind direction')
            label_data['wind_dir'] = 'Error'


        image_label = image_label_tmpl.format(**label_data)  # fill in the data


        # Add moon mode indicator
        if self.moonmode_v.value:
            image_label += '\n* Moon Mode *'


        # Add eclipse indicator
        if self.astrometric_data['sun_moon_sep'] < 1.25 and self.night_v.value:
            # Lunar eclipse (earth's penumbra is large)
            image_label += '\n* LUNAR ECLIPSE *'

        if self.astrometric_data['sun_moon_sep'] > 179.0 and not self.night_v.value:
            # Solar eclipse
            image_label += '\n* SOLAR ECLIPSE *'


        # add extra text to image
        extra_text_lines = self.get_extra_text()
        if extra_text_lines:
            logger.info('Adding extra text from %s', self.config['IMAGE_EXTRA_TEXT'])

            for line in extra_text_lines:
                image_label += '\n{0:s}'.format(line)


        # aircraft lines
        adsb_aircraft_lines = self.get_adsb_aircraft_text(adsb_aircraft_list)
        if adsb_aircraft_lines:
            logger.info('Adding aircraft text')

            for line in adsb_aircraft_lines:
                image_label += '\n{0:s}'.format(line)


        # satellite tracking lines
        satellite_tracking_lines = self.get_satellite_tracking_text()
        if satellite_tracking_lines:
            logger.info('Adding satellite text')

            for line in satellite_tracking_lines:
                image_label += '\n{0:s}'.format(line)


        return image_label


    def label_image(self, adsb_aircraft_list=[]):
        # this needs to be enabled during focus mode


        # set initial values
        self.text_color_rgb = list(self.config['TEXT_PROPERTIES']['FONT_COLOR'])
        self.text_xy = [int(self.config['TEXT_PROPERTIES']['FONT_X']), int(self.config['TEXT_PROPERTIES']['FONT_Y'])]
        self.text_anchor_pillow = 'la'  # Pillow: left-ascender
        self.text_size_pillow = int(self.config['TEXT_PROPERTIES']['PIL_FONT_SIZE'])
        self.text_font_height = int(self.config['TEXT_PROPERTIES']['FONT_HEIGHT'])


        i_ref = self.getLatestImage()

        # Labels are enabled by default
        image_label_system = self.config.get('IMAGE_LABEL_SYSTEM', 'pillow')

        if image_label_system == 'opencv':
            self._label_image_opencv(i_ref, adsb_aircraft_list)
        elif image_label_system == 'pillow':
            self._label_image_pillow(i_ref, adsb_aircraft_list)
        else:
            logger.warning('Image labels disabled')
            return


    def cardinal_dirs_label(self):
        if self.focus_mode:
            return

        if not self.config.get('CARDINAL_DIRS', {}).get('ENABLE'):
            return

        self.image = self._cardinal_dirs_label.main(self.image)


    def orb_image(self):
        # Disabled when focus mode is enabled
        if self.focus_mode:
            return

        orb_mode = self.config.get('ORB_PROPERTIES', {}).get('MODE', 'ha')
        if orb_mode == 'off':
            # orbs disabled
            return


        i_ref = self.getLatestImage()

        self._image_orb_opencv(i_ref)


    def _image_orb_opencv(self, i_ref):
        image_height, image_width = self.image.shape[:2]


        utcnow = datetime.now(tz=timezone.utc)  # ephem expects UTC dates
        #utcnow = datetime.now(tz=timezone.utc) - timedelta(hours=13)  # testing

        obs = ephem.Observer()
        obs.lon = math.radians(self.position_av[1])
        obs.lat = math.radians(self.position_av[0])
        obs.elevation = self.position_av[2]


        # disable atmospheric refraction calcs
        obs.pressure = 0


        obs.date = utcnow

        sun = ephem.Sun()
        sun.compute(obs)


        moon = ephem.Moon()
        moon.compute(obs)


        ### ORBS
        orb_mode = self.config.get('ORB_PROPERTIES', {}).get('MODE', 'ha')

        self._orb.text_color_rgb = self.text_color_rgb

        if orb_mode == 'ha':
            self._orb.drawOrbsHourAngle_opencv(self.image, utcnow, obs, sun, moon)
        elif orb_mode == 'az':
            self._orb.drawOrbsAzimuth_opencv(self.image, utcnow, obs, sun, moon)
        elif orb_mode == 'alt':
            self._orb.drawOrbsAltitude_opencv(self.image, utcnow, obs, sun, moon)
        elif orb_mode == 'off':
            # orbs disabled
            pass
        else:
            logger.error('Unknown orb display mode: %s', orb_mode)


    def _label_image_opencv(self, i_ref, adsb_aircraft_list):
        image_height, image_width = self.image.shape[:2]


        # Disabled when focus mode is enabled
        if self.focus_mode:
            logger.warning('Focus mode enabled, labels disabled')

            # indicate focus mode is enabled in indi-allsky
            self.drawText_opencv(
                self.image,
                'Focus Mode',
                tuple(self.image_xy),
                tuple(self.text_color_bgr),
            )

            self.image_xy = [image_width - 250, image_height - 10]
            self.drawText_opencv(
                self.image,
                i_ref.exp_date.strftime('%H:%M:%S'),
                tuple(self.image_xy),
                tuple(self.text_color_bgr),
            )

            return


        image_label = self.get_image_label(i_ref, adsb_aircraft_list)


        for line in image_label.split('\n'):
            if line.startswith('#'):
                self._processLabelComment(line)
                continue


            self.drawText_opencv(
                self.image,
                line,
                tuple(self.text_xy),
                tuple(self.text_color_bgr),
            )

            self._text_next_line()


    def drawText_opencv(self, data, text, pt, color_bgr):
        fontFace = getattr(cv2, self.config['TEXT_PROPERTIES']['FONT_FACE'])
        lineType = getattr(cv2, self.config['TEXT_PROPERTIES']['FONT_AA'])

        if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
            cv2.putText(
                img=data,
                text=text,
                org=pt,
                fontFace=fontFace,
                color=(0, 0, 0),
                lineType=lineType,
                fontScale=self.config['TEXT_PROPERTIES']['FONT_SCALE'],
                thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'] + 1,
            )  # black outline
        cv2.putText(
            img=data,
            text=text,
            org=pt,
            fontFace=fontFace,
            color=tuple(color_bgr),
            lineType=lineType,
            fontScale=self.config['TEXT_PROPERTIES']['FONT_SCALE'],
            thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'],
        )


    def _label_image_pillow(self, i_ref, adsb_aircraft_list):
        img_rgb = Image.fromarray(cv2.cvtColor(self.image, cv2.COLOR_BGR2RGB))
        image_width, image_height  = img_rgb.size  # backwards from opencv


        if self.config['TEXT_PROPERTIES']['PIL_FONT_FILE'] == 'custom':
            pillow_font_file_p = Path(self.config['TEXT_PROPERTIES']['PIL_FONT_CUSTOM'])
        else:
            pillow_font_file_p = self.font_path.joinpath(self.config['TEXT_PROPERTIES']['PIL_FONT_FILE'])


        draw = ImageDraw.Draw(img_rgb)


        # Disabled when focus mode is enabled
        if self.focus_mode:
            logger.warning('Focus mode enabled, labels disabled')

            # indicate focus mode is enabled in indi-allsky
            self.drawText_pillow(
                draw,
                'Focus Mode',
                pillow_font_file_p,
                self.text_size_pillow,
                tuple(self.text_xy),
                tuple(self.text_color_rgb),
                anchor=self.text_anchor_pillow,
            )

            self.text_xy = [image_width - 300, image_height - (self.text_font_height * 2)]
            self.drawText_pillow(
                draw,
                i_ref.exp_date.strftime('%H:%M:%S'),
                pillow_font_file_p,
                self.text_size_pillow,
                tuple(self.text_xy),
                tuple(self.text_color_rgb),
                anchor=self.text_anchor_pillow,
            )

            # convert back to numpy array
            self.image = cv2.cvtColor(numpy.array(img_rgb), cv2.COLOR_RGB2BGR)

            return


        image_label = self.get_image_label(i_ref, adsb_aircraft_list)


        for line in image_label.split('\n'):
            if line.startswith('#'):
                self._processLabelComment(line)
                continue


            self.drawText_pillow(
                draw,
                line,
                pillow_font_file_p,
                self.text_size_pillow,
                tuple(self.text_xy),
                tuple(self.text_color_rgb),
                anchor=self.text_anchor_pillow,
            )

            self._text_next_line()


        # convert back to numpy array
        self.image = cv2.cvtColor(numpy.array(img_rgb), cv2.COLOR_RGB2BGR)


    def drawText_pillow(self, draw, text, font_file, font_size, pt, color_rgb, anchor='la'):
        font = ImageFont.truetype(str(font_file), font_size)

        if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
            # black outline
            stroke_width = 4
        else:
            stroke_width = 0

        draw.text(
            pt,
            text,
            fill=color_rgb,
            font=font,
            stroke_width=stroke_width,
            stroke_fill=(0, 0, 0),
            anchor=anchor,
        )


    def get_extra_text(self):
        if not self.config.get('IMAGE_EXTRA_TEXT'):
            return list()


        image_extra_text_p = Path(self.config['IMAGE_EXTRA_TEXT'])

        try:
            if not image_extra_text_p.exists():
                logger.error('%s does not exist', image_extra_text_p)
                return list()


            if not image_extra_text_p.is_file():
                logger.error('%s is not a file', image_extra_text_p)
                return list()


            # Sanity check
            if image_extra_text_p.stat().st_size > 10000:
                logger.error('%s is too large', image_extra_text_p)
                return list()

        except PermissionError as e:
            logger.error(str(e))
            return list()


        try:
            with io.open(str(image_extra_text_p), 'r') as image_extra_text_f:
                extra_lines = [x.rstrip() for x in image_extra_text_f.readlines()]
                image_extra_text_f.close()
        except PermissionError as e:
            logger.error('Permission Error: %s', str(e))
            return list()


        #logger.info('Extra text: %s', extra_lines)

        return extra_lines


    def get_adsb_aircraft_text(self, adsb_aircraft_list):
        if not self.config.get('ADSB', {}).get('ENABLE'):
            return list()

        if not self.config.get('ADSB', {}).get('LABEL_ENABLE'):
            return list()


        aircraft_lines = []


        for line in self.config.get('ADSB', {}).get('IMAGE_LABEL_TEMPLATE_PREFIX', '').splitlines():
            aircraft_lines.append(line)


        label_limit = self.config.get('ADSB', {}).get('LABEL_LIMIT', 10)
        aircraft_tmpl = self.config.get('ADSB', {}).get('AIRCRAFT_LABEL_TEMPLATE', '')
        for i in range(label_limit):
            try:
                aircraft_data = adsb_aircraft_list[i].copy()
            except IndexError:
                # no more aircraft
                break


            if not aircraft_data['squawk']:
                aircraft_data['squawk'] = ''

            if not aircraft_data['flight']:
                aircraft_data['flight'] = ''

            if not aircraft_data['hex']:
                aircraft_data['hex'] = ''

            try:
                aircraft_data['dir'] = self.cardinal_directions[round(aircraft_data['az'] / 22.5)]
            except IndexError:
                logger.error('Unable to calculate aircraft direction')
                aircraft_data['dir'] = 'Error'


            aircraft_lines.append(aircraft_tmpl.format(**aircraft_data))  # fill in the data


        return aircraft_lines


    def get_satellite_tracking_text(self):
        if not self.config.get('SATELLITE_TRACK', {}).get('ENABLE'):
            return list()

        if not self.config.get('SATELLITE_TRACK', {}).get('LABEL_ENABLE'):
            return list()

        if not self.config.get('SATELLITE_TRACK', {}).get('DAYTIME_TRACK') and not self.night_v.value:
            return list()


        sat_track_start = time.time()


        utcnow = datetime.now(tz=timezone.utc)  # ephem expects UTC dates
        #utcnow = datetime.now(tz=timezone.utc) - timedelta(hours=13)  # testing

        obs = ephem.Observer()
        obs.lon = math.radians(self.position_av[1])
        obs.lat = math.radians(self.position_av[0])
        obs.elevation = self.position_av[2]


        # disable atmospheric refraction calcs
        obs.pressure = 0


        obs.date = utcnow


        # there may be multiple satellites of the same name, usually pieces of the same rocket
        sat_entries = IndiAllSkyDbTleDataTable.query\
            .filter(IndiAllSkyDbTleDataTable.group == constants.SATELLITE_VISUAL)\
            .order_by(IndiAllSkyDbTleDataTable.id.desc())\
            .limit(300)  # 300 is a sanity check


        satellite_lines = []

        for line in self.config.get('SATELLITE_TRACK', {}).get('IMAGE_LABEL_TEMPLATE_PREFIX', '').splitlines():
            satellite_lines.append(line)


        alt_deg_min = self.config.get('SATELLITE_TRACK', {}).get('ALT_DEG_MIN', 20)
        label_limit = self.config.get('SATELLITE_TRACK', {}).get('LABEL_LIMIT', 10)
        satellite_tmpl = self.config.get('SATELLITE_TRACK', {}).get('SAT_LABEL_TEMPLATE', '')


        sat_list = list()
        for sat_entry in sat_entries:

            try:
                sat = ephem.readtle(sat_entry.title, sat_entry.line1, sat_entry.line2)
            except ValueError as e:
                logger.error('Satellite TLE data error: %s', str(e))
                continue


            sat.compute(obs)


            if sat.eclipsed:
                continue


            sat_alt = math.degrees(sat.alt)

            if sat_alt < alt_deg_min:
                continue


            sat_sublat = math.degrees(sat.sublat)
            sat_sublong = math.degrees(sat.sublong)

            sat_data = {
                'title'     : sat_entry.title.rstrip(),
                'alt'       : sat_alt,
                'az'        : math.degrees(sat.az),
                'elevation' : sat.elevation / 1000,
                'mag'       : sat.mag,
                'sublat'    : sat_sublat,
                'latitude'  : sat_sublat,  # alias
                'sublong'   : sat_sublong,
                'longitude' : sat_sublong,  # alias
                'range'     : sat.range / 1000,
                'range_velocity' : sat.range_velocity / 1000,
            }


            try:
                sat_data['dir'] = self.cardinal_directions[round(sat_data['az'] / 22.5)]
            except IndexError:
                logger.error('Unable to calculate aircraft direction')
                sat_data['dir'] = 'Error'


            sat_list.append(sat_data)


        sat_track_elapsed_s = time.time() - sat_track_start
        logger.info('Satellite tracking in %0.4f s', sat_track_elapsed_s)


        # sort by highest satellites
        sorted_sat_list = sorted(sat_list, key=lambda x: x['alt'], reverse=True)


        for i in range(label_limit):
            try:
                sat_data = sorted_sat_list[i]
            except IndexError:
                # no more satellites
                break


            satellite_lines.append(satellite_tmpl.format(**sat_data))  # fill in the data


        return satellite_lines


    def _text_next_line(self):
        text_xy = self.text_xy

        text_xy[1] += self.text_font_height

        self.text_xy = text_xy

        return text_xy


    def _processLabelComment(self, line):
        # text color and location can be updated here

        m_color = re.search(r'color:(?P<red>\d{1,3}),(?P<green>\d{1,3}),(?P<blue>\d{1,3})', line, re.IGNORECASE)
        if m_color:
            color_data = m_color.groupdict()
            self.text_color_rgb = [color_data['red'], color_data['green'], color_data['blue']]


        m_xy = re.search(r'xy:(?P<x>\-?\d+),(?P<y>\-?\d+)', line, re.IGNORECASE)
        if m_xy:
            xy_data = m_xy.groupdict()
            self.text_xy = [xy_data['x'], xy_data['y']]


        m_anchor = re.search(r'anchor:(?P<anchor>[a-z][a-z])', line, re.IGNORECASE)
        if m_anchor:
            anchor_data = m_anchor.groupdict()
            self.text_anchor_pillow = str(anchor_data['anchor']).lower()


        m_size = re.search(r'size:(?P<size>\d+)', line, re.IGNORECASE)
        if m_size:
            size_data = m_size.groupdict()
            self.text_size_pillow = int(size_data['size'])
            self.text_font_height = int(size_data['size'])  # increase spacing


    def stretch(self):
        if self.focus_mode:
            # disable processing in focus mode
            return


        if isinstance(self._stretch, type(None)):
            return


        if self.night_v.value:
            # night
            if self.moonmode_v.value and not self.config.get('IMAGE_STRETCH', {}).get('MOONMODE'):
                return
        else:
            # daytime
            if not self.config.get('IMAGE_STRETCH', {}).get('DAYTIME'):
                return



        stretched_image = self._stretch.stretch(self.image, self.max_bit_depth)


        if self.config.get('IMAGE_STRETCH', {}).get('SPLIT'):
            self.image = self.splitscreen(self.image, stretched_image)
            return


        self.image = stretched_image


    def fish2pano_module(self):
        import fish2pano

        #fish2pano_start = time.time()

        image_height, image_width = self.image.shape[:2]

        x_offset = self.config.get('LENS_OFFSET_X', 0)
        y_offset = self.config.get('LENS_OFFSET_Y', 0)

        recenter_width = image_width + (abs(x_offset) * 2)
        recenter_height = image_height + (abs(y_offset) * 2)
        #logger.info('New: %d x %d', recenter_width, recenter_height)


        recenter_image = numpy.zeros([recenter_height, recenter_width, 3], dtype=numpy.uint8)
        recenter_image[
            int((recenter_height / 2) - (image_height / 2) + y_offset):int((recenter_height / 2) + (image_height / 2) + y_offset),
            int((recenter_width / 2) - (image_width / 2) - x_offset):int((recenter_width / 2) + (image_width / 2) - x_offset),
        ] = self.image  # recenter the image circle in the new image


        angle = self.config.get('FISH2PANO', {}).get('ROTATE_ANGLE', 0)
        if angle:
            center_x = int(recenter_width / 2)
            center_y = int(recenter_height / 2)

            rot = cv2.getRotationMatrix2D((center_x, center_y), int(angle), 1.0)

            abs_cos = abs(rot[0, 0])
            abs_sin = abs(rot[0, 1])

            bound_w = int(recenter_height * abs_sin + recenter_width * abs_cos)
            bound_h = int(recenter_height * abs_cos + recenter_width * abs_sin)

            rot[0, 2] += bound_w / 2 - center_x
            rot[1, 2] += bound_h / 2 - center_y

            rotated_image = cv2.warpAffine(recenter_image, rot, (bound_w, bound_h))
        else:
            rotated_image = recenter_image


        rot_height, rot_width = rotated_image.shape[:2]


        center_x = int(rot_width / 2)
        center_y = int(rot_height / 2)

        radius = self.config.get('FISH2PANO', {}).get('DIAMETER', 3000) / 2
        scale = self.config.get('FISH2PANO', {}).get('SCALE', 0.3)


        img_pano = fish2pano.fish2pano(rotated_image, radius, [center_x, center_y], scale)


        pano_height, pano_width = img_pano.shape[:2]
        mod_height = pano_height % 2
        mod_width = pano_width % 2

        if mod_height or mod_width:
            # width and height needs to be divisible by 2 for timelapse
            crop_width = pano_width - mod_width

            img_pano = img_pano[
                mod_height:pano_height,  # trim the top
                0:crop_width,
            ]


        if self.config.get('FISH2PANO', {}).get('FLIP_H'):
            img_pano = cv2.flip(img_pano, 1)


        #fish2pano_elapsed_s = time.time() - fish2pano_start
        #logger.info('Panorama in %0.4f s', fish2pano_elapsed_s)

        # original image not replaced
        return img_pano


    def fish2pano_warpPolar(self):
        #fish2pano_start = time.time()

        image_height, image_width = self.image.shape[:2]

        x_offset = self.config.get('LENS_OFFSET_X', 0)
        y_offset = self.config.get('LENS_OFFSET_Y', 0)

        recenter_width = image_width + (abs(x_offset) * 2)
        recenter_height = image_height + (abs(y_offset) * 2)
        #logger.info('New: %d x %d', recenter_width, recenter_height)


        recenter_image = numpy.zeros([recenter_height, recenter_width, 3], dtype=numpy.uint8)
        recenter_image[
            int((recenter_height / 2) - (image_height / 2) + y_offset):int((recenter_height / 2) + (image_height / 2) + y_offset),
            int((recenter_width / 2) - (image_width / 2) - x_offset):int((recenter_width / 2) + (image_width / 2) - x_offset),
        ] = self.image  # recenter the image circle in the new image


        angle = self.config.get('FISH2PANO', {}).get('ROTATE_ANGLE', 0)
        if angle:
            center_x = int(recenter_width / 2)
            center_y = int(recenter_height / 2)

            rot = cv2.getRotationMatrix2D((center_x, center_y), int(angle), 1.0)

            abs_cos = abs(rot[0, 0])
            abs_sin = abs(rot[0, 1])

            bound_w = int(recenter_height * abs_sin + recenter_width * abs_cos)
            bound_h = int(recenter_height * abs_cos + recenter_width * abs_sin)

            rot[0, 2] += bound_w / 2 - center_x
            rot[1, 2] += bound_h / 2 - center_y

            rotated_image = cv2.warpAffine(recenter_image, rot, (bound_w, bound_h))
        else:
            rotated_image = recenter_image


        #cv2.imwrite('/tmp/rot_fish2pano.jpg', rotated_image, [cv2.IMWRITE_JPEG_QUALITY, 90])  # debugging


        rot_height, rot_width = rotated_image.shape[:2]


        center_x = int(rot_width / 2)
        center_y = int(rot_height / 2)

        radius = int(self.config.get('FISH2PANO', {}).get('DIAMETER', 3000) / 2)
        scale = self.config.get('FISH2PANO', {}).get('SCALE', 0.3)


        # FIXME: areas outside the image have a pattern
        img_pano = cv2.warpPolar(rotated_image, (int(radius * scale), int((2 * math.pi * radius) * scale)), (center_x, center_y), radius, cv2.WARP_POLAR_LINEAR)
        img_pano = cv2.rotate(img_pano, cv2.ROTATE_90_CLOCKWISE)


        pano_height, pano_width = img_pano.shape[:2]
        mod_height = pano_height % 2
        mod_width = pano_width % 2

        if mod_height or mod_width:
            # width and height needs to be divisible by 2 for timelapse
            crop_width = pano_width - mod_width

            img_pano = img_pano[
                mod_height:pano_height,  # trim the top
                0:crop_width,
            ]


        # this logic is reversed due to changes between fish2pano to opencv warpPolar
        if not self.config.get('FISH2PANO', {}).get('FLIP_H'):
            img_pano = cv2.flip(img_pano, 1)


        #fish2pano_elapsed_s = time.time() - fish2pano_start
        #logger.info('Panorama in %0.4f s', fish2pano_elapsed_s)

        # original image not replaced
        return img_pano


    def fish2pano(self):
        return self.fish2pano_module()
        #return self.fish2pano_warpPolar()


    def fish2pano_cardinal_dirs_label(self, pano_data):
        if not self.config.get('CARDINAL_DIRS', {}).get('ENABLE'):
            return pano_data

        return self._cardinal_dirs_label.panorama_label(pano_data)


    def moon_overlay(self):
        if self.focus_mode:
            return


        if not self.config.get('MOON_OVERLAY', {}).get('ENABLE', True):
            return

        self._moon_overlay.apply(self.image, self.astrometric_data['moon_cycle'], self.astrometric_data['moon_phase'])


    def lightgraph_overlay(self):
        if self.focus_mode:
            return


        if not self.config.get('LIGHTGRAPH_OVERLAY', {}).get('ENABLE', True):
            return

        self._lightgraph_overlay.apply(self.image)


    def add_border(self):
        top = self.config.get('IMAGE_BORDER', {}).get('TOP', 0)
        left = self.config.get('IMAGE_BORDER', {}).get('LEFT', 0)
        right = self.config.get('IMAGE_BORDER', {}).get('RIGHT', 0)
        bottom = self.config.get('IMAGE_BORDER', {}).get('BOTTOM', 0)


        if not top and not left and not right and not bottom:
            return


        border_color_bgr = list(self.config.get('IMAGE_BORDER', {}).get('COLOR', [0, 0, 0]))
        border_color_bgr.reverse()


        image_height, image_width = self.image.shape[:2]

        new_height = image_height + top + bottom
        new_width = image_width + left + right


        new_image = numpy.full([new_height, new_width, 3], border_color_bgr, dtype=numpy.uint8)

        new_image[
            top:top + image_height,
            left:left + image_width,
        ] = self.image


        self.image = new_image


    def realtimeKeogramUpdate(self):
        if self.focus_mode:
            return

        image_height, image_width = self.image.shape[:2]


        if isinstance(self.realtime_keogram_data, type(None)):
            if self._keogram_store_p.exists() and self._keogram_store_p.stat().st_size > 0:
                # load stored data
                try:
                    self.realtime_keogram_data = self.realtimeKeogramDataLoad()
                except ValueError:
                    logger.error('Invalid numpy data for realtime keogram')
                    self._keogram_store_p.unlink()


        try:
            self._keogram_gen.processImage(self.image, int(time.time()))
        except KeogramMismatchException as e:
            logger.error('Error processing keogram image: %s', str(e))
            self.realtime_keogram_data = None

            if self._keogram_store_p.exists():
                # remove any existing data store
                self._keogram_store_p.unlink()

            return


        max_entries = self.config.get('REALTIME_KEOGRAM', {}).get('MAX_ENTRIES', 1000)
        while self._keogram_gen.keogram_data.shape[1] > max_entries:
            self._keogram_gen.keogram_data = numpy.delete(self.realtime_keogram_data, 0, 1)

        # timestamps might not be populated if numpy data loaded from file
        while len(self._keogram_gen.timestamps_list) > max_entries:
            self._keogram_gen.timestamps_list.pop(0)


    def realtimeKeogramDataLoad(self):
        logger.info('Loading stored realtime keogram data')
        with io.open(str(self._keogram_store_p), 'r+b') as f_numpy:
            keogram_data = numpy.load(f_numpy)

        return keogram_data


    def realtimeKeogramDataSave(self):
        if isinstance(self.realtime_keogram_data, type(None)):
            logger.warning('Realtime keogram data is empty')
            return

        logger.info('Storing realtime keogram data')
        with io.open(str(self._keogram_store_p), 'w+b') as f_numpy:
            numpy.save(f_numpy, self.realtime_keogram_data)


    def _load_detection_mask(self):
        detect_mask = self.config.get('DETECT_MASK', '')

        if not detect_mask:
            logger.warning('No detection mask defined')
            return


        detect_mask_p = Path(detect_mask)

        try:
            if not detect_mask_p.exists():
                logger.error('%s does not exist', detect_mask_p)
                return


            if not detect_mask_p.is_file():
                logger.error('%s is not a file', detect_mask_p)
                return

        except PermissionError as e:
            logger.error(str(e))
            return

        mask_data = cv2.imread(str(detect_mask_p), cv2.IMREAD_GRAYSCALE)  # mono
        if isinstance(mask_data, type(None)):
            logger.error('%s is not a valid image', detect_mask_p)
            return


        logger.info('Loaded detection mask: %s', detect_mask_p)

        ### any compression artifacts will be set to black
        #mask_data[mask_data < 255] = 0  # did not quite work


        return mask_data


    def _load_logo_overlay(self, image):
        logo_overlay = self.config.get('LOGO_OVERLAY', '')

        if not logo_overlay:
            logger.warning('No logo overlay defined')
            return None, None


        logo_overlay_p = Path(logo_overlay)

        try:
            if not logo_overlay_p.exists():
                logger.error('%s does not exist', logo_overlay_p)
                return None, None


            if not logo_overlay_p.is_file():
                logger.error('%s is not a file', logo_overlay_p)
                return None, None

        except PermissionError as e:
            logger.error(str(e))
            return None, None

        overlay_img = cv2.imread(str(logo_overlay_p), cv2.IMREAD_UNCHANGED)
        if isinstance(overlay_img, type(None)):
            logger.error('%s is not a valid image', logo_overlay_p)
            return False, None  # False so the image is not retried


        if overlay_img.shape[:2] != image.shape[:2]:
            logger.error('Logo dimensions do not match image')
            return False, None  # False so the image is not retried


        try:
            if overlay_img.shape[2] != 4:
                logger.error('%s does not have an alpha channel')
                return False, None  # False so the image is not retried
        except IndexError:
            logger.error('%s does not have an alpha channel')
            return False, None  # False so the image is not retried


        overlay_bgr = overlay_img[:, :, :3]
        overlay_alpha = (overlay_img[:, :, 3] / 255).astype(numpy.float32)


        alpha_mask = numpy.dstack((overlay_alpha, overlay_alpha, overlay_alpha))


        return overlay_bgr, alpha_mask


    def _generateAduMask(self, img):
        logger.info('Generating mask based on ADU_ROI')

        image_height, image_width = img.shape[:2]

        # create a black background
        mask = numpy.zeros((image_height, image_width), dtype=numpy.uint8)

        adu_roi = self.config.get('ADU_ROI', [])

        try:
            x1 = int(adu_roi[0] / self.bin_v.value)
            y1 = int(adu_roi[1] / self.bin_v.value)
            x2 = int(adu_roi[2] / self.bin_v.value)
            y2 = int(adu_roi[3] / self.bin_v.value)
        except IndexError:
            logger.warning('Using central ROI for ADU calculations')
            adu_fov_div = self.config.get('ADU_FOV_DIV', 4)
            x1 = int((image_width / 2) - (image_width / adu_fov_div))
            y1 = int((image_height / 2) - (image_height / adu_fov_div))
            x2 = int((image_width / 2) + (image_width / adu_fov_div))
            y2 = int((image_height / 2) + (image_height / adu_fov_div))

        # The white area is what we keep
        cv2.rectangle(
            img=mask,
            pt1=(x1, y1),
            pt2=(x2, y2),
            color=(255),  # mono
            thickness=cv2.FILLED,
        )

        self._adu_mask = mask


    def _generate_image_circle_mask(self, image):
        image_height, image_width = image.shape[:2]


        opacity = self.config['IMAGE_CIRCLE_MASK']['OPACITY']
        if self.config['IMAGE_CIRCLE_MASK']['OUTLINE']:
            logger.warning('Opacity disabled for image circle outline')
            opacity = 0


        background = int(255 * (100 - opacity) / 100)
        #logger.info('Image circle backgound: %d', background)

        channel_mask = numpy.full([image_height, image_width], background, dtype=numpy.uint8)

        center_x = int(image_width / 2) + self.config.get('LENS_OFFSET_X', 0)
        center_y = int(image_height / 2) - self.config.get('LENS_OFFSET_Y', 0)  # minus
        radius = int(self.config['IMAGE_CIRCLE_MASK']['DIAMETER'] / 2)
        blur = self.config['IMAGE_CIRCLE_MASK']['BLUR']


        # draw a white circle
        cv2.circle(
            img=channel_mask,
            center=(center_x, center_y),
            radius=radius,
            color=(255),
            thickness=cv2.FILLED,
        )


        if blur:
            # blur circle
            channel_mask = cv2.blur(
                src=channel_mask,
                ksize=(blur, blur),
                borderType=cv2.BORDER_DEFAULT,
            )


        channel_alpha = (channel_mask / 255).astype(numpy.float32)

        alpha_mask = numpy.dstack((channel_alpha, channel_alpha, channel_alpha))

        return alpha_mask



class ImageData(object):

    def __init__(
        self,
        config,
        hdulist,
        exposure,
        exp_date,
        exp_elapsed,
        day_date,
        camera_id,
        camera_name,
        camera_uuid,
        owner,
        location,
        image_bitpix,
        image_bayerpat,
        target_adu,
    ):
        self.config = config

        self._hdulist = hdulist
        self._exposure = exposure
        self._exp_date = exp_date
        self._exp_elapsed = exp_elapsed
        self._day_date = day_date
        self._camera_id = camera_id
        self._camera_name = camera_name
        self._camera_uuid = camera_uuid
        self._owner = owner
        self._location = location
        self._image_bitpix = image_bitpix
        self._image_bayerpat = image_bayerpat
        self._target_adu = target_adu

        self._detected_bit_depth = 8  # updated below
        self._calibrated = False
        self._libcamera_black_level = None
        self._opencv_data = None

        self._kpindex = 0.0
        self._ovation_max = 0
        self._aurora_mag_bt = 0.0
        self._aurora_mag_gsm_bz = 0.0
        self._aurora_plasma_density = 0.0
        self._aurora_plasma_speed = 0.0
        self._aurora_plasma_temp = 0
        self._aurora_n_hemi_gw = 0
        self._aurora_s_hemi_gw = 0

        self._smoke_rating = constants.SMOKE_RATING_NODATA

        self._sqm_value = None
        self._lines = list()
        self._stars = list()


        self.detectBitDepth()


    @property
    def hdulist(self):
        return self._hdulist

    @property
    def exposure(self):
        return self._exposure

    @property
    def exp_date(self):
        return self._exp_date

    @property
    def exp_elapsed(self):
        return self._exp_elapsed

    @property
    def day_date(self):
        return self._day_date

    @property
    def camera_id(self):
        return self._camera_id

    @property
    def camera_name(self):
        return self._camera_name

    @property
    def camera_uuid(self):
        return self._camera_uuid

    @property
    def owner(self):
        return self._owner

    @property
    def location(self):
        return self._location

    @property
    def image_bayerpat(self):
        return self._image_bayerpat

    @property
    def target_adu(self):
        return self._target_adu


    @property
    def detected_bit_depth(self):
        return self._detected_bit_depth

    @detected_bit_depth.setter
    def detected_bit_depth(self, new_detected_bit_depth):
        self._detected_bit_depth = int(new_detected_bit_depth)

    @property
    def calibrated(self):
        return self._calibrated

    @calibrated.setter
    def calibrated(self, new_calibrated):
        self._calibrated = bool(new_calibrated)

    @property
    def libcamera_black_level(self):
        return self._libcamera_black_level

    @libcamera_black_level.setter
    def libcamera_black_level(self, new_libcamera_black_level):
        self._libcamera_black_level = bool(new_libcamera_black_level)


    @property
    def image_bitpix(self):
        return self._image_bitpix

    @image_bitpix.setter
    def image_bitpix(self, new_image_bitpix):
        self._image_bitpix = int(new_image_bitpix)

    @property
    def opencv_data(self):
        return self._opencv_data

    @opencv_data.setter
    def opencv_data(self, new_opencv_data):
        self._opencv_data = new_opencv_data


    @property
    def kpindex(self):
        return self._kpindex

    @kpindex.setter
    def kpindex(self, new_kpindex):
        self._kpindex = float(new_kpindex)

    @property
    def ovation_max(self):
        return self._ovation_max

    @ovation_max.setter
    def ovation_max(self, new_ovation_max):
        self._ovation_max = int(new_ovation_max)

    @property
    def aurora_mag_bt(self):
        return self._aurora_mag_bt

    @aurora_mag_bt.setter
    def aurora_mag_bt(self, new_aurora_mag_bt):
        self._aurora_mag_bt = float(new_aurora_mag_bt)

    @property
    def aurora_mag_gsm_bz(self):
        return self._aurora_mag_gsm_bz

    @aurora_mag_gsm_bz.setter
    def aurora_mag_gsm_bz(self, new_aurora_mag_gsm_bz):
        self._aurora_mag_gsm_bz = float(new_aurora_mag_gsm_bz)

    @property
    def aurora_plasma_density(self):
        return self._aurora_plasma_density

    @aurora_plasma_density.setter
    def aurora_plasma_density(self, new_aurora_plasma_density):
        self._aurora_plasma_density = float(new_aurora_plasma_density)

    @property
    def aurora_plasma_speed(self):
        return self._aurora_plasma_speed

    @aurora_plasma_speed.setter
    def aurora_plasma_speed(self, new_aurora_plasma_speed):
        self._aurora_plasma_speed = float(new_aurora_plasma_speed)

    @property
    def aurora_plasma_temp(self):
        return self._aurora_plasma_temp

    @aurora_plasma_temp.setter
    def aurora_plasma_temp(self, new_aurora_plasma_temp):
        self._aurora_plasma_temp = int(new_aurora_plasma_temp)

    @property
    def aurora_n_hemi_gw(self):
        return self._aurora_n_hemi_gw

    @aurora_n_hemi_gw.setter
    def aurora_n_hemi_gw(self, new_aurora_n_hemi_gw):
        self._aurora_n_hemi_gw = int(new_aurora_n_hemi_gw)

    @property
    def aurora_s_hemi_gw(self):
        return self._aurora_s_hemi_gw

    @aurora_s_hemi_gw.setter
    def aurora_s_hemi_gw(self, new_aurora_s_hemi_gw):
        self._aurora_s_hemi_gw = int(new_aurora_s_hemi_gw)


    @property
    def smoke_rating(self):
        return self._smoke_rating

    @smoke_rating.setter
    def smoke_rating(self, new_smoke_rating):
        self._smoke_rating = int(new_smoke_rating)

    @property
    def sqm_value(self):
        return self._sqm_value

    @sqm_value.setter
    def sqm_value(self, new_sqm_value):
        self._sqm_value = float(new_sqm_value)

    @property
    def lines(self):
        return self._lines

    @lines.setter
    def lines(self, new_lines):
        self._lines = new_lines

    @property
    def stars(self):
        return self._stars

    @stars.setter
    def stars(self, new_stars):
        self._stars = new_stars


    def detectBitDepth(self):
        max_val = numpy.amax(self.hdulist[0].data)
        logger.info('Image max value: %d', int(max_val))

        # This method of detecting bit depth can cause the 16->8 bit conversion
        # to stretch too much.  This most commonly happens with very low gains
        # during the day when there are no hot pixels.  This can result in a
        # trippy effect
        if max_val > 16383:
            detected_bit_depth = 16
        elif max_val > 4095:
            detected_bit_depth = 14
        elif max_val > 1023:
            detected_bit_depth = 12
        elif max_val > 255:
            detected_bit_depth = 10
        else:
            detected_bit_depth = 8

        #logger.info('Detected bit depth: %d', detected_bit_depth)


        self.detected_bit_depth = detected_bit_depth



