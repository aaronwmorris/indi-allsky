import numpy as np
import pytest

from indi_allsky.stretch.mode1_stddev_cutoff import IndiAllSky_Mode1_Stretch


def test_stretch_mode1_8bit_mono_with_mask():
    config = {
        'IMAGE_STRETCH': {
            'MODE1_GAMMA': 2.0,
            'MODE1_STDDEVS': 2.0,
        }
    }
    mask = {1: np.ones((50, 50), dtype=np.uint8) * 255}
    stretcher = IndiAllSky_Mode1_Stretch(config, mask=mask)

    # 8-bit mono image
    img = (np.arange(2500) % 256).astype(np.uint8).reshape((50, 50))
    stretched = stretcher.stretch(img, image_bit_depth=8, binning=1)


    assert stretched.shape == img.shape
    assert stretched.dtype == np.uint8


def test_stretch_mode1_16bit_color_with_mask():
    config = {
        'IMAGE_STRETCH': {
            'MODE1_GAMMA': 2.5,
            'MODE1_STDDEVS': 3.0,
        }
    }
    mask = {1: np.ones((50, 50), dtype=np.uint8) * 255}
    stretcher = IndiAllSky_Mode1_Stretch(config, mask=mask)

    # 16-bit 3-channel color image
    img = np.full((50, 50, 3), 1000, dtype=np.uint16)
    img[20:30, 20:30] = 5000

    stretched = stretcher.stretch(img, image_bit_depth=16, binning=1)

    assert stretched.shape == img.shape
    assert stretched.dtype == np.uint16


def test_stretch_mode1_zero_gamma():
    config = {
        'IMAGE_STRETCH': {
            'MODE1_GAMMA': 0.0,
            'MODE1_STDDEVS': 2.0,
        }
    }
    mask = {1: np.ones((50, 50), dtype=np.uint8) * 255}
    stretcher = IndiAllSky_Mode1_Stretch(config, mask=mask)

    img = np.full((50, 50), 128, dtype=np.uint8)
    # When gamma is 0, mode1_apply_gamma returns data unmodified
    gamma_res = stretcher.mode1_apply_gamma(img, image_bit_depth=8, binning=1)
    assert np.array_equal(gamma_res, img)


def test_stretch_mode1_generate_numpy_mask_sqm_roi():
    config = {
        'IMAGE_STRETCH': {
            'MODE1_GAMMA': 2.0,
            'MODE1_STDDEVS': 2.0,
        },
        'SQM_ROI': [10, 10, 40, 40],
    }
    # mask is None, triggering _generateNumpyMask
    mask = {1: None}
    stretcher = IndiAllSky_Mode1_Stretch(config, mask=mask)

    img = np.full((50, 50, 3), 128, dtype=np.uint8)
    stretched = stretcher.stretch(img, image_bit_depth=8, binning=1)

    assert stretcher._numpy_mask_dict[1] is not None
    assert stretched.shape == img.shape


def test_stretch_mode1_generate_numpy_mask_fallback_central_roi():
    config = {
        'IMAGE_STRETCH': {
            'MODE1_GAMMA': 2.0,
            'MODE1_STDDEVS': 2.0,
        },
        'SQM_ROI': [],  # triggers IndexError -> central ROI
        'SQM_FOV_DIV': 4,
    }
    mask = {1: None}
    stretcher = IndiAllSky_Mode1_Stretch(config, mask=mask)

    img = np.full((60, 60), 100, dtype=np.uint8)
    stretched = stretcher.stretch(img, image_bit_depth=8, binning=1)

    assert stretcher._numpy_mask_dict[1] is not None
    assert stretched.shape == img.shape
