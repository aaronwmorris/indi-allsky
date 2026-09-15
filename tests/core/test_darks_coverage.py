import os
import sys
import io
import json
import ctypes
import queue
import tempfile
import subprocess
from pathlib import Path
from multiprocessing import Array, Queue
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from astropy.io import fits
from sqlalchemy.orm.exc import NoResultFound

from indi_allsky.darks import (
    IndiAllSkyDarks,
    IndiAllSkyDarksProcessor,
    IndiAllSkyDarksAverage,
    IndiAllSkyDarksSigmaClip,
)
from indi_allsky.exceptions import (
    CameraException,
    TimeOutException,
    TemperatureException,
    BadImage,
)
from indi_allsky import constants
from indi_allsky.utils import IndiAllSkyExposureUtils
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbDarkFrameTable,
    IndiAllSkyDbBadPixelMapTable,
)


@pytest.fixture
def darks_processor_setup(tmp_path):
    config = {
        'LOCATION_LATITUDE': -34.9285,
        'LOCATION_LONGITUDE': 138.6007,
        'LOCATION_ELEVATION': 50,
        'IMAGE_DIR': str(tmp_path / 'images'),
        'VARLIB_FOLDER': str(tmp_path / 'varlib'),
        'CCD_CONFIG': {
            'NIGHT': {'BINNING': 1},
            'DAY': {'BINNING': 1},
            'MOONMODE': {'BINNING': 1},
        },
    }
    Path(config['IMAGE_DIR']).mkdir(parents=True, exist_ok=True)
    Path(config['VARLIB_FOLDER']).mkdir(parents=True, exist_ok=True)

    exposure_av = Array(ctypes.c_int32, [1000000, 1000000, 0, 1000, 100, 30000000, 5000000])
    gain_av = Array(ctypes.c_int32, [100000, 100000, 0, 0, 100000, 100000, 400000, 50000, 200000, 100000])
    binning_av = Array('i', [1, 1, 1, 2, 1, 1])

    return config, exposure_av, gain_av, binning_av


@pytest.fixture
def darks_instance(base_config, tmp_path):
    """Provide an initialized IndiAllSkyDarks instance with mocked __init__."""
    with patch.object(IndiAllSkyDarks, '__init__', return_value=None):
        darks = IndiAllSkyDarks()
        darks.config = dict(base_config)
        darks.config['CAMERA_INTERFACE'] = 'indi'
        darks._daytime = True
        darks._gain_list = []
        darks._binning = 1
        darks._count = 2
        darks._temp_delta = 5.0
        darks._time_delta = 5
        darks._hotpixel_adu_percent = 90
        darks._reverse = True
        darks._bitmax = 0
        darks._flush_camera_id = 1

        darks.image_q = Queue()
        darks.indiclient = MagicMock()
        darks.camera_id = 1
        darks.camera_name = "MockCamera"
        darks.camera_server = "indi_simulator_ccd"
        darks.ccd_info = {
            'CCD_CFA': {'CFA_TYPE': {'text': 'RGGB'}},
            'CCD_EXPOSURE': {'CCD_EXPOSURE_VALUE': {'min': 0.001, 'max': 60.0}},
            'GAIN_INFO': {'min': 0.0, 'max': 400.0},
            'BINNING_INFO': {'min': 1, 'max': 4},
            'SERIALNUMBER_INFO': {'text': 'MOCK1234'},
            'CCD_FRAME': {'WIDTH': {'max': 64}, 'HEIGHT': {'max': 64}},
            'CCD_INFO': {'CCD_BITSPERPIXEL': {'current': 16}, 'CCD_PIXEL_SIZE': {'current': 3.75}},
        }

        darks.sensor_q = Queue()
        darks.sensor_error_q = Queue()
        darks.sensor_worker = None
        darks.sensor_worker_idx = 0

        darks.indi_config = darks.config.get('INDI_CONFIG_DEFAULTS', {})

        darks.exposure_av = Array(ctypes.c_int32, [-1, -1, -1, -1, -1, -1, -1])
        darks.gain_av = Array(ctypes.c_int32, [-1, -1, -1, -1, -1, -1, -1, -1, -1, -1])
        darks.binning_av = Array('i', [-1, -1, -1, -1, -1, -1])
        darks.sensors_temp_av = Array('f', [0.0 for _ in range(60)])
        darks.sensors_user_av = Array('f', [0.0 for _ in range(110)])
        darks.night_av = Array('i', [-1, 0])
        darks.position_av = Array('f', [
            float(darks.config['LOCATION_LATITUDE']),
            float(darks.config['LOCATION_LONGITUDE']),
            float(darks.config.get('LOCATION_ELEVATION', 300)),
            0.0,
            0.0,
        ])
        darks.astro_av = Array('f', [0.0, 0.0, 0.0])

        darks._miscDb = MagicMock()
        darks._expUtils = IndiAllSkyExposureUtils(darks.config, darks.exposure_av, darks.gain_av, darks.binning_av)
        darks._shutdown = False

        darks.image_dir = tmp_path / "images"
        darks.image_dir.mkdir(parents=True, exist_ok=True)
        darks.darks_dir = darks.image_dir / "darks"
        darks.darks_dir.mkdir(parents=True, exist_ok=True)

        return darks


# ============================================================================
# 1. Initialization and Properties
# ============================================================================

def test_rawpy_import_error():
    import importlib
    orig_import = __builtins__['__import__'] if isinstance(__builtins__, dict) else getattr(__builtins__, '__import__')

    def fake_import(name, *args, **kwargs):
        if name == 'rawpy':
            raise ImportError("No module named 'rawpy'")
        return orig_import(name, *args, **kwargs)

    import indi_allsky.darks as darks_mod
    with patch('builtins.__import__', side_effect=fake_import):
        importlib.reload(darks_mod)
        assert darks_mod.rawpy is None

    # Reload with real or mock rawpy
    mock_rawpy = MagicMock()
    with patch.dict('sys.modules', {'rawpy': mock_rawpy}):
        importlib.reload(darks_mod)
        assert darks_mod.rawpy is not None



def test_init_success(app, base_config):
    with app.app_context():
        mock_cfg_obj = MagicMock()
        mock_cfg_obj.config = base_config
        with patch('indi_allsky.darks.IndiAllSkyConfig', return_value=mock_cfg_obj):
            darks = IndiAllSkyDarks()
            assert darks.count == 10
            assert darks.binning == 1
            assert darks.temp_delta == 5.0
            assert darks.time_delta == 5
            assert darks.daytime is True
            assert darks.reverse is True
            assert darks.bitmax == 0
            assert darks.flush_camera_id == 1
            assert darks.hotpixel_adu_percent == 90
            assert darks.image_dir == Path(base_config['IMAGE_FOLDER']).absolute()
            assert darks.darks_dir == darks.image_dir / 'darks'


def test_init_no_config_found(app):
    with app.app_context():
        with patch('indi_allsky.darks.IndiAllSkyConfig', side_effect=NoResultFound):
            with pytest.raises(SystemExit) as exc_info:
                IndiAllSkyDarks()
            assert exc_info.value.code == 1


def test_init_fallback_image_folder(app, base_config):
    with app.app_context():
        cfg = dict(base_config)
        cfg['IMAGE_FOLDER'] = ''
        mock_cfg_obj = MagicMock()
        mock_cfg_obj.config = cfg
        with patch('indi_allsky.darks.IndiAllSkyConfig', return_value=mock_cfg_obj):
            darks = IndiAllSkyDarks()
            assert darks.image_dir.name == 'images'


