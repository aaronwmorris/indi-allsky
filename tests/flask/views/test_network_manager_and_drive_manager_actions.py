from unittest.mock import MagicMock, patch
import pytest
from flask import json
import dbus

from indi_allsky.exceptions import NotFound
from indi_allsky.flask.views import (
    NetworkManagerView,
    AjaxNetworkManagerView,
    DriveManagerView,
    AjaxDriveManagerView,
)


def test_network_manager_activate_deactivate_delete(flask_app, system_db):
    """Test AjaxNetworkManagerView activate, deactivate, and delete connection branches."""
    view = AjaxNetworkManagerView()
    mock_bus = MagicMock()
    mock_manager = MagicMock()

    mock_settings_conn = MagicMock()
    mock_settings_conn.GetSettings.return_value = {"connection": {"type": "802-11-wireless"}}

    # 1. ActivateConnection DBusException (400)
    mock_manager.ActivateConnection.side_effect = dbus.exceptions.DBusException("Activation failed")
    with patch("dbus.SystemBus", return_value=mock_bus):
        with patch("indi_allsky.flask.views.AjaxNetworkManagerView.getSettingsPath", return_value="/path/s1"):
            with patch("dbus.Interface", side_effect=[mock_settings_conn, mock_settings_conn, mock_manager]):
                with flask_app.test_request_context():
                    resp, code = view.activateConnection("uuid-1")
                    assert code == 400
                    data = json.loads(resp.data)
                    assert "D-Bus Exception" in data["failure-message"]

    # 2. ActivateConnection timeout (400)
    mock_manager.ActivateConnection.side_effect = None
    mock_manager.ActivateConnection.return_value = "/active/1"
    mock_props = MagicMock()
    mock_props.Get.return_value = 100  # Unknown state
    with patch("dbus.SystemBus", return_value=mock_bus):
        with patch("indi_allsky.flask.views.AjaxNetworkManagerView.getSettingsPath", return_value="/path/s1"):
            with patch("dbus.Interface", side_effect=[mock_settings_conn, mock_settings_conn, mock_manager, mock_props]):
                with patch("time.sleep"):
                    with flask_app.test_request_context():
                        resp, code = view.activateConnection("uuid-1")
                        assert code == 400
                        data = json.loads(resp.data)
                        assert "Connection failed to activate" in data["failure-message"]

    # 3. DeactivateConnection: active connection not found (400)
    with patch("dbus.SystemBus", return_value=mock_bus):
        with patch("indi_allsky.flask.views.AjaxNetworkManagerView.getSettingsPath", return_value="/path/s1"):
            with patch("indi_allsky.flask.views.AjaxNetworkManagerView.getActiveConnection", side_effect=NotFound):
                with flask_app.test_request_context():
                    resp, code = view.deactivateConnection("uuid-1")
                    assert code == 400
                    data = json.loads(resp.data)
                    assert "Active connection not found" in data["failure-message"]

    # 4. DeactivateConnection: non-wireless/ethernet (400)
    mock_vpn_settings = MagicMock()
    mock_vpn_settings.GetSettings.return_value = {"connection": {"type": "vpn"}}
    with patch("dbus.SystemBus", return_value=mock_bus):
        with patch("indi_allsky.flask.views.AjaxNetworkManagerView.getSettingsPath", return_value="/path/s1"):
            with patch("indi_allsky.flask.views.AjaxNetworkManagerView.getActiveConnection", return_value="/act/1"):
                with patch("dbus.Interface", side_effect=[mock_vpn_settings, mock_vpn_settings]):
                    with flask_app.test_request_context():
                        resp, code = view.deactivateConnection("uuid-1")
                        assert code == 400
                        data = json.loads(resp.data)
                        assert "Only Ethernet and Wireless" in data["failure-message"]

    # 5. DeleteConnection: active connection cannot be deleted (400)
    with patch("dbus.SystemBus", return_value=mock_bus):
        with patch("indi_allsky.flask.views.AjaxNetworkManagerView.getSettingsPath", return_value="/path/s1"):
            with patch("indi_allsky.flask.views.AjaxNetworkManagerView.getActiveConnection", return_value="/act/1"):
                with flask_app.test_request_context():
                    resp, code = view.deleteConnection("uuid-1")
                    assert code == 400
                    data = json.loads(resp.data)
                    assert "Cannot delete active connections" in data["failure-message"]


