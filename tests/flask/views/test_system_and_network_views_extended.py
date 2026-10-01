"""Tests for extended system, network, drive, and websocket view branches."""

import io
import json
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import dbus
import pytest
import simple_websocket
from flask import session
from flask_login import login_user

from indi_allsky.flask import db
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbUserTable,
)
from indi_allsky.flask.views import (
    AjaxDriveManagerView,
    AjaxNetworkManagerView,
    CameraLensView,
    DriveManagerView,
    NetworkManagerView,
    SystemInfoView,
    WsControlView,
    WsEventsView,
    WsShellView,
)


def test_system_info_view_additional_branches(flask_app, system_db):
    """Test SystemInfoView CPU bits 32-bit branch, camera driver fallbacks, system type, and fan errors."""
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True
    mock_user.username = 'admin_user'

    cam = db.session.get(IndiAllSkyDbCameraTable, 1)

    # 1. 32-bit cpu and rpicam-still driver
    cam.driver = 'rpicam-still'
    db.session.commit()

    with flask_app.test_request_context():
        view = SystemInfoView(template_name='system_info.html')
        login_user(mock_user)
        with patch('sys.maxsize', 1000000):
            with patch.object(view, 'getSystemdTimeDate', return_value={'Timezone': 'UTC'}):
                with patch.dict('sys.modules', {'skyfield': None}):
                    context = view.get_context()
                    assert context['cpu_bits'] == 32
                    assert context['skyfield_version'] == 'Not installed'

    # 2. Camera driver is None
    cam.driver = None
    db.session.commit()
    with flask_app.test_request_context():
        view = SystemInfoView(template_name='system_info.html')
        login_user(mock_user)
        with patch.object(view, 'getSystemdTimeDate', return_value={'Timezone': 'UTC'}):
            context = view.get_context()
            assert context['form_indiserver_change'].data['CAMERA_SERVER_SELECT'] == 'indi_simulator_ccd'

        # 3. getSystemType from /proc/device-tree/model
        with patch('pathlib.Path.exists', return_value=True):
            with patch('io.open', return_value=io.StringIO('Raspberry Pi 5 Model B\n')):
                assert view.getSystemType() == 'Raspberry Pi 5 Model B'

        with patch('pathlib.Path.exists', return_value=True):
            with patch('io.open', return_value=io.StringIO('   \n')):
                assert view.getSystemType() == 'Unknown'

        # 4. getFans psutil exceptions and active cooler fallback
        with patch('psutil.sensors_fans', side_effect=Exception('Fan error')):
            with patch('pathlib.Path.glob', return_value=[MagicMock(read_text=MagicMock(return_value='3500\n'))]):
                fans = view.getFans()
                assert len(fans) == 1
                assert fans[0]['name'] == 'cooling_fan/fan1'
                assert fans[0]['rpm'] == 3500.0

        # Fan with exception on getattr(f, 'current') and fan label present
        mock_fan = MagicMock()
        mock_fan.label = 'Case_Fan'
        type(mock_fan).current = property(fget=MagicMock(side_effect=Exception('Sensor error')))
        with patch('psutil.sensors_fans', return_value={'fan_chip': [mock_fan]}):
            fans = view.getFans()
            assert len(fans) == 1
            assert fans[0]['name'] == 'fan_chip/Case_Fan'
            assert fans[0]['rpm'] == 0.0


def test_network_and_drive_manager_views_error_branches(flask_app, system_db):
    """Test NetworkManagerView and DriveManagerView D-Bus failure branches."""
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True
    mock_user.username = 'admin_user'

    # 1. NetworkManagerView with hostname IndexError and DBusException
    with flask_app.test_request_context():
        nm_view = NetworkManagerView(template_name='network_manager.html')
        login_user(mock_user)
        with patch('socket.gethostname', return_value=''):
            with patch('dbus.SystemBus', side_effect=dbus.exceptions.DBusException('No NM')):
                context = nm_view.get_context()
                assert context['nm_installed'] is False

    # 2. DriveManagerView with DBusException
    with flask_app.test_request_context():
        dm_view = DriveManagerView(template_name='drive_manager.html')
        login_user(mock_user)
        with patch('dbus.SystemBus', side_effect=dbus.exceptions.DBusException('No UDisks2')):
            context = dm_view.get_context()
            assert context['udisks2_installed'] is False


