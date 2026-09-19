import os
import io
import json
import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

from indi_allsky.flask import db
from indi_allsky.flask.base_views import BaseView
from indi_allsky.flask.views import AjaxLensSolverView, ImageCircleHelperView, ManualGpioView
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbConfigTable,
    IndiAllSkyDbUserTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbTaskQueueTable,
)


@pytest.fixture
def lens_solver_db(flask_app):
    """Seed database for lens solver and image circle helper tests."""
    with flask_app.app_context():
        db.session.query(IndiAllSkyDbTaskQueueTable).delete()
        db.session.query(IndiAllSkyDbImageTable).delete()
        db.session.query(IndiAllSkyDbCameraTable).delete()
        db.session.query(IndiAllSkyDbConfigTable).delete()
        db.session.query(IndiAllSkyDbUserTable).delete()
        db.session.commit()

        camera = IndiAllSkyDbCameraTable(
            id=1,
            name="main_camera",
            driver="indi_asi_ccd",
            friendlyName="Camera 1",
            uuid="cam1_uuid",
            lensImageCircle=1000,
            latitude=-34.0,
            longitude=138.0,
            elevation=0.0,
            nightSunAlt=-6.0,
        )
        db.session.add(camera)

        system_user = IndiAllSkyDbUserTable(
            username="system",
            email="system@example.com",
            password="pass",
            admin=True,
        )
        db.session.add(system_user)

        admin_user = IndiAllSkyDbUserTable(
            username="admin",
            email="admin@example.com",
            password="pass",
            admin=True,
        )
        db.session.add(admin_user)

        normal_user = IndiAllSkyDbUserTable(
            username="user",
            email="user@example.com",
            password="pass",
            admin=False,
        )
        db.session.add(normal_user)

        config = IndiAllSkyDbConfigTable(
            id=1,
            level=1,
            note="Initial config",
            data={
                "IMAGE_FOLDER": "/tmp",
                "LENS_OFFSET_X": 5,
                "LENS_OFFSET_Y": -5,
                "KEOGRAM_ANGLE": 90.0,
                "ENCRYPT_PASSWORDS": False,
            },
        )
        db.session.add(config)
        db.session.commit()
        yield


def test_ajax_lens_solver_unknown_action(flask_app, lens_solver_db):
    client = flask_app.test_client()
    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        res = client.post('/indi-allsky/ajax/lens_solver', json={'action': 'unknown'})
        assert res.status_code == 400
        data = res.get_json()
        assert data['message'] == 'Unknown action'


def test_ajax_lens_solver_solve_validation_errors(flask_app, lens_solver_db):
    client = flask_app.test_client()
    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        # 1. Missing solver request values
        with patch('indi_allsky.flask.views.parseSolverRequestValues', return_value=({}, 'Invalid solver params')):
            res = client.post('/indi-allsky/ajax/lens_solver', json={'action': 'solve'})
            assert res.status_code == 400
            assert res.get_json()['message'] == 'Invalid solver params'

        # 2. Missing camera_id and timestamp
        with patch('indi_allsky.flask.views.parseSolverRequestValues', return_value=({}, None)):
            res = client.post('/indi-allsky/ajax/lens_solver', json={'action': 'solve'})
            assert res.status_code == 400
            assert res.get_json()['message'] == 'camera_id and timestamp required'

        # 3. Unknown camera_id
        with patch('indi_allsky.flask.views.parseSolverRequestValues', return_value=({}, None)):
            res = client.post('/indi-allsky/ajax/lens_solver', json={
                'action': 'solve',
                'camera_id': 999,
                'timestamp': 1600000000
            })
            assert res.status_code == 400
            assert res.get_json()['message'] == 'Unknown camera'

        # 4. Invalid timestamp (OverflowError)
        with patch('indi_allsky.flask.views.parseSolverRequestValues', return_value=({}, None)):
            res = client.post('/indi-allsky/ajax/lens_solver', json={
                'action': 'solve',
                'camera_id': 1,
                'timestamp': 99999999999999999999
            })
            assert res.status_code == 400
            assert res.get_json()['message'] == 'Invalid timestamp'

        # 5. Image not found for timestamp
        with patch('indi_allsky.flask.views.parseSolverRequestValues', return_value=({}, None)):
            res = client.post('/indi-allsky/ajax/lens_solver', json={
                'action': 'solve',
                'camera_id': 1,
                'timestamp': 1600000000
            })
            assert res.status_code == 400
            assert res.get_json()['message'] == 'Image not found for timestamp'


