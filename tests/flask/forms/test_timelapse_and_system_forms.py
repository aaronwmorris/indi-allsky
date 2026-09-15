"""Tests for timelapse generator forms, user info, timezone, and system manager forms."""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import dbus
import dbus.exceptions

from indi_allsky.flask import forms as f_mod
from indi_allsky.flask import db as _db
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbThumbnailTable,
    IndiAllSkyDbPanoramaImageTable,
    IndiAllSkyDbVideoTable,
    IndiAllSkyDbMiniVideoTable,
    IndiAllSkyDbKeogramTable,
    IndiAllSkyDbStarTrailsTable,
    IndiAllSkyDbStarTrailsVideoTable,
    IndiAllSkyDbPanoramaVideoTable,
)


@pytest.fixture
def g13_timelapse_data(flask_app, db):
    with flask_app.app_context():
        cam = IndiAllSkyDbCameraTable(
            name='g13_tl_cam', uuid='g13-tl-uuid', friendlyName='G13 TL Cam',
            latitude=0.0, longitude=0.0, local=True,
        )
        db.session.add(cam)
        db.session.commit()

        now = datetime(2026, 7, 20, 12, 0, 0)
        day_date = now.date()

        keo_thumb = IndiAllSkyDbThumbnailTable(
            camera_id=cam.id, uuid='keo-thumb-uuid', filename='keo_thumb.jpg', createDate=now,
        )
        st_thumb = IndiAllSkyDbThumbnailTable(
            camera_id=cam.id, uuid='st-thumb-uuid', filename='st_thumb.jpg', createDate=now,
        )
        db.session.add_all([keo_thumb, st_thumb])
        db.session.commit()

        img_night = IndiAllSkyDbImageTable(
            camera_id=cam.id, filename='g13_img_night.jpg', createDate=now,
            createDate_year=now.year, createDate_month=now.month, createDate_day=now.day, createDate_hour=now.hour,
            dayDate=day_date, detections=0, exposure=1.0, gain=100.0, adu=100.0, night=True,
        )
        img_day = IndiAllSkyDbImageTable(
            camera_id=cam.id, filename='g13_img_day.jpg', createDate=now,
            createDate_year=now.year, createDate_month=now.month, createDate_day=now.day, createDate_hour=now.hour,
            dayDate=day_date, detections=0, exposure=1.0, gain=100.0, adu=100.0, night=False,
        )
        db.session.add_all([img_night, img_day])

        pano_img_night = IndiAllSkyDbPanoramaImageTable(
            camera_id=cam.id, filename='g13_pano_night.jpg', createDate=now,
            createDate_year=now.year, createDate_month=now.month, createDate_day=now.day, createDate_hour=now.hour,
            dayDate=day_date, exposure=1.0, gain=100.0, night=True,
        )
        pano_img_day = IndiAllSkyDbPanoramaImageTable(
            camera_id=cam.id, filename='g13_pano_day.jpg', createDate=now,
            createDate_year=now.year, createDate_month=now.month, createDate_day=now.day, createDate_hour=now.hour,
            dayDate=day_date, exposure=1.0, gain=100.0, night=False,
        )
        db.session.add_all([pano_img_night, pano_img_day])

        vid_night = IndiAllSkyDbVideoTable(
            camera_id=cam.id, filename='g13_vid_night.mp4', createDate=now,
            dayDate=day_date, dayDate_year=now.year, dayDate_month=now.month, dayDate_day=now.day,
            night=True, success=True, data={'max_smoke_rating': 0, 'max_stars': 10, 'avg_stars': 8, 'avg_sqm': 19},
        )
        vid_day = IndiAllSkyDbVideoTable(
            camera_id=cam.id, filename='g13_vid_day.mp4', createDate=now,
            dayDate=day_date, dayDate_year=now.year, dayDate_month=now.month, dayDate_day=now.day,
            night=False, success=False,
        )
        db.session.add_all([vid_night, vid_day])

        keo_night = IndiAllSkyDbKeogramTable(
            camera_id=cam.id, filename='g13_keo_night.jpg', createDate=now,
            dayDate=day_date, night=True, success=True, thumbnail_uuid='keo-thumb-uuid',
        )
        keo_day = IndiAllSkyDbKeogramTable(
            camera_id=cam.id, filename='g13_keo_day.jpg', createDate=now,
            dayDate=day_date, night=False, success=False,
        )
        db.session.add_all([keo_night, keo_day])

        st_night = IndiAllSkyDbStarTrailsTable(
            camera_id=cam.id, filename='g13_st_night.jpg', createDate=now,
            dayDate=day_date, night=True, success=True, thumbnail_uuid='st-thumb-uuid',
        )
        st_day = IndiAllSkyDbStarTrailsTable(
            camera_id=cam.id, filename='g13_st_day.jpg', createDate=now,
            dayDate=day_date, night=False, success=False,
        )
        db.session.add_all([st_night, st_day])

        stv_night = IndiAllSkyDbStarTrailsVideoTable(
            camera_id=cam.id, filename='g13_stv_night.mp4', createDate=now,
            dayDate=day_date, night=True, success=True, data={'youtube_id': 'yt123'},
        )
        stv_day = IndiAllSkyDbStarTrailsVideoTable(
            camera_id=cam.id, filename='g13_stv_day.mp4', createDate=now,
            dayDate=day_date, night=False, success=False,
        )
        db.session.add_all([stv_night, stv_day])

        pv_night = IndiAllSkyDbPanoramaVideoTable(
            camera_id=cam.id, filename='g13_pv_night.mp4', createDate=now,
            dayDate=day_date, night=True, success=True, data={'youtube_id': 'yt456'},
        )
        pv_day = IndiAllSkyDbPanoramaVideoTable(
            camera_id=cam.id, filename='g13_pv_day.mp4', createDate=now,
            dayDate=day_date, night=False, success=False,
        )
        db.session.add_all([pv_night, pv_day])

        db.session.commit()
        return cam.id, now


