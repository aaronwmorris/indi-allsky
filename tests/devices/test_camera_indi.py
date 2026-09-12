import io
import time
from datetime import datetime
from pathlib import Path
from multiprocessing import Queue, Array, Value
from unittest.mock import MagicMock, patch
import pytest
from astropy.io import fits
import PyIndi

from indi_allsky.camera.indi import IndiClient
from indi_allsky.camera.fake_indi import FakeIndiCcd
from indi_allsky.exceptions import CameraException, TimeOutException


class MockIndiElement:
    def __init__(self, name, label='', value=0, text='', state=PyIndi.ISS_OFF, min_val=0, max_val=100, step=1, fmt='%f'):
        self._name = name
        self._label = label or name
        self._value = value
        self._text = text
        self._state = state
        self.min = min_val
        self.max = max_val
        self.step = step
        self.format = fmt

    def getName(self):
        return self._name

    def getLabel(self):
        return self._label

    def getValue(self):
        return self._value

    def setValue(self, v):
        self._value = v

    def getText(self):
        return self._text

    def setText(self, t):
        self._text = t

    def getState(self):
        return self._state

    def setState(self, s):
        self._state = s


class MockIndiVector(list):
    def __init__(self, elements, name='VECTOR', device_name='DEVICE', perm=PyIndi.IP_RW, rule=PyIndi.ISR_1OFMANY, state=PyIndi.IPS_OK):
        super().__init__(elements)
        self._name = name
        self._device_name = device_name
        self._perm = perm
        self._rule = rule
        self._state = state

    def getName(self):
        return self._name

    def getDeviceName(self):
        return self._device_name

    def getPermission(self):
        return self._perm

    def getRule(self):
        return self._rule

    def getState(self):
        return self._state


class MockIndiDevice:
    def __init__(self, name='TestCCD', exec_name='indi_asi_ccd', interfaces=PyIndi.BaseDevice.CCD_INTERFACE):
        self._name = name
        self._exec = exec_name
        self._interfaces = interfaces
        self.controls = {}

    def getDeviceName(self):
        return self._name

    def getDriverExec(self):
        return self._exec

    def getDriverInterface(self):
        return self._interfaces

    def add_control(self, name, ctl_type, vector):
        self.controls[(name, ctl_type)] = vector

    def getNumber(self, name):
        return self.controls.get((name, 'number'))

    def getSwitch(self, name):
        return self.controls.get((name, 'switch'))

    def getText(self, name):
        return self.controls.get((name, 'text'))

    def getLight(self, name):
        return self.controls.get((name, 'light'))

    def getBLOB(self, name):
        return self.controls.get((name, 'blob'))


def create_mock_fits_blob(shape=(10, 10), data_val=10):
    import numpy as np
    data = np.full(shape, data_val, dtype=np.uint16)
    hdu = fits.PrimaryHDU(data)
    buf = io.BytesIO()
    hdu.writeto(buf)
    mock_blob = MagicMock()
    mock_blob.getblobdata.return_value = buf.getvalue()
    mock_blob.getName.return_value = 'CCD1'
    mock_blob.getDeviceName.return_value = 'TestCCD'
    return mock_blob


@pytest.fixture
def indi_client(flask_app):
    config = {}
    image_q = Queue()
    position_av = Array('d', [0.0] * 5)
    exposure_av = Array('i', [1000000] * 7)
    gain_av = Array('i', [100000] * 10)
    binning_av = Array('i', [1] * 6)
    night_av = Array('i', [1, 0])

    with patch.object(PyIndi.BaseClient, 'sendNewNumber'), \
         patch.object(PyIndi.BaseClient, 'sendNewSwitch'), \
         patch.object(PyIndi.BaseClient, 'sendNewText'), \
         patch.object(PyIndi.BaseClient, 'setBLOBMode'), \
         patch.object(PyIndi.BaseClient, 'getHost', return_value='localhost'), \
         patch.object(PyIndi.BaseClient, 'getPort', return_value=7624):

        client = IndiClient(
            config,
            image_q,
            position_av,
            exposure_av,
            gain_av,
            binning_av,
            night_av,
        )
        yield client


def test_indi_properties(indi_client):
    indi_client.disconnected = True
    assert indi_client.disconnected is True

    indi_client.ccd_removed = True
    assert indi_client.ccd_removed is True

    indi_client.camera_id = 3
    assert indi_client.camera_id == 3

    dev = MockIndiDevice()
    indi_client.ccd_device = dev
    assert indi_client.ccd_device == dev

    tel = MockIndiDevice('Tel', interfaces=PyIndi.BaseDevice.TELESCOPE_INTERFACE)
    indi_client.telescope_device = tel
    assert indi_client.telescope_device == tel

    gps = MockIndiDevice('GPS', interfaces=PyIndi.BaseDevice.GPS_INTERFACE)
    indi_client.gps_device = gps
    assert indi_client.gps_device == gps

    indi_client.timeout = 15.0
    assert indi_client.timeout == 15.0

    indi_client.sqm_exposure = True
    assert indi_client.sqm_exposure is True

    indi_client.exposure = 2.5
    assert indi_client.exposure == 2.5

    indi_client.gain = 100.0
    assert indi_client.gain == 100.0

    indi_client.binning = 2
    assert indi_client.binning == 2

    indi_client.filename_t = 'test_{0}.fit'
    assert indi_client.filename_t == 'test_{0}.fit'

    assert indi_client.libcamera_bit_depth is None
    indi_client.libcamera_bit_depth = 12

    indi_client.ccd_temp = -10.5
    assert indi_client.ccd_temp == -10.5

    indi_client.updateConfig({'NEW': 1})
    assert indi_client.config == {'NEW': 1}


