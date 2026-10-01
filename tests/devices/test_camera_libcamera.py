import sys
import io
import json
import tempfile
import subprocess
from pathlib import Path
from multiprocessing import Array, Queue
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky.camera.libcamera import (
    IndiClientLibCameraGeneric,
    IndiClientLibCameraImx477,
    IndiClientLibCameraImx378,
    IndiClientLibCameraOv5647,
    IndiClientLibCameraImx219,
    IndiClientLibCameraImx519,
    IndiClientLibCamera64mpHawkeye,
    IndiClientLibCameraOv64a40OwlSight,
    IndiClientLibCameraImx708,
    IndiClientLibCameraImx296,
    IndiClientLibCameraImx296Color,
    IndiClientLibCameraImx290,
    IndiClientLibCameraImx462,
    IndiClientLibCameraImx327,
    IndiClientLibCameraImx298,
    IndiClientLibCameraImx500,
    IndiClientLibCameraImx283,
    IndiClientLibCameraImx678,
    IndiClientLibCameraImx335,
)
from indi_allsky.exceptions import BinModeException, TimeOutException
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


def test_libcamera_init_exec_selection(flask_app):
    config = {}
    image_q = Queue()
    position_av = Array('d', [0.0] * 5)
    exposure_av = Array('f', [-1.0] * 7)
    gain_av = Array('f', [-1.0] * 10)
    binning_av = Array('i', [1] * 6)
    night_av = Array('i', [1, 0])

    # 1. libcamera-still available
    def mock_which_libcamera(name):
        return '/usr/bin/libcamera-still' if name == 'libcamera-still' else None

    with patch('shutil.which', side_effect=mock_which_libcamera):
        client = IndiClientLibCameraGeneric(
            config, image_q, position_av, exposure_av, gain_av, binning_av, night_av
        )
        assert client.ccd_driver_exec == 'libcamera-still'

    # 2. neither available -> fallback
    with patch('shutil.which', return_value=None):
        client = IndiClientLibCameraGeneric(
            config, image_q, position_av, exposure_av, gain_av, binning_av, night_av
        )
        assert client.ccd_driver_exec == 'rpicam-still'


ALL_LIBCAMERA_SUBCLASSES = [
    IndiClientLibCameraImx477,
    IndiClientLibCameraImx378,
    IndiClientLibCameraOv5647,
    IndiClientLibCameraImx219,
    IndiClientLibCameraImx519,
    IndiClientLibCamera64mpHawkeye,
    IndiClientLibCameraOv64a40OwlSight,
    IndiClientLibCameraImx708,
    IndiClientLibCameraImx296,
    IndiClientLibCameraImx296Color,
    IndiClientLibCameraImx290,
    IndiClientLibCameraImx462,
    IndiClientLibCameraImx327,
    IndiClientLibCameraImx298,
    IndiClientLibCameraImx500,
    IndiClientLibCameraImx283,
    IndiClientLibCameraImx678,
    IndiClientLibCameraImx335,
]


@pytest.mark.parametrize('cls', ALL_LIBCAMERA_SUBCLASSES)
def test_all_libcamera_subclasses(flask_app, cls):
    config = {}
    image_q = Queue()
    position_av = Array('d', [0.0] * 5)
    exposure_av = Array('f', [-1.0] * 7)
    gain_av = Array('f', [-1.0] * 10)
    binning_av = Array('i', [1] * 6)
    night_av = Array('i', [1, 0])

    with patch('shutil.which', return_value='/usr/bin/rpicam-still'):
        cam = cls(config, image_q, position_av, exposure_av, gain_av, binning_av, night_av)
        ccd = cam.findCcd()
        assert ccd.width > 0
        assert ccd.height > 0
        assert cam.camera_info['width'] == ccd.width
        assert cam.camera_info['height'] == ccd.height
        assert cam._getBinModeOptions(1) == ''
        with pytest.raises(BinModeException):
            cam._getBinModeOptions(999)


def test_binmode_options(libcamera_client):
    assert libcamera_client._getBinModeOptions(1) == ''
    with pytest.raises(BinModeException):
        libcamera_client._getBinModeOptions(99)


