#!/usr/bin/env python

import sys
import time
import logging
import io
import json
from pathlib import Path
from datetime import datetime
from datetime import timedelta
import copy
import functools
import math
import argparse
import subprocess
import tempfile
import shutil
import signal

import ephem

from multiprocessing import Process
from multiprocessing import Pipe
from multiprocessing import Queue
from multiprocessing import Value
import multiprocessing

import PyIndi
from astropy.io import fits
import cv2
import numpy


logger = multiprocessing.get_logger()
LOG_FORMATTER = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s %(funcName)s() #%(lineno)d: %(message)s')
LOG_HANDLER = logging.StreamHandler()
LOG_HANDLER.setFormatter(LOG_FORMATTER)
LOG_LEVEL = logging.INFO
logger.addHandler(LOG_HANDLER)
logger.setLevel(LOG_LEVEL)


class IndiClient(PyIndi.BaseClient):
    def __init__(self, config, indiblob_status_send, img_q):
        super(IndiClient, self).__init__()

        self.config = config
        self.indiblob_status_send = indiblob_status_send
        self.img_q = img_q

        self._filename_t = '{0:s}'

        logger.info('creating an instance of IndiClient')

    @property
    def filename_t(self):
        return self._filename_t

    @filename_t.setter
    def filename_t(self, new_filename_t):
        self._filename_t = new_filename_t

    def newDevice(self, d):
        logger.info("new device %s", d.getDeviceName())

    def newProperty(self, p):
        logger.info("new property %s for device %s", p.getName(), p.getDeviceName())

    def removeProperty(self, p):
        logger.info("remove property %s for device %s", p.getName(), p.getDeviceName())


    def newBLOB(self, bp):
        logger.info("new BLOB %s", bp.name)
        start = time.time()

        ### get image data
        imgdata = bp.getblobdata()

        elapsed_s = time.time() - start
        logger.info('Blob downloaded in %0.4f s', elapsed_s)

        self.indiblob_status_send.send(True)  # Notify main process next exposure may begin

        exp_date = datetime.now()

        ### process data in worker
        self.img_q.put((imgdata, exp_date, self._filename_t))


    def newSwitch(self, svp):
        logger.info("new Switch %s for device %s", svp.name, svp.device)

    def newNumber(self, nvp):
        #logger.info("new Number %s for device %s", nvp.name, nvp.device)
        pass

    def newText(self, tvp):
        logger.info("new Text %s for device %s", tvp.name, tvp.device)

    def newLight(self, lvp):
        logger.info("new Light %s for device %s", lvp.name, lvp.device)

    def newMessage(self, d, m):
        logger.info("new Message %s", d.messageQueue(m))

    def serverConnected(self):
        logger.info("Server connected (%s:%d)", self.getHost(), self.getPort())

    def serverDisconnected(self, code):
        logger.info("Server disconnected (exit code = %d, %s, %d", code, str(self.getHost()), self.getPort())


