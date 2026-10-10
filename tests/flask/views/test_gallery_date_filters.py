from datetime import datetime
from unittest.mock import patch, MagicMock
from indi_allsky.flask import db
from indi_allsky.flask.models import IndiAllSkyDbImageTable


def test_ajax_gallery_view_date_filtering_hierarchy(flask_app, system_db):
    client = flask_app.test_client()

    with flask_app.app_context():
        img = IndiAllSkyDbImageTable(
            camera_id=1,
            filename="/tmp/test_gallery.jpg",
            createDate=datetime(2026, 9, 19, 12, 30, 0),
            createDate_year=2026,
            createDate_month=9,
            createDate_day=19,
            createDate_hour=12,
            dayDate=datetime(2026, 9, 19).date(),
            exposure=1.0,
            gain=100.0,
            adu=500,
            night=True,
            width=1000,
            height=1000,
        )
        db.session.add(img)
        db.session.commit()

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):

        # 1. Hour filter specified (HOUR_SELECT >= 0)
        res_hour = client.post(
            "/indi-allsky/ajax/gallery",
            json={
                "CAMERA_ID": 1,
                "YEAR_SELECT": 2026,
                "MONTH_SELECT": 9,
                "DAY_SELECT": 19,
                "HOUR_SELECT": 12,
            }
        )
        assert res_hour.status_code == 200
        assert "IMAGE_DATA" in res_hour.json

        # 2. Day filter specified (DAY_SELECT)
        res_day = client.post(
            "/indi-allsky/ajax/gallery",
            json={
                "CAMERA_ID": 1,
                "YEAR_SELECT": 2026,
                "MONTH_SELECT": 9,
                "DAY_SELECT": 19,
            }
        )
        assert res_day.status_code == 200
        assert "HOUR_SELECT" in res_day.json

        # 3. Month filter specified (MONTH_SELECT)
        res_month = client.post(
            "/indi-allsky/ajax/gallery",
            json={
                "CAMERA_ID": 1,
                "YEAR_SELECT": 2026,
                "MONTH_SELECT": 9,
            }
        )
        assert res_month.status_code == 200
        assert "DAY_SELECT" in res_month.json

        # 4. Year filter specified (YEAR_SELECT)
        res_year = client.post(
            "/indi-allsky/ajax/gallery",
            json={
                "CAMERA_ID": 1,
                "YEAR_SELECT": 2026,
            }
        )
        assert res_year.status_code == 200
        assert "MONTH_SELECT" in res_year.json

        # 5. Default filtering when no dates specified
        res_default = client.post(
            "/indi-allsky/ajax/gallery",
            json={"CAMERA_ID": 1}
        )
        assert res_default.status_code == 200
        assert "YEAR_SELECT" in res_default.json

        # 6. Detections filter
        res_det = client.post(
            "/indi-allsky/ajax/gallery",
            json={"CAMERA_ID": 1, "FILTER_DETECTIONS": True}
        )
        assert res_det.status_code == 200

        # 7. ASI676MC repair filters
        res_asi = client.post(
            "/indi-allsky/ajax/gallery",
            json={
                "CAMERA_ID": 1,
                "FILTER_ASI676MC_REPAIRED": True,
                "FILTER_ASI676MC_EXCLUDED": True,
                "FILTER_ASI676MC_FAILED": True,
            }
        )
        assert res_asi.status_code == 200


def test_ajax_gallery_view_empty_db_returns_fallback(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):
        res_empty = client.post("/indi-allsky/ajax/gallery", json={"CAMERA_ID": 1})
        assert res_empty.status_code == 200
        assert res_empty.json["IMAGE_DATA"] == []