def test_gain_and_binning_setters(libcamera_client):
    libcamera_client.setCcdGain(10.5)
    assert libcamera_client.gain == 10.5
    assert libcamera_client.getCcdGain() == 10.5

    libcamera_client.setCcdBinning(2)
    assert libcamera_client.binning == 2

    # Falsy bin_value should return without changes
    libcamera_client.setCcdBinning(None)
    assert libcamera_client.binning == 2


def test_bit_depth_property(libcamera_client):
    libcamera_client.libcamera_bit_depth = 14
    assert libcamera_client.libcamera_bit_depth == 14
    assert libcamera_client.camera_info['bit_depth'] == 14
    assert libcamera_client.ccd_device.bit_depth == 14


def test_set_ccd_exposure_already_active(libcamera_client):
    libcamera_client.active_exposure = True
    with patch('subprocess.Popen') as mock_popen:
        libcamera_client.setCcdExposure(1.0, 5.0, 1)
        mock_popen.assert_not_called()


def test_set_ccd_exposure_night_options(libcamera_client):
    libcamera_client.night_av[constants.NIGHT_NIGHT] = 1
    libcamera_client.config['LIBCAMERA'] = {
        'CAMERA_ID': 1,
        'IMAGE_FILE_TYPE': 'dng',
        'IMMEDIATE': True,
        'AWB_ENABLE': True,
        'AWB': 'cloudy',
        'CCM_DISABLE': True,
        'EXTRA_OPTIONS': '--tuning-file /etc/tuning.json',
    }
    libcamera_client.memory_total_mb = 512  # trigger <= 768 warning

    with patch('subprocess.Popen') as mock_popen:
        mock_proc = MagicMock()
        mock_proc.pid = 1234
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        libcamera_client.setCcdExposure(exposure=2.0, gain=8.0, binning=1, sync=False)

        cmd = mock_popen.call_args[0][0]
        assert '--raw' in cmd
        assert '--immediate' in cmd
        assert '--camera' in cmd and '1' in cmd
        assert '--awb' in cmd and 'cloudy' in cmd
        assert '--ccm' in cmd
        assert '--tuning-file' in cmd
        assert '--shutter' in cmd and '2000000' in cmd


def test_set_ccd_exposure_day_options(libcamera_client):
    libcamera_client.night_av[constants.NIGHT_NIGHT] = 0
    libcamera_client.config['LIBCAMERA'] = {
        'CAMERA_ID': 0,
        'IMAGE_FILE_TYPE_DAY': 'png',
        'IMMEDIATE_DAY': False,
        'AWB_ENABLE_DAY': True,
        'AWB_DAY': 'daylight',
        'CCM_DISABLE_DAY': True,
        'EXTRA_OPTIONS_DAY': '--rotation 180',
    }

    with patch('subprocess.Popen') as mock_popen:
        mock_proc = MagicMock()
        mock_proc.pid = 1234
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        libcamera_client.setCcdExposure(exposure=0.5, gain=1.0, binning=1, sync=False)

        cmd = mock_popen.call_args[0][0]
        assert '--encoding' in cmd and 'png' in cmd
        assert '--immediate' not in cmd
        assert '--awb' in cmd and 'daylight' in cmd
        assert '--ccm' in cmd
        assert '--rotation' in cmd


def test_set_ccd_exposure_invalid_type(libcamera_client):
    libcamera_client.config['LIBCAMERA'] = {'IMAGE_FILE_TYPE': 'bmp'}
    libcamera_client.night_av[constants.NIGHT_NIGHT] = 1

    with pytest.raises(Exception, match='Invalid image type'):
        libcamera_client.setCcdExposure(1.0, 1.0, 1)


def test_set_ccd_exposure_oserror(libcamera_client):
    with patch('tempfile.NamedTemporaryFile', side_effect=OSError('Disk error')), \
         patch('subprocess.Popen') as mock_popen:
        libcamera_client.setCcdExposure(1.0, 1.0, 1)
        mock_popen.assert_not_called()


