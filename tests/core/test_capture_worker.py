import ctypes
from multiprocessing import Queue, Array
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky.capture import CaptureWorker
from indi_allsky.flask.models import IndiAllSkyDbCameraTable
from indi_allsky.flask import db


def test_capture_worker_init(app, tmp_path):
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        if not cam:
            cam = IndiAllSkyDbCameraTable(
                name='CaptureWorker Cam',
                uuid='cam-capture-1',
                latitude=-34.9285,
                longitude=138.6007,
                elevation=50,
                nightSunAlt=-6.0,
            )
            db.session.add(cam)
            db.session.commit()

        config = {
            'LOCATION_LATITUDE': -34.9285,
            'LOCATION_LONGITUDE': 138.6007,
            'LOCATION_ELEVATION': 50,
            'NIGHT_SUN_ALT_DEG': -6.0,
            'NIGHT_MOONMODE_ALT_DEG': -12.0,
            'IMAGE_FOLDER': str(tmp_path),
            'VARLIB_FOLDER': str(tmp_path),
        }

        error_q = Queue()
        capture_q = Queue()
        image_q = Queue()
        video_q = Queue()
        upload_q = Queue()

        position_av = Array('f', [-34.9285, 138.6007, 50.0, 0.0, 0.0])
        exposure_av = Array(ctypes.c_int32, [-1] * 7)
        gain_av = Array(ctypes.c_int32, [-1] * 10)
        binning_av = Array('i', [-1] * 6)
        sensors_temp_av = Array('f', [0.0] * 60)
        sensors_user_av = Array('f', [0.0] * 110)
        night_av = Array('i', [-1, -1])
        astro_av = Array('f', [0.0, 0.0, 0.0])

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

        assert worker.name == 'Capture-0'
        assert len(worker.SENSOR_SLOTS) > 50
        assert worker.focus_mode is False
        assert worker._shutdown is False
