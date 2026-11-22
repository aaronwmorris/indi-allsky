import io
import json
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import numpy as np
import pytest
import simple_websocket
from cryptography.fernet import InvalidToken
from PIL import UnidentifiedImageError

from indi_allsky import constants
from indi_allsky.flask import db
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbFitsImageTable,
    IndiAllSkyDbPanoramaImageTable,
    IndiAllSkyDbVideoTable,
    IndiAllSkyDbMiniVideoTable,
    IndiAllSkyDbStarTrailsVideoTable,
    IndiAllSkyDbPanoramaVideoTable,
    IndiAllSkyDbKeogramTable,
    IndiAllSkyDbStarTrailsTable,
    IndiAllSkyDbRawImageTable,
    IndiAllSkyDbTleDataTable,
    IndiAllSkyDbConfigTable,
)
from indi_allsky.flask.views import (
    ConfigView,
    AjaxConfigView,
    MiniTimelapseGeneratorView,
    TimelapseVideoView,
    MiniTimelapseVideoView,
    StartrailVideoView,
    PanoramaVideoView,
    TimelapseImageView,
    PanoramaImageView,
    KeogramImageView,
    StartrailImageView,
    RawImageView,
    ESP32ImageView,
    WsControlView,
    AjaxAstroPanelView,
)


def test_manifest_and_images_backup_routes(flask_app, system_db, tmp_path):
    client = flask_app.test_client()

    # 1. /manifest.json
    res_manifest = client.get("/indi-allsky/manifest.json")
    assert res_manifest.status_code == 200
    assert res_manifest.headers["Content-Type"] == "application/manifest+json"
    manifest_data = res_manifest.get_json()
    assert manifest_data["name"] == "indi-allsky"
    assert len(manifest_data["icons"]) >= 2

    # 2. /images/<path>
    img_folder = tmp_path / "images"
    img_folder.mkdir(parents=True, exist_ok=True)
    test_img = img_folder / "test.jpg"
    test_img.write_bytes(b"TEST_IMAGE_BYTES")

    with patch.dict(flask_app.config, {"INDI_ALLSKY_IMAGE_FOLDER": str(img_folder)}):
        res_img = client.get("/indi-allsky/images/test.jpg")
        assert res_img.status_code == 200
        assert res_img.data == b"TEST_IMAGE_BYTES"


def test_esp32_image_view_branches(flask_app, system_db, tmp_path):
    client = flask_app.test_client()

    img_folder = tmp_path / "images"
    img_folder.mkdir(parents=True, exist_ok=True)

    # Create dummy jpg image
    dummy_jpg = img_folder / "circular_display.jpg"
    import cv2
    img_arr = np.zeros((100, 100, 3), dtype=np.uint8)
    _, encoded = cv2.imencode(".jpg", img_arr)
    dummy_jpg.write_bytes(encoded.tobytes())

    cfg = {
        "IMAGE_FOLDER": str(img_folder),
        "IMAGE_FILE_TYPE": "jpg",
        "IMAGE_FILE_COMPRESSION": {"jpg": 90},
        "CIRCULAR_DISPLAY": {"ENABLE": True},
    }

    def mock_cam_setup(self, camera_id=0):
        self.indi_allsky_config = cfg
        self.camera = system_db

    # 1. Circular display enabled with valid/invalid sizes
    with patch.object(ESP32ImageView, "cameraSetup", mock_cam_setup), \
         patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        res_default = client.get("/indi-allsky/allsky_esp32?camera_id=1&size=240")
        assert res_default.status_code == 200
        assert res_default.mimetype == "image/jpeg"

        # Invalid size string -> defaults to 240
        res_invalid_size = client.get("/indi-allsky/allsky_esp32?camera_id=1&size=invalid")
        assert res_invalid_size.status_code == 200

        # Size not in VALID_SIZES -> defaults to 240
        res_unsupported_size = client.get("/indi-allsky/allsky_esp32?camera_id=1&size=999")
        assert res_unsupported_size.status_code == 200

        # Invalid camera_id -> uses latest camera
        with patch.object(ESP32ImageView, "getLatestCamera", return_value=system_db):
            res_no_cam = client.get("/indi-allsky/allsky_esp32?camera_id=invalid")
            assert res_no_cam.status_code == 200

    # 2. _readImage error paths
    v_esp = ESP32ImageView()
    corrupt_jpg = img_folder / "corrupt.jpg"
    corrupt_jpg.write_bytes(b"NOT_A_JPEG")
    assert v_esp._readImage(corrupt_jpg) is None

    missing_png = img_folder / "missing.png"
    assert v_esp._readImage(missing_png) is None

    corrupt_fits = img_folder / "corrupt.fit"
    corrupt_fits.write_bytes(b"CORRUPT_FITS_DATA")
    assert v_esp._readImage(corrupt_fits) is None

    corrupt_webp = img_folder / "corrupt.webp"
    corrupt_webp.write_bytes(b"NOT_A_VALID_IMAGE_FORMAT")
    assert v_esp._readImage(corrupt_webp) is None


