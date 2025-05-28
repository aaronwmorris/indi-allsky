#!/usr/bin/env python3

import sys
import signal
import logging
import time
from collections import OrderedDict
import ctypes
import PyIndi


CCD_EXPOSURES = [15 for x in range(6000)]
#CCD_EXPOSURES = [
#    15.0,
#    14.0,
#    14.0,
#    10.0,
#     9.0,
#     7.0,
#     6.0,
#     5.0,
#     3.0,
#     1.0,
#]


### rpicam
CCD_GAIN = [1]
#CCD_GAIN = [
#    10,
#    10,
#    10,
#    25,
#    25,
#    25,
#    50,
#    50,
#    50,
#    100,
#    100,
#    100
#]  # loop through these exposures forever

CCD_BINMODE = 1

### sv305
#CCD_GAIN = [250]
#CCD_BINMODE = 1

INDI_CONFIG = OrderedDict({
    "SWITCHES" : {},
    "PROPERTIES" : {},
    "TEXT" : {},
})



### Debugging
#INDI_CONFIG = OrderedDict({
#    "PROPERTIES" : {},
#    "SWITCHES" : {
#        "DEBUG" : {
#            "on"  : ["ENABLE"],
#            "off" : ["DISABLE"],
#        },
#        "DEBUG_LEVEL" : {
#            "on"  : ["DBG_ERROR", "DBG_WARNING", "DBG_SESSION", "DBG_DEBUG"],
#            "off" : ["DBG_EXTRA_1"],
#        },
#        "LOGGING_LEVEL" : {
#            "on"  : ["LOG_ERROR", "LOG_WARNING", "LOG_SESSION", "LOG_DEBUG"],
#            "off" : ["LOG_EXTRA_1"],
#        },
#        "LOG_OUTPUT" : {
#            "on"  : ["CLIENT_DEBUG", "FILE_DEBUG"],
#            "off" : [],
#        },
#    }
#})

### simulator
#CCD_GAIN = [100]
#CCD_BINMODE = 1

#INDI_CONFIG = OrderedDict({
#    "PROPERTIES" : {
#        "EQUATORIAL_PE" : {
#            "RA_PE"  : 16.7175,
#            "DEC_PE" : 36.4233
#        },
#    },
#    "SWITCHES" : {}
#})


### webcam
#INDI_CONFIG = OrderedDict({
#    "PROPERTIES" : {},
#    "TEXT" : {
#        "ONLINE_PATH": {
#            "URL_PATH": "http://10.11.12.13/cgi-bin/api.cgi?cmd=Snap&channel=0&rs=abcdefg123456789&user=username&password=password"
#        }
#    },
#    "SWITCHES" : {
#        "CAPTURE_DEVICE": {
#            "on": ["IP Camera"]
#        },
#        "ONLINE_PROTOCOL": {
#            "on": ["HTTP"],
#            "off": ["CUSTOM"],
#        },
#    }
#})

### not working
#            "#URL_PATH": "rtsp://username:password@10.11.12.13:554/h264Preview_01_main"
#            "#URL_PATH": "rtmp://10.11.12.13:1935/bcs/channel0_main.bcs?channel=0&stream=0&user=username&password=password"


logger = logging.getLogger(__name__)
logger.setLevel(level=logging.INFO)

LOG_FORMATTER_STREAM = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s %(funcName)s() [%(lineno)d]: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)
logger.addHandler(LOG_HANDLER_STREAM)