@pytest.fixture
def g13_minivideo_with_thumb(flask_app, db):
    with flask_app.app_context():
        cam = IndiAllSkyDbCameraTable(
            name='g13_mv_cam', uuid='g13-mv-uuid', friendlyName='G13 MV Cam',
            latitude=0.0, longitude=0.0, local=True,
        )
        db.session.add(cam)
        db.session.commit()

        now = datetime(2026, 8, 5, 10, 0, 0)

        thumb = IndiAllSkyDbThumbnailTable(
            camera_id=cam.id,
            uuid='g13-mv-thumb-uuid',
            filename='g13_mv_thumb.jpg',
            createDate=now,
        )
        db.session.add(thumb)
        db.session.commit()

        mvid = IndiAllSkyDbMiniVideoTable(
            camera_id=cam.id,
            filename='g13_mvid.mp4',
            createDate=now,
            targetDate=now,
            startDate=now,
            endDate=now,
            note='test mini',
            dayDate=now.date(),
            dayDate_year=now.year,
            dayDate_month=now.month,
            dayDate_day=now.day,
            night=True,
            thumbnail_uuid='g13-mv-thumb-uuid',
            data={'source': 'test', 'max_stars': 5},
        )
        db.session.add(mvid)
        db.session.commit()
        return cam.id, now


def test_video_viewer_with_keogram_startrail_data(flask_app, g13_timelapse_data):
    cam_id, now = g13_timelapse_data
    with flask_app.test_request_context():
        vv = f_mod.IndiAllskyVideoViewer(camera_id=cam_id, local=True)
        videos = vv.getVideos(now.year, now.month, 'all')
        assert isinstance(videos, list)
        assert len(videos) > 0
        entry = videos[0]
        assert 'keogram' in entry
        assert 'startrail' in entry


def test_video_viewer_with_data_field(flask_app, g13_timelapse_data):
    cam_id, now = g13_timelapse_data
    with flask_app.test_request_context():
        vv = f_mod.IndiAllskyVideoViewer(camera_id=cam_id, local=True)
        videos = vv.getVideos(now.year, now.month, 'all')
        assert any(v.get('max_stars', 0) > 0 for v in videos)


def test_video_viewer_remote_with_keogram(flask_app, g13_timelapse_data):
    cam_id, now = g13_timelapse_data
    with flask_app.test_request_context():
        vv = f_mod.IndiAllskyVideoViewer(camera_id=cam_id, local=False)
        videos = vv.getVideos(now.year, now.month, 'all')
        assert isinstance(videos, list)


def test_timelapse_generator_old_success_flags(flask_app, g13_timelapse_data):
    cam_id, now = g13_timelapse_data
    with flask_app.test_request_context():
        t_old = f_mod.IndiAllskyTimelapseGeneratorForm_old(camera_id=cam_id)
        choices = t_old.DAY_SELECT.choices
        assert len(choices) > 0
        day_strs = [label for _, label in choices]
        assert any('[T]' in s for s in day_strs)


