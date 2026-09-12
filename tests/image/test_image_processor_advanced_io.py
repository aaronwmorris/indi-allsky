import ctypes
from datetime import datetime, timezone
import io
from multiprocessing import Array
from pathlib import Path
from unittest.mock import MagicMock, patch
from astropy.io import fits
import cv2
import ephem
import numpy as np
import pytest

from indi_allsky import constants
from indi_allsky.processing import ImageProcessor, ImageData
from indi_allsky.exceptions import BadImage, KeogramMismatchException


class DummyCamera:
    def __init__(self):
        self.id = 1
        self.name = "Test_Camera"
        self.uuid = "12345678-1234-5678-1234-567812345678"
        self.location = "Observatory"
        self.lensFocalLength = 2.5
        self.lensFocalRatio = 1.4
        self.lensImageCircle = 1000
        self.width = 64
        self.height = 64
        self.pixelSize = 2.9
        self.cfa = constants.CFA_RGGB
        self.owner = "Admin"
        self.data = {
            'KPINDEX_CURRENT': 3.5,
            'OVATION_MAX': 50,
            'SMOKE_RATING': 'invalid_legacy_value',  # will trigger ValueError / TypeError
        }


@pytest.fixture
def adv_processor(base_config, tmp_path):
    config = dict(base_config)
    config['VARLIB_FOLDER'] = str(tmp_path / 'varlib')
    config['LOCATION_LATITUDE'] = -34.9285
    config['LOCATION_LONGITUDE'] = 138.6007
    config['LOCATION_ELEVATION'] = 50.0
    config['NIGHT_SUN_ALT_DEG'] = -6.0

    position_av = Array('d', [0.0] * 5)
    exposure_av = Array(ctypes.c_int32, [1000000, 1000000, 0, 1000, 100, 30000000, 5000000])
    gain_av = Array(ctypes.c_int32, [100000, 100000, 0, 0, 100000, 100000, 400000, 50000, 200000, 100000])
    binning_av = Array('i', [1, 1, 1, 2, 1, 1])
    sensors_temp_av = Array('f', [0.0] * 110)
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


def test_properties_and_setters(adv_processor):
    ip = adv_processor
    ip.image = np.full((64, 64, 3), 128, dtype=np.uint8)

    # Shape read-only setter
    ip.shape = (10, 10)
    assert ip.shape == (64, 64, 3)

    # text_color_rgb error branch
    ip.text_color_rgb = [1, 2]  # len != 3
    # text_color_bgr error branch
    ip.text_color_bgr = [1, 2]  # len != 3

    # text_xy error branch and negative coords
    ip.text_xy = [10]  # len != 2
    ip.text_xy = [-10, -20]
    assert ip.text_xy == [64 - 10, 64 - 20]

    # realtime_keogram_trimmed
    ip._keogram_gen = MagicMock()
    ip._keogram_gen.trimEdges.return_value = np.zeros((10, 10), dtype=np.uint8)
    res = ip.realtime_keogram_trimmed
    assert res is not None