def test_darks_properties_accessors(darks_instance):
    # count
    darks_instance.count = "5"
    assert darks_instance.count == 5

    # gain_list: None (logs warning, sleeps)
    with patch('time.sleep') as mock_sleep:
        darks_instance.gain_list = None
        assert mock_sleep.called
        assert darks_instance.gain_list == []

    # gain_list: valid list
    darks_instance.gain_list = [10.1234, 50.555, 20.0]
    assert darks_instance.gain_list == [50.555, 20.0, 10.123]

    # gain_list: invalid value via BadRound raises SystemExit with ValueError
    class BadRound:
        def __round__(self, n):
            return "not_a_float"

    with pytest.raises(SystemExit):
        darks_instance.gain_list = [BadRound()]

    # gain_list: invalid type raises SystemExit
    with pytest.raises(SystemExit):
        darks_instance.gain_list = 12345

    # binning: valid
    darks_instance.binning = 2
    assert darks_instance.binning == 2

    # binning: invalid
    with pytest.raises(AssertionError):
        darks_instance.binning = 0
    with pytest.raises(AssertionError):
        darks_instance.binning = 5

    # temp_delta: abs float
    darks_instance.temp_delta = -3.5
    assert darks_instance.temp_delta == 3.5

    # time_delta: abs int
    darks_instance.time_delta = -15
    assert darks_instance.time_delta == 15

    # bitmax: valid (0, 8, 10, 12, 14, 16)
    for b in (0, 8, 10, 12, 14, 16):
        darks_instance.bitmax = b
        assert darks_instance.bitmax == b
    with pytest.raises(AssertionError):
        darks_instance.bitmax = 7

    # flush_camera_id
    darks_instance.flush_camera_id = "3"
    assert darks_instance.flush_camera_id == 3

    # hotpixel_adu_percent
    darks_instance.hotpixel_adu_percent = "80"
    assert darks_instance.hotpixel_adu_percent == 80

    # daytime
    darks_instance.daytime = 0
    assert darks_instance.daytime is False
    darks_instance.daytime = True
    assert darks_instance.daytime is True

    # reverse
    darks_instance.reverse = 0
    assert darks_instance.reverse is False

    # sigint handler
    darks_instance.sigint_handler_main(None, None)
    assert darks_instance._shutdown is True


# ============================================================================
# 2. Camera Initialization and Clamping
# ============================================================================

def test_initialize_connect_server_failure(darks_instance):
    mock_client = MagicMock()
    mock_client.connectServer.return_value = False
    mock_client.getHost.return_value = "localhost"
    mock_client.getPort.return_value = 7624

    with patch('indi_allsky.camera.indi', return_value=mock_client), patch('time.sleep'):
        with pytest.raises(SystemExit) as exc_info:
            darks_instance._initialize()
        assert exc_info.value.code == 1


def test_initialize_find_ccd_camera_exception(darks_instance):
    mock_client = MagicMock()
    mock_client.connectServer.return_value = True
    mock_client.findCcd.side_effect = CameraException("Device not found")

    with patch('indi_allsky.camera.indi', return_value=mock_client), patch('time.sleep'):
        with pytest.raises(SystemExit) as exc_info:
            darks_instance._initialize()
        assert exc_info.value.code == 1


def test_initialize_no_ccd_detected(darks_instance):
    mock_client = MagicMock()
    mock_client.connectServer.return_value = True
    mock_client.ccd_device = None

    with patch('indi_allsky.camera.indi', return_value=mock_client), patch('time.sleep'):
        with pytest.raises(SystemExit) as exc_info:
            darks_instance._initialize()
        assert exc_info.value.code == 1


def test_initialize_success_with_clamping(darks_instance):
    mock_client = MagicMock()
    mock_client.connectServer.return_value = True
    mock_device = MagicMock()
    mock_device.getDeviceName.return_value = "CCD Simulator"
    mock_device.getDriverExec.return_value = "indi_simulator_ccd"
    mock_client.ccd_device = mock_device
    mock_client.getIndiAllskyCameraName.return_value = "Mock Camera"
    mock_client.getCcdDeviceProperties.return_value = {}
    mock_client.getCcdInfo.return_value = {
        'CCD_CFA': {'CFA_TYPE': {'text': 'RGGB'}},
        'CCD_EXPOSURE': {'CCD_EXPOSURE_VALUE': {'min': 0.0001, 'max': 120.0}},
        'GAIN_INFO': {'min': 10.0, 'max': 200.0},
        'BINNING_INFO': {'min': 1, 'max': 2},
        'SERIALNUMBER_INFO': {'text': 'SN-001'},
        'CCD_FRAME': {'WIDTH': {'max': 128}, 'HEIGHT': {'max': 128}},
        'CCD_INFO': {'CCD_BITSPERPIXEL': {'current': 16}, 'CCD_PIXEL_SIZE': {'current': 2.4}},
    }
    # Exceptions on optional setup steps
    mock_client.disableDebugCcd.side_effect = TimeOutException("Debug not supported")
    mock_client.setCcdFrameType.side_effect = TimeOutException("Frame type not supported")

    # Set config values that will trigger below-min and above-max clamping
    darks_instance.config['CCD_CONFIG']['NIGHT']['GAIN'] = 5.0      # below min (10.0)
    darks_instance.config['CCD_CONFIG']['MOONMODE']['GAIN'] = 300.0 # above max (200.0)
    darks_instance.config['CCD_CONFIG']['DAY']['GAIN'] = 5.0        # below min (10.0)
    darks_instance.config['CAMERA_SQM'] = {'EXPOSURE': 5.0, 'GAIN': 500.0, 'BINNING': 5} # gain above max, bin above max
    darks_instance.config['CCD_CONFIG']['NIGHT']['BINNING'] = 0     # below min (1)
    darks_instance.config['CCD_CONFIG']['MOONMODE']['BINNING'] = 3  # above max (2)
    darks_instance.config['CCD_CONFIG']['DAY']['BINNING'] = 4       # above max (2)
    darks_instance.config['CFA_PATTERN'] = 'RGGB'

    mock_db_camera = MagicMock()
    mock_db_camera.id = 42
    darks_instance._miscDb.addCamera.return_value = mock_db_camera

    with patch('indi_allsky.camera.indi', return_value=mock_client), patch('time.sleep'):
        darks_instance._initialize()

    assert darks_instance.camera_id == 42
    assert darks_instance._expUtils.GAIN_MIN_NIGHT == 10.0
    assert darks_instance._expUtils.GAIN_MAX_MOONMODE == 200.0
    assert darks_instance._expUtils.GAIN_MIN_DAY == 10.0
    assert darks_instance._expUtils.GAIN_SQM == 200.0
    assert darks_instance._expUtils.BINNING_NIGHT == 1
    assert darks_instance._expUtils.BINNING_MOONMODE == 2
    assert darks_instance._expUtils.BINNING_DAY == 2
    assert darks_instance._expUtils.BINNING_SQM == 2


def test_initialize_gain_and_binning_upper_and_lower_bounds(darks_instance):
    mock_client = MagicMock()
    mock_client.connectServer.return_value = True
    mock_device = MagicMock()
    mock_device.getDeviceName.return_value = "CCD Simulator"
    mock_device.getDriverExec.return_value = "indi_simulator_ccd"
    mock_client.ccd_device = mock_device
    mock_client.getIndiAllskyCameraName.return_value = "Mock Camera"
    mock_client.getCcdDeviceProperties.return_value = {}
    mock_client.getCcdInfo.return_value = {
        'CCD_CFA': {'CFA_TYPE': {'text': 'RGGB'}},
        'CCD_EXPOSURE': {'CCD_EXPOSURE_VALUE': {'min': 0.001, 'max': 60.0}},
        'GAIN_INFO': {'min': 20.0, 'max': 100.0},
        'BINNING_INFO': {'min': 1, 'max': 4},
        'CCD_FRAME': {'WIDTH': {'max': 64}, 'HEIGHT': {'max': 64}},
        'CCD_INFO': {'CCD_BITSPERPIXEL': {'current': 16}, 'CCD_PIXEL_SIZE': {'current': 3.75}},
    }

    # Alternate branch: night gain > max, moonmode < min, day > max, sqm < min
    darks_instance.config['CCD_CONFIG']['NIGHT']['GAIN'] = 150.0
    darks_instance.config['CCD_CONFIG']['MOONMODE']['GAIN'] = 10.0
    darks_instance.config['CCD_CONFIG']['DAY']['GAIN'] = 120.0
    darks_instance.config['CAMERA_SQM'] = {'EXPOSURE': 2.0, 'GAIN': 5.0, 'BINNING': 0}
    darks_instance.config['CCD_CONFIG']['NIGHT']['BINNING'] = 10
    darks_instance.config['CCD_CONFIG']['MOONMODE']['BINNING'] = 0
    darks_instance.config['CCD_CONFIG']['DAY']['BINNING'] = 0
    darks_instance.config.pop('CFA_PATTERN', None)

    mock_db_camera = MagicMock()
    mock_db_camera.id = 10
    darks_instance._miscDb.addCamera.return_value = mock_db_camera

    with patch('indi_allsky.camera.indi', return_value=mock_client), patch('time.sleep'):
        darks_instance._initialize()

    assert darks_instance._expUtils.GAIN_MIN_NIGHT == 100.0
    assert darks_instance._expUtils.GAIN_MIN_MOONMODE == 20.0
    assert darks_instance._expUtils.GAIN_MAX_DAY == 100.0
    assert darks_instance._expUtils.GAIN_SQM == 20.0
    assert darks_instance._expUtils.BINNING_NIGHT == 4
    assert darks_instance._expUtils.BINNING_MOONMODE == 1
    assert darks_instance._expUtils.BINNING_DAY == 1
    assert darks_instance._expUtils.BINNING_SQM == 1