def test_timelapse_generator_success_flags(flask_app, g13_timelapse_data):
    cam_id, now = g13_timelapse_data
    with flask_app.test_request_context():
        t_new = f_mod.IndiAllskyTimelapseGeneratorForm(camera_id=cam_id)
        choices = t_new.DAY_SELECT.choices
        assert len(choices) > 0
        day_strs = [label for _, label in choices]
        assert any('[T]' in s for s in day_strs)


def test_minivideo_viewer_with_thumbnail_and_data(flask_app, g13_minivideo_with_thumb):
    cam_id, now = g13_minivideo_with_thumb
    with flask_app.test_request_context():
        mv = f_mod.IndiAllskyMiniVideoViewer(camera_id=cam_id, local=True)
        videos = mv.getVideos(now.year, now.month)
        assert isinstance(videos, list)
        assert len(videos) > 0
        assert videos[0].get('source') == 'test'


def test_network_manager_get_object_exception(flask_app):
    with flask_app.test_request_context():
        mock_bus = MagicMock()
        mock_bus.get_object.side_effect = dbus.exceptions.DBusException('no nm object')

        with patch('dbus.SystemBus', return_value=mock_bus):
            nm_form = f_mod.IndiAllskyNetworkManagerForm()
            assert nm_form is not None


def test_network_manager_wifi_type(flask_app):
    with flask_app.test_request_context():
        mock_bus = MagicMock()
        mock_nm_settings = MagicMock()
        mock_nm_settings.Get.return_value = ['/org/freedesktop/NetworkManager/Settings/2']

        mock_setting_conn = MagicMock()
        mock_setting_conn.GetSettings.return_value = {
            'connection': {
                'uuid': 'wifi-uuid-1',
                'id': 'My Wifi Network',
                'type': '802-11-wireless',
                'interface-name': 'wlan0',
                'autoconnect': True,
                'autoconnect-priority': 10,
            },
            'ipv4': {'address-data': []},
            '802-11-wireless': {'powersave': 2},
        }

        mock_nm = MagicMock()
        mock_nm.Get.side_effect = lambda iface, prop, dbus_interface=None: (
            [] if prop == 'ActiveConnections' else []
        )

        def mock_get_object(bus_name, object_path):
            if 'Settings/2' in object_path:
                return mock_setting_conn
            if 'Settings' in object_path:
                return mock_nm_settings
            return mock_nm

        mock_bus.get_object.side_effect = mock_get_object

        with patch('dbus.SystemBus', return_value=mock_bus), \
             patch('dbus.Interface', side_effect=lambda obj, iface: obj):
            nm_form = f_mod.IndiAllskyNetworkManagerForm()
            assert nm_form is not None


def test_network_manager_no_static_address(flask_app):
    with flask_app.test_request_context():
        mock_bus = MagicMock()
        mock_nm_settings = MagicMock()
        mock_nm_settings.Get.return_value = ['/org/freedesktop/NetworkManager/Settings/3']

        mock_setting_conn = MagicMock()
        mock_setting_conn.GetSettings.return_value = {
            'connection': {
                'uuid': 'eth-uuid-noaddr',
                'id': 'Wired No Address',
                'type': '802-3-ethernet',
                'interface-name': 'eth1',
                'autoconnect': False,
                'autoconnect-priority': 0,
            },
            'ipv4': {'address-data': []},
        }

        mock_nm = MagicMock()
        mock_nm.Get.return_value = []

        def mock_get_obj(bus_name, object_path):
            if 'Settings/3' in object_path:
                return mock_setting_conn
            if 'Settings' in object_path:
                return mock_nm_settings
            return mock_nm

        mock_bus.get_object.side_effect = mock_get_obj

        with patch('dbus.SystemBus', return_value=mock_bus), \
             patch('dbus.Interface', side_effect=lambda obj, iface: obj):
            nm_form = f_mod.IndiAllskyNetworkManagerForm()
            assert nm_form is not None


def test_network_manager_other_type(flask_app):
    with flask_app.test_request_context():
        mock_bus = MagicMock()
        mock_nm_settings = MagicMock()
        mock_nm_settings.Get.return_value = ['/org/freedesktop/NetworkManager/Settings/4']

        mock_setting_conn = MagicMock()
        mock_setting_conn.GetSettings.return_value = {
            'connection': {
                'uuid': 'other-uuid-1',
                'id': 'VPN Connection',
                'type': 'vpn',
                'interface-name': 'tun0',
                'autoconnect': True,
                'autoconnect-priority': 0,
            },
            'ipv4': {'address-data': [{'address': '10.0.0.1'}]},
        }

        mock_nm = MagicMock()
        mock_nm.Get.return_value = []

        def mock_get_obj(bus_name, object_path):
            if 'Settings/4' in object_path:
                return mock_setting_conn
            if 'Settings' in object_path:
                return mock_nm_settings
            return mock_nm

        mock_bus.get_object.side_effect = mock_get_obj

        with patch('dbus.SystemBus', return_value=mock_bus), \
             patch('dbus.Interface', side_effect=lambda obj, iface: obj):
            nm_form = f_mod.IndiAllskyNetworkManagerForm()
            assert nm_form is not None