class ImageProcessWorker(Process):
    def __init__(self, idx, config, img_q, exposure_v, gain_v, sensortemp_v, night_v, writefits=False):
        super(ImageProcessWorker, self).__init__()

        self.config = config
        self.img_q = img_q
        self.exposure_v = exposure_v
        self.gain_v = gain_v
        self.sensortemp_v = sensortemp_v
        self.night_v = night_v

        self.last_exposure = None

        self.filename_t = '{0:s}'
        self.writefits = writefits

        self.stable_mean = False
        self.scale_factor = 1.0
        self.hist_mean = []
        self.target_mean = float(self.config['TARGET_MEAN'])
        self.target_mean_dev = float(self.config['TARGET_MEAN_DEV'])
        self.target_mean_min = self.target_mean - (self.target_mean * (self.target_mean_dev / 100.0))
        self.target_mean_max = self.target_mean + (self.target_mean * (self.target_mean_dev / 100.0))

        self.base_dir = Path(__file__).parent.absolute()

        self.name = 'ImageProcessWorker{0:03d}'.format(idx)


    def run(self):
        while True:
            imgdata, exp_date, filename_override = self.img_q.get()

            if not imgdata:
                return

            if filename_override:
                self.filename_t = filename_override

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
            self.write_img(scidata_blur, exp_date)



    def write_fit(self, hdulist, exp_date):
        ### Do not write image files if fits are enabled
        if not self.writefits:
            return


        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.fit')

        hdulist.writeto(f_tmpfile)

        f_tmpfile.flush()
        f_tmpfile.close()


        date_str = exp_date.strftime('%Y%m%d_%H%M%S')

        fitname_t = '{0:s}/{1:s}.fit'.format(str(self.base_dir), self.filename_t)
        filename = Path(fitname_t.format(date_str))

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
            return


        ### Write the timelapse file
        folder = self.getImageFolder(exp_date)

        date_str = exp_date.strftime('%Y%m%d_%H%M%S')

        imgname_t = '{0:s}/{1:s}.{2:s}'.format(str(folder), self.filename_t, self.config['IMAGE_FILE_TYPE'])
        filename = Path(imgname_t.format(date_str))

        if filename.exists():
            logger.error('File exists: %s (skipping)', filename)
            return

        shutil.copy2(str(tmpfile_name), str(filename))
        filename.chmod(0o644)


        ### Cleanup
        tmpfile_name.unlink()

        logger.info('Finished writing files')


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

        dark_file = self.base_dir.joinpath('dark_{0:d}s_gain{1:d}.fit'.format(int(self.last_exposure), self.gain_v.value))

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



