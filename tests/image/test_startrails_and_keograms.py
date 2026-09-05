import pytest
import numpy as np
import cv2
from datetime import datetime, timezone
from pathlib import Path

from indi_allsky.starTrails import StarTrailGenerator
from indi_allsky.keogram import KeogramGenerator
from indi_allsky.detectLines import IndiAllskyDetectLines


# ==============================================================================
# Keogram Generator Tests
# ==============================================================================

def test_keogram_generator_basic(tmp_path):
    config = {
        'KEOGRAM_ANGLE': 0,
        'LENS_OFFSET_X': 0,
        'LENS_OFFSET_Y': 0,
        'IMAGE_BORDER': {'TOP': 0, 'LEFT': 0, 'RIGHT': 0, 'BOTTOM': 0},
    }
    keogram_gen = KeogramGenerator(config=config)
    keogram_gen.label = False

    # Process 3 sequential frames (100x100 BGR)
    for i in range(3):
        frame = np.full((100, 100, 3), 50 + i * 20, dtype=np.uint8)
        time_exp = datetime(2026, 9, 1, 12, i, 0, tzinfo=timezone.utc)
        keogram_gen.processImage(frame, time_exp)

    assert keogram_gen.process_count == 3
    assert keogram_gen.keogram_data is not None


def test_keogram_rotation_angles():
    config = {
        'KEOGRAM_ANGLE': 90,
        'LENS_OFFSET_X': 0,
        'LENS_OFFSET_Y': 0,
        'IMAGE_BORDER': {},
    }
    keogram_gen = KeogramGenerator(config=config)
    keogram_gen.label = False

    frame = np.zeros((80, 80, 3), dtype=np.uint8)
    time_exp = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    keogram_gen.processImage(frame, time_exp)

    assert keogram_gen.process_count == 1


# ==============================================================================
# Star Trails Generator Tests
# ==============================================================================

def test_startrails_generator_process(tmp_path):
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir(exist_ok=True)

    config = {
        'IMAGE_FOLDER': str(tmp_path),
        'IMAGE_FILE_TYPE': 'jpg',
        'IMAGE_FILE_COMPRESSION': {'jpg': 90},
        'STARTRAILS_TIMELAPSE': False,
        'STARTRAILS_PIXEL_THOLD': 1.0,
        'STARTRAILS_MASK_THOLD': 200,
        'STARTRAILS_MAX_ADU': 250,
        'STARTRAILS_SUN_ALT_THOLD': -6.0,
        'STARTRAILS_MIN_STARS': 0,
        'LATITUDE': -34.9,
        'LONGITUDE': 138.6,
    }

    mask = {1: None}
    trail_gen = StarTrailGenerator(config=config, mask=mask)
    trail_gen.max_adu = 250
    trail_gen.sun_alt_threshold = 90.0  # Allow test execution regardless of real-world local time

    # Frame 1: Base background
    f1 = np.full((64, 64, 3), 10, dtype=np.uint8)
    # Frame 2: Bright star pixel at (20, 20)
    f2 = np.full((64, 64, 3), 10, dtype=np.uint8)
    f2[20, 20] = [200, 200, 200]
    # Frame 3: Bright star pixel at (21, 21)
    f3 = np.full((64, 64, 3), 10, dtype=np.uint8)
    f3[21, 21] = [220, 220, 220]

    night_time = datetime(2026, 9, 1, 15, 0, 0, tzinfo=timezone.utc)  # Night time for solar alt
    dummy_path = tmp_path / "test.jpg"
    dummy_path.touch()

    trail_gen.processImage(dummy_path, f1, binning=1, adu=20)
    trail_gen.processImage(dummy_path, f2, binning=1, adu=20)
    trail_gen.processImage(dummy_path, f3, binning=1, adu=20)

    assert trail_gen.trail_count >= 2
    assert trail_gen.trail_image is not None
    assert trail_gen.trail_image.shape == (64, 64, 3)
    # The max pixel composite should contain the bright stars
    assert np.all(trail_gen.trail_image[20, 20] >= 200)
    assert np.all(trail_gen.trail_image[21, 21] >= 220)