def test_set_ccd_exposure_binmode_exception_handled(libcamera_client):
    with patch.object(libcamera_client, '_getBinModeOptions', side_effect=BinModeException('Bad bin')), \
         patch('subprocess.Popen') as mock_popen:
        mock_proc = MagicMock()
        mock_proc.pid = 1234
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        libcamera_client.setCcdExposure(1.0, 1.0, 99)
        assert mock_popen.called


def test_set_ccd_exposure_sync_success_and_error(libcamera_client):
    with patch('subprocess.Popen') as mock_popen, \
         patch.object(libcamera_client, '_processMetadata') as mock_proc_meta, \
         patch.object(libcamera_client, '_queueImage') as mock_queue:
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout.readlines.return_value = ['Error line 1', 'Error line 2']
        mock_popen.return_value = mock_proc

        libcamera_client.setCcdExposure(1.0, 1.0, 1, sync=True)
        assert libcamera_client.active_exposure is False
        mock_proc_meta.assert_called_once()
        mock_queue.assert_called_once()


def test_set_ccd_exposure_sync_timeout(libcamera_client):
    with patch('subprocess.Popen') as mock_popen:
        mock_proc = MagicMock()
        mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd='cmd', timeout=1.0)
        mock_popen.return_value = mock_proc

        with pytest.raises(TimeOutException, match='Timeout waiting for exposure'):
            libcamera_client.setCcdExposure(1.0, 1.0, 1, sync=True, timeout=1.0)


def test_get_ccd_exposure_status_running_and_finished(libcamera_client):
    # Process running
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    libcamera_client.libcamera_process = mock_proc

    ready, state = libcamera_client.getCcdExposureStatus()
    assert ready is False
    assert state == 'BUSY'

    # Process finished and active_exposure was True
    mock_proc.poll.return_value = 0
    mock_proc.returncode = 0
    libcamera_client.active_exposure = True
    with patch.object(libcamera_client, '_processMetadata') as mock_meta, \
         patch.object(libcamera_client, '_queueImage') as mock_queue:
        ready, state = libcamera_client.getCcdExposureStatus()
        assert ready is True
        assert state == 'READY'
        assert libcamera_client.active_exposure is False
        mock_meta.assert_called_once()
        mock_queue.assert_called_once()

    # Process finished with error code
    mock_proc.returncode = 2
    mock_proc.stdout.readlines.return_value = ['Capture failed']
    libcamera_client.active_exposure = True
    with patch.object(libcamera_client, '_processMetadata'), \
         patch.object(libcamera_client, '_queueImage'):
        ready, state = libcamera_client.getCcdExposureStatus()
        assert ready is True
        assert state == 'READY'


def test_process_metadata_full(libcamera_client, tmp_path):
    meta_file = tmp_path / 'metadata.json'
    metadata_data = {
        'AnalogueGain': 2.5,
        'DigitalGain': 1.0,
        'SensorTemperature': 35.4,
        'ColourGains': [1.8, 2.1],
        'SensorBlackLevels': [4096, 4096, 4096, 4096],
    }
    meta_file.write_text(json.dumps(metadata_data))
    libcamera_client.current_metadata_file_p = meta_file

    # Night mode with AWB enabled
    libcamera_client.night_av[constants.NIGHT_NIGHT] = 1
    libcamera_client.config['LIBCAMERA']['AWB_ENABLE'] = True

    libcamera_client._processMetadata()
    assert libcamera_client.ccd_temp == 35.4
    assert libcamera_client._awb_gains == [1.8, 2.1]
    assert libcamera_client._black_level == 4096
    assert not meta_file.exists()


def test_process_metadata_day_and_errors(libcamera_client, tmp_path):
    # Day mode with AWB enabled
    meta_file = tmp_path / 'metadata_day.json'
    metadata_data = {
        'AnalogueGain': 'invalid',
        'DigitalGain': 'invalid',
        'SensorTemperature': 'invalid',
        'ColourGains': [],  # will trigger IndexError
        'SensorBlackLevels': [],  # will trigger IndexError
    }
    meta_file.write_text(json.dumps(metadata_data))
    libcamera_client.current_metadata_file_p = meta_file
    libcamera_client.night_av[constants.NIGHT_NIGHT] = 0
    libcamera_client.config['LIBCAMERA']['AWB_ENABLE_DAY'] = True

    libcamera_client._processMetadata()
    assert libcamera_client._awb_gains is None
    assert libcamera_client._black_level is None


