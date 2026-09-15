import io
import time
import datetime
from pathlib import Path
from multiprocessing import Queue, Array
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from indi_allsky.camera.test_cameras import (
    IndiClientTestCameraBase,
    IndiClientTestCameraBubbles,
    IndiClientTestCameraRotatingStars,
)


@pytest.fixture
def base_camera_setup(tmp_path):
    config = {
        'VARLIB_FOLDER': str(tmp_path),
        'TEST_CAMERA': {
            'WIDTH': 100,
            'HEIGHT': 80,
            'IMAGE_CIRCLE_DIAMETER': 60,
            'IMAGE_CIRCLE_OFFSET_X': 5,
            'IMAGE_CIRCLE_OFFSET_Y': 5,
            'BUBBLE_COUNT': 5,
            'ROTATING_STAR_COUNT': 10,
            'ROTATING_STAR_FACTOR': 1.0,
        },
    }
    image_q = Queue()
    position_av = Array('d', [0.0] * 5)
    exposure_av = Array('i', [1000000, 1000000, 0, 1000, 100, 30000000, 5000000])
    gain_av = Array('i', [100000, 100000, 0, 0, 100000, 100000, 400000, 50000, 200000, 100000])
    binning_av = Array('i', [1, 1, 1, 2, 1, 1])
    night_av = Array('i', [1, 0])

    return {
        'config': config,
        'image_q': image_q,
        'position_av': position_av,
        'exposure_av': exposure_av,
        'gain_av': gain_av,
        'binning_av': binning_av,
        'night_av': night_av,
        'tmp_path': tmp_path,
    }


def test_test_camera_base_properties_and_controls(base_camera_setup):
    setup = base_camera_setup
    cam = IndiClientTestCameraBase(
        setup['config'],
        setup['image_q'],
        setup['position_av'],
        setup['exposure_av'],
        setup['gain_av'],
        setup['binning_av'],
        setup['night_av'],
    )
    cam.camera_id = 0

    assert cam.width == 100
    assert cam.height == 80
    assert cam.image_circle_diameter == 60
    assert cam.image_circle_offset_x == -5
    assert cam.image_circle_offset_y == -5

    # Gain and binning
    cam.setCcdGain(45.0)
    assert cam.getCcdGain() == 45.0
    assert cam.gain == 45.0

    cam.setCcdBinning(2)
    assert cam.binning == 2
    cam.setCcdBinning(None)
    assert cam.binning == 2

    # Cooler & telescope controls
    cam.enableCcdCooler()
    cam.disableCcdCooler()
    cam.setCcdTemperature(10.0)
    cam.setCcdScopeInfo('RA', 'DEC')
    assert cam.getCcdTemperature() == -273.15

    # findCcd and getCcdInfo
    ccd = cam.findCcd()
    assert ccd.width == 100
    assert ccd.height == 80
    info = cam.getCcdInfo()
    assert 'CCD_EXPOSURE' in info
    assert 'CCD_INFO' in info
    assert 'CCD_FRAME' in info


def test_test_camera_base_exposure_async_and_abort(base_camera_setup):
    setup = base_camera_setup
    cam = IndiClientTestCameraBase(
        setup['config'],
        setup['image_q'],
        setup['position_av'],
        setup['exposure_av'],
        setup['gain_av'],
        setup['binning_av'],
        setup['night_av'],
    )
    cam.camera_id = 0
    cam.findCcd()
    cam._image = np.zeros((80, 100, 3), dtype=np.uint16)
    cam.updateImage = MagicMock()

    # Trigger async exposure
    cam.setCcdExposure(exposure=2.0, gain=10.0, binning=1, sync=False)
    assert cam.active_exposure is True

    # Calling exposure while active returns early
    cam.setCcdExposure(exposure=5.0, gain=10.0, binning=1, sync=False)

    # Immediately check status -> BUSY
    status, state = cam.getCcdExposureStatus()
    assert status is False and state == 'BUSY'

    # Abort exposure
    temp_file = cam.current_exposure_file_p
    cam.abortCcdExposure()
    assert cam.active_exposure is False
    assert not temp_file.exists()

    # When not active, status returns True, READY
    status, state = cam.getCcdExposureStatus()
    assert status is True and state == 'READY'

    # Calling abort again handles FileNotFoundError
    cam.abortCcdExposure()


def test_test_camera_base_exposure_sync_and_status(base_camera_setup):
    setup = base_camera_setup
    cam = IndiClientTestCameraBase(
        setup['config'],
        setup['image_q'],
        setup['position_av'],
        setup['exposure_av'],
        setup['gain_av'],
        setup['binning_av'],
        setup['night_av'],
    )
    cam.camera_id = 0
    cam.findCcd()
    cam._image = np.zeros((80, 100, 3), dtype=np.uint16)
    cam.updateImage = MagicMock()

    # Simulate completed exposure via getCcdExposureStatus
    cam.setCcdExposure(exposure=0.01, gain=20.0, binning=1, sync=False)
    time.sleep(0.02)
    status, state = cam.getCcdExposureStatus()
    assert status is True and state == 'READY'
    assert setup['image_q'].qsize() == 1
    job = setup['image_q'].get()
    assert job['exposure'] == 0.01
    assert job['camera_id'] == 0

    # Sync exposure with mock sleep
    with patch('time.sleep', return_value=None):
        cam.setCcdExposure(exposure=1.0, gain=30.0, binning=1, sync=True)
        assert cam.active_exposure is False
        assert setup['image_q'].qsize() == 1

    # NamedTemporaryFile OSError handling
    with patch('tempfile.NamedTemporaryFile', side_effect=OSError("Disk full")):
        cam.setCcdExposure(exposure=1.0, gain=10.0, binning=1, sync=False)


