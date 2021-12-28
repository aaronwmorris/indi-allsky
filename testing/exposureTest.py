#!/usr/bin/env python3

import sys
import logging
import time
import ctypes
import PyIndi


CCD_EXPOSURE = 15.0

### rpicam
CCD_GAIN = 1
CCD_BINMODE = 1

INDI_CONFIG = {
    "PROPERTIES" : {},
    "SWITCHES" : {
        "DEBUG" : {
            "on"  : ["ENABLE"],
            "off" : ["DISABLE"],
        },
        "DEBUG_LEVEL" : {
            "on"  : ["DBG_ERROR", "DBG_WARNING", "DBG_SESSION", "DBG_DEBUG"],
            "off" : ["DBG_EXTRA_1"],
        },
        "LOGGING_LEVEL" : {
            "on"  : ["LOG_ERROR", "LOG_WARNING", "LOG_SESSION", "LOG_DEBUG"],
            "off" : ["LOG_EXTRA_1"],
        },
        "LOG_OUTPUT" : {
            "on"  : ["CLIENT_DEBUG", "FILE_DEBUG"],
            "off" : [],
        },
    }
}


### sv305
#CCD_GAIN = 250
#CCD_BINMODE = 1

#INDI_CONFIG = {
#    "PROPERTIES" : {},
#    "SWITCHES" : {
#        "FRAME_FORMAT" : {
#            "on"  : ["FORMAT_RAW8"],
#            "off" : ["FORMAT_RAW12"],
#        },
#    }
#}

### simulator
#CCD_GAIN = 100
#CCD_BINMODE = 1

#INDI_CONFIG = {
#    "PROPERTIES" : {
#        "EQUATORIAL_PE" : {
#            "RA_PE"  : 16.7175,
#            "DEC_PE" : 36.4233
#        },
#    },
#    "SWITCHES" : {}
#}



logger = logging.getLogger(__name__)
logger.setLevel(level=logging.INFO)

LOG_FORMATTER_STREAM = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s %(funcName)s() #%(lineno)d: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)
logger.addHandler(LOG_HANDLER_STREAM)


