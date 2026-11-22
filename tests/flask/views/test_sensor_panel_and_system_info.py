from datetime import datetime, timedelta
import io
from pathlib import Path
from unittest.mock import patch, MagicMock
import dbus
import psutil

from indi_allsky.flask import db
from indi_allsky.flask.models import (
    IndiAllSkyDbImageTable,
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbPanoramaImageTable,
    IndiAllSkyDbFitsImageTable,
)


def test_system_info_view_internals(flask_app, system_db):
    from indi_allsky.flask.views import SystemInfoView

    with flask_app.test_request_context("/indi-allsky/system"):
        view = SystemInfoView(template_name="system.html")
        view.indi_allsky_config = {"TEMP_DISPLAY": "f"}

        # 1. getSystemType with PermissionError
        with patch("pathlib.Path.exists", return_value=True), \
             patch("io.open", side_effect=PermissionError("Permission denied")):
            assert view.getSystemType() == "Unknown"

        # 2. getSystemType with empty file
        with patch("pathlib.Path.exists", return_value=True), \
             patch("io.open", return_value=io.StringIO("   \n")):
            assert view.getSystemType() == "Unknown"

        # 3. getSystemType when model file does not exist
        with patch("pathlib.Path.exists", return_value=False):
            assert view.getSystemType() == "Generic PC"

        # 4. getAllFsUsage with PermissionError on one mountpoint
        fake_part = MagicMock()
        fake_part.mountpoint = "/home"
        with patch("psutil.disk_partitions", return_value=[fake_part]), \
             patch("psutil.disk_usage", side_effect=PermissionError("denied")):
            assert view.getAllFsUsage() == []

        # 5. getTemps with Fahrenheit, Kelvin, Celsius
        mock_sensor = MagicMock()
        mock_sensor.current = 25.0
        mock_sensor.label = "CPU"
        with patch("psutil.sensors_temperatures", return_value={"coretemp": [mock_sensor]}):
            view.indi_allsky_config["TEMP_DISPLAY"] = "f"
            temps_f = view.getTemps()
            assert temps_f[0]["sys"] == "F"
            assert temps_f[0]["temp"] == 77.0

            view.indi_allsky_config["TEMP_DISPLAY"] = "k"
            temps_k = view.getTemps()
            assert temps_k[0]["sys"] == "K"
            assert temps_k[0]["temp"] == 298.15

            view.indi_allsky_config["TEMP_DISPLAY"] = "c"
            temps_c = view.getTemps()
            assert temps_c[0]["sys"] == "C"
            assert temps_c[0]["temp"] == 25.0

        # 6. getFans with active cooler sysfs fallback
        with patch("psutil.sensors_fans", return_value={}), \
             patch("pathlib.Path.glob") as mock_glob:
            fake_fan_file = MagicMock()
            fake_fan_file.read_text.return_value = "3500\n"
            mock_glob.return_value = [fake_fan_file]

            fans = view.getFans()
            assert len(fans) == 1
            assert fans[0]["rpm"] == 3500.0

        # 7. getSystemdTarget and getSystemdTimeDate with DBusException
        with patch("dbus.SystemBus", side_effect=dbus.exceptions.DBusException("No bus")):
            assert view.getSystemdTarget() == "D-Bus Unavailable"
            timedate = view.getSystemdTimeDate()
            assert timedate["Timezone"] == "Unknown"

        mock_bus = MagicMock()
        mock_systemd1 = MagicMock()
        mock_manager = MagicMock()
        mock_manager.GetDefaultTarget.side_effect = dbus.exceptions.DBusException("Error")
        with patch("dbus.SystemBus", return_value=mock_bus), \
             patch("dbus.Interface", return_value=mock_manager):
            assert view.getSystemdTarget() == "D-Bus Exception"


