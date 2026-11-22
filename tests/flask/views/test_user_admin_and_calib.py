import io
import json
import socket
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from passlib.hash import argon2
import pytest
import numpy as np
import cv2
from PIL import Image

from indi_allsky.flask import db
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbConfigTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbTleDataTable,
    IndiAllSkyDbUserTable,
    IndiAllSkyDbTaskQueueTable,
)
from indi_allsky import constants
from indi_allsky.exceptions import ConfigSaveException
from indi_allsky.devices.exceptions import DeviceControlException
from indi_allsky.flask.views import (
    AjaxAstroPanelView,
    ESP32ImageView,
    NetworkManagerView,
    AjaxUserInfoView,
    AjaxConfigRestoreView,
    ManualGpioView,
    AjaxManualGpioView,
    Asi676mcCalibrationView,
    AjaxAsi676mcCalibrationSessionView,
    AjaxAsi676mcCalibrationUploadView,
    AjaxAsi676mcCalibrationDatabaseView,
    AjaxAsi676mcCalibrationCancelView,
    AjaxAsi676mcCalibrationStartView,
    AjaxAsi676mcCalibrationStatusView,
    Asi676mcCalibrationReportView,
    AjaxAsi676mcCalibrationDiscardView,
    AjaxAsi676mcCalibrationApplyView,
)


def test_astro_panel_view(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):
        res = client.get("/indi-allsky/ajax/astropanel?camera_id=1")
        assert res.status_code in (200, 400)


def test_ephem_info_view_with_satellites(flask_app, system_db):
    client = flask_app.test_client()

    with flask_app.app_context():
        # Insert satellite TLE record
        tle = IndiAllSkyDbTleDataTable(
            group=constants.SATELLITE_VISUAL,
            title="ISS (ZARYA)",
            line1="1 25544U 98067A   20336.54791667  .00001448  00000-0  34473-4 0  9990",
            line2="2 25544  51.6443 208.6309 0001542 344.9750 148.5146 15.49168442257211",
        )
        db.session.add(tle)
        db.session.commit()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        res = client.get("/indi-allsky/ajax/astropanel?camera_id=1")
        assert res.status_code == 200
        data = res.get_json()
        assert "satellites" in data or "latitude" in data

    # POST method should return 400
    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        res_post = client.post("/indi-allsky/ajax/astropanel?camera_id=1")
        assert res_post.status_code == 400


def test_network_manager_view(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user), \
         patch("indi_allsky.flask.views.IndiAllskyNetworkManagerForm"), \
         patch("dbus.SystemBus"):
        res = client.get("/indi-allsky/network?camera_id=1")
        assert res.status_code == 200