def test_indi_device_and_property_callbacks(indi_client):
    dev = MockIndiDevice('TestCCD')
    indi_client.ccd_device = dev

    indi_client.newDevice(dev)
    indi_client.removeDevice(MockIndiDevice('OtherDev'))
    assert indi_client.ccd_removed is False

    indi_client.removeDevice(dev)
    assert indi_client.ccd_removed is True

    indi_client.ccd_device = None
    indi_client.removeDevice(dev)

    p = MagicMock()
    p.getName.return_value = 'PROP'
    p.getDeviceName.return_value = 'TestCCD'
    indi_client.newProperty(p)
    indi_client.removeProperty(p)

    m = MagicMock()
    dev_msg = MagicMock()
    dev_msg.messageQueue.return_value = 'Log message'
    indi_client.newMessage(dev_msg, m)

    indi_client.getHost = MagicMock(return_value='localhost')
    indi_client.getPort = MagicMock(return_value=7624)
    indi_client.serverConnected()
    assert indi_client.disconnected is False

    indi_client.serverDisconnected(0)
    assert indi_client.disconnected is True


def test_indi_new_callbacks_and_blob_processing(indi_client):
    blob = create_mock_fits_blob()
    indi_client.exposure = 1.0
    indi_client.gain = 50.0
    indi_client.binning = 1
    indi_client.sqm_exposure = True
    indi_client.camera_id = 0
    dev = MockIndiDevice('TestCCD')
    indi_client.ccd_device = dev

    indi_client.newBLOB(blob)
    assert indi_client.sqm_exposure is False
    job = indi_client.image_q.get(timeout=1.0)
    assert job['exposure'] == 1.0
    assert job['gain'] == 50.0

    indi_client.newSwitch(MagicMock())
    indi_client.newNumber(MagicMock())
    indi_client.newText(MagicMock())
    indi_client.newLight(MagicMock())


def test_indi_process_blob_oserror(indi_client):
    blob = create_mock_fits_blob()
    indi_client.ccd_device = MockIndiDevice('TestCCD')
    with patch('astropy.io.fits.HDUList.writeto', side_effect=OSError('Write failed')):
        indi_client.processBlob(blob)
        assert indi_client.image_q.empty()


def test_indi_update_property_variants(indi_client):
    # If hasattr BaseMediator newNumber
    with patch.object(PyIndi.BaseMediator, 'newNumber', create=True):
        p = MagicMock()
        indi_client.updateProperty(p)

    # INDI 2.x code path
    indi_client.ccd_device = MockIndiDevice('TestCCD')
    blob_item = create_mock_fits_blob()

    with patch.object(PyIndi, 'PropertyBlob') as mock_prop_blob:
        # 1. Matching CCD blob
        mock_pb = MagicMock()
        mock_pb.getDeviceName.return_value = 'TestCCD'
        mock_pb.__getitem__.return_value = blob_item
        mock_prop_blob.return_value = mock_pb

        p_blob = MagicMock()
        p_blob.getType.return_value = PyIndi.INDI_BLOB
        with patch.object(indi_client, 'processBlob') as mock_proc:
            indi_client.updateProperty(p_blob)
            mock_proc.assert_called_once_with(blob_item)

        # 2. Blob with no ccd_device
        indi_client.ccd_device = None
        with patch.object(indi_client, 'processBlob') as mock_proc:
            indi_client.updateProperty(p_blob)
            mock_proc.assert_not_called()

        # 3. Blob with different device name
        indi_client.ccd_device = MockIndiDevice('ExpectedCCD')
        with patch.object(indi_client, 'processBlob') as mock_proc:
            indi_client.updateProperty(p_blob)
            mock_proc.assert_not_called()

    # Other property types
    for ptype in [PyIndi.INDI_NUMBER, PyIndi.INDI_SWITCH, PyIndi.INDI_TEXT, PyIndi.INDI_LIGHT, 9999]:
        mock_p = MagicMock()
        mock_p.getType.return_value = ptype
        indi_client.updateProperty(mock_p)


def test_indi_telescope_and_gps_methods(indi_client):
    # Without telescope/gps device
    indi_client.telescope_device = None
    indi_client.gps_device = None
    indi_client.parkTelescope()
    indi_client.unparkTelescope()
    indi_client.setTelescopeParkPosition(10, 20)
    indi_client.configureTelescopeDevice({})
    indi_client.configureGpsDevice({})
    indi_client.refreshGps()
    assert indi_client.getGpsTime() == (None, None)

    indi_client.ra_v = Value('d', 1.5)
    indi_client.dec_v = Value('d', 45.0)
    assert indi_client.getTelescopeRaDec() == (1.5, 45.0)
    assert indi_client.getGpsPosition() == list(indi_client.position_av[0:3])

    # With telescope and gps devices
    tel = MockIndiDevice('Telescope Simulator', interfaces=PyIndi.BaseDevice.TELESCOPE_INTERFACE)
    gps = MockIndiDevice('GPS Simulator', interfaces=PyIndi.BaseDevice.GPS_INTERFACE)
    indi_client.telescope_device = tel
    indi_client.gps_device = gps

    with patch.object(indi_client, 'configureTelescopeDevice') as mock_conf_tel:
        indi_client.parkTelescope()
        assert mock_conf_tel.called
        indi_client.unparkTelescope()
        assert mock_conf_tel.called
        indi_client.setTelescopeParkPosition(12.0, 45.0)
        assert mock_conf_tel.called
        indi_client.setTelescopeGps('GPS Simulator')
        assert mock_conf_tel.called

    with patch.object(indi_client, 'configureGpsDevice') as mock_conf_gps:
        indi_client.refreshGps()
        assert mock_conf_gps.called


