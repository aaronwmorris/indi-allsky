import io
from pathlib import Path
from datetime import timedelta
import functools
import tempfile
import shutil


from multiprocessing import Process
#from threading import Thread
import multiprocessing

from astropy.io import fits
import cv2
import numpy


logger = multiprocessing.get_logger()


class ImageProcessWorker(Process):
    def __init__(self, idx, config, image_q, upload_q, exposure_v, gain_v, sensortemp_v, night_v, writefits=False):
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
        self.writefits = writefits

        self.stable_mean = False
        self.scale_factor = 1.0
        self.hist_mean = []
        self.target_mean = float(self.config['TARGET_MEAN'])
        self.target_mean_dev = float(self.config['TARGET_MEAN_DEV'])
        self.target_mean_min = self.target_mean - (self.target_mean * (self.target_mean_dev / 100.0))
        self.target_mean_max = self.target_mean + (self.target_mean * (self.target_mean_dev / 100.0))

        self.image_count = 0

        self.base_dir = Path(__file__).parent.parent.absolute()


    def run(self):
        while True:
            imgdata, exp_date, filename_t_override = self.image_q.get()

            if not imgdata:
                return

            if filename_t_override:
                self.filename_t = filename_t_override

            self.image_count += 1

            # Save last exposure value for picture
            self.last_exposure = self.exposure_v.value

            ### OpenCV ###
            blobfile = io.BytesIO(imgdata)
            hdulist = fits.open(blobfile)
            scidata_uncalibrated = hdulist[0].data

            if self.writefits:
                self.write_fit(hdulist, exp_date)

            scidata_calibrated = self.calibrate(scidata_uncalibrated)
            scidata_color = self.debayer(scidata_calibrated)

            #scidata_blur = self.median_blur(scidata_color)
            scidata_blur = scidata_color

            self.calculate_histogram(scidata_color)  # calculate based on pre_blur data

            #scidata_denoise = cv2.fastNlMeansDenoisingColored(
            #    scidata_color,
            #    None,
            #    h=3,
            #    hColor=3,
            #    templateWindowSize=7,
            #    searchWindowSize=21,
            #)

            self.image_text(scidata_blur, exp_date)
            latest_file = self.write_img(scidata_blur, exp_date)


            if latest_file:
                if not self.config['FILETRANSFER']['UPLOAD_IMAGE']:
                    logger.warning('Image uploading disabled')
                    continue

                if (self.image_count % int(self.config['FILETRANSFER']['UPLOAD_IMAGE'])) != 0:
                    # upload every X image
                    continue


                remote_path = Path(self.config['FILETRANSFER']['REMOTE_IMAGE_FOLDER'])
                remote_file = remote_path.joinpath(self.config['FILETRANSFER']['REMOTE_IMAGE_NAME'].format(self.config['IMAGE_FILE_TYPE']))

                # tell worker to upload file
                self.upload_q.put((latest_file, remote_file))




    def write_fit(self, hdulist, exp_date):
        ### Do not write image files if fits are enabled
        if not self.writefits:
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
        if self.writefits:
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


    def getImageFolder(self, exp_date):
        # images should be written to previous day's folder until noon
        day_ref = exp_date - timedelta(hours=12)
        hour_str = exp_date.strftime('%d_%H')

        day_folder = self.base_dir.joinpath('images', '{0:s}'.format(day_ref.strftime('%Y%m%d')))
        if not day_folder.exists():
            day_folder.mkdir()
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

            k = m_avg
        else:
            r, g, b = cv2.split(data_bytes)
            r_avg = cv2.mean(r)[0]
            g_avg = cv2.mean(g)[0]
            b_avg = cv2.mean(b)[0]

            logger.info('R mean: %0.2f', r_avg)
            logger.info('G mean: %0.2f', g_avg)
            logger.info('B mean: %0.2f', b_avg)

            # Find the gain of each channel
            k = (r_avg + g_avg + b_avg) / 3

        if k <= 0.0:
            # ensure we do not divide by zero
            logger.warning('Zero average, setting a default of 0.1')
            k = 0.1


        logger.info('Brightness average: %0.2f', k)


        if not self.stable_mean:
            self.recalculate_exposure(k)
            return


        self.hist_mean.insert(0, k)
        self.hist_mean = self.hist_mean[:5]  # only need last 5 values

        k_moving_average = functools.reduce(lambda a, b: a + b, self.hist_mean) / len(self.hist_mean)
        logger.info('Moving average: %0.2f', k_moving_average)

        if k_moving_average > self.target_mean_max:
            logger.warning('Moving average exceeded target by %d%%, recalculating next exposure', int(self.target_mean_dev))
            self.stable_mean = False
        elif k_moving_average < self.target_mean_min:
            logger.warning('Moving average exceeded target by %d%%, recalculating next exposure', int(self.target_mean_dev))
            self.stable_mean = False


    def recalculate_exposure(self, k):

        # Until we reach a good starting point, do not calculate a moving average
        if k <= self.target_mean_max and k >= self.target_mean_min:
            logger.warning('Found stable mean for exposure')
            self.stable_mean = True
            [self.hist_mean.insert(0, k) for x in range(50)]  # populate 50 entries, reduced later
            return


        current_exposure = self.exposure_v.value

        # Scale the exposure up and down based on targets
        if k > self.target_mean_max:
            new_exposure = current_exposure / (( k / self.target_mean ) * self.scale_factor)
        elif k < self.target_mean_min:
            new_exposure = current_exposure * (( self.target_mean / k ) * self.scale_factor)
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



