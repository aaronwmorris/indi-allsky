from unittest.mock import patch, MagicMock, PropertyMock
from pathlib import Path
import pytest

from indi_allsky.flask.views import (
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


def test_asi676mc_calibration_session_view(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user), \
         patch("indi_allsky.asi676mc.feature_enabled", return_value=True), \
         patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[MagicMock(id=1)]), \
         patch("indi_allsky.flask.views._supported_asi676mc_camera") as mock_cam:
        mock_cam.return_value = MagicMock(id=1)
        with patch("indi_allsky.asi676mc_calibration.create_session") as mock_cs:
            mock_cs.return_value = {"session_id": "test-session-123"}
            res = client.post("/indi-allsky/ajax/asi676mc/calibration/session", json={"camera_id": 1})
            assert res.status_code == 200
            assert res.get_json()["session_id"] == "test-session-123"


def test_asi676mc_calibration_upload_view(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user), \
         patch("indi_allsky.asi676mc.feature_enabled", return_value=True), \
         patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[MagicMock(id=1)]), \
         patch("indi_allsky.asi676mc_calibration.store_upload") as mock_store:
        mock_store.return_value = ({"name": "test.fits"}, {"files": [1], "total_bytes": 100})
        res = client.post("/indi-allsky/ajax/asi676mc/calibration/upload/test-session-123", data={})
        assert res.status_code == 200


def test_asi676mc_calibration_status_and_cancel(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user), \
         patch("indi_allsky.asi676mc.feature_enabled", return_value=True), \
         patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[MagicMock(id=1)]), \
         patch("indi_allsky.asi676mc_calibration.get_session") as mock_status:
        mock_status.return_value = (Path("/tmp"), {"session_id": "test-session-123", "state": "ready"})
        res = client.get("/indi-allsky/ajax/asi676mc/calibration/status/test-session-123")
        assert res.status_code in (200, 400, 404)

        with patch("indi_allsky.asi676mc_calibration.cancel_session") as mock_cancel:
            mock_cancel.return_value = {"session_id": "test-session-123", "status": "cancelled", "sources_deleted_utc": ["2026-09-19T00:00:00"]}
            res_cancel = client.post("/indi-allsky/ajax/asi676mc/calibration/cancel/test-session-123")
            assert res_cancel.status_code in (200, 400, 404)


def test_asi676mc_calibration_start_view(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user), \
         patch("indi_allsky.asi676mc.feature_enabled", return_value=True), \
         patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[MagicMock(id=1)]):

        # Invalid gap seconds
        res_invalid = client.post("/indi-allsky/ajax/asi676mc/calibration/start/test-session-123", json={"max_pair_seconds": -5})
        assert res_invalid.status_code == 400

        # Session error
        from indi_allsky import asi676mc_calibration
        with patch("indi_allsky.asi676mc_calibration.get_session", side_effect=asi676mc_calibration.CalibrationSessionError("Session not found")):
            res_err = client.post("/indi-allsky/ajax/asi676mc/calibration/start/test-session-123", json={"max_pair_seconds": 90.0})
            assert res_err.status_code == 400


def test_asi676mc_calibration_report_view(flask_app, system_db, tmp_path):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user), \
         patch("indi_allsky.asi676mc.feature_enabled", return_value=True), \
         patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[MagicMock(id=1)]):

        from indi_allsky import asi676mc_calibration

        # Report missing 404
        with patch("indi_allsky.asi676mc_calibration.get_report_download", side_effect=asi676mc_calibration.CalibrationSessionError("Report missing")):
            res_missing = client.get("/indi-allsky/asi676mc/calibration/report/test-session-123")
            assert res_missing.status_code == 404

        # Report success
        report_file = tmp_path / "report.txt"
        report_file.write_text("ASI676MC Calibration Report")
        with patch("indi_allsky.asi676mc_calibration.get_report_download", return_value=(report_file, "asi676mc_report.txt")):
            res_ok = client.get("/indi-allsky/asi676mc/calibration/report/test-session-123")
            assert res_ok.status_code == 200


