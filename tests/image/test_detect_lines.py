import numpy as np
import cv2
import pytest

from indi_allsky.detectLines import IndiAllskyDetectLines


def test_detect_lines_basic():
    config = {
        'DETECT_METEORS_THOLD': 30,
        'DETECT_DRAW': True,
        'TEXT_PROPERTIES': {'FONT_COLOR': [255, 255, 255]},
        'SQM_ROI': [0, 0, 300, 300],
    }
    mask = {1: np.ones((300, 300), dtype=np.uint8) * 255}
    detector = IndiAllskyDetectLines(config, mask=mask)

    # Blank image (should find 0 lines)
    blank = np.zeros((300, 300, 3), dtype=np.uint8)
    lines = detector.detectLines(blank, binning=1)
    assert len(lines) == 0

    # Image with a bright straight line
    line_img = np.zeros((300, 300, 3), dtype=np.uint8)
    cv2.line(line_img, (50, 50), (250, 250), (255, 255, 255), thickness=3)

    lines = detector.detectLines(line_img.copy(), binning=1)
    assert len(lines) > 0


def test_detect_lines_mono_and_split_stack():
    config = {
        'DETECT_METEORS_THOLD': 30,
        'DETECT_DRAW': False,
        'IMAGE_STACK_COUNT': 2,
        'IMAGE_STACK_SPLIT': True,
    }
    mask = {1: None}
    detector = IndiAllskyDetectLines(config, mask=mask)

    mono_img = np.zeros((300, 300), dtype=np.uint8)
    cv2.line(mono_img, (30, 150), (270, 150), 255, thickness=4)

    lines = detector.detectLines(mono_img.copy(), binning=1)
    assert isinstance(lines, (list, np.ndarray))
