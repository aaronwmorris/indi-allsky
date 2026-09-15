import ctypes
from datetime import datetime
from multiprocessing import Array
from unittest.mock import MagicMock, patch
from astropy.io import fits
import cv2
import numpy as np
import pytest

from indi_allsky import constants
from indi_allsky.processing import ImageProcessor, ImageData
from indi_allsky.exceptions import TimeOutException


@pytest.fixture
def ss_processor(base_config, tmp_path):
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
    sensors_user_av = Array('f', [0.0] * 110)
    night_av = Array('i', [1, 0])
    astro_av = Array('f', [0.0] * 10)

    ip = ImageProcessor(
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
    # Mock stacker and sqm
    ip._stacker = MagicMock()
    ip._sqm = MagicMock()
    ip._stretch_o = MagicMock()
    ip._ia_denoise = MagicMock()
    ip._ia_scnr = MagicMock()
    return ip


def make_img_ref(ip, data, exposure=1.0, bitpix=8, binning=1, repair_result=None):
    hdu = fits.PrimaryHDU(data)
    hdulist = fits.HDUList([hdu])
    i_ref = ImageData(
        config=ip.config,
        hdulist=hdulist,
        exposure=exposure,
        gain=100.0,
        binning=binning,
        exp_date=datetime.now(),
        exp_elapsed=exposure,
        day_date=datetime.now().date(),
        camera_id=1,
        camera_name="TestCam",
        camera_uuid="uuid",
        owner="Admin",
        location="Lab",
        image_bitpix=bitpix,
        image_bayerpat='RGGB',
        target_adu=10000,
    )
    i_ref.opencv_data = data
    if repair_result:
        i_ref.asi676mc_repair_result = repair_result
    return i_ref


def test_stack_branches(ss_processor):
    ip = ss_processor
    data = np.full((32, 32, 3), 100, dtype=np.uint8)

    # 1. Focus mode
    ip.focus_mode = True
    i_ref1 = make_img_ref(ip, data)
    ip.image_list = [i_ref1]
    ip.stack()
    assert ip.image is data

    # 2. Excluded from downstream measurements
    ip.focus_mode = False
    i_ref_bad = make_img_ref(ip, data, repair_result={'status': 'excluded'})
    ip.image_list = [i_ref_bad]
    ip.stack()
    assert ip.image is data

    # 3. Stack list len == 1 (e.g. only 1 image in list)
    i_ref2 = make_img_ref(ip, data)
    ip.image_list = [i_ref2]
    ip.stack()
    assert ip.image is data

    # 4. Multiple images in list
    i_ref3 = make_img_ref(ip, data)
    ip.image_list = [i_ref2, i_ref3, None]
    ip._stacker.maximum.return_value = data

    # Unknown bitpix exception
    i_ref2.image_bitpix = 64
    with pytest.raises(Exception, match='Unknown bits per pixel'):
        ip.stack()

    # 16-bit stacking
    i_ref2.image_bitpix = 16
    ip.stack()
    assert ip.image is not None

    # 8-bit stacking with registration and exposure > threshold
    i_ref2.image_bitpix = 8
    i_ref2._exposure = 10.0
    i_ref3._exposure = 10.0
    ip.config['IMAGE_STACK_ALIGN'] = True
    ip.config['EXPOSURE_PERIOD'] = 15.0
    ip._stacker.register.return_value = [data, data]
    with patch('signal.alarm'):
        ip.stack()

    # Registration TimeOutException
    ip._stacker.register.side_effect = TimeOutException('Timed out')
    with patch('signal.alarm'):
        ip.stack()
    ip._stacker.register.side_effect = None

    # Registration bypassed due to low exposure
    i_ref2._exposure = 1.0
    i_ref3._exposure = 1.0
    ip.stack()

    # Invalid stack method AttributeError
    ip.config['IMAGE_STACK_ALIGN'] = False
    ip.stack_method = 'nonexistent_method'
    ip.stack()

    # IMAGE_STACK_SPLIT
    ip.stack_method = 'maximum'
    ip.config['IMAGE_STACK_SPLIT'] = True
    ip.stack()


def test_calculate_8bit_adu_and_sqm(ss_processor):
    ip = ss_processor
    data_color = np.full((32, 32, 3), 128, dtype=np.uint8)
    i_ref = make_img_ref(ip, data_color, bitpix=8)
    ip.image_list = [i_ref]
    ip.image = data_color
    ip._adu_mask_dict = {1: None}

    # First call generates mask and computes ADU for 8-bit color
    adu8 = ip.calculate_8bit_adu()
    assert 120 <= adu8 <= 135

    # 2D mono image
    data_mono = np.full((32, 32), 128, dtype=np.uint8)
    ip.image = data_mono
    adu_mono = ip._calculate_8bit_adu(i_ref)
    assert 120 <= adu_mono <= 135

    # Dimension mismatch notification
    ip._adu_mask_dict = {1: np.zeros((16, 16), dtype=np.uint8)}
    ip._miscDb = MagicMock()
    with pytest.raises(Exception):
        ip._calculate_8bit_adu(i_ref)
    ip._miscDb.addNotification.assert_called_once()

    # 16-bit ADU scaling
    ip._adu_mask_dict = {1: np.full((32, 32), 255, dtype=np.uint8)}
    i_ref.image_bitpix = 16
    ip.max_bit_depth = 12
    ip.image = np.full((32, 32), 2048, dtype=np.uint16)
    adu16 = ip._calculate_8bit_adu(i_ref)
    assert adu16 > 0

    # Unsupported bit depth
    i_ref.image_bitpix = 32
    with pytest.raises(Exception, match='Unsupported bit depth'):
        ip._calculate_8bit_adu(i_ref)

    # calculateJankySqm focus mode vs normal
    ip.focus_mode = True
    ip.calculateJankySqm()
    assert i_ref.sqm_value == 0

    ip.focus_mode = False
    ip._sqm.jSqm.return_value = 19.5
    ip.calculateJankySqm()
    assert i_ref.sqm_value == 19.5

    # _calculateMagnitudeSqm
    ip._sqm.magnitudeSqm.return_value = (20.0, 18.0, 100)
    res = ip._calculateMagnitudeSqm(i_ref)
    assert res == (20.0, 18.0, 100)
    assert ip.camera_sqm_raw_mag == 18.0


def test_denoise_and_scnr(ss_processor):
    ip = ss_processor
    ip.image = np.full((32, 32, 3), 100, dtype=np.uint8)

    # 1. Denoise focus mode
    ip.focus_mode = True
    ip.denoise()

    # 2. Denoise daytime vs night algo
    ip.focus_mode = False
    ip.config['USE_NIGHT_COLOR'] = False
    ip.night_av[constants.NIGHT_NIGHT] = 0
    ip.config['IMAGE_DENOISE_DAY'] = 'gaussian'
    ip._ia_denoise.gaussian = MagicMock(return_value=ip.image)
    ip.denoise()
    ip._ia_denoise.gaussian.assert_called_once()

    # Denoise night
    ip.night_av[constants.NIGHT_NIGHT] = 1
    ip.config['IMAGE_DENOISE'] = 'bilateral'
    ip._ia_denoise.bilateral = MagicMock(return_value=ip.image)
    ip.denoise()
    ip._ia_denoise.bilateral.assert_called_once()

    # Denoise empty / unknown
    ip.config['USE_NIGHT_COLOR'] = True
    ip.config['IMAGE_DENOISE'] = None
    ip.denoise()

    ip.config['IMAGE_DENOISE'] = 'unknown_denoise'
    ip.denoise()

    # 3. SCNR focus mode
    ip.focus_mode = True
    assert ip.scnr() is None

    # SCNR daytime vs night
    ip.focus_mode = False
    ip.config['USE_NIGHT_COLOR'] = False
    ip.night_av[constants.NIGHT_NIGHT] = 0
    ip.config['SCNR_ALGORITHM_DAY'] = 'average_neutral'
    ip._ia_scnr.average_neutral = MagicMock(return_value=ip.image)
    assert ip.scnr() is True
    ip._ia_scnr.average_neutral.assert_called_once()

    # SCNR night
    ip.night_av[constants.NIGHT_NIGHT] = 1
    ip.config['SCNR_ALGORITHM'] = 'maximum_neutral'
    ip._ia_scnr.maximum_neutral = MagicMock(return_value=ip.image)
    assert ip.scnr() is True

    # SCNR empty / unknown
    ip.config['USE_NIGHT_COLOR'] = True
    ip.config['SCNR_ALGORITHM'] = None
    assert ip.scnr() is None

    ip.config['SCNR_ALGORITHM'] = 'unknown_scnr'
    assert ip.scnr() is True


def test_stretch(ss_processor):
    ip = ss_processor
    data = np.full((32, 32, 3), 100, dtype=np.uint8)
    i_ref = make_img_ref(ip, data)
    ip.image_list = [i_ref]
    ip.image = data

    # 1. Focus mode
    ip.focus_mode = True
    ip.stretch()

    # 2. _stretch_o is None
    ip.focus_mode = False
    orig_stretch = ip._stretch_o
    ip._stretch_o = None
    ip.stretch()
    ip._stretch_o = orig_stretch

    # 3. Night moonmode without config
    ip.night_av[constants.NIGHT_NIGHT] = 1
    ip.night_av[constants.NIGHT_MOONMODE] = 1
    ip.config['IMAGE_STRETCH'] = {'MOONMODE': False}
    ip.stretch()

    # 4. Day without DAYTIME
    ip.night_av[constants.NIGHT_NIGHT] = 0
    ip.config['IMAGE_STRETCH'] = {'DAYTIME': False}
    ip.stretch()

    # 5. Day with DAYTIME
    ip.config['IMAGE_STRETCH'] = {'DAYTIME': True, 'SPLIT': True}
    ip._stretch_o.stretch.return_value = np.full((32, 32, 3), 150, dtype=np.uint8)
    ip.stretch()
    assert ip.image is not None


def test_white_balance_and_adjustments(ss_processor):
    ip = ss_processor
    data_color = np.full((32, 32, 3), 100, dtype=np.uint8)
    ip.image = data_color.copy()

    # 1. white_balance_auto_bgr
    # Focus mode
    ip.focus_mode = True
    assert ip.white_balance_auto_bgr() is None

    # Mono image
    ip.focus_mode = False
    ip.image = np.full((32, 32), 100, dtype=np.uint8)
    assert ip.white_balance_auto_bgr() is None

    # Color daytime vs night
    ip.image = data_color.copy()
    ip.config['USE_NIGHT_COLOR'] = False
    ip.night_av[constants.NIGHT_NIGHT] = 0
    ip.config['AUTO_WB_DAY'] = True
    assert ip.white_balance_auto_bgr() is True

    ip.night_av[constants.NIGHT_NIGHT] = 1
    ip.config['AUTO_WB'] = True
    # Test zero-division branch by setting one channel to 0
    ip.image[:, :, 0] = 0
    assert ip.white_balance_auto_bgr() is True

    # 2. white_balance_mtf
    ip.focus_mode = True
    assert ip.white_balance_mtf() is None

    ip.focus_mode = False
    ip.image = np.full((32, 32), 100, dtype=np.uint8)
    assert ip.white_balance_mtf() is None

    ip.image = data_color.copy()
    ip.config['USE_NIGHT_COLOR'] = False
    ip.night_av[constants.NIGHT_NIGHT] = 0
    ip.config['WBB_MTF_MIDTONES'] = 0.5
    ip.config['WBG_MTF_MIDTONES'] = 0.5
    ip.config['WBR_MTF_MIDTONES'] = 0.5
    assert ip.white_balance_mtf() is None  # no action

    ip.night_av[constants.NIGHT_NIGHT] = 1
    ip.config['WBB_MTF_MIDTONES'] = 0.4
    ip.config['WBG_MTF_MIDTONES'] = 0.6
    ip.config['WBR_MTF_MIDTONES'] = 0.3
    # First call builds LUTs
    assert ip.white_balance_mtf() is True
    # Change night mode triggers recalculate LUT
    ip.night_av[constants.NIGHT_NIGHT] = 0
    assert ip.white_balance_mtf() is True

    # 3. saturation_adjust
    ip.focus_mode = True
    assert ip.saturation_adjust() is None

    ip.focus_mode = False
    ip.image = np.full((32, 32), 100, dtype=np.uint8)
    assert ip.saturation_adjust() is None

    ip.image = data_color.copy()
    ip.config['USE_NIGHT_COLOR'] = False
    ip.night_av[constants.NIGHT_NIGHT] = 0
    ip.config['SATURATION_FACTOR_DAY'] = 1.0
    assert ip.saturation_adjust() is None

    ip.night_av[constants.NIGHT_NIGHT] = 1
    ip.config['SATURATION_FACTOR'] = 1.2
    assert ip.saturation_adjust() is True

    # 4. contrast_clahe
    ip.focus_mode = True
    ip.contrast_clahe()

    ip.focus_mode = False
    ip.image = np.full((32, 32), 100, dtype=np.uint8)
    ip.contrast_clahe()
    assert ip.image.shape == (32, 32)

    ip.image = data_color.copy()
    ip.contrast_clahe()
    assert ip.image.shape == (32, 32, 3)

    # 5. contrast_clahe_16bit
    ip.focus_mode = True
    ip.contrast_clahe_16bit()

    ip.focus_mode = False
    ip.image = np.full((32, 32), 100, dtype=np.uint8)
    ip.contrast_clahe_16bit()

    ip.image = data_color.copy()
    ip.max_bit_depth = 8
    ip.contrast_clahe_16bit()

    ip.max_bit_depth = 12
    ip.image = np.full((32, 32, 3), 1000, dtype=np.uint16)
    ip.contrast_clahe_16bit()

    # 6. apply_gamma_correction
    ip.focus_mode = True
    assert ip.apply_gamma_correction() is None

    ip.focus_mode = False
    ip.config['USE_NIGHT_COLOR'] = False
    ip.night_av[constants.NIGHT_NIGHT] = 0
    ip.config['GAMMA_CORRECTION_DAY'] = 1.0
    assert ip.apply_gamma_correction() is None

    ip.night_av[constants.NIGHT_NIGHT] = 1
    ip.config['GAMMA_CORRECTION'] = 1.5
    ip.image = data_color.copy()
    assert ip.apply_gamma_correction() is True
    # Re-call uses cached LUT
    assert ip.apply_gamma_correction() is True

    # 7. sharpen
    ip.focus_mode = True
    assert ip.sharpen() is None

    ip.focus_mode = False
    ip.config['USE_NIGHT_COLOR'] = False
    ip.night_av[constants.NIGHT_NIGHT] = 0
    ip.config['SHARPEN_AMOUNT_DAY'] = 0.0
    assert ip.sharpen() is None

    ip.night_av[constants.NIGHT_NIGHT] = 1
    ip.config['SHARPEN_AMOUNT'] = 0.5
    ip.image = data_color.copy()
    assert ip.sharpen() is True

    # 8. colorize
    ip.image = data_color.copy()
    ip.colorize()  # already color, returns

    ip.image = np.full((32, 32), 100, dtype=np.uint8)
    ip.colorize()
    assert ip.image.ndim == 3


def test_masks_logos_scaling_and_splitscreen(ss_processor, tmp_path):
    ip = ss_processor
    data_color = np.full((64, 64, 3), 100, dtype=np.uint8)
    ip.image = data_color.copy()

    # 1. apply_image_circle_mask disabled vs enabled
    ip.config['IMAGE_CIRCLE_MASK'] = {'ENABLE': False}
    ip.apply_image_circle_mask(1)

    ip.config['IMAGE_CIRCLE_MASK'] = {
        'ENABLE': True,
        'OUTLINE': True,
        'OPACITY': 50,
        'DIAMETER': 40,
        'BLUR': 3,
    }
    ip.apply_image_circle_mask(1)

    # 2. apply_logo_overlay
    # Empty config
    ip.config['LOGO_OVERLAY'] = ''
    ip.apply_logo_overlay(1)

    # Already failed
    ip._overlay_dict[1] = False
    ip.apply_logo_overlay(1)

    # Valid logo
    logo_path = tmp_path / "logo.png"
    logo_data = np.full((64, 64, 4), 200, dtype=np.uint8)
    cv2.imwrite(str(logo_path), logo_data)
    ip.config['LOGO_OVERLAY'] = str(logo_path)
    ip._overlay_dict[1] = None
    ip.apply_logo_overlay(1)

    # 3. scale_image
    ip.focus_mode = True
    assert ip.scale_image() is None

    ip.focus_mode = False
    ip.config['IMAGE_SCALE'] = 100
    assert ip.scale_image() is None

    ip.config['IMAGE_SCALE'] = 50
    ip.image = data_color.copy()
    assert ip.scale_image() is True
    assert ip.image.shape == (32, 32, 3)

    # 4. splitscreen flip_h True vs False
    d1 = np.full((32, 32, 3), 50, dtype=np.uint8)
    d2 = np.full((32, 32, 3), 150, dtype=np.uint8)
    ip.config['IMAGE_FLIP_H'] = True
    split1 = ip.splitscreen(d1, d2)
    assert split1.shape == (32, 32, 3)

    ip.config['IMAGE_FLIP_H'] = False
    split2 = ip.splitscreen(d1, d2)
    assert split2.shape == (32, 32, 3)
