import io
import uuid
from unittest.mock import patch, MagicMock
import pytest
from sqlalchemy.exc import SQLAlchemyError

from indi_allsky.flask import db
from indi_allsky.flask.models import IndiAllSkyDbCameraTable
from indi_allsky.flask.views import (
    AjaxAsi676mcCalibrationSessionView,
    AjaxAsi676mcCalibrationUploadView,
    AjaxAsi676mcCalibrationDatabaseView,
    AjaxAsi676mcCalibrationStartView,
    AjaxAsi676mcCalibrationDiscardView,
    AjaxAsi676mcCalibrationApplyView,
)
from indi_allsky import asi676mc_calibration
from indi_allsky.exceptions import ConfigSaveException


def test_asi676mc_session_create_errors(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user), \
         patch("indi_allsky.asi676mc.feature_enabled", return_value=True), \
         patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[MagicMock(id=1)]), \
         patch("indi_allsky.flask.views._calibration_owner", return_value="admin"), \
         patch("indi_allsky.flask.views._camera_identity", return_value={"id": 1, "uuid": "cam-123"}), \
         patch("indi_allsky.flask.views._supported_asi676mc_camera", return_value=MagicMock(id=1)):

        # 1. CalibrationSessionError -> 400
        with patch("indi_allsky.asi676mc_calibration.create_session", side_effect=asi676mc_calibration.CalibrationSessionError("Session limit reached")):
            res = client.post("/indi-allsky/ajax/asi676mc/calibration/session", json={"camera_id": 1})
            assert res.status_code == 400
            assert "Session limit reached" in res.get_json()["error"]

        # 2. OSError -> 500
        with patch("indi_allsky.asi676mc_calibration.create_session", side_effect=OSError("Disk full")):
            res = client.post("/indi-allsky/ajax/asi676mc/calibration/session", json={"camera_id": 1})
            assert res.status_code == 500
            assert "Free some disk space" in res.get_json()["error"]


def test_asi676mc_upload_errors(flask_app, system_db):
    client = flask_app.test_client()
    session_id = "test-session-123"

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user), \
         patch("indi_allsky.asi676mc.feature_enabled", return_value=True), \
         patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[MagicMock(id=1)]), \
         patch("indi_allsky.flask.views._calibration_owner", return_value="admin"):

        # 1. CalibrationUploadError -> 400
        with patch("indi_allsky.asi676mc_calibration.store_upload", side_effect=asi676mc_calibration.CalibrationUploadError("invalid FITS format")):
            res = client.post(
                f"/indi-allsky/ajax/asi676mc/calibration/upload/{session_id}",
                data={"file": (io.BytesIO(b"fakefits"), "test.fits")},
                content_type="multipart/form-data",
            )
            assert res.status_code == 400
            assert res.get_json()["error"] == "Invalid FITS format."

        # 2. CalibrationSessionError -> 400
        with patch("indi_allsky.asi676mc_calibration.store_upload", side_effect=asi676mc_calibration.CalibrationSessionError("expired")):
            res = client.post(
                f"/indi-allsky/ajax/asi676mc/calibration/upload/{session_id}",
                data={"file": (io.BytesIO(b"fakefits"), "test.fits")},
                content_type="multipart/form-data",
            )
            assert res.status_code == 400
            assert "no longer available" in res.get_json()["error"]

        # 3. OSError -> 500
        with patch("indi_allsky.asi676mc_calibration.store_upload", side_effect=OSError("write error")):
            res = client.post(
                f"/indi-allsky/ajax/asi676mc/calibration/upload/{session_id}",
                data={"file": (io.BytesIO(b"fakefits"), "test.fits")},
                content_type="multipart/form-data",
            )
            assert res.status_code == 500
            assert "Free some disk space" in res.get_json()["error"]


