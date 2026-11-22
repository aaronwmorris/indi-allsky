import numpy as np
import pytest
from unittest.mock import patch, MagicMock

from indi_allsky.denoise import IndiAllskyDenoise
from indi_allsky import constants


def create_denoise(config=None, night=True):
    cfg = config or {}
    night_av = {constants.NIGHT_NIGHT: night}
    return IndiAllskyDenoise(cfg, night_av)


def test_denoise_dtype_max_and_luminance():
    den = create_denoise()

    # _get_dtype_max
    u8 = np.zeros((10, 10), dtype=np.uint8)
    assert den._get_dtype_max(u8) == 255.0
    u16 = np.zeros((10, 10), dtype=np.uint16)
    assert den._get_dtype_max(u16) == 65535.0
    f32 = np.zeros((10, 10), dtype=np.float32)
    assert den._get_dtype_max(f32) == 1.0

    # _compute_luminance
    img_3d = np.full((10, 10, 3), 100, dtype=np.uint8)
    lum_3d = den._compute_luminance(img_3d)
    assert lum_3d.shape == (10, 10)

    img_2d = np.full((10, 10), 100, dtype=np.uint8)
    lum_2d = den._compute_luminance(img_2d)
    assert lum_2d.shape == (10, 10)

    # _local_variance: even vs odd ksize
    var_map_odd = den._local_variance(img_3d, ksize=3)
    assert var_map_odd.shape == (10, 10)
    var_map_even = den._local_variance(img_2d, ksize=4)
    assert var_map_even.shape == (10, 10)

    # _match_luminance
    orig_3d = np.full((20, 20, 3), 100, dtype=np.uint8)
    res_3d = np.full((20, 20, 3), 90, dtype=np.uint8)
    matched_3d = den._match_luminance(orig_3d, res_3d)
    assert matched_3d.shape == (20, 20, 3)

    orig_2d = np.full((20, 20), 100, dtype=np.uint8)
    res_2d = np.full((20, 20), 90, dtype=np.uint8)
    matched_2d = den._match_luminance(orig_2d, res_2d)
    assert matched_2d.shape == (20, 20)

    # _match_luminance low luminance early return (<= 1e-6)
    zero_res = np.zeros((10, 10), dtype=np.uint8)
    assert np.array_equal(den._match_luminance(zero_res, zero_res), zero_res)

    # _match_luminance exception fallback
    with patch('numpy.issubdtype', side_effect=Exception('err')):
        assert np.array_equal(den._match_luminance(orig_2d, res_2d), res_2d)


def test_denoise_star_protection_and_adaptive_blend():
    config = {
        'DENOISE_STAR_PERCENTILE': '95',
        'DENOISE_STAR_SIGMA': '2.0',
        'DENOISE_STAR_FWHM': '3.0',
        'DENOISE_STAR_PROTECT_RADIUS': '2',
        'DENOISE_PROTECT_STARS': True,
        'ADAPTIVE_BLEND': True,
        'LOCAL_STATS_KSIZE': 3,
    }
    den = create_denoise(config, night=True)

    img = np.full((50, 50, 3), 50, dtype=np.uint8)
    # Put bright star
    img[25, 25] = [255, 255, 255]

    # Test _star_mask with 3D and 2D
    mask_3d = den._star_mask(img)
    assert mask_3d.shape == (50, 50)

    mask_2d = den._star_mask(img[:, :, 0])
    assert mask_2d.shape == (50, 50)

    # Test _star_mask exception fallback
    with patch('indi_allsky.protection_masks.star_mask', side_effect=Exception('fail')):
        empty_mask = den._star_mask(img)
        assert np.all(empty_mask == 0)


    # Test _is_star_mask_time
    is_time = den._is_star_mask_time()
    assert isinstance(is_time, bool)

    # Test _apply_star_protection
    denoised = np.full((50, 50, 3), 45, dtype=np.uint8)

    # When daytime: bypass star protection
    with patch.object(den, '_is_star_mask_time', return_value=False):
        prot_day = den._apply_star_protection(img, denoised, 255.0)
        assert np.array_equal(prot_day, denoised)

    # When DENOISE_PROTECT_STARS is False
    den.config['DENOISE_PROTECT_STARS'] = False
    with patch.object(den, '_is_star_mask_time', return_value=True):
        prot_disabled = den._apply_star_protection(img, denoised, 255.0)
        assert np.array_equal(prot_disabled, denoised)

    den.config['DENOISE_PROTECT_STARS'] = True
    # When star mask is empty (all <= 0.01)
    with patch.object(den, '_is_star_mask_time', return_value=True), \
         patch.object(den, '_star_mask', return_value=np.zeros((50, 50), dtype=np.float32)):
        prot_empty = den._apply_star_protection(img, denoised, 255.0)
        assert np.array_equal(prot_empty, denoised)

    # When star mask is active on 3D and 2D
    fake_mask = np.ones((50, 50), dtype=np.float32)
    fake_mask[25, 25] = 0.0  # Star region
    with patch.object(den, '_is_star_mask_time', return_value=True), \
         patch.object(den, '_star_mask', return_value=fake_mask):
        prot_3d = den._apply_star_protection(img, denoised, 255.0)
        assert np.array_equal(prot_3d[25, 25], img[25, 25])  # Star preserved

        prot_2d = den._apply_star_protection(img[:, :, 0], denoised[:, :, 0], 255.0)
        assert prot_2d[25, 25] == img[25, 25, 0]

    # Test _compute_adaptive_blend
    # ADAPTIVE_BLEND = False
    den.config['ADAPTIVE_BLEND'] = False
    assert den._compute_adaptive_blend(0.5, img) == 0.5

    # base_blend <= 0 or >= 1
    den.config['ADAPTIVE_BLEND'] = True
    assert den._compute_adaptive_blend(0.0, img) == 0.0
    assert den._compute_adaptive_blend(1.0, img) == 1.0

    # Normal adaptive blend on 3D and 2D
    blend_3d = den._compute_adaptive_blend(0.5, img)
    assert blend_3d.shape == (50, 50, 1)

    blend_2d = den._compute_adaptive_blend(0.5, img[:, :, 0])
    assert blend_2d.shape == (50, 50)


