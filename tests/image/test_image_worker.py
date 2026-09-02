import copy
import ctypes
from multiprocessing import Queue, Array
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky.image import ImageWorker
from indi_allsky.config import IndiAllSkyConfig
from indi_allsky.flask.models import IndiAllSkyDbCameraTable, IndiAllSkyDbConfigTable
from indi_allsky.flask import db


def test_image_worker_init(app, tmp_path):
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        if not cam:
            cam = IndiAllSkyDbCameraTable(
                name='ImageWorker Cam',
                uuid='cam-image-1',
                latitude=-34.9285,
                longitude=138.6007,
                elevation=50,
                nightSunAlt=-6.0,
            )
            db.session.add(cam)

        config_entry = IndiAllSkyDbConfigTable.query.first()
        if not config_entry:
            config_entry = IndiAllSkyDbConfigTable(
                config={'WEBSITE': {'TITLE': 'indi-allsky'}},
            )
            db.session.add(config_entry)
        db.session.commit()

        config_obj = IndiAllSkyConfig()
        config = copy.deepcopy(config_obj.config)
        config['IMAGE_FOLDER'] = str(tmp_path)
        config['VARLIB_FOLDER'] = str(tmp_path)

        error_q = Queue()
        image_q = Queue()
        upload_q = Queue()

        position_av = Array('f', [-34.9285, 138.6007, 50.0, 0.0, 0.0])
        exposure_av = Array(ctypes.c_int32, [-1] * 7)
        gain_av = Array(ctypes.c_int32, [-1] * 10)
        binning_av = Array('i', [-1] * 6)
        sensors_temp_av = Array('f', [0.0] * 60)
        sensors_user_av = Array('f', [0.0] * 110)
        night_av = Array('i', [-1, -1])
        astro_av = Array('f', [0.0, 0.0, 0.0])

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

        assert worker.name == 'Image-0'
        assert worker.image_count == 0
        assert worker.generate_mask_base is True
        assert worker._shutdown is False

        worker.libcamera_raw = True
        assert worker.libcamera_raw is True