def test_indi_get_gps_position_variations(indi_client):
    gps = MockIndiDevice('GPS')
    indi_client.gps_device = gps

    # 1. Timeout
    with patch.object(indi_client, 'get_control', side_effect=TimeOutException):
        assert indi_client.getGpsPosition() == list(indi_client.position_av[0:3])

    # 2. Zero lat/long
    vec_zero = MockIndiVector([MockIndiElement('LAT', value=0.0), MockIndiElement('LONG', value=0.0), MockIndiElement('ELEV', value=0.0)])
    with patch.object(indi_client, 'get_control', return_value=vec_zero):
        assert indi_client.getGpsPosition() == list(indi_client.position_av[0:3])

    # 3. Normal with long > 180 (wrap-around)
    vec_valid = MockIndiVector([MockIndiElement('LAT', value=-35.0), MockIndiElement('LONG', value=210.0), MockIndiElement('ELEV', value=150.0)])
    with patch.object(indi_client, 'get_control', return_value=vec_valid):
        lat, lon, elev = indi_client.getGpsPosition()
        assert lat == -35.0
        assert lon == -150.0  # 210 - 360
        assert elev == 150


def test_indi_get_gps_time_variations(indi_client):
    gps = MockIndiDevice('GPS')
    indi_client.gps_device = gps

    # 1. Timeout
    with patch.object(indi_client, 'get_control', side_effect=TimeOutException):
        assert indi_client.getGpsTime() == (None, None)

    # 2. Empty UTC
    vec_empty = MockIndiVector([MockIndiElement('UTC', text=''), MockIndiElement('OFFSET', text='0')])
    with patch.object(indi_client, 'get_control', return_value=vec_empty):
        assert indi_client.getGpsTime() == (None, None)

    # 3. Invalid date / offset
    vec_bad = MockIndiVector([MockIndiElement('UTC', text='bad_date'), MockIndiElement('OFFSET', text='bad_offset')])
    with patch.object(indi_client, 'get_control', return_value=vec_bad):
        dt, offset = indi_client.getGpsTime()
        assert dt is None
        assert offset is None

    # 4. Valid ISO date and offset
    vec_good = MockIndiVector([MockIndiElement('UTC', text='2026-09-13T01:00:00Z'), MockIndiElement('OFFSET', text='9.5')])
    with patch.object(indi_client, 'get_control', return_value=vec_good):
        dt, offset = indi_client.getGpsTime()
        assert dt == datetime.fromisoformat('2026-09-13T01:00:00+00:00')
        assert offset == 9.5


def test_indi_get_telescope_radec(indi_client):
    tel = MockIndiDevice('Tel')
    indi_client.telescope_device = tel
    indi_client.ra_v = Value('d', 5.0)
    indi_client.dec_v = Value('d', -20.0)

    # Timeout
    with patch.object(indi_client, 'get_control', side_effect=TimeOutException):
        assert indi_client.getTelescopeRaDec() == (5.0, -20.0)

    # Valid
    vec = MockIndiVector([MockIndiElement('RA', value=18.5), MockIndiElement('DEC', value=60.0)])
    with patch.object(indi_client, 'get_control', return_value=vec):
        assert indi_client.getTelescopeRaDec() == (18.5, 60.0)


def test_indi_cooler_and_temperature_controls(indi_client):
    dev = MockIndiDevice('CCD')
    indi_client.ccd_device = dev

    # getCcdTemperature: Timeout vs valid
    with patch.object(indi_client, 'get_control', side_effect=TimeOutException):
        assert indi_client.getCcdTemperature() == -273.15

    vec_temp = MockIndiVector([MockIndiElement('CCD_TEMPERATURE_VALUE', value=-5.5)])
    with patch.object(indi_client, 'get_control', return_value=vec_temp):
        assert indi_client.getCcdTemperature() == -5.5

    # enableCcdCooler: Timeout, IP_RO, Success
    with patch.object(indi_client, 'get_control', side_effect=TimeOutException):
        assert indi_client.enableCcdCooler() is False

    vec_cooler_ro = MockIndiVector([MockIndiElement('ON'), MockIndiElement('OFF')], perm=PyIndi.IP_RO)
    with patch.object(indi_client, 'get_control', return_value=vec_cooler_ro):
        assert indi_client.enableCcdCooler() is False

    vec_cooler_rw = MockIndiVector([MockIndiElement('ON'), MockIndiElement('OFF')], perm=PyIndi.IP_RW)
    with patch.object(indi_client, 'get_control', return_value=vec_cooler_rw):
        indi_client.enableCcdCooler()
        assert vec_cooler_rw[0].getState() == PyIndi.ISS_ON
        assert vec_cooler_rw[1].getState() == PyIndi.ISS_OFF

    # disableCcdCooler: Timeout, IP_RO, Success
    with patch.object(indi_client, 'get_control', side_effect=TimeOutException):
        assert indi_client.disableCcdCooler() is False

    with patch.object(indi_client, 'get_control', return_value=vec_cooler_ro):
        assert indi_client.disableCcdCooler() is False

    with patch.object(indi_client, 'get_control', return_value=vec_cooler_rw):
        indi_client.disableCcdCooler()
        assert vec_cooler_rw[0].getState() == PyIndi.ISS_OFF
        assert vec_cooler_rw[1].getState() == PyIndi.ISS_ON

    # setCcdTemperature
    assert indi_client.setCcdTemperature(-60.0) is False

    with patch.object(indi_client, 'get_control', side_effect=TimeOutException):
        assert indi_client.setCcdTemperature(-20.0) is False

    with patch.object(indi_client, 'get_control', return_value=MockIndiVector([], perm=PyIndi.IP_RO)):
        assert indi_client.setCcdTemperature(-20.0) is False

    with patch.object(indi_client, 'get_control', return_value=MockIndiVector([], perm=PyIndi.IP_RW)), \
         patch.object(indi_client, 'set_number') as mock_set_num:
        assert indi_client.setCcdTemperature(-15.0) == -15.0
        mock_set_num.assert_called_once()


