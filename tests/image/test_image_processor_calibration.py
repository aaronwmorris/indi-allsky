import ctypes
from datetime import datetime
from multiprocessing import Array
from pathlib import Path
from unittest.mock import MagicMock, patch
from astropy.io import fits
import cv2
import numpy as np
import pytest

from indi_allsky import constants
from indi_allsky.processing import ImageProcessor, ImageData
from indi_allsky.exceptions import CalibrationNotFound


@pytest.fixture
def calib_processor(base_config, tmp_path):
    config = dict(base_config)
    config['VARLIB_FOLDER'] = str(tmp_path)
    config['LOCATION_LATITUDE'] = -34.9285
    config['LOCATION_LONGITUDE'] = 138.6007
    config['LOCATION_ELEVATION'] = 50.0
    config['NIGHT_SUN_ALT_DEG'] = -6.0

    position_av = Array('d', [0.0] * 5)
    exposure_av = Array(ctypes.c_int32, [1000000, 1000000, 0, 1000, 100, 30000000, 5000000])
    gain_av = Array(ctypes.c_int32, [100000, 100000, 0, 0, 100000, 100000, 400000, 50000, 200000, 100000])
    binning_av = Array('i', [1, 1, 1, 2, 1, 1])
    sensors_temp_av = Array('f', [0.0] * 110)
    sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP] = 10.0
    sensors_user_av = Array('f', [0.0] * 110)
    night_av = Array('i', [1, 0])
    astro_av = Array('f', [0.0] * 10)

    return ImageProcessor(
        config=config,
        position_av=position_av,
        exposure_av=exposure_av,
        gain_av=gain_av,
        binning_av=binning_av,
        sensors_temp_av=sensors_temp_av,
        sensors_user_av=sensors_user_av,
        night_av=night_av,
        astro_av=astro_av,
    )


def create_image_data(ip, data, bitpix=16, bayerpat='RGGB'):
    hdu = fits.PrimaryHDU(data)
    hdulist = fits.HDUList([hdu])
    i_ref = ImageData(
        config=ip.config,
        hdulist=hdulist,
        exposure=2.0,
        gain=100.0,
        binning=1,
        exp_date=datetime.now(),
        exp_elapsed=2.0,
        day_date=datetime.now().date(),
        camera_id=1,
        camera_name="TestCam",
        camera_uuid="test-uuid",
        owner="Admin",
        location="Lab",
        image_bitpix=bitpix,
        image_bayerpat=bayerpat,
        target_adu=10000,
    )
    return i_ref


class DummyDbFrame:
    def __init__(self, filepath, filename="dark.fits"):
        self.filepath = filepath
        self.filename = filename

    def getFilesystemPath(self):
        return str(self.filepath)


def test_calibrate_disabled_or_already_calibrated(calib_processor):
    ip = calib_processor
    data = np.full((32, 32), 100, dtype=np.uint16)
    i_ref = create_image_data(ip, data)
    ip.image_list = [i_ref]

    # Disabled
    ip.config['IMAGE_CALIBRATE_DARK'] = False
    ip.calibrate()
    assert i_ref.calibrated is False

    # Already calibrated
    ip.config['IMAGE_CALIBRATE_DARK'] = True
    i_ref.calibrated = True
    ip.calibrate()
    assert i_ref.calibrated is True

    # Successful calibrate() execution
    i_ref.calibrated = False
    with patch.object(ip, '_apply_calibration', return_value=np.full((32, 32), 200, dtype=np.uint16)):
        ip.calibrate()
        assert i_ref.calibrated is True
        assert i_ref.hdulist[0].data[0, 0] == 200



def test_calibrate_fallback_black_level_and_manual_offset(calib_processor):
    ip = calib_processor
    data = np.full((32, 32), 500, dtype=np.uint16)
    i_ref = create_image_data(ip, data)
    ip.image_list = [i_ref]

    # CalibrationNotFound with libcamera_raw and libcamera_black_level
    ip.libcamera_raw = True
    ip.max_bit_depth = 12
    with patch.object(ip, '_apply_calibration', side_effect=CalibrationNotFound('No dark')):
        ip.calibrate(libcamera_black_level=2048)
        assert i_ref.calibrated is True
        assert np.all(i_ref.hdulist[0].data < 500)

    # CalibrationNotFound with manual_offset
    ip.libcamera_raw = False
    i_ref.calibrated = False
    i_ref.hdulist[0].data = np.full((32, 32), 500, dtype=np.uint16)
    ip.config['IMAGE_CALIBRATE_MANUAL_OFFSET'] = 4096
    with patch.object(ip, '_apply_calibration', side_effect=CalibrationNotFound('No dark')):
        ip.calibrate()
        assert np.all(i_ref.hdulist[0].data < 500)


def make_mock_query(first_result):
    mock_q = MagicMock()
    mock_q.filter.return_value = mock_q
    mock_q.order_by.return_value = mock_q
    if isinstance(first_result, (list, tuple)):
        mock_q.first.side_effect = list(first_result)
    else:
        mock_q.first.return_value = first_result
    return mock_q