def test_denoise_strength_and_bilateral_sigma():
    # Test night with short exposure warning
    den_short = create_denoise({'EXPOSURE_PERIOD': '3.0', 'IMAGE_DENOISE_STRENGTH': '4'}, night=True)
    assert den_short._get_strength() == 4
    assert den_short._norm_strength() == 0.75

    # Test day with IMAGE_DENOISE_STRENGTH_DAY
    den_day = create_denoise({
        'USE_NIGHT_COLOR': False,
        'EXPOSURE_PERIOD_DAY': '10.0',
        'IMAGE_DENOISE_STRENGTH_DAY': '2',
    }, night=False)
    assert den_day._get_strength() == 2
    assert den_day._norm_strength() == 0.25

    # _get_bilateral_sigma with default bump and with config override
    sig_color, sig_space = den_short._get_bilateral_sigma()
    assert sig_color >= 1 and sig_space >= 1

    den_short.config['BILATERAL_SIGMA_COLOR'] = 25
    sig_color_override, _ = den_short._get_bilateral_sigma()
    assert sig_color_override == 25


def test_denoise_median_blur_all_branches():
    den = create_denoise({'IMAGE_DENOISE_STRENGTH': '3'}, night=True)

    # 1. Fast path (small image < 512, ksize <= 5):
    # - 2D uint8
    img_2d_u8 = np.full((30, 30), 50, dtype=np.uint8)
    b1 = den._medianBlur(img_2d_u8, ksize=3)
    assert b1.shape == (30, 30)

    # - 2D uint16 (lines 386-392)
    img_2d_u16 = np.full((30, 30), 5000, dtype=np.uint16)
    b2 = den._medianBlur(img_2d_u16, ksize=3)
    assert b2.shape == (30, 30)
    assert b2.dtype == np.uint16

    # - 2D float32 (lines 393-396)
    img_2d_f32 = np.full((30, 30), 0.5, dtype=np.float32)
    b3 = den._medianBlur(img_2d_f32, ksize=3)
    assert b3.shape == (30, 30)
    assert b3.dtype == np.float32

    # - 3D uint8 (lines 402-404)
    img_3d_u8 = np.full((30, 30, 3), 50, dtype=np.uint8)
    b4 = den._medianBlur(img_3d_u8, ksize=3)
    assert b4.shape == (30, 30, 3)

    # 2. Large image / large kernel (> 5):
    # - 2D (lines 407-408)
    b5 = den._medianBlur(img_2d_u8, ksize=7)
    assert b5.shape == (30, 30)

    # - 3D multi-channel (lines 410-415)
    b6 = den._medianBlur(img_3d_u8, ksize=7)
    assert b6.shape == (30, 30, 3)

    # 3. Full median_blur call:
    # - strength <= 0 (bypasses)
    den.config['IMAGE_DENOISE_STRENGTH'] = 0
    assert np.array_equal(den.median_blur(img_3d_u8), img_3d_u8)

    # - strength 1..5
    den.config['IMAGE_DENOISE_STRENGTH'] = 3
    res_med = den.median_blur(img_3d_u8)
    assert res_med.shape == (30, 30, 3)