def test_indi_exposure_and_abort(indi_client):
    dev = MockIndiDevice('CCD')
    indi_client.ccd_device = dev
    indi_client.gain = 10.0
    indi_client.binning = 1

    with patch.object(indi_client, 'set_number') as mock_set_num, \
         patch.object(indi_client, 'setCcdGain') as mock_gain, \
         patch.object(indi_client, 'setCcdBinning') as mock_bin:
        indi_client.setCcdExposure(5.0, 20.0, 2, sync=False)
        mock_gain.assert_called_once_with(20.0)
        mock_bin.assert_called_once_with(2)
        mock_set_num.assert_called_once()

    with patch.object(indi_client, 'ctl_ready', return_value=(True, 'OK')):
        assert indi_client.getCcdExposureStatus() == (True, 'OK')

    # abortCcdExposure: Timeout, IP_RO, Success
    with patch.object(indi_client, 'get_control', side_effect=TimeOutException):
        indi_client.abortCcdExposure()

    vec_abort_ro = MockIndiVector([MockIndiElement('ABORT')], perm=PyIndi.IP_RO)
    with patch.object(indi_client, 'get_control', return_value=vec_abort_ro):
        indi_client.abortCcdExposure()

    vec_abort_rw = MockIndiVector([MockIndiElement('ABORT')], perm=PyIndi.IP_RW)
    with patch.object(indi_client, 'get_control', return_value=vec_abort_rw):
        indi_client.abortCcdExposure()
        assert vec_abort_rw[0].getState() == PyIndi.ISS_ON
        assert indi_client.sendNewSwitch.called


def test_indi_configure_device_methods(indi_client):
    # FakeIndiCcd device is ignored
    fake_ccd = FakeIndiCcd()
    assert indi_client.configureDevice(fake_ccd, {}) is None

    # Normal device
    dev = MockIndiDevice('CCD')
    indi_client.ccd_device = dev
    config = {
        'SWITCHES': {'SW': {'on': ['ON'], 'off': ['OFF']}},
        'PROPERTIES': {'NUM': {'VAL': 10}},
        'TEXT': {'TXT': {'KEY': 'VAL'}},
    }
    with patch.object(indi_client, 'set_switch') as mock_sw, \
         patch.object(indi_client, 'set_number') as mock_num, \
         patch.object(indi_client, 'set_text') as mock_txt:
        indi_client.configureDevice(dev, config, sleep=0.0)
        mock_sw.assert_called_once()
        mock_num.assert_called_once()
        mock_txt.assert_called_once()

    with patch.object(indi_client, 'configureDevice') as mock_conf:
        indi_client.disableDebug(dev)
        indi_client.disableDebugCcd()
        indi_client.saveCcdConfig()
        indi_client.resetCcdFrame()
        indi_client.setCcdFrameType('DARK')
        indi_client.setCcdScopeInfo(500.0, 5.0)
        assert mock_conf.call_count == 6

    indi_client.setBLOBMode = MagicMock()
    indi_client.updateCcdBlobMode()
    indi_client.setBLOBMode.assert_called_once()

    assert indi_client.getDeviceProperties(dev) == {}
    assert indi_client.getCcdDeviceProperties() == {}


def test_indi_get_ccd_gain_all_drivers(indi_client):
    dev = MockIndiDevice('CCD')
    indi_client.ccd_device = dev

    # 1. asi / toupcam / altair
    for drv in ['indi_asi_ccd', 'indi_toupcam_ccd', 'indi_altair_ccd', 'indi_playerone_ccd']:
        dev._exec = drv
        vec = MockIndiVector([MockIndiElement('Gain', value=120.0, min_val=0, max_val=400)])
        with patch.object(indi_client, 'get_control', return_value=vec):
            info = indi_client.getCcdGain()
            assert info['current'] == 120.0
            assert info['max'] == 400

    # 2. qhy / simulator / rpicam
    for drv in ['indi_qhy_ccd', 'indi_simulator_ccd', 'indi_rpicam', 'indi_dsi_ccd']:
        dev._exec = drv
        vec = MockIndiVector([MockIndiElement('GAIN', value=15.0, min_val=0, max_val=100)])
        with patch.object(indi_client, 'get_control', return_value=vec):
            info = indi_client.getCcdGain()
            assert info['current'] == 15.0

    # 3. svbony: CCD_CONTROLS success vs fallback to CCD_GAIN
    dev._exec = 'indi_svbony_ccd'
    vec_controls = MockIndiVector([MockIndiElement('Gain', value=50.0)])
    with patch.object(indi_client, 'get_control', return_value=vec_controls):
        assert indi_client.getCcdGain()['current'] == 50.0

    def mock_svbony_get_ctl(d, name, ctl_type, timeout=None):
        if name == 'CCD_CONTROLS':
            raise TimeOutException
        return MockIndiVector([MockIndiElement('GAIN', value=75.0)])

    with patch.object(indi_client, 'get_control', side_effect=mock_svbony_get_ctl):
        assert indi_client.getCcdGain()['current'] == 75.0

    # 4. sx / webcam
    for drv in ['indi_sx_ccd', 'indi_webcam_ccd']:
        dev._exec = drv
        assert indi_client.getCcdGain()['current'] == -1

    # 5. gphoto / canon / nikon
    dev._exec = 'indi_canon_ccd'
    vec_iso = MockIndiVector([
        MockIndiElement('ISO1', label='100'),
        MockIndiElement('ISO2', label='auto'),  # ValueError on int(label)
        MockIndiElement('ISO3', label='800'),
    ])
    with patch.object(indi_client, 'get_control', return_value=vec_iso):
        info = indi_client.getCcdGain()
        assert info['min'] == 100
        assert info['max'] == 800

    # gphoto with empty list
    with patch.object(indi_client, 'get_control', return_value=MockIndiVector([])):
        with pytest.raises(Exception, match='No available ISO/gain'):
            indi_client.getCcdGain()

    # 6. v4l2
    dev._exec = 'indi_v4l2_ccd'
    vec_v4l2 = MockIndiVector([MockIndiElement('Gain', value=20.0)])
    with patch.object(indi_client, 'get_control', return_value=vec_v4l2):
        assert indi_client.getCcdGain()['current'] == 20.0

    with patch.object(indi_client, 'get_control', side_effect=TimeOutException):
        assert indi_client.getCcdGain()['current'] == -1

    with patch.object(indi_client, 'get_control', return_value=MockIndiVector([MockIndiElement('Other')])):
        assert indi_client.getCcdGain()['current'] == -1

    # 7. rpicam-still / libcamera-still / fake
    dev._exec = 'rpicam-still'
    dev.getCcdGain = MagicMock(return_value=33.3)
    assert indi_client.getCcdGain() == 33.3

    # 8. indi_pylibcamera
    dev._exec = 'indi_pylibcamera_ccd'
    vec_pylib = MockIndiVector([MockIndiElement('GAIN', value=12.0)])
    with patch.object(indi_client, 'get_control', return_value=vec_pylib):
        assert indi_client.getCcdGain()['current'] == 12.0

    # 9. unknown driver
    dev._exec = 'unknown_ccd'
    with pytest.raises(Exception, match='Gain config not implemented'):
        indi_client.getCcdGain()


