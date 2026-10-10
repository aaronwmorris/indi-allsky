import io
from pathlib import Path
from datetime import datetime, date
from unittest.mock import patch, MagicMock
import pytest

from indi_allsky.flask import db
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbPanoramaImageTable,
)
from indi_allsky.flask.views import (
    AjaxFocusControllerView,
    AjaxTimelapseGeneratorView,
)
from indi_allsky.devices.exceptions import DeviceControlException


def test_ajax_focus_controller_permissions_and_errors(flask_app, system_db):
    client = flask_app.test_client()

    mock_admin = MagicMock()
    mock_admin.is_admin = True

    mock_non_admin = MagicMock()
    mock_non_admin.is_admin = False

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        # 1. Non-admin user -> 400
        with patch("indi_allsky.flask.views.current_user", mock_non_admin):
            res_perm = client.post("/indi-allsky/ajax/focuscontroller", json={})
            assert res_perm.status_code == 400
            assert "permission" in res_perm.get_json()["focuser_error"][0]

        # 2. Validation failure -> 400
        with patch("indi_allsky.flask.views.current_user", mock_admin):
            res_val = client.post(
                "/indi-allsky/ajax/focuscontroller",
                json={"DIRECTION": "invalid", "STEP_DEGREES": -10},
            )
            assert res_val.status_code == 400

            # 3. Admin network check failure -> 400
            with patch.object(AjaxFocusControllerView, "verify_admin_network", return_value=False):
                res_net = client.post(
                    "/indi-allsky/ajax/focuscontroller",
                    json={"DIRECTION": "in", "STEP_DEGREES": 24},
                )
                assert res_net.status_code == 400
                assert "Request not from admin network" in res_net.get_json()["focuser_error"][0]

            # 4. Error initializing focuser (SystemError, ValueError, DeviceControlException)
            with patch.object(AjaxFocusControllerView, "verify_admin_network", return_value=True):
                with patch("indi_allsky.focuser.IndiAllSkyFocuserInterface", side_effect=SystemError("SysErr")):
                    res_sys = client.post("/indi-allsky/ajax/focuscontroller", json={"DIRECTION": "in", "STEP_DEGREES": 24})
                    assert res_sys.status_code == 400
                    assert "Error initializing focuser: SysErr" in res_sys.get_json()["focuser_error"][0]

                with patch("indi_allsky.focuser.IndiAllSkyFocuserInterface", side_effect=ValueError("ValErr")):
                    res_val_err = client.post("/indi-allsky/ajax/focuscontroller", json={"DIRECTION": "in", "STEP_DEGREES": 24})
                    assert res_val_err.status_code == 400
                    assert "Error initializing focuser: ValErr" in res_val_err.get_json()["focuser_error"][0]

                with patch("indi_allsky.focuser.IndiAllSkyFocuserInterface", side_effect=DeviceControlException("DevErr")):
                    res_dev_err = client.post("/indi-allsky/ajax/focuscontroller", json={"DIRECTION": "in", "STEP_DEGREES": 24})
                    assert res_dev_err.status_code == 400
                    assert "Error initializing focuser: DevErr" in res_dev_err.get_json()["focuser_error"][0]

                # 5. Error moving focuser (DeviceControlException)
                mock_focuser = MagicMock()
                mock_focuser.move.side_effect = DeviceControlException("MoveErr")
                with patch("indi_allsky.focuser.IndiAllSkyFocuserInterface", return_value=mock_focuser):
                    res_move_err = client.post("/indi-allsky/ajax/focuscontroller", json={"DIRECTION": "in", "STEP_DEGREES": 24})
                    assert res_move_err.status_code == 400
                    assert "Error moving focuser: MoveErr" in res_move_err.get_json()["focuser_error"][0]

                # 6. Success
                mock_focuser_ok = MagicMock()
                mock_focuser_ok.move.return_value = 42
                with patch("indi_allsky.focuser.IndiAllSkyFocuserInterface", return_value=mock_focuser_ok):
                    res_ok = client.post("/indi-allsky/ajax/focuscontroller", json={"DIRECTION": "in", "STEP_DEGREES": 24})
                    assert res_ok.status_code == 200
                    assert res_ok.get_json()["steps"] == 42
                    mock_focuser_ok.deinit.assert_called_once()


