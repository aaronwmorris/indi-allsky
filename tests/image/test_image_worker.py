import ctypes
from datetime import datetime, timezone, timedelta
from multiprocessing import Array, Queue
from pathlib import Path
from unittest.mock import MagicMock, patch
import cv2
import numpy as np
import pytest

from indi_allsky import constants
from indi_allsky.image import ImageWorker
from indi_allsky.flask.models import IndiAllSkyDbCameraTable, IndiAllSkyDbImageTable
from indi_allsky.flask import db


@pytest.fixture
def image_worker_setup(app, base_config, tmp_path):
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
        config['VARLIB_FOLDER'] = str(tmp_path / 'varlib')
        config['IMAGE_DIR'] = str(tmp_path / 'images')
        Path(config['VARLIB_FOLDER']).mkdir(parents=True, exist_ok=True)
        Path(config['IMAGE_DIR']).mkdir(parents=True, exist_ok=True)

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

    worker.sighup_handler_worker(1, None)
    assert worker._shutdown is True


    worker._shutdown = False
    worker.sigterm_handler_worker(15, None)
    assert worker._shutdown is True

    worker._shutdown = False
    worker.sigint_handler_worker(2, None)
    assert worker._shutdown is True


def test_image_worker_properties(image_worker_setup):
    worker = image_worker_setup

    worker.libcamera_raw = True
    assert worker.libcamera_raw is True


def test_image_worker_decdeg2dms(image_worker_setup):
    worker = image_worker_setup

    # Positive degree
    deg, minutes, seconds = worker.decdeg2dms(34.5678)
    assert deg == 34
    assert minutes == 34
    assert round(seconds, 1) == 4.1

    # Negative degree
    deg_neg, min_neg, sec_neg = worker.decdeg2dms(-12.3456)
    assert deg_neg == -12


def test_image_worker_mask_and_focus_writes(image_worker_setup):
    worker = image_worker_setup
    data = np.full((32, 32, 3), 128, dtype=np.uint8)

    # Base mask
    worker.write_mask_base_img(data)
    assert worker.image_dir.joinpath('mask_base.png').exists()

    # Focus PNG
    worker.write_focus_png(data)
    assert worker.image_dir.joinpath('focus.png').exists()

    # Focus FIT
    worker.write_focus_fit(data)
    assert worker.image_dir.joinpath('focus.fit').exists()


def test_image_worker_get_image_folder(image_worker_setup, app):
    worker = image_worker_setup
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        now = datetime.now()
        folder = worker._getImageFolder(now, now.date(), cam, 'raw')
        assert folder.exists()
        assert str(folder).startswith(str(worker.image_dir))


def test_image_worker_sqm_and_stars_data(image_worker_setup, app):
    worker = image_worker_setup
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        now = datetime.now()

        # Add dummy image record
        img = IndiAllSkyDbImageTable(
            camera_id=cam.id,
            filename='dummy.jpg',
            dayDate=now.date(),
            createDate=now,
            exposure=1.0,
            gain=100.0,
            adu=128.0,
            sqm=21.4,
            stars=55,
        )
        db.session.add(img)
        db.session.commit()

        sqm_data = worker.getSqmData(cam.id)
        assert sqm_data['max'] is not None

        stars_data = worker.getStarsData(cam.id)
        assert stars_data['max'] is not None


def test_image_worker_write_status_json(image_worker_setup, app):
    worker = image_worker_setup
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()

        mock_i_ref = MagicMock()
        mock_i_ref.camera_name = cam.name
        mock_i_ref.gain = 100.0
        mock_i_ref.exposure = 1.0
        mock_i_ref.target_adu = 128.0
        mock_i_ref.sqm_value = 21.0
        mock_i_ref.stars = [1, 2, 3]
        mock_i_ref.lines = []
        mock_i_ref.exp_date = datetime.now()
        mock_i_ref.kpindex = 2.0
        mock_i_ref.ovation_max = 30
        mock_i_ref.aurora_mag_bt = 4.0
        mock_i_ref.aurora_mag_gsm_bz = -1.0
        mock_i_ref.aurora_plasma_density = 3.0
        mock_i_ref.aurora_plasma_speed = 400.0
        mock_i_ref.aurora_plasma_temp = 50000
        mock_i_ref.aurora_n_hemi_gw = 10
        mock_i_ref.aurora_s_hemi_gw = 12
        mock_i_ref.smoke_rating = constants.SMOKE_RATING_CLEAR
        mock_i_ref.uptime = 12345

        worker.write_status_json(mock_i_ref, adu=128.0, adu_average=127.5)
        status_file = worker.varlib_folder_p.joinpath('indi_allsky_status.json')
        assert status_file.exists()
