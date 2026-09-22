import os
import pty
import subprocess
import select
import json
import dbus
import wtforms
import simple_websocket
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky.exceptions import ConfigSaveException, NotFound
from indi_allsky.flask.models import (
    db,
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbUserTable,
)
from indi_allsky.flask.views import (
    WsShellView,
    AjaxNetworkManagerView,
    AjaxConfigView,
)


def test_ws_terminal_view_lifecycle_and_exception_handling(flask_app, system_db):
    """Test WsShellView websocket loop, input/resize messages, connection errors and kill fallback."""
    view = WsShellView()

    mock_ws = MagicMock()
    # Messages: input, resize, invalid JSON, then disconnect
    mock_ws.receive.side_effect = [
        json.dumps({"type": "input", "data": "ls\n"}),
        json.dumps({"type": "resize", "cols": 120, "rows": 40}),
        "invalid json",
        None,
    ]

    mock_proc = MagicMock()
    # proc.wait raises TimeoutError on terminate, forcing kill branch
    mock_proc.wait.side_effect = Exception("Process timeout")

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    with patch("pty.openpty", return_value=(100, 101)), \
         patch("subprocess.Popen", return_value=mock_proc), \
         patch("os.write") as mock_write, \
         patch("os.read", side_effect=[b"terminal output", b""]), \
         patch("os.close") as mock_close, \
         patch("select.select", return_value=([100], [], [])), \
         patch("indi_allsky.flask.views.set_winsize"), \
         patch("indi_allsky.flask.views.current_user", mock_user), \
         patch.object(view, "verify_admin_network", return_value=True):
        with flask_app.test_request_context("/indi-allsky/ws/terminal"):
            with patch("simple_websocket.Server.accept", return_value=mock_ws):
                res = view.dispatch_request()
                assert res == ""
                mock_write.assert_called_with(100, b"ls\n")
                mock_proc.kill.assert_called()


def test_network_manager_dbus_exception_and_priority_branches(flask_app, system_db):
    """Test AjaxNetworkManagerView DBus error branches in priority, powersave, scan, and connect."""
    view = AjaxNetworkManagerView()

    with flask_app.test_request_context("/indi-allsky/ajax/network"):
        # 1. incrementConnectionPriority DBusException on get_object
        mock_bus = MagicMock()
        mock_bus.get_object.side_effect = dbus.exceptions.DBusException("Bus unavailable")
        with patch("indi_allsky.flask.views.dbus.SystemBus", return_value=mock_bus):
            res = view.incrementConnectionPriority("uuid-123")
            assert res[1] == 400
            assert "Bus unavailable" in res[0].json["failure-message"]

        # 2. incrementConnectionPriority with missing/invalid autoconnect-priority
        mock_bus_ok = MagicMock()
        mock_nm_settings = MagicMock()
        mock_bus_ok.get_object.return_value = mock_nm_settings
        with patch("indi_allsky.flask.views.dbus.SystemBus", return_value=mock_bus_ok), \
             patch.object(view, "getSettingsPath", return_value="/settings/path"):
            mock_settings_conn = MagicMock()
            # autoconnect-priority is None (TypeError branch)
            mock_settings_conn.GetSettings.return_value = {"connection": {"autoconnect-priority": None}}
            mock_settings_conn.Update.side_effect = dbus.exceptions.DBusException("Update failed")
            with patch("indi_allsky.flask.views.dbus.Interface", return_value=mock_settings_conn), \
                 patch("indi_allsky.flask.views.time.sleep"):
                res = view.incrementConnectionPriority("uuid-123")
                assert res[1] == 400
                assert "Update failed" in res[0].json["failure-message"]

        # 3. setPowersave DBusException
        with patch("indi_allsky.flask.views.dbus.SystemBus", return_value=mock_bus):
            res = view.setPowersave("uuid-123", powersave=True)
            assert res[1] == 400
            assert "Bus unavailable" in res[0].json["failure-message"]

        # 4. setPowersave update DBusException
        with patch("indi_allsky.flask.views.dbus.SystemBus", return_value=mock_bus_ok), \
             patch.object(view, "getSettingsPath", return_value="/settings/path"):
            mock_settings_conn = MagicMock()
            mock_settings_conn.GetSettings.return_value = {
                "connection": {"type": "802-11-wireless"},
                "802-11-wireless": {"powersave": 2},
            }
            mock_settings_conn.Update.side_effect = dbus.exceptions.DBusException("Powersave update error")
            with patch("indi_allsky.flask.views.dbus.Interface", return_value=mock_settings_conn), \
                 patch("indi_allsky.flask.views.time.sleep"):
                res = view.setPowersave("uuid-123", powersave=True)
                assert res[1] == 400
                assert "Powersave update error" in res[0].json["failure-message"]

        # 5. scanAPs DBusException on RequestScan and GetAccessPoints
        mock_device = MagicMock()
        mock_device.RequestScan.side_effect = dbus.exceptions.DBusException("Scan request failed")
        with patch("indi_allsky.flask.views.dbus.SystemBus", return_value=mock_bus_ok), \
             patch("indi_allsky.flask.views.dbus.Interface", return_value=mock_device):
            res = view.scanAPs("wlan0")
            assert res[1] == 400
            assert "Scan request failed" in res[0].json["failure-message"]

            mock_device.RequestScan.side_effect = None
            mock_device.GetAccessPoints.side_effect = dbus.exceptions.DBusException("Get APs failed")
            with patch("indi_allsky.flask.views.time.sleep"):
                res = view.scanAPs("wlan0")
                assert res[1] == 400
                assert "Get APs failed" in res[0].json["failure-message"]

        # 6. connectAP DBusException on AddAndActivateConnection and timeout
        mock_manager = MagicMock()
        mock_manager.GetDeviceByIpIface.return_value = "/device/path"
        mock_manager.AddAndActivateConnection.side_effect = dbus.exceptions.DBusException("Add connection failed")
        with patch("indi_allsky.flask.views.dbus.SystemBus", return_value=mock_bus_ok), \
             patch("indi_allsky.flask.views.dbus.Interface", return_value=mock_manager):
            res = view.connectAP("wlan0", "/ap/path", "secretpsk", 10, 3)
            assert res[1] == 400
            assert "Add connection failed" in res[0].json["failure-message"]

            mock_manager.AddAndActivateConnection.side_effect = None
            mock_manager.AddAndActivateConnection.return_value = ("/settings/path", "/conn/path")
            mock_conn_props = MagicMock()
            mock_conn_props.Get.return_value = 1  # Not active
            with patch("indi_allsky.flask.views.dbus.Interface", side_effect=[mock_manager, mock_conn_props]), \
                 patch("indi_allsky.flask.views.time.sleep"):
                res = view.connectAP("wlan0", "/ap/path", "secretpsk", 10, 3)
                assert res[1] == 400
                assert "Wireless connection failed" in res[0].json["failure-message"]

        # 7. createHotspot DBusException
        with patch("indi_allsky.flask.views.dbus.SystemBus", return_value=mock_bus):
            res = view.createHotspot("wlan0", "HotspotSSID", "bg", "secretpsk")
            assert res[1] == 400
            assert "Bus unavailable" in res[0].json["failure-message"]