def test_ajax_gallery_view_date_filtering_empty_sublists(flask_app, system_db):
    from indi_allsky.flask.forms import IndiAllskyFitsImageViewer
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    empty_func = lambda self, *a, **k: []

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):

        # 1. form_day specified, getHours returns empty
        with patch.object(IndiAllskyFitsImageViewer, "getHours", empty_func):
            res = client.post(
                "/indi-allsky/ajax/gallery",
                json={"CAMERA_ID": 1, "YEAR_SELECT": 2026, "MONTH_SELECT": 9, "DAY_SELECT": 19}
            )
            assert res.status_code == 200
            assert res.json["IMAGE_DATA"] == []

        # 2. form_month specified, getDays returns empty
        with patch.object(IndiAllskyFitsImageViewer, "getDays", empty_func):
            res = client.post(
                "/indi-allsky/ajax/gallery",
                json={"CAMERA_ID": 1, "YEAR_SELECT": 2026, "MONTH_SELECT": 9}
            )
            assert res.status_code == 200
            assert res.json["DAY_SELECT"] == []
            assert res.json["HOUR_SELECT"] == []
            assert res.json["IMAGE_DATA"] == []

        # 3. form_month specified, getDays returns [(19, 19)], getHours returns empty
        with patch.object(IndiAllskyFitsImageViewer, "getDays", lambda self, *a, **k: [(19, 19)]), \
             patch.object(IndiAllskyFitsImageViewer, "getHours", empty_func):
            res = client.post(
                "/indi-allsky/ajax/gallery",
                json={"CAMERA_ID": 1, "YEAR_SELECT": 2026, "MONTH_SELECT": 9}
            )
            assert res.status_code == 200
            assert res.json["HOUR_SELECT"] == []
            assert res.json["IMAGE_DATA"] == []

        # 4. form_year specified, getMonths returns empty
        with patch.object(IndiAllskyFitsImageViewer, "getMonths", empty_func):
            res = client.post(
                "/indi-allsky/ajax/gallery",
                json={"CAMERA_ID": 1, "YEAR_SELECT": 2026}
            )
            assert res.status_code == 200
            assert res.json["MONTH_SELECT"] == []
            assert res.json["IMAGE_DATA"] == []

        # 5. form_year specified, getMonths returns [(9, 9)], getDays returns empty
        with patch.object(IndiAllskyFitsImageViewer, "getMonths", lambda self, *a, **k: [(9, 9)]), \
             patch.object(IndiAllskyFitsImageViewer, "getDays", empty_func):
            res = client.post(
                "/indi-allsky/ajax/gallery",
                json={"CAMERA_ID": 1, "YEAR_SELECT": 2026}
            )
            assert res.status_code == 200
            assert res.json["DAY_SELECT"] == []
            assert res.json["IMAGE_DATA"] == []

        # 6. form_year specified, getMonths returns [(9, 9)], getDays returns [(19, 19)], getHours returns empty
        with patch.object(IndiAllskyFitsImageViewer, "getMonths", lambda self, *a, **k: [(9, 9)]), \
             patch.object(IndiAllskyFitsImageViewer, "getDays", lambda self, *a, **k: [(19, 19)]), \
             patch.object(IndiAllskyFitsImageViewer, "getHours", empty_func):
            res = client.post(
                "/indi-allsky/ajax/gallery",
                json={"CAMERA_ID": 1, "YEAR_SELECT": 2026}
            )
            assert res.status_code == 200
            assert res.json["HOUR_SELECT"] == []
            assert res.json["IMAGE_DATA"] == []



