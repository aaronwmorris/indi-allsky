import os
import cv2
import dbus
import math
import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
import pytest
from flask import json, session
from sqlalchemy.exc import SQLAlchemyError

import indi_allsky.devices.generic as indi_allsky_gpio
from indi_allsky.config import IndiAllSkyConfig
from indi_allsky.exceptions import ConfigSaveException
from indi_allsky.devices.exceptions import DeviceControlException
from indi_allsky.flask.forms import IndiAllskyImageProcessingForm
from indi_allsky.flask.models import (
    db,
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbConfigTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbFitsImageTable,
    IndiAllSkyDbDarkFrameTable,
    IndiAllSkyDbBadPixelMapTable,
    IndiAllSkyDbUserTable,
    IndiAllSkyDbTaskQueueTable,
    TaskQueueQueue,
    TaskQueueState,
)
from indi_allsky.flask.views import (
    JsonLatestImageView,
    ImageViewerView,
    AjaxImageViewerView,
    FitsImageViewerView,
    AjaxFitsImageViewerView,
    GalleryViewerView,
    AjaxGalleryViewerView,
    VideoViewerView,
    AjaxVideoViewerView,
    MiniVideoViewerView,
    AjaxMiniVideoViewerView,
    AjaxAllskyMapRequestKeyView,
    AjaxSetTimeView,
    AjaxSetTimezoneView,
    JsonFocusView,
    ManualGpioView,
    ImageProcessingView,
    JsonImageProcessingView,
    AjaxAsi676mcCalibrationDatabaseView,
    AjaxAsi676mcCalibrationCancelView,
    AjaxAsi676mcCalibrationStartView,
    AjaxAsi676mcCalibrationDiscardView,
    AjaxAsi676mcCalibrationApplyView,
    AjaxSystemInfoView,
)
from indi_allsky.asi676mc_calibration import CalibrationSessionError
from tests.flask.views.test_config_and_controls import config_db


def test_ajax_admin_authorization_restrictions(flask_app, config_db):
    """Test that sensitive admin AJAX endpoints reject non-admin users with HTTP 400 when login is active."""
    client = flask_app.test_client()
    with flask_app.app_context():
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_admin = False  # Non-admin user

        with patch.dict(flask_app.config, {"LOGIN_DISABLED": False}), \
             patch("flask_login.utils._get_user", return_value=mock_user), \
             patch("indi_allsky.flask.views.current_user", mock_user):

            # 1. AjaxAllskyMapRequestKeyView
            res = client.post("/indi-allsky/ajax/allskymap/request_key", json={})
            assert res.status_code == 400
            assert b"permission" in res.data

            # 2. AjaxSetTimeView
            res = client.post("/indi-allsky/ajax/settime", json={"NEW_DATE": "2026-01-01", "NEW_TIME": "12:00:00"})
            assert res.status_code == 400
            assert b"permission" in res.data

            # 3. AjaxSetTimezoneView
            res = client.post("/indi-allsky/ajax/settimezone", json={"NEW_TIMEZONE": "UTC"})
            assert res.status_code == 400
            assert b"permission" in res.data

            # 4. AjaxSystemInfoView commands without admin
            res = client.post("/indi-allsky/ajax/system", json={"CAMERA_ID": 1, "SERVICE_HIDDEN": "indi-allsky", "COMMAND_HIDDEN": "restart"})
            assert res.status_code == 400
            assert b"permission" in res.data


def test_ajax_allskymap_api_key_and_settimezone_branches(flask_app, config_db):
    """Test AjaxAllskyMapRequestKeyView success/failure and AjaxSetTimezoneView validation/dbus errors."""
    client = flask_app.test_client()
    with flask_app.app_context():
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_admin = True

        with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
             patch("indi_allsky.flask.views.current_user", mock_user):

            # 1. AjaxAllskyMapRequestKeyView success
            with patch("indi_allsky.allsky_map.request_allsky_map_api_key", return_value=(True, "valid-key-12345")):
                res = client.post("/indi-allsky/ajax/allskymap/request_key", json={"API_URL": "https://custom-map.com"})
                assert res.status_code == 200
                assert res.json["api_key"] == "valid-key-12345"

            # 2. AjaxAllskyMapRequestKeyView failure with default API URL fallback
            with patch("indi_allsky.allsky_map.request_allsky_map_api_key", return_value=(False, "Connection Timeout")):
                res = client.post("/indi-allsky/ajax/allskymap/request_key", json={})
                assert res.status_code == 400
                assert res.json["error"] == "Connection Timeout"

            # 3. AjaxSetTimezoneView validation error
            res = client.post("/indi-allsky/ajax/settimezone", json={"NEW_TIMEZONE": "Invalid/Zone_Name_12345"})
            assert res.status_code == 400
            assert "form_timezone_global" in res.json

            # 4. AjaxSetTimezoneView DBusException
            with patch.object(AjaxSetTimezoneView, "setTimezoneSystemd", side_effect=dbus.exceptions.DBusException("DBus disconnected")):
                res = client.post("/indi-allsky/ajax/settimezone", json={"NEW_TIMEZONE": "Australia/Adelaide"})
                assert res.status_code == 400
                assert "DBus Error: DBus disconnected" in res.json["form_timezone_global"][0]


