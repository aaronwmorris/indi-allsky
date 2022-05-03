import sys
import io
import json
from pathlib import Path
from datetime import datetime
from datetime import timedelta
import time
import functools
import tempfile
import shutil
import copy
import math
import logging
import traceback
#from pprint import pformat

import ephem

from multiprocessing import Process
#from threading import Thread
import queue

from astropy.io import fits
import cv2
import numpy

from .sqm import IndiAllskySqm
from .stars import IndiAllSkyStars

from .flask import db
from .flask.miscDb import miscDb

from .flask.models import TaskQueueState
from .flask.models import TaskQueueQueue
from .flask.models import IndiAllSkyDbDarkFrameTable
from .flask.models import IndiAllSkyDbTaskQueueTable

from sqlalchemy.orm.exc import NoResultFound

from .exceptions import CalibrationNotFound


logger = logging.getLogger('indi_allsky')


def unhandled_exception(exc_type, exc_value, exc_traceback):
    # Do not print exception when user cancels the program
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger.error("An uncaught exception occurred:")
    logger.error("Type: %s", exc_type)
    logger.error("Value: %s", exc_value)

    if exc_traceback:
        format_exception = traceback.format_tb(exc_traceback)
        for line in format_exception:
            logger.error(repr(line))


#log unhandled exceptions
sys.excepthook = unhandled_exception