def test_indi_set_ccd_gain_all_drivers(indi_client):
    dev = MockIndiDevice('CCD')
    indi_client.ccd_device = dev

    with patch.object(indi_client, 'configureDevice') as mock_conf:
        # 1. asi / toupcam
        dev._exec = 'indi_asi_ccd'
        indi_client.setCcdGain(100.0)
        assert mock_conf.call_args[0][1]['PROPERTIES']['CCD_CONTROLS']['Gain'] == 100.0

        # 2. qhy
        dev._exec = 'indi_qhy_ccd'
        indi_client.setCcdGain(20.0)
        assert mock_conf.call_args[0][1]['PROPERTIES']['CCD_GAIN']['GAIN'] == 20.0

        # 3. svbony
        dev._exec = 'indi_svbony_ccd'
        with patch.object(indi_client, 'get_control'):
            indi_client.setCcdGain(30.0)
            assert 'CCD_CONTROLS' in mock_conf.call_args[0][1]['PROPERTIES']

        with patch.object(indi_client, 'get_control', side_effect=TimeOutException):
            indi_client.setCcdGain(30.0)
            assert 'CCD_GAIN' in mock_conf.call_args[0][1]['PROPERTIES']

        # 4. canon / gphoto (mapped vs fallback)
        dev._exec = 'indi_canon_ccd'
        indi_client._IndiClient__canon_gain_to_iso[400] = 'ISO4'
        indi_client.setCcdGain(400)
        assert mock_conf.call_args[0][1]['SWITCHES']['CCD_ISO']['on'] == ['ISO4']

        # KeyError fallback
        indi_client.setCcdGain(9999)
        assert mock_conf.call_args[0][1]['SWITCHES']['CCD_ISO']['on'] == ['ISO1']

        # 5. sx / webcam
        dev._exec = 'indi_sx_ccd'
        indi_client.setCcdGain(10)
        assert mock_conf.call_args[0][1] == {}

        dev._exec = 'indi_webcam_ccd'
        indi_client.setCcdGain(10)
        assert mock_conf.call_args[0][1] == {}

        # 6. v4l2
        dev._exec = 'indi_v4l2_ccd'
        with patch.object(indi_client, 'get_control', return_value=MockIndiVector([MockIndiElement('Gain')])):
            indi_client.setCcdGain(5)
            assert mock_conf.call_args[0][1]['PROPERTIES']['Image Adjustments']['Gain'] == 5.0

        with patch.object(indi_client, 'get_control', side_effect=TimeOutException):
            indi_client.setCcdGain(5)
            assert mock_conf.call_args[0][1] == {}

        with patch.object(indi_client, 'get_control', return_value=MockIndiVector([MockIndiElement('Other')])):
            indi_client.setCcdGain(5)
            assert mock_conf.call_args[0][1] == {}

        # 7. indi_pylibcamera
        dev._exec = 'indi_pylibcamera_ccd'
        indi_client.setCcdGain(8.0)
        assert mock_conf.call_args[0][1]['PROPERTIES']['CCD_GAIN']['GAIN'] == 8.0

    # 8. rpicam-still
    dev._exec = 'rpicam-still'
    dev.setCcdGain = MagicMock(return_value=True)
    indi_client.setCcdGain(15.0)
    dev.setCcdGain.assert_called_once_with(15.0)

    # 9. unknown
    dev._exec = 'unknown_driver'
    with pytest.raises(Exception, match='Gain config not implemented'):
        indi_client.setCcdGain(10.0)


def test_indi_binning_all_drivers(indi_client):
    dev = MockIndiDevice('CCD')
    indi_client.ccd_device = dev

    # getCcdBinning: gphoto / webcam vs normal
    dev._exec = 'indi_gphoto_ccd'
    assert indi_client.getCcdBinning()['current'] == 1

    dev._exec = 'indi_webcam_ccd'
    assert indi_client.getCcdBinning()['current'] == 1

    dev._exec = 'indi_asi_ccd'
    vec_bin = MockIndiVector([MockIndiElement('HOR_BIN', value=2, min_val=1, max_val=4)])
    with patch.object(indi_client, 'get_control', return_value=vec_bin):
        assert indi_client.getCcdBinning()['current'] == 2

    # setCcdBinning: falsy raises
    with pytest.raises(Exception, match='Invalid binning mode'):
        indi_client.setCcdBinning(None)

    # gphoto / webcam early return
    dev._exec = 'indi_gphoto_ccd'
    indi_client.setCcdBinning(2)
    assert indi_client.binning == 2

    dev._exec = 'indi_webcam_ccd'
    indi_client.setCcdBinning('2')
    assert indi_client.binning == 2

    # normal device: success and Timeout
    dev._exec = 'indi_asi_ccd'
    with patch.object(indi_client, 'get_control'), \
         patch.object(indi_client, 'configureDevice') as mock_conf:
        indi_client.setCcdBinning(2)
        assert mock_conf.call_args[0][1]['PROPERTIES']['CCD_BINNING']['HOR_BIN'] == 2

    with patch.object(indi_client, 'get_control', side_effect=TimeOutException):
        indi_client.setCcdBinning(2)