def test_nonlocal_images_and_daytime_capture_branches(flask_app, config_db, tmp_path):
    """Test getLatestImage, getLoopImages, ImageViewerView, and FitsImageViewerView with nonlocal images and daytime logic."""
    client = flask_app.test_client()
    with flask_app.app_context():
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_admin = True

        cam = IndiAllSkyDbCameraTable.query.first()
        cam_id = cam.id if cam else 1

        # Create dummy image folder and latest image
        img_folder = tmp_path / "images"
        img_folder.mkdir(parents=True, exist_ok=True)
        latest_file = img_folder / "latest.jpg"
        latest_file.write_bytes(b"dummy image bytes")

        # 1. JsonLatestImageView when daytime capture is disabled and sun_set_date is set / not set
        with flask_app.test_request_context(f"/indi-allsky/js/latest_image?camera_id={cam_id}&night=0"):
            session["camera_id"] = cam_id
            view = JsonLatestImageView()
            view.camera = cam
            view.local_indi_allsky = True
            view.indi_allsky_config = {
                "IMAGE_FOLDER": str(img_folder),
                "IMAGE_FILE_TYPE": "jpg",
                "DAYTIME_CAPTURE": False,
                "DAYTIME_CAPTURE_SAVE": False,
                "WEB_NONLOCAL_IMAGES": True,
                "WEB_LOCAL_IMAGES_ADMIN": True,
            }
            view.sun_set_date = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=3)
            view.camera_now = datetime.now(timezone.utc)
            view.latest_image_t = str(img_folder / "latest.{0}")

            with patch.object(view, "cameraSetup"), \
                 patch.object(view, "getLatestImage", return_value={}):
                view.capture_pause = False
                view.daytime_capture = False
                view.daytime_capture_save = False
                with patch.object(view, "verify_admin_network", return_value=False):
                    view.web_nonlocal_images = True
                    view.web_local_images_admin = True
                    # Daytime capture disabled with sun_set_date
                    res_data = view.get_objects()
                    assert "Night starts in" in res_data["latest_image"]["message"]

                    # Daytime capture disabled without sun_set_date
                    view.sun_set_date = None
                    res_data = view.get_objects()
                    assert "Sun never sets" in res_data["latest_image"]["message"]

                    # Daytime capture enabled without save, nonlocal check fails
                    view.daytime_capture = True
                    view.daytime_capture_save = False
                    res_data = view.get_objects()
                    assert res_data["latest_image"]["url"] is None

                    # Daytime capture enabled without save, admin bypass
                    with patch.object(view, "verify_admin_network", return_value=True):
                        res_data = view.get_objects()
                        assert "latest.jpg" in res_data["latest_image"]["url"]

            # 2. ImageViewerView, FitsImageViewerView, GalleryViewerView, VideoViewerView, MiniVideoViewerView
            for view_cls in (ImageViewerView, FitsImageViewerView, GalleryViewerView, VideoViewerView, MiniVideoViewerView):
                v = view_cls(template_name="dummy.html")
                v.camera = cam
                v.web_nonlocal_images = True
                v.web_local_images_admin = True
                with patch.object(v, "verify_admin_network", return_value=False):
                    ctx = v.get_context()
                    form_key = [k for k in ctx if k.startswith("form_")][0]
                    assert getattr(ctx[form_key], "local", False) is False


def test_json_focus_view_unreadable_images(flask_app, config_db, tmp_path):
    """Test JsonFocusView handling of unreadable/corrupted PNG and PIL image files."""
    with flask_app.app_context():
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_admin = True

        img_dir = tmp_path / "detect_images"
        img_dir.mkdir(parents=True, exist_ok=True)

        corrupt_png = img_dir / "latest.png"
        corrupt_png.write_bytes(b"invalid png data")

        corrupt_bmp = img_dir / "latest.bmp"
        corrupt_bmp.write_bytes(b"invalid bmp data")

        # 1. Unreadable PNG (cv2.imread returns None)
        with flask_app.test_request_context("/indi-allsky/js/focus?zoom=2&x_offset=0&y_offset=0"):
            view = JsonFocusView()
            view.indi_allsky_config = {"IMAGE_FOLDER": str(img_dir), "IMAGE_FILE_TYPE": "png"}
            with patch("cv2.imread", return_value=None):
                res = view.dispatch_request()
                assert res[1] == 400

        # 2. Corrupt Pillow image (PIL.UnidentifiedImageError)
        with flask_app.test_request_context("/indi-allsky/js/focus?zoom=2&x_offset=0&y_offset=0"):
            view = JsonFocusView()
            view.indi_allsky_config = {"IMAGE_FOLDER": str(img_dir), "IMAGE_FILE_TYPE": "bmp"}
            res = view.dispatch_request()
            assert res[1] == 400