def test_sensor_panel_and_config_view_dew_heater_and_fan_branches(flask_app, system_db):
    client = flask_app.test_client()
    now = datetime(2026, 9, 19, 12, 0, 0)

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    with flask_app.app_context():
        # Add image with sensor data
        img = IndiAllSkyDbImageTable(
            camera_id=1,
            filename="/tmp/test_sensor.jpg",
            createDate=now,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
            adu=500,
            night=True,
            width=1000,
            height=1000,
            data={
                "camera_sqm_raw_mag": -5.0,
                "sensor_user_10": 20.0, # dh_temp / fan_temp
                "sensor_user_2": 15.0,  # dh_dewpoint
            },
        )
        db.session.add(img)
        db.session.commit()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):

        # 1. SensorPanelView with show_all=1 and show_all=0
        res_sensor_all = client.get("/indi-allsky/sensor_panel?all=1")
        assert res_sensor_all.status_code == 200
        res_sensor = client.get("/indi-allsky/sensor_panel?all=0")
        assert res_sensor.status_code == 200

        # 2. ConfigView with dew heater auto & fan thresholds
        config_override = {
            "DEW_HEATER": {
                "MANUAL_TARGET": 0.0,
                "THOLD_DIFF_LOW": 10.0,
                "THOLD_DIFF_MED": 5.0,
                "THOLD_DIFF_HIGH": 2.0,
                "LEVEL_LOW": 20,
                "LEVEL_MED": 50,
                "LEVEL_HIGH": 100,
                "LEVEL_DEF": 0,
            },
            "FAN": {
                "TARGET": 10.0,
                "THOLD_DIFF_LOW": 2.0,
                "THOLD_DIFF_MED": 5.0,
                "THOLD_DIFF_HIGH": 8.0,
                "LEVEL_LOW": 25,
                "LEVEL_MED": 50,
                "LEVEL_HIGH": 100,
                "LEVEL_DEF": 0,
            },
            "IMAGE_SAVE_FITS": True,
            "IMAGE_SAVE_FITS_PERIOD": 300,
        }

        with patch.object(flask_app, "indi_allsky_config", config_override, create=True), \
             patch("indi_allsky.flask.views.ConfigView.validate_longitude_timezone", return_value=True):
            res_cfg = client.get("/indi-allsky/config")
            assert res_cfg.status_code == 200

        # 3. ConfigView with manual dew heater target
        config_manual = {
            "DEW_HEATER": {
                "MANUAL_TARGET": 18.0,
                "THOLD_DIFF_LOW": 10.0,
                "THOLD_DIFF_MED": 5.0,
                "THOLD_DIFF_HIGH": 1.0,
                "LEVEL_LOW": 20,
                "LEVEL_MED": 50,
                "LEVEL_HIGH": 100,
                "LEVEL_DEF": 0,
            },
            "FAN": {
                "TARGET": 25.0,
                "THOLD_DIFF_LOW": 5.0,
                "THOLD_DIFF_MED": 10.0,
                "THOLD_DIFF_HIGH": 15.0,
            }
        }
        with patch.object(flask_app, "indi_allsky_config", config_manual, create=True):
            res_cfg_man = client.get("/indi-allsky/config")
            assert res_cfg_man.status_code == 200


