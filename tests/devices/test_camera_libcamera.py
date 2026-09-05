import sys
import json
import tempfile
from pathlib import Path
from multiprocessing import Array, Queue
from unittest.mock import MagicMock, patch
import pytest

# Mock PyIndi if not installed
if 'PyIndi' not in sys.modules:
    mock_pyindi = MagicMock()
    mock_pyindi.BaseClient = object
    mock_pyindi.IPS_IDLE = 0
    mock_pyindi.IPS_OK = 1
    mock_pyindi.IPS_BUSY = 2
    mock_pyindi.IPS_ALERT = 3
    mock_pyindi.ISS_OFF = 0
    mock_pyindi.ISS_ON = 1
    mock_pyindi.ISR_1OFMANY = 0
    mock_pyindi.ISR_ATMOST1 = 1
    mock_pyindi.ISR_NOFMANY = 2
    mock_pyindi.INDI_NUMBER = 0
    mock_pyindi.INDI_SWITCH = 1
    mock_pyindi.INDI_TEXT = 2
    mock_pyindi.INDI_LIGHT = 3
    mock_pyindi.INDI_BLOB = 4
    sys.modules['PyIndi'] = mock_pyindi

from indi_allsky.camera.libcamera import (
    IndiClientLibCameraGeneric,
    IndiClientLibCameraImx477,
    IndiClientLibCameraImx708,
    IndiClientLibCameraOv5647,
)
from indi_allsky.exceptions import BinModeException
from indi_allsky import constants


@pytest.fixture
def libcamera_client(flask_app):
    config = {
        'LIBCAMERA': {
            'CAMERA_ID': 0,
            'IMAGE_FILE_TYPE': 'jpg',
            'IMAGE_FILE_TYPE_DAY': 'jpg',
            'IMMEDIATE': True,
            'IMMEDIATE_DAY': True,
            'AWB_ENABLE': False,
            'AWB_ENABLE_DAY': False,
        }
    }
    image_q = Queue()
    position_av = Array('d', [0.0] * 5)
    exposure_av = Array('f', [-1.0] * 7)
    gain_av = Array('f', [-1.0] * 10)
    binning_av = Array('i', [1] * 6)
    night_av = Array('i', [1, 0])

    with patch('shutil.which', return_value='/usr/bin/rpicam-still'):
        client = IndiClientLibCameraGeneric(
            config,
            image_q,
            position_av,
            exposure_av,
            gain_av,
            binning_av,
            night_av,
        )
        client.findCcd()
    return client


def test_libcamera_init(libcamera_client):
    assert libcamera_client.ccd_driver_exec in ['rpicam-still', 'libcamera-still']
    assert libcamera_client.camera_info['width'] == 0
    assert libcamera_client.ccd_device is not None


def test_libcamera_subclasses_camera_info(flask_app):
    config = {}
    image_q = Queue()
    position_av = Array('d', [0.0] * 5)
    exposure_av = Array('f', [-1.0] * 7)
    gain_av = Array('f', [-1.0] * 10)
    binning_av = Array('i', [1] * 6)
    night_av = Array('i', [1, 0])

    with patch('shutil.which', return_value='/usr/bin/rpicam-still'):
        imx477 = IndiClientLibCameraImx477(
            config, image_q, position_av, exposure_av, gain_av, binning_av, night_av
        )
        imx477.findCcd()
        assert imx477.camera_info['width'] == 4056
        assert imx477.camera_info['height'] == 3040
        assert imx477.camera_info['cfa'] == 'BGGR'

        imx708 = IndiClientLibCameraImx708(
            config, image_q, position_av, exposure_av, gain_av, binning_av, night_av
        )
        imx708.findCcd()
        assert imx708.camera_info['width'] == 4608
        assert imx708.camera_info['height'] == 2592

        ov5647 = IndiClientLibCameraOv5647(
            config, image_q, position_av, exposure_av, gain_av, binning_av, night_av
        )
        ov5647.findCcd()
        assert ov5647.camera_info['width'] == 2592
        assert ov5647.camera_info['height'] == 1944


def test_binmode_options(libcamera_client):
    assert libcamera_client._getBinModeOptions(1) == ''
    with pytest.raises(BinModeException):
        libcamera_client._getBinModeOptions(99)


def test_gain_and_binning_setters(libcamera_client):
    libcamera_client.setCcdGain(10.5)
    assert libcamera_client.gain == 10.5

    libcamera_client.setCcdBinning(2)
    assert libcamera_client.binning == 2


def test_set_ccd_exposure_command_construction(libcamera_client):
    with patch('subprocess.Popen') as mock_popen:
        mock_proc = MagicMock()
        mock_proc.pid = 1234
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        libcamera_client.setCcdExposure(
            exposure=1.5,
            gain=5.0,
            binning=1,
            sync=False,
        )

        assert mock_popen.called
        cmd = mock_popen.call_args[0][0]
        assert '--camera' in cmd
        assert '--gain' in cmd
        assert '--shutter' in cmd
        assert '1500000' in cmd  # 1.5s in microseconds