def test_asi676mc_database_and_start_queue_failures(flask_app, system_db):
    client = flask_app.test_client()
    session_id = "test-session-123"

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user), \
         patch("indi_allsky.asi676mc.feature_enabled", return_value=True), \
         patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[MagicMock(id=1)]), \
         patch("indi_allsky.flask.views._calibration_owner", return_value="admin"):

        # 1. Database View: mark_failed fallback under SQLAlchemyError
        mock_cam = MagicMock(id=1)
        mock_cam.uuid = "cam-123"
        checkpoint_manifest = {"camera": {"id": 1, "uuid": "cam-123"}}
        with patch("indi_allsky.flask.views._supported_asi676mc_camera", return_value=mock_cam), \
             patch("indi_allsky.asi676mc_calibration.database_search_checkpoint", return_value=checkpoint_manifest), \
             patch("indi_allsky.asi676mc_calibration.mark_queued", return_value={"session_id": session_id}), \
             patch.object(db.session, "commit", side_effect=SQLAlchemyError("DB error")), \
             patch("indi_allsky.asi676mc_calibration.mark_failed") as mock_mark:
            res = client.post(
                f"/indi-allsky/ajax/asi676mc/calibration/database",
                json={"camera_id": 1, "target_groups": 10, "exposure_levels": [0.001]},
            )
            assert res.status_code == 500
            mock_mark.assert_called_once()
            assert "service is unavailable" in res.get_json()["error"]

        # 2. Start View: mark_failed fallback under SQLAlchemyError
        upload_manifest = {"files": [1], "camera": {"id": 1, "uuid": "cam-123"}}
        with patch("indi_allsky.flask.views._supported_asi676mc_camera", return_value=mock_cam), \
             patch("indi_allsky.asi676mc_calibration.get_session", return_value=(None, upload_manifest)), \
             patch("indi_allsky.asi676mc_calibration.mark_queued", return_value={"session_id": session_id}), \
             patch.object(db.session, "commit", side_effect=SQLAlchemyError("DB error")), \
             patch("indi_allsky.asi676mc_calibration.mark_failed") as mock_mark:
            res = client.post(
                f"/indi-allsky/ajax/asi676mc/calibration/start/{session_id}",
                json={"max_pair_seconds": 60},
            )
            assert res.status_code == 500
            mock_mark.assert_called_once()
            assert "service is unavailable" in res.get_json()["error"]


def test_asi676mc_discard_error_branches(flask_app, system_db):
    client = flask_app.test_client()
    session_id = "test-session-123"

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user), \
         patch("indi_allsky.asi676mc.feature_enabled", return_value=True), \
         patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[MagicMock(id=1)]), \
         patch("indi_allsky.flask.views._calibration_owner", return_value="admin"):

        # 1. CalibrationSessionError -> 409
        with patch("indi_allsky.asi676mc_calibration.discard_session", side_effect=asi676mc_calibration.CalibrationSessionError("Not ready")):
            res = client.post(f"/indi-allsky/ajax/asi676mc/calibration/discard/{session_id}")
            assert res.status_code == 409
            assert res.get_json()["error_code"] == "discard_rejected"

        # 2. OSError -> 500
        with patch("indi_allsky.asi676mc_calibration.discard_session", side_effect=OSError("Cannot delete")):
            res = client.post(f"/indi-allsky/ajax/asi676mc/calibration/discard/{session_id}")
            assert res.status_code == 500
            assert res.get_json()["error_code"] == "discard_failed"