class IndiClient(PyIndi.BaseClient):

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

        self._exposureReceived = False


    @property
    def exposureReceived(self):
        return self._exposureReceived

    @exposureReceived.setter
    def exposureReceived(self, foobar):
        self._exposureReceived = False


    def newDevice(self, d):
        logger.info("new device %s", d.getDeviceName())

    def newProperty(self, p):
        #logger.info("new property %s for device %s", p.getName(), p.getDeviceName())
        pass

    def removeProperty(self, p):
        logger.info("remove property %s for device %s", p.getName(), p.getDeviceName())


    def newBLOB(self, bp):
        logger.info("new BLOB %s", bp.name)

        self._exposureReceived = True

        #start = time.time()

        ### get image data
        bp.getblobdata()

        #elapsed_s = time.time() - start
        #logger.info('Blob downloaded in %0.4f s', elapsed_s)


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
        ### Configure Device Properties
        for k, v in indi_config.get('PROPERTIES', {}).items():
            logger.info('Setting property %s', k)
            self.set_number(device, k, v)

        ### Configure Device Switches
        for k, v in indi_config.get('SWITCHES', {}).items():
            logger.info('Setting switch %s', k)
            self.set_switch(device, k, on_switches=v['on'], off_switches=v.get('off', []))

        ### Configure controls
        #self.set_controls(device, indi_config.get('CONTROLS', {}))

        # Sleep after configuration
        time.sleep(1.0)


    def setCcdGain(self, ccdDevice, gain_value):
        logger.warning('Setting CCD gain to %s', str(gain_value))
        indi_exec = ccdDevice.getDriverExec()

        if indi_exec in ['indi_asi_ccd', 'indi_asi_single_ccd', 'indi_toupcam_ccd']:
            gain_config = {
                "PROPERTIES" : {
                    "CCD_CONTROLS" : {
                        "Gain" : gain_value,
                    },
                },
            }
        elif indi_exec in ['indi_sv305_ccd', 'indi_qhy_ccd', 'indi_simulator_ccd', 'indi_rpicam']:
            gain_config = {
                "PROPERTIES" : {
                    "CCD_GAIN" : {
                        "GAIN" : gain_value,
                    },
                },
            }
        elif indi_exec in ['indi_canon_ccd']:
            logger.info('Mapping gain to ISO for Canon device')

            try:
                gain_switch = self.__canon_iso_switch[gain_value]
            except KeyError:
                logger.error('Canon ISO not found for %s, using auto', str(gain_value))
                gain_switch = 'ISO0'

            gain_config = {
                'SWITCHES' : {
                    'CCD_ISO' : {
                        'on' : [gain_switch],
                    },
                },
            }
        elif indi_exec in ['indi_webcam_ccd']:
            logger.warning('indi_webcam_ccd does not support gain settings')
            gain_config = {}
        elif indi_exec in ['indi_v4l2_ccd']:
            logger.warning('indi_v4l2_ccd does not support gain settings')
            gain_config = {}
        else:
            raise Exception('Gain config not implemented for {0:s}, open an enhancement request'.format(indi_exec))


        self.configureDevice(ccdDevice, gain_config)


    def setCcdBinning(self, ccdDevice, bin_value):
        if type(bin_value) is int:
            bin_value = [bin_value, bin_value]
        elif type(bin_value) is str:
            bin_value = [int(bin_value), int(bin_value)]
        elif not bin_value:
            # Assume default
            return

        logger.warning('Setting CCD binning to (%d, %d)', bin_value[0], bin_value[1])

        indi_exec = ccdDevice.getDriverExec()

        if indi_exec in ['indi_asi_ccd', 'indi_asi_single_ccd', 'indi_sv305_ccd', 'indi_qhy_ccd', 'indi_toupcam_ccd', 'indi_simulator_ccd', 'indi_rpicam']:
            binning_config = {
                "PROPERTIES" : {
                    "CCD_BINNING" : {
                        "HOR_BIN" : bin_value[0],
                        "VER_BIN" : bin_value[1],
                    },
                },
            }
        elif indi_exec in ['indi_canon_ccd']:
            logger.warning('indi_canon_ccd does not support bin settings')
            return
        elif indi_exec in ['indi_webcam_ccd']:
            logger.warning('indi_webcam_ccd does not support bin settings')
            return
        elif indi_exec in ['indi_v4l2_ccd']:
            logger.warning('indi_v4l2_ccd does not support bin settings')
            return
        else:
            raise Exception('Binning config not implemented for {0:s}, open an enhancement request'.format(indi_exec))

        self.configureDevice(ccdDevice, binning_config)



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
            c[index].value = values[control_name]

        self.sendNewNumber(c)

        if sync:
            self.__wait_for_ctl_statuses(c, timeout=timeout)

        return c


    def set_switch(self, device, name, on_switches=[], off_switches=[], sync=True, timeout=None):
        c = self.get_control(device, name, 'switch')

        is_exclusive = c.getRule() == PyIndi.ISR_ATMOST1 or c.getRule() == PyIndi.ISR_1OFMANY
        if is_exclusive :
            on_switches = on_switches[0:1]
            off_switches = [s.name for s in c if s.name not in on_switches]

        for index in range(0, len(c)):
            current_state = c[index].getState()
            new_state = current_state

            if c[index].name in on_switches:
                new_state = PyIndi.ISS_ON
            elif is_exclusive or c[index].name in off_switches:
                new_state = PyIndi.ISS_OFF

            c[index].setState(new_state)

        self.sendNewSwitch(c)


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
        while not(ctl):
            ctl = getattr(device, attr)(name)

            if not ctl and 0 < timeout < time.time() - started:
                raise TimeOutException('Timeout finding control {0}'.format(name))

            time.sleep(0.1)

        return ctl


    def __map_indexes(self, ctl, values):
        result = {}
        for i, c in enumerate(ctl):
            #logger.info('Value name: %s', c.name)  # useful to find value names
            if c.name in values:
                result[c.name] = i
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


    def shoot(self, ccdDevice, exposure, sync=True, timeout=None):
        logger.info('Taking %0.8f s exposure', exposure)
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
        self.ccdDevice = ccdDevice

        logger.warning('Connecting to device %s', ccdDevice.getDeviceName())
        self.indiclient.connectDevice(ccdDevice.getDeviceName())


        logger.info('Set BLOB mode')
        self.indiclient.setBLOBMode(1, ccdDevice.getDeviceName(), None)

        self.indiclient.configureDevice(ccdDevice, INDI_CONFIG)

        self.indiclient.setFrameType(ccdDevice, 'FRAME_LIGHT')  # default frame type is light
        self.indiclient.setCcdGain(ccdDevice, CCD_GAIN)
        self.indiclient.setCcdBinning(ccdDevice, CCD_BINMODE)

        self._pre_run_tasks(ccdDevice)

        next_frame_time = time.time()  # start immediately
        frame_start_time = time.time()
        waiting_for_frame = False

        ### main loop starts
        while True:
            now = time.time()

            ### Blocking mode ###

            #try:
            #    self.shoot(ccdDevce, CCD_EXPOSURE, sync=True)
            #except TimeOutException as e:
            #    logger.error('Timeout: %s', str(e))
            #    time.sleep(5.0)
            #    continue


            #full_elapsed_s = time.time() - now
            #logger.info('Exposure finished in ######## %0.4f s ########', full_elapsed_s)

            ### sleep for the remaining eposure period
            #remaining_s = CCD_EXPOSURE - full_elapsed_s
            #if remaining_s > 0:
            #    logger.info('Sleeping for additional %0.4f s', remaining_s)
            #    time.sleep(remaining_s)

            ### End Blocking mode ###


            ### Non-blocking mode ###

            if not waiting_for_frame and now >= next_frame_time:
                total_elapsed = now - frame_start_time

                frame_start_time = now

                self.shoot(ccdDevice, CCD_EXPOSURE, sync=False)
                waiting_for_frame = True

                next_frame_time = frame_start_time + CCD_EXPOSURE

                logger.info('Total time since last exposure %0.4f s', total_elapsed)


            if self.indiclient.exposureReceived:
                frame_elapsed = now - frame_start_time

                waiting_for_frame = False
                self.indiclient.exposureReceived = False

                logger.info('Exposure received in ######## %0.4f s ########', frame_elapsed)


            time.sleep(0.05)

            ### End Non-blocking mode ###


class TimeOutException(Exception):
    pass


if __name__ == "__main__":
    ia = IndiExposureTest()
    ia.run()
