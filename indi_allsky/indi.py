import time
from datetime import datetime

import multiprocessing

import PyIndi

from .exceptions import TimeOutException


logger = multiprocessing.get_logger()


class IndiClient(PyIndi.BaseClient):
    def __init__(self, config, indiblob_status_send, image_q):
        super(IndiClient, self).__init__()

        self.config = config
        self.indiblob_status_send = indiblob_status_send
        self.image_q = image_q

        self._device = None
        self._filename_t = '{0:s}.{1:s}'

        self._timeout = 10.0

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
        self.image_q.put({ 'imgdata' : imgdata, 'exp_date' : exp_date, 'filename_t' : self._filename_t })


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


