from datetime import datetime
from unittest.mock import patch, MagicMock
from indi_allsky.flask import db
from indi_allsky.flask.models import (
    IndiAllSkyDbMiniVideoTable,
    IndiAllSkyDbTaskQueueTable,
    TaskQueueQueue,
    TaskQueueState,
)


def test_ajax_mini_video_delete_view_not_found(flask_app, system_db):
    client = flask_app.test_client()
    mock_user = MagicMock()
    mock_user.is_authenticated = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):
        res = client.post("/indi-allsky/ajax/minivideoviewer/delete", json={"CAMERA_ID": 1, "VIDEO_ID": 99999})
        assert res.status_code == 404
        assert "not found" in res.json["failure-message"]


def test_ajax_mini_video_delete_view_active_generation_task(flask_app, system_db):
    client = flask_app.test_client()

    now = datetime(2026, 9, 19, 12, 0, 0)
    with flask_app.app_context():
        gen_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=TaskQueueState.RUNNING,
            createDate=now,
            priority=100,
            data={"action": "miniVideo"},
        )
        db.session.add(gen_task)
        db.session.commit()

        mini_vid = IndiAllSkyDbMiniVideoTable(
            camera_id=1,
            filename="/tmp/active_mini.mp4",
            createDate=now,
            dayDate=now.date(),
            targetDate=now,
            startDate=now,
            endDate=now,
            note="test",
            night=True,
            data={
                "generation_task_id": gen_task.id,
                "generation_task_created": gen_task.createDate.isoformat(),
            },
        )
        db.session.add(mini_vid)
        db.session.commit()
        vid_id = mini_vid.id

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):
        res = client.post("/indi-allsky/ajax/minivideoviewer/delete", json={"CAMERA_ID": 1, "VIDEO_ID": vid_id})
        assert res.status_code == 409
        assert "still being created" in res.json["failure-message"]


def test_ajax_mini_video_delete_view_active_upload_task(flask_app, system_db):
    client = flask_app.test_client()

    now = datetime(2026, 9, 19, 12, 0, 0)
    with flask_app.app_context():
        mini_vid = IndiAllSkyDbMiniVideoTable(
            camera_id=1,
            filename="/tmp/upload_mini.mp4",
            createDate=now,
            dayDate=now.date(),
            targetDate=now,
            startDate=now,
            endDate=now,
            note="test",
            night=True,
            data={},
        )
        db.session.add(mini_vid)
        db.session.commit()
        vid_id = mini_vid.id

        upload_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.RUNNING,
            createDate=now,
            priority=100,
            data={"model": "IndiAllSkyDbMiniVideoTable", "id": vid_id},
        )
        db.session.add(upload_task)
        db.session.commit()

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):
        res = client.post("/indi-allsky/ajax/minivideoviewer/delete", json={"CAMERA_ID": 1, "VIDEO_ID": vid_id})
        assert res.status_code == 409
        assert "still being uploaded" in res.json["failure-message"]


def test_ajax_mini_video_delete_view_success_and_oserror(flask_app, system_db):
    client = flask_app.test_client()

    now = datetime(2026, 9, 19, 12, 0, 0)
    with flask_app.app_context():
        mini_vid = IndiAllSkyDbMiniVideoTable(
            camera_id=1,
            filename="/tmp/delete_mini.mp4",
            createDate=now,
            dayDate=now.date(),
            targetDate=now,
            startDate=now,
            endDate=now,
            note="test",
            night=True,
            data={},
        )
        db.session.add(mini_vid)
        db.session.commit()
        vid_id = mini_vid.id

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):

        # OSError on deleteAsset
        with patch.object(IndiAllSkyDbMiniVideoTable, "deleteAsset", side_effect=OSError("Disk error")):
            res_err = client.post("/indi-allsky/ajax/minivideoviewer/delete", json={"CAMERA_ID": 1, "VIDEO_ID": vid_id})
            assert res_err.status_code == 400

        # Success
        with patch.object(IndiAllSkyDbMiniVideoTable, "deleteAsset"):
            res_ok = client.post("/indi-allsky/ajax/minivideoviewer/delete", json={"CAMERA_ID": 1, "VIDEO_ID": vid_id})
            assert res_ok.status_code == 200
            assert "deleted" in res_ok.json["success-message"]


