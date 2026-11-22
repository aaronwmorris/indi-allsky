import io
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import pytest

from indi_allsky.flask import db
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbPanoramaImageTable,
)
from indi_allsky.flask.views import (
    JsonPanoramaLoopView,
    ConfigView,
    AjaxImageViewerView,
)


def test_json_panorama_loop_view_dimensions_and_reference(flask_app, system_db, tmp_path):
    client = flask_app.test_client()

    t_now = datetime(2026, 9, 21, 12, 0, 0)
    pano_file1 = tmp_path / "pano1.jpg"
    pano_file1.write_bytes(b"PANO_BYTES_1")

    pano_file2 = tmp_path / "pano2.jpg"
    pano_file2.write_bytes(b"PANO_BYTES_2")

    with flask_app.app_context():
        p1 = IndiAllSkyDbPanoramaImageTable(
            camera_id=1,
            filename=str(pano_file1),
            exposure=1.0,
            gain=100.0,
            createDate=t_now - timedelta(minutes=2),
            dayDate=t_now.date(),
            width=2000,
            height=500,
            exclude=False,
        )
        p2 = IndiAllSkyDbPanoramaImageTable(
            camera_id=1,
            filename=str(pano_file2),
            exposure=1.0,
            gain=100.0,
            createDate=t_now - timedelta(minutes=1),
            dayDate=t_now.date(),
            width=1000,  # dimension mismatch
            height=500,
            exclude=False,
        )
        db.session.add_all([p1, p2])
        db.session.commit()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        res = client.get(
            f"/indi-allsky/js/looppanorama?camera_id=1&source_width=2000&source_height=500&limit_s=600&timestamp={int(t_now.timestamp())}"
        )
        assert res.status_code == 200
        data = res.get_json()
        assert "image_list" in data