def test_asi676mc_apply_error_and_recovery_branches(flask_app, system_db):
    client = flask_app.test_client()
    session_id = "test-session-123"

    cam_uuid = str(uuid.uuid4())
    mock_cam = MagicMock()
    mock_cam.uuid = cam_uuid

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    from indi_allsky.config import IndiAllSkyConfig
    from indi_allsky.flask.base_views import miscDb

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user), \
         patch("indi_allsky.asi676mc.feature_enabled", return_value=True), \
         patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[mock_cam]), \
         patch("indi_allsky.flask.views._calibration_owner", return_value="admin"), \
         patch("indi_allsky.flask.views._supported_asi676mc_camera", return_value=mock_cam):

        # 1. CalibrationSessionError -> 400
        with patch("indi_allsky.asi676mc_calibration.get_completed_result", side_effect=asi676mc_calibration.CalibrationSessionError("Expired")):
            res = client.post(f"/indi-allsky/ajax/asi676mc/calibration/apply/{session_id}")
            assert res.status_code == 400
            assert res.get_json()["error_code"] == "result_unavailable"

        # 2. Camera mismatch -> 409
        manifest_mismatch = {"camera": {"id": 1, "uuid": "different-uuid"}}
        with patch("indi_allsky.asi676mc_calibration.get_completed_result", return_value=(manifest_mismatch, {}, {})):
            res = client.post(f"/indi-allsky/ajax/asi676mc/calibration/apply/{session_id}")
            assert res.status_code == 409
            assert res.get_json()["error_code"] == "camera_changed"

        # 3. Population confirmation required for threshold suggestion -> 400
        manifest_ok = {"camera": {"id": 1, "uuid": cam_uuid}, "config_id": 1}
        result_thresh = {"outcome": "threshold_suggestion"}
        with patch("indi_allsky.asi676mc_calibration.get_completed_result", return_value=(manifest_ok, result_thresh, {})):
            res = client.post(f"/indi-allsky/ajax/asi676mc/calibration/apply/{session_id}", json={})
            assert res.status_code == 400
            assert res.get_json()["error_code"] == "population_confirmation_required"

        # 4. Configuration changed -> 409
        manifest_diff_cfg = {"camera": {"id": 1, "uuid": cam_uuid}, "config_id": 9999}
        with patch("indi_allsky.asi676mc_calibration.get_completed_result", return_value=(manifest_diff_cfg, {"outcome": "calibration"}, {})):
            res = client.post(f"/indi-allsky/ajax/asi676mc/calibration/apply/{session_id}", json={})
            assert res.status_code == 409
            assert res.get_json()["error_code"] == "configuration_changed"

        # 5. ConfigSaveException during save -> 400 with rollback of config
        result_calib = {"outcome": "calibration", "quality": {"matched_bad_count": 5, "matched_normal_count": 10}}
        values = {"SPLIT_ROWS": 16}
        with patch.object(IndiAllSkyConfig, "config_id", 1):
            with patch("indi_allsky.asi676mc_calibration.get_completed_result", return_value=(manifest_ok, result_calib, values)):
                with patch("indi_allsky.asi676mc.normalize_settings"):
                    with patch("indi_allsky.flask.views._calibration_save_actor", return_value="admin"):
                        with patch.object(IndiAllSkyConfig, "save", side_effect=ConfigSaveException("Save error")):
                            res = client.post(f"/indi-allsky/ajax/asi676mc/calibration/apply/{session_id}", json={})
                            assert res.status_code == 400
                            assert res.get_json()["error_code"] == "configuration_save_failed"

        # 6. Incompatible settings (ValueError) during normalize -> 400
        with patch.object(IndiAllSkyConfig, "config_id", 1):
            with patch("indi_allsky.asi676mc_calibration.get_completed_result", return_value=(manifest_ok, result_calib, values)):
                with patch("indi_allsky.asi676mc.normalize_settings", side_effect=ValueError("bad setting")):
                    res = client.post(f"/indi-allsky/ajax/asi676mc/calibration/apply/{session_id}", json={})
                    assert res.status_code == 400
                    assert res.get_json()["error_code"] == "incompatible_settings"

        # 7. Successful save with reload SQLAlchemyError fallback
        with patch.object(IndiAllSkyConfig, "config_id", 1):
            with patch("indi_allsky.asi676mc_calibration.get_completed_result", return_value=(manifest_ok, result_calib, values)):
                with patch("indi_allsky.asi676mc.normalize_settings"):
                    with patch.object(IndiAllSkyConfig, "save"):
                        with patch.object(miscDb, "setState"):
                            with patch.object(db.session, "commit", side_effect=SQLAlchemyError("DB task error")):
                                res = client.post(f"/indi-allsky/ajax/asi676mc/calibration/apply/{session_id}", json={})
                                assert res.status_code == 200
                                assert "success-message" in res.get_json()
