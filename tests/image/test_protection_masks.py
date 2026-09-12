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


def test_protection_masks_edge_cases():
    from unittest.mock import patch
    from indi_allsky.protection_masks import (
        _estimate_background_std,
        _apply_star_dilation,
        _paint_stars_from_table,
        star_mask,
        fast_star_mask,
    )

    # 1. _estimate_background_std exception fallback to np.std
    data = np.ones((10, 10), dtype=np.float32)
    with patch('astropy.stats.sigma_clipped_stats', side_effect=RuntimeError('stats error')):
        std_val = _estimate_background_std(data)
        assert std_val == 0.0

    # 2. _apply_star_dilation with expand_radius <= 0 or None
    mask = np.ones((20, 20), dtype=np.float32)
    assert _apply_star_dilation(mask, 0) is mask
    assert _apply_star_dilation(mask, None) is mask

    # 3. _apply_star_dilation with large expand_radius > max(h, w)
    mask[5, 5] = 0.0
    dilated = _apply_star_dilation(mask.copy(), expand_radius=100)
    assert dilated.shape == (20, 20)

    # 4. _apply_star_dilation exception handling
    with patch('cv2.distanceTransform', side_effect=RuntimeError('cv error')):
        res = _apply_star_dilation(mask.copy(), expand_radius=5)
        assert res.shape == mask.shape

    # 5. _paint_stars_from_table with None or empty table
    assert _paint_stars_from_table(None, (20, 20), 2.0).shape == (20, 20)
    assert _paint_stars_from_table([], (20, 20), 2.0).shape == (20, 20)

    # 6. star_mask with expand_radius=None (uses DEFAULT_EXPAND_RADIUS)
    flat_img = np.full((30, 30), 10.0, dtype=np.float32)
    sm = star_mask(flat_img, expand_radius=None)
    assert sm.shape == (30, 30)

    # 7. fast_star_mask with flat image (no candidates)
    flat_mask = fast_star_mask(flat_img, downsample=2)
    assert np.all(flat_mask == 1.0)

    # 8. fast_star_mask percentile exception fallback
    with patch('numpy.percentile', side_effect=Exception('percentile error')):
        flat_mask2 = fast_star_mask(flat_img, downsample=2)
        assert flat_mask2.shape == (30, 30)

    # 9. fast_star_mask max_patches limiting
    # Create image with many noisy spots
    noisy = np.random.RandomState(42).uniform(0, 100, (64, 64)).astype(np.float32)
    mask_patches = fast_star_mask(noisy, downsample=1, patch_size=8, max_patches=2, percentile=50)
    assert mask_patches.shape == (64, 64)

    # 10. fast_star_mask with daofind throwing exception or returning None
    with patch('photutils.detection.DAOStarFinder.__call__', side_effect=RuntimeError('daofind error')):
        mask_err = fast_star_mask(noisy, downsample=1, patch_size=8, percentile=50)
        assert mask_err.shape == (64, 64)

    with patch('photutils.detection.DAOStarFinder.__call__', return_value=None):
        mask_none = fast_star_mask(noisy, downsample=1, patch_size=8, percentile=50)
        assert mask_none.shape == (64, 64)

    from unittest.mock import MagicMock, patch
    # 11. _cached_star exception in profiling
    with patch('indi_allsky.protection_masks._last_profile', MagicMock(__setitem__=MagicMock(side_effect=RuntimeError('profile error')))):
        # Calling star_mask with a fresh image to bypass LRU cache
        fresh_img = np.zeros((20, 20), dtype=np.float32)
        fresh_img[10, 10] = 50.0
        sm = star_mask(fresh_img)
        assert sm.shape == (20, 20)

    # 12. fast_star_mask with edge detections (sy1 <= sy0 or sx1 <= sx0)
    fake_tbl = {'xcentroid': [1000.0, -1000.0], 'ycentroid': [1000.0, -1000.0]}
    with patch('photutils.detection.DAOStarFinder.__call__', return_value=fake_tbl):
        mask_bounds = fast_star_mask(noisy, downsample=1, patch_size=8, percentile=50)
        assert mask_bounds.shape == (64, 64)

    # 13. Test patch.size == 0 with candidate far outside image
    with patch('numpy.nonzero', return_value=([200], [200])):
        mask_empty = fast_star_mask(noisy, downsample=1, patch_size=8, percentile=50)
        assert mask_empty.shape == (64, 64)



