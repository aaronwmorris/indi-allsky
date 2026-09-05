#!/usr/bin/env python3

import sys
import logging
import time
from collections import OrderedDict
import ctypes
import PyIndi


INDI_CONFIG = OrderedDict({
    "PROPERTIES": {
        "SIMULATOR_SETTINGS": {
            #"SIM_SKYGLOW": 13.0,
            "SIM_SKYGLOW": 14.0,
        },
    },
    "SWITCHES" : {},
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


    def saveConfig(self, ccd_device):
        save_config = {
            "SWITCHES" : {
                "CONFIG_PROCESS" : {
                    "on"  : ['CONFIG_SAVE'],
                }
            }
        }

        self.configureDevice(ccd_device, save_config)


    def set_number(self, device, name, values, sync=True, timeout=None):
        #logger.info('Name: %s, values: %s', name, str(values))
        c = self.get_control(device, name, 'number')


        if c.getPermission() == PyIndi.IP_RO:
            logger.error('Number control %s is read only', name)
            return c

        for control_name, index in self.__map_indexes(c, values.keys()).items():
            logger.info('Setting %s = %s', c[index].getLabel(), str(values[control_name]))
            c[index].setValue(values[control_name])

        self.sendNewNumber(c)

        if sync:
            self.__wait_for_ctl_statuses(c, timeout=timeout)

        return c


    def set_switch(self, device, name, on_switches=[], off_switches=[], sync=True, timeout=None):
        c = self.get_control(device, name, 'switch')

        if c.getPermission() == PyIndi.IP_RO:
            logger.error('Switch control %s is read only', name)
            return c

        is_exclusive = c.getRule() == PyIndi.ISR_ATMOST1 or c.getRule() == PyIndi.ISR_1OFMANY
        if is_exclusive :
            on_switches = on_switches[0:1]
            off_switches = [s.getName() for s in c if s.getName() not in on_switches]

        for index in range(0, len(c)):
            current_state = c[index].getState()
            new_state = current_state

            if c[index].getName() in on_switches:
                logger.info('Enabling %s (%s)', c[index].getLabel(), c[index].getName())
                new_state = PyIndi.ISS_ON
            elif is_exclusive or c[index].getName() in off_switches:
                new_state = PyIndi.ISS_OFF

            c[index].setState(new_state)

        self.sendNewSwitch(c)

        return c


    def set_text(self, device, name, control_name, values, sync=True, timeout=None):
        c = self.get_control(device, control_name, 'text')

        if c.getPermission() == PyIndi.IP_RO:
            logger.error('Text control %s is read only', name)
            return c

        for control_name, index in self.__map_indexes(c, values.keys()).items():
            logger.info('Setting %s = %s', c[index].getLabel(), str(values[control_name]))
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




class IndiChangeSetting(object):
    def __init__(self):
        self._indi_server = 'localhost'
        self._indi_port = 7624

        self.indiclient = None


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
        time.sleep(3)

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


        self.indiclient.configureDevice(ccdDevice, INDI_CONFIG)


class TimeOutException(Exception):
    pass


if __name__ == "__main__":
    IndiChangeSetting().run()
