import sys
import time
import io
import json
import re
from pathlib import Path
from datetime import datetime
from datetime import timedelta
#from pprint import pformat
import math
import signal

import ephem

from multiprocessing import Pipe
from multiprocessing import Queue
from multiprocessing import Value
import multiprocessing

import PyIndi

from .indi import IndiClient
from .image import ImageProcessWorker
from .video import VideoProcessWorker
from .uploader import FileUploader
from .db import IndiAllSkyDb
from .exceptions import TimeOutException

from sqlalchemy.orm.exc import NoResultFound

logger = multiprocessing.get_logger()


class IndiAllSky(object):

    CCD_EXPOSURE_DEF = 0.000100
    DATABASE_URI = 'sqlite:////var/lib/indi-allsky/indi-allsky.sqlite'


    def __init__(self, f_config_file):
        self.config = self._parseConfig(f_config_file.read())
        f_config_file.close()

        self.config['DB_URI'] = self.DATABASE_URI

        self.config_file = f_config_file.name

        self._indi_server = 'localhost'
        self._indi_port = 7624

        self.image_q = Queue()
        self.indiblob_status_receive, self.indiblob_status_send = Pipe(duplex=False)
        self.indiclient = None
        self.ccdDevice = None
        self.exposure_v = Value('f', -1.0)
        self.gain_v = Value('i', -1)  # value set in CCD config
        self.bin_v = Value('i', 1)  # set 1 for sane default
        self.sensortemp_v = Value('f', 0)
        self.night_v = Value('i', -1)  # bogus initial value
        self.night = None
        self.moonmode_v = Value('f', 0.0)  # contains moon phase %
        self.moonmode = None

        self.night_sun_radians = math.radians(float(self.config['NIGHT_SUN_ALT_DEG']))
        self.night_moonmode_radians = math.radians(float(self.config['NIGHT_MOONMODE_ALT_DEG']))

        self.image_worker = None
        self.image_worker_idx = 0

        self.video_worker = None
        self.video_q = Queue()
        self.video_worker_idx = 0

        self.save_images = True

        self.upload_worker = None
        self.upload_q = Queue()
        self.upload_worker_idx = 0

        self._db = IndiAllSkyDb(self.config)

        self.__state_to_str = { PyIndi.IPS_IDLE: 'IDLE', PyIndi.IPS_OK: 'OK', PyIndi.IPS_BUSY: 'BUSY', PyIndi.IPS_ALERT: 'ALERT' }
        self.__switch_types = { PyIndi.ISR_1OFMANY: 'ONE_OF_MANY', PyIndi.ISR_ATMOST1: 'AT_MOST_ONE', PyIndi.ISR_NOFMANY: 'ANY'}
        self.__type_to_str = { PyIndi.INDI_NUMBER: 'number', PyIndi.INDI_SWITCH: 'switch', PyIndi.INDI_TEXT: 'text', PyIndi.INDI_LIGHT: 'light', PyIndi.INDI_BLOB: 'blob', PyIndi.INDI_UNKNOWN: 'unknown' }


        if self.config['IMAGE_FOLDER']:
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()


        self.generate_timelapse_flag = False   # This is updated once images have been generated

        signal.signal(signal.SIGALRM, self.sigalarm_handler)
        signal.signal(signal.SIGHUP, self.sighup_handler)
        signal.signal(signal.SIGTERM, self.sigterm_handler)
        signal.signal(signal.SIGINT, self.sigint_handler)


    @property
    def indi_server(self):
        return self._indi_server

    @indi_server.setter
    def indi_server(self, new_server):
        self._indi_server = str(new_server)


    @property
    def indi_port(self):
        return self._indi_port

    @indi_port.setter
    def indi_port(self, new_port):
        self._indi_port = int(new_port)


    def sighup_handler(self, signum, frame):
        logger.warning('Caught HUP signal, reconfiguring')

        with io.open(self.config_file, 'r') as f_config_file:
            try:
                c = self._parseConfig(f_config_file.read())
                f_config_file.close()
            except json.JSONDecodeError as e:
                logger.error('Error decoding json: %s', str(e))
                f_config_file.close()
                return

        # overwrite config
        self.config = c

        self.config['DATABASE_URI'] = self.DATABASE_URI

        # Update shared values
        self.night_sun_radians = math.radians(float(self.config['NIGHT_SUN_ALT_DEG']))
        self.night_moonmode_radians = math.radians(float(self.config['NIGHT_MOONMODE_ALT_DEG']))

        # reconfigure if needed
        self.reconfigureCcd()

        # add driver name to config
        self.config['CCD_NAME'] = self.ccdDevice.getDeviceName()

        db_camera = self._db.addCamera(self.config['CCD_NAME'])
        self.config['DB_CCD_ID'] = db_camera.id

        # get CCD information
        ccd_info = self.indiclient.getCcdInfo(self.ccdDevice)
        self.config['CCD_INFO'] = ccd_info

        # set minimum exposure
        if not self.config.get('CCD_EXPOSURE_MIN'):
            self.config['CCD_EXPOSURE_MIN'] = self.config['CCD_INFO']['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['min']


        # CFA/Debayer setting
        if not self.config.get('CFA_PATTERN'):
            self.config['CFA_PATTERN'] = self.config['CCD_INFO']['CCD_CFA']['CFA_TYPE'].get('text')


        self._stopVideoProcessWorker()
        self._stopImageProcessWorker()
        self._stopImageUploadWorker()

        # Restart worker with new config
        self._startVideoProcessWorker()
        self._startImageProcessWorker()
        self._startImageUploadWorker()


    def sigterm_handler(self, signum, frame):
        logger.warning('Caught TERM signal, shutting down')

        self._stopVideoProcessWorker(terminate=True)
        self._stopImageProcessWorker(terminate=True)
        self._stopImageUploadWorker(terminate=True)

        sys.exit()


    def sigint_handler(self, signum, frame):
        logger.warning('Caught INT signal, shutting down')

        self._stopVideoProcessWorker()
        self._stopImageProcessWorker()
        self._stopImageUploadWorker()

        sys.exit()


    def sigalarm_handler(self, signum, frame):
        raise TimeOutException()


    def _parseConfig(self, json_config):
        c = json.loads(json_config)

        # set any new config defaults which might not be in the config

        # translate old config option
        if c.get('IMAGE_SCALE_PERCENT') and not c.get('IMAGE_SCALE'):
            c['IMAGE_SCALE'] = c['IMAGE_SCALE_PERCENT']


        # set default exposure
        if not c.get('CCD_EXPOSURE_DEF'):
            c['CCD_EXPOSURE_DEF'] = self.CCD_EXPOSURE_DEF


        # set keogram scale factor
        if not c.get('KEOGRAM_V_SCALE'):
            c['KEOGRAM_V_SCALE'] = 33

        if not c.get('KEOGRAM_H_SCALE'):
            c['KEOGRAM_H_SCALE'] = 100


        return c


    def _initialize(self):
        # instantiate the client
        self.indiclient = IndiClient(
            self.config,
            self.indiblob_status_send,
            self.image_q,
            self.gain_v,
            self.bin_v,
        )

        # set indi server localhost and port
        self.indiclient.setServer(self._indi_server, self._indi_port)

        # connect to indi server
        logger.info("Connecting to indiserver")
        if (not(self.indiclient.connectServer())):
            logger.error("No indiserver running on %s:%d - Try to run", self.indiclient.getHost(), self.indiclient.getPort())
            logger.error("  indiserver indi_simulator_telescope indi_simulator_ccd")
            sys.exit(1)

        # give devices a chance to register
        time.sleep(8)

        # connect to all devices
        ccd_list = self.indiclient.findCcds()

        if len(ccd_list) == 0:
            logger.error('No CCDs detected')
            time.sleep(1)
            sys.exit(1)

        logger.info('Found %d CCDs', len(ccd_list))
        ccdDevice = ccd_list[0]

        logger.warning('Connecting to device %s', ccdDevice.getDeviceName())
        self.indiclient.connectDevice(ccdDevice.getDeviceName())
        self.ccdDevice = ccdDevice

        # set default device in indiclient
        self.indiclient.device = self.ccdDevice

        # add driver name to config
        self.config['CCD_NAME'] = self.ccdDevice.getDeviceName()

        db_camera = self._db.addCamera(self.config['CCD_NAME'])
        self.config['DB_CCD_ID'] = db_camera.id

        # set BLOB mode to BLOB_ALSO
        logger.info('Set BLOB mode')
        self.indiclient.setBLOBMode(1, self.ccdDevice.getDeviceName(), None)

        self.indiclient.configureDevice(self.ccdDevice, self.config['INDI_CONFIG_DEFAULTS'])
        self.indiclient.setFrameType(self.ccdDevice, 'FRAME_LIGHT')  # default frame type is light

        # get CCD information
        ccd_info = self.indiclient.getCcdInfo(self.ccdDevice)
        self.config['CCD_INFO'] = ccd_info


        # set minimum exposure
        if not self.config.get('CCD_EXPOSURE_MIN'):
            self.config['CCD_EXPOSURE_MIN'] = self.config['CCD_INFO']['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['min']

        logger.info('Minimum CCD exposure: {0:0.8f}'.format(self.config['CCD_EXPOSURE_MIN']))


        with self.exposure_v.get_lock():
            self.exposure_v.value = self.config['CCD_EXPOSURE_DEF']

        logger.info('Default CCD exposure: {0:0.8f}'.format(self.config['CCD_EXPOSURE_DEF']))


        # CFA/Debayer setting
        if not self.config.get('CFA_PATTERN'):
            self.config['CFA_PATTERN'] = self.config['CCD_INFO']['CCD_CFA']['CFA_TYPE'].get('text')

        logger.info('CCD CFA: {0:s}'.format(str(self.config['CFA_PATTERN'])))


    def _startImageProcessWorker(self):
        if self.image_worker:
            if self.image_worker.is_alive():
                return

        self.image_worker_idx += 1

        logger.info('Starting ImageProcessorWorker process')
        self.image_worker = ImageProcessWorker(
            self.image_worker_idx,
            self.config,
            self.image_q,
            self.upload_q,
            self.exposure_v,
            self.gain_v,
            self.bin_v,
            self.sensortemp_v,
            self.night_v,
            self.moonmode_v,
            save_images=self.save_images,
        )
        self.image_worker.start()


    def _stopImageProcessWorker(self, terminate=False):
        if not self.image_worker:
            return

        if not self.image_worker.is_alive():
            return

        if terminate:
            logger.info('Terminating ImageProcessorWorker process')
            self.image_worker.terminate()

        logger.info('Stopping ImageProcessorWorker process')
        self.image_q.put({ 'stop' : True })
        self.image_worker.join()


    def _startVideoProcessWorker(self):
        if self.video_worker:
            if self.video_worker.is_alive():
                return

        self.video_worker_idx += 1

        logger.info('Starting VideoProcessorWorker process')
        self.video_worker = VideoProcessWorker(
            self.video_worker_idx,
            self.config,
            self.video_q,
            self.upload_q,
        )
        self.video_worker.start()


    def _stopVideoProcessWorker(self, terminate=False):
        if not self.video_worker:
            return

        if not self.video_worker.is_alive():
            return

        if terminate:
            logger.info('Terminating VideoProcessorWorker process')
            self.video_worker.terminate()

        logger.info('Stopping VideoProcessorWorker process')
        self.video_q.put({ 'stop' : True })
        self.video_worker.join()


    def _startImageUploadWorker(self):
        if self.upload_worker:
            if self.upload_worker.is_alive():
                return

        self.upload_worker_idx += 1

        logger.info('Starting FileUploader process %d', self.upload_worker_idx)
        self.upload_worker = FileUploader(
            self.upload_worker_idx,
            self.config,
            self.upload_q,
        )

        self.upload_worker.start()


    def _stopImageUploadWorker(self, terminate=False):
        if not self.upload_worker:
            return

        if not self.upload_worker.is_alive():
            return

        if terminate:
            logger.info('Terminating ImageUploadWorker process')
            self.upload_worker.terminate()

        logger.info('Stopping ImageUploadWorker process')
        self.upload_q.put({ 'stop' : True })
        self.upload_worker.join()


    def run(self):

        self._initialize()

        ### main loop starts
        while True:
            # restart worker if it has failed
            self._startImageProcessWorker()
            self._startVideoProcessWorker()
            self._startImageUploadWorker()


            self.night = self.detectNight()
            #logger.info('self.night_v.value: %r', self.night_v.value)
            #logger.info('is night: %r', self.night)
            self.moonmode = self.detectMoonMode()

            if not self.night and not self.config['DAYTIME_CAPTURE']:
                logger.info('Daytime capture is disabled')
                time.sleep(60)
                continue


            ### Change between day and night
            if self.night_v.value != int(self.night):
                if self.generate_timelapse_flag:
                    self.expireImages()  # cleanup old images and folders

                if not self.night and self.generate_timelapse_flag:
                    ### Generate timelapse at end of night
                    yesterday_ref = datetime.now() - timedelta(days=1)
                    timespec = yesterday_ref.strftime('%Y%m%d')
                    self._generateNightTimelapse(timespec, keogram=True)

                elif self.night and self.generate_timelapse_flag:
                    ### Generate timelapse at end of day
                    today_ref = datetime.now()
                    timespec = today_ref.strftime('%Y%m%d')
                    self._generateDayTimelapse(timespec, keogram=True)


            # reconfigure if needed
            self.reconfigureCcd()


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


            if self.night:
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


    def reconfigureCcd(self):

        if self.night_v.value != int(self.night):
            pass
        elif self.night and bool(self.moonmode_v.value) != bool(self.moonmode):
            pass
        else:
            # Update shared values
            with self.night_v.get_lock():
                self.night_v.value = int(self.night)

            with self.moonmode_v.get_lock():
                self.moonmode_v.value = float(self.moonmode)

            temp = self.indiclient.getCcdTemperature(self.ccdDevice)
            if temp:
                with self.sensortemp_v.get_lock():
                    logger.info("Sensor temperature: %0.1f", temp[0].value)
                    self.sensortemp_v.value = temp[0].value

            # No need to reconfigure
            return


        if self.night:
            if self.moonmode:
                logger.warning('Change to night (moon mode)')
                self.indiclient.setCcdGain(self.ccdDevice, self.config['CCD_CONFIG']['MOONMODE']['GAIN'])
                self.indiclient.setCcdBinning(self.ccdDevice, self.config['CCD_CONFIG']['MOONMODE']['BINNING'])
            else:
                logger.warning('Change to night (normal mode)')
                self.indiclient.setCcdGain(self.ccdDevice, self.config['CCD_CONFIG']['NIGHT']['GAIN'])
                self.indiclient.setCcdBinning(self.ccdDevice, self.config['CCD_CONFIG']['NIGHT']['BINNING'])
        else:
            logger.warning('Change to day')
            self.indiclient.setCcdGain(self.ccdDevice, self.config['CCD_CONFIG']['DAY']['GAIN'])
            self.indiclient.setCcdBinning(self.ccdDevice, self.config['CCD_CONFIG']['DAY']['BINNING'])


        # Update shared values
        with self.night_v.get_lock():
            self.night_v.value = int(self.night)

        with self.moonmode_v.get_lock():
            self.moonmode_v.value = float(self.moonmode)


        temp = self.indiclient.getCcdTemperature(self.ccdDevice)
        if temp:
            with self.sensortemp_v.get_lock():
                logger.info("Sensor temperature: %0.1f", temp[0].value)
                self.sensortemp_v.value = temp[0].value


        # Sleep after reconfiguration
        time.sleep(1.0)


    def detectNight(self):
        obs = ephem.Observer()
        obs.lon = str(self.config['LOCATION_LONGITUDE'])
        obs.lat = str(self.config['LOCATION_LATITUDE'])
        obs.date = datetime.utcnow()  # ephem expects UTC dates

        sun = ephem.Sun()
        sun.compute(obs)

        logger.info('Sun altitude: %s', sun.alt)
        return sun.alt < self.night_sun_radians


    def detectMoonMode(self):
        if not type(self.night) is bool:
            self.night = self.detectNight()

        obs = ephem.Observer()
        obs.lon = str(self.config['LOCATION_LONGITUDE'])
        obs.lat = str(self.config['LOCATION_LATITUDE'])
        obs.date = datetime.utcnow()  # ephem expects UTC dates

        moon = ephem.Moon()
        moon.compute(obs)

        moon_phase = moon.moon_phase * 100.0

        logger.info('Moon altitide: %s, phase %0.1f%%', moon.alt, moon_phase)
        if self.night:
            if moon.alt >= self.night_moonmode_radians:
                if moon_phase >= self.config['NIGHT_MOONMODE_PHASE']:
                    logger.info('Moon Mode conditions detected')
                    return moon_phase

        return 0.0


    def darks(self):
        self.config['IMAGE_SAVE_RAW'] = True
        self.save_images = False

        self._initialize()

        self.indiclient.setFrameType(self.ccdDevice, 'FRAME_DARK')

        # update CCD information
        ccd_info = self.indiclient.getCcdInfo(self.ccdDevice)
        self.config['CCD_INFO'] = ccd_info

        self._startImageProcessWorker()

        self.indiclient.img_subdirs = ['darks']  # write darks into darks sub directory

        ######
        # dark frames are taken in increments of 5 seconds (offset +1)  1, 6, 11, 16, 21...
        # Note the weird +2 in the ranges below are necessary for range to return the max value in the series
        ######

        ### NIGHT MODE DARKS ###
        self.indiclient.setCcdGain(self.ccdDevice, self.config['CCD_CONFIG']['NIGHT']['GAIN'])
        self.indiclient.setCcdBinning(self.ccdDevice, self.config['CCD_CONFIG']['NIGHT']['BINNING'])

        ccd_bits = int(self.config['CCD_INFO']['CCD_INFO']['CCD_BITSPERPIXEL']['current'])

        ### take darks
        night_dark_exposures = range(1, (int(self.config['CCD_EXPOSURE_MAX']) + 5) + 2, 5)  # dark frames round up
        for exp in night_dark_exposures:
            filename_t = 'dark_{0:d}s_{1:d}bit_gain{2:d}_bin{3:d}.{4:s}'.format(int(exp), ccd_bits, self.gain_v.value, self.bin_v.value, '{1}')
            self.indiclient.filename_t = filename_t  # override file name for darks

            start = time.time()

            self.shoot(float(exp))
            self.indiblob_status_receive.recv()  # wait until image is received

            elapsed_s = time.time() - start

            logger.info('Exposure received in %0.4f s', elapsed_s)

            logger.info('Sleeping for additional %0.4f s', 1.0)
            time.sleep(1.0)


        ### NIGHT MOON MODE DARKS ###
        self.indiclient.setCcdGain(self.ccdDevice, self.config['CCD_CONFIG']['MOONMODE']['GAIN'])
        self.indiclient.setCcdBinning(self.ccdDevice, self.config['CCD_CONFIG']['MOONMODE']['BINNING'])


        ### take darks
        night_moonmode_dark_exposures = range(1, (int(self.config['CCD_EXPOSURE_MAX']) + 5) + 2, 5)  # dark frames round up
        for exp in night_moonmode_dark_exposures:
            filename_t = 'dark_{0:d}s_gain{1:d}_bin{2:d}.{3:s}'.format(int(exp), self.gain_v.value, self.bin_v.value, '{1}')
            self.indiclient.filename_t = filename_t  # override file name for darks

            start = time.time()

            self.shoot(float(exp))
            self.indiblob_status_receive.recv()  # wait until image is received

            elapsed_s = time.time() - start

            logger.info('Exposure received in %0.4f s', elapsed_s)

            logger.info('Sleeping for additional %0.4f s', 1.0)
            time.sleep(1.0)



        ### DAY DARKS ###
        self.indiclient.setCcdGain(self.ccdDevice, self.config['CCD_CONFIG']['DAY']['GAIN'])
        self.indiclient.setCcdBinning(self.ccdDevice, self.config['CCD_CONFIG']['DAY']['BINNING'])


        ### take darks
        # day will rarely exceed 1 second
        day_dark_exposures = range(1, (5 + 2), 5)  # 1 and 6, don't ask
        for exp in day_dark_exposures:
            filename_t = 'dark_{0:d}s_gain{1:d}_bin{2:d}.{3:s}'.format(int(exp), self.gain_v.value, self.bin_v.value, '{1}')
            self.indiclient.filename_t = filename_t  # override file name for darks

            start = time.time()

            self.shoot(float(exp))
            self.indiblob_status_receive.recv()  # wait until image is received

            elapsed_s = time.time() - start

            logger.info('Exposure received in %0.4f s', elapsed_s)

            logger.info('Sleeping for additional %0.4f s', 1.0)
            time.sleep(1.0)



        ### stop image processing worker
        self._stopImageProcessWorker()
        self._stopVideoProcessWorker()
        self._stopImageUploadWorker()


        ### INDI disconnect
        self.indiclient.disconnectServer()


    def generateDayTimelapse(self, timespec):
        self._generateDayTimelapse(timespec, keogram=False)
        self._stopVideoProcessWorker()


    def _generateDayTimelapse(self, timespec, keogram=True):
        self._startVideoProcessWorker()

        img_base_folder = self.image_dir.joinpath('{0:s}'.format(timespec))

        logger.warning('Generating day time timelapse for %s', timespec)
        img_day_folder = img_base_folder.joinpath('day')

        self.video_q.put({
            'timespec'    : timespec,
            'img_folder'  : img_day_folder,
            'timeofday'   : 'day',
            'video'       : True,
            'keogram'     : keogram,
        })


    def generateNightTimelapse(self, timespec):
        self._generateNightTimelapse(timespec, keogram=False)
        self._stopVideoProcessWorker()


    def _generateNightTimelapse(self, timespec, keogram=True):
        self._startVideoProcessWorker()

        img_base_folder = self.image_dir.joinpath('{0:s}'.format(timespec))

        logger.warning('Generating night time timelapse for %s', timespec)
        img_day_folder = img_base_folder.joinpath('night')

        self.video_q.put({
            'timespec'    : timespec,
            'img_folder'  : img_day_folder,
            'timeofday'   : 'night',
            'video'       : True,
            'keogram'     : keogram,
        })


    def generateNightKeogram(self, timespec):
        self._generateNightKeogram(timespec)
        self._stopVideoProcessWorker()


    def _generateNightKeogram(self, timespec):
        self._startVideoProcessWorker()

        img_base_folder = self.image_dir.joinpath('{0:s}'.format(timespec))

        logger.warning('Generating night time keogram for %s', timespec)
        img_day_folder = img_base_folder.joinpath('night')

        self.video_q.put({
            'timespec'    : timespec,
            'img_folder'  : img_day_folder,
            'timeofday'   : 'night',
            'video'       : False,
            'keogram'     : True,
        })


    def generateDayKeogram(self, timespec):
        self._generateDayKeogram(timespec)
        self._stopVideoProcessWorker()


    def _generateDayKeogram(self, timespec):
        self._startVideoProcessWorker()

        img_base_folder = self.image_dir.joinpath('{0:s}'.format(timespec))

        logger.warning('Generating day time keogram for %s', timespec)
        img_day_folder = img_base_folder.joinpath('day')

        self.video_q.put({
            'timespec'    : timespec,
            'img_folder'  : img_day_folder,
            'timeofday'   : 'day',
            'video'       : False,
            'keogram'     : True,
        })


    def shoot(self, exposure, sync=True, timeout=None):
        if not timeout:
            timeout = (exposure * 2.0) + 5.0

        logger.info('Taking %0.8f s exposure (gain %d)', exposure, self.gain_v.value)
        self.indiclient.setCcdExposure(self.ccdDevice, exposure, sync=sync, timeout=timeout)


    def expireImages(self, days=None):
        ### This needs to be run before generating a timelapse
        from .db import IndiAllSkyDbImageTable

        dbsession = self._db.session


        if not days:
            days = self.config['IMAGE_EXPIRE_DAYS']

        # Orphaned symlinks need to be removed
        symlink_list = list()
        self.getFolderSymlinks(self.image_dir, symlink_list)
        for f in symlink_list:
            logger.info('Removing orphaned symlink: %s', f)

            try:
                f.unlink()
            except OSError as e:
                logger.error('Cannot remove symlink: %s', str(e))

        # Old image files need to be pruned
        cutoff_age = datetime.now() - timedelta(days=days)

        old_images = dbsession.query(IndiAllSkyDbImageTable).filter(IndiAllSkyDbImageTable.datetime < cutoff_age)


        logger.warning('Found %d expired images to delete', old_images.count())
        for file_entry in old_images:
            logger.info('Removing old image: %s', file_entry.filename)

            file_p = Path(file_entry.filename)

            try:
                file_p.unlink()
            except OSError as e:
                logger.error('Cannot remove file: %s', str(e))
                continue
            except FileNotFoundError as e:
                logger.warning('File already removed: %s', str(e))

            dbsession.delete(file_entry)
            dbsession.commit()


        # Remove empty folders
        dir_list = list()
        self.getFolderFolders(self.image_dir, dir_list)

        empty_dirs = filter(lambda p: not any(p.iterdir()), dir_list)
        for d in empty_dirs:
            logger.info('Removing empty directory: %s', d)

            try:
                d.rmdir()
            except OSError as e:
                logger.error('Cannot remove folder: %s', str(e))


    def dbImportImages(self):
        from .db import IndiAllSkyDbImageTable
        from .db import IndiAllSkyDbVideoTable
        from .db import IndiAllSkyDbKeogramTable

        dbsession = self._db.session

        try:
            camera_id = self._db.getCurrentCameraId()
        except NoResultFound:
            logger.error('No camera found')
            sys.exit(1)


        file_list_videos = list()
        self.getFolderFilesByExt(self.image_dir, file_list_videos, extension_list=['mp4'])


        #/var/www/html/allsky/images/20210915/allsky-timelapse-20210915-night.mp4
        re_video = re.compile(r'(?P<daydate_str>\d{8})\/.+timelapse\-\d{8}\-(?P<timeofday_str>[a-z]+)\.[a-z0-9]+$')
        for f in file_list_videos:
            logger.info('Timelapse: %s', f)

            m = re.search(re_video, str(f))
            if not m:
                logger.error(' Regex did not match file')
                continue

            #logger.info('Daydate string: %s', m.group('daydate_str'))
            #logger.info('Time of day string: %s', m.group('timeofday_str'))

            d_daydate = datetime.strptime(m.group('daydate_str'), '%Y%m%d')
            #logger.info('Daydate: %s', str(d_daydate))

            if m.group('timeofday_str') == 'night':
                night = True
            else:
                night = False

            d_datetime = datetime.fromtimestamp(f.stat().st_mtime)

            try:
                video = dbsession.query(IndiAllSkyDbVideoTable).filter(IndiAllSkyDbVideoTable.filename == str(f)).one()
                logger.info(' Timelapse already imported')
                continue
            except NoResultFound:
                video = IndiAllSkyDbVideoTable(
                    filename=str(f),
                    datetime=d_datetime,
                    daydate=d_daydate,
                    night=night,
                    uploaded=False,
                    camera_id=camera_id,
                )

                dbsession.add(video)
                dbsession.commit()

                logger.info(' Timelapse inserted')



        file_list = list()
        self.getFolderFilesByExt(self.image_dir, file_list, extension_list=['jpg', 'jpeg', 'png', 'tif', 'tiff'])


        file_list_keograms = filter(lambda p: 'keogram' in p.name, file_list)

        #/var/www/html/allsky/images/20210915/allsky-keogram-20210915-night.jpg
        re_keogram = re.compile(r'(?P<daydate_str>\d{8})\/.+keogram\-\d{8}\-(?P<timeofday_str>[a-z]+)\.[a-z]+$')
        for f in file_list_keograms:
            logger.info('Keogram: %s', f)

            m = re.search(re_keogram, str(f))
            if not m:
                logger.error(' Regex did not match file')
                continue

            #logger.info('Daydate string: %s', m.group('daydate_str'))
            #logger.info('Time of day string: %s', m.group('timeofday_str'))

            d_daydate = datetime.strptime(m.group('daydate_str'), '%Y%m%d')
            #logger.info('Daydate: %s', str(d_daydate))

            if m.group('timeofday_str') == 'night':
                night = True
            else:
                night = False

            d_datetime = datetime.fromtimestamp(f.stat().st_mtime)

            try:
                keogram = dbsession.query(IndiAllSkyDbKeogramTable).filter(IndiAllSkyDbKeogramTable.filename == str(f)).one()
                logger.info(' Keogram already imported')
                continue
            except NoResultFound:
                keogram = IndiAllSkyDbKeogramTable(
                    filename=str(f),
                    datetime=d_datetime,
                    daydate=d_daydate,
                    night=night,
                    uploaded=False,
                    camera_id=camera_id,
                )

                dbsession.add(keogram)
                dbsession.commit()

                logger.info(' Keogram inserted')


        # Exclude keograms
        file_list_images = filter(lambda p: 'keogram' not in p.name, file_list)

        #/var/www/html/allsky/images/20210825/night/26_02/20210826_020202.jpg
        re_image = re.compile(r'(?P<daydate_str>\d{8})\/(?P<timeofday_str>[a-z]+)\/\d{2}_\d{2}\/(?P<datetime_str>[0-9_]+)\.[a-z]+$')
        for f in file_list_images:
            logger.info('Image: %s', f)

            m = re.search(re_image, str(f))
            if not m:
                logger.error(' Regex did not match file')
                continue

            #logger.info('Daydate string: %s', m.group('daydate_str'))
            #logger.info('Time of day string: %s', m.group('timeofday_str'))
            #logger.info('Datetime string: %s', m.group('datetime_str'))

            d_daydate = datetime.strptime(m.group('daydate_str'), '%Y%m%d')
            #logger.info('Daydate: %s', str(d_daydate))

            if m.group('timeofday_str') == 'night':
                night = True
            else:
                night = False

            d_datetime = datetime.strptime(m.group('datetime_str'), '%Y%m%d_%H%M%S')
            #logger.info('Datetime: %s', str(d_datetime))


            try:
                image = dbsession.query(IndiAllSkyDbImageTable).filter(IndiAllSkyDbImageTable.filename == str(f)).one()
                logger.info(' Image already imported')
                continue
            except NoResultFound:
                image = IndiAllSkyDbImageTable(
                    filename=str(f),
                    camera_id=camera_id,
                    datetime=d_datetime,
                    daydate=d_daydate,
                    exposure=0.0,
                    gain=-1,
                    binmode=1,
                    night=night,
                    adu=0.0,
                    stable=True,
                    moonmode=False,
                    adu_roi=False,
                    uploaded=False
                )

                dbsession.add(image)
                dbsession.commit()

                logger.info(' Image inserted')


    def getFolderSymlinks(self, folder, symlink_list):
        for item in Path(folder).iterdir():
            if item.is_symlink():
                symlink_list.append(item)
            elif item.is_dir():
                self.getFolderSymlinks(item, symlink_list)  # recursion


    def getFolderFilesByExt(self, folder, file_list, extension_list=None):
        if not extension_list:
            extension_list = [self.config['IMAGE_FILE_TYPE']]

        logger.info('Searching for image files in %s', folder)

        dot_extension_list = ['.{0:s}'.format(e) for e in extension_list]

        for item in Path(folder).iterdir():
            if item.is_file() and item.suffix in dot_extension_list:
                file_list.append(item)
            elif item.is_dir():
                self.getFolderFilesByExt(item, file_list, extension_list=extension_list)  # recursion


    def getFolderFolders(self, folder, dir_list):
        for item in Path(folder).iterdir():
            if item.is_dir():
                dir_list.append(item)
                self.getFolderFolders(item, dir_list)  # recursion

