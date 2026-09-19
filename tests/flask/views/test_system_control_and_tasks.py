import os
import io
import json
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import dbus
from indi_allsky.flask import db
from indi_allsky.flask.views import (
    TaskQueueView,
    AjaxSystemInfoView,
    AjaxSystemStatsView,
    AjaxIndiServerChangeView,
    TimelapseGeneratorView,
    AjaxTimelapseGeneratorView,
)
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbConfigTable,
    IndiAllSkyDbUserTable,
    IndiAllSkyDbTaskQueueTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbFitsImageTable,
    IndiAllSkyDbRawImageTable,
    IndiAllSkyDbPanoramaImageTable,
    IndiAllSkyDbBadPixelMapTable,
    IndiAllSkyDbDarkFrameTable,
    IndiAllSkyDbVideoTable,
    IndiAllSkyDbMiniVideoTable,
    IndiAllSkyDbKeogramTable,
    IndiAllSkyDbStarTrailsTable,
    IndiAllSkyDbStarTrailsVideoTable,
    IndiAllSkyDbPanoramaVideoTable,
    IndiAllSkyDbThumbnailTable,
    TaskQueueState,
    TaskQueueQueue,
)


@pytest.fixture
def system_db(flask_app):
    """Seed database for system control and task queue tests."""
    with flask_app.app_context():
        # Clear tables
        for table in (
            IndiAllSkyDbTaskQueueTable,
            IndiAllSkyDbThumbnailTable,
            IndiAllSkyDbPanoramaVideoTable,
            IndiAllSkyDbStarTrailsVideoTable,
            IndiAllSkyDbStarTrailsTable,
            IndiAllSkyDbKeogramTable,
            IndiAllSkyDbMiniVideoTable,
            IndiAllSkyDbVideoTable,
            IndiAllSkyDbDarkFrameTable,
            IndiAllSkyDbBadPixelMapTable,
            IndiAllSkyDbPanoramaImageTable,
            IndiAllSkyDbRawImageTable,
            IndiAllSkyDbFitsImageTable,
            IndiAllSkyDbImageTable,
            IndiAllSkyDbCameraTable,
            IndiAllSkyDbConfigTable,
            IndiAllSkyDbUserTable,
        ):
            db.session.query(table).delete()
        db.session.commit()

        camera = IndiAllSkyDbCameraTable(
            id=1,
            name="main_camera",
            driver="indi_asi_ccd",
            friendlyName="Camera 1",
            uuid="cam1_uuid",
            lensImageCircle=1000,
            latitude=-34.0,
            longitude=138.0,
            elevation=0.0,
            nightSunAlt=-6.0,
        )
        db.session.add(camera)

        user = IndiAllSkyDbUserTable(
            username="admin",
            email="admin@example.com",
            password="pbkdf2:sha256:1000$hash$salt",
            admin=True,
        )
        db.session.add(user)

        config = IndiAllSkyDbConfigTable(
            id=1,
            level=1,
            note="Initial config",
            data={
                "IMAGE_FOLDER": "/tmp",
                "IMAGE_FILE_TYPE": "jpg",
                "IMAGE_FILE_COMPRESSION": {"jpg": 85},
                "ENCRYPT_PASSWORDS": False,
            },
        )
        db.session.add(config)
        db.session.commit()

        yield camera


def test_task_queue_view(flask_app, system_db):
    client = flask_app.test_client()

    with flask_app.app_context():
        # Create a task with data and one without data
        task1 = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.MAIN,
            state=TaskQueueState.QUEUED,
            priority=100,
            createDate=datetime.now(),
            data={"action": "test_action"},
        )
        task2 = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.MAIN,
            state=TaskQueueState.RUNNING,
            priority=100,
            createDate=datetime.now(),
            data=None,
        )
        db.session.add(task1)
        db.session.add(task2)
        db.session.commit()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        res = client.get("/indi-allsky/tasks")
        assert res.status_code == 200
        assert b"Task Queue" in res.data


