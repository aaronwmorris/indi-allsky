from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, mock_open
import io
import pytest
from flask import json
from sqlalchemy.exc import SQLAlchemyError

from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbTaskQueueTable,
    TaskQueueQueue,
    TaskQueueState,
    db,
)
from indi_allsky.config import IndiAllSkyConfig
from indi_allsky.exceptions import ConfigSaveException
from indi_allsky.asi676mc_calibration import CalibrationSessionError


def test_lens_solver_save_config_save_exception(flask_app, system_db):
    """Test AjaxLensSolverView save branch raising ConfigSaveException."""
    client = flask_app.test_client()
    with flask_app.app_context():
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_admin = True
        mock_user.username = "admin"

        with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
             patch("indi_allsky.flask.views.current_user", mock_user):
            payload = {
                "action": "save",
                "RELOAD_ON_SAVE": False,
                "AZIMUTH_ANGLE": 180.0,
                "LATITUDE_OFFSET": 0.0,
                "LONGITUDE_OFFSET": 0.0,
                "IMAGE_CIRCLE_DIAMETER": 2000,
                "OFFSET_X": 5,
                "OFFSET_Y": -5,
                "LENS_ALTITUDE": 45.0,
                "POINTING_AZIMUTH": 180.0,
                "LENS_AZIMUTH": 10.0,
            }
            with patch("indi_allsky.config.IndiAllSkyConfig.save", side_effect=ConfigSaveException("Write error")):
                response = client.post(
                    "/indi-allsky/ajax/lens_solver",
                    json=payload,
                )
                assert response.status_code == 400
                data = json.loads(response.data)
                assert "form_global" in data
                assert "Write error" in data["form_global"][0]


def test_lens_solver_solve_extended_branches(flask_app, system_db):
    """Test AjaxLensSolverView solve() locking, calibration hints, and error branches."""
    client = flask_app.test_client()
    with flask_app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        if not cam:
            cam = IndiAllSkyDbCameraTable(
                name="SolverCam",
                driver="indi_simulator",
                uuid="solv-uuid-1",
                width=3000,
                height=3000,
                alt=45.0,
                latitude=52.0,
                longitude=0.0,
                elevation=100.0,
                data={"vs_pointing_azimuth": 90.0},
            )
            db.session.add(cam)
            db.session.commit()
        else:
            cam.width = 3000
            cam.height = 3000
            cam.data = {"vs_pointing_azimuth": 90.0}
            db.session.commit()

        now_dt = datetime.now()
        img = IndiAllSkyDbImageTable(
            camera_id=cam.id,
            filename="solver_test.jpg",
            createDate=now_dt,
            dayDate=now_dt.date(),
            exposure=1.0,
            gain=100.0,
            binmode=2,
            adu=1000,
            temp=20.0,
        )
        db.session.add(img)
        db.session.commit()

        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_admin = True
        mock_user.username = "admin"

        with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
             patch("indi_allsky.flask.views.current_user", mock_user):
            # 1. Lock acquisition failure (429)
            mock_lock = MagicMock()
            mock_lock.acquire.return_value = False
            with patch("indi_allsky.flask.views.AjaxLensSolverView._solve_lock", mock_lock):
                with patch("pathlib.Path.exists", return_value=True):
                    payload = {
                        "action": "solve",
                        "camera_id": cam.id,
                        "timestamp": int(now_dt.timestamp()),
                        "AZIMUTH_ANGLE": 180.0,
                        "LATITUDE_OFFSET": 0.0,
                        "LONGITUDE_OFFSET": 0.0,
                        "IMAGE_CIRCLE_DIAMETER": 2000,
                        "OFFSET_X": 5,
                        "OFFSET_Y": -5,
                        "CALIBRATION_ENABLED": True,
                    }
                    response = client.post(
                        "/indi-allsky/ajax/lens_solver",
                        json=payload,
                    )
                    assert response.status_code == 429
                    data = json.loads(response.data)
                    assert "already in progress" in data["message"]

            # 2. Successful solve with hints and calibration return dict
            mock_result = {
                "success": True,
                "calibration": {
                    "context": [0, 0, 0],
                },
            }
            with patch("pathlib.Path.exists", return_value=True):
                with patch("indi_allsky.lens_solver.IndiAllSkyLensSolver.solve", return_value=mock_result) as mock_solve:
                    payload = {
                        "action": "solve",
                        "camera_id": cam.id,
                        "timestamp": int(now_dt.timestamp()),
                        "AZIMUTH_ANGLE": 180.0,
                        "LATITUDE_OFFSET": 0.0,
                        "LONGITUDE_OFFSET": 0.0,
                        "IMAGE_CIRCLE_DIAMETER": 2000,
                        "OFFSET_X": 5,
                        "OFFSET_Y": -5,
                        "CALIBRATION_ENABLED": True,
                    }
                    response = client.post(
                        "/indi-allsky/ajax/lens_solver",
                        json=payload,
                    )
                    assert response.status_code == 200
                    data = json.loads(response.data)
                    assert data["success"] is True
                    assert data["calibration"]["camera_uuid"] == cam.uuid
                    mock_solve.assert_called_once()

            # 3. Solver exception (500)
            with patch("pathlib.Path.exists", return_value=True):
                with patch("indi_allsky.lens_solver.IndiAllSkyLensSolver.solve", side_effect=RuntimeError("Scipy crash")):
                    payload = {
                        "action": "solve",
                        "camera_id": cam.id,
                        "timestamp": int(now_dt.timestamp()),
                        "AZIMUTH_ANGLE": 180.0,
                        "LATITUDE_OFFSET": 0.0,
                        "LONGITUDE_OFFSET": 0.0,
                        "IMAGE_CIRCLE_DIAMETER": 2000,
                        "OFFSET_X": 5,
                        "OFFSET_Y": -5,
                        "CALIBRATION_ENABLED": False,
                    }
                    response = client.post(
                        "/indi-allsky/ajax/lens_solver",
                        json=payload,
                    )
                    assert response.status_code == 500
                    data = json.loads(response.data)
                    assert "Solver error" in data["message"]