def test_manual_gpio_view_and_ajax_manual_gpio(flask_app, system_db):
    from indi_allsky.devices.exceptions import DeviceControlException
    from indi_allsky.flask.models import IndiAllSkyDbConfigTable
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    class DummyPin:
        def __init__(self, config, pin_1_name=None):
            if pin_1_name == "pin_fail":
                raise DeviceControlException("GPIO fail")
            self.state = 1

    with flask_app.app_context():
        cfg = IndiAllSkyDbConfigTable.query.first()
        data = dict(cfg.data)
        data["MANUAL_GPIO"] = {
            "A_CLASSNAME": "DummyPin",
            "A_PIN_1": "pin_fail",
            "A_PIN_2": "pin_ok",
            "A_PIN_3": "pin_ok2",
        }
        cfg.data = data
        db.session.commit()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user), \
         patch("indi_allsky.devices.generic.DummyPin", DummyPin, create=True):

        res_view = client.get("/indi-allsky/manual_gpio")
        assert res_view.status_code == 200

        # AjaxManualGpioView success
        res_ajax = client.post("/indi-allsky/ajax/manual_gpio", json={"PIN_ID": 2, "NEW_PIN_STATE": 1})
        assert res_ajax.status_code == 200
        assert res_ajax.json["success-message"] == "Pin configured"

        # AjaxManualGpioView unknown pin
        res_unk = client.post("/indi-allsky/ajax/manual_gpio", json={"PIN_ID": 99, "NEW_PIN_STATE": 1})
        assert res_unk.status_code == 400

    # AjaxManualGpioView missing classname
    with flask_app.app_context():
        cfg = IndiAllSkyDbConfigTable.query.first()
        data = dict(cfg.data)
        data["MANUAL_GPIO"] = {}
        cfg.data = data
        db.session.commit()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):
        res_noclass = client.post("/indi-allsky/ajax/manual_gpio", json={"PIN_ID": 1, "NEW_PIN_STATE": 1})
        assert res_noclass.status_code == 400

    # AjaxManualGpioView invalid classname
    with flask_app.app_context():
        cfg = IndiAllSkyDbConfigTable.query.first()
        data = dict(cfg.data)
        data["MANUAL_GPIO"] = {"A_CLASSNAME": "NonExistentClass"}
        cfg.data = data
        db.session.commit()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):
        res_inv = client.post("/indi-allsky/ajax/manual_gpio", json={"PIN_ID": 1, "NEW_PIN_STATE": 1})
        assert res_inv.status_code == 400

    # Non-admin user check
    mock_nonadmin = MagicMock()
    mock_nonadmin.is_authenticated = True
    mock_nonadmin.is_admin = False
    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_nonadmin):
        res_denied = client.post("/indi-allsky/ajax/manual_gpio", json={"PIN_ID": 1, "NEW_PIN_STATE": 1})
        assert res_denied.status_code == 400


def test_queue_panorama_mini_video_branches(flask_app, system_db):
    from indi_allsky.flask.models import IndiAllSkyDbImageTable, IndiAllSkyDbPanoramaImageTable, IndiAllSkyDbConfigTable
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    now = datetime(2026, 9, 19, 12, 0, 0)
    with flask_app.app_context():
        img = IndiAllSkyDbImageTable(
            camera_id=1,
            filename="/tmp/pano_src.jpg",
            createDate=now,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
            adu=500,
            night=True,
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
            night=True,
        )
        db.session.add(pano)
        db.session.commit()

        img_id = img.id
        pano_id = pano.id

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):

        with flask_app.app_context():
            real_entry = IndiAllSkyDbConfigTable.query.first()
            data_disabled = dict(real_entry.data)
            data_disabled["FISH2PANO"] = {"ENABLE": False}
            data_enabled = dict(real_entry.data)
            data_enabled["FISH2PANO"] = {"ENABLE": True}

        mock_entry_disabled = MagicMock()
        mock_entry_disabled.id = real_entry.id
        mock_entry_disabled.level = real_entry.level
        mock_entry_disabled.createDate = real_entry.createDate
        mock_entry_disabled.data = data_disabled

        mock_entry_enabled = MagicMock()
        mock_entry_enabled.id = real_entry.id
        mock_entry_enabled.level = real_entry.level
        mock_entry_enabled.createDate = real_entry.createDate
        mock_entry_enabled.data = data_enabled

        # 1. Panorama creation disabled
        with patch("indi_allsky.config.IndiAllSkyConfig._getConfigEntry", return_value=mock_entry_disabled):
            res_dis = client.post("/indi-allsky/ajax/minigenerate", json={"SOURCE_TYPE": "panorama"})
            assert res_dis.status_code == 400
            assert "turned off" in res_dis.json["failure-message"]

        # 2. Enable FISH2PANO and proceed with valid requests
        with patch("indi_allsky.config.IndiAllSkyConfig._getConfigEntry", return_value=mock_entry_enabled):
            # 3. Invalid PANORAMA_IMAGE_ID
            res_bad_id = client.post(
                "/indi-allsky/ajax/minigenerate",
                json={
                    "SOURCE_TYPE": "panorama",
                    "CAMERA_ID": 1,
                    "IMAGE_ID": img_id,
                    "PRE_SECONDS": 60,
                    "POST_SECONDS": 60,
                    "FRAMERATE": 10,
                    "NOTE": "test panorama video",
                    "START_TIME": "2026-09-19 12:00:00",
                    "END_TIME": "2026-09-19 13:00:00",
                    "PANORAMA_IMAGE_ID": "invalid",
                }
            )
            assert res_bad_id.status_code == 400

            # 4. Mismatched panorama selection
            res_mismatch = client.post(
                "/indi-allsky/ajax/minigenerate",
                json={
                    "SOURCE_TYPE": "panorama",
                    "CAMERA_ID": 1,
                    "IMAGE_ID": img_id,
                    "PRE_SECONDS": 60,
                    "POST_SECONDS": 60,
                    "FRAMERATE": 10,
                    "NOTE": "test panorama video",
                    "START_TIME": "2026-09-19 12:00:00",
                    "END_TIME": "2026-09-19 13:00:00",
                    "PANORAMA_IMAGE_ID": 9999,
                }
            )
            assert res_mismatch.status_code == 400

            # 5. Valid panorama mini video request
            with patch("indi_allsky.flask.views.validatePanoramaMiniTimelapseRequest", return_value={
                "crop_x": 0, "crop_y": 0, "crop_width": 100, "crop_height": 100,
                "aspect_ratio": "16:9", "pan_mode": "none", "end_crop_x": 0, "end_crop_y": 0, "pan_direction": "right"
            }):
                res_ok = client.post(
                    "/indi-allsky/ajax/minigenerate",
                    json={
                        "SOURCE_TYPE": "panorama",
                        "CAMERA_ID": 1,
                        "IMAGE_ID": img_id,
                        "PRE_SECONDS": 60,
                        "POST_SECONDS": 60,
                        "FRAMERATE": 10,
                        "NOTE": "test panorama video",
                        "START_TIME": "2026-09-19 12:00:00",
                        "END_TIME": "2026-09-19 13:00:00",
                        "PANORAMA_IMAGE_ID": pano_id,
                    }
                )
                assert res_ok.status_code == 200
                assert "mini timelapse is being created" in res_ok.json["success-message"]