def test_process_metadata_exceptions(libcamera_client, tmp_path):
    # Non-existent file (FileNotFoundError)
    libcamera_client.current_metadata_file_p = tmp_path / 'nonexistent.json'
    libcamera_client._processMetadata()

    # Invalid JSON (JSONDecodeError)
    bad_json = tmp_path / 'bad.json'
    bad_json.write_text('{invalid json')
    libcamera_client.current_metadata_file_p = bad_json
    libcamera_client._processMetadata()

    # PermissionError
    with patch('io.open', side_effect=PermissionError('Denied')):
        libcamera_client.current_metadata_file_p = bad_json
        libcamera_client._processMetadata()


def test_abort_ccd_exposure(libcamera_client, tmp_path):
    mock_proc = MagicMock()
    # Process running initially, then terminates
    poll_results = [None, None, 0]
    mock_proc.poll.side_effect = lambda: poll_results.pop(0) if poll_results else 0
    libcamera_client.libcamera_process = mock_proc

    img_f = tmp_path / 'exp.jpg'
    img_f.write_text('dummy')
    meta_f = tmp_path / 'meta.json'
    meta_f.write_text('dummy')

    libcamera_client.current_exposure_file_p = img_f
    libcamera_client.current_metadata_file_p = meta_f

    libcamera_client.abortCcdExposure()
    assert libcamera_client.active_exposure is False
    assert mock_proc.terminate.called
    assert not img_f.exists()
    assert not meta_f.exists()

    # When process won't terminate and needs kill()
    poll_results_kill = [None] * 10
    mock_proc2 = MagicMock()
    mock_proc2.poll.side_effect = lambda: poll_results_kill.pop(0) if poll_results_kill else 0
    libcamera_client.libcamera_process = mock_proc2
    libcamera_client.current_exposure_file_p = None
    libcamera_client.current_metadata_file_p = None

    libcamera_client.abortCcdExposure()
    assert mock_proc2.kill.called


def test_queue_image(libcamera_client, tmp_path):
    libcamera_client.current_exposure_file_p = tmp_path / 'image.jpg'
    libcamera_client.exposure = 2.0
    libcamera_client.gain = 10.0
    libcamera_client.binning = 1
    libcamera_client.sqm_exposure = True
    libcamera_client.exposureStartTime = 1000.0
    libcamera_client.camera_id = 0
    libcamera_client._black_level = 256
    libcamera_client._awb_gains = [1.5, 2.0]

    libcamera_client._queueImage()
    job = libcamera_client.image_q.get(timeout=1.0)
    assert job['exposure'] == 2.0
    assert job['gain'] == 10.0
    assert job['sqm_exposure'] is True
    assert job['libcamera_black_level'] == 256
    assert job['libcamera_awb_gains'] == [1.5, 2.0]


def test_libcamera_process_running_none(libcamera_client):
    libcamera_client.libcamera_process = None
    assert libcamera_client._libCameraProcessRunning() is False


def test_abort_ccd_exposure_file_not_found(libcamera_client):
    libcamera_client.libcamera_process = None
    libcamera_client.current_exposure_file_p = Path('/nonexistent/exposure.jpg')
    libcamera_client.current_metadata_file_p = Path('/nonexistent/metadata.json')
    libcamera_client.abortCcdExposure()
    assert libcamera_client.active_exposure is False