def test_initialize_gain_and_binning_within_bounds(darks_instance):
    mock_client = MagicMock()
    mock_client.connectServer.return_value = True
    mock_device = MagicMock()
    mock_device.getDeviceName.return_value = "CCD Simulator"
    mock_device.getDriverExec.return_value = "indi_simulator_ccd"
    mock_client.ccd_device = mock_device
    mock_client.getIndiAllskyCameraName.return_value = "Mock Camera"
    mock_client.getCcdDeviceProperties.return_value = {}
    mock_client.getCcdInfo.return_value = {
        'CCD_CFA': {'CFA_TYPE': {'text': 'RGGB'}},
        'CCD_EXPOSURE': {'CCD_EXPOSURE_VALUE': {'min': 0.001, 'max': 60.0}},
        'GAIN_INFO': {'min': 0.0, 'max': 400.0},
        'BINNING_INFO': {'min': 1, 'max': 4},
        'CCD_FRAME': {'WIDTH': {'max': 64}, 'HEIGHT': {'max': 64}},
        'CCD_INFO': {'CCD_BITSPERPIXEL': {'current': 16}, 'CCD_PIXEL_SIZE': {'current': 3.75}},
    }

    # Within bounds
    darks_instance.config['CCD_CONFIG']['NIGHT']['GAIN'] = 100.0
    darks_instance.config['CCD_CONFIG']['MOONMODE']['GAIN'] = 100.0
    darks_instance.config['CCD_CONFIG']['DAY']['GAIN'] = 50.0
    darks_instance.config['CAMERA_SQM'] = {'EXPOSURE': 5.0, 'GAIN': 100.0, 'BINNING': 1}
    darks_instance.config['CCD_CONFIG']['NIGHT']['BINNING'] = 1
    darks_instance.config['CCD_CONFIG']['MOONMODE']['BINNING'] = 1
    darks_instance.config['CCD_CONFIG']['DAY']['BINNING'] = 1
    darks_instance.config['CFA_PATTERN'] = 'RGGB'

    mock_db_camera = MagicMock()
    mock_db_camera.id = 15
    darks_instance._miscDb.addCamera.return_value = mock_db_camera

    with patch('indi_allsky.camera.indi', return_value=mock_client), patch('time.sleep'):
        darks_instance._initialize()

    assert darks_instance._expUtils.GAIN_MIN_NIGHT == 100.0
    assert darks_instance._expUtils.GAIN_MIN_MOONMODE == 100.0
    assert darks_instance._expUtils.GAIN_MAX_DAY == 50.0
    assert darks_instance._expUtils.GAIN_SQM == 100.0
    assert darks_instance._expUtils.BINNING_NIGHT == 1
    assert darks_instance._expUtils.BINNING_MOONMODE == 1
    assert darks_instance._expUtils.BINNING_DAY == 1
    assert darks_instance._expUtils.BINNING_SQM == 1


# ============================================================================
# 3. Shooting and Image Handling
# ============================================================================

def test_shoot(darks_instance):
    darks_instance.shoot(2.5, 100.0, 1, sync=True, timeout=30.0)
    darks_instance.indiclient.setCcdExposure.assert_called_once_with(2.5, 100.0, 1, sync=True, timeout=30.0)


def test_wait_for_image_missing_file(darks_instance, tmp_path):
    missing_file = tmp_path / "missing.fit"
    darks_instance.image_q.put({'filename': str(missing_file)})
    with pytest.raises(Exception) as exc_info:
        darks_instance._wait_for_image(1.0)
    assert 'Frame not found' in str(exc_info.value)


def test_wait_for_image_empty_file(darks_instance, tmp_path):
    empty_file = tmp_path / "empty.fit"
    empty_file.write_bytes(b"")
    darks_instance.image_q.put({'filename': str(empty_file)})
    with pytest.raises(Exception) as exc_info:
        darks_instance._wait_for_image(1.0)
    assert 'Frame is empty' in str(exc_info.value)


def test_wait_for_image_valid_fits(darks_instance, tmp_path):
    fit_file = tmp_path / "frame.fit"
    data = np.zeros((32, 32), dtype=np.uint16)
    fits.writeto(fit_file, data)

    darks_instance.image_q.put({'filename': str(fit_file)})
    hdulist = darks_instance._wait_for_image(1.0)

    assert hdulist[0].data.shape == (32, 32)
    assert not fit_file.exists()  # unlinked after reading


def test_wait_for_image_corrupt_fits(darks_instance, tmp_path):
    corrupt_fit = tmp_path / "corrupt.fit"
    corrupt_fit.write_bytes(b"NOT_A_VALID_FITS_HEADER_DATA")

    darks_instance.image_q.put({'filename': str(corrupt_fit)})
    with pytest.raises(BadImage):
        darks_instance._wait_for_image(1.0)
    assert not corrupt_fit.exists()


def test_wait_for_image_jpeg(darks_instance, tmp_path):
    jpg_file = tmp_path / "frame.jpg"
    img_data = np.ones((32, 32, 3), dtype=np.uint8) * 128
    import simplejpeg
    encoded = simplejpeg.encode_jpeg(img_data, quality=90, colorspace='RGB')
    jpg_file.write_bytes(encoded)

    darks_instance.image_q.put({'filename': str(jpg_file)})
    hdulist = darks_instance._wait_for_image(2.0)

    assert hdulist[0].header['IMAGETYP'] == 'Dark Frame'
    assert hdulist[0].header['INSTRUME'] == 'jpeg'
    assert hdulist[0].header['EXPTIME'] == 2.0
    assert not jpg_file.exists()


def test_wait_for_image_jpeg_corrupt(darks_instance, tmp_path):
    jpg_file = tmp_path / "corrupt.jpg"
    jpg_file.write_bytes(b"INVALID_JPEG_DATA_1234567890")

    darks_instance.image_q.put({'filename': str(jpg_file)})
    with pytest.raises(BadImage):
        darks_instance._wait_for_image(1.0)
    assert not jpg_file.exists()


def test_wait_for_image_png(darks_instance, tmp_path):
    import cv2

    # 3-channel PNG
    png_file = tmp_path / "frame.png"
    img_data = np.ones((32, 32, 3), dtype=np.uint8) * 50
    cv2.imwrite(str(png_file), img_data)

    darks_instance.image_q.put({'filename': str(png_file)})
    hdulist = darks_instance._wait_for_image(1.5)

    assert hdulist[0].header['IMAGETYP'] == 'Dark Frame'
    assert hdulist[0].header['INSTRUME'] == 'png'
    assert hdulist[0].header['EXPTIME'] == 1.5
    assert not png_file.exists()

    # 4-channel PNG (RGBA)
    png_rgba = tmp_path / "frame_rgba.png"
    rgba_data = np.ones((32, 32, 4), dtype=np.uint8) * 50
    cv2.imwrite(str(png_rgba), rgba_data)

    darks_instance.image_q.put({'filename': str(png_rgba)})
    hdulist_rgba = darks_instance._wait_for_image(1.5)
    assert not png_rgba.exists()

    # Corrupt PNG
    corrupt_png = tmp_path / "bad.png"
    corrupt_png.write_bytes(b"NOT_A_PNG")
    darks_instance.image_q.put({'filename': str(corrupt_png)})
    with pytest.raises(BadImage):
        darks_instance._wait_for_image(1.0)
    assert not corrupt_png.exists()


