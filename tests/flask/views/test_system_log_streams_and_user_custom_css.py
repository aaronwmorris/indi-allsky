import io
import os
import subprocess
import builtins
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
import pytest
from flask import json

from indi_allsky.flask.models import db, IndiAllSkyDbUserTable
from indi_allsky.flask.views import (
    StreamLogView,
    StreamIndiserverLogView,
    StreamLogViewBase,
)


def test_stream_log_view_base_unit_matching_and_generator(flask_app, system_db):
    """Test StreamLogViewBase branches: syslog_facility, user_unit_name, unit_name, and generator loop."""
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    # 1. Test user_unit_name branch and generator yielding logs and keep-alive
    mock_reader = MagicMock()
    mock_reader.process.return_value = 1  # journal.APPEND
    mock_reader.__iter__.return_value = [{"MESSAGE": "Test log entry line 1"}]

    mock_poller = MagicMock()
    mock_poller.poll.side_effect = [[(1, 1)], []]

    mock_journal = MagicMock()
    mock_journal.APPEND = 1
    mock_journal.Reader = MagicMock(return_value=mock_reader)
    mock_systemd = MagicMock()
    mock_systemd.journal = mock_journal

    with patch.dict("sys.modules", {"systemd": mock_systemd, "systemd.journal": mock_journal}):
        with patch("select.poll", return_value=mock_poller):
            view = StreamLogViewBase()
            view.syslog_facility = None
            view.user_unit_name = "indi-allsky-user.service"
            view.unit_name = None

            with flask_app.test_request_context("/indi-allsky/stream/log"):
                with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
                     patch("indi_allsky.flask.views.current_user", mock_user):
                    resp = view.dispatch_request()
                    assert resp.status_code == 200
                    gen = resp.response
                    try:
                        chunk1 = next(gen)
                        assert "Test log entry line 1" in chunk1
                        chunk2 = next(gen)
                        assert ": keep-alive" in chunk2
                    finally:
                        gen.close()
                        resp.close()

                    mock_reader.add_match.assert_called_with(_SYSTEMD_USER_UNIT="indi-allsky-user.service")

    # 2. Test syslog_facility branch
    mock_reader_syslog = MagicMock()
    mock_reader_syslog.process.return_value = 1
    mock_reader_syslog.__iter__.return_value = []
    mock_poller_syslog = MagicMock()
    mock_poller_syslog.poll.return_value = []

    mock_journal_syslog = MagicMock()
    mock_journal_syslog.APPEND = 1
    mock_journal_syslog.Reader = MagicMock(return_value=mock_reader_syslog)
    mock_systemd_syslog = MagicMock()
    mock_systemd_syslog.journal = mock_journal_syslog

    with patch.dict("sys.modules", {"systemd": mock_systemd_syslog, "systemd.journal": mock_journal_syslog}):
        with patch("select.poll", return_value=mock_poller_syslog):
            view_syslog = StreamLogView()
            assert view_syslog.syslog_facility == "22"
            with flask_app.test_request_context("/indi-allsky/stream/log"):
                with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
                     patch("indi_allsky.flask.views.current_user", mock_user):
                    resp = view_syslog.dispatch_request()
                    gen = resp.response
                    try:
                        chunk = next(gen)
                        assert ": keep-alive" in chunk
                    finally:
                        gen.close()
                        resp.close()
                    mock_reader_syslog.add_match.assert_called_with(SYSLOG_FACILITY="22")

    # 3. Test unit_name branch
    mock_reader_unit = MagicMock()
    mock_reader_unit.process.return_value = 1
    mock_reader_unit.__iter__.return_value = []
    mock_poller_unit = MagicMock()
    mock_poller_unit.poll.return_value = []

    mock_journal_unit = MagicMock()
    mock_journal_unit.APPEND = 1
    mock_journal_unit.Reader = MagicMock(return_value=mock_reader_unit)
    mock_systemd_unit = MagicMock()
    mock_systemd_unit.journal = mock_journal_unit

    with patch.dict("sys.modules", {"systemd": mock_systemd_unit, "systemd.journal": mock_journal_unit}):
        with patch("select.poll", return_value=mock_poller_unit):
            view_unit = StreamLogViewBase()
            view_unit.syslog_facility = None
            view_unit.user_unit_name = None
            view_unit.unit_name = "indi-allsky.service"
            with flask_app.test_request_context("/indi-allsky/stream/log"):
                with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
                     patch("indi_allsky.flask.views.current_user", mock_user):
                    resp = view_unit.dispatch_request()
                    gen = resp.response
                    try:
                        chunk = next(gen)
                        assert ": keep-alive" in chunk
                    finally:
                        gen.close()
                        resp.close()
                    mock_reader_unit.add_match.assert_called_with(_SYSTEMD_UNIT="indi-allsky.service")