def test_ws_control_systemd_methods_and_auth(flask_app, system_db):
    view = WsControlView()

    # 1. rebootSystemd
    mock_bus = MagicMock()
    mock_manager = MagicMock()
    mock_systemd1 = MagicMock()
    mock_bus.get_object.return_value = mock_systemd1
    with patch("dbus.SystemBus", return_value=mock_bus), \
         patch("dbus.Interface", return_value=mock_manager):
        view.rebootSystemd()
        mock_manager.Reboot.assert_called_once_with(False)

        view.poweroffSystemd()
        mock_manager.PowerOff.assert_called_once_with(False)

    # 2. Authorization Bearer key match
    mock_ws = MagicMock()
    mock_ws.receive.side_effect = simple_websocket.ConnectionClosed(1000, "Done")

    with flask_app.test_request_context(
        "/indi-allsky/ws/control",
        headers={"Authorization": "Bearer valid_ws_key"}
    ):
        with patch.dict(flask_app.config, {"WEBSOCKET_API_KEY": "valid_ws_key"}), \
             patch("simple_websocket.Server.accept", return_value=mock_ws), \
             patch("indi_allsky.events.event_manager"), \
             patch("indi_allsky.flask.views.current_user") as mock_user:
            mock_user.is_authenticated = False
            res = view.dispatch_request()
            assert res == ""


def test_mini_timelapse_generator_dimensions_and_panorama_context(flask_app, system_db, tmp_path):
    # 1. _getStandardVideoDimensions
    mock_img = MagicMock()
    mock_img.width = 1920
    mock_img.height = 1080

    # None scale
    assert MiniTimelapseGeneratorView._getStandardVideoDimensions(mock_img, None) == (1920, 1080)

    # Invalid dimension on image entry
    mock_bad_img = MagicMock()
    mock_bad_img.width = 0
    mock_bad_img.height = 0
    assert MiniTimelapseGeneratorView._getStandardVideoDimensions(mock_bad_img, None) == (None, None)

    mock_bad_img.width = "not_an_int"
    assert MiniTimelapseGeneratorView._getStandardVideoDimensions(mock_bad_img, None) == (None, None)

    # Height match -1:720
    assert MiniTimelapseGeneratorView._getStandardVideoDimensions(mock_img, "-1:720") == (1280, 720)

    # Height match with invalid height < 1
    assert MiniTimelapseGeneratorView._getStandardVideoDimensions(mock_img, "-1:0") == (None, None)

    # Percentage match iw*.5:ih*.5
    assert MiniTimelapseGeneratorView._getStandardVideoDimensions(mock_img, "iw*.5:ih*.5") == (960, 540)

    # Percentage match iw*.5:-2
    assert MiniTimelapseGeneratorView._getStandardVideoDimensions(mock_img, "iw*.5:-2") == (960, 540)

    # Invalid vf_scale pattern
    assert MiniTimelapseGeneratorView._getStandardVideoDimensions(mock_img, "scale=invalid") == (None, None)

    # 2. _getPanoramaContext
    with flask_app.app_context():
        cam = db.session.get(IndiAllSkyDbCameraTable, 1)

        t_now = datetime(2026, 9, 21, 12, 0, 0)
        t_prev = t_now - timedelta(minutes=5)
        t_next = t_now + timedelta(minutes=5)

        img_curr = IndiAllSkyDbImageTable(camera_id=1, filename="/tmp/curr.jpg", exposure=1.0, gain=100.0, adu=100.0, createDate=t_now, dayDate=t_now.date())
        img_prev = IndiAllSkyDbImageTable(camera_id=1, filename="/tmp/prev.jpg", exposure=1.0, gain=100.0, adu=100.0, createDate=t_prev, dayDate=t_prev.date())
        img_next = IndiAllSkyDbImageTable(camera_id=1, filename="/tmp/next.jpg", exposure=1.0, gain=100.0, adu=100.0, createDate=t_next, dayDate=t_next.date())

        pano_prev = IndiAllSkyDbPanoramaImageTable(camera_id=1, filename="/tmp/pano_prev.jpg", exposure=1.0, gain=100.0, createDate=t_prev, dayDate=t_prev.date(), exclude=False)
        pano_next = IndiAllSkyDbPanoramaImageTable(camera_id=1, filename="/tmp/pano_next.jpg", exposure=1.0, gain=100.0, createDate=t_next, dayDate=t_next.date(), exclude=False)

        db.session.add_all([img_curr, img_prev, img_next, pano_prev, pano_next])
        db.session.commit()

        with flask_app.test_request_context("/indi-allsky/mini_timelapse/generate?image_id=1&camera_id=1"):
            view = MiniTimelapseGeneratorView(template_name="mini_generate.html")
            view.camera = cam
            view.web_nonlocal_images = False
            view.s3_prefix = ""

            # FISH2PANO disabled
            view.indi_allsky_config = {"FISH2PANO": {"ENABLE": False}}
            enabled, p_data, sugg = view._getPanoramaContext(img_curr)
            assert enabled is False
            assert p_data["available"] is False
            assert len(sugg) == 0

            # FISH2PANO enabled, no current pano but previous and next exist
            view.indi_allsky_config = {
                "FISH2PANO": {"ENABLE": True, "DIAMETER": 1000},
                "LENS_OFFSET_X": 0,
                "LENS_OFFSET_Y": 0,
            }
            enabled, p_data, sugg = view._getPanoramaContext(img_curr)
            assert enabled is True
            assert p_data["available"] is False
            assert len(sugg) == 2
            labels = [s["label"] for s in sugg]
            assert "Previous panorama" in labels
            assert "Next panorama" in labels

            # Exact matching panorama with circle_clipped fallback calculation
            pano_file = tmp_path / "pano_curr.jpg"
            pano_file.write_bytes(b"PANO_DATA")
            pano_curr = IndiAllSkyDbPanoramaImageTable(
                camera_id=1,
                filename=str(pano_file),
                exposure=1.0,
                gain=100.0,
                createDate=t_now,
                dayDate=t_now.date(),
                width=2000,
                height=500,
                exclude=False,
                data={},
            )
            db.session.add(pano_curr)
            db.session.commit()

            enabled, p_data, sugg = view._getPanoramaContext(img_curr)
            assert enabled is True
            assert p_data["available"] is True
            assert p_data["id"] == pano_curr.id


