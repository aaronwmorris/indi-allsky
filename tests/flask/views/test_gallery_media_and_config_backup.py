import io
import json
from pathlib import Path
from datetime import datetime, date
from unittest.mock import patch, MagicMock
import pytest

from indi_allsky.flask import db
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbConfigTable,
)
from indi_allsky.flask.views import (
    ConfigDownloadView,
    AjaxConfigRestoreView,
    AjaxGalleryViewerView,
    AjaxVideoViewerView,
    AjaxMiniVideoViewerView,
)


def test_config_backup_view_redact_and_dict_merge(flask_app, system_db):
    client = flask_app.test_client()

    with flask_app.app_context():
        cfg_entry = IndiAllSkyDbConfigTable(
            id=1,
            level="1.0.0",
            data={
                "LOCATION_LATITUDE": 45.123456,
                "LOCATION_LONGITUDE": -75.654321,
                "YOUTUBE": {"API_KEY": "secret_key"},
            },
        )
        db.session.merge(cfg_entry)
        db.session.commit()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        # 1. Redact=True download
        res = client.get("/indi-allsky/config/download?id=1&redact=1")
        assert res.status_code == 200
        assert res.headers["Content-Type"] == "application/octet-stream"
        assert "attachment" in res.headers["Content-Disposition"]
        data = json.loads(res.data.decode())
        assert data["LOCATION_LATITUDE"] == 45.0
        assert data["LOCATION_LONGITUDE"] == -76.0

        # 2. dict_merge conflict branch
        v = ConfigDownloadView()
        with pytest.raises(Exception, match="Dictionary conflict"):
            v.dict_merge({"key": "string_value"}, {"key": {"nested": "dict_value"}})


def test_ajax_config_restore_validation_and_permissions(flask_app, system_db):
    client = flask_app.test_client()

    mock_non_admin = MagicMock()
    mock_non_admin.is_admin = False

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        # 1. Non-admin user -> 400
        with patch("indi_allsky.flask.views.current_user", mock_non_admin):
            res_perm = client.post("/indi-allsky/ajax/config/restore", data={})
            assert res_perm.status_code == 400

        # 2. Admin user validation error -> 400
        mock_admin = MagicMock()
        mock_admin.is_admin = True
        with patch("indi_allsky.flask.views.current_user", mock_admin):
            res_val = client.post("/indi-allsky/ajax/config/restore", data={})
            assert res_val.status_code == 400


def test_ajax_gallery_and_video_viewers_nonlocal_and_cascades(flask_app, system_db):
    client = flask_app.test_client()

    with flask_app.app_context():
        cam = IndiAllSkyDbCameraTable.query.get(1)
        cam.web_nonlocal_images = True
        cam.web_local_images_admin = True
        db.session.commit()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        # 1. AjaxGalleryViewerView with nonlocal network failure & empty sub-selections
        with patch.object(AjaxGalleryViewerView, "verify_admin_network", return_value=False):
            # year only, where getDays returns empty
            mock_fv1 = MagicMock()
            mock_fv1.getMonths.return_value = ((9, "Sep"),)
            mock_fv1.getDays.return_value = ()
            with patch("indi_allsky.flask.views.IndiAllskyGalleryViewer", return_value=mock_fv1):
                res_g1 = client.post(
                    "/indi-allsky/ajax/gallery",
                    json={"CAMERA_ID": 1, "YEAR_SELECT": 2026, "MONTH_SELECT": 0, "DAY_SELECT": 0},
                )
                assert res_g1.status_code == 200
                assert res_g1.get_json()["DAY_SELECT"] == []

            # year + month + day, where getHours returns empty
            mock_fv2 = MagicMock()
            mock_fv2.getHours.return_value = ()
            with patch("indi_allsky.flask.views.IndiAllskyGalleryViewer", return_value=mock_fv2):
                res_g2 = client.post(
                    "/indi-allsky/ajax/gallery",
                    json={"CAMERA_ID": 1, "YEAR_SELECT": 2026, "MONTH_SELECT": 9, "DAY_SELECT": 20},
                )
                assert res_g2.status_code == 200
                assert res_g2.get_json()["HOUR_SELECT"] == []

        # 2. AjaxVideoViewerView with nonlocal network failure
        with patch.object(AjaxVideoViewerView, "verify_admin_network", return_value=False):
            res_v = client.post(
                "/indi-allsky/ajax/videoviewer",
                json={"CAMERA_ID": 1, "YEAR_SELECT": 2026, "MONTH_SELECT": 0, "TIMEOFDAY_SELECT": "night"},
            )
            assert res_v.status_code == 200

        # 3. AjaxMiniVideoViewerView with nonlocal network failure
        with patch.object(AjaxMiniVideoViewerView, "verify_admin_network", return_value=False):
            res_mv = client.post(
                "/indi-allsky/ajax/minivideoviewer",
                json={"CAMERA_ID": 1, "YEAR_SELECT": 2026, "MONTH_SELECT": 9},
            )
            assert res_mv.status_code == 200
