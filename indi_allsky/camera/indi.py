import time
#import math
import io
import tempfile
import ctypes
from datetime import datetime
from dateutil import parser
from pathlib import Path
import logging
#from pprint import pformat

import PyIndi

from .fake_indi import FakeIndiCcd

#from ..flask import db
from ..flask import create_app

#from ..flask.models import TaskQueueQueue
#from ..flask.models import TaskQueueState
#from ..flask.models import IndiAllSkyDbTaskQueueTable

from ..exceptions import TimeOutException
from ..exceptions import CameraException

logger = logging.getLogger('indi_allsky')


app = create_app()


class IndiClient(PyIndi.BaseClient):

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

    __type_to_str = {
        PyIndi.INDI_NUMBER  : 'number',
        PyIndi.INDI_SWITCH  : 'switch',
        PyIndi.INDI_TEXT    : 'text',
        PyIndi.INDI_LIGHT   : 'light',
        PyIndi.INDI_BLOB    : 'blob',
        PyIndi.INDI_UNKNOWN : 'unknown',
    }

    __perm_to_str = {
        PyIndi.IP_RO : 'READ_ONLY',
        PyIndi.IP_WO : 'WRITE_ONLY',
        PyIndi.IP_RW : 'READ_WRITE',
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


    __canon_gain_to_iso = {}  # auto generated
    __canon_iso_to_gain = {}  # auto generated



    def __init__(
        self,
        config,
        image_q,
        position_av,
        gain_v,
        bin_v,
        night_v,
    ):
        super(IndiClient, self).__init__()

        self.config = config
        self.image_q = image_q

        self.position_av = position_av

        self.gain_v = gain_v
        self.bin_v = bin_v

        self.night_v = night_v

        self._camera_id = None

        self._ccd_device = None
        self._ctl_ccd_exposure = None

        self._telescope_device = None
        self._gps_device = None

        self._filename_t = 'ccd{0:d}_{1:s}.{2:s}'

        self._timeout = 10.0
        self._exposure = 0.0

        self.exposureStartTime = None

        self._disconnected = False

        logger.info('creating an instance of IndiClient')

        pyindi_version = '.'.join((
            str(getattr(PyIndi, 'INDI_VERSION_MAJOR', -1)),
            str(getattr(PyIndi, 'INDI_VERSION_MINOR', -1)),
            str(getattr(PyIndi, 'INDI_VERSION_RELEASE', -1)),
        ))
        logger.info('PyIndi version: %s', pyindi_version)


    @property
    def disconnected(self):
        return self._disconnected

    @disconnected.setter
    def disconnected(self, new_disconnected):
        self._disconnected = bool(new_disconnected)


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
        self._filename_t = str(new_filename_t)


    @property
    def libcamera_bit_depth(self):
        # Not needed here
        return None

    @libcamera_bit_depth.setter
    def libcamera_bit_depth(self, new_libcamera_bit_depth):
        # Not needed here
        pass


    def updateConfig(self, new_config):
        self.config = new_config


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
        from astropy.io import fits

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
            'exposure'    : self.exposure,
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

        self.disconnected = False

    def serverDisconnected(self, code):
        logger.info("Server disconnected (exit code = %d, %s, %d", code, str(self.getHost()), self.getPort())

        self.disconnected = True


    def parkTelescope(self):
        if not self.telescope_device:
            return

        logger.info('Parking telescope')

        park_config = {
            'SWITCHES' : {
                'TELESCOPE_PARK' : {
                    'on'  : ['PARK'],
                    'off' : ['UNPARK'],
                },
            }
        }

        self.configureTelescopeDevice(park_config)


    def unparkTelescope(self):
        if not self.telescope_device:
            return

        logger.info('Unparking telescope')

        unpark_config = {
            'SWITCHES' : {
                'TELESCOPE_PARK' : {
                    'on'   : ['UNPARK'],
                    'off'  : ['PARK'],
                },
            }
        }

        self.configureTelescopeDevice(unpark_config)


    def setTelescopeParkPosition(self, ra, dec):
        if not self.telescope_device:
            return

        logger.info('Setting telescope park position to RA %0.2f, Dec %0.2f', ra, dec)

        park_pos = {
            'PROPERTIES' : {
                'TELESCOPE_PARK_POSITION' : {
                    'PARK_HA'  : float(ra),
                    'PARK_DEC' : float(dec),
                },
            },
        }


        self.configureTelescopeDevice(park_pos)


    def updateCcdBlobMode(self, blobmode=PyIndi.B_ALSO, prop=None):
        logger.info('Set BLOB mode')
        self.setBLOBMode(blobmode, self.ccd_device.getDeviceName(), prop)

        # FastBlobs?
        #self.enableDirectBlobAccess(self.ccd_device.getDeviceName(), prop)


    def disableDebug(self, ccd_device):
        debug_config = {
            "SWITCHES" : {
                "DEBUG" : {
                    "on"  : ["DISABLE"],
                    "off" : ["ENABLE"],
                },
            }
        }

        self.configureDevice(ccd_device, debug_config)


    def disableDebugCcd(self):
        self.disableDebug(self.ccd_device)


    def saveCcdConfig(self):
        save_config = {
            "SWITCHES" : {
                "CONFIG_PROCESS" : {
                    "on"  : ['CONFIG_SAVE'],
                }
            }
        }

        self.configureDevice(self.ccd_device, save_config)


    def resetCcdFrame(self):
        reset_config = {
            "SWITCHES" : {
                "CCD_FRAME_RESET" : {
                    "on"  : ['RESET'],
                }
            }
        }

        self.configureDevice(self.ccd_device, reset_config)


    def setCcdFrameType(self, frame_type):
        frame_config = {
            "SWITCHES" : {
                "CCD_FRAME_TYPE" : {
                    "on"  : [frame_type],
                }
            }
        }

        self.configureDevice(self.ccd_device, frame_config)


    def setCcdScopeInfo(self, focal_length, focal_ratio):
        aperture = focal_length / focal_ratio

        scope_info_config = {
            "PROPERTIES" : {
                "SCOPE_INFO" : {
                    "FOCAL_LENGTH" : round(focal_length, 2),
                    "APERTURE" : round(aperture, 2),
                }
            }
        }

        self.configureDevice(self.ccd_device, scope_info_config)


    def getDeviceProperties(self, device):
        properties = dict()

        ### Causing a segfault as of 8/25/22
        #for p in device.getProperties():
        #    name = p.getName()
        #    properties[name] = dict()

        #    if p.getType() == PyIndi.INDI_TEXT:
        #        for t in p.getText():
        #            properties[name][t.getName()] = t.getText()
        #    elif p.getType() == PyIndi.INDI_NUMBER:
        #        for t in p.getNumber():
        #            properties[name][t.getName()] = t.getValue()
        #    elif p.getType() == PyIndi.INDI_SWITCH:
        #        for t in p.getSwitch():
        #            properties[name][t.getName()] = self.__state_to_str_s[t.getState()]
        #    elif p.getType() == PyIndi.INDI_LIGHT:
        #        for t in p.getLight():
        #            properties[name][t.getName()] = self.__state_to_str_p[t.getState()]
        #    elif p.getType() == PyIndi.INDI_BLOB:
        #        pass
        #        #for t in p.getBLOB():
        #        #    logger.info("       %s(%s) = %d bytes", t.name, t.label, t.size)

        #logger.warning('%s', pformat(properties))

        return properties


    def getCcdDeviceProperties(self):
        return self.getDeviceProperties(self.ccd_device)


    def getCcdInfo(self):
        ccdinfo = dict()

        ctl_CCD_EXPOSURE = self.get_control(self.ccd_device, 'CCD_EXPOSURE', 'number')
        ccdinfo['CCD_EXPOSURE'] = dict()
        for i in ctl_CCD_EXPOSURE:
            ccdinfo['CCD_EXPOSURE'][i.getName()] = {
                'current' : i.getValue(),
                'min'     : i.min,
                'max'     : i.max,
                'step'    : i.step,
                'format'  : i.format,
            }


        ctl_CCD_INFO = self.get_control(self.ccd_device, 'CCD_INFO', 'number')

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
            ctl_CCD_CFA = self.get_control(self.ccd_device, 'CCD_CFA', 'text', timeout=3.0)

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


        ctl_CCD_FRAME = self.get_control(self.ccd_device, 'CCD_FRAME', 'number')

        ccdinfo['CCD_FRAME'] = dict()
        for i in ctl_CCD_FRAME:
            ccdinfo['CCD_FRAME'][i.getName()] = {
                'current' : i.getValue(),
                'min'     : i.min,
                'max'     : i.max,
                'step'    : i.step,
                'format'  : i.format,
            }


        ctl_CCD_FRAME_TYPE = self.get_control(self.ccd_device, 'CCD_FRAME_TYPE', 'switch')
        ccdinfo['CCD_FRAME_TYPE'] = dict()

        for i in ctl_CCD_FRAME_TYPE:
            ccdinfo['CCD_FRAME_TYPE'][i.getName()] = i.getState()


        gain_info = self.getCcdGain()
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


    def _findCcds(self):
        logger.info('Searching for available cameras')

        ccd_list = list()

        for device in self.getDevices():
            #logger.info('Found device %s', device.getDeviceName())
            device_interfaces = self.findDeviceInterfaces(device)

            for k, v in self.__indi_interfaces.items():
                if device_interfaces & k:
                    if k == PyIndi.BaseDevice.CCD_INTERFACE:
                        logger.info(' Detected %s', device.getDeviceName())
                        ccd_list.append(device)

        return ccd_list


    def findCcd(self, camera_name=None):
        ccd_list = self._findCcds()

        logger.info('Found %d CCDs', len(ccd_list))

        if camera_name:
            for ccd in ccd_list:
                if ccd.getDeviceName().lower() == camera_name.lower():
                    self.ccd_device = ccd
                    return ccd
            else:
                raise CameraException('Camera not found: {0:s}'.format(camera_name))


        # if no camera name is passed, just return the first found
        try:
            # set default device in indiclient
            self.ccd_device = ccd_list[0]
        except IndexError:
            raise CameraException('No cameras found')

        return self.ccd_device


    def _findTelescopes(self):
        logger.info('Searching for available telescopes/mounts')

        telescope_list = list()

        for device in self.getDevices():
            #logger.info('Found device %s', device.getDeviceName())
            device_interfaces = self.findDeviceInterfaces(device)

            for k, v in self.__indi_interfaces.items():
                if device_interfaces & k:
                    if k == PyIndi.BaseDevice.TELESCOPE_INTERFACE:
                        logger.info(' Detected %s', device.getDeviceName())
                        telescope_list.append(device)

        return telescope_list


    def findTelescope(self, telescope_name='Telescope Simulator'):
        telescope_list = self._findTelescopes()

        logger.info('Found %d Telescopess', len(telescope_list))

        for t in telescope_list:
            if t.getDeviceName().lower() == telescope_name.lower():
                self.telescope_device = t
                break
        else:
            logger.error('No telescopes found')

        return self.telescope_device


    def _findGpss(self):
        logger.info('Searching for available GPS interfaces')

        gps_list = list()

        for device in self.getDevices():
            #logger.info('Found device %s', device.getDeviceName())
            device_interfaces = self.findDeviceInterfaces(device)

            for k, v in self.__indi_interfaces.items():
                if device_interfaces & k:
                    if k == PyIndi.BaseDevice.GPS_INTERFACE:
                        logger.info(' Detected %s', device.getDeviceName())
                        gps_list.append(device)

        return gps_list


    def findGps(self, gps_name=None):
        gps_list = self._findGpss()

        logger.info('Found %d GPSs', len(gps_list))

        if gps_name:
            for gps in gps_list:
                if gps.getDeviceName().lower() == gps_name.lower():
                    self.gps_device = gps
                    return gps
            else:
                raise CameraException('GPS not found: {0:s}'.format(gps_name))


        # if no gps name is passed, just return the first found
        try:
            # set default device in indiclient
            self.gps_device = gps_list[0]
        except IndexError:
            pass

        return self.gps_device


    def configureDevice(self, device, indi_config, sleep=1.0):
        if isinstance(device, FakeIndiCcd):
            # ignore configuration
            return

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
        time.sleep(sleep)


    def configureCcdDevice(self, *args, **kwargs):
        self.configureDevice(self.ccd_device, *args, **kwargs)


    def configureTelescopeDevice(self, *args, **kwargs):
        if not self.telescope_device:
            logger.warning('No telescope to configure')
            return

        self.configureDevice(self.telescope_device, *args, **kwargs)


    def setTelescopeGps(self, gps_name):
        gps_config = {
            'TEXT' : {
                'ACTIVE_DEVICES' : {
                    'ACTIVE_GPS' : gps_name,
                },
            },
        }

        self.configureTelescopeDevice(gps_config)


    def configureGpsDevice(self, *args, **kwargs):
        if not self.gps_device:
            logger.warning('No GPS to configure')
            return

        self.configureDevice(self.gps_device, *args, **kwargs)


    def refreshGps(self):
        if not self.gps_device:
            return

        refresh_config = {
            'SWITCHES' : {
                'GPS_REFRESH' : {
                    'on' : ['REFRESH'],
                },
            },
        }

        self.configureGpsDevice(refresh_config)


    def getGpsPosition(self):
        if not self.gps_device:
            return self.position_av[0:3]

        try:
            geographic_coord = self.get_control(self.gps_device, 'GEOGRAPHIC_COORD', 'number', timeout=0.5)
        except TimeOutException:
            return self.position_av[0:3]

        gps_lat = float(geographic_coord[0].getValue())   # LAT
        gps_long = float(geographic_coord[1].getValue())  # LONG
        gps_elev = int(geographic_coord[2].getValue())    # ELEV

        if not gps_lat and not gps_long:
            logger.warning('GPS fix not found')
            return self.position_av[0:3]

        if gps_long > 180.0:
            # put longitude in range of -180 to 180
            gps_long = gps_long - 360.0

        logger.info("GPS location: lat %0.2f, long %0.2f, elev %dm", gps_lat, gps_long, gps_elev)

        return gps_lat, gps_long, gps_elev


    def getGpsTime(self):
        if not self.gps_device:
            return None, None

        try:
            time_utc = self.get_control(self.gps_device, 'TIME_UTC', 'text', timeout=0.5)
        except TimeOutException:
            return None, None

        gps_utc = str(time_utc[0].getText())   # UTC
        gps_offset = str(time_utc[1].getText())  # OFFSET


        if not gps_utc:
            logger.warning('GPS fix not found')
            return None, None

        if not gps_offset:
            logger.error('GPS time offset not defined')


        # example string: 2022-12-11T14:00:50.000Z
        try:
            gps_utc_dt = parser.isoparse(gps_utc)
        except ValueError:
            logger.error('Unable to parse GPS time: %s', gps_utc)
            gps_utc_dt = None

        try:
            gps_offset_f = float(gps_offset)
        except ValueError:
            logger.error('Unknown GPS time offset: %s', gps_offset)
            gps_offset_f = None


        logger.info('GPS time (utc): %s, local offset: %s', str(gps_utc_dt), str(gps_offset_f))

        return gps_utc_dt, gps_offset_f


    def getTelescopeRaDec(self):
        if not self.telescope_device:
            return self.ra_v.value, self.dec_v.value

        try:
            equatorial_eod_coord = self.get_control(self.telescope_device, 'EQUATORIAL_EOD_COORD', 'number', timeout=0.5)
        except TimeOutException:
            return self.ra_v.value, self.dec_v.value

        ra = float(equatorial_eod_coord[0].getValue())   # RA
        dec = float(equatorial_eod_coord[1].getValue())  # DEC

        #logger.info("Telescope Coord: RA %0.2f, Dec %0.2f", ra, dec)

        return ra, dec


    def getCcdTemperature(self):

        try:
            ccd_temperature = self.get_control(self.ccd_device, 'CCD_TEMPERATURE', 'number', timeout=0.2)
        except TimeOutException:
            logger.warning("Camera temperature not supported")
            return -273.15  # absolute zero  :-)


        temp_val = float(ccd_temperature[0].getValue())  # CCD_TEMPERATURE_VALUE
        logger.info("Camera temperature: %0.1f", temp_val)

        return temp_val


    def enableCcdCooler(self):
        logger.warning('Enabling CCD cooling')

        try:
            ccd_cooler = self.get_control(self.ccd_device, 'CCD_COOLER', 'switch', timeout=2.0)
        except TimeOutException:
            logger.warning("Cooling not supported")
            return False


        if ccd_cooler.getPermission() == PyIndi.IP_RO:
            logger.warning("Cooling control is read only")
            return False


        ccd_cooler[0].setState(PyIndi.ISS_ON)   # COOLER_ON
        ccd_cooler[1].setState(PyIndi.ISS_OFF)  # COOLER_OFF

        self.sendNewSwitch(ccd_cooler)


    def disableCcdCooler(self):
        logger.warning('Disabling CCD cooling')

        try:
            ccd_cooler = self.get_control(self.ccd_device, 'CCD_COOLER', 'switch', timeout=2.0)
        except TimeOutException:
            logger.warning("Cooling not supported")
            return False


        if ccd_cooler.getPermission() == PyIndi.IP_RO:
            logger.warning("Cooling control is read only")
            return False


        ccd_cooler[0].setState(PyIndi.ISS_OFF)  # COOLER_ON
        ccd_cooler[1].setState(PyIndi.ISS_ON)   # COOLER_OFF

        self.sendNewSwitch(ccd_cooler)


    def setCcdTemperature(self, temp_val, sync=False, timeout=None):
        logger.info('Setting CCD temperature to %0.2f', temp_val)

        if temp_val < -50:
            logger.error('Temperature value too low')
            return False


        try:
            ccd_temperature = self.get_control(self.ccd_device, 'CCD_TEMPERATURE', 'number', timeout=2.0)
        except TimeOutException:
            logger.warning("Sensor temperature not supported")
            return False


        if ccd_temperature.getPermission() == PyIndi.IP_RO:
            logger.warning("Temperature control is read only")
            return False


        # this needs to be done asynchronously most of the time
        self.set_number(self.ccd_device, 'CCD_TEMPERATURE', {'CCD_TEMPERATURE_VALUE': float(temp_val)}, sync=sync, timeout=timeout)

        return temp_val


    def setCcdExposure(self, exposure, sync=False, timeout=None):
        if not timeout:
            timeout = self.timeout

        self.exposure = exposure


        self.exposureStartTime = time.time()

        ctl_ccd_exposure = self.set_number(self.ccd_device, 'CCD_EXPOSURE', {'CCD_EXPOSURE_VALUE': exposure}, sync=sync, timeout=timeout)

        self._ctl_ccd_exposure = ctl_ccd_exposure


    def getCcdExposureStatus(self):
        camera_ready, exposure_state = self.ctl_ready(self._ctl_ccd_exposure)

        return camera_ready, exposure_state


    def abortCcdExposure(self):
        logger.warning('Aborting exposure')

        try:
            ccd_abort = self.get_control(self.ccd_device, 'CCD_ABORT_EXPOSURE', 'switch', timeout=2.0)
        except TimeOutException:
            logger.warning("Abort not supported")
            return


        if ccd_abort.getPermission() == PyIndi.IP_RO:
            logger.warning("Abort control is read only")
            return


        ccd_abort[0].setState(PyIndi.ISS_ON)   # ABORT

        self.sendNewSwitch(ccd_abort)


    def getCcdGain(self):
        indi_exec = self.ccd_device.getDriverExec()


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
            gain_ctl = self.get_control(self.ccd_device, 'CCD_CONTROLS', 'number')
            gain_index_dict = self.__map_indexes(gain_ctl, ['Gain'])
            index = gain_index_dict['Gain']
        elif indi_exec in [
            'indi_qhy_ccd',
            'indi_simulator_ccd',
            'indi_rpicam',
            'indi_libcamera_ccd',
        ]:
            gain_ctl = self.get_control(self.ccd_device, 'CCD_GAIN', 'number')
            gain_index_dict = self.__map_indexes(gain_ctl, ['GAIN'])
            index = gain_index_dict['GAIN']
        elif indi_exec in [
            'indi_svbony_ccd',
            'indi_sv305_ccd',  # legacy name
        ]:
            # the GAIN property changed in INDI 2.0.4
            try:
                gain_ctl = self.get_control(self.ccd_device, 'CCD_CONTROLS', 'number', timeout=2.0)
                gain_index_dict = self.__map_indexes(gain_ctl, ['Gain'])
                index = gain_index_dict['Gain']
            except TimeOutException:
                # use the old property
                gain_ctl = self.get_control(self.ccd_device, 'CCD_GAIN', 'number', timeout=2.0)
                gain_index_dict = self.__map_indexes(gain_ctl, ['GAIN'])
                index = gain_index_dict['GAIN']
        elif indi_exec in ['indi_sx_ccd']:
            logger.warning('indi_sx_ccd does not support gain settings')
            return fake_gain_info
        elif indi_exec in [
            'indi_gphoto_ccd',
            'indi_canon_ccd',
            'indi_nikon_ccd',
            'indi_pentax_ccd',
            'indin_sony_ccd',
        ]:
            gain_ctl = self.get_control(self.ccd_device, 'CCD_ISO', 'switch')


            gain_list = list()
            for index in range(0, len(gain_ctl)):  # avoid using iterator
                try:
                    # The label should be the ISO number in string format
                    gain_str = gain_ctl[index].getLabel()
                    gain = int(gain_str)
                except ValueError:
                    # skip values like "auto"
                    logger.warning('Skipping ISO setting "%s"', gain_str)
                    continue


                gain_list.append(gain)

                # populate translation dicts
                self.__canon_gain_to_iso[gain] = gain_ctl[index].getName()
                self.__canon_iso_to_gain[gain_ctl[index].getName()] = gain


            try:
                gain_info = {
                    'current' : 0,  # this should not matter
                    'min'     : min(gain_list),
                    'max'     : max(gain_list),
                    'step'    : None,
                    'format'  : '',
                }
            except ValueError:
                raise Exception('No available ISO/gain settings for camera.  Make sure your camera is set to Manual/Bulb mode.')

            return gain_info
        elif indi_exec in ['indi_webcam_ccd']:
            logger.warning('indi_webcam_ccd does not support gain settings')
            return fake_gain_info
        elif indi_exec in ['indi_v4l2_ccd']:
            try:
                gain_ctl = self.get_control(self.ccd_device, 'Image Adjustments', 'number', timeout=2.0)
            except TimeOutException:
                logger.warning('Timeout: indi_v4l2_ccd does not support gain settings')
                return fake_gain_info

            gain_index_dict = self.__map_indexes(gain_ctl, ['Gain'])
            index = gain_index_dict['Gain']
        elif indi_exec in ['rpicam-still', 'libcamera-still', 'indi_fake_ccd']:
            return self.ccd_device.getCcdGain()
        elif 'indi_pylibcamera' in indi_exec:  # SPECIAL CASE
            # the exec name can have many variations
            gain_ctl = self.get_control(self.ccd_device, 'CCD_GAIN', 'number')
            gain_index_dict = self.__map_indexes(gain_ctl, ['GAIN'])
            index = gain_index_dict['GAIN']

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
        logger.warning('Setting CCD gain to %s', str(gain_value))
        indi_exec = self.ccd_device.getDriverExec()

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
            'indi_qhy_ccd',
            'indi_simulator_ccd',
            'indi_rpicam',
            'indi_libcamera_ccd',
        ]:
            gain_config = {
                "PROPERTIES" : {
                    "CCD_GAIN" : {
                        "GAIN" : gain_value,
                    },
                },
            }
        elif indi_exec in [
            'indi_svbony_ccd',
            'indi_sv305_ccd',  # legacy name
        ]:
            # the GAIN property changed in INDI 2.0.4
            try:
                self.get_control(self.ccd_device, 'CCD_CONTROLS', 'number', timeout=2.0)

                gain_config = {
                    "PROPERTIES" : {
                        "CCD_CONTROLS" : {
                            "Gain" : gain_value,
                        },
                    },
                }
            except TimeOutException:
                # use the old property
                gain_config = {
                    "PROPERTIES" : {
                        "CCD_GAIN" : {
                            "GAIN" : gain_value,
                        },
                    },
                }
        elif indi_exec in [
            'indi_gphoto_ccd',
            'indi_canon_ccd',
            'indi_nikon_ccd',
            'indi_pentax_ccd',
            'indi_sony_ccd',
        ]:
            logger.info('Mapping gain to ISO for libgphoto device')

            try:
                gain_switch = self.__canon_gain_to_iso[gain_value]
                logger.info('Setting ISO switch: %s', gain_switch)
            except KeyError:
                logger.error('Canon ISO not found for %s, using ISO 100', str(gain_value))
                gain_switch = 'ISO1'

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
            try:
                self.get_control(self.ccd_device, 'Image Adjustments', 'number', timeout=2.0)

                gain_config = {
                    "PROPERTIES" : {
                        "Image Adjustments" : {
                            "Gain" : gain_value,
                        },
                    },
                }
            except TimeOutException:
                logger.warning('Timeout: indi_v4l2_ccd does not support gain settings')
                gain_config = {}
        elif indi_exec in ['rpicam-still', 'libcamera-still', 'indi_fake_ccd']:
            return self.ccd_device.setCcdGain(gain_value)
        elif 'indi_pylibcamera' in indi_exec:  # SPECIAL CASE
            # the exec name can have many variations
            gain_config = {
                "PROPERTIES" : {
                    "CCD_GAIN" : {
                        "GAIN" : gain_value,
                    },
                },
            }
        else:
            raise Exception('Gain config not implemented for {0:s}, open an enhancement request'.format(indi_exec))


        self.configureDevice(self.ccd_device, gain_config)


        # Update shared gain value
        with self.gain_v.get_lock():
            self.gain_v.value = int(gain_value)


    def setCcdBinning(self, bin_value):
        if type(bin_value) is int:
            bin_value = [bin_value, bin_value]
        elif type(bin_value) is str:
            bin_value = [int(bin_value), int(bin_value)]
        elif not bin_value:
            # Assume default
            return

        logger.warning('Setting CCD binning to (%d, %d)', bin_value[0], bin_value[1])

        indi_exec = self.ccd_device.getDriverExec()

        if indi_exec in [
            'indi_asi_ccd',
            'indi_asi_single_ccd',
            'indi_svbony_ccd',
            'indi_sv305_ccd',  # legacy name
            'indi_qhy_ccd',
            'indi_toupcam_ccd',
            'indi_altair_ccd',
            'indi_simulator_ccd',
            'indi_rpicam',
            'indi_libcamera_ccd',
            'indi_playerone_ccd',
            'indi_sx_ccd',
            'indi_v4l2_ccd',
        ]:
            binning_config = {
                "PROPERTIES" : {
                    "CCD_BINNING" : {
                        "HOR_BIN" : bin_value[0],
                        "VER_BIN" : bin_value[1],
                    },
                },
            }
        elif indi_exec in [
            'indi_gphoto_ccd',
            'indi_canon_ccd',
            'indi_nikon_ccd',
            'indi_pentax_ccd',
            'indi_sony_ccd',
        ]:
            logger.warning('indi_gphoto_ccd does not support bin settings')
            return
        elif indi_exec in ['indi_webcam_ccd']:
            logger.warning('indi_webcam_ccd does not support bin settings')
            return
        elif indi_exec in ['rpicam-still', 'libcamera-still', 'indi_fake_ccd']:
            return self.ccd_device.setCcdBinMode(bin_value)
        elif 'indi_pylibcamera' in indi_exec:  # SPECIAL CASE
            # the exec name can have many variations
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

        self.configureDevice(self.ccd_device, binning_config)

        # Update shared gain value
        with self.bin_v.get_lock():
            self.bin_v.value = bin_value[0]


    # Most of below was borrowed from https://github.com/GuLinux/indi-lite-tools/blob/master/pyindi_sequence/device.py


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


    def set_text(self, device, name, values, sync=True, timeout=None):
        c = self.get_control(device, name, 'text')

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
            timeout = self.timeout

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