def test_ajax_network_manager_view_extended_actions(flask_app, system_db):
    """Test AjaxNetworkManagerView non-admin, createhotspot with nosecurity, connection type guards, and error branches."""
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = False
    mock_user.username = 'standard_user'

    # 1. Non-admin access
    with flask_app.test_request_context(method='POST', json={'COMMAND': 'scanap'}):
        view = AjaxNetworkManagerView()
        login_user(mock_user)
        res, code = view.dispatch_request()
        assert code == 400
        assert 'User does not have permission' in res.get_json()['failure-message']

    # 2. Admin access: createhotspot with nosecurity=True
    mock_admin = MagicMock()
    mock_admin.is_authenticated = True
    mock_admin.is_admin = True
    mock_admin.username = 'admin_user'

    with flask_app.test_request_context(
        method='POST',
        json={
            'COMMAND': 'createhotspot',
            'INTERFACE': 'wlan0',
            'SSID': 'OpenHotspot',
            'BAND': 'bg',
            'PSK': '',
            'NOSECURITY': True,
        }
    ):
        view = AjaxNetworkManagerView()
        login_user(mock_admin)
        with patch.object(view, 'createHotspot', return_value=('Hotspot Created', 200)) as mock_hotspot:
            view.dispatch_request()
            mock_hotspot.assert_called_once_with('wlan0', 'OpenHotspot', 'bg', '', nosecurity=True)

    # 3. createHotspot DBusException handling
    with flask_app.test_request_context():
        view = AjaxNetworkManagerView()
        with patch('dbus.SystemBus'):
            with patch('dbus.Interface') as mock_iface_cls:
                mock_mgr_instance = MagicMock()
                mock_settings_instance = MagicMock()
                mock_settings_instance.AddConnection.side_effect = dbus.exceptions.DBusException('AddConn failed')
                mock_iface_cls.side_effect = [mock_mgr_instance, mock_settings_instance]
                res, code = view.createHotspot('wlan0', 'OpenHotspot', 'bg', '', nosecurity=True)
                assert code == 400
                assert 'D-Bus Exception' in res.get_json()['failure-message']

    # 4. activateConnection non-wifi/ethernet type guard
    mock_settings_conn = MagicMock()
    mock_settings_conn.GetSettings.return_value = {'connection': {'type': 'vpn'}}
    with flask_app.test_request_context():
        view = AjaxNetworkManagerView()
        with patch('dbus.SystemBus'):
            with patch.object(view, 'getSettingsPath', return_value='/settings/1'):
                with patch('dbus.Interface', return_value=mock_settings_conn):
                    res, code = view.activateConnection('test-uuid')
                    assert code == 400
                    assert 'Only Ethernet and Wireless' in res.get_json()['failure-message']

    # 5. deactivateConnection DBusException handling
    mock_settings_conn.GetSettings.return_value = {'connection': {'type': '802-11-wireless'}}
    mock_mgr = MagicMock()
    mock_mgr.DeactivateConnection.side_effect = dbus.exceptions.DBusException('Deactivate failed')
    with flask_app.test_request_context():
        view = AjaxNetworkManagerView()
        with patch('dbus.SystemBus'):
            with patch.object(view, 'getSettingsPath', return_value='/settings/1'):
                with patch.object(view, 'getActiveConnection', return_value='/active/1'):
                    with patch('dbus.Interface', side_effect=[mock_settings_conn, mock_settings_conn, mock_mgr]):
                        res, code = view.deactivateConnection('test-uuid')
                        assert code == 400
                        assert 'Failed to deactivate' in res.get_json()['failure-message']

    # 6. deleteConnection non-wifi/ethernet guard
    mock_settings_conn.GetSettings.return_value = {'connection': {'type': 'bridge'}}
    with flask_app.test_request_context():
        view = AjaxNetworkManagerView()
        from indi_allsky.exceptions import NotFound
        with patch('dbus.SystemBus'):
            with patch.object(view, 'getSettingsPath', return_value='/settings/1'):
                with patch.object(view, 'getActiveConnection', side_effect=NotFound()):
                    with patch('dbus.Interface', side_effect=[mock_settings_conn, mock_settings_conn, mock_settings_conn]):
                        res, code = view.deleteConnection('test-uuid')
                        assert code == 400
                        assert 'Only Ethernet and Wireless' in res.get_json()['failure-message']

    # 7. setAutostartConnection DBusException handling
    mock_settings_conn.GetSettings.return_value = {'connection': {'type': '802-11-wireless', 'autoconnect': True}}
    mock_settings_conn.Update.side_effect = dbus.exceptions.DBusException('Update failed')
    with flask_app.test_request_context():
        view = AjaxNetworkManagerView()
        with patch('dbus.SystemBus'):
            with patch.object(view, 'getSettingsPath', return_value='/settings/1'):
                with patch('dbus.Interface', side_effect=[mock_settings_conn, mock_settings_conn]):
                    res, code = view.setAutostartConnection('test-uuid', auto_connect=True)
                    assert code == 400
                    assert 'Configure Failed' in res.get_json()['failure-message']

    # 8. incrementConnectionPriority autoconnect-priority parse error
    mock_settings_conn.GetSettings.return_value = {'connection': {'type': '802-11-wireless', 'autoconnect-priority': 'invalid'}}
    mock_settings_conn.Update.side_effect = None
    with flask_app.test_request_context():
        view = AjaxNetworkManagerView()
        with patch('dbus.SystemBus'):
            with patch('time.sleep'):
                with patch.object(view, 'getSettingsPath', return_value='/settings/1'):
                    with patch('dbus.Interface', side_effect=[mock_settings_conn, mock_settings_conn]):
                        res = view.incrementConnectionPriority('test-uuid', increment=10)
                        assert res.get_json()['success-message'] == 'Priority Updated'


