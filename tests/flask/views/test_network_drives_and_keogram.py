from datetime import datetime, timedelta
import io
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import dbus
import pytest

from indi_allsky.flask import db
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbImageTable,
)
from indi_allsky.flask.views import (
    LongTermKeogramView,
    JsonLongTermKeogramView,
    AjaxNetworkManagerView,
    DriveManagerView,
    AjaxDriveManagerView,
    ImageCircleHelperView,
)


def test_longterm_keogram_view_context_cached_image(flask_app, system_db, tmp_path):
    # Set up cached longterm keogram file
    cam_folder = tmp_path / "ccd_test-uuid"
    cam_folder.mkdir(parents=True, exist_ok=True)
    keogram_file = cam_folder / "longterm_keogram.jpg"
    keogram_file.write_bytes(b"KEOGRAM_IMAGE_DATA")

    with flask_app.app_context():
        cam = db.session.get(IndiAllSkyDbCameraTable, 1)
        cam.uuid = "test-uuid"
        db.session.commit()

    with patch.dict(flask_app.config, {"INDI_ALLSKY_IMAGE_FOLDER": str(tmp_path), "LOGIN_DISABLED": True}), \
         flask_app.test_request_context("/indi-allsky/longtermkeogram?camera_id=1"):
        view = LongTermKeogramView(template_name="longterm_keogram.html")
        ctx = view.get_context()
        assert "Generated" in ctx["keogram_age"]
        assert "longterm_keogram.jpg" in ctx["keogram_uri"]


def test_json_longterm_keogram_view_branches(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):

        # 1. offset_seconds > 43200 sanity check (via mock validate)
        mock_form = MagicMock()
        mock_form.validate.return_value = True
        with patch("indi_allsky.flask.views.IndiAllskyLongTermKeogramForm", return_value=mock_form):
            res_offset = client.post(
                "/indi-allsky/js/longtermkeogram",
                json={
                    "CAMERA_ID": 1,
                    "END_SELECT": "today",
                    "DAYS_SELECT": 30,
                    "PIXELS_SELECT": 1,
                    "ALIGNMENT_SELECT": 60,
                    "OFFSET_SELECT": 50000,
                    "REVERSE": False,
                    "LABEL": False,
                }
            )
            assert res_offset.status_code == 400

            # 2. query_days > 2000 sanity check
            res_days = client.post(
                "/indi-allsky/js/longtermkeogram",
                json={
                    "CAMERA_ID": 1,
                    "END_SELECT": "today",
                    "DAYS_SELECT": 3000,
                    "PIXELS_SELECT": 1,
                    "ALIGNMENT_SELECT": 60,
                    "OFFSET_SELECT": 0,
                    "REVERSE": False,
                    "LABEL": False,
                }
            )
            assert res_days.status_code == 400

            # 3. alignment_seconds < 5 sanity check
            res_align = client.post(
                "/indi-allsky/js/longtermkeogram",
                json={
                    "CAMERA_ID": 1,
                    "END_SELECT": "today",
                    "DAYS_SELECT": 30,
                    "PIXELS_SELECT": 1,
                    "ALIGNMENT_SELECT": 2,
                    "OFFSET_SELECT": 0,
                    "REVERSE": False,
                    "LABEL": False,
                }
            )
            assert res_align.status_code == 400

            # 4. end == 'thisyear' and 'lastyear'
            import numpy as np
            fake_img = np.zeros((100, 100, 3), dtype=np.uint8)
            with patch("indi_allsky.longTermKeogram.LongTermKeogramGenerator.generate", return_value=fake_img), \
                 patch("io.open", side_effect=PermissionError("disk write error")):
                res_thisyear = client.post(
                    "/indi-allsky/js/longtermkeogram",
                    json={
                        "CAMERA_ID": 1,
                        "END_SELECT": "thisyear",
                        "DAYS_SELECT": 30,
                        "PIXELS_SELECT": 1,
                        "ALIGNMENT_SELECT": 60,
                        "OFFSET_SELECT": 0,
                        "REVERSE": False,
                        "LABEL": False,
                    }
                )
                assert res_thisyear.status_code == 200
                assert "disk write error" in res_thisyear.json["failure-message"]

                res_lastyear = client.post(
                    "/indi-allsky/js/longtermkeogram",
                    json={
                        "CAMERA_ID": 1,
                        "END_SELECT": "lastyear",
                        "DAYS_SELECT": 30,
                        "PIXELS_SELECT": 1,
                        "ALIGNMENT_SELECT": 60,
                        "OFFSET_SELECT": 0,
                        "REVERSE": False,
                        "LABEL": False,
                    }
                )
                assert res_lastyear.status_code == 200


