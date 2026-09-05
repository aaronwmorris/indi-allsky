import numpy as np
import cv2
import pytest

from indi_allsky.stars import IndiAllSkyStars
from indi_allsky.starsSep import IndiAllSkyStarsSEP


@pytest.fixture
def test_image_with_stars():
    # 200x200 black image with artificial stars
    img = np.zeros((200, 200, 3), dtype=np.uint8)
    # Draw bright stars
    cv2.circle(img, (50, 50), 3, (255, 255, 255), -1)
    cv2.circle(img, (120, 80), 4, (255, 255, 255), -1)
    cv2.circle(img, (150, 150), 3, (255, 255, 255), -1)
    # Blur slightly
    return cv2.GaussianBlur(img, (3, 3), 0.8)


def test_indi_allsky_stars_detection(test_image_with_stars):
    config = {
        'IMAGE_FOLDER': '',
        'DETECT_STARS_THOLD': 0.3,
        'DETECT_DRAW': True,
        'TEXT_PROPERTIES': {'FONT_COLOR': [255, 255, 255]},
        'SQM_ROI': [0, 0, 200, 200],
    }
    mask = {1: np.ones((200, 200), dtype=np.uint8) * 255}
    star_detector = IndiAllSkyStars(config, mask=mask)

    blobs = star_detector.detectObjects(test_image_with_stars.copy(), binning=1)
    assert len(blobs) >= 1

    # Test grayscale input
    gray_img = cv2.cvtColor(test_image_with_stars, cv2.COLOR_BGR2GRAY)
    blobs_gray = star_detector.detectObjects(gray_img.copy(), binning=1)
    assert len(blobs_gray) >= 1


def test_indi_allsky_stars_sep_detection(test_image_with_stars):
    config = {
        'IMAGE_FOLDER': '',
        'DETECT_STARS_SEP_THOLD': 2.0,
        'DETECT_STARS_SEP_MAX_RADIUS': 25,
        'DETECT_DRAW': True,
        'TEXT_PROPERTIES': {'FONT_COLOR': [255, 255, 255]},
        'SQM_ROI': [0, 0, 200, 200],
    }
    mask = {1: np.ones((200, 200), dtype=np.uint8) * 255}
    sep_detector = IndiAllSkyStarsSEP(config, mask=mask)

    blobs = sep_detector.detectObjects(test_image_with_stars.copy(), binning=1)
    assert len(blobs) >= 1

    # Test grayscale
    gray_img = cv2.cvtColor(test_image_with_stars, cv2.COLOR_BGR2GRAY)
    blobs_gray = sep_detector.detectObjects(gray_img.copy(), binning=1)
    assert len(blobs_gray) >= 1
