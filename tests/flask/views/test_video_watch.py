from unittest.mock import patch, MagicMock
from pathlib import Path
import pytest
from datetime import datetime

from indi_allsky.flask import db
from indi_allsky.flask.models import (
    IndiAllSkyDbFitsImageTable,
    IndiAllSkyDbDarkFrameTable,
    IndiAllSkyDbBadPixelMapTable,
    IndiAllSkyDbVideoTable,
    IndiAllSkyDbPanoramaVideoTable,
    IndiAllSkyDbKeogramTable,
    IndiAllSkyDbStarTrailsTable,
    IndiAllSkyDbStarTrailsVideoTable,
    IndiAllSkyDbMiniVideoTable,
    IndiAllSkyDbCameraTable,
)
from indi_allsky.flask.views import (
    ImageProcessingView,
    JsonImageProcessingView,
    TimelapseVideoView,
    MiniTimelapseVideoView,
    StartrailVideoView,
    PanoramaVideoView,
)


def test_image_processing_view_get_context(flask_app, system_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        # Test light frame (default, no id passed, no fits entry)
        res = client.get("/indi-allsky/processing")
        assert res.status_code == 200
        assert b"Image Processing" in res.data

        # Add a FITS entry and test light frame selection
        with flask_app.app_context():
            fits = IndiAllSkyDbFitsImageTable(
                camera_id=1,
                filename="test.fits",
                dayDate=datetime.now().date(),
                exposure=1.0,
                gain=100.0,
            )
            db.session.add(fits)
            db.session.commit()
            fits_id = fits.id

        res = client.get(f"/indi-allsky/processing?id={fits_id}&type=light")
        assert res.status_code == 200

        # Test dark frame type
        res = client.get("/indi-allsky/processing?type=dark")
        assert res.status_code == 200

        # Test bpm frame type
        res = client.get("/indi-allsky/processing?type=bpm")
        assert res.status_code == 200


def test_json_image_processing_view_no_fits(flask_app, system_db):
    client = flask_app.test_client()

    mock_form_cls = MagicMock()
    mock_form = mock_form_cls.return_value
    mock_form.validate.return_value = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.IndiAllskyImageProcessingForm", mock_form_cls):

        payload = {
            "DISABLE_PROCESSING": False,
            "OUTPUT_IMAGE_TYPE": "jpg",
            "CAMERA_ID": 1,
            "FRAME_TYPE": "light",
            "FITS_ID": 99999,
        }
        res = client.post("/indi-allsky/js/processing", json=payload)
        assert res.status_code == 200
        data = res.get_json()
        assert data["message"] == "No FITS images found"


def test_watch_video_views(flask_app, system_db):
    client = flask_app.test_client()

    with flask_app.app_context():
        vid = IndiAllSkyDbVideoTable(
            camera_id=1,
            filename="test_video.mp4",
            dayDate=datetime.now().date(),
            success=True,
        )
        pvid = IndiAllSkyDbPanoramaVideoTable(
            camera_id=1,
            filename="test_panovideo.mp4",
            dayDate=datetime.now().date(),
            success=True,
        )
        mvid = IndiAllSkyDbMiniVideoTable(
            camera_id=1,
            filename="test_minivid.mp4",
            dayDate=datetime.now().date(),
            targetDate=datetime.now().date(),
            startDate=datetime.now(),
            endDate=datetime.now(),
            note="test",
            success=True,
        )
        stvid = IndiAllSkyDbStarTrailsVideoTable(
            camera_id=1,
            filename="test_stvid.mp4",
            dayDate=datetime.now().date(),
            success=True,
        )
        db.session.add_all([vid, pvid, mvid, stvid])
        db.session.commit()
        vid_id = vid.id
        pvid_id = pvid.id
        mvid_id = mvid.id
        stvid_id = stvid.id

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        res = client.get(f"/indi-allsky/watch_timelapse?id={vid_id}")
        assert res.status_code == 200

        res_mini = client.get(f"/indi-allsky/watch_mini_timelapse?id={mvid_id}")
        assert res_mini.status_code == 200

        res_st = client.get(f"/indi-allsky/watch_startrail?id={stvid_id}")
        assert res_st.status_code == 200

        res_pano = client.get(f"/indi-allsky/watch_panorama?id={pvid_id}")
        assert res_pano.status_code == 200