def test_wait_for_image_dng(darks_instance, tmp_path):
    dng_file = tmp_path / "frame.dng"
    dng_file.write_bytes(b"DUMMY_DNG")

    # When rawpy is None
    with patch('indi_allsky.darks.rawpy', None):
        darks_instance.image_q.put({'filename': str(dng_file)})
        with pytest.raises(Exception) as exc_info:
            darks_instance._wait_for_image(1.0)
        assert 'rawpy module not available' in str(exc_info.value)

    # When rawpy raises LibRawIOError
    dng_file2 = tmp_path / "bad.dng"
    dng_file2.write_bytes(b"DUMMY_DNG")
    mock_rawpy = MagicMock()
    mock_libraw_err = type('LibRawIOError', (Exception,), {})
    mock_rawpy._rawpy.LibRawIOError = mock_libraw_err
    mock_rawpy.imread.side_effect = mock_libraw_err("Corrupt DNG")

    with patch('indi_allsky.darks.rawpy', mock_rawpy):
        darks_instance.image_q.put({'filename': str(dng_file2)})
        with pytest.raises(BadImage):
            darks_instance._wait_for_image(1.0)
        assert not dng_file2.exists()

    # Valid DNG reading with Bayer pattern from config
    dng_file3 = tmp_path / "good.dng"
    dng_file3.write_bytes(b"DUMMY_DNG")
    mock_raw = MagicMock()
    mock_raw.raw_image = np.zeros((32, 32), dtype=np.uint16)
    mock_rawpy.imread.side_effect = None
    mock_rawpy.imread.return_value = mock_raw

    darks_instance.config['CFA_PATTERN'] = 'GRBG'
    with patch('indi_allsky.darks.rawpy', mock_rawpy):
        darks_instance.image_q.put({'filename': str(dng_file3)})
        hdulist = darks_instance._wait_for_image(3.0)
        assert hdulist[0].header['INSTRUME'] == 'libcamera'
        assert hdulist[0].header['BAYERPAT'] == 'GRBG'
        assert not dng_file3.exists()

    # Valid DNG reading fallback to ccd_info BAYERPAT
    dng_file4 = tmp_path / "good2.dng"
    dng_file4.write_bytes(b"DUMMY_DNG")
    darks_instance.config.pop('CFA_PATTERN', None)
    darks_instance.ccd_info = {'CCD_CFA': {'CFA_TYPE': {'text': 'BGGR'}}}
    with patch('indi_allsky.darks.rawpy', mock_rawpy):
        darks_instance.image_q.put({'filename': str(dng_file4)})
        hdulist = darks_instance._wait_for_image(3.0)
        assert hdulist[0].header['BAYERPAT'] == 'BGGR'
        assert not dng_file4.exists()


def test_wait_for_image_unsupported_type(darks_instance, tmp_path):
    txt_file = tmp_path / "frame.txt"
    txt_file.write_text("unsupported")
    darks_instance.image_q.put({'filename': str(txt_file)})
    with pytest.raises(Exception) as exc_info:
        darks_instance._wait_for_image(1.0)
    assert 'Unsupported dark frame source' in str(exc_info.value)


# ============================================================================
# 4. Pre-run Tasks & Pre-shoot Reconfigurations
# ============================================================================

def test_pre_run_tasks(darks_instance, tmp_path):
    # Other camera -> no action
    darks_instance.camera_server = 'indi_simulator_ccd'
    darks_instance._pre_run_tasks()

    # indi_rpicam -> throw away exposure
    darks_instance.camera_server = 'indi_rpicam'
    throwaway_file = tmp_path / "throwaway.fit"
    throwaway_file.write_bytes(b"data")
    darks_instance.image_q.put({'filename': str(throwaway_file)})

    with patch.object(darks_instance, 'shoot') as mock_shoot:
        darks_instance._pre_run_tasks()
        mock_shoot.assert_called_once_with(7.0, darks_instance._expUtils.GAIN_MIN_DAY, 1, sync=True, timeout=20.0)
        assert not throwaway_file.exists()

    # indi_rpicam but missing file -> raises Exception
    darks_instance.image_q.put({'filename': str(tmp_path / 'nonexistent.fit')})
    with patch.object(darks_instance, 'shoot'):
        with pytest.raises(Exception) as exc_info:
            darks_instance._pre_run_tasks()
        assert 'Frame not found' in str(exc_info.value)


def test_pre_shoot_reconfigure(darks_instance):
    # ZWO ASI120 on indi_asi_ccd
    darks_instance.camera_server = 'indi_asi_ccd'
    darks_instance.camera_name = 'ZWO CCD ASI120MC'
    darks_instance._pre_shoot_reconfigure()
    darks_instance.indiclient.configureCcdDevice.assert_called_with(darks_instance.indi_config)

    darks_instance.indiclient.configureCcdDevice.reset_mock()

    # ZWO ASI120 on indi_asi_single_ccd
    darks_instance.camera_server = 'indi_asi_single_ccd'
    darks_instance.camera_name = 'ZWO ASI120MM'
    darks_instance._pre_shoot_reconfigure()
    darks_instance.indiclient.configureCcdDevice.assert_called_with(darks_instance.indi_config)

    darks_instance.indiclient.configureCcdDevice.reset_mock()

    # Normal camera -> no call
    darks_instance.camera_server = 'indi_simulator_ccd'
    darks_instance.camera_name = 'CCD Simulator'
    darks_instance._pre_shoot_reconfigure()
    darks_instance.indiclient.configureCcdDevice.assert_not_called()


def test_pre_temperature_action(darks_instance, tmp_path):
    # libcamera interface with file removed early (FileNotFoundError handled)
    darks_instance.config['CAMERA_INTERFACE'] = 'libcamera_picam'
    non_existent = tmp_path / "temp_throwaway_missing.fit"
    darks_instance.image_q.put({'filename': str(non_existent)})

    with patch.object(darks_instance, 'shoot') as mock_shoot:
        darks_instance._pre_temperature_action()
        mock_shoot.assert_called_once_with(0.1, darks_instance._expUtils.GAIN_MIN_DAY, 1, sync=True, timeout=10.0)

    # indi_libcamera_ccd server with FileNotFoundError handled
    darks_instance.config['CAMERA_INTERFACE'] = 'indi'
    darks_instance.camera_server = 'indi_libcamera_ccd'
    darks_instance.image_q.put({'filename': str(non_existent)})
    with patch.object(darks_instance, 'shoot'):
        darks_instance._pre_temperature_action()

    # indi_pylibcamera server with FileNotFoundError handled
    darks_instance.camera_server = 'indi_pylibcamera_ccd'
    darks_instance.image_q.put({'filename': str(non_existent)})
    with patch.object(darks_instance, 'shoot'):
        darks_instance._pre_temperature_action()


# ============================================================================
# 5. Temperature Acquisition and External Temperature Script
# ============================================================================

def test_get_ccd_temperature_normal(darks_instance):
    darks_instance.indiclient.getCcdTemperature.return_value = 24.5
    temp = darks_instance.getCcdTemperature()
    assert temp == 24.5
    assert darks_instance.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP] == pytest.approx(24.5)


def test_get_ccd_temperature_fallback_script(darks_instance, tmp_path):
    darks_instance.indiclient.getCcdTemperature.return_value = -120.0
    script = tmp_path / "temp_script.sh"
    script.write_text("#!/bin/sh\n")
    darks_instance.config['CCD_TEMP_SCRIPT'] = str(script)

    with patch.object(darks_instance, 'getExternalTemperature', return_value=18.2):
        temp = darks_instance.getCcdTemperature()
        assert temp == 18.2
        assert darks_instance.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP] == pytest.approx(18.2)

    # If external script raises TemperatureException, fallback keeps -120.0
    with patch.object(darks_instance, 'getExternalTemperature', side_effect=TemperatureException("error")):
        temp = darks_instance.getCcdTemperature()
        assert temp == -120.0


