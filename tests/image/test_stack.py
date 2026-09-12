import numpy as np
import pytest
from unittest.mock import MagicMock, patch
import astroalign

from indi_allsky.stack import IndiAllskyStacker


class DummyRefImage:
    def __init__(self, data):
        self.opencv_data = data


def test_stacker_properties():
    config = {'SQM_ROI': [10, 10, 40, 40]}
    mask = {1: None}
    stacker = IndiAllskyStacker(config, mask=mask)

    stacker.detection_sigma = 6
    assert stacker.detection_sigma == 6

    stacker.max_control_points = 60
    assert stacker.max_control_points == 60

    stacker.min_area = 15
    assert stacker.min_area == 15

    stacker.MIN_MATCHES_FRACTION = 0.75
    assert stacker.MIN_MATCHES_FRACTION == 0.75

    stacker.NUM_NEAREST_NEIGHBORS = 6
    assert stacker.NUM_NEAREST_NEIGHBORS == 6

    stacker.PIXEL_TOL = 3
    assert stacker.PIXEL_TOL == 3


def test_stacker_math_methods():
    config = {}
    mask = {1: None}
    stacker = IndiAllskyStacker(config, mask=mask)

    img1 = np.full((10, 10, 3), 20, dtype=np.uint8)
    img2 = np.full((10, 10, 3), 40, dtype=np.uint8)
    img3 = np.full((10, 10, 3), 60, dtype=np.uint8)

    # mean / average
    avg_res = stacker.average([img1, img2, img3], np.uint8)
    assert np.all(avg_res == 40)
    assert avg_res.dtype == np.uint8

    mean_res = stacker.mean([img1, img2, img3], np.uint8)
    assert np.array_equal(mean_res, avg_res)

    # maximum
    max_res = stacker.maximum([img1, img2, img3], np.uint8)
    assert np.all(max_res == 60)
    assert max_res.dtype == np.uint8

    # minimum
    min_res = stacker.minimum([img1, img2, img3], np.uint8)
    assert np.all(min_res == 20)
    assert min_res.dtype == np.uint8

    # _crop
    cropped = stacker._crop(img1)
    assert cropped.shape == (5, 5, 3)


def test_stacker_mask_generation():
    # 1. With valid SQM_ROI
    config_roi = {'SQM_ROI': [8, 8, 32, 32]}
    mask = {1: None}
    stacker_roi = IndiAllskyStacker(config_roi, mask=mask)
    dummy_img = np.zeros((40, 40), dtype=np.uint8)
    stacker_roi._generateStackMask(dummy_img, binning=1)
    assert stacker_roi._stack_mask_dict[1] is not None
    assert stacker_roi._stack_mask_dict[1].shape == (40, 40)
    assert stacker_roi._stack_mask_dict[1][15, 15] == 255

    # 2. With fallback to SQM_FOV_DIV
    config_div = {'SQM_ROI': [], 'SQM_FOV_DIV': 4}
    stacker_div = IndiAllskyStacker(config_div, mask=mask)
    stacker_div._generateStackMask(dummy_img, binning=1)
    assert stacker_div._stack_mask_dict[1] is not None
    assert stacker_div._stack_mask_dict[1].shape == (40, 40)


def test_stacker_register_workflow():
    config = {'SQM_ROI': [0, 0, 100, 100]}
    mask = {1: None}
    stacker = IndiAllskyStacker(config, mask=mask)

    ref_data = np.zeros((100, 100, 3), dtype=np.uint8)
    tgt_data1 = np.zeros((100, 100, 3), dtype=np.uint8)
    tgt_data2 = np.zeros((100, 100, 3), dtype=np.uint8)
    tgt_data3 = np.zeros((100, 100, 3), dtype=np.uint8)

    ref_img = DummyRefImage(ref_data)
    tgt_img1 = DummyRefImage(tgt_data1)
    tgt_img2 = DummyRefImage(tgt_data2)
    tgt_img3 = DummyRefImage(tgt_data3)

    mock_transform = MagicMock()
    mock_transform.rotation = 0.05
    mock_transform.translation = (1.0, -1.0)
    mock_transform.scale = 1.0

    with patch('astroalign.find_transform', return_value=(mock_transform, ([1, 2], [3, 4]))), \
         patch('astroalign.apply_transform', return_value=(tgt_data1, None)):

        # Normal successful register
        res = stacker.register([ref_img, tgt_img1], binning=1, max_bit_depth=8)
        assert len(res) == 2
        assert len(stacker.hist_rotation) == 1

        # Test rotation history threshold check
        # Pre-fill history to >= 15 values
        stacker.hist_rotation = [0.05] * 20
        # New rotation that deviates excessively (> rotation_mean + rotation_stddev_limit)
        mock_transform_deviant = MagicMock()
        mock_transform_deviant.rotation = 5.0
        mock_transform_deviant.translation = (0.0, 0.0)
        mock_transform_deviant.scale = 1.0

        with patch('astroalign.find_transform', return_value=(mock_transform_deviant, ([1], [2]))):
            res_dev = stacker.register([ref_img, tgt_img2], binning=1, max_bit_depth=8)
            # Only reference image returned because deviant image was skipped
            assert len(res_dev) == 1

        # Test scale limit exceeded (abs(scale) < _scale_limit)
        mock_transform_bad_scale = MagicMock()
        mock_transform_bad_scale.rotation = 0.05
        mock_transform_bad_scale.translation = (0.0, 0.0)
        mock_transform_bad_scale.scale = 0.5  # < 0.97

        stacker.hist_rotation = []  # reset rotation history
        with patch('astroalign.find_transform', return_value=(mock_transform_bad_scale, ([1], [2]))):
            res_scale = stacker.register([ref_img, tgt_img3], binning=1, max_bit_depth=8)
            assert len(res_scale) == 1


def test_stacker_register_exceptions():
    config = {'SQM_ROI': [0, 0, 100, 100]}
    mask = {1: None}
    stacker = IndiAllskyStacker(config, mask=mask)

    ref_img = DummyRefImage(np.zeros((100, 100, 3), dtype=np.uint8))
    tgt_img = DummyRefImage(np.zeros((100, 100, 3), dtype=np.uint8))

    for exc in [astroalign.MaxIterError('max iter'), ValueError('val err'), TypeError('type err')]:
        with patch('astroalign.find_transform', side_effect=exc):
            res = stacker.register([ref_img, tgt_img], binning=1, max_bit_depth=8)
            assert len(res) == 1
