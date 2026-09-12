import pytest
import numpy as np

from indi_allsky.scnr import IndiAllskyScnr
from indi_allsky.denoise import IndiAllskyDenoise
from indi_allsky.stretch.mode1_stddev_cutoff import IndiAllSky_Mode1_Stretch
from indi_allsky.stretch.mode2_mtf import IndiAllSky_Mode2_MTF_Stretch
from indi_allsky.stretch.mode3_adaptive_mtf import IndiAllSky_Mode3_Adaptive_MTF_Stretch
from indi_allsky import constants


# ==============================================================================
# SCNR Tests (Subtractive Chromatic Noise Reduction)
# ==============================================================================

def test_scnr_grayscale_passthrough():
    scnr = IndiAllskyScnr(config={}, night_av={constants.NIGHT_NIGHT: True})
    gray = np.full((100, 100), 128, dtype=np.uint8)
    assert np.array_equal(scnr.average_neutral(gray), gray)
    assert np.array_equal(scnr.maximum_neutral(gray), gray)
    assert np.array_equal(scnr.green_mtf(gray), gray)


def test_scnr_average_neutral_bgr():
    scnr = IndiAllskyScnr(config={}, night_av={constants.NIGHT_NIGHT: True})
    # B=50, G=200 (heavy green cast), R=50
    bgr = np.zeros((50, 50, 3), dtype=np.uint8)
    bgr[:, :, 0] = 50   # Blue
    bgr[:, :, 1] = 200  # Green
    bgr[:, :, 2] = 50   # Red

    result = scnr.average_neutral(bgr)
    # Green should be capped to average of R and B = (50 + 50) / 2 = 50
    assert result[:, :, 1].max() == 50
    assert result[:, :, 0].max() == 50
    assert result[:, :, 2].max() == 50


def test_scnr_maximum_neutral_bgr():
    scnr = IndiAllskyScnr(config={}, night_av={constants.NIGHT_NIGHT: True})
    # B=40, G=220, R=80
    bgr = np.zeros((50, 50, 3), dtype=np.uint8)
    bgr[:, :, 0] = 40   # Blue
    bgr[:, :, 1] = 220  # Green
    bgr[:, :, 2] = 80   # Red

    result = scnr.maximum_neutral(bgr)
    # Green should be capped to max(R, B) = 80
    assert result[:, :, 1].max() == 80


# ==============================================================================
# Stretch Modes Tests (Mode 1, Mode 2 MTF, Mode 3 Adaptive MTF)
# ==============================================================================

def test_stretch_mode1_stddev_cutoff():
    config = {
        'IMAGE_STRETCH': {
            'MODE1_GAMMA': 2.2,
            'MODE1_STDDEVS': 2.5,
        }
    }
    # Mock circular mask
    mask = {1: np.ones((64, 64), dtype=bool)}
    stretch_m1 = IndiAllSky_Mode1_Stretch(config, mask=mask)

    data = np.linspace(10, 200, 64 * 64, dtype=np.uint8).reshape((64, 64))
    stretched = stretch_m1.stretch(data, image_bit_depth=8, binning=1)

    assert stretched.shape == (64, 64)
    assert stretched.dtype == np.uint8
    assert not np.array_equal(stretched, data)


def test_stretch_mode2_mtf():
    config = {
        'IMAGE_STRETCH': {
            'MODE2_SHADOWS': 0.0,
            'MODE2_MIDTONES': 0.35,
            'MODE2_HIGHLIGHTS': 1.0,
        }
    }
    # 8-bit image test (midtones < 0.5 boosts mid-range values)
    stretch_m2_8 = IndiAllSky_Mode2_MTF_Stretch(config)
    data_8 = np.linspace(0, 255, 100 * 100, dtype=np.uint8).reshape((100, 100))
    stretched_8 = stretch_m2_8.stretch(data_8, image_bit_depth=8, binning=1)
    assert stretched_8.dtype == np.uint8
    assert stretched_8.shape == (100, 100)
    assert stretched_8[50, 50] > data_8[50, 50]

    # 16-bit image test (uses its own instance to initialize 16-bit LUT)
    stretch_m2_16 = IndiAllSky_Mode2_MTF_Stretch(config)
    data_16 = np.linspace(0, 65535, 100 * 100, dtype=np.uint16).reshape((100, 100))
    stretched_16 = stretch_m2_16.stretch(data_16, image_bit_depth=16, binning=1)
    assert stretched_16.dtype == np.uint16
    assert stretched_16.shape == (100, 100)
    assert stretched_16[50, 50] > data_16[50, 50]


def test_stretch_mode3_adaptive_mtf():
    config = {
        'IMAGE_STRETCH': {
            'MODE3_BLACK_CLIP': -2.8,
            'MODE3_SHADOWS': 0.0,
            'MODE3_MIDTONES': 0.25,
            'MODE3_HIGHLIGHTS': 1.0,
        }
    }
    stretch_m3 = IndiAllSky_Mode3_Adaptive_MTF_Stretch(config)

    data = np.random.randint(10, 240, size=(128, 128), dtype=np.uint8)
    stretched = stretch_m3.stretch(data, image_bit_depth=8, binning=1)

    assert stretched.shape == (128, 128)
    assert stretched.dtype == np.uint8
    assert not np.array_equal(stretched, data)


# ==============================================================================
# Denoise Tests (Gaussian, Bilateral, Median)
# ==============================================================================

def test_denoise_gaussian_and_bilateral():
    config = {
        'IMAGE_DENOISE_STRENGTH': 2,
        'BILATERAL_SIGMA': 10,
        'DENOISE_PROTECT_STARS': False,
        'ADAPTIVE_BLEND': False,
    }
    night_av = {constants.NIGHT_NIGHT: True}
    denoiser = IndiAllskyDenoise(config, night_av)

    # Test 3-channel noisy image (variance reduction check)
    rng = np.random.RandomState(42)
    base = np.full((64, 64, 3), 128, dtype=np.int16)
    noise = rng.normal(0, 20, size=(64, 64, 3)).astype(np.int16)
    bgr_img = np.clip(base + noise, 0, 255).astype(np.uint8)

    out_gaussian = denoiser.gaussian_blur(bgr_img)
    assert out_gaussian.shape == (64, 64, 3)
    assert out_gaussian.dtype == np.uint8
    assert out_gaussian.std() < bgr_img.std()

    out_bilateral = denoiser.bilateral(bgr_img)
    assert out_bilateral.shape == (64, 64, 3)
    assert out_bilateral.dtype == np.uint8
    assert out_bilateral.std() < bgr_img.std()

    out_median = denoiser.median_blur(bgr_img)
    assert out_median.shape == (64, 64, 3)
    assert out_median.dtype == np.uint8
    assert out_median.std() < bgr_img.std()