def test_manual_gpio_view_device_control_exceptions(flask_app, config_db):
    """Test ManualGpioView when pin initializations encounter DeviceControlException."""
    with flask_app.app_context():
        with flask_app.test_request_context("/indi-allsky/manual_gpio"):
            view = ManualGpioView(template_name="manual_gpio.html")
            view.indi_allsky_config.update({
                "MANUAL_GPIO": {
                    "A_CLASSNAME": "DummyGpio",
                    "A_PIN_1": "21",
                    "A_PIN_2": "22",
                    "A_PIN_3": "23",
                }
            })

            class DummyGpio:
                def __init__(self, config, pin_1_name=None):
                    if pin_1_name == "21":
                        self.state = 1
                    else:
                        raise DeviceControlException(f"Pin {pin_1_name} error")

            setattr(indi_allsky_gpio, "DummyGpio", DummyGpio)
            try:
                ctx = view.get_context()
                assert ctx["pin_states"] == [1, -1, -1]
            finally:
                if hasattr(indi_allsky_gpio, "DummyGpio"):
                    delattr(indi_allsky_gpio, "DummyGpio")


def test_image_processing_view_and_json_branches(flask_app, config_db, tmp_path):
    """Test ImageProcessingView context defaults and JsonImageProcessingView validation and stack branches."""
    client = flask_app.test_client()
    with flask_app.app_context():
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_admin = True

        cam = IndiAllSkyDbCameraTable.query.first()
        cam_id = cam.id if cam else 1

        # 1. ImageProcessingView without fits_id and no SQM_ROI in config
        with flask_app.test_request_context("/indi-allsky/processing?type=light"):
            session["camera_id"] = cam_id
            view = ImageProcessingView(template_name="imageprocessing.html")
            view.camera = cam
            view.indi_allsky_config["SQM_ROI"] = None
            view.indi_allsky_config["IMAGE_LABEL_SYSTEM"] = "pillow"
            ctx = view.get_context()
            assert ctx["form_image_processing"].SQM_ROI_X1.data == 0

        # 2. JsonImageProcessingView form validation failure (400)
        with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
             patch("indi_allsky.flask.views.current_user", mock_user), \
             patch.object(IndiAllskyImageProcessingForm, "validate", lambda self, extra_validators=None: False):
            res = client.post("/indi-allsky/js/processing", json={"CAMERA_ID": cam_id})
            assert res.status_code == 400
            assert "form_global" in res.json

            # 3. JsonImageProcessingView with DARK frame type table lookup and file not found
            dark_entry = IndiAllSkyDbDarkFrameTable(
                camera_id=cam_id,
                filename="dark.fits",
                createDate=datetime.now(timezone.utc),
                exposure=10,
                gain=100.0,
                binmode=1,
                bitdepth=16,
                temp=15.0,
            )
            db.session.add(dark_entry)
            db.session.commit()

            base_proc_payload = {
                "CAMERA_ID": cam_id,
                "FRAME_TYPE": "dark",
                "FITS_ID": dark_entry.id,
                "DISABLE_PROCESSING": False,
                "OUTPUT_IMAGE_TYPE": "jpg",
                "SQM_ROI_X1": 10,
                "SQM_ROI_Y1": 10,
                "SQM_ROI_X2": 50,
                "SQM_ROI_Y2": 50,
                "CCD_BIT_DEPTH": "0",
                "TEXT_PROPERTIES__FONT_COLOR": "255,255,255",
                "CARDINAL_DIRS__FONT_COLOR": "255,255,255",
                "IMAGE_BORDER__COLOR": "0,0,0",
                "LIGHTGRAPH_OVERLAY__DAY_COLOR": "255,255,255",
                "LIGHTGRAPH_OVERLAY__DUSK_COLOR": "255,255,255",
                "LIGHTGRAPH_OVERLAY__NIGHT_COLOR": "0,0,0",
                "LIGHTGRAPH_OVERLAY__MOONMODE_COLOR": "100,100,100",
                "LIGHTGRAPH_OVERLAY__HOUR_COLOR": "150,150,150",
                "LIGHTGRAPH_OVERLAY__BORDER_COLOR": "200,200,200",
                "LIGHTGRAPH_OVERLAY__NOW_COLOR": "255,0,0",
                "LIGHTGRAPH_OVERLAY__FONT_COLOR": "150,150,150",
                "RUN_DETECTION": False,
            }

            # File does not exist -> 404
            with patch.object(IndiAllskyImageProcessingForm, "validate", lambda self, extra_validators=None: True), \
                 patch.object(IndiAllSkyDbDarkFrameTable, "getLocalOrCachedPath", side_effect=Exception("S3 download failure")):
                res = client.post("/indi-allsky/js/processing", json=base_proc_payload)
                assert res.status_code == 404
                assert res.json["message"] == "FITS file not found"


