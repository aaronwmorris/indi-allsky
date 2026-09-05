import ctypes
import signal
import time
from multiprocessing import Array, Queue
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky import constants
from indi_allsky.capture import CaptureWorker
from indi_allsky.flask.models import IndiAllSkyDbCameraTable
from indi_allsky.flask import db


@pytest.fixture
def capture_worker_setup(app, base_config):
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        if not cam:
            cam = IndiAllSkyDbCameraTable(
                name='Test Capture Camera',
                uuid='cam-cap-test-1',
                latitude=-34.9285,
                longitude=138.6007,
                elevation=50,
                nightSunAlt=-6.0,
            )
            db.session.add(cam)
            db.session.commit()

        config = base_config

        error_q = Queue()
        capture_q = Queue()
        image_q = Queue()
        video_q = Queue()
        upload_q = Queue()

        position_av = Array('d', [0.0] * 5)
        exposure_av = Array(ctypes.c_int32, [1000000, 1000000, 0, 1000, 100, 30000000, 5000000])
        gain_av = Array(ctypes.c_int32, [100000, 100000, 0, 0, 100000, 100000, 400000, 50000, 200000, 100000])
        binning_av = Array('i', [1, 1, 1, 2, 1, 1])
        sensors_temp_av = Array('f', [0.0] * 110)
        sensors_user_av = Array('f', [0.0] * 110)
        night_av = Array('i', [1, 0])
        astro_av = Array('f', [0.0] * 10)

        worker = CaptureWorker(
            idx=0,
            config=config,
            error_q=error_q,
            capture_q=capture_q,
            image_q=image_q,
            video_q=video_q,
            upload_q=upload_q,
            position_av=position_av,
            exposure_av=exposure_av,
            gain_av=gain_av,
            binning_av=binning_av,
            sensors_temp_av=sensors_temp_av,
            sensors_user_av=sensors_user_av,
            night_av=night_av,
            astro_av=astro_av,
        )

        return worker


def test_capture_worker_init(capture_worker_setup):
    worker = capture_worker_setup
    assert worker.name == 'Capture-0'
    assert worker._shutdown is False
    assert worker.periodic_tasks_offset == 300.0


def test_capture_worker_signals(capture_worker_setup):
    worker = capture_worker_setup

    worker.sighup_handler_worker(signal.SIGHUP, None)
    assert worker._shutdown is True

    worker._shutdown = False
    worker.sigterm_handler_worker(signal.SIGTERM, None)
    assert worker._shutdown is True

    worker._shutdown = False
    worker.sigint_handler_worker(signal.SIGINT, None)
    assert worker._shutdown is True


def test_capture_worker_detect_night(capture_worker_setup):
    worker = capture_worker_setup
    worker.detectNight()
    # verify astro_av values populated
    assert -90.0 <= worker.astro_av[constants.ASTRO_SUN_ALT] <= 90.0
    assert -90.0 <= worker.astro_av[constants.ASTRO_MOON_ALT] <= 90.0
    assert 0.0 <= worker.astro_av[constants.ASTRO_MOON_PHASE] <= 100.0


def test_capture_worker_update_sensor_slot_labels(capture_worker_setup):
    worker = capture_worker_setup
    worker.update_sensor_slot_labels()
    # verify slots initialized
    assert len(worker.SENSOR_SLOTS) > 0

