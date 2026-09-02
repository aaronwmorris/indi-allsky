import pytest
from passlib.hash import argon2
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbUserTable,
    IndiAllSkyDbConfigTable,
)


@pytest.fixture(autouse=True)
def setup_camera_and_config(flask_app, db):
    """Ensure a default camera and config entry exist for Flask views."""
    with flask_app.app_context():
        camera = IndiAllSkyDbCameraTable.query.first()
        if not camera:
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
        else:
            if camera.nightSunAlt is None:
                camera.nightSunAlt = -6.0
            if camera.latitude is None:
                camera.latitude = -34.9285
            if camera.longitude is None:
                camera.longitude = 138.6007
            if camera.elevation is None:
                camera.elevation = 50
            db.session.add(camera)

        config_entry = IndiAllSkyDbConfigTable.query.first()
        if not config_entry:
            config_entry = IndiAllSkyDbConfigTable(
                config={'WEBSITE': {'TITLE': 'indi-allsky'}},
            )
            db.session.add(config_entry)

        db.session.commit()


def test_auth_login_get(flask_app):
    client = flask_app.test_client()
    response = client.get('/indi-allsky/login')
    assert response.status_code == 200
    assert b"login" in response.data.lower() or b"username" in response.data.lower()


def test_auth_login_post_invalid_user(flask_app, db):
    client = flask_app.test_client()
    response = client.post(
        '/indi-allsky/login',
        json={
            "USERNAME": "nonexistentuser",
            "PASSWORD": "AnyPassword123!",
            "NEXT": "",
        },
    )
    assert response.status_code == 400
    data = response.get_json()
    assert "USERNAME" in data or "form_global" in data


def test_auth_login_post_success(flask_app, db):
    with flask_app.app_context():
        user = IndiAllSkyDbUserTable.query.filter_by(username="validuser").first()
        if not user:
            user = IndiAllSkyDbUserTable(
                username="validuser",
                password=argon2.hash("ValidPassword123!"),
                email="validuser@example.org",
                name="Valid User",
                active=True,
                admin=True,
            )
            db.session.add(user)
            db.session.commit()

    client = flask_app.test_client()
    response = client.post(
        '/indi-allsky/login',
        json={
            "USERNAME": "validuser",
            "PASSWORD": "ValidPassword123!",
            "NEXT": "",
        },
    )
    assert response.status_code == 200
    data = response.get_json()
    assert "redirect" in data
    assert "/indi-allsky" in data["redirect"]