def test_debayer_branches(adv_processor):
    ip = adv_processor

    # 1. float32 (-32)
    f32_data = np.array([[-10.0, 100.0], [70000.0, 500.0]], dtype=np.float32)
    hdu = fits.PrimaryHDU(f32_data)
    i_ref = ImageData(
        config=ip.config,
        hdulist=fits.HDUList([hdu]),
        exposure=1.0,
        gain=100.0,
        binning=1,
        exp_date=datetime.now(),
        exp_elapsed=1.0,
        day_date=datetime.now().date(),
        camera_id=1,
        camera_name="Cam",
        camera_uuid="uuid",
        owner="Admin",
        location="Lab",
        image_bitpix=-32,
        image_bayerpat=None,
        target_adu=1000,
    )
    ip.image_list = [i_ref]
    ip.debayer()
    assert i_ref.opencv_data.dtype == np.uint16
    assert i_ref.opencv_data[0, 0] == 0
    assert i_ref.opencv_data[1, 0] == 65535

    # 2. uint32 (32)
    u32_data = np.array([[100, 70000], [200, 300]], dtype=np.uint32)
    hdu32 = fits.PrimaryHDU(u32_data)
    i_ref32 = ImageData(
        config=ip.config,
        hdulist=fits.HDUList([hdu32]),
        exposure=1.0,
        gain=100.0,
        binning=1,
        exp_date=datetime.now(),
        exp_elapsed=1.0,
        day_date=datetime.now().date(),
        camera_id=1,
        camera_name="Cam",
        camera_uuid="uuid",
        owner="Admin",
        location="Lab",
        image_bitpix=32,
        image_bayerpat=None,
        target_adu=1000,
    )
    ip.image_list = [i_ref32]
    ip.debayer()
    assert i_ref32.opencv_data.dtype == np.uint16
    assert i_ref32.opencv_data[0, 1] == 65535

    # 3. Unsupported bitpix
    i_ref32.image_bitpix = 64
    with pytest.raises(Exception, match='Unsupported bit format'):
        ip.debayer()

    # 4. Already RGB 3D data (len == 3)
    rgb_data = np.full((3, 32, 32), 100, dtype=np.uint8)
    hdu_rgb = fits.PrimaryHDU(rgb_data)
    i_ref_rgb = ImageData(
        config=ip.config,
        hdulist=fits.HDUList([hdu_rgb]),
        exposure=1.0,
        gain=100.0,
        binning=1,
        exp_date=datetime.now(),
        exp_elapsed=1.0,
        day_date=datetime.now().date(),
        camera_id=1,
        camera_name="Cam",
        camera_uuid="uuid",
        owner="Admin",
        location="Lab",
        image_bitpix=8,
        image_bayerpat=None,
        target_adu=1000,
    )
    ip.image_list = [i_ref_rgb]
    ip.debayer()
    assert i_ref_rgb.opencv_data.shape == (32, 32, 3)

    # 5. Bayer patterns: NIGHT_GRAYSCALE and DAYTIME_GRAYSCALE and CFA_PATTERN override
    bayer_data = np.full((32, 32), 100, dtype=np.uint8)
    hdu_bayer = fits.PrimaryHDU(bayer_data)
    i_ref_b = ImageData(
        config=ip.config,
        hdulist=fits.HDUList([hdu_bayer]),
        exposure=1.0,
        gain=100.0,
        binning=1,
        exp_date=datetime.now(),
        exp_elapsed=1.0,
        day_date=datetime.now().date(),
        camera_id=1,
        camera_name="Cam",
        camera_uuid="uuid",
        owner="Admin",
        location="Lab",
        image_bitpix=8,
        image_bayerpat='RGGB',
        target_adu=1000,
    )
    ip.image_list = [i_ref_b]

    # Night grayscale
    ip.config['NIGHT_GRAYSCALE'] = True
    ip.night_av[constants.NIGHT_NIGHT] = 1
    ip.debayer()
    assert i_ref_b.opencv_data.ndim == 2

    # Daytime grayscale
    ip.config['NIGHT_GRAYSCALE'] = False
    ip.config['DAYTIME_GRAYSCALE'] = True
    ip.night_av[constants.NIGHT_NIGHT] = 0
    ip.debayer()
    assert i_ref_b.opencv_data.ndim == 2

    # CFA_PATTERN override in config
    ip.config['CFA_PATTERN'] = 'GRBG'
    ip.config['DAYTIME_GRAYSCALE'] = False
    ip.debayer()
    assert i_ref_b.opencv_data.ndim == 3


