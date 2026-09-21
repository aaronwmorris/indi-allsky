from unittest.mock import patch, MagicMock
from pathlib import Path
from datetime import datetime
import pytest

from indi_allsky.flask import db
from indi_allsky.flask.models import IndiAllSkyDbImageTable, IndiAllSkyDbPanoramaImageTable
from indi_allsky.flask.views import (
    AjaxUploadYoutubeView,
    CameraSimulatorView,
    TimelapseImageView,
    AjaxMiniTimelapseGeneratorView,
    AjaxCustomCssView,
    AjaxSelectCameraView,
    AjaxImageExcludeView,
)


def test_youtube_upload_view(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):
        res = client.post("/indi-allsky/ajax/upload_youtube", json={"video_id": 1, "model": "IndiAllSkyDbVideoTable"})
        assert res.status_code in (200, 400, 404)


def test_camera_simulator_and_timelapse_image_view(flask_app, system_db):
    client = flask_app.test_client()

    with flask_app.app_context():
        img = IndiAllSkyDbImageTable(
            camera_id=1,
            filename="/tmp/test_tl.jpg",
            createDate=datetime(2026, 9, 19, 12, 0, 0),
            dayDate=datetime(2026, 9, 19).date(),
            exposure=1.0,
            gain=100.0,
            adu=500,
            night=True,
            width=1000,
            height=1000,
        )
        db.session.add(img)

        pano = IndiAllSkyDbPanoramaImageTable(
            camera_id=1,
            filename="/tmp/test_pano.jpg",
            createDate=datetime(2026, 9, 19, 12, 0, 0),
            dayDate=datetime(2026, 9, 19).date(),
            exposure=1.0,
            gain=100.0,
            night=False,
            width=1000,
            height=1000,
        )
        db.session.add(pano)
        db.session.commit()
        img_id = img.id
        pano_id = pano.id

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        res = client.get("/indi-allsky/camerasimulator")
        assert res.status_code == 200

        with patch("indi_allsky.flask.models.IndiAllSkyDbFileBase.getLocalOrCachedPath", return_value=Path(__file__)):
            res_tl = client.get(f"/indi-allsky/view_image?id={img_id}")
            assert res_tl.status_code == 200

            res_tl_latest = client.get("/indi-allsky/view_image")
            assert res_tl_latest.status_code == 200

            res_pano = client.get(f"/indi-allsky/view_panorama?id={pano_id}")
            assert res_pano.status_code == 200

            # Image not found branch
            res_not_found = client.get("/indi-allsky/view_image?id=99999")
            assert res_not_found.status_code == 200

            # Non-local images branch
            from indi_allsky.flask.base_views import BaseView
            with patch.object(BaseView, "web_nonlocal_images", create=True, new=True), \
                 patch.object(BaseView, "verify_admin_network", return_value=False):
                res_nonlocal = client.get("/indi-allsky/view_image?id=99999")
                assert res_nonlocal.status_code == 200



def test_mini_timelapse_and_custom_css_views(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):
        with patch("subprocess.run") as mock_sub:
            mock_sub.return_value.returncode = 0
            res_css = client.post("/indi-allsky/ajax/custom_css", json={"custom_css": "body { color: red; }"})
            assert res_css.status_code in (200, 500)

        res_cam = client.post("/indi-allsky/ajax/selectcamera", json={"camera_id": 1})
        assert res_cam.status_code in (200, 400)

        res_ex = client.post("/indi-allsky/ajax/image_exclude", json={"image_id": 1, "exclude": True})
        assert res_ex.status_code in (200, 400, 404)

        res_mini = client.post("/indi-allsky/ajax/minigenerate", json={"camera_id": 1})
        assert res_mini.status_code in (200, 400)


def test_file_space_usage_view(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):

        res = client.get("/indi-allsky/filespaceusage")
        assert res.status_code == 200