class IndiTimelapse(object):

    def __init__(self, f_config_file):
        self.config = json.loads(f_config_file.read())
        f_config_file.close()

        self.config_file = f_config_file.name

        self.img_q = Queue()
        self.indiblob_status_receive, self.indiblob_status_send = Pipe(duplex=False)
        self.indiclient = None
        self.device = None
        self.exposure_v = Value('f', copy.copy(self.config['CCD_EXPOSURE_DEF']))
        self.gain_v = Value('i', copy.copy(self.config['INDI_CONFIG_DEFAULTS']['GAIN_TEXT']))
        self.sensortemp_v = Value('f', 0)
        self.night_v = Value('i', 1)

        self.night_sun_radians = (float(self.config['NIGHT_SUN_ALT_DEG']) / 180.0) * math.pi

        self.img_worker = None
        self.img_worker_idx = 0
        self.writefits = False

        self.indi_timeout = 10.0
        self.__state_to_str = { PyIndi.IPS_IDLE: 'IDLE', PyIndi.IPS_OK: 'OK', PyIndi.IPS_BUSY: 'BUSY', PyIndi.IPS_ALERT: 'ALERT' }
        self.__switch_types = { PyIndi.ISR_1OFMANY: 'ONE_OF_MANY', PyIndi.ISR_ATMOST1: 'AT_MOST_ONE', PyIndi.ISR_NOFMANY: 'ANY'}
        self.__type_to_str = { PyIndi.INDI_NUMBER: 'number', PyIndi.INDI_SWITCH: 'switch', PyIndi.INDI_TEXT: 'text', PyIndi.INDI_LIGHT: 'light', PyIndi.INDI_BLOB: 'blob', PyIndi.INDI_UNKNOWN: 'unknown' }

        self.base_dir = Path(__file__).parent.absolute()

        signal.signal(signal.SIGALRM, self.alarm_handler)
        signal.signal(signal.SIGHUP, self.hup_handler)


    def hup_handler(self, signum, frame):
        logger.warning('Caught HUP signal, reconfiguring')

        with io.open(self.config_file, 'r') as f_config_file:
            try:
                c = json.loads(f_config_file.read())
                f_config_file.close()
            except json.JSONDecodeError as e:
                logger.error('Error decoding json: %s', str(e))
                f_config_file.close()
                return

        # overwrite config
        self.config = c
        self.night_sun_radians = (float(self.config['NIGHT_SUN_ALT_DEG']) / 180.0) * math.pi

        nighttime = self.is_night()

        # reconfigure if needed
        if self.night_v.value != int(nighttime):
            self.dayNightReconfigure(nighttime)

        logger.warning('Stopping image process worker')
        self.img_q.put((False, False, ''))
        self.img_worker.join()

        # Restart worker with new config
        self._startImageProcessWorker()


    def alarm_handler(self, signum, frame):
        raise TimeOutException()


    def _initialize(self, writefits=False):
        if writefits:
            self.writefits = True

        self._startImageProcessWorker()

        # instantiate the client
        self.indiclient = IndiClient(
            self.config,
            self.indiblob_status_send,
            self.img_q,
        )

        # set roi
        #indiclient.roi = (270, 200, 700, 700) # region of interest for my allsky cam

        # set indi server localhost and port 7624
        self.indiclient.setServer("localhost", 7624)

        # connect to indi server
        logger.info("Connecting to indiserver")
        if (not(self.indiclient.connectServer())):
            logger.error("No indiserver running on %s:%d - Try to run", self.indiclient.getHost(), self.indiclient.getPort())
            logger.error("  indiserver indi_simulator_telescope indi_simulator_ccd")
            sys.exit(1)

        # give devices a chance to register
        time.sleep(8)

        # connect to all devices
        for d in self.indiclient.getDevices():
            logger.info('Found device %s', d.getDeviceName())

            if d.getDeviceName() == self.config['CCD_NAME']:
                logger.info('Connecting to device %s', d.getDeviceName())
                self.indiclient.connectDevice(d.getDeviceName())
                self.device = d


        # set BLOB mode to BLOB_ALSO
        logger.info('Set BLOB mode')
        self.indiclient.setBLOBMode(1, self.device.getDeviceName(), None)


        ### Perform device config
        self._configureCcd(
            self.config['INDI_CONFIG_DEFAULTS'],
        )



    def _startImageProcessWorker(self):
        self.img_worker_idx += 1

        logger.info('Starting ImageProcessorWorker process')
        self.img_worker = ImageProcessWorker(
            self.img_worker_idx,
            self.config,
            self.img_q,
            self.exposure_v,
            self.gain_v,
            self.sensortemp_v,
            self.night_v,
            writefits=self.writefits,
        )
        self.img_worker.start()



    def _configureCcd(self, indi_config):
        ### Configure CCD Properties
        for k, v in indi_config['PROPERTIES'].items():
            logger.info('Setting property %s', k)
            self.set_number(k, v)


        ### Configure CCD Switches
        for k, v in indi_config['SWITCHES'].items():
            logger.info('Setting switch %s', k)
            self.set_switch(k, on_switches=v['on'], off_switches=v.get('off', []))

        ### Configure controls
        #self.set_controls(indi_config.get('CONTROLS', {}))

        # Update shared gain value
        gain = indi_config.get('GAIN_TEXT')
        if gain:
            with self.gain_v.get_lock():
                self.gain_v.value = gain


        # Sleep after configuration
        time.sleep(1.0)


    def run(self):

        self._initialize()

        ### main loop starts
        while True:
            nighttime = self.is_night()
            #logger.info('self.night_v.value: %r', self.night_v.value)
            #logger.info('is night: %r', nighttime)

            if not nighttime and not self.config['DAYTIME_CAPTURE']:
                logger.info('Daytime capture is disabled')
                time.sleep(60)
                continue

            temp = self.device.getNumber("CCD_TEMPERATURE")
            if temp:
                with self.sensortemp_v.get_lock():
                    logger.info("Sensor temperature: %0.1f", temp[0].value)
                    self.sensortemp_v.value = temp[0].value


            ### Change gain when we change between day and night
            if self.night_v.value != int(nighttime):
                self.dayNightReconfigure(nighttime)

                if not nighttime:
                    ### Generate timelapse at end of night
                    yesterday_ref = datetime.now() - timedelta(days=1)
                    timespec = yesterday_ref.strftime('%Y%m%d')))
                    self.avconv(timespec, restart_worker=True)


            start = time.time()

            try:
                self.shoot(self.exposure_v.value)
            except TimeOutException as e:
                logger.error('Timeout: %s', str(e))
                time.sleep(5.0)
                continue

            shoot_elapsed_s = time.time() - start
            logger.info('shoot() completed in %0.4f s', shoot_elapsed_s)

            # should take far less than 5 seconds here
            signal.alarm(5)

            try:
                self.indiblob_status_receive.recv()  # wait until image is received
            except TimeOutException:
                logger.error('Timeout waiting on exposure, continuing')
                time.sleep(5.0)
                continue

            signal.alarm(0)  # reset timeout


            full_elapsed_s = time.time() - start
            logger.info('Exposure received in %0.4f s', full_elapsed_s)

            # sleep for the remaining eposure period
            remaining_s = float(self.config['EXPOSURE_PERIOD']) - full_elapsed_s
            if remaining_s > 0:
                logger.info('Sleeping for additional %0.4f s', remaining_s)
                time.sleep(remaining_s)


    def dayNightReconfigure(self, nighttime):
        logger.warning('Change between night and day')
        with self.night_v.get_lock():
            self.night_v.value = int(nighttime)

        if nighttime:
            self._configureCcd(
                self.config['INDI_CONFIG_NIGHT'],
            )
        else:
            self._configureCcd(
                self.config['INDI_CONFIG_DAY'],
            )

        # Sleep after reconfiguration
        time.sleep(1.0)


    def is_night(self):
        obs = ephem.Observer()
        obs.lon = str(self.config['LOCATION_LONGITUDE'])
        obs.lat = str(self.config['LOCATION_LATITUDE'])
        obs.date = datetime.utcnow()  # ephem expects UTC dates

        sun = ephem.Sun()
        sun.compute(obs)

        logger.info('Sun altitude: %s', sun.alt)
        return sun.alt < self.night_sun_radians



    def darks(self):

        self._initialize(writefits=True)

        ### NIGHT DARKS ###
        self._configureCcd(
            self.config['INDI_CONFIG_NIGHT'],
        )

        ### take darks
        dark_exposures = (self.config['CCD_EXPOSURE_MIN'], 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15)
        for exp in dark_exposures:
            filename = 'dark_{0:d}s_gain{1:d}'.format(int(exp), self.gain_v.value)

            start = time.time()

            self.indiclient.filename_t = filename
            self.shoot(float(exp))
            self.indiblob_status_receive.recv()  # wait until image is received

            elapsed_s = time.time() - start

            logger.info('Exposure received in %0.4f s', elapsed_s)

            logger.info('Sleeping for additional %0.4f s', 1.0)
            time.sleep(1.0)


        ### DAY DARKS ###
        self._configureCcd(
            self.config['INDI_CONFIG_DAY'],
        )


        ### take darks
        dark_exposures = (self.config['CCD_EXPOSURE_MIN'],)  # day will rarely exceed the minimum exposure
        for exp in dark_exposures:
            filename = 'dark_{0:d}s_gain{1:d}'.format(int(exp), self.gain_v.value)

            start = time.time()

            self.indiclient.filename_t = filename
            self.shoot(float(exp))
            self.indiblob_status_receive.recv()  # wait until image is received

            elapsed_s = time.time() - start

            logger.info('Exposure received in %0.4f s', elapsed_s)

            logger.info('Sleeping for additional %0.4f s', 1.0)
            time.sleep(1.0)



        ### stop image processing worker
        self.img_q.put((False, False, ''))
        self.img_worker.join()


        ### INDI disconnect
        self.indiclient.disconnectServer()


    def avconv(self, timespec, restart_worker=False):
        if self.img_worker:
            logger.warning('Stopping image process worker to save memory')
            self.img_q.put((False, False, ''))
            self.img_worker.join()


        img_day_folder = self.base_dir.joinpath('images', '{0:s}'.format(timespec))

        if not img_day_folder.exists():
            logger.error('Image folder does not exist: %s', img_day_folder)
            sys.exit(1)


        seqfolder = img_day_folder.joinpath('.sequence')

        if not seqfolder.exists():
            logger.info('Creating sequence folder %s', seqfolder)
            seqfolder.mkdir()


        # delete all existing symlinks in seqfolder
        rmlinks = list(filter(lambda p: p.is_symlink(), seqfolder.iterdir()))
        if rmlinks:
            logger.warning('Removing existing symlinks in %s', seqfolder)
            for l_p in rmlinks:
                l_p.unlink()


        # find all files
        timelapse_files = list()
        self.getFolderImgFiles(img_day_folder, timelapse_files)


        logger.info('Creating symlinked files for timelapse')
        timelapse_files_sorted = sorted(timelapse_files, key=lambda p: p.stat().st_mtime)
        for i, f in enumerate(timelapse_files_sorted):
            symlink_p = seqfolder.joinpath('{0:04d}.{1:s}'.format(i, self.config['IMAGE_FILE_TYPE']))
            symlink_p.symlink_to(f)

        cmd = 'ffmpeg -y -f image2 -r {0:d} -i {1:s}/%04d.{2:s} -vcodec libx264 -b:v {3:s} -pix_fmt yuv420p -movflags +faststart {4:s}/allsky-{5:s}.mp4'.format(self.config['FFMPEG_FRAMERATE'], str(seqfolder), self.config['IMAGE_FILE_TYPE'], self.config['FFMPEG_BITRATE'], str(img_day_folder), timespec).split()
        subprocess.run(cmd)


        # delete all existing symlinks in seqfolder
        rmlinks = list(filter(lambda p: p.is_symlink(), Path(seqfolder).iterdir()))
        if rmlinks:
            logger.warning('Removing existing symlinks in %s', seqfolder)
            for l_p in rmlinks:
                l_p.unlink()


        # remove sequence folder
        try:
            seqfolder.rmdir()
        except OSError as e:
            logger.error('Cannote remove sequence folder: %s', str(e))


        if restart_worker:
            self._startImageProcessWorker()


    def getFolderImgFiles(self, folder, file_list):
        logger.info('Searching for image files in %s', folder)

        # Add all files in current folder
        img_files = filter(lambda p: p.is_file(), Path(folder).glob('*.{0:s}'.format(self.config['IMAGE_FILE_TYPE'])))
        file_list.extend(img_files)

        # Recurse through all sub folders
        folders = filter(lambda p: p.is_dir(), Path(folder).iterdir())
        for f in folders:
            self.getFolderImgFiles(f, file_list)  # recursion


    def shoot(self, exposure, sync=True, timeout=None):
        if not timeout:
            timeout = (exposure * 2.0) + 5.0
        logger.info('Taking %0.6f s exposure', exposure)
        self.set_number('CCD_EXPOSURE', {'CCD_EXPOSURE_VALUE': exposure}, sync=sync, timeout=timeout)


    def get_control(self, name, ctl_type, timeout=None):
        ctl = None
        attr = {
            'number'  : 'getNumber',
            'switch'  : 'getSwitch',
            'text'    : 'getText',
            'light'   : 'getLight',
            'blob'    : 'getBLOB'
        }[ctl_type]
        if timeout is None:
            timeout = self.indi_timeout
        started = time.time()
        while not(ctl):
            ctl = getattr(self.device, attr)(name)
            if not ctl and 0 < timeout < time.time() - started:
                raise TimeOutException('Timeout finding control {0}'.format(name))
            time.sleep(0.01)
        return ctl


    def set_controls(self, controls):
        self.set_number('CCD_CONTROLS', controls)


    def set_number(self, name, values, sync=True, timeout=None):
        #logger.info('Name: %s, values: %s', name, str(values))
        c = self.get_control(name, 'number')
        for control_name, index in self.__map_indexes(c, values.keys()).items():
            c[index].value = values[control_name]
        self.indiclient.sendNewNumber(c)

        if sync:
            self.__wait_for_ctl_statuses(c, timeout=timeout)
        return c


    def set_switch(self, name, on_switches=[], off_switches=[], sync=True, timeout=None):
        c = self.get_control(name, 'switch')
        is_exclusive = c.r == PyIndi.ISR_ATMOST1 or c.r == PyIndi.ISR_1OFMANY
        if is_exclusive :
            on_switches = on_switches[0:1]
            off_switches = [s.name for s in c if s.name not in on_switches]
        for index in range(0, len(c)):
            current_state = c[index].s
            new_state = current_state
            if c[index].name in on_switches:
                new_state = PyIndi.ISS_ON
            elif is_exclusive or c[index].name in off_switches:
                new_state = PyIndi.ISS_OFF
            c[index].s = new_state
        self.indiclient.sendNewSwitch(c)


    def set_text(self, control_name, values, sync=True, timeout=None):
        c = self.get_control(control_name, 'text')
        for control_name, index in self.__map_indexes(c, values.keys()).items():
            c[index].text = values[control_name]
        self.indi_client.sendNewText(c)

        if sync:
            self.__wait_for_ctl_statuses(c, timeout=timeout)

        return c


    def values(self, ctl_name, ctl_type):
        return dict(map(lambda c: (c.name, c.value), self.get_control(ctl_name, ctl_type)))


    def switch_values(self, name, ctl=None):
        return self.__control2dict(name, 'switch', lambda c: {'value': c.s == PyIndi.ISS_ON}, ctl)


    def text_values(self, name, ctl=None):
        return self.__control2dict(name, 'text', lambda c: {'value': c.text}, ctl)


    def number_values(self, name, ctl=None):
        return self.__control2dict(name, 'text', lambda c: {'value': c.value, 'min': c.min, 'max': c.max, 'step': c.step, 'format': c.format}, ctl)


    def light_values(self, name, ctl=None):
        return self.__control2dict(name, 'light', lambda c: {'value': self.__state_to_str[c.s]}, ctl)


    def __wait_for_ctl_statuses(self, ctl, statuses=[PyIndi.IPS_OK, PyIndi.IPS_IDLE], timeout=None):
        started = time.time()
        if timeout is None:
            timeout = self.indi_timeout
        while ctl.s not in statuses:
            #logger.info('%s/%s/%s: %s', ctl.device, ctl.group, ctl.name, self.__state_to_str[ctl.s])
            if ctl.s == PyIndi.IPS_ALERT and 0.5 > time.time() - started:
                raise RuntimeError('Error while changing property {0}'.format(ctl.name))
            elapsed = time.time() - started
            if 0 < timeout < elapsed:
                raise TimeOutException('Timeout error while changing property {0}: elapsed={1}, timeout={2}, status={3}'.format(ctl.name, elapsed, timeout, self.__state_to_str[ctl.s] ))
            time.sleep(0.05)


    def __map_indexes(self, ctl, values):
        result = {}
        for i, c in enumerate(ctl):
            #logger.info('Value name: %s', c.name)  # useful to find value names
            if c.name in values:
                result[c.name] = i
        return result


    def __control2dict(self, control_name, control_type, transform, control=None):
        def get_dict(element):
            dest = {'name': element.name, 'label': element.label}
            dest.update(transform(element))
            return dest

        control = control if control else self.get_control(control_name, control_type)
        return [get_dict(c) for c in control]


class TimeOutException(Exception):
    pass




if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'action',
        help='action',
        choices=('run', 'darks', 'avconv'),
    )
    argparser.add_argument(
        '--config',
        '-c',
        help='config file',
        type=argparse.FileType('r'),
        required=True,
    )
    argparser.add_argument(
        '--timespec',
        '-t',
        help='time spec',
        type=str,
    )

    args = argparser.parse_args()


    args_list = list()
    if args.timespec:
        args_list.append(args.timespec)


    it = IndiTimelapse(args.config)

    action_func = getattr(it, args.action)
    action_func(*args_list)


# vim let=g:syntastic_python_flake8_args='--ignore="E203,E303,E501,E265,E266,E201,E202,W391"'
# vim: set tabstop=4 shiftwidth=4 expandtab