def test_get_external_temperature_validations(darks_instance, tmp_path):
    non_existent = tmp_path / "missing.sh"
    with pytest.raises(TemperatureException) as exc_info:
        darks_instance.getExternalTemperature(str(non_existent))
    assert 'does not exist' in str(exc_info.value)

    # directory
    dir_path = tmp_path / "subdir"
    dir_path.mkdir()
    with pytest.raises(TemperatureException) as exc_info:
        darks_instance.getExternalTemperature(str(dir_path))
    assert 'is not a file' in str(exc_info.value)

    # empty file
    empty_file = tmp_path / "empty.sh"
    empty_file.write_bytes(b"")
    with pytest.raises(TemperatureException) as exc_info:
        darks_instance.getExternalTemperature(str(empty_file))
    assert 'is empty' in str(exc_info.value)

    # not executable
    non_exec = tmp_path / "non_exec.sh"
    non_exec.write_text("#!/bin/sh\necho test\n")
    non_exec.chmod(0o644)
    with pytest.raises(TemperatureException) as exc_info:
        darks_instance.getExternalTemperature(str(non_exec))
    assert 'is not executable' in str(exc_info.value)


def test_get_external_temperature_execution_paths(darks_instance, tmp_path):
    script = tmp_path / "test_temp.sh"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o755)

    # Process OSError
    with patch('subprocess.Popen', side_effect=OSError("Exec error")):
        with pytest.raises(TemperatureException) as exc:
            darks_instance.getExternalTemperature(str(script))
        assert 'failed to execute' in str(exc.value)

    # Process Timeout
    mock_proc = MagicMock()
    mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=3.0)
    with patch('subprocess.Popen', return_value=mock_proc), patch('time.sleep'):
        with pytest.raises(TemperatureException) as exc:
            darks_instance.getExternalTemperature(str(script))
        assert 'timed out' in str(exc.value)

    # Process non-zero exit code
    mock_proc_fail = MagicMock()
    mock_proc_fail.wait.return_value = None
    mock_proc_fail.returncode = 2
    with patch('subprocess.Popen', return_value=mock_proc_fail):
        with pytest.raises(TemperatureException) as exc:
            darks_instance.getExternalTemperature(str(script))
        assert 'exited abnormally' in str(exc.value)


def test_get_external_temperature_json_parsing(darks_instance, tmp_path):
    script = tmp_path / "valid_script.sh"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o755)

    def make_run(json_content, permission_err=False):
        def fake_popen(cmd, env, **kwargs):
            out_file = env['TEMP_JSON']
            if permission_err:
                Path(out_file).write_text('{"temp": 19.5}')
            elif json_content is not None:
                Path(out_file).write_text(json_content)
            proc = MagicMock()
            proc.wait.return_value = None
            proc.returncode = 0
            return proc
        return fake_popen

    # Valid JSON
    with patch('subprocess.Popen', side_effect=make_run('{"temp": 19.5}')):
        val = darks_instance.getExternalTemperature(str(script))
        assert val == 19.5

    # PermissionError on json read
    orig_io_open = io.open
    def fake_open_perm(*args, **kwargs):
        mode = kwargs.get('mode', args[1] if len(args) > 1 else 'r')
        file = args[0] if args else kwargs.get('file')
        if 'r' in mode and str(file).endswith('.json'):
            raise PermissionError("Cannot read")
        return orig_io_open(*args, **kwargs)

    with patch('subprocess.Popen', side_effect=make_run('{"temp": 19.5}')), \
         patch('io.open', side_effect=fake_open_perm):
        with pytest.raises(TemperatureException) as exc:
            darks_instance.getExternalTemperature(str(script))
        assert 'Cannot read' in str(exc.value)

    # Missing file
    with patch('subprocess.Popen', side_effect=make_run(None)):
        with pytest.raises(TemperatureException):
            darks_instance.getExternalTemperature(str(script))

    # Invalid JSON
    with patch('subprocess.Popen', side_effect=make_run('NOT_JSON')):
        with pytest.raises(TemperatureException) as exc:
            darks_instance.getExternalTemperature(str(script))
        assert 'Error decoding json' in str(exc.value) or 'TemperatureException' in exc.type.__name__

    # Missing temp key
    with patch('subprocess.Popen', side_effect=make_run('{"humidity": 50}')):
        with pytest.raises(TemperatureException) as exc:
            darks_instance.getExternalTemperature(str(script))
        assert 'incorrect data' in str(exc.value)

    # Non-numerical value
    with patch('subprocess.Popen', side_effect=make_run('{"temp": "hot"}')):
        with pytest.raises(TemperatureException) as exc:
            darks_instance.getExternalTemperature(str(script))
        assert 'non-numerical value' in str(exc.value)


# ============================================================================
# 6. Check Available Space & Sensor Worker Lifecycle
# ============================================================================

def test_check_available_space(darks_instance):
    mock_part_tmp = MagicMock()
    mock_part_tmp.mountpoint = '/tmp'
    mock_part_other = MagicMock()
    mock_part_other.mountpoint = '/var'

    # Low space (< 600MB) triggers sleep
    low_usage = MagicMock()
    low_usage.total = 500 * 1024 * 1024  # 500MB
    with patch('psutil.disk_partitions', return_value=[mock_part_other, mock_part_tmp]), \
         patch('psutil.disk_usage', return_value=low_usage), \
         patch('time.sleep') as mock_sleep:
        darks_instance.checkAvailableSpace()
        assert mock_sleep.called

    # PermissionError handled
    with patch('psutil.disk_partitions', return_value=[mock_part_tmp]), \
         patch('psutil.disk_usage', side_effect=PermissionError("Denied")), \
         patch('time.sleep') as mock_sleep:
        mock_sleep.reset_mock()
        darks_instance.checkAvailableSpace()
        assert not mock_sleep.called


def test_darks_sensor_worker_lifecycle(darks_instance):
    # Already alive -> returns immediately
    mock_worker = MagicMock()
    mock_worker.is_alive.return_value = True
    darks_instance.sensor_worker = mock_worker
    darks_instance._startSensorWorker()
    assert darks_instance.sensor_worker_idx == 0

    # Dead worker with error queue items
    mock_worker.is_alive.return_value = False
    mock_error_q = MagicMock()
    mock_error_q.get_nowait.return_value = ("TestError", "Traceback line 1\nTraceback line 2")
    darks_instance.sensor_error_q = mock_error_q
    darks_instance.config['FAN'] = {'CLASSNAME': 'mock_fan', 'LEVEL_DEF': 100, 'THOLD_ENABLE': True}
    darks_instance.config['DEW_HEATER'] = {'CLASSNAME': 'mock_heater', 'LEVEL_DEF': 100, 'THOLD_ENABLE': True}
    darks_instance.config['GENERIC_GPIO'] = {'A_CLASSNAME': 'active'}

    with patch('indi_allsky.sensor.SensorWorker') as mock_sensor_worker_cls:
        new_worker = MagicMock()
        mock_sensor_worker_cls.return_value = new_worker
        darks_instance._startSensorWorker()

        assert darks_instance.config['GENERIC_GPIO']['A_CLASSNAME'] == ''
        assert darks_instance.config['FAN']['LEVEL_DEF'] == 0
        assert darks_instance.config['FAN']['THOLD_ENABLE'] is False
        assert darks_instance.config['DEW_HEATER']['LEVEL_DEF'] == 0
        assert darks_instance.config['DEW_HEATER']['THOLD_ENABLE'] is False
        assert new_worker.start.called

    # Dead worker with empty error queue (exercises queue.Empty)
    darks_instance.sensor_worker = mock_worker
    mock_worker.is_alive.return_value = False
    darks_instance.sensor_error_q = Queue()
    with patch('indi_allsky.sensor.SensorWorker'):
        darks_instance._startSensorWorker()

    # Stop worker
    darks_instance.sensor_worker = new_worker
    new_worker.is_alive.return_value = True
    darks_instance._stopSensorWorker()
    assert new_worker.join.called

    # Stop worker when dead or None
    new_worker.is_alive.return_value = False
    new_worker.join.reset_mock()
    darks_instance._stopSensorWorker()
    assert not new_worker.join.called

    darks_instance.sensor_worker = None
    darks_instance._stopSensorWorker()