def test_set_ccd_exposure_day_immediate_and_binning(flask_app):
    config = {
        'LIBCAMERA': {
            'CAMERA_ID': 0,
            'IMAGE_FILE_TYPE_DAY': 'jpg',
            'IMMEDIATE_DAY': True,
            'AWB_ENABLE_DAY': False,
        }
    }
    image_q = Queue()
    position_av = Array('d', [0.0] * 5)
    exposure_av = Array('f', [-1.0] * 7)
    gain_av = Array('f', [-1.0] * 10)
    binning_av = Array('i', [1] * 6)
    night_av = Array('i', [0, 0])  # Day

    with patch('shutil.which', return_value='/usr/bin/rpicam-still'):
        cam = IndiClientLibCameraImx477(config, image_q, position_av, exposure_av, gain_av, binning_av, night_av)
        cam.findCcd()

    with patch('subprocess.Popen') as mock_popen:
        mock_proc = MagicMock()
        mock_proc.pid = 1234
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        cam.setCcdExposure(exposure=0.1, gain=1.0, binning=2, sync=False)
        cmd = mock_popen.call_args[0][0]
        assert '--immediate' in cmd
        assert '--awbgains' in cmd
        assert '--mode' in cmd


def test_process_metadata_awb_variations(libcamera_client, tmp_path):
    # 1. Night with KeyError on ColourGains
    meta1 = tmp_path / 'meta1.json'
    meta1.write_text(json.dumps({'SensorTemperature': 20}))
    libcamera_client.current_metadata_file_p = meta1
    libcamera_client.night_av[constants.NIGHT_NIGHT] = 1
    libcamera_client.config['LIBCAMERA']['AWB_ENABLE'] = True
    libcamera_client._processMetadata()
    assert libcamera_client._awb_gains is None

    # 2. Night with IndexError on ColourGains
    meta2 = tmp_path / 'meta2.json'
    meta2.write_text(json.dumps({'SensorTemperature': 20, 'ColourGains': []}))
    libcamera_client.current_metadata_file_p = meta2
    libcamera_client.night_av[constants.NIGHT_NIGHT] = 1
    libcamera_client.config['LIBCAMERA']['AWB_ENABLE'] = True
    libcamera_client._processMetadata()
    assert libcamera_client._awb_gains is None

    # 3. Day with AWB_ENABLE_DAY = False
    meta3 = tmp_path / 'meta3.json'
    meta3.write_text(json.dumps({'SensorTemperature': 20}))
    libcamera_client.current_metadata_file_p = meta3
    libcamera_client.night_av[constants.NIGHT_NIGHT] = 0
    libcamera_client.config['LIBCAMERA']['AWB_ENABLE_DAY'] = False
    libcamera_client._processMetadata()
    assert libcamera_client._awb_gains is None

    # 4. Day with valid ColourGains
    meta4 = tmp_path / 'meta4.json'
    meta4.write_text(json.dumps({'SensorTemperature': 20, 'ColourGains': [1.5, 2.5]}))
    libcamera_client.current_metadata_file_p = meta4
    libcamera_client.night_av[constants.NIGHT_NIGHT] = 0
    libcamera_client.config['LIBCAMERA']['AWB_ENABLE_DAY'] = True
    libcamera_client._processMetadata()
    assert libcamera_client._awb_gains == [1.5, 2.5]

    # 5. Day with KeyError on ColourGains
    meta5 = tmp_path / 'meta5.json'
    meta5.write_text(json.dumps({'SensorTemperature': 20}))
    libcamera_client.current_metadata_file_p = meta5
    libcamera_client.night_av[constants.NIGHT_NIGHT] = 0
    libcamera_client.config['LIBCAMERA']['AWB_ENABLE_DAY'] = True
    libcamera_client._processMetadata()
    assert libcamera_client._awb_gains is None


def test_get_ccd_info_and_unsupported_methods(libcamera_client):
    info = libcamera_client.getCcdInfo()
    assert 'CCD_EXPOSURE' in info
    assert 'CCD_INFO' in info
    assert 'CCD_FRAME' in info
    assert 'CCD_CFA' in info
    assert 'GAIN_INFO' in info
    assert 'BINNING_INFO' in info
    assert 'SERIALNUMBER_INFO' in info

    libcamera_client.enableCcdCooler()
    libcamera_client.disableCcdCooler()
    libcamera_client.setCcdTemperature(-10.0)
    libcamera_client.setCcdScopeInfo(100, 2.8)
    libcamera_client.ccd_temp = 22.5
    assert libcamera_client.getCcdTemperature() == 22.5