def test_ajax_image_viewer_date_filtering_branches(flask_app, system_db):
    from indi_allsky.flask.forms import IndiAllskyImageViewer
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    empty_func = lambda self, *a, **k: []

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):

        # 1. Day specified, getHours returns empty
        with patch.object(IndiAllskyImageViewer, "getHours", empty_func):
            res = client.post(
                "/indi-allsky/ajax/imageviewer",
                json={"CAMERA_ID": 1, "YEAR_SELECT": 2026, "MONTH_SELECT": 9, "DAY_SELECT": 19}
            )
            assert res.status_code == 200
            assert res.json["IMAGE_DATA"] == []

        # 2. Month specified, getDays returns empty
        with patch.object(IndiAllskyImageViewer, "getDays", empty_func):
            res = client.post(
                "/indi-allsky/ajax/imageviewer",
                json={"CAMERA_ID": 1, "YEAR_SELECT": 2026, "MONTH_SELECT": 9}
            )
            assert res.status_code == 200
            assert res.json["DAY_SELECT"] == []

        # 3. Month specified, getDays returns item, getHours empty
        with patch.object(IndiAllskyImageViewer, "getDays", lambda self, *a, **k: [(19, 19)]), \
             patch.object(IndiAllskyImageViewer, "getHours", empty_func):
            res = client.post(
                "/indi-allsky/ajax/imageviewer",
                json={"CAMERA_ID": 1, "YEAR_SELECT": 2026, "MONTH_SELECT": 9}
            )
            assert res.status_code == 200
            assert res.json["HOUR_SELECT"] == []

        # 4. Year specified, getMonths returns empty
        with patch.object(IndiAllskyImageViewer, "getMonths", empty_func):
            res = client.post(
                "/indi-allsky/ajax/imageviewer",
                json={"CAMERA_ID": 1, "YEAR_SELECT": 2026}
            )
            assert res.status_code == 200
            assert res.json["MONTH_SELECT"] == []

        # 5. Year specified, getMonths returns item, getDays empty
        with patch.object(IndiAllskyImageViewer, "getMonths", lambda self, *a, **k: [(9, 9)]), \
             patch.object(IndiAllskyImageViewer, "getDays", empty_func):
            res = client.post(
                "/indi-allsky/ajax/imageviewer",
                json={"CAMERA_ID": 1, "YEAR_SELECT": 2026}
            )
            assert res.status_code == 200
            assert res.json["DAY_SELECT"] == []

        # 6. Year specified, getMonths & getDays return item, getHours empty
        with patch.object(IndiAllskyImageViewer, "getMonths", lambda self, *a, **k: [(9, 9)]), \
             patch.object(IndiAllskyImageViewer, "getDays", lambda self, *a, **k: [(19, 19)]), \
             patch.object(IndiAllskyImageViewer, "getHours", empty_func):
            res = client.post(
                "/indi-allsky/ajax/imageviewer",
                json={"CAMERA_ID": 1, "YEAR_SELECT": 2026}
            )
            assert res.status_code == 200
            assert res.json["HOUR_SELECT"] == []

        # 7. No filters (empty DB)
        with patch.object(IndiAllskyImageViewer, "getYears", empty_func):
            res_none = client.post(
                "/indi-allsky/ajax/imageviewer",
                json={"CAMERA_ID": 1}
            )
            assert res_none.status_code == 200

        # 8. No filters (valid hierarchy)
        with patch.object(IndiAllskyImageViewer, "getYears", lambda self, *a, **k: [(2026, 2026)]), \
             patch.object(IndiAllskyImageViewer, "getMonths", lambda self, *a, **k: [(9, 9)]), \
             patch.object(IndiAllskyImageViewer, "getDays", lambda self, *a, **k: [(19, 19)]), \
             patch.object(IndiAllskyImageViewer, "getHours", lambda self, *a, **k: [(12, 12)]), \
             patch.object(IndiAllskyImageViewer, "getImages", lambda self, *a, **k: [{"id": 1}]):
            res_all = client.post(
                "/indi-allsky/ajax/imageviewer",
                json={"CAMERA_ID": 1}
            )
            assert res_all.status_code == 200
            assert res_all.json["IMAGE_DATA"] == [{"id": 1}]


def test_json_panorama_loop_dimension_filtering(flask_app, system_db):
    client = flask_app.test_client()
    now = datetime(2026, 9, 19, 12, 0, 0)

    with flask_app.app_context():
        p1 = IndiAllSkyDbPanoramaImageTable(
            camera_id=1,
            filename="/tmp/pano1.jpg",
            createDate=now,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
            night=True,
            width=1920,
            height=1080,
            exclude=False,
        )
        p2 = IndiAllSkyDbPanoramaImageTable(
            camera_id=1,
            filename="/tmp/pano2.jpg",
            createDate=now + timedelta(minutes=1),
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
            night=True,
            width=1280, # mismatch
            height=720,
            exclude=False,
        )
        db.session.add_all([p1, p2])
        db.session.commit()

    with patch("pathlib.Path.stat") as mock_stat, \
         patch("indi_allsky.flask.models.IndiAllSkyDbPanoramaImageTable.getFilesystemPath", return_value="/tmp/pano1.jpg"):
        mock_stat_res = MagicMock()
        mock_stat_res.st_size = 5000
        mock_stat.return_value = mock_stat_res

        res = client.get(
            "/indi-allsky/js/looppanorama?camera_id=1&source_width=1920&source_height=1080&limit_s=3600"
        )
        assert res.status_code == 200
        assert "image_list" in res.json


