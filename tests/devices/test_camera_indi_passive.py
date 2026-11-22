import pytest
from multiprocessing import Queue, Array
from unittest.mock import MagicMock, patch

from indi_allsky.camera.indi_passive import IndiClientPassive


@pytest.fixture
def passive_camera_setup(flask_app):
    config = {}
    image_q = Queue()
    position_av = Array('d', [0.0] * 5)
    exposure_av = Array('i', [1000000] * 7)
    gain_av = Array('i', [100000] * 10)
    binning_av = Array('i', [1] * 6)
    night_av = Array('i', [1, 0])

    client = IndiClientPassive(
        config,
        image_q,
        position_av,
        exposure_av,
        gain_av,
        binning_av,
        night_av,
    )
    return client


def test_passive_noops(passive_camera_setup):
    client = passive_camera_setup
    assert client.parkTelescope() is None
    assert client.unparkTelescope() is None
    assert client.setTelescopeParkPosition(10.0, 20.0) is None
    assert client.disableDebug() is None
    assert client.disableDebugCcd() is None
    assert client.saveCcdConfig() is None
    assert client.resetCcdFrame() is None
    assert client.setCcdFrameType('LIGHT') is None
    assert client.configureDevice() is None
    assert client.configureCcdDevice() is None
    assert client.configureTelescopeDevice() is None
    assert client.setTelescopeGps('GPS') is None
    assert client.configureGpsDevice() is None
    assert client.refreshGps() is None
    assert client.enableCcdCooler() is None
    assert client.disableCcdCooler() is None
    assert client.setCcdTemperature(-10.0) is None
    assert client.setCcdScopeInfo(100, 2.8) is None
    assert client.abortCcdExposure() is None


def test_passive_set_gain_and_binning(passive_camera_setup):
    client = passive_camera_setup

    client.setCcdGain(50.0)
    assert client.gain == 50.0
    assert client._expUtils.GAIN_CURRENT == 50.0

    client.setCcdBinning(2)
    assert client.binning == 2
    assert client._expUtils.BINNING_CURRENT == 2

    # Falsy bin_value should be a no-op
    client.setCcdBinning(None)
    assert client.binning == 2
    client.setCcdBinning(0)
    assert client.binning == 2


def test_passive_set_ccd_exposure_and_status(passive_camera_setup):
    client = passive_camera_setup
    client.gain = 10.0
    client.binning = 1

    mock_ctl = MagicMock()
    with patch.object(client, 'get_control', return_value=mock_ctl) as mock_get_control, \
         patch.object(client, 'ctl_ready', return_value=(True, 'OK')) as mock_ctl_ready:
        client.ccd_device = MagicMock()
        client.setCcdExposure(
            exposure=2.5,
            gain=20.0,
            binning=2,
            sync=False,
            timeout=10,
            sqm_exposure=True,
        )

        assert client.exposure == 2.5
        assert client.sqm_exposure is True
        assert client.gain == 20.0
        assert client.binning == 2
        assert client._expUtils.EXPOSURE_CURRENT == 2.5
        mock_get_control.assert_called_once_with(client.ccd_device, 'CCD_EXPOSURE', 'number')
        assert client._ctl_ccd_exposure == mock_ctl

        ready, state = client.getCcdExposureStatus()
        assert ready is True
        assert state == 'OK'
        mock_ctl_ready.assert_called_once_with(mock_ctl)