def test_asi676mc_calibration_discard_and_apply_views(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user), \
         patch("indi_allsky.asi676mc.feature_enabled", return_value=True), \
         patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[MagicMock(id=1)]):

        from indi_allsky import asi676mc_calibration

        # Discard already discarded
        with patch("indi_allsky.asi676mc_calibration.discard_session", side_effect=asi676mc_calibration.CalibrationSessionError("This calibration run is no longer available. Reload the page and start a new calibration.")):
            res_disc = client.post("/indi-allsky/ajax/asi676mc/calibration/discard/test-session-123")
            assert res_disc.status_code == 200
            assert res_disc.get_json()["status"] == "already_discarded"

        # Apply result unavailable
        with patch("indi_allsky.asi676mc_calibration.get_completed_result", side_effect=asi676mc_calibration.CalibrationSessionError("Unavailable")):
            res_apply_err = client.post("/indi-allsky/ajax/asi676mc/calibration/apply/test-session-123")
            assert res_apply_err.status_code == 400


def test_asi676mc_calibration_view_and_database(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    mock_cam = MagicMock(id=1, friendlyName="ASI676MC", name="asi676mc", uuid="cam-uuid-1")

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user), \
         patch("indi_allsky.asi676mc.feature_enabled", return_value=True), \
         patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[mock_cam]), \
         patch("indi_allsky.flask.views._supported_asi676mc_camera", return_value=mock_cam):

        # GET calibration page
        res = client.get("/indi-allsky/asi676mc/calibration")
        assert res.status_code == 200

        # POST database search - invalid target groups
        res_bad_groups = client.post("/indi-allsky/ajax/asi676mc/calibration/database", json={
            "session_id": "test-session-123",
            "camera_id": 1,
            "target_groups": 1,  # less than MIN (5)
        })
        assert res_bad_groups.status_code == 400

        # POST database search - invalid gap
        res_bad_gap = client.post("/indi-allsky/ajax/asi676mc/calibration/database", json={
            "session_id": "test-session-123",
            "camera_id": 1,
            "target_groups": 20,
            "max_pair_seconds": -1,
        })
        assert res_bad_gap.status_code == 400


def test_asi676mc_calibration_apply_detailed_branches(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    mock_cam = MagicMock(id=1, friendlyName="ASI676MC", name="asi676mc", uuid="cam-uuid-1")

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user), \
         patch("indi_allsky.asi676mc.feature_enabled", return_value=True), \
         patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[mock_cam]), \
         patch("indi_allsky.flask.views._supported_asi676mc_camera", return_value=mock_cam):

        # 1. Camera changed/mismatch (uuid mismatch)
        manifest_diff_cam = {
            "config_id": "cfg-123",
            "camera": {"id": 1, "uuid": "different-uuid"},
        }
        res_dict_diff = {
            "outcome": "calibration",
            "values": {"MEDIAN_THRESHOLD": 50},
            "quality": {"matched_bad_count": 10, "matched_normal_count": 20},
        }
        with patch("indi_allsky.asi676mc_calibration.get_completed_result", return_value=(manifest_diff_cam, res_dict_diff, {"MEDIAN_THRESHOLD": 50})):
            res_cam_diff = client.post("/indi-allsky/ajax/asi676mc/calibration/apply/test-session-123")
            assert res_cam_diff.status_code == 409
            assert res_cam_diff.get_json()["error_code"] == "camera_changed"

        # 2. Threshold suggestion unconfirmed
        manifest_valid = {
            "config_id": "cfg-123",
            "camera": {"id": 1, "uuid": "cam-uuid-1"},
        }
        res_dict_thresh = {
            "outcome": "threshold_suggestion",
            "values": {"MEDIAN_THRESHOLD": 50},
            "quality": {"matched_bad_count": 10, "matched_normal_count": 20},
        }
        with patch("indi_allsky.asi676mc_calibration.get_completed_result", return_value=(manifest_valid, res_dict_thresh, {"MEDIAN_THRESHOLD": 50})):
            res_unconf = client.post("/indi-allsky/ajax/asi676mc/calibration/apply/test-session-123", json={})
            assert res_unconf.status_code == 400
            assert res_unconf.get_json()["error_code"] == "population_confirmation_required"

        # 3. Configuration changed mismatch
        manifest_old_cfg = {
            "config_id": "old-config-id",
            "camera": {"id": 1, "uuid": "cam-uuid-1"},
        }
        res_dict_cfg_mismatch = {
            "outcome": "calibration",
            "values": {"MEDIAN_THRESHOLD": 50},
            "quality": {"matched_bad_count": 10, "matched_normal_count": 20},
        }
        with patch("indi_allsky.asi676mc_calibration.get_completed_result", return_value=(manifest_old_cfg, res_dict_cfg_mismatch, {"MEDIAN_THRESHOLD": 50})):
            with patch("indi_allsky.config.IndiAllSkyConfig.config_id", new_callable=PropertyMock, return_value="new-config-id"):
                res_cfg_diff = client.post("/indi-allsky/ajax/asi676mc/calibration/apply/test-session-123")
                assert res_cfg_diff.status_code == 409
                assert res_cfg_diff.get_json()["error_code"] == "configuration_changed"

        # 4. Successful apply for calibration outcome
        manifest_success = {
            "config_id": "cfg-123",
            "camera": {"id": 1, "uuid": "cam-uuid-1"},
        }
        res_dict_success = {
            "outcome": "calibration",
            "values": {"MEDIAN_THRESHOLD": 50},
            "quality": {"matched_bad_count": 10, "matched_normal_count": 20},
        }
        with patch("indi_allsky.asi676mc_calibration.get_completed_result", return_value=(manifest_success, res_dict_success, {"MEDIAN_THRESHOLD": 50})):
            with patch("indi_allsky.asi676mc.normalize_settings"):
                with patch("indi_allsky.config.IndiAllSkyConfig.config_id", new_callable=PropertyMock, return_value="cfg-123"):
                    with patch("indi_allsky.config.IndiAllSkyConfig.save"):
                        res_ok = client.post("/indi-allsky/ajax/asi676mc/calibration/apply/test-session-123")
                        assert res_ok.status_code == 200
                        assert "success-message" in res_ok.get_json()