# ============================================================================
# 7. Processors & Stacking (Processor Base, Average, SigmaClip)
# ============================================================================

def test_processor_base_repr_str_and_stack(darks_processor_setup, tmp_path):
    config, exp_av, gain_av, bin_av = darks_processor_setup
    proc = IndiAllSkyDarksProcessor(config, exp_av, gain_av, bin_av)

    assert proc.__repr__() is NotImplementedError
    assert proc.__str__() is NotImplementedError

    with pytest.raises(Exception) as exc:
        proc.stack(tmp_path, tmp_path / "out.fit", 1.0, 16)
    assert 'Must be redefined in sub-class' in str(exc.value)


def test_build_bad_pixel_map_all_bitpix_and_rgb(darks_processor_setup, tmp_path):
    config, exp_av, gain_av, bin_av = darks_processor_setup
    proc = IndiAllSkyDarksProcessor(config, exp_av, gain_av, bin_av)
    proc.hotpixel_adu_percent = 50

    fit_dir = tmp_path / "fits_bpm_types"
    fit_dir.mkdir()

    # Unknown bitpix raises
    with pytest.raises(Exception) as exc:
        proc.buildBadPixelMap(fit_dir, tmp_path / "out.fit", 1.0, 24)
    assert 'Unknown bits per pixel' in str(exc.value)

    # 8-bit, 32-bit, -32-bit
    for bitpix, dtype in [(8, np.uint8), (32, np.uint32), (-32, np.float32)]:
        d = np.full((16, 16), 10, dtype=dtype)
        d[2, 2] = 250 if bitpix == 8 else 50000
        f_p = fit_dir / f"frame_{bitpix}.fit"
        fits.writeto(f_p, d, overwrite=True)

        out_f = tmp_path / f"bpm_{bitpix}.fit"
        avg_val, count = proc.buildBadPixelMap(fit_dir, out_f, 1.0, bitpix)
        assert out_f.exists()
        f_p.unlink()

    # RGB (3D) fits BPM
    rgb_dir = tmp_path / "rgb_bpm"
    rgb_dir.mkdir()
    rgb_data = np.zeros((3, 16, 16), dtype=np.uint16)
    rgb_data[0, 5, 5] = 60000
    fits.writeto(rgb_dir / "rgb.fit", rgb_data)

    out_rgb = tmp_path / "bpm_rgb.fit"
    avg_val, count = proc.buildBadPixelMap(rgb_dir, out_rgb, 1.0, 16)
    assert count == 1

    # Warning thresholds (>50000 and 0)
    proc.bitmax = 16
    hot_dir = tmp_path / "hot_bpm"
    hot_dir.mkdir()
    hot_data = np.full((300, 300), 65535, dtype=np.uint16)  # 90,000 hot pixels
    fits.writeto(hot_dir / "hot.fit", hot_data)
    out_hot = tmp_path / "bpm_hot.fit"
    _, count = proc.buildBadPixelMap(hot_dir, out_hot, 1.0, 16)
    assert count == 90000

    zero_dir = tmp_path / "zero_bpm"
    zero_dir.mkdir()
    zero_data = np.zeros((16, 16), dtype=np.uint16)
    fits.writeto(zero_dir / "zero.fit", zero_data)
    out_zero = tmp_path / "bpm_zero.fit"
    _, count = proc.buildBadPixelMap(zero_dir, out_zero, 1.0, 16)
    assert count == 0


def test_average_stacking_types_and_branches(darks_processor_setup, tmp_path):
    config, exp_av, gain_av, bin_av = darks_processor_setup
    stacker = IndiAllSkyDarksAverage(config, exp_av, gain_av, bin_av)

    # Unknown bitpix
    with pytest.raises(Exception) as exc:
        stacker.stack(tmp_path, tmp_path / "out.fit", 1.0, 99)
    assert 'Unknown bits per pixel' in str(exc.value)

    # 8-bit, 32-bit, -32-bit
    test_dir = tmp_path / "avg_types"
    test_dir.mkdir()
    for bitpix, dtype in [(8, np.uint8), (32, np.uint32), (-32, np.float32)]:
        d1 = np.full((16, 16), 50, dtype=dtype)
        d2 = np.full((16, 16), 60, dtype=dtype)
        fits.writeto(test_dir / f"f1_{bitpix}.fit", d1, overwrite=True)
        fits.writeto(test_dir / f"f2_{bitpix}.fit", d2, overwrite=True)

        out_f = tmp_path / f"master_avg_{bitpix}.fit"
        avg_adu, count = stacker.stack(test_dir, out_f, 1.0, bitpix)
        assert out_f.exists()
        (test_dir / f"f1_{bitpix}.fit").unlink()
        (test_dir / f"f2_{bitpix}.fit").unlink()

    # RGB 3D array with hot pixels
    rgb_dir = tmp_path / "rgb_avg"
    rgb_dir.mkdir()
    rgb1 = np.full((3, 16, 16), 30000, dtype=np.uint16)
    rgb2 = np.full((3, 16, 16), 30000, dtype=np.uint16)
    fits.writeto(rgb_dir / "rgb1.fit", rgb1)
    fits.writeto(rgb_dir / "rgb2.fit", rgb2)
    out_rgb = tmp_path / "master_avg_rgb.fit"
    stacker.bitmax = 16
    avg_adu, count = stacker.stack(rgb_dir, out_rgb, 1.0, 16)
    assert count == 256

    # > 50000 hot pixels
    hot_dir = tmp_path / "hot_avg"
    hot_dir.mkdir()
    hot_frame = np.full((300, 300), 50000, dtype=np.uint16)
    fits.writeto(hot_dir / "h1.fit", hot_frame)
    out_hot = tmp_path / "master_avg_hot.fit"
    _, count = stacker.stack(hot_dir, out_hot, 1.0, 16)
    assert count == 90000

    # 0 hot pixels
    cold_dir = tmp_path / "cold_avg"
    cold_dir.mkdir()
    cold_frame = np.full((16, 16), 10, dtype=np.uint16)
    fits.writeto(cold_dir / "c1.fit", cold_frame)
    out_cold = tmp_path / "master_avg_cold.fit"
    _, count = stacker.stack(cold_dir, out_cold, 1.0, 16)
    assert count == 0


