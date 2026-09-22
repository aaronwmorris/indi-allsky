import pytest
from multiprocessing import Queue, Value, Array
from unittest.mock import MagicMock

from indi_allsky.camera.fake_indi import (
    FakeIndiClient,
    FakeIndiDevice,
    FakeIndiCcd,
    FakeIndiTelescope,
    FakeIndiGps,
    FakeIndiVectorGeneric,
    FakeIndiVectorSwitch,
    FakeIndiVectorNumber,
    FakeIndiVectorOption,
)


@pytest.fixture
def fake_client():
    config = {}
    image_q = Queue()
    lat_v = Value('d', 45.0)
    long_v = Value('d', -75.0)
    ra_v = Value('d', 12.5)
    dec_v = Value('d', 89.0)
    gain_av = Array('i', [100000] * 10)
    bin_av = Array('i', [1] * 6)
    night_av = Array('i', [1, 0])

    client = FakeIndiClient(
        config,
        image_q,
        lat_v,
        long_v,
        ra_v,
        dec_v,
        gain_av,
        bin_av,
        night_av,
    )
    client._expUtils = MagicMock()
    return client


def test_fake_indi_client_properties(fake_client):
    ccd = FakeIndiCcd()
    telescope = FakeIndiTelescope()
    gps = FakeIndiGps()

    fake_client.ccd_device = ccd
    assert fake_client.ccd_device == ccd

    fake_client.telescope_device = telescope
    assert fake_client.telescope_device == telescope

    fake_client.gps_device = gps
    assert fake_client.gps_device == gps

    fake_client.timeout = 12.5
    assert fake_client.timeout == 12.5

    fake_client.exposure = 3.2
    assert fake_client.exposure == 3.2

    fake_client.gain = 25
    assert fake_client.gain == 25

    fake_client.filename_t = 'test_{0}.jpg'
    assert fake_client.filename_t == 'test_{0}.jpg'


def test_fake_indi_client_server_and_network_methods(fake_client):
    assert fake_client.setServer('localhost', 7624) is None
    assert fake_client.connectServer() is True
    assert fake_client.disconnectServer() is None
    assert fake_client.connectDevice('CCD') is None
    assert fake_client.getHost() == 'FakeIndiClient'
    assert fake_client.getPort() == 0


