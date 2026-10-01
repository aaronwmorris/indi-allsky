import os
import io
import json
import pytest
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

from indi_allsky import constants
from indi_allsky.config import IndiAllSkyConfig
from indi_allsky.flask import db
from indi_allsky.flask.base_views import BaseView
from indi_allsky.flask.views import (
    ManualGpioView,
    AjaxManualGpioView,
    LogView,
    LogIndiserverLogView,
    LogDownloadView,
    LogWebappDownloadView,
    LogSyslogDownloadView,
    LogKernDownloadView,
    LogIndiserverDownloadView,
    LogUpgradeDownloadView,
    SupportInfoView,
    JsonSupportInfoView,
    UserInfoView,
    AjaxUserInfoView,
    UsersView,
    NotificationsView,
    AjaxNotificationView,
    AjaxSelectCameraView,
    CameraLensView,
    AjaxCustomCssView,
)
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbConfigTable,
    IndiAllSkyDbUserTable,
    IndiAllSkyDbNotificationTable,
    NotificationCategory,
)


@pytest.fixture
def system_logs_db(flask_app):
    """Seed database for system logs, GPIO, and user endpoints."""
    with flask_app.app_context():
        for table in (
            IndiAllSkyDbNotificationTable,
            IndiAllSkyDbCameraTable,
            IndiAllSkyDbConfigTable,
            IndiAllSkyDbUserTable,
        ):
            db.session.query(table).delete()
        db.session.commit()

        camera = IndiAllSkyDbCameraTable(
            id=1,
            name="main_camera",
            driver="indi_asi_ccd",
            friendlyName="Camera 1",
            uuid="cam1_uuid",
            lensImageCircle=1000,
            lensFocalLength=50.0,
            lensFocalRatio=2.0,
            width=4000,
            height=3000,
            pixelSize=2.4,
            cfa=constants.CFA_RGGB,
            latitude=-34.0,
            longitude=138.0,
            elevation=0.0,
            nightSunAlt=-6.0,
            owner="Test Owner",
        )
        db.session.add(camera)

        user = IndiAllSkyDbUserTable(
            username="admin",
            email="admin@example.com",
            password="pbkdf2:sha256:1000$hash$salt",
            name="Admin User",
            admin=True,
        )
        db.session.add(user)

        config = IndiAllSkyDbConfigTable(
            id=1,
            level=1,
            note="Initial config",
            data={
                "IMAGE_FOLDER": "/tmp",
                "IMAGE_FILE_TYPE": "jpg",
                "IMAGE_FILE_COMPRESSION": {"jpg": 85},
                "ENCRYPT_PASSWORDS": False,
                "MANUAL_GPIO": {
                    "A_CLASSNAME": "MockGpio",
                    "A_PIN_1": "PIN1",
                    "A_PIN_2": "PIN2",
                    "A_PIN_3": "PIN3",
                },
            },
        )
        db.session.add(config)
        db.session.commit()

        yield camera


def mock_logged_in_user():
    mock_u = MagicMock()
    mock_u.is_authenticated = True
    mock_u.is_admin = True
    mock_u.username = "admin"
    mock_u.name = "Admin User"
    mock_u.email = "admin@example.com"
    mock_u.admin = True
    mock_u.data = {"idp": "local"}
    return mock_u


