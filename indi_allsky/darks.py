import os
import sys
import locale
import io
import time
import math
import tempfile
import json
import psutil
import subprocess
from datetime import datetime
from collections import OrderedDict
from pathlib import Path
import logging

import numpy
import cv2

from multiprocessing import Queue
from multiprocessing import Value
from multiprocessing import Array

from .exceptions import TimeOutException
from .exceptions import TemperatureException
from .exceptions import CameraException
from .exceptions import BadImage

from .config import IndiAllSkyConfig

from . import camera as camera_module

from . import constants

from .flask import create_app
from .flask import db
from .flask.miscDb import miscDb

#from .flask.models import TaskQueueState
#from .flask.models import TaskQueueQueue
from .flask.models import IndiAllSkyDbCameraTable
from .flask.models import IndiAllSkyDbDarkFrameTable
from .flask.models import IndiAllSkyDbBadPixelMapTable
#from .flask.models import IndiAllSkyDbTaskQueueTable

from sqlalchemy.orm.exc import NoResultFound


try:
    import rawpy  # not available in all cases
except ImportError:
    rawpy = None


app = create_app()

logger = logging.getLogger('indi_allsky')


class IndiAllSkyDarks(object):

    def __init__(self):
        # should be inherited by all of the sub-processes
        locale.setlocale(locale.LC_ALL, '')

        with app.app_context():
            try:
                self._config_obj = IndiAllSkyConfig()
            except NoResultFound:
                logger.error('No config file found, please import a config')
                sys.exit(1)

            self.config = self._config_obj.config

        self._daytime = True  # build daytime dark library

        self._gain_list = []
        self._binning = 1
        self._count = 10
        self._temp_delta = 5.0
        self._time_delta = 5

        self._hotpixel_adu_percent = 90

        self._reverse = True  # default high to low exposures

        # this is used to set a max value of data returned by the camera
        self._bitmax = 0

        self._flush_camera_id = 1

        self.image_q = Queue()
        self.indiclient = None

        self.camera_id = None
        self.camera_name = None
        self.camera_server = None
        self.ccd_info = None

        self.indi_config = self.config.get('INDI_CONFIG_DEFAULTS', {})


        self.exposure_av = Array('f', [
            -1.0,  # current exposure
            -1.0,  # next exposure
            -1.0,  # exposure delta
            -1.0,  # night minimum
            -1.0,  # day minimum
            -1.0,  # maximum
            -1.0,  # sqm
        ])


        self.gain_av = Array('f', [
            -1.0,  # current gain
            -1.0,  # next gain
            -1.0,  # gain delta
            -1.0,  # day minimum
            -1.0,  # day maximum
            -1.0,  # night minimum
            -1.0,  # night maximum
            -1.0,  # moon mode minimum
            -1.0,  # moon mode maximum
            -1.0,  # sqm
        ])


        self.binning_av = Array('i', [
            -1,  # current bin
            -1,  # next bin
            -1,  # day bin
            -1,  # night bin
            -1,  # moonmode bin
            -1,  # sqm
        ])


        self.sensors_temp_av = Array('f', [0.0])  # 0 ccd_temp

        self.night_v = Value('i', -1)  # bogus initial value
        self.moonmode_v = Value('i', 0)

        # not used, but required
        self.position_av = Array('f', [
            float(self.config['LOCATION_LATITUDE']),
            float(self.config['LOCATION_LONGITUDE']),
            float(self.config.get('LOCATION_ELEVATION', 300)),
            0.0,  # Ra
            0.0,  # Dec
        ])

        self._miscDb = miscDb(self.config)


        if self.config['IMAGE_FOLDER']:
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()

        self.darks_dir = self.image_dir.joinpath('darks')


    @property
    def count(self):
        return self._count

    @count.setter
    def count(self, new_count):
        #logger.info('Changing image count to %d', int(new_count))
        self._count = int(new_count)


    @property
    def gain_list(self):
        return self._gain_list

    @gain_list.setter
    def gain_list(self, new_list_str):
        if isinstance(new_list_str, type(None)):
            logger.warning('Using gain values from config')
            time.sleep(3.0)
            return

        try:
            gain_list = [float(round(x, 2)) for x in new_list_str]
        except ValueError:
            logger.error('Invalid gain list: %s', str(new_list_str))
            sys.exit(1)
        except TypeError:
            logger.error('Invalid gain list: %s', str(new_list_str))
            sys.exit(1)


        self._gain_list = sorted(gain_list, reverse=True)
        logger.warning('Using gain list: %s', ', '.join(['{0:0.2f}'.format(x) for x in self._gain_list]))


    @property
    def binning(self):
        return self._binning

    @binning.setter
    def binning(self, new_binning):
        self._binning = int(new_binning)
        assert self._binning >= 1
        assert self._binning <= 4


    @property
    def temp_delta(self):
        return self._temp_delta

    @temp_delta.setter
    def temp_delta(self, new_temp_delta):
        self._temp_delta = float(abs(new_temp_delta))
        logger.warning('New Temp delta: %0.1f', self.temp_delta)


    @property
    def time_delta(self):
        return self._time_delta

    @time_delta.setter
    def time_delta(self, new_time_delta):
        self._time_delta = int(abs(new_time_delta))
        logger.warning('New Time delta: %d', self.time_delta)


    @property
    def bitmax(self):
        return self._bitmax

    @bitmax.setter
    def bitmax(self, new_bitmax):
        self._bitmax = int(new_bitmax)
        assert self._bitmax in (0, 8, 10, 12, 14, 16)

        if self.bitmax > 0:
            logger.warning('New bitmax: %d', self.bitmax)


    @property
    def flush_camera_id(self):
        return self._flush_camera_id

    @flush_camera_id.setter
    def flush_camera_id(self, new_camera_id):
        self._flush_camera_id = int(new_camera_id)


    @property
    def hotpixel_adu_percent(self):
        return self._hotpixel_adu_percent

    @hotpixel_adu_percent.setter
    def hotpixel_adu_percent(self, new_hotpixel_adu_percent):
        self._hotpixel_adu_percent = int(new_hotpixel_adu_percent)


    @property
    def daytime(self):
        return self._daytime

    @daytime.setter
    def daytime(self, new_daytime):
        self._daytime = bool(new_daytime)


    @property
    def reverse(self):
        return self._reverse

    @reverse.setter
    def reverse(self, new_reverse):
        self._reverse = bool(new_reverse)


    def _initialize(self):
        camera_interface = getattr(camera_module, self.config.get('CAMERA_INTERFACE', 'indi'))


        # instantiate the client
        self.indiclient = camera_interface(
            self.config,
            self.image_q,
            self.position_av,
            self.exposure_av,
            self.gain_av,
            self.binning_av,
            self.night_v,
            self.moonmode_v,
        )


        # set indi server localhost and port
        self.indiclient.setServer(self.config['INDI_SERVER'], self.config['INDI_PORT'])

        # connect to indi server
        logger.info("Connecting to indiserver")
        if not self.indiclient.connectServer():
            logger.error("No indiserver running on %s:%d - Try to run", self.indiclient.getHost(), self.indiclient.getPort())
            logger.error("  indiserver indi_simulator_telescope indi_simulator_ccd")
            sys.exit(1)

        # give devices a chance to register
        time.sleep(8)


        try:
            self.indiclient.findCcd(camera_name=self.config.get('INDI_CAMERA_NAME'))
        except CameraException as e:
            logger.error('Camera error: %s', str(e))
            sys.exit(1)


        if not self.indiclient.ccd_device:
            logger.error('No CCDs detected')
            time.sleep(1)
            sys.exit(1)


        logger.warning('Connecting to device %s', self.indiclient.ccd_device.getDeviceName())
        self.indiclient.connectDevice(self.indiclient.ccd_device.getDeviceName())

        # add driver name to config
        self.camera_name = self.indiclient.ccd_device.getDeviceName()
        self.camera_server = self.indiclient.ccd_device.getDriverExec()


        # Get Properties
        ccd_properties = self.indiclient.getCcdDeviceProperties()
        self.config['CCD_PROPERTIES'] = ccd_properties


        # get CCD information
        ccd_info = self.indiclient.getCcdInfo()
        self.ccd_info = ccd_info


        if self.config.get('CFA_PATTERN'):
            cfa_pattern = self.config['CFA_PATTERN']
        else:
            cfa_pattern = ccd_info['CCD_CFA']['CFA_TYPE'].get('text')


        # need to get camera info before adding to DB
        camera_metadata = {
            'type'        : constants.CAMERA,
            'name'        : self.camera_name,
            'driver'      : self.camera_server,

            'hidden'      : False,  # unhide camera

            'minExposure' : float(ccd_info.get('CCD_EXPOSURE', {}).get('CCD_EXPOSURE_VALUE', {}).get('min')),
            'maxExposure' : float(ccd_info.get('CCD_EXPOSURE', {}).get('CCD_EXPOSURE_VALUE', {}).get('max')),
            'minGain'     : float(ccd_info.get('GAIN_INFO', {}).get('min')),
            'maxGain'     : float(ccd_info.get('GAIN_INFO', {}).get('max')),
            'minBinning'  : int(ccd_info.get('BINNING_INFO', {}).get('min')),
            'maxBinning'  : int(ccd_info.get('BINNING_INFO', {}).get('max')),

            'width'       : int(ccd_info.get('CCD_FRAME', {}).get('WIDTH', {}).get('max')),
            'height'      : int(ccd_info.get('CCD_FRAME', {}).get('HEIGHT', {}).get('max')),
            'bits'        : int(ccd_info.get('CCD_INFO', {}).get('CCD_BITSPERPIXEL', {}).get('current')),
            'pixelSize'   : float(ccd_info.get('CCD_INFO', {}).get('CCD_PIXEL_SIZE', {}).get('current')),
            'cfa'         : constants.CFA_STR_MAP[cfa_pattern],

            'location'    : self.config['LOCATION_NAME'],
            'latitude'    : self.position_av[constants.POSITION_LATITUDE],
            'longitude'   : self.position_av[constants.POSITION_LONGITUDE],
            'elevation'   : int(self.position_av[constants.POSITION_ELEVATION]),

            'owner'           : self.config['OWNER'],
            'lensName'        : self.config['LENS_NAME'],
            'lensFocalLength' : self.config['LENS_FOCAL_LENGTH'],
            'lensFocalRatio'  : self.config['LENS_FOCAL_RATIO'],
            'lensImageCircle' : self.config['LENS_IMAGE_CIRCLE'],
            'lensOffsetX'     : self.config.get('LENS_OFFSET_X', 0),
            'lensOffsetY'     : self.config.get('LENS_OFFSET_Y', 0),

            'alt'             : self.config['LENS_ALTITUDE'],
            'az'              : self.config['LENS_AZIMUTH'],
            'nightSunAlt'     : self.config['NIGHT_SUN_ALT_DEG'],
        }

        db_camera = self._miscDb.addCamera(camera_metadata)
        self.camera_id = db_camera.id

        try:
            # Disable debugging
            self.indiclient.disableDebugCcd()
        except TimeOutException:
            logger.warning('Camera does not support debug')

        # set BLOB mode to BLOB_ALSO
        self.indiclient.updateCcdBlobMode()

        self.indiclient.configureCcdDevice(self.indi_config)  # night config by default


        try:
            self.indiclient.setCcdFrameType('FRAME_DARK')
        except TimeOutException:
            # this is an optional step
            # occasionally the CCD_FRAME_TYPE property is not available during initialization
            logger.warning('Unable to set CCD_FRAME_TYPE to Dark')


        # set SQM exposure
        sqm_exposure = float(self.config.get('CAMERA_SQM', {}).get('EXPOSURE', 15.0))
        with self.exposure_av.get_lock():
            self.exposure_av[constants.EXPOSURE_SQM] = float(sqm_exposure)


        logger.info('SQM CCD exposure: %0.8f', self.exposure_av[constants.EXPOSURE_SQM])


        # Validate gain settings
        ccd_min_gain = float(ccd_info['GAIN_INFO']['min'])
        ccd_max_gain = float(ccd_info['GAIN_INFO']['max'])

        if self.config['CCD_CONFIG']['NIGHT']['GAIN'] < ccd_min_gain:
            logger.error('CCD night gain below minimum, changing to %0.2f', float(ccd_min_gain))
            gain_night = float(ccd_min_gain)
            time.sleep(3)
        elif self.config['CCD_CONFIG']['NIGHT']['GAIN'] > ccd_max_gain:
            logger.error('CCD night gain above maximum, changing to %0.2f', float(ccd_max_gain))
            gain_night = float(ccd_max_gain)
            time.sleep(3)
        else:
            gain_night = float(self.config['CCD_CONFIG']['NIGHT']['GAIN'])


        if self.config['CCD_CONFIG']['MOONMODE']['GAIN'] < ccd_min_gain:
            logger.error('CCD moon mode gain below minimum, changing to %0.2f', float(ccd_min_gain))
            gain_moonmode = float(ccd_min_gain)
            time.sleep(3)
        elif self.config['CCD_CONFIG']['MOONMODE']['GAIN'] > ccd_max_gain:
            logger.error('CCD moon mode gain above maximum, changing to %0.2f', float(ccd_max_gain))
            gain_moonmode = float(ccd_max_gain)
            time.sleep(3)
        else:
            gain_moonmode = float(self.config['CCD_CONFIG']['MOONMODE']['GAIN'])


        if self.config['CCD_CONFIG']['DAY']['GAIN'] < ccd_min_gain:
            logger.error('CCD day gain below minimum, changing to %0.12f', float(ccd_min_gain))
            gain_day = float(ccd_min_gain)
            time.sleep(3)
        elif self.config['CCD_CONFIG']['DAY']['GAIN'] > ccd_max_gain:
            logger.error('CCD day gain above maximum, changing to %0.2f', float(ccd_max_gain))
            gain_day = float(ccd_max_gain)
            time.sleep(3)
        else:
            gain_day = float(self.config['CCD_CONFIG']['DAY']['GAIN'])


        if self.config.get('CAMERA_SQM', {}).get('GAIN', 0.0) < ccd_min_gain:
            logger.error('CCD sqm gain below minimum, changing to %0.2f', float(ccd_min_gain))
            gain_sqm = float(ccd_min_gain)
            time.sleep(3)
        elif self.config.get('CAMERA_SQM', {}).get('GAIN', 0.0) > ccd_max_gain:
            logger.error('CCD sqm gain above maximum, changing to %0.2f', float(ccd_max_gain))
            gain_sqm = float(ccd_max_gain)
            time.sleep(3)
        else:
            gain_sqm = self.config.get('CAMERA_SQM', {}).get('GAIN', 0.0)


        with self.gain_av.get_lock():
            self.gain_av[constants.GAIN_CURRENT] = float(gain_day)  # just need a valid value
            self.gain_av[constants.GAIN_NEXT] = float(gain_day)

            self.gain_av[constants.GAIN_MAX_NIGHT] = float(gain_night)
            self.gain_av[constants.GAIN_MAX_MOONMODE] = float(gain_moonmode)

            # day is always lowest gain
            self.gain_av[constants.GAIN_MAX_DAY] = float(gain_day)
            self.gain_av[constants.GAIN_MIN_DAY] = float(gain_day)

            self.gain_av[constants.GAIN_MIN_NIGHT] = float(gain_night)
            self.gain_av[constants.GAIN_MIN_MOONMODE] = float(gain_moonmode)

            self.gain_av[constants.GAIN_SQM] = float(gain_sqm)


        logger.info('Minimum CCD gain: %0.2f (day)', self.gain_av[constants.GAIN_MIN_DAY])
        logger.info('Maximum CCD gain: %0.2f (day)', self.gain_av[constants.GAIN_MAX_DAY])
        logger.info('Minimum CCD gain: %0.2f (night)', self.gain_av[constants.GAIN_MIN_NIGHT])
        logger.info('Maximum CCD gain: %0.2f (night)', self.gain_av[constants.GAIN_MAX_NIGHT])
        logger.info('Minimum CCD gain: %0.2f (moonmode)', self.gain_av[constants.GAIN_MIN_MOONMODE])
        logger.info('Maximum CCD gain: %0.2f (moonmode)', self.gain_av[constants.GAIN_MAX_MOONMODE])
        logger.info('SQM CCD gain: %0.2f', self.gain_av[constants.GAIN_SQM])


        # Validate binning settings
        ccd_min_binning = int(ccd_info['BINNING_INFO']['min'])
        ccd_max_binning = int(ccd_info['BINNING_INFO']['max'])


        if self.config['CCD_CONFIG']['NIGHT']['BINNING'] < ccd_min_binning:
            logger.error('CCD night binning below minimum, changing to %d', int(ccd_min_binning))
            binning_night = int(ccd_min_binning)
            time.sleep(3)
        elif self.config['CCD_CONFIG']['NIGHT']['BINNING'] > ccd_max_binning:
            logger.error('CCD night binning above maximum, changing to %d', int(ccd_max_binning))
            binning_night = int(ccd_max_binning)
            time.sleep(3)
        else:
            binning_night = int(self.config['CCD_CONFIG']['NIGHT']['BINNING'])


        if self.config['CCD_CONFIG']['MOONMODE']['BINNING'] < ccd_min_binning:
            logger.error('CCD moonmode binning below minimum, changing to %d', int(ccd_min_binning))
            binning_moonmode = int(ccd_min_binning)
            time.sleep(3)
        elif self.config['CCD_CONFIG']['MOONMODE']['BINNING'] > ccd_max_binning:
            logger.error('CCD moonmode binning above maximum, changing to %d', int(ccd_max_binning))
            binning_moonmode = int(ccd_max_binning)
            time.sleep(3)
        else:
            binning_moonmode = int(self.config['CCD_CONFIG']['MOONMODE']['BINNING'])


        if self.config['CCD_CONFIG']['DAY']['BINNING'] < ccd_min_binning:
            logger.error('CCD day binning below minimum, changing to %d', int(ccd_min_binning))
            binning_day = int(ccd_min_binning)
            time.sleep(3)
        elif self.config['CCD_CONFIG']['DAY']['BINNING'] > ccd_max_binning:
            logger.error('CCD day binning above maximum, changing to %d', int(ccd_max_binning))
            binning_day = int(ccd_max_binning)
            time.sleep(3)
        else:
            binning_day = int(self.config['CCD_CONFIG']['DAY']['BINNING'])


        if self.config.get('CAMERA_SQM', {}).get('BINNING', 1) < ccd_min_binning:
            logger.error('CCD sqm binning below minimum, changing to %d', int(ccd_min_binning))
            binning_sqm = int(ccd_min_binning)
            time.sleep(3)
        elif self.config.get('CAMERA_SQM', {}).get('BINNING', 1) > ccd_max_binning:
            logger.error('CCD sqm binning above maximum, changing to %d', int(ccd_max_binning))
            binning_sqm = int(ccd_max_binning)
            time.sleep(3)
        else:
            binning_sqm = int(self.config.get('CAMERA_SQM', {}).get('BINNING', 1))



        with self.binning_av.get_lock():
            self.binning_av[constants.BINNING_DAY] = int(binning_day)
            self.binning_av[constants.BINNING_NIGHT] = int(binning_night)
            self.binning_av[constants.BINNING_MOONMODE] = int(binning_moonmode)
            self.binning_av[constants.BINNING_SQM] = int(binning_sqm)


        logger.info('CCD binning: %d (day)', self.binning_av[constants.BINNING_DAY])
        logger.info('CCD binning: %d (night)', self.binning_av[constants.BINNING_NIGHT])
        logger.info('CCD binning: %d (moonmode)', self.binning_av[constants.BINNING_MOONMODE])
        logger.info('CCD binning: %d (SQM)', self.binning_av[constants.BINNING_SQM])


    def shoot(self, exposure, gain, binning, sync=True, timeout=None):
        logger.info('Taking %0.8fs exposure (gain %0.2f / bin %d)', exposure, gain, binning)

        self.indiclient.setCcdExposure(exposure, gain, binning, sync=sync, timeout=timeout)


    def _wait_for_image(self, exposure):
        from astropy.io import fits

        i_dict = self.image_q.get(timeout=10)

        ### Not using DB task queue for image processing to reduce database I/O
        #task_id = i_dict['task_id']

        #try:
        #    task = IndiAllSkyDbTaskQueueTable.query\
        #        .filter(IndiAllSkyDbTaskQueueTable.id == task_id)\
        #        .filter(IndiAllSkyDbTaskQueueTable.state == TaskQueueState.QUEUED)\
        #        .filter(IndiAllSkyDbTaskQueueTable.queue == TaskQueueQueue.IMAGE)\
        #        .one()

        #except NoResultFound:
        #    logger.error('Task ID %d not found', task_id)
        #    raise


        # go ahead and set complete
        #task.setSuccess('Dark frame processed')

        #filename = Path(task.data['filename'])
        ###


        filename_p = Path(i_dict['filename'])

        if not filename_p.exists():
            #task.setFailed('Frame not found: {0:s}'.format(str(filename_p)))
            raise Exception('Frame not found {0:s}'.format(str(filename_p)))


        if filename_p.stat().st_size == 0:
            #task.setFailed('Frame is empty: {0:s}'.format(str(filename_p)))
            raise Exception('Frame is empty: {0:s}'.format(str(filename_p)))



        ### Open file
        if filename_p.suffix in ['.fit']:
            try:
                hdulist = fits.open(filename_p)
            except OSError as e:
                filename_p.unlink()
                raise BadImage(str(e)) from e
        elif filename_p.suffix in ['.jpg', '.jpeg']:
            ### OpenCV
            #data = cv2.imread(str(filename_p), cv2.IMREAD_UNCHANGED)

            #if isinstance(data, type(None)):
            #    raise BadImage('Bad jpeg image')

            #if len(data.shape) == 3:
            #    data = cv2.cvtColor(data, cv2.COLOR_BGR2RGB)  # opencv returns BGR


            ### pillow
            #import PIL
            #from PIL import Image

            #try:
            #    with Image.open(str(filename_p)) as img:
            #        data = numpy.array(img)  # pillow returns RGB
            #except PIL.UnidentifiedImageError:
            #    raise BadImage('Bad jpeg image')


            ### simplejpeg
            import simplejpeg

            try:
                with io.open(str(filename_p), 'rb') as f_img:
                    data = simplejpeg.decode_jpeg(f_img.read(), colorspace='RGB')
            except ValueError as e:
                filename_p.unlink()
                raise BadImage('Bad jpeg image - {0:s}'.format(str(e)))


            if len(data.shape) == 3:
                # swap axes for FITS
                data = numpy.swapaxes(data, 1, 0)
                data = numpy.swapaxes(data, 2, 0)


            # create a new fits container
            hdu = fits.PrimaryHDU(data)
            hdulist = fits.HDUList([hdu])

            hdu.update_header()  # populates BITPIX, NAXIS, etc

            hdulist[0].header['IMAGETYP'] = 'Dark Frame'
            hdulist[0].header['INSTRUME'] = 'jpeg'
            hdulist[0].header['EXPTIME'] = float(exposure)
            hdulist[0].header['XBINNING'] = int(self.binning_av[constants.BINNING_CURRENT])
            hdulist[0].header['YBINNING'] = int(self.binning_av[constants.BINNING_CURRENT])
            hdulist[0].header['GAIN'] = float(self.gain_av[constants.GAIN_CURRENT])
            hdulist[0].header['CCD-TEMP'] = self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP]
            #hdulist[0].header['BITPIX'] = 8
        elif filename_p.suffix in ['.png']:
            # PNGs may be 16-bit, use OpenCV
            data = cv2.imread(str(filename_p), cv2.IMREAD_UNCHANGED)

            if isinstance(data, type(None)):
                filename_p.unlink()
                raise BadImage('Bad png image')


            if len(data.shape) == 3:
                if data.shape[2] == 4:
                    # remove alpha channel
                    data = data[:, :, :3]

                data = cv2.cvtColor(data, cv2.COLOR_BGR2RGB)

                # swap axes for FITS
                data = numpy.swapaxes(data, 1, 0)
                data = numpy.swapaxes(data, 2, 0)


            # create a new fits container
            hdu = fits.PrimaryHDU(data)
            hdulist = fits.HDUList([hdu])

            hdu.update_header()  # populates BITPIX, NAXIS, etc

            hdulist[0].header['IMAGETYP'] = 'Dark Frame'
            hdulist[0].header['INSTRUME'] = 'png'
            hdulist[0].header['EXPTIME'] = float(exposure)
            hdulist[0].header['XBINNING'] = int(self.binning_av[constants.BINNING_CURRENT])
            hdulist[0].header['YBINNING'] = int(self.binning_av[constants.BINNING_CURRENT])
            hdulist[0].header['GAIN'] = float(self.gain_av[constants.GAIN_CURRENT])
            hdulist[0].header['CCD-TEMP'] = self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP]
            #hdulist[0].header['BITPIX'] = 8
        elif filename_p.suffix in ['.dng']:
            if not rawpy:
                filename_p.unlink()
                raise Exception('*** rawpy module not available ***')

            # DNG raw
            try:
                raw = rawpy.imread(str(filename_p))
            except rawpy._rawpy.LibRawIOError as e:
                filename_p.unlink()
                raise BadImage(str(e)) from e

            scidata_uncalibrated = raw.raw_image

            # create a new fits container for DNG data
            hdu = fits.PrimaryHDU(scidata_uncalibrated)
            hdulist = fits.HDUList([hdu])

            hdu.update_header()  # populates BITPIX, NAXIS, etc

            hdulist[0].header['IMAGETYP'] = 'Dark Frame'
            hdulist[0].header['INSTRUME'] = 'libcamera'
            hdulist[0].header['EXPTIME'] = float(exposure)
            hdulist[0].header['XBINNING'] = int(self.binning_av[constants.BINNING_CURRENT])
            hdulist[0].header['YBINNING'] = int(self.binning_av[constants.BINNING_CURRENT])
            hdulist[0].header['GAIN'] = float(self.gain_av[constants.GAIN_CURRENT])
            hdulist[0].header['CCD-TEMP'] = self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP]
            #hdulist[0].header['BITPIX'] = 16

            if self.config.get('CFA_PATTERN'):
                hdulist[0].header['BAYERPAT'] = self.config['CFA_PATTERN']
                hdulist[0].header['XBAYROFF'] = 0
                hdulist[0].header['YBAYROFF'] = 0
            elif self.ccd_info['CCD_CFA']['CFA_TYPE'].get('text'):
                hdulist[0].header['BAYERPAT'] = self.ccd_info['CCD_CFA']['CFA_TYPE']['text']
                hdulist[0].header['XBAYROFF'] = 0
                hdulist[0].header['YBAYROFF'] = 0

            #for h in hdulist[0].header.keys():
            #    logger.info('  Header: %s = %s', h, str(hdulist[0].header[h]))
        else:
            raise Exception('Unsupported dark frame source')


        filename_p.unlink()  # no longer need the original file


        return hdulist


    def average(self):
        self.checkAvailableSpace()


        with app.app_context():
            self._average()


        # shutdown
        self.indiclient.disableCcdCooler()
        self.indiclient.disconnectServer()


    def _average(self):
        self._initialize()
        self._pre_run_tasks()

        self._run(IndiAllSkyDarksAverage)


    def tempaverage(self):
        self.checkAvailableSpace()


        with app.app_context():
            self._tempaverage()


        # shutdown
        self.indiclient.disableCcdCooler()
        self.indiclient.disconnectServer()


    def _tempaverage(self):
        # disable daytime darks processing when doing temperature calibrated frames
        self.daytime = False

        self._initialize()

        self._pre_run_tasks()

        self._pre_temperature_action()
        self.getCcdTemperature()
        logger.info('Camera temperature: %0.1f', self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP])


        next_temp_thold = self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP] - self.temp_delta

        # get first set of images
        self._run(IndiAllSkyDarksAverage)

        while True:
            # This loop will run forever, it is up to the user to cancel
            self._pre_temperature_action()
            self.getCcdTemperature()

            logger.info('Next temperature threshold: %0.1f (current: %0.1f)', next_temp_thold, self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP])

            if self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP] > next_temp_thold:
                time.sleep(30.0)
                continue

            logger.warning('Achieved next temperature threshold: %0.1f | %0.1f', next_temp_thold, self.temp_delta)
            next_temp_thold -= self.temp_delta

            self._run(IndiAllSkyDarksAverage)


    def sigmaclip(self):
        self.checkAvailableSpace()


        with app.app_context():
            self._sigmaclip()


        # shutdown
        self.indiclient.disableCcdCooler()
        self.indiclient.disconnectServer()


    def _sigmaclip(self):
        self._initialize()
        self._pre_run_tasks()

        self._run(IndiAllSkyDarksSigmaClip)


    def tempsigmaclip(self):
        self.checkAvailableSpace()


        with app.app_context():
            self._tempsigmaclip()


        # shutdown
        self.indiclient.disableCcdCooler()
        self.indiclient.disconnectServer()


    def _tempsigmaclip(self):
        # disable daytime darks processing when doing temperature calibrated frames
        self.daytime = False

        self._initialize()

        self._pre_run_tasks()

        self._pre_temperature_action()
        self.getCcdTemperature()
        logger.info('Camera temperature: %0.1f', self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP])


        next_temp_thold = self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP] - self.temp_delta

        # get first set of images
        self._run(IndiAllSkyDarksSigmaClip)

        while True:
            # This loop will run forever, it is up to the user to cancel
            self._pre_temperature_action()
            self.getCcdTemperature()

            logger.info('Next temperature threshold: %0.1f (current: %0.1f)', next_temp_thold, self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP])

            if self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP] > next_temp_thold:
                time.sleep(30.0)
                continue

            logger.warning('Achieved next temperature threshold: %0.1f | %0.1f', next_temp_thold, self.temp_delta)
            next_temp_thold -= self.temp_delta

            self._run(IndiAllSkyDarksSigmaClip)


    def _pre_run_tasks(self):
        # Tasks that need to be run before the main program loop

        if self.camera_server in ['indi_rpicam']:
            # Raspberry PI HQ Camera requires an initial throw away exposure of over 6s
            # in order to take exposures longer than 7s
            logger.info('Taking throw away exposure for rpicam')
            self.shoot(7.0, self.gain_av[constants.GAIN_MIN_DAY], 1, sync=True, timeout=20.0)


            i_dict = self.image_q.get(timeout=10)

            ### Not using DB task queue for image processing to reduce database I/O
            #task_id = i_dict['task_id']

            #try:
            #    task = IndiAllSkyDbTaskQueueTable.query\
            #        .filter(IndiAllSkyDbTaskQueueTable.id == task_id)\
            #        .filter(IndiAllSkyDbTaskQueueTable.state == TaskQueueState.QUEUED)\
            #        .filter(IndiAllSkyDbTaskQueueTable.queue == TaskQueueQueue.IMAGE)\
            #        .one()

            #except NoResultFound:
            #    logger.error('Task ID %d not found', task_id)
            #    raise


            ### go ahead and set complete
            #task.setSuccess('Throw away frame')

            #filename = Path(task.data['filename'])
            ###


            filename = Path(i_dict['filename'])

            if not filename.exists():
                #task.setFailed('Frame not found: {0:s}'.format(str(filename)))
                raise Exception('Frame not found {0:s}'.format(str(filename)))


            filename.unlink()  # no longer need the original file


    def _pre_shoot_reconfigure(self):
        if self.camera_server in ['indi_asi_ccd']:
            # There is a bug in the ASI120M* camera that causes exposures to fail on gain changes
            # The indi_asi_ccd server will switch the camera to 8-bit mode to try to correct
            if self.camera_name.startswith('ZWO CCD ASI120'):
                self.indiclient.configureCcdDevice(self.indi_config)
        elif self.camera_server in ['indi_asi_single_ccd']:
            if self.camera_name.startswith('ZWO ASI120'):
                self.indiclient.configureCcdDevice(self.indi_config)


    def _pre_temperature_action(self):
        if self.config['CAMERA_INTERFACE'].startswith('libcamera_') or self.config['CAMERA_INTERFACE'].startswith('mqtt_'):
            # libcamera only reports temperature changes when an exposure is taken
            logger.warning('TAKING THROW AWAY EXPOSURE TO UPDATE TEMPERATURE')
            self.shoot(0.1, self.gain_av[constants.GAIN_MIN_DAY], 1, sync=True, timeout=10.0)
            i_dict = self.image_q.get(timeout=10)
            filename = Path(i_dict['filename'])

            try:
                filename.unlink()
            except FileNotFoundError:
                pass
        elif self.camera_server == 'indi_libcamera_ccd':
            # libcamera only reports temperature changes when an exposure is taken
            logger.warning('TAKING THROW AWAY EXPOSURE TO UPDATE TEMPERATURE')
            self.shoot(0.1, self.gain_av[constants.GAIN_MIN_DAY], 1, sync=True, timeout=10.0)
            i_dict = self.image_q.get(timeout=10)
            filename = Path(i_dict['filename'])

            try:
                filename.unlink()
            except FileNotFoundError:
                pass
        elif 'indi_pylibcamera' in self.camera_server:  # SPECIAL CASE
            # libcamera only reports temperature changes when an exposure is taken
            logger.warning('TAKING THROW AWAY EXPOSURE TO UPDATE TEMPERATURE')
            self.shoot(0.1, self.gain_av[constants.GAIN_MIN_DAY], 1, sync=True, timeout=10.0)
            i_dict = self.image_q.get(timeout=10)
            filename = Path(i_dict['filename'])

            try:
                filename.unlink()
            except FileNotFoundError:
                pass


    @staticmethod
    def _format_time(seconds):
        """Take an integer number of seconds and return a string in the format HH:MM:SS."""
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return "{:02}h:{:02}m:{:02}s".format(int(hours), int(minutes), int(seconds))


    def _estimate_runtime(self, remaining_exposures, remaining_configs, overhead_per_exposure):
        """Estimate the remaining runtime in seconds of the _run function."""

        # Initialize time to zero
        total_time = 0

        # Add the time for each exposure plus overhead.
        total_exposure_time = sum(remaining_exposures) * self.count + len(remaining_exposures) * overhead_per_exposure
        total_time += total_exposure_time * remaining_configs

        return total_time


    def _run(self, stacking_class):
        dark_exposures_set = set()  # prevent duplicate exposures
        dark_exposures_set.add(1)  # 1s is the shortest exposure

        x = math.ceil(self.config['CCD_EXPOSURE_MAX'])
        while x > 1:
            dark_exposures_set.add(int(x))
            x -= self.time_delta


        dark_exposures = sorted(dark_exposures_set)


        if self.reverse:
            dark_exposures.reverse()  # take longer exposures first


        logger.info('Exposures: %s', ', '.join([str(x) for x in dark_exposures]))


        bpm_filename_t = 'bpm_ccd{0:d}_{1:d}bit_{2:d}s_gain{3:d}_bin{4:d}_{5:d}c_{6:s}.fit'  # filename gain as int
        dark_filename_t = 'dark_ccd{0:d}_{1:d}bit_{2:d}s_gain{3:d}_bin{4:d}_{5:d}c_{6:s}.fit'
        # 0  = ccd id
        # 1  = bits
        # 2  = exposure (seconds)
        # 3  = gain
        # 4  = binning
        # 5  = temperature
        # 6  = date
        # 7  = extension


        night_darks_odict = OrderedDict()  # using OrderedDict as a pseudo-set, we only care about keys
        # keys are a tuple of (gain, binmode)


        if self.gain_list:
            # use CLI values for gain
            self.daytime = False

            for gain in self.gain_list:
                night_darks_odict.update(
                    {
                        (float(gain), self.binning) : None,
                    }
                )

        else:
            # use config values for gain
            # if NIGHT and MOONMODE have the same parameters, no need to double the work
            night_darks_odict.update(
                {
                    (float(self.gain_av[constants.GAIN_MAX_NIGHT]), int(self.binning_av[constants.BINNING_NIGHT])) : None,
                }
            )
            night_darks_odict.update(
                {
                    (float(self.gain_av[constants.GAIN_MAX_MOONMODE]), int(self.binning_av[constants.BINNING_MOONMODE])) : None,
                }
            )
            night_darks_odict.update(
                {
                    (float(self.gain_av[constants.GAIN_SQM]), int(self.binning_av[constants.BINNING_SQM])) : None,
                }
            )


        ### take darks
        remaining_configs = len(night_darks_odict.keys()) + 1  # include daytime
        overhead_per_exposure = 30.0  # seconds, initial estimate
        completed_exposures = 0


        if self.config['CAMERA_INTERFACE'].startswith('libcamera_') or self.config['CAMERA_INTERFACE'].startswith('mqtt_'):
            if self.config.get('LIBCAMERA', {}).get('AWB_ENABLE_DAY'):
                logger.warning('DAYTIME AWB IS ENABLED.  DISABLING DAYTIME DARKS')
                self.daytime = False


        # take day darks with cooling disabled
        if self.daytime:
            ### DAY
            with self.night_v.get_lock():
                self.night_v.value = 0


            # take day darks with cooling enabled
            if self.config.get('CCD_COOLING_DAY'):
                ccd_temp = self.config.get('CCD_TEMP_DAY', 35.0)
                self.indiclient.enableCcdCooler()
                logger.warning('****** WAITING UP TO 20 MINUTES FOR TARGET TEMPERATURE ******')
                self.indiclient.setCcdTemperature(ccd_temp, sync=True, timeout=1200.0)
            else:
                self.indiclient.disableCcdCooler()
                logger.warning('****** IF THE CCD COOLER WAS ENABLED, YOU MAY CONSIDER STOPPING THIS UNTIL THE SENSOR HAS WARMED ******')
                time.sleep(8.0)


            if self.config['CAMERA_INTERFACE'].startswith('libcamera_') or self.config['CAMERA_INTERFACE'].startswith('mqtt_'):
                libcamera_image_type = self.config.get('LIBCAMERA', {}).get('IMAGE_FILE_TYPE_DAY', 'jpg')
                if libcamera_image_type == 'dng':
                    self.indiclient.libcamera_bit_depth = 16
                else:
                    self.indiclient.libcamera_bit_depth = 8


            # update CCD config
            if self.config.get('INDI_CONFIG_DAY', {}):
                self.indi_config = self.config['INDI_CONFIG_DAY']
            else:
                self.indi_config = self.config['INDI_CONFIG_DEFAULTS']

            self.indiclient.configureCcdDevice(self.indi_config)


            ### DAY DARKS ###
            day_params = (float(self.gain_av[constants.GAIN_MAX_DAY]), int(self.binning_av[constants.BINNING_DAY]))
            if day_params not in night_darks_odict.keys():
                total_exposures = len(dark_exposures) * remaining_configs
                estimated_time_left = self._estimate_runtime(dark_exposures, remaining_configs, overhead_per_exposure)
                logger.info(f"Processing {total_exposures} darks, {self.count} exposures each. Estimated time left: {self._format_time(int(estimated_time_left))}")


                # day will rarely exceed 1 second (with good cameras and proper conditions)
                for index, exposure in enumerate(dark_exposures):
                    # Create a temporary list of remaining exposures
                    remaining_exposures = dark_exposures[index + 1:]

                    start = time.time()
                    self._take_exposures(exposure, self.gain_av[constants.GAIN_MAX_DAY], self.binning_av[constants.BINNING_DAY], dark_filename_t, bpm_filename_t, stacking_class)
                    elapsed_s = time.time()
                    exposure_time = elapsed_s - start

                    completed_exposures += 1

                    # Calculate the overhead for this exposure
                    overhead_per_exposure = exposure_time - exposure * float(self.count)
                    estimated_time_left = self._estimate_runtime(remaining_exposures, remaining_configs, overhead_per_exposure)
                    logger.info(f"Exposure {completed_exposures}/{total_exposures} done. Estimated time left: {self._format_time(int(estimated_time_left))}")

                remaining_configs -= 1

            else:
                remaining_configs -= 1  # daytime parameters included in night configs

        else:
            logger.warning('Daytime dark processing is disabled')

            remaining_configs -= 1  # skip daytime

            time.sleep(8.0)



        ### NIGHT
        with self.night_v.get_lock():
            self.night_v.value = 1



        if self.config['CAMERA_INTERFACE'].startswith('libcamera_') or self.config['CAMERA_INTERFACE'].startswith('mqtt_'):
            if self.config.get('LIBCAMERA', {}).get('AWB_ENABLE'):
                logger.error('NIGHT AWB IS ENABLED.  CANCELING DARKS.')
                sys.exit(1)


            libcamera_image_type = self.config.get('LIBCAMERA', {}).get('IMAGE_FILE_TYPE', 'jpg')
            if libcamera_image_type == 'dng':
                self.indiclient.libcamera_bit_depth = 16
            else:
                self.indiclient.libcamera_bit_depth = 8


        # update CCD config
        self.indi_config = self.config['INDI_CONFIG_DEFAULTS']
        self.indiclient.configureCcdDevice(self.indi_config)


        total_exposures = len(dark_exposures) * remaining_configs
        estimated_time_left = self._estimate_runtime(dark_exposures, remaining_configs, overhead_per_exposure)
        logger.info(f"Processing {total_exposures} darks, {self.count} exposures each. Estimated time left: {self._format_time(int(estimated_time_left))}")


        # take night darks with cooling enabled
        if self.config.get('CCD_COOLING'):
            ccd_temp = self.config.get('CCD_TEMP', 15.0)
            self.indiclient.enableCcdCooler()
            logger.warning('****** WAITING UP TO 20 MINUTES FOR TARGET TEMPERATURE ******')
            self.indiclient.setCcdTemperature(ccd_temp, sync=True, timeout=1200.0)
        else:
            self.indiclient.disableCcdCooler()
            logger.warning('****** IF THE CCD COOLER WAS ENABLED, YOU MAY CONSIDER STOPPING THIS UNTIL THE SENSOR HAS WARMED ******')
            time.sleep(8.0)


        ### NIGHT DARKS ###
        for gain, binning in night_darks_odict.keys():
            for index, exposure in enumerate(dark_exposures):
                # Create a temporary list of remaining exposures
                remaining_exposures = dark_exposures[index + 1:]

                start = time.time()
                self._take_exposures(exposure, gain, binning, dark_filename_t, bpm_filename_t, stacking_class)
                elapsed_s = time.time()
                exposure_time = elapsed_s - start

                completed_exposures += 1

                # Calculate the overhead for this exposure
                overhead_per_exposure = exposure_time - exposure * float(self.count)
                estimated_time_left = self._estimate_runtime(remaining_exposures, remaining_configs, overhead_per_exposure)
                logger.info(f"Exposure {completed_exposures}/{total_exposures} done. Estimated time left: {self._format_time(int(estimated_time_left))}")

            remaining_configs -= 1


    def _take_exposures(self, exposure, gain, binning, dark_filename_t, bpm_filename_t, stacking_class):
        exposure_f = float(exposure)

        tmp_fit_dir = tempfile.TemporaryDirectory()    # context manager automatically deletes files when finished
        tmp_fit_dir_p = Path(tmp_fit_dir.name)

        logger.info('Temp folder: %s', tmp_fit_dir_p)

        image_bitpix = None

        i = 1
        while i <= self.count:
            # sometimes image data is bad, take images until we reach the desired number
            logger.info(f"Starting image {i}/{self.count}.")
            start = time.time()

            self._pre_shoot_reconfigure()

            self.shoot(exposure_f, gain, binning, sync=True, timeout=180.0)  # flat 3 minute timeout

            frame_elapsed = time.time() - start
            frame_delta = frame_elapsed - exposure_f

            logger.info('Exposure received in %0.4fs (%+0.4fs)', frame_elapsed, frame_delta)

            if frame_delta < 0:
                logger.error('%0.1fs EXPOSURE RECEIVED IN %0.1fs.  POSSIBLE CAMERA PROBLEM.', exposure_f, frame_elapsed)


            try:
                hdulist = self._wait_for_image(exposure_f)
            except BadImage as e:
                logger.error('Bad Image: %s', str(e))
                continue


            hdulist[0].header['BUNIT'] = 'ADU'  # hack for ccdproc


            #logger.info('Shape: %s', str(hdulist[0].data.shape))
            if len(hdulist[0].data.shape) == 3:
                # RGB fits data
                image_height, image_width = hdulist[0].data.shape[-2:]
            else:
                # Mono data
                image_height, image_width = hdulist[0].data.shape[:2]

            image_bitpix = hdulist[0].header['BITPIX']


            with tempfile.NamedTemporaryFile(mode='w+b', dir=tmp_fit_dir_p, suffix='.fit', delete=False) as f_tmp_fit:
                hdulist.writeto(f_tmp_fit)


            #logger.info('FIT: %s', f_tmp_fit.name)

            m_avg = numpy.mean(hdulist[0].data)
            logger.info('Image average adu: %0.2f', m_avg)

            self.getCcdTemperature()
            logger.info('Camera temperature: %0.1f', self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP])

            i += 1  # increment


        # libcamera does not know the temperature until the first exposure is taken
        exp_date = datetime.now()
        date_str = exp_date.strftime('%Y%m%d_%H%M%S')
        dark_filename = dark_filename_t.format(
            self.camera_id,
            image_bitpix,
            int(exposure),
            int(self.gain_av[constants.GAIN_CURRENT]),  # filename gain as int
            int(self.binning_av[constants.BINNING_CURRENT]),
            int(self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP]),
            date_str,
        )
        bpm_filename = bpm_filename_t.format(
            self.camera_id,
            image_bitpix,
            int(exposure),
            int(self.gain_av[constants.GAIN_CURRENT]),  # filename gain as int
            int(self.binning_av[constants.BINNING_CURRENT]),
            int(self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP]),
            date_str,
        )

        full_dark_filename_p = self.darks_dir.joinpath(dark_filename)
        full_bpm_filename_p = self.darks_dir.joinpath(bpm_filename)


        s = stacking_class(self.gain_av, self.binning_av)
        s.bitmax = self.bitmax
        s.hotpixel_adu_percent = self.hotpixel_adu_percent


        # build dark before BPM
        dark_adu_avg, dark_hot_pixel_count = s.stack(tmp_fit_dir_p, full_dark_filename_p, exposure_f, image_bitpix)
        bpm_adu_avg, bpm_hot_pixel_count = s.buildBadPixelMap(tmp_fit_dir_p, full_bpm_filename_p, exposure_f, image_bitpix)


        bpm_metadata = {
            'type'       : constants.BPM_FRAME,
            'createDate' : exp_date.timestamp(),
            'bitdepth'   : image_bitpix,
            'exposure'   : exposure_f,
            'gain'       : float(self.gain_av[constants.GAIN_CURRENT]),
            'binmode'    : int(self.binning_av[constants.BINNING_CURRENT]),
            'temp'       : float(self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP]),
            'adu'        : bpm_adu_avg,
            'height'     : image_height,
            'width'      : image_width,
        }

        bpm_metadata['data'] = {
            'hot_pixels' : int(bpm_hot_pixel_count),
            'count'      : self.count,
        }


        dark_metadata = {
            'type'       : constants.DARK_FRAME,
            'createDate' : exp_date.timestamp(),
            'bitdepth'   : image_bitpix,
            'exposure'   : exposure_f,
            'gain'       : float(self.gain_av[constants.GAIN_CURRENT]),
            'binmode'    : int(self.binning_av[constants.BINNING_CURRENT]),
            'temp'       : float(self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP]),
            'adu'        : dark_adu_avg,
            'height'     : image_height,
            'width'      : image_width,
        }

        dark_metadata['data'] = {
            'count'      : self.count,
            'hot_pixels' : int(dark_hot_pixel_count),
            #'method'     : stacking_class.__name__,
            'method'     : str(s),
        }


        self._miscDb.addBadPixelMap(
            full_bpm_filename_p.relative_to(self.image_dir),
            self.camera_id,
            bpm_metadata,
        )

        self._miscDb.addDarkFrame(
            full_dark_filename_p.relative_to(self.image_dir),
            self.camera_id,
            dark_metadata,
        )

        tmp_fit_dir.cleanup()



    def flush(self):
        with app.app_context():
            self._flush()


    def _flush(self):
        try:
            flush_camera = IndiAllSkyDbCameraTable.query\
                .filter(IndiAllSkyDbCameraTable.id == self.flush_camera_id)\
                .one()
        except NoResultFound:
            logger.error('Camera ID %d not found', self.flush_camera_id)
            sys.exit(1)


        badpixelmaps = IndiAllSkyDbBadPixelMapTable.query\
            .join(IndiAllSkyDbBadPixelMapTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == flush_camera.id)

        dark_frames = IndiAllSkyDbDarkFrameTable.query\
            .join(IndiAllSkyDbDarkFrameTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == flush_camera.id)


        logger.warning('Found %d bad pixel maps to flush', badpixelmaps.count())
        logger.warning('Found %d dark frames to flush', dark_frames.count())


        if badpixelmaps.count() == 0 and dark_frames.count() == 0:
            logger.error('No dark frames found for camera "%s"', flush_camera.name)
            sys.exit(1)


        logger.warning('Flushing camera "%s" darks in 10 seconds...', flush_camera.name)
        time.sleep(10.0)


        for bpm_entry in badpixelmaps:
            filename = Path(bpm_entry.getFilesystemPath())

            if filename.exists():
                logger.warning('Removing bad pixel map: %s', filename)
                filename.unlink()

            db.session.delete(bpm_entry)


        for dark_frame_entry in dark_frames:
            filename = Path(dark_frame_entry.getFilesystemPath())

            if filename.exists():
                logger.warning('Removing dark frame: %s', filename)
                filename.unlink()

            db.session.delete(dark_frame_entry)


        db.session.commit()


    def getCcdTemperature(self):
        temp_val = self.indiclient.getCcdTemperature()


        # query external temperature if camera does not return temperature
        if temp_val < -100.0 and self.config.get('CCD_TEMP_SCRIPT'):
            try:
                ext_temp_val = self.getExternalTemperature(self.config.get('CCD_TEMP_SCRIPT'))
                temp_val = ext_temp_val
            except TemperatureException as e:
                logger.error('Exception querying external temperature: %s', str(e))


        temp_val_f = float(temp_val)

        with self.sensors_temp_av.get_lock():
            self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP] = temp_val_f


        return temp_val_f


    def getExternalTemperature(self, script_path):
        temp_script_p = Path(script_path)

        logger.info('Running external script for temperature: %s', temp_script_p)

        # need to be extra careful running in the main thread
        if not temp_script_p.exists():
            raise TemperatureException('Temperature script does not exist')

        if not temp_script_p.is_file():
            raise TemperatureException('Temperature script is not a file')

        if temp_script_p.stat().st_size == 0:
            raise TemperatureException('Temperature script is empty')

        if not os.access(str(temp_script_p), os.X_OK):
            raise TemperatureException('Temperature script is not executable')


        # generate a tempfile for the data
        f_tmp_tempjson = tempfile.NamedTemporaryFile(mode='w', delete=True, suffix='.json')
        f_tmp_tempjson.close()

        tempjson_name_p = Path(f_tmp_tempjson.name)


        cmd = [
            str(temp_script_p),
        ]


        # the file used for the json data is communicated via environment variable
        cmd_env = {
            'TEMP_JSON' : str(tempjson_name_p),
        }


        try:
            temp_process = subprocess.Popen(
                cmd,
                env=cmd_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            raise TemperatureException('Temperature script failed to execute')


        try:
            temp_process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            temp_process.kill()
            time.sleep(1.0)
            temp_process.poll()  # close out process
            raise TemperatureException('Temperature script timed out')


        if temp_process.returncode != 0:
            raise TemperatureException('Temperature script returned exited abnormally')


        try:
            with io.open(str(tempjson_name_p), 'r', encoding='utf-8') as tempjson_name_f:
                temp_data = json.load(tempjson_name_f)

            tempjson_name_p.unlink()  # remove temp file
        except PermissionError as e:
            logger.error(str(e))
            raise TemperatureException(str(e))
        except json.JSONDecodeError as e:
            logger.error('Error decoding json: %s', str(e))
            raise TemperatureException(str(e))
        except FileNotFoundError as e:
            raise TemperatureException(str(e))


        try:
            temp_float = float(temp_data['temp'])
        except ValueError:
            raise TemperatureException('Temperature script returned a non-numerical value')
        except KeyError:
            raise TemperatureException('Temperature script returned incorrect data')


        return temp_float


    def checkAvailableSpace(self):
        fs_list = psutil.disk_partitions(all=True)

        for fs in fs_list:
            if fs.mountpoint not in ('/tmp'):
                continue

            try:
                disk_usage = psutil.disk_usage(fs.mountpoint)
            except PermissionError as e:
                logger.error('PermissionError: %s', str(e))
                continue


            fs_free_mb = disk_usage.total / 1024.0 / 1024.0
            if fs_free_mb < 600:
                logger.warning('%s filesystem has less than 600MB of available space', fs.mountpoint)
                time.sleep(10)


class IndiAllSkyDarksProcessor(object):
    def __init__(self, gain_av, binning_av):
        self.gain_av = gain_av
        self.binning_av = binning_av

        self._hotpixel_adu_percent = 90

        self._bitmax = 0


    def __repr__(self):
        return NotImplementedError

    def __str__(self):
        return NotImplementedError


    @property
    def bitmax(self):
        return self._bitmax

    @bitmax.setter
    def bitmax(self, new_bitmax):
        self._bitmax = int(new_bitmax)


    @property
    def hotpixel_adu_percent(self):
        return self._hotpixel_adu_percent

    @hotpixel_adu_percent.setter
    def hotpixel_adu_percent(self, new_hotpixel_adu_percent):
        self._hotpixel_adu_percent = int(new_hotpixel_adu_percent)



    def buildBadPixelMap(self, tmp_fit_dir_p, filename_p, exposure, image_bitpix):
        from astropy.io import fits

        logger.info('Building bad pixel map for exposure %0.1fs, gain %0.2f, bin %d', exposure, self.gain_av[constants.GAIN_CURRENT], self.binning_av[constants.BINNING_CURRENT])

        if image_bitpix == 16:
            numpy_type = numpy.uint16
        elif image_bitpix == 8:
            numpy_type = numpy.uint8
        elif image_bitpix == -32:
            numpy_type = numpy.float32
        elif image_bitpix == 32:
            numpy_type = numpy.uint32
        else:
            raise Exception('Unknown bits per pixel')


        dark_data_list = list()
        hdulist = None
        for item in Path(tmp_fit_dir_p).iterdir():
            #logger.info('Found item: %s', item)
            if item.is_file() and item.suffix in ['.fit']:
                #logger.info('Found fit: %s', item)
                hdulist = fits.open(item)
                dark_data_list.append(hdulist[0].data)


        bpm = numpy.zeros(dark_data_list[0].shape, dtype=numpy_type)


        # take the max values of each pixel from each image
        for dark in dark_data_list:
            bpm = numpy.maximum(bpm, dark)


        max_val = numpy.amax(bpm)
        logger.info('Image max value: %0.1f', float(max_val))


        if self.bitmax:
            max_value = (2 ** self.bitmax) - 1
        else:
            if numpy_type in (numpy.float32, numpy.uint32):
                # assume 16bit max
                max_value = (2 ** 16) - 1
            else:
                max_value = (2 ** image_bitpix) - 1


        hot_pixel_thold = int(max_value * (self.hotpixel_adu_percent / 100.0))
        bpm[bpm < hot_pixel_thold] = 0  # filter all values less than max value

        bpm_adu_avg = numpy.mean(bpm)
        logger.info('Master BPM average adu: %0.2f', bpm_adu_avg)


        if len(bpm.shape) == 3:
            # RGB fits data
            hot_pixels = numpy.maximum.reduce([bpm[0], bpm[1], bpm[2]]) > 0
        else:
            # Mono data
            hot_pixels = bpm > 0


        hot_pixel_count = hot_pixels.sum()

        if hot_pixel_count > 50000:
            logger.warning('DETECTED MORE THAN 50000 BAD PIXELS (>%d/%d%% ADU) - MAKE SURE YOUR SENSOR IS COVERED', hot_pixel_thold, self.hotpixel_adu_percent)
        elif hot_pixel_count == 0:
            logger.warning('DETECTED 0 BAD PIXELS (>%d/%d%% ADU) - BITMAX MAY NEED TO BE REDUCED', hot_pixel_thold, self.hotpixel_adu_percent)
        else:
            logger.info('Detected %d bad pixels (>%d/%d%% ADU)', hot_pixel_count, hot_pixel_thold, self.hotpixel_adu_percent)


        hdulist[0].data = bpm

        # reuse the last fits file for the stacked data
        hdulist.writeto(filename_p)

        return bpm_adu_avg, hot_pixel_count


    def stack(self, tmp_fit_dir_p, filename_p, exposure, image_bitpix):
        raise Exception('Must be redefined in sub-class')


class IndiAllSkyDarksAverage(IndiAllSkyDarksProcessor):
    def __repr__(self):
        return 'Average Stacking'

    def __str__(self):
        return 'Average Stacking'


    def stack(self, tmp_fit_dir_p, filename_p, exposure, image_bitpix):
        from astropy.io import fits

        logger.info('Stacking dark frames for exposure %0.1fs, gain %0.2f, bin %d', exposure, self.gain_av[constants.GAIN_CURRENT], self.binning_av[constants.BINNING_CURRENT])

        if image_bitpix == 16:
            numpy_type = numpy.uint16
            cast_type = numpy.uint32
        elif image_bitpix == 8:
            numpy_type = numpy.uint8
            cast_type = numpy.uint16
        elif image_bitpix == -32:
            numpy_type = numpy.float32
            cast_type = numpy.float32
        elif image_bitpix == 32:
            numpy_type = numpy.uint32
            cast_type = numpy.float32
        else:
            raise Exception('Unknown bits per pixel')

        dark_data_list = list()
        hdulist = None
        for item in Path(tmp_fit_dir_p).iterdir():
            #logger.info('Found item: %s', item)
            if item.is_file() and item.suffix in ('.fit',):
                #logger.info('Found fit: %s', item)
                hdulist = fits.open(item)
                dark_data_list.append(hdulist[0].data.astype(cast_type))

        #logger.info('Dark images found: %d', len(dark_data_list))

        start = time.time()

        avg_data = (numpy.sum(dark_data_list, axis=0) / len(dark_data_list)).astype(numpy_type)
        #logger.info('Avg dims: %s', str(avg_data.shape))

        elapsed_s = time.time() - start
        logger.info('Exposure average stacked in %0.4f s', elapsed_s)

        dark_adu_avg = numpy.mean(avg_data)
        logger.info('Master Dark average adu: %0.2f', dark_adu_avg)


        if self.bitmax:
            max_value = (2 ** self.bitmax) - 1
        else:
            if numpy_type in (numpy.float32, numpy.uint32):
                # assume 16bit max
                max_value = (2 ** self.bitmax) - 1
            else:
                max_value = (2 ** image_bitpix) - 1


        hot_pixel_thold = int(max_value * (30 / 100))

        if len(avg_data.shape) == 3:
            # RGB fits data
            hot_pixels = numpy.maximum.reduce([avg_data[0], avg_data[1], avg_data[2]]) > hot_pixel_thold
        else:
            # Mono data
            hot_pixels = avg_data > hot_pixel_thold

        hot_pixel_count = hot_pixels.sum()

        if hot_pixel_count > 50000:
            logger.warning('DETECTED MORE THAN 50000 HOT PIXELS (>%d/%d%% ADU) - MAKE SURE YOUR SENSOR IS COVERED', hot_pixel_thold, 30)
        elif hot_pixel_count == 0:
            logger.warning('DETECTED 0 HOT PIXELS (>%d/%d%% ADU)', hot_pixel_thold, 30)
        else:
            logger.info('Detected %d hot pixels (>%d/%d%% ADU)', hot_pixel_count, hot_pixel_thold, 30)

        hdulist[0].data = avg_data

        # reuse the last fits file for the stacked data
        hdulist.writeto(filename_p)

        return dark_adu_avg, hot_pixel_count


class IndiAllSkyDarksSigmaClip(IndiAllSkyDarksProcessor):
    def __repr__(self):
        return 'Sigma Clipping'

    def __str__(self):
        return 'Sigma Clipping'


    def stack(self, tmp_fit_dir_p, filename_p, exposure, image_bitpix):
        from astropy.io import fits
        from astropy.stats import mad_std
        import ccdproc

        logger.info('Stacking dark frames for exposure %0.1fs, gain %0.2f, bin %d', exposure, self.gain_av[constants.GAIN_CURRENT], self.binning_av[constants.BINNING_CURRENT])

        if image_bitpix == 16:
            numpy_type = numpy.uint16
        elif image_bitpix == 8:
            numpy_type = numpy.uint8
        elif image_bitpix == -32:
            numpy_type = numpy.float32
        elif image_bitpix == 32:
            numpy_type = numpy.uint32
        else:
            raise Exception('Unknown bits per pixel')

        dark_images = ccdproc.ImageFileCollection(tmp_fit_dir_p)
        #logger.info('Full dark count: %d', len(dark_images.files))

        # indi_pylibcamera reports slightly lower than the expected exposure values which cause the filter to exclude them
        #dark_images_filtered = dark_images.files_filtered(exptime=exposure, include_path=True)
        #logger.info('Filtered dark count: %d', len(dark_images_filtered))

        dark_images_files = [str(tmp_fit_dir_p.joinpath(x)) for x in dark_images.files]


        start = time.time()

        try:
            combined_dark = ccdproc.combine(
                dark_images_files,
                method='average',
                sigma_clip=True,
                sigma_clip_low_thresh=5,
                sigma_clip_high_thresh=5,
                sigma_clip_func=numpy.ma.median,
                signma_clip_dev_func=mad_std,
                dtype=numpy_type,
                mem_limit=350000000,
            )
        except ValueError as e:
            logger.error('ValueError: %s', str(e))
            logger.error('Performing sigma clipping stacking on RGB data is the most common cause of this error, use "average" instead')
            sys.exit(1)

        elapsed_s = time.time() - start
        logger.info('Exposure sigma clip stacked in %0.4f s', elapsed_s)


        combined_dark.meta['combined'] = True


        dark_adu_avg = numpy.mean(combined_dark[0].data)
        logger.info('Master Dark average adu: %0.2f', dark_adu_avg)


        combined_dark.write(filename_p)


        # counting hot pixels does not work on the data before being written to the file, I have no idea why
        # re-reading file to count hot pixels
        dark_from_file = fits.open(filename_p)


        if self.bitmax:
            max_value = (2 ** self.bitmax) - 1
        else:
            if numpy_type in (numpy.float32, numpy.uint32):
                # assume 16bit max
                max_value = (2 ** 16) - 1
            else:
                max_value = (2 ** image_bitpix) - 1


        hot_pixel_thold = int(max_value * (30 / 100))

        # Mono data
        hot_pixels = dark_from_file[0].data > hot_pixel_thold
        hot_pixel_count = hot_pixels.sum()  # this is not working correctly for some reason

        if hot_pixel_count > 50000:
            logger.warning('DETECTED MORE THAN 50000 HOT PIXELS (>%d/%d%% ADU) - MAKE SURE YOUR SENSOR IS COVERED', hot_pixel_thold, 30)
        elif hot_pixel_count == 0:
            logger.warning('DETECTED 0 HOT PIXELS (>%d/%d%% ADU)', hot_pixel_thold, 30)
        else:
            logger.info('Detected %d hot pixels (>%d/%d%% ADU)', hot_pixel_count, hot_pixel_thold, 30)


        return dark_adu_avg, hot_pixel_count