def test_network_manager_priority_autostart_powersave(flask_app, system_db):
    """Test autostart, priority increment/decrement, and powersave configuration."""
    view = AjaxNetworkManagerView()
    mock_bus = MagicMock()

    # 1. Autostart Update DBusException (400)
    mock_settings_conn = MagicMock()
    mock_settings_conn.GetSettings.return_value = {"connection": {"autoconnect": False}}
    mock_settings_conn.Update.side_effect = dbus.exceptions.DBusException("Update denied")
    with patch("dbus.SystemBus", return_value=mock_bus):
        with patch("indi_allsky.flask.views.AjaxNetworkManagerView.getSettingsPath", return_value="/path/s1"):
            with patch("dbus.Interface", side_effect=[mock_settings_conn, mock_settings_conn]):
                with flask_app.test_request_context():
                    resp, code = view.setAutostartConnection("uuid-1", True)
                    assert code == 400
                    data = json.loads(resp.data)
                    assert "Configure Failed" in data["failure-message"]

    # 2. Priority missing / invalid key fallback to 0 and decrement (200)
    mock_settings_conn = MagicMock()
    mock_settings_conn.GetSettings.return_value = {"connection": {}}
    mock_settings_conn.Update.side_effect = None
    with patch("dbus.SystemBus", return_value=mock_bus):
        with patch("indi_allsky.flask.views.AjaxNetworkManagerView.getSettingsPath", return_value="/path/s1"):
            with patch("dbus.Interface", side_effect=[mock_settings_conn, mock_settings_conn]):
                with patch("time.sleep"):
                    with flask_app.test_request_context():
                        resp = view.decrementConnectionPriority("uuid-1")
                        data = json.loads(resp.data)
                        assert data["success-message"] == "Priority Updated"

    # 3. Powersave on non-wireless connection (400)
    mock_settings_conn = MagicMock()
    mock_settings_conn.GetSettings.return_value = {"connection": {"type": "802-3-ethernet"}}
    with patch("dbus.SystemBus", return_value=mock_bus):
        with patch("indi_allsky.flask.views.AjaxNetworkManagerView.getSettingsPath", return_value="/path/s1"):
            with patch("dbus.Interface", side_effect=[mock_settings_conn, mock_settings_conn]):
                with flask_app.test_request_context():
                    resp, code = view.setPowersave("uuid-1", powersave=True)
                    assert code == 400
                    data = json.loads(resp.data)
                    assert "Powersave only valid for wifi" in data["failure-message"]


def test_network_manager_scan_wifi_and_ap_connect(flask_app, system_db):
    """Test scanAPs frequencies and connectAP/createHotspot branches."""
    view = AjaxNetworkManagerView()
    mock_bus = MagicMock()

    # 1. Scan WiFi with WiFi disabled -> enables WiFi, scans APs on 2.4, 5, and 6 GHz
    mock_manager_props = MagicMock()
    mock_manager_props.Get.return_value = False  # wifi_enabled = False

    mock_device = MagicMock()
    mock_device.GetAccessPoints.return_value = ["/ap/1", "/ap/2", "/ap/3"]

    ap1_props = MagicMock()
    ap1_props.Get.side_effect = lambda iface, prop: {
        "Ssid": [84, 101, 115, 116, 54],  # "Test6"
        "Strength": 80,
        "Frequency": 6100,
        "HwAddress": "00:11:22:33:44:55",
    }[prop]

    ap2_props = MagicMock()
    ap2_props.Get.side_effect = lambda iface, prop: {
        "Ssid": [84, 101, 115, 116, 53],  # "Test5"
        "Strength": 70,
        "Frequency": 5200,
        "HwAddress": "00:11:22:33:44:56",
    }[prop]

    ap3_props = MagicMock()
    ap3_props.Get.side_effect = lambda iface, prop: {
        "Ssid": [84, 101, 115, 116, 50],  # "Test2"
        "Strength": 90,
        "Frequency": 2412,
        "HwAddress": "00:11:22:33:44:57",
    }[prop]

    with patch("dbus.SystemBus", return_value=mock_bus):
        with patch("dbus.Interface", side_effect=[MagicMock(), mock_manager_props, mock_device, ap1_props, ap2_props, ap3_props]):
            with patch("time.sleep"):
                with flask_app.test_request_context():
                    resp = view.scanAPs("wlan0")
                    data = json.loads(resp.data)
                    assert data["success-message"] == "Scan Successful"
                    assert len(data["data"]) == 3
                    assert "6 GHz" in data["data"][1]["desc"] or "6 GHz" in data["data"][0]["desc"]

    # 2. connectAP password failure during active loop (deletes settings, returns 400)
    mock_manager = MagicMock()
    mock_manager.AddAndActivateConnection.return_value = ("/settings/1", "/active/1")
    mock_conn_props = MagicMock()
    mock_conn_props.Get.side_effect = dbus.exceptions.DBusException("Secrets invalid")
    mock_settings = MagicMock()

    with patch("dbus.SystemBus", return_value=mock_bus):
        with patch("dbus.Interface", side_effect=[mock_manager, mock_conn_props, mock_settings]):
            with patch("time.sleep"):
                with flask_app.test_request_context():
                    resp, code = view.connectAP("wlan0", "/ap/1", "badpsk", 0, 3)
                    assert code == 400
                    data = json.loads(resp.data)
                    assert "PSK may be incorrect" in data["failure-message"]
                    mock_settings.Delete.assert_called_once()

    # 3. createHotspot nosecurity=True (200)
    mock_settings_mgr = MagicMock()
    with patch("dbus.SystemBus", return_value=mock_bus):
        with patch("dbus.Interface", side_effect=[mock_manager, mock_settings_mgr]):
            with patch("time.sleep"):
                with flask_app.test_request_context():
                    resp = view.createHotspot("wlan0", "OpenHotspot", "bg", "", nosecurity=True)
                    data = json.loads(resp.data)
                    assert data["success-message"] == "Hotspot Created"


