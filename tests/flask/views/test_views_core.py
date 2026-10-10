import pytest
from passlib.hash import argon2

from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbUserTable,
    IndiAllSkyDbConfigTable,
    IndiAllSkyDbImageTable,
)
from indi_allsky.flask import db


@pytest.fixture
def populated_db(flask_app, db):
    """Seed test database with camera, config, and admin user."""
    with flask_app.app_context():
        camera = IndiAllSkyDbCameraTable(
            name="main_camera",
            driver="indi_simulator_ccd",
            friendlyName="Main Camera",
            latitude=-34.9285,
            longitude=138.6007,
            elevation=50,
            nightSunAlt=-6.0,
            local=True,
        )
        db.session.add(camera)

        config_entry = IndiAllSkyDbConfigTable(
            data={'WEBSITE': {'TITLE': 'indi-allsky'}},
            level="1.0",
            note='test',
        )
        db.session.add(config_entry)

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
        db.session.commit()
        yield


def test_index_view_anonymous(flask_app, populated_db):
    client = flask_app.test_client()
    response = client.get('/indi-allsky/')
    assert response.status_code == 200


def test_sensor_panel_view(flask_app, populated_db):
    client = flask_app.test_client()
    response = client.get('/indi-allsky/sensor_panel')
    assert response.status_code == 200


def test_sqm_view(flask_app, populated_db):
    client = flask_app.test_client()
    response = client.get('/indi-allsky/sqm')
    assert response.status_code == 200


def test_charts_view(flask_app, populated_db):
    client = flask_app.test_client()
    response = client.get('/indi-allsky/charts')
    assert response.status_code == 200


def test_image_viewer_view(flask_app, populated_db):
    client = flask_app.test_client()
    response = client.get('/indi-allsky/imageviewer')
    assert response.status_code == 200


def test_gallery_view(flask_app, populated_db):
    client = flask_app.test_client()
    response = client.get('/indi-allsky/gallery')
    assert response.status_code == 200


def test_video_viewer_view(flask_app, populated_db):
    client = flask_app.test_client()
    response = client.get('/indi-allsky/videoviewer')
    assert response.status_code == 200


def test_ajax_status_update(flask_app, populated_db):
    client = flask_app.test_client()
    response = client.get('/indi-allsky/ajax/status_update?camera_id=1')
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, dict)


def test_config_view_requires_auth_or_renders(flask_app, populated_db):
    client = flask_app.test_client()

    # Log in as admin
    login_res = client.post(
        '/indi-allsky/login',
        json={
            "USERNAME": "admin",
            "PASSWORD": "AdminPassword123!",
            "NEXT": "",
        },
    )
    assert login_res.status_code == 200

    # Access config page
    response = client.get('/indi-allsky/config')
    assert response.status_code == 200
