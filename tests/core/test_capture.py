import ctypes
import signal
import time
from multiprocessing import Array, Queue
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky import constants
from indi_allsky.capture import CaptureWorker
from indi_allsky.flask.models import IndiAllSkyDbCameraTable, IndiAllSkyDbTaskQueueTable
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
                lensFocalLength=2.5,
                lensFocalRatio=1.4,
                lensImageCircle=1000,
                width=1920,
                height=1080,
                pixelSize=2.9,
                cfa=constants.CFA_RGGB,
                owner='Admin',
            )
            db.session.add(cam)
            db.session.commit()

        config = dict(base_config)
        config['LOCATION_LATITUDE'] = -34.9285
        config['LOCATION_LONGITUDE'] = 138.6007
        config['LOCATION_ELEVATION'] = 50

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


def test_capture_worker_get_ccd_temperature(capture_worker_setup):
    worker = capture_worker_setup
    worker.indiclient = MagicMock()
    worker.indiclient.getCcdTemperature.return_value = 18.5

    temp = worker.getCcdTemperature()
    assert temp == 18.5
    assert worker.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP] == 18.5


def test_capture_worker_update_config_location(capture_worker_setup, app):
    worker = capture_worker_setup
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        worker.camera_id = cam.id

        worker.updateConfigLocation(-34.95, 138.62, 75)
        assert worker.config['LOCATION_LATITUDE'] == -34.95
        assert worker.config['LOCATION_LONGITUDE'] == 138.62
        assert worker.config['LOCATION_ELEVATION'] == 75

        # Verify task was added
        task = IndiAllSkyDbTaskQueueTable.query.order_by(IndiAllSkyDbTaskQueueTable.id.desc()).first()
        assert task is not None
        assert task.data['action'] == 'setlocation'
        assert task.data['latitude'] == -34.95



def test_capture_worker_get_gps_position(capture_worker_setup, app):
    worker = capture_worker_setup
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        worker.camera_id = cam.id
        worker.config['GPS_ENABLE'] = True

        worker.indiclient = MagicMock()
        worker.indiclient.gps_device = True
        worker.indiclient.getGpsPosition.return_value = (-34.9285, 138.6007, 50.0)

        lat, lon, elev = worker.getGpsPosition()
        assert lat == -34.9285
        assert lon == 138.6007
        assert elev == 50.0


def test_capture_worker_get_telescope_ra_dec(capture_worker_setup):
    worker = capture_worker_setup
    worker.indiclient = MagicMock()
    worker.indiclient.telescope_device = True
    worker.indiclient.getTelescopeRaDec.return_value = (180.5, 45.2)

    ra, dec = worker.getTelescopeRaDec()
    assert ra == 180.5
    assert dec == 45.2
    assert worker.position_av[constants.POSITION_RA] == 180.5
    assert worker.position_av[constants.POSITION_DEC] == 45.2


def test_capture_worker_task_queue_generators(capture_worker_setup, app):
    worker = capture_worker_setup
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()

        worker._generateDayTimelapse('20260906', cam.id)
        worker._generateNightTimelapse('20260906', cam.id)
        worker._generateNightKeogram('20260906', cam.id)
        worker._generateDayKeogram('20260906', cam.id)
        worker._uploadAllskyEndOfNight(cam.id)
        worker._expireData(cam.id)

        # Check tasks queued
        tasks = IndiAllSkyDbTaskQueueTable.query.all()
        assert len(tasks) >= 6