class ImageWorker(Process):

    dark_temperature_range = 5.0  # dark must be within this range

    line_thickness = 2

    __cfa_bgr_map = {
        'GRBG' : cv2.COLOR_BAYER_GB2BGR,
        'RGGB' : cv2.COLOR_BAYER_BG2BGR,
        'BGGR' : cv2.COLOR_BAYER_RG2BGR,  # untested
        'GBRG' : cv2.COLOR_BAYER_GR2BGR,  # untested
    }

    __cfa_gray_map = {
        'GRBG' : cv2.COLOR_BAYER_GB2GRAY,
        'RGGB' : cv2.COLOR_BAYER_BG2GRAY,
        'BGGR' : cv2.COLOR_BAYER_RG2GRAY,
        'GBRG' : cv2.COLOR_BAYER_GR2GRAY,
    }


    def __init__(
        self,
        idx,
        config,
        image_q,
        upload_q,
        exposure_v,
        gain_v,
        bin_v,
        sensortemp_v,
        night_v,
        moonmode_v,
        save_images=True,
    ):
        super(ImageWorker, self).__init__()

        #self.threadID = idx
        self.name = 'ImageWorker{0:03d}'.format(idx)

        self.config = config
        self.image_q = image_q
        self.upload_q = upload_q

        self.exposure_v = exposure_v
        self.gain_v = gain_v
        self.bin_v = bin_v
        self.sensortemp_v = sensortemp_v
        self.night_v = night_v
        self.moonmode_v = moonmode_v

        self.sun_alt = 0.0
        self.moon_alt = 0.0
        self.moon_phase = 0.0

        self.filename_t = 'ccd{0:d}_{1:s}.{2:s}'
        self.save_images = save_images

        self.target_adu_found = False
        self.current_adu_target = 0
        self.hist_adu = []
        self.target_adu = float(self.config['TARGET_ADU'])
        self.target_adu_dev = float(self.config['TARGET_ADU_DEV'])

        self.image_count = 0

        self._sqm = IndiAllskySqm(self.config)
        self.sqm_value = 0

        self._stars = IndiAllSkyStars(self.config)

        self._miscDb = miscDb(self.config)

        self.shutdown = False
        self.terminate = False

        if self.config.get('IMAGE_FOLDER'):
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()


    def run(self):
        while True:
            time.sleep(1.1)  # sleep every loop

            try:
                i_dict = self.image_q.get_nowait()
            except queue.Empty:
                continue

            if i_dict.get('stop'):
                return


            task_id = i_dict['task_id']


            try:
                task = IndiAllSkyDbTaskQueueTable.query\
                    .filter(IndiAllSkyDbTaskQueueTable.id == task_id)\
                    .filter(IndiAllSkyDbTaskQueueTable.state == TaskQueueState.QUEUED)\
                    .filter(IndiAllSkyDbTaskQueueTable.queue == TaskQueueQueue.IMAGE)\
                    .one()

            except NoResultFound:
                logger.error('Task ID %d not found', task_id)
                continue


            task.setRunning()


            filename = Path(task.data['filename'])
            exposure = task.data['exposure']
            exp_date = datetime.fromtimestamp(task.data['exp_time'])
            exp_elapsed = task.data['exp_elapsed']
            camera_id = task.data['camera_id']
            filename_t = task.data.get('filename_t')

            if filename_t:
                self.filename_t = filename_t

            self.image_count += 1


            if not filename.exists():
                logger.error('Frame not found: %s', filename)
                task.setFailed('Frame not found: {0:s}'.format(str(filename)))
                continue


            hdulist = fits.open(filename)
            filename.unlink()  # no longer need the original file

            #logger.info('HDU Header = %s', pformat(hdulist[0].header))
            image_type = hdulist[0].header['IMAGETYP']
            image_bitpix = hdulist[0].header['BITPIX']

            logger.info('Detected image type: %s, bits: %d', image_type, image_bitpix)

            scidata_uncalibrated = hdulist[0].data


            processing_start = time.time()


            image_bit_depth = self.detectBitDepth(scidata_uncalibrated)

            image_height, image_width = scidata_uncalibrated.shape[:2]
            logger.info('Image: %d x %d', image_width, image_height)


            if len(scidata_uncalibrated.shape) == 2:
                # gray scale or bayered

                if self.config.get('IMAGE_SAVE_FITS'):
                    self.write_fit(hdulist, camera_id, exposure, exp_date, image_type, image_bitpix)

                try:
                    scidata_calibrated = self.calibrate(scidata_uncalibrated, exposure, camera_id, image_bitpix)
                    calibrated = True
                except CalibrationNotFound:
                    scidata_calibrated = scidata_uncalibrated
                    calibrated = False


                # sqm calculation
                self.sqm_value = self.calculateSqm(scidata_calibrated, exposure)

                # debayer
                scidata_debayered = self.debayer(scidata_calibrated)

            else:
                # data is probably RGB
                #logger.info('Channels: %s', pformat(scidata_uncalibrated.shape))

                #INDI returns array in the wrong order for cv2
                scidata_uncalibrated = numpy.swapaxes(scidata_uncalibrated, 0, 2)
                scidata_uncalibrated = numpy.swapaxes(scidata_uncalibrated, 0, 1)
                #logger.info('Channels: %s', pformat(scidata_uncalibrated.shape))

                # sqm calculation
                self.sqm_value = self.calculateSqm(scidata_uncalibrated, exposure)

                scidata_debayered = cv2.cvtColor(scidata_uncalibrated, cv2.COLOR_RGB2BGR)

                calibrated = False


            ### IMAGE IS CALIBRATED ###
            self._export_raw_image(scidata_debayered, exp_date, camera_id, image_bitpix, image_bit_depth)

            scidata_debayered_8 = self._convert_16bit_to_8bit(scidata_debayered, image_bitpix, image_bit_depth)
            #scidata_debayered_8 = scidata_debayered


            #with io.open('/tmp/indi_allsky_numpy.npy', 'w+b') as f_numpy:
            #    numpy.save(f_numpy, scidata_debayered_8)
            #logger.info('Wrote Numpy data: /tmp/indi_allsky_numpy.npy')


            # adu calculate (before processing)
            adu, adu_average = self.calculate_histogram(scidata_debayered_8, exposure)


            # source extraction
            if self.night_v.value and self.config['DETECT_STARS']:
                blob_stars = self._stars.detectObjects(scidata_debayered_8)
            else:
                blob_stars = list()


            # white balance
            #scidata_balanced = self.equalizeHistogram(scidata_debayered_8)
            scidata_balanced = self.white_balance_bgr(scidata_debayered_8)
            #scidata_balanced = self.white_balance_bgr_2(scidata_debayered_8)
            #scidata_balanced = scidata_debayered_8


            if not self.night_v.value and self.config['DAYTIME_CONTRAST_ENHANCE']:
                # Contrast enhancement during the day
                scidata_contrast = self.contrast_clahe(scidata_balanced)
            elif self.night_v.value and self.config['NIGHT_CONTRAST_ENHANCE']:
                # Contrast enhancement during night
                scidata_contrast = self.contrast_clahe(scidata_balanced)
            else:
                scidata_contrast = scidata_balanced


            # crop
            if self.config.get('IMAGE_CROP_ROI'):
                scidata_cropped = self.crop_image(scidata_contrast)
            else:
                scidata_cropped = scidata_contrast


            # verticle flip
            if self.config['IMAGE_FLIP_V']:
                scidata_cal_flip_v = cv2.flip(scidata_cropped, 0)
            else:
                scidata_cal_flip_v = scidata_cropped

            # horizontal flip
            if self.config['IMAGE_FLIP_H']:
                scidata_cal_flip = cv2.flip(scidata_cal_flip_v, 1)
            else:
                scidata_cal_flip = scidata_cal_flip_v


            if self.config['IMAGE_SCALE'] and self.config['IMAGE_SCALE'] != 100:
                scidata_scaled = self.scale_image(scidata_cal_flip)
            else:
                scidata_scaled = scidata_cal_flip

            # blur
            #scidata_blur = self.median_blur(scidata_cal_flip)

            # denoise
            #scidata_denoise = self.fastDenoise(scidata_sci_cal_flip)

            self.image_text(scidata_scaled, exposure, exp_date, exp_elapsed)


            processing_elapsed_s = time.time() - processing_start
            logger.info('Image processed in %0.4f s', processing_elapsed_s)


            task.setSuccess('Image processed')


            self.write_status_json(exposure, exp_date, adu, adu_average, blob_stars)  # write json status file

            if self.save_images:
                latest_file, new_filename = self.write_img(scidata_scaled, exp_date, camera_id)

                image_entry = self._miscDb.addImage(
                    new_filename,
                    camera_id,
                    exp_date,
                    exposure,
                    exp_elapsed,
                    self.gain_v.value,
                    self.bin_v.value,
                    self.sensortemp_v.value,
                    adu,
                    self.target_adu_found,  # stable
                    bool(self.moonmode_v.value),
                    self.moon_phase,
                    night=bool(self.night_v.value),
                    adu_roi=self.config['ADU_ROI'],
                    calibrated=calibrated,
                    sqm=self.sqm_value,
                    stars=len(blob_stars),
                )


                # build mqtt data
                mqtt_data = {
                    'exposure' : round(exposure, 6),
                    'gain'     : self.gain_v.value,
                    'bin'      : self.bin_v.value,
                    'temp'     : round(self.sensortemp_v.value, 1),
                    'sunalt'   : round(self.sun_alt, 1),
                    'moonalt'  : round(self.moon_alt, 1),
                    'moonphase': round(self.moon_phase, 1),
                    'moonmode' : bool(self.moonmode_v.value),
                    'night'    : bool(self.night_v.value),
                    'sqm'      : round(self.sqm_value, 1),
                    'stars'    : len(blob_stars),
                }

                self.mqtt_publish(latest_file, mqtt_data)


                self.upload_image(latest_file, image_entry)



    def upload_image(self, latest_file, image_entry):
        ### upload images
        if not self.config.get('FILETRANSFER', {}).get('UPLOAD_IMAGE'):
            logger.warning('Image uploading disabled')
            return

        if (self.image_count % int(self.config['FILETRANSFER']['UPLOAD_IMAGE'])) != 0:
            next_image = int(self.config['FILETRANSFER']['UPLOAD_IMAGE']) - (self.image_count % int(self.config['FILETRANSFER']['UPLOAD_IMAGE']))
            logger.info('Next image upload in %d images (%d s)', next_image, int(self.config['EXPOSURE_PERIOD'] * next_image))
            return


        remote_path = Path(self.config['FILETRANSFER']['REMOTE_IMAGE_FOLDER'])
        remote_file = remote_path.joinpath(self.config['FILETRANSFER']['REMOTE_IMAGE_NAME'].format(self.config['IMAGE_FILE_TYPE']))

        # tell worker to upload file
        jobdata = {
            'action'      : 'upload',
            'local_file'  : str(latest_file),
            'remote_file' : str(remote_file),
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.upload_q.put({'task_id' : task.id})

        self._miscDb.addUploadedFlag(image_entry)


    def mqtt_publish(self, latest_file, mq_data):
        if not self.config.get('MQTTPUBLISH', {}).get('ENABLE'):
            logger.warning('MQ publishing disabled')
            return

        logger.info('Publishing data to MQ broker')

        # publish data to mq broker
        jobdata = {
            'action'      : 'mqttpub',
            'local_file'  : str(latest_file),
            'mq_data'     : mq_data,
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.upload_q.put({'task_id' : task.id})


    def detectBitDepth(self, data):
        ### This will need some rework if cameras return signed int data
        max_val = numpy.amax(data)
        logger.info('Image max value: %d', int(max_val))

        if max_val > 32768:
            image_bit_depth = 16
        elif max_val > 16384:
            image_bit_depth = 15
        elif max_val > 8192:
            image_bit_depth = 14
        elif max_val > 4096:
            image_bit_depth = 13
        elif max_val > 2096:
            image_bit_depth = 12
        elif max_val > 1024:
            image_bit_depth = 11
        elif max_val > 512:
            image_bit_depth = 10
        elif max_val > 256:
            image_bit_depth = 9
        else:
            image_bit_depth = 8

        logger.info('Detected bit depth: %d', image_bit_depth)

        return image_bit_depth


    def write_fit(self, hdulist, camera_id, exposure, exp_date, image_type, image_bitpix):
        ### Do not write image files if fits are enabled
        if not self.config.get('IMAGE_SAVE_FITS'):
            return


        try:
            calibrated_data = self.calibrate(hdulist[0].data, exposure, camera_id, image_bitpix)
            hdulist[0].data = calibrated_data
        except CalibrationNotFound:
            pass


        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.fit')

        hdulist.writeto(f_tmpfile)

        f_tmpfile.flush()
        f_tmpfile.close()


        date_str = exp_date.strftime('%Y%m%d_%H%M%S')
        # raw light
        folder = self.getImageFolder(exp_date)
        filename = folder.joinpath(self.filename_t.format(
            camera_id,
            date_str,
            'fit',
        ))


        file_dir = filename.parent
        if not file_dir.exists():
            file_dir.mkdir(mode=0o755, parents=True)

        logger.info('fit filename: %s', filename)


        if filename.exists():
            logger.error('File exists: %s (skipping)', filename)
            return

        shutil.copy2(f_tmpfile.name, str(filename))  # copy file in place
        filename.chmod(0o644)


        Path(f_tmpfile.name).unlink()  # delete temp file

        logger.info('Finished writing fit file')



    def write_img(self, scidata, exp_date, camera_id):
        ### Do not write image files if fits are enabled
        if not self.save_images:
            return None, None


        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.{0}'.format(self.config['IMAGE_FILE_TYPE']))
        f_tmpfile.close()

        tmpfile_name = Path(f_tmpfile.name)
        tmpfile_name.unlink()  # remove tempfile, will be reused below


        write_img_start = time.time()

        # write to temporary file
        if self.config['IMAGE_FILE_TYPE'] in ('jpg', 'jpeg'):
            cv2.imwrite(str(tmpfile_name), scidata, [cv2.IMWRITE_JPEG_QUALITY, self.config['IMAGE_FILE_COMPRESSION']['jpg']])
        elif self.config['IMAGE_FILE_TYPE'] in ('png',):
            cv2.imwrite(str(tmpfile_name), scidata, [cv2.IMWRITE_PNG_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION']['png']])
        elif self.config['IMAGE_FILE_TYPE'] in ('tif', 'tiff'):
            cv2.imwrite(str(tmpfile_name), scidata, [cv2.IMWRITE_TIFF_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION']['tif']])
        else:
            raise Exception('Unknown file type: %s', self.config['IMAGE_FILE_TYPE'])

        write_img_elapsed_s = time.time() - write_img_start
        logger.info('Image compressed in %0.4f s', write_img_elapsed_s)


        ### Always write the latest file for web access
        latest_file = self.image_dir.joinpath('latest.{0:s}'.format(self.config['IMAGE_FILE_TYPE']))

        try:
            latest_file.unlink()
        except FileNotFoundError:
            pass

        shutil.copy2(str(tmpfile_name), str(latest_file))
        latest_file.chmod(0o644)


        ### Do not write daytime image files if daytime timelapse is disabled
        if not self.night_v.value and not self.config['DAYTIME_TIMELAPSE']:
            logger.info('Daytime timelapse is disabled')
            tmpfile_name.unlink()  # cleanup temp file
            logger.info('Finished writing files')
            return latest_file, None


        ### Write the timelapse file
        folder = self.getImageFolder(exp_date)

        date_str = exp_date.strftime('%Y%m%d_%H%M%S')
        filename = folder.joinpath(self.filename_t.format(camera_id, date_str, self.config['IMAGE_FILE_TYPE']))

        logger.info('Image filename: %s', filename)

        if filename.exists():
            logger.error('File exists: %s (skipping)', filename)
            return latest_file, None

        shutil.copy2(str(tmpfile_name), str(filename))
        filename.chmod(0o644)


        ### Cleanup
        tmpfile_name.unlink()

        logger.info('Finished writing files')

        return latest_file, filename


    def write_status_json(self, exposure, exp_date, adu, adu_average, blob_stars):
        status = {
            'name'                : 'indi_json',
            'class'               : 'ccd',
            'device'              : self.config['CCD_NAME'],
            'night'               : self.night_v.value,
            'temp'                : self.sensortemp_v.value,
            'gain'                : self.gain_v.value,
            'exposure'            : exposure,
            'stable_exposure'     : int(self.target_adu_found),
            'target_adu'          : self.target_adu,
            'current_adu_target'  : self.current_adu_target,
            'current_adu'         : adu,
            'adu_average'         : adu_average,
            'sqm'                 : self.sqm_value,
            'stars'               : len(blob_stars),
            'time'                : exp_date.strftime('%s'),
        }


        indi_allsky_status_p = Path('/var/lib/indi-allsky/indi_allsky_status.json')

        with io.open(str(indi_allsky_status_p), 'w') as f_indi_status:
            json.dump(status, f_indi_status, indent=4)
            f_indi_status.flush()
            f_indi_status.close()

        indi_allsky_status_p.chmod(0o644)


    def getImageFolder(self, exp_date):
        if self.night_v.value:
            # images should be written to previous day's folder until noon
            day_ref = exp_date - timedelta(hours=12)
            timeofday_str = 'night'
        else:
            # daytime
            # images should be written to current day's folder
            day_ref = exp_date
            timeofday_str = 'day'

        hour_str = exp_date.strftime('%d_%H')

        day_folder = self.image_dir.joinpath('{0:s}'.format(day_ref.strftime('%Y%m%d')), timeofday_str)
        if not day_folder.exists():
            day_folder.mkdir(mode=0o755, parents=True)

        hour_folder = day_folder.joinpath('{0:s}'.format(hour_str))
        if not hour_folder.exists():
            hour_folder.mkdir(mode=0o755)

        return hour_folder


    def calibrate(self, scidata_uncalibrated, exposure, camera_id, image_bitpix):
        # pick a dark frame that is closest to the exposure and temperature
        logger.info('Searching for dark frame: gain %d, exposure >= %0.1f, temp >= %0.1fc', self.gain_v.value, exposure, self.sensortemp_v.value)
        dark_frame_entry = IndiAllSkyDbDarkFrameTable.query\
            .filter(IndiAllSkyDbDarkFrameTable.camera_id == camera_id)\
            .filter(IndiAllSkyDbDarkFrameTable.bitdepth == image_bitpix)\
            .filter(IndiAllSkyDbDarkFrameTable.gain == self.gain_v.value)\
            .filter(IndiAllSkyDbDarkFrameTable.binmode == self.bin_v.value)\
            .filter(IndiAllSkyDbDarkFrameTable.exposure >= exposure)\
            .filter(IndiAllSkyDbDarkFrameTable.temp >= self.sensortemp_v.value)\
            .filter(IndiAllSkyDbDarkFrameTable.temp <= (self.sensortemp_v.value + self.dark_temperature_range))\
            .order_by(
                IndiAllSkyDbDarkFrameTable.exposure.asc(),
                IndiAllSkyDbDarkFrameTable.temp.asc(),
                IndiAllSkyDbDarkFrameTable.createDate.asc(),
            )\
            .first()

        if not dark_frame_entry:
            logger.warning('Temperature matched dark not found: %0.2fc', self.sensortemp_v.value)

            # pick a dark frame that matches the exposure at the hightest temperature found
            dark_frame_entry = IndiAllSkyDbDarkFrameTable.query\
                .filter(IndiAllSkyDbDarkFrameTable.camera_id == camera_id)\
                .filter(IndiAllSkyDbDarkFrameTable.bitdepth == image_bitpix)\
                .filter(IndiAllSkyDbDarkFrameTable.gain == self.gain_v.value)\
                .filter(IndiAllSkyDbDarkFrameTable.binmode == self.bin_v.value)\
                .filter(IndiAllSkyDbDarkFrameTable.exposure >= exposure)\
                .order_by(
                    IndiAllSkyDbDarkFrameTable.exposure.asc(),
                    IndiAllSkyDbDarkFrameTable.temp.desc(),
                    IndiAllSkyDbDarkFrameTable.createDate.asc(),
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
                    self.sensortemp_v.value,
                )

                raise CalibrationNotFound('Dark not found')

        p_dark_frame = Path(dark_frame_entry.filename)
        if not p_dark_frame.exists():
            logger.error('Dark file missing: %s', dark_frame_entry.filename)
            raise CalibrationNotFound('Dark file missing: {0:s}'.format(dark_frame_entry.filename))


        logger.info('Matched dark: %s', p_dark_frame)

        with fits.open(p_dark_frame) as dark:
            scidata = cv2.subtract(scidata_uncalibrated, dark[0].data)
            del dark[0].data   # make sure memory is freed

        return scidata


    def debayer(self, scidata):
        if not self.config['CFA_PATTERN']:
            return scidata

        if self.config.get('NIGHT_GRAYSCALE') and self.night_v.value:
            debayer_algorithm = self.__cfa_gray_map[self.config['CFA_PATTERN']]
        elif self.config.get('DAYTIME_GRAYSCALE') and not self.night_v.value:
            debayer_algorithm = self.__cfa_gray_map[self.config['CFA_PATTERN']]
        else:
            debayer_algorithm = self.__cfa_bgr_map[self.config['CFA_PATTERN']]

        scidata_bgr = cv2.cvtColor(scidata, debayer_algorithm)

        return scidata_bgr


    def image_text(self, data_bytes, exposure, exp_date, exp_elapsed):
        if not self.config['TEXT_PROPERTIES'].get('FONT_FACE'):
            logger.warning('Image labels disabled')
            return

        image_height, image_width = data_bytes.shape[:2]

        utcnow = datetime.utcnow()  # ephem expects UTC dates
        #utcnow = datetime.utcnow() - timedelta(hours=13)  # testing

        obs = ephem.Observer()
        obs.lon = math.radians(self.config['LOCATION_LONGITUDE'])
        obs.lat = math.radians(self.config['LOCATION_LATITUDE'])


        sun = ephem.Sun()
        obs.date = utcnow
        sun.compute(obs)
        self.sun_alt = math.degrees(sun.alt)

        sunOrbX, sunOrbY = self.getOrbXY(sun, obs, (image_height, image_width))



        moon = ephem.Moon()
        obs.date = utcnow
        moon.compute(obs)
        self.moon_alt = math.degrees(moon.alt)
        self.moon_phase = moon.moon_phase * 100.0

        moonOrbX, moonOrbY = self.getOrbXY(moon, obs, (image_height, image_width))


        # Civil dawn
        try:
            obs.horizon = math.radians(self.config['NIGHT_SUN_ALT_DEG'])
            sun_civilDawn_date = obs.next_rising(sun, use_center=True)

            obs.date = sun_civilDawn_date
            sun.compute(obs)
            sunCivilDawnX, sunCivilDawnY = self.getOrbXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunCivilDawnX, sunCivilDawnY), self.config['TEXT_PROPERTIES']['FONT_COLOR'])
        except ephem.NeverUpError:
            # northern hemisphere
            pass
        except ephem.AlwaysUpError:
            # southern hemisphere
            pass


        # Astronomical dawn
        try:
            obs.horizon = math.radians(-18)
            sun_astroDawn_date = obs.next_rising(sun, use_center=True)

            obs.date = sun_astroDawn_date
            sun.compute(obs)
            sunAstroDawnX, sunAstroDawnY = self.getOrbXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunAstroDawnX, sunAstroDawnY), (100, 100, 100))
        except ephem.NeverUpError:
            # northern hemisphere
            pass
        except ephem.AlwaysUpError:
            # southern hemisphere
            pass



        # Civil twilight
        try:
            obs.horizon = math.radians(self.config['NIGHT_SUN_ALT_DEG'])
            sun_civilTwilight_date = obs.next_setting(sun, use_center=True)

            obs.date = sun_civilTwilight_date
            sun.compute(obs)
            sunCivilTwilightX, sunCivilTwilightY = self.getOrbXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunCivilTwilightX, sunCivilTwilightY), self.config['TEXT_PROPERTIES']['FONT_COLOR'])
        except ephem.AlwaysUpError:
            # northern hemisphere
            pass
        except ephem.NeverUpError:
            # southern hemisphere
            pass


        # Astronomical twilight
        try:
            obs.horizon = math.radians(-18)
            sun_astroTwilight_date = obs.next_setting(sun, use_center=True)

            obs.date = sun_astroTwilight_date
            sun.compute(obs)
            sunAstroTwilightX, sunAstroTwilightY = self.getOrbXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunAstroTwilightX, sunAstroTwilightY), (100, 100, 100))
        except ephem.AlwaysUpError:
            # northern hemisphere
            pass
        except ephem.NeverUpError:
            # southern hemisphere
            pass


        # Sun
        self.drawEdgeCircle(data_bytes, (sunOrbX, sunOrbY), self.config['ORB_PROPERTIES']['SUN_COLOR'])


        # Moon
        self.drawEdgeCircle(data_bytes, (moonOrbX, moonOrbY), self.config['ORB_PROPERTIES']['MOON_COLOR'])


        #cv2.rectangle(
        #    img=data_bytes,
        #    pt1=(0, 0),
        #    pt2=(350, 125),
        #    color=(0, 0, 0),
        #    thickness=cv2.FILLED,
        #)

        line_offset = 0
        self.drawText(
            data_bytes,
            exp_date.strftime('%Y%m%d %H:%M:%S'),
            (self.config['TEXT_PROPERTIES']['FONT_X'], self.config['TEXT_PROPERTIES']['FONT_Y'] + line_offset),
            self.config['TEXT_PROPERTIES']['FONT_COLOR'],
        )


        line_offset += self.config['TEXT_PROPERTIES']['FONT_HEIGHT']
        self.drawText(
            data_bytes,
            'Exposure {0:0.6f}'.format(exposure),
            (self.config['TEXT_PROPERTIES']['FONT_X'], self.config['TEXT_PROPERTIES']['FONT_Y'] + line_offset),
            self.config['TEXT_PROPERTIES']['FONT_COLOR'],
        )


        #line_offset += self.config['TEXT_PROPERTIES']['FONT_HEIGHT']
        #self.drawText(
        #    data_bytes,
        #    'Elapsed {0:0.2f} ({1:0.2f})'.format(exp_elapsed, exp_elapsed - exposure),
        #    (self.config['TEXT_PROPERTIES']['FONT_X'], self.config['TEXT_PROPERTIES']['FONT_Y'] + line_offset),
        #    self.config['TEXT_PROPERTIES']['FONT_COLOR'],
        #)


        # Add if gain is supported
        if self.gain_v.value > -1:
            line_offset += self.config['TEXT_PROPERTIES']['FONT_HEIGHT']
            self.drawText(
                data_bytes,
                'Gain {0:d}'.format(self.gain_v.value),
                (self.config['TEXT_PROPERTIES']['FONT_X'], self.config['TEXT_PROPERTIES']['FONT_Y'] + line_offset),
                self.config['TEXT_PROPERTIES']['FONT_COLOR'],
            )


        # Add temp if value is set
        if self.sensortemp_v.value > -100.0:
            if self.config.get('TEMP_DISPLAY') == 'f':
                sensortemp = ((self.sensortemp_v.value * 9.0) / 5.0) + 32
                temp_sys = 'F'
            elif self.config.get('TEMP_DISPLAY') == 'k':
                sensortemp = self.sensortemp_v.value + 273.15
                temp_sys = 'K'
            else:
                sensortemp = self.sensortemp_v.value
                temp_sys = 'C'

            line_offset += self.config['TEXT_PROPERTIES']['FONT_HEIGHT']
            self.drawText(
                data_bytes,
                'Temp {0:0.1f}{1:s}'.format(sensortemp, temp_sys),  # hershey fonts do not support degree symbol
                (self.config['TEXT_PROPERTIES']['FONT_X'], self.config['TEXT_PROPERTIES']['FONT_Y'] + line_offset),
                self.config['TEXT_PROPERTIES']['FONT_COLOR'],
            )


        # Add moon mode indicator
        if self.moonmode_v.value:
            line_offset += self.config['TEXT_PROPERTIES']['FONT_HEIGHT']
            self.drawText(
                data_bytes,
                '* Moon {0:0.1f}% *'.format(self.moon_phase),
                (self.config['TEXT_PROPERTIES']['FONT_X'], self.config['TEXT_PROPERTIES']['FONT_Y'] + line_offset),
                self.config['TEXT_PROPERTIES']['FONT_COLOR'],
            )



        # add extra text to image
        extra_text_lines = self.get_extra_text()
        if extra_text_lines:
            logger.info('Adding extra text from %s', self.config['IMAGE_EXTRA_TEXT'])

            for extra_text_line in extra_text_lines:
                line_offset += self.config['TEXT_PROPERTIES']['FONT_HEIGHT']
                self.drawText(
                    data_bytes,
                    extra_text_line,
                    (self.config['TEXT_PROPERTIES']['FONT_X'], self.config['TEXT_PROPERTIES']['FONT_Y'] + line_offset),
                    self.config['TEXT_PROPERTIES']['FONT_COLOR'],
                )


    def drawText(self, data_bytes, text, pt, color):
        fontFace = getattr(cv2, self.config['TEXT_PROPERTIES']['FONT_FACE'])
        lineType = getattr(cv2, self.config['TEXT_PROPERTIES']['FONT_AA'])

        if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
            cv2.putText(
                img=data_bytes,
                text=text,
                org=pt,
                fontFace=fontFace,
                color=(0, 0, 0),
                lineType=lineType,
                fontScale=self.config['TEXT_PROPERTIES']['FONT_SCALE'],
                thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'] + 1,
            )  # black outline
        cv2.putText(
            img=data_bytes,
            text=text,
            org=pt,
            fontFace=fontFace,
            color=self.config['TEXT_PROPERTIES']['FONT_COLOR'],
            lineType=lineType,
            fontScale=self.config['TEXT_PROPERTIES']['FONT_SCALE'],
            thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'],
        )


    def drawEdgeCircle(self, data_bytes, pt, color):
        if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
            cv2.circle(
                img=data_bytes,
                center=pt,
                radius=self.config['ORB_PROPERTIES']['RADIUS'],
                color=(0, 0, 0),
                thickness=cv2.FILLED,
            )

        cv2.circle(
            img=data_bytes,
            center=pt,
            radius=self.config['ORB_PROPERTIES']['RADIUS'] - 1,
            color=color,
            thickness=cv2.FILLED,
        )


    def drawEdgeLine(self, data_bytes, pt, color):
        lineType = getattr(cv2, self.config['TEXT_PROPERTIES']['FONT_AA'])

        image_height, image_width = data_bytes.shape[:2]

        line_length = int(self.config['ORB_PROPERTIES']['RADIUS'] / 2)

        x, y = pt
        if x == 0 or x == image_width:
            # line is on the left or right
            x1 = x - line_length
            y1 = y
            x2 = x + line_length
            y2 = y
        else:
            # line is on the top or bottom
            x1 = x
            y1 = y - line_length
            x2 = x
            y2 = y + line_length


        if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
            cv2.line(
                img=data_bytes,
                pt1=(x1, y1),
                pt2=(x2, y2),
                color=(0, 0, 0),
                thickness=self.line_thickness + 1,
                lineType=lineType,
            )  # black outline
        cv2.line(
            img=data_bytes,
            pt1=(x1, y1),
            pt2=(x2, y2),
            color=color,
            thickness=self.line_thickness,
            lineType=lineType,
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
            logger.error(str(e))
            return list()


        return extra_lines


    def calculate_histogram(self, data_bytes, exposure):
        image_height, image_width = data_bytes.shape[:2]

        if self.config['ADU_ROI']:
            logger.warning('Calculating ADU from RoI')
            # divide the coordinates by binning value
            x1 = int(self.config['ADU_ROI'][0] / self.bin_v.value)
            y1 = int(self.config['ADU_ROI'][1] / self.bin_v.value)
            x2 = int(self.config['ADU_ROI'][2] / self.bin_v.value)
            y2 = int(self.config['ADU_ROI'][3] / self.bin_v.value)

        else:
            logger.warning('Using central ROI for ADU calculations')
            x1 = int((image_width / 2) - (image_width / 3))
            y1 = int((image_height / 2) - (image_height / 3))
            x2 = int((image_width / 2) + (image_width / 3))
            y2 = int((image_height / 2) + (image_height / 3))


        scidata = data_bytes[
            y1:y2,
            x1:x2,
        ]


        if len(scidata.shape) == 2:
            # mono
            m_avg = cv2.mean(scidata)[0]

            logger.info('Greyscale mean: %0.2f', m_avg)

            adu = m_avg
        else:
            scidata_mono = cv2.cvtColor(scidata, cv2.COLOR_BGR2GRAY)

            m_avg = cv2.mean(scidata_mono)[0]

            logger.info('Greyscale mean: %0.2f', m_avg)

            adu = m_avg


        if adu <= 0.0:
            # ensure we do not divide by zero
            logger.warning('Zero average, setting a default of 0.1')
            adu = 0.1


        logger.info('Brightness average: %0.2f', adu)


        if exposure < 0.001000:
            # expand the allowed deviation for very short exposures to prevent flashing effect due to exposure flapping
            target_adu_min = self.target_adu - (self.target_adu_dev * 2.0)
            target_adu_max = self.target_adu + (self.target_adu_dev * 2.0)
            current_adu_target_min = self.current_adu_target - (self.target_adu_dev * 1.5)
            current_adu_target_max = self.current_adu_target + (self.target_adu_dev * 1.5)
            exp_scale_factor = 0.50  # scale exposure calculation
            history_max_vals = 6  # number of entries to use to calculate average
        else:
            target_adu_min = self.target_adu - (self.target_adu_dev * 1.0)
            target_adu_max = self.target_adu + (self.target_adu_dev * 1.0)
            current_adu_target_min = self.current_adu_target - (self.target_adu_dev * 1.0)
            current_adu_target_max = self.current_adu_target + (self.target_adu_dev * 1.0)
            exp_scale_factor = 1.0  # scale exposure calculation
            history_max_vals = 6  # number of entries to use to calculate average


        if not self.target_adu_found:
            self.recalculate_exposure(exposure, adu, target_adu_min, target_adu_max, exp_scale_factor)
            return adu, 0.0


        self.hist_adu.append(adu)
        self.hist_adu = self.hist_adu[(history_max_vals * -1):]  # remove oldest values, up to history_max_vals

        logger.info('Current target ADU: %0.2f (%0.2f/%0.2f)', self.current_adu_target, current_adu_target_min, current_adu_target_max)
        logger.info('Current ADU history: (%d) [%s]', len(self.hist_adu), ', '.join(['{0:0.2f}'.format(x) for x in self.hist_adu]))


        adu_average = functools.reduce(lambda a, b: a + b, self.hist_adu) / len(self.hist_adu)
        logger.info('ADU average: %0.2f', adu_average)


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


    def recalculate_exposure(self, exposure, adu, target_adu_min, target_adu_max, exp_scale_factor):

        # Until we reach a good starting point, do not calculate a moving average
        if adu <= target_adu_max and adu >= target_adu_min:
            logger.warning('Found target value for exposure')
            self.current_adu_target = copy.copy(adu)
            self.target_adu_found = True
            self.hist_adu = []
            return


        # Scale the exposure up and down based on targets
        if adu > target_adu_max:
            new_exposure = exposure - ((exposure - (exposure * (self.target_adu / adu))) * exp_scale_factor)
        elif adu < target_adu_min:
            new_exposure = exposure - ((exposure - (exposure * (self.target_adu / adu))) * exp_scale_factor)
        else:
            new_exposure = exposure



        # Do not exceed the limits
        if new_exposure < self.config['CCD_EXPOSURE_MIN']:
            new_exposure = self.config['CCD_EXPOSURE_MIN']
        elif new_exposure > self.config['CCD_EXPOSURE_MAX']:
            new_exposure = self.config['CCD_EXPOSURE_MAX']


        logger.warning('New calculated exposure: %0.6f', new_exposure)
        with self.exposure_v.get_lock():
            self.exposure_v.value = new_exposure


    def contrast_clahe(self, data_bytes):
        ### ohhhh, contrasty
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))

        if len(data_bytes.shape) == 2:
            # mono
            return clahe.apply(data_bytes)

        # color, apply to luminance
        lab = cv2.cvtColor(data_bytes, cv2.COLOR_BGR2LAB)

        l, a, b = cv2.split(lab)

        cl = clahe.apply(l)

        new_lab = cv2.merge((cl, a, b))

        return cv2.cvtColor(new_lab, cv2.COLOR_LAB2BGR)


    def equalizeHistogram(self, data_bytes):
        if len(data_bytes.shape) == 2:
            # mono
            return cv2.equalizeHist(data_bytes)

        # color, apply to luminance
        lab = cv2.cvtColor(data_bytes, cv2.COLOR_BGR2LAB)

        l, a, b = cv2.split(lab)

        cl = cv2.equalizeHist(l)

        new_lab = cv2.merge((cl, a, b))

        return cv2.cvtColor(new_lab, cv2.COLOR_LAB2BGR)


    def equalizeHistogramColor(self, data_bytes):
        if len(data_bytes.shape) == 2:
            # mono
            return data_bytes

        ycrcb_img = cv2.cvtColor(data_bytes, cv2.COLOR_BGR2YCrCb)
        ycrcb_img[:, :, 0] = cv2.equalizeHist(ycrcb_img[:, :, 0])
        return cv2.cvtColor(ycrcb_img, cv2.COLOR_YCrCb2BGR)


    def white_balance_bgr(self, data_bytes):
        if len(data_bytes.shape) == 2:
            # mono
            return data_bytes

        if not self.config['AUTO_WB']:
            return data_bytes

        ### This seems to work
        b, g, r = cv2.split(data_bytes)
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

        return cv2.merge([b, g, r])


    def white_balance_bgr_2(self, data_bytes):
        if len(data_bytes.shape) == 2:
            # mono
            return data_bytes

        lab = cv2.cvtColor(data_bytes, cv2.COLOR_BGR2LAB)
        avg_a = numpy.average(lab[:, :, 1])
        avg_b = numpy.average(lab[:, :, 2])
        lab[:, :, 1] = lab[:, :, 1] - ((avg_a - 128) * (lab[:, :, 0] / 255.0) * 1.1)
        lab[:, :, 2] = lab[:, :, 2] - ((avg_b - 128) * (lab[:, :, 0] / 255.0) * 1.1)
        return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


    def median_blur(self, data_bytes):
        data_blur = cv2.medianBlur(data_bytes, ksize=3)
        return data_blur


    def fastDenoise(self, data_bytes):
        scidata_denoise = cv2.fastNlMeansDenoisingColored(
            data_bytes,
            None,
            h=3,
            hColor=3,
            templateWindowSize=7,
            searchWindowSize=21,
        )

        return scidata_denoise


    def scale_image(self, data_bytes):
        image_height, image_width = data_bytes.shape[:2]

        logger.info('Scaling image by %d%%', self.config['IMAGE_SCALE'])
        new_width = int(image_width * self.config['IMAGE_SCALE'] / 100.0)
        new_height = int(image_height * self.config['IMAGE_SCALE'] / 100.0)

        logger.info('New size: %d x %d', new_width, new_height)

        return cv2.resize(data_bytes, (new_width, new_height), interpolation=cv2.INTER_AREA)


    def crop_image(self, data_bytes):
        # divide the coordinates by binning value
        x1 = int(self.config['IMAGE_CROP_ROI'][0] / self.bin_v.value)
        y1 = int(self.config['IMAGE_CROP_ROI'][1] / self.bin_v.value)
        x2 = int(self.config['IMAGE_CROP_ROI'][2] / self.bin_v.value)
        y2 = int(self.config['IMAGE_CROP_ROI'][3] / self.bin_v.value)


        scidata = data_bytes[
            y1:y2,
            x1:x2,
        ]

        new_height, new_width = scidata.shape[:2]
        logger.info('New cropped size: %d x %d', new_width, new_height)

        return scidata


    def _convert_16bit_to_8bit(self, data_bytes_16, image_bitpix, image_bit_depth):
        if image_bitpix == 8:
            return data_bytes_16

        logger.info('Resampling image from %d to 8 bits', image_bitpix)

        div_factor = int((2 ** image_bit_depth) / 255)

        return (data_bytes_16 / div_factor).astype('uint8')


    def _export_raw_image(self, scidata, exp_date, camera_id, image_bitpix, image_bit_depth):
        if not self.config.get('IMAGE_EXPORT_RAW'):
            return

        if not self.config.get('IMAGE_EXPORT_FOLDER'):
            logger.error('IMAGE_EXPORT_FOLDER not defined')
            return


        if image_bitpix == 8:
            # nothing to scale
            scaled_data = scidata
        elif image_bitpix == 16:
            if image_bit_depth == 8:
                logger.info('Upscaling data from 8 to 16 bit')
                scaled_data = numpy.left_shift(scidata, 8)
            elif image_bit_depth == 9:
                logger.info('Upscaling data from 9 to 16 bit')
                scaled_data = numpy.left_shift(scidata, 7)
            elif image_bit_depth == 10:
                logger.info('Upscaling data from 10 to 16 bit')
                scaled_data = numpy.left_shift(scidata, 6)
            elif image_bit_depth == 11:
                logger.info('Upscaling data from 11 to 16 bit')
                scaled_data = numpy.left_shift(scidata, 5)
            elif image_bit_depth == 12:
                logger.info('Upscaling data from 12 to 16 bit')
                scaled_data = numpy.left_shift(scidata, 4)
            elif image_bit_depth == 13:
                logger.info('Upscaling data from 13 to 16 bit')
                scaled_data = numpy.left_shift(scidata, 3)
            elif image_bit_depth == 14:
                logger.info('Upscaling data from 14 to 16 bit')
                scaled_data = numpy.left_shift(scidata, 2)
            elif image_bit_depth == 15:
                logger.info('Upscaling data from 15 to 16 bit')
                scaled_data = numpy.left_shift(scidata, 1)
            elif image_bit_depth == 16:
                # nothing to scale
                scaled_data = scidata
            else:
                # assume 16 bit
                scaled_data = scidata
        else:
            raise Exception('Unsupported bit depth')


        export_dir = Path(self.config['IMAGE_EXPORT_FOLDER'])

        if self.night_v.value:
            # images should be written to previous day's folder until noon
            day_ref = exp_date - timedelta(hours=12)
            timeofday_str = 'night'
        else:
            # daytime
            # images should be written to current day's folder
            day_ref = exp_date
            timeofday_str = 'day'

        date_str = exp_date.strftime('%Y%m%d_%H%M%S')

        hour_str = exp_date.strftime('%d_%H')

        day_folder = export_dir.joinpath('{0:s}'.format(day_ref.strftime('%Y%m%d')), timeofday_str)
        if not day_folder.exists():
            day_folder.mkdir(mode=0o755, parents=True)

        hour_folder = day_folder.joinpath('{0:s}'.format(hour_str))
        if not hour_folder.exists():
            hour_folder.mkdir(mode=0o755)


        filename = hour_folder.joinpath(self.filename_t.format(
            camera_id,
            date_str,
            self.config['IMAGE_EXPORT_RAW'],  # file suffix
        ))


        logger.info('RAW filename: %s', filename)

        write_img_start = time.time()

        if self.config['IMAGE_EXPORT_RAW'] in ('png',):
            cv2.imwrite(str(filename), scaled_data, [cv2.IMWRITE_PNG_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION']['png']])
        elif self.config['IMAGE_EXPORT_RAW'] in ('tif', 'tiff'):
            cv2.imwrite(str(filename), scaled_data, [cv2.IMWRITE_TIFF_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION']['tif']])
        else:
            raise Exception('Unknown file type: %s', self.config['IMAGE_EXPORT_RAW'])

        write_img_elapsed_s = time.time() - write_img_start
        logger.info('Raw image written in %0.4f s', write_img_elapsed_s)


    def getOrbXY(self, skyObj, obs, image_size):
        image_height, image_width = image_size

        ha_rad = obs.sidereal_time() - skyObj.ra
        ha_deg = math.degrees(ha_rad)

        if ha_deg < -180:
            ha_deg = 360 + ha_deg
        elif ha_deg > 180:
            ha_deg = -360 + ha_deg
        else:
            pass

        logger.info('%s hour angle: %0.2f @ %s', skyObj.name, ha_deg, obs.date)

        abs_ha_deg = abs(ha_deg)
        perimeter_half = image_width + image_height

        mapped_ha_deg = int(self.remap(abs_ha_deg, 0, 180, 0, perimeter_half))
        #logger.info('Mapped hour angle: %d', mapped_ha_deg)

        ### The image perimeter is mapped to the hour angle for the X,Y coordinates
        if mapped_ha_deg < (image_width / 2) and ha_deg < 0:
            #logger.info('Top right')
            x = (image_width / 2) + mapped_ha_deg
            y = 0
        elif mapped_ha_deg < (image_width / 2) and ha_deg > 0:
            #logger.info('Top left')
            x = (image_width / 2) - mapped_ha_deg
            y = 0
        elif mapped_ha_deg > ((image_width / 2) + image_height) and ha_deg < 0:
            #logger.info('Bottom right')
            x = image_width - (mapped_ha_deg - (image_height + (image_width / 2)))
            y = image_height
        elif mapped_ha_deg > ((image_width / 2) + image_height) and ha_deg > 0:
            #logger.info('Bottom left')
            x = mapped_ha_deg - (image_height + (image_width / 2))
            y = image_height
        elif ha_deg < 0:
            #logger.info('Right')
            x = image_width
            y = mapped_ha_deg - (image_width / 2)
        elif ha_deg > 0:
            #logger.info('Left')
            x = 0
            y = mapped_ha_deg - (image_width / 2)
        else:
            raise Exception('This cannot happen')


        #logger.info('Orb: %0.2f x %0.2f', x, y)

        return int(x), int(y)


    def remap(self, x, in_min, in_max, out_min, out_max):
        return (float(x) - float(in_min)) * (float(out_max) - float(out_min)) / (float(in_max) - float(in_min)) + float(out_min)


    def calculateSqm(self, data, exposure):
        sqm_value = self._sqm.calculate(data, exposure, self.gain_v.value)
        return sqm_value

