import ctypes
import signal
from multiprocessing import Array, Queue
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky.image import ImageWorker
from indi_allsky.flask.models import IndiAllSkyDbCameraTable
from indi_allsky.flask import db


@pytest.fixture
def image_worker_setup(app, base_config):
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        if not cam:
            cam = IndiAllSkyDbCameraTable(
                name='ImageWorker Camera',
                uuid='cam-img-test-1',
                latitude=-34.9285,
                longitude=138.6007,
                elevation=50,
                nightSunAlt=-6.0,
            )
            db.session.add(cam)
            db.session.commit()

        config = base_config

        error_q = Queue()
        image_q = Queue()
        upload_q = Queue()

        position_av = Array('d', [0.0] * 5)
        exposure_av = Array(ctypes.c_int32, [1000000, 1000000, 0, 1000, 100, 30000000, 5000000])
        gain_av = Array(ctypes.c_int32, [100000, 100000, 0, 0, 100000, 100000, 400000, 50000, 200000, 100000])
        binning_av = Array('i', [1, 1, 1, 2, 1, 1])
        sensors_temp_av = Array('f', [0.0] * 110)
        sensors_user_av = Array('f', [0.0] * 110)
        night_av = Array('i', [1, 0])
        astro_av = Array('f', [0.0] * 10)

        worker = ImageWorker(
            idx=0,
            config=config,
            error_q=error_q,
            image_q=image_q,
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


def test_image_worker_init(image_worker_setup):
    worker = image_worker_setup
    assert worker.name == 'Image-0'
    assert worker._shutdown is False
    assert worker.sqm_history_minutes == 30


def test_image_worker_signals(image_worker_setup):
    worker = image_worker_setup

    worker.sighup_handler_worker(signal.SIGHUP, None)
    assert worker._shutdown is True

    worker._shutdown = False
    worker.sigterm_handler_worker(signal.SIGTERM, None)
    assert worker._shutdown is True

    worker._shutdown = False
    worker.sigint_handler_worker(signal.SIGINT, None)
    assert worker._shutdown is True


def test_image_worker_properties(image_worker_setup):
    worker = image_worker_setup

    worker.libcamera_raw = True
    assert worker.libcamera_raw is True
