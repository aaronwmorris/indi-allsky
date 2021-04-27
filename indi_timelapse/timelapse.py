import sys
import time
import io
import json
from pathlib import Path
from datetime import datetime
from datetime import timedelta
import copy
import math
import subprocess
import signal

import ephem

from multiprocessing import Pipe
from multiprocessing import Queue
from multiprocessing import Value
import multiprocessing

import PyIndi

from .indi import IndiClient
from .worker import ImageProcessWorker
from .uploader import FileUploader
from .exceptions import TimeOutException

logger = multiprocessing.get_logger()



class IndiTimelapse(object):

    def __init__(self, f_config_file):
        self.config = json.loads(f_config_file.read())
        f_config_file.close()

        self.config_file = f_config_file.name

        self.image_q = Queue()
        self.indiblob_status_receive, self.indiblob_status_send = Pipe(duplex=False)
        self.indiclient = None
        self.device = None
        self.exposure_v = Value('f', copy.copy(self.config['CCD_EXPOSURE_DEF']))
        self.gain_v = Value('i', copy.copy(self.config['INDI_CONFIG_NIGHT']['GAIN_TEXT']))
        self.sensortemp_v = Value('f', 0)
        self.night_v = Value('i', 1)

        self.night_sun_radians = (float(self.config['NIGHT_SUN_ALT_DEG']) / 180.0) * math.pi

        self.image_worker = None
        self.image_worker_idx = 0
        self.writefits = False

        self.upload_worker = None
        self.upload_q = Queue()
        self.upload_worker_idx = 0


        self.__state_to_str = { PyIndi.IPS_IDLE: 'IDLE', PyIndi.IPS_OK: 'OK', PyIndi.IPS_BUSY: 'BUSY', PyIndi.IPS_ALERT: 'ALERT' }
        self.__switch_types = { PyIndi.ISR_1OFMANY: 'ONE_OF_MANY', PyIndi.ISR_ATMOST1: 'AT_MOST_ONE', PyIndi.ISR_NOFMANY: 'ANY'}
        self.__type_to_str = { PyIndi.INDI_NUMBER: 'number', PyIndi.INDI_SWITCH: 'switch', PyIndi.INDI_TEXT: 'text', PyIndi.INDI_LIGHT: 'light', PyIndi.INDI_BLOB: 'blob', PyIndi.INDI_UNKNOWN: 'unknown' }

        self.base_dir = Path(__file__).parent.parent.absolute()

        self.generate_timelapse_flag = False   # This is updated once images have been generated

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
        self.image_q.put((False, False, False))
        self.image_worker.join()

        logger.warning('Stopping upload process worker')
        self.upload_q.put((False, False))
        self.upload_worker.join()

        # Restart worker with new config
        self._startImageProcessWorker()
        self._startImageUploadWorker()


    def alarm_handler(self, signum, frame):
        raise TimeOutException()


    def _initialize(self, writefits=False):
        if writefits:
            self.writefits = True

        self._startImageProcessWorker()
        self._startImageUploadWorker()

        # instantiate the client
        self.indiclient = IndiClient(
            self.config,
            self.indiblob_status_send,
            self.image_q,
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

        # set default device in indiclient
        self.indiclient.device = self.device

        # set BLOB mode to BLOB_ALSO
        logger.info('Set BLOB mode')
        self.indiclient.setBLOBMode(1, self.device.getDeviceName(), None)


        ### Perform device config
        self._configureCcd(
            self.config['INDI_CONFIG_NIGHT'],
        )



    def _startImageProcessWorker(self):
        self.image_worker_idx += 1

        logger.info('Starting ImageProcessorWorker process')
        self.image_worker = ImageProcessWorker(
            self.image_worker_idx,
            self.config,
            self.image_q,
            self.upload_q,
            self.exposure_v,
            self.gain_v,
            self.sensortemp_v,
            self.night_v,
            writefits=self.writefits,
        )
        self.image_worker.start()


    def _startImageUploadWorker(self):
        self.upload_worker_idx += 1

        logger.info('Starting FileUploader process %d', self.upload_worker_idx)
        self.upload_worker = FileUploader(
            self.upload_worker_idx,
            self.config,
            self.upload_q,
        )

        self.upload_worker.start()


    def _configureCcd(self, indi_config):
        ### Configure CCD Properties
        for k, v in indi_config['PROPERTIES'].items():
            logger.info('Setting property %s', k)
            self.indiclient.set_number(k, v)


        ### Configure CCD Switches
        for k, v in indi_config['SWITCHES'].items():
            logger.info('Setting switch %s', k)
            self.indiclient.set_switch(k, on_switches=v['on'], off_switches=v.get('off', []))

        ### Configure controls
        #self.indiclient.set_controls(indi_config.get('CONTROLS', {}))

        # Update shared gain value
        gain = indi_config.get('GAIN_TEXT')

        with self.gain_v.get_lock():
            self.gain_v.value = gain

        logger.info('Gain set to %d', self.gain_v.value)

        # Sleep after configuration
        time.sleep(1.0)


    def run(self):

        self._initialize()

        ### main loop starts
        while True:
            # restart worker if it has failed
            if not self.image_worker.is_alive():
                del self.image_worker  # try to free up some memory
                self._startImageProcessWorker()

            if not self.upload_worker.is_alive():
                del self.upload_worker  # try to free up some memory
                self._startImageUploadWorker()


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

                if not nighttime and self.generate_timelapse_flag:
                    ### Generate timelapse at end of night
                    yesterday_ref = datetime.now() - timedelta(days=1)
                    timespec = yesterday_ref.strftime('%Y%m%d')
                    self.generateNightTimelapse(timespec)

                if nighttime and self.generate_timelapse_flag:
                    ### Generate timelapse at end of day
                    today_ref = datetime.now()
                    timespec = today_ref.strftime('%Y%m%d')
                    self.generateDayTimelapse(timespec)



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


            if nighttime:
                # always indicate timelapse generation at night
                self.generate_timelapse_flag = True  # indicate images have been generated for timelapse
            elif self.config['DAYTIME_TIMELAPSE']:
                # must be day time
                self.generate_timelapse_flag = True  # indicate images have been generated for timelapse

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
            filename_t = 'dark_{0:d}s_gain{1:d}.{2:s}'.format(int(exp), self.gain_v.value, '{1}')

            start = time.time()

            self.indiclient.filename_t = filename_t
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
            filename_t = 'dark_{0:d}s_gain{1:d}.{2:s}'.format(int(exp), self.gain_v.value, '{1}')

            start = time.time()

            self.indiclient.filename_t = filename_t
            self.shoot(float(exp))
            self.indiblob_status_receive.recv()  # wait until image is received

            elapsed_s = time.time() - start

            logger.info('Exposure received in %0.4f s', elapsed_s)

            logger.info('Sleeping for additional %0.4f s', 1.0)
            time.sleep(1.0)



        ### stop image processing worker
        logger.warning('Stopping image process worker')
        self.image_q.put((False, False, False))
        self.image_worker.join()

        logger.warning('Stopping upload process worker')
        self.uplaod_q.put((False, False))
        self.upload_worker.join()

        ### INDI disconnect
        self.indiclient.disconnectServer()


    def generateAllTimelapse(self, timespec, day=True, night=True):
        if day:
            self.generateDayTimelapse(timespec)

        if night:
            self.generateNightTimelapse(timespec)


    def generateDayTimelapse(self, timespec):
        if self.image_worker:
            logger.warning('Stopping image process worker to save memory')
            self.image_q.put((False, False, False))
            self.image_worker.join()

        if self.upload_worker:
            logger.warning('Stopping upload process worker to save memory')
            self.upload_q.put((False, False))
            self.upload_worker.join()

        img_base_folder = self.base_dir.joinpath('images', '{0:s}'.format(timespec))

        logger.warning('Generating day time timelapse for %s', timespec)
        img_day_folder = img_base_folder.joinpath('day')
        self.generateTimelapse_timeofday(timespec, img_day_folder)


    def generateNightTimelapse(self, timespec):
        if self.image_worker:
            logger.warning('Stopping image process worker to save memory')
            self.image_q.put((False, False, False))
            self.image_worker.join()

        if self.upload_worker:
            logger.warning('Stopping upload process worker to save memory')
            self.upload_q.put((False, False))
            self.upload_worker.join()

        img_base_folder = self.base_dir.joinpath('images', '{0:s}'.format(timespec))

        logger.warning('Generating day time timelapse for %s', timespec)
        img_day_folder = img_base_folder.joinpath('night')
        self.generateTimelapse_timeofday(timespec, img_day_folder)



    def generateTimelapse_timeofday(self, timespec, img_folder):
        if not img_folder.exists():
            logger.error('Image folder does not exist: %s', img_folder)
            return


        video_file = img_folder.joinpath('allsky-{0:s}.mp4'.format(timespec))

        if video_file.exists():
            logger.warning('Video is already generated: %s', video_file)
            return


        seqfolder = img_folder.joinpath('.sequence')

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
        self.getFolderImgFiles(img_folder, timelapse_files)


        logger.info('Creating symlinked files for timelapse')
        timelapse_files_sorted = sorted(timelapse_files, key=lambda p: p.stat().st_mtime)
        for i, f in enumerate(timelapse_files_sorted):
            symlink_p = seqfolder.joinpath('{0:04d}.{1:s}'.format(i, self.config['IMAGE_FILE_TYPE']))
            symlink_p.symlink_to(f)


        start = time.time()

        cmd = 'ffmpeg -y -f image2 -r {0:d} -i {1:s}/%04d.{2:s} -vcodec libx264 -b:v {3:s} -pix_fmt yuv420p -movflags +faststart {4:s}'.format(self.config['FFMPEG_FRAMERATE'], str(seqfolder), self.config['IMAGE_FILE_TYPE'], self.config['FFMPEG_BITRATE'], str(video_file)).split()
        subprocess.run(cmd)

        elapsed_s = time.time() - start
        logger.info('Timelapse generated in %0.4f s', elapsed_s)

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
        logger.info('Taking %0.6f s exposure (gain %d)', exposure, self.gain_v.value)
        self.indiclient.set_number('CCD_EXPOSURE', {'CCD_EXPOSURE_VALUE': exposure}, sync=sync, timeout=timeout)



