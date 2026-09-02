import numpy as np
import cv2
import pytest

from indi_allsky.protection_masks import (
    star_mask,
    fast_star_mask,
    async_star_mask,
    set_cache_size,
    get_last_star_profile,
)


@pytest.fixture
def test_star_field():
    img = np.zeros((128, 128), dtype=np.float32)
    # Add fake stars
    cv2.circle(img, (32, 32), 3, 200.0, -1)
    cv2.circle(img, (80, 70), 4, 250.0, -1)
    cv2.circle(img, (100, 100), 2, 180.0, -1)
    # Gaussian blur to mimic PSF
    return cv2.GaussianBlur(img, (5, 5), 1.2)


def test_star_mask_basic(test_star_field):
    mask = star_mask(test_star_field, expand_radius=3)
    assert mask.shape == test_star_field.shape
    assert mask.dtype == np.float32
    assert np.min(mask) >= 0.0
    assert np.max(mask) <= 1.0
    # Values around stars should be protected (< 1.0)
    assert np.any(mask < 0.5)

    profile = get_last_star_profile()
    assert isinstance(profile, dict)


def test_fast_star_mask_and_cache(test_star_field):
    set_cache_size(16)

    # Grayscale
    mask_fast = fast_star_mask(test_star_field, downsample=2, patch_size=16, expand_radius=2)
    assert mask_fast.shape == test_star_field.shape
    assert mask_fast.dtype == np.float32

    # Color (3 channel)
    color_img = np.dstack([test_star_field, test_star_field, test_star_field])
    mask_fast_color = fast_star_mask(color_img, downsample=2, patch_size=16)
    assert mask_fast_color.shape == test_star_field.shape


def test_async_star_mask(test_star_field):
    future = async_star_mask(test_star_field, expand_radius=2)
    mask = future.result(timeout=5)
    assert mask.shape == test_star_field.shape
    assert mask.dtype == np.float32