def test_network_manager_conn_state_keyerror(flask_app):
    with flask_app.test_request_context():
        mock_bus = MagicMock()
        mock_nm_settings = MagicMock()
        mock_nm_settings.Get.return_value = ['/org/freedesktop/NetworkManager/Settings/5']

        mock_setting_conn = MagicMock()
        mock_setting_conn.GetSettings.return_value = {
            'connection': {
                'uuid': 'eth-uuid-state',
                'id': 'State Test',
                'type': '802-3-ethernet',
                'interface-name': 'eth2',
                'autoconnect': True,
                'autoconnect-priority': 0,
            },
            'ipv4': {'address-data': [{'address': '192.168.1.99'}]},
        }

        mock_nm = MagicMock()
        mock_nm.Get.side_effect = lambda iface, prop, dbus_interface=None: (
            ['/org/freedesktop/NetworkManager/ActiveConnection/99'] if prop == 'ActiveConnections' else []
        )

        mock_active_conn = MagicMock()
        mock_active_conn.Get.side_effect = lambda iface, prop, dbus_interface=None: (
            'eth-uuid-state' if prop == 'Uuid' else
            999 if prop == 'State' else
            '/org/freedesktop/NetworkManager/IP4Config/99' if prop == 'Ip4Config' else
            [] if prop == 'Devices' else ''
        )

        mock_ip4 = MagicMock()
        mock_ip4.Get.return_value = [{'address': '192.168.1.99'}]

        def mock_get_obj(bus_name, object_path):
            if 'Settings/5' in object_path:
                return mock_setting_conn
            if 'Settings' in object_path:
                return mock_nm_settings
            if 'ActiveConnection/99' in object_path:
                return mock_active_conn
            if 'IP4Config/99' in object_path:
                return mock_ip4
            return mock_nm

        mock_bus.get_object.side_effect = mock_get_obj

        with patch('dbus.SystemBus', return_value=mock_bus), \
             patch('dbus.Interface', side_effect=lambda obj, iface: obj):
            nm_form = f_mod.IndiAllskyNetworkManagerForm()
            assert nm_form is not None


def test_network_manager_address_dbus_exception(flask_app):
    with flask_app.test_request_context():
        mock_bus = MagicMock()
        mock_nm_settings = MagicMock()
        mock_nm_settings.Get.return_value = ['/org/freedesktop/NetworkManager/Settings/6']

        mock_setting_conn = MagicMock()
        mock_setting_conn.GetSettings.return_value = {
            'connection': {
                'uuid': 'eth-uuid-ip4err',
                'id': 'IP4 Error',
                'type': '802-3-ethernet',
                'interface-name': 'eth3',
                'autoconnect': True,
                'autoconnect-priority': 0,
            },
            'ipv4': {'address-data': []},
        }

        mock_nm = MagicMock()
        mock_nm.Get.side_effect = lambda iface, prop, dbus_interface=None: (
            ['/org/freedesktop/NetworkManager/ActiveConnection/6'] if prop == 'ActiveConnections' else []
        )

        mock_active_conn = MagicMock()
        mock_active_conn.Get.side_effect = lambda iface, prop, dbus_interface=None: (
            'eth-uuid-ip4err' if prop == 'Uuid' else
            2 if prop == 'State' else
            '/org/freedesktop/NetworkManager/IP4Config/6' if prop == 'Ip4Config' else
            [] if prop == 'Devices' else ''
        )

        mock_ip4 = MagicMock()
        mock_ip4.Get.side_effect = dbus.exceptions.DBusException('ip4 error')

        def mock_get_obj(bus_name, object_path):
            if 'Settings/6' in object_path:
                return mock_setting_conn
            if 'Settings' in object_path:
                return mock_nm_settings
            if 'ActiveConnection/6' in object_path:
                return mock_active_conn
            if 'IP4Config/6' in object_path:
                return mock_ip4
            return mock_nm

        mock_bus.get_object.side_effect = mock_get_obj

        with patch('dbus.SystemBus', return_value=mock_bus), \
             patch('dbus.Interface', side_effect=lambda obj, iface: obj):
            nm_form = f_mod.IndiAllskyNetworkManagerForm()
            assert nm_form is not None