class IndiClient(PyIndi.BaseClient):

    __state_to_str = {
        PyIndi.IPS_IDLE  : 'IDLE',
        PyIndi.IPS_OK    : 'OK',
        PyIndi.IPS_BUSY  : 'BUSY',
        PyIndi.IPS_ALERT : 'ALERT',
    }

    __indi_interfaces = {
        PyIndi.BaseDevice.GENERAL_INTERFACE   : 'general',
        PyIndi.BaseDevice.TELESCOPE_INTERFACE : 'telescope',
        PyIndi.BaseDevice.CCD_INTERFACE       : 'ccd',
        PyIndi.BaseDevice.GUIDER_INTERFACE    : 'guider',
        PyIndi.BaseDevice.FOCUSER_INTERFACE   : 'focuser',
        PyIndi.BaseDevice.FILTER_INTERFACE    : 'filter',
        PyIndi.BaseDevice.DOME_INTERFACE      : 'dome',
        PyIndi.BaseDevice.GPS_INTERFACE       : 'gps',
        PyIndi.BaseDevice.WEATHER_INTERFACE   : 'weather',
        PyIndi.BaseDevice.AO_INTERFACE        : 'ao',
        PyIndi.BaseDevice.DUSTCAP_INTERFACE   : 'dustcap',
        PyIndi.BaseDevice.LIGHTBOX_INTERFACE  : 'lightbox',
        PyIndi.BaseDevice.DETECTOR_INTERFACE  : 'detector',
        PyIndi.BaseDevice.ROTATOR_INTERFACE   : 'rotator',
        PyIndi.BaseDevice.AUX_INTERFACE       : 'aux',
    }


    def __init__(self):
        super(IndiClient, self).__init__()
        self._timeout = 60.0
        logger.info('creating an instance of IndiClient')


    def newDevice(self, d):
        logger.info("new device %s", d.getDeviceName())

    def removeDevice(self, d):
        logger.info("remove device %s", d.getDeviceName())

    def newProperty(self, p):
        #logger.info("new property %s for device %s", p.getName(), p.getDeviceName())
        pass

    def removeProperty(self, p):
        logger.info("remove property %s for device %s", p.getName(), p.getDeviceName())


    def updateProperty(self, p):
        # INDI 2.x.x code path

        if hasattr(PyIndi.BaseMediator, 'newNumber'):
            # indi 1.9.9 has a bug that will run both the new an old code paths for properties
            return

        if p.getType() == PyIndi.INDI_BLOB:
            p_blob = PyIndi.PropertyBlob(p)
            logger.info("new Blob %s for %s", p_blob.getName(), p_blob.getDeviceName())
            self.processBlob(p_blob[0])
        elif p.getType() == PyIndi.INDI_NUMBER:
            #p_number = PyIndi.PropertyNumber(p)
            #logger.info("new Number %s for %s", p_number.getName(), p_number.getDeviceName())
            pass
        elif p.getType() == PyIndi.INDI_SWITCH:
            p_switch = PyIndi.PropertySwitch(p)
            logger.info("new Switch %s for %s", p_switch.getName(), p_switch.getDeviceName())
        elif p.getType() == PyIndi.INDI_TEXT:
            p_text = PyIndi.PropertyText(p)
            logger.info("new Text %s for %s", p_text.getName(), p_text.getDeviceName())
        elif p.getType() == PyIndi.INDI_LIGHT:
            p_light = PyIndi.PropertyLight(p)
            logger.info("new Light %s for %s", p_light.getName(), p_light.getDeviceName())
        else:
            logger.warning('Property type not matched: %d', p.getType())


    def newBLOB(self, bp):
        # legacy INDI 1.x.x code path
        logger.info("new BLOB %s", bp.name)
        self.processBlob(bp)


    def newSwitch(self, svp):
        # legacy INDI 1.x.x code path
        logger.info("new Switch %s for device %s", svp.name, svp.device)

    def newNumber(self, nvp):
        # legacy INDI 1.x.x code path
        #logger.info("new Number %s for device %s", nvp.name, nvp.device)
        pass

    def newText(self, tvp):
        # legacy INDI 1.x.x code path
        logger.info("new Text %s for device %s", tvp.name, tvp.device)

    def newLight(self, lvp):
        # legacy INDI 1.x.x code path
        logger.info("new Light %s for device %s", lvp.name, lvp.device)


    def processBlob(self, blob):
        #start = time.time()

        ### get image data
        blob.getblobdata()

        #elapsed_s = time.time() - start
        #logger.info('Blob downloaded in %0.4f s', elapsed_s)


    def newMessage(self, d, m):
        logger.info("new Message %s", d.messageQueue(m))

    def serverConnected(self):
        logger.info("Server connected (%s:%d)", self.getHost(), self.getPort())

    def serverDisconnected(self, code):
        logger.info("Server disconnected (exit code = %d, %s, %d", code, str(self.getHost()), self.getPort())


    def findDeviceInterfaces(self, device):
        interface = device.getDriverInterface()
        if type(interface) is int:
            device_interfaces = interface
        else:
            interface.acquire()
            device_interfaces = int(ctypes.cast(interface.__int__(), ctypes.POINTER(ctypes.c_uint16)).contents.value)
            interface.disown()

        return device_interfaces



    def findCcds(self):
        ccd_list = list()

        for device in self.getDevices():
            logger.info('Found device %s', device.getDeviceName())
            device_interfaces = self.findDeviceInterfaces(device)

            for k, v in self.__indi_interfaces.items():
                if device_interfaces & k:
                    logger.info(' Detected %s', v)
                    if k == PyIndi.BaseDevice.CCD_INTERFACE:
                        ccd_list.append(device)

        return ccd_list


    def configureDevice(self, device, indi_config):
        ### Configure Device Switches
        for k, v in indi_config.get('SWITCHES', {}).items():
            logger.info('Setting switch %s', k)
            self.set_switch(device, k, on_switches=v.get('on', []), off_switches=v.get('off', []))

        ### Configure Device Properties
        for k, v in indi_config.get('PROPERTIES', {}).items():
            logger.info('Setting property (number) %s', k)
            self.set_number(device, k, v)

        ### Configure Device Text
        for k, v in indi_config.get('TEXT', {}).items():
            logger.info('Setting property (text) %s', k)
            self.set_text(device, k, v)


        # Sleep after configuration
        time.sleep(1.0)


    def setCcdGain(self, ccdDevice, gain_value):
        logger.warning('Setting CCD gain to %s', str(gain_value))
        indi_exec = ccdDevice.getDriverExec()

        if indi_exec in [
            'indi_asi_ccd',
            'indi_asi_single_ccd',
            'indi_toupcam_ccd',
            'indi_altair_ccd',
            'indi_playerone_ccd',
        ]:
            gain_config = {
                "PROPERTIES" : {
                    "CCD_CONTROLS" : {
                        "Gain" : gain_value,
                    },
                },
            }
        elif indi_exec in [
            'indi_qhy_ccd',
            'indi_simulator_ccd',
            'indi_rpicam',
            'indi_libcamera_ccd',
            'indi_dsi_ccd',
        ]:
            gain_config = {
                "PROPERTIES" : {
                    "CCD_GAIN" : {
                        "GAIN" : gain_value,
                    },
                },
            }
        elif indi_exec in [
            'indi_svbony_ccd',
            'indi_sv305_ccd',  # legacy name
        ]:
            # the GAIN property changed in INDI 2.0.4
            try:
                self.get_control(ccdDevice, 'CCD_CONTROLS', 'number', timeout=2.0)

                gain_config = {
                    "PROPERTIES" : {
                        "CCD_CONTROLS" : {
                            "Gain" : gain_value,
                        },
                    },
                }
            except TimeOutException:
                # use the old property
                gain_config = {
                    "PROPERTIES" : {
                        "CCD_GAIN" : {
                            "GAIN" : gain_value,
                        },
                    },
                }
        elif indi_exec in [
            'indi_gphoto_ccd',
            'indi_canon_ccd',
            'indi_nikon_ccd',
            'indi_pentax_ccd',
            'indi_sony_ccd',
        ]:
            logger.info('Mapping gain to ISO for libgphoto device')

            try:
                gain_switch = self.__canon_gain_to_iso[gain_value]
                logger.info('Setting ISO switch: %s', gain_switch)
            except KeyError:
                logger.error('Canon ISO not found for %s, using ISO 100', str(gain_value))
                gain_switch = 'ISO1'

            gain_config = {
                'SWITCHES' : {
                    'CCD_ISO' : {
                        'on' : [gain_switch],
                    },
                },
            }
        elif indi_exec in ['indi_sx_ccd']:
            logger.warning('indi_sx_ccd does not support gain settings')
            gain_config = {}
        elif indi_exec in ['indi_webcam_ccd']:
            logger.warning('indi_webcam_ccd does not support gain settings')
            gain_config = {}
        elif indi_exec in ['indi_v4l2_ccd']:
            logger.warning('indi_v4l2_ccd does not support gain settings')
            gain_config = {}
        elif 'indi_pylibcamera' in indi_exec:  # SPECIAL CASE
            # the exec name can have many variations
            gain_config = {
                "PROPERTIES" : {
                    "CCD_GAIN" : {
                        "GAIN" : gain_value,
                    },
                },
            }
        else:
            raise Exception('Gain config not implemented for {0:s}, open an enhancement request'.format(indi_exec))


        self.configureDevice(ccdDevice, gain_config)


    def setCcdBinning(self, ccdDevice, bin_value):
        if type(bin_value) is int:
            new_bin_value = [bin_value, bin_value]
        elif type(bin_value) is str:
            new_bin_value = [int(bin_value), int(bin_value)]
        elif not bin_value:
            # Assume default
            return

        logger.warning('Setting CCD binning to (%d, %d)', new_bin_value[0], new_bin_value[1])

        indi_exec = ccdDevice.getDriverExec()

        if indi_exec in [
            'indi_gphoto_ccd',
            'indi_canon_ccd',
            'indi_nikon_ccd',
            'indi_pentax_ccd',
            'indi_sony_ccd',
        ]:
            logger.warning('indi_gphoto_ccd does not support bin settings')
            return
        elif indi_exec in ['indi_webcam_ccd']:
            logger.warning('indi_webcam_ccd does not support bin settings')
            return


        try:
            self.get_control(ccdDevice, 'CCD_BINNING', 'number', timeout=2.0)

            binning_config = {
                "PROPERTIES" : {
                    "CCD_BINNING" : {
                        "HOR_BIN" : new_bin_value[0],
                        "VER_BIN" : new_bin_value[1],
                    },
                },
            }

            self.configureDevice(ccdDevice, binning_config)

        except TimeOutException:
            logger.error('Failed to find CCD binning control, bypassing binning config')


    def saveConfig(self, ccd_device):
        save_config = {
            "SWITCHES" : {
                "CONFIG_PROCESS" : {
                    "on"  : ['CONFIG_SAVE'],
                }
            }
        }

        self.configureDevice(ccd_device, save_config)


    def setFrameType(self, ccd_device, frame_type):
        frame_config = {
            "SWITCHES" : {
                "CCD_FRAME_TYPE" : {
                    "on"  : [frame_type],
                }
            }
        }

        self.configureDevice(ccd_device, frame_config)


    def setCcdExposure(self, ccdDevice, exposure, sync=False, timeout=None):
        if not timeout:
            timeout = self._timeout

        self._exposure = exposure

        ctl = self.set_number(ccdDevice, 'CCD_EXPOSURE', {'CCD_EXPOSURE_VALUE': exposure}, sync=sync, timeout=timeout)

        return ctl


    def set_number(self, device, name, values, sync=True, timeout=None):
        #logger.info('Name: %s, values: %s', name, str(values))
        c = self.get_control(device, name, 'number')
        for control_name, index in self.__map_indexes(c, values.keys()).items():
            c[index].setValue(values[control_name])

        self.sendNewNumber(c)

        if sync:
            self.__wait_for_ctl_statuses(c, timeout=timeout)

        return c


    def set_switch(self, device, name, on_switches=[], off_switches=[], sync=True, timeout=None):
        c = self.get_control(device, name, 'switch')

        is_exclusive = c.getRule() == PyIndi.ISR_ATMOST1 or c.getRule() == PyIndi.ISR_1OFMANY
        if is_exclusive :
            on_switches = on_switches[0:1]
            off_switches = [s.getName() for s in c if s.getName() not in on_switches]

        for index in range(0, len(c)):
            current_state = c[index].getState()
            new_state = current_state

            if c[index].getName() in on_switches:
                new_state = PyIndi.ISS_ON
            elif is_exclusive or c[index].getName() in off_switches:
                new_state = PyIndi.ISS_OFF

            c[index].setState(new_state)

        self.sendNewSwitch(c)

        return c


    def set_text(self, device, control_name, values, sync=True, timeout=None):
        c = self.get_control(device, control_name, 'text')
        for control_name, index in self.__map_indexes(c, values.keys()).items():
            c[index].setText(values[control_name])
        self.sendNewText(c)

        if sync:
            self.__wait_for_ctl_statuses(c, timeout=timeout)

        return c


    def get_control(self, device, name, ctl_type, timeout=None):
        if timeout is None:
            timeout = self._timeout

        ctl = None
        attr = {
            'number'  : 'getNumber',
            'switch'  : 'getSwitch',
            'text'    : 'getText',
            'light'   : 'getLight',
            'blob'    : 'getBLOB'
        }[ctl_type]

        started = time.time()
        while not ctl:
            ctl = getattr(device, attr)(name)

            if not ctl and 0 < timeout < time.time() - started:
                raise TimeOutException('Timeout finding control {0}'.format(name))

            time.sleep(0.1)

        return ctl


    def ctl_ready(self, ctl, statuses=[PyIndi.IPS_OK, PyIndi.IPS_IDLE]):
        if not ctl:
            return True, 'unset'

        state = ctl.getState()

        ready = state in statuses
        state_str = self.__state_to_str.get(state, 'UNKNOWN')

        return ready, state_str


    def __map_indexes(self, ctl, values):
        result = {}
        for i, c in enumerate(ctl):
            #logger.info('Value name: %s', c.getName())  # useful to find value names
            if c.getName() in values:
                result[c.getName()] = i
        return result


    def __wait_for_ctl_statuses(self, ctl, statuses=[PyIndi.IPS_OK, PyIndi.IPS_IDLE], timeout=None):
        started = time.time()
        if timeout is None:
            timeout = self._timeout

        while ctl.getState() not in statuses:
            #logger.info('%s/%s/%s: %s', ctl.getDeviceName(), ctl.getGroupName(), ctl.getName(), self.__state_to_str[ctl.getState()])
            if ctl.getState() == PyIndi.IPS_ALERT and 0.5 > time.time() - started:
                raise RuntimeError('Error while changing property {0}'.format(ctl.getName()))

            elapsed = time.time() - started

            if 0 < timeout < elapsed:
                raise TimeOutException('Timeout error while changing property {0}: elapsed={1}, timeout={2}, status={3}'.format(ctl.getName(), elapsed, timeout, self.__state_to_str[ctl.getState()] ))

            time.sleep(0.05)




