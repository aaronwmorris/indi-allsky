from datetime import datetime
from datetime import timedelta
import json
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from wtforms import ValidationError

if 'INDI_ALLSKY_FLASK_CONFIG' not in os.environ:
    _tmp_flask_cfg = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
    json.dump({
        'SECRET_KEY': 'test-secret-key',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'MIGRATION_FOLDER': 'migrations',
        'INDI_ALLSKY_IMAGE_FOLDER': tempfile.gettempdir(),
        'ADMIN_NETWORKS': ['127.0.0.1/32'],
    }, _tmp_flask_cfg)
    _tmp_flask_cfg.close()
    os.environ['INDI_ALLSKY_FLASK_CONFIG'] = _tmp_flask_cfg.name

from indi_allsky.flask import create_app
from indi_allsky.flask import db
from indi_allsky.flask.forms import IMAGE_NON_DETECTION_EXPIRE_DAYS_validator
from indi_allsky.flask.models import IndiAllSkyDbCameraTable
from indi_allsky.flask.models import IndiAllSkyDbImageTable
from indi_allsky.video import VideoWorker


class TestNonDetectionExpireValidator:
    def test_accepts_zero_and_positive(self):
        IMAGE_NON_DETECTION_EXPIRE_DAYS_validator(None, SimpleNamespace(data=0))
        IMAGE_NON_DETECTION_EXPIRE_DAYS_validator(None, SimpleNamespace(data=5))

    def test_rejects_negative_or_non_int(self):
        with pytest.raises(ValidationError):
            IMAGE_NON_DETECTION_EXPIRE_DAYS_validator(None, SimpleNamespace(data=-1))
        with pytest.raises(ValidationError):
            IMAGE_NON_DETECTION_EXPIRE_DAYS_validator(None, SimpleNamespace(data=None))


class TestExpireNonDetectionImages:
    def _make_worker(self, config_overrides):
        worker = object.__new__(VideoWorker)
        worker.config = {
            'IMAGE_EXPIRE_DAYS': 10,
            'IMAGE_RAW_EXPIRE_DAYS': 10,
            'IMAGE_FITS_EXPIRE_DAYS': 10,
            'TIMELAPSE_EXPIRE_DAYS': 365,
            'IMAGE_NON_DETECTION_EXPIRE_DAYS': 0,
            **config_overrides,
        }
        worker.image_dir = tempfile.gettempdir()
        worker.scratch_base_dir = type('FakePath', (), {'is_dir': lambda self: False})()
        worker._getFolderFolders = lambda *args, **kwargs: None
        return worker

    def test_purges_only_non_detection_images_older_than_cutoff(self):
        flask_app = create_app()
        now = datetime.now()
        with flask_app.app_context():
            db.create_all()
            cam = IndiAllSkyDbCameraTable(
                uuid='cam-uuid-1',
                name='TestCam',
                friendlyName='TestCam',
            )
            db.session.add(cam)
            db.session.commit()

            old_no_det = IndiAllSkyDbImageTable(
                filename='old_no_det.jpg',
                camera_id=cam.id,
                createDate=now - timedelta(days=5),
                dayDate=(now - timedelta(days=5)).date(),
                exposure=1.0,
                gain=1.0,
                adu=100.0,
                detections=0,
            )
            old_with_det = IndiAllSkyDbImageTable(
                filename='old_with_det.jpg',
                camera_id=cam.id,
                createDate=now - timedelta(days=5),
                dayDate=(now - timedelta(days=5)).date(),
                exposure=1.0,
                gain=1.0,
                adu=100.0,
                detections=2,
            )
            recent_no_det = IndiAllSkyDbImageTable(
                filename='recent_no_det.jpg',
                camera_id=cam.id,
                createDate=now - timedelta(days=1),
                dayDate=(now - timedelta(days=1)).date(),
                exposure=1.0,
                gain=1.0,
                adu=100.0,
                detections=0,
            )
            db.session.add_all([old_no_det, old_with_det, recent_no_det])
            db.session.commit()

            deleted_batches = []

            def fake_delete_assets(table, id_list):
                deleted_batches.append((table, list(id_list)))
                table.query.filter(table.id.in_(id_list)).delete(synchronize_session=False)
                db.session.commit()
                return len(id_list)

            worker = self._make_worker({'IMAGE_NON_DETECTION_EXPIRE_DAYS': 3})
            worker._deleteAssets = fake_delete_assets
            task = MagicMock()

            with patch('indi_allsky.video.asi676mc_calibration.cleanup_expired_sessions', return_value=0):
                worker.expireData(task, camera_id=cam.id)

            remaining = [r.filename for r in IndiAllSkyDbImageTable.query.all()]
            assert 'old_no_det.jpg' not in remaining
            assert 'old_with_det.jpg' in remaining
            assert 'recent_no_det.jpg' in remaining
            task.setSuccess.assert_called_once()
