import io
import json
from pathlib import Path
from datetime import datetime
from datetime import timedelta
import functools
import tempfile
import shutil
import copy
#import math

import ephem

from multiprocessing import Process
#from threading import Thread
import multiprocessing

from astropy.io import fits
import cv2
import numpy


logger = multiprocessing.get_logger()


class ImageProcessWorker(Process):
    def __init__(self, idx, config, image_q, upload_q, exposure_v, gain_v, sensortemp_v, night_v, save_fits=False, save_images=True):
        super(ImageProcessWorker, self).__init__()

        #self.threadID = idx
        self.name = 'ImageProcessWorker{0:03d}'.format(idx)

        self.config = config
        self.image_q = image_q
        self.upload_q = upload_q
        self.exposure_v = exposure_v
        self.gain_v = gain_v
        self.sensortemp_v = sensortemp_v
        self.night_v = night_v

        self.last_exposure = None

        self.filename_t = '{0:s}.{1:s}'
        self.save_fits = save_fits
        self.save_images = save_images

        self.target_adu_found = False
        self.current_adu_target = 0
        self.hist_adu = []
        self.target_adu = float(self.config['TARGET_ADU'])
        self.target_adu_dev = float(self.config['TARGET_ADU_DEV'])

        self.image_count = 0
        self.image_width = 0
        self.image_height = 0

        self.base_dir = Path(__file__).parent.parent.absolute()


    def run(self):
        while True:
            i_dict = self.image_q.get()

            if i_dict.get('stop'):
                return

            imgdata = i_dict['imgdata']
            exp_date = i_dict['exp_date']
            filename_t = i_dict.get('filename_t')

            if filename_t:
                self.filename_t = filename_t

            self.image_count += 1

            # Save last exposure value for picture
            self.last_exposure = self.exposure_v.value

            ### OpenCV ###
            blobfile = io.BytesIO(imgdata)
            hdulist = fits.open(blobfile)
            scidata_uncalibrated = hdulist[0].data

            self.image_height, self.image_width = scidata_uncalibrated.shape

            if self.save_fits:
                self.write_fit(hdulist, exp_date)

            scidata_calibrated = self.calibrate(scidata_uncalibrated)
            scidata_color = self.debayer(scidata_calibrated)

            #scidata_blur = self.median_blur(scidata_color)
            scidata_blur = scidata_color

            adu, adu_average = self.calculate_histogram(scidata_color)  # calculate based on pre_blur data

            #scidata_denoise = cv2.fastNlMeansDenoisingColored(
            #    scidata_color,
            #    None,
            #    h=3,
            #    hColor=3,
            #    templateWindowSize=7,
            #    searchWindowSize=21,
            #)

            self.image_text(scidata_blur, exp_date)

            self.write_status_json(exp_date, adu, adu_average)  # write json status file

            if self.save_images:
                latest_file = self.write_img(scidata_blur, exp_date)

                if not self.config['FILETRANSFER']['UPLOAD_IMAGE']:
                    logger.warning('Image uploading disabled')
                    continue

                if (self.image_count % int(self.config['FILETRANSFER']['UPLOAD_IMAGE'])) != 0:
                    # upload every X image
                    continue


                remote_path = Path(self.config['FILETRANSFER']['REMOTE_IMAGE_FOLDER'])
                remote_file = remote_path.joinpath(self.config['FILETRANSFER']['REMOTE_IMAGE_NAME'].format(self.config['IMAGE_FILE_TYPE']))

                # tell worker to upload file
                self.upload_q.put({ 'local_file' : latest_file, 'remote_file' : remote_file })




    def write_fit(self, hdulist, exp_date):
        ### Do not write image files if fits are enabled
        if not self.save_fits:
            return


        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.fit')

        hdulist.writeto(f_tmpfile)

        f_tmpfile.flush()
        f_tmpfile.close()


        date_str = exp_date.strftime('%Y%m%d_%H%M%S')
        filename = self.base_dir.joinpath(self.filename_t.format(date_str, 'fit'))

        logger.info('fit filename: %s', filename)

        if filename.exists():
            logger.error('File exists: %s (skipping)', filename)
            return

        shutil.copy2(f_tmpfile.name, str(filename))  # copy file in place
        filename.chmod(0o644)

        Path(f_tmpfile.name).unlink()  # delete temp file

        logger.info('Finished writing fit file')


    def write_img(self, scidata, exp_date):
        ### Do not write image files if fits are enabled
        if not self.save_images:
            return


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
        latest_file = self.base_dir.joinpath('images', 'latest.{0:s}'.format(self.config['IMAGE_FILE_TYPE']))

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
            return latest_file


        ### Write the timelapse file
        folder = self.getImageFolder(exp_date)

        date_str = exp_date.strftime('%Y%m%d_%H%M%S')
        filename = folder.joinpath(self.filename_t.format(date_str, self.config['IMAGE_FILE_TYPE']))

        logger.info('Image filename: %s', filename)

        if filename.exists():
            logger.error('File exists: %s (skipping)', filename)
            return

        shutil.copy2(str(tmpfile_name), str(filename))
        filename.chmod(0o644)


        ### Cleanup
        tmpfile_name.unlink()

        logger.info('Finished writing files')

        return latest_file


    def write_status_json(self, exp_date, adu, adu_average):
        status = {
            'name'                : 'indi_json',
            'class'               : 'ccd',
            'device'              : self.config['CCD_NAME'],
            'night'               : self.night_v.value,
            'temp'                : self.sensortemp_v.value,
            'gain'                : self.gain_v.value,
            'exposure'            : self.last_exposure,
            'stable_exposure'     : int(self.target_adu_found),
            'target_adu'          : self.target_adu,
            'current_adu_target'  : self.current_adu_target,
            'current_adu'         : adu,
            'adu_average'         : adu_average,
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

        day_folder = self.base_dir.joinpath('images', '{0:s}'.format(day_ref.strftime('%Y%m%d')), timeofday_str)
        if not day_folder.exists():
            day_folder.mkdir(parents=True)
            day_folder.chmod(0o755)

        hour_folder = day_folder.joinpath('{0:s}'.format(hour_str))
        if not hour_folder.exists():
            hour_folder.mkdir()
            hour_folder.chmod(0o755)

        return hour_folder


    def calibrate(self, scidata_uncalibrated):

        dark_file = self.base_dir.joinpath('darks', 'dark_{0:d}s_gain{1:d}.fit'.format(int(self.last_exposure), self.gain_v.value))

        if not dark_file.exists():
            logger.warning('Dark not found: %s', dark_file)
            return scidata_uncalibrated

        with fits.open(str(dark_file)) as dark:
            scidata = cv2.subtract(scidata_uncalibrated, dark[0].data)
            del dark[0].data   # make sure memory is freed

        return scidata



    def debayer(self, scidata):
        if not self.config['IMAGE_DEBAYER']:
            return scidata

        bayer_pattern = getattr(cv2, self.config['IMAGE_DEBAYER'])
        ###
        #scidata_rgb = cv2.cvtColor(scidata, cv2.COLOR_BayerGR2RGB)
        scidata_rgb = cv2.cvtColor(scidata, bayer_pattern)
        ###

        #scidata_rgb = self._convert_GRBG_to_RGB_8bit(scidata)

        #scidata_wb = self.white_balance2(scidata_rgb)
        scidata_wb = scidata_rgb

        if not self.night_v.value and self.config['DAYTIME_CONTRAST_ENHANCE']:
            # Contrast enhancement during the day
            scidata_contrast = self.contrast_clahe(scidata_wb)
        else:
            scidata_contrast = scidata_wb


        #if self.roi is not None:
        #    scidata = scidata[self.roi[1]:self.roi[1]+self.roi[3], self.roi[0]:self.roi[0]+self.roi[2]]
        #hdulist[0].data = scidata

        return scidata_contrast


    def image_text(self, data_bytes, exp_date):
        # not sure why these are returned as tuples
        fontFace = getattr(cv2, self.config['TEXT_PROPERTIES']['FONT_FACE']),
        lineType = getattr(cv2, self.config['TEXT_PROPERTIES']['FONT_AA']),

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
                text='Exposure {0:0.6f}'.format(self.last_exposure),
                org=(self.config['TEXT_PROPERTIES']['FONT_X'], self.config['TEXT_PROPERTIES']['FONT_Y'] + line_offset),
                fontFace=fontFace[0],
                color=(0, 0, 0),
                lineType=lineType[0],
                fontScale=self.config['TEXT_PROPERTIES']['FONT_SCALE'],
                thickness=self.config['TEXT_PROPERTIES']['FONT_THICKNESS'] + 1,
            )  # black outline
        cv2.putText(
            img=data_bytes,
            text='Exposure {0:0.6f}'.format(self.last_exposure),
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


    def calculate_histogram(self, data_bytes):
        if not self.config['IMAGE_DEBAYER']:
            m_avg = cv2.mean(data_bytes)[0]

            logger.info('Greyscale mean: %0.2f', m_avg)

            adu = m_avg
        else:
            r, g, b = cv2.split(data_bytes)
            r_avg = cv2.mean(r)[0]
            g_avg = cv2.mean(g)[0]
            b_avg = cv2.mean(b)[0]

            logger.info('R mean: %0.2f', r_avg)
            logger.info('G mean: %0.2f', g_avg)
            logger.info('B mean: %0.2f', b_avg)

            # Find the gain of each channel
            adu = (r_avg + g_avg + b_avg) / 3

        if adu <= 0.0:
            # ensure we do not divide by zero
            logger.warning('Zero average, setting a default of 0.1')
            adu = 0.1


        logger.info('Brightness average: %0.2f', adu)


        if self.exposure_v.value < 0.005:
            # expand the allowed deviation for very short exposures to prevent flashing effect due to exposure flapping
            target_adu_min = self.target_adu - (self.target_adu_dev * 1.0)
            target_adu_max = self.target_adu + (self.target_adu_dev * 1.0)
            current_adu_target_min = self.current_adu_target - (self.target_adu_dev * 1.0)
            current_adu_target_max = self.current_adu_target + (self.target_adu_dev * 1.0)
            exp_scale_factor = 1.0  # scale exposure calculation
            history_max_vals = 6  # number of entries to use to calculate average
        else:
            target_adu_min = self.target_adu - (self.target_adu_dev * 1.0)
            target_adu_max = self.target_adu + (self.target_adu_dev * 1.0)
            current_adu_target_min = self.current_adu_target - (self.target_adu_dev * 1.0)
            current_adu_target_max = self.current_adu_target + (self.target_adu_dev * 1.0)
            exp_scale_factor = 1.0  # scale exposure calculation
            history_max_vals = 6  # number of entries to use to calculate average


        if not self.target_adu_found:
            self.recalculate_exposure(adu, target_adu_min, target_adu_max, exp_scale_factor)
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


    def recalculate_exposure(self, adu, target_adu_min, target_adu_max, exp_scale_factor):

        # Until we reach a good starting point, do not calculate a moving average
        if adu <= target_adu_max and adu >= target_adu_min:
            logger.warning('Found target value for exposure')
            self.current_adu_target = copy.copy(adu)
            self.target_adu_found = True
            self.hist_adu = []
            return


        current_exposure = self.exposure_v.value

        # Scale the exposure up and down based on targets
        if adu > target_adu_max:
            new_exposure = current_exposure / (( adu / self.target_adu ) * exp_scale_factor)
        elif adu < target_adu_min:
            new_exposure = current_exposure * (( self.target_adu / adu ) * exp_scale_factor)
        else:
            new_exposure = current_exposure



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
        lab = cv2.cvtColor(data_bytes, cv2.COLOR_RGB2LAB)

        l, a, b = cv2.split(lab)

        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        cl = clahe.apply(l)

        new_lab = cv2.merge((cl, a, b))

        new_data = cv2.cvtColor(new_lab, cv2.COLOR_LAB2RGB)
        return new_data


    def white_balance2(self, data_bytes):
        ### This seems to work
        r, g, b = cv2.split(data_bytes)
        r_avg = cv2.mean(r)[0]
        g_avg = cv2.mean(g)[0]
        b_avg = cv2.mean(b)[0]

        # Find the gain of each channel
        k = (r_avg + g_avg + b_avg) / 3
        kr = k / r_avg
        kg = k / g_avg
        kb = k / b_avg

        r = cv2.addWeighted(src1=r, alpha=kr, src2=0, beta=0, gamma=0)
        g = cv2.addWeighted(src1=g, alpha=kg, src2=0, beta=0, gamma=0)
        b = cv2.addWeighted(src1=b, alpha=kb, src2=0, beta=0, gamma=0)

        balance_img = cv2.merge([b, g, r])
        return balance_img


    def median_blur(self, data_bytes):
        data_blur = cv2.medianBlur(data_bytes, ksize=3)
        return data_blur


    def _convert_GRBG_to_RGB_8bit(self, data_bytes):
        data_bytes = numpy.frombuffer(data_bytes, dtype=numpy.uint8)
        even = data_bytes[0::2]
        odd = data_bytes[1::2]
        # Convert bayer16 to bayer8
        bayer8_image = (even >> 4) | (odd << 4)
        bayer8_image = bayer8_image.reshape((1080, 1920))
        # Use OpenCV to convert Bayer GRBG to RGB
        return cv2.cvtColor(bayer8_image, cv2.COLOR_BayerGR2RGB)


    def calculateSkyObject(self, so):
        obs = ephem.Observer()
        obs.lon = str(self.config['LOCATION_LONGITUDE'])
        obs.lat = str(self.config['LOCATION_LATITUDE'])
        obs.date = datetime.utcnow()  # ephem expects UTC dates

        so.compute(obs)


    def getBoxXY(self, so):
        pass


