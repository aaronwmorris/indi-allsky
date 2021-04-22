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

logger = multiprocessing.get_logger()



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

        with self.gain_v.get_lock():
            self.gain_v.value = gain

        logger.info('Gain set to %d', self.gain_v.value)

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

                if not nighttime and self.generate_timelapse_flag:
                    ### Generate timelapse at end of night
                    yesterday_ref = datetime.now() - timedelta(days=1)
                    timespec = yesterday_ref.strftime('%Y%m%d')
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

        video_file = img_day_folder.joinpath('allsky-{0:s}.mp4'.format(timespec))

        if video_file.exists():
            logger.warning('Video is already generated: %s', video_file)

            if restart_worker:
                self._startImageProcessWorker()

            return


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

        cmd = 'ffmpeg -y -f image2 -r {0:d} -i {1:s}/%04d.{2:s} -vcodec libx264 -b:v {3:s} -pix_fmt yuv420p -movflags +faststart {4:s}'.format(self.config['FFMPEG_FRAMERATE'], str(seqfolder), self.config['IMAGE_FILE_TYPE'], self.config['FFMPEG_BITRATE'], str(video_file)).split()
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
        logger.info('Taking %0.6f s exposure (gain %d)', exposure, self.gain_v.value)
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