class IndiExposureTest(object):
    def __init__(self):
        self._indi_server = 'localhost'
        self._indi_port = 7624

        self.indiclient = None

        self.current_gain = None
        self._gain_index = 0

        self._shutdown = False

        signal.signal(signal.SIGINT, self.sigint_handler_main)


    def sigint_handler_main(self, signum, frame):
        logger.warning('Caught INT signal, shutting down')

        # set flag for program to stop processes
        self._shutdown = True


    def shoot(self, ccdDevice, exposure, sync=True, timeout=None):
        logger.info('Taking %0.8f s exposure (gain %d)', exposure, self.current_gain)
        ctl = self.indiclient.setCcdExposure(ccdDevice, exposure, sync=sync, timeout=timeout)

        return ctl


    def _pre_run_tasks(self, ccdDevice):
        # Tasks that need to be run before the main program loop

        indi_exec = ccdDevice.getDriverExec()

        if indi_exec in ['indi_rpicam']:
            # Raspberry PI HQ Camera requires an initial throw away exposure of over 6s
            # in order to take exposures longer than 7s
            logger.info('Taking throw away exposure for rpicam')
            self.shoot(ccdDevice, 7.0, sync=True)


    def run(self):
        # instantiate the client
        self.indiclient = IndiClient()

        # set indi server localhost and port
        self.indiclient.setServer(self._indi_server, self._indi_port)

        logger.info("Connecting to indiserver")
        if not self.indiclient.connectServer():
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
        self.ccd_device = ccdDevice

        logger.warning('Connecting to device %s', ccdDevice.getDeviceName())
        self.indiclient.connectDevice(ccdDevice.getDeviceName())


        logger.info('Set BLOB mode')
        self.indiclient.setBLOBMode(1, ccdDevice.getDeviceName(), None)

        self.indiclient.configureDevice(ccdDevice, INDI_CONFIG)

        self.indiclient.setFrameType(ccdDevice, 'FRAME_LIGHT')  # default frame type is light

        #self.indiclient.saveConfig(ccdDevice)

        self.indiclient.setCcdGain(ccdDevice, CCD_GAIN[0])
        self.current_gain = CCD_GAIN[0]

        self.indiclient.setCcdBinning(ccdDevice, CCD_BINMODE)

        self._pre_run_tasks(ccdDevice)

        next_frame_time = time.time()  # start immediately
        frame_start_time = time.time()
        waiting_for_frame = False
        exposure_ctl = None  # populated later

        camera_ready_time = time.time()
        camera_ready = False
        last_camera_ready = False
        exposure_state = 'unset'

        exposure = 0  # populated later
        last_exposure = 0


        ### main loop starts
        while True:
            loop_start_time = time.time()

            ### Blocking mode ###

            #try:
            #    self.shoot(ccdDevce, exposure, sync=True)
            #except TimeOutException as e:
            #    logger.error('Timeout: %s', str(e))
            #    time.sleep(5.0)
            #    continue


            #full_elapsed_s = time.time() - loop_start_time
            #logger.info('Exposure finished in ######## %0.4f s ########', full_elapsed_s)

            ### sleep for the remaining eposure period
            #remaining_s = exposure - full_elapsed_s
            #if remaining_s > 0:
            #    logger.info('Sleeping for additional %0.4f s', remaining_s)
            #    time.sleep(remaining_s)

            #try:
            #    exposure = CCD_EXPOSURES.pop(0)
            #except IndexError:
            #    logger.info('End of exposures')
            #    sys.exit(0)
            ### End Blocking mode ###


            ### Non-blocking mode ###

            logger.info('Camera last ready: %0.1fs', loop_start_time - camera_ready_time)
            logger.info('Exposure state: %s', exposure_state)


            # Loop to run for 7 seconds (prime number)
            loop_end = time.time() + 7

            while True:
                time.sleep(0.05)

                now = time.time()
                if now >= loop_end:
                    break

                last_camera_ready = camera_ready
                camera_ready, exposure_state = self.indiclient.ctl_ready(exposure_ctl)

                if camera_ready and not last_camera_ready:
                    camera_ready_time = now


                if camera_ready and waiting_for_frame:
                    frame_elapsed = now - frame_start_time

                    waiting_for_frame = False

                    logger.warning('Exposure received in ######## %0.4f s (%0.4f) ########', frame_elapsed, frame_elapsed - last_exposure)


                    if self._shutdown:
                        sys.exit(0)


                if camera_ready and now >= next_frame_time:
                    total_elapsed = now - frame_start_time

                    frame_start_time = now

                    last_exposure = exposure

                    try:
                        exposure = CCD_EXPOSURES.pop(0)
                    except IndexError:
                        logger.info('End of exposures')
                        sys.exit(0)


                    new_gain = self.getNextGain()
                    if new_gain != self.current_gain:
                        self.indiclient.setCcdGain(ccdDevice, new_gain)
                        self.current_gain = new_gain


                    exposure_ctl = self.shoot(ccdDevice, exposure, sync=False)
                    waiting_for_frame = True

                    next_frame_time = frame_start_time + exposure

                    logger.info('Total time since last exposure %0.4f s', total_elapsed)


            ### End Non-blocking mode ###


    def getNextGain(self):
        if type(CCD_GAIN) is int:
            return CCD_GAIN
        elif type(CCD_GAIN) in (list, tuple):

            try:
                gain = CCD_GAIN[self._gain_index]
            except IndexError:
                self._gain_index = 0
                gain = CCD_GAIN[self._gain_index]

            self._gain_index += 1

            return gain

        else:
            raise Exception('Unknown gain variable type')


class TimeOutException(Exception):
    pass


if __name__ == "__main__":
    IndiExposureTest().run()