def test_manual_gpio_views(flask_app, system_logs_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("flask_login.utils._get_user", return_value=mock_logged_in_user()):

        # GET /indi-allsky/manual_gpio
        res = client.get("/indi-allsky/manual_gpio")
        assert res.status_code == 200

        # POST /indi-allsky/ajax/manual_gpio missing MANUAL_GPIO config
        with patch.object(IndiAllSkyConfig, "config", new_callable=PropertyMock, return_value={"ENCRYPT_PASSWORDS": False}):
            res = client.post("/indi-allsky/ajax/manual_gpio", json={"PIN_ID": 1, "NEW_PIN_STATE": 1})
            assert res.status_code == 400

        # POST /indi-allsky/ajax/manual_gpio non-admin
        with patch.dict(flask_app.config, {"LOGIN_DISABLED": False}):
            with patch("flask_login.utils._get_user") as mock_user:
                mock_u = MagicMock()
                mock_u.is_authenticated = True
                mock_u.is_admin = False
                mock_user.return_value = mock_u
                res = client.post("/indi-allsky/ajax/manual_gpio", json={"PIN_ID": 1, "NEW_PIN_STATE": 1})
                assert res.status_code == 400


def test_log_views_and_downloads(flask_app, system_logs_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("flask_login.utils._get_user", return_value=mock_logged_in_user()):

        # Log view pages
        assert client.get("/indi-allsky/log").status_code == 200
        assert client.get("/indi-allsky/log/indiserver").status_code == 200

        # Log file downloads with mock file paths
        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.stat") as mock_stat, \
             patch("io.open", side_effect=lambda *a, **k: io.BytesIO(b"Log line 1\nLog line 2\n")):
            mock_stat.return_value.st_size = 25

            # Download endpoints
            assert client.get("/indi-allsky/log/download").status_code == 200
            assert client.get("/indi-allsky/log/webapp_download").status_code == 200
            assert client.get("/indi-allsky/log/syslog_download").status_code == 200
            assert client.get("/indi-allsky/log/kern_download").status_code == 200

        # Nonexistent log file fallback
        with patch("pathlib.Path.exists", return_value=False):
            res = client.get("/indi-allsky/log/download")
            assert res.status_code == 200
            assert b"Log file does not exist" in res.data


def test_support_info_views(flask_app, system_logs_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("flask_login.utils._get_user", return_value=mock_logged_in_user()):

        # GET /indi-allsky/support
        res = client.get("/indi-allsky/support")
        assert res.status_code == 200

        # GET /indi-allsky/js/support success
        with patch("subprocess.run") as mock_run:
            mock_subproc = MagicMock()
            mock_subproc.stdout = b"System support info output"
            mock_run.return_value = mock_subproc

            res = client.get("/indi-allsky/js/support")
            assert res.status_code == 200
            data = res.get_json()
            assert "support_info" in data

        # GET /indi-allsky/js/support failure
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "cmd", output=b"Error")):
            res = client.get("/indi-allsky/js/support")
            assert res.status_code == 400


def test_notifications_views(flask_app, system_logs_db):
    client = flask_app.test_client()

    with flask_app.app_context():
        notice = IndiAllSkyDbNotificationTable(
            category=NotificationCategory.GENERAL,
            item="test_item",
            notification="Test notification",
            expireDate=datetime.now() + timedelta(days=1),
            ack=False,
        )
        db.session.add(notice)
        db.session.commit()
        notice_id = notice.id

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("flask_login.utils._get_user", return_value=mock_logged_in_user()):

        # GET /indi-allsky/notifications
        res = client.get("/indi-allsky/notifications")
        assert res.status_code == 200

        # GET /indi-allsky/ajax/notification
        res = client.get("/indi-allsky/ajax/notification?camera_id=1")
        assert res.status_code == 200
        data = res.get_json()
        assert data["id"] == notice_id

        # POST /indi-allsky/ajax/notification (acknowledge)
        res = client.post("/indi-allsky/ajax/notification", json={"camera_id": 1, "ack_id": notice_id})
        assert res.status_code == 200


def test_user_and_camera_views(flask_app, system_logs_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("flask_login.utils._get_user", return_value=mock_logged_in_user()):

        # User info GET
        assert client.get("/indi-allsky/user").status_code == 200

        # Users list GET
        assert client.get("/indi-allsky/users").status_code == 200

        # Camera lens GET
        assert client.get("/indi-allsky/camera").status_code == 200

        # Select camera POST
        res = client.post("/indi-allsky/ajax/selectcamera", json={"camera_id": 1})
        assert res.status_code == 200

        # Service worker JS route
        res = client.get("/indi-allsky/sw.js")
        assert res.status_code == 200


def test_custom_css_view(flask_app, system_logs_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("flask_login.utils._get_user", return_value=mock_logged_in_user()):

        with patch("builtins.open", MagicMock()), \
             patch("subprocess.run") as mock_subproc:

            mock_res = MagicMock()
            mock_res.returncode = 0
            mock_subproc.return_value = mock_res

            res = client.post("/indi-allsky/ajax/custom_css", json={"custom_css": "body { color: red; }"})
            assert res.status_code == 200
            data = res.get_json()
            assert data["success"] is True