def test_fits2jpeg_view_branches(flask_app, system_db):
    client = flask_app.test_client()
    now = datetime(2026, 9, 19, 12, 0, 0)

    with flask_app.app_context():
        fits_img = IndiAllSkyDbFitsImageTable(
            camera_id=1,
            filename="/tmp/test_fits2jpeg.fits",
            createDate=now,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
            night=True,
            width=1000,
            height=1000,
        )
        db.session.add(fits_img)
        db.session.commit()
        fits_id = fits_img.id

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):

        # 1. 404 on nonexistent fits
        res_404 = client.get("/indi-allsky/fits2jpeg?id=99999")
        assert res_404.status_code == 404

        # 2. Error resolving FITS path -> 404
        with patch.object(IndiAllSkyDbFitsImageTable, "getLocalOrCachedPath", side_effect=Exception("resolve error")):
            res_err = client.get(f"/indi-allsky/fits2jpeg?id={fits_id}")
            assert res_err.status_code == 404


def test_ajax_config_view_permissions_and_branches(flask_app, system_db):
    client = flask_app.test_client()

    mock_non_admin = MagicMock()
    mock_non_admin.is_authenticated = True
    mock_non_admin.is_admin = False

    mock_admin = MagicMock()
    mock_admin.is_authenticated = True
    mock_admin.is_admin = True

    mock_form = MagicMock()
    mock_form.validate.return_value = False
    mock_form.errors = {}

    # 1. Non-admin user rejected when LOGIN_DISABLED is False
    with patch.dict(flask_app.config, {"LOGIN_DISABLED": False}), \
         patch("flask_login.utils.current_user", mock_non_admin), \
         patch("indi_allsky.flask.views.current_user", mock_non_admin), \
         patch("indi_allsky.flask.views.IndiAllskyConfigForm", return_value=mock_form):
        res = client.post("/indi-allsky/ajax/config", json={})
        assert res.status_code == 400
        assert "You do not have permission" in str(res.json)

    # 2. Form validation error
    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_admin), \
         patch("indi_allsky.flask.views.IndiAllskyConfigForm", return_value=mock_form):
        res_val = client.post("/indi-allsky/ajax/config", json={"INVALID": 123})
        assert res_val.status_code == 400

    # 3. ASI676MC enable requested when no camera visible
    mock_valid_form = MagicMock()
    mock_valid_form.validate.return_value = True
    mock_valid_form.errors = {}
    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_admin), \
         patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[]), \
         patch("indi_allsky.flask.views.IndiAllskyConfigForm", return_value=mock_valid_form):
        res_asi = client.post("/indi-allsky/ajax/config", json={"IMAGE_ASI676MC_REPAIR__ENABLE": True})
        assert res_asi.status_code == 400


def test_config_view_fitsheaders_and_net_errors(flask_app, system_db):
    from cryptography.fernet import InvalidToken
    client = flask_app.test_client()

    mock_admin = MagicMock()
    mock_admin.is_authenticated = True
    mock_admin.is_admin = True

    # Config with empty fitsheaders, missing leaves, and youtube decryption error
    cfg = {
        "FITSHEADERS": [],
        "YOUTUBE": {"TAGS": ["allsky", "astronomy"]},
        "CCD_CONFIG": {},
    }

    def mock_get_state(key, *args, **kwargs):
        if key == "YOUTUBE_CREDENTIALS":
            raise InvalidToken
        return "1"

    mock_misc_db = MagicMock()
    mock_misc_db.getState.side_effect = mock_get_state

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_admin), \
         patch.object(flask_app, "indi_allsky_config", cfg, create=True), \
         patch("indi_allsky.flask.base_views.miscDb", return_value=mock_misc_db), \
         patch("socket.gethostname", return_value="test-host"), \
         patch("psutil.net_if_addrs", return_value={"eth0": [MagicMock(family=99)]}):
        res = client.get("/indi-allsky/config")
        assert res.status_code == 200