def test_timelapse_and_image_views_nonlocal_branches(flask_app, system_db):
    now = datetime(2026, 9, 21, 12, 0, 0)
    with flask_app.app_context():
        vid = IndiAllSkyDbVideoTable(camera_id=1, filename="/tmp/vid.mp4", remote_url="https://s3.example.org/vid.mp4", createDate=now, dayDate=now.date(), night=True)
        mini_vid = IndiAllSkyDbMiniVideoTable(camera_id=1, filename="/tmp/mini.mp4", remote_url="https://s3.example.org/mini.mp4", targetDate=now, startDate=now, endDate=now, note="test", createDate=now, dayDate=now.date(), night=False, data={"source": "standard"})
        st_vid = IndiAllSkyDbStarTrailsVideoTable(camera_id=1, filename="/tmp/st.mp4", remote_url="https://s3.example.org/st.mp4", createDate=now, dayDate=now.date(), night=True)
        pano_vid = IndiAllSkyDbPanoramaVideoTable(camera_id=1, filename="/tmp/pano.mp4", remote_url="https://s3.example.org/pano.mp4", createDate=now, dayDate=now.date(), night=False)

        img_pano = IndiAllSkyDbPanoramaImageTable(camera_id=1, filename="/tmp/pano.jpg", exposure=1.0, gain=100.0, remote_url="https://s3.example.org/p.jpg", createDate=now, dayDate=now.date(), night=False)
        img_keo = IndiAllSkyDbKeogramTable(camera_id=1, filename="/tmp/keo.jpg", remote_url="https://s3.example.org/k.jpg", createDate=now, dayDate=now.date(), night=True)
        img_st = IndiAllSkyDbStarTrailsTable(camera_id=1, filename="/tmp/st.jpg", remote_url="https://s3.example.org/s.jpg", createDate=now, dayDate=now.date(), night=True)
        img_raw = IndiAllSkyDbRawImageTable(camera_id=1, filename="/tmp/raw.jpg", exposure=1.0, gain=100.0, remote_url="https://s3.example.org/r.jpg", createDate=now, dayDate=now.date(), night=False)

        db.session.add_all([vid, mini_vid, st_vid, pano_vid, img_pano, img_keo, img_st, img_raw])
        db.session.commit()

        vid_id = vid.id
        mini_id = mini_vid.id
        st_id = st_vid.id
        pano_id = pano_vid.id
        pano_img_id = img_pano.id
        keo_img_id = img_keo.id
        st_img_id = img_st.id
        raw_img_id = img_raw.id

    with flask_app.test_request_context(f"/indi-allsky/timelapse/video?id={vid_id}&camera_id=1"):
        v = TimelapseVideoView(template_name="timelapse_video.html")
        v.web_nonlocal_images = True
        v.web_local_images_admin = False
        ctx = v.get_context()
        assert ctx["timeofday"] == "Night"
        assert "s3.example.org" in ctx["video_url"]

    with flask_app.test_request_context(f"/indi-allsky/mini_timelapse/video?id={mini_id}&camera_id=1"):
        v_mini = MiniTimelapseVideoView(template_name="mini_timelapse_video.html")
        v_mini.web_nonlocal_images = True
        v_mini.web_local_images_admin = False
        ctx_mini = v_mini.get_context()
        assert ctx_mini["timeofday"] == "Day"
        assert ctx_mini["video_source"] == "standard"

    with flask_app.test_request_context(f"/indi-allsky/startrail/video?id={st_id}&camera_id=1"):
        v_st = StartrailVideoView(template_name="startrail_video.html")
        v_st.web_nonlocal_images = True
        v_st.web_local_images_admin = False
        ctx_st = v_st.get_context()
        assert ctx_st["timeofday"] == "Night"

    with flask_app.test_request_context(f"/indi-allsky/panorama/video?id={pano_id}&camera_id=1"):
        v_pano = PanoramaVideoView(template_name="panorama_video.html")
        v_pano.web_nonlocal_images = True
        v_pano.web_local_images_admin = False
        ctx_pano = v_pano.get_context()
        assert ctx_pano["timeofday"] == "Day"

    # Image views with nonlocal
    for view_cls, img_id, tod in [
        (PanoramaImageView, pano_img_id, "Day"),
        (KeogramImageView, keo_img_id, "Night"),
        (StartrailImageView, st_img_id, "Night"),
        (RawImageView, raw_img_id, "Day"),
    ]:
        with flask_app.test_request_context(f"/indi-allsky/test?id={img_id}&camera_id=1"):
            v_img = view_cls(template_name="test.html")
            v_img.web_nonlocal_images = True
            v_img.web_local_images_admin = False
            ctx_i = v_img.get_context()
            assert ctx_i["timeofday"] == tod
            assert "s3.example.org" in ctx_i["image_url"]