def test_indi_serial_number_all_drivers(indi_client):
    dev = MockIndiDevice('CCD')
    indi_client.ccd_device = dev

    # 1. asi: SN
    dev._exec = 'indi_asi_ccd'
    vec_sn = MockIndiVector([MockIndiElement('SN', text='ASI12345')])
    with patch.object(indi_client, 'get_control', return_value=vec_sn):
        assert indi_client.getCcdSerialNumber()['text'] == 'ASI12345'

    with patch.object(indi_client, 'get_control', side_effect=TimeOutException):
        assert indi_client.getCcdSerialNumber()['text'] is None

    with patch.object(indi_client, 'get_control', return_value=MockIndiVector([MockIndiElement('OTHER')])):
        assert indi_client.getCcdSerialNumber()['text'] is None

    # 2. playerone: SN#
    dev._exec = 'indi_playerone_ccd'
    vec_p1 = MockIndiVector([MockIndiElement('SN#', text='POA999')])
    with patch.object(indi_client, 'get_control', return_value=vec_p1):
        assert indi_client.getCcdSerialNumber()['text'] == 'POA999'

    with patch.object(indi_client, 'get_control', side_effect=TimeOutException):
        assert indi_client.getCcdSerialNumber()['text'] is None

    with patch.object(indi_client, 'get_control', return_value=MockIndiVector([MockIndiElement('OTHER')])):
        assert indi_client.getCcdSerialNumber()['text'] is None

    # 3. toupcam: CAMERA / SN
    dev._exec = 'indi_toupcam_ccd'
    vec_toup = MockIndiVector([MockIndiElement('SN', text='TOUP01')])
    with patch.object(indi_client, 'get_control', return_value=vec_toup):
        assert indi_client.getCcdSerialNumber()['text'] == 'TOUP01'

    with patch.object(indi_client, 'get_control', side_effect=TimeOutException):
        assert indi_client.getCcdSerialNumber()['text'] is None

    with patch.object(indi_client, 'get_control', return_value=MockIndiVector([MockIndiElement('OTHER')])):
        assert indi_client.getCcdSerialNumber()['text'] is None

    # 4. other driver
    dev._exec = 'indi_simulator_ccd'
    assert indi_client.getCcdSerialNumber()['text'] is None


def test_indi_allsky_camera_name(indi_client):
    dev = MockIndiDevice('MainCCD', exec_name='indi_asi_ccd')
    indi_client.ccd_device = dev
    assert indi_client.getIndiAllskyCameraName() == 'MainCCD'
    # Cached
    assert indi_client.getIndiAllskyCameraName() == 'MainCCD'

    # Alpaca camera: success, Timeout, KeyError
    dev_alpaca = MockIndiDevice('AlpacaDev', exec_name='indi_alpaca_ccd')
    indi_client.ccd_device = dev_alpaca
    indi_client._indi_allsky_camera_name = None

    vec_alpaca = MockIndiVector([MockIndiElement('NAME', text='ZWO ASI294MC')])
    with patch.object(indi_client, 'get_control', return_value=vec_alpaca):
        assert indi_client.generateIndiAllskyCameraName() == 'Alpaca Camera ZWO ASI294MC'

    with patch.object(indi_client, 'get_control', side_effect=TimeOutException):
        assert indi_client.generateIndiAllskyCameraName() == 'AlpacaDev'

    with patch.object(indi_client, 'get_control', return_value=MockIndiVector([MockIndiElement('OTHER')])):
        assert indi_client.generateIndiAllskyCameraName() == 'AlpacaDev'


def test_indi_find_devices(indi_client):
    dev1 = MockIndiDevice('CCD1', interfaces=PyIndi.BaseDevice.CCD_INTERFACE)
    dev2 = MockIndiDevice('CCD2', interfaces=PyIndi.BaseDevice.CCD_INTERFACE)
    tel = MockIndiDevice('Telescope Simulator', interfaces=PyIndi.BaseDevice.TELESCOPE_INTERFACE)
    gps = MockIndiDevice('GPS Simulator', interfaces=PyIndi.BaseDevice.GPS_INTERFACE)

    with patch.object(PyIndi.BaseClient, 'getDevices', return_value=[dev1, dev2, tel, gps]):
        # findCcd
        assert indi_client.findCcd('CCD2') == dev2
        with pytest.raises(CameraException, match='Camera not found'):
            indi_client.findCcd('NonExistent')

        assert indi_client.findCcd() == dev1

    with patch.object(PyIndi.BaseClient, 'getDevices', return_value=[]):
        with pytest.raises(CameraException, match='No cameras found'):
            indi_client.findCcd()

    # findTelescope
    with patch.object(PyIndi.BaseClient, 'getDevices', return_value=[dev1, tel]):
        assert indi_client.findTelescope('Telescope Simulator') == tel
        indi_client.telescope_device = None
        assert indi_client.findTelescope('UnknownTel') is None

    # findGps
    with patch.object(PyIndi.BaseClient, 'getDevices', return_value=[dev1, gps]):
        assert indi_client.findGps('GPS Simulator') == gps
        with pytest.raises(CameraException, match='GPS not found'):
            indi_client.findGps('UnknownGPS')

        assert indi_client.findGps() == gps

    with patch.object(PyIndi.BaseClient, 'getDevices', return_value=[]):
        indi_client.gps_device = None
        assert indi_client.findGps() is None