def test_esp32_square_image_view_branches(flask_app, system_db):
    import numpy as np
    import cv2
    from pathlib import Path
    from indi_allsky.flask.models import IndiAllSkyDbImageTable, IndiAllSkyDbConfigTable

    client = flask_app.test_client()

    # 1. Circular display enabled and circular_display.jpg exists
    circ_file = Path("/tmp/circular_display.jpg")
    img_data = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.imwrite(str(circ_file), img_data)

    with flask_app.app_context():
        cfg = IndiAllSkyDbConfigTable.query.first()
        data = dict(cfg.data)
        data["CIRCULAR_DISPLAY"] = {"ENABLE": True}
        data["IMAGE_FOLDER"] = "/tmp"
        data["IMAGE_FILE_TYPE"] = "jpg"
        cfg.data = data
        db.session.commit()

    try:
        res_circ = client.get("/indi-allsky/allsky_esp32?size=240")
        assert res_circ.status_code == 200
        assert res_circ.mimetype == "image/jpeg"
    finally:
        if circ_file.exists():
            circ_file.unlink()

    # Disable CIRCULAR_DISPLAY
    with flask_app.app_context():
        cfg = IndiAllSkyDbConfigTable.query.first()
        data = dict(cfg.data)
        data["CIRCULAR_DISPLAY"] = {"ENABLE": False}
        cfg.data = data
        db.session.commit()

    # 2. No image in DB -> 404
    res_noimg = client.get("/indi-allsky/allsky_esp32")
    assert res_noimg.status_code == 404

    # Seed an image entry
    now = datetime(2026, 9, 19, 12, 0, 0)
    with flask_app.app_context():
        img_entry = IndiAllSkyDbImageTable(
            camera_id=1,
            filename="esp32_test.jpg",
            createDate=now,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
            adu=500,
            night=True,
        )
        db.session.add(img_entry)
        db.session.commit()

    # 3. Image file missing on disk -> 404
    res_missing = client.get("/indi-allsky/allsky_esp32")
    assert res_missing.status_code == 404

    # 4. JPG image file exists -> 200
    jpg_path = Path("/tmp/esp32_test.jpg")
    cv2.imwrite(str(jpg_path), img_data)
    try:
        with patch.object(IndiAllSkyDbImageTable, "getFilesystemPath", return_value=jpg_path):
            res_jpg = client.get("/indi-allsky/allsky_esp32?size=240")
            assert res_jpg.status_code == 200
    finally:
        if jpg_path.exists():
            jpg_path.unlink()

    # 5. PNG image file exists -> 200
    png_path = Path("/tmp/esp32_test.png")
    cv2.imwrite(str(png_path), img_data)
    try:
        with patch.object(IndiAllSkyDbImageTable, "getFilesystemPath", return_value=png_path):
            res_png = client.get("/indi-allsky/allsky_esp32")
            assert res_png.status_code == 200
    finally:
        if png_path.exists():
            png_path.unlink()

    # 6. Corrupt simplejpeg JPG -> returns 500
    corrupt_jpg = Path("/tmp/esp32_corrupt.jpg")
    corrupt_jpg.write_bytes(b"not a valid jpeg header")
    try:
        with patch.object(IndiAllSkyDbImageTable, "getFilesystemPath", return_value=corrupt_jpg):
            res_err = client.get("/indi-allsky/allsky_esp32")
            assert res_err.status_code == 500
    finally:
        if corrupt_jpg.exists():
            corrupt_jpg.unlink()





