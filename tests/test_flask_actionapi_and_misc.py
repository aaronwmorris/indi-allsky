from unittest.mock import patch
from passlib.hash import argon2
import pytest

from indi_allsky.flask.misc import login_optional, login_optional_media
from indi_allsky.flask.models import (
    IndiAllSkyDbUserTable,
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbConfigTable,
)


@pytest.fixture(autouse=True)
def setup_camera_and_config_for_actionapi(flask_app, db):
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

        config_entry = IndiAllSkyDbConfigTable.query.first()
        if not config_entry:
            config_entry = IndiAllSkyDbConfigTable(
                level="20260826.0",
                note="Test config",
                data={
                    'CAPTURE_PAUSE': False,
                    'FLASK': {'ADMIN_NETWORK': ['127.0.0.1/32']},
                }
            )
            db.session.add(config_entry)

        db.session.commit()


def test_login_optional_decorators(flask_app):
    with flask_app.test_request_context():
        # Test with LOGIN_DISABLED
        flask_app.config['LOGIN_DISABLED'] = True

        @login_optional
        def dummy_view():
            return "ok"

        assert dummy_view() == "ok"

        @login_optional_media
        def dummy_media_view():
            return "media_ok"

        assert dummy_media_view() == "media_ok"


def test_actionapi_pause_unpause(flask_app, db):
    with flask_app.app_context():
        password_hash = argon2.using(rounds=4).hash("testpass")
        user = IndiAllSkyDbUserTable.query.filter_by(username="admin").first()
        if not user:
            user = IndiAllSkyDbUserTable(
                username="admin",
                password=password_hash,
                email="admin@example.org",
                admin=True,
                active=True,
            )
            db.session.add(user)
            db.session.commit()
        else:
            user.password = password_hash
            user.admin = True
            db.session.commit()

    client = flask_app.test_client()

    with patch('time.sleep', return_value=None):
        # Test pause action
        res_pause = client.post(
            '/indi-allsky/action/pause',
            json={'username': 'admin', 'password': 'testpass'},
        )
        assert res_pause.status_code in (200, 201)

        # Test unpause action
        res_unpause = client.post(
            '/indi-allsky/action/unpause',
            json={'username': 'admin', 'password': 'testpass'},
        )
        assert res_unpause.status_code in (200, 201)

        # Test auth failure with bad password
        res_bad = client.post(
            '/indi-allsky/action/pause',
            json={'username': 'admin', 'password': 'wrongpassword'},
        )
        assert res_bad.status_code == 400