def test_log_download_views_error_and_seek_branches(flask_app, system_db, tmp_path):
    """Test LogDownloadView, LogWebappDownloadView, LogSyslogDownloadView, LogKernDownloadView."""
    client = flask_app.test_client()

    with flask_app.app_context():
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_admin = True

        with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
             patch("indi_allsky.flask.views.current_user", mock_user):
            endpoints = [
                "/indi-allsky/log/download",
                "/indi-allsky/log/webapp_download",
                "/indi-allsky/log/syslog_download",
                "/indi-allsky/log/kern_download",
            ]

            for ep in endpoints:
                # 1. Non-existent log file
                with patch("pathlib.Path.exists", return_value=False):
                    res = client.get(ep)
                    assert res.status_code == 200
                    assert b"Log file does not exist" in res.data

                # 2. Empty log file (0 bytes)
                with patch("pathlib.Path.exists", return_value=True):
                    mock_stat = MagicMock()
                    mock_stat.st_size = 0
                    with patch("pathlib.Path.stat", return_value=mock_stat):
                        res = client.get(ep)
                        assert res.status_code == 200
                        assert b"Log file is empty" in res.data

                # 3. PermissionError when opening file
                with patch("pathlib.Path.exists", return_value=True):
                    mock_stat = MagicMock()
                    mock_stat.st_size = 5000000
                    with patch("pathlib.Path.stat", return_value=mock_stat):
                        with patch("io.open", side_effect=PermissionError("Permission denied")):
                            res = client.get(ep)
                            assert res.status_code == 200
                            assert b"PermissionError" in res.data

                # 4. Successful download with log_file_size > read_bytes seeking
                fake_log_data = b"X" * 10000
                with patch("pathlib.Path.exists", return_value=True):
                    mock_stat = MagicMock()
                    mock_stat.st_size = 10000
                    with patch("pathlib.Path.stat", return_value=mock_stat):
                        with patch("io.open", mock_open(read_data=fake_log_data)):
                            res = client.get(ep + "?lines=10")
                            assert res.status_code == 200
                            assert res.mimetype == "application/octet-stream"


def test_custom_css_view_and_user_info(flask_app, system_db, tmp_path):
    """Test AjaxCustomCssView build branches and UserInfoView / AjaxUserInfoView."""
    client = flask_app.test_client()

    with flask_app.app_context():
        user = IndiAllSkyDbUserTable.query.filter_by(admin=True).first()
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_admin = True
        mock_user.username = "admin"
        mock_user.name = "Admin"
        mock_user.email = "admin@example.com"
        mock_user.admin = True
        mock_user.data = {}
        mock_user.password = "hashed_pass"

        orig_open = builtins.open

        def selective_open(file, *args, **kwargs):
            if isinstance(file, (str, Path)) and "custom.css" in str(file):
                raise OSError("Custom CSS access error")
            return orig_open(file, *args, **kwargs)

        with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
             patch("indi_allsky.flask.views.current_user", mock_user):
            # 1. Custom CSS write failure (500)
            with patch("builtins.open", side_effect=selective_open):
                res = client.post("/indi-allsky/ajax/custom_css", json={"custom_css": "body { color: red; }"})
                assert res.status_code == 500
                data = json.loads(res.data)
                assert "Failed to save" in data["error"]

            # 2. Custom CSS build failed (400)
            with patch("builtins.open", mock_open()):
                mock_res = MagicMock()
                mock_res.returncode = 1
                mock_res.stderr = "Tailwind CSS syntax error"
                with patch("subprocess.run", return_value=mock_res):
                    res = client.post("/indi-allsky/ajax/custom_css", json={"custom_css": "bad css"})
                    assert res.status_code == 400
                    data = json.loads(res.data)
                    assert "stylesheet build failed" in data["error"]

            # 3. Custom CSS build trigger exception (500)
            with patch("builtins.open", mock_open()):
                with patch("subprocess.run", side_effect=RuntimeError("Subprocess timeout")):
                    res = client.post("/indi-allsky/ajax/custom_css", json={"custom_css": "bad css"})
                    assert res.status_code == 500
                    data = json.loads(res.data)
                    assert "build trigger failed" in data["error"]

            # 4. Custom CSS success (200)
            with patch("builtins.open", mock_open()):
                mock_res = MagicMock()
                mock_res.returncode = 0
                with patch("subprocess.run", return_value=mock_res):
                    res = client.post("/indi-allsky/ajax/custom_css", json={"custom_css": "/* theme */ name: 'mytheme'"})
                    assert res.status_code == 200
                    data = json.loads(res.data)
                    assert data["success"] is True

            # 5. UserInfoView custom.css read exception handling
            with patch("os.path.exists", return_value=True):
                with patch("builtins.open", side_effect=selective_open):
                    res = client.get("/indi-allsky/user")
                    assert res.status_code == 200

            # 6. AjaxUserInfoView invalid current password (400)
            with patch("passlib.hash.argon2.verify", return_value=False):
                res = client.post(
                    "/indi-allsky/ajax/user",
                    json={
                        "USERNAME": user.username if user else "admin",
                        "NAME": "Admin User",
                        "EMAIL": "admin@example.com",
                        "CURRENT_PASSWORD": "wrongpassword",
                        "NEW_PASSWORD": "",
                        "NEW_PASSWORD_CONFIRM": "",
                    },
                )
                assert res.status_code == 400
                data = json.loads(res.data)
                assert "CURRENT_PASSWORD" in data or "form_global" in data