def test_ajax_drive_manager_view_extended_actions(flask_app, system_db):
    """Test AjaxDriveManagerView non-admin, non-matching drive/device, unmounted drive, and DBus errors."""
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = False
    mock_user.username = 'standard_user'

    # 1. Non-admin access
    with flask_app.test_request_context(method='POST', json={'COMMAND': 'getmetadata', 'DRIVE_ID': 'drv1'}):
        view = AjaxDriveManagerView()
        login_user(mock_user)
        res, code = view.dispatch_request()
        assert code == 400
        assert 'User does not have permission' in res.get_json()['failure-message']

    # 2. getMetadata skipping other drives and failing if not found
    mock_admin = MagicMock()
    mock_admin.is_authenticated = True
    mock_admin.is_admin = True
    mock_admin.username = 'admin_user'

    mock_iface = MagicMock()
    mock_iface.GetManagedObjects.return_value = [
        '/org/freedesktop/UDisks2/block_devices/sda',  # skipped (doesn't start with /drives/)
        '/org/freedesktop/UDisks2/drives/Drive_Other',
    ]

    mock_props = MagicMock()
    mock_props.GetAll.return_value = {
        'Id': 'Drive_Other',
        'Vendor': 'Vendor',
        'Model': 'Model',
        'Size': 1000000000,
        'ConnectionBus': 'usb',
        'Serial': '123',
        'Media': 'thumb',
        'MediaCompatibility': [],
        'CanPowerOff': False,
        'Removable': True,
        'Ejectable': True,
        'TimeDetected': 1600000000000000,
        'TimeMediaDetected': 0,
    }

    with flask_app.test_request_context(method='POST', json={'COMMAND': 'getmetadata', 'DRIVE_ID': 'Drive_Target'}):
        view = AjaxDriveManagerView()
        login_user(mock_admin)
        with patch('dbus.SystemBus'):
            with patch('dbus.Interface', side_effect=[mock_iface, mock_props]):
                res, code = view.dispatch_request()
                assert code == 400
                assert 'Drive not found' in res.get_json()['failure-message']

    # 3. powerOffDrive non-matching drive and DBusException
    mock_iface.GetManagedObjects.return_value = ['/org/freedesktop/UDisks2/drives/Drive_Target']
    mock_props.GetAll.return_value = {'Id': 'Drive_Target', 'CanPowerOff': True}
    mock_drive_iface = MagicMock()
    mock_drive_iface.PowerOff.side_effect = dbus.exceptions.DBusException('PowerOff failed')

    with flask_app.test_request_context():
        view = AjaxDriveManagerView()
        with patch('dbus.SystemBus'):
            with patch('dbus.Interface', side_effect=[mock_iface, mock_props, mock_drive_iface]):
                res, code = view.powerOffDrive('Drive_Target')
                assert code == 400
                assert 'PowerOff failed' in res.get_json()['failure-message']

    # 4. unmountDevice non-matching device, unmounted device, and DBusException
    mock_iface.GetManagedObjects.return_value = {
        '/org/freedesktop/UDisks2/drives/sda': {},  # skipped (doesn't start with /block_devices/)
        '/org/freedesktop/UDisks2/block_devices/sda1': {
            'org.freedesktop.UDisks2.Filesystem': {'MountPoints': []},
        },
    }
    mock_props.GetAll.return_value = {'Id': 'dev1'}

    # 4a. Not mounted
    with flask_app.test_request_context():
        view = AjaxDriveManagerView()
        with patch('dbus.SystemBus'):
            with patch('dbus.Interface', side_effect=[mock_iface, mock_props]):
                res, code = view.unmountDevice('dev1')
                assert code == 400
                assert 'Filesystem not mounted' in res.get_json()['failure-message']

    # 4b. DBusException during unmount
    mock_iface.GetManagedObjects.return_value = {
        '/org/freedesktop/UDisks2/block_devices/sda1': {
            'org.freedesktop.UDisks2.Filesystem': {'MountPoints': [[ord(c) for c in '/media/usb'] + [0]]},
        },
    }
    mock_fs_iface = MagicMock()
    mock_fs_iface.Unmount.side_effect = dbus.exceptions.DBusException('Unmount failed')
    with flask_app.test_request_context():
        view = AjaxDriveManagerView()
        with patch('dbus.SystemBus'):
            with patch('dbus.Interface', side_effect=[mock_iface, mock_props, mock_fs_iface]):
                res, code = view.unmountDevice('dev1')
                assert code == 400
                assert 'Unmount failed' in res.get_json()['failure-message']

    # 5. mountDevice non-matching device and DBusException
    mock_fs_iface.Mount.side_effect = dbus.exceptions.DBusException('Mount failed')
    with flask_app.test_request_context():
        view = AjaxDriveManagerView()
        with patch('dbus.SystemBus'):
            with patch('dbus.Interface', side_effect=[mock_iface, mock_props, mock_fs_iface]):
                res, code = view.mountDevice('dev1')
                assert code == 400
                assert 'Mount failed' in res.get_json()['failure-message']


