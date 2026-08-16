import os
import io
import json
import re
from pathlib import Path
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import time
import tempfile
import shutil
import psutil
import subprocess
import signal
import logging
import traceback
import uuid
#from pprint import pformat

from multiprocessing import Process
from multiprocessing import Queue
#from threading import Thread
import queue

import cv2
import numpy

from PIL import Image

from fractions import Fraction

from . import constants
from . import asi676mc

from .processing import ImageProcessor
from .panorama import panoramaSourceCircleClipped
from .miscUpload import miscUpload
from .adsb import AdsbAircraftHttpWorker

from . import exposure as exposure_module

from .flask import create_app
from .flask import db
from .flask.miscDb import miscDb

from .flask.models import TaskQueueState
from .flask.models import TaskQueueQueue
from .flask.models import IndiAllSkyDbCameraTable
from .flask.models import IndiAllSkyDbFitsImageTable
from .flask.models import IndiAllSkyDbImageTable
from .flask.models import IndiAllSkyDbTaskQueueTable

from sqlalchemy import func
#from sqlalchemy.orm.exc import NoResultFound

from .exceptions import TimeOutException
from .exceptions import BadImage



app = create_app()

logger = logging.getLogger('indi_allsky')



class ImageWorker(Process):

    sqm_history_minutes = 30
    stars_history_minutes = 30


    def __init__(
        self,
        idx,
        config,
        error_q,
        image_q,
        upload_q,
        position_av,
        exposure_av,
        gain_av,
        binning_av,
        sensors_temp_av,
        sensors_user_av,
        night_av,
        astro_av,
    ):
        super(ImageWorker, self).__init__()

        self.name = 'Image-{0:d}'.format(idx)

        self.config = config

        self.error_q = error_q
        self.image_q = image_q
        self.upload_q = upload_q

        self.position_av = position_av
        self.exposure_av = exposure_av
        self.gain_av = gain_av
        self.binning_av = binning_av

        self.sensors_temp_av = sensors_temp_av  # 0 ccd_temp
        self.sensors_user_av = sensors_user_av
        self.night_av = night_av
        self.astro_av = astro_av

        self.filename_t = 'ccd{0:d}_{1:s}.{2:s}'

        self.adsb_worker = None
        self.adsb_worker_idx = 0
        self.adsb_aircraft_q = None
        self.adsb_aircraft_list = []

        self.generate_mask_base = True

        self.sqm_value = 0

        self.image_count = 0
        self.metadata_count = 0
        self.asi676mc_diagnostic_pending = {}
        # Populated only by the optional preceding-frame setting.  Each camera
        # can retain one untouched, normal input FITS as bytes until the next
        # frame is classified; the default bad/following path uses no cache.
        self.asi676mc_diagnostic_previous = {}

        self.image_processor = ImageProcessor(
            self.config,
            self.position_av,
            self.exposure_av,
            self.gain_av,
            self.binning_av,
            self.sensors_temp_av,
            self.sensors_user_av,
            self.night_av,
            self.astro_av,
        )


        exposure_class_str = self.config.get('CCD_CONFIG', {}).get('EXPOSURE_CLASSNAME', 'exposure_basic')
        logger.warning('Exposure Class: %s', exposure_class_str)

        try:
            exposure_class = getattr(exposure_module, exposure_class_str)
        except AttributeError:
            logger.error('Unknown exposure class: %s', exposure_class_str)
            exposure_class = getattr(exposure_module, 'exposure_basic')


        self.exposure_o = exposure_class(
            self.config,
            self.exposure_av,
            self.gain_av,
            self.binning_av,
            self.night_av,
        )


        self._miscDb = miscDb(self.config)
        self._miscUpload = miscUpload(
            self.config,
            self.upload_q,
            self.night_av,
        )


        self.image_save_hook_process = None  # used for both pre- and post-hooks
        self.image_save_hook_process_start = 0
        self.pre_hook_datajson_name_p = None


        self.next_save_fits_offset = self.config.get('IMAGE_SAVE_FITS_PERIOD', 7200)
        self.next_save_fits_time = time.time() + self.next_save_fits_offset

        self._libcamera_raw = False

        if self.config.get('IMAGE_FOLDER'):
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()


        varlib_folder = self.config.get('VARLIB_FOLDER', '/var/lib/indi-allsky')
        self.varlib_folder_p = Path(varlib_folder)


        self._shutdown = False


    @property
    def libcamera_raw(self):
        return self._libcamera_raw

    @libcamera_raw.setter
    def libcamera_raw(self, new_libcamera_raw):
        self._libcamera_raw = bool(new_libcamera_raw)


    def sighup_handler_worker(self, signum, frame):
        logger.warning('Caught HUP signal')

        # set flag for program to stop processes
        self._shutdown = True


    def sigterm_handler_worker(self, signum, frame):
        logger.warning('Caught TERM signal')

        # set flag for program to stop processes
        self._shutdown = True


    def sigint_handler_worker(self, signum, frame):
        logger.warning('Caught INT signal')

        # set flag for program to stop processes
        self._shutdown = True


    def sigalarm_handler_worker(self, signum, frame):
        raise TimeOutException()



    def run(self):
        # setup signal handling after detaching from the main process
        signal.signal(signal.SIGHUP, self.sighup_handler_worker)
        signal.signal(signal.SIGTERM, self.sigterm_handler_worker)
        signal.signal(signal.SIGINT, self.sigint_handler_worker)
        signal.signal(signal.SIGALRM, self.sigalarm_handler_worker)


        ### use this as a method to log uncaught exceptions
        try:
            self.saferun()
        except Exception as e:
            tb = traceback.format_exc()
            self.error_q.put((str(e), tb))
            raise e



    def saferun(self):
        #raise Exception('Test exception handling in worker')

        while True:
            try:
                i_dict = self.image_q.get(timeout=23)  # prime number
            except queue.Empty:
                continue


            if i_dict.get('stop'):
                self._shutdown = True


            if self._shutdown:
                self.image_processor.realtimeKeogramDataSave()

                logger.warning('Goodbye')

                return


            # new context for every task, reduces the effects of caching
            with app.app_context():
                self.processImage(i_dict)


    def processImage(self, i_dict):
        import piexif

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
        #    continue


        #task.setRunning()


        #filename = Path(task.data['filename'])
        #exposure = task.data['exposure']
        #gain = task.data['gain']
        #exp_date = datetime.fromtimestamp(task.data['exp_time'])
        #exp_elapsed = task.data['exp_elapsed']
        #camera_id = task.data['camera_id']
        #filename_t = task.data.get('filename_t')
        ###

        filename_p = Path(i_dict['filename'])
        exposure = i_dict['exposure']
        gain = i_dict['gain']
        binning = i_dict['binning']
        exp_date = datetime.fromtimestamp(i_dict['exp_time'])
        exp_elapsed = i_dict['exp_elapsed']
        camera_id = i_dict['camera_id']
        detected_camera_name = i_dict.get('camera_name')
        filename_t = i_dict.get('filename_t')
        sqm_exposure = i_dict.get('sqm_exposure')


        # libcamera
        libcamera_black_level = i_dict.get('libcamera_black_level', 0)
        libcamera_awb_gains = i_dict.get('libcamera_awb_gains')
        libcamera_ccm = i_dict.get('libcamera_ccm')


        if self.config['CAMERA_INTERFACE'].startswith('libcamera_') or self.config['CAMERA_INTERFACE'].startswith('mqtt_'):
            if filename_p.suffix == '.dng':
                self.libcamera_raw = True
                self.image_processor.libcamera_raw = True
            else:
                self.libcamera_raw = False
                self.image_processor.libcamera_raw = False


        if filename_t:
            self.filename_t = filename_t


        if not filename_p.exists():
            logger.error('Frame not found: %s', filename_p)
            #task.setFailed('Frame not found: {0:s}'.format(str(filename_p)))
            return


        image_size = filename_p.stat().st_size
        if image_size == 0:
            logger.error('Frame is empty: %s', filename_p)
            filename_p.unlink()
            return

        #logger.info('Image size: %0.2fMB', image_size / 1024 / 1024)


        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        ### Special function: image is for SQM calculations only
        if sqm_exposure:
            self.process_sqm_exposure(
                filename_p,
                exposure,
                gain,
                binning,
                exp_date,
                exp_elapsed,
                camera,
                libcamera_black_level,
                detected_camera_name=detected_camera_name,
            )
            return


        processing_start = time.time()


        ### simulate performance degradation
        #time.sleep(30)


        ### start fetching ADSB info
        if self.config.get('ADSB', {}).get('ENABLE'):
            self.adsb_aircraft_q = Queue()
            self.adsb_worker_idx += 1
            self.adsb_worker = AdsbAircraftHttpWorker(
                self.adsb_worker_idx,
                self.config,
                self.adsb_aircraft_q,
                self.position_av,
            )
            self.adsb_worker.start()


        now = datetime.now()
        self.image_processor.update_astrometric_data(now)


        try:
            i_ref = self.image_processor.add(
                filename_p,
                exposure,
                gain,
                binning,
                exp_date,
                exp_elapsed,
                camera,
                detected_camera_name=detected_camera_name,
            )
        except BadImage as e:
            logger.error('Bad Image: %s', str(e))
            filename_p.unlink()
            #task.setFailed('Bad Image: {0:s}'.format(str(filename_p)))
            return


        # Purple-frame handling deliberately precedes both pre-dark and
        # post-dark standard FITS saving. In active repair mode those outputs
        # therefore contain the restored mosaic; diagnostic FITS below retain
        # the untouched camera input when calibration evidence is requested.
        self.image_processor.correct_asi676mc_frame(i_ref)
        try:
            self.capture_asi676mc_diagnostic_fits(filename_p, i_ref, camera)
        except Exception:
            logger.exception(
                'Unexpected error while capturing ASI676MC diagnostic FITS'
            )


        filename_p.unlink()  # original file is no longer needed


        self.image_count += 1


        #############################################################################################
        ### Image data at this stage may be uint16 (grayscale or BGR) or uint8 (grayscale or BGR) ###
        #############################################################################################


        self.start_image_save_pre_hook(exposure, gain, binning)


        if self.config.get('IMAGE_SAVE_FITS'):
            if self.config.get('IMAGE_SAVE_FITS_PRE_DARK'):
                logger.warning('Saving FITS without dark frame calibration')
                self.write_fit(i_ref, camera)


        # use original value if not defined
        if i_ref.libcamera_black_level:
            libcamera_black_level = i_ref.libcamera_black_level


        self.image_processor.calibrate(libcamera_black_level=libcamera_black_level)


        self.image_processor.fix_holes_early()


        if self.config.get('IMAGE_SAVE_FITS'):
            if not self.config.get('IMAGE_SAVE_FITS_PRE_DARK'):
                self.write_fit(i_ref, camera)


        self.image_processor.calculateJankySqm()


        self.image_processor.debayer()  # populates self.opencv_data


        self.image_processor.stack()  # populates self.image


        image_height, image_width = self.image_processor.image.shape[:2]
        logger.info('Image: %d x %d', image_width, image_height)


        ### IMAGE IS CALIBRATED ###


        ### EXIF tags ###
        exp_date_utc = exp_date.replace(tzinfo=timezone.utc)

        # Python 3.6, 3.7 does not support as_integer_ratio()
        focal_length_frac = Fraction(camera.lensFocalLength).limit_denominator()
        focal_length = (focal_length_frac.numerator, focal_length_frac.denominator)

        f_number_frac = Fraction(camera.lensFocalRatio).limit_denominator()
        f_number = (f_number_frac.numerator, f_number_frac.denominator)

        exposure_time_frac = Fraction(exposure).limit_denominator(max_denominator=31250)
        exposure_time = (exposure_time_frac.numerator, exposure_time_frac.denominator)

        zeroth_ifd = {
            piexif.ImageIFD.Model            : camera.name,
            piexif.ImageIFD.Software         : 'indi-allsky',
            piexif.ImageIFD.ExposureTime     : exposure_time,
        }
        exif_ifd = {
            piexif.ExifIFD.DateTimeOriginal  : exp_date_utc.strftime('%Y:%m:%d %H:%M:%S'),
            piexif.ExifIFD.LensModel         : camera.lensName,
            piexif.ExifIFD.LensSpecification : (focal_length, focal_length, f_number, f_number),
            piexif.ExifIFD.FocalLength       : focal_length,
            piexif.ExifIFD.FNumber           : f_number,
            #piexif.ExifIFD.ApertureValue  # this is not the Aperture size
        }


        if self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP] > -150:
            # Add temperature data
            temperature_frac = Fraction(self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP]).limit_denominator()
            exif_ifd[piexif.ExifIFD.Temperature] = (temperature_frac.numerator, temperature_frac.denominator)


        jpeg_exif_dict = {
            '0th'   : zeroth_ifd,
            'Exif'  : exif_ifd,
        }


        if not self.config.get('IMAGE_EXIF_PRIVACY'):
            if camera.owner:
                zeroth_ifd[piexif.ImageIFD.Copyright] = camera.owner


            if self.config.get('PRIVACY_MODE'):
                long_deg, long_min, long_sec = self.decdeg2dms(float(round(camera.longitude)))
                lat_deg, lat_min, lat_sec = self.decdeg2dms(float(round(camera.latitude)))
            else:
                long_deg, long_min, long_sec = self.decdeg2dms(camera.longitude)
                lat_deg, lat_min, lat_sec = self.decdeg2dms(camera.latitude)


            if long_deg < 0:
                long_ref = 'W'
            else:
                long_ref = 'E'

            if lat_deg < 0:
                lat_ref = 'S'
            else:
                lat_ref = 'N'

            gps_datestamp = exp_date_utc.strftime('%Y:%m:%d')
            gps_hour   = int(exp_date_utc.strftime('%H'))
            gps_minute = int(exp_date_utc.strftime('%M'))
            gps_second = int(exp_date_utc.strftime('%S'))

            gps_ifd = {
                piexif.GPSIFD.GPSVersionID       : (2, 2, 0, 0),
                piexif.GPSIFD.GPSDateStamp       : gps_datestamp,
                piexif.GPSIFD.GPSTimeStamp       : ((gps_hour, 1), (gps_minute, 1), (gps_second, 1)),
                piexif.GPSIFD.GPSLongitudeRef    : long_ref,
                piexif.GPSIFD.GPSLongitude       : ((int(abs(long_deg)), 1), (int(long_min), 1), (0, 1)),  # no seconds
                piexif.GPSIFD.GPSLatitudeRef     : lat_ref,
                piexif.GPSIFD.GPSLatitude        : ((int(abs(lat_deg)), 1), (int(lat_min), 1), (0, 1)),  # no seconds
                #piexif.GPSIFD.GPSAltitudeRef     : 0,  # 0 = above sea level, 1 = below
                #piexif.GPSIFD.GPSAltitude        : (0, 1),
            }

            jpeg_exif_dict['GPS'] = gps_ifd


        jpeg_exif = piexif.dump(jpeg_exif_dict)


        # only perform this processing if libcamera is set to raw mode
        if self.libcamera_raw:
            # These values come from libcamera
            if libcamera_awb_gains:
                logger.info('Overriding Red balance: %f', libcamera_awb_gains[0])
                logger.info('Overriding Blue balance: %f', libcamera_awb_gains[1])
                self.config['WBR_FACTOR'] = float(libcamera_awb_gains[0])
                self.config['WBB_FACTOR'] = float(libcamera_awb_gains[1])


            # Not quite working
            if libcamera_ccm:
                self.image_processor.apply_color_correction_matrix(libcamera_ccm)


        if self.config.get('IMAGE_EXPORT_RAW'):
            self.export_raw_image(i_ref, camera, jpeg_exif=jpeg_exif)


        # Calculate ADU before stretch
        adu = self.image_processor.calculate_8bit_adu()
        # adu value may be updated below


        self.image_processor.denoise()

        self.image_processor.stretch()


        if self.config.get('CONTRAST_ENHANCE_16BIT'):
            if not self.night_av[constants.NIGHT_NIGHT] and self.config['DAYTIME_CONTRAST_ENHANCE']:
                # Contrast enhancement during the day
                self.image_processor.contrast_clahe_16bit()
            elif self.night_av[constants.NIGHT_NIGHT] and self.config['NIGHT_CONTRAST_ENHANCE']:
                # Contrast enhancement during night
                self.image_processor.contrast_clahe_16bit()


        self.image_processor.convert_16bit_to_8bit()

        #################################################################
        ### Image data at this stage will be uint8 (grayscale or BGR) ###
        #################################################################


        #with io.open('/tmp/indi_allsky_numpy.npy', 'w+b') as f_numpy:
        #    numpy.save(f_numpy, self.image_processor.image)
        #logger.info('Wrote Numpy data: /tmp/indi_allsky_numpy.npy')


        # A retained purple/failed frame is diagnostic evidence, not a valid
        # brightness sample. Do not let it alter exposure history or the next
        # capture settings.
        repair_result = i_ref.asi676mc_repair_result
        exclude_from_exposure = (
            asi676mc.excluded_from_downstream_measurements(repair_result)
        )
        if exclude_from_exposure:
            exposure_history = list(
                getattr(self.exposure_o, 'hist_adu', ())
            )
            adu_average = (
                sum(exposure_history) / len(exposure_history)
                if exposure_history
                else 0.0
            )
            logger.warning(
                'Ignoring excluded ASI676MC frame for exposure control'
            )
        else:
            adu, adu_average = self.exposure_o.compare_exposure(
                adu,
                exposure,
                gain,
            )


        # generate a new mask base once the target ADU is found
        # this should only only fire once per restart
        if (
            self.generate_mask_base
            and self.exposure_o.target_adu_found
            and not exclude_from_exposure
        ):
            self.generate_mask_base = False
            self.write_mask_base_img(self.image_processor.image)


        # line detection
        if self.night_av[constants.NIGHT_NIGHT] and self.config.get('DETECT_METEORS'):
            self.image_processor.detectLines()


        # star detection
        if self.night_av[constants.NIGHT_NIGHT] and self.config.get('DETECT_STARS', True):
            self.image_processor.detectStars()


        # additional draw code
        if self.config.get('DETECT_DRAW'):
            self.image_processor.drawDetections()


        # rotation
        self.image_processor.rotate_90()
        self.image_processor.rotate_angle()


        # verticle flip
        self.image_processor.flip_v()

        # horizontal flip
        self.image_processor.flip_h()


        # crop
        self.image_processor.crop_image()


        # green removal
        self.image_processor.scnr()


        # white balance
        self.image_processor.white_balance_mtf()
        self.image_processor.white_balance_manual_bgr()
        self.image_processor.white_balance_auto_bgr()


        # saturation
        self.image_processor.saturation_adjust()


        # gamma correction
        self.image_processor.apply_gamma_correction()


        # sharpening (unsharp mask)
        self.image_processor.sharpen()


        if not self.config.get('CONTRAST_ENHANCE_16BIT'):
            if not self.night_av[constants.NIGHT_NIGHT] and self.config['DAYTIME_CONTRAST_ENHANCE']:
                # Contrast enhancement during the day
                self.image_processor.contrast_clahe()
            elif self.night_av[constants.NIGHT_NIGHT] and self.config['NIGHT_CONTRAST_ENHANCE']:
                # Contrast enhancement during night
                self.image_processor.contrast_clahe()


        self.image_processor.colorize()

        ##################################################
        ### Image data at this stage will be uint8 BGR ###
        ##################################################


        longterm_keogram_pixels = self.save_longterm_keogram_data(exp_date, camera_id)


        self.image_processor.colormap()


        self.image_processor.apply_image_circle_mask(i_ref.binning)


        self.image_processor.realtimeKeogramUpdate()


        if self.config.get('FISH2PANO', {}).get('ENABLE'):
            if not self.image_count % self.config.get('FISH2PANO', {}).get('MODULUS', 2):
                pano_data = self.image_processor.fish2pano(i_ref.binning)


                if self.config.get('FISH2PANO', {}).get('ENABLE_CARDINAL_DIRS'):
                    pano_data = self.image_processor.fish2pano_cardinal_dirs_label(pano_data)


                self.write_panorama_img(pano_data, i_ref, camera, jpeg_exif=jpeg_exif)


        if self.config.get('CIRCULAR_DISPLAY', {}).get('ENABLE'):
            if not self.config.get('FOCUS_MODE', False):
                circular_display_image = self.image_processor.circular_display(i_ref.binning)
                self.write_circular_display_img(circular_display_image, jpeg_exif=jpeg_exif)


        self.image_processor.apply_logo_overlay(i_ref.binning)


        self.image_processor.scale_image()


        self.image_processor.add_border()

        self.image_processor.moon_overlay()

        self.image_processor.lightgraph_overlay()

        self.image_processor.image_overlay()

        self.image_processor.orb_image()

        self.image_processor.cardinal_dirs_label()


        # get ADS-B data
        if self.adsb_worker:
            try:
                self.adsb_aircraft_list = self.adsb_aircraft_q.get(timeout=5.0)
            except queue.Empty:
                self.adsb_aircraft_list = []

            self.adsb_aircraft_q.close()
            self.adsb_aircraft_q = None

            self.adsb_worker.join()
            self.adsb_worker = None


        # wait on the pre-hook to finish
        custom_hook_data = self.wait_image_save_pre_hook()


        self.image_processor.label_image(adsb_aircraft_list=self.adsb_aircraft_list, custom_hook_data=custom_hook_data)


        processing_elapsed_s = time.time() - processing_start
        logger.info('Image processed in %0.4f s', processing_elapsed_s)


        # need this after resizing and scaling
        final_height, final_width = self.image_processor.image.shape[:2]


        #task.setSuccess('Image processed')

        self.write_status_json(i_ref, adu, adu_average)  # write json status file


        if not isinstance(self.image_processor.realtime_keogram_data, type(None)):
            # keogram might be empty on dimension mismatch
            self.write_realtime_keogram(self.image_processor.realtime_keogram_trimmed, camera)


        latest_file, new_filename = self.write_img(self.image_processor.image, i_ref, camera, jpeg_exif=jpeg_exif)

        if new_filename:
            self.start_image_save_post_hook(new_filename, exposure, gain, binning)

            image_metadata = {
                'type'            : constants.IMAGE,
                'createDate'      : int(exp_date.timestamp()),
                'dayDate'         : i_ref.day_date.strftime('%Y%m%d'),
                'utc_offset'      : exp_date.astimezone().utcoffset().total_seconds(),
                'exposure'        : i_ref.exposure,
                'exp_elapsed'     : exp_elapsed,
                'gain'            : i_ref.gain,
                'binmode'         : i_ref.binning,
                'temp'            : self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP],
                'adu'             : adu,
                'stable'          : self.exposure_o.target_adu_found,
                'moonmode'        : bool(self.night_av[constants.NIGHT_MOONMODE]),
                'moonphase'       : self.image_processor.astrometric_data['moon_phase'],
                'night'           : bool(self.night_av[constants.NIGHT_NIGHT]),
                'adu_roi'         : self.config['ADU_ROI'],
                'calibrated'      : i_ref.calibrated,
                'sqm'             : i_ref.sqm_value,
                'stars'           : len(i_ref.stars),
                'detections'      : len(i_ref.lines),
                'process_elapsed' : processing_elapsed_s,
                'kpindex'         : i_ref.kpindex,
                'ovation_max'     : i_ref.ovation_max,
                'smoke_rating'    : i_ref.smoke_rating,
                'fileSize'        : new_filename.stat().st_size,
                'height'          : final_height,
                'width'           : final_width,
                'keogram_pixels'  : longterm_keogram_pixels,
                'camera_uuid'     : i_ref.camera_uuid,
            }


            image_add_data = {
                'uptime'            : i_ref.uptime,
                'kpindex'           : i_ref.kpindex,
                'ovation_max'       : i_ref.ovation_max,
                'aurora_mag_bt'     : i_ref.aurora_mag_bt,
                'aurora_mag_gsm_bz' : i_ref.aurora_mag_gsm_bz,
                'aurora_plasma_density' : i_ref.aurora_plasma_density,
                'aurora_plasma_speed'   : i_ref.aurora_plasma_speed,
                'aurora_plasma_temp'    : i_ref.aurora_plasma_temp,
                'aurora_n_hemi_gw'  : i_ref.aurora_n_hemi_gw,
                'aurora_s_hemi_gw'  : i_ref.aurora_s_hemi_gw,
                'camera_sqm_raw_mag' : self.image_processor.camera_sqm_raw_mag,
            }

            asi676mc_repair_result = i_ref.asi676mc_repair_result
            if (
                asi676mc_repair_result
                and asi676mc_repair_result['status'] in (
                    'excluded',
                    'validation_failed',
                )
            ):
                # The processed JPEG has already been written.  Mark its new
                # database row so existing timelapse queries skip it.
                image_metadata['exclude'] = True

            if (
                asi676mc_repair_result
                and asi676mc_repair_result.get('diagnostic_fits')
            ):
                image_add_data['asi676mc_diagnostic_fits'] = dict(
                    asi676mc_repair_result['diagnostic_fits']
                )

            if (
                asi676mc_repair_result
                and asi676mc_repair_result['status'] in (
                    'repaired',
                    'validation_failed',
                    'excluded',
                )
            ):
                image_add_data['asi676mc_repair_status'] = asi676mc_repair_result['status']
                image_add_data['asi676mc_repair'] = dict(asi676mc_repair_result)


            for i in range(60):
                v = self.sensors_temp_av[i]

                if self.config.get('TEMP_DISPLAY') == 'f':
                    v_temp = (v * 9.0 / 5.0) + 32
                elif self.config.get('TEMP_DISPLAY') == 'k':
                    v_temp = v + 273.15
                else:
                    v_temp = v

                image_add_data['sensor_temp_{0:d}'.format(i)] = v_temp


            for i in range(60):
                image_add_data['sensor_user_{0:d}'.format(i)] = self.sensors_user_av[i]

            for i in range(100, 110):
                image_add_data['sensor_user_{0:d}'.format(i)] = self.sensors_user_av[i]


            if self.adsb_aircraft_list:
                image_add_data['aircraft'] = list()

                for aircraft in self.adsb_aircraft_list:
                    image_add_data['aircraft'].append(aircraft)


            image_metadata['data'] = image_add_data


            image_entry = self._miscDb.addImage(
                new_filename.relative_to(self.image_dir),
                camera_id,
                image_metadata,
            )

            # The raw previous-frame cache is filled before the source FITS is
            # deleted, but its rendered image row does not exist until here.
            # Remember the row so a later purple frame can expose the saved
            # preceding FITS from this image's own download strip as well.
            self._set_asi676mc_cached_image_id(i_ref, image_entry.id)


            image_thumbnail_metadata = {
                'type'       : constants.THUMBNAIL,
                'origin'     : constants.IMAGE,
                'createDate' : int(exp_date.timestamp()),
                'dayDate'    : i_ref.day_date.strftime('%Y%m%d'),
                'utc_offset' : exp_date.astimezone().utcoffset().total_seconds(),
                'night'      : bool(self.night_av[constants.NIGHT_NIGHT]),
                'camera_uuid': camera.uuid,
            }

            image_thumbnail_entry = self._miscDb.addThumbnail(
                image_entry,
                image_metadata,
                camera.id,
                image_thumbnail_metadata,
                numpy_data=self.image_processor.image,
            )


            # add fileSize to metadata
            image_thumbnail_metadata['fileSize'] = image_thumbnail_entry.fileSize


            # wait on the post-hook to finish
            self.wait_image_save_post_hook()
        else:
            # images not being saved
            image_entry = None
            image_metadata = {}
            image_thumbnail_entry = None
            image_thumbnail_metadata = {}


        if latest_file:
            # build mqtt data
            mq_topic_latest = 'latest'

            mqtt_data = {
                'exp_date' : exp_date.strftime('%Y-%m-%d %H:%M:%S'),
                'exposure' : round(i_ref.exposure, 6),
                'gain'     : round(i_ref.gain, 3),
                'bin'      : i_ref.binning,
                'temp'     : round(self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP], 1),
                'sunalt'   : round(self.image_processor.astrometric_data['sun_alt'], 1),
                'moonalt'  : round(self.image_processor.astrometric_data['moon_alt'], 1),
                'moonphase': round(self.image_processor.astrometric_data['moon_phase'], 1),
                'mooncycle': round(self.image_processor.astrometric_data['moon_cycle'], 1),
                'moonmode' : bool(self.night_av[constants.NIGHT_MOONMODE]),
                'night'    : bool(self.night_av[constants.NIGHT_NIGHT]),
                'sqm'      : round(i_ref.sqm_value, 1),
                'stars'    : len(i_ref.stars),
                'detections' : len(i_ref.lines),
                'latitude' : round(self.position_av[constants.POSITION_LATITUDE], 3),
                'longitude': round(self.position_av[constants.POSITION_LONGITUDE], 3),
                'elevation': int(self.position_av[constants.POSITION_ELEVATION]),
                'smoke_rating'  : constants.SMOKE_RATING_MAP_STR[i_ref.smoke_rating],
                'aircraft'      : len(self.adsb_aircraft_list),
                'sidereal_time' : self.image_processor.astrometric_data['sidereal_time'],
                'kpindex'       : round(i_ref.kpindex, 2),
                'ovation_max'   : int(i_ref.ovation_max),
                'aurora_mag_bt'     : round(i_ref.aurora_mag_bt, 2),
                'aurora_mag_gsm_bz' : round(i_ref.aurora_mag_gsm_bz, 2),
                'aurora_plasma_density' : round(i_ref.aurora_plasma_density, 2),
                'aurora_plasma_speed'   : round(i_ref.aurora_plasma_speed, 2),
                'aurora_plasma_temp'    : i_ref.aurora_plasma_temp,
                'aurora_n_hemi_gw'  : i_ref.aurora_n_hemi_gw,
                'aurora_s_hemi_gw'  : i_ref.aurora_s_hemi_gw,
                'camera_sqm_raw_mag' : self.image_processor.camera_sqm_raw_mag,
            }


            # publish cpu info
            cpu_info = psutil.cpu_times_percent()
            mqtt_data['cpu/user'] = round(cpu_info.user, 1)
            mqtt_data['cpu/system'] = round(cpu_info.system, 1)
            mqtt_data['cpu/nice'] = round(cpu_info.nice, 1)
            mqtt_data['cpu/iowait'] = round(cpu_info.iowait, 1)  # io wait is not true cpu usage, not including in total
            mqtt_data['cpu/total'] = round(cpu_info.user + cpu_info.system + cpu_info.nice, 1)


            # publish memory info
            memory_info = psutil.virtual_memory()
            memory_total = memory_info.total
            memory_free = memory_info.free

            mqtt_data['memory/user'] = round((memory_info.used / memory_total) * 100.0, 1)
            mqtt_data['memory/cached'] = round((memory_info.cached / memory_total) * 100.0, 1)
            mqtt_data['memory/total'] = round(100 - ((memory_free * 100) / memory_total), 1)


            # publish disk info
            fs_list = psutil.disk_partitions(all=False)

            for fs in fs_list:

                skip = False
                for p in ('/snap',):
                    if fs.mountpoint.startswith(p + '/'):
                        skip = True
                        break
                    elif fs.mountpoint == p:
                        skip = True
                        break

                if skip:
                    continue


                try:
                    disk_usage = psutil.disk_usage(fs.mountpoint)
                except PermissionError as e:
                    logger.error('PermissionError: %s', str(e))
                    continue

                if fs.mountpoint == '/':
                    mqtt_data['disk/root'] = round(disk_usage.percent, 1)  # hopefully there is not a /root filesystem
                    continue
                else:
                    # slash is included with filesystem name
                    mqtt_data['disk{0:s}'.format(fs.mountpoint)] = round(disk_usage.percent, 1)


            # publish temperature info
            temp_info = psutil.sensors_temperatures()

            system_temp_count = 0  # need index for shared sensor values
            for t_key in sorted(temp_info):  # always return the keys in the same order
                for i, t in enumerate(temp_info[t_key]):
                    if system_temp_count > 49:
                        # limit to 50
                        continue

                    temp_c = float(t.current)

                    if self.config.get('TEMP_DISPLAY') == 'f':
                        current_temp = (temp_c * 9.0 / 5.0) + 32
                    elif self.config.get('TEMP_DISPLAY') == 'k':
                        current_temp = temp_c + 273.15
                    else:
                        current_temp = temp_c


                    if not t.label:
                        # use index for label name
                        label = str(i)
                    else:
                        label = t.label

                    topic = 'temp/{0:s}/{1:s}'.format(t_key, label)

                    # no spaces, etc in topics
                    topic_sub = re.sub(r'[#+\$\*\>\.\ ]', '_', topic)

                    mqtt_data[topic_sub] = round(current_temp, 1)


                    # update share array
                    # temperatures always Celsius here
                    with self.sensors_temp_av.get_lock():
                        # index 0 is always ccd_temp
                        self.sensors_temp_av[10 + system_temp_count] = temp_c

                    system_temp_count += 1


            # system temp sensors
            for i in range(60):
                v = self.sensors_temp_av[i]

                if self.config.get('TEMP_DISPLAY') == 'f':
                    v_temp = (v * 9.0 / 5.0) + 32
                elif self.config.get('TEMP_DISPLAY') == 'k':
                    v_temp = v + 273.15
                else:
                    v_temp = v


                sensor_topic = 'sensor_temp_{0:d}'.format(i)
                mqtt_data[sensor_topic] = round(v_temp, 1)


            # user sensors
            for i in range(60):
                sensor_topic = 'sensor_user_{0:d}'.format(i)
                mqtt_data[sensor_topic] = round(self.sensors_user_av[i], 3)

            for i in range(100, 110):
                sensor_topic = 'sensor_user_{0:d}'.format(i)
                mqtt_data[sensor_topic] = round(self.sensors_user_av[i], 3)


            if new_filename:
                upload_filename = new_filename
            else:
                upload_filename = latest_file


            ### upload thumbnail first
            if image_thumbnail_entry:
                self._miscUpload.syncapi_thumbnail(image_thumbnail_entry, image_thumbnail_metadata)  # syncapi before s3
                self._miscUpload.s3_upload_thumbnail(image_thumbnail_entry, image_thumbnail_metadata)


            self._miscUpload.syncapi_image(image_entry, image_metadata)  # syncapi before s3
            self._miscUpload.s3_upload_image(image_entry, image_metadata)
            self._miscUpload.mqtt_publish_image(upload_filename, mq_topic_latest, mqtt_data)
            self._miscUpload.upload_image(image_entry)

            self.upload_metadata(i_ref, adu, adu_average)


    def decdeg2dms(self, dd):
        is_positive = dd >= 0
        dd = abs(dd)
        minutes, seconds = divmod(dd * 3600, 60)
        degrees, minutes = divmod(minutes, 60)
        degrees = degrees if is_positive else -degrees
        return degrees, minutes, seconds


    def upload_metadata(self, i_ref, adu, adu_average):
        ### upload metadata
        if not self.config.get('FILETRANSFER', {}).get('UPLOAD_METADATA'):
            #logger.warning('Metadata uploading disabled')
            return

        if not self.config.get('FILETRANSFER', {}).get('UPLOAD_IMAGE'):
            logger.warning('Metadata uploading disabled when image upload is disabled')
            return


        self.metadata_count += 1

        metadata_remain = self.metadata_count % int(self.config['FILETRANSFER']['UPLOAD_IMAGE'])
        if metadata_remain != 0:
            #next_metadata = int(self.config['FILETRANSFER']['UPLOAD_IMAGE']) - image_metadata
            #logger.info('Next metadata upload in %d images (%d s)', next_metadata, int(self.config['EXPOSURE_PERIOD'] * next_metadata))
            return


        metadata = {
            'type'                : constants.METADATA,
            'device'              : i_ref.camera_name,
            'night'               : self.night_av[constants.NIGHT_NIGHT],
            'temp'                : self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP],
            'gain'                : i_ref.gain,
            'exposure'            : i_ref.exposure,
            'stable_exposure'     : int(self.exposure_o.target_adu_found),
            'target_adu'          : i_ref.target_adu,
            'current_adu_target'  : self.exposure_o.current_adu_target,
            'current_adu'         : adu,
            'adu_average'         : adu_average,
            'sqm'                 : i_ref.sqm_value,
            'stars'               : len(i_ref.stars),
            'time'                : i_ref.exp_date.strftime('%s'),
            'tz'                  : str(i_ref.exp_date.astimezone().tzinfo),
            'utc_offset'          : i_ref.exp_date.astimezone().utcoffset().total_seconds(),
            'sqm_data'            : self.getSqmData(i_ref.camera_id),
            'stars_data'          : self.getStarsData(i_ref.camera_id),
            'latitude'            : self.position_av[constants.POSITION_LATITUDE],
            'longitude'           : self.position_av[constants.POSITION_LONGITUDE],
            'elevation'           : int(self.position_av[constants.POSITION_ELEVATION]),
            'sidereal_time'       : self.image_processor.astrometric_data['sidereal_time'],
            'kpindex'             : i_ref.kpindex,
            'aurora_mag_bt'       : i_ref.aurora_mag_bt,
            'aurora_mag_gsm_bz'   : i_ref.aurora_mag_gsm_bz,
            'aurora_plasma_density' : i_ref.aurora_plasma_density,
            'aurora_plasma_speed'   : i_ref.aurora_plasma_speed,
            'aurora_plasma_temp'    : i_ref.aurora_plasma_temp,
            'aurora_n_hemi_gw'    : i_ref.aurora_n_hemi_gw,
            'aurora_s_hemi_gw'    : i_ref.aurora_s_hemi_gw,
            'ovation_max'         : i_ref.ovation_max,
            'smoke_rating'        : constants.SMOKE_RATING_MAP_STR[i_ref.smoke_rating],
            'aircraft'            : len(self.adsb_aircraft_list),
            'camera_sqm_raw_mag'  : self.image_processor.camera_sqm_raw_mag,
        }


        # system temp sensors
        for i in range(60):
            v = self.sensors_temp_av[i]

            if self.config.get('TEMP_DISPLAY') == 'f':
                v_temp = (v * 9.0 / 5.0) + 32
            elif self.config.get('TEMP_DISPLAY') == 'k':
                v_temp = v + 273.15
            else:
                v_temp = v


            sensor_topic = 'sensor_temp_{0:d}'.format(i)
            metadata[sensor_topic] = v_temp


        # user sensors
        for i in range(60):
            sensor_topic = 'sensor_user_{0:d}'.format(i)
            metadata[sensor_topic] = self.sensors_user_av[i]

        for i in range(100, 110):
            sensor_topic = 'sensor_user_{0:d}'.format(i)
            metadata[sensor_topic] = self.sensors_user_av[i]


        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as f_tmp_metadata:
            json.dump(
                metadata,
                f_tmp_metadata,
                indent=4,
                ensure_ascii=False,
            )

            tmp_metadata_name_p = Path(f_tmp_metadata.name)


        tmp_metadata_name_p.chmod(0o644)


        file_data_dict = {
            'timestamp'    : i_ref.exp_date,
            'ts'           : i_ref.exp_date,  # shortcut
            'day_date'     : i_ref.day_date,
            'ext'          : 'json',
            'camera_uuid'  : i_ref.camera_uuid,
            'camera_id'    : i_ref.camera_id,
        }


        if self.night_av[constants.NIGHT_NIGHT]:
            file_data_dict['timeofday'] = 'night'
            file_data_dict['tod'] = 'night'
        else:
            file_data_dict['timeofday'] = 'day'
            file_data_dict['tod'] = 'day'


        # Replace parameters in names
        remote_dir = self.config['FILETRANSFER']['REMOTE_METADATA_FOLDER'].format(**file_data_dict)
        remote_file = self.config['FILETRANSFER']['REMOTE_METADATA_NAME'].format(**file_data_dict)

        remote_file_p = Path(remote_dir).joinpath(remote_file)

        # tell worker to upload file
        jobdata = {
            'action'       : constants.TRANSFER_UPLOAD,
            'local_file'   : str(tmp_metadata_name_p),
            'remote_file'  : str(remote_file_p),
            'remove_local' : True,
        }

        upload_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(upload_task)
        db.session.commit()

        self.upload_q.put({'task_id' : upload_task.id})


    def getSqmData(self, camera_id):
        now_minus_minutes = datetime.now() - timedelta(minutes=self.sqm_history_minutes)

        sqm_images = IndiAllSkyDbImageTable.query\
            .add_columns(
                func.max(IndiAllSkyDbImageTable.sqm).label('image_max_sqm'),
                func.min(IndiAllSkyDbImageTable.sqm).label('image_min_sqm'),
                func.avg(IndiAllSkyDbImageTable.sqm).label('image_avg_sqm'),
            )\
            .join(IndiAllSkyDbCameraTable)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .filter(IndiAllSkyDbImageTable.createDate > now_minus_minutes)\
            .first()


        sqm_data = {
            'max' : sqm_images.image_max_sqm,
            'min' : sqm_images.image_min_sqm,
            'avg' : sqm_images.image_avg_sqm,
        }

        return sqm_data


    def getStarsData(self, camera_id):
        now_minus_minutes = datetime.now() - timedelta(minutes=self.stars_history_minutes)

        stars_images = IndiAllSkyDbImageTable.query\
            .add_columns(
                func.max(IndiAllSkyDbImageTable.stars).label('image_max_stars'),
                func.min(IndiAllSkyDbImageTable.stars).label('image_min_stars'),
                func.avg(IndiAllSkyDbImageTable.stars).label('image_avg_stars'),
            )\
            .join(IndiAllSkyDbCameraTable)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .filter(IndiAllSkyDbImageTable.createDate > now_minus_minutes)\
            .first()


        stars_data = {
            'max' : stars_images.image_max_stars,
            'min' : stars_images.image_min_stars,
            'avg' : stars_images.image_avg_stars,
        }

        return stars_data


    def capture_asi676mc_diagnostic_fits(self, source_filename_p, i_ref, camera):
        """Save bad/following evidence and optionally a cached preceding FITS.

        The default path copies only a detected purple frame and the next
        compatible ingested frame, with no persistent RAW cache. An
        incompatible immediate successor breaks the evidence group rather than
        saving a reference the calibration engine would reject.
        ``SAVE_PRECEDING_FITS`` opts into one in-memory FITS per camera. A
        cached normal frame is written only when the immediately following
        compatible frame is purple, then the cache advances or is discarded.
        If that normal frame was already saved as a previous group's following
        frame, its database FITS is reused without retaining duplicate bytes.
        """
        repair_config = self.config.get('IMAGE_ASI676MC_REPAIR', {})
        camera_id = i_ref.camera_id

        if (
            not repair_config.get('ENABLE', False)
            or not repair_config.get('SAVE_DIAGNOSTIC_FITS', False)
            or not asi676mc.camera_name_matches(
                i_ref.detected_camera_name
            )
        ):
            self.asi676mc_diagnostic_pending.pop(camera_id, None)
            self.asi676mc_diagnostic_previous.pop(camera_id, None)
            return

        save_preceding = bool(
            repair_config.get('SAVE_PRECEDING_FITS', False)
        )
        if save_preceding:
            previous_context = self.asi676mc_diagnostic_previous.pop(
                camera_id,
                None,
            )
        else:
            # Changing the child option at runtime must release its large byte
            # buffer promptly, while leaving the parent bad/following state.
            self.asi676mc_diagnostic_previous.pop(camera_id, None)
            previous_context = None

        repair_result = i_ref.asi676mc_repair_result or {}
        repair_status = repair_result.get('status')
        current_context = self._asi676mc_diagnostic_frame_context(i_ref)
        pending_state = self.asi676mc_diagnostic_pending.pop(camera_id, None)
        pending_capture_id = asi676mc.diagnostic_pending_capture_id(
            pending_state,
            current_context,
        )
        if pending_state and not pending_capture_id:
            logger.warning(
                'Discarding incompatible following ASI676MC diagnostic frame '
                'for capture %s',
                pending_state.get('capture_id', 'unknown')
                if isinstance(pending_state, dict)
                else pending_state,
            )
        new_capture_id = (
            uuid.uuid4().hex
            if repair_status in asi676mc.DIAGNOSTIC_BAD_STATUSES
            else None
        )
        roles, next_capture_id = asi676mc.diagnostic_capture_plan(
            pending_capture_id,
            repair_status,
            new_capture_id=new_capture_id,
        )

        # A preceding normal frame belongs to the new purple-frame group, not
        # to a pending older group.  Save it independently so a failure here
        # never prevents the current bad FITS from being captured.
        if previous_context and new_capture_id:
            if asi676mc.diagnostic_reference_compatible(
                previous_context,
                current_context,
            ):
                preceding_role = {
                    'capture_id': new_capture_id,
                    'role': 'preceding',
                }
                try:
                    previous_fits_id = previous_context.get(
                        'diagnostic_fits_id'
                    )
                    if previous_fits_id:
                        preceding_entry = (
                            self._add_asi676mc_diagnostic_role(
                                previous_fits_id,
                                preceding_role,
                            )
                        )
                    else:
                        preceding_entry = (
                            self._archive_asi676mc_diagnostic_fits(
                                None,
                                None,
                                camera,
                                [preceding_role],
                                cached_context=previous_context,
                            )
                        )

                    # When the previous rendered image exists, associate it
                    # with this capture too. The bad image can find the triplet
                    # from its own role even if this optional update is absent.
                    try:
                        self._attach_asi676mc_diagnostic_to_image(
                            previous_context,
                            preceding_entry,
                            preceding_role,
                        )
                    except Exception:
                        logger.exception(
                            'Unable to add preceding ASI676MC FITS to the '
                            'previous image row'
                        )

                    logger.warning(
                        'Saved ASI676MC diagnostic FITS (preceding): %s',
                        preceding_entry.filename,
                    )
                except Exception:
                    logger.exception(
                        'Unable to save cached preceding ASI676MC diagnostic '
                        'FITS for %s',
                        previous_context.get('source_name', 'previous frame'),
                    )
            else:
                logger.debug(
                    'Discarding incompatible cached ASI676MC preceding frame '
                    'before purple capture %s',
                    new_capture_id,
                )

        # Drop the old byte buffer before reading a new normal frame below;
        # steady-state caching therefore retains one full FITS, not two.
        previous_context = None

        fits_entry = None
        if roles:
            try:
                fits_entry = self._archive_asi676mc_diagnostic_fits(
                    Path(source_filename_p),
                    i_ref,
                    camera,
                    roles,
                )
            except Exception:
                logger.exception(
                    'Unable to save ASI676MC diagnostic FITS for %s',
                    source_filename_p,
                )

        if fits_entry is not None:
            repair_result['diagnostic_fits'] = {
                'fits_id': fits_entry.id,
                'roles': [dict(role) for role in roles],
            }
            i_ref.asi676mc_repair_result = repair_result

            if next_capture_id:
                self.asi676mc_diagnostic_pending[camera_id] = {
                    'capture_id': next_capture_id,
                    'context': current_context,
                }

            role_names = ', '.join(role['role'] for role in roles)
            logger.warning(
                'Saved ASI676MC diagnostic FITS (%s): %s',
                role_names,
                fits_entry.filename,
            )

        # Only a positively classified normal frame can become the immediate
        # reference for the next purple frame. A bad, skipped, or unsupported
        # frame breaks adjacency and therefore leaves no cache behind.
        if save_preceding and repair_status == 'normal':
            try:
                cached_context = self._cache_asi676mc_diagnostic_frame(
                    Path(source_filename_p),
                    i_ref,
                    fits_entry=fits_entry,
                )
                self.asi676mc_diagnostic_previous[camera_id] = cached_context
                if fits_entry is not None:
                    logger.debug(
                        'Reusing saved ASI676MC FITS as a preceding-frame '
                        'candidate: %s',
                        cached_context['source_name'],
                    )
                else:
                    logger.debug(
                        'Cached %0.2f MiB ASI676MC preceding-frame candidate: '
                        '%s',
                        len(cached_context['fits_bytes']) / (1024 * 1024),
                        cached_context['source_name'],
                    )
            except (MemoryError, OSError, ValueError):
                logger.exception(
                    'Unable to cache ASI676MC preceding-frame candidate: %s',
                    source_filename_p,
                )


    @staticmethod
    def _asi676mc_diagnostic_extension(source_filename_p):
        """Return the complete FITS extension used by diagnostic filenames."""
        source_name_lower = Path(source_filename_p).name.lower()
        for candidate_ext in ('fits.gz', 'fit.gz', 'fits', 'fit'):
            if source_name_lower.endswith('.{0:s}'.format(candidate_ext)):
                return candidate_ext
        raise ValueError(
            'ASI676MC diagnostic source is not a FITS file: {0:s}'.format(
                str(source_filename_p),
            )
        )


    def _asi676mc_diagnostic_frame_context(self, i_ref):
        """Snapshot metadata needed after the live image reference is gone."""
        data = i_ref.hdulist[0].data
        return {
            'camera_id': i_ref.camera_id,
            'camera_uuid': i_ref.camera_uuid,
            'exp_date': i_ref.exp_date,
            'day_date': i_ref.day_date,
            'exposure': i_ref.exposure,
            'gain': i_ref.gain,
            'binning': i_ref.binning,
            'night': bool(self.night_av[constants.NIGHT_NIGHT]),
            'image_shape': tuple(data.shape[:2]),
            'bayer_pattern': str(i_ref.image_bayerpat or '').upper(),
            'image_id': None,
            # Keep the already-computed ratios with cached preceding frames;
            # recalculating them later would require decoding the cached FITS.
            'asi676mc_signature': asi676mc.saved_fits_signature_metadata(
                i_ref.asi676mc_repair_result
            ),
        }


    def _cache_asi676mc_diagnostic_frame(
        self,
        source_filename_p,
        i_ref,
        fits_entry=None,
    ):
        """Retain one normal FITS record or byte string for a possible triplet.

        A normal frame that is already a saved ``following`` diagnostic needs
        only its database ID. Other normal frames retain the untouched source
        bytes because the capture file is deleted before the next frame is
        classified.
        """
        context = self._asi676mc_diagnostic_frame_context(i_ref)
        context.update({
            'source_name': Path(source_filename_p).name,
            'fits_ext': self._asi676mc_diagnostic_extension(
                source_filename_p
            ),
            'diagnostic_fits_id': (
                fits_entry.id if fits_entry is not None else None
            ),
        })
        if fits_entry is None:
            context['fits_bytes'] = Path(source_filename_p).read_bytes()
        return context


    def _set_asi676mc_cached_image_id(self, i_ref, image_id):
        """Complete a current-frame cache entry after its JPEG row is saved."""
        context = self.asi676mc_diagnostic_previous.get(i_ref.camera_id)
        if not context or context.get('exp_date') != i_ref.exp_date:
            return
        context['image_id'] = int(image_id)


    def _add_asi676mc_diagnostic_role(self, fits_id, role):
        """Reuse a saved following FITS as a later preceding reference."""
        fits_entry = IndiAllSkyDbFitsImageTable.query\
            .filter(IndiAllSkyDbFitsImageTable.id == int(fits_id))\
            .one()
        fits_data = dict(fits_entry.data or {})
        diagnostic = dict(
            fits_data.get(asi676mc.DIAGNOSTIC_METADATA_KEY) or {}
        )
        diagnostic['version'] = max(int(diagnostic.get('version', 1)), 1)
        diagnostic['source'] = diagnostic.get('source', 'untouched_input')
        diagnostic['roles'] = asi676mc.append_diagnostic_role(
            diagnostic.get('roles'),
            role,
        )
        fits_data[asi676mc.DIAGNOSTIC_METADATA_KEY] = diagnostic
        fits_entry.data = fits_data
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        return fits_entry


    def _attach_asi676mc_diagnostic_to_image(
        self,
        cached_context,
        fits_entry,
        role,
    ):
        """Expose a preceding FITS from its already-saved rendered image."""
        image_id = cached_context.get('image_id')
        if not image_id:
            return
        image_entry = IndiAllSkyDbImageTable.query\
            .filter(IndiAllSkyDbImageTable.id == int(image_id))\
            .first()
        if image_entry is None:
            return

        image_data = dict(image_entry.data or {})
        diagnostic = dict(image_data.get('asi676mc_diagnostic_fits') or {})
        diagnostic['fits_id'] = fits_entry.id
        diagnostic['roles'] = asi676mc.append_diagnostic_role(
            diagnostic.get('roles'),
            role,
        )
        image_data['asi676mc_diagnostic_fits'] = diagnostic
        image_entry.data = image_data
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise


    def _archive_asi676mc_diagnostic_fits(
        self,
        source_filename_p,
        i_ref,
        camera,
        roles,
        cached_context=None,
    ):
        """Archive a live source path or a previously cached FITS byte string."""
        if cached_context is None:
            frame_context = self._asi676mc_diagnostic_frame_context(i_ref)
            fits_ext = self._asi676mc_diagnostic_extension(source_filename_p)
        else:
            frame_context = cached_context
            fits_ext = cached_context['fits_ext']

        image_height, image_width = frame_context['image_shape']
        date_str = frame_context['exp_date'].strftime('%Y%m%d_%H%M%S')
        role_name = '_'.join(role['role'] for role in roles)
        capture_tag = roles[0]['capture_id'][:8]
        base_filename = self.filename_t.format(
            frame_context['camera_id'],
            date_str,
            fits_ext,
        )
        filename = self._getImageFolder(
            frame_context['exp_date'],
            frame_context['day_date'],
            camera,
            'fits',
        ).joinpath(
            'asi676mc_{0:s}_{1:s}_{2:s}'.format(
                role_name,
                capture_tag,
                base_filename,
            )
        )

        if filename.exists():
            raise FileExistsError(
                'ASI676MC diagnostic FITS already exists: {0:s}'.format(
                    str(filename),
                )
            )

        try:
            if cached_context is None:
                shutil.copy2(str(source_filename_p), str(filename))
            else:
                with filename.open('xb') as fits_file:
                    fits_file.write(cached_context['fits_bytes'])
            filename.chmod(0o644)
            fits_size_bytes = filename.stat().st_size
        except Exception:
            try:
                filename.unlink()
            except FileNotFoundError:
                pass
            raise

        fits_metadata = {
            'type'       : constants.FITS_IMAGE,
            'createDate' : int(frame_context['exp_date'].timestamp()),
            'dayDate'    : frame_context['day_date'].strftime('%Y%m%d'),
            'utc_offset' : frame_context['exp_date'].astimezone().utcoffset().total_seconds(),
            'exposure'   : frame_context['exposure'],
            'gain'       : frame_context['gain'],
            'binmode'    : frame_context['binning'],
            'night'      : frame_context['night'],
            'fileSize'   : fits_size_bytes,
            'height'     : image_height,
            'width'      : image_width,
            'camera_uuid': frame_context['camera_uuid'],
            'data'       : {
                asi676mc.DIAGNOSTIC_METADATA_KEY: {
                    'version': 1,
                    'source': 'untouched_input',
                    'roles': [dict(role) for role in roles],
                },
            },
        }
        if frame_context.get('asi676mc_signature'):
            fits_metadata['data'][asi676mc.SIGNATURE_METADATA_KEY] = dict(
                frame_context['asi676mc_signature']
            )

        try:
            fits_entry = self._miscDb.addFitsImage(
                filename.relative_to(self.image_dir),
                frame_context['camera_id'],
                fits_metadata,
            )
        except Exception:
            db.session.rollback()
            try:
                filename.unlink()
            except OSError:
                logger.exception(
                    'Unable to remove unregistered ASI676MC diagnostic FITS: %s',
                    filename,
                )
            raise

        try:
            self._miscUpload.s3_upload_fits(fits_entry, fits_metadata)
            self._miscUpload.upload_fits_image(fits_entry)
        except Exception:
            db.session.rollback()
            logger.exception(
                'Unable to queue ASI676MC diagnostic FITS upload: %s',
                filename,
            )

        return fits_entry


    def write_fit(self, i_ref, camera):
        now_time = time.time()
        if now_time < self.next_save_fits_time:
            return

        self.next_save_fits_time = time.time() + self.next_save_fits_offset


        ### Do not write daytime image files if daytime capture is disabled
        if not self.night_av[constants.NIGHT_NIGHT] and not self.config.get('DAYTIME_CAPTURE_SAVE', True):
            return


        data = i_ref.hdulist[0].data
        image_height, image_width = data.shape[:2]


        if self.config.get('IMAGE_SAVE_FITS_COMPRESSED'):
            import gzip

            fits_image_buffer = io.BytesIO()
            i_ref.hdulist.writeto(fits_image_buffer)

            f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.fit.gz')
            f_tmpfile.write(gzip.compress(fits_image_buffer.getbuffer()))

            fits_ext = 'fit.gz'
        else:
            f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.fit')
            i_ref.hdulist.writeto(f_tmpfile)

            fits_ext = 'fit'


        f_tmpfile.close()


        tmpfile_p = Path(f_tmpfile.name)


        fits_size_bytes = tmpfile_p.stat().st_size
        logger.info('FITS image file size: %0.1f MB', fits_size_bytes / 1024 / 1024)


        date_str = i_ref.exp_date.strftime('%Y%m%d_%H%M%S')
        # raw light
        folder = self._getImageFolder(i_ref.exp_date, i_ref.day_date, camera, 'fits')
        filename = folder.joinpath(self.filename_t.format(
            i_ref.camera_id,
            date_str,
            fits_ext,  # defined above
        ))


        fits_metadata = {
            'type'       : constants.FITS_IMAGE,
            'createDate' : int(i_ref.exp_date.timestamp()),
            'dayDate'    : i_ref.day_date.strftime('%Y%m%d'),
            'utc_offset' : i_ref.exp_date.astimezone().utcoffset().total_seconds(),
            'exposure'   : i_ref.exposure,
            'gain'       : i_ref.gain,
            'binmode'    : i_ref.binning,
            'night'      : bool(self.night_av[constants.NIGHT_NIGHT]),
            'fileSize'   : fits_size_bytes,
            'height'     : image_height,
            'width'      : image_width,
            'camera_uuid': i_ref.camera_uuid,
        }

        fits_metadata['data'] = {
            'moonmode'        : bool(self.night_av[constants.NIGHT_MOONMODE]),
            'moonphase'       : self.image_processor.astrometric_data['moon_phase'],
            'sqm'             : i_ref.sqm_value,
            'stars'           : len(i_ref.stars),
            'detections'      : len(i_ref.lines),
            'kpindex'         : i_ref.kpindex,
            'ovation_max'     : i_ref.ovation_max,
            'smoke_rating'    : i_ref.smoke_rating,
            'aurora_mag_bt'     : i_ref.aurora_mag_bt,
            'aurora_mag_gsm_bz' : i_ref.aurora_mag_gsm_bz,
            'aurora_plasma_density' : i_ref.aurora_plasma_density,
            'aurora_plasma_speed'   : i_ref.aurora_plasma_speed,
            'aurora_plasma_temp'    : i_ref.aurora_plasma_temp,
            'aurora_n_hemi_gw'      : i_ref.aurora_n_hemi_gw,
            'aurora_s_hemi_gw'      : i_ref.aurora_s_hemi_gw,
            'camera_sqm_raw_mag'    : self.image_processor.camera_sqm_raw_mag,
        }
        signature_metadata = asi676mc.saved_fits_signature_metadata(
            i_ref.asi676mc_repair_result
        )
        if signature_metadata:
            fits_metadata['data'][asi676mc.SIGNATURE_METADATA_KEY] = (
                signature_metadata
            )
        repair_result = i_ref.asi676mc_repair_result
        if isinstance(repair_result, dict) and repair_result.get('status'):
            fits_metadata['data'][
                asi676mc.FITS_REPAIR_STATUS_METADATA_KEY
            ] = str(repair_result['status'])

        fits_entry = self._miscDb.addFitsImage(
            filename.relative_to(self.image_dir),
            i_ref.camera_id,
            fits_metadata,
        )


        file_dir = filename.parent
        if not file_dir.exists():
            file_dir.mkdir(mode=0o755, parents=True)

        logger.info('fit filename: %s', filename)


        if filename.exists():
            logger.error('File exists: %s (skipping)', filename)
            tmpfile_p.unlink()
            return


        shutil.copy2(str(tmpfile_p), str(filename))
        filename.chmod(0o644)

        # set mtime to original exposure time
        #os.utime(str(filename), (i_ref.exp_date.timestamp(), i_ref.exp_date.timestamp()))

        tmpfile_p.unlink()


        self._miscUpload.s3_upload_fits(fits_entry, fits_metadata)
        self._miscUpload.upload_fits_image(fits_entry)


    def export_raw_image(self, i_ref, camera, jpeg_exif=None):
        if not self.config.get('IMAGE_EXPORT_RAW'):
            return

        if not self.config.get('IMAGE_EXPORT_FOLDER'):
            logger.error('IMAGE_EXPORT_FOLDER not defined')
            return


        ### Do not write daytime image files if daytime capture is disabled
        if not self.night_av[constants.NIGHT_NIGHT] and not self.config.get('DAYTIME_CAPTURE_SAVE', True):
            return


        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.{0}'.format(self.config['IMAGE_EXPORT_RAW']))
        f_tmpfile.close()

        tmpfile_name = Path(f_tmpfile.name)


        data = i_ref.opencv_data

        image_height, image_width = data.shape[:2]
        max_bit_depth = self.image_processor.max_bit_depth

        if i_ref.image_bitpix == 8:
            # nothing to scale
            scaled_data = data
        elif i_ref.image_bitpix == 16:
            logger.info('Upscaling data from %d to 16 bit', max_bit_depth)
            shift_factor = 16 - max_bit_depth
            scaled_data = numpy.left_shift(data, shift_factor)
        else:
            raise Exception('Unsupported bit depth')


        #logger.info('Image type: %s', str(scaled_data.dtype))
        #logger.info('Image shape: %s', str(scaled_data.shape))


        if not self.config.get('IMAGE_EXPORT_FLIP_V'):
            scaled_data = self.image_processor._flip(scaled_data, 0)

        if not self.config.get('IMAGE_EXPORT_FLIP_H'):
            scaled_data = self.image_processor._flip(scaled_data, 1)


        write_img_start = time.time()

        if self.config['IMAGE_EXPORT_RAW'] in ('jpg', 'jpeg'):
            if i_ref.image_bitpix == 8:
                scaled_data_8 = scaled_data
            else:
                # jpeg has to be 8 bits
                logger.info('Resampling image from %d to 8 bits', i_ref.image_bitpix)

                #div_factor = int((2 ** max_bit_depth) / 255)
                #scaled_data_8 = (scaled_data / div_factor).astype(numpy.uint8)

                # shifting is 5x faster than division
                shift_factor = max_bit_depth - 8
                scaled_data_8 = numpy.right_shift(scaled_data, shift_factor).astype(numpy.uint8)

            if len(scaled_data_8.shape) == 2:
                img = Image.fromarray(scaled_data_8)
            else:
                img = Image.fromarray(cv2.cvtColor(scaled_data_8, cv2.COLOR_BGR2RGB))

            img.save(str(tmpfile_name), quality=self.config['IMAGE_FILE_COMPRESSION']['jpg'], exif=jpeg_exif)
        elif self.config['IMAGE_EXPORT_RAW'] in ('png',):
            # Pillow does not support 16-bit RGB data
            # opencv is faster than Pillow with PNG
            cv2.imwrite(str(tmpfile_name), scaled_data, [cv2.IMWRITE_PNG_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION']['png']])
        elif self.config['IMAGE_EXPORT_RAW'] in ('jp2',):
            cv2.imwrite(str(tmpfile_name), scaled_data)
        elif self.config['IMAGE_EXPORT_RAW'] in ('webp',):
            cv2.imwrite(str(tmpfile_name), scaled_data, [cv2.IMWRITE_WEBP_QUALITY, 101])  # lossless
        elif self.config['IMAGE_EXPORT_RAW'] in ('tif', 'tiff'):
            # Pillow does not support 16-bit RGB data
            cv2.imwrite(str(tmpfile_name), scaled_data, [cv2.IMWRITE_TIFF_COMPRESSION, 5])  # LZW
        else:
            raise Exception('Unknown file type: %s', self.config['IMAGE_EXPORT_RAW'])

        write_img_elapsed_s = time.time() - write_img_start
        logger.info('Raw image written in %0.4f s', write_img_elapsed_s)



        export_dir = Path(self.config['IMAGE_EXPORT_FOLDER'])

        if self.night_av[constants.NIGHT_NIGHT]:
            timeofday_str = 'night'
        else:
            # daytime
            timeofday_str = 'day'


        day_folder = export_dir.joinpath(
            'ccd_{0:s}'.format(camera.uuid),
            '{0:s}'.format(i_ref.day_date.strftime('%Y%m%d')),
            timeofday_str,
        )

        if not day_folder.exists():
            day_folder.mkdir(mode=0o755, parents=True)


        hour_str = i_ref.exp_date.strftime('%d_%H')

        hour_folder = day_folder.joinpath('{0:s}'.format(hour_str))
        if not hour_folder.exists():
            hour_folder.mkdir(mode=0o755)


        date_str = i_ref.exp_date.strftime('%Y%m%d_%H%M%S')

        raw_filename_t = 'raw_{0:s}'.format(self.filename_t)
        filename = hour_folder.joinpath(raw_filename_t.format(
            i_ref.camera_id,
            date_str,
            self.config['IMAGE_EXPORT_RAW'],  # file suffix
        ))


        raw_metadata = {
            'type'       : constants.RAW_IMAGE,
            'createDate' : int(i_ref.exp_date.timestamp()),
            'dayDate'    : i_ref.day_date.strftime('%Y%m%d'),
            'utc_offset' : i_ref.exp_date.astimezone().utcoffset().total_seconds(),
            'exposure'   : i_ref.exposure,
            'gain'       : i_ref.gain,
            'binmode'    : i_ref.binning,
            'night'      : bool(self.night_av[constants.NIGHT_NIGHT]),
            'fileSize'   : tmpfile_name.stat().st_size,
            'height'     : image_height,
            'width'      : image_width,
            'camera_uuid': i_ref.camera_uuid,
        }

        raw_metadata['data'] = {
            'moonmode'        : bool(self.night_av[constants.NIGHT_MOONMODE]),
            'moonphase'       : self.image_processor.astrometric_data['moon_phase'],
            'sqm'             : i_ref.sqm_value,
            'stars'           : len(i_ref.stars),
            'detections'      : len(i_ref.lines),
            'kpindex'         : i_ref.kpindex,
            'ovation_max'     : i_ref.ovation_max,
            'smoke_rating'    : i_ref.smoke_rating,
            'aurora_mag_bt'     : i_ref.aurora_mag_bt,
            'aurora_mag_gsm_bz' : i_ref.aurora_mag_gsm_bz,
            'aurora_plasma_density' : i_ref.aurora_plasma_density,
            'aurora_plasma_speed'   : i_ref.aurora_plasma_speed,
            'aurora_plasma_temp'    : i_ref.aurora_plasma_temp,
            'aurora_n_hemi_gw'      : i_ref.aurora_n_hemi_gw,
            'aurora_s_hemi_gw'      : i_ref.aurora_s_hemi_gw,
            'camera_sqm_raw_mag'    : self.image_processor.camera_sqm_raw_mag,
        }

        try:
            raw_filename = filename.relative_to(self.image_dir)
        except ValueError:
            # raw exports may be outside the image path
            raw_filename = filename

        raw_entry = self._miscDb.addRawImage(
            raw_filename,
            i_ref.camera_id,
            raw_metadata,
        )


        logger.info('RAW filename: %s', filename)

        if filename.exists():
            logger.error('File exists: %s (skipping)', filename)
            tmpfile_name.unlink()
            return


        shutil.copy2(str(tmpfile_name), str(filename))
        filename.chmod(0o644)

        tmpfile_name.unlink()

        # set mtime to original exposure time
        #os.utime(str(filename), (i_ref.exp_date.timestamp(), i_ref.exp_date.timestamp()))

        self._miscUpload.s3_upload_raw(raw_entry, raw_metadata)
        self._miscUpload.upload_raw_image(raw_entry)


    def write_mask_base_img(self, data):
        logger.info('Generating new mask base')
        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.png')
        f_tmpfile.close()

        tmpfile_name = Path(f_tmpfile.name)


        cv2.imwrite(str(tmpfile_name), data, [cv2.IMWRITE_PNG_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION']['png']])

        mask_file = self.image_dir.joinpath('mask_base.png')

        try:
            mask_file.unlink()
        except FileNotFoundError:
            pass


        shutil.copy2(str(tmpfile_name), str(mask_file))
        mask_file.chmod(0o644)


        tmpfile_name.unlink()


    def write_focus_fit(self, data):
        from astropy.io import fits

        if len(data.shape) == 3:
            # swap axes for FITS
            data = numpy.swapaxes(data, 1, 0)
            data = numpy.swapaxes(data, 2, 0)


        # create a new fits container
        hdu = fits.PrimaryHDU(data)
        hdulist = fits.HDUList([hdu])

        hdu.update_header()  # populates BITPIX, NAXIS, etc

        hdulist[0].header['IMAGETYP'] = 'Light Frame'
        hdulist[0].header['INSTRUME'] = 'focus'


        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.fit')
        hdulist.writeto(f_tmpfile)
        f_tmpfile.close()

        tmpfile_p = Path(f_tmpfile.name)


        focus_fit_p = self.image_dir.joinpath('focus.fit')


        try:
            focus_fit_p.unlink()
        except FileNotFoundError:
            pass


        shutil.copy2(str(tmpfile_p), str(focus_fit_p))
        focus_fit_p.chmod(0o644)


        # cleanup
        tmpfile_p.unlink()


    def write_focus_png(self, data):

        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.png')
        f_tmpfile.close()

        tmpfile_p = Path(f_tmpfile.name)

        cv2.imwrite(str(tmpfile_p), data, [cv2.IMWRITE_PNG_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION']['png']])


        focus_png_p = self.image_dir.joinpath('focus.png')


        try:
            focus_png_p.unlink()
        except FileNotFoundError:
            pass


        shutil.copy2(str(tmpfile_p), str(focus_png_p))
        focus_png_p.chmod(0o644)


        # cleanup
        tmpfile_p.unlink()


    def write_img(self, data, i_ref, camera, jpeg_exif=None):
        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.{0}'.format(self.config['IMAGE_FILE_TYPE']))
        f_tmpfile.close()

        tmpfile_name = Path(f_tmpfile.name)


        #write_img_start = time.time()

        # write to temporary file
        if self.config['IMAGE_FILE_TYPE'] in ('jpg', 'jpeg'):
            # opencv is faster but we have exif data
            img_rgb = Image.fromarray(cv2.cvtColor(data, cv2.COLOR_BGR2RGB))
            img_rgb.save(str(tmpfile_name), quality=self.config['IMAGE_FILE_COMPRESSION']['jpg'], exif=jpeg_exif)
        elif self.config['IMAGE_FILE_TYPE'] in ('png',):
            # exif does not appear to work with png
            #img_rgb = Image.fromarray(cv2.cvtColor(data, cv2.COLOR_BGR2RGB))
            #img_rgb.save(str(tmpfile_name), compress_level=self.config['IMAGE_FILE_COMPRESSION']['png'])

            # opencv is faster than Pillow with PNG
            cv2.imwrite(str(tmpfile_name), data, [cv2.IMWRITE_PNG_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION']['png']])
        elif self.config['IMAGE_FILE_TYPE'] in ('webp',):
            img_rgb = Image.fromarray(cv2.cvtColor(data, cv2.COLOR_BGR2RGB))
            img_rgb.save(str(tmpfile_name), quality=90, lossless=False, exif=jpeg_exif)
        elif self.config['IMAGE_FILE_TYPE'] in ('tif', 'tiff'):
            # exif does not appear to work with tiff
            img_rgb = Image.fromarray(cv2.cvtColor(data, cv2.COLOR_BGR2RGB))
            img_rgb.save(str(tmpfile_name), compression='tiff_lzw')
        else:
            tmpfile_name.unlink()
            raise Exception('Unknown file type: %s', self.config['IMAGE_FILE_TYPE'])

        #write_img_elapsed_s = time.time() - write_img_start
        #logger.info('Image compressed in %0.4f s', write_img_elapsed_s)


        file_size_bytes = tmpfile_name.stat().st_size
        if file_size_bytes < 1024000:
            logger.info('Compressed image file size: %0.2f KB', file_size_bytes / 1024)
        else:
            logger.info('Compressed image file size: %0.2f MB', file_size_bytes / 1024 / 1024)


        ### Always write the latest file for web access
        latest_file = self.image_dir.joinpath('latest.{0:s}'.format(self.config['IMAGE_FILE_TYPE']))

        try:
            latest_file.unlink()
        except FileNotFoundError:
            pass


        shutil.copy2(str(tmpfile_name), str(latest_file))
        latest_file.chmod(0o644)


        ### disable timelapse images in focus mode
        if self.config.get('FOCUS_MODE', False):
            logger.warning('Focus mode enabled, not saving timelapse image')
            #self.write_focus_fit(data)
            #self.write_focus_png(data)
            tmpfile_name.unlink()
            return None, None


        ### Do not write daytime image files if daytime capture is disabled
        if not self.night_av[constants.NIGHT_NIGHT] and self.config['DAYTIME_CAPTURE'] and not self.config.get('DAYTIME_CAPTURE_SAVE', True):
            logger.info('Daytime image save is disabled')
            tmpfile_name.unlink()
            return latest_file, None


        ### Write the timelapse file
        folder = self._getImageFolder(i_ref.exp_date, i_ref.day_date, camera, 'exposures')

        date_str = i_ref.exp_date.strftime('%Y%m%d_%H%M%S')
        filename = folder.joinpath(self.filename_t.format(i_ref.camera_id, date_str, self.config['IMAGE_FILE_TYPE']))

        #logger.info('Image filename: %s', filename)

        if filename.exists():
            logger.error('File exists: %s (skipping)', filename)
            tmpfile_name.unlink()
            return latest_file, None


        shutil.copy2(str(tmpfile_name), str(filename))
        filename.chmod(0o644)

        tmpfile_name.unlink()


        # set mtime to original exposure time
        #os.utime(str(filename), (i_ref.exp_date.timestamp(), i_ref.exp_date.timestamp()))

        #logger.info('Finished writing files')

        return latest_file, filename


    def write_status_json(self, i_ref, adu, adu_average):
        status = {
            'name'                : 'indi_json',
            'class'               : 'ccd',
            'device'              : i_ref.camera_name,
            'night'               : self.night_av[constants.NIGHT_NIGHT],
            'temp'                : self.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP],
            'gain'                : i_ref.gain,
            'exposure'            : i_ref.exposure,
            'stable_exposure'     : int(self.exposure_o.target_adu_found),
            'target_adu'          : i_ref.target_adu,
            'current_adu_target'  : self.exposure_o.current_adu_target,
            'current_adu'         : adu,
            'adu_average'         : adu_average,
            'sqm'                 : i_ref.sqm_value,
            'stars'               : len(i_ref.stars),
            'detections'          : len(i_ref.lines),
            'time'                : i_ref.exp_date.strftime('%s'),
            'latitude'            : self.position_av[constants.POSITION_LATITUDE],
            'longitude'           : self.position_av[constants.POSITION_LONGITUDE],
            'elevation'           : int(self.position_av[constants.POSITION_ELEVATION]),
            'kpindex'             : i_ref.kpindex,
            'ovation_max'         : int(i_ref.ovation_max),
            'aurora_mag_bt'       : i_ref.aurora_mag_bt,
            'aurora_mag_gsm_bz'   : i_ref.aurora_mag_gsm_bz,
            'aurora_plasma_density' : i_ref.aurora_plasma_density,
            'aurora_plasma_speed'   : i_ref.aurora_plasma_speed,
            'aurora_plasma_temp'    : i_ref.aurora_plasma_temp,
            'aurora_n_hemi_gw'    : i_ref.aurora_n_hemi_gw,
            'aurora_s_hemi_gw'    : i_ref.aurora_s_hemi_gw,
            'smoke_rating'        : constants.SMOKE_RATING_MAP_STR[i_ref.smoke_rating],
            'aircraft'            : len(self.adsb_aircraft_list),
            'camera_sqm_raw_mag'  : self.image_processor.camera_sqm_raw_mag,
            'uptime'              : i_ref.uptime,
        }


        # system temp sensors
        for i in range(60):
            v = self.sensors_temp_av[i]

            if self.config.get('TEMP_DISPLAY') == 'f':
                v_temp = (v * 9.0 / 5.0) + 32
            elif self.config.get('TEMP_DISPLAY') == 'k':
                v_temp = v + 273.15
            else:
                v_temp = v


            sensor_topic = 'sensor_temp_{0:d}'.format(i)
            status[sensor_topic] = v_temp


        # user sensors
        for i in range(60):
            sensor_topic = 'sensor_user_{0:d}'.format(i)
            status[sensor_topic] = self.sensors_user_av[i]

        for i in range(100, 110):
            sensor_topic = 'sensor_user_{0:d}'.format(i)
            status[sensor_topic] = self.sensors_user_av[i]


        indi_allsky_status_p = self.varlib_folder_p.joinpath('indi_allsky_status.json')

        with io.open(str(indi_allsky_status_p), 'w', encoding='utf-8') as f_indi_status:
            json.dump(
                status,
                f_indi_status,
                indent=4,
                ensure_ascii=False,
            )

        indi_allsky_status_p.chmod(0o644)


    def _getImageFolder(self, exp_date, day_date, camera, type_folder):
        if self.night_av[constants.NIGHT_NIGHT]:
            # images should be written to previous day's folder until noon
            timeofday_str = 'night'
        else:
            # images should be written to current day's folder
            timeofday_str = 'day'


        day_folder = self.image_dir.joinpath(
            'ccd_{0:s}'.format(camera.uuid),
            type_folder,
            '{0:s}'.format(day_date.strftime('%Y%m%d')),
            timeofday_str,
        )

        if not day_folder.exists():
            day_folder.mkdir(mode=0o755, parents=True)

        hour_str = exp_date.strftime('%d_%H')

        hour_folder = day_folder.joinpath('{0:s}'.format(hour_str))
        if not hour_folder.exists():
            hour_folder.mkdir(mode=0o755)

        return hour_folder


    def write_panorama_img(self, pano_data, i_ref, camera, jpeg_exif=None):
        panorama_height, panorama_width = pano_data.shape[:2]

        # Store the source geometry used for this panorama. This keeps later
        # warnings accurate even if the panorama configuration is changed.
        source_height, source_width = self.image_processor.image.shape[:2]
        binning = max(int(i_ref.binning), 1)
        fish2pano_config = self.config.get('FISH2PANO', {})
        circle_diameter = int(fish2pano_config.get('DIAMETER', 3000) / binning)
        circle_offset_x = int(self.config.get('LENS_OFFSET_X', 0) / binning)
        circle_offset_y = int(self.config.get('LENS_OFFSET_Y', 0) / binning)
        circle_clipped = panoramaSourceCircleClipped(
            source_width,
            source_height,
            circle_diameter,
            circle_offset_x,
            circle_offset_y,
        )

        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.{0}'.format(self.config['IMAGE_FILE_TYPE']))
        f_tmpfile.close()

        tmpfile_name = Path(f_tmpfile.name)


        #write_img_start = time.time()

        # write to temporary file
        if self.config['IMAGE_FILE_TYPE'] in ('jpg', 'jpeg'):
            img_rgb = Image.fromarray(cv2.cvtColor(pano_data, cv2.COLOR_BGR2RGB))
            img_rgb.save(str(tmpfile_name), quality=self.config['IMAGE_FILE_COMPRESSION']['jpg'], exif=jpeg_exif)
        elif self.config['IMAGE_FILE_TYPE'] in ('png',):
            # exif does not appear to work with png
            #img_rgb = Image.fromarray(cv2.cvtColor(data, cv2.COLOR_BGR2RGB))
            #img_rgb.save(str(tmpfile_name), compress_level=self.config['IMAGE_FILE_COMPRESSION']['png'])

            # opencv is faster than Pillow with PNG
            cv2.imwrite(str(tmpfile_name), pano_data, [cv2.IMWRITE_PNG_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION']['png']])
        elif self.config['IMAGE_FILE_TYPE'] in ('webp',):
            img_rgb = Image.fromarray(cv2.cvtColor(pano_data, cv2.COLOR_BGR2RGB))
            img_rgb.save(str(tmpfile_name), quality=90, lossless=False, exif=jpeg_exif)
        elif self.config['IMAGE_FILE_TYPE'] in ('tif', 'tiff'):
            # exif does not appear to work with tiff
            img_rgb = Image.fromarray(cv2.cvtColor(pano_data, cv2.COLOR_BGR2RGB))
            img_rgb.save(str(tmpfile_name), compression='tiff_lzw')
        else:
            tmpfile_name.unlink()
            raise Exception('Unknown file type: %s', self.config['IMAGE_FILE_TYPE'])

        #write_img_elapsed_s = time.time() - write_img_start
        #logger.info('Panorama image compressed in %0.4f s', write_img_elapsed_s)


        ### Always write the latest file for web access
        latest_pano_file = self.image_dir.joinpath('panorama.{0:s}'.format(self.config['IMAGE_FILE_TYPE']))

        try:
            latest_pano_file.unlink()
        except FileNotFoundError:
            pass


        shutil.copy2(str(tmpfile_name), str(latest_pano_file))
        latest_pano_file.chmod(0o644)


        ### disable timelapse images in focus mode
        if self.config.get('FOCUS_MODE', False):
            logger.warning('Focus mode enabled, not saving timelapse image')
            tmpfile_name.unlink()
            return


        ### Do not write daytime image files if daytime capture is disabled
        if not self.night_av[constants.NIGHT_NIGHT] and self.config['DAYTIME_CAPTURE'] and not self.config.get('DAYTIME_CAPTURE_SAVE', True):
            tmpfile_name.unlink()
            return


        ### Write the panorama file
        folder = self._getImageFolder(i_ref.exp_date, i_ref.day_date, camera, 'panoramas')


        panorama_filename_t = 'panorama_{0:s}'.format(self.filename_t)
        date_str = i_ref.exp_date.strftime('%Y%m%d_%H%M%S')
        filename = folder.joinpath(panorama_filename_t.format(i_ref.camera_id, date_str, self.config['IMAGE_FILE_TYPE']))

        #logger.info('Panorama filename: %s', filename)


        panorama_metadata = {
            'type'       : constants.PANORAMA_IMAGE,
            'createDate' : int(i_ref.exp_date.timestamp()),
            'dayDate'    : i_ref.day_date.strftime('%Y%m%d'),
            'utc_offset' : i_ref.exp_date.astimezone().utcoffset().total_seconds(),
            'exposure'   : i_ref.exposure,
            'gain'       : i_ref.gain,
            'binmode'    : i_ref.binning,
            'night'      : bool(self.night_av[constants.NIGHT_NIGHT]),
            'fileSize'   : latest_pano_file.stat().st_size,
            'height'     : panorama_height,
            'width'      : panorama_width,
            'camera_uuid': i_ref.camera_uuid,
            'exclude'    : asi676mc.excluded_from_downstream_measurements(
                i_ref.asi676mc_repair_result
            ),
        }

        panorama_metadata['data'] = {
            'moonmode'        : bool(self.night_av[constants.NIGHT_MOONMODE]),
            'moonphase'       : self.image_processor.astrometric_data['moon_phase'],
            'sqm'             : i_ref.sqm_value,
            'stars'           : len(i_ref.stars),
            'detections'      : len(i_ref.lines),
            'kpindex'         : i_ref.kpindex,
            'ovation_max'     : i_ref.ovation_max,
            'smoke_rating'    : i_ref.smoke_rating,
            'aurora_mag_bt'     : i_ref.aurora_mag_bt,
            'aurora_mag_gsm_bz' : i_ref.aurora_mag_gsm_bz,
            'aurora_plasma_density' : i_ref.aurora_plasma_density,
            'aurora_plasma_speed'   : i_ref.aurora_plasma_speed,
            'aurora_plasma_temp'    : i_ref.aurora_plasma_temp,
            'aurora_n_hemi_gw'      : i_ref.aurora_n_hemi_gw,
            'aurora_s_hemi_gw'      : i_ref.aurora_s_hemi_gw,
            'camera_sqm_raw_mag'    : self.image_processor.camera_sqm_raw_mag,
            'fish2pano_source_width'   : source_width,
            'fish2pano_source_height'  : source_height,
            'fish2pano_circle_diameter' : circle_diameter,
            'fish2pano_circle_offset_x' : circle_offset_x,
            'fish2pano_circle_offset_y' : circle_offset_y,
            'fish2pano_circle_clipped'  : circle_clipped,
        }


        panorama_entry = self._miscDb.addPanoramaImage(
            filename.relative_to(self.image_dir),
            i_ref.camera_id,
            panorama_metadata,
        )


        if filename.exists():
            logger.error('File exists: %s (skipping)', filename)
            tmpfile_name.unlink()
            return


        shutil.copy2(str(tmpfile_name), str(filename))
        filename.chmod(0o644)

        tmpfile_name.unlink()


        # set mtime to original exposure time
        #os.utime(str(filename), (i_ref.exp_date.timestamp(), i_ref.exp_date.timestamp()))

        self._miscUpload.syncapi_panorama(panorama_entry, panorama_metadata)  # syncapi before s3
        self._miscUpload.s3_upload_panorama(panorama_entry, panorama_metadata)
        self._miscUpload.mqtt_publish_image(filename, 'panorama', {})
        self._miscUpload.upload_panorama(panorama_entry)


    def write_circular_display_img(self, circular_image_data, jpeg_exif=None):
        height, width = circular_image_data.shape[:2]

        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.{0}'.format(self.config['IMAGE_FILE_TYPE']))
        f_tmpfile.close()

        tmpfile_name = Path(f_tmpfile.name)


        #write_img_start = time.time()

        # write to temporary file
        if self.config['IMAGE_FILE_TYPE'] in ('jpg', 'jpeg'):
            img_rgb = Image.fromarray(cv2.cvtColor(circular_image_data, cv2.COLOR_BGR2RGB))
            img_rgb.save(str(tmpfile_name), quality=self.config['IMAGE_FILE_COMPRESSION']['jpg'], exif=jpeg_exif)
        elif self.config['IMAGE_FILE_TYPE'] in ('png',):
            # exif does not appear to work with png
            #img_rgb = Image.fromarray(cv2.cvtColor(data, cv2.COLOR_BGR2RGB))
            #img_rgb.save(str(tmpfile_name), compress_level=self.config['IMAGE_FILE_COMPRESSION']['png'])

            # opencv is faster than Pillow with PNG
            cv2.imwrite(str(tmpfile_name), circular_image_data, [cv2.IMWRITE_PNG_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION']['png']])
        elif self.config['IMAGE_FILE_TYPE'] in ('webp',):
            img_rgb = Image.fromarray(cv2.cvtColor(circular_image_data, cv2.COLOR_BGR2RGB))
            img_rgb.save(str(tmpfile_name), quality=90, lossless=False, exif=jpeg_exif)
        elif self.config['IMAGE_FILE_TYPE'] in ('tif', 'tiff'):
            # exif does not appear to work with tiff
            img_rgb = Image.fromarray(cv2.cvtColor(circular_image_data, cv2.COLOR_BGR2RGB))
            img_rgb.save(str(tmpfile_name), compression='tiff_lzw')
        else:
            tmpfile_name.unlink()
            raise Exception('Unknown file type: %s', self.config['IMAGE_FILE_TYPE'])

        #write_img_elapsed_s = time.time() - write_img_start
        #logger.info('Panorama image compressed in %0.4f s', write_img_elapsed_s)


        ### Always write the latest file for web access
        latest_circular_image_file = self.image_dir.joinpath('circular_display.{0:s}'.format(self.config['IMAGE_FILE_TYPE']))

        try:
            latest_circular_image_file.unlink()
        except FileNotFoundError:
            pass


        shutil.copy2(str(tmpfile_name), str(latest_circular_image_file))
        latest_circular_image_file.chmod(0o644)

        # cleanup
        tmpfile_name.unlink()


    def write_realtime_keogram(self, data, camera):
        if isinstance(data, type(None)):
            logger.warning('Realtime keogram data empty')
            return


        save_interval = self.config.get('REALTIME_KEOGRAM', {}).get('SAVE_INTERVAL', 25)
        if self.image_count % save_interval == 0:
            # store keogram data every X images
            self.image_processor.realtimeKeogramDataSave()


        keogram_height, keogram_width = data.shape[:2]

        # scale size
        h_scale_factor = int(self.config.get('KEOGRAM_H_SCALE', 100))
        v_scale_factor = int(self.config.get('KEOGRAM_V_SCALE', 33))
        new_width = int(keogram_width * h_scale_factor / 100)
        new_height = int(keogram_height * v_scale_factor / 100)

        #logger.info('Keogram: %d x %d', new_width, new_height)
        data = cv2.resize(data, (new_width, new_height), interpolation=cv2.INTER_AREA)

        data = self.image_processor.realtimeKeogramApplyLabels(data)

        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.{0}'.format(self.config['IMAGE_FILE_TYPE']))
        f_tmpfile.close()

        tmpfile_name = Path(f_tmpfile.name)


        #write_img_start = time.time()

        # write to temporary file
        if self.config['IMAGE_FILE_TYPE'] in ('jpg', 'jpeg'):
            #img_rgb = Image.fromarray(cv2.cvtColor(data, cv2.COLOR_BGR2RGB))
            #img_rgb.save(str(tmpfile_name), quality=self.config['IMAGE_FILE_COMPRESSION']['jpg'])

            # opencv is faster
            cv2.imwrite(str(tmpfile_name), data, [cv2.IMWRITE_JPEG_QUALITY, self.config['IMAGE_FILE_COMPRESSION']['jpg']])
        elif self.config['IMAGE_FILE_TYPE'] in ('png',):
            # opencv is faster than Pillow with PNG
            cv2.imwrite(str(tmpfile_name), data, [cv2.IMWRITE_PNG_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION']['png']])
        elif self.config['IMAGE_FILE_TYPE'] in ('webp',):
            img_rgb = Image.fromarray(cv2.cvtColor(data, cv2.COLOR_BGR2RGB))
            img_rgb.save(str(tmpfile_name), quality=90, lossless=False)
        elif self.config['IMAGE_FILE_TYPE'] in ('tif', 'tiff'):
            # exif does not appear to work with tiff
            img_rgb = Image.fromarray(cv2.cvtColor(data, cv2.COLOR_BGR2RGB))
            img_rgb.save(str(tmpfile_name), compression='tiff_lzw')
        else:
            tmpfile_name.unlink()
            raise Exception('Unknown file type: %s', self.config['IMAGE_FILE_TYPE'])

        #write_img_elapsed_s = time.time() - write_img_start
        #logger.info('Image compressed in %0.4f s', write_img_elapsed_s)


        ccd_folder = self.image_dir.joinpath('ccd_{0:s}'.format(camera.uuid))

        if not ccd_folder.exists():
            ccd_folder.mkdir(mode=0o755, parents=True)


        ### Always write the latest file for web access
        keogram_file = ccd_folder.joinpath('realtime_keogram.{0:s}'.format(self.config['IMAGE_FILE_TYPE']))

        try:
            keogram_file.unlink()
        except FileNotFoundError:
            pass


        shutil.copy2(str(tmpfile_name), str(keogram_file))
        keogram_file.chmod(0o644)

        tmpfile_name.unlink()

        self._miscUpload.upload_realtime_keogram(keogram_file, camera)


    def save_longterm_keogram_data(self, exp_date, camera_id):
        if self.image_processor.focus_mode:
            # disable processing in focus mode
            return

        if not self.config.get('LONGTERM_KEOGRAM', {}).get('ENABLE', True):
            logger.info('Long term keogram data disabled')
            return

        offset_x = self.config.get('LONGTERM_KEOGRAM', {}).get('OFFSET_X', 0)
        offset_y = self.config.get('LONGTERM_KEOGRAM', {}).get('OFFSET_Y', 0)

        image_height, image_width = self.image_processor.image.shape[:2]


        x = int(image_width / 2) + offset_x
        y = int(image_height / 2) - offset_y  # minus


        rgb_pixel_list = list()
        for p_y in range(5):
            pixel = self.image_processor.image[y + p_y, x]
            rgb_pixel_list.append([int(pixel[2]), int(pixel[1]), int(pixel[0])])  # bgr


        self._miscDb.add_long_term_keogram_data(
            exp_date,
            camera_id,
            rgb_pixel_list,
        )


        return rgb_pixel_list


    def start_image_save_pre_hook(self, exposure, gain, binning):
        if self.image_processor.focus_mode:
            return

        if not self.config.get('IMAGE_SAVE_HOOK_PRE'):
            return


        pre_save_hook_p = Path(self.config.get('IMAGE_SAVE_HOOK_PRE'))
        logger.info('Running image pre-save hook: %s', pre_save_hook_p)

        if not pre_save_hook_p.is_file():
            logger.error('Image pre-save script is not a file')
            return

        if pre_save_hook_p.stat().st_size == 0:
            logger.error('Image pre-save script is empty')
            return

        if not os.access(str(pre_save_hook_p), os.R_OK | os.X_OK):
            logger.error('Image pre-save script is not readable or executable')
            return


        # generate a tempfile for the data
        f_tmp_datajson = tempfile.NamedTemporaryFile(mode='w', delete=True, suffix='.json')
        f_tmp_datajson.close()

        self.pre_hook_datajson_name_p = Path(f_tmp_datajson.name)


        # Communicate sensor values as environment variables
        cmd_env = {
            'DATA_JSON': str(self.pre_hook_datajson_name_p),  # the file used for the json data is communicated via environment variable
            'EXPOSURE' : '{0:0.6f}'.format(exposure),
            'GAIN'     : '{0:0.3f}'.format(gain),
            'BIN'      : '{0:d}'.format(binning),
            'SUNALT'   : '{0:0.1f}'.format(self.image_processor.astrometric_data['sun_alt']),
            'MOONALT'  : '{0:0.1f}'.format(self.image_processor.astrometric_data['moon_alt']),
            'MOONPHASE': '{0:0.1f}'.format(self.image_processor.astrometric_data['moon_phase']),
            'MOONMODE' : '{0:d}'.format(int(bool(self.night_av[constants.NIGHT_MOONMODE]))),
            'NIGHT'    : '{0:d}'.format(int(self.night_av[constants.NIGHT_NIGHT])),
            'LATITUDE' : '{0:0.3f}'.format(self.position_av[constants.POSITION_LATITUDE]),
            'LONGITUDE': '{0:0.3f}'.format(self.position_av[constants.POSITION_LONGITUDE]),
            'ELEVATION': '{0:d}'.format(int(self.position_av[constants.POSITION_ELEVATION])),
        }


        # system temp sensors
        for i in range(60):
            v = self.sensors_temp_av[i]

            if self.config.get('TEMP_DISPLAY') == 'f':
                v_temp = (v * 9.0 / 5.0) + 32
            elif self.config.get('TEMP_DISPLAY') == 'k':
                v_temp = v + 273.15
            else:
                v_temp = v


            sensor_env_var = 'SENSOR_TEMP_{0:d}'.format(i)
            cmd_env[sensor_env_var] = '{0:0.3f}'.format(v_temp)


        # user sensors
        for i in range(60):
            sensor_env_var = 'SENSOR_USER_{0:d}'.format(i)
            cmd_env[sensor_env_var] = '{0:0.3f}'.format(self.sensors_user_av[i])

        for i in range(100, 110):
            sensor_env_var = 'SENSOR_USER_{0:d}'.format(i)
            cmd_env[sensor_env_var] = '{0:0.3f}'.format(self.sensors_user_av[i])


        cmd = [
            str(pre_save_hook_p),
        ]


        try:
            self.image_save_hook_process = subprocess.Popen(
                cmd,
                env=cmd_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )

            self.image_save_hook_process_start = time.time()
        except OSError:
            self.image_save_hook_process = None
            logger.error('Image pre-save script failed to execute')


    def start_image_save_post_hook(self, image_p, exposure, gain, binning):
        if self.image_processor.focus_mode:
            return

        if not self.config.get('IMAGE_SAVE_HOOK_POST'):
            return


        post_save_hook_p = Path(self.config.get('IMAGE_SAVE_HOOK_POST'))
        logger.info('Running image post-save hook: %s', post_save_hook_p)

        if not post_save_hook_p.is_file():
            logger.error('Image post-save script is not a file')
            return

        if post_save_hook_p.stat().st_size == 0:
            logger.error('Image post-save script is empty')
            return

        if not os.access(str(post_save_hook_p), os.R_OK | os.X_OK):
            logger.error('Image post-save script is not readable or executable')
            return


        # Communicate sensor values as environment variables
        hook_env = {
            'EXPOSURE' : '{0:0.6f}'.format(exposure),
            'GAIN'     : '{0:0.3f}'.format(gain),
            'BIN'      : '{0:d}'.format(binning),
            'SUNALT'   : '{0:0.1f}'.format(self.image_processor.astrometric_data['sun_alt']),
            'MOONALT'  : '{0:0.1f}'.format(self.image_processor.astrometric_data['moon_alt']),
            'MOONPHASE': '{0:0.1f}'.format(self.image_processor.astrometric_data['moon_phase']),
            'MOONMODE' : '{0:d}'.format(int(bool(self.night_av[constants.NIGHT_MOONMODE]))),
            'NIGHT'    : '{0:d}'.format(int(self.night_av[constants.NIGHT_NIGHT])),
            'LATITUDE' : '{0:0.3f}'.format(self.position_av[constants.POSITION_LATITUDE]),
            'LONGITUDE': '{0:0.3f}'.format(self.position_av[constants.POSITION_LONGITUDE]),
            'ELEVATION': '{0:d}'.format(int(self.position_av[constants.POSITION_ELEVATION])),
        }


        # system temp sensors
        for i in range(60):
            v = self.sensors_temp_av[i]

            if self.config.get('TEMP_DISPLAY') == 'f':
                v_temp = (v * 9.0 / 5.0) + 32
            elif self.config.get('TEMP_DISPLAY') == 'k':
                v_temp = v + 273.15
            else:
                v_temp = v


            sensor_env_var = 'SENSOR_TEMP_{0:d}'.format(i)
            hook_env[sensor_env_var] = '{0:0.3f}'.format(v_temp)


        # user sensors
        for i in range(60):
            sensor_env_var = 'SENSOR_USER_{0:d}'.format(i)
            hook_env[sensor_env_var] = '{0:0.3f}'.format(self.sensors_user_av[i])

        for i in range(100, 110):
            sensor_env_var = 'SENSOR_USER_{0:d}'.format(i)
            hook_env[sensor_env_var] = '{0:0.3f}'.format(self.sensors_user_av[i])


        cmd = [
            str(post_save_hook_p),
            str(image_p),
        ]


        try:
            self.image_save_hook_process = subprocess.Popen(
                cmd,
                env=hook_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )

            self.image_save_hook_process_start = time.time()
        except OSError:
            self.image_save_hook_process = None
            logger.error('Image post-save script failed to execute')


    def wait_image_save_pre_hook(self):
        if isinstance(self.image_save_hook_process, type(None)):
            return {}


        save_hook_timeout = self.config.get('IMAGE_SAVE_HOOK_TIMEOUT', 5)

        while self._processRunning(self.image_save_hook_process):
            now_time = time.time()
            if now_time - self.image_save_hook_process_start < save_hook_timeout:
                time.sleep(0.1)
                continue


            logger.error('Image pre-save script exceeded runtime')

            for _ in range(5):
                if not self._processRunning(self.image_save_hook_process):
                    break

                self.image_save_hook_process.terminate()
                time.sleep(0.25)
                continue


            if self._processRunning(self.image_save_hook_process):
                logger.error('Killing image pre-save script')
                self.image_save_hook_process.kill()
                self.image_save_hook_process.poll()  # close out process


            try:
                self.pre_hook_datajson_name_p.unlink()
            except FileNotFoundError:
                pass
            except PermissionError as e:
                logger.error('Unable to delete temp file: %s', str(e))


            return {}


        stdout, stderr = self.image_save_hook_process.communicate()
        hook_rc = self.image_save_hook_process.returncode

        if hook_rc == 0:
            try:
                with io.open(str(self.pre_hook_datajson_name_p), 'r', encoding='utf-8') as datajson_name_f:
                    hook_data = json.load(datajson_name_f)

                self.pre_hook_datajson_name_p.unlink()
            except json.JSONDecodeError as e:
                logger.error('Error decoding json: %s', str(e))
                self.pre_hook_datajson_name_p.unlink()
                hook_data = dict()
            except PermissionError as e:
                # cannot delete file
                logger.error(str(e))
                hook_data = dict()
            except FileNotFoundError as e:
                logger.error(str(e))
                hook_data = dict()
        else:
            logger.error('Image pre-save hook failed rc: %d', hook_rc)

            for line in stdout.decode().split('\n'):
                logger.error('Hook: %s', line)

            hook_data = dict()


            try:
                self.pre_hook_datajson_name_p.unlink()
            except FileNotFoundError:
                pass
            except PermissionError:
                pass


        self.image_save_hook_process = None


        # fetch these custom vars for image labels
        # all values should be str
        custom_hook_data = {
            'custom_1'  : hook_data.get('custom_1', ''),
            'custom_2'  : hook_data.get('custom_2', ''),
            'custom_3'  : hook_data.get('custom_3', ''),
            'custom_4'  : hook_data.get('custom_4', ''),
            'custom_5'  : hook_data.get('custom_5', ''),
            'custom_6'  : hook_data.get('custom_6', ''),
            'custom_7'  : hook_data.get('custom_7', ''),
            'custom_8'  : hook_data.get('custom_8', ''),
            'custom_9'  : hook_data.get('custom_9', ''),
        }


        return custom_hook_data


    def wait_image_save_post_hook(self):
        if isinstance(self.image_save_hook_process, type(None)):
            return


        save_hook_timeout = self.config.get('IMAGE_SAVE_HOOK_TIMEOUT', 5)

        while self._processRunning(self.image_save_hook_process):
            now_time = time.time()
            if now_time - self.image_save_hook_process_start < save_hook_timeout:
                time.sleep(0.1)
                continue


            logger.error('Image post-save script exceeded runtime')

            for _ in range(5):
                if not self._processRunning(self.image_save_hook_process):
                    break

                self.image_save_hook_process.terminate()
                time.sleep(0.25)
                continue


            if self._processRunning(self.image_save_hook_process):
                logger.error('Killing image post-save script')
                self.image_save_hook_process.kill()
                self.image_save_hook_process.poll()  # close out process

            return


        stdout, stderr = self.image_save_hook_process.communicate()
        hook_rc = self.image_save_hook_process.returncode

        if hook_rc != 0:
            logger.error('Image post-save hook failed rc: %d', hook_rc)

            for line in stdout.decode().split('\n'):
                logger.error('Hook: %s', line)


        self.image_save_hook_process = None


    def _processRunning(self, process):
        if not process:
            return False

        # poll returns None when process is active, rc (normally 0) when finished
        poll = process.poll()
        if isinstance(poll, type(None)):
            return True

        return False


    def process_sqm_exposure(
        self,
        filename_p,
        exposure,
        gain,
        binning,
        exp_date,
        exp_elapsed,
        camera,
        libcamera_black_level,
        detected_camera_name=None,
    ):
        """Process an SQM-only capture through the same camera safety gate."""
        logger.warning('Processing SQM exposure')

        try:
            i_ref = self.image_processor._add(
                filename_p,
                exposure,
                gain,
                binning,
                exp_date,
                exp_elapsed,
                camera,
                detected_camera_name=detected_camera_name,
            )
        except BadImage as e:
            logger.error('Bad Image: %s', str(e))
            filename_p.unlink()
            #task.setFailed('Bad Image: {0:s}'.format(str(filename_p)))
            return


        self.image_processor.correct_asi676mc_frame(i_ref)


        filename_p.unlink()


        # use original value if not defined
        if i_ref.libcamera_black_level:
            libcamera_black_level = i_ref.libcamera_black_level


        self.image_processor._calibrate(i_ref, libcamera_black_level=libcamera_black_level)


        mag_sqm, raw_mag, raw_adu = self.image_processor._calculateMagnitudeSqm(i_ref)


        logger.warning('Camera SQM Magnitude: %0.2f, Raw Magnitude: %0.2f, ADU: %0.2f', mag_sqm, raw_mag, raw_adu)
        with self.sensors_user_av.get_lock():
            self.sensors_user_av[constants.SENSOR_USER_CAMERA_SQM_MAG] = float(mag_sqm)
            self.sensors_user_av[constants.SENSOR_USER_CAMERA_SQM_ADU] = float(raw_adu)