def test_mini_timelapse_generator_view(flask_app, system_db):
    client = flask_app.test_client()

    with flask_app.app_context():
        img = IndiAllSkyDbImageTable(
            camera_id=1,
            filename="/tmp/test.jpg",
            createDate=datetime(2026, 9, 19, 12, 0, 0),
            dayDate=datetime(2026, 9, 19).date(),
            exposure=1.0,
            gain=100.0,
            adu=500,
            night=False,
            width=1000,
            height=1000,
        )
        db.session.add(img)
        db.session.commit()
        img_id = img.id

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):

        # GET /indi-allsky/minigenerate
        res_get = client.get(f"/indi-allsky/minigenerate?image_id={img_id}")
        assert res_get.status_code == 200

        # POST /indi-allsky/ajax/minigenerate validation failures
        # Missing note
        payload_no_note = {
            "IMAGE_ID": img_id,
            "CAMERA_ID": 1,
            "PRE_SECONDS": 60,
            "POST_SECONDS": 60,
            "FRAMERATE": 10.0,
            "NOTE": "",
        }
        res_no_note = client.post("/indi-allsky/ajax/minigenerate", json=payload_no_note)
        assert res_no_note.status_code == 400

        # Note too long (> 255 chars)
        payload_long_note = dict(payload_no_note, NOTE="a" * 256)
        res_long_note = client.post("/indi-allsky/ajax/minigenerate", json=payload_long_note)
        assert res_long_note.status_code == 400

        # Invalid bitrate format
        payload_bad_bitrate = dict(payload_no_note, NOTE="Valid note", BITRATE="invalid")
        res_bad_bitrate = client.post("/indi-allsky/ajax/minigenerate", json=payload_bad_bitrate)
        assert res_bad_bitrate.status_code == 400

        # Invalid time range
        payload_bad_range = dict(payload_no_note, NOTE="Valid note", PRE_SECONDS=0)
        res_bad_range = client.post("/indi-allsky/ajax/minigenerate", json=payload_bad_range)
        assert res_bad_range.status_code == 400

        # Success case
        payload_valid = dict(payload_no_note, NOTE="Valid note", BITRATE="5000k")
        res_valid = client.post("/indi-allsky/ajax/minigenerate", json=payload_valid)
        assert res_valid.status_code == 200


def test_longterm_keogram_views(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):

        # GET /indi-allsky/longtermkeogram
        res_get = client.get("/indi-allsky/longtermkeogram")
        assert res_get.status_code == 200

        # POST /indi-allsky/js/longtermkeogram sanity checks
        import wtforms
        with patch.object(wtforms.Form, "validate", lambda self, extra_validators=None: True):
            # Days > 2000
            res_too_many_days = client.post("/indi-allsky/js/longtermkeogram", json={
                "CAMERA_ID": 1,
                "END_SELECT": "today",
                "DAYS_SELECT": 2001,
                "PIXELS_SELECT": 1,
                "ALIGNMENT_SELECT": 60,
                "OFFSET_SELECT": 0,
                "REVERSE": False,
                "LABEL": True,
            })
            assert res_too_many_days.status_code == 400

            # Alignment < 5
            res_small_align = client.post("/indi-allsky/js/longtermkeogram", json={
                "CAMERA_ID": 1,
                "END_SELECT": "today",
                "DAYS_SELECT": 30,
                "PIXELS_SELECT": 1,
                "ALIGNMENT_SELECT": 4,
                "OFFSET_SELECT": 0,
                "REVERSE": False,
                "LABEL": True,
            })
            assert res_small_align.status_code == 400

            # Invalid END_SELECT
            res_bad_end = client.post("/indi-allsky/js/longtermkeogram", json={
                "CAMERA_ID": 1,
                "END_SELECT": "invalid",
                "DAYS_SELECT": 30,
                "PIXELS_SELECT": 1,
                "ALIGNMENT_SELECT": 60,
                "OFFSET_SELECT": 0,
                "REVERSE": False,
                "LABEL": True,
            })
            assert res_bad_end.status_code == 400

            # Success path with mock numpy array returned by LongTermKeogramGenerator
            import numpy as np
            mock_arr = np.zeros((100, 100, 3), dtype=np.uint8)
            with patch("indi_allsky.longTermKeogram.LongTermKeogramGenerator.generate", return_value=mock_arr):
                res_success = client.post("/indi-allsky/js/longtermkeogram", json={
                    "CAMERA_ID": 1,
                    "END_SELECT": "today",
                    "DAYS_SELECT": 7,
                    "PIXELS_SELECT": 1,
                    "ALIGNMENT_SELECT": 60,
                    "OFFSET_SELECT": 0,
                    "REVERSE": False,
                    "LABEL": True,
                })
                assert res_success.status_code == 200
                assert "image_b64" in res_success.json


def test_filespace_usage_view(flask_app, system_db):
    from indi_allsky.flask.models import IndiAllSkyDbThumbnailTable, IndiAllSkyDbImageTable, IndiAllSkyDbPanoramaImageTable
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    now = datetime(2026, 9, 19, 12, 0, 0)
    with flask_app.app_context():
        thumb = IndiAllSkyDbThumbnailTable(
            uuid="thumb-uuid-123",
            filename="/tmp/thumb.jpg",
            createDate=now,
            fileSize=500,
            camera_id=1,
        )
        db.session.add(thumb)

        img = IndiAllSkyDbImageTable(
            camera_id=1,
            filename="/tmp/file_space.jpg",
            createDate=now,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
            adu=500,
            night=True,
            fileSize=10000,
            thumbnail_uuid="thumb-uuid-123",
        )
        db.session.add(img)

        pano = IndiAllSkyDbPanoramaImageTable(
            camera_id=1,
            filename="/tmp/pano.jpg",
            createDate=now,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
            width=1920,
            height=1080,
            exclude=False,
            night=False,
            fileSize=15000,
        )
        db.session.add(pano)
        db.session.commit()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):

        res = client.get("/indi-allsky/filespaceusage")
        assert res.status_code == 200


