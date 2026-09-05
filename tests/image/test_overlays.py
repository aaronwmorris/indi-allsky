import numpy as np
import cv2
import pytest

from indi_allsky.overlay.cardinalDirsLabel import IndiAllskyCardinalDirsLabel
from indi_allsky.overlay.moonOverlay import IndiAllSkyMoonOverlay


def test_cardinal_dirs_label_opencv():
    config = {
        'IMAGE_FLIP_V': False,
        'IMAGE_FLIP_H': False,
        'IMAGE_LABEL_SYSTEM': 'opencv',
        'LENS_AZIMUTH': 0,
        'CARDINAL_DIRS': {
            'CHAR_NORTH': 'N',
            'CHAR_EAST': 'E',
            'CHAR_WEST': 'W',
            'CHAR_SOUTH': 'S',
            'OFFSET_TOP': 10,
            'OFFSET_BOTTOM': 10,
            'OFFSET_LEFT': 10,
            'OFFSET_RIGHT': 10,
            'OUTLINE_CIRCLE': True,
            'FONT_COLOR': [255, 255, 255],
        },
        'TEXT_PROPERTIES': {
            'FONT_FACE': 'FONT_HERSHEY_SIMPLEX',
            'FONT_AA': 'LINE_AA',
            'FONT_SCALE': 1.0,
            'FONT_THICKNESS': 1,
            'FONT_OUTLINE': True,
        },
    }

    labeler = IndiAllskyCardinalDirsLabel(config)
    img = np.zeros((300, 300, 3), dtype=np.uint8)

    res = labeler.main(img.copy())
    assert res.shape == (300, 300, 3)
    assert not np.array_equal(res, img)


def test_moon_overlay_apply():
    config = {
        'MOON_OVERLAY': {
            'SCALE': 0.5,
            'X': 50,
            'Y': 50,
            'FLIP_V': False,
            'FLIP_H': False,
            'DARK_SIDE_SCALE': 0.3,
        }
    }

    moon_overlay = IndiAllSkyMoonOverlay(config)
    # Mock moon_orig to a synthetic 100x100 4-channel image
    fake_moon = np.zeros((100, 100, 4), dtype=np.uint8)
    cv2.circle(fake_moon, (50, 50), 40, (255, 255, 255, 255), -1)
    moon_overlay.moon_orig = fake_moon

    target_img = np.zeros((300, 300, 3), dtype=np.uint8)
    # Apply waxing crescent (cycle 15%, illumination phase 20%) - modifies target_img in place
    moon_overlay.apply(target_img, moon_cycle_percent=15.0, moon_phase=20.0)
    assert target_img.shape == (300, 300, 3)
    assert np.any(target_img > 0)

    # Apply full moon (cycle 50%, illumination phase 100%)
    target_img_full = np.zeros((300, 300, 3), dtype=np.uint8)
    moon_overlay.apply(target_img_full, moon_cycle_percent=50.0, moon_phase=100.0)
    assert target_img_full.shape == (300, 300, 3)
    assert np.any(target_img_full > 0)
    assert target_img_full.sum() > target_img.sum()
