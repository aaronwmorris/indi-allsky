import time
import io
import tempfile
import ctypes
from datetime import datetime
import logging
#from pprint import pformat

from astropy.io import fits

import PyIndi

from .flask import db
from .flask import create_app

from .flask.models import TaskQueueQueue
from .flask.models import TaskQueueState
from .flask.models import IndiAllSkyDbTaskQueueTable

from .exceptions import TimeOutException

logger = logging.getLogger('indi_allsky')


app = create_app()


class IndiClient(PyIndi.BaseClient):

    __state_to_str = {
        PyIndi.IPS_IDLE  : 'IDLE',
        PyIndi.IPS_OK    : 'OK',
        PyIndi.IPS_BUSY  : 'BUSY',
        PyIndi.IPS_ALERT : 'ALERT',
    }

    __switch_types = {
        PyIndi.ISR_1OFMANY : 'ONE_OF_MANY',
        PyIndi.ISR_ATMOST1 : 'AT_MOST_ONE',
        PyIndi.ISR_NOFMANY : 'ANY',
    }

    __type_to_str = {
        PyIndi.INDI_NUMBER  : 'number',
        PyIndi.INDI_SWITCH  : 'switch',
        PyIndi.INDI_TEXT    : 'text',
        PyIndi.INDI_LIGHT   : 'light',
        PyIndi.INDI_BLOB    : 'blob',
        PyIndi.INDI_UNKNOWN : 'unknown',
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


    __canon_iso_switch = {
        'auto' : 'ISO0',
        0      : 'ISO0',  # ISO0 is auto
        100    : 'ISO1',
        200    : 'ISO2',
        400    : 'ISO3',
        800    : 'ISO4',
        1600   : 'ISO5',
        3200   : 'ISO6',
        6400   : 'ISO7',
        12800  : 'ISO8',   # untested
        25600  : 'ISO9',   # untested
        51200  : 'ISO10',  # untested
    }


    def __init__(self, config, image_q, gain_v, bin_v, sensortemp_v):
        super(IndiClient, self).__init__()

        self.config = config
        self.image_q = image_q
        self.gain_v = gain_v
        self.bin_v = bin_v
        self.sensortemp_v = sensortemp_v

        self._filename_t = 'ccd{0:d}_{1:s}.{2:s}'

        self._timeout = 65.0
        self._exposure = 0.0

        self.exposureStartTime = None

        logger.info('creating an instance of IndiClient')


    @property
    def timeout(self):
        return self._timeout

    @timeout.setter
    def timeout(self, new_timeout):
        self._timeout = float(new_timeout)

    @property
    def exposure(self):
        return self._exposure

    @exposure.setter
    def exposure(self, new_exposure):
        self._exposure = float(new_exposure)

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

        exposure_elapsed_s = time.time() - self.exposureStartTime

        #start = time.time()

        ### get image data
        imgdata = bp.getblobdata()

        blobfile = io.BytesIO(imgdata)
        hdulist = fits.open(blobfile)

        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.fit')

        hdulist.writeto(f_tmpfile)

        f_tmpfile.flush()
        f_tmpfile.close()


        #elapsed_s = time.time() - start
        #logger.info('Blob downloaded in %0.4f s', elapsed_s)

        exp_date = datetime.now()

        ### process data in worker
        jobdata = {
            'filename'    : f_tmpfile.name,
            'exposure'    : self._exposure,
            'exp_time'    : datetime.timestamp(exp_date),  # datetime objects are not json serializable
            'exp_elapsed' : exposure_elapsed_s,
            'camera_id'   : self.config['DB_CCD_ID'],
            'filename_t'  : self._filename_t,
        }

        with app.app_context():
            task = IndiAllSkyDbTaskQueueTable(
                queue=TaskQueueQueue.IMAGE,
                state=TaskQueueState.QUEUED,
                data=jobdata,
            )

            db.session.add(task)
            db.session.commit()

            self.image_q.put({'task_id' : task.id})


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


    def updateCcdBlobMode(self, ccd_device, blobmode=PyIndi.B_ALSO, prop=None):
        logger.info('Set BLOB mode')
        self.setBLOBMode(blobmode, ccd_device.getDeviceName(), prop)


    def disableDebug(self, device):
        debug_config = {
            "SWITCHES" : {
                "DEBUG" : {
                    "on"  : ["DISABLE"],
                    "off" : ["ENABLE"],
                },
            }
        }

        self.configureDevice(device, debug_config)


    def resetCcdFrame(self, ccd_device):
        reset_config = {
            "SWITCHES" : {
                "CCD_FRAME_RESET" : {
                    "on"  : ['RESET'],
                }
            }
        }

        self.configureDevice(ccd_device, reset_config)


    def setFrameType(self, ccd_device, frame_type):
        frame_config = {
            "SWITCHES" : {
                "CCD_FRAME_TYPE" : {
                    "on"  : [frame_type],
                }
            }
        }

        self.configureDevice(ccd_device, frame_config)


    def getCcdInfo(self, ccdDevice):
        ccdinfo = dict()

        ctl_CCD_EXPOSURE = self.get_control(ccdDevice, 'CCD_EXPOSURE', 'number')
        ccdinfo['CCD_EXPOSURE'] = dict()
        for i in ctl_CCD_EXPOSURE:
            ccdinfo['CCD_EXPOSURE'][i.getName()] = {
                'current' : i.getValue(),
                'min'     : i.min,
                'max'     : i.max,
                'step'    : i.step,
                'format'  : i.format,
            }


        ctl_CCD_INFO = self.get_control(ccdDevice, 'CCD_INFO', 'number')

        ccdinfo['CCD_INFO'] = dict()
        for i in ctl_CCD_INFO:
            ccdinfo['CCD_INFO'][i.getName()] = {
                'current' : i.getValue(),
                'min'     : i.min,
                'max'     : i.max,
                'step'    : i.step,
                'format'  : i.format,
            }


        try:
            logger.info('Detecting bayer pattern')
            ctl_CCD_CFA = self.get_control(ccdDevice, 'CCD_CFA', 'text', timeout=5.0)

            ccdinfo['CCD_CFA'] = dict()
            for i in ctl_CCD_CFA:
                ccdinfo['CCD_CFA'][i.getName()] = {
                    'text' : i.getText(),
                }
        except TimeOutException:
            logger.warning('CCD_CFA fetch timeout, assuming monochrome camera')
            ccdinfo['CCD_CFA'] = {
                'CFA_TYPE' : {},
            }


        ctl_CCD_FRAME = self.get_control(ccdDevice, 'CCD_FRAME', 'number')

        ccdinfo['CCD_FRAME'] = dict()
        for i in ctl_CCD_FRAME:
            ccdinfo['CCD_FRAME'][i.getName()] = {
                'current' : i.getValue(),
                'min'     : i.min,
                'max'     : i.max,
                'step'    : i.step,
                'format'  : i.format,
            }


        ctl_CCD_FRAME_TYPE = self.get_control(ccdDevice, 'CCD_FRAME_TYPE', 'switch')
        ccdinfo['CCD_FRAME_TYPE'] = dict()

        for i in ctl_CCD_FRAME_TYPE:
            ccdinfo['CCD_FRAME_TYPE'][i.getName()] = i.getState()


        gain_info = self.getCcdGain(ccdDevice)
        ccdinfo['GAIN_INFO'] = gain_info

        #logger.info('CCD Info: %s', pformat(ccdinfo))
        return ccdinfo


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


    def configureDevice(self, device, indi_config, sleep=1.0):
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
        time.sleep(sleep)


    def getCcdTemperature(self, ccdDevice):
        temp = ccdDevice.getNumber("CCD_TEMPERATURE")

        if isinstance(temp, type(None)):
            logger.warning("Sensor temperature: not supported")
            temp_val = -273.15  # absolute zero  :-)
        else:
            temp_val = float(temp[0].value)
            logger.info("Sensor temperature: %0.1f", temp_val)

        with self.sensortemp_v.get_lock():
            self.sensortemp_v.value = temp_val

        return temp_val


    def setCcdExposure(self, ccdDevice, exposure, sync=False, timeout=None):
        self.exposureStartTime = time.time()

        if not timeout:
            timeout = self._timeout

        self._exposure = exposure

        ctl = self.set_number(ccdDevice, 'CCD_EXPOSURE', {'CCD_EXPOSURE_VALUE': exposure}, sync=sync, timeout=timeout)

        return ctl


    def getCcdGain(self, ccdDevice):
        indi_exec = ccdDevice.getDriverExec()


        # for cameras that do not support gain
        fake_gain_info = {
            'current' : -1,
            'min'     : -1,
            'max'     : -1,
            'step'    : 1,
            'format'  : '',
        }


        if indi_exec in [
            'indi_asi_ccd',
            'indi_asi_single_ccd',
            'indi_toupcam_ccd',
            'indi_altair_ccd',
            'indi_playerone_ccd',
        ]:
            gain_ctl = self.get_control(ccdDevice, 'CCD_CONTROLS', 'number')
            gain_index_dict = self.__map_indexes(gain_ctl, ['Gain'])
            index = gain_index_dict['Gain']
        elif indi_exec in [
            'indi_sv305_ccd',
            'indi_qhy_ccd',
            'indi_simulator_ccd',
            'indi_rpicam',
        ]:
            gain_ctl = self.get_control(ccdDevice, 'CCD_GAIN', 'number')
            gain_index_dict = self.__map_indexes(gain_ctl, ['GAIN'])
            index = gain_index_dict['GAIN']
        elif indi_exec in ['indi_sx_ccd']:
            logger.warning('indi_sx_ccd does not support gain settings')
            return fake_gain_info
        elif indi_exec in ['indi_canon_ccd']:
            logger.warning('indi_canon_ccd does not support gain settings')
            return fake_gain_info
        elif indi_exec in ['indi_webcam_ccd']:
            logger.warning('indi_webcam_ccd does not support gain settings')
            return fake_gain_info
        elif indi_exec in ['indi_v4l2_ccd']:
            logger.warning('indi_v4l2_ccd does not support gain settings')
            return fake_gain_info
        else:
            raise Exception('Gain config not implemented for {0:s}, open an enhancement request'.format(indi_exec))

        gain_info = {
            'current' : gain_ctl[index].getValue(),
            'min'     : gain_ctl[index].min,
            'max'     : gain_ctl[index].max,
            'step'    : gain_ctl[index].step,
            'format'  : gain_ctl[index].format,
        }

        #logger.info('Gain Info: %s', pformat(gain_info))
        return gain_info


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
            'indi_sv305_ccd',
            'indi_qhy_ccd',
            'indi_simulator_ccd',
            'indi_rpicam',
        ]:
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
        elif indi_exec in ['indi_sx_ccd']:
            logger.warning('indi_sx_ccd does not support gain settings')
            gain_config = {}
        elif indi_exec in ['indi_webcam_ccd']:
            logger.warning('indi_webcam_ccd does not support gain settings')
            gain_config = {}
        elif indi_exec in ['indi_v4l2_ccd']:
            logger.warning('indi_v4l2_ccd does not support gain settings')
            gain_config = {}
        else:
            raise Exception('Gain config not implemented for {0:s}, open an enhancement request'.format(indi_exec))


        self.configureDevice(ccdDevice, gain_config)


        # Update shared gain value
        with self.gain_v.get_lock():
            self.gain_v.value = int(gain_value)


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

        if indi_exec in [
            'indi_asi_ccd',
            'indi_asi_single_ccd',
            'indi_sv305_ccd',
            'indi_qhy_ccd',
            'indi_toupcam_ccd',
            'indi_altair_ccd',
            'indi_simulator_ccd',
            'indi_rpicam',
            'indi_playerone_ccd',
            'indi_sx_ccd',
        ]:
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

        # Update shared gain value
        with self.bin_v.get_lock():
            self.bin_v.value = bin_value[0]


    # Most of below was borrowed from https://github.com/GuLinux/indi-lite-tools/blob/master/pyindi_sequence/device.py


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


    def set_controls(self, device, controls):
        self.set_number(device, 'CCD_CONTROLS', controls)


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

        return c


    def set_text(self, device, control_name, values, sync=True, timeout=None):
        c = self.get_control(device, control_name, 'text')
        for control_name, index in self.__map_indexes(c, values.keys()).items():
            c[index].text = values[control_name]

        self.sendNewText(c)

        if sync:
            self.__wait_for_ctl_statuses(c, timeout=timeout)

        return c


    def values(self, device, ctl_name, ctl_type):
        return dict(map(lambda c: (c.name, c.value), self.get_control(device, ctl_name, ctl_type)))


    def switch_values(self, device, name, ctl=None):
        return self.__control2dict(device, name, 'switch', lambda c: {'value': c.getState() == PyIndi.ISS_ON}, ctl)


    def text_values(self, device, name, ctl=None):
        return self.__control2dict(device, name, 'text', lambda c: {'value': c.text}, ctl)


    def number_values(self, device, name, ctl=None):
        return self.__control2dict(device, name, 'text', lambda c: {'value': c.value, 'min': c.min, 'max': c.max, 'step': c.step, 'format': c.format}, ctl)


    def light_values(self, device, name, ctl=None):
        return self.__control2dict(device, name, 'light', lambda c: {'value': self.__state_to_str[c.getState()]}, ctl)


    def ctl_ready(self, ctl, statuses=[PyIndi.IPS_OK, PyIndi.IPS_IDLE]):
        if not ctl:
            return True, 'unset'

        state = ctl.getState()

        ready = state in statuses
        state_str = self.__state_to_str.get(state, 'UNKNOWN')

        return ready, state_str


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

            time.sleep(0.15)


    def __map_indexes(self, ctl, values):
        result = {}
        for i, c in enumerate(ctl):
            #logger.info('Value name: %s', c.name)  # useful to find value names
            if c.name in values:
                result[c.name] = i
        return result


    def __control2dict(self, device, control_name, control_type, transform, control=None):
        def get_dict(element):
            dest = {'name': element.name, 'label': element.label}
            dest.update(transform(element))
            return dest

        control = control if control else self.get_control(device, control_name, control_type)

        return [get_dict(c) for c in control]


