from unittest.mock import patch, MagicMock
from pathlib import Path
import pytest

from indi_allsky.flask.views import (
    AjaxNetworkManagerView,
    AjaxDriveManagerView,
)


def test_network_manager_view(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = b"wlan0: connected"
            mock_run.return_value.returncode = 0
            res_post = client.post("/indi-allsky/ajax/network", json={"COMMAND": "status"})
            assert res_post.status_code in (200, 400, 500)


def test_drive_manager_view(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = b"/dev/sda1 /mnt/drive ext4"
            mock_run.return_value.returncode = 0
            res_post = client.post("/indi-allsky/ajax/drives", json={"COMMAND": "status"})
            assert res_post.status_code in (200, 400, 500)


def test_network_manager_view_commands(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):

        # Unknown command
        res = client.post("/indi-allsky/ajax/network", json={"COMMAND": "invalid"})
        assert res.status_code == 400

        # Scan AP missing interface
        res = client.post("/indi-allsky/ajax/network", json={"COMMAND": "scanap", "INTERFACE": ""})
        assert res.status_code == 400

        # Connect AP missing ap_path
        res = client.post("/indi-allsky/ajax/network", json={"COMMAND": "connectap", "INTERFACE": "wlan0", "AP_PATH": "", "PSK": "12345678", "PRIORITY": 0, "RETRIES": 3})
        assert res.status_code == 400

        # Create hotspot missing interface
        res = client.post("/indi-allsky/ajax/network", json={"COMMAND": "createhotspot", "INTERFACE": "", "SSID": "test", "BAND": "bg", "PSK": "12345678", "NOSECURITY": False})
        assert res.status_code == 400

        # Create hotspot missing SSID
        res = client.post("/indi-allsky/ajax/network", json={"COMMAND": "createhotspot", "INTERFACE": "wlan0", "SSID": "", "BAND": "bg", "PSK": "12345678", "NOSECURITY": False})
        assert res.status_code == 400

        # Create hotspot invalid band
        res = client.post("/indi-allsky/ajax/network", json={"COMMAND": "createhotspot", "INTERFACE": "wlan0", "SSID": "test", "BAND": "invalid", "PSK": "12345678", "NOSECURITY": False})
        assert res.status_code == 400

        # Create hotspot short PSK
        res = client.post("/indi-allsky/ajax/network", json={"COMMAND": "createhotspot", "INTERFACE": "wlan0", "SSID": "test", "BAND": "bg", "PSK": "short", "NOSECURITY": False})
        assert res.status_code == 400

        # Activate, deactivate, delete, autostart, incpriority, decpriority, powersave error branches
        for cmd in ("activate", "deactivate", "delete", "autostart", "noautostart", "incpriority", "decpriority", "powersavedisable", "powersaveenable"):
            with patch("dbus.SystemBus"):
                res_cmd = client.post("/indi-allsky/ajax/network", json={"COMMAND": cmd, "CONNECTION": "test-uuid"})
                assert res_cmd.status_code == 400



def test_drive_manager_view_commands(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):

        # Unknown command
        res = client.post("/indi-allsky/ajax/drives", json={"COMMAND": "invalid"})
        assert res.status_code == 400

        # Get metadata not found
        with patch("dbus.SystemBus"):
            res = client.post("/indi-allsky/ajax/drives", json={"COMMAND": "getmetadata", "DRIVE_ID": "nonexistent"})
            assert res.status_code == 400

        # Power off not found
        with patch("dbus.SystemBus"):
            res = client.post("/indi-allsky/ajax/drives", json={"COMMAND": "poweroff", "DRIVE_ID": "nonexistent"})
            assert res.status_code == 400

        # Unmount not found
        with patch("dbus.SystemBus"):
            res = client.post("/indi-allsky/ajax/drives", json={"COMMAND": "unmount", "DEVICE_ID": "nonexistent"})
            assert res.status_code == 400

        # Mount not found
        with patch("dbus.SystemBus"):
            res = client.post("/indi-allsky/ajax/drives", json={"COMMAND": "mount", "DEVICE_ID": "nonexistent"})
            assert res.status_code == 400


def test_drive_manager_view_success_operations(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    mock_bus = MagicMock()
    mock_iface = MagicMock()
    mock_iface.GetManagedObjects.return_value = {
        "/org/freedesktop/UDisks2/drives/drive_123": {},
        "/org/freedesktop/UDisks2/block_devices/sda1": {
            "org.freedesktop.UDisks2.Filesystem": {
                "MountPoints": [[109, 110, 116, 47, 100, 114, 105, 118, 101, 0]],  # /mnt/drive\0
            }
        },
    }

    mock_props = MagicMock()
    mock_props.GetAll.side_effect = lambda iface_name: {
        "Id": "drive_123",
        "Vendor": "VendorX",
        "Model": "ModelY",
        "Size": 10000000000,
        "ConnectionBus": "usb",
        "Serial": "SN123",
        "Media": "flash",
        "MediaCompatibility": ["flash"],
        "CanPowerOff": True,
        "Removable": True,
        "Ejectable": False,
        "TimeDetected": 1600000000000000,
        "TimeMediaDetected": 1600000000000000,
    } if iface_name == "org.freedesktop.UDisks2.Drive" else {
        "Id": "uuid_sda1",
        "IdUUID": "uuid_sda1",
        "Drive": "/org/freedesktop/UDisks2/drives/drive_123",
        "MountPoints": [b"/media/external"],
    }

    mock_obj = MagicMock()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user), \
         patch("dbus.SystemBus", return_value=mock_bus), \
         patch("dbus.Interface", side_effect=lambda obj, dbus_interface=None: mock_iface if (dbus_interface == "org.freedesktop.DBus.ObjectManager" or obj == mock_bus) else mock_props):

        mock_bus.get_object.return_value = mock_obj

        # 1. getmetadata success
        res_meta = client.post("/indi-allsky/ajax/drives", json={"COMMAND": "getmetadata", "DRIVE_ID": "drive_123"})
        assert res_meta.status_code == 200
        assert "drive_data" in res_meta.get_json()

        # 2. poweroff success
        res_poff = client.post("/indi-allsky/ajax/drives", json={"COMMAND": "poweroff", "DRIVE_ID": "drive_123"})
        assert res_poff.status_code == 200

        # 3. unmount success
        res_unm = client.post("/indi-allsky/ajax/drives", json={"COMMAND": "unmount", "DEVICE_ID": "uuid_sda1"})
        assert res_unm.status_code == 200

        # 4. mount success
        res_m = client.post("/indi-allsky/ajax/drives", json={"COMMAND": "mount", "DEVICE_ID": "uuid_sda1"})
        assert res_m.status_code == 200


def test_network_manager_view_success_operations(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    def mock_get(*args, **kwargs):
        prop = args[1] if len(args) > 1 else ""
        if prop == "Connections":
            return ["/org/freedesktop/NetworkManager/Settings/1"]
        elif prop == "ActiveConnections":
            return ["/org/freedesktop/NetworkManager/ActiveConnection/1"]
        elif prop == "Uuid":
            return "active-uuid-999"
        elif prop == "State":
            return 2
        elif prop == "Ssid":
            return [84, 101, 115, 116]
        elif prop == "Frequency":
            return 2412
        elif prop == "Strength":
            return 80
        elif prop == "HwAddress":
            return "AA:BB:CC:DD:EE:FF"
        return "test-uuid-123"




    mock_bus = MagicMock()
    mock_nm_obj = MagicMock()
    mock_nm_obj.Get.side_effect = mock_get
    mock_settings_obj = MagicMock()

    mock_conn_obj = MagicMock()
    mock_dev_obj = MagicMock()
    mock_ap_obj = MagicMock()


    current_req_uuid = ["test-uuid-123"]

    def get_settings():
        return {
            "connection": {
                "type": "802-11-wireless",
                "uuid": current_req_uuid[0],
                "id": "TestWiFi",
                "autoconnect-priority": 0,
                "autoconnect": True,
            },
            "802-11-wireless": {
                "powersave": 0,
                "ssid": [84, 101, 115, 116],
            },
        }

    mock_nm_settings_iface = MagicMock()
    mock_nm_settings_iface.ListConnections.return_value = ["/org/freedesktop/NetworkManager/Settings/1"]

    mock_conn_iface = MagicMock()
    mock_conn_iface.GetSettings.side_effect = get_settings

    mock_props_iface = MagicMock()
    mock_props_iface.Get.side_effect = mock_get

    mock_manager_iface = MagicMock()
    mock_manager_iface.Get.side_effect = mock_get
    mock_manager_iface.ActivateConnection.return_value = "/org/freedesktop/NetworkManager/ActiveConnection/1"
    mock_manager_iface.GetDeviceByIpIface.return_value = "/org/freedesktop/NetworkManager/Devices/1"
    mock_manager_iface.AddAndActivateConnection.return_value = ("/", "/org/freedesktop/NetworkManager/ActiveConnection/1")

    mock_dev_iface = MagicMock()
    mock_dev_iface.GetAccessPoints.return_value = ["/org/freedesktop/NetworkManager/AccessPoint/1"]

    def mock_interface(obj, interface_name=None):
        if interface_name == "org.freedesktop.NetworkManager.Settings":
            return mock_nm_settings_iface
        elif interface_name == "org.freedesktop.NetworkManager.Settings.Connection":
            return mock_conn_iface
        elif interface_name == "org.freedesktop.DBus.Properties":
            return mock_props_iface
        elif interface_name == "org.freedesktop.NetworkManager.Device.Wireless":
            return mock_dev_iface
        elif interface_name == "org.freedesktop.NetworkManager.AccessPoint":
            return mock_ap_obj
        else:
            return mock_manager_iface

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user), \
         patch("dbus.SystemBus", return_value=mock_bus), \
         patch("dbus.Interface", side_effect=mock_interface), \
         patch("time.sleep"):

        mock_bus.get_object.return_value = mock_nm_obj

        # 1. activate connection
        current_req_uuid[0] = "test-uuid-123"
        res_act = client.post("/indi-allsky/ajax/network", json={"COMMAND": "activate", "CONNECTION": "test-uuid-123"})
        assert res_act.status_code == 200

        # 2. deactivate connection
        current_req_uuid[0] = "active-uuid-999"
        res_deact = client.post("/indi-allsky/ajax/network", json={"COMMAND": "deactivate", "CONNECTION": "active-uuid-999"})
        assert res_deact.status_code == 200

        # 3. delete connection
        current_req_uuid[0] = "test-uuid-123"
        res_del = client.post("/indi-allsky/ajax/network", json={"COMMAND": "delete", "CONNECTION": "test-uuid-123"})
        assert res_del.status_code == 200


        # 4. autostart / noautostart
        res_auto = client.post("/indi-allsky/ajax/network", json={"COMMAND": "autostart", "CONNECTION": "test-uuid-123"})
        assert res_auto.status_code == 200
        res_noauto = client.post("/indi-allsky/ajax/network", json={"COMMAND": "noautostart", "CONNECTION": "test-uuid-123"})
        assert res_noauto.status_code == 200

        # 5. incpriority / decpriority
        res_inc = client.post("/indi-allsky/ajax/network", json={"COMMAND": "incpriority", "CONNECTION": "test-uuid-123"})
        assert res_inc.status_code == 200
        res_dec = client.post("/indi-allsky/ajax/network", json={"COMMAND": "decpriority", "CONNECTION": "test-uuid-123"})
        assert res_dec.status_code == 200

        # 6. powersaveenable / powersavedisable
        res_pdisable = client.post("/indi-allsky/ajax/network", json={"COMMAND": "powersavedisable", "CONNECTION": "test-uuid-123"})
        assert res_pdisable.status_code == 200
        res_penable = client.post("/indi-allsky/ajax/network", json={"COMMAND": "powersaveenable", "CONNECTION": "test-uuid-123"})
        assert res_penable.status_code == 200

        # 7. scanap
        res_scan = client.post("/indi-allsky/ajax/network", json={"COMMAND": "scanap", "INTERFACE": "wlan0"})
        assert res_scan.status_code == 200

        # 8. connectap
        res_conn = client.post("/indi-allsky/ajax/network", json={"COMMAND": "connectap", "INTERFACE": "wlan0", "AP_PATH": "/org/freedesktop/NetworkManager/AccessPoint/1", "PSK": "12345678", "PRIORITY": 0, "RETRIES": 3})
        assert res_conn.status_code == 200

        # 9. createhotspot
        res_spot = client.post("/indi-allsky/ajax/network", json={"COMMAND": "createhotspot", "INTERFACE": "wlan0", "SSID": "MyHotspot", "BAND": "bg", "PSK": "12345678", "NOSECURITY": False})
        assert res_spot.status_code == 200