def test_asi676mc_calibration_report_view(flask_app, system_db, tmp_path):
    """Test Asi676mcCalibrationReportView for success and error cases."""
    client = flask_app.test_client()
    with flask_app.app_context():
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_admin = True
        mock_user.username = "admin"

        mock_cam = MagicMock(id=1, uuid="cam-uuid")

        with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
             patch("indi_allsky.flask.views.current_user", mock_user), \
             patch("indi_allsky.flask.views._asi676mc_feature_enabled", return_value=True), \
             patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[mock_cam]):
            # 1. CalibrationSessionError -> 404
            with patch("indi_allsky.asi676mc_calibration.get_report_download", side_effect=CalibrationSessionError("Report expired")):
                response = client.get("/indi-allsky/asi676mc/calibration/report/sess-123")
                assert response.status_code == 404
                assert b"no longer available" in response.data

            # 2. Success -> send_file download
            report_file = tmp_path / "calibration_report.txt"
            report_file.write_text("ASI676MC Calibration Report Data")
            with patch("indi_allsky.asi676mc_calibration.get_report_download", return_value=(str(report_file), "report.txt")):
                response = client.get("/indi-allsky/asi676mc/calibration/report/sess-123")
                assert response.status_code == 200
                assert response.data == b"ASI676MC Calibration Report Data"