def test_crop_and_white_balance_manual(adv_processor):
    ip = adv_processor
    data = np.full((64, 64, 3), 100, dtype=np.uint8)
    ip.image = data.copy()

    # 1. _crop_image with circle crop
    i_ref = MagicMock(binning=1)
    ip.config['IMAGE_CROP_IMAGE_CIRCLE'] = True
    ip.config['LENS_IMAGE_CIRCLE'] = 40

    # Negative lens offset
    ip.config['LENS_OFFSET_X'] = -5
    ip.config['LENS_OFFSET_Y'] = -5
    cropped_neg = ip._crop_image(i_ref)
    assert cropped_neg.shape[0] > 0

    # Positive lens offset
    ip.config['LENS_OFFSET_X'] = 5
    ip.config['LENS_OFFSET_Y'] = 5
    cropped_pos = ip._crop_image(i_ref)
    assert cropped_pos.shape[0] > 0

    # No crop configured
    ip.config['IMAGE_CROP_IMAGE_CIRCLE'] = False
    ip.config['IMAGE_CROP_ROI'] = None
    assert ip._crop_image(i_ref) is ip.image

    # 2. white_balance_manual_bgr branches
    ip.image = data.copy()
    ip.focus_mode = False
    ip.config['USE_NIGHT_COLOR'] = False
    ip.night_av[constants.NIGHT_NIGHT] = 0
    ip.config['WBB_FACTOR_DAY'] = 1.0
    ip.config['WBG_FACTOR_DAY'] = 1.2
    ip.config['WBR_FACTOR_DAY'] = 1.0
    ip.white_balance_manual_bgr()
    assert ip.image is not None

    ip.night_av[constants.NIGHT_NIGHT] = 1
    ip.config['WBB_FACTOR'] = 1.1
    ip.config['WBG_FACTOR'] = 1.0
    ip.config['WBR_FACTOR'] = 0.9
    ip.white_balance_manual_bgr()
    assert ip.image is not None


def test_astrometric_data_full(adv_processor):
    ip = adv_processor
    ip.position_av[constants.POSITION_LATITUDE] = 0.0
    ip.position_av[constants.POSITION_LONGITUDE] = 0.0
    ip.position_av[constants.POSITION_ELEVATION] = 0.0

    # Test ephem NeverUpError and AlwaysUpError
    with patch('ephem.Observer.next_rising', side_effect=ephem.NeverUpError):
        with patch('ephem.Observer.next_setting', side_effect=ephem.AlwaysUpError):
            ip.update_astrometric_data(datetime.now(tz=timezone.utc))
            assert ip.astrometric_data['sun_next_rise'] == '--:--'

    # Test satellites: ISS, HST, Tiangong next_pass branches
    mock_pass = [ephem.Date(datetime.now(tz=timezone.utc)), 0.0, 0.0, 1.0, 0.0, 0.0]
    with patch.object(ip, 'populateSatelliteData') as mock_sat_pop:
        iss_mock = MagicMock()
        iss_mock.alt = 0.5
        hst_mock = MagicMock()
        hst_mock.alt = -0.5
        tg_mock = MagicMock()
        tg_mock.alt = 0.5
        mock_sat_pop.return_value = {
            'iss': iss_mock,
            'hst': hst_mock,
            'tiangong': tg_mock,
        }
        with patch('ephem.Observer.next_pass', side_effect=ValueError('calc error')):
            ip.update_astrometric_data(datetime.now(tz=timezone.utc))
            assert ip.astrometric_data['iss_next_h'] == 0.0