def test_fake_indi_client_ccd_controls(fake_client):
    ccd = FakeIndiCcd()
    ccd.min_exposure = 0.001
    ccd.max_exposure = 60.0
    ccd.bit_depth = 16
    ccd.cfa = 'RGGB'
    ccd.min_gain = 0
    ccd.max_gain = 100

    fake_client.ccd_device = ccd

    assert fake_client.updateCcdBlobMode() is None
    assert fake_client.disableDebug() is None
    assert fake_client.disableDebugCcd() is None
    assert fake_client.saveCcdConfig() is None
    assert fake_client.resetCcdFrame() is None

    fake_client.setCcdFrameType('DARK')
    assert fake_client._ccd_frame_type == 'DARK'

    assert fake_client.getDeviceProperties(ccd) == {}
    assert fake_client.getCcdDeviceProperties() == {}

    info = fake_client.getCcdInfo()
    assert info['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['min'] == 0.001
    assert info['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['max'] == 60.0
    assert info['CCD_INFO']['CCD_BITSPERPIXEL']['current'] == 16
    assert info['CCD_CFA']['CFA_TYPE']['text'] == 'RGGB'
    assert info['GAIN_INFO']['max'] == 100

    assert fake_client.findCcd() is None
    assert fake_client.findTelescope() is None
    assert fake_client.findGps() is None

    assert fake_client.configureCcdDevice() is None
    assert fake_client.configureTelescopeDevice() is None
    assert fake_client.setTelescopeGps('GPS') is None
    assert fake_client.configureGpsDevice() is None
    assert fake_client.refreshGps() is None

    assert fake_client.getGpsPosition() == (45.0, -75.0, 0.0)
    assert fake_client.getGpsTime() == (None, None)
    assert fake_client.getTelescopeRaDec() == (0.0, 0.0)

    assert fake_client.parkTelescope() is None
    assert fake_client.unparkTelescope() is None
    assert fake_client.setTelescopeParkPosition(10, 20) is None

    assert fake_client.getCcdTemperature() == -273.15
    assert fake_client.enableCcdCooler() is True
    assert fake_client.disableCcdCooler() is True
    assert fake_client.setCcdTemperature(-15.0) is True

    assert fake_client.setCcdExposure(1.0) is None
    assert fake_client.getCcdExposureStatus() is None

    assert fake_client.getCcdGain() == -1
    fake_client.setCcdGain(40.0)
    assert fake_client.getCcdGain() == 40.0
    assert fake_client._expUtils.GAIN_CURRENT == 40.0

    fake_client.setCcdBinning(2)
    assert fake_client._ccd_bin == 2
    assert fake_client._expUtils.BINNING_CURRENT == 2

    # None or empty binning is no-op
    fake_client.setCcdBinning(None)
    assert fake_client._ccd_bin == 2


def test_fake_indi_device():
    dev = FakeIndiDevice()
    assert dev.device_name == 'UNDEFINED'
    assert dev.driver_exec == 'UNDEFINED'
    assert dev.getDeviceName() == 'UNDEFINED'
    assert dev.getDriverExec() == 'UNDEFINED'

    dev.device_name = 'MyDev'
    dev.driver_exec = 'my_exec'
    assert dev.device_name == 'MyDev'
    assert dev.driver_exec == 'my_exec'
    assert dev.getDeviceName() == 'MyDev'
    assert dev.getDriverExec() == 'my_exec'

    sw = dev.getSwitch('DEBUG')
    assert isinstance(sw, FakeIndiVectorSwitch)
    assert len(sw) == 2
    assert sw[0].name == 'ENABLE'
    assert sw[1].name == 'DISABLE'

    with pytest.raises(Exception, match='Unknown config switch'):
        dev.getSwitch('UNKNOWN')

    num = dev.getNumber('CCD_TEMPERATURE')
    assert isinstance(num, FakeIndiVectorNumber)
    assert len(num) == 1
    assert num[0].name == 'CCD_TEMPERATURE_VALUE'
    assert num[0].getValue() == -273.15

    with pytest.raises(Exception, match='Unknown config number'):
        dev.getNumber('UNKNOWN')


def test_fake_indi_ccd_properties():
    ccd = FakeIndiCcd()
    ccd.width = 1920
    ccd.height = 1080
    ccd.pixel = 3.75
    ccd.min_gain = 0.0
    ccd.max_gain = 300.0
    ccd.min_binning = 1
    ccd.max_binning = 4
    ccd.min_exposure = 0.0001
    ccd.max_exposure = 300.0
    ccd.cfa = 'RGGB'
    ccd.bit_depth = 12

    assert ccd.width == 1920
    assert ccd.height == 1080
    assert ccd.pixel == 3.75
    assert ccd.min_gain == 0.0
    assert ccd.max_gain == 300.0
    assert ccd.min_binning == 1
    assert ccd.max_binning == 4
    assert ccd.min_exposure == 0.0001
    assert ccd.max_exposure == 300.0
    assert ccd.cfa == 'RGGB'
    assert ccd.bit_depth == 12


def test_fake_indi_telescope_and_gps():
    tel = FakeIndiTelescope()
    assert tel.lat == 0.0
    assert tel.long == 0.0
    tel.lat = 51.5
    tel.long = -0.1
    assert tel.lat == 51.5
    assert tel.long == -0.1

    gps = FakeIndiGps()
    assert gps.lat == 0.0
    assert gps.long == 0.0
    gps.lat = -33.8
    gps.long = 151.2
    assert gps.lat == -33.8
    assert gps.long == 151.2


def test_fake_indi_vectors_and_options():
    vec = FakeIndiVectorGeneric('OPT1', 'OPT2', 'OPT3')
    assert len(vec) == 3
    assert vec[0].name == 'OPT1'
    assert vec[1].name == 'OPT2'
    assert vec[2].name == 'OPT3'

    # Iteration
    names = [opt.name for opt in vec]
    assert names == ['OPT1', 'OPT2', 'OPT3']

    sw_vec = FakeIndiVectorSwitch('A', 'B')
    assert sw_vec.getRule() == 999

    num_vec = FakeIndiVectorNumber('N1')
    assert len(num_vec) == 1

    opt = FakeIndiVectorOption('TEST_OPT')
    assert opt.name == 'TEST_OPT'
    assert opt.getName() == 'TEST_OPT'
    opt.name = 'RENAMED'
    assert opt.getName() == 'RENAMED'

    # switch state
    assert opt.state == 0
    assert opt.getState() == 0
    opt.setState(1)
    assert opt.state == 1
    assert opt.getState() == 1
    opt.state = 0
    assert opt.getState() == 0

    # number value
    assert opt.value == 0
    assert opt.getValue() == 0.0
    opt.setValue(42.5)
    assert opt.value == 42.5
    assert opt.getValue() == 42.5
    opt.value = 10.0
    assert opt.getValue() == 10.0

    # text
    assert opt.text == ''
    assert opt.getText() == ''
    opt.setText('hello')
    assert opt.text == 'hello'
    assert opt.getText() == 'hello'
    opt.text = 'world'
    assert opt.getText() == 'world'