def test_ajax_fits_image_viewer_date_filtering(flask_app, system_db):
    from indi_allsky.flask.forms import IndiAllskyFitsImageViewer
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    empty_func = lambda self, *a, **k: []

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):

        # 1. Hour filter specified
        res_hour = client.post(
            "/indi-allsky/ajax/fitsimageviewer",
            json={
                "CAMERA_ID": 1,
                "YEAR_SELECT": 2026,
                "MONTH_SELECT": 9,
                "DAY_SELECT": 19,
                "HOUR_SELECT": 12,
            }
        )
        assert res_hour.status_code == 200
        assert "IMAGE_DATA" in res_hour.json

        # 2. Day filter specified
        res_day = client.post(
            "/indi-allsky/ajax/fitsimageviewer",
            json={
                "CAMERA_ID": 1,
                "YEAR_SELECT": 2026,
                "MONTH_SELECT": 9,
                "DAY_SELECT": 19,
            }
        )
        assert res_day.status_code == 200
        assert "HOUR_SELECT" in res_day.json

        # 3. Day filter specified but getHours empty
        with patch.object(IndiAllskyFitsImageViewer, "getHours", empty_func):
            res_day_empty = client.post(
                "/indi-allsky/ajax/fitsimageviewer",
                json={
                    "CAMERA_ID": 1,
                    "YEAR_SELECT": 2026,
                    "MONTH_SELECT": 9,
                    "DAY_SELECT": 19,
                }
            )
            assert res_day_empty.status_code == 200
            assert res_day_empty.json["IMAGE_DATA"] == []

        # 4. Month filter specified
        res_month = client.post(
            "/indi-allsky/ajax/fitsimageviewer",
            json={
                "CAMERA_ID": 1,
                "YEAR_SELECT": 2026,
                "MONTH_SELECT": 9,
            }
        )
        assert res_month.status_code == 200
        assert "DAY_SELECT" in res_month.json

        # 5. Month filter specified but getDays empty
        with patch.object(IndiAllskyFitsImageViewer, "getDays", empty_func):
            res_month_empty = client.post(
                "/indi-allsky/ajax/fitsimageviewer",
                json={
                    "CAMERA_ID": 1,
                    "YEAR_SELECT": 2026,
                    "MONTH_SELECT": 9,
                }
            )
            assert res_month_empty.status_code == 200

        # 6. Year filter specified
        res_year = client.post(
            "/indi-allsky/ajax/fitsimageviewer",
            json={
                "CAMERA_ID": 1,
                "YEAR_SELECT": 2026,
            }
        )
        assert res_year.status_code == 200
        assert "MONTH_SELECT" in res_year.json

        # 7. Year filter specified but getMonths empty
        with patch.object(IndiAllskyFitsImageViewer, "getMonths", empty_func):
            res_year_empty = client.post(
                "/indi-allsky/ajax/fitsimageviewer",
                json={
                    "CAMERA_ID": 1,
                    "YEAR_SELECT": 2026,
                }
            )
            assert res_year_empty.status_code == 200

        # 8. No filters specified, empty getYears
        with patch.object(IndiAllskyFitsImageViewer, "getYears", empty_func):
            res_no_years = client.post(
                "/indi-allsky/ajax/fitsimageviewer",
                json={"CAMERA_ID": 1}
            )
            assert res_no_years.status_code == 200

        # 9. No filters specified, valid getYears
        res_default = client.post(
            "/indi-allsky/ajax/fitsimageviewer",
            json={"CAMERA_ID": 1}
        )
        assert res_default.status_code == 200


def test_ajax_timelapse_and_mini_timelapse_views(flask_app, system_db):
    from indi_allsky.flask.forms import IndiAllskyVideoViewer, IndiAllskyMiniVideoViewer
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):

        # 1. Timelapse: form_year specified, getMonths returns month
        with patch.object(IndiAllskyVideoViewer, "getMonths", lambda self, *a, **k: [(9, "September")]), \
             patch.object(IndiAllskyVideoViewer, "getVideos", lambda self, *a, **k: ["video1.mp4"]):
            res = client.post(
                "/indi-allsky/ajax/videoviewer",
                json={"CAMERA_ID": 1, "YEAR_SELECT": 2026}
            )
            assert res.status_code == 200
            assert res.json["video_list"] == ["video1.mp4"]

        # 2. Timelapse: form_year specified, getMonths returns empty
        with patch.object(IndiAllskyVideoViewer, "getMonths", lambda self, *a, **k: []):
            res = client.post(
                "/indi-allsky/ajax/videoviewer",
                json={"CAMERA_ID": 1, "YEAR_SELECT": 2026}
            )
            assert res.status_code == 200
            assert res.json["video_list"] == []

        # 3. Timelapse: form_month specified
        with patch.object(IndiAllskyVideoViewer, "getVideos", lambda self, *a, **k: ["video2.mp4"]):
            res_m = client.post(
                "/indi-allsky/ajax/videoviewer",
                json={"CAMERA_ID": 1, "YEAR_SELECT": 2026, "MONTH_SELECT": 9}
            )
            assert res_m.status_code == 200
            assert res_m.json["video_list"] == ["video2.mp4"]

        # 4. Timelapse: no year specified (empty DB)
        res_empty = client.post(
            "/indi-allsky/ajax/videoviewer",
            json={"CAMERA_ID": 1}
        )
        assert res_empty.status_code == 200
        assert res_empty.json["video_list"] == []

        # 5. Mini Timelapse: form_year specified, getMonths returns month
        with patch.object(IndiAllskyMiniVideoViewer, "getMonths", lambda self, *a, **k: [(9, "September")]), \
             patch.object(IndiAllskyMiniVideoViewer, "getVideos", lambda self, *a, **k: ["mini1.mp4"]):
            res_mini = client.post(
                "/indi-allsky/ajax/minivideoviewer",
                json={"CAMERA_ID": 1, "YEAR_SELECT": 2026}
            )
            assert res_mini.status_code == 200
            assert res_mini.json["video_list"] == ["mini1.mp4"]

        # 6. Mini Timelapse: form_year specified, getMonths returns empty
        with patch.object(IndiAllskyMiniVideoViewer, "getMonths", lambda self, *a, **k: []):
            res_mini_empty = client.post(
                "/indi-allsky/ajax/minivideoviewer",
                json={"CAMERA_ID": 1, "YEAR_SELECT": 2026}
            )
            assert res_mini_empty.status_code == 200
            assert res_mini_empty.json["video_list"] == []

        # 7. Mini Timelapse: form_month specified
        with patch.object(IndiAllskyMiniVideoViewer, "getVideos", lambda self, *a, **k: ["mini2.mp4"]):
            res_mini_m = client.post(
                "/indi-allsky/ajax/minivideoviewer",
                json={"CAMERA_ID": 1, "YEAR_SELECT": 2026, "MONTH_SELECT": 9}
            )
            assert res_mini_m.status_code == 200
            assert res_mini_m.json["video_list"] == ["mini2.mp4"]

        # 8. Mini Timelapse: no year specified
        res_mini_no_year = client.post(
            "/indi-allsky/ajax/minivideoviewer",
            json={"CAMERA_ID": 1}
        )
        assert res_mini_no_year.status_code == 200
        assert res_mini_no_year.json["video_list"] == []


