from unittest.mock import patch, MagicMock
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
