import time
import io
import tempfile
from datetime import datetime
from pathlib import Path
import logging
#from pprint import pformat

from astropy.io import fits

import PyIndi

from .indi import IndiClient

#from ..flask import db
from ..flask import create_app

#from ..flask.models import TaskQueueQueue
#from ..flask.models import TaskQueueState
#from ..flask.models import IndiAllSkyDbTaskQueueTable

from ..exceptions import TimeOutException

logger = logging.getLogger('indi_allsky')


app = create_app()


class IndiClientPassive(IndiClient):

    __state_to_str_p = {
        PyIndi.IPS_IDLE  : 'IDLE',
        PyIndi.IPS_OK    : 'OK',
        PyIndi.IPS_BUSY  : 'BUSY',
        PyIndi.IPS_ALERT : 'ALERT',
    }


    def __init__(
        self,
        config,
        image_q,
        latitude_v,
        longitude_v,
        ra_v,
        dec_v,
        gain_v,
        bin_v,
    ):
        super(IndiClient, self).__init__()

        self.config = config
        self.image_q = image_q

        self.latitude_v = latitude_v
        self.longitude_v = longitude_v

        self.ra_v = ra_v
        self.dec_v = dec_v

        self.gain_v = gain_v
        self.bin_v = bin_v

        self._camera_id = None

        self._ccd_device = None
        self._ctl_ccd_exposure = None

        self._telescope_device = None
        self._gps_device = None

        self._filename_t = 'ccd{0:d}_{1:s}.{2:s}'

        self._timeout = 10.0
        self._exposure = 0.0

        self.exposureStartTime = None

        logger.info('creating an instance of IndiClient')

        pyindi_version = '.'.join((
            str(getattr(PyIndi, 'INDI_VERSION_MAJOR', -1)),
            str(getattr(PyIndi, 'INDI_VERSION_MINOR', -1)),
            str(getattr(PyIndi, 'INDI_VERSION_RELEASE', -1)),
        ))
        logger.info('PyIndi version: %s', pyindi_version)


    @property
    def camera_id(self):
        return self._camera_id

    @camera_id.setter
    def camera_id(self, new_camera_id):
        self._camera_id = int(new_camera_id)

    @property
    def ccd_device(self):
        return self._ccd_device

    @ccd_device.setter
    def ccd_device(self, new_ccd_device):
        self._ccd_device = new_ccd_device


    @property
    def telescope_device(self):
        return self._telescope_device

    @telescope_device.setter
    def telescope_device(self, new_telescope_device):
        self._telescope_device = new_telescope_device


    @property
    def gps_device(self):
        return self._gps_device

    @gps_device.setter
    def gps_device(self, new_gps_device):
        self._gps_device = new_gps_device


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

    def removeDevice(self, d):
        logger.info("remove device %s", d.getDeviceName())


    def newProperty(self, p):
        #logger.info("new property %s for %s", p.getName(), p.getDeviceName())
        pass

    def removeProperty(self, p):
        logger.info("remove property %s for %s", p.getName(), p.getDeviceName())


    def updateProperty(self, p):
        # INDI 2.x.x code path

        if hasattr(PyIndi.BaseMediator, 'newNumber'):
            # indi 1.9.9 has a bug that will run both the new an old code paths for properties
            return

        if p.getType() == PyIndi.INDI_BLOB:
            p_blob = PyIndi.PropertyBlob(p)
            #logger.info("new Blob %s for %s", p_blob.getName(), p_blob.getDeviceName())
            self.processBlob(p_blob[0])
        elif p.getType() == PyIndi.INDI_NUMBER:
            #p_number = PyIndi.PropertyNumber(p)
            #logger.info("new Number %s for %s", p_number.getName(), p_number.getDeviceName())
            pass
        elif p.getType() == PyIndi.INDI_SWITCH:
            #p_switch = PyIndi.PropertySwitch(p)
            #logger.info("new Switch %s for %s", p_switch.getName(), p_switch.getDeviceName())
            pass
        elif p.getType() == PyIndi.INDI_TEXT:
            #p_text = PyIndi.PropertyText(p)
            #logger.info("new Text %s for %s", p_text.getName(), p_text.getDeviceName())
            pass
        elif p.getType() == PyIndi.INDI_LIGHT:
            #p_light = PyIndi.PropertyLight(p)
            #logger.info("new Light %s for %s", p_light.getName(), p_light.getDeviceName())
            pass
        else:
            logger.warning('Property type not matched: %d', p.getType())


    def newBLOB(self, bp):
        # legacy INDI 1.x.x code path
        #logger.info("new BLOB %s", bp.name)
        self.processBlob(bp)

    def newSwitch(self, svp):
        # legacy INDI 1.x.x code path
        #logger.info("new Switch %s for %s", svp.name, svp.device)
        pass

    def newNumber(self, nvp):
        # legacy INDI 1.x.x code path
        #logger.info("new Number %s for %s", nvp.name, nvp.device)
        pass

    def newText(self, tvp):
        # legacy INDI 1.x.x code path
        #logger.info("new Text %s for %s", tvp.name, tvp.device)
        pass

    def newLight(self, lvp):
        # legacy INDI 1.x.x code path
        #logger.info("new Light %s for %s", lvp.name, lvp.device)
        pass


    def processBlob(self, blob):
        exposure_elapsed_s = time.time() - self.exposureStartTime

        #start = time.time()

        ### get image data
        imgdata = blob.getblobdata()
        blobfile = io.BytesIO(imgdata)
        hdulist = fits.open(blobfile)

        try:
            f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.fit')
            f_tmpfile_p = Path(f_tmpfile.name)

            hdulist.writeto(f_tmpfile)

            f_tmpfile.flush()
            f_tmpfile.close()
        except OSError as e:
            logger.error('OSError: %s', str(e))
            return


        #elapsed_s = time.time() - start
        #logger.info('Blob downloaded in %0.4f s', elapsed_s)

        exp_date = datetime.now()

        ### process data in worker
        jobdata = {
            'filename'    : str(f_tmpfile_p),
            'exposure'    : self._exposure,
            'exp_time'    : datetime.timestamp(exp_date),  # datetime objects are not json serializable
            'exp_elapsed' : exposure_elapsed_s,
            'camera_id'   : self.camera_id,
            'filename_t'  : self._filename_t,
        }

        ### Not using DB task queue to reduce DB I/O
        #with app.app_context():
        #    task = IndiAllSkyDbTaskQueueTable(
        #        queue=TaskQueueQueue.IMAGE,
        #        state=TaskQueueState.QUEUED,
        #        data=jobdata,
        #    )

        #    db.session.add(task)
        #    db.session.commit()

        #    self.image_q.put({'task_id' : task.id})
        ###

        self.image_q.put(jobdata)


    def newMessage(self, d, m):
        logger.info("new Message %s", d.messageQueue(m))

    def serverConnected(self):
        logger.info("Server connected (%s:%d)", self.getHost(), self.getPort())

    def serverDisconnected(self, code):
        logger.info("Server disconnected (exit code = %d, %s, %d", code, str(self.getHost()), self.getPort())


    def parkTelescope(self):
        pass

    def unparkTelescope(self):
        pass

    def setTelescopeParkPosition(self, *args):
        pass

    def disableDebug(self, *args):
        pass

    def disableDebugCcd(self):
        pass

    def saveCcdConfig(self):
        pass

    def resetCcdFrame(self):
        pass

    def setCcdFrameType(self, *args):
        pass

    def configureDevice(self, *args, **kwargs):
        pass

    def configureCcdDevice(self, *args, **kwargs):
        pass


    def configureTelescopeDevice(self, *args, **kwargs):
        pass

    def setTelescopeGps(self, *args):
        pass

    def configureGpsDevice(self, *args, **kwargs):
        pass

    def refreshGps(self):
        pass

    def enableCcdCooler(self):
        pass

    def disableCcdCooler(self):
        pass


    def setCcdTemperature(self, *args, **kwargs):
        pass


    def setCcdExposure(self, exposure, sync=False, timeout=None):
        self.exposureStartTime = time.time()

        self._exposure = exposure

        exposure_ctl = self.get_control(self._ccd_device, 'CCD_CONTROLS', 'number')

        self._ctl_ccd_exposure = exposure_ctl


    def getCcdExposureStatus(self):
        camera_ready, exposure_state = self.ctl_ready(self._ctl_ccd_exposure)

        return camera_ready, exposure_state


    def abortCcdExposure(self):
        pass


    def getCcdGain(self):
        indi_exec = self._ccd_device.getDriverExec()


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
            gain_ctl = self.get_control(self._ccd_device, 'CCD_CONTROLS', 'number')
            gain_index_dict = self.__map_indexes(gain_ctl, ['Gain'])
            index = gain_index_dict['Gain']
        elif indi_exec in [
            'indi_svbony_ccd',
            'indi_sv305_ccd',  # legacy name
            'indi_qhy_ccd',
            'indi_simulator_ccd',
            'indi_rpicam',
            'indi_pylibcamera.py', './indi_pylibcamera.py', '././indi_pylibcamera.py',
        ]:
            gain_ctl = self.get_control(self._ccd_device, 'CCD_GAIN', 'number')
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
        elif indi_exec in ['indi_fake_ccd']:
            return self.ccd_device.getCcdGain()
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


    def setCcdGain(self, gain_value):
        # Update shared gain value
        with self.gain_v.get_lock():
            self.gain_v.value = int(gain_value)


    def setCcdBinning(self, bin_value):
        bin_value = [bin_value, bin_value]

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
        while not ctl:
            ctl = getattr(device, attr)(name)

            if not ctl and 0 < timeout < time.time() - started:
                raise TimeOutException('Timeout finding control {0}'.format(name))

            time.sleep(0.1)

        return ctl


    def set_number(self, device, name, values, sync=True, timeout=None):
        #logger.info('Name: %s, values: %s', name, str(values))
        c = self.get_control(device, name, 'number')

        if c.getPermission() == PyIndi.IP_RO:
            logger.error('Number control %s is read only', name)
            return c

        for control_name, index in self.__map_indexes(c, values.keys()).items():
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
                new_state = PyIndi.ISS_ON
            elif is_exclusive or c[index].getName() in off_switches:
                new_state = PyIndi.ISS_OFF

            c[index].setState(new_state)

        self.sendNewSwitch(c)

        return c


    def set_text(self, device, name, values, sync=True, timeout=None):
        c = self.get_control(device, name, 'text')

        if c.getPermission() == PyIndi.IP_RO:
            logger.error('Text control %s is read only', name)
            return c

        for control_name, index in self.__map_indexes(c, values.keys()).items():
            c[index].setText(values[control_name])

        self.sendNewText(c)

        if sync:
            self.__wait_for_ctl_statuses(c, timeout=timeout)

        return c


    def values(self, device, ctl_name, ctl_type):
        return dict(map(lambda c: (c.getName(), c.getValue()), self.get_control(device, ctl_name, ctl_type)))


    def switch_values(self, device, name, ctl=None):
        return self.__control2dict(device, name, 'switch', lambda c: {'value': c.getState() == PyIndi.ISS_ON}, ctl)


    def text_values(self, device, name, ctl=None):
        return self.__control2dict(device, name, 'text', lambda c: {'value': c.getText()}, ctl)


    def number_values(self, device, name, ctl=None):
        return self.__control2dict(device, name, 'text', lambda c: {'value': c.getValue(), 'min': c.min, 'max': c.max, 'step': c.step, 'format': c.format}, ctl)


    def light_values(self, device, name, ctl=None):
        return self.__control2dict(device, name, 'light', lambda c: {'value': self.__state_to_str_p[c.getState()]}, ctl)


    def ctl_ready(self, ctl, statuses=[PyIndi.IPS_OK, PyIndi.IPS_IDLE]):
        if not ctl:
            return True, 'unset'

        state = ctl.getState()

        ready = state in statuses
        state_str = self.__state_to_str_p.get(state, 'UNKNOWN')

        return ready, state_str


    def __wait_for_ctl_statuses(self, ctl, statuses=[PyIndi.IPS_OK, PyIndi.IPS_IDLE], timeout=None):
        started = time.time()

        if timeout is None:
            timeout = self._timeout

        while ctl.getState() not in statuses:
            #logger.info('%s/%s/%s: %s', ctl.getDeviceName(), ctl.getGroupName(), ctl.getName(), self.__state_to_str_p[ctl.getState()])
            if ctl.getState() == PyIndi.IPS_ALERT and 0.5 > time.time() - started:
                raise RuntimeError('Error while changing property {0}'.format(ctl.getName()))

            elapsed = time.time() - started

            if 0 < timeout < elapsed:
                raise TimeOutException('Timeout error while changing property {0}: elapsed={1}, timeout={2}, status={3}'.format(ctl.getName(), elapsed, timeout, self.__state_to_str_p[ctl.getState()] ))

            time.sleep(0.15)


    def __map_indexes(self, ctl, values):
        result = {}
        for i, c in enumerate(ctl):
            #logger.info('Value name: %s', c.getName())  # useful to find value names
            if c.getName() in values:
                result[c.getName()] = i
        return result


    def __control2dict(self, device, control_name, control_type, transform, control=None):
        def get_dict(element):
            dest = {'name': element.getName(), 'label': element.getLabel()}
            dest.update(transform(element))
            return dest

        control = control if control else self.get_control(device, control_name, control_type)

        return [get_dict(c) for c in control]