def test_ajax_system_info_view_permissions_and_validation(flask_app, system_db):
    client = flask_app.test_client()

    # Non-admin user check
    with flask_app.app_context():
        user_non_admin = IndiAllSkyDbUserTable(
            username="user",
            email="user@example.com",
            password="hash",
            admin=False,
        )
        db.session.add(user_non_admin)
        db.session.commit()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": False}):
        with patch("flask_login.utils._get_user") as mock_user:
            mock_u = MagicMock()
            mock_u.is_authenticated = True
            mock_u.is_admin = False
            mock_user.return_value = mock_u

            payload = {"CAMERA_ID": "1", "SERVICE_HIDDEN": "system", "COMMAND_HIDDEN": "reboot"}
            res = client.post("/indi-allsky/ajax/system", json=payload)
            assert res.status_code == 400
            assert b"You do not have permission" in res.data

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        # Invalid form data
        res = client.post("/indi-allsky/ajax/system", json={})
        assert res.status_code == 400


def test_ajax_system_info_view_indiserver_service(flask_app, system_db):
    client = flask_app.test_client()
    indiserver_name = flask_app.config["INDISERVER_SERVICE_NAME"]

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        with patch.object(AjaxSystemInfoView, "stopSystemdUnit", return_value="stopped"), \
             patch.object(AjaxSystemInfoView, "startSystemdUnit", return_value="started"):

            # Stop
            payload = {"CAMERA_ID": "1", "SERVICE_HIDDEN": indiserver_name, "COMMAND_HIDDEN": "stop"}
            res = client.post("/indi-allsky/ajax/system", json=payload)
            assert res.status_code == 200

            # Start
            payload["COMMAND_HIDDEN"] = "start"
            res = client.post("/indi-allsky/ajax/system", json=payload)
            assert res.status_code == 200

            # Unhandled command
            payload["COMMAND_HIDDEN"] = "invalid"
            res = client.post("/indi-allsky/ajax/system", json=payload)
            assert res.status_code == 400


def test_ajax_system_info_view_allsky_service(flask_app, system_db):
    client = flask_app.test_client()
    allsky_name = flask_app.config["ALLSKY_SERVICE_NAME"]

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        with patch.object(AjaxSystemInfoView, "stopSystemdUnit", return_value="stopped"), \
             patch.object(AjaxSystemInfoView, "startSystemdUnit", return_value="started"):

            # HUP / reload task
            payload = {"CAMERA_ID": "1", "SERVICE_HIDDEN": allsky_name, "COMMAND_HIDDEN": "hup"}
            res = client.post("/indi-allsky/ajax/system", json=payload)
            assert res.status_code == 200
            assert b"Job submitted" in res.data

            # Stop
            payload["COMMAND_HIDDEN"] = "stop"
            res = client.post("/indi-allsky/ajax/system", json=payload)
            assert res.status_code == 200

            # Start
            payload["COMMAND_HIDDEN"] = "start"
            res = client.post("/indi-allsky/ajax/system", json=payload)
            assert res.status_code == 200

            # Invalid
            payload["COMMAND_HIDDEN"] = "invalid"
            res = client.post("/indi-allsky/ajax/system", json=payload)
            assert res.status_code == 400


