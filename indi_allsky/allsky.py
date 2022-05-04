import sys
import os
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
import logging

import ephem

from multiprocessing import Queue
from multiprocessing import Value

from .indi import IndiClient
from .image import ImageWorker
from .video import VideoWorker
from .uploader import FileUploader
from .exceptions import TimeOutException

#from flask import current_app as app
from .flask import db
from .flask.miscDb import miscDb

from .flask.models import TaskQueueQueue
from .flask.models import TaskQueueState
from .flask.models import IndiAllSkyDbTaskQueueTable

from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.exc import IntegrityError


logger = logging.getLogger('indi_allsky')


class IndiAllSky(object):

    periodic_reconfigure_offset = 300.0  # 5 minutes
    DB_URI = 'sqlite:////var/lib/indi-allsky/indi-allsky.sqlite'


    def __init__(self, f_config_file):
        self.config = self._parseConfig(f_config_file.read())
        f_config_file.close()

        self.config['DB_URI'] = self.DB_URI

        self.config_file = f_config_file.name

        self._pidfile = '/var/lib/indi-allsky/indi-allsky.pid'

        self.indiclient = None
        self.ccdDevice = None
        self.exposure_v = Value('f', -1.0)
        self.gain_v = Value('i', -1)  # value set in CCD config
        self.bin_v = Value('i', 1)  # set 1 for sane default
        self.sensortemp_v = Value('f', 0)
        self.night_v = Value('i', -1)  # bogus initial value
        self.night = None
        self.moonmode_v = Value('i', -1)  # bogus initial value
        self.moonmode = None

        self.night_sun_radians = math.radians(self.config['NIGHT_SUN_ALT_DEG'])
        self.night_moonmode_radians = math.radians(self.config['NIGHT_MOONMODE_ALT_DEG'])

        self.image_q = Queue()
        self.image_worker = None
        self.image_worker_idx = 0

        self.video_q = Queue()
        self.video_worker = None
        self.video_worker_idx = 0

        self.save_images = True

        self.upload_q = Queue()
        self.upload_worker = None
        self.upload_worker_idx = 0

        self.periodic_reconfigure_time = time.time() + self.periodic_reconfigure_offset

        self._miscDb = miscDb(self.config)


        if self.config['IMAGE_FOLDER']:
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()


        self.generate_timelapse_flag = False   # This is updated once images have been generated

        signal.signal(signal.SIGALRM, self.sigalarm_handler)
        signal.signal(signal.SIGHUP, self.sighup_handler)
        signal.signal(signal.SIGTERM, self.sigterm_handler)
        signal.signal(signal.SIGINT, self.sigint_handler)

        self.restart = False
        self.shutdown = False
        self.terminate = False


    @property
    def pidfile(self):
        return self._pidfile

    @pidfile.setter
    def pidfile(self, new_pidfile):
        self._pidfile = str(new_pidfile)


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

        self.config['DB_URI'] = self.DB_URI

        # Update shared values
        self.night_sun_radians = math.radians(self.config['NIGHT_SUN_ALT_DEG'])
        self.night_moonmode_radians = math.radians(self.config['NIGHT_MOONMODE_ALT_DEG'])

        # reconfigure if needed
        self.reconfigureCcd(self.ccdDevice)

        # add driver name to config
        self.config['CCD_NAME'] = self.ccdDevice.getDeviceName()
        self.config['CCD_SERVER'] = self.ccdDevice.getDriverExec()

        db_camera = self._miscDb.addCamera(self.config['CCD_NAME'])
        self.config['DB_CCD_ID'] = db_camera.id

        # get CCD information
        ccd_info = self.indiclient.getCcdInfo(self.ccdDevice)
        self.config['CCD_INFO'] = ccd_info


        # set minimum exposure
        ccd_min_exp = self.config['CCD_INFO']['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['min']

        # Some CCD drivers will not accept their stated minimum exposure.
        # There might be some python -> C floating point conversion problem causing this.
        ccd_min_exp = ccd_min_exp + 0.00000001

        if not self.config.get('CCD_EXPOSURE_MIN'):
            logger.warning('Setting minimum to %0.8f', ccd_min_exp)
            self.config['CCD_EXPOSURE_MIN'] = ccd_min_exp
        elif self.config.get('CCD_EXPOSURE_MIN') < ccd_min_exp:
            logger.warning(
                'Minimum exposure %0.8f too low, increasing to %0.8f',
                self.config.get('CCD_EXPOSURE_MIN'),
                ccd_min_exp,
            )
            self.config['CCD_EXPOSURE_MIN'] = ccd_min_exp

        logger.info('Minimum CCD exposure: %0.8f', self.config['CCD_EXPOSURE_MIN'])


        # CFA/Debayer setting
        if not self.config.get('CFA_PATTERN'):
            self.config['CFA_PATTERN'] = self.config['CCD_INFO']['CCD_CFA']['CFA_TYPE'].get('text')


        # Validate gain settings
        ccd_min_gain = self.config['CCD_INFO']['GAIN_INFO']['min']
        ccd_max_gain = self.config['CCD_INFO']['GAIN_INFO']['max']

        if self.config['CCD_CONFIG']['NIGHT']['GAIN'] < ccd_min_gain:
            logger.error('CCD night gain below minimum, changing to %d', int(ccd_min_gain))
            self.config['CCD_CONFIG']['NIGHT']['GAIN'] = int(ccd_min_gain)
        elif self.config['CCD_CONFIG']['NIGHT']['GAIN'] > ccd_max_gain:
            logger.error('CCD night gain above maximum, changing to %d', int(ccd_max_gain))
            self.config['CCD_CONFIG']['NIGHT']['GAIN'] = int(ccd_max_gain)

        if self.config['CCD_CONFIG']['MOONMODE']['GAIN'] < ccd_min_gain:
            logger.error('CCD moon mode gain below minimum, changing to %d', int(ccd_min_gain))
            self.config['CCD_CONFIG']['MOONMODE']['GAIN'] = int(ccd_min_gain)
        elif self.config['CCD_CONFIG']['MOONMODE']['GAIN'] > ccd_max_gain:
            logger.error('CCD moon mode gain above maximum, changing to %d', int(ccd_max_gain))
            self.config['CCD_CONFIG']['MOONMODE']['GAIN'] = int(ccd_max_gain)

        if self.config['CCD_CONFIG']['DAY']['GAIN'] < ccd_min_gain:
            logger.error('CCD day gain below minimum, changing to %d', int(ccd_min_gain))
            self.config['CCD_CONFIG']['DAY']['GAIN'] = int(ccd_min_gain)
        elif self.config['CCD_CONFIG']['DAY']['GAIN'] > ccd_max_gain:
            logger.error('CCD day gain above maximum, changing to %d', int(ccd_max_gain))
            self.config['CCD_CONFIG']['DAY']['GAIN'] = int(ccd_max_gain)


        # set flag for program to restart processes
        self.restart = True


    def sigterm_handler(self, signum, frame):
        logger.warning('Caught TERM signal, shutting down')

        # set flag for program to stop processes
        self.shutdown = True
        self.terminate = True


    def sigint_handler(self, signum, frame):
        logger.warning('Caught INT signal, shutting down')

        # set flag for program to stop processes
        self.shutdown = True


    def sigalarm_handler(self, signum, frame):
        raise TimeOutException()


    def write_pid(self):
        pidfile_p = Path(self._pidfile)

        try:
            pidfile_p.unlink()
        except FileNotFoundError:
            pass

        with io.open(str(pidfile_p), 'w') as pid_f:
            pid_f.write('{0:d}'.format(os.getpid()))
            pid_f.flush()


    def _parseConfig(self, json_config):
        c = json.loads(json_config)

        # set any new config defaults which might not be in the config

        # indi server
        if not c.get('INDI_SERVER'):
            c['INDI_SERVER'] = 'localhost'

        if not c.get('INDI_PORT'):
            c['INDI_PORT'] = 7624


        # translate old config option
        if c.get('IMAGE_SCALE_PERCENT') and not c.get('IMAGE_SCALE'):
            c['IMAGE_SCALE'] = c['IMAGE_SCALE_PERCENT']


        # normalize exposure period
        if c['EXPOSURE_PERIOD'] < c['CCD_EXPOSURE_MAX']:
            logger.warning('Exposure period is less than maximum exposure, correcting')
            c['EXPOSURE_PERIOD'] = c['CCD_EXPOSURE_MAX']


        # set keogram scale factor
        if not c.get('KEOGRAM_V_SCALE'):
            c['KEOGRAM_V_SCALE'] = 33

        if not c.get('KEOGRAM_H_SCALE'):
            c['KEOGRAM_H_SCALE'] = 100


        # enable star detection by default
        if not c.get('DETECT_STARS'):
            c['DETECT_STARS'] = True


        return c


    def _initialize(self):
        # instantiate the client
        self.indiclient = IndiClient(
            self.config,
            self.image_q,
            self.gain_v,
            self.bin_v,
            self.sensortemp_v,
        )

        # set indi server localhost and port
        self.indiclient.setServer(self.config['INDI_SERVER'], self.config['INDI_PORT'])

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
        self.config['CCD_SERVER'] = self.ccdDevice.getDriverExec()

        db_camera = self._miscDb.addCamera(self.config['CCD_NAME'])
        self.config['DB_CCD_ID'] = db_camera.id

        # Disable debugging
        self.indiclient.disableDebug(self.ccdDevice)

        # set BLOB mode to BLOB_ALSO
        self.indiclient.updateCcdBlobMode(self.ccdDevice)

        self.indiclient.configureDevice(self.ccdDevice, self.config['INDI_CONFIG_DEFAULTS'])
        self.indiclient.setFrameType(self.ccdDevice, 'FRAME_LIGHT')  # default frame type is light

        # get CCD information
        ccd_info = self.indiclient.getCcdInfo(self.ccdDevice)
        self.config['CCD_INFO'] = ccd_info


        # set minimum exposure
        ccd_min_exp = self.config['CCD_INFO']['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['min']

        # Some CCD drivers will not accept their stated minimum exposure.
        # There might be some python -> C floating point conversion problem causing this.
        ccd_min_exp = ccd_min_exp + 0.00000001

        if not self.config.get('CCD_EXPOSURE_MIN'):
            self.config['CCD_EXPOSURE_MIN'] = ccd_min_exp
        elif self.config.get('CCD_EXPOSURE_MIN') < ccd_min_exp:
            logger.warning(
                'Minimum exposure %0.8f too low, increasing to %0.8f',
                self.config.get('CCD_EXPOSURE_MIN'),
                ccd_min_exp,
            )
            self.config['CCD_EXPOSURE_MIN'] = ccd_min_exp

        logger.info('Minimum CCD exposure: %0.8f', self.config['CCD_EXPOSURE_MIN'])


        # set default exposure
        #
        # Note:  I have tried setting a default exposure of 1.0s which works fine for night time, but
        #        during the day weird things can happen when the image sensor is completely oversaturated.
        #        Instead of an all white image, you can get intermediate pixel values which confuses the
        #        exposure detection algorithm
        if not self.config.get('CCD_EXPOSURE_DEF'):
            self.config['CCD_EXPOSURE_DEF'] = self.config['CCD_EXPOSURE_MIN']

        with self.exposure_v.get_lock():
            self.exposure_v.value = self.config['CCD_EXPOSURE_DEF']

        logger.info('Default CCD exposure: {0:0.8f}'.format(self.config['CCD_EXPOSURE_DEF']))


        # CFA/Debayer setting
        if not self.config.get('CFA_PATTERN'):
            self.config['CFA_PATTERN'] = self.config['CCD_INFO']['CCD_CFA']['CFA_TYPE'].get('text')

        logger.info('CCD CFA: {0:s}'.format(str(self.config['CFA_PATTERN'])))


        # Validate gain settings
        ccd_min_gain = self.config['CCD_INFO']['GAIN_INFO']['min']
        ccd_max_gain = self.config['CCD_INFO']['GAIN_INFO']['max']

        if self.config['CCD_CONFIG']['NIGHT']['GAIN'] < ccd_min_gain:
            logger.error('CCD night gain below minimum, changing to %d', int(ccd_min_gain))
            self.config['CCD_CONFIG']['NIGHT']['GAIN'] = int(ccd_min_gain)
            time.sleep(3)
        elif self.config['CCD_CONFIG']['NIGHT']['GAIN'] > ccd_max_gain:
            logger.error('CCD night gain above maximum, changing to %d', int(ccd_max_gain))
            self.config['CCD_CONFIG']['NIGHT']['GAIN'] = int(ccd_max_gain)
            time.sleep(3)

        if self.config['CCD_CONFIG']['MOONMODE']['GAIN'] < ccd_min_gain:
            logger.error('CCD moon mode gain below minimum, changing to %d', int(ccd_min_gain))
            self.config['CCD_CONFIG']['MOONMODE']['GAIN'] = int(ccd_min_gain)
            time.sleep(3)
        elif self.config['CCD_CONFIG']['MOONMODE']['GAIN'] > ccd_max_gain:
            logger.error('CCD moon mode gain above maximum, changing to %d', int(ccd_max_gain))
            self.config['CCD_CONFIG']['MOONMODE']['GAIN'] = int(ccd_max_gain)
            time.sleep(3)

        if self.config['CCD_CONFIG']['DAY']['GAIN'] < ccd_min_gain:
            logger.error('CCD day gain below minimum, changing to %d', int(ccd_min_gain))
            self.config['CCD_CONFIG']['DAY']['GAIN'] = int(ccd_min_gain)
            time.sleep(3)
        elif self.config['CCD_CONFIG']['DAY']['GAIN'] > ccd_max_gain:
            logger.error('CCD day gain above maximum, changing to %d', int(ccd_max_gain))
            self.config['CCD_CONFIG']['DAY']['GAIN'] = int(ccd_max_gain)
            time.sleep(3)


    def _startImageWorker(self):
        if self.image_worker:
            if self.image_worker.is_alive():
                return

        self.image_worker_idx += 1

        logger.info('Starting ImageWorker process')
        self.image_worker = ImageWorker(
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


    def _stopImageWorker(self, terminate=False):
        if not self.image_worker:
            return

        if not self.image_worker.is_alive():
            return

        if terminate:
            logger.info('Terminating ImageWorker process')
            if self.image_worker:
                self.image_worker.terminate()

        logger.info('Stopping ImageWorker process')

        self.image_q.put({'stop' : True})
        self.image_worker.join()


    def _startVideoWorker(self):
        if self.video_worker:
            if self.video_worker.is_alive():
                return

        self.video_worker_idx += 1

        logger.info('Starting VideoWorker process')
        self.video_worker = VideoWorker(
            self.video_worker_idx,
            self.config,
            self.video_q,
            self.upload_q,
        )
        self.video_worker.start()


    def _stopVideoWorker(self, terminate=False):
        if not self.video_worker:
            return

        if not self.video_worker.is_alive():
            return

        if terminate:
            logger.info('Terminating VideoWorker process')
            if self.video_worker:
                self.video_worker.terminate()

        logger.info('Stopping VideoWorker process')

        self.video_q.put({'stop' : True})
        self.video_worker.join()


    def _startFileUploadWorker(self):
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


    def _stopFileUploadWorker(self, terminate=False):
        if not self.upload_worker:
            return

        if not self.upload_worker.is_alive():
            return

        if terminate:
            logger.info('Terminating FileUploadWorker process')
            if self.upload_worker:
                self.upload_worker.terminate()

        logger.info('Stopping FileUploadWorker process')

        self.upload_q.put({'stop' : True})
        self.upload_worker.join()


    def _pre_run_tasks(self, ccdDevice):
        # Tasks that need to be run before the main program loop

        if self.config['CCD_SERVER'] in ['indi_rpicam']:
            # Raspberry PI HQ Camera requires an initial throw away exposure of over 6s
            # in order to take exposures longer than 7s
            logger.info('Taking throw away exposure for rpicam')
            self.shoot(ccdDevice, 7.0, sync=True)


    def periodic_reconfigure(self, ccdDevice):
        # Tasks that need to be run periodically
        if self.periodic_reconfigure_time > time.time():
            return

        # set next reconfigure time
        self.periodic_reconfigure_time = time.time() + self.periodic_reconfigure_offset

        logger.warning('Periodic reconfigure triggered')

        if self.config['CCD_SERVER'] in ['indi_asi_ccd']:
            # There is a bug in the ASI120M* camera that causes exposures to fail on gain changes
            # The indi_asi_ccd server will switch the camera to 8-bit mode to try to correct
            if self.config['CCD_NAME'].startswith('ZWO CCD ASI120'):
                self.indiclient.configureDevice(ccdDevice, self.config['INDI_CONFIG_DEFAULTS'])
        elif self.config['CCD_SERVER'] in ['indi_asi_single_ccd']:
            if self.config['CCD_NAME'].startswith('ZWO ASI120'):
                self.indiclient.configureDevice(ccdDevice, self.config['INDI_CONFIG_DEFAULTS'])


    def run(self):
        self.write_pid()

        self._expireOrphanedTasks()

        self._initialize()

        self._pre_run_tasks(self.ccdDevice)

        next_frame_time = time.time()  # start immediately
        frame_start_time = time.time()
        waiting_for_frame = False
        exposure_ctl = None  # populated later

        camera_ready_time = time.time()
        camera_ready = False
        last_camera_ready = False
        exposure_state = 'unset'

        ### main loop starts
        while True:
            loop_start_time = time.time()


            logger.info('Camera last ready: %0.1fs', loop_start_time - camera_ready_time)
            logger.info('Exposure state: %s', exposure_state)


            # restart worker if it has failed
            self._startImageWorker()
            self._startVideoWorker()
            self._startFileUploadWorker()


            self.detectNight()
            self.detectMoonMode()

            if not self.night and not self.config['DAYTIME_CAPTURE']:
                logger.info('Daytime capture is disabled')
                time.sleep(60)
                continue


            ### Change between day and night
            if self.night_v.value != int(self.night):
                if self.generate_timelapse_flag:
                    self._expireData()  # cleanup old images and folders
                    self._flushOldTasks()  # cleanup old tasks in DB

                if not self.night and self.generate_timelapse_flag:
                    ### Generate timelapse at end of night
                    yesterday_ref = datetime.now() - timedelta(days=1)
                    timespec = yesterday_ref.strftime('%Y%m%d')
                    self._generateNightTimelapse(timespec, self.config['DB_CCD_ID'], keogram=True)

                elif self.night and self.generate_timelapse_flag:
                    ### Generate timelapse at end of day
                    today_ref = datetime.now()
                    timespec = today_ref.strftime('%Y%m%d')
                    self._generateDayTimelapse(timespec, self.config['DB_CCD_ID'], keogram=True)


            self.indiclient.getCcdTemperature(self.ccdDevice)

            if self.night:
                # always indicate timelapse generation at night
                self.generate_timelapse_flag = True  # indicate images have been generated for timelapse
            elif self.config['DAYTIME_TIMELAPSE']:
                # must be day time
                self.generate_timelapse_flag = True  # indicate images have been generated for timelapse


            # Queue externally defined tasks
            self._queueManualTasks()


            # every ~10 seconds end this loop and run the code above
            for x in range(200):
                time.sleep(0.05)

                now = time.time()

                last_camera_ready = camera_ready
                camera_ready, exposure_state = self.indiclient.ctl_ready(exposure_ctl)

                if not camera_ready:
                    continue

                ###########################################
                # Camera is ready, not taking an exposure #
                ###########################################
                if not last_camera_ready:
                    camera_ready_time = now


                if waiting_for_frame:
                    frame_elapsed = now - frame_start_time

                    waiting_for_frame = False

                    logger.info('Exposure received in %0.4f s (%0.4f)', frame_elapsed, frame_elapsed - self.exposure_v.value)


                ##########################################################################
                # Here we know the camera is not busy and we are not waiting for a frame #
                ##########################################################################

                # shutdown here to ensure camera is not taking images
                if self.shutdown:
                    logger.warning('Shutting down')
                    self._stopImageWorker(terminate=self.terminate)
                    self._stopVideoWorker(terminate=self.terminate)
                    self._stopFileUploadWorker(terminate=self.terminate)

                    self.indiclient.disconnectServer()

                    sys.exit()


                # restart here to ensure camera is not taking images
                if self.restart:
                    logger.warning('Restarting processes')
                    self.restart = False
                    self._stopImageWorker()
                    self._stopVideoWorker()
                    self._stopFileUploadWorker()
                    # processes will start at the next loop


                # reconfigure if needed
                self.reconfigureCcd(self.ccdDevice)

                # these tasks run every ~5 minutes
                self.periodic_reconfigure(self.ccdDevice)


                if now >= next_frame_time:
                    #######################
                    # Start next exposure #
                    #######################

                    total_elapsed = now - frame_start_time

                    frame_start_time = now

                    exposure_ctl = self.shoot(self.ccdDevice, self.exposure_v.value, sync=False)
                    camera_ready = False
                    waiting_for_frame = True

                    next_frame_time = frame_start_time + self.config['EXPOSURE_PERIOD']

                    logger.info('Total time since last exposure %0.4f s', total_elapsed)


            loop_elapsed = now - loop_start_time
            logger.debug('Loop completed in %0.4f s', loop_elapsed)


    def cameraReport(self):
        # instantiate the client
        self.indiclient = IndiClient(
            self.config,
            self.image_q,
            self.gain_v,
            self.bin_v,
            self.sensortemp_v,
        )

        # set indi server localhost and port
        self.indiclient.setServer(self.config['INDI_SERVER'], self.config['INDI_PORT'])

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

        # get CCD information
        ccd_info = self.indiclient.getCcdInfo(self.ccdDevice)

        logger.info('Camera Info: %s', json.dumps(ccd_info, indent=4))

        self.indiclient.disconnectServer()



    def reconfigureCcd(self, ccdDevice):

        if self.night_v.value != int(self.night):
            pass
        elif self.night and bool(self.moonmode_v.value) != bool(self.moonmode):
            pass
        else:
            # No need to reconfigure
            return


        # Sleep before reconfiguration
        time.sleep(5.0)

        if self.night:
            if self.moonmode:
                logger.warning('Change to night (moon mode)')
                self.indiclient.setCcdGain(ccdDevice, self.config['CCD_CONFIG']['MOONMODE']['GAIN'])
                self.indiclient.setCcdBinning(ccdDevice, self.config['CCD_CONFIG']['MOONMODE']['BINNING'])
            else:
                logger.warning('Change to night (normal mode)')
                self.indiclient.setCcdGain(ccdDevice, self.config['CCD_CONFIG']['NIGHT']['GAIN'])
                self.indiclient.setCcdBinning(ccdDevice, self.config['CCD_CONFIG']['NIGHT']['BINNING'])
        else:
            logger.warning('Change to day')
            self.indiclient.setCcdGain(ccdDevice, self.config['CCD_CONFIG']['DAY']['GAIN'])
            self.indiclient.setCcdBinning(ccdDevice, self.config['CCD_CONFIG']['DAY']['BINNING'])


        # Update shared values
        with self.night_v.get_lock():
            self.night_v.value = int(self.night)

        with self.moonmode_v.get_lock():
            self.moonmode_v.value = int(self.moonmode)


        # Sleep after reconfiguration
        time.sleep(5.0)


    def detectNight(self):
        obs = ephem.Observer()
        obs.lon = math.radians(self.config['LOCATION_LONGITUDE'])
        obs.lat = math.radians(self.config['LOCATION_LATITUDE'])
        obs.date = datetime.utcnow()  # ephem expects UTC dates

        sun = ephem.Sun()
        sun.compute(obs)

        logger.info('Sun altitude: %s', sun.alt)

        self.night = sun.alt < self.night_sun_radians  # boolean


    def detectMoonMode(self):
        # detectNight() should be run first
        obs = ephem.Observer()
        obs.lon = math.radians(self.config['LOCATION_LONGITUDE'])
        obs.lat = math.radians(self.config['LOCATION_LATITUDE'])
        obs.date = datetime.utcnow()  # ephem expects UTC dates

        moon = ephem.Moon()
        moon.compute(obs)

        moon_phase = moon.moon_phase * 100.0

        logger.info('Moon altitide: %s, phase %0.1f%%', moon.alt, moon_phase)
        if self.night:
            if moon.alt >= self.night_moonmode_radians:
                if moon_phase >= self.config['NIGHT_MOONMODE_PHASE']:
                    logger.info('Moon Mode conditions detected')
                    self.moonmode = True
                    return

        self.moonmode = False


    def darks(self):
        logger.error('This functionality has been moved to the darks.py script')
        sys.exit()


    def generateDayTimelapse(self, timespec='', camera_id=0):
        # run from command line
        self.config['TIMELAPSE_ENABLE'] = True

        if camera_id == 0:
            try:
                camera_id = self._miscDb.getCurrentCameraId()
            except NoResultFound:
                logger.error('No camera found')
                sys.exit(1)
        else:
            camera_id = int(camera_id)


        self._generateDayTimelapse(timespec, camera_id, keogram=False, task_state=TaskQueueState.MANUAL)


    def _generateDayTimelapse(self, timespec, camera_id, keogram=True, task_state=TaskQueueState.QUEUED):
        if not self.config.get('TIMELAPSE_ENABLE', True):
            logger.warning('Timelapse creation disabled')
            return

        img_base_folder = self.image_dir.joinpath('{0:s}'.format(timespec))

        logger.warning('Generating day time timelapse for %s camera %d', timespec, camera_id)
        img_day_folder = img_base_folder.joinpath('day')

        jobdata = {
            'timespec'    : timespec,
            'img_folder'  : str(img_day_folder),
            'timeofday'   : 'day',
            'camera_id'   : camera_id,
            'video'       : True,
            'keogram'     : keogram,
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=task_state,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.video_q.put({'task_id' : task.id})


    def generateNightTimelapse(self, timespec='', camera_id=0):
        # run from command line
        self.config['TIMELAPSE_ENABLE'] = True

        if camera_id == 0:
            try:
                camera_id = self._miscDb.getCurrentCameraId()
            except NoResultFound:
                logger.error('No camera found')
                sys.exit(1)
        else:
            camera_id = int(camera_id)


        self._generateNightTimelapse(timespec, camera_id, keogram=False, task_state=TaskQueueState.MANUAL)


    def _generateNightTimelapse(self, timespec, camera_id, keogram=True, task_state=TaskQueueState.QUEUED):
        if not self.config.get('TIMELAPSE_ENABLE', True):
            logger.warning('Timelapse creation disabled')
            return

        img_base_folder = self.image_dir.joinpath('{0:s}'.format(timespec))

        logger.warning('Generating night time timelapse for %s camera %d', timespec, camera_id)
        img_day_folder = img_base_folder.joinpath('night')

        jobdata = {
            'timespec'    : timespec,
            'img_folder'  : str(img_day_folder),
            'timeofday'   : 'night',
            'camera_id'   : camera_id,
            'video'       : True,
            'keogram'     : keogram,
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=task_state,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.video_q.put({'task_id' : task.id})


    def generateNightKeogram(self, timespec='', camera_id=0):
        # run from command line
        self.config['TIMELAPSE_ENABLE'] = True

        if camera_id == 0:
            try:
                camera_id = self._miscDb.getCurrentCameraId()
            except NoResultFound:
                logger.error('No camera found')
                sys.exit(1)
        else:
            camera_id = int(camera_id)


        self._generateNightKeogram(timespec, camera_id, task_state=TaskQueueState.MANUAL)


    def _generateNightKeogram(self, timespec, camera_id, task_state=TaskQueueState.QUEUED):
        if not self.config.get('TIMELAPSE_ENABLE', True):
            logger.warning('Timelapse creation disabled')
            return

        img_base_folder = self.image_dir.joinpath('{0:s}'.format(timespec))

        logger.warning('Generating night time keogram for %s camera %d', timespec, camera_id)
        img_day_folder = img_base_folder.joinpath('night')

        jobdata = {
            'timespec'    : timespec,
            'img_folder'  : str(img_day_folder),
            'timeofday'   : 'night',
            'camera_id'   : camera_id,
            'video'       : False,
            'keogram'     : True,
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=task_state,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.video_q.put({'task_id' : task.id})


    def generateDayKeogram(self, timespec='', camera_id=0):
        # run from command line
        self.config['TIMELAPSE_ENABLE'] = True

        if camera_id == 0:
            try:
                camera_id = self._miscDb.getCurrentCameraId()
            except NoResultFound:
                logger.error('No camera found')
                sys.exit(1)
        else:
            camera_id = int(camera_id)


        self._generateDayKeogram(timespec, camera_id, task_state=TaskQueueState.MANUAL)


    def _generateDayKeogram(self, timespec, camera_id, task_state=TaskQueueState.QUEUED):
        if not self.config.get('TIMELAPSE_ENABLE', True):
            logger.warning('Timelapse creation disabled')
            return

        img_base_folder = self.image_dir.joinpath('{0:s}'.format(timespec))

        logger.warning('Generating day time keogram for %s camera %d', timespec, camera_id)
        img_day_folder = img_base_folder.joinpath('day')

        jobdata = {
            'timespec'    : timespec,
            'img_folder'  : str(img_day_folder),
            'timeofday'   : 'day',
            'camera_id'   : camera_id,
            'video'       : False,
            'keogram'     : True,
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=task_state,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.video_q.put({'task_id' : task.id})


    def shoot(self, ccdDevice, exposure, sync=True, timeout=None):
        logger.info('Taking %0.8f s exposure (gain %d)', exposure, self.gain_v.value)

        ctl = self.indiclient.setCcdExposure(ccdDevice, exposure, sync=sync, timeout=timeout)

        return ctl


    def expireData(self):
        self._expireData(TaskQueueState.MANUAL)


    def _expireData(self, task_state=TaskQueueState.QUEUED):
        # This will delete old images from the filesystem and DB
        jobdata = {
            'expireData'   : True,
            'img_folder'   : str(self.image_dir),
            'timespec'     : None,  # Not needed
            'timeofday'    : None,  # Not needed
            'camera_id'    : None,  # Not needed
            'video'        : False,
            'keogram'      : False,
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=task_state,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.video_q.put({'task_id' : task.id})


    def dbImportImages(self):
        from .flask.models import IndiAllSkyDbImageTable
        from .flask.models import IndiAllSkyDbDarkFrameTable
        from .flask.models import IndiAllSkyDbVideoTable
        from .flask.models import IndiAllSkyDbKeogramTable
        from .flask.models import IndiAllSkyDbStarTrailsTable

        try:
            camera_id = self._miscDb.getCurrentCameraId()
        except NoResultFound:
            logger.error('No camera found')
            sys.exit(1)


        ### Dark frames
        file_list_darkframes = list()
        self.getFolderFilesByExt(self.image_dir.joinpath('darks'), file_list_darkframes, extension_list=['fit', 'fits'])


        #/var/www/html/allsky/images/darks/dark_ccd1_8bit_6s_gain250_bin1_10c_20210826_020202.fit
        re_darkframe = re.compile(r'\/dark_ccd(?P<ccd_id_str>\d+)_(?P<bitdepth_str>\d+)bit_(?P<exposure_str>\d+)s_gain(?P<gain_str>\d+)_bin(?P<binmode_str>\d+)_(?P<ccdtemp_str>\-?\d+)c_(?P<createDate_str>[0-9_]+)\.[a-z]+$')

        darkframe_entries = list()
        for f in file_list_darkframes:
            #logger.info('Raw frame: %s', f)

            m = re.search(re_darkframe, str(f))
            if not m:
                logger.error('Regex did not match file: %s', f)
                continue


            #logger.info('CCD ID string: %s', m.group('ccd_id_str'))
            #logger.info('Exposure string: %s', m.group('exposure_str'))
            #logger.info('Bitdepth string: %s', m.group('bitdepth_str'))
            #logger.info('Gain string: %s', m.group('gain_str'))
            #logger.info('Binmode string: %s', m.group('binmode_str'))
            #logger.info('Ccd temp string: %s', m.group('ccdtemp_str'))

            ccd_id = int(m.group('ccd_id_str'))
            exposure = int(m.group('exposure_str'))
            bitdepth = int(m.group('bitdepth_str'))
            gain = int(m.group('gain_str'))
            binmode = int(m.group('binmode_str'))
            ccdtemp = float(m.group('ccdtemp_str'))


            d_createDate = datetime.fromtimestamp(f.stat().st_mtime)

            darkframe_dict = {
                'filename'   : str(f),
                'createDate' : d_createDate,
                'bitdepth'   : bitdepth,
                'exposure'   : exposure,
                'gain'       : gain,
                'binmode'    : binmode,
                'camera_id'  : ccd_id,
                'temp'       : ccdtemp,
            }

            darkframe_entries.append(darkframe_dict)


        try:
            db.session.bulk_insert_mappings(IndiAllSkyDbDarkFrameTable, darkframe_entries)
            db.session.commit()

            logger.warning('*** Dark frames inserted ***')
        except IntegrityError as e:
            logger.warning('Integrity error: %s', str(e))
            db.session.rollback()


        ### Timelapse
        file_list_videos = list()
        self.getFolderFilesByExt(self.image_dir, file_list_videos, extension_list=['mp4'])


        #/var/www/html/allsky/images/20210915/allsky-timelapse_ccd1_20210915_night.mp4
        re_video = re.compile(r'(?P<dayDate_str>\d{8})\/.+timelapse_ccd(?P<ccd_id_str>\d+)_\d{8}_(?P<timeofday_str>[a-z]+)\.[a-z0-9]+$')

        video_entries = list()
        for f in file_list_videos:
            #logger.info('Timelapse: %s', f)

            m = re.search(re_video, str(f))
            if not m:
                logger.error('Regex did not match file: %s', f)
                continue

            #logger.info('dayDate string: %s', m.group('dayDate_str'))
            #logger.info('Time of day string: %s', m.group('timeofday_str'))

            d_dayDate = datetime.strptime(m.group('dayDate_str'), '%Y%m%d').date()
            #logger.info('dayDate: %s', str(d_dayDate))

            if m.group('timeofday_str') == 'night':
                night = True
            else:
                night = False

            d_createDate = datetime.fromtimestamp(f.stat().st_mtime)

            video_dict = {
                'filename'   : str(f),
                'createDate' : d_createDate,
                'dayDate'    : d_dayDate,
                'night'      : night,
                'uploaded'   : False,
                'camera_id'  : camera_id,
            }

            video_entries.append(video_dict)


        try:
            db.session.bulk_insert_mappings(IndiAllSkyDbVideoTable, video_entries)
            db.session.commit()

            logger.warning('*** Timelapse videos inserted ***')
        except IntegrityError as e:
            logger.warning('Integrity error: %s', str(e))
            db.session.rollback()



        ### find all imaegs
        file_list = list()
        self.getFolderFilesByExt(self.image_dir, file_list, extension_list=['jpg', 'jpeg', 'png', 'tif', 'tiff'])


        ### Keograms
        file_list_keograms = filter(lambda p: 'keogram' in p.name, file_list)

        #/var/www/html/allsky/images/20210915/allsky-keogram_ccd1_20210915_night.jpg
        re_keogram = re.compile(r'(?P<dayDate_str>\d{8})\/.+keogram_ccd(?P<ccd_id_str>\d+)_\d{8}_(?P<timeofday_str>[a-z]+)\.[a-z]+$')

        keogram_entries = list()
        for f in file_list_keograms:
            #logger.info('Keogram: %s', f)

            m = re.search(re_keogram, str(f))
            if not m:
                logger.error('Regex did not match file: %s', f)
                continue

            #logger.info('dayDate string: %s', m.group('dayDate_str'))
            #logger.info('Time of day string: %s', m.group('timeofday_str'))

            d_dayDate = datetime.strptime(m.group('dayDate_str'), '%Y%m%d').date()
            #logger.info('dayDate: %s', str(d_dayDate))

            if m.group('timeofday_str') == 'night':
                night = True
            else:
                night = False

            d_createDate = datetime.fromtimestamp(f.stat().st_mtime)

            keogram_dict = {
                'filename'   : str(f),
                'createDate' : d_createDate,
                'dayDate'    : d_dayDate,
                'night'      : night,
                'uploaded'   : False,
                'camera_id'  : camera_id,
            }

            keogram_entries.append(keogram_dict)


        try:
            db.session.bulk_insert_mappings(IndiAllSkyDbKeogramTable, keogram_entries)
            db.session.commit()

            logger.warning('*** Keograms inserted ***')
        except IntegrityError as e:
            logger.warning('Integrity error: %s', str(e))
            db.session.rollback()


        ### Star trails
        file_list_startrail = filter(lambda p: 'startrail' in p.name, file_list)

        #/var/www/html/allsky/images/20210915/allsky-startrail_ccd1_20210915_night.jpg
        re_startrail = re.compile(r'(?P<dayDate_str>\d{8})\/.+startrails?_ccd(?P<ccd_id_str>\d+)_\d{8}_(?P<timeofday_str>[a-z]+)\.[a-z]+$')

        startrail_entries = list()
        for f in file_list_startrail:
            #logger.info('Star trail: %s', f)

            m = re.search(re_startrail, str(f))
            if not m:
                logger.error('Regex did not match file: %s', f)
                continue

            #logger.info('dayDate string: %s', m.group('dayDate_str'))
            #logger.info('Time of day string: %s', m.group('timeofday_str'))

            d_dayDate = datetime.strptime(m.group('dayDate_str'), '%Y%m%d').date()
            #logger.info('dayDate: %s', str(d_dayDate))

            if m.group('timeofday_str') == 'night':
                night = True
            else:
                night = False

            d_createDate = datetime.fromtimestamp(f.stat().st_mtime)

            startrail_dict = {
                'filename'   : str(f),
                'createDate' : d_createDate,
                'dayDate'    : d_dayDate,
                'night'      : night,
                'uploaded'   : False,
                'camera_id'  : camera_id,
            }

            startrail_entries.append(startrail_dict)


        try:
            db.session.bulk_insert_mappings(IndiAllSkyDbStarTrailsTable, startrail_entries)
            db.session.commit()

            logger.warning('*** Star trails inserted ***')
        except IntegrityError as e:
            logger.warning('Integrity error: %s', str(e))
            db.session.rollback()


        ### Images
        # Exclude keograms and star trails
        file_list_images_nok = filter(lambda p: 'keogram' not in p.name, file_list)
        file_list_images_nok_nost = filter(lambda p: 'startrail' not in p.name, file_list_images_nok)

        #/var/www/html/allsky/images/20210825/night/26_02/ccd1_20210826_020202.jpg
        re_image = re.compile(r'(?P<dayDate_str>\d{8})\/(?P<timeofday_str>[a-z]+)\/\d{2}_\d{2}\/ccd(?P<ccd_id_str>\d+)_(?P<createDate_str>[0-9_]+)\.[a-z]+$')

        image_entries = list()
        for f in file_list_images_nok_nost:
            #logger.info('Image: %s', f)

            m = re.search(re_image, str(f))
            if not m:
                logger.error('Regex did not match file: %s', f)
                continue

            #logger.info('dayDate string: %s', m.group('dayDate_str'))
            #logger.info('Time of day string: %s', m.group('timeofday_str'))
            #logger.info('createDate string: %s', m.group('createDate_str'))

            d_dayDate = datetime.strptime(m.group('dayDate_str'), '%Y%m%d').date()
            #logger.info('dayDate: %s', str(d_dayDate))

            if m.group('timeofday_str') == 'night':
                night = True
            else:
                night = False

            #d_createDate = datetime.strptime(m.group('createDate_str'), '%Y%m%d_%H%M%S')
            d_createDate = datetime.fromtimestamp(f.stat().st_mtime)
            #logger.info('createDate: %s', str(d_createDate))


            image_dict = {
                'filename'   : str(f),
                'camera_id'  : camera_id,
                'createDate' : d_createDate,
                'dayDate'    : d_dayDate,
                'exposure'   : 0.0,
                'gain'       : -1,
                'binmode'    : 1,
                'night'      : night,
                'adu'        : 0.0,
                'stable'     : True,
                'moonmode'   : False,
                'adu_roi'    : False,
                'uploaded'   : False,
            }


            image_entries.append(image_dict)

        try:
            db.session.bulk_insert_mappings(IndiAllSkyDbImageTable, image_entries)
            db.session.commit()

            logger.warning('*** Images inserted ***')
        except IntegrityError as e:
            logger.warning('Integrity error: %s', str(e))
            db.session.rollback()


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


    def _expireOrphanedTasks(self):
        orphaned_statuses = (
            TaskQueueState.MANUAL,
            TaskQueueState.QUEUED,
            TaskQueueState.RUNNING,
        )

        old_task_list = IndiAllSkyDbTaskQueueTable.query\
            .filter(IndiAllSkyDbTaskQueueTable.state.in_(orphaned_statuses))

        for task in old_task_list:
            logger.warning('Expiring orphaned task %d', task.id)
            task.state = TaskQueueState.EXPIRED

        db.session.commit()


    def _flushOldTasks(self):
        now_minus_3d = datetime.now() - timedelta(days=3)

        flush_old_tasks = IndiAllSkyDbTaskQueueTable.query\
            .filter(IndiAllSkyDbTaskQueueTable.createDate < now_minus_3d)

        logger.warning('Found %d expired tasks to delete', flush_old_tasks.count())
        flush_old_tasks.delete()
        db.session.commit()


    def _queueManualTasks(self):
        logger.info('Checking for manually submitted tasks')
        manual_video_tasks = IndiAllSkyDbTaskQueueTable.query\
            .filter(IndiAllSkyDbTaskQueueTable.queue == TaskQueueQueue.VIDEO)\
            .filter(IndiAllSkyDbTaskQueueTable.state == TaskQueueState.MANUAL)\
            .order_by(IndiAllSkyDbTaskQueueTable.createDate.asc())


        for video_task in manual_video_tasks:
            logger.info('Queuing manual task %d', video_task.id)
            video_task.setQueued()
            self.video_q.put({'task_id' : video_task.id})

