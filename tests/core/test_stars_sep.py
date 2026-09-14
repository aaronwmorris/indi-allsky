import numpy as np
import cv2
import pytest
from unittest.mock import patch

from indi_allsky.starsSep import IndiAllSkyStarsSEP


@pytest.fixture
def sample_star_image():
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.circle(img, (50, 50), 3, (255, 255, 255), -1)
    return cv2.GaussianBlur(img, (3, 3), 0.8)


def test_stars_sep_init_image_folder():
    config = {'IMAGE_FOLDER': '/tmp/test_images'}
    detector = IndiAllSkyStarsSEP(config, mask={1: None})
    assert str(detector.image_dir) == '/tmp/test_images'

    # Empty image folder uses default
    config_empty = {'IMAGE_FOLDER': ''}
    detector_empty = IndiAllSkyStarsSEP(config_empty, mask={1: None})
    assert 'html/images' in str(detector_empty.image_dir)


def test_stars_sep_detect_with_existing_mask(sample_star_image):
    config = {
        'IMAGE_FOLDER': '',
        'DETECT_STARS_SEP_THOLD': 1.0,
        'DETECT_STARS_SEP_MAX_RADIUS': 20,
        'DETECT_DRAW': True,
        'TEXT_PROPERTIES': {'FONT_COLOR': [255, 255, 255]},
    }
    mask = {1: np.ones((100, 100), dtype=np.uint8) * 255}
    detector = IndiAllSkyStarsSEP(config, mask=mask)

    # Color image
    blobs = detector.detectObjects(sample_star_image.copy(), binning=1)
    assert isinstance(blobs, list)

    # Grayscale image
    gray = cv2.cvtColor(sample_star_image, cv2.COLOR_BGR2GRAY)
    blobs_gray = detector.detectObjects(gray.copy(), binning=1)
    assert isinstance(blobs_gray, list)


def test_stars_sep_generate_mask_sqm_roi(sample_star_image):
    config = {
        'IMAGE_FOLDER': '',
        'DETECT_STARS_SEP_THOLD': 1.0,
        'DETECT_STARS_SEP_MAX_RADIUS': 20,
        'DETECT_DRAW': False,  # Test early return in _drawCircles
        'SQM_ROI': [20, 20, 80, 80],
    }
    # SQM mask is None for binning 1, so it generates from SQM_ROI
    detector = IndiAllSkyStarsSEP(config, mask={1: None})
    blobs = detector.detectObjects(sample_star_image.copy(), binning=1)
    assert isinstance(blobs, list)
    assert detector._star_mask_dict[1] is not None


def test_stars_sep_generate_mask_fallback_central_roi(sample_star_image):
    config = {
        'IMAGE_FOLDER': '',
        'DETECT_STARS_SEP_THOLD': 1.0,
        'DETECT_STARS_SEP_MAX_RADIUS': 20,
        'DETECT_DRAW': False,
        'SQM_ROI': [],  # Triggers IndexError, falls back to central ROI
        'SQM_FOV_DIV': 4,
    }
    detector = IndiAllSkyStarsSEP(config, mask={1: None})
    blobs = detector.detectObjects(sample_star_image.copy(), binning=1)
    assert isinstance(blobs, list)
    assert detector._star_mask_dict[1] is not None


def test_stars_sep_extraction_exception(sample_star_image):
    config = {
        'IMAGE_FOLDER': '',
        'DETECT_STARS_SEP_THOLD': 1.0,
        'DETECT_STARS_SEP_MAX_RADIUS': 20,
        'DETECT_DRAW': False,
    }
    detector = IndiAllSkyStarsSEP(config, mask={1: np.ones((100, 100), dtype=np.uint8) * 255})
    with patch('sep.extract', side_effect=Exception("Extraction error")):
        blobs = detector.detectObjects(sample_star_image.copy(), binning=1)
        assert blobs == []


def test_stars_sep_none_mask(sample_star_image):
    config = {
        'IMAGE_FOLDER': '',
        'DETECT_STARS_SEP_THOLD': 1.0,
        'DETECT_STARS_SEP_MAX_RADIUS': 1,  # Max radius 1 will filter out any blobs
        'DETECT_DRAW': True,
        'TEXT_PROPERTIES': {'FONT_COLOR': [255, 255, 255]},
    }
    detector = IndiAllSkyStarsSEP(config, mask={1: None})
    # Force _star_mask_dict to None after mask generation to test line 47
    orig_generate = detector._generateStarMask
    def fake_generate(img, binning):
        orig_generate(img, binning)
        detector._star_mask_dict[binning] = None
    detector._generateStarMask = fake_generate

    blobs = detector.detectObjects(sample_star_image.copy(), binning=1)
    assert blobs == []
