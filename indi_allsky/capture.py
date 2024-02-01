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

from .config import IndiAllSkyConfig

from .flask.models import TaskQueueQueue
from .flask.models import TaskQueueState

from .flask.models import IndiAllSkyDbCameraTable
from .flask.models import IndiAllSkyDbImageTable
from .flask.models import NotificationCategory
from .flask.models import IndiAllSkyDbTaskQueueTable

from .exceptions import CameraException
from .exceptions import TimeOutException
from .exceptions import TemperatureException

from .flask import create_app
from .flask import db
from .flask.miscDb import miscDb


app = create_app()

logger = logging.getLogger('indi_allsky')


class CaptureWorker(Process):

    periodic_tasks_offset = 180.0  # 3 minutes


    def __init__(
        self,
        idx,
        config,
        error_q,
        capture_q,
        image_q,
        video_q,
        upload_q,
        latitude_v,
        longitude_v,
        elevation_v,
        ra_v,
        dec_v,
        exposure_v,
        exposure_min_v,
        exposure_max_v,
        gain_v,
        bin_v,
        sensortemp_v,
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

        self.latitude_v = latitude_v
        self.longitude_v = longitude_v
        self.elevation_v = elevation_v

        self.ra_v = ra_v
        self.dec_v = dec_v

        self.exposure_v = exposure_v
        self.exposure_min_v = exposure_min_v
        self.exposure_max_v = exposure_max_v
        self.gain_v = gain_v
        self.bin_v = bin_v
        self.sensortemp_v = sensortemp_v
        self.night_v = night_v
        self.moonmode_v = moonmode_v

        self._miscDb = miscDb(self.config)

        self.indiclient = None

        self.night = None
        self.moonmode = None

        self.camera_id = None
        self.camera_name = None
        self.camera_server = None

        self.focus_mode = self.config.get('FOCUS_MODE', False)  # focus mode takes images as fast as possible

        self.night_sun_radians = math.radians(self.config['NIGHT_SUN_ALT_DEG'])
        self.night_moonmode_radians = math.radians(self.config['NIGHT_MOONMODE_ALT_DEG'])

        self.update_time_offset = None  # when time needs to be updated, this will be the offset

        self.periodic_tasks_time = time.time() + self.periodic_tasks_offset
        #self.periodic_tasks_time = time.time()  # testing


        if self.config['IMAGE_FOLDER']:
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()


        self.generate_timelapse_flag = False   # This is updated once images have been generated

        self._reload = False
        self._shutdown = False



    def sighup_handler_worker(self, signum, frame):
        logger.warning('Caught HUP signal, reconfiguring')

        # set flag for program to restart processes
        self._reload = True


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
        last_camera_ready = False
        exposure_state = 'unset'
        check_exposure_state = time.time() + 300  # check in 5 minutes


        ### main loop starts
        while True:
            loop_start_time = time.time()


            logger.info('Camera last ready: %0.1fs', loop_start_time - camera_ready_time)
            logger.info('Exposure state: %s', exposure_state)


            try:
                c_dict = self.capture_q.get(False)

                if c_dict.get('stop'):
                    self._shutdown = True
                elif c_dict.get('reload'):
                    self._reload = True
                elif c_dict.get('settime'):
                    self.update_time_offset = int(c_dict['settime'])
                else:
                    logger.error('Unknown action: %s', str(c_dict))

            except queue.Empty:
                pass


            self.detectNight()
            self.detectMoonMode()


            with app.app_context():
                ### Change between day and night
                if self.night_v.value != int(self.night):
                    if not self.night and self.generate_timelapse_flag:
                        ### Generate timelapse at end of night
                        yesterday_ref = datetime.now() - timedelta(days=1)
                        timespec = yesterday_ref.strftime('%Y%m%d')
                        self._generateNightTimelapse(timespec, self.camera_id)
                        self._generateNightKeogram(timespec, self.camera_id)
                        self._uploadAllskyEndOfNight(self.camera_id)

                    elif self.night and self.generate_timelapse_flag:
                        ### Generate timelapse at end of day
                        today_ref = datetime.now()
                        timespec = today_ref.strftime('%Y%m%d')
                        self._generateDayTimelapse(timespec, self.camera_id)
                        self._generateDayKeogram(timespec, self.camera_id)
                        self._expireData(self.camera_id)  # cleanup old images and folders


                # this is to prevent expiring images at startup
                if self.night:
                    # always indicate timelapse generation at night
                    self.generate_timelapse_flag = True  # indicate images have been generated for timelapse
                elif self.config['DAYTIME_CAPTURE'] and self.config['DAYTIME_TIMELAPSE']:
                    # must be day time
                    self.generate_timelapse_flag = True  # indicate images have been generated for timelapse


                self.getSensorTemperature()
                self.getTelescopeRaDec()
                self.getGpsPosition()


                if not self.night and not self.config['DAYTIME_CAPTURE']:
                    logger.info('Daytime capture is disabled')
                    self.generate_timelapse_flag = False

                    if self._shutdown:
                        logger.warning('Shutting down')
                        self.indiclient.disableCcdCooler()  # safety

                        self.indiclient.disconnectServer()

                        logger.warning('Goodbye')
                        return


                    time.sleep(59)  # prime number
                    continue


                # check exposure state every 5 minutes
                if check_exposure_state < loop_start_time:
                    check_exposure_state = time.time() + 300  # next check in 5 minutes

                    camera_last_ready_s = int(loop_start_time - camera_ready_time)
                    if camera_last_ready_s > 300:
                        self._miscDb.addNotification(
                            NotificationCategory.CAMERA,
                            'last_ready',
                            'Camera last ready {0:d}s ago.  Camera might be hung.'.format(camera_last_ready_s),
                            expire=timedelta(minutes=60),
                        )


                # Loop to run for 11 seconds (prime number)
                loop_end = time.time() + 11

                while True:
                    time.sleep(0.05)

                    now = time.time()
                    if now >= loop_end:
                        break

                    last_camera_ready = camera_ready
                    camera_ready, exposure_state = self.indiclient.getCcdExposureStatus()

                    if not camera_ready:
                        continue

                    ###########################################
                    # Camera is ready, not taking an exposure #
                    ###########################################
                    if not last_camera_ready:
                        camera_ready_time = now


                    if waiting_for_frame:
                        frame_elapsed = now - frame_start_time
                        frame_delta = frame_elapsed - self.exposure_v.value

                        waiting_for_frame = False

                        logger.info('Exposure received in %0.4f s (%0.4f)', frame_elapsed, frame_delta)


                        if frame_delta < -1:
                            logger.error('%0.4fs EXPOSURE RECEIVED IN %0.4fs.  POSSIBLE CAMERA PROBLEM.', self.exposure_v.value, frame_elapsed)
                            self._miscDb.addNotification(
                                NotificationCategory.CAMERA,
                                'exposure_delta',
                                '{0:0.1f}s exposure received in {1:0.1f}s.  Possible camera problem.'.format(self.exposure_v.value, frame_elapsed),
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


                    # restart here to ensure camera is not taking images
                    if self._reload:
                        self._reload = False
                        self.reload_handler()


                    # reconfigure if needed
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

                        self.shoot(self.exposure_v.value, sync=False)
                        camera_ready = False
                        waiting_for_frame = True

                        if self.focus_mode:
                            # Start frame immediately in focus mode
                            logger.warning('*** FOCUS MODE ENABLED ***')
                            next_frame_time = now + self.config.get('FOCUS_DELAY', 4.0)
                        elif self.night:
                            next_frame_time = frame_start_time + self.config['EXPOSURE_PERIOD']
                        else:
                            next_frame_time = frame_start_time + self.config['EXPOSURE_PERIOD_DAY']

                        logger.info('Total time since last exposure %0.4f s', total_elapsed)


                loop_elapsed = now - loop_start_time
                logger.debug('Loop completed in %0.4f s', loop_elapsed)




    def _initialize(self):
        camera_interface = getattr(camera_module, self.config.get('CAMERA_INTERFACE', 'indi'))

        # instantiate the client
        self.indiclient = camera_interface(
            self.config,
            self.image_q,
            self.latitude_v,
            self.longitude_v,
            self.elevation_v,
            self.ra_v,
            self.dec_v,
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

            self._miscDb.addNotification(
                NotificationCategory.GENERAL,
                'no_indiserver',
                'Unable to connect to indiserver at {0:s}:{1:d}'.format(host, port),
                expire=timedelta(hours=2),
            )

            return

        # give devices a chance to register
        time.sleep(8)

        try:
            self.indiclient.findCcd(camera_name=self.config.get('INDI_CAMERA_NAME'))
        except CameraException as e:
            logger.error('Camera error: %s', str(e))

            self._miscDb.addNotification(
                NotificationCategory.CAMERA,
                'no_camera',
                'Camera was not detected.',
                expire=timedelta(hours=2),
            )

            return


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
                    'TELESCOPE_SLEW_RATE' : {
                        'on' : ['4x'],  # zoom zoom
                    },
                    'TELESCOPE_TRACK_STATE' : {
                        'on'  : ['TRACK_OFF'],
                        'off' : ['TRACK_ON'],
                    },
                },
                'PROPERTIES' : {
                    'GEOGRAPHIC_COORD' : {
                        'LAT' : self.latitude_v.value,
                        'LONG' : self.longitude_v.value,
                    },
                    'TELESCOPE_INFO' : {
                        'TELESCOPE_APERTURE' : 10,
                        'TELESCOPE_FOCAL_LENGTH' : 10,
                    },
                },
                'TEXT' : {
                    'SCOPE_CONFIG_NAME' : {
                        'SCOPE_CONFIG_NAME' : 'indi-allsky',
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
        # which queries the exposure control
        self.indiclient.configureCcdDevice(self.config['INDI_CONFIG_DEFAULTS'])


        # Get Properties
        #ccd_properties = self.indiclient.getCcdDeviceProperties()


        # get CCD information
        ccd_info = self.indiclient.getCcdInfo()


        if self.config.get('CFA_PATTERN'):
            cfa_pattern = self.config['CFA_PATTERN']
        else:
            cfa_pattern = ccd_info['CCD_CFA']['CFA_TYPE'].get('text')


        # need to get camera info before adding to DB
        camera_metadata = {
            'type'        : constants.CAMERA,
            'name'        : self.camera_name,
            'driver'      : self.camera_server,

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
            'latitude'    : self.latitude_v.value,
            'longitude'   : self.longitude_v.value,
            'elevation'   : self.elevation_v.value,

            'owner'           : self.config['OWNER'],
            'lensName'        : self.config['LENS_NAME'],
            'lensFocalLength' : self.config['LENS_FOCAL_LENGTH'],
            'lensFocalRatio'  : self.config['LENS_FOCAL_RATIO'],
            'lensImageCircle' : self.config['LENS_IMAGE_CIRCLE'],
            'alt'             : self.config['LENS_ALTITUDE'],
            'az'              : self.config['LENS_AZIMUTH'],
            'nightSunAlt'     : self.config['NIGHT_SUN_ALT_DEG'],
        }

        camera = self._miscDb.addCamera(camera_metadata)
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


        # save config to defaults (disabled)
        #self.indiclient.saveCcdConfig()


        # set minimum exposure
        ccd_min_exp = float(ccd_info['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['min'])

        # Some CCD drivers will not accept their stated minimum exposure.
        # There might be some python -> C floating point conversion problem causing this.
        ccd_min_exp = ccd_min_exp + 0.00000001

        if not self.config.get('CCD_EXPOSURE_MIN'):
            with self.exposure_min_v.get_lock():
                self.exposure_min_v.value = ccd_min_exp
        elif self.config.get('CCD_EXPOSURE_MIN') < ccd_min_exp:
            logger.warning(
                'Minimum exposure %0.8f too low, increasing to %0.8f',
                self.config.get('CCD_EXPOSURE_MIN'),
                ccd_min_exp,
            )
            with self.exposure_min_v.get_lock():
                self.exposure_min_v.value = ccd_min_exp

        logger.info('Minimum CCD exposure: %0.8f', self.exposure_min_v.value)


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


        with self.exposure_max_v.get_lock():
            self.exposure_max_v.value = maximum_exposure


        logger.info('Maximum CCD exposure: %0.8f', self.exposure_max_v.value)


        # set default exposure
        #
        # Note:  I have tried setting a default exposure of 1.0s which works fine for night time, but
        #        during the day weird things can happen when the image sensor is completely oversaturated.
        #        Instead of an all white image, you can get intermediate pixel values which confuses the
        #        exposure detection algorithm
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
                #ccd_exposure_default = self.exposure_min_v.value
                ccd_exposure_default = 0.001  # this should give better results for many cameras


        # sanity check
        if ccd_exposure_default > maximum_exposure:
            ccd_exposure_default = maximum_exposure
        if ccd_exposure_default < ccd_min_exp:
            ccd_exposure_default = ccd_min_exp


        if self.exposure_v.value == -1.0:
            # only set this on first start
            with self.exposure_v.get_lock():
                self.exposure_v.value = ccd_exposure_default


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


    def reload_handler(self):
        ### method is no longer used and will be removed later

        logger.warning('Reconfiguring...')

        self._config_obj = IndiAllSkyConfig()

        # overwrite config
        self.config = self._config_obj.config


        # send new config to camera object
        self.indiclient.updateConfig(self.config)


        # Update shared values
        self.night_sun_radians = math.radians(self.config['NIGHT_SUN_ALT_DEG'])
        self.night_moonmode_radians = math.radians(self.config['NIGHT_MOONMODE_ALT_DEG'])


        # reconfigure if needed
        self.reconfigureCcd()

        # add driver name to config
        self.camera_name = self.indiclient.ccd_device.getDeviceName()
        self._miscDb.setState('CAMERA_NAME', self.camera_name)

        self.camera_server = self.indiclient.ccd_device.getDriverExec()
        self._miscDb.setState('CAMERA_SERVER', self.camera_server)


        ### Telescope config
        # park the telescope at zenith
        if self.indiclient.telescope_device:
            telescope_config = {
                'SWITCHES' : {},
                'PROPERTIES' : {
                    'GEOGRAPHIC_COORD' : {
                        'LAT' : self.latitude_v.value,
                        'LONG' : self.longitude_v.value,
                    },
                },
            }

            self.indiclient.configureTelescopeDevice(telescope_config)

            self.reparkTelescope()


        # configuration needs to be performed before getting CCD_INFO
        # which queries the exposure control
        self.indiclient.configureCcdDevice(self.config['INDI_CONFIG_DEFAULTS'])


        # Get Properties
        #ccd_properties = self.indiclient.getCcdDeviceProperties()


        # get CCD information
        ccd_info = self.indiclient.getCcdInfo()


        if self.config.get('CFA_PATTERN'):
            cfa_pattern = self.config['CFA_PATTERN']
        else:
            cfa_pattern = ccd_info['CCD_CFA']['CFA_TYPE'].get('text')


        # need to get camera info before adding to DB
        camera_metadata = {
            'type'        : constants.CAMERA,
            'name'        : self.camera_name,
            'driver'      : self.camera_server,

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
            'latitude'    : self.latitude_v.value,
            'longitude'   : self.longitude_v.value,
            'elevation'   : self.elevation_v.value,

            'owner'           : self.config['OWNER'],
            'lensName'        : self.config['LENS_NAME'],
            'lensFocalLength' : self.config['LENS_FOCAL_LENGTH'],
            'lensFocalRatio'  : self.config['LENS_FOCAL_RATIO'],
            'lensImageCircle' : self.config['LENS_IMAGE_CIRCLE'],
            'alt'             : self.config['LENS_ALTITUDE'],
            'az'              : self.config['LENS_AZIMUTH'],
            'nightSunAlt'     : self.config['NIGHT_SUN_ALT_DEG'],
        }

        camera = self._miscDb.addCamera(camera_metadata)
        self.camera_id = camera.id

        self.indiclient.camera_id = camera.id

        self._miscDb.setState('DB_CAMERA_ID', camera.id)


        self._sync_camera(camera, camera_metadata)


        # Update focus mode
        self.focus_mode = self.config.get('FOCUS_MODE', False)

        # set minimum exposure
        ccd_min_exp = ccd_info['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['min']

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


        # Validate gain settings
        ccd_min_gain = ccd_info['GAIN_INFO']['min']
        ccd_max_gain = ccd_info['GAIN_INFO']['max']

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
        now = time.time()


        # Update watchdog
        self._miscDb.setState('WATCHDOG', int(now))


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
                self.indiclient.configureCcdDevice(self.config['INDI_CONFIG_DEFAULTS'])
        elif self.camera_server in ['indi_asi_single_ccd']:
            if self.camera_name.startswith('ZWO ASI120'):
                self.indiclient.configureCcdDevice(self.config['INDI_CONFIG_DEFAULTS'])


    def getSensorTemperature(self):
        temp_val = self.indiclient.getCcdTemperature()


        # query external temperature if defined
        if self.config.get('CCD_TEMP_SCRIPT'):
            try:
                ext_temp_val = self.getExternalTemperature(self.config.get('CCD_TEMP_SCRIPT'))
                temp_val = ext_temp_val
            except TemperatureException as e:
                logger.error('Exception querying external temperature: %s', str(e))


        temp_val_f = float(temp_val)

        with self.sensortemp_v.get_lock():
            self.sensortemp_v.value = temp_val_f


        return temp_val_f


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
        if abs(gps_lat - self.latitude_v.value) > 0.1:
            self.updateConfigLocation(gps_lat, gps_long, gps_elev)
            update_position = True
        elif abs(gps_long - self.longitude_v.value) > 0.1:
            self.updateConfigLocation(gps_lat, gps_long, gps_elev)
            update_position = True
        elif abs(gps_elev - self.elevation_v.value) > 30:
            self.updateConfigLocation(gps_lat, gps_long, gps_elev)
            update_position = True


        if update_position:
            # Update shared values
            with self.latitude_v.get_lock():
                self.latitude_v.value = float(gps_lat)

            with self.longitude_v.get_lock():
                self.longitude_v.value = float(gps_long)

            with self.elevation_v.get_lock():
                self.elevation_v.value = int(gps_elev)


            self.reparkTelescope()


        return gps_lat, gps_long, gps_elev


    def getTelescopeRaDec(self):
        if not self.indiclient.telescope_device:
            return

        ra, dec = self.indiclient.getTelescopeRaDec()

        # Update shared values
        with self.ra_v.get_lock():
            self.ra_v.value = ra

        with self.dec_v.get_lock():
            self.dec_v.value = dec


        return ra, dec


    def updateConfigLocation(self, gps_lat, gps_long, gps_elev):
        logger.warning('Queuing config update with new geographic location')

        self.config['LOCATION_LATITUDE'] = round(float(gps_lat), 3)
        self.config['LOCATION_LONGITUDE'] = round(float(gps_long), 3)
        self.config['LOCATION_ELEVATION'] = int(gps_elev)


        task_setlocation = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.MAIN,
            state=TaskQueueState.MANUAL,
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
        self.indiclient.setTelescopeParkPosition(0.0, self.latitude_v.value)
        self.indiclient.parkTelescope()


    def reconfigureCcd(self):

        if self.night_v.value != int(self.night):
            pass
        elif self.night and bool(self.moonmode_v.value) != bool(self.moonmode):
            pass
        else:
            # No need to reconfigure
            return


        if self.night:
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
        else:
            logger.warning('Change to day')
            self.indiclient.disableCcdCooler()
            self.indiclient.setCcdGain(self.config['CCD_CONFIG']['DAY']['GAIN'])
            self.indiclient.setCcdBinning(self.config['CCD_CONFIG']['DAY']['BINNING'])



        # Update shared values
        with self.night_v.get_lock():
            self.night_v.value = int(self.night)

        with self.moonmode_v.get_lock():
            self.moonmode_v.value = int(self.moonmode)



    def detectNight(self):
        obs = ephem.Observer()
        obs.lon = math.radians(self.longitude_v.value)
        obs.lat = math.radians(self.latitude_v.value)
        obs.elevation = self.elevation_v.value
        obs.date = datetime.now(tz=timezone.utc)  # ephem expects UTC dates

        sun = ephem.Sun()
        sun.compute(obs)

        logger.info('Sun altitude: %s', sun.alt)

        self.night = sun.alt < self.night_sun_radians  # boolean


    def detectMoonMode(self):
        # detectNight() should be run first
        obs = ephem.Observer()
        obs.lon = math.radians(self.longitude_v.value)
        obs.lat = math.radians(self.latitude_v.value)
        obs.elevation = self.elevation_v.value
        obs.date = datetime.now(tz=timezone.utc)  # ephem expects UTC dates

        moon = ephem.Moon()
        moon.compute(obs)

        moon_phase = moon.moon_phase * 100.0

        logger.info('Moon altitude: %s, phase %0.1f%%', moon.alt, moon_phase)
        if self.night:
            if moon.alt >= self.night_moonmode_radians:
                if moon_phase >= self.config['NIGHT_MOONMODE_PHASE']:
                    logger.info('Moon Mode conditions detected')
                    self.moonmode = True
                    return

        self.moonmode = False


    def _generateDayTimelapse(self, timespec, camera_id, task_state=TaskQueueState.QUEUED):
        if not self.config.get('TIMELAPSE_ENABLE', True):
            logger.warning('Timelapse creation disabled')
            return


        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        img_day_folder = self.image_dir.joinpath('ccd_{0:s}'.format(camera.uuid), '{0:s}'.format(timespec), 'day')

        logger.warning('Generating day time timelapse for %s camera %d', timespec, camera.id)

        jobdata = {
            'action'      : 'generateVideo',
            'timespec'    : timespec,
            'img_folder'  : str(img_day_folder),
            'night'       : False,
            'camera_id'   : camera.id,
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=task_state,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.video_q.put({'task_id' : task.id})


    def _generateNightTimelapse(self, timespec, camera_id, task_state=TaskQueueState.QUEUED):
        if not self.config.get('TIMELAPSE_ENABLE', True):
            logger.warning('Timelapse creation disabled')
            return


        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        img_day_folder = self.image_dir.joinpath('ccd_{0:s}'.format(camera.uuid), '{0:s}'.format(timespec), 'night')

        logger.warning('Generating night time timelapse for %s camera %d', timespec, camera.id)

        jobdata = {
            'action'      : 'generateVideo',
            'timespec'    : timespec,
            'img_folder'  : str(img_day_folder),
            'night'       : True,
            'camera_id'   : camera.id,
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=task_state,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.video_q.put({'task_id' : task.id})


    def _generateNightKeogram(self, timespec, camera_id, task_state=TaskQueueState.QUEUED):
        if not self.config.get('TIMELAPSE_ENABLE', True):
            logger.warning('Timelapse creation disabled')
            return


        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        img_day_folder = self.image_dir.joinpath('ccd_{0:s}'.format(camera.uuid), '{0:s}'.format(timespec), 'night')

        logger.warning('Generating night time keogram for %s camera %d', timespec, camera.id)

        jobdata = {
            'action'      : 'generateKeogramStarTrails',
            'timespec'    : timespec,
            'img_folder'  : str(img_day_folder),
            'night'       : True,
            'camera_id'   : camera.id,
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


        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()


        img_day_folder = self.image_dir.joinpath('ccd_{0:s}'.format(camera.uuid), '{0:s}'.format(timespec), 'day')

        logger.warning('Generating day time keogram for %s camera %d', timespec, camera.id)

        jobdata = {
            'action'      : 'generateKeogramStarTrails',
            'timespec'    : timespec,
            'img_folder'  : str(img_day_folder),
            'night'       : False,
            'camera_id'   : camera.id,
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
            'action'       : 'uploadAllskyEndOfNight',
            'img_folder'   : str(self.image_dir),  # not needed
            'timespec'     : None,  # Not needed
            'night'        : True,
            'camera_id'    : camera.id,
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
            'action'       : 'expireData',
            'img_folder'   : str(self.image_dir),
            'timespec'     : None,  # Not needed
            'night'        : None,  # Not needed
            'camera_id'    : camera.id,
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=task_state,
            data=jobdata,
        )
        db.session.add(task)
        db.session.commit()

        self.video_q.put({'task_id' : task.id})