def test_ajax_astropanel_satellite_visual_pass(flask_app, system_db):
    client = flask_app.test_client()

    with flask_app.app_context():
        # Add ISS satellite TLE entry
        sat = IndiAllSkyDbTleDataTable(
            title="ISS (ZARYA)",
            group=constants.SATELLITE_VISUAL,
            line1="1 25544U 98067A   26264.51782528 -.00002182  00000-0 -11606-4 0  2927",
            line2="2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537",
        )
        db.session.add(sat)
        db.session.commit()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        res = client.get("/indi-allsky/ajax/astropanel?camera_id=1")
        assert res.status_code == 200
        data = res.get_json()
        assert "satellite_list" in data
        assert len(data["satellite_list"]) >= 1
        assert data["satellite_list"][0]["name"] == "ISS (ZARYA)"


def test_config_view_youtube_exceptions_and_fitsheaders(flask_app, system_db):
    with flask_app.test_request_context("/indi-allsky/config?camera_id=1"):
        v_cfg = ConfigView(template_name="config.html")

        # 1. InvalidToken & ValueError from getState('YOUTUBE_CREDENTIALS')
        mock_misc = MagicMock()
        def mock_state_fn(k):
            if k == "WATCHDOG":
                return 1234567890
            if k == "YOUTUBE_CREDENTIALS":
                raise InvalidToken()
            raise KeyError()

        mock_misc.getState.side_effect = mock_state_fn
        v_cfg._miscDb = mock_misc
        ctx1 = v_cfg.get_context()
        assert ctx1["form_config"].data["YOUTUBE__CREDS_STORED"] is False

        def mock_state_val_err(k):
            if k == "WATCHDOG":
                return 1234567890
            if k == "YOUTUBE_CREDENTIALS":
                raise ValueError("Corrupt token")
            raise KeyError()

        mock_misc.getState.side_effect = mock_state_val_err
        ctx2 = v_cfg.get_context()
        assert ctx2["form_config"].data["YOUTUBE__CREDS_STORED"] is False

        # 2. FITS headers with empty list (IndexError branch)
        v_cfg.indi_allsky_config["FITSHEADERS"] = []
        ctx3 = v_cfg.get_context()
        assert ctx3["form_config"].data["FITSHEADERS__0__KEY"] == "INSTRUME"
        assert ctx3["form_config"].data["FITSHEADERS__1__KEY"] == "OBSERVER"