def test_indi_find_device_interfaces_ctypes(indi_client):
    import ctypes
    # Test interface as int
    dev_int = MagicMock()
    dev_int.getDriverInterface.return_value = 4
    assert indi_client.findDeviceInterfaces(dev_int) == 4

    # Test interface as swig object with memory pointer
    dev_swig = MagicMock()
    mock_interface = MagicMock()
    val = ctypes.c_uint16(8)
    mock_interface.__int__.return_value = ctypes.addressof(val)
    dev_swig.getDriverInterface.return_value = mock_interface

    assert indi_client.findDeviceInterfaces(dev_swig) == 8
    mock_interface.acquire.assert_called_once()
    mock_interface.disown.assert_called_once()


def test_indi_controls_get_and_set(indi_client):
    dev = MockIndiDevice('CCD')
    vec_num = MockIndiVector([MockIndiElement('VAL', value=10.0, min_val=0, max_val=100)], perm=PyIndi.IP_RW)
    dev.add_control('TEST_NUM', 'number', vec_num)

    # get_control
    ctl = indi_client.get_control(dev, 'TEST_NUM', 'number')
    assert ctl == vec_num

    with pytest.raises(TimeOutException):
        indi_client.get_control(dev, 'NONEXISTENT', 'number', timeout=0.05)

    # set_number: read-only
    vec_num_ro = MockIndiVector([MockIndiElement('VAL', value=10.0)], perm=PyIndi.IP_RO)
    dev.add_control('RO_NUM', 'number', vec_num_ro)
    assert indi_client.set_number(dev, 'RO_NUM', {'VAL': 20.0}, sync=False) == vec_num_ro
    assert vec_num_ro[0].getValue() == 10.0

    # set_number: read-write sync=False
    indi_client.set_number(dev, 'TEST_NUM', {'VAL': 25.0}, sync=False)
    assert vec_num[0].getValue() == 25.0
    indi_client.sendNewNumber.assert_called_with(vec_num)

    # set_switch: read-only
    vec_sw_ro = MockIndiVector([MockIndiElement('S1')], perm=PyIndi.IP_RO)
    dev.add_control('RO_SW', 'switch', vec_sw_ro)
    assert indi_client.set_switch(dev, 'RO_SW', on_switches=['S1']) == vec_sw_ro

    # set_switch: exclusive
    s1 = MockIndiElement('S1', state=PyIndi.ISS_OFF)
    s2 = MockIndiElement('S2', state=PyIndi.ISS_ON)
    vec_sw_ex = MockIndiVector([s1, s2], perm=PyIndi.IP_RW, rule=PyIndi.ISR_1OFMANY)
    dev.add_control('EX_SW', 'switch', vec_sw_ex)
    indi_client.set_switch(dev, 'EX_SW', on_switches=['S1'], sync=False)
    assert s1.getState() == PyIndi.ISS_ON
    assert s2.getState() == PyIndi.ISS_OFF

    # set_switch: non-exclusive
    vec_sw_any = MockIndiVector([s1, s2], perm=PyIndi.IP_RW, rule=PyIndi.ISR_NOFMANY)
    dev.add_control('ANY_SW', 'switch', vec_sw_any)
    indi_client.set_switch(dev, 'ANY_SW', on_switches=['S1', 'S2'], sync=False)
    assert s1.getState() == PyIndi.ISS_ON
    assert s2.getState() == PyIndi.ISS_ON

    # set_text: read-only
    vec_txt_ro = MockIndiVector([MockIndiElement('T1')], perm=PyIndi.IP_RO)
    dev.add_control('RO_TXT', 'text', vec_txt_ro)
    assert indi_client.set_text(dev, 'RO_TXT', {'T1': 'foo'}, sync=False) == vec_txt_ro

    # set_text: read-write
    t1 = MockIndiElement('T1', text='old')
    vec_txt_rw = MockIndiVector([t1], perm=PyIndi.IP_RW)
    dev.add_control('RW_TXT', 'text', vec_txt_rw)
    indi_client.set_text(dev, 'RW_TXT', {'T1': 'new'}, sync=False)
    assert t1.getText() == 'new'
    indi_client.sendNewText.assert_called_with(vec_txt_rw)


def test_indi_values_helpers(indi_client):
    dev = MockIndiDevice('CCD')
    vec_num = MockIndiVector([MockIndiElement('V1', value=5.0)])
    dev.add_control('N1', 'number', vec_num)
    assert indi_client.values(dev, 'N1', 'number') == {'V1': 5.0}

    vec_sw = MockIndiVector([MockIndiElement('S1', state=PyIndi.ISS_ON)])
    dev.add_control('SW1', 'switch', vec_sw)
    sw_dict = indi_client.switch_values(dev, 'SW1')
    assert sw_dict[0]['name'] == 'S1'
    assert sw_dict[0]['value'] is True

    vec_txt = MockIndiVector([MockIndiElement('T1', text='hello')])
    dev.add_control('TX1', 'text', vec_txt)
    txt_dict = indi_client.text_values(dev, 'TX1')
    assert txt_dict[0]['name'] == 'T1'
    assert txt_dict[0]['value'] == 'hello'

    num_dict = indi_client.number_values(dev, 'N1')
    assert num_dict[0]['name'] == 'V1'
    assert num_dict[0]['value'] == 5.0

    vec_light = MockIndiVector([MockIndiElement('L1', state=PyIndi.IPS_OK)])
    dev.add_control('LT1', 'light', vec_light)
    lt_dict = indi_client.light_values(dev, 'LT1')
    assert lt_dict[0]['name'] == 'L1'
    assert lt_dict[0]['value'] == 'OK'


