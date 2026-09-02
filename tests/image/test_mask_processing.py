import numpy as np
import pytest

from indi_allsky.maskProcessing import MaskProcessor


def test_mask_processor_rotation_90():
    config = {'IMAGE_ROTATE': 'ROTATE_90_CLOCKWISE'}
    processor = MaskProcessor(config)
    img = np.zeros((100, 200), dtype=np.uint8)
    processor.image = img
    processor.rotate_90()
    assert processor.image.shape == (200, 100)


def test_mask_processor_rotation_angle():
    config = {
        'IMAGE_ROTATE_ANGLE': 45,
        'IMAGE_ROTATE_KEEP_SIZE': True,
    }
    processor = MaskProcessor(config)
    processor.image = np.zeros((100, 100), dtype=np.uint8)
    processor.rotate_angle()
    assert processor.image.shape == (100, 100)

    # Test keep size False
    config_resize = {
        'IMAGE_ROTATE_ANGLE': 45,
        'IMAGE_ROTATE_KEEP_SIZE': False,
    }
    proc_resize = MaskProcessor(config_resize)
    proc_resize.image = np.zeros((100, 100), dtype=np.uint8)
    proc_resize.rotate_angle()
    assert proc_resize.image.shape[0] > 100
    assert proc_resize.image.shape[1] > 100


def test_mask_processor_flips():
    config = {'IMAGE_FLIP_V': True, 'IMAGE_FLIP_H': True}
    processor = MaskProcessor(config)
    img = np.arange(100, dtype=np.uint8).reshape((10, 10))
    processor.image = img.copy()

    processor.flip_v()
    processor.flip_h()
    assert processor.image.shape == (10, 10)
    assert not np.array_equal(processor.image, img)


def test_mask_processor_crop_roi_and_circle():
    # Test Crop ROI
    config_roi = {'IMAGE_CROP_ROI': [10, 20, 50, 60]}
    processor_roi = MaskProcessor(config_roi)
    processor_roi.image = np.zeros((100, 100), dtype=np.uint8)
    processor_roi.binning = 1
    processor_roi.crop_image()
    assert processor_roi.image.shape == (40, 40)

    # Test Image Circle
    config_circle = {
        'IMAGE_CROP_IMAGE_CIRCLE': True,
        'LENS_IMAGE_CIRCLE': 60,
        'LENS_OFFSET_X': 2,
        'LENS_OFFSET_Y': -2,
    }
    processor_circle = MaskProcessor(config_circle)
    processor_circle.image = np.zeros((100, 100), dtype=np.uint8)
    processor_circle.crop_image()
    assert processor_circle.image.shape[0] > 0
    assert processor_circle.image.shape[1] > 0


def test_mask_processor_scale_and_border():
    config = {
        'IMAGE_SCALE': 50,
        'IMAGE_BORDER': {'TOP': 10, 'BOTTOM': 10, 'LEFT': 5, 'RIGHT': 5},
    }
    processor = MaskProcessor(config)
    processor.image = np.zeros((100, 100), dtype=np.uint8)
    processor.scale_image()
    assert processor.image.shape == (50, 50)

    processor.add_border()
    assert processor.image.shape == (70, 60)
