from unittest.mock import patch, MagicMock
from pathlib import Path
import pytest
from datetime import datetime, timedelta
import io
import gzip

from indi_allsky.flask import db
from indi_allsky.flask.models import (
    IndiAllSkyDbNotificationTable,
    NotificationCategory,
    IndiAllSkyDbUserTable,
)
from indi_allsky.flask.views import (
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
    NotificationsView,
    AjaxNotificationView,
    UserInfoView,
)


def test_log_views(flask_app, system_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        res = client.get("/indi-allsky/log")
        assert res.status_code == 200

        res_indi = client.get("/indi-allsky/log/indiserver")
        assert res_indi.status_code == 200


def test_log_file_downloads(flask_app, system_db, tmp_path):
    client = flask_app.test_client()

    # Create dummy log file
    dummy_log = tmp_path / "dummy.log"
    dummy_log.write_bytes(b"Line 1\nLine 2\nLine 3\n")

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        # Non-existent file case
        with patch("pathlib.Path.exists", return_value=False):
            res = client.get("/indi-allsky/log/download")
            assert res.status_code == 200
            assert b"Log file does not exist" in res.data

        # Exists case
        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.stat") as mock_stat, \
             patch("io.open", return_value=io.BytesIO(b"Log data content")):
            mock_stat.return_value.st_size = 100
            res = client.get("/indi-allsky/log/download?lines=10")
            assert res.status_code == 200

        # Webapp log download
        with patch("pathlib.Path.exists", return_value=False):
            res = client.get("/indi-allsky/log/webapp_download")
            assert res.status_code == 200

        # Syslog download
        with patch("pathlib.Path.exists", return_value=False):
            res = client.get("/indi-allsky/log/syslog_download")
            assert res.status_code == 200

        # Kern log download
        with patch("pathlib.Path.exists", return_value=False):
            res = client.get("/indi-allsky/log/kern_download")
            assert res.status_code == 200


def test_journal_log_downloads(flask_app, system_db):
    client = flask_app.test_client()

    mock_reader = MagicMock()
    mock_reader.return_value.__iter__.return_value = [
        {"MESSAGE": "Log entry 1"},
        {"MESSAGE": "Log entry 2"},
    ]

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("systemd.journal.Reader", mock_reader, create=True):
        res = client.get("/indi-allsky/log/indiserver_download")
        assert res.status_code == 200

        res_upg = client.get("/indi-allsky/log/upgrade_download")
        assert res_upg.status_code == 200


def test_support_info_views(flask_app, system_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        res = client.get("/indi-allsky/support")
        assert res.status_code == 200

        # Ajax support info view success
        with patch("subprocess.run") as mock_subproc:
            mock_subproc.return_value.stdout = b"Support diagnostic data"
            res_ajax = client.get("/indi-allsky/js/support")
            assert res_ajax.status_code == 200
            data = res_ajax.get_json()
            assert "Support diagnostic data" in data["support_info"]


def test_notifications_views(flask_app, system_db):
    client = flask_app.test_client()

    with flask_app.app_context():
        notice = IndiAllSkyDbNotificationTable(
            category=NotificationCategory.GENERAL,
            item="test",
            notification="System update available",
            expireDate=datetime.now() + timedelta(days=7),
        )
        db.session.add(notice)
        db.session.commit()
        notice_id = notice.id

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):
        res = client.get("/indi-allsky/notifications")
        assert res.status_code == 200

        # Ajax notification get
        res_get = client.get(f"/indi-allsky/ajax/notification?camera_id=1")
        assert res_get.status_code == 200
        data = res_get.get_json()
        assert data["id"] == notice_id

        # Ajax notification post (acknowledge)
        res_post = client.post("/indi-allsky/ajax/notification", json={"camera_id": 1, "ack_id": notice_id})
        assert res_post.status_code == 200


def test_user_info_view(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.username = "testadmin"
    mock_user.name = "Test Admin"
    mock_user.email = "admin@test.com"
    mock_user.admin = True
    mock_user.data = {"idp": "local"}

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):
        res = client.get("/indi-allsky/user")
        assert res.status_code == 200
