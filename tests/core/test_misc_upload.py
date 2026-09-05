import queue
from datetime import datetime, date
from unittest.mock import MagicMock
from pathlib import Path
import pytest

from indi_allsky.miscUpload import miscUpload
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbTaskQueueTable,
    TaskQueueState,
    TaskQueueQueue,
)
from indi_allsky.flask import db


def test_misc_upload_disabled(app):
    with app.app_context():
        upload_q = queue.Queue()
        night_av = [1, 0]
        uploader = miscUpload({'FILETRANSFER': {'UPLOAD_IMAGE': False}}, upload_q, night_av)

        # upload_image should return early if upload is disabled
        uploader.upload_image(None)
        assert uploader._image_count == 0


def test_misc_upload_image_task(app, tmp_path):
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        if not cam:
            cam = IndiAllSkyDbCameraTable(
                name='MiscUpload Cam',
                uuid='cam-misc-1',
                latitude=-34.9285,
                longitude=138.6007,
                elevation=50,
                nightSunAlt=-6.0,
            )
            db.session.add(cam)
            db.session.commit()

        img_file = tmp_path / "test_img.jpg"
        img_file.write_bytes(b"image data")

        image = IndiAllSkyDbImageTable(
            camera_id=cam.id,
            filename=str(img_file),
            createDate=datetime.now(),
            dayDate=date.today(),
            night=True,
            exposure=10.0,
            gain=100.0,
            binmode=1,
            adu=128.0,
            data={},
        )
        db.session.add(image)
        db.session.commit()

        config = {
            'IMAGE_FILE_TYPE': 'jpg',
            'FILETRANSFER': {
                'UPLOAD_IMAGE': 1,
                'REMOTE_IMAGE_FOLDER': '/remote/images',
                'REMOTE_IMAGE_NAME': 'img_{0:s}.jpg',
            },
        }

        upload_q = queue.Queue()
        night_av = [1, 0]
        uploader = miscUpload(config, upload_q, night_av)

        uploader.upload_image(image)
        assert uploader._image_count == 1
        assert upload_q.qsize() == 1
        task_msg = upload_q.get()
        assert 'task_id' in task_msg