def test_apply_calibration_bpm_and_dark_queries(calib_processor, tmp_path):
    ip = calib_processor
    data = np.full((32, 32), 500, dtype=np.uint16)
    i_ref = create_image_data(ip, data)

    dark_file = tmp_path / "dark.fits"
    dark_data = np.full((32, 32), 50, dtype=np.uint16)
    fits.writeto(str(dark_file), dark_data)
    dummy_dark = DummyDbFrame(dark_file, "dark.fits")

    bpm_file = tmp_path / "bpm.fits"
    bpm_data = np.full((32, 32), 10, dtype=np.uint16)
    fits.writeto(str(bpm_file), bpm_data)
    dummy_bpm = DummyDbFrame(bpm_file, "bpm.fits")

    # 1. BPM enabled, temp match found, dark temp match found
    ip.config['IMAGE_CALIBRATE_BPM'] = True
    with patch('indi_allsky.flask.models.IndiAllSkyDbBadPixelMapTable.query', make_mock_query(dummy_bpm)), \
         patch('indi_allsky.flask.models.IndiAllSkyDbDarkFrameTable.query', make_mock_query(dummy_dark)):
        out = ip._apply_calibration(i_ref)
        assert out.shape == (32, 32)
        assert out.dtype == np.uint16

    # 2. BPM fallback query (temp match None, fallback returns None)
    with patch('indi_allsky.flask.models.IndiAllSkyDbBadPixelMapTable.query', make_mock_query([None, None])), \
         patch('indi_allsky.flask.models.IndiAllSkyDbDarkFrameTable.query', make_mock_query(dummy_dark)):
        out = ip._apply_calibration(i_ref)
        assert out.shape == (32, 32)

    # 3. Dark fallback query (temp match None, fallback returns None -> CalibrationNotFound)
    ip.config['IMAGE_CALIBRATE_BPM'] = False
    with patch('indi_allsky.flask.models.IndiAllSkyDbDarkFrameTable.query', make_mock_query([None, None])):
        with pytest.raises(CalibrationNotFound, match='Dark not found'):
            ip._apply_calibration(i_ref)

    # 4. BPM file missing
    ip.config['IMAGE_CALIBRATE_BPM'] = True
    missing_bpm = DummyDbFrame(tmp_path / "nonexistent_bpm.fits", "nonexistent_bpm.fits")
    with patch('indi_allsky.flask.models.IndiAllSkyDbBadPixelMapTable.query', make_mock_query(missing_bpm)), \
         patch('indi_allsky.flask.models.IndiAllSkyDbDarkFrameTable.query', make_mock_query(dummy_dark)):
        out = ip._apply_calibration(i_ref)
        assert out.shape == (32, 32)

    # 5. Dark file missing -> CalibrationNotFound
    ip.config['IMAGE_CALIBRATE_BPM'] = False
    missing_dark = DummyDbFrame(tmp_path / "nonexistent_dark.fits", "nonexistent_dark.fits")
    with patch('indi_allsky.flask.models.IndiAllSkyDbDarkFrameTable.query', make_mock_query(missing_dark)):
        with pytest.raises(CalibrationNotFound, match='Dark file missing'):
            ip._apply_calibration(i_ref)

    # 6. Dark shape mismatch
    mismatch_dark_file = tmp_path / "dark_mismatch.fits"
    fits.writeto(str(mismatch_dark_file), np.full((16, 16), 50, dtype=np.uint16))
    mismatch_dark = DummyDbFrame(mismatch_dark_file, "dark_mismatch.fits")
    with patch('indi_allsky.flask.models.IndiAllSkyDbDarkFrameTable.query', make_mock_query(mismatch_dark)):
        with pytest.raises(CalibrationNotFound, match='Dark frame calibration dimension mismatch'):
            ip._apply_calibration(i_ref)


