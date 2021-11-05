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
#from pprint import pformat

import ephem

from multiprocessing import Process
import queue
#from threading import Thread
import multiprocessing

from astropy.io import fits
import cv2
import numpy

from .sqm import IndiAllskySqm
from .db import IndiAllSkyDb
from .sep import IndiAllSkySep

from sqlalchemy.orm.exc import NoResultFound

from .exceptions import CalibrationNotFound


logger = multiprocessing.get_logger()


class ImageProcessWorker(Process):

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


    def __init__(self, idx, config, image_q, upload_q, exposure_v, gain_v, bin_v, sensortemp_v, night_v, moonmode_v, save_images=True):
        super(ImageProcessWorker, self).__init__()

        #self.threadID = idx
        self.name = 'ImageProcessWorker{0:03d}'.format(idx)

        self.config = config
        self.image_q = image_q
        self.upload_q = upload_q
        self.exposure_v = exposure_v
        self.gain_v = gain_v
        self.bin_v = bin_v
        self.sensortemp_v = sensortemp_v
        self.night_v = night_v
        self.moonmode_v = moonmode_v

        self.filename_t = '{0:s}.{1:s}'
        self.save_images = save_images

        self.target_adu_found = False
        self.current_adu_target = 0
        self.hist_adu = []
        self.target_adu = float(self.config['TARGET_ADU'])
        self.target_adu_dev = float(self.config['TARGET_ADU_DEV'])

        self.image_count = 0
        self.image_width = 0
        self.image_height = 0

        self.image_bit_depth = 0
        self.color = self.config['CFA_PATTERN']  # flag can be overriden if color data is convert to grayscale

        self._sqm = IndiAllskySqm(self.config)
        self.sqm_value = 0

        self._sep = IndiAllSkySep(self.config)

        self._db = IndiAllSkyDb(self.config)

        if self.config['IMAGE_FOLDER']:
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()


    def run(self):
        while True:
            try:
                i_dict = self.image_q.get(block=True, timeout=0.5)
            except queue.Empty:
                continue

            if i_dict.get('stop'):
                return

            imgdata = i_dict['imgdata']
            exposure = i_dict['exposure']
            exp_date = i_dict['exp_date']
            filename_t = i_dict.get('filename_t')
            img_subdirs = i_dict.get('img_subdirs', [])  # we only use this for fits/darks

            if filename_t:
                self.filename_t = filename_t

            self.image_count += 1

            ### OpenCV ###
            blobfile = io.BytesIO(imgdata)
            hdulist = fits.open(blobfile)

            #logger.info('HDU Header = %s', pformat(hdulist[0].header))
            image_type = hdulist[0].header['IMAGETYP']
            image_bitpix = hdulist[0].header['BITPIX']

            logger.info('Detected image type: %s, bits: %d', image_type, image_bitpix)

            scidata_uncalibrated = hdulist[0].data


            processing_start = time.time()

            if len(scidata_uncalibrated.shape) == 2:
                # gray scale or bayered
                self.image_height, self.image_width = scidata_uncalibrated.shape[:2]
                logger.info('Image: %d x %d', self.image_width, self.image_height)

                self.detectBitDepth(scidata_uncalibrated)

                if self.config.get('IMAGE_SAVE_RAW'):
                    self.write_fit(hdulist, exposure, exp_date, img_subdirs, image_type, image_bitpix)

                try:
                    scidata_calibrated = self.calibrate(scidata_uncalibrated, exposure, image_bitpix)
                    calibrated = True
                except CalibrationNotFound:
                    scidata_calibrated = scidata_uncalibrated
                    calibrated = False


                # sqm calculation
                self.sqm_value = self.calculateSqm(scidata_calibrated, exposure)

                # debayer
                scidata_debayered = self.debayer(scidata_calibrated)

                scidata_debayered_8 = self._convert_16bit_to_8bit(scidata_debayered, image_bitpix)
                #scidata_debayered_8 = scidata_debayered

            else:
                # data is probably RGB
                #logger.info('Channels: %s', pformat(scidata_uncalibrated.shape))
                self.color = True  # probably RGB data

                #INDI returns array in the wrong order for cv2
                scidata_uncalibrated = numpy.swapaxes(scidata_uncalibrated, 0, 2)
                scidata_uncalibrated = numpy.swapaxes(scidata_uncalibrated, 0, 1)
                #logger.info('Channels: %s', pformat(scidata_uncalibrated.shape))

                self.image_height, self.image_width = scidata_uncalibrated.shape[:2]

                # sqm calculation
                self.sqm_value = self.calculateSqm(scidata_uncalibrated, exposure)

                self.detectBitDepth(scidata_uncalibrated)

                scidata_bgr = cv2.cvtColor(scidata_uncalibrated, cv2.COLOR_RGB2BGR)

                scidata_debayered_8 = self._convert_16bit_to_8bit(scidata_bgr, image_bitpix)

                calibrated = False



            # adu calculate (before processing)
            adu, adu_average = self.calculate_histogram(scidata_debayered_8, exposure)


            # source extraction
            if self.night_v.value and self.config['DETECT_STARS']:
                blob_stars = self._sep.detectObjects(scidata_debayered_8)
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


            # verticle flip
            if self.config['IMAGE_FLIP_V']:
                scidata_cal_flip_v = cv2.flip(scidata_contrast, 0)
            else:
                scidata_cal_flip_v = scidata_contrast

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

            self.image_text(scidata_scaled, exposure, exp_date)


            processing_elapsed_s = time.time() - processing_start
            logger.info('Image processed in %0.4f s', processing_elapsed_s)


            self.write_status_json(exposure, exp_date, adu, adu_average, blob_stars)  # write json status file

            if self.save_images:
                latest_file, new_filename = self.write_img(scidata_scaled, exp_date, img_subdirs)

                image_entry = self._db.addImage(
                    new_filename,
                    exposure,
                    self.gain_v.value,
                    self.bin_v.value,
                    self.sensortemp_v.value,
                    adu,
                    self.target_adu_found,  # stable
                    self.moonmode_v.value,
                    night=self.night_v.value,
                    adu_roi=self.config['ADU_ROI'],
                    calibrated=calibrated,
                    sqm=self.sqm_value,
                    stars=len(blob_stars),
                )

                ### upload images
                if not self.config['FILETRANSFER']['UPLOAD_IMAGE']:
                    logger.warning('Image uploading disabled')
                    continue

                if (self.image_count % int(self.config['FILETRANSFER']['UPLOAD_IMAGE'])) != 0:
                    next_image = int(self.config['FILETRANSFER']['UPLOAD_IMAGE']) - (self.image_count % int(self.config['FILETRANSFER']['UPLOAD_IMAGE']))
                    logger.info('Next image upload in %d images (%d s)', next_image, int(self.config['EXPOSURE_PERIOD'] * next_image))
                    continue


                remote_path = Path(self.config['FILETRANSFER']['REMOTE_IMAGE_FOLDER'])
                remote_file = remote_path.joinpath(self.config['FILETRANSFER']['REMOTE_IMAGE_NAME'].format(self.config['IMAGE_FILE_TYPE']))

                # tell worker to upload file
                self.upload_q.put({
                    'local_file' : latest_file,
                    'remote_file' : remote_file,
                })

                self._db.addUploadedFlag(image_entry)


    def detectBitDepth(self, data):
        ### This will need some rework if cameras return signed int data
        max_val = numpy.amax(data)
        logger.info('Image max value: %d', int(max_val))

        if max_val > 32768:
            self.image_bit_depth = 16
        elif max_val > 16384:
            self.image_bit_depth = 15
        elif max_val > 8192:
            self.image_bit_depth = 14
        elif max_val > 4096:
            self.image_bit_depth = 13
        elif max_val > 2096:
            self.image_bit_depth = 12
        elif max_val > 1024:
            self.image_bit_depth = 11
        elif max_val > 512:
            self.image_bit_depth = 10
        elif max_val > 256:
            self.image_bit_depth = 9
        else:
            self.image_bit_depth = 8

        logger.info('Detected bit depth: %d', self.image_bit_depth)


    def write_fit(self, hdulist, exposure, exp_date, img_subdirs, image_type, image_bitpix):
        ### Do not write image files if fits are enabled
        if not self.config.get('IMAGE_SAVE_RAW'):
            return

        from .db import IndiAllSkyDbDarkFrameTable
        dbsession = self._db.session


        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.fit')

        hdulist.writeto(f_tmpfile)

        f_tmpfile.flush()
        f_tmpfile.close()


        date_str = exp_date.strftime('%Y%m%d_%H%M%S')
        if img_subdirs:
            filename = self.image_dir.joinpath(*img_subdirs).joinpath(self.filename_t.format(date_str, 'fit'))
        else:
            folder = self.getImageFolder(exp_date)
            filename = folder.joinpath(self.filename_t.format(date_str, 'fit'))


        file_dir = filename.parent
        if not file_dir.exists():
            file_dir.mkdir(mode=0o755, parents=True)

        logger.info('fit filename: %s', filename)


        if image_type == 'Dark Frame':
            try:
                dark_frame_entry = dbsession.query(IndiAllSkyDbDarkFrameTable)\
                    .filter(IndiAllSkyDbDarkFrameTable.filename == str(filename))\
                    .one()

                if filename.exists():
                    logger.warning('Removing old dark frame: %s', filename)
                    filename.unlink()

                dbsession.delete(dark_frame_entry)
                dbsession.commit()
            except NoResultFound:
                pass


            shutil.copy2(f_tmpfile.name, str(filename))  # copy file in place
            filename.chmod(0o644)


            self._db.addDarkFrame(
                filename,
                image_bitpix,
                exposure,
                self.gain_v.value,
                self.bin_v.value,
                self.sensortemp_v.value,
            )

        else:
            if filename.exists():
                logger.error('File exists: %s (skipping)', filename)
                return

            shutil.copy2(f_tmpfile.name, str(filename))  # copy file in place
            filename.chmod(0o644)


        Path(f_tmpfile.name).unlink()  # delete temp file

        logger.info('Finished writing fit file')



    def write_img(self, scidata, exp_date, img_subdirs):
        ### Do not write image files if fits are enabled
        if not self.save_images:
            return None, None


        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.{0}'.format(self.config['IMAGE_FILE_TYPE']))
        f_tmpfile.close()

        tmpfile_name = Path(f_tmpfile.name)
        tmpfile_name.unlink()  # remove tempfile, will be reused below


        # write to temporary file
        if self.config['IMAGE_FILE_TYPE'] in ('jpg', 'jpeg'):
            cv2.imwrite(str(tmpfile_name), scidata, [cv2.IMWRITE_JPEG_QUALITY, self.config['IMAGE_FILE_COMPRESSION'][self.config['IMAGE_FILE_TYPE']]])
        elif self.config['IMAGE_FILE_TYPE'] in ('png',):
            cv2.imwrite(str(tmpfile_name), scidata, [cv2.IMWRITE_PNG_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION'][self.config['IMAGE_FILE_TYPE']]])
        elif self.config['IMAGE_FILE_TYPE'] in ('tif', 'tiff'):
            cv2.imwrite(str(tmpfile_name), scidata)
        else:
            raise Exception('Unknown file type: %s', self.config['IMAGE_FILE_TYPE'])


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
        filename = folder.joinpath(*img_subdirs).joinpath(self.filename_t.format(date_str, self.config['IMAGE_FILE_TYPE']))

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


        with io.open('/tmp/indi_status.json', 'w') as f_indi_status:
            json.dump(status, f_indi_status, indent=4)
            f_indi_status.flush()
            f_indi_status.close()


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


    def calibrate(self, scidata_uncalibrated, exposure, image_bitpix):
        from .db import IndiAllSkyDbDarkFrameTable

        dbsession = self._db.session

        # dark frames are taken in increments of 5 seconds (offset +1)  1, 6, 11, 16, 21...
        dark_exposure = int(exposure) + (5 - (int(exposure) % 5)) + 1  # round up exposure for dark frame

        try:
            dark_frame_entry = dbsession.query(IndiAllSkyDbDarkFrameTable)\
                .filter(IndiAllSkyDbDarkFrameTable.camera_id == self.config['DB_CCD_ID'])\
                .filter(IndiAllSkyDbDarkFrameTable.exposure == float(dark_exposure))\
                .filter(IndiAllSkyDbDarkFrameTable.bitdepth == image_bitpix)\
                .filter(IndiAllSkyDbDarkFrameTable.gain == self.gain_v.value)\
                .filter(IndiAllSkyDbDarkFrameTable.binmode == self.bin_v.value)\
                .one()
        except NoResultFound:
            logger.warning('Dark not found: ccd%d %dbit %ds gain %d bin %d', self.config['DB_CCD_ID'], image_bitpix, int(dark_exposure), self.gain_v.value, self.bin_v.value)
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

        if self.config.get('IMAGE_GRAYSCALE'):
            debayer_algorithm = self.__cfa_gray_map[self.config['CFA_PATTERN']]
            self.color = False
        else:
            debayer_algorithm = self.__cfa_bgr_map[self.config['CFA_PATTERN']]

        scidata_bgr = cv2.cvtColor(scidata, debayer_algorithm)

        return scidata_bgr


    def image_text(self, data_bytes, exposure, exp_date):
        # not sure why these are returned as tuples
        fontFace = getattr(cv2, self.config['TEXT_PROPERTIES']['FONT_FACE']),
        lineType = getattr(cv2, self.config['TEXT_PROPERTIES']['FONT_AA']),

        sunOrbX, sunOrbY = self.getOrbXY(ephem.Sun())

        # Sun outline
        cv2.circle(
            img=data_bytes,
            center=(sunOrbX, sunOrbY),
            radius=self.config['ORB_PROPERTIES']['RADIUS'],
            color=(0, 0, 0),
            thickness=cv2.FILLED,
        )
        # Draw sun
        cv2.circle(
            img=data_bytes,
            center=(sunOrbX, sunOrbY),
            radius=self.config['ORB_PROPERTIES']['RADIUS'] - 1,
            color=self.config['ORB_PROPERTIES']['SUN_COLOR'],
            thickness=cv2.FILLED,
        )


        moonOrbX, moonOrbY = self.getOrbXY(ephem.Moon())

        # Moon outline
        cv2.circle(
            img=data_bytes,
            center=(moonOrbX, moonOrbY),
            radius=self.config['ORB_PROPERTIES']['RADIUS'],
            color=(0, 0, 0),
            thickness=cv2.FILLED,
        )
        # Draw moon
        cv2.circle(
            img=data_bytes,
            center=(moonOrbX, moonOrbY),
            radius=self.config['ORB_PROPERTIES']['RADIUS'] - 1,
            color=self.config['ORB_PROPERTIES']['MOON_COLOR'],
            thickness=cv2.FILLED,
        )

        #cv2.rectangle(
        #    img=data_bytes,
        #    pt1=(0, 0),
        #    pt2=(350, 125),
        #    color=(0, 0, 0),
        #    thickness=cv2.FILLED,
        #)

        line_offset = 0

        if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
            cv2.putText(
                img=data_bytes,
                text=exp_date.strftime('%Y%m%d %H:%M:%S'),
                org=(self.config['TEXT_PROPERTIES']['FONT_X'], self.config['TEXT_PROPERTIES']['FONT_Y'] + line_offset),
                fontFace=fontFace[0],
                color=(0, 0, 0),
                lineType=lineType[0],
                fontScale=self.config['TEXT_PROPERTIES']['FONT_SCALE'],
                thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'] + 1,
            )  # black outline
        cv2.putText(
            img=data_bytes,
            text=exp_date.strftime('%Y%m%d %H:%M:%S'),
            org=(self.config['TEXT_PROPERTIES']['FONT_X'], self.config['TEXT_PROPERTIES']['FONT_Y'] + line_offset),
            fontFace=fontFace[0],
            color=self.config['TEXT_PROPERTIES']['FONT_COLOR'],
            lineType=lineType[0],
            fontScale=self.config['TEXT_PROPERTIES']['FONT_SCALE'],
            thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'],
        )


        line_offset += self.config['TEXT_PROPERTIES']['FONT_HEIGHT']

        if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
            cv2.putText(
                img=data_bytes,
                text='Exposure {0:0.6f}'.format(exposure),
                org=(self.config['TEXT_PROPERTIES']['FONT_X'], self.config['TEXT_PROPERTIES']['FONT_Y'] + line_offset),
                fontFace=fontFace[0],
                color=(0, 0, 0),
                lineType=lineType[0],
                fontScale=self.config['TEXT_PROPERTIES']['FONT_SCALE'],
                thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'] + 1,
            )  # black outline
        cv2.putText(
            img=data_bytes,
            text='Exposure {0:0.6f}'.format(exposure),
            org=(self.config['TEXT_PROPERTIES']['FONT_X'], self.config['TEXT_PROPERTIES']['FONT_Y'] + line_offset),
            fontFace=fontFace[0],
            color=self.config['TEXT_PROPERTIES']['FONT_COLOR'],
            lineType=lineType[0],
            fontScale=self.config['TEXT_PROPERTIES']['FONT_SCALE'],
            thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'],
        )


        line_offset += self.config['TEXT_PROPERTIES']['FONT_HEIGHT']

        if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
            cv2.putText(
                img=data_bytes,
                text='Gain {0:d}'.format(self.gain_v.value),
                org=(self.config['TEXT_PROPERTIES']['FONT_X'], self.config['TEXT_PROPERTIES']['FONT_Y'] + line_offset),
                fontFace=fontFace[0],
                color=(0, 0, 0),
                lineType=lineType[0],
                fontScale=self.config['TEXT_PROPERTIES']['FONT_SCALE'],
                thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'] + 1,
            )  # black outline
        cv2.putText(
            img=data_bytes,
            text='Gain {0:d}'.format(self.gain_v.value),
            org=(self.config['TEXT_PROPERTIES']['FONT_X'], self.config['TEXT_PROPERTIES']['FONT_Y'] + line_offset),
            fontFace=fontFace[0],
            color=self.config['TEXT_PROPERTIES']['FONT_COLOR'],
            lineType=lineType[0],
            fontScale=self.config['TEXT_PROPERTIES']['FONT_SCALE'],
            thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'],
        )


        # Add temp if value is set, will be skipped if the temp is exactly 0
        if self.sensortemp_v.value:
            line_offset += self.config['TEXT_PROPERTIES']['FONT_HEIGHT']

            if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
                cv2.putText(
                    img=data_bytes,
                    text='Temp {0:0.1f}'.format(self.sensortemp_v.value),
                    org=(self.config['TEXT_PROPERTIES']['FONT_X'], self.config['TEXT_PROPERTIES']['FONT_Y'] + line_offset),
                    fontFace=fontFace[0],
                    color=(0, 0, 0),
                    lineType=lineType[0],
                    fontScale=self.config['TEXT_PROPERTIES']['FONT_SCALE'],
                    thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'] + 1,
                )  # black outline
            cv2.putText(
                img=data_bytes,
                text='Temp {0:0.1f}'.format(self.sensortemp_v.value),
                org=(self.config['TEXT_PROPERTIES']['FONT_X'], self.config['TEXT_PROPERTIES']['FONT_Y'] + line_offset),
                fontFace=fontFace[0],
                color=self.config['TEXT_PROPERTIES']['FONT_COLOR'],
                lineType=lineType[0],
                fontScale=self.config['TEXT_PROPERTIES']['FONT_SCALE'],
                thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'],
            )

        # Add moon mode indicator
        if self.moonmode_v.value:
            line_offset += self.config['TEXT_PROPERTIES']['FONT_HEIGHT']

            if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
                cv2.putText(
                    img=data_bytes,
                    text='* Moon Mode {0:0.1f}% *'.format(self.moonmode_v.value),
                    org=(self.config['TEXT_PROPERTIES']['FONT_X'], self.config['TEXT_PROPERTIES']['FONT_Y'] + line_offset),
                    fontFace=fontFace[0],
                    color=(0, 0, 0),
                    lineType=lineType[0],
                    fontScale=self.config['TEXT_PROPERTIES']['FONT_SCALE'],
                    thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'] + 1,
                )  # black outline
            cv2.putText(
                img=data_bytes,
                text='* Moon Mode {0:0.1f}% *'.format(self.moonmode_v.value),
                org=(self.config['TEXT_PROPERTIES']['FONT_X'], self.config['TEXT_PROPERTIES']['FONT_Y'] + line_offset),
                fontFace=fontFace[0],
                color=self.config['TEXT_PROPERTIES']['FONT_COLOR'],
                lineType=lineType[0],
                fontScale=self.config['TEXT_PROPERTIES']['FONT_SCALE'],
                thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'],
            )


    def calculate_histogram(self, data_bytes, exposure):
        if self.config['ADU_ROI']:
            logger.warning('Calculating ADU from RoI')
            # divide the coordinates by binning value
            x1 = int(self.config['ADU_ROI'][0] / self.bin_v.value)
            y1 = int(self.config['ADU_ROI'][1] / self.bin_v.value)
            x2 = int(self.config['ADU_ROI'][2] / self.bin_v.value)
            y2 = int(self.config['ADU_ROI'][3] / self.bin_v.value)

        else:
            logger.warning('Using central ROI for ADU calculations')
            x1 = int((self.image_width / 2) - (self.image_width / 3))
            y1 = int((self.image_height / 2) - (self.image_height / 3))
            x2 = int((self.image_width / 2) + (self.image_width / 3))
            y2 = int((self.image_height / 2) + (self.image_height / 3))


        scidata = data_bytes[
            y1:y2,
            x1:x2,
        ]


        if not self.color:
            m_avg = cv2.mean(scidata)[0]

            logger.info('Greyscale mean: %0.2f', m_avg)

            adu = m_avg
        else:
            b, g, r = cv2.split(scidata)
            b_avg = cv2.mean(b)[0]
            g_avg = cv2.mean(g)[0]
            r_avg = cv2.mean(r)[0]

            logger.info('B mean: %0.2f', b_avg)
            logger.info('G mean: %0.2f', g_avg)
            logger.info('R mean: %0.2f', r_avg)

            # Find the gain of each channel
            adu = (b_avg + g_avg + r_avg) / 3

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

        if not self.color:
            # mono
            return clahe.apply(data_bytes)

        # color, apply to luminance
        lab = cv2.cvtColor(data_bytes, cv2.COLOR_BGR2LAB)

        l, a, b = cv2.split(lab)

        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        cl = clahe.apply(l)

        new_lab = cv2.merge((cl, a, b))

        return cv2.cvtColor(new_lab, cv2.COLOR_LAB2BGR)


    def equalizeHistogram(self, data_bytes):
        if not self.color:
            # mono
            return cv2.equalizeHist(data_bytes)

        # color, apply to luminance
        lab = cv2.cvtColor(data_bytes, cv2.COLOR_BGR2LAB)

        l, a, b = cv2.split(lab)

        cl = cv2.equalizeHist(l)

        new_lab = cv2.merge((cl, a, b))

        return cv2.cvtColor(new_lab, cv2.COLOR_LAB2BGR)


    def equalizeHistogramColor(self, data_bytes):
        if not self.color:
            return data_bytes

        ycrcb_img = cv2.cvtColor(data_bytes, cv2.COLOR_BGR2YCrCb)
        ycrcb_img[:, :, 0] = cv2.equalizeHist(ycrcb_img[:, :, 0])
        return cv2.cvtColor(ycrcb_img, cv2.COLOR_YCrCb2BGR)


    def white_balance_bgr(self, data_bytes):
        if not self.color:
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
        if not self.color:
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
        logger.info('Scaling image by %d%%', self.config['IMAGE_SCALE'])
        new_width = int(self.image_width * self.config['IMAGE_SCALE'] / 100.0)
        new_height = int(self.image_height * self.config['IMAGE_SCALE'] / 100.0)

        logger.info('New size: %d x %d', new_width, new_height)
        self.image_width = new_width
        self.image_height = new_height

        return cv2.resize(data_bytes, (new_width, new_height), interpolation=cv2.INTER_AREA)


    def _convert_16bit_to_8bit(self, data_bytes_16, image_bitpix):
        if image_bitpix == 8:
            return data_bytes_16

        logger.info('Resampling image from %d to 8 bits', image_bitpix)

        div_factor = int((2 ** self.image_bit_depth) / 255)

        return (data_bytes_16 / div_factor).astype('uint8')


    def calculateSkyObject(self, skyObj):
        obs = ephem.Observer()
        obs.lon = str(self.config['LOCATION_LONGITUDE'])
        obs.lat = str(self.config['LOCATION_LATITUDE'])
        obs.date = datetime.utcnow()  # ephem expects UTC dates
        #obs.date = datetime.utcnow() - timedelta(hours=13)  # testing

        skyObj.compute(obs)

        return obs


    def getOrbXY(self, skyObj):
        obs = self.calculateSkyObject(skyObj)

        ha_rad = obs.sidereal_time() - skyObj.ra
        ha_deg = math.degrees(ha_rad)

        if ha_deg < -180:
            ha_deg = 360 + ha_deg
        elif ha_deg > 180:
            ha_deg = -360 + ha_deg
        else:
            pass

        logger.info('%s hour angle: %0.2f', skyObj.name, ha_deg)

        abs_ha_deg = abs(ha_deg)
        perimeter_half = self.image_width + self.image_height

        mapped_ha_deg = int(self.remap(abs_ha_deg, 0, 180, 0, perimeter_half))
        #logger.info('Mapped hour angle: %d', mapped_ha_deg)

        ### The image perimeter is mapped to the hour angle for the X,Y coordinates
        if mapped_ha_deg < (self.image_width / 2) and ha_deg < 0:
            #logger.info('Top right')
            x = (self.image_width / 2) + mapped_ha_deg
            y = 0
        elif mapped_ha_deg < (self.image_width / 2) and ha_deg > 0:
            #logger.info('Top left')
            x = (self.image_width / 2) - mapped_ha_deg
            y = 0
        elif mapped_ha_deg > ((self.image_width / 2) + self.image_height) and ha_deg < 0:
            #logger.info('Bottom right')
            x = self.image_width - (mapped_ha_deg - (self.image_height + (self.image_width / 2)))
            y = self.image_height
        elif mapped_ha_deg > ((self.image_width / 2) + self.image_height) and ha_deg > 0:
            #logger.info('Bottom left')
            x = mapped_ha_deg - (self.image_height + (self.image_width / 2))
            y = self.image_height
        elif ha_deg < 0:
            #logger.info('Right')
            x = self.image_width
            y = mapped_ha_deg - (self.image_width / 2)
        elif ha_deg > 0:
            #logger.info('Left')
            x = 0
            y = mapped_ha_deg - (self.image_width / 2)
        else:
            raise Exception('This cannot happen')


        #logger.info('Orb: %0.2f x %0.2f', x, y)

        return int(x), int(y)


    def remap(self, x, in_min, in_max, out_min, out_max):
        return (float(x) - float(in_min)) * (float(out_max) - float(out_min)) / (float(in_max) - float(in_min)) + float(out_min)


    def calculateSqm(self, data, exposure):
        sqm_value = self._sqm.calculate(data, exposure, self.gain_v.value)
        return sqm_value