def test_ajax_asi676mc_calibration_database_search_error_branches(flask_app, config_db):
    """Test AjaxAsi676mcCalibrationDatabaseView error branches (retention, invalid params, session mismatch)."""
    client = flask_app.test_client()
    with flask_app.app_context():
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_admin = True
        mock_user.username = "admin"

        cam = IndiAllSkyDbCameraTable.query.first()
        cam_id = cam.id if cam else 1

        with patch.dict(flask_app.config, {"LOGIN_DISABLED": True, "IMAGE_ASI676MC_REPAIR": {"ENABLE": True}}), \
             patch("indi_allsky.flask.views._can_save_standard_configuration", return_value=True), \
             patch("indi_allsky.flask.views._asi676mc_feature_enabled", return_value=True), \
             patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[cam]), \
             patch("indi_allsky.flask.views.asi676mc.camera_record_matches", return_value=True), \
             patch("indi_allsky.flask.views.current_user", mock_user):

            # 1. Invalid target_groups / max_pair_seconds (400)
            res = client.post(
                "/indi-allsky/ajax/asi676mc/calibration/database",
                json={"camera_id": cam_id, "target_groups": "invalid", "max_pair_seconds": "invalid"},
            )
            assert res.status_code == 400
            assert "valid number" in res.json["error"]

            # 2. Camera not found (404)
            res = client.post(
                "/indi-allsky/ajax/asi676mc/calibration/database",
                json={"camera_id": 9999, "target_groups": 20, "max_pair_seconds": 90.0},
            )
            assert res.status_code == 404

            # 3. Session checkpoint camera mismatch (409)
            with patch("indi_allsky.flask.views._supported_asi676mc_camera", return_value=cam), \
                 patch("indi_allsky.asi676mc_calibration.database_search_checkpoint", return_value={"camera": {"id": 999, "uuid": "other-uuid"}}):
                res = client.post(
                    "/indi-allsky/ajax/asi676mc/calibration/database",
                    json={"camera_id": cam_id, "target_groups": 20, "max_pair_seconds": 90.0},
                )
                assert res.status_code == 409
                assert "changed" in res.json["error"]

            # 4. Invalid retention_days < 1 (400)
            config_entry = IndiAllSkyDbConfigTable.query.first()
            orig_data = dict(config_entry.data)
            config_entry.data = {**orig_data, "IMAGE_FITS_EXPIRE_DAYS": 0}
            db.session.commit()

            with patch("indi_allsky.flask.views._supported_asi676mc_camera", return_value=cam), \
                 patch("indi_allsky.asi676mc_calibration.database_search_checkpoint", return_value={"camera": {"id": cam.id, "uuid": str(cam.uuid)}}):
                res = client.post(
                    "/indi-allsky/ajax/asi676mc/calibration/database",
                    json={"camera_id": cam_id, "target_groups": 20, "max_pair_seconds": 90.0},
                )
                assert res.status_code == 400
                assert "retention must be at least 1 day" in res.json["error"]

            # 5. Database queue failure and mark_failed raising CalibrationSessionError (500)
            config_entry.data = {**orig_data, "IMAGE_FITS_EXPIRE_DAYS": 10}
            db.session.commit()

            with patch("indi_allsky.flask.views._supported_asi676mc_camera", return_value=cam), \
                 patch("indi_allsky.asi676mc_calibration.database_search_checkpoint", return_value={"camera": {"id": cam.id, "uuid": str(cam.uuid)}}), \
                 patch("indi_allsky.asi676mc_calibration.mark_queued", return_value={"session_id": "test"}), \
                 patch.object(db.session, "commit", side_effect=SQLAlchemyError("DB locked")), \
                 patch("indi_allsky.asi676mc_calibration.mark_failed", side_effect=CalibrationSessionError("Cannot mark failed")):
                res = client.post(
                    "/indi-allsky/ajax/asi676mc/calibration/database",
                    json={"camera_id": cam_id, "target_groups": 20, "max_pair_seconds": 90.0},
                )
                assert res.status_code == 500
                assert "service is unavailable" in res.json["error"]