def test_realtime_keogram(adv_processor, tmp_path):
    ip = adv_processor
    ip.varlib_folder_p = tmp_path
    ip.image = np.full((32, 32, 3), 100, dtype=np.uint8)
    ip._keogram_store_p = tmp_path / "keogram.npy"
    ip._keogram_store_metadata_p = tmp_path / "keogram_meta.npy"

    # 1. Focus mode
    ip.focus_mode = True
    ip.realtimeKeogramUpdate()

    # 2. FileNotFoundError / load error handling
    ip.focus_mode = False
    ip.realtime_keogram_data = None
    # Files missing -> FileNotFoundError caught
    ip.realtimeKeogramUpdate()

    # 3. ValueError / EOFError handling
    ip._keogram_store_p.write_bytes(b'corrupt')
    ip._keogram_store_metadata_p.write_bytes(b'corrupt')
    ip.realtime_keogram_data = None
    ip.realtimeKeogramUpdate()
    assert not ip._keogram_store_p.exists()

    # 4. Save when None vs valid
    ip.realtime_keogram_data = None
    ip.realtimeKeogramDataSave()

    ip.realtime_keogram_data = np.full((32, 10, 3), 100, dtype=np.uint8)
    ip.realtime_keogram_timestamps = [100] * 10
    ip.realtimeKeogramDataSave()
    assert ip._keogram_store_p.exists()

    # 5. Successful load
    loaded_data, loaded_meta = ip.realtimeKeogramDataLoad()
    assert loaded_data.shape == (32, 10, 3)

    # 6. KeogramMismatchException unlinks store
    with patch.object(ip._keogram_gen, 'processImage', side_effect=KeogramMismatchException('Mismatch')):
        ip.realtimeKeogramUpdate()
        assert not ip._keogram_store_p.exists()

    # 7. max_entries pruning
    ip.config['REALTIME_KEOGRAM'] = {'MAX_ENTRIES': 5}
    ip.realtime_keogram_data = np.full((32, 10, 3), 100, dtype=np.uint8)
    ip.realtime_keogram_timestamps = list(range(10))
    ip.realtimeKeogramUpdate()
    assert ip.realtime_keogram_data.shape[1] <= 6
    assert len(ip.realtime_keogram_timestamps) <= 6

    # 8. applyLabels
    ip._keogram_gen.applyLabels = MagicMock(return_value=ip.image)
    assert ip.realtimeKeogramApplyLabels(ip.image) is ip.image


def test_mask_and_overlay_loaders(adv_processor, tmp_path):
    ip = adv_processor

    # 1. _load_detection_mask: nonexistent, not a file, PermissionError, invalid image, binning > 1
    ip.binning_av = [1, 2]
    ip.config['DETECT_MASK'] = str(tmp_path / 'nonexistent.png')
    res_none = ip._load_detection_mask()
    assert res_none[1] is None

    ip.config['DETECT_MASK'] = str(tmp_path)  # directory
    assert ip._load_detection_mask()[1] is None

    invalid_img = tmp_path / 'invalid.png'
    invalid_img.write_bytes(b'not an image')
    ip.config['DETECT_MASK'] = str(invalid_img)
    assert ip._load_detection_mask()[1] is None

    # Valid mask with binning 1 and 2
    valid_mask = tmp_path / 'mask.png'
    cv2.imwrite(str(valid_mask), np.full((32, 32), 128, dtype=np.uint8))
    ip.config['DETECT_MASK'] = str(valid_mask)
    res_valid = ip._load_detection_mask()
    assert res_valid[1].shape == (32, 32)
    assert res_valid[2].shape == (16, 16)

    # 2. _load_logo_overlay: nonexistent, not a file, invalid, binning > 1, dimension mismatch, missing alpha
    dummy_img = np.full((64, 64, 3), 100, dtype=np.uint8)
    ip.config['LOGO_OVERLAY'] = str(tmp_path / 'missing.png')
    assert ip._load_logo_overlay(dummy_img, 1) == (None, None)

    ip.config['LOGO_OVERLAY'] = str(tmp_path)
    assert ip._load_logo_overlay(dummy_img, 1) == (None, None)

    ip.config['LOGO_OVERLAY'] = str(invalid_img)
    assert ip._load_logo_overlay(dummy_img, 1) == (False, None)

    # Missing alpha channel (3 channels only)
    no_alpha = tmp_path / 'no_alpha.png'
    cv2.imwrite(str(no_alpha), np.full((64, 64, 3), 100, dtype=np.uint8))
    ip.config['LOGO_OVERLAY'] = str(no_alpha)
    assert ip._load_logo_overlay(dummy_img, 1) == (False, None)

    # Dimension mismatch
    alpha_img = tmp_path / 'alpha.png'
    cv2.imwrite(str(alpha_img), np.full((32, 32, 4), 100, dtype=np.uint8))
    ip.config['LOGO_OVERLAY'] = str(alpha_img)
    assert ip._load_logo_overlay(dummy_img, 1) == (False, None)

    # Binning > 1
    assert ip._load_logo_overlay(dummy_img, 2) == (False, None)


