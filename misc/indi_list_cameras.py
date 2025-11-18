#!/usr/bin/env python3
##################################################################
# This script lists all cameras/CCDs connected to the indiserver #
##################################################################


import PyIndi
import ctypes
import sys
import time
from prettytable import PrettyTable
import logging


INDI_SERVER = "localhost"
INDI_PORT = 7624


logger = logging.getLogger(__name__)
logger.setLevel(level=logging.WARNING)

LOG_FORMATTER_STREAM = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s %(funcName)s() [%(lineno)d]: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)
logger.addHandler(LOG_HANDLER_STREAM)


class IndiListCameras(PyIndi.BaseClient):

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
        super(IndiListCameras, self).__init__()

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


    def main(self):
        ccd_list = self._findCcds()
        logger.warning('Found %d CCDs', len(ccd_list))


        table = PrettyTable()
        table.field_names = ['', 'Name', 'Driver']


        print()
        for x in range(len(ccd_list)):
            table.add_row([str(x), ccd_list[x].getDeviceName(), ccd_list[x].getDriverExec()])


        print(table)


if __name__ == "__main__":
    indiclient = IndiListCameras()
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
