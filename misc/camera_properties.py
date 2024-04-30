#!/usr/bin/env python3

import PyIndi
import time
import sys
import ctypes
from pprint import pformat  # noqa: F401
import logging


INDI_SERVER = "localhost"
INDI_PORT = 7624


logger = logging.getLogger(__name__)
logger.setLevel(level=logging.INFO)

LOG_FORMATTER_STREAM = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s %(funcName)s() [%(lineno)d]: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)
logger.addHandler(LOG_HANDLER_STREAM)


class IndiProperties(PyIndi.BaseClient):

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

    __state_to_str_p = {
        PyIndi.IPS_IDLE  : 'IDLE',
        PyIndi.IPS_OK    : 'OK',
        PyIndi.IPS_BUSY  : 'BUSY',
        PyIndi.IPS_ALERT : 'ALERT',
    }

    __state_to_str_s = {
        PyIndi.ISS_OFF : 'OFF',
        PyIndi.ISS_ON  : 'ON',
    }

    __switch_types = {
        PyIndi.ISR_1OFMANY : 'ONE_OF_MANY',
        PyIndi.ISR_ATMOST1 : 'AT_MOST_ONE',
        PyIndi.ISR_NOFMANY : 'ANY',
    }


    def __init__(self):
        super(IndiProperties, self).__init__()

        pyindi_version = '.'.join((
            str(getattr(PyIndi, 'INDI_VERSION_MAJOR', -1)),
            str(getattr(PyIndi, 'INDI_VERSION_MINOR', -1)),
            str(getattr(PyIndi, 'INDI_VERSION_RELEASE', -1)),
        ))

        logger.info("INDI version: %s", pyindi_version)


    def newDevice(self, d):
        logger.info("new device %s", d.getDeviceName())

    def removeDevice(self, d):
        logger.info("removed device %s", d.getDeviceName())

    def newProperty(self, p):
        pass

    def removeProperty(self, p):
        pass

    def newBLOB(self, bp):
        logger.info("new BLOB %s", bp.name)

    def newSwitch(self, svp):
        pass

    def newNumber(self, nvp):
        pass

    def newText(self, tvp):
        pass

    def newLight(self, lvp):
        pass

    def newMessage(self, d, m):
        pass

    def serverConnected(self):
        pass

    def serverDisconnected(self, code):
        pass


    def main(self):
        ccd_list = self._findCcds()
        logger.info('Found %d CCDs', len(ccd_list))

        for device_ccd in ccd_list:

            connection = device_ccd.getSwitch("CONNECTION")
            time.sleep(0.5)

            if not device_ccd.isConnected():
                connection[0].setState(PyIndi.ISS_ON)   # CONNECT
                connection[1].setState(PyIndi.ISS_OFF)  # DISCONNECT
                self.sendNewSwitch(connection)


            while not device_ccd.isConnected():
                logger.warning('Waiting on ccd connection')
                time.sleep(0.5)

            logger.info("ccd connected")


            print('#########################################')
            print('########## Start properties #############')
            print('#########################################')
            print('```')  # github formatting

            prop_dict = self.getDeviceProperties(device_ccd)
            for k, v in prop_dict.items():
                print('{0}'.format(k))

                for k2, v2 in v.items():
                    print('  {0}'.format(k2))

                    for k3, v3 in v2.items():
                        print('    {0}: {1}'.format(k3, v3))

            print('```')  # github formatting
            print('#########################################')
            print('########### End properties ##############')
            print('#########################################')


    def getDeviceProperties(self, device):
        properties = dict()

        for p in device.getProperties():
            name = p.getName()
            properties[name] = dict()

            #logger.info('%s', p.getType())
            if p.getType() == PyIndi.INDI_TEXT:
                for t in p.getText():
                    properties[name][t.getName() + ' (text)'] = {
                        'current' : t.getText(),
                    }
            elif p.getType() == PyIndi.INDI_NUMBER:
                for t in p.getNumber():
                    properties[name][t.getName() + ' (number)'] = {
                        'current' : t.getValue(),
                        'min'     : t.getMin(),
                        'max'     : t.getMax(),
                        'step'    : t.getStep(),
                        'format'  : t.getFormat(),
                    }
            elif p.getType() == PyIndi.INDI_SWITCH:
                for t in p.getSwitch():
                    properties[name][t.getName() + ' (switch)'] = {
                        'state' : self.__state_to_str_s[t.getState()],
                    }
            elif p.getType() == PyIndi.INDI_LIGHT:
                for t in p.getLight():
                    properties[name][t.getName() + ' (light)'] = {
                        'state' : self.__state_to_str_p[t.getState()],
                    }
            elif p.getType() == PyIndi.INDI_BLOB:
                pass
                #for t in p.getBLOB():
                #    properties[name][t.getName() + ' (blob)'] = {}
            #else:
            #    logger.info('%s', p.getType())

        #logger.warning('%s', pformat(properties))

        return properties


    def findDeviceInterfaces(self, device):
        interface = device.getDriverInterface()
        if type(interface) is int:
            device_interfaces = interface
        else:
            interface.acquire()
            device_interfaces = int(ctypes.cast(interface.__int__(), ctypes.POINTER(ctypes.c_uint16)).contents.value)
            interface.disown()

        return device_interfaces



    def _findCcds(self):
        logger.info('Searching for available cameras')

        ccd_list = list()

        for device in self.getDevices():
            logger.info('Found device %s', device.getDeviceName())
            device_interfaces = self.findDeviceInterfaces(device)

            for k, v in self.__indi_interfaces.items():
                if device_interfaces & k:
                    if k == PyIndi.BaseDevice.CCD_INTERFACE:
                        logger.info(' Detected %s', device.getDeviceName())
                        ccd_list.append(device)

        return ccd_list


if __name__ == "__main__":
    indiclient = IndiProperties()
    indiclient.setServer(INDI_SERVER, INDI_PORT)


    logger.info("Connecting to indiserver")
    if not indiclient.connectServer():
        logger.error(
            "No indiserver running on %s:%d",
            indiclient.getHost(),
            indiclient.getPort()
        )
        sys.exit(1)


    time.sleep(5)  # give devices time to present

    indiclient.main()

