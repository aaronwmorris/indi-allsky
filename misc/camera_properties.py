#!/usr/bin/env python3
##################################################################
# This script enumerates camera properties                       #
##################################################################


import PyIndi
import time
import sys
import ctypes
from pprint import pformat  # noqa: F401
from prettytable import PrettyTable
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

    __perm_to_str = {
        PyIndi.IP_RO : 'READ_ONLY',
        PyIndi.IP_WO : 'WRITE_ONLY',
        PyIndi.IP_RW : 'READ_WRITE',
    }


    def __init__(self):
        super(IndiProperties, self).__init__()

        pyindi_version = '.'.join((
            str(getattr(PyIndi, 'INDI_VERSION_MAJOR', -1)),
            str(getattr(PyIndi, 'INDI_VERSION_MINOR', -1)),
            str(getattr(PyIndi, 'INDI_VERSION_RELEASE', -1)),
        ))

        logger.warning("INDI version: %s", pyindi_version)


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
        logger.warning('Found %d CCDs', len(ccd_list))

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


            table_number = PrettyTable()
            table_number.field_names = ['Control', 'Property', 'Label', 'Current', 'Min', 'Max', 'Perm']

            table_text = PrettyTable()
            table_text.field_names = ['Control', 'Property', 'Label', 'Current', 'Perm']

            table_switch = PrettyTable()
            table_switch.field_names = ['Control', 'Property', 'Label', 'State', 'Perm']

            table_light = PrettyTable()
            table_light.field_names = ['Control', 'Property', 'Label', 'State', 'Perm']

            table_blob = PrettyTable()
            table_blob.field_names = ['Control', 'Property', 'Label', 'Perm']


            print('#########################################')
            print('########## Start properties #############')
            print('#########################################')
            print('```')  # github formatting


            prop_dict = self.getDeviceProperties(device_ccd)
            for prop, prop_v in prop_dict.items():
                if prop_v['type'] == PyIndi.INDI_NUMBER:
                    # number
                    for c in prop_v['controls']:
                        try:
                            # try to use embedded C formatting
                            c_value = c['format'] % c['value']
                            c_min = c['format'] % c['min']
                            c_max = c['format'] % c['max']
                        except ValueError:
                            c_value = c['value']
                            c_min = c['min']
                            c_max = c['max']


                        table_number.add_row([
                            prop,
                            c['name'],
                            '"{0:s}"'.format(c['label']),
                            #'{0:0.2f}'.format(c['value']),
                            c_value,
                            c_min,
                            c_max,
                            self.__perm_to_str[prop_v['permissions']],
                        ])


                    table_number.add_divider()

                elif prop_v['type'] == PyIndi.INDI_TEXT:
                    # text
                    for c in prop_v['controls']:
                        table_text.add_row([
                            prop,
                            c['name'],
                            '"{0:s}"'.format(c['label']),
                            '"{0:s}"'.format(c['text']),
                            self.__perm_to_str[prop_v['permissions']],
                        ])

                    table_text.add_divider()

                elif prop_v['type'] == PyIndi.INDI_SWITCH:
                    # switch
                    for c in prop_v['controls']:
                        table_switch.add_row([
                            prop,
                            c['name'],
                            '"{0:s}"'.format(c['label']),
                            self.__state_to_str_s[c['state']],
                            self.__perm_to_str[prop_v['permissions']],
                        ])

                    table_switch.add_divider()

                elif prop_v['type'] == PyIndi.INDI_LIGHT:
                    # light
                    for c in prop_v['controls']:
                        table_light.add_row([
                            prop,
                            c['name'],
                            '"{0:s}"'.format(c['label']),
                            self.__state_to_str_s[c['state']],
                            self.__perm_to_str[prop_v['permissions']],
                        ])

                    table_text.add_divider()

                elif prop_v['type'] == PyIndi.INDI_BLOB:
                    # blob
                    for c in prop_v['controls']:
                        table_blob.add_row([
                            prop,
                            c['name'],
                            '"{0:s}"'.format(c['label']),
                            self.__perm_to_str[prop_v['permissions']],
                        ])


            print('Control Type: Number')
            print(table_number)

            print()
            print('Control Type: Text')
            print(table_text)

            print()
            print('Control Type: Switch')
            print(table_switch)

            print()
            print('Control Type: Light')
            print(table_light)

            print()
            print('Control Type: Blob')
            print(table_blob)


            print('```')  # github formatting
            print('#########################################')
            print('########### End properties ##############')
            print('#########################################')


    def getDeviceProperties(self, device):
        properties = dict()

        for p in device.getProperties():
            name = p.getName()

            properties[name] = {
                'type'        : p.getType(),
                'permissions' : p.getPermission(),
                'controls'    : list(),
            }

            #logger.info('%s', p.getType())
            if p.getType() == PyIndi.INDI_TEXT:

                for t in p.getText():
                    control = {
                        'name'    : t.getName(),
                        'label'   : t.getLabel(),
                        'text'    : t.getText(),
                    }

                    properties[name]['controls'].append(control)

                continue
            elif p.getType() == PyIndi.INDI_NUMBER:
                for t in p.getNumber():
                    control = {
                        'name'    : t.getName(),
                        'label'   : t.getLabel(),
                        'value'   : t.getValue(),
                        'min'     : t.getMin(),
                        'max'     : t.getMax(),
                        'format'  : t.getFormat(),
                    }

                    properties[name]['controls'].append(control)

                continue
            elif p.getType() == PyIndi.INDI_SWITCH:
                for t in p.getSwitch():
                    control = {
                        'name'    : t.getName(),
                        'label'   : t.getLabel(),
                        'state'   : t.getState(),
                    }

                    properties[name]['controls'].append(control)

                continue
            elif p.getType() == PyIndi.INDI_LIGHT:
                for t in p.getLight():
                    control = {
                        'name'    : t.getName(),
                        'label'   : t.getLabel(),
                        'state'   : t.getState(),
                    }

                    properties[name]['controls'].append(control)

                continue
            elif p.getType() == PyIndi.INDI_BLOB:
                for t in p.getBLOB():
                    control = {
                        'name'    : t.getName(),
                        'label'   : t.getLabel(),
                    }

                    properties[name]['controls'].append(control)

                continue
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

