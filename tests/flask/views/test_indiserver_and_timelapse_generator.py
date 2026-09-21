import io
import os
import shutil
from pathlib import Path
from datetime import datetime, date
from unittest.mock import patch, MagicMock
import pytest
import dbus

from indi_allsky.flask import db
from indi_allsky.flask.models import IndiAllSkyDbCameraTable, IndiAllSkyDbTaskQueueTable
from indi_allsky.flask.views import (
    AjaxIndiServerChangeView,
    AjaxTimelapseGeneratorView,
)


def test_ajax_indiserver_change_validation_failure(flask_app, system_db):
    client = flask_app.test_client()
    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        # Send invalid choices
        res = client.post(
            "/indi-allsky/ajax/indiserver",
            json={
                "CAMERA_SERVER_SELECT": "nonexistent_driver",
                "GPS_SERVER_SELECT": "nonexistent_gps",
                "RESTART_INDISERVER": False,
            },
        )
        assert res.status_code == 400


def test_ajax_indiserver_change_paths_and_execution(flask_app, system_db, tmp_path):
    client = flask_app.test_client()

    fake_home = tmp_path / "home"
    systemd_user_dir = fake_home / ".config" / "systemd" / "user"
    systemd_user_dir.mkdir(parents=True, exist_ok=True)

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True, "INDISERVER_SERVICE_NAME": "indiserver.service"}):
        with patch.dict(os.environ, {"HOME": str(fake_home)}):
            with patch("os.getlogin", return_value="testuser"):
                # 1. Test indiserver not found exception
                with patch("shutil.which", return_value=None):
                    with patch("pathlib.Path.exists", lambda self: False):
                        with pytest.raises(Exception, match="indiserver not found"):
                            with flask_app.test_request_context(
                                "/indi-allsky/ajax/indiserver",
                                json={
                                    "CAMERA_SERVER_SELECT": "",
                                    "GPS_SERVER_SELECT": "",
                                    "RESTART_INDISERVER": True,
                                },
                            ):
                                v = AjaxIndiServerChangeView()
                                v.dispatch_request()

                # 2. Test successful indiserver change with restart
                with patch("shutil.which", return_value="/usr/bin/indiserver"):
                    with patch("pathlib.Path.exists", lambda self: True if "service" in str(self) or str(self) == "/usr/bin/indiserver" else False):
                        with patch.object(AjaxIndiServerChangeView, "reloadSystemdUnits") as mock_reload:
                            with patch.object(AjaxIndiServerChangeView, "restartSystemdUnit") as mock_restart:
                                res = client.post(
                                    "/indi-allsky/ajax/indiserver",
                                    json={
                                        "CAMERA_SERVER_SELECT": "",
                                        "GPS_SERVER_SELECT": "",
                                        "RESTART_INDISERVER": True,
                                    },
                                )
                                assert res.status_code == 200
                                assert "Restart complete" in res.get_json()["success-message"]
                                mock_reload.assert_called_once()
                                mock_restart.assert_called_once_with("indiserver.service")


def test_reload_systemd_units_dbus_exceptions(flask_app, system_db):
    with flask_app.test_request_context("/"):
        v = AjaxIndiServerChangeView()

        # 1. DBusException on bus connection (e.g. docker environment)
        with patch.object(v, "_get_systemd_bus", side_effect=dbus.exceptions.DBusException("No bus")):
            res = v.reloadSystemdUnits()
            assert res == ("D-Bus Unavailable", "D-Bus Unavailable")

        # 2. DBusException on Reload call
        mock_bus = MagicMock()
        mock_mgr = MagicMock()
        mock_mgr.Reload.side_effect = dbus.exceptions.DBusException("Reload failed")
        with patch.object(v, "_get_systemd_bus", return_value=mock_bus):
            with patch("dbus.Interface", return_value=mock_mgr):
                res = v.reloadSystemdUnits()
                assert res == ("UNKNOWN", "UNKNOWN")


def test_ajax_timelapse_generator_validation_and_admin_network(flask_app, system_db):
    client = flask_app.test_client()

    t_day = date(2026, 9, 20)
    with flask_app.app_context():
        from indi_allsky.flask.models import IndiAllSkyDbImageTable
        img = IndiAllSkyDbImageTable(
            camera_id=1,
            filename="/tmp/timelapse_test_img.jpg",
            exposure=1.0,
            gain=100.0,
            adu=100.0,
            createDate=datetime(2026, 9, 20, 22, 0, 0),
            dayDate=t_day,
            night=True,
        )
        db.session.add(img)
        db.session.commit()

    mock_admin = MagicMock()
    mock_admin.is_admin = True

    mock_non_admin = MagicMock()
    mock_non_admin.is_admin = False

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        # 0. Permission check failure
        with patch("indi_allsky.flask.views.current_user", mock_non_admin):
            res_perm = client.post(
                "/indi-allsky/ajax/generate",
                json={"CAMERA_ID": 1},
            )
            assert res_perm.status_code == 400
            assert "permission" in res_perm.get_json()["form_global"][0]

        # 1. Validation failure
        with patch("indi_allsky.flask.views.current_user", mock_admin):
            res_invalid = client.post(
                "/indi-allsky/ajax/generate",
                json={"CAMERA_ID": 1, "ACTION_SELECT": "invalid", "DAY_SELECT": "invalid"},
            )
            assert res_invalid.status_code == 400

            # 2. Verify admin network failure
            with patch.object(AjaxTimelapseGeneratorView, "verify_admin_network", return_value=False):
                res_net = client.post(
                    "/indi-allsky/ajax/generate",
                    json={
                        "CAMERA_ID": 1,
                        "ACTION_SELECT": "generate_video",
                        "DAY_SELECT": "2026-09-20_night",
                    },
                )
                assert res_net.status_code == 400
                assert "Request not from admin network" in res_net.get_json()["form_global"][0]