def test_ajax_indiserver_and_timelapsegen_branches(flask_app, system_db):
    from indi_allsky.flask.models import (
        IndiAllSkyDbVideoTable,
        IndiAllSkyDbKeogramTable,
        IndiAllSkyDbStarTrailsTable,
        IndiAllSkyDbStarTrailsVideoTable,
        IndiAllSkyDbPanoramaVideoTable,
    )
    client = flask_app.test_client()
    now = datetime(2026, 9, 19, 12, 0, 0)

    mock_admin = MagicMock()
    mock_admin.is_authenticated = True
    mock_admin.is_admin = True

    mock_non_admin = MagicMock()
    mock_non_admin.is_authenticated = True
    mock_non_admin.is_admin = False

    # 1. AjaxIndiServerChangeView non-admin & validation
    with patch.dict(flask_app.config, {"LOGIN_DISABLED": False}), \
         patch("flask_login.utils.current_user", mock_non_admin), \
         patch("indi_allsky.flask.views.current_user", mock_non_admin):
        res = client.post("/indi-allsky/ajax/indiserver", json={})
        assert res.status_code == 400

    # 2. AjaxTimelapseGeneratorView non-admin & non-admin network
    with patch.dict(flask_app.config, {"LOGIN_DISABLED": False}), \
         patch("flask_login.utils.current_user", mock_non_admin), \
         patch("indi_allsky.flask.views.current_user", mock_non_admin):
        res_tg = client.post("/indi-allsky/ajax/generate", json={})
        assert res_tg.status_code == 400

    # 3. AjaxTimelapseGeneratorView delete_video_k_st_p action
    with flask_app.app_context():
        vid = IndiAllSkyDbVideoTable(
            camera_id=1,
            filename="/tmp/vid.mp4",
            createDate=now,
            dayDate=now.date(),
            night=True,
        )
        keo = IndiAllSkyDbKeogramTable(
            camera_id=1,
            filename="/tmp/keo.jpg",
            createDate=now,
            dayDate=now.date(),
            night=True,
        )
        st = IndiAllSkyDbStarTrailsTable(
            camera_id=1,
            filename="/tmp/st.jpg",
            createDate=now,
            dayDate=now.date(),
            night=True,
        )
        stv = IndiAllSkyDbStarTrailsVideoTable(
            camera_id=1,
            filename="/tmp/stv.mp4",
            createDate=now,
            dayDate=now.date(),
            night=True,
        )
        pv = IndiAllSkyDbPanoramaVideoTable(
            camera_id=1,
            filename="/tmp/pv.mp4",
            createDate=now,
            dayDate=now.date(),
            night=True,
        )
        db.session.add_all([vid, keo, st, stv, pv])
        db.session.commit()

    mock_tl_form = MagicMock()
    mock_tl_form.validate.return_value = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_admin), \
         patch("indi_allsky.flask.views.IndiAllskyTimelapseGeneratorForm", return_value=mock_tl_form), \
         patch("indi_allsky.flask.views.AjaxTimelapseGeneratorView.verify_admin_network", return_value=True), \
         patch.object(IndiAllSkyDbVideoTable, "deleteAsset"), \
         patch.object(IndiAllSkyDbKeogramTable, "deleteAsset"), \
         patch.object(IndiAllSkyDbStarTrailsTable, "deleteAsset"), \
         patch.object(IndiAllSkyDbStarTrailsVideoTable, "deleteAsset"), \
         patch.object(IndiAllSkyDbPanoramaVideoTable, "deleteAsset"):
        res_del = client.post(
            "/indi-allsky/ajax/generate",
            json={
                "CAMERA_ID": 1,
                "ACTION_SELECT": "delete_video_k_st_p",
                "DAY_SELECT": "2026-09-19_night",
            }
        )
        assert res_del.status_code == 200