def test_apply_calibration_datatypes(calib_processor, tmp_path):
    ip = calib_processor
    dark_file = tmp_path / "dark_generic.fits"
    dummy_dark = DummyDbFrame(dark_file, "dark_generic.fits")

    ip.config['IMAGE_CALIBRATE_BPM'] = False
    ip.config['IMAGE_CALIBRATE_FIX_HOLES'] = True

    # 1. float32
    f32_data = np.full((32, 32), 100.0, dtype=np.float32)
    fits.writeto(str(dark_file), np.full((32, 32), 150.0, dtype=np.float32), overwrite=True)
    i_ref_f32 = create_image_data(ip, f32_data, bitpix=-32)
    with patch('indi_allsky.flask.models.IndiAllSkyDbDarkFrameTable.query', make_mock_query(dummy_dark)):
        out = ip._apply_calibration(i_ref_f32)
        assert out.dtype == np.float32
        assert np.all(out >= 0)

    # 2. uint32
    u32_data = np.full((32, 32), 100, dtype=np.uint32)
    fits.writeto(str(dark_file), np.full((32, 32), 150, dtype=np.uint32), overwrite=True)
    i_ref_u32 = create_image_data(ip, u32_data, bitpix=32)
    with patch('indi_allsky.flask.models.IndiAllSkyDbDarkFrameTable.query', make_mock_query(dummy_dark)):
        out = ip._apply_calibration(i_ref_u32)
        assert out.dtype == np.uint32
        assert np.all(out >= 0)

    # 3. uint16 3D RGB (fits)
    u16_rgb = np.full((3, 32, 32), 500, dtype=np.uint16)
    fits.writeto(str(dark_file), np.full((3, 32, 32), 100, dtype=np.uint16), overwrite=True)
    i_ref_u16_rgb = create_image_data(ip, u16_rgb, bitpix=16)
    with patch('indi_allsky.flask.models.IndiAllSkyDbDarkFrameTable.query', make_mock_query(dummy_dark)):
        out = ip._apply_calibration(i_ref_u16_rgb)
        assert out.shape == (3, 32, 32)
        assert out.dtype == np.uint16

    # 3b. uint16 2D mono with hole mask
    u16_mono = np.full((32, 32), 500, dtype=np.uint16)
    fits.writeto(str(dark_file), np.full((32, 32), 100, dtype=np.uint16), overwrite=True)
    i_ref_u16_mono = create_image_data(ip, u16_mono, bitpix=16)
    with patch('indi_allsky.flask.models.IndiAllSkyDbDarkFrameTable.query', make_mock_query(dummy_dark)):
        out = ip._apply_calibration(i_ref_u16_mono)
        assert out.shape == (32, 32)
        assert i_ref_u16_mono.hole_mask is not None


    # 4. uint8 2D mono
    u8_data = np.full((32, 32), 200, dtype=np.uint8)
    fits.writeto(str(dark_file), np.full((32, 32), 100, dtype=np.uint8), overwrite=True)
    i_ref_u8 = create_image_data(ip, u8_data, bitpix=8)
    with patch('indi_allsky.flask.models.IndiAllSkyDbDarkFrameTable.query', make_mock_query(dummy_dark)):
        out = ip._apply_calibration(i_ref_u8)
        assert out.shape == (32, 32)
        assert i_ref_u8.hole_mask is not None

    # 5. uint8 3D RGB (fits)
    u8_rgb = np.full((3, 32, 32), 200, dtype=np.uint8)
    fits.writeto(str(dark_file), np.full((3, 32, 32), 100, dtype=np.uint8), overwrite=True)
    i_ref_u8_rgb = create_image_data(ip, u8_rgb, bitpix=8)
    with patch('indi_allsky.flask.models.IndiAllSkyDbDarkFrameTable.query', make_mock_query(dummy_dark)):
        out = ip._apply_calibration(i_ref_u8_rgb)
        assert out.shape == (3, 32, 32)
        assert i_ref_u8_rgb.hole_mask is not None

    # 6. Unsupported dtype -> CalibrationNotFound
    int64_data = np.full((32, 32), 100, dtype=np.int64)
    fits.writeto(str(dark_file), np.full((32, 32), 50, dtype=np.int64), overwrite=True)
    i_ref_int64 = create_image_data(ip, int64_data, bitpix=64)
    with patch('indi_allsky.flask.models.IndiAllSkyDbDarkFrameTable.query', make_mock_query(dummy_dark)):
        with pytest.raises(CalibrationNotFound, match='Unknown image data type'):
            ip._apply_calibration(i_ref_int64)


def test_fix_holes_early(calib_processor):
    ip = calib_processor

    # Focus mode
    ip.focus_mode = True
    ip.fix_holes_early()

    # No hole mask
    ip.focus_mode = False
    data = np.full((32, 32), 100, dtype=np.uint16)
    i_ref = create_image_data(ip, data)
    ip.image_list = [i_ref]
    i_ref.hole_mask = None
    ip.fix_holes_early()

    # Too many holes (> 50000)
    i_ref.hole_mask = np.ones((300, 300), dtype=bool)
    ip.fix_holes_early()

    # Mono/bayered holes (center and boundary corner)
    i_ref.hole_mask = np.zeros((32, 32), dtype=bool)
    i_ref.hole_mask[0, 0] = True   # index error fallback
    i_ref.hole_mask[10, 10] = True # normal case

    class SafeArray(np.ndarray):
        def __getitem__(self, idx):
            if isinstance(idx, (int, np.integer)) and idx < 0:
                raise IndexError("Negative index")
            return super().__getitem__(idx)

    i_ref.hdulist[0].data = np.full((32, 32), 100, dtype=np.uint16).view(SafeArray)
    ip.fix_holes_early()

    # RGB 3D holes (center and boundary corner)
    rgb_data = np.full((3, 32, 32), 100, dtype=np.uint8).view(SafeArray)
    i_ref_rgb = create_image_data(ip, np.full((3, 32, 32), 100, dtype=np.uint8), bitpix=8)
    i_ref_rgb.hdulist[0].data = rgb_data
    i_ref_rgb.hole_mask = np.zeros((32, 32), dtype=bool)
    i_ref_rgb.hole_mask[0, 0] = True   # boundary corner
    i_ref_rgb.hole_mask[15, 15] = True # center
    ip.image_list = [i_ref_rgb]
    ip.fix_holes_early()


