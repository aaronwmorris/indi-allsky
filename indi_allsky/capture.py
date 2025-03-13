import os
import time
import io
import json
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
import tempfile
import math
import subprocess
import dbus
import signal
import logging
import traceback

import ephem

from multiprocessing import Process
#from threading import Thread
import queue

from . import constants
from . import camera as camera_module

from .utils import IndiAllSkyDateCalcs

from .flask.models import TaskQueueQueue
from .flask.models import TaskQueueState

from .flask.models import IndiAllSkyDbCameraTable
from .flask.models import IndiAllSkyDbImageTable
from .flask.models import NotificationCategory
from .flask.models import IndiAllSkyDbTaskQueueTable

from .exceptions import IndiServerException
from .exceptions import CameraException
from .exceptions import TimeOutException
from .exceptions import TemperatureException

from .flask import create_app
from .flask import db
from .flask.miscDb import miscDb

from sqlalchemy.orm.exc import MultipleResultsFound


app = create_app()

logger = logging.getLogger('indi_allsky')


class CaptureWorker(Process):

    periodic_tasks_offset = 300.0  # 5 minutes


    SENSOR_SLOTS = (
        ['sensor_user_0', 'Camera Temp'],  # mutable
        ['sensor_user_1', 'Dew Heater Level'],
        ['sensor_user_2', 'Dew Point'],
        ['sensor_user_3', 'Frost Point'],
        ['sensor_user_4', 'Fan Level'],
        ['sensor_user_5', 'Heat Index'],
        ['sensor_user_6', 'Wind Dir Degrees'],
        ['sensor_user_7', 'SQM'],
        ['sensor_user_8', 'Future Use 8'],
        ['sensor_user_9', 'Future Use 9'],
        ['sensor_user_10', 'User Slot 10'],
        ['sensor_user_11', 'User Slot 11'],
        ['sensor_user_12', 'User Slot 12'],
        ['sensor_user_13', 'User Slot 13'],
        ['sensor_user_14', 'User Slot 14'],
        ['sensor_user_15', 'User Slot 15'],
        ['sensor_user_16', 'User Slot 16'],
        ['sensor_user_17', 'User Slot 17'],
        ['sensor_user_18', 'User Slot 18'],
        ['sensor_user_19', 'User Slot 19'],
        ['sensor_user_20', 'User Slot 20'],
        ['sensor_user_21', 'User Slot 21'],
        ['sensor_user_22', 'User Slot 22'],
        ['sensor_user_23', 'User Slot 23'],
        ['sensor_user_24', 'User Slot 24'],
        ['sensor_user_25', 'User Slot 25'],
        ['sensor_user_26', 'User Slot 26'],
        ['sensor_user_27', 'User Slot 27'],
        ['sensor_user_28', 'User Slot 28'],
        ['sensor_user_29', 'User Slot 29'],
        ['sensor_temp_0', 'Camera Temp'],
        ['sensor_temp_1', 'Future Use 1'],
        ['sensor_temp_2', 'Future Use 2'],
        ['sensor_temp_3', 'Future Use 3'],
        ['sensor_temp_4', 'Future Use 4'],
        ['sensor_temp_5', 'Future Use 5'],
        ['sensor_temp_6', 'Future Use 6'],
        ['sensor_temp_7', 'Future Use 7'],
        ['sensor_temp_8', 'Future Use 8'],
        ['sensor_temp_9', 'Future Use 9'],
        ['sensor_temp_10', 'System Temp 10'],
        ['sensor_temp_11', 'System Temp 11'],
        ['sensor_temp_12', 'System Temp 12'],
        ['sensor_temp_13', 'System Temp 13'],
        ['sensor_temp_14', 'System Temp 14'],
        ['sensor_temp_15', 'System Temp 15'],
        ['sensor_temp_16', 'System Temp 16'],
        ['sensor_temp_17', 'System Temp 17'],
        ['sensor_temp_18', 'System Temp 18'],
        ['sensor_temp_19', 'System Temp 19'],
        ['sensor_temp_20', 'System Temp 20'],
        ['sensor_temp_21', 'System Temp 21'],
        ['sensor_temp_22', 'System Temp 22'],
        ['sensor_temp_23', 'System Temp 23'],
        ['sensor_temp_24', 'System Temp 24'],
        ['sensor_temp_25', 'System Temp 25'],
        ['sensor_temp_26', 'System Temp 26'],
        ['sensor_temp_27', 'System Temp 27'],
        ['sensor_temp_28', 'System Temp 28'],
        ['sensor_temp_29', 'System Temp 29'],
    )


    def __init__(
        self,
        idx,
        config,
        error_q,
        capture_q,
        image_q,
        video_q,
        upload_q,
        position_av,
        exposure_av,
        gain_v,
        bin_v,
        sensors_temp_av,
        sensors_user_av,
        night_v,
        moonmode_v,
    ):

        super(CaptureWorker, self).__init__()

        self.name = 'Capture-{0:d}'.format(idx)

        self.config = config
        self.error_q = error_q
        self.capture_q = capture_q
        self.image_q = image_q
        self.video_q = video_q
        self.upload_q = upload_q

        self.position_av = position_av  # lat, long, elev, ra, dec

        self.exposure_av = exposure_av  # current, min night, min day, max

        self.gain_v = gain_v
        self.bin_v = bin_v
        self.sensors_temp_av = sensors_temp_av  # 0 ccd_temp
        self.sensors_user_av = sensors_user_av  # 0 ccd_temp
        self.night_v = night_v
        self.moonmode_v = moonmode_v

        self._miscDb = miscDb(self.config)
        self._dateCalcs = IndiAllSkyDateCalcs(self.config, self.position_av)

        self.next_forced_transition_time = None

        self.indiclient = None

        self.night = None
        self.moonmode = None

        self.camera_id = None
        self.camera_name = None
        self.camera_server = None

        self.indi_config = self.config.get('INDI_CONFIG_DEFAULTS', {})
        self.reconfigure_camera = False

        self.focus_mode = self.config.get('FOCUS_MODE', False)  # focus mode takes images as fast as possible

        self.night_sun_radians = math.radians(self.config['NIGHT_SUN_ALT_DEG'])
        self.night_moonmode_radians = math.radians(self.config['NIGHT_MOONMODE_ALT_DEG'])

        self.update_time_offset = None  # when time needs to be updated, this will be the offset

        self.image_queue_max = self.config.get('IMAGE_QUEUE_MAX', 3)
        self.image_queue_min = self.config.get('IMAGE_QUEUE_MIN', 1)
        self.image_queue_backoff = self.config.get('IMAGE_QUEUE_BACKOFF', 0.5)
        self.add_period_delay = 0.0

        self.periodic_tasks_time = time.time() + self.periodic_tasks_offset
        #self.periodic_tasks_time = time.time()  # testing


        if self.config['IMAGE_FOLDER']:
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()


        self.generate_timelapse_flag = False   # This is updated once images have been generated

        self._shutdown = False



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

        with app.app_context():
            self._initialize()

            self._pre_run_tasks()


        next_frame_time = time.time()  # start immediately
        frame_start_time = time.time()
        waiting_for_frame = False

        camera_ready_time = time.time()
        camera_ready = False
        exposure_aborted = False
        last_camera_ready = False
        exposure_state = 'unset'
        check_exposure_state = time.time() + 300  # check in 5 minutes

        self.reconfigure_camera = True  # reconfigure on first run


        self.next_forced_transition_time = self._dateCalcs.getNextDayNightTransition().timestamp()
        logger.warning(
            'Next forced transition time: %s (%0.1fh)',
            datetime.fromtimestamp(self.next_forced_transition_time).strftime('%Y-%m-%d %H:%M:%S'),
            (self.next_forced_transition_time - time.time()) / 3600,
        )


        self.detectNight()

        ### Update shared values to match current state
        with self.night_v.get_lock():
            self.night_v.value = int(self.night)

        with self.moonmode_v.get_lock():
            self.moonmode_v.value = int(self.moonmode)



        ### main loop starts
        while True:
            loop_start_time = time.time()


            logger.info('Camera last ready: %0.1fs', loop_start_time - camera_ready_time)
            logger.info('Exposure state: %s', exposure_state)


            if self.indiclient.disconnected:
                logger.error('indiclient indicates indiserver disconnected, restarting capture process')
                return


            try:
                c_dict = self.capture_q.get(False)

                if c_dict.get('stop'):
                    self._shutdown = True
                elif c_dict.get('settime'):
                    self.update_time_offset = int(c_dict['settime'])
                else:
                    logger.error('Unknown action: %s', str(c_dict))

            except queue.Empty:
                pass


            self.detectNight()


            with app.app_context():
                if bool(self.night_v.value) != self.night:
                    ### Change between day and night

                    self.reconfigure_camera = True

                    # update transition time
                    self.next_forced_transition_time = self._dateCalcs.getNextDayNightTransition().timestamp()

                    logger.warning(
                        'Next forced transition time: %s (%0.1fh)',
                        datetime.fromtimestamp(self.next_forced_transition_time).strftime('%Y-%m-%d %H:%M:%S'),
                        (self.next_forced_transition_time - loop_start_time) / 3600,
                    )


                    dayDate = self._dateCalcs.getDayDate()


                    if not self.night and self.generate_timelapse_flag:
                        self._expireData(self.camera_id)  # cleanup old images and folders

                        ### Generate timelapse at end of night
                        yesterday_ref = dayDate - timedelta(days=1)
                        timespec = yesterday_ref.strftime('%Y%m%d')
                        self._generateNightKeogram(timespec, self.camera_id)  # keogram/st first
                        self._generateNightTimelapse(timespec, self.camera_id)
                        self._uploadAllskyEndOfNight(self.camera_id)

                    elif self.night and self.generate_timelapse_flag:
                        self._expireData(self.camera_id)  # cleanup old images and folders

                        ### Generate timelapse at end of day
                        today_ref = dayDate
                        timespec = today_ref.strftime('%Y%m%d')
                        self._generateDayKeogram(timespec, self.camera_id)  # keogram/st first
                        self._generateDayTimelapse(timespec, self.camera_id)

                elif self.night and bool(self.moonmode_v.value) != self.moonmode:
                    # Switch between night non-moonmode and moonmode
                    self.reconfigure_camera = True

                elif loop_start_time > self.next_forced_transition_time:
                    # this should only happen when the sun never sets/rises

                    self.reconfigure_camera = True

                    if self.night:
                        logger.warning('End of night reached, forcing transition to next night period')
                    else:
                        logger.warning('End of day reached, forcing transition to next day period')


                    # update transition time
                    self.next_forced_transition_time = self._dateCalcs.getNextDayNightTransition().timestamp()
                    logger.warning(
                        'Next forced transition time: %s (%0.1fh)',
                        datetime.fromtimestamp(self.next_forced_transition_time).strftime('%Y-%m-%d %H:%M:%S'),
                        (self.next_forced_transition_time - loop_start_time) / 3600,
                    )


                    dayDate = self._dateCalcs.getDayDate()


                    if not self.night and self.generate_timelapse_flag:
                        self._expireData(self.camera_id)  # cleanup old images and folders

                        ### Generate timelapse at end of day
                        yesterday_ref = dayDate - timedelta(days=1)
                        timespec = yesterday_ref.strftime('%Y%m%d')
                        self._generateDayKeogram(timespec, self.camera_id)  # keogram/st first
                        self._generateDayTimelapse(timespec, self.camera_id)
                        self._expireData(self.camera_id)  # cleanup old images and folders

                    elif self.night and self.generate_timelapse_flag:
                        self._expireData(self.camera_id)  # cleanup old images and folders

                        ### Generate timelapse at end of night
                        yesterday_ref = dayDate - timedelta(days=1)
                        timespec = yesterday_ref.strftime('%Y%m%d')
                        self._generateNightKeogram(timespec, self.camera_id)  # keogram/st first
                        self._generateNightTimelapse(timespec, self.camera_id)
                        self._uploadAllskyEndOfNight(self.camera_id)


                if self.night:
                    # always indicate timelapse generation at night
                    self.generate_timelapse_flag = True
                else:
                    # day
                    if not self.config.get('DAYTIME_CAPTURE') or not self.config.get('DAYTIME_CAPTURE_SAVE', True):
                        self.generate_timelapse_flag = False
                    else:
                        self.generate_timelapse_flag = True


                #logger.warning(
                #    'Next forced transition time: %s (%0.1fh)',
                #    datetime.fromtimestamp(self.next_forced_transition_time).strftime('%Y-%m-%d %H:%M:%S'),
                #    (self.next_forced_transition_time - loop_start_time) / 3600,
                #)


                self.getCcdTemperature()
                self.getTelescopeRaDec()
                self.getGpsPosition()


                if self.config.get('CAPTURE_PAUSE'):
                    logger.warning('*** CAPTURE PAUSED ***')

                    now = time.time()
                    self._miscDb.setState('WATCHDOG', int(now))
                    self._miscDb.setState('STATUS', constants.STATUS_PAUSED)

                    if self._shutdown:
                        logger.warning('Shutting down')
                        self.indiclient.disableCcdCooler()  # safety

                        self.indiclient.disconnectServer()

                        logger.warning('Goodbye')
                        return


                    time.sleep(31)  # prime number
                    continue

                elif not self.night and not self.config.get('DAYTIME_CAPTURE'):
                    logger.info('Daytime capture disabled')
                    self.generate_timelapse_flag = False

                    now = time.time()
                    self._miscDb.setState('WATCHDOG', int(now))
                    self._miscDb.setState('STATUS', constants.STATUS_SLEEPING)

                    if self._shutdown:
                        logger.warning('Shutting down')
                        self.indiclient.disableCcdCooler()  # safety

                        self.indiclient.disconnectServer()

                        logger.warning('Goodbye')
                        return


                    time.sleep(31)  # prime number
                    continue


                # check exposure state every 5 minutes
                if check_exposure_state < loop_start_time:
                    check_exposure_state = time.time() + 300  # next check in 5 minutes

                    camera_last_ready_s = int(loop_start_time - camera_ready_time)
                    if camera_last_ready_s > 300:
                        self._miscDb.addNotification(
                            NotificationCategory.CAMERA,
                            'last_ready',
                            'Camera last ready {0:d}s ago. Camera might be hung. Aborting exposure.'.format(camera_last_ready_s),
                            expire=timedelta(minutes=60),
                        )

                        self.indiclient.abortCcdExposure()
                        exposure_aborted = True


                # Loop to run for 11 seconds (prime number)
                loop_end = time.time() + 11

                while True:
                    time.sleep(0.05)

                    now = time.time()
                    if now >= loop_end:
                        break

                    last_camera_ready = camera_ready


                    if not exposure_aborted:
                        camera_ready, exposure_state = self.indiclient.getCcdExposureStatus()
                    else:
                        # Aborted exposure, bypass next checks
                        exposure_aborted = False  # reset
                        camera_ready = True
                        exposure_state = 'Aborted'
                        waiting_for_frame = False


                    if not camera_ready:
                        continue

                    ###########################################
                    # Camera is ready, not taking an exposure #
                    ###########################################
                    if not last_camera_ready:
                        camera_ready_time = now


                    if waiting_for_frame:
                        frame_elapsed = now - frame_start_time
                        frame_delta = frame_elapsed - self.exposure_av[0]

                        waiting_for_frame = False

                        logger.info('Exposure received in %0.4f s (%0.4f)', frame_elapsed, frame_delta)


                        if frame_delta < -1:

                            if self.config['CAMERA_INTERFACE'].startswith('pycurl'):
                                ### camera does not obey expsoure values
                                pass
                            elif self.config['CAMERA_INTERFACE'] == 'indi_passive':
                                ### camera does not obey expsoure values
                                pass
                            else:
                                logger.error('%0.4fs EXPOSURE RECEIVED IN %0.4fs.  POSSIBLE CAMERA PROBLEM.', self.exposure_av[0], frame_elapsed)
                                self._miscDb.addNotification(
                                    NotificationCategory.CAMERA,
                                    'exposure_delta',
                                    '{0:0.1f}s exposure received in {1:0.1f}s.  Possible camera problem.'.format(self.exposure_av[0], frame_elapsed),
                                    expire=timedelta(minutes=60),
                                )



                    ##########################################################################
                    # Here we know the camera is not busy and we are not waiting for a frame #
                    ##########################################################################

                    # shutdown here to ensure camera is not taking images
                    if self._shutdown:
                        logger.warning('Shutting down')

                        self.indiclient.disableCcdCooler()  # safety

                        self.indiclient.disconnectServer()

                        logger.warning('Goodbye')
                        return


                    # reconfigure if needed
                    if self.reconfigure_camera:
                        self.reconfigureCcd()


                    # these tasks run every ~3 minutes
                    self._periodic_tasks()


                    # update system time from time offset
                    if self.update_time_offset:
                        utcnow = datetime.now(tz=timezone.utc)

                        new_time_utc = datetime.fromtimestamp(utcnow.timestamp() - self.update_time_offset).astimezone(tz=timezone.utc)

                        self.update_time_offset = None  # reset

                        try:
                            self.setTimeSystemd(new_time_utc)
                        except dbus.exceptions.DBusException as e:
                            logger.error('DBus Error: %s', str(e))

                        # time change, need to update next frame time
                        if self.night:
                            next_frame_time = time.time() + self.config['EXPOSURE_PERIOD']
                        else:
                            next_frame_time = time.time() + self.config['EXPOSURE_PERIOD_DAY']

                        break  # go ahead and break the loop to update other timestamps



                    if now >= next_frame_time:
                        #######################
                        # Start next exposure #
                        #######################

                        total_elapsed = now - frame_start_time

                        frame_start_time = now

                        self.shoot(self.exposure_av[0], sync=False)
                        camera_ready = False
                        waiting_for_frame = True


                        # if the image queue grows too large, introduce delays to new exposures
                        image_queue_size = self.image_q.qsize()
                        if image_queue_size > 0:
                            logger.warning('Image queue depth: %d', image_queue_size)


                        if image_queue_size <= self.image_queue_min:
                            if self.add_period_delay > 0:
                                logger.warning('IMAGE QUEUE UNDER MINIMUM: %d *** REMOVING DELAY BETWEEN EXPOSURES ***', image_queue_size)
                                self.add_period_delay = 0.0
                        elif image_queue_size >= self.image_queue_max:
                            if self.night:
                                self.add_period_delay = (image_queue_size / self.image_queue_max) * self.config['EXPOSURE_PERIOD'] * self.image_queue_backoff
                            else:
                                self.add_period_delay = (image_queue_size / self.image_queue_max) * self.config['EXPOSURE_PERIOD_DAY'] * self.image_queue_backoff

                            logger.warning('IMAGE QUEUE MAXIMUM EXCEEDED: %d *** ADDING ADDITIONAL %0.3fs DELAY BETWEEN EXPOSURES ***', image_queue_size, self.add_period_delay)

                            self._miscDb.addNotification(
                                NotificationCategory.WORKER,
                                'image_queue_depth',
                                'Image queue exceeded maximum threshold depth.  System processing might be degraded.',
                                expire=timedelta(hours=1),
                            )


                        if self.focus_mode:
                            # Start frame immediately in focus mode
                            logger.warning('*** FOCUS MODE ENABLED ***')
                            next_frame_time = now + self.config.get('FOCUS_DELAY', 4.0) + self.add_period_delay
                        elif self.night:
                            next_frame_time = frame_start_time + self.config['EXPOSURE_PERIOD'] + self.add_period_delay
                        else:
                            next_frame_time = frame_start_time + self.config['EXPOSURE_PERIOD_DAY'] + self.add_period_delay

                        logger.info('Total time since last exposure %0.4f s', total_elapsed)


                loop_elapsed = now - loop_start_time
                logger.debug('Loop completed in %0.4f s', loop_elapsed)




    def _initialize(self):
        camera_interface = getattr(camera_module, self.config.get('CAMERA_INTERFACE', 'indi'))


        # instantiate the client
        self.indiclient = camera_interface(
            self.config,
            self.image_q,
            self.position_av,
            self.gain_v,
            self.bin_v,
            self.night_v,
        )


        # set indi server localhost and port
        self.indiclient.setServer(self.config['INDI_SERVER'], self.config['INDI_PORT'])

        # connect to indi server
        logger.info("Connecting to indiserver")
        if not self.indiclient.connectServer():
            host = self.indiclient.getHost()
            port = self.indiclient.getPort()

            logger.error("No indiserver available at %s:%d", host, port)

            self._miscDb.setState('STATUS', constants.STATUS_NOINDISERVER)

            self._miscDb.addNotification(
                NotificationCategory.GENERAL,
                'no_indiserver',
                'Unable to connect to indiserver at {0:s}:{1:d}'.format(host, port),
                expire=timedelta(hours=2),
            )

            raise IndiServerException('indiserver not available')


        # give devices a chance to register
        time.sleep(5)

        try:
            self.indiclient.findCcd(camera_name=self.config.get('INDI_CAMERA_NAME'))
        except CameraException as e:
            logger.error('Camera error: !!! %s !!!', str(e).upper())

            self._miscDb.setState('STATUS', constants.STATUS_NOCAMERA)

            self._miscDb.addNotification(
                NotificationCategory.CAMERA,
                'no_camera',
                'Camera was not detected.',
                expire=timedelta(hours=2),
            )

            time.sleep(60)
            raise


        self.indiclient.findTelescope(telescope_name='Telescope Simulator')
        self.indiclient.findGps()


        logger.warning('Connecting to CCD device %s', self.indiclient.ccd_device.getDeviceName())
        self.indiclient.connectDevice(self.indiclient.ccd_device.getDeviceName())

        if self.indiclient.telescope_device:
            logger.warning('Connecting to Telescope device %s', self.indiclient.telescope_device.getDeviceName())
            self.indiclient.connectDevice(self.indiclient.telescope_device.getDeviceName())

        if self.config.get('GPS_ENABLE') and self.indiclient.gps_device:
            logger.warning('Connecting to GPS device %s', self.indiclient.gps_device.getDeviceName())
            self.indiclient.connectDevice(self.indiclient.gps_device.getDeviceName())


        # add driver name to config
        self.camera_name = self.indiclient.ccd_device.getDeviceName()
        self._miscDb.setState('CAMERA_NAME', self.camera_name)

        self.camera_server = self.indiclient.ccd_device.getDriverExec()
        self._miscDb.setState('CAMERA_SERVER', self.camera_server)


        ### GPS config
        if self.config.get('GPS_ENABLE') and self.indiclient.gps_device:
            gps_config = {
                'PROPERTIES' : {
                    'GPS_REFRESH_PERIOD' : {
                        'PERIOD' : 293,  # prime number
                    },
                },
            }

            self.indiclient.configureGpsDevice(gps_config)
            self.indiclient.refreshGps()


            # GPSD simulation
            #sim_gps_config = {
            #    'SWITCHES' : {
            #        'SIMULATION' : {
            #            'on'  : ['ENABLE'],
            #            'off' : ['DISABLE'],
            #        },
            #    },
            #    'PROPERTIES' : {
            #        'SIM_GEOGRAPHIC_COORD' : {  # rio
            #            'SIM_LAT'  : -22,  # requires integers
            #            'SIM_LONG' : 317,
            #            'SIM_ELEV' : 7,
            #        },
            #    },
            #}

            #self.indiclient.configureGpsDevice(sim_gps_config)



        ### Telescope config
        # park the telescope at zenith and stop tracking
        if self.indiclient.telescope_device:
            telescope_config = {
                'SWITCHES' : {
                    'TELESCOPE_TRACK_STATE' : {
                        'on'  : ['TRACK_OFF'],
                        'off' : ['TRACK_ON'],
                    },
                },
                'PROPERTIES' : {
                    'GEOGRAPHIC_COORD' : {
                        'LAT' : self.position_av[0],
                        'LONG' : self.position_av[1],
                    },
                },
            }

            self.indiclient.configureTelescopeDevice(telescope_config)

            self.reparkTelescope()


        if self.config.get('GPS_ENABLE'):
            if self.indiclient.telescope_device and self.indiclient.gps_device:
                # Set Telescope GPS
                self.indiclient.setTelescopeGps(self.indiclient.gps_device.getDeviceName())


        # configuration needs to be performed before getting CCD_INFO
        self.indiclient.configureCcdDevice(self.indi_config)  # night config by default


        # Get Properties
        #ccd_properties = self.indiclient.getCcdDeviceProperties()


        # get CCD information
        ccd_info = self.indiclient.getCcdInfo()


        if self.config.get('CFA_PATTERN'):
            cfa_pattern = self.config['CFA_PATTERN']
        else:
            cfa_pattern = ccd_info['CCD_CFA']['CFA_TYPE'].get('text')


        # populate S3 data
        s3_data = {
            'host'      : self.config['S3UPLOAD'].get('HOST', ''),
            'bucket'    : self.config['S3UPLOAD'].get('BUCKET', ''),
            'region'    : self.config['S3UPLOAD'].get('REGION', ''),
            'namespace' : self.config['S3UPLOAD'].get('NAMESPACE', ''),
        }


        try:
            s3_prefix = self.config['S3UPLOAD']['URL_TEMPLATE'].format(**s3_data)
        except KeyError as e:
            app.logger.error('Failure to generate S3 prefix: %s', str(e))
            s3_prefix = ''
        except ValueError as e:
            app.logger.error('Failure to generate S3 prefix: %s', str(e))
            s3_prefix = ''


        now = datetime.now()

        # need to get camera info before adding to DB
        camera_metadata = {
            'type'        : constants.CAMERA,
            'name'        : self.camera_name,
            'driver'      : self.camera_server,

            'hidden'      : False,  # unhide camera

            'minExposure' : float(ccd_info.get('CCD_EXPOSURE', {}).get('CCD_EXPOSURE_VALUE', {}).get('min')),
            'maxExposure' : float(ccd_info.get('CCD_EXPOSURE', {}).get('CCD_EXPOSURE_VALUE', {}).get('max')),
            'minGain'     : int(ccd_info.get('GAIN_INFO', {}).get('min')),
            'maxGain'     : int(ccd_info.get('GAIN_INFO', {}).get('max')),
            'width'       : int(ccd_info.get('CCD_FRAME', {}).get('WIDTH', {}).get('max')),
            'height'      : int(ccd_info.get('CCD_FRAME', {}).get('HEIGHT', {}).get('max')),
            'bits'        : int(ccd_info.get('CCD_INFO', {}).get('CCD_BITSPERPIXEL', {}).get('current')),
            'pixelSize'   : float(ccd_info.get('CCD_INFO', {}).get('CCD_PIXEL_SIZE', {}).get('current')),
            'cfa'         : constants.CFA_STR_MAP[cfa_pattern],

            'location'    : self.config['LOCATION_NAME'],
            'latitude'    : self.position_av[0],
            'longitude'   : self.position_av[1],
            'elevation'   : int(self.position_av[2]),

            'tz'          : str(now.astimezone().tzinfo),
            'utc_offset'  : now.astimezone().utcoffset().total_seconds(),

            'owner'           : self.config['OWNER'],
            'lensName'        : self.config['LENS_NAME'],
            'lensFocalLength' : self.config['LENS_FOCAL_LENGTH'],
            'lensFocalRatio'  : self.config['LENS_FOCAL_RATIO'],
            'lensImageCircle' : self.config['LENS_IMAGE_CIRCLE'],
            'alt'             : self.config['LENS_ALTITUDE'],
            'az'              : self.config['LENS_AZIMUTH'],
            'nightSunAlt'     : self.config['NIGHT_SUN_ALT_DEG'],

            'daytime_capture'       : self.config.get('DAYTIME_CAPTURE', True),
            'daytime_capture_save'  : self.config.get('DAYTIME_CAPTURE_SAVE', True),
            'daytime_timelapse'     : self.config.get('DAYTIME_TIMELAPSE', True),
            'capture_pause'         : self.config.get('CAPTURE_PAUSE', False),

            's3_prefix'             : s3_prefix,
            'web_nonlocal_images'   : self.config.get('WEB_NONLOCAL_IMAGES', False),
            'web_local_images_admin': self.config.get('WEB_LOCAL_IMAGES_ADMIN', False),

            'data'                  : {},
        }


        self.update_sensor_slot_labels()


        for k, v in self.SENSOR_SLOTS:
            camera_metadata['data'][k] = v


        camera_metadata['data']['custom_chart_1_key'] = self.config.get('CHARTS', {}).get('CUSTOM_SLOT_1', 'sensor_user_10')
        camera_metadata['data']['custom_chart_2_key'] = self.config.get('CHARTS', {}).get('CUSTOM_SLOT_2', 'sensor_user_11')
        camera_metadata['data']['custom_chart_3_key'] = self.config.get('CHARTS', {}).get('CUSTOM_SLOT_3', 'sensor_user_12')
        camera_metadata['data']['custom_chart_4_key'] = self.config.get('CHARTS', {}).get('CUSTOM_SLOT_4', 'sensor_user_13')
        camera_metadata['data']['custom_chart_5_key'] = self.config.get('CHARTS', {}).get('CUSTOM_SLOT_5', 'sensor_user_14')
        camera_metadata['data']['custom_chart_6_key'] = self.config.get('CHARTS', {}).get('CUSTOM_SLOT_6', 'sensor_user_15')
        camera_metadata['data']['custom_chart_7_key'] = self.config.get('CHARTS', {}).get('CUSTOM_SLOT_7', 'sensor_user_16')
        camera_metadata['data']['custom_chart_8_key'] = self.config.get('CHARTS', {}).get('CUSTOM_SLOT_8', 'sensor_user_17')
        camera_metadata['data']['custom_chart_9_key'] = self.config.get('CHARTS', {}).get('CUSTOM_SLOT_9', 'sensor_user_18')



        try:
            camera = self._miscDb.addCamera(camera_metadata)
        except MultipleResultsFound:
            logger.error('!!! MULTIPLE CAMERAS WITH SAME NAME (%s) !!!', camera_metadata['name'])

            self._miscDb.setState('STATUS', constants.STATUS_CAMERAERROR)

            self._miscDb.addNotification(
                NotificationCategory.CAMERA,
                'camera_name',
                'Multiple cameras defined with same name ({0:s})'.format(camera_metadata['name']),
                expire=timedelta(hours=2),
            )

            time.sleep(60)
            raise



        self.camera_id = camera.id
        self.indiclient.camera_id = camera.id

        self._miscDb.setState('DB_CAMERA_ID', camera.id)


        self._sync_camera(camera, camera_metadata)


        try:
            # Disable debugging
            self.indiclient.disableDebugCcd()
        except TimeOutException:
            logger.warning('Camera does not support debug')


        # set BLOB mode to BLOB_ALSO
        self.indiclient.updateCcdBlobMode()


        try:
            self.indiclient.setCcdFrameType('FRAME_LIGHT')  # default frame type is light
        except TimeOutException:
            # this is an optional step
            # occasionally the CCD_FRAME_TYPE property is not available during initialization
            logger.warning('Unable to set CCD_FRAME_TYPE to Light')


        try:
            self.indiclient.setCcdScopeInfo(camera.lensFocalLength, camera.lensFocalRatio)
        except TimeOutException:
            logger.warning('Unable to set SCOPE_INFO')


        # save config to defaults (disabled)
        #self.indiclient.saveCcdConfig()


        # set minimum exposure
        ccd_min_exp = float(ccd_info['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['min'])

        # Some CCD drivers will not accept their stated minimum exposure.
        # There might be some python -> C floating point conversion problem causing this.
        ccd_min_exp += 0.00000001


        if not self.config.get('CCD_EXPOSURE_MIN_DAY'):
            with self.exposure_av.get_lock():
                self.exposure_av[2] = ccd_min_exp
        elif self.config.get('CCD_EXPOSURE_MIN_DAY') > ccd_min_exp:
            with self.exposure_av.get_lock():
                self.exposure_av[2] = float(self.config.get('CCD_EXPOSURE_MIN_DAY'))
        elif self.config.get('CCD_EXPOSURE_MIN_DAY') < ccd_min_exp:
            logger.warning(
                'Minimum exposure (day) %0.8f too low, increasing to %0.8f',
                self.config.get('CCD_EXPOSURE_MIN_DAY'),
                ccd_min_exp,
            )
            with self.exposure_av.get_lock():
                self.exposure_av[2] = ccd_min_exp

        logger.info('Minimum CCD exposure: %0.8f (day)', self.exposure_av[2])


        if not self.config.get('CCD_EXPOSURE_MIN'):
            with self.exposure_av.get_lock():
                self.exposure_av[1] = ccd_min_exp
        elif self.config.get('CCD_EXPOSURE_MIN') > ccd_min_exp:
            with self.exposure_av.get_lock():
                self.exposure_av[1] = float(self.config.get('CCD_EXPOSURE_MIN'))
        elif self.config.get('CCD_EXPOSURE_MIN') < ccd_min_exp:
            logger.warning(
                'Minimum exposure (night) %0.8f too low, increasing to %0.8f',
                self.config.get('CCD_EXPOSURE_MIN'),
                ccd_min_exp,
            )
            with self.exposure_av.get_lock():
                self.exposure_av[1] = ccd_min_exp

        logger.info('Minimum CCD exposure: %0.8f (night)', self.exposure_av[1])


        # set maximum exposure
        ccd_max_exp = float(ccd_info['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['max'])
        maximum_exposure = self.config.get('CCD_EXPOSURE_MAX')

        if self.config.get('CCD_EXPOSURE_MAX') > ccd_max_exp:
            logger.warning(
                'Maximum exposure %0.8f too high, decreasing to %0.8f',
                self.config.get('CCD_EXPOSURE_MAX'),
                ccd_max_exp,
            )

            maximum_exposure = ccd_max_exp


        with self.exposure_av.get_lock():
            self.exposure_av[3] = maximum_exposure


        logger.info('Maximum CCD exposure: %0.8f', self.exposure_av[3])


        # set default exposure
        if self.config.get('CCD_EXPOSURE_DEF'):
            ccd_exposure_default = self.config['CCD_EXPOSURE_DEF']
        else:
            # use last exposure value within 10 minutes
            now_minus_10min = datetime.now() - timedelta(minutes=10)

            last_image = IndiAllSkyDbImageTable.query\
                .join(IndiAllSkyDbImageTable.camera)\
                .filter(IndiAllSkyDbCameraTable.id == self.camera_id)\
                .filter(IndiAllSkyDbImageTable.createDate > now_minus_10min)\
                .order_by(IndiAllSkyDbImageTable.createDate.desc())\
                .first()


            if last_image:
                ccd_exposure_default = float(last_image.exposure)
                logger.warning('Reusing last stable exposure: %0.6f', ccd_exposure_default)
            else:
                #ccd_exposure_default = self.exposure_av[1]
                ccd_exposure_default = 0.01  # this should give better results for many cameras


        # sanity check
        if ccd_exposure_default > maximum_exposure:
            ccd_exposure_default = maximum_exposure
        if ccd_exposure_default < ccd_min_exp:
            ccd_exposure_default = ccd_min_exp


        if self.exposure_av[0] == -1.0:
            # only set this on first start
            with self.exposure_av.get_lock():
                self.exposure_av[0] = ccd_exposure_default


        logger.info('Default CCD exposure: {0:0.8f}'.format(ccd_exposure_default))


        # Validate gain settings
        ccd_min_gain = ccd_info['GAIN_INFO']['min']
        ccd_max_gain = ccd_info['GAIN_INFO']['max']

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


    def _sync_camera(self, camera, camera_metadata):
        ### sync camera
        if not self.config.get('SYNCAPI', {}).get('ENABLE'):
            return


        camera_metadata['uuid'] = camera.uuid

        # tell worker to upload file
        jobdata = {
            'action'      : constants.TRANSFER_SYNC_V1,
            'model'       : camera.__class__.__name__,
            'id'          : camera.id,
            'metadata'    : camera_metadata,
        }

        upload_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(upload_task)
        db.session.commit()

        self.upload_q.put({'task_id' : upload_task.id})


    def _pre_run_tasks(self):
        # Tasks that need to be run before the main program loop

        # Update status
        self._miscDb.setState('STATUS', constants.STATUS_RUNNING)

        if self.camera_server in ['indi_rpicam']:
            # Raspberry PI HQ Camera requires an initial throw away exposure of over 6s
            # in order to take exposures longer than 7s
            logger.info('Taking throw away exposure for rpicam')
            self.shoot(7.0, sync=True, timeout=20.0)


    def _periodic_tasks(self):
        # Tasks that need to be run periodically
        now = time.time()

        if self.periodic_tasks_time > now:
            return

        # set next reconfigure time
        self.periodic_tasks_time = now + self.periodic_tasks_offset

        logger.warning('Periodic tasks triggered')


        # Update watchdog
        self._miscDb.setState('WATCHDOG', int(now))


        if self.camera_server in ['indi_asi_ccd']:
            # There is a bug in the ASI120M* camera that causes exposures to fail on gain changes
            # The indi_asi_ccd server will switch the camera to 8-bit mode to try to correct
            if self.camera_name.startswith('ZWO CCD ASI120'):
                self.indiclient.configureCcdDevice(self.indi_config)
        elif self.camera_server in ['indi_asi_single_ccd']:
            if self.camera_name.startswith('ZWO ASI120'):
                self.indiclient.configureCcdDevice(self.indi_config)


    def getCcdTemperature(self):
        temp_c = self.indiclient.getCcdTemperature()


        # query external temperature if defined
        if self.config.get('CCD_TEMP_SCRIPT'):
            try:
                ext_temp_c = self.getExternalTemperature(self.config.get('CCD_TEMP_SCRIPT'))
                temp_c = ext_temp_c
            except TemperatureException as e:
                logger.error('Exception querying external temperature: %s', str(e))


        temp_c_float = float(temp_c)


        with self.sensors_temp_av.get_lock():
            self.sensors_temp_av[0] = temp_c_float

        with self.sensors_user_av.get_lock():
            if self.config.get('TEMP_DISPLAY') == 'f':
                self.sensors_user_av[0] = (temp_c_float * 9.0 / 5.0) + 32
            elif self.config.get('TEMP_DISPLAY') == 'k':
                self.sensors_user_av[0] = temp_c_float + 273.15
            else:
                self.sensors_user_av[0] = temp_c_float


        return temp_c_float


    def getExternalTemperature(self, script_path):
        temp_script_p = Path(script_path)

        logger.info('Running external script for temperature: %s', temp_script_p)

        # need to be extra careful running in the main thread
        if not temp_script_p.exists():
            raise TemperatureException('Temperature script does not exist')

        if not temp_script_p.is_file():
            raise TemperatureException('Temperature script is not a file')

        if temp_script_p.stat().st_size == 0:
            raise TemperatureException('Temperature script is empty')

        if not os.access(str(temp_script_p), os.X_OK):
            raise TemperatureException('Temperature script is not executable')


        # generate a tempfile for the data
        f_tmp_tempjson = tempfile.NamedTemporaryFile(mode='w', delete=True, suffix='.json')
        f_tmp_tempjson.close()

        tempjson_name_p = Path(f_tmp_tempjson.name)


        cmd = [
            str(temp_script_p),
        ]


        # the file used for the json data is communicated via environment variable
        cmd_env = {
            'TEMP_JSON' : str(tempjson_name_p),
        }


        try:
            temp_process = subprocess.Popen(
                cmd,
                env=cmd_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            raise TemperatureException('Temperature script failed to execute')


        try:
            temp_process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            temp_process.kill()
            time.sleep(1.0)
            temp_process.poll()  # close out process
            raise TemperatureException('Temperature script timed out')


        if temp_process.returncode != 0:
            raise TemperatureException('Temperature script returned exited abnormally')


        try:
            with io.open(str(tempjson_name_p), 'r') as tempjson_name_f:
                temp_data = json.load(tempjson_name_f)

            tempjson_name_p.unlink()  # remove temp file
        except PermissionError as e:
            logger.error(str(e))
            raise TemperatureException(str(e))
        except json.JSONDecodeError as e:
            logger.error('Error decoding json: %s', str(e))
            raise TemperatureException(str(e))
        except FileNotFoundError as e:
            raise TemperatureException(str(e))


        try:
            temp_float = float(temp_data['temp'])
        except ValueError:
            raise TemperatureException('Temperature script returned a non-numerical value')
        except KeyError:
            raise TemperatureException('Temperature script returned incorrect data')


        return temp_float


    def getGpsPosition(self):
        if not self.config.get('GPS_ENABLE'):
            return

        if not self.indiclient.gps_device:
            return

        update_position = False

        gps_lat, gps_long, gps_elev = self.indiclient.getGpsPosition()

        if gps_long > 180.0:
            # put longitude in range of -180 to 180
            gps_long = gps_long - 360.0


        # need 1/10 degree difference before updating location
        if abs(gps_lat - self.position_av[0]) > 0.1:
            self.updateConfigLocation(gps_lat, gps_long, gps_elev)
            update_position = True
        elif abs(gps_long - self.position_av[1]) > 0.1:
            self.updateConfigLocation(gps_lat, gps_long, gps_elev)
            update_position = True
        elif abs(gps_elev - self.position_av[2]) > 30:
            self.updateConfigLocation(gps_lat, gps_long, gps_elev)
            update_position = True


        if update_position:
            # Update shared values
            with self.position_av.get_lock():
                self.position_av[0] = float(gps_lat)
                self.position_av[1] = float(gps_long)
                self.position_av[2] = float(gps_elev)


            self.reparkTelescope()


            # update transition time
            self.next_forced_transition_time = self._dateCalcs.getNextDayNightTransition().timestamp()
            logger.warning(
                'Next forced transition time: %s (%0.1fh)',
                datetime.fromtimestamp(self.next_forced_transition_time).strftime('%Y-%m-%d %H:%M:%S'),
                (self.next_forced_transition_time - time.time()) / 3600,
            )


        return gps_lat, gps_long, gps_elev


    def getTelescopeRaDec(self):
        if not self.indiclient.telescope_device:
            return

        ra, dec = self.indiclient.getTelescopeRaDec()

        # Update shared values
        with self.position_av.get_lock():
            self.position_av[3] = ra
            self.position_av[4] = dec


        return ra, dec


    def updateConfigLocation(self, gps_lat, gps_long, gps_elev):
        logger.warning('Queuing config update with new geographic location')

        self.config['LOCATION_LATITUDE'] = round(float(gps_lat), 3)
        self.config['LOCATION_LONGITUDE'] = round(float(gps_long), 3)
        self.config['LOCATION_ELEVATION'] = int(gps_elev)


        task_setlocation = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.MAIN,
            state=TaskQueueState.MANUAL,
            priority=100,
            data={
                'action'      : 'setlocation',
                'camera_id'   : self.camera_id,
                'latitude'    : float(gps_lat),
                'longitude'   : float(gps_long),
                'elevation'   : int(gps_elev),
            },
        )

        db.session.add(task_setlocation)
        db.session.commit()


    def reparkTelescope(self):
        if not self.indiclient.telescope_device:
            return

        self.indiclient.unparkTelescope()
        self.indiclient.setTelescopeParkPosition(0.0, self.position_av[0])
        self.indiclient.parkTelescope()


    def reconfigureCcd(self):
        if not self.reconfigure_camera:
            return

        self.reconfigure_camera = False


        if self.night:
            self.indi_config = self.config['INDI_CONFIG_DEFAULTS']

            # cooling
            if self.config.get('CCD_COOLING'):
                ccd_temp = self.config.get('CCD_TEMP', 15.0)
                self.indiclient.enableCcdCooler()
                self.indiclient.setCcdTemperature(ccd_temp)


            if self.moonmode:
                logger.warning('Change to night (moon mode)')
                self.indiclient.setCcdGain(self.config['CCD_CONFIG']['MOONMODE']['GAIN'])
                self.indiclient.setCcdBinning(self.config['CCD_CONFIG']['MOONMODE']['BINNING'])
            else:
                logger.warning('Change to night (normal mode)')
                self.indiclient.setCcdGain(self.config['CCD_CONFIG']['NIGHT']['GAIN'])
                self.indiclient.setCcdBinning(self.config['CCD_CONFIG']['NIGHT']['BINNING'])


            if self.config['CAMERA_INTERFACE'].startswith('libcamera'):
                libcamera_image_type = self.config.get('LIBCAMERA', {}).get('IMAGE_FILE_TYPE', 'jpg')
                if libcamera_image_type == 'dng':
                    self.indiclient.libcamera_bit_depth = 16
                else:
                    self.indiclient.libcamera_bit_depth = 8
        else:
            logger.warning('Change to day')

            if self.config.get('INDI_CONFIG_DAY', {}):
                self.indi_config = self.config['INDI_CONFIG_DAY']
            else:
                self.indi_config = self.config['INDI_CONFIG_DEFAULTS']

            self.indiclient.disableCcdCooler()
            self.indiclient.setCcdGain(self.config['CCD_CONFIG']['DAY']['GAIN'])
            self.indiclient.setCcdBinning(self.config['CCD_CONFIG']['DAY']['BINNING'])


            if self.config['CAMERA_INTERFACE'].startswith('libcamera'):
                libcamera_image_type = self.config.get('LIBCAMERA', {}).get('IMAGE_FILE_TYPE_DAY', 'jpg')
                if libcamera_image_type == 'dng':
                    self.indiclient.libcamera_bit_depth = 16
                else:
                    self.indiclient.libcamera_bit_depth = 8


        # update CCD config
        self.indiclient.configureCcdDevice(self.indi_config)


        ### Update shared values
        # These need to be updated in the capture process to indicate the real state of the camera
        with self.night_v.get_lock():
            self.night_v.value = int(self.night)

        with self.moonmode_v.get_lock():
            self.moonmode_v.value = int(self.moonmode)


    def detectNight(self):
        obs = ephem.Observer()
        obs.lon = math.radians(self.position_av[1])
        obs.lat = math.radians(self.position_av[0])
        obs.elevation = self.position_av[2]

        # disable atmospheric refraction calcs
        obs.pressure = 0

        obs.date = datetime.now(tz=timezone.utc)  # ephem expects UTC dates

        sun = ephem.Sun()
        moon = ephem.Moon()

        sun.compute(obs)
        moon.compute(obs)

        # Night
        self.night = sun.alt < self.night_sun_radians  # boolean

        # Moonmode
        moon_phase = moon.moon_phase * 100.0

        logger.info('Sun alt: %0.1f, Moon alt: %0.1f, phase %0.1f%%', math.degrees(sun.alt), math.degrees(moon.alt), moon_phase)

        if self.night:
            if moon.alt >= self.night_moonmode_radians:
                if moon_phase >= self.config['NIGHT_MOONMODE_PHASE']:
                    #logger.info('Moon Mode conditions detected')
                    self.moonmode = True
                    return

        self.moonmode = False


    def _generateDayTimelapse(self, timespec, camera_id, task_state=TaskQueueState.QUEUED):
        if not self.config.get('TIMELAPSE_ENABLE', True):
            logger.warning('Timelapse creation disabled')
            return

        if not self.config.get('DAYTIME_TIMELAPSE', True):
            logger.warning('Daytime Timelapse creation disabled')
            return


        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        logger.warning('Generating day time timelapse for %s camera %d', timespec, camera.id)

        video_jobdata = {
            'action' : 'generateVideo',
            'kwargs' : {
                'timespec'    : timespec,
                'night'       : False,
                'camera_id'   : camera.id,
            }
        }

        video_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=task_state,
            data=video_jobdata,
        )
        db.session.add(video_task)
        db.session.commit()

        self.video_q.put({'task_id' : video_task.id})


        if self.config.get('FISH2PANO', {}).get('ENABLE'):
            panorama_video_jobdata = {
                'action'      : 'generatePanoramaVideo',
                'kwargs' : {
                    'timespec'    : timespec,
                    'night'       : False,
                    'camera_id'   : camera.id,
                },
            }

            panorama_video_task = IndiAllSkyDbTaskQueueTable(
                queue=TaskQueueQueue.VIDEO,
                state=task_state,
                data=panorama_video_jobdata,
            )
            db.session.add(panorama_video_task)
            db.session.commit()

            self.video_q.put({'task_id' : panorama_video_task.id})


    def _generateNightTimelapse(self, timespec, camera_id, task_state=TaskQueueState.QUEUED):
        if not self.config.get('TIMELAPSE_ENABLE', True):
            logger.warning('Timelapse creation disabled')
            return


        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        logger.warning('Generating night time timelapse for %s camera %d', timespec, camera.id)

        video_jobdata = {
            'action'      : 'generateVideo',
            'kwargs' : {
                'timespec'    : timespec,
                'night'       : True,
                'camera_id'   : camera.id,
            },
        }

        video_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=task_state,
            data=video_jobdata,
        )
        db.session.add(video_task)
        db.session.commit()

        self.video_q.put({'task_id' : video_task.id})


        if self.config.get('FISH2PANO', {}).get('ENABLE'):
            panorama_video_jobdata = {
                'action'      : 'generatePanoramaVideo',
                'kwargs' : {
                    'timespec'    : timespec,
                    'night'       : True,
                    'camera_id'   : camera.id,
                },
            }

            panorama_video_task = IndiAllSkyDbTaskQueueTable(
                queue=TaskQueueQueue.VIDEO,
                state=task_state,
                data=panorama_video_jobdata,
            )
            db.session.add(panorama_video_task)
            db.session.commit()

            self.video_q.put({'task_id' : panorama_video_task.id})


    def _generateNightKeogram(self, timespec, camera_id, task_state=TaskQueueState.QUEUED):
        if not self.config.get('TIMELAPSE_ENABLE', True):
            logger.warning('Timelapse creation disabled')
            return


        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        logger.warning('Generating night time keogram for %s camera %d', timespec, camera.id)

        jobdata = {
            'action' : 'generateKeogramStarTrails',
            'kwargs' : {
                'timespec'    : timespec,
                'night'       : True,
                'camera_id'   : camera.id,
            },
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=task_state,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.video_q.put({'task_id' : task.id})


    def _generateDayKeogram(self, timespec, camera_id, task_state=TaskQueueState.QUEUED):
        if not self.config.get('TIMELAPSE_ENABLE', True):
            logger.warning('Timelapse creation disabled')
            return

        if not self.config.get('DAYTIME_TIMELAPSE', True):
            logger.warning('Daytime Timelapse creation disabled')
            return


        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        logger.warning('Generating day time keogram for %s camera %d', timespec, camera.id)

        jobdata = {
            'action'      : 'generateKeogramStarTrails',
            'kwargs' : {
                'timespec'    : timespec,
                'night'       : False,
                'camera_id'   : camera.id,
            },
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=task_state,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.video_q.put({'task_id' : task.id})


    def shoot(self, exposure, sync=True, timeout=None):
        logger.info('Taking %0.8f s exposure (gain %d)', exposure, self.gain_v.value)

        self.indiclient.setCcdExposure(exposure, sync=sync, timeout=timeout)


    def setTimeSystemd(self, new_datetime_utc):
        logger.warning('Setting system time to %s (UTC)', new_datetime_utc)

        epoch = new_datetime_utc.timestamp() + 5  # add 5 due to sleep below
        epoch_msec = epoch * 1000000

        system_bus = dbus.SystemBus()
        timedate1 = system_bus.get_object('org.freedesktop.timedate1', '/org/freedesktop/timedate1')
        manager = dbus.Interface(timedate1, 'org.freedesktop.timedate1')

        logger.warning('Disabling NTP time sync')
        manager.SetNTP(False, False)  # disable time sync
        time.sleep(5.0)  # give enough time for time sync to diable

        r2 = manager.SetTime(epoch_msec, False, False)

        return r2


    def _uploadAllskyEndOfNight(self, camera_id, task_state=TaskQueueState.QUEUED):
        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        # This will delete old images from the filesystem and DB
        jobdata = {
            'action' : 'uploadAllskyEndOfNight',
            'kwargs' : {
                'night'        : True,
                'camera_id'    : camera.id,
            },
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=task_state,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.video_q.put({'task_id' : task.id})


    def _expireData(self, camera_id, task_state=TaskQueueState.QUEUED):

        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        # This will delete old images from the filesystem and DB
        jobdata = {
            'action' : 'expireData',
            'kwargs' : {
                'camera_id' : camera.id,
            }
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=task_state,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.video_q.put({'task_id' : task.id})


    def update_sensor_slot_labels(self):
        import psutil
        from .devices import sensors as indi_allsky_sensors

        temp_sensor__a_classname = self.config.get('TEMP_SENSOR', {}).get('A_CLASSNAME', '')
        temp_sensor__a_label = self.config.get('TEMP_SENSOR', {}).get('A_LABEL', 'Sensor A')
        temp_sensor__a_user_var_slot = self.config.get('TEMP_SENSOR', {}).get('A_USER_VAR_SLOT', 'sensor_user_10')
        temp_sensor__b_classname = self.config.get('TEMP_SENSOR', {}).get('B_CLASSNAME', '')
        temp_sensor__b_label = self.config.get('TEMP_SENSOR', {}).get('B_LABEL', 'Sensor B')
        temp_sensor__b_user_var_slot = self.config.get('TEMP_SENSOR', {}).get('B_USER_VAR_SLOT', 'sensor_user_15')
        temp_sensor__c_classname = self.config.get('TEMP_SENSOR', {}).get('C_CLASSNAME', '')
        temp_sensor__c_label = self.config.get('TEMP_SENSOR', {}).get('C_LABEL', 'Sensor C')
        temp_sensor__c_user_var_slot = self.config.get('TEMP_SENSOR', {}).get('C_USER_VAR_SLOT', 'sensor_user_20')


        if temp_sensor__a_classname:
            try:
                temp_sensor__a_class = getattr(indi_allsky_sensors, temp_sensor__a_classname)
                sensor_a_index = constants.SENSOR_INDEX_MAP[str(temp_sensor__a_user_var_slot)]

                for x in range(temp_sensor__a_class.METADATA['count']):
                    try:
                        self.SENSOR_SLOTS[sensor_a_index + x][1] = '{0:s} - {1:s} - {2:s}'.format(
                            temp_sensor__a_class.METADATA['name'],
                            temp_sensor__a_label,
                            temp_sensor__a_class.METADATA['labels'][x],
                        )
                    except IndexError:
                        logger.error('Not enough slots for sensor values')
                        pass
            except AttributeError:
                logger.error('Unknown sensor class: %s', temp_sensor__a_classname)


        if temp_sensor__b_classname:
            try:
                temp_sensor__b_class = getattr(indi_allsky_sensors, temp_sensor__b_classname)
                sensor_b_index = constants.SENSOR_INDEX_MAP[str(temp_sensor__b_user_var_slot)]

                for x in range(temp_sensor__b_class.METADATA['count']):
                    try:
                        self.SENSOR_SLOTS[sensor_b_index + x][1] = '{0:s} - {1:s} - {2:s}'.format(
                            temp_sensor__b_class.METADATA['name'],
                            temp_sensor__b_label,
                            temp_sensor__b_class.METADATA['labels'][x],
                        )
                    except IndexError:
                        logger.error('Not enough slots for sensor values')
                        pass
            except AttributeError:
                logger.error('Unknown sensor class: %s', temp_sensor__b_classname)


        if temp_sensor__c_classname:
            try:
                temp_sensor__c_class = getattr(indi_allsky_sensors, temp_sensor__c_classname)
                sensor_c_index = constants.SENSOR_INDEX_MAP[str(temp_sensor__c_user_var_slot)]

                for x in range(temp_sensor__c_class.METADATA['count']):
                    try:
                        self.SENSOR_SLOTS[sensor_c_index + x][1] = '{0:s} - {1:s} - {2:s}'.format(
                            temp_sensor__c_class.METADATA['name'],
                            temp_sensor__c_label,
                            temp_sensor__c_class.METADATA['labels'][x],
                        )
                    except IndexError:
                        logger.error('Not enough slots for sensor values')
                        pass
            except AttributeError:
                logger.error('Unknown sensor class: %s', temp_sensor__c_classname)


        # Set system temp names
        temp_info = psutil.sensors_temperatures()

        temp_label_list = list()
        for t_key in sorted(temp_info):  # always return the keys in the same order
            for i, t in enumerate(temp_info[t_key]):
                # these names will match the mqtt topics
                if not t.label:
                    # use index for label name
                    label = str(i)
                else:
                    label = t.label

                topic = '{0:s}/{1:s}'.format(t_key, label)
                temp_label_list.append(topic)


        for x, label in enumerate(temp_label_list[:20]):  # limit to 20
            self.SENSOR_SLOTS[x + 40][1] = '{0:s}'.format(label)