def test_asi676mc_calibration_database_and_start_deep_branches(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    mock_cam = MagicMock(id=1, friendlyName="ASI676MC", name="asi676mc", uuid="cam-uuid-1")

    from indi_allsky import asi676mc_calibration

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user), \
         patch("indi_allsky.asi676mc.feature_enabled", return_value=True), \
         patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[mock_cam]), \
         patch("indi_allsky.flask.views._supported_asi676mc_camera", return_value=mock_cam):

        # Database search: camera not found (404)
        with patch("indi_allsky.flask.views._supported_asi676mc_camera", return_value=None):
            res_404 = client.post("/indi-allsky/ajax/asi676mc/calibration/database", json={"session_id": "s1", "camera_id": 1, "target_groups": 10, "max_pair_seconds": 60})
            assert res_404.status_code == 404

        # Database search: checkpoint CalibrationSessionError (409)
        with patch("indi_allsky.asi676mc_calibration.database_search_checkpoint", side_effect=asi676mc_calibration.CalibrationSessionError("Checkpoint error")):
            res_409 = client.post("/indi-allsky/ajax/asi676mc/calibration/database", json={"session_id": "s1", "camera_id": 1, "target_groups": 10, "max_pair_seconds": 60})
            assert res_409.status_code == 409

        # Database search: camera uuid mismatch (409)
        with patch("indi_allsky.asi676mc_calibration.database_search_checkpoint", return_value={"camera": {"id": 1, "uuid": "other-uuid"}}):
            res_mismatch = client.post("/indi-allsky/ajax/asi676mc/calibration/database", json={"session_id": "s1", "camera_id": 1, "target_groups": 10, "max_pair_seconds": 60})
            assert res_mismatch.status_code == 409

        # Database search: retention days invalid (400)
        with patch("indi_allsky.asi676mc_calibration.database_search_checkpoint", return_value={"camera": {"id": 1, "uuid": "cam-uuid-1"}}):
            flask_app.config["IMAGE_FITS_EXPIRE_DAYS"] = "invalid"
            res_ret_bad = client.post("/indi-allsky/ajax/asi676mc/calibration/database", json={"session_id": "s1", "camera_id": 1, "target_groups": 10, "max_pair_seconds": 60})
            assert res_ret_bad.status_code == 400

            flask_app.config["IMAGE_FITS_EXPIRE_DAYS"] = 0
            res_ret_low = client.post("/indi-allsky/ajax/asi676mc/calibration/database", json={"session_id": "s1", "camera_id": 1, "target_groups": 10, "max_pair_seconds": 60})
            assert res_ret_low.status_code == 400
            flask_app.config["IMAGE_FITS_EXPIRE_DAYS"] = 10


        # Database search: normalize settings error (400)
        with patch("indi_allsky.asi676mc_calibration.database_search_checkpoint", return_value={"camera": {"id": 1, "uuid": "cam-uuid-1"}}), \
             patch("indi_allsky.asi676mc.normalize_settings", side_effect=ValueError("Invalid settings")):
            res_norm_err = client.post("/indi-allsky/ajax/asi676mc/calibration/database", json={"session_id": "s1", "camera_id": 1, "target_groups": 10, "max_pair_seconds": 60})
            assert res_norm_err.status_code == 400

        # Database search: mark_queued CalibrationSessionError (400)
        with patch("indi_allsky.asi676mc_calibration.database_search_checkpoint", return_value={"camera": {"id": 1, "uuid": "cam-uuid-1"}}), \
             patch("indi_allsky.asi676mc.normalize_settings", return_value={}), \
             patch("indi_allsky.asi676mc_calibration.mark_queued", side_effect=asi676mc_calibration.CalibrationSessionError("Queue failed")), \
             patch("indi_allsky.asi676mc_calibration.cancel_session"):
            res_queue_err = client.post("/indi-allsky/ajax/asi676mc/calibration/database", json={"session_id": "s1", "camera_id": 1, "target_groups": 10, "max_pair_seconds": 60})
            assert res_queue_err.status_code == 400

        # Database search: success (200)
        with patch("indi_allsky.asi676mc_calibration.database_search_checkpoint", return_value={"camera": {"id": 1, "uuid": "cam-uuid-1"}}), \
             patch("indi_allsky.asi676mc.normalize_settings", return_value={}), \
             patch("indi_allsky.asi676mc_calibration.mark_queued", return_value={"status": "queued"}):
            res_db_ok = client.post("/indi-allsky/ajax/asi676mc/calibration/database", json={"session_id": "s1", "camera_id": 1, "target_groups": 10, "max_pair_seconds": 60})
            assert res_db_ok.status_code == 200
            assert res_db_ok.get_json()["status"] == "queued"

        # Start calibration: camera mismatch (409)
        with patch("indi_allsky.asi676mc_calibration.get_session", return_value=(None, {"camera": {"id": 1, "uuid": "mismatch-uuid"}})):
            res_start_mismatch = client.post("/indi-allsky/ajax/asi676mc/calibration/start/s1", json={"max_pair_seconds": 60})
            assert res_start_mismatch.status_code == 409

        # Start calibration: normalize settings error (400)
        with patch("indi_allsky.asi676mc_calibration.get_session", return_value=(None, {"camera": {"id": 1, "uuid": "cam-uuid-1"}})), \
             patch("indi_allsky.asi676mc.normalize_settings", side_effect=ValueError("Bad settings")):
            res_start_norm_err = client.post("/indi-allsky/ajax/asi676mc/calibration/start/s1", json={"max_pair_seconds": 60})
            assert res_start_norm_err.status_code == 400

        # Start calibration: mark_queued CalibrationSessionError (400)
        with patch("indi_allsky.asi676mc_calibration.get_session", return_value=(None, {"camera": {"id": 1, "uuid": "cam-uuid-1"}})), \
             patch("indi_allsky.asi676mc.normalize_settings", return_value={}), \
             patch("indi_allsky.asi676mc_calibration.mark_queued", side_effect=asi676mc_calibration.CalibrationSessionError("Queue error")):
            res_start_q_err = client.post("/indi-allsky/ajax/asi676mc/calibration/start/s1", json={"max_pair_seconds": 60})
            assert res_start_q_err.status_code == 400

        # Start calibration: success (200)
        with patch("indi_allsky.asi676mc_calibration.get_session", return_value=(None, {"camera": {"id": 1, "uuid": "cam-uuid-1"}})), \
             patch("indi_allsky.asi676mc.normalize_settings", return_value={}), \
             patch("indi_allsky.asi676mc_calibration.mark_queued", return_value={"status": "queued"}):
            res_start_ok = client.post("/indi-allsky/ajax/asi676mc/calibration/start/s1", json={"max_pair_seconds": 60})
            assert res_start_ok.status_code == 200
            assert res_start_ok.get_json()["status"] == "queued"