def test_sigma_clip_stacking_types_and_branches(darks_processor_setup, tmp_path):
    config, exp_av, gain_av, bin_av = darks_processor_setup
    stacker = IndiAllSkyDarksSigmaClip(config, exp_av, gain_av, bin_av)

    def write_sc_fit(path, data):
        hdu = fits.PrimaryHDU(data)
        hdu.header['BUNIT'] = 'adu'
        hdu.header['EXPTIME'] = 1.0
        hdu.writeto(path, overwrite=True)

    # Unknown bitpix
    with pytest.raises(Exception) as exc:
        stacker.stack(tmp_path, tmp_path / "out.fit", 1.0, 64)
    assert 'Unknown bits per pixel' in str(exc.value)

    # 8-bit, 32-bit, -32-bit
    test_dir = tmp_path / "sc_types"
    test_dir.mkdir()
    for bitpix, dtype in [(8, np.uint8), (32, np.uint32), (-32, np.float32)]:
        for i in range(3):
            d = np.full((16, 16), 40 + i, dtype=dtype)
            write_sc_fit(test_dir / f"f{i}_{bitpix}.fit", d)

        out_f = tmp_path / f"master_sc_{bitpix}.fit"
        avg_adu, count = stacker.stack(test_dir, out_f, 1.0, bitpix)
        assert out_f.exists()
        for i in range(3):
            (test_dir / f"f{i}_{bitpix}.fit").unlink()

    # ValueError handled in combine (e.g., RGB data)
    err_dir = tmp_path / "sc_err"
    err_dir.mkdir()
    write_sc_fit(err_dir / "err.fit", np.zeros((16, 16), dtype=np.uint16))
    with patch('ccdproc.combine', side_effect=ValueError("Cannot combine RGB")):
        with pytest.raises(SystemExit) as exc:
            stacker.stack(err_dir, tmp_path / "err_out.fit", 1.0, 16)
        assert exc.value.code == 1

    # > 50000 hot pixels and 0 hot pixels
    hot_dir = tmp_path / "sc_hot"
    hot_dir.mkdir()
    for i in range(3):
        write_sc_fit(hot_dir / f"h{i}.fit", np.full((300, 300), 50000, dtype=np.uint16))
    out_hot = tmp_path / "master_sc_hot.fit"
    _, count = stacker.stack(hot_dir, out_hot, 1.0, 16)
    assert count == 90000

    cold_dir = tmp_path / "sc_cold"
    cold_dir.mkdir()
    for i in range(3):
        write_sc_fit(cold_dir / f"c{i}.fit", np.full((16, 16), 5, dtype=np.uint16))
    out_cold = tmp_path / "master_sc_cold.fit"
    _, count = stacker.stack(cold_dir, out_cold, 1.0, 16)
    assert count == 0

    # Moderate hot pixel count (between 1 and 50000) with bitmax
    stacker.bitmax = 12
    mod_dir = tmp_path / "sc_mod"
    mod_dir.mkdir()
    for i in range(3):
        d = np.zeros((16, 16), dtype=np.uint16)
        d[5, 5] = 4000
        write_sc_fit(mod_dir / f"m{i}.fit", d)
    out_mod = tmp_path / "master_sc_mod.fit"
    _, count = stacker.stack(mod_dir, out_mod, 1.0, 16)
    assert count == 1


# ============================================================================
# 8. Exposure Taking & Run Workflow
# ============================================================================

def test_take_exposures(darks_instance):
    darks_instance.count = 2
    mock_stacker_cls = MagicMock()
    mock_stacker_instance = MagicMock()
    mock_stacker_cls.return_value = mock_stacker_instance
    mock_stacker_instance.stack.return_value = (150.0, 5)
    mock_stacker_instance.buildBadPixelMap.return_value = (20.0, 2)

    # Return a bad image first, then 2 good images
    hdu1 = fits.PrimaryHDU(np.zeros((32, 32), dtype=np.uint16))
    hdu2 = fits.PrimaryHDU(np.zeros((32, 32), dtype=np.uint16))
    hdulist1 = fits.HDUList([hdu1])
    hdulist2 = fits.HDUList([hdu2])

    with patch.object(darks_instance, '_wait_for_image', side_effect=[BadImage("Bad"), hdulist1, hdulist2]), \
         patch.object(darks_instance, 'shoot'), \
         patch.object(darks_instance, 'getCcdTemperature'):

        # Also mock stat size on darks dir files
        with patch.object(Path, 'stat') as mock_stat:
            mock_stat_res = MagicMock()
            mock_stat_res.st_size = 2048
            mock_stat.return_value = mock_stat_res

            darks_instance._take_exposures(
                exposure=2.0,
                gain=100.0,
                binning=1,
                dark_filename_t='dark_{0:d}_{1:d}bit_{2:d}s_gain{3:d}_bin{4:d}_{5:d}c_{6:s}.fit',
                bpm_filename_t='bpm_{0:d}_{1:d}bit_{2:d}s_gain{3:d}_bin{4:d}_{5:d}c_{6:s}.fit',
                stacking_class=mock_stacker_cls,
            )

            assert darks_instance._miscDb.addBadPixelMap.called
            assert darks_instance._miscDb.addDarkFrame.called


def test_take_exposures_rgb(darks_instance):
    darks_instance.count = 1
    mock_stacker_cls = MagicMock()
    mock_stacker_instance = MagicMock()
    mock_stacker_cls.return_value = mock_stacker_instance
    mock_stacker_instance.stack.return_value = (100.0, 0)
    mock_stacker_instance.buildBadPixelMap.return_value = (10.0, 0)

    # 3D RGB data
    hdu_rgb = fits.PrimaryHDU(np.zeros((3, 32, 32), dtype=np.uint16))
    hdulist_rgb = fits.HDUList([hdu_rgb])

    with patch.object(darks_instance, '_wait_for_image', return_value=hdulist_rgb), \
         patch.object(darks_instance, 'shoot'), \
         patch.object(darks_instance, 'getCcdTemperature'), \
         patch.object(Path, 'stat') as mock_stat:
        mock_stat.return_value.st_size = 4096
        darks_instance._take_exposures(
            exposure=1.0,
            gain=100.0,
            binning=1,
            dark_filename_t='dark_{0:d}_{1:d}bit_{2:d}s_gain{3:d}_bin{4:d}_{5:d}c_{6:s}.fit',
            bpm_filename_t='bpm_{0:d}_{1:d}bit_{2:d}s_gain{3:d}_bin{4:d}_{5:d}c_{6:s}.fit',
            stacking_class=mock_stacker_cls,
        )
        assert darks_instance._miscDb.addDarkFrame.called


def test_run_day_and_night_workflow(darks_instance):
    darks_instance.config['CCD_EXPOSURE_MAX'] = 6
    darks_instance.time_delta = 5
    darks_instance.daytime = True
    darks_instance.reverse = False
    darks_instance.config['CCD_COOLING_DAY'] = True
    darks_instance.config['CCD_TEMP_DAY'] = 30.0
    darks_instance.config['INDI_CONFIG_DAY'] = {'SOME': 'CONFIG'}
    darks_instance.config['CCD_COOLING'] = True
    darks_instance.config['CCD_TEMP'] = 10.0

    # Differentiate day and night configs to trigger day exposures
    darks_instance._expUtils.GAIN_MAX_DAY = 50.0
    darks_instance._expUtils.BINNING_DAY = 2
    darks_instance._expUtils.GAIN_MAX_NIGHT = 100.0
    darks_instance._expUtils.BINNING_NIGHT = 1
    darks_instance._expUtils.GAIN_MAX_MOONMODE = 100.0
    darks_instance._expUtils.BINNING_MOONMODE = 1
    darks_instance._expUtils.GAIN_SQM = 100.0
    darks_instance._expUtils.BINNING_SQM = 1

    with patch.object(darks_instance, '_take_exposures') as mock_take_exp, \
         patch('time.sleep'):
        darks_instance._run(IndiAllSkyDarksAverage)
        # Should execute day exposures and night exposures
        assert mock_take_exp.called
        assert darks_instance.indiclient.enableCcdCooler.called


def test_run_cooling_disabled_and_gain_list(darks_instance):
    darks_instance.config['CCD_EXPOSURE_MAX'] = 2
    darks_instance.time_delta = 5
    darks_instance.daytime = False  # daytime disabled
    darks_instance.gain_list = [200.0, 100.0]
    darks_instance.config['CCD_COOLING'] = False

    with patch.object(darks_instance, '_take_exposures') as mock_take_exp, \
         patch('time.sleep'):
        darks_instance._run(IndiAllSkyDarksAverage)
        assert mock_take_exp.called
        assert darks_instance.indiclient.disableCcdCooler.called


def test_run_day_cooling_disabled_and_shared_params(darks_instance):
    darks_instance.config['CCD_EXPOSURE_MAX'] = 2
    darks_instance.time_delta = 5
    darks_instance.daytime = True
    darks_instance.config['CCD_COOLING_DAY'] = False
    darks_instance.config.pop('INDI_CONFIG_DAY', None)
    darks_instance.config['CCD_COOLING'] = False

    # Day params identical to night params -> hits day_params in night_darks_odict
    darks_instance._expUtils.GAIN_MAX_DAY = 100.0
    darks_instance._expUtils.BINNING_DAY = 1
    darks_instance._expUtils.GAIN_MAX_NIGHT = 100.0
    darks_instance._expUtils.BINNING_NIGHT = 1
    darks_instance._expUtils.GAIN_MAX_MOONMODE = 100.0
    darks_instance._expUtils.BINNING_MOONMODE = 1
    darks_instance._expUtils.GAIN_SQM = 100.0
    darks_instance._expUtils.BINNING_SQM = 1

    with patch.object(darks_instance, '_take_exposures'), patch('time.sleep'):
        darks_instance._run(IndiAllSkyDarksAverage)