from tests.flask.views.test_config_and_controls import get_base_payload


def test_ajax_config_view_roi_and_save_branches(flask_app, system_db):
    """Test AjaxConfigView ROI arrays, config save exception, and allskymap ping branch."""
    client = flask_app.test_client()
    with flask_app.app_context():
        user = IndiAllSkyDbUserTable.query.filter_by(admin=True).first()
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_admin = True
        mock_user.username = user.username if user else "admin"

        with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
             patch("indi_allsky.flask.views.current_user", mock_user), \
             patch.object(wtforms.Form, "validate", lambda self, extra_validators=None: True):

            # Base valid form payload with non-zero ROIs and allskymap enabled
            payload = get_base_payload()
            payload.update({
                "CAMERA_ID": 1,
                "ADU_ROI_X1": 10,
                "ADU_ROI_Y1": 10,
                "ADU_ROI_X2": 50,
                "ADU_ROI_Y2": 50,
                "SQM_ROI_X1": 20,
                "SQM_ROI_Y1": 20,
                "SQM_ROI_X2": 60,
                "SQM_ROI_Y2": 60,
                "IMAGE_CROP_ROI_X1": 10,
                "IMAGE_CROP_ROI_Y1": 10,
                "IMAGE_CROP_ROI_X2": 100,
                "IMAGE_CROP_ROI_Y2": 100,
                "TEXT_PROPERTIES__FONT_COLOR": "255,255,255",
                "CARDINAL_DIRS__FONT_COLOR": "255,255,255",
                "ORB_PROPERTIES__SUN_COLOR": "255,200,0",
                "ORB_PROPERTIES__MOON_COLOR": "200,200,200",
                "IMAGE_BORDER__COLOR": "0,0,0",
                "LIGHTGRAPH_OVERLAY__DAY_COLOR": "255,255,255",
                "LIGHTGRAPH_OVERLAY__DUSK_COLOR": "255,255,255",
                "LIGHTGRAPH_OVERLAY__NIGHT_COLOR": "0,0,0",
                "LIGHTGRAPH_OVERLAY__MOONMODE_COLOR": "100,100,100",
                "LIGHTGRAPH_OVERLAY__HOUR_COLOR": "150,150,150",
                "LIGHTGRAPH_OVERLAY__BORDER_COLOR": "200,200,200",
                "LIGHTGRAPH_OVERLAY__NOW_COLOR": "255,0,0",
                "LIGHTGRAPH_OVERLAY__FONT_COLOR": "150,150,150",
                "YOUTUBE__TAGS_STR": "allsky, astronomy",
                "ALLSKYMAP__ENABLE": True,
                "RELOAD_ON_SAVE": False,
            })

            # 1. ConfigSaveException (400)
            with patch("indi_allsky.config.IndiAllSkyConfig.save", side_effect=ConfigSaveException("Cannot write config")):
                res = client.post("/indi-allsky/ajax/config", json=payload)
                assert res.status_code == 400
                assert b"Cannot write config" in res.data

            # 2. Successful save with AllskyMap ping
            with patch("indi_allsky.config.IndiAllSkyConfig.save"), \
                 patch("indi_allsky.allsky_map.send_allsky_map_ping", return_value=(True, "Ping Success")):
                res = client.post("/indi-allsky/ajax/config", json=payload)
                assert res.status_code == 200
                assert b"Allsky Map Ping: Success" in res.data