def test_denoise_gaussian_blur_all_branches():
    den = create_denoise({'IMAGE_DENOISE_STRENGTH': '3'}, night=True)

    # 1. _apply_gaussian_blur:
    # - 2D single channel
    img_2d = np.full((40, 40), 60, dtype=np.uint8)
    gb_2d = den._apply_gaussian_blur(img_2d, 1.5)
    assert gb_2d.shape == (40, 40)

    # - 3D multi-channel
    img_3d = np.full((40, 40, 3), 60, dtype=np.uint8)
    gb_3d = den._apply_gaussian_blur(img_3d, 1.5)
    assert gb_3d.shape == (40, 40, 3)

    # 2. Full gaussian_blur call:
    # - strength <= 0
    den.config['IMAGE_DENOISE_STRENGTH'] = 0
    assert np.array_equal(den.gaussian_blur(img_3d), img_3d)

    # - strength 1..5
    den.config['IMAGE_DENOISE_STRENGTH'] = 2
    res_gb = den.gaussian_blur(img_3d)
    assert res_gb.shape == (40, 40, 3)


def test_denoise_bilateral_all_branches():
    den = create_denoise({'IMAGE_DENOISE_STRENGTH': '3'}, night=True)

    # 1. _apply_bilateral_filter:
    # - uint8 (needs_conversion=False)
    img_u8 = np.full((40, 40, 3), 70, dtype=np.uint8)
    f_u8, nc_u8 = den._apply_bilateral_filter(img_u8, 5, 10, 15, 255.0)
    assert not nc_u8
    assert f_u8.shape == (40, 40, 3)

    # - uint16 (needs_conversion=True)
    img_u16 = np.full((40, 40, 3), 7000, dtype=np.uint16)
    f_u16, nc_u16 = den._apply_bilateral_filter(img_u16, 5, 10, 15, 65535.0)
    assert nc_u16
    assert f_u16.shape == (40, 40, 3)
    assert f_u16.dtype == np.uint16

    # 2. Full bilateral call:
    # - strength <= 0
    den.config['IMAGE_DENOISE_STRENGTH'] = 0
    assert np.array_equal(den.bilateral(img_u8), img_u8)

    # - uint8 and uint16 on full bilateral
    den.config['IMAGE_DENOISE_STRENGTH'] = 3
    res_bil_u8 = den.bilateral(img_u8)
    assert res_bil_u8.shape == (40, 40, 3)

    res_bil_u16 = den.bilateral(img_u16)
    assert res_bil_u16.shape == (40, 40, 3)


def test_denoise_wavelet_all_branches():
    den = create_denoise({'IMAGE_DENOISE_STRENGTH': '3'}, night=True)

    # 1. strength <= 0 (bypasses)
    img_3d = np.full((64, 64, 3), 80, dtype=np.uint8)
    den.config['IMAGE_DENOISE_STRENGTH'] = 0
    assert np.array_equal(den.wavelet(img_3d), img_3d)

    # 2. 3D multi-channel color uint8
    den.config['IMAGE_DENOISE_STRENGTH'] = 2
    res_3d = den.wavelet(img_3d)
    assert res_3d.shape == (64, 64, 3)

    # 3. 2D grayscale uint8
    img_2d = np.full((64, 64), 80, dtype=np.uint8)
    res_2d = den.wavelet(img_2d)
    assert res_2d.shape == (64, 64)

    # 4. float32 input with custom WAVELET_SCALE and WAVELET_MIN_SIGMA
    den.config['WAVELET_SCALE'] = 3.0
    den.config['WAVELET_MIN_SIGMA'] = 0.01
    img_f32 = np.full((64, 64), 0.5, dtype=np.float32)
    res_f32 = den.wavelet(img_f32)
    assert res_f32.shape == (64, 64)
    assert res_f32.dtype == np.float32

    # 5. Non-uniform noisy image to cover threshold calculation (line 750)
    rng = np.random.RandomState(42)
    noisy_img = rng.randint(0, 255, (64, 64, 3), dtype=np.uint8)
    res_noisy = den.wavelet(noisy_img)
    assert res_noisy.shape == (64, 64, 3)