def test_run_libcamera_awb_checks(darks_instance):
    darks_instance.config['CAMERA_INTERFACE'] = 'libcamera_picam'
    darks_instance.config['CCD_EXPOSURE_MAX'] = 1
    darks_instance.time_delta = 1

    # Daytime AWB enabled -> disables daytime darks
    darks_instance.config['LIBCAMERA'] = {
        'AWB_ENABLE_DAY': True,
        'AWB_ENABLE': False,
        'IMAGE_FILE_TYPE_DAY': 'dng',
        'IMAGE_FILE_TYPE': 'jpg',
    }
    darks_instance.daytime = True

    with patch.object(darks_instance, '_take_exposures'), patch('time.sleep'):
        darks_instance._run(IndiAllSkyDarksAverage)
        assert darks_instance.daytime is False
        assert darks_instance.indiclient.libcamera_bit_depth == 8

    # Daytime AWB disabled, daytime image file type dng, night image file type dng
    darks_instance.config['LIBCAMERA']['AWB_ENABLE_DAY'] = False
    darks_instance.config['LIBCAMERA']['IMAGE_FILE_TYPE_DAY'] = 'dng'
    darks_instance.config['LIBCAMERA']['IMAGE_FILE_TYPE'] = 'dng'
    darks_instance.daytime = True
    with patch.object(darks_instance, '_take_exposures'), patch('time.sleep'):
        darks_instance._run(IndiAllSkyDarksAverage)
        assert darks_instance.indiclient.libcamera_bit_depth == 16

    # Daytime AWB disabled, daytime image file type jpg, night image file type jpg (bit depth 8)
    darks_instance.config['LIBCAMERA']['IMAGE_FILE_TYPE_DAY'] = 'jpg'
    darks_instance.config['LIBCAMERA']['IMAGE_FILE_TYPE'] = 'jpg'
    darks_instance.daytime = True
    with patch.object(darks_instance, '_take_exposures'), patch('time.sleep'):
        darks_instance._run(IndiAllSkyDarksAverage)
        assert darks_instance.indiclient.libcamera_bit_depth == 8

    # Night AWB enabled -> sys.exit(1)
    darks_instance.config['LIBCAMERA']['AWB_ENABLE'] = True
    with patch('time.sleep'):
        with pytest.raises(SystemExit) as exc:
            darks_instance._run(IndiAllSkyDarksAverage)
        assert exc.value.code == 1


# ============================================================================
# 9. High-Level Workflows (average, sigmaclip, tempaverage, tempsigmaclip)
# ============================================================================

def test_average_and_sigmaclip(app, darks_instance):
    with app.app_context():
        with patch.object(darks_instance, 'checkAvailableSpace') as mock_space, \
             patch.object(darks_instance, '_startSensorWorker') as mock_start, \
             patch.object(darks_instance, '_stopSensorWorker') as mock_stop, \
             patch.object(darks_instance, '_initialize') as mock_init, \
             patch.object(darks_instance, '_pre_run_tasks') as mock_pre, \
             patch.object(darks_instance, '_run') as mock_run:

            darks_instance.average()
            assert mock_space.called
            assert mock_start.called
            assert mock_stop.called
            assert mock_init.called
            assert mock_pre.called
            assert mock_run.called

            mock_run.reset_mock()
            darks_instance.sigmaclip()
            assert mock_run.called


def test_tempaverage_and_tempsigmaclip_loop(app, darks_instance):
    with app.app_context():
        with patch.object(darks_instance, '_initialize'), \
             patch.object(darks_instance, '_pre_run_tasks'), \
             patch.object(darks_instance, '_pre_temperature_action'), \
             patch.object(darks_instance, 'getCcdTemperature') as mock_temp, \
             patch.object(darks_instance, '_run') as mock_run:

            darks_instance.temp_delta = 2.0
            darks_instance.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP] = 20.0

            def fake_temp():
                val = fake_temp.seq[fake_temp.idx]
                fake_temp.idx += 1
                if isinstance(val, BaseException):
                    raise val
                darks_instance.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP] = val
                return val

            # Sequence: initial, loop iteration 1 (temp > thold -> sleep), loop iteration 2 (temp <= thold -> achieves), loop 3 break
            fake_temp.seq = [20.0, 19.5, 17.5, KeyboardInterrupt()]
            fake_temp.idx = 0
            mock_temp.side_effect = fake_temp

            with patch('time.sleep'), pytest.raises(KeyboardInterrupt):
                darks_instance._tempaverage()

            assert darks_instance.daytime is False
            assert mock_run.called

            fake_temp.idx = 0
            with patch('time.sleep'), pytest.raises(KeyboardInterrupt):
                darks_instance._tempsigmaclip()


def test_tempaverage_and_tempsigmaclip_wrappers(app, darks_instance):
    with app.app_context():
        with patch.object(darks_instance, 'checkAvailableSpace') as mock_space, \
             patch.object(darks_instance, '_startSensorWorker') as mock_start, \
             patch.object(darks_instance, '_stopSensorWorker') as mock_stop, \
             patch.object(darks_instance, '_tempaverage') as mock_tempavg, \
             patch.object(darks_instance, '_tempsigmaclip') as mock_tempsc:

            darks_instance.tempaverage()
            assert mock_space.called
            assert mock_start.called
            assert mock_tempavg.called
            assert mock_stop.called
            assert darks_instance.indiclient.disableCcdCooler.called
            assert darks_instance.indiclient.disconnectServer.called

            darks_instance.tempsigmaclip()
            assert mock_tempsc.called


# ============================================================================
# 10. Flush Workflow
# ============================================================================

def test_flush_camera_not_found(app, db, darks_instance):
    with app.app_context():
        darks_instance.flush_camera_id = 999
        with pytest.raises(SystemExit) as exc:
            darks_instance.flush()
        assert exc.value.code == 1


def test_flush_no_dark_frames(app, db, darks_instance):
    with app.app_context():
        cam = IndiAllSkyDbCameraTable(name="CameraWithoutDarks")
        db.session.add(cam)
        db.session.commit()

        darks_instance.flush_camera_id = cam.id
        with pytest.raises(SystemExit) as exc:
            darks_instance.flush()
        assert exc.value.code == 1


def test_flush_success(app, db, darks_instance, tmp_path):
    with app.app_context():
        app.config['INDI_ALLSKY_IMAGE_FOLDER'] = str(tmp_path)
        cam = IndiAllSkyDbCameraTable(name="CameraWithDarks")
        db.session.add(cam)
        db.session.commit()

        bpm_file = tmp_path / "bpm.fit"
        bpm_file.write_bytes(b"bpm_data")
        dark_file = tmp_path / "dark.fit"
        dark_file.write_bytes(b"dark_data")

        bpm_entry = IndiAllSkyDbBadPixelMapTable(
            camera_id=cam.id,
            filename=str(bpm_file),
            bitdepth=16,
            exposure=1,
            gain=100.0,
        )
        dark_entry = IndiAllSkyDbDarkFrameTable(
            camera_id=cam.id,
            filename=str(dark_file),
            bitdepth=16,
            exposure=1,
            gain=100.0,
        )
        db.session.add_all([bpm_entry, dark_entry])
        db.session.commit()

        darks_instance.flush_camera_id = cam.id

        with patch('time.sleep'):
            darks_instance.flush()

        assert not bpm_file.exists()
        assert not dark_file.exists()

        # Database rows removed
        assert IndiAllSkyDbBadPixelMapTable.query.filter_by(camera_id=cam.id).count() == 0
        assert IndiAllSkyDbDarkFrameTable.query.filter_by(camera_id=cam.id).count() == 0