def test_config_view_dew_heater_all_thresholds(flask_app, system_db):
    with flask_app.test_request_context("/indi-allsky/config?camera_id=1"):
        v = ConfigView(template_name="config.html")

        # Mock latest_image_entry with sensors data
        mock_img = MagicMock()
        mock_img.temp = 10.0
        v.latest_image_entry = mock_img

        from indi_allsky.config import IndiAllSkyConfigBase
        base_cfg = dict(IndiAllSkyConfigBase._base_config)
        base_cfg.update({
            "DEW_HEATER": {
                "ENABLE": True,
                "MODE": "auto",
                "TEMP_USER_VAR_SLOT": "temp",
                "DEWPOINT_USER_VAR_SLOT": "dewpoint",
                "THOLD_DIFF_HIGH": 1,
                "THOLD_DIFF_MED": 3,
                "THOLD_DIFF_LOW": 5,
                "LEVEL_HIGH": 100,
                "LEVEL_MED": 60,
                "LEVEL_LOW": 30,
                "LEVEL_DEFAULT": 10,
                "MANUAL_TARGET": 0.0,
            },
            "FAN": {
                "ENABLE": True,
                "TEMP_USER_VAR_SLOT": "temp",
                "TARGET": 30.0,
                "THOLD_DIFF_HIGH": 10,
                "THOLD_DIFF_MED": 5,
                "THOLD_DIFF_LOW": 0,
                "LEVEL_HIGH": 100,
                "LEVEL_MED": 60,
                "LEVEL_LOW": 30,
                "LEVEL_DEFAULT": 10,
            },
        })
        v.indi_allsky_config = base_cfg

        # 1. Auto mode: dh_temp_delta = dh_temp - dh_dewpoint
        # High: dh_temp_delta = 0.5 (<= 1)
        mock_img.data = {"temp": 10.5, "dewpoint": 10.0}
        ctx_high = v.get_context()
        assert "High" in ctx_high["dh_status_str"]

        # Medium: dh_temp_delta = 2.0 (<= 3)
        mock_img.data = {"temp": 12.0, "dewpoint": 10.0}
        ctx_med = v.get_context()
        assert "Medium" in ctx_med["dh_status_str"]

        # Low: dh_temp_delta = 4.0 (<= 5)
        mock_img.data = {"temp": 14.0, "dewpoint": 10.0}
        ctx_low = v.get_context()
        assert "Low" in ctx_low["dh_status_str"]

        # Default: dh_temp_delta = 8.0 (> 5)
        mock_img.data = {"temp": 18.0, "dewpoint": 10.0}
        ctx_def = v.get_context()
        assert "Default" in ctx_def["dh_status_str"]

        # Auto without dewpoint available -> n/a
        mock_img.data = {"temp": 18.0}
        ctx_na = v.get_context()
        assert ctx_na["dh_status_str"] == "n/a"

        # 2. dh_manual_target > 0 branches: high, med, low, default, None
        v.indi_allsky_config["DEW_HEATER"]["MANUAL_TARGET"] = 15.0

        # High: dh_temp_delta = 0.0 (<= 1)
        mock_img.data = {"temp": 15.0}
        ctx_m_high = v.get_context()
        assert "High" in ctx_m_high["dh_status_str"]

        # Med: dh_temp_delta = 2.0 (<= 3)
        mock_img.data = {"temp": 17.0}
        ctx_m_med = v.get_context()
        assert "Medium" in ctx_m_med["dh_status_str"]

        # Low: dh_temp_delta = 4.0 (<= 5)
        mock_img.data = {"temp": 19.0}
        ctx_m_low = v.get_context()
        assert "Low" in ctx_m_low["dh_status_str"]

        # Default: dh_temp_delta = 25.0 (> 5)
        mock_img.data = {"temp": 25.0}
        ctx_m_def = v.get_context()
        assert "Default" in ctx_m_def["dh_status_str"]

        # Manual without temperature -> n/a
        mock_img.data = {}
        ctx_m_na = v.get_context()
        assert ctx_m_na["dh_status_str"] == "n/a"

        # 3. Fan branches: high (> 10), med (> 5), low (> 0), default (<= 0), None
        # Fan high: fan_temp_delta = 15.0 (> 10)
        mock_img.data = {"temp": 45.0}
        ctx_f_high = v.get_context()
        assert "High" in ctx_f_high["fan_status_str"]

        # Fan med: fan_temp_delta = 8.0 (> 5)
        mock_img.data = {"temp": 38.0}
        ctx_f_med = v.get_context()
        assert "Medium" in ctx_f_med["fan_status_str"]

        # Fan low: fan_temp_delta = 3.0 (> 0)
        mock_img.data = {"temp": 33.0}
        ctx_f_low = v.get_context()
        assert "Low" in ctx_f_low["fan_status_str"]

        # Fan default: fan_temp_delta = -5.0 (<= 0)
        mock_img.data = {"temp": 25.0}
        ctx_f_def = v.get_context()
        assert "Default" in ctx_f_def["fan_status_str"]

        # Fan none
        mock_img.data = {}
        ctx_f_na = v.get_context()
        assert ctx_f_na["fan_status_str"] == "n/a"


def test_ajax_image_viewer_year_and_fallback_cascades(flask_app, system_db):
    client = flask_app.test_client()

    now = datetime(2026, 9, 21, 12, 0, 0)
    with flask_app.app_context():
        img = IndiAllSkyDbImageTable(
            camera_id=1,
            filename="/tmp/viewer_img.jpg",
            exposure=1.0,
            gain=100.0,
            adu=100.0,
            createDate=now,
            createDate_year=2026,
            createDate_month=9,
            createDate_day=21,
            createDate_hour=12,
            dayDate=now.date(),
        )
        db.session.add(img)
        db.session.commit()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        # 1. FORM_YEAR only (lines 5000-5022)
        res_year = client.post(
            "/indi-allsky/ajax/imageviewer",
            json={"CAMERA_ID": 1, "FORM_YEAR": "2026", "FORM_MONTH": "", "FORM_DAY": "", "FORM_HOUR": ""}
        )
        assert res_year.status_code == 200
        assert "IMAGE_DATA" in res_year.get_json()

        # 2. No date selection fallback cascade (lines 5025-5052)
        res_fallback = client.post(
            "/indi-allsky/ajax/imageviewer",
            json={"CAMERA_ID": 1, "FORM_YEAR": "", "FORM_MONTH": "", "FORM_DAY": "", "FORM_HOUR": ""}
        )
        assert res_fallback.status_code == 200
        assert "IMAGE_DATA" in res_fallback.get_json()
