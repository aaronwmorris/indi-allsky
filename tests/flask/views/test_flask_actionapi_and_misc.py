from unittest.mock import patch
from passlib.hash import argon2
import pytest

from indi_allsky.flask.misc import login_optional, login_optional_media
from indi_allsky.flask.models import (
    IndiAllSkyDbUserTable,
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbConfigTable,
    IndiAllSkyDbTaskQueueTable,
    TaskQueueQueue,
    TaskQueueState,
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
    orig_login_disabled = flask_app.config.get('LOGIN_DISABLED', False)
    try:
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
    finally:
        flask_app.config['LOGIN_DISABLED'] = orig_login_disabled


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
        # 1. Test pause action (creates task queue entry and returns 201)
        res_pause = client.post(
            '/indi-allsky/action/pause',
            json={'username': 'admin', 'password': 'testpass'},
        )
        assert res_pause.status_code == 201
        data_pause = res_pause.get_json()
        assert 'message' in data_pause

        # Verify task was written to DB
        with flask_app.app_context():
            task = IndiAllSkyDbTaskQueueTable.query.filter_by(
                queue=TaskQueueQueue.MAIN,
                state=TaskQueueState.MANUAL,
            ).first()
            assert task is not None
            assert task.data.get('action') == 'setpaused'
            assert task.data.get('pause') is True

        # 2. Test unpause when already unpaused (CAPTURE_PAUSE is False) -> 200
        res_unpause_already = client.post(
            '/indi-allsky/action/unpause',
            json={'username': 'admin', 'password': 'testpass'},
        )
        assert res_unpause_already.status_code == 200
        assert 'already unpaused' in res_unpause_already.get_json().get('message', '').lower()

        # 3. Test auth failure with bad password -> 400
        res_bad = client.post(
            '/indi-allsky/action/pause',
            json={'username': 'admin', 'password': 'wrongpassword'},
        )
        assert res_bad.status_code == 400