def test_ajax_network_manager_error_branches(flask_app, system_db):
    client = flask_app.test_client()

    mock_admin = MagicMock()
    mock_admin.is_authenticated = True
    mock_admin.is_admin = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_admin), \
         patch("time.sleep"):

        # 1. Unknown command
        res_unk = client.post("/indi-allsky/ajax/network", json={"COMMAND": "invalid_cmd"})
        assert res_unk.status_code == 400

        # 2. scanap without interface
        res_no_if = client.post("/indi-allsky/ajax/network", json={"COMMAND": "scanap", "INTERFACE": ""})
        assert res_no_if.status_code == 400

        # 3. connectap without ap_path
        res_no_ap = client.post(
            "/indi-allsky/ajax/network",
            json={
                "COMMAND": "connectap",
                "INTERFACE": "wlan0",
                "AP_PATH": "",
                "PSK": "secretpass",
                "PRIORITY": 0,
                "RETRIES": 3,
            }
        )
        assert res_no_ap.status_code == 400

        # 4. createhotspot validation errors
        res_hs_no_if = client.post(
            "/indi-allsky/ajax/network",
            json={"COMMAND": "createhotspot", "INTERFACE": "", "SSID": "hotspot", "BAND": "bg", "PSK": "12345678", "NOSECURITY": False}
        )
        assert res_hs_no_if.status_code == 400

        # 5. DBus exception on activateConnection
        mock_bus = MagicMock()
        mock_bus.get_object.side_effect = dbus.exceptions.DBusException("DBus down")
        with patch("dbus.SystemBus", return_value=mock_bus):
            res_act = client.post("/indi-allsky/ajax/network", json={"COMMAND": "activate", "CONNECTION": "uuid-123"})
            assert res_act.status_code == 400

            res_deact = client.post("/indi-allsky/ajax/network", json={"COMMAND": "deactivate", "CONNECTION": "uuid-123"})
            assert res_deact.status_code == 400

            res_scan = client.post("/indi-allsky/ajax/network", json={"COMMAND": "scanap", "INTERFACE": "wlan0"})
            assert res_scan.status_code == 400


def test_drive_manager_and_image_circle_branches(flask_app, system_db):
    client = flask_app.test_client()

    mock_admin = MagicMock()
    mock_admin.is_authenticated = True
    mock_admin.is_admin = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_admin):

        # 1. DriveManagerView with DBus down
        with patch("dbus.SystemBus", side_effect=dbus.exceptions.DBusException("No udisks")):
            with flask_app.test_request_context("/indi-allsky/drives?camera_id=1"):
                v_drive = DriveManagerView(template_name="drive_manager.html")
                ctx = v_drive.get_context()
                assert ctx["udisks2_installed"] is False

        # 2. AjaxDriveManagerView powerOffDrive, unmountDevice, mountDevice with drive not found
        mock_bus = MagicMock()
        mock_iface = MagicMock()
        mock_iface.GetManagedObjects.return_value = {}
        mock_bus.get_object.return_value = MagicMock()
        with patch("dbus.SystemBus", return_value=mock_bus), \
             patch("dbus.Interface", return_value=mock_iface):
            with flask_app.test_request_context("/indi-allsky/ajax/drives"):
                v_ajax_drive = AjaxDriveManagerView()
                res_power = v_ajax_drive.powerOffDrive("drive-1")
                assert res_power[1] == 400

                res_unmount = v_ajax_drive.unmountDevice("block-1")
                assert res_unmount[1] == 400

                res_mount = v_ajax_drive.mountDevice("block-1")
                assert res_mount[1] == 400

        # 3. ImageCircleHelperView with web_nonlocal_images
        with flask_app.app_context():
            cam = db.session.get(IndiAllSkyDbCameraTable, 1)
            cam.web_nonlocal_images = True
            cam.web_local_images_admin = False
            db.session.commit()

        with flask_app.test_request_context("/indi-allsky/imagecirclehelper?camera_id=1"):
            v_circle = ImageCircleHelperView(template_name="imagecirclehelper.html")
            ctx_circle = v_circle.get_context()
            assert "form_imagecircle" in ctx_circle