def test_network_manager_wifi_has_choices(flask_app):
    with flask_app.test_request_context():
        mock_bus = MagicMock()
        mock_nm_settings = MagicMock()
        mock_nm_settings.Get.return_value = ['/org/freedesktop/NetworkManager/Settings/7']

        mock_setting_conn = MagicMock()
        mock_setting_conn.GetSettings.return_value = {
            'connection': {
                'uuid': 'wifi-uuid-2',
                'id': 'Home WiFi',
                'type': '802-11-wireless',
                'interface-name': 'wlan0',
                'autoconnect': True,
                'autoconnect-priority': 0,
            },
            'ipv4': {'address-data': [{'address': '192.168.0.50'}]},
            '802-11-wireless': {'powersave': 2},
        }

        mock_nm = MagicMock()
        mock_nm.Get.return_value = []

        def mock_get_obj(bus_name, object_path):
            if 'Settings/7' in object_path:
                return mock_setting_conn
            if 'Settings' in object_path:
                return mock_nm_settings
            return mock_nm

        mock_bus.get_object.side_effect = mock_get_obj

        with patch('dbus.SystemBus', return_value=mock_bus), \
             patch('dbus.Interface', side_effect=lambda obj, iface: obj):
            nm_form = f_mod.IndiAllskyNetworkManagerForm()
            choices = nm_form.CONNECTIONS_SELECT.choices
            wifi_choices = choices.get('Wi-Fi', [])
            assert any('Home WiFi' in label for _, label in wifi_choices)


def test_drive_manager_get_object_exception(flask_app):
    with flask_app.test_request_context():
        mock_bus = MagicMock()
        call_count = [0]

        def mock_get_obj(bus_name, object_path):
            call_count[0] += 1
            if call_count[0] <= 1:
                raise dbus.exceptions.DBusException('no udisks2')
            return MagicMock()

        mock_bus.get_object.side_effect = mock_get_obj

        with patch('dbus.SystemBus', return_value=mock_bus), \
             patch('dbus.Interface', side_effect=lambda obj, dbus_interface=None: obj):
            dm_form = f_mod.IndiAllskyDriveManagerForm()
            assert dm_form is not None


def test_drive_manager_no_vendor(flask_app):
    with flask_app.test_request_context():
        mock_bus = MagicMock()
        mock_obj_mgr = MagicMock()
        mock_obj_mgr.GetManagedObjects.return_value = {
            '/org/freedesktop/UDisks2/drives/drive_novend': {},
        }

        mock_drive_props = MagicMock()
        mock_drive_props.GetAll.return_value = {
            'Id': 'no-vendor-drive',
            'Vendor': '',
            'Model': 'Model X',
            'Size': 16000000000,
            'ConnectionBus': '',
            'Removable': 0,
            'CanPowerOff': 0,
        }

        def mock_get_obj(bus_name, object_path):
            if 'drives/drive_novend' in object_path:
                return mock_drive_props
            return mock_obj_mgr

        mock_bus.get_object.side_effect = mock_get_obj

        with patch('dbus.SystemBus', return_value=mock_bus), \
             patch('dbus.Interface', side_effect=lambda obj, dbus_interface=None: obj):
            dm_form = f_mod.IndiAllskyDriveManagerForm()
            drives = dm_form.getDrives()
            assert any('No Vendor' in label for _, label in drives if isinstance(label, str))


def test_drive_manager_no_drives(flask_app):
    with flask_app.test_request_context():
        mock_bus = MagicMock()
        mock_obj_mgr = MagicMock()
        mock_obj_mgr.GetManagedObjects.return_value = {}

        mock_bus.get_object.return_value = mock_obj_mgr

        with patch('dbus.SystemBus', return_value=mock_bus), \
             patch('dbus.Interface', side_effect=lambda obj, dbus_interface=None: obj):
            dm_form = f_mod.IndiAllskyDriveManagerForm()
            drives = dm_form.getDrives()
            assert any('No Removable' in label for _, label in drives)


def test_indi_server_change_form(flask_app):
    with flask_app.test_request_context():
        form = f_mod.IndiAllskyIndiServerChangeForm()
        assert form is not None
        assert form.CAMERA_SERVER_SELECT.choices == [['', 'None']]
        assert form.GPS_SERVER_SELECT.choices == [['', 'None']]