def test_ajax_system_info_view_timers_and_gunicorn(flask_app, system_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        with patch.object(AjaxSystemInfoView, "disableSystemdUnit", return_value="disabled"), \
             patch.object(AjaxSystemInfoView, "enableSystemdUnit", return_value="enabled"), \
             patch.object(AjaxSystemInfoView, "stopSystemdUnit", return_value="stopped"):

            # Indiserver service
            indiserver_svc = flask_app.config.get("INDISERVER_SERVICE_NAME", "indiserver.service")
            payload = {"CAMERA_ID": "1", "SERVICE_HIDDEN": indiserver_svc, "COMMAND_HIDDEN": "disable"}
            assert client.post("/indi-allsky/ajax/system", json=payload).status_code == 200
            payload["COMMAND_HIDDEN"] = "enable"
            assert client.post("/indi-allsky/ajax/system", json=payload).status_code == 200
            payload["COMMAND_HIDDEN"] = "invalid"
            assert client.post("/indi-allsky/ajax/system", json=payload).status_code == 400

            # Allsky service
            allsky_svc = flask_app.config.get("ALLSKY_SERVICE_NAME", "indi-allsky.service")
            payload = {"CAMERA_ID": "1", "SERVICE_HIDDEN": allsky_svc, "COMMAND_HIDDEN": "enable"}
            assert client.post("/indi-allsky/ajax/system", json=payload).status_code == 200
            payload["COMMAND_HIDDEN"] = "disable"
            assert client.post("/indi-allsky/ajax/system", json=payload).status_code == 200
            payload["COMMAND_HIDDEN"] = "invalid"
            assert client.post("/indi-allsky/ajax/system", json=payload).status_code == 400

            # Gunicorn service
            gunicorn_svc = flask_app.config.get("GUNICORN_SERVICE_NAME", "indi-allsky-ui.service")
            payload = {"CAMERA_ID": "1", "SERVICE_HIDDEN": gunicorn_svc, "COMMAND_HIDDEN": "stop"}
            assert client.post("/indi-allsky/ajax/system", json=payload).status_code == 200
            payload["COMMAND_HIDDEN"] = "invalid"
            assert client.post("/indi-allsky/ajax/system", json=payload).status_code == 400


def test_ajax_system_info_view_upgrade_service(flask_app, system_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        with patch.object(AjaxSystemInfoView, "startSystemdUnit", return_value="started"), \
             patch("psutil.disk_partitions") as mock_parts, \
             patch("psutil.disk_usage") as mock_usage:

            mock_fs = MagicMock()
            mock_fs.mountpoint = "/"
            mock_parts.return_value = [mock_fs]

            # Case 1: Enough space (> 1000MB)
            mock_u = MagicMock()
            mock_u.total = 2000 * 1024 * 1024
            mock_usage.return_value = mock_u

            payload = {"CAMERA_ID": "1", "SERVICE_HIDDEN": flask_app.config["UPGRADE_ALLSKY_SERVICE_NAME"], "COMMAND_HIDDEN": "start"}
            res = client.post("/indi-allsky/ajax/system", json=payload)
            assert res.status_code == 200

            # Case 2: Not enough space (< 1000MB)
            mock_u.total = 500 * 1024 * 1024
            mock_usage.return_value = mock_u
            res = client.post("/indi-allsky/ajax/system", json=payload)
            assert res.status_code == 400
            assert b"Not enough available space" in res.data

            # Case 3: PermissionError on disk usage
            mock_usage.side_effect = PermissionError("Denied")
            res = client.post("/indi-allsky/ajax/system", json=payload)
            assert res.status_code == 200

            # Invalid command
            payload["COMMAND_HIDDEN"] = "invalid"
            res = client.post("/indi-allsky/ajax/system", json=payload)
            assert res.status_code == 400


def test_ajax_system_info_view_system_commands(flask_app, system_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        # Reboot
        with patch.object(AjaxSystemInfoView, "rebootSystemd", return_value="ok"):
            payload = {"CAMERA_ID": "1", "SERVICE_HIDDEN": "system", "COMMAND_HIDDEN": "reboot"}
            assert client.post("/indi-allsky/ajax/system", json=payload).status_code == 200

        with patch.object(AjaxSystemInfoView, "rebootSystemd", side_effect=dbus.exceptions.DBusException("Error")):
            payload = {"CAMERA_ID": "1", "SERVICE_HIDDEN": "system", "COMMAND_HIDDEN": "reboot"}
            assert client.post("/indi-allsky/ajax/system", json=payload).status_code == 400

        # Poweroff
        with patch.object(AjaxSystemInfoView, "verify_admin_network", return_value=False):
            payload = {"CAMERA_ID": "1", "SERVICE_HIDDEN": "system", "COMMAND_HIDDEN": "poweroff"}
            res = client.post("/indi-allsky/ajax/system", json=payload)
            assert res.status_code == 400
            assert b"Request not from admin network" in res.data

        with patch.object(AjaxSystemInfoView, "verify_admin_network", return_value=True), \
             patch.object(AjaxSystemInfoView, "poweroffSystemd", return_value="ok"):
            payload = {"CAMERA_ID": "1", "SERVICE_HIDDEN": "system", "COMMAND_HIDDEN": "poweroff"}
            assert client.post("/indi-allsky/ajax/system", json=payload).status_code == 200

        with patch.object(AjaxSystemInfoView, "verify_admin_network", return_value=True), \
             patch.object(AjaxSystemInfoView, "poweroffSystemd", side_effect=dbus.exceptions.DBusException("Error")):
            payload = {"CAMERA_ID": "1", "SERVICE_HIDDEN": "system", "COMMAND_HIDDEN": "poweroff"}
            assert client.post("/indi-allsky/ajax/system", json=payload).status_code == 400

        # Validate DB
        with patch.object(AjaxSystemInfoView, "validateDbEntries", return_value=["<p>OK</p>"]):
            payload = {"CAMERA_ID": "1", "SERVICE_HIDDEN": "system", "COMMAND_HIDDEN": "validate_db"}
            res = client.post("/indi-allsky/ajax/system", json=payload)
            assert res.status_code == 200
            assert b"OK" in res.data

        # Backup DB
        payload = {"CAMERA_ID": "1", "SERVICE_HIDDEN": "system", "COMMAND_HIDDEN": "backup_db"}
        res = client.post("/indi-allsky/ajax/system", json=payload)
        assert res.status_code == 200
        assert b"Submitted backup task" in res.data

        # Expire data
        payload = {"CAMERA_ID": "1", "SERVICE_HIDDEN": "system", "COMMAND_HIDDEN": "expire_data"}
        res = client.post("/indi-allsky/ajax/system", json=payload)
        assert res.status_code == 200
        assert b"Submitted expire task" in res.data

        # Flush commands (admin network check & execution)
        for cmd, method in [
            ("flush_images", "flushImages"),
            ("flush_16min_images", "flush16MinutesImages"),
            ("flush_timelapses", "flushTimelapses"),
            ("flush_daytime", "flushDaytime"),
        ]:
            # Failed admin network
            with patch.object(AjaxSystemInfoView, "verify_admin_network", return_value=False):
                payload = {"CAMERA_ID": "1", "SERVICE_HIDDEN": "system", "COMMAND_HIDDEN": cmd}
                assert client.post("/indi-allsky/ajax/system", json=payload).status_code == 400

            # Successful admin network
            with patch.object(AjaxSystemInfoView, "verify_admin_network", return_value=True), \
                 patch.object(AjaxSystemInfoView, method, return_value=5):
                payload = {"CAMERA_ID": "1", "SERVICE_HIDDEN": "system", "COMMAND_HIDDEN": cmd}
                res = client.post("/indi-allsky/ajax/system", json=payload)
                assert res.status_code == 200
                assert b"5" in res.data

        # Unhandled system command
        payload = {"CAMERA_ID": "1", "SERVICE_HIDDEN": "system", "COMMAND_HIDDEN": "unhandled_cmd"}
        assert client.post("/indi-allsky/ajax/system", json=payload).status_code == 400

        # Unhandled service
        payload = {"CAMERA_ID": "1", "SERVICE_HIDDEN": "unhandled_svc", "COMMAND_HIDDEN": "foo"}
        assert client.post("/indi-allsky/ajax/system", json=payload).status_code == 400


def test_ajax_system_info_view_helper_methods(flask_app, system_db):
    view = AjaxSystemInfoView()

    # rebootSystemd & poweroffSystemd with mock DBus
    with patch("dbus.SystemBus") as mock_bus:
        mock_obj = MagicMock()
        mock_iface = MagicMock()
        mock_iface.Reboot.return_value = True
        mock_iface.PowerOff.return_value = True
        mock_bus.return_value.get_object.return_value = mock_obj
        with patch("dbus.Interface", return_value=mock_iface):
            assert view.rebootSystemd() is True
            assert view.poweroffSystemd() is True

    # _deleteAssets error handling
    with flask_app.app_context():
        img = IndiAllSkyDbImageTable(
            camera_id=1,
            filename="test_img.jpg",
            dayDate=datetime.now().date(),
            exposure=1.0,
            gain=100.0,
            adu=30000.0,
        )
        db.session.add(img)
        db.session.commit()
        img_id = img.id

        with patch.object(IndiAllSkyDbImageTable, "deleteAsset", side_effect=OSError("File delete failed")):
            count = view._deleteAssets(IndiAllSkyDbImageTable, [img_id])
            assert count == 0

    # flushImages, flush16MinutesImages, flushTimelapses, flushDaytime
    with flask_app.app_context():
        img1 = IndiAllSkyDbImageTable(
            camera_id=1,
            filename="img1.jpg",
            dayDate=datetime.now().date(),
            exposure=1.0,
            gain=100.0,
            adu=30000.0,
            night=False,
            createDate=datetime.now(),
        )
        fits1 = IndiAllSkyDbFitsImageTable(
            camera_id=1,
            filename="fits1.fits",
            dayDate=datetime.now().date(),
            exposure=1.0,
            gain=100.0,
            night=False,
            createDate=datetime.now(),
        )
        raw1 = IndiAllSkyDbRawImageTable(
            camera_id=1,
            filename="raw1.raw",
            dayDate=datetime.now().date(),
            exposure=1.0,
            gain=100.0,
            night=False,
            createDate=datetime.now(),
        )
        pano1 = IndiAllSkyDbPanoramaImageTable(
            camera_id=1,
            filename="pano1.jpg",
            dayDate=datetime.now().date(),
            exposure=1.0,
            gain=100.0,
            night=False,
            createDate=datetime.now(),
        )
        db.session.add_all([img1, fits1, raw1, pano1])
        db.session.commit()

        with patch.object(view, "_deleteAssets", wraps=view._deleteAssets) as mock_del:
            assert view.flushImages(1) == 5
            assert view.flush16MinutesImages(1) == 0
            assert view.flushTimelapses(1) == 0
            assert view.flushDaytime(1) == 0


def test_ajax_system_info_validate_db_entries(flask_app, system_db):
    view = AjaxSystemInfoView()

    with flask_app.app_context():
        # Add entries for validateDbEntries
        img = IndiAllSkyDbImageTable(
            camera_id=1,
            filename="nonexistent_img.jpg",
            dayDate=datetime.now().date(),
            exposure=1.0,
            gain=100.0,
            adu=30000.0,
        )
        fits = IndiAllSkyDbFitsImageTable(
            camera_id=1,
            filename="nonexistent_fits.fits",
            dayDate=datetime.now().date(),
            exposure=1.0,
            gain=100.0,
        )
        raw = IndiAllSkyDbRawImageTable(
            camera_id=1,
            filename="nonexistent_raw.raw",
            dayDate=datetime.now().date(),
            exposure=1.0,
            gain=100.0,
        )
        pano = IndiAllSkyDbPanoramaImageTable(
            camera_id=1,
            filename="nonexistent_pano.jpg",
            dayDate=datetime.now().date(),
            exposure=1.0,
            gain=100.0,
        )
        bpm = IndiAllSkyDbBadPixelMapTable(
            camera_id=1,
            filename="nonexistent_bpm.txt",
            bitdepth=16,
            exposure=1.0,
            gain=100.0,
        )
        dark = IndiAllSkyDbDarkFrameTable(
            camera_id=1,
            filename="nonexistent_dark.fits",
            bitdepth=16,
            exposure=1.0,
            gain=100.0,
        )
        vid = IndiAllSkyDbVideoTable(
            camera_id=1,
            filename="nonexistent_video.mp4",
            dayDate=datetime.now().date(),
            success=True,
        )
        mvid = IndiAllSkyDbMiniVideoTable(
            camera_id=1,
            filename="nonexistent_mvideo.mp4",
            dayDate=datetime.now().date(),
            targetDate=datetime.now().date(),
            startDate=datetime.now(),
            endDate=datetime.now(),
            note="test",
            success=True,
        )
        keo = IndiAllSkyDbKeogramTable(
            camera_id=1,
            filename="nonexistent_keogram.jpg",
            dayDate=datetime.now().date(),
        )
        st = IndiAllSkyDbStarTrailsTable(
            camera_id=1,
            filename="nonexistent_st.jpg",
            dayDate=datetime.now().date(),
            success=True,
        )
        stv = IndiAllSkyDbStarTrailsVideoTable(
            camera_id=1,
            filename="nonexistent_stv.mp4",
            dayDate=datetime.now().date(),
            success=True,
        )
        pv = IndiAllSkyDbPanoramaVideoTable(
            camera_id=1,
            filename="nonexistent_pv.mp4",
            dayDate=datetime.now().date(),
            success=True,
        )
        thumb = IndiAllSkyDbThumbnailTable(
            camera_id=1,
            filename="nonexistent_thumb.jpg",
        )
        db.session.add_all([img, fits, raw, pano, bpm, dark, vid, mvid, keo, st, stv, pv, thumb])
        db.session.commit()

        # Mock validateFile on all tables to return False (file missing)
        with patch.object(IndiAllSkyDbImageTable, "validateFile", return_value=False), \
             patch.object(IndiAllSkyDbFitsImageTable, "validateFile", return_value=False), \
             patch.object(IndiAllSkyDbRawImageTable, "validateFile", return_value=False), \
             patch.object(IndiAllSkyDbPanoramaImageTable, "validateFile", return_value=False), \
             patch.object(IndiAllSkyDbBadPixelMapTable, "validateFile", return_value=False), \
             patch.object(IndiAllSkyDbDarkFrameTable, "validateFile", return_value=False), \
             patch.object(IndiAllSkyDbVideoTable, "validateFile", return_value=False), \
             patch.object(IndiAllSkyDbMiniVideoTable, "validateFile", return_value=False), \
             patch.object(IndiAllSkyDbKeogramTable, "validateFile", return_value=False), \
             patch.object(IndiAllSkyDbStarTrailsTable, "validateFile", return_value=False), \
             patch.object(IndiAllSkyDbStarTrailsVideoTable, "validateFile", return_value=False), \
             patch.object(IndiAllSkyDbPanoramaVideoTable, "validateFile", return_value=False), \
             patch.object(IndiAllSkyDbThumbnailTable, "validateFile", return_value=False):

            messages = view.validateDbEntries()
            assert any("Images: 1" in m for m in messages)
            assert any("Removed 1 missing image entries" in m for m in messages)


def test_ajax_system_stats_view(flask_app, system_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        with patch.object(AjaxSystemStatsView, "get_context") as mock_ctx:
            now_dt = datetime(2026, 9, 19, 12, 34, 56)
            mock_ctx.return_value = {
                "cpu_usage": 15.0,
                "cpu_count": 4,
                "cpu_load5": 0.5,
                "cpu_load10": 0.6,
                "cpu_load15": 0.7,
                "mem_total": 8000,
                "mem_usage": 4000,
                "swap_total": 2000,
                "swap_usage": 100,
                "fs_data": [],
                "uptime_str": "1 day",
                "temp_list": [],
                "fan_list": [],
                "now": now_dt,
            }

            res = client.get("/indi-allsky/ajax/system/stats")
            assert res.status_code == 200
            data = res.get_json()
            assert data["cpu_usage"] == 15.0
            assert data["now"] == "2026-09-19 12:34:56"


def test_ajax_indiserver_change_view(flask_app, system_db, tmp_path):
    client = flask_app.test_client()

    # Mock service template path and user home systemd path
    service_file = tmp_path / "indiserver.service"
    service_file.write_text("%ALLSKY_DIRECTORY% %INDI_DRIVER_PATH% %INDI_PORT% %INDI_CCD_DRIVER% %INDI_GPS_DRIVER% %INDISERVER_USER%")

    user_config_dir = tmp_path / ".config" / "systemd" / "user"
    user_config_dir.mkdir(parents=True)
    target_service_file = user_config_dir / flask_app.config["INDISERVER_SERVICE_NAME"]

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        with patch("shutil.which", return_value="/usr/bin/indiserver"), \
             patch("pathlib.Path.exists", return_value=True), \
             patch("io.open", side_effect=lambda path, mode="r", *a, **k: open(
                 service_file if "service" in str(path) else target_service_file, mode
             )), \
             patch("os.getlogin", return_value="testuser"), \
             patch.object(Path, "chmod", return_value=None), \
             patch.object(AjaxIndiServerChangeView, "reloadSystemdUnits", return_value=None), \
             patch.object(AjaxIndiServerChangeView, "restartSystemdUnit", return_value=None):

            payload = {
                "CAMERA_SERVER_SELECT": "indi_asi_ccd",
                "GPS_SERVER_SELECT": "",
                "RESTART_INDISERVER": True,
            }
            res = client.post("/indi-allsky/ajax/indiserver", json=payload)
            assert res.status_code == 200
            assert b"Reconfigure completed" in res.data


def test_timelapse_generator_view(flask_app, system_db):
    client = flask_app.test_client()

    with flask_app.app_context():
        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=TaskQueueState.QUEUED,
            priority=100,
            createDate=datetime.now(),
            data={"action": "generateVideo"},
        )
        db.session.add(task)
        db.session.commit()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        res = client.get("/indi-allsky/generate")
        assert res.status_code == 200
        assert b"Generate" in res.data


def test_ajax_timelapse_generator_view(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    mock_form_cls = MagicMock()
    mock_form = mock_form_cls.return_value
    mock_form.validate.return_value = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user), \
         patch("indi_allsky.flask.views.IndiAllskyTimelapseGeneratorForm", mock_form_cls):
        # Deletion actions
        with patch.object(AjaxTimelapseGeneratorView, "verify_admin_network", return_value=True):
            actions = [
                "delete_video_k_st_p",
                "delete_video",
                "delete_panorama_video",
                "delete_k_st",
            ]
            for act in actions:
                payload = {
                    "CAMERA_ID": 1,
                    "ACTION_SELECT": act,
                    "DAY_SELECT": "2026-09-19_night",
                    "CONFIRM1": True,
                }
                res = client.post("/indi-allsky/ajax/generate", json=payload)
                assert res.status_code == 200

            # Generation actions
            gen_actions = [
                ("generate_video_k_st", True),
                ("generate_video", False),
                ("generate_panorama_video", True),
                ("generate_k_st", False),
                ("upload_endofnight", True),
            ]
            for act, is_night in gen_actions:
                payload = {
                    "CAMERA_ID": 1,
                    "ACTION_SELECT": act,
                    "DAY_SELECT": f"2026-09-19_{'night' if is_night else 'day'}",
                    "CONFIRM1": True,
                }
                res = client.post("/indi-allsky/ajax/generate", json=payload)
                assert res.status_code == 200
