import numpy as np
import cv2
import pytest

from indi_allsky.draw import IndiAllSkyDraw


@pytest.fixture
def draw_config():
    return {
        'DETECT_DRAW': True,
        'IMAGE_FLIP_V': True,
        'IMAGE_FLIP_H': True,
        'TEXT_PROPERTIES': {
            'FONT_FACE': 'FONT_HERSHEY_SIMPLEX',
            'FONT_AA': 'LINE_AA',
            'FONT_SCALE': 0.8,
            'FONT_THICKNESS': 1,
            'FONT_OUTLINE': True,
        },
    }


def test_draw_main_color(draw_config):
    mask = {1: np.full((100, 100), 255, dtype=np.uint8)}
    drawer = IndiAllSkyDraw(draw_config, mask=mask)

    img = np.zeros((100, 100, 3), dtype=np.uint8)
    res = drawer.main(img, binning=1)

    assert res.shape == (100, 100, 3)
    assert res.dtype == np.uint8


def test_draw_main_mono_and_disabled():
    # Test disabled
    drawer_disabled = IndiAllSkyDraw({'DETECT_DRAW': False}, mask={1: None})
    img = np.zeros((50, 50), dtype=np.uint8)
    res = drawer_disabled.main(img, binning=1)
    assert np.array_equal(res, img)

    # Test mono alpha mask generation
    config = {
        'DETECT_DRAW': True,
        'TEXT_PROPERTIES': {
            'FONT_FACE': 'FONT_HERSHEY_SIMPLEX',
            'FONT_AA': 'LINE_AA',
            'FONT_SCALE': 0.8,
            'FONT_THICKNESS': 1,
            'FONT_OUTLINE': False,
        }
    }
    mask = {1: np.full((60, 60), 255, dtype=np.uint8)}
    drawer = IndiAllSkyDraw(config, mask=mask)
    mono_img = np.full((60, 60), 100, dtype=np.uint8)
    res = drawer.main(mono_img, binning=1)
    assert res.shape == (60, 60)
