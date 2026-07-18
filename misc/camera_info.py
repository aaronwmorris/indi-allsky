#!/usr/bin/env python3
##################################################################
# This script gathers simple info about connected cameras        #
##################################################################


import PyIndi
import sys
import time
#import sys
import ctypes
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

    timeout = 2.0


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

            ctl_CONNECTION = self.get_control(device_ccd, 'CONNECTION', 'switch')
            time.sleep(0.5)

            if not device_ccd.isConnected():
                ctl_CONNECTION[0].setState(PyIndi.ISS_ON)   # CONNECT
                ctl_CONNECTION[1].setState(PyIndi.ISS_OFF)  # DISCONNECT
                self.sendNewSwitch(ctl_CONNECTION)


            while not device_ccd.isConnected():
                logger.warning('Waiting on ccd connection')
                time.sleep(0.5)

            logger.info("ccd connected")



        table = PrettyTable()
        table.field_names = ['Device', 'Control', 'Property', 'Current', 'Min', 'Max']

        for device_ccd in ccd_list:
            ctl_CCD_EXPOSURE = self.get_control(device_ccd, 'CCD_EXPOSURE', 'number')
            CCD_EXPOSURE_index_dict = self.__map_indexes(ctl_CCD_EXPOSURE, ['CCD_EXPOSURE_VALUE'])
            exp_index = CCD_EXPOSURE_index_dict['CCD_EXPOSURE_VALUE']

            table.add_row([
                device_ccd.getDeviceName(),
                ctl_CCD_EXPOSURE.getName(),
                ctl_CCD_EXPOSURE[exp_index].getName(),
                ctl_CCD_EXPOSURE[exp_index].getValue(),
                ctl_CCD_EXPOSURE[exp_index].getMin(),
                ctl_CCD_EXPOSURE[exp_index].getMax(),
            ])



            ctl_gain = None
            try:
                ctl_gain = self.get_control(device_ccd, 'CCD_CONTROLS', 'number')
                gain_index_dict = self.__map_indexes(ctl_gain, ['Gain'])
                gain_index = gain_index_dict['Gain']
            except TimeOutException:
                try:
                    ctl_gain = self.get_control(device_ccd, 'CCD_GAIN', 'number')
                    gain_index_dict = self.__map_indexes(ctl_gain, ['GAIN'])
                    gain_index = gain_index_dict['GAIN']
                except TimeOutException:
                    logger.error('Gain control not found')


            if not isinstance(ctl_gain, type(None)):
                table.add_row([
                    device_ccd.getDeviceName(),
                    ctl_gain.getName(),
                    ctl_gain[gain_index].getName(),
                    ctl_gain[gain_index].getValue(),
                    ctl_gain[gain_index].getMin(),
                    ctl_gain[gain_index].getMax(),
                ])


            ctl_CCD_BINNING = self.get_control(device_ccd, 'CCD_BINNING', 'number')
            binning_index_dict = self.__map_indexes(ctl_CCD_BINNING, ['HOR_BIN'])  # base binning on horizontal, ignore vertical
            binning_index = binning_index_dict['HOR_BIN']


            table.add_row([
                device_ccd.getDeviceName(),
                ctl_CCD_BINNING.getName(),
                ctl_CCD_BINNING[binning_index].getName(),
                ctl_CCD_BINNING[binning_index].getValue(),
                ctl_CCD_BINNING[binning_index].getMin(),
                ctl_CCD_BINNING[binning_index].getMax(),
            ])


        print(table)


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


    def get_control(self, device, name, ctl_type, timeout=None):
        if timeout is None:
            timeout = self.timeout

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


    def __map_indexes(self, ctl, values):
        result = {}
        for i, c in enumerate(ctl):
            #logger.info('Value name: %s', c.getName())  # useful to find value names
            if c.getName() in values:
                result[c.getName()] = i
        return result


class TimeOutException(Exception):
    pass


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