def test_ajax_timelapse_generator_additional_actions(flask_app, system_db):
    client = flask_app.test_client()

    t_day = date(2026, 9, 20)
    with flask_app.app_context():
        img = IndiAllSkyDbImageTable(
            camera_id=1,
            filename="/tmp/timelapse_test_img2.jpg",
            exposure=1.0,
            gain=100.0,
            adu=100.0,
            createDate=datetime(2026, 9, 20, 22, 0, 0),
            dayDate=t_day,
            night=True,
        )
        pano = IndiAllSkyDbPanoramaImageTable(
            camera_id=1,
            filename="/tmp/timelapse_test_pano2.jpg",
            exposure=1.0,
            gain=100.0,
            createDate=datetime(2026, 9, 20, 22, 0, 0),
            dayDate=t_day,
            width=2000,
            height=500,
        )
        db.session.add_all([img, pano])
        db.session.commit()

    mock_admin = MagicMock()
    mock_admin.is_admin = True

    from indi_allsky.config import IndiAllSkyConfig, IndiAllSkyConfigBase

    cfg_dis = dict(IndiAllSkyConfigBase._base_config)
    cfg_dis["FISH2PANO"] = {"ENABLE": False}

    cfg_en = dict(IndiAllSkyConfigBase._base_config)
    cfg_en["FISH2PANO"] = {"ENABLE": True}

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        with patch("indi_allsky.flask.views.current_user", mock_admin):
            with patch.object(AjaxTimelapseGeneratorView, "verify_admin_network", return_value=True):
                # 1. generate_panorama_video disabled
                with patch.object(IndiAllSkyConfig, "config", cfg_dis):
                    res_p_dis = client.post(
                        "/indi-allsky/ajax/generate",
                        json={"CAMERA_ID": 1, "ACTION_SELECT": "generate_panorama_video", "DAY_SELECT": "2026-09-20_night"},
                    )
                    assert res_p_dis.status_code == 200
                    assert "Panoramas disabled" in res_p_dis.get_json()["success-message"]

                # 2. generate_panorama_video enabled
                with patch.object(IndiAllSkyConfig, "config", cfg_en):
                    res_p_en = client.post(
                        "/indi-allsky/ajax/generate",
                        json={"CAMERA_ID": 1, "ACTION_SELECT": "generate_panorama_video", "DAY_SELECT": "2026-09-20_night"},
                    )
                    assert res_p_en.status_code == 200
                    assert "Job submitted" in res_p_en.get_json()["success-message"]

                # 3. generate_k_st
                res_kst = client.post(
                    "/indi-allsky/ajax/generate",
                    json={"CAMERA_ID": 1, "ACTION_SELECT": "generate_k_st", "DAY_SELECT": "2026-09-20_night"},
                )
                assert res_kst.status_code == 200
                assert "Job submitted" in res_kst.get_json()["success-message"]

                # 4. upload_endofnight
                res_eon = client.post(
                    "/indi-allsky/ajax/generate",
                    json={"CAMERA_ID": 1, "ACTION_SELECT": "upload_endofnight", "DAY_SELECT": "2026-09-20_night"},
                )
                assert res_eon.status_code == 200
                assert "Job submitted" in res_eon.get_json()["success-message"]

                # 5. delete_images with deleteAsset OSError fallback
                with patch.object(IndiAllSkyDbImageTable, "deleteAsset", side_effect=OSError("Permission denied")):
                    with patch.object(IndiAllSkyDbPanoramaImageTable, "deleteAsset", return_value=None):
                        res_del = client.post(
                            "/indi-allsky/ajax/generate",
                            json={"CAMERA_ID": 1, "ACTION_SELECT": "delete_images", "DAY_SELECT": "2026-09-20_night"},
                        )
                        assert res_del.status_code == 200
                        assert "images deleted" in res_del.get_json()["success-message"]