def test_asi676mc_calibration_discard_and_apply_extended(flask_app, system_db):
    """Test discard and apply views for ASI676MC calibration error and outcome branches."""
    client = flask_app.test_client()
    with flask_app.app_context():
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_admin = True
        mock_user.username = "admin"

        mock_cam = MagicMock(id=1, uuid="cam-uuid")
        current_cfg_id = IndiAllSkyConfig().config_id

        with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
             patch("indi_allsky.flask.views.current_user", mock_user), \
             patch("indi_allsky.flask.views._asi676mc_feature_enabled", return_value=True), \
             patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[mock_cam]), \
             patch("indi_allsky.flask.views._supported_asi676mc_camera", return_value=mock_cam):
            # 1. Discard with already expired session message -> status 'already_discarded'
            with patch("indi_allsky.asi676mc_calibration.discard_session", side_effect=CalibrationSessionError("This calibration run is no longer available. Reload the page and start a new calibration.")):
                response = client.post("/indi-allsky/ajax/asi676mc/calibration/discard/sess-123")
                assert response.status_code == 200
                data = json.loads(response.data)
                assert data["status"] == "already_discarded"

            # 2. Discard with general session error -> 409
            with patch("indi_allsky.asi676mc_calibration.discard_session", side_effect=CalibrationSessionError("Session active")):
                response = client.post("/indi-allsky/ajax/asi676mc/calibration/discard/sess-123")
                assert response.status_code == 409
                data = json.loads(response.data)
                assert data["error_code"] == "discard_rejected"

            # 3. Discard with OSError -> 500
            with patch("indi_allsky.asi676mc_calibration.discard_session", side_effect=OSError("Disk failed")):
                response = client.post("/indi-allsky/ajax/asi676mc/calibration/discard/sess-123")
                assert response.status_code == 500
                data = json.loads(response.data)
                assert data["error_code"] == "discard_failed"

            # 4. Apply with threshold_suggestion outcome note & SQLAlchemy rollback during queue
            manifest = {
                "session_id": "sess-456",
                "camera": {"id": 1, "uuid": "cam-uuid"},
                "config_id": current_cfg_id,
            }
            result = {
                "outcome": "threshold_suggestion",
                "quality": {"matched_bad_count": 5, "matched_normal_count": 5},
            }
            values = {"THRESHOLD_BIAS": 1.5}
            with patch("indi_allsky.asi676mc_calibration.get_completed_result", return_value=(manifest, result, values)):
                with patch("indi_allsky.flask.views._calibration_save_actor", return_value="admin"):
                    with patch("indi_allsky.config.IndiAllSkyConfig.save") as mock_save:
                        with patch("indi_allsky.flask.miscDb.miscDb.setState"):
                            with patch("indi_allsky.flask.models.db.session.commit", side_effect=SQLAlchemyError("DB lock")):
                                response = client.post(
                                    "/indi-allsky/ajax/asi676mc/calibration/apply/sess-456",
                                    json={"confirm_higher_population": True},
                                )
                                assert response.status_code == 200
                                data = json.loads(response.data)
                                assert data["reload_queued"] is False
                                assert "recommended detection settings" in data["success-message"]

            # 5. Apply with ConfigSaveException -> 400 configuration_save_failed
            with patch("indi_allsky.asi676mc_calibration.get_completed_result", return_value=(manifest, result, values)):
                with patch("indi_allsky.config.IndiAllSkyConfig.save", side_effect=ConfigSaveException("Save error")):
                    response = client.post(
                        "/indi-allsky/ajax/asi676mc/calibration/apply/sess-456",
                        json={"confirm_higher_population": True},
                    )
                    assert response.status_code == 400
                    data = json.loads(response.data)
                    assert data["error_code"] == "configuration_save_failed"

            # 6. Apply with ValueError during normalization -> 400 incompatible_settings
            with patch("indi_allsky.asi676mc_calibration.get_completed_result", return_value=(manifest, result, values)):
                with patch("indi_allsky.asi676mc.normalize_settings", side_effect=ValueError("Bad threshold")):
                    response = client.post(
                        "/indi-allsky/ajax/asi676mc/calibration/apply/sess-456",
                        json={"confirm_higher_population": True},
                    )
                    assert response.status_code == 400
                    data = json.loads(response.data)
                    assert data["error_code"] == "incompatible_settings"
