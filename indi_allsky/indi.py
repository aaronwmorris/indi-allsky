import time
import ctypes
from datetime import datetime

import multiprocessing

import PyIndi

from .exceptions import TimeOutException


logger = multiprocessing.get_logger()


class IndiClient(PyIndi.BaseClient):
    def __init__(self, config, indiblob_status_send, image_q, gain_v, bin_v):
        super(IndiClient, self).__init__()

        self.config = config
        self.indiblob_status_send = indiblob_status_send
        self.image_q = image_q
        self.gain_v = gain_v
        self.bin_v = bin_v

        self._device = None
        self._filename_t = '{0:s}.{1:s}'
        self._img_subdirs = []

        self._timeout = 10.0

        self.__state_to_str = { PyIndi.IPS_IDLE: 'IDLE', PyIndi.IPS_OK: 'OK', PyIndi.IPS_BUSY: 'BUSY', PyIndi.IPS_ALERT: 'ALERT' }

        self.__indi_interfaces = {
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

        logger.info('creating an instance of IndiClient')


    @property
    def device(self):
        return self._device

    @device.setter
    def device(self, new_device):
        self._device = new_device

    @property
    def timeout(self):
        return self._timeout

    @timeout.setter
    def timeout(self, new_timeout):
        self._timeout = float(new_timeout)

    @property
    def filename_t(self):
        return self._filename_t

    @filename_t.setter
    def filename_t(self, new_filename_t):
        self._filename_t = new_filename_t

    @property
    def img_subdirs(self):
        return self._img_subdirs

    @img_subdirs.setter
    def img_subdirs(self, new_img_subdirs):
        self._img_subdirs = new_img_subdirs


    def newDevice(self, d):
        logger.info("new device %s", d.getDeviceName())

    def newProperty(self, p):
        #logger.info("new property %s for device %s", p.getName(), p.getDeviceName())
        pass

    def removeProperty(self, p):
        logger.info("remove property %s for device %s", p.getName(), p.getDeviceName())


    def newBLOB(self, bp):
        logger.info("new BLOB %s", bp.name)
        start = time.time()

        ### get image data
        imgdata = bp.getblobdata()

        elapsed_s = time.time() - start
        logger.info('Blob downloaded in %0.4f s', elapsed_s)

        self.indiblob_status_send.send(True)  # Notify main process next exposure may begin

        exp_date = datetime.now()

        ### process data in worker
        self.image_q.put({
            'imgdata'     : imgdata,
            'exp_date'    : exp_date,
            'filename_t'  : self._filename_t,
            'img_subdirs' : self._img_subdirs,
        })


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


    def configureCcd(self, indi_config):
        ### Configure CCD Properties
        for k, v in indi_config.get('PROPERTIES', {}).items():
            logger.info('Setting property %s', k)
            self.set_number(k, v)

        ### Configure CCD Switches
        for k, v in indi_config.get('SWITCHES', {}).items():
            logger.info('Setting switch %s', k)
            self.set_switch(k, on_switches=v['on'], off_switches=v.get('off', []))

        ### Configure controls
        #self.indiclient.set_controls(indi_config.get('CONTROLS', {}))

        # Sleep after configuration
        time.sleep(1.0)


    def setCcdGain(self, gain_value):
        logger.warning('Setting CCD gain to %d', gain_value)
        indi_exec = self.device.getDriverExec()

        if indi_exec in ['indi_asi_ccd']:
            gain_config = {
                "CCD_CONTROLS" : {
                    "Gain" : gain_value,
                },
            }
        elif indi_exec in ['indi_sv305_ccd']:
            gain_config = {
                "PROPERTIES" : {
                    "CCD_GAIN" : {
                        "GAIN" : gain_value,
                    },
                },
            }
        else:
            raise Exception('Gain config not implemented for {0:s}, open an enhancement request'.format(indi_exec))


        self.configureCcd(gain_config)


        # Update shared gain value
        with self.gain_v.get_lock():
            self.gain_v.value = int(gain_value)


    def setCcdBinning(self, bin_value):
        if type(bin_value) is int:
            bin_value = [bin_value, bin_value]
        elif not bin_value:
            # Assume default
            return

        logger.warning('Setting CCD binning to (%d, %d)', bin_value[0], bin_value[1])

        indi_exec = self.device.getDriverExec()

        if indi_exec in ['indi_asi_ccd', 'indi_sv305_ccd']:
            binning_config = {
                "PROPERTIES" : {
                    "CCD_BINNING" : {
                        "HOR_BIN" : bin_value[0],
                        "VER_BIN" : bin_value[1],
                    },
                },
            }
        else:
            raise Exception('Binning config not implemented for {0:s}, open an enhancement request'.format(indi_exec))

        self.configureCcd(binning_config)

        # Update shared gain value
        with self.bin_v.get_lock():
            self.bin_v.value = int(bin_value)


    # Most of below was borrowed from https://github.com/GuLinux/indi-lite-tools/blob/master/pyindi_sequence/device.py

    def get_control(self, name, ctl_type, timeout=None, device=None):
        if not device:
            device = self._device

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

            time.sleep(0.01)

        return ctl


    def set_controls(self, controls, device=None):
        if not device:
            device = self._device

        self.set_number('CCD_CONTROLS', controls, device=device)


    def set_number(self, name, values, sync=True, timeout=None, device=None):
        if not device:
            device = self._device

        #logger.info('Name: %s, values: %s', name, str(values))
        c = self.get_control(name, 'number', device=device)
        for control_name, index in self.__map_indexes(c, values.keys()).items():
            c[index].value = values[control_name]

        self.sendNewNumber(c)

        if sync:
            self.__wait_for_ctl_statuses(c, timeout=timeout)

        return c


    def set_switch(self, name, on_switches=[], off_switches=[], sync=True, timeout=None, device=None):
        if not device:
            device = self._device

        c = self.get_control(name, 'switch', device=device)

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


    def set_text(self, control_name, values, sync=True, timeout=None, device=None):
        if not device:
            device = self._device

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
        return self.__control2dict(name, 'switch', lambda c: {'value': c.getState() == PyIndi.ISS_ON}, ctl)


    def text_values(self, name, ctl=None):
        return self.__control2dict(name, 'text', lambda c: {'value': c.text}, ctl)


    def number_values(self, name, ctl=None):
        return self.__control2dict(name, 'text', lambda c: {'value': c.value, 'min': c.min, 'max': c.max, 'step': c.step, 'format': c.format}, ctl)


    def light_values(self, name, ctl=None):
        return self.__control2dict(name, 'light', lambda c: {'value': self.__state_to_str[c.getState()]}, ctl)


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