def test_ajax_mini_video_delete_view_branches(flask_app, system_db):
    from indi_allsky.flask.models import (
        IndiAllSkyDbMiniVideoTable,
        IndiAllSkyDbTaskQueueTable,
        IndiAllSkyDbThumbnailTable,
        TaskQueueQueue,
        TaskQueueState,
    )
    import uuid

    client = flask_app.test_client()

    mock_admin = MagicMock()
    mock_admin.is_authenticated = True
    mock_admin.is_admin = True

    now = datetime(2026, 9, 19, 12, 0, 0)
    thumb_uuid = str(uuid.uuid4())

    with flask_app.app_context():
        # Insert thumbnail
        thumb = IndiAllSkyDbThumbnailTable(
            uuid=thumb_uuid,
            camera_id=1,
            createDate=now,
            filename="/tmp/thumb.jpg",
        )
        db.session.add(thumb)

        # Insert mini video
        mini_vid = IndiAllSkyDbMiniVideoTable(
            camera_id=1,
            filename="/tmp/mini.mp4",
            createDate=now,
            dayDate=now.date(),
            targetDate=now,
            startDate=now,
            endDate=now,
            night=True,
            uploaded=False,
            success=True,
            framerate=30,
            frames=100,
            note="test",
            thumbnail_uuid=thumb_uuid,
            data={"generation_task_id": 999, "generation_task_created": now.isoformat()},
        )
        db.session.add(mini_vid)

        # Insert active generation task
        task_gen = IndiAllSkyDbTaskQueueTable(
            id=999,
            queue=TaskQueueQueue.VIDEO,
            state=TaskQueueState.RUNNING,
            priority=100,
            createDate=now,
        )
        db.session.add(task_gen)

        # Insert active upload task
        task_upload = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            priority=100,
            createDate=now,
            data={"model": "IndiAllSkyDbThumbnailTable", "id": 1},
        )
        db.session.add(task_upload)
        db.session.commit()
        mini_vid_id = mini_vid.id

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_admin), \
         patch("indi_allsky.flask.views._can_save_standard_configuration", return_value=True):

        # 1. Generation task running -> 409 conflict
        res_gen = client.post(
            "/indi-allsky/ajax/minivideoviewer/delete",
            json={"CAMERA_ID": 1, "VIDEO_ID": mini_vid_id}
        )
        assert res_gen.status_code == 409

        # Mark generation task finished
        with flask_app.app_context():
            t = db.session.get(IndiAllSkyDbTaskQueueTable, 999)
            t.state = TaskQueueState.SUCCESS
            db.session.commit()

        # 2. Upload task running -> 409 conflict
        res_up = client.post(
            "/indi-allsky/ajax/minivideoviewer/delete",
            json={"CAMERA_ID": 1, "VIDEO_ID": mini_vid_id}
        )
        assert res_up.status_code == 409

        # Mark upload task finished
        with flask_app.app_context():
            db.session.query(IndiAllSkyDbTaskQueueTable).delete()
            db.session.commit()

        # 3. Successful deletion
        with patch("pathlib.Path.unlink"):
            res_success = client.post(
                "/indi-allsky/ajax/minivideoviewer/delete",
                json={"CAMERA_ID": 1, "VIDEO_ID": mini_vid_id}
            )
            assert res_success.status_code == 200







