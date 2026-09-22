import sys
from unittest.mock import MagicMock
from datetime import datetime, timedelta, timezone
import pytest
from passlib.hash import argon2

if 'gunicorn' not in sys.modules:
    try:
        import gunicorn  # noqa: F401
    except ImportError:
        mock_gunicorn = MagicMock()
        mock_gunicorn.__version__ = '21.2.0'
        sys.modules['gunicorn'] = mock_gunicorn

from indi_allsky import constants
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbUserTable,
    IndiAllSkyDbConfigTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbTaskQueueTable,
    IndiAllSkyDbNotificationTable,
    NotificationCategory,
    TaskQueueState,
    TaskQueueQueue,
)
from indi_allsky.flask import db


@pytest.fixture
def populated_env(flask_app, db):
    with flask_app.app_context():
        camera = IndiAllSkyDbCameraTable.query.first()
        if not camera:
            camera = IndiAllSkyDbCameraTable(
                name="main_camera",
                uuid="cam-main-uuid-1",
                driver="indi_simulator_ccd",
                friendlyName="Main Camera",
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
                owner="Admin",
                local=True,
            )
            db.session.add(camera)
        else:
            camera.uuid = "cam-main-uuid-1"
            camera.lensFocalLength = 2.5
            camera.lensFocalRatio = 1.4
            camera.lensImageCircle = 1000
            camera.width = 1920
            camera.height = 1080
            camera.pixelSize = 2.9
            camera.cfa = constants.CFA_RGGB
            camera.owner = "Admin"
            db.session.add(camera)

        config_entry = IndiAllSkyDbConfigTable.query.first()
        if not config_entry:
            config_entry = IndiAllSkyDbConfigTable(
                data={
                    'WEBSITE': {'TITLE': 'indi-allsky'},
                    'SYNCAPI': {'ENABLE': False},
                    'IMAGE_FILE_TYPE': 'jpg',
                },
                level="1.0",
                note='test',
            )
            db.session.add(config_entry)
        else:
            config_entry.data = {
                'WEBSITE': {'TITLE': 'indi-allsky'},
                'SYNCAPI': {'ENABLE': False},
                'IMAGE_FILE_TYPE': 'jpg',
            }
            db.session.add(config_entry)

        admin_user = IndiAllSkyDbUserTable.query.filter_by(username="admin").first()
        if not admin_user:
            admin_user = IndiAllSkyDbUserTable(
                username="admin",
                password=argon2.hash("AdminPassword123!"),
                email="admin@example.org",
                name="Admin User",
                active=True,
                admin=True,
                staff=True,
            )
            db.session.add(admin_user)

        # Seed sample images
        now = datetime.now(timezone.utc)
        img = IndiAllSkyDbImageTable(
            camera_id=1,
            createDate=now,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
            adu=128.0,
            sqm=21.5,
            stars=42,
            filename="test_img.jpg",
            data={'sqm': 21.5, 'stars': 42},
        )
        db.session.add(img)

        # Seed sample task
        task = IndiAllSkyDbTaskQueueTable(
            createDate=now,
            queue=TaskQueueQueue.VIDEO,
            state=TaskQueueState.QUEUED,
            data={'action': 'test'},
        )
        db.session.add(task)

        # Seed sample notification
        notif = IndiAllSkyDbNotificationTable(
            category=NotificationCategory.GENERAL,
            item="Test Item",
            notification="Test message",
            createDate=now,
            expireDate=now + timedelta(days=1),
        )
        db.session.add(notif)

        db.session.commit()
        yield


@pytest.fixture
def auth_client(flask_app, populated_env):
    client = flask_app.test_client()
    client.post(
        '/indi-allsky/login',
        json={'USERNAME': 'admin', 'PASSWORD': 'AdminPassword123!', 'NEXT': ''},
    )
    return client


# ==============================================================================
# Public and JSON Endpoint Tests
# ==============================================================================

def test_json_endpoints(flask_app, populated_env):
    client = flask_app.test_client()

    routes = [
        '/indi-allsky/js/sensor_panel?camera_id=1',
        '/indi-allsky/js/latest?camera_id=1',
        '/indi-allsky/js/latest_panorama?camera_id=1',
        '/indi-allsky/js/latest_rawimage?camera_id=1',
        '/indi-allsky/js/loop?camera_id=1',
        '/indi-allsky/js/looppanorama?camera_id=1',
        '/indi-allsky/js/charts?camera_id=1',
        '/indi-allsky/js/support?camera_id=1',
    ]
    for route in routes:
        resp = client.get(route)
        assert resp.status_code in (200, 204, 302, 404), f"Failed on {route}"


def test_public_view_modes(flask_app, populated_env):
    client = flask_app.test_client()

    routes = [
        '/indi-allsky/index_canvas',
        '/indi-allsky/index_img',
        '/indi-allsky/panorama',
        '/indi-allsky/panorama_canvas',
        '/indi-allsky/panorama_img',
        '/indi-allsky/raw',
        '/indi-allsky/raw_canvas',
        '/indi-allsky/raw_img',
        '/indi-allsky/loop',
        '/indi-allsky/loop_canvas',
        '/indi-allsky/loop_img',
        '/indi-allsky/looppanorama',
        '/indi-allsky/looppanorama_canvas',
        '/indi-allsky/looppanorama_img',
        '/indi-allsky/loopraw',
        '/indi-allsky/loopraw_canvas',
        '/indi-allsky/loopraw_img',
    ]
    for route in routes:
        resp = client.get(route)
        assert resp.status_code == 200, f"Failed on {route}"


# ==============================================================================
# Authenticated Admin View Tests
# ==============================================================================

def test_admin_config_views(auth_client):
    # GET config page
    resp = auth_client.get('/indi-allsky/config')
    assert resp.status_code == 200

    # GET config list page
    resp = auth_client.get('/indi-allsky/config/list')
    assert resp.status_code == 200

    # GET user info page
    resp = auth_client.get('/indi-allsky/user')
    assert resp.status_code == 200

    # GET system info page
    resp = auth_client.get('/indi-allsky/system')
    assert resp.status_code == 200


def test_admin_operational_views(auth_client):
    resp = auth_client.get('/indi-allsky/focus')
    assert resp.status_code == 200

    resp = auth_client.get('/indi-allsky/log')
    assert resp.status_code == 200

    resp = auth_client.get('/indi-allsky/support')
    assert resp.status_code == 200

    resp = auth_client.get('/indi-allsky/camera')
    assert resp.status_code == 200

    resp = auth_client.get('/indi-allsky/lag')
    assert resp.status_code == 200

    resp = auth_client.get('/indi-allsky/adu')
    assert resp.status_code == 200

    resp = auth_client.get('/indi-allsky/darks')
    assert resp.status_code == 200

    resp = auth_client.get('/indi-allsky/mask')
    assert resp.status_code == 200

    resp = auth_client.get('/indi-allsky/astropanel')
    assert resp.status_code == 200

    resp = auth_client.get('/indi-allsky/longtermkeogram')
    assert resp.status_code == 200


def test_admin_ajax_calls(auth_client):
    resp = auth_client.get('/indi-allsky/ajax/system/stats?camera_id=1')
    assert resp.status_code in (200, 400)

    resp = auth_client.get('/indi-allsky/ajax/astropanel?camera_id=1')
    assert resp.status_code in (200, 400)

    resp = auth_client.post(
        '/indi-allsky/ajax/exclude',
        json={'CAMERA_ID': 1, 'EXCLUDE_IMAGE_ID': '1', 'EXCLUDE_EXCLUDE': True},
    )
    assert resp.status_code in (200, 302, 400)