def test_camera_lens_view_privacy_and_circle_dimensions(flask_app, system_db):
    """Test CameraLensView with PRIVACY_MODE and image_circle_diameter comparisons."""
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True
    mock_user.username = 'admin_user'

    cam = db.session.get(IndiAllSkyDbCameraTable, 1)
    cam.width = 1000
    cam.height = 800
    cam.lensImageCircle = 500  # less than width and height
    db.session.commit()

    with flask_app.test_request_context():
        view = CameraLensView(template_name='camera_lens.html')
        login_user(mock_user)
        view.indi_allsky_config = {'PRIVACY_MODE': True, 'NIGHT_SUN_ALT_DEG': -6.0}
        context = view.get_context()
        assert context['owner'] == 'Private'
        assert context['image_circle_diameter'] == 500


def test_ws_shell_and_websocket_views_exceptions(flask_app, system_db):
    """Test WsShellView, WsEventsView, and WsControlView error and exception branches."""
    # 1. WsEventsView with auth_required and API key from database/flask config
    mock_ws = MagicMock()
    mock_ws.receive.side_effect = ['{"type": "get_status"}', '{"invalid_json":', simple_websocket.ConnectionClosed()]

    with flask_app.test_request_context('/ws/events?api_key=valid-db-key'):
        events_view = WsEventsView()
        with patch.dict(flask_app.config, {'INDI_ALLSKY_AUTH_ALL_VIEWS': True, 'WEBSOCKET_API_KEY': 'valid-flask-key'}):
            events_view.indi_allsky_config = {'WEBSOCKET_API_KEY': 'valid-db-key'}
            with patch('simple_websocket.Server.accept', return_value=mock_ws):
                res = events_view.dispatch_request()
                assert res == ''

    # 2. WsEventsView initial handshake failure
    mock_broken_ws = MagicMock()
    mock_broken_ws.send.side_effect = Exception('Send failed')
    with flask_app.test_request_context('/ws/events'):
        events_view = WsEventsView()
        with patch.dict(flask_app.config, {'INDI_ALLSKY_AUTH_ALL_VIEWS': False}):
            with patch('simple_websocket.Server.accept', return_value=mock_broken_ws):
                res = events_view.dispatch_request()
                assert res == ''

    # 3. WsControlView with DB key authentication and shutdown/reboot execution
    mock_ctrl_ws = MagicMock()
    mock_ctrl_ws.receive.side_effect = ['{"action": "shutdown"}', simple_websocket.ConnectionClosed()]

    with flask_app.test_request_context('/ws/control?api_key=ctrl-db-key'):
        control_view = WsControlView()
        control_view.indi_allsky_config = {'WEBSOCKET_API_KEY': 'ctrl-db-key'}
        with patch('simple_websocket.Server.accept', return_value=mock_ctrl_ws):
            with patch.object(control_view, 'poweroffSystemd', return_value=True):
                res = control_view.dispatch_request()
                assert res == ''