def test_indi_ctl_ready_and_wait(indi_client):
    assert indi_client.ctl_ready(None) == (True, 'unset')

    vec_ok = MockIndiVector([MockIndiElement('item')], state=PyIndi.IPS_OK)
    assert indi_client.ctl_ready(vec_ok) == (True, 'OK')

    vec_busy = MockIndiVector([MockIndiElement('item')], state=PyIndi.IPS_BUSY)
    assert indi_client.ctl_ready(vec_busy) == (False, 'BUSY')

    # wait_for_ctl_statuses success
    indi_client._IndiClient__wait_for_ctl_statuses(vec_ok)

    # wait_for_ctl_statuses alert exception
    vec_alert = MockIndiVector([MockIndiElement('item')], state=PyIndi.IPS_ALERT)
    with pytest.raises(RuntimeError, match='Error while changing property'):
        indi_client._IndiClient__wait_for_ctl_statuses(vec_alert, timeout=1.0)

    # wait_for_ctl_statuses timeout exception
    with patch('time.time', side_effect=[0.0, 0.0, 10.0, 20.0]):
        with pytest.raises(TimeOutException):
            indi_client._IndiClient__wait_for_ctl_statuses(vec_busy, timeout=0.1)


def test_indi_get_ccd_info(indi_client):
    dev = MockIndiDevice('CCD', exec_name='indi_asi_ccd')
    indi_client.ccd_device = dev

    vec_exp = MockIndiVector([MockIndiElement('CCD_EXPOSURE_VALUE', value=1.0, min_val=0.001, max_val=300)])
    dev.add_control('CCD_EXPOSURE', 'number', vec_exp)

    vec_info = MockIndiVector([MockIndiElement('CCD_MAX_X', value=1920), MockIndiElement('CCD_MAX_Y', value=1080)])
    dev.add_control('CCD_INFO', 'number', vec_info)

    vec_cfa = MockIndiVector([MockIndiElement('CFA_TYPE', text='RGGB')])
    dev.add_control('CCD_CFA', 'text', vec_cfa)

    vec_frame = MockIndiVector([MockIndiElement('X', value=0), MockIndiElement('Y', value=0)])
    dev.add_control('CCD_FRAME', 'number', vec_frame)

    vec_ft = MockIndiVector([MockIndiElement('FRAME_LIGHT', state=PyIndi.ISS_ON)])
    dev.add_control('CCD_FRAME_TYPE', 'switch', vec_ft)

    vec_gain = MockIndiVector([MockIndiElement('Gain', value=100.0, min_val=0, max_val=400)])
    dev.add_control('CCD_CONTROLS', 'number', vec_gain)

    vec_bin = MockIndiVector([MockIndiElement('HOR_BIN', value=1, min_val=1, max_val=4)])
    dev.add_control('CCD_BINNING', 'number', vec_bin)

    vec_sn = MockIndiVector([MockIndiElement('SN', text='ASI12345')])
    dev.add_control('Serial Number', 'text', vec_sn)

    info = indi_client.getCcdInfo()
    assert 'CCD_EXPOSURE' in info
    assert 'CCD_INFO' in info
    assert info['CCD_CFA']['CFA_TYPE']['text'] == 'RGGB'
    assert 'CCD_FRAME' in info
    assert 'CCD_FRAME_TYPE' in info
    assert info['GAIN_INFO']['current'] == 100.0
    assert info['BINNING_INFO']['current'] == 1
    assert info['SERIALNUMBER_INFO']['text'] == 'ASI12345'

    # CFA timeout assumes monochrome
    with patch.object(indi_client, 'get_control') as mock_get_ctl:
        def side_effect_cfa(device, name, ctl_type, timeout=None):
            if name == 'CCD_CFA':
                raise TimeOutException
            return dev.controls.get((name, ctl_type))
        mock_get_ctl.side_effect = side_effect_cfa
        info_mono = indi_client.getCcdInfo()
        assert info_mono['CCD_CFA'] == {'CFA_TYPE': {}}


def test_indi_final_edge_cases(indi_client):
    dev = MockIndiDevice('CCD')
    indi_client.ccd_device = dev
    indi_client.telescope_device = dev
    indi_client.gps_device = dev

    with patch.object(indi_client, 'configureDevice') as mock_conf:
        indi_client.configureCcdDevice({'SWITCHES': {}}, sleep=0.0)
        assert mock_conf.call_count == 1
        indi_client.configureTelescopeDevice({'SWITCHES': {}}, sleep=0.0)
        assert mock_conf.call_count == 2
        indi_client.configureGpsDevice({'SWITCHES': {}}, sleep=0.0)
        assert mock_conf.call_count == 3

    # getGpsTime with empty offset
    vec_no_offset = MockIndiVector([MockIndiElement('UTC', text='2026-09-13T01:00:00Z'), MockIndiElement('OFFSET', text='')])
    with patch.object(indi_client, 'get_control', return_value=vec_no_offset):
        indi_client.getGpsTime()

    # set_number sync=True and set_text sync=True
    vec_num = MockIndiVector([MockIndiElement('V1', value=10.0)], state=PyIndi.IPS_OK)
    dev.add_control('NUM_SYNC', 'number', vec_num)
    indi_client.set_number(dev, 'NUM_SYNC', {'V1': 20.0}, sync=True)

    vec_txt = MockIndiVector([MockIndiElement('T1', text='old')], state=PyIndi.IPS_OK)
    dev.add_control('TXT_SYNC', 'text', vec_txt)
    indi_client.set_text(dev, 'TXT_SYNC', {'T1': 'new'}, sync=True)