def test_drive_manager_views_and_ajax_actions(flask_app, system_db):
    """Test DriveManagerView udisks2 detection and AjaxDriveManagerView actions."""
    # 1. DriveManagerView DBusException -> udisks2_installed = False
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    client = flask_app.test_client()
    with flask_app.app_context():
        with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
             patch("indi_allsky.flask.views.current_user", mock_user):
            with patch("dbus.SystemBus.get_object", side_effect=dbus.exceptions.DBusException("No udisks2")):
                res = client.get("/indi-allsky/drives")
                assert res.status_code == 200

    # 2. AjaxDriveManagerView actions
    view = AjaxDriveManagerView()
    mock_bus = MagicMock()
    mock_obj_mgr = MagicMock()

    # getMetadata: finds drive, formats data with TimeMediaDetected = 0 vs > 0
    mock_obj_mgr.GetManagedObjects.return_value = {
        "/org/freedesktop/UDisks2/drives/drive1": {},
        "/other/path": {},
    }
    mock_drive_props = MagicMock()
    mock_drive_props.GetAll.return_value = {
        "Id": "drive1",
        "Vendor": "Samsung",
        "Model": "SSD",
        "Size": 100000000000,
        "ConnectionBus": "usb",
        "Serial": "12345",
        "Media": "flash",
        "MediaCompatibility": ["flash"],
        "CanPowerOff": True,
        "Removable": True,
        "Ejectable": False,
        "TimeDetected": 1700000000000000,
        "TimeMediaDetected": 0,
    }

    with patch("dbus.SystemBus", return_value=mock_bus):
        with patch("dbus.Interface", side_effect=[mock_obj_mgr, mock_drive_props]):
            with flask_app.test_request_context():
                resp = view.getMetadata("drive1")
                data = json.loads(resp.data)
                assert data["drive_data"][1][2] == "Samsung"
                assert data["drive_data"][12][2] == ""

    # powerOffDrive: CanPowerOff is False (400)
    mock_drive_props.GetAll.return_value["CanPowerOff"] = False
    with patch("dbus.SystemBus", return_value=mock_bus):
        with patch("dbus.Interface", side_effect=[mock_obj_mgr, mock_drive_props]):
            with flask_app.test_request_context():
                resp, code = view.powerOffDrive("drive1")
                assert code == 400
                data = json.loads(resp.data)
                assert "Drive cannot be powered off" in data["failure-message"]

    # unmountDevice: protected filesystem (400)
    mock_block_obj_mgr = MagicMock()
    mock_block_obj_mgr.GetManagedObjects.return_value = {
        "/org/freedesktop/UDisks2/block_devices/sda1": {
            "org.freedesktop.UDisks2.Filesystem": {
                "MountPoints": [[ord(c) for c in "/var\x00"]],
            },
        },
    }
    mock_block_props = MagicMock()
    mock_block_props.GetAll.return_value = {"Id": "sda1"}

    with patch("dbus.SystemBus", return_value=mock_bus):
        with patch("dbus.Interface", side_effect=[mock_block_obj_mgr, mock_block_props]):
            with flask_app.test_request_context():
                resp, code = view.unmountDevice("sda1")
                assert code == 400
                data = json.loads(resp.data)
                assert "Not allowed to unmount protected filesystem" in data["failure-message"]

    # mountDevice: already mounted (400)
    mock_block_obj_mgr.GetManagedObjects.return_value = {
        "/org/freedesktop/UDisks2/block_devices/sdb1": {
            "org.freedesktop.UDisks2.Filesystem": {
                "MountPoints": ["/mnt/1", "/mnt/2"],
            },
        },
    }
    mock_block_props.GetAll.return_value = {"Id": "sdb1"}
    with patch("dbus.SystemBus", return_value=mock_bus):
        with patch("dbus.Interface", side_effect=[mock_block_obj_mgr, mock_block_props]):
            with flask_app.test_request_context():
                resp, code = view.mountDevice("sdb1")
                assert code == 400
                data = json.loads(resp.data)
                assert "Filesystem already mounted" in data["failure-message"]