def test_user_info_view(flask_app, system_db):
    with flask_app.app_context():
        hashed = argon2.hash("oldpassword")
        user = IndiAllSkyDbUserTable(
            username="adminuser",
            name="Admin User",
            email="admin@example.com",
            password=hashed,
            admin=True,
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    with flask_app.app_context():
        user = db.session.get(IndiAllSkyDbUserTable, user_id)
        # 1. Invalid current password
        with flask_app.test_request_context(
            "/indi-allsky/ajax/user",
            method="POST",
            json={"CURRENT_PASSWORD": "wrongpassword", "NAME": "New Name", "NEW_PASSWORD": "", "NEW_PASSWORD2": ""},
        ):
            with patch("indi_allsky.flask.views.current_user", user):
                view = AjaxUserInfoView()
                res = view.dispatch_request()
                status = res[1] if isinstance(res, tuple) else res.status_code
                assert status == 400

        # 2. Valid update without password change
        with flask_app.test_request_context(
            "/indi-allsky/ajax/user",
            method="POST",
            json={"CURRENT_PASSWORD": "oldpassword", "NAME": "Updated Name", "IDP": "local", "NEW_PASSWORD": "", "NEW_PASSWORD2": ""},
        ):
            with patch("indi_allsky.flask.views.current_user", user):
                view = AjaxUserInfoView()
                res = view.dispatch_request()
                status = res[1] if isinstance(res, tuple) else res.status_code
                assert status == 200
                assert user.name == "Updated Name"

        # 3. Valid update with new password
        with flask_app.test_request_context(
            "/indi-allsky/ajax/user",
            method="POST",
            json={"CURRENT_PASSWORD": "oldpassword", "NAME": "Updated Name 2", "IDP": "local", "NEW_PASSWORD": "newsecretpassword", "NEW_PASSWORD2": "newsecretpassword"},
        ):
            with patch("indi_allsky.flask.views.current_user", user):
                view = AjaxUserInfoView()
                res = view.dispatch_request()
                status = res[1] if isinstance(res, tuple) else res.status_code
                assert status == 200
                assert argon2.verify("newsecretpassword", user.password)


def test_config_restore_view(flask_app, system_db, tmp_path):
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True
    mock_user.username = "admin"

    # Create dummy flask.json
    flask_json = tmp_path / "flask.json"
    flask_json.write_text(json.dumps({"SECRET_KEY": "old", "PASSWORD_KEY": "old"}))

    valid_config = {
        "INDI_SERVER": "localhost",
        "CCD_CONFIG": {},
        "INDI_CONFIG_DEFAULTS": {},
    }

    # 1. Non-admin forbidden
    mock_non_admin = MagicMock()
    mock_non_admin.is_admin = False
    with flask_app.test_request_context("/indi-allsky/ajax/config/restore", method="POST"):
        view = AjaxConfigRestoreView()
        with patch("indi_allsky.flask.views.current_user", mock_non_admin):
            res = view.dispatch_request()
            status = res[1] if isinstance(res, tuple) else res.status_code
            assert status == 400

    # 2. Empty file
    with flask_app.test_request_context(
        "/indi-allsky/ajax/config/restore",
        method="POST",
        data={"CONFIG_UPLOAD": (io.BytesIO(b""), "config.json")},
    ):
        view = AjaxConfigRestoreView()
        with patch("indi_allsky.flask.views.current_user", mock_user):
            res = view.dispatch_request()
            status = res[1] if isinstance(res, tuple) else res.status_code
            assert status == 400

    # 3. File too large (>100000 bytes)
    with flask_app.test_request_context(
        "/indi-allsky/ajax/config/restore",
        method="POST",
        data={"CONFIG_UPLOAD": (io.BytesIO(b"x" * 100001), "config.json")},
    ):
        view = AjaxConfigRestoreView()
        with patch("indi_allsky.flask.views.current_user", mock_user):
            res = view.dispatch_request()
            status = res[1] if isinstance(res, tuple) else res.status_code
            assert status == 400

    # 4. Invalid JSON
    with flask_app.test_request_context(
        "/indi-allsky/ajax/config/restore",
        method="POST",
        data={"CONFIG_UPLOAD": (io.BytesIO(b"not json"), "config.json")},
    ):
        view = AjaxConfigRestoreView()
        with patch("indi_allsky.flask.views.current_user", mock_user):
            res = view.dispatch_request()
            status = res[1] if isinstance(res, tuple) else res.status_code
            assert status == 400

    # 5. Invalid schema (missing CCD_CONFIG)
    with flask_app.test_request_context(
        "/indi-allsky/ajax/config/restore",
        method="POST",
        data={"CONFIG_UPLOAD": (io.BytesIO(b'{"INDI_SERVER": "localhost"}'), "config.json")},
    ):
        view = AjaxConfigRestoreView()
        with patch("indi_allsky.flask.views.current_user", mock_user):
            res = view.dispatch_request()
            status = res[1] if isinstance(res, tuple) else res.status_code
            assert status == 400

    # 6. ConfigSaveException
    with flask_app.test_request_context(
        "/indi-allsky/ajax/config/restore",
        method="POST",
        data={"CONFIG_UPLOAD": (io.BytesIO(json.dumps(valid_config).encode()), "config.json")},
    ):
        view = AjaxConfigRestoreView()
        with patch("indi_allsky.flask.views.current_user", mock_user), \
             patch.object(view._indi_allsky_config_obj, "save", side_effect=ConfigSaveException("Save error")):
            res = view.dispatch_request()
            status = res[1] if isinstance(res, tuple) else res.status_code
            assert status == 400

    # 7. Success with flush_configs and reset_keys
    orig_io_open = io.open

    def mock_io_open(file, *args, **kwargs):
        if str(file) == "/etc/indi-allsky/flask.json":
            return orig_io_open(str(flask_json), *args, **kwargs)
        return orig_io_open(file, *args, **kwargs)

    with flask_app.test_request_context(
        "/indi-allsky/ajax/config/restore",
        method="POST",
        data={
            "CONFIG_UPLOAD": (io.BytesIO(json.dumps(valid_config).encode()), "config.json"),
            "FLUSH_CONFIGS": "1",
            "RESET_KEYS": "1",
        },
    ):
        view = AjaxConfigRestoreView()
        with patch("indi_allsky.flask.views.current_user", mock_user), \
             patch.object(view._indi_allsky_config_obj, "save"), \
             patch("io.open", side_effect=mock_io_open), \
             patch("shutil.copy2"), \
             patch("pathlib.Path.chmod"):
            res = view.dispatch_request()
            status = res[1] if isinstance(res, tuple) else res.status_code
            assert status == 200


def test_esp32_image_view_formats(flask_app, system_db, tmp_path):
    with flask_app.test_request_context("/indi-allsky/allsky_esp32"):
        view = ESP32ImageView()

        # Create dummy images
        img_array = np.zeros((100, 100, 3), dtype=np.uint8)
        jpg_path = tmp_path / "test.jpg"
        png_path = tmp_path / "test.png"
        cv2.imwrite(str(jpg_path), img_array)
        cv2.imwrite(str(png_path), img_array)

        pil_img = Image.new("RGB", (100, 100), color="red")
        bmp_path = tmp_path / "test.bmp"
        pil_img.save(str(bmp_path))

        # 1. _readImage JPG
        assert view._readImage(jpg_path) is not None

        # 2. _readImage PNG
        assert view._readImage(png_path) is not None

        # 3. _readImage PIL fallback
        assert view._readImage(bmp_path) is not None

        # 4. _readImage FITS
        fits_path = tmp_path / "test.fits"
        from astropy.io import fits
        hdu = fits.PrimaryHDU(np.zeros((3, 100, 100), dtype=np.uint8))
        hdu.writeto(str(fits_path))
        assert view._readImage(fits_path) is not None


def test_manual_gpio_views(flask_app, system_db):
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    # 1. ManualGpioView without configured GPIO
    with flask_app.test_request_context("/indi-allsky/manual_gpio?camera_id=1"):
        view = ManualGpioView(template_name="manual_gpio.html")
        with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
             patch.object(view, "indi_allsky_config", {"NIGHT_SUN_ALT_DEG": -6.0}):
            ctx = view.get_context()
            assert ctx["gpio_class"] == ""

    # 2. ManualGpioView with configured mock GPIO
    mock_gpio_cls = MagicMock()
    mock_pin_inst = MagicMock()
    mock_pin_inst.state = 1
    mock_gpio_cls.return_value = mock_pin_inst

    with flask_app.test_request_context("/indi-allsky/manual_gpio?camera_id=1"):
        view = ManualGpioView(template_name="manual_gpio.html")
        with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
             patch.object(view, "indi_allsky_config", {
                 "NIGHT_SUN_ALT_DEG": -6.0,
                 "MANUAL_GPIO": {
                     "A_CLASSNAME": "MockGPIO",
                     "A_PIN_1": "17",
                     "A_PIN_2": "27",
                     "A_PIN_3": "22",
                 }
             }), \
             patch("indi_allsky.devices.generic.MockGPIO", mock_gpio_cls, create=True):
            ctx = view.get_context()
            assert ctx["gpio_class"] == "MockGPIO"

    # 3. AjaxManualGpioView success
    with flask_app.test_request_context(
        "/indi-allsky/ajax/manual_gpio",
        method="POST",
        json={"PIN_ID": 1, "NEW_PIN_STATE": 1},
    ):
        ajax_view = AjaxManualGpioView()
        with patch.dict(flask_app.config, {"LOGIN_DISABLED": False}), \
             patch("indi_allsky.flask.views.current_user", mock_user), \
             patch.object(ajax_view, "indi_allsky_config", {
                 "MANUAL_GPIO": {
                     "A_CLASSNAME": "MockGPIO",
                     "A_PIN_1": "17",
                 }
             }), \
             patch("indi_allsky.devices.generic.MockGPIO", mock_gpio_cls, create=True), \
             patch("time.sleep"):
            res = ajax_view.dispatch_request()
            assert res.status_code == 200


def test_asi676mc_calibration_all_views(flask_app, system_db, tmp_path):
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True
    mock_user.username = "admin"

    camera = db.session.get(IndiAllSkyDbCameraTable, 1)

    # 1. Asi676mcCalibrationView get_context
    with flask_app.test_request_context("/indi-allsky/asi676mc/calibration?camera_id=1"):
        view_calib = Asi676mcCalibrationView(template_name="asi676mc_calibration.html")
        with patch("indi_allsky.flask.views.current_user", mock_user), \
             patch("indi_allsky.flask.views._asi676mc_feature_enabled", return_value=True), \
             patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[camera]), \
             patch("indi_allsky.asi676mc.camera_record_identity_name", return_value="ASI676MC"), \
             patch("indi_allsky.asi676mc_calibration.capture_configuration_guidance", return_value={}):
            ctx = view_calib.get_context()
            assert "form_calibration" in ctx

    # 2. AjaxAsi676mcCalibrationSessionView
    # Missing camera
    with flask_app.test_request_context("/indi-allsky/ajax/asi676mc/calibration/session", method="POST", json={"camera_id": 999}):
        view_sess = AjaxAsi676mcCalibrationSessionView()
        with patch("indi_allsky.flask.views.current_user", mock_user), \
             patch("indi_allsky.flask.views._asi676mc_feature_enabled", return_value=True), \
             patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[camera]), \
             patch("indi_allsky.flask.views._supported_asi676mc_camera", return_value=None):
            res = view_sess.dispatch_request()
            status = res[1] if isinstance(res, tuple) else res.status_code
            assert status == 400

    # Success session create
    with flask_app.test_request_context("/indi-allsky/ajax/asi676mc/calibration/session", method="POST", json={"camera_id": 1}):
        view_sess = AjaxAsi676mcCalibrationSessionView()
        with patch("indi_allsky.flask.views.current_user", mock_user), \
             patch("indi_allsky.flask.views._asi676mc_feature_enabled", return_value=True), \
             patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[camera]), \
             patch("indi_allsky.flask.views._supported_asi676mc_camera", return_value=camera), \
             patch("indi_allsky.asi676mc_calibration.create_session", return_value={"session_id": "sess-123"}):
            res = view_sess.dispatch_request()
            status = res[1] if isinstance(res, tuple) else res.status_code
            assert status == 200
            data = res.get_json() if hasattr(res, "get_json") else res[0].get_json()
            assert data["session_id"] == "sess-123"

    # 3. AjaxAsi676mcCalibrationUploadView
    with flask_app.test_request_context(
        "/indi-allsky/ajax/asi676mc/calibration/sess-123/upload",
        method="POST",
        data={"file": (io.BytesIO(b"fits data"), "frame.fits")},
    ):
        view_upload = AjaxAsi676mcCalibrationUploadView()
        with patch("indi_allsky.flask.views.current_user", mock_user), \
             patch("indi_allsky.flask.views._asi676mc_feature_enabled", return_value=True), \
             patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[camera]), \
             patch("indi_allsky.asi676mc_calibration.store_upload", return_value=({"name": "frame.fits"}, {"files": [1], "total_bytes": 100})):
            res = view_upload.dispatch_request("sess-123")
            status = res[1] if isinstance(res, tuple) else res.status_code
            assert status == 200
            data = res.get_json() if hasattr(res, "get_json") else res[0].get_json()
            assert data["file_count"] == 1

    # 4. AjaxAsi676mcCalibrationDatabaseView
    with flask_app.test_request_context(
        "/indi-allsky/ajax/asi676mc/calibration/database",
        method="POST",
        json={"session_id": "sess-123", "camera_id": 1, "target_groups": 10, "max_pair_seconds": 60.0},
    ):
        view_db_c = AjaxAsi676mcCalibrationDatabaseView()
        with patch("indi_allsky.flask.views.current_user", mock_user), \
             patch("indi_allsky.flask.views._asi676mc_feature_enabled", return_value=True), \
             patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[camera]), \
             patch("indi_allsky.flask.views._supported_asi676mc_camera", return_value=camera), \
             patch("indi_allsky.asi676mc_calibration.database_search_checkpoint", return_value={"camera": {"id": 1, "uuid": str(camera.uuid)}}), \
             patch("indi_allsky.asi676mc_calibration.mark_queued", return_value={"status": "queued"}):
            res = view_db_c.dispatch_request()
            status = res[1] if isinstance(res, tuple) else res.status_code
            assert status == 200
            data = res.get_json() if hasattr(res, "get_json") else res[0].get_json()
            assert data["status"] == "queued"

    # 5. AjaxAsi676mcCalibrationCancelView
    with flask_app.test_request_context("/indi-allsky/ajax/asi676mc/calibration/sess-123/cancel", method="POST"):
        view_cancel = AjaxAsi676mcCalibrationCancelView()
        with patch("indi_allsky.flask.views.current_user", mock_user), \
             patch("indi_allsky.flask.views._asi676mc_feature_enabled", return_value=True), \
             patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[camera]), \
             patch("indi_allsky.asi676mc_calibration.cancel_session", return_value={"status": "cancelled"}):
            res = view_cancel.dispatch_request("sess-123")
            status = res[1] if isinstance(res, tuple) else res.status_code
            assert status == 200
            data = res.get_json() if hasattr(res, "get_json") else res[0].get_json()
            assert data["status"] == "cancelled"

    # 6. AjaxAsi676mcCalibrationStartView
    with flask_app.test_request_context(
        "/indi-allsky/ajax/asi676mc/calibration/sess-123/start",
        method="POST",
        json={"max_pair_seconds": 60.0},
    ):
        view_start = AjaxAsi676mcCalibrationStartView()
        with patch("indi_allsky.flask.views.current_user", mock_user), \
             patch("indi_allsky.flask.views._asi676mc_feature_enabled", return_value=True), \
             patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[camera]), \
             patch("indi_allsky.flask.views._supported_asi676mc_camera", return_value=camera), \
             patch("indi_allsky.asi676mc_calibration.get_session", return_value=(tmp_path, {"camera": {"id": 1, "uuid": str(camera.uuid)}})), \
             patch("indi_allsky.asi676mc_calibration.mark_queued", return_value={"status": "queued"}):
            res = view_start.dispatch_request("sess-123")
            status = res[1] if isinstance(res, tuple) else res.status_code
            assert status == 200

    # 7. AjaxAsi676mcCalibrationStatusView
    with flask_app.test_request_context("/indi-allsky/ajax/asi676mc/calibration/sess-123/status"):
        view_status = AjaxAsi676mcCalibrationStatusView()
        with patch("indi_allsky.flask.views.current_user", mock_user), \
             patch("indi_allsky.flask.views._asi676mc_feature_enabled", return_value=True), \
             patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[camera]), \
             patch("indi_allsky.asi676mc_calibration.get_status", return_value={
                 "status": "success",
                 "result": {"outcome": "calibration"},
             }), \
             patch("indi_allsky.asi676mc_calibration.compare_result_to_configuration", return_value={}):
            res = view_status.dispatch_request("sess-123")
            status = res[1] if isinstance(res, tuple) else res.status_code
            assert status == 200
            data = res.get_json() if hasattr(res, "get_json") else res[0].get_json()
            assert "configuration_comparison" in data

    # 8. Asi676mcCalibrationReportView
    report_file = tmp_path / "report.txt"
    report_file.write_text("Calibration report details")
    with flask_app.test_request_context("/indi-allsky/asi676mc/calibration/sess-123/report"):
        view_report = Asi676mcCalibrationReportView()
        with patch("indi_allsky.flask.views.current_user", mock_user), \
             patch("indi_allsky.flask.views._asi676mc_feature_enabled", return_value=True), \
             patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[camera]), \
             patch("indi_allsky.asi676mc_calibration.get_report_download", return_value=(str(report_file), "report.txt")):
            res = view_report.dispatch_request("sess-123")
            status = res[1] if isinstance(res, tuple) else res.status_code
            assert status == 200

    # 9. AjaxAsi676mcCalibrationDiscardView
    with flask_app.test_request_context("/indi-allsky/ajax/asi676mc/calibration/sess-123/discard", method="POST"):
        view_discard = AjaxAsi676mcCalibrationDiscardView()
        with patch("indi_allsky.flask.views.current_user", mock_user), \
             patch("indi_allsky.flask.views._asi676mc_feature_enabled", return_value=True), \
             patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[camera]), \
             patch("indi_allsky.asi676mc_calibration.discard_session"):
            res = view_discard.dispatch_request("sess-123")
            status = res[1] if isinstance(res, tuple) else res.status_code
            assert status == 200
            data = res.get_json() if hasattr(res, "get_json") else res[0].get_json()
            assert data["status"] == "discarded"

    # 10. AjaxAsi676mcCalibrationApplyView
    with flask_app.test_request_context(
        "/indi-allsky/ajax/asi676mc/calibration/sess-123/apply",
        method="POST",
        json={},
    ):
        view_apply = AjaxAsi676mcCalibrationApplyView()
        with patch("indi_allsky.flask.views.current_user", mock_user), \
             patch("indi_allsky.flask.views._asi676mc_feature_enabled", return_value=True), \
             patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[camera]), \
             patch("indi_allsky.flask.views._supported_asi676mc_camera", return_value=camera), \
             patch("indi_allsky.asi676mc_calibration.get_completed_result", return_value=(
                 {"camera": {"id": 1, "uuid": str(camera.uuid)}, "config_id": view_apply.indi_allsky_config_id},
                 {"outcome": "calibration", "quality": {"matched_bad_count": 5, "matched_normal_count": 5}},
                 {"ENABLE": True},
             )), \
             patch.object(view_apply._indi_allsky_config_obj, "save"), \
             patch.object(view_apply._miscDb, "setState"):
            res = view_apply.dispatch_request("sess-123")
            status = res[1] if isinstance(res, tuple) else res.status_code
            assert status == 200
            data = res.get_json() if hasattr(res, "get_json") else res[0].get_json()
            assert data["reload_queued"] is True
