import os
import io
import json
import re
from pathlib import Path
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import time
import functools
import tempfile
import shutil
import psutil
import subprocess
import copy
import signal
import logging
import traceback
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

from .processing import ImageProcessor
from .miscUpload import miscUpload
from .adsb import AdsbAircraftHttpWorker

from .flask import create_app
from .flask import db
from .flask.miscDb import miscDb

from .flask.models import TaskQueueState
from .flask.models import TaskQueueQueue
from .flask.models import IndiAllSkyDbCameraTable
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

    auto_gain_exposure_cutoff_level_low = 80  # percent of max exposure
    auto_gain_exposure_cutoff_level_high = 95  # percent of max exposure


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
        bin_v,
        sensors_temp_av,
        sensors_user_av,
        night_v,
        moonmode_v,
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
        self.bin_v = bin_v

        self.sensors_temp_av = sensors_temp_av  # 0 ccd_temp
        self.sensors_user_av = sensors_user_av
        self.night_v = night_v
        self.moonmode_v = moonmode_v

        self.filename_t = 'ccd{0:d}_{1:s}.{2:s}'

        self.adsb_worker = None
        self.adsb_worker_idx = 0
        self.adsb_aircraft_q = None
        self.adsb_aircraft_list = []

        self.generate_mask_base = True

        self.target_adu_found = False
        self.current_adu_target = 0
        self.hist_adu = []

        self.sqm_value = 0

        self.image_count = 0
        self.metadata_count = 0

        self.image_processor = ImageProcessor(
            self.config,
            self.position_av,
            self.gain_av,
            self.bin_v,
            self.sensors_temp_av,
            self.sensors_user_av,
            self.night_v,
            self.moonmode_v,
        )

        self._miscDb = miscDb(self.config)
        self._miscUpload = miscUpload(
            self.config,
            self.upload_q,
            self.night_v,
        )


        self._gain_step = None  # calculate on first image
        self.auto_gain_step_list = None  # list of fixed gain values
        self.auto_gain_exposure_cutoff_low = None
        self.auto_gain_exposure_cutoff_high = None


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


    @property
    def gain_step(self):
        return self._gain_step


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
        exp_date = datetime.fromtimestamp(i_dict['exp_time'])
        exp_elapsed = i_dict['exp_elapsed']
        camera_id = i_dict['camera_id']
        filename_t = i_dict.get('filename_t')


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


        if isinstance(self.gain_step, type(None)):
            # the gain steps cannot be calculated until the gain_av variable is populated
            gain_range = self.gain_av[constants.GAIN_MAX_NIGHT] - self.gain_av[constants.GAIN_MIN_NIGHT]
            auto_gain_div = self.config.get('CCD_CONFIG', {}).get('AUTO_GAIN_DIV', 5) - 1


            self._gain_step = gain_range / auto_gain_div

            self.auto_gain_step_list = [float(round((self.gain_step * x) + self.gain_av[constants.GAIN_MIN_NIGHT])) for x in range(auto_gain_div)]  # round to ints
            #self.auto_gain_step_list[0] = float(self.gain_av[constants.GAIN_MIN_NIGHT])  # replace first value
            self.auto_gain_step_list[-1] = float(self.gain_av[constants.GAIN_MAX_NIGHT])  # replace last value


            self.auto_gain_exposure_cutoff_high = self.exposure_av[constants.EXPOSURE_MAX] * (self.auto_gain_exposure_cutoff_level_high / 100)
            if self.exposure_av[constants.EXPOSURE_MAX] - self.auto_gain_exposure_cutoff_high < 1.0:
                self.auto_gain_exposure_cutoff_high = self.exposure_av[constants.EXPOSURE_MAX] - 1.0

            self.auto_gain_exposure_cutoff_low = self.exposure_av[constants.EXPOSURE_MAX] * (self.auto_gain_exposure_cutoff_level_low / 100)
            if self.exposure_av[constants.EXPOSURE_MAX] - self.auto_gain_exposure_cutoff_low > 10.0:
                self.auto_gain_exposure_cutoff_low = self.exposure_av[constants.EXPOSURE_MAX] - 10.0


            if self.config.get('CCD_CONFIG', {}).get('AUTO_GAIN_ENABLE'):
                logger.info('Gain Steps: %d @ %0.2f', auto_gain_div, self.gain_step)
                logger.info('Gain Step list: %s', str(self.auto_gain_step_list))
                logger.info('Auto-Gain Exposure cutoff: %0.2fs/%0.2fs', self.auto_gain_exposure_cutoff_low, self.auto_gain_exposure_cutoff_high)


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
            i_ref = self.image_processor.add(filename_p, exposure, gain, exp_date, exp_elapsed, camera)
        except BadImage as e:
            logger.error('Bad Image: %s', str(e))
            filename_p.unlink()
            #task.setFailed('Bad Image: {0:s}'.format(str(filename_p)))
            return


        filename_p.unlink()  # original file is no longer needed


        self.image_count += 1


        self.start_image_save_pre_hook(exposure, gain)


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


        self.image_processor.debayer()

        self.image_processor.calculateSqm()

        self.image_processor.stack()  # this populates self.image


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


        if self.sensors_temp_av[0] > -150:
            # Add temperature data
            temperature_frac = Fraction(self.sensors_temp_av[0]).limit_denominator()
            exif_ifd[piexif.ExifIFD.Temperature] = (temperature_frac.numerator, temperature_frac.denominator)


        jpeg_exif_dict = {
            '0th'   : zeroth_ifd,
            'Exif'  : exif_ifd,
        }


        if not self.config.get('IMAGE_EXIF_PRIVACY'):
            if camera.owner:
                zeroth_ifd[piexif.ImageIFD.Copyright] = camera.owner


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


        self.image_processor.stretch()


        if self.config.get('CONTRAST_ENHANCE_16BIT'):
            if not self.night_v.value and self.config['DAYTIME_CONTRAST_ENHANCE']:
                # Contrast enhancement during the day
                self.image_processor.contrast_clahe_16bit()
            elif self.night_v.value and self.config['NIGHT_CONTRAST_ENHANCE']:
                # Contrast enhancement during night
                self.image_processor.contrast_clahe_16bit()


        self.image_processor.convert_16bit_to_8bit()


        #with io.open('/tmp/indi_allsky_numpy.npy', 'w+b') as f_numpy:
        #    numpy.save(f_numpy, self.image_processor.image)
        #logger.info('Wrote Numpy data: /tmp/indi_allsky_numpy.npy')


        # adu calculate (before processing)
        adu, adu_average = self.calculate_exposure(adu, exposure, gain)


        # generate a new mask base once the target ADU is found
        # this should only only fire once per restart
        if self.generate_mask_base and self.target_adu_found:
            self.generate_mask_base = False
            self.write_mask_base_img(self.image_processor.image)


        # line detection
        if self.night_v.value and self.config.get('DETECT_METEORS'):
            self.image_processor.detectLines()


        # star detection
        if self.night_v.value and self.config.get('DETECT_STARS', True):
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
        if self.config.get('IMAGE_CROP_ROI'):
            self.image_processor.crop_image()


        # green removal
        self.image_processor.scnr()


        # white balance
        self.image_processor.white_balance_manual_bgr()
        self.image_processor.white_balance_auto_bgr()


        # saturation
        self.image_processor.saturation_adjust()


        # gamma correction
        self.image_processor.apply_gamma_correction()


        if not self.config.get('CONTRAST_ENHANCE_16BIT'):
            if not self.night_v.value and self.config['DAYTIME_CONTRAST_ENHANCE']:
                # Contrast enhancement during the day
                self.image_processor.contrast_clahe()
            elif self.night_v.value and self.config['NIGHT_CONTRAST_ENHANCE']:
                # Contrast enhancement during night
                self.image_processor.contrast_clahe()


        self.image_processor.colorize()


        longterm_keogram_pixels = self.save_longterm_keogram_data(exp_date, camera_id)


        self.image_processor.colormap()


        self.image_processor.apply_image_circle_mask()


        self.image_processor.realtimeKeogramUpdate()


        if self.config.get('FISH2PANO', {}).get('ENABLE'):
            if not self.image_count % self.config.get('FISH2PANO', {}).get('MODULUS', 2):
                pano_data = self.image_processor.fish2pano()


                if self.config.get('FISH2PANO', {}).get('ENABLE_CARDINAL_DIRS'):
                    pano_data = self.image_processor.fish2pano_cardinal_dirs_label(pano_data)


                self.write_panorama_img(pano_data, i_ref, camera, jpeg_exif=jpeg_exif)


        self.image_processor.apply_logo_overlay()


        self.image_processor.scale_image()


        self.image_processor.add_border()

        self.image_processor.moon_overlay()

        self.image_processor.lightgraph_overlay()

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
            self.start_image_save_post_hook(new_filename, exposure, gain)

            image_metadata = {
                'type'            : constants.IMAGE,
                'createDate'      : int(exp_date.timestamp()),
                'dayDate'         : i_ref.day_date.strftime('%Y%m%d'),
                'utc_offset'      : exp_date.astimezone().utcoffset().total_seconds(),
                'exposure'        : exposure,
                'exp_elapsed'     : exp_elapsed,
                'gain'            : float(gain),
                'binmode'         : self.bin_v.value,
                'temp'            : self.sensors_temp_av[0],
                'adu'             : adu,
                'stable'          : self.target_adu_found,
                'moonmode'        : bool(self.moonmode_v.value),
                'moonphase'       : self.image_processor.astrometric_data['moon_phase'],
                'night'           : bool(self.night_v.value),
                'adu_roi'         : self.config['ADU_ROI'],
                'calibrated'      : i_ref.calibrated,
                'sqm'             : i_ref.sqm_value,
                'stars'           : len(i_ref.stars),
                'detections'      : len(i_ref.lines),
                'process_elapsed' : processing_elapsed_s,
                'kpindex'         : i_ref.kpindex,
                'ovation_max'     : i_ref.ovation_max,
                'smoke_rating'    : i_ref.smoke_rating,
                'height'          : final_height,
                'width'           : final_width,
                'keogram_pixels'  : longterm_keogram_pixels,
                'camera_uuid'     : i_ref.camera_uuid,
            }


            image_add_data = {
                'kpindex'           : i_ref.kpindex,
                'ovation_max'       : i_ref.ovation_max,
                'aurora_mag_bt'     : i_ref.aurora_mag_bt,
                'aurora_mag_gsm_bz' : i_ref.aurora_mag_gsm_bz,
                'aurora_plasma_density' : i_ref.aurora_plasma_density,
                'aurora_plasma_speed'   : i_ref.aurora_plasma_speed,
                'aurora_plasma_temp'    : i_ref.aurora_plasma_temp,
                'aurora_n_hemi_gw'  : i_ref.aurora_n_hemi_gw,
                'aurora_s_hemi_gw'  : i_ref.aurora_s_hemi_gw,
            }


            for i, v in enumerate(self.sensors_temp_av):
                image_add_data['sensor_temp_{0:d}'.format(i)] = v

            for i, v in enumerate(self.sensors_user_av):
                image_add_data['sensor_user_{0:d}'.format(i)] = v

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


            image_thumbnail_metadata = {
                'type'       : constants.THUMBNAIL,
                'origin'     : constants.IMAGE,
                'createDate' : int(exp_date.timestamp()),
                'dayDate'    : i_ref.day_date.strftime('%Y%m%d'),
                'utc_offset' : exp_date.astimezone().utcoffset().total_seconds(),
                'night'      : bool(self.night_v.value),
                'camera_uuid': camera.uuid,
            }

            image_thumbnail_entry = self._miscDb.addThumbnail(
                image_entry,
                image_metadata,
                camera.id,
                image_thumbnail_metadata,
                numpy_data=self.image_processor.image,
            )


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
                'exposure' : round(exposure, 6),
                'gain'     : round(gain, 2),
                'bin'      : self.bin_v.value,
                'temp'     : round(self.sensors_temp_av[0], 1),
                'sunalt'   : round(self.image_processor.astrometric_data['sun_alt'], 1),
                'moonalt'  : round(self.image_processor.astrometric_data['moon_alt'], 1),
                'moonphase': round(self.image_processor.astrometric_data['moon_phase'], 1),
                'mooncycle': round(self.image_processor.astrometric_data['moon_cycle'], 1),
                'moonmode' : bool(self.moonmode_v.value),
                'night'    : bool(self.night_v.value),
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
            for i, v in enumerate(self.sensors_temp_av):
                sensor_topic = 'sensor_temp_{0:d}'.format(i)
                mqtt_data[sensor_topic] = round(v, 1)


            # user sensors
            for i, v in enumerate(self.sensors_user_av):
                sensor_topic = 'sensor_user_{0:d}'.format(i)
                mqtt_data[sensor_topic] = round(v, 3)


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
            'night'               : self.night_v.value,
            'temp'                : self.sensors_temp_av[0],
            'gain'                : i_ref.gain,
            'exposure'            : i_ref.exposure,
            'stable_exposure'     : int(self.target_adu_found),
            'target_adu'          : i_ref.target_adu,
            'current_adu_target'  : self.current_adu_target,
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
        }


        # system temp sensors
        for i, v in enumerate(self.sensors_temp_av):
            sensor_topic = 'sensor_temp_{0:d}'.format(i)
            metadata[sensor_topic] = v


        # user sensors
        for i, v in enumerate(self.sensors_user_av):
            sensor_topic = 'sensor_user_{0:d}'.format(i)
            metadata[sensor_topic] = v


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


        if self.night_v.value:
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


    def write_fit(self, i_ref, camera):
        now_time = time.time()
        if now_time < self.next_save_fits_time:
            return

        self.next_save_fits_time = time.time() + self.next_save_fits_offset


        data = i_ref.hdulist[0].data
        image_height, image_width = data.shape[:2]


        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.fit')

        i_ref.hdulist.writeto(f_tmpfile)
        f_tmpfile.close()

        tmpfile_p = Path(f_tmpfile.name)


        date_str = i_ref.exp_date.strftime('%Y%m%d_%H%M%S')
        # raw light
        folder = self._getImageFolder(i_ref.exp_date, i_ref.day_date, camera, 'fits')
        filename = folder.joinpath(self.filename_t.format(
            i_ref.camera_id,
            date_str,
            'fit',
        ))


        fits_metadata = {
            'type'       : constants.FITS_IMAGE,
            'createDate' : int(i_ref.exp_date.timestamp()),
            'dayDate'    : i_ref.day_date.strftime('%Y%m%d'),
            'utc_offset' : i_ref.exp_date.astimezone().utcoffset().total_seconds(),
            'exposure'   : i_ref.exposure,
            'gain'       : i_ref.gain,
            'binmode'    : self.bin_v.value,
            'night'      : bool(self.night_v.value),
            'height'     : image_height,
            'width'      : image_width,
            'camera_uuid': i_ref.camera_uuid,
        }

        fits_metadata['data'] = {
            'moonmode'        : bool(self.moonmode_v.value),
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
            'aurora_n_hemi_gw'  : i_ref.aurora_n_hemi_gw,
            'aurora_s_hemi_gw'  : i_ref.aurora_s_hemi_gw,
        }

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

        if self.night_v.value:
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
            'binmode'    : self.bin_v.value,
            'night'      : bool(self.night_v.value),
            'height'     : image_height,
            'width'      : image_width,
            'camera_uuid': i_ref.camera_uuid,
        }

        raw_metadata['data'] = {
            'moonmode'        : bool(self.moonmode_v.value),
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
            'aurora_n_hemi_gw'  : i_ref.aurora_n_hemi_gw,
            'aurora_s_hemi_gw'  : i_ref.aurora_s_hemi_gw,
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
            tmpfile_name.unlink()
            return None, None


        ### Do not write daytime image files if daytime capture is disabled
        if not self.night_v.value and self.config['DAYTIME_CAPTURE'] and not self.config.get('DAYTIME_CAPTURE_SAVE', True):
            logger.info('Daytime capture is disabled')
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
            'night'               : self.night_v.value,
            'temp'                : self.sensors_temp_av[0],
            'gain'                : i_ref.gain,
            'exposure'            : i_ref.exposure,
            'stable_exposure'     : int(self.target_adu_found),
            'target_adu'          : i_ref.target_adu,
            'current_adu_target'  : self.current_adu_target,
            'current_adu'         : adu,
            'adu_average'         : adu_average,
            'sqm'                 : i_ref.sqm_value,
            'stars'               : len(i_ref.stars),
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

        }


        # system temp sensors
        for i, v in enumerate(self.sensors_temp_av):
            sensor_topic = 'sensor_temp_{0:d}'.format(i)
            status[sensor_topic] = v


        # user sensors
        for i, v in enumerate(self.sensors_user_av):
            sensor_topic = 'sensor_user_{0:d}'.format(i)
            status[sensor_topic] = v



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
        if self.night_v.value:
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
        if not self.night_v.value and self.config['DAYTIME_CAPTURE'] and not self.config.get('DAYTIME_CAPTURE_SAVE', True):
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
            'binmode'    : self.bin_v.value,
            'night'      : bool(self.night_v.value),
            'height'     : panorama_height,
            'width'      : panorama_width,
            'camera_uuid': i_ref.camera_uuid,
        }

        panorama_metadata['data'] = {
            'moonmode'        : bool(self.moonmode_v.value),
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
            'aurora_n_hemi_gw'  : i_ref.aurora_n_hemi_gw,
            'aurora_s_hemi_gw'  : i_ref.aurora_s_hemi_gw,
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


    def calculate_exposure(self, adu, exposure, gain):
        if adu <= 0.0:
            # ensure we do not divide by zero
            logger.warning('Zero average, setting a default of 0.1')
            adu = 0.1


        if self.night_v.value:
            target_adu = self.config['TARGET_ADU']
        else:
            target_adu = self.config['TARGET_ADU_DAY']


        # Brightness when the sun is in view (very short exposures) can change drastically when clouds pass through the view
        # Setting a deviation that is too short can cause exposure flapping
        if exposure < 0.001000:
            # DAY
            adu_dev = float(self.config.get('TARGET_ADU_DEV_DAY', 20))

            target_adu_min = target_adu - adu_dev
            target_adu_max = target_adu + adu_dev
            current_adu_target_min = self.current_adu_target - adu_dev
            current_adu_target_max = self.current_adu_target + adu_dev

            exp_scale_factor = 0.50  # scale exposure calculation
            history_max_vals = 6     # number of entries to use to calculate average
        else:
            # NIGHT
            adu_dev = float(self.config.get('TARGET_ADU_DEV', 10))

            target_adu_min = target_adu - adu_dev
            target_adu_max = target_adu + adu_dev
            current_adu_target_min = self.current_adu_target - adu_dev
            current_adu_target_max = self.current_adu_target + adu_dev

            exp_scale_factor = 1.0  # scale exposure calculation
            history_max_vals = 6    # number of entries to use to calculate average



        if not self.target_adu_found:
            self.recalculate_exposure(exposure, gain, adu, target_adu, target_adu_min, target_adu_max, exp_scale_factor)
            return adu, 0.0


        self.hist_adu.append(adu)
        self.hist_adu = self.hist_adu[(history_max_vals * -1):]  # remove oldest values, up to history_max_vals

        adu_average = functools.reduce(lambda a, b: a + b, self.hist_adu) / len(self.hist_adu)

        #logger.info('ADU average: %0.2f', adu_average)
        #logger.info('Current target ADU: %0.2f (%0.2f/%0.2f)', self.current_adu_target, current_adu_target_min, current_adu_target_max)
        #logger.info('Current ADU history: (%d) [%s]', len(self.hist_adu), ', '.join(['{0:0.2f}'.format(x) for x in self.hist_adu]))


        ### Need at least x values to continue
        if len(self.hist_adu) < history_max_vals:
            return adu, 0.0


        ### only change exposure when 70% of the values exceed the max or minimum
        if adu_average > current_adu_target_max:
            logger.warning('ADU increasing beyond limits, recalculating next exposure')
            self.target_adu_found = False
        elif adu_average < current_adu_target_min:
            logger.warning('ADU decreasing beyond limits, recalculating next exposure')
            self.target_adu_found = False

        return adu, adu_average


    def recalculate_exposure(self, exposure, gain, adu, target_adu, target_adu_min, target_adu_max, exp_scale_factor):
        # Until we reach a good starting point, do not calculate a moving average
        if adu <= target_adu_max and adu >= target_adu_min:
            logger.warning('Found target value for exposure')
            self.current_adu_target = copy.copy(adu)
            self.target_adu_found = True
            self.hist_adu = []
            return


        if self.night_v.value:
            exposure_min = float(self.exposure_av[constants.EXPOSURE_MIN_NIGHT])

            gain_min = float(self.gain_av[constants.GAIN_MIN_NIGHT])
            gain_max = float(self.gain_av[constants.GAIN_MAX_NIGHT])

            # ignore moon mode when using auto-gain
            if not self.config.get('CCD_CONFIG', {}).get('AUTO_GAIN_ENABLE'):
                if self.moonmode_v.value:
                    gain_min = float(self.gain_av[constants.GAIN_MIN_MOONMODE])
                    gain_max = float(self.gain_av[constants.GAIN_MAX_MOONMODE])
        else:
            exposure_min = float(self.exposure_av[constants.EXPOSURE_MIN_NIGHT])

            gain_min = float(self.gain_av[constants.GAIN_MIN_DAY])
            gain_max = float(self.gain_av[constants.GAIN_MAX_DAY])


        # Scale the exposure up and down based on targets
        if adu > target_adu_max:
            new_exposure = exposure - ((exposure - (exposure * (target_adu / adu))) * exp_scale_factor)
        elif adu < target_adu_min:
            new_exposure = exposure - ((exposure - (exposure * (target_adu / adu))) * exp_scale_factor)
        else:
            new_exposure = exposure


        # Do not exceed the exposure limits
        if new_exposure < exposure_min:
            new_exposure = float(exposure_min)
        elif new_exposure > self.exposure_av[constants.EXPOSURE_MAX]:
            new_exposure = float(self.exposure_av[constants.EXPOSURE_MAX])


        if self.config.get('CCD_CONFIG', {}).get('AUTO_GAIN_ENABLE'):
            try:
                auto_gain_idx = self.auto_gain_step_list.index(gain)
            except ValueError:
                # fallback to min if gain does not match
                logger.error('Current gain not found in list, reset to minimum gain')
                auto_gain_idx = 0


            if new_exposure == exposure:
                # no change
                next_gain = gain
            elif new_exposure > exposure:
                # exposure/gain needs to increase
                if gain == self.auto_gain_step_list[-1]:
                    # already at max gain, increase exposure
                    next_gain = gain
                else:

                    if exposure < self.auto_gain_exposure_cutoff_high:
                        # maintain gain, increase exposure
                        next_gain = gain
                        new_exposure = min(new_exposure, self.auto_gain_exposure_cutoff_high)
                    else:
                        # increase gain, maintain exposure
                        next_gain = self.auto_gain_step_list[auto_gain_idx + 1]
                        new_exposure = exposure

                        # Do not exceed the gain limits
                        if next_gain > gain_max:
                            next_gain = gain_max

            else:
                # exposure/gain needs to decrease
                if gain == self.auto_gain_step_list[0]:
                    # already at minimum gain, decrease exposure
                    next_gain = gain
                else:
                    if exposure > self.auto_gain_exposure_cutoff_low:
                        # maintain gain, decrease exposure
                        next_gain = gain
                        new_exposure = max(new_exposure, self.auto_gain_exposure_cutoff_low)
                    else:
                        # decrease gain, maintain exposure
                        next_gain = self.auto_gain_step_list[auto_gain_idx - 1]
                        new_exposure = exposure

                        # Do not exceed the gain limits
                        if next_gain < gain_min:
                            next_gain = gain_min
        else:
            # just set the gain to the max for the current mode
            next_gain = gain_max


        logger.warning('New calculated exposure: %0.8f (gain %0.2f)', new_exposure, next_gain)
        with self.exposure_av.get_lock():
            self.exposure_av[constants.EXPOSURE_NEXT] = float(new_exposure)

        with self.gain_av.get_lock():
            self.gain_av[constants.GAIN_NEXT] = float(next_gain)


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


    def start_image_save_pre_hook(self, exposure, gain):
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
            'GAIN'     : '{0:0.2f}'.format(gain),
            'BIN'      : '{0:d}'.format(self.bin_v.value),
            'SUNALT'   : '{0:0.1f}'.format(self.image_processor.astrometric_data['sun_alt']),
            'MOONALT'  : '{0:0.1f}'.format(self.image_processor.astrometric_data['moon_alt']),
            'MOONPHASE': '{0:0.1f}'.format(self.image_processor.astrometric_data['moon_phase']),
            'MOONMODE' : '{0:d}'.format(int(bool(self.moonmode_v.value))),
            'NIGHT'    : '{0:d}'.format(int(self.night_v.value)),
            'LATITUDE' : '{0:0.3f}'.format(self.position_av[constants.POSITION_LATITUDE]),
            'LONGITUDE': '{0:0.3f}'.format(self.position_av[constants.POSITION_LONGITUDE]),
            'ELEVATION': '{0:d}'.format(int(self.position_av[constants.POSITION_ELEVATION])),
        }


        # system temp sensors
        for i, v in enumerate(self.sensors_temp_av):
            sensor_env_var = 'SENSOR_TEMP_{0:d}'.format(i)
            cmd_env[sensor_env_var] = '{0:0.3f}'.format(v)


        # user sensors
        for i, v in enumerate(self.sensors_user_av):
            sensor_env_var = 'SENSOR_USER_{0:d}'.format(i)
            cmd_env[sensor_env_var] = '{0:0.3f}'.format(v)


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


    def start_image_save_post_hook(self, image_p, exposure, gain):
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
            'BIN'      : '{0:d}'.format(self.bin_v.value),
            'SUNALT'   : '{0:0.1f}'.format(self.image_processor.astrometric_data['sun_alt']),
            'MOONALT'  : '{0:0.1f}'.format(self.image_processor.astrometric_data['moon_alt']),
            'MOONPHASE': '{0:0.1f}'.format(self.image_processor.astrometric_data['moon_phase']),
            'MOONMODE' : '{0:d}'.format(int(bool(self.moonmode_v.value))),
            'NIGHT'    : '{0:d}'.format(int(self.night_v.value)),
            'LATITUDE' : '{0:0.3f}'.format(self.position_av[constants.POSITION_LATITUDE]),
            'LONGITUDE': '{0:0.3f}'.format(self.position_av[constants.POSITION_LONGITUDE]),
            'ELEVATION': '{0:d}'.format(int(self.position_av[constants.POSITION_ELEVATION])),
        }


        # system temp sensors
        for i, v in enumerate(self.sensors_temp_av):
            sensor_env_var = 'SENSOR_TEMP_{0:d}'.format(i)
            hook_env[sensor_env_var] = '{0:0.3f}'.format(v)


        # user sensors
        for i, v in enumerate(self.sensors_user_av):
            sensor_env_var = 'SENSOR_USER_{0:d}'.format(i)
            hook_env[sensor_env_var] = '{0:0.3f}'.format(v)


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