def test_ajax_lens_solver_solve_missing_file_and_errors(flask_app, lens_solver_db):
    client = flask_app.test_client()
    ts = 1600000000
    ts_dt = datetime.fromtimestamp(ts)

    with flask_app.app_context():
        image = IndiAllSkyDbImageTable(
            camera_id=1,
            createDate=ts_dt,
            dayDate=ts_dt.date(),
            exposure=1.0,
            gain=100.0,
            adu=30000.0,
            filename="test_image.jpg",
        )
        db.session.add(image)
        db.session.commit()

    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        # 1. Missing filesystem path
        with patch('indi_allsky.flask.views.parseSolverRequestValues', return_value=({}, None)):
            with patch.object(IndiAllSkyDbImageTable, 'getFilesystemPath', return_value=Path('/tmp/non_existent_image_file.jpg')):
                res = client.post('/indi-allsky/ajax/lens_solver', json={
                    'action': 'solve',
                    'camera_id': 1,
                    'timestamp': ts
                })
                assert res.status_code == 400
                assert res.get_json()['message'] == 'Image file missing from filesystem'

        # 2. Lock acquire failure (429)
        test_img_path = Path('/tmp/test_lens_image.jpg')
        test_img_path.touch()
        try:
            with patch('indi_allsky.flask.views.parseSolverRequestValues', return_value=({}, None)):
                with patch.object(IndiAllSkyDbImageTable, 'getFilesystemPath', return_value=test_img_path):
                    mock_lock = MagicMock()
                    mock_lock.acquire.return_value = False
                    with patch.object(AjaxLensSolverView, '_solve_lock', mock_lock):
                        res = client.post('/indi-allsky/ajax/lens_solver', json={
                            'action': 'solve',
                            'camera_id': 1,
                            'timestamp': ts
                        })
                        assert res.status_code == 429
                        assert 'already in progress' in res.get_json()['message']

            # 3. Solver exception (500)
            with patch('indi_allsky.flask.views.parseSolverRequestValues', return_value=({}, None)):
                with patch.object(IndiAllSkyDbImageTable, 'getFilesystemPath', return_value=test_img_path):
                    with patch('indi_allsky.flask.views.IndiAllSkyLensSolver') as mock_solver_cls:
                        mock_solver_cls.return_value.solve.side_effect = Exception('Solver fail')
                        res = client.post('/indi-allsky/ajax/lens_solver', json={
                            'action': 'solve',
                            'camera_id': 1,
                            'timestamp': ts
                        })
                        assert res.status_code == 500
                        assert res.get_json()['message'] == 'Solver error -- check server logs'

            # 4. Successful solve
            with patch('indi_allsky.flask.views.parseSolverRequestValues', return_value=({}, None)):
                with patch.object(IndiAllSkyDbImageTable, 'getFilesystemPath', return_value=test_img_path):
                    with patch('indi_allsky.flask.views.IndiAllSkyLensSolver') as mock_solver_cls:
                        mock_solver_cls.return_value.solve.return_value = {'success': True, 'focal_length': 2.1}
                        res = client.post('/indi-allsky/ajax/lens_solver', json={
                            'action': 'solve',
                            'camera_id': 1,
                            'timestamp': ts
                        })
                        assert res.status_code == 200
                        assert res.get_json()['success'] is True
        finally:
            if test_img_path.exists():
                test_img_path.unlink()


def test_ajax_lens_solver_save_action(flask_app, lens_solver_db):
    client = flask_app.test_client()

    # 1. Validation error in save
    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        with patch('indi_allsky.flask.views.parseSolverRequestValues', return_value=({}, 'Invalid save params')):
            res = client.post('/indi-allsky/ajax/lens_solver', json={'action': 'save'})
            assert res.status_code == 400
            assert res.get_json()['message'] == 'Invalid save params'

    # 2. Successful save without reload
    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        with patch('indi_allsky.flask.views.parseSolverRequestValues', return_value=({'focal_length': 2.1}, None)):
            with patch('indi_allsky.flask.views.applySolvedValuesToConfig'):
                res = client.post('/indi-allsky/ajax/lens_solver', json={'action': 'save', 'RELOAD_ON_SAVE': False})
                assert res.status_code == 200
                assert res.get_json()['success'] is True
                assert 'Values become page defaults' in res.get_json()['message']

    # 3. Successful save with reload_on_save
    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        with patch('indi_allsky.flask.views.parseSolverRequestValues', return_value=({'focal_length': 2.1}, None)):
            with patch('indi_allsky.flask.views.applySolvedValuesToConfig'):
                res = client.post('/indi-allsky/ajax/lens_solver', json={'action': 'save', 'RELOAD_ON_SAVE': True})
                assert res.status_code == 200
                assert res.get_json()['success'] is True
                assert 'Reloading indi-allsky service' in res.get_json()['message']


def test_image_circle_helper_view(flask_app, lens_solver_db):
    client = flask_app.test_client()
    now_dt = datetime.now()

    with flask_app.app_context():
        image = IndiAllSkyDbImageTable(
            camera_id=1,
            createDate=now_dt,
            dayDate=now_dt.date(),
            exposure=1.0,
            gain=100.0,
            adu=30000.0,
            filename="circle_test.jpg",
        )
        db.session.add(image)
        db.session.commit()

    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        res = client.get('/indi-allsky/imagecirclehelper?camera_id=1')
        assert res.status_code == 200