def test_test_camera_bubbles_lifecycle_and_caching(base_camera_setup):
    setup = base_camera_setup
    cam = IndiClientTestCameraBubbles(
        setup['config'],
        setup['image_q'],
        setup['position_av'],
        setup['exposure_av'],
        setup['gain_av'],
        setup['binning_av'],
        setup['night_av'],
    )
    cam.camera_id = 1
    cam.findCcd()

    # 1. First updateImage generates random bubbles array
    cam.updateImage(binning=1)
    assert cam._image is not None
    assert cam._image.shape == (80, 100, 3)
    assert cam.bubbles_array is not None
    assert cam.bubbles_array.shape[1] == 5

    # Move bubbles past boundary to hit reset branch
    cam.bubbles_array[1][0] = 500
    cam.updateImage(binning=1)

    # 2. disconnectServer saves numpy data
    cam.disconnectServer()
    store_file = cam.varlib_folder_p.joinpath(cam._bubbles_store_tmpl.format(cam.camera_id))
    assert store_file.exists()

    # 3. Reload from cache
    cam2 = IndiClientTestCameraBubbles(
        setup['config'],
        setup['image_q'],
        setup['position_av'],
        setup['exposure_av'],
        setup['gain_av'],
        setup['binning_av'],
        setup['night_av'],
    )
    cam2.camera_id = 1
    cam2.findCcd()
    cam2.updateImage(binning=1)
    assert cam2.bubbles_array is not None

    # 4. Cache count mismatch
    cam2.bubble_count = 10
    cam2.bubbles_array = None
    cam2.updateImage(binning=1)
    assert cam2.bubbles_array.shape[1] == 10

    # 5. Corrupted cache (ValueError / EOFError)
    store_file.write_bytes(b'corrupted numpy data')
    cam2.bubbles_array = None
    cam2.bubble_count = 5
    cam2.updateImage(binning=1)
    assert cam2.bubbles_array.shape[1] == 5

    store_file.write_bytes(b'eof')
    with patch('numpy.load', side_effect=EOFError("EOF")):
        cam2.bubbles_array = None
        cam2.updateImage(binning=1)
        assert cam2.bubbles_array.shape[1] == 5


def test_test_camera_rotating_stars_lifecycle_and_caching(base_camera_setup):
    setup = base_camera_setup
    cam = IndiClientTestCameraRotatingStars(
        setup['config'],
        setup['image_q'],
        setup['position_av'],
        setup['exposure_av'],
        setup['gain_av'],
        setup['binning_av'],
        setup['night_av'],
    )
    cam.camera_id = 2
    cam.findCcd()

    # 1. First updateImage generates stars array and applies rotation
    cam.updateImage(binning=1)
    assert cam._image is not None
    assert cam._image.shape == (80, 100, 3)
    assert cam.stars_array is not None
    assert cam.stars_array.shape[1] == 10

    # Second updateImage after a small delay rotates the stars
    cam._last_exposure_time = time.time() - 10
    cam.updateImage(binning=1)

    # 2. disconnectServer saves numpy data
    cam.disconnectServer()
    store_file = cam.varlib_folder_p.joinpath(cam._stars_store_tmpl.format(cam.camera_id))
    assert store_file.exists()

    # 3. Reload from cache
    cam2 = IndiClientTestCameraRotatingStars(
        setup['config'],
        setup['image_q'],
        setup['position_av'],
        setup['exposure_av'],
        setup['gain_av'],
        setup['binning_av'],
        setup['night_av'],
    )
    cam2.camera_id = 2
    cam2.findCcd()
    cam2.updateImage(binning=1)
    assert cam2.stars_array is not None

    # 4. Cache count mismatch
    cam2.star_count = 20
    cam2.stars_array = None
    cam2.updateImage(binning=1)
    assert cam2.stars_array.shape[1] == 20

    # 5. Corrupt cache file (ValueError / EOFError)
    store_file.write_bytes(b'corrupt data')
    cam2.stars_array = None
    cam2.star_count = 10
    cam2.updateImage(binning=1)
    assert cam2.stars_array.shape[1] == 10

    store_file.write_bytes(b'eof')
    with patch('numpy.load', side_effect=EOFError("EOF")):
        cam2.stars_array = None
        cam2.updateImage(binning=1)
        assert cam2.stars_array.shape[1] == 10

