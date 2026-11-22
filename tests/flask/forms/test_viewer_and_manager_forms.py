"""Tests for viewer and manager forms in indi_allsky.flask.forms."""
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import dbus
import dbus.exceptions

from indi_allsky.flask import forms as f_mod
from indi_allsky.flask import db as _db
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbFitsImageTable,
    IndiAllSkyDbVideoTable,
    IndiAllSkyDbMiniVideoTable,
    IndiAllSkyDbThumbnailTable,
)


@pytest.fixture
def viewer_db_data(flask_app, db):
    with flask_app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        if not cam:
            cam = IndiAllSkyDbCameraTable(
                name="viewer_cam",
                uuid="viewer-cam-uuid-1",
                friendlyName="Viewer Cam",
                latitude=0.0, longitude=0.0,
                local=True,
            )
            db.session.add(cam)
            db.session.commit()

        now = datetime.now()
        # Create thumbnail
        thumb = IndiAllSkyDbThumbnailTable(
            camera_id=cam.id,
            uuid="thumb-uuid-1",
            filename="thumb.jpg",
            createDate=now,
        )
        db.session.add(thumb)
        db.session.commit()

        # Create image
        img = IndiAllSkyDbImageTable(
            camera_id=cam.id,
            filename="test_img.jpg",
            thumbnail_uuid="thumb-uuid-1",
            createDate=now,
            createDate_year=now.year,
            createDate_month=now.month,
            createDate_day=now.day,
            createDate_hour=now.hour,
            dayDate=now.date(),
            detections=5,
            exposure=1.0,
            gain=100.0,
            adu=100.0,
        )
        # Create remote image
        img_remote = IndiAllSkyDbImageTable(
            camera_id=cam.id,
            filename="remote_img.jpg",
            createDate=now,
            createDate_year=now.year,
            createDate_month=now.month,
            createDate_day=now.day,
            createDate_hour=now.hour,
            dayDate=now.date(),
            detections=5,
            remote_url="http://example.com/img.jpg",
            exposure=1.0,
            gain=100.0,
            adu=100.0,
        )
        # Create FITS
        fits = IndiAllSkyDbFitsImageTable(
            camera_id=cam.id,
            filename="test_fits.fits",
            createDate=now,
            createDate_year=now.year,
            createDate_month=now.month,
            createDate_day=now.day,
            createDate_hour=now.hour,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
        )
        # Create Video
        vid = IndiAllSkyDbVideoTable(
            camera_id=cam.id,
            filename="test_vid.mp4",
            createDate=now,
            dayDate=now.date(),
            dayDate_year=now.year,
            dayDate_month=now.month,
            dayDate_day=now.day,
            night=True,
        )
        # Create MiniVideo
        mvid = IndiAllSkyDbMiniVideoTable(
            camera_id=cam.id,
            filename="test_mvid.mp4",
            createDate=now,
            targetDate=now,
            startDate=now,
            endDate=now,
            note="test note",
            dayDate=now.date(),
            dayDate_year=now.year,
            dayDate_month=now.month,
            dayDate_day=now.day,
            night=True,
        )
        db.session.add_all([img, img_remote, fits, vid, mvid])
        db.session.commit()
        return cam.id, now


# ==============================================================================
# Image Viewer Forms
# ==============================================================================

def test_image_viewer_methods(flask_app, viewer_db_data):
    cam_id, now = viewer_db_data
    with flask_app.test_request_context():
        # local=True
        iv_local = f_mod.IndiAllskyImageViewer(camera_id=cam_id, local=True, detections_count=0)
        years = iv_local.getYears()
        assert (now.year, str(now.year)) in years

        months = iv_local.getMonths(now.year)
        assert len(months) > 0

        days = iv_local.getDays(now.year, now.month)
        assert (now.day, str(now.day)) in days

        hours = iv_local.getHours(now.year, now.month, now.day)
        assert len(hours) > 0

        imgs = iv_local.getImages(now.year, now.month, now.day, now.hour)
        assert len(imgs) > 0

        # local=False
        iv_remote = f_mod.IndiAllskyImageViewer(camera_id=cam_id, local=False, detections_count=0)
        assert len(iv_remote.getYears()) > 0
        assert len(iv_remote.getMonths(now.year)) > 0
        assert len(iv_remote.getDays(now.year, now.month)) > 0
        assert len(iv_remote.getHours(now.year, now.month, now.day)) > 0
        assert len(iv_remote.getImages(now.year, now.month, now.day, now.hour)) > 0

        # Preload form
        preload = f_mod.IndiAllskyImageViewerPreload(camera_id=cam_id, local=True)
        assert preload is not None


# ==============================================================================
# Fits Image Viewer Forms
# ==============================================================================

def test_fits_image_viewer_methods(flask_app, viewer_db_data):
    cam_id, now = viewer_db_data
    with flask_app.test_request_context():
        fv = f_mod.IndiAllskyFitsImageViewer(camera_id=cam_id)
        assert len(fv.getYears()) > 0
        assert len(fv.getMonths(now.year)) > 0
        assert len(fv.getDays(now.year, now.month)) > 0
        assert len(fv.getHours(now.year, now.month, now.day)) > 0
        assert len(fv.getImages(now.year, now.month, now.day, now.hour)) > 0

        preload = f_mod.IndiAllskyFitsImageViewerPreload(camera_id=cam_id)
        assert preload is not None


# ==============================================================================
# Gallery Viewer Forms
# ==============================================================================

def test_gallery_viewer_methods(flask_app, viewer_db_data):
    cam_id, now = viewer_db_data
    with flask_app.test_request_context():
        # local=True
        gv_local = f_mod.IndiAllskyGalleryViewer(camera_id=cam_id, local=True)
        assert len(gv_local.getYears()) > 0
        assert len(gv_local.getMonths(now.year)) > 0
        assert len(gv_local.getDays(now.year, now.month)) > 0
        assert len(gv_local.getHours(now.year, now.month, now.day)) > 0
        assert len(gv_local.getImages(now.year, now.month, now.day, now.hour)) > 0

        # local=False
        gv_remote = f_mod.IndiAllskyGalleryViewer(camera_id=cam_id, local=False)
        assert len(gv_remote.getYears()) > 0

        preload = f_mod.IndiAllskyGalleryViewerPreload(camera_id=cam_id, local=True)
        assert preload is not None


# ==============================================================================
# Video & MiniVideo Viewer Forms
# ==============================================================================

def test_video_and_minivideo_viewer_methods(flask_app, viewer_db_data):
    cam_id, now = viewer_db_data
    with flask_app.test_request_context():
        # VideoViewer
        vv_local = f_mod.IndiAllskyVideoViewer(camera_id=cam_id, local=True)
        assert len(vv_local.getYears()) > 0
        assert len(vv_local.getMonths(now.year)) > 0
        assert len(vv_local.getVideos(now.year, now.month, 'all')) > 0

        vv_remote = f_mod.IndiAllskyVideoViewer(camera_id=cam_id, local=False)
        vv_remote.getYears()
        vv_remote.getMonths(now.year)
        vv_remote.getVideos(now.year, now.month, 'all')

        vv_preload = f_mod.IndiAllskyVideoViewerPreload(camera_id=cam_id, local=True)
        assert vv_preload is not None

        # MiniVideoViewer
        mv_local = f_mod.IndiAllskyMiniVideoViewer(camera_id=cam_id, local=True)
        assert len(mv_local.getYears()) > 0
        assert len(mv_local.getMonths(now.year)) > 0
        assert len(mv_local.getVideos(now.year, now.month)) > 0

        mv_remote = f_mod.IndiAllskyMiniVideoViewer(camera_id=cam_id, local=False)
        mv_remote.getYears()
        mv_remote.getMonths(now.year)
        mv_remote.getVideos(now.year, now.month)

        mv_preload = f_mod.IndiAllskyMiniVideoViewerPreload(camera_id=cam_id, local=True)
        assert mv_preload is not None


# ==============================================================================
# Timelapse Generator Forms
# ==============================================================================

def test_timelapse_generator_forms(flask_app, viewer_db_data):
    cam_id, now = viewer_db_data
    with flask_app.test_request_context():
        # IndiAllskyTimelapseGeneratorForm_old
        t_old = f_mod.IndiAllskyTimelapseGeneratorForm_old(camera_id=cam_id)
        assert t_old is not None
        assert len(t_old.DAY_SELECT.choices) > 0

        # IndiAllskyTimelapseGeneratorForm
        t_new = f_mod.IndiAllskyTimelapseGeneratorForm(camera_id=cam_id)
        assert t_new is not None
        assert len(t_new.DAY_SELECT.choices) > 0


# ==============================================================================
# Network & Drive Manager Forms
# ==============================================================================

def test_network_manager_form(flask_app):
    with flask_app.test_request_context():
        # 1. D-Bus exception
        with patch('dbus.SystemBus', side_effect=dbus.exceptions.DBusException('no dbus')):
            nm_form = f_mod.IndiAllskyNetworkManagerForm()
            assert nm_form is not None

        # 2. Mocked D-Bus with active connections and devices
        mock_bus = MagicMock()
        mock_nm_settings = MagicMock()
        mock_nm_settings.Get.return_value = ['/org/freedesktop/NetworkManager/Settings/1']

        mock_setting_conn = MagicMock()
        mock_setting_conn.GetSettings.return_value = {
            'connection': {
                'uuid': 'conn-uuid-1',
                'id': 'Wired Connection 1',
                'type': '802-3-ethernet',
                'interface-name': 'eth0',
                'autoconnect': True,
                'autoconnect-priority': 0,
            },
            'ipv4': {'address-data': [{'address': '192.168.1.50'}]},
        }

        mock_nm = MagicMock()
        mock_nm.Get.side_effect = lambda iface, prop, dbus_interface=None: (
            ['/org/freedesktop/NetworkManager/ActiveConnection/1'] if prop == 'ActiveConnections' else []
        )

        mock_active_conn = MagicMock()
        mock_active_conn.Get.side_effect = lambda iface, prop, dbus_interface=None: (
            'conn-uuid-1' if prop == 'Uuid' else
            2 if prop == 'State' else
            '/org/freedesktop/NetworkManager/IP4Config/1' if prop == 'Ip4Config' else
            ['/org/freedesktop/NetworkManager/Devices/1'] if prop == 'Devices' else ''
        )

        mock_ip4_config = MagicMock()
        mock_ip4_config.Get.return_value = [{'address': '192.168.1.50'}]

        mock_dev = MagicMock()
        mock_dev.Get.return_value = 'eth0'

        def mock_get_object(bus_name, object_path):
            if 'Settings/1' in object_path:
                return mock_setting_conn
            if 'Settings' in object_path:
                return mock_nm_settings
            if 'ActiveConnection' in object_path:
                return mock_active_conn
            if 'IP4Config' in object_path:
                return mock_ip4_config
            if 'Devices' in object_path:
                return mock_dev
            return mock_nm

        mock_bus.get_object.side_effect = mock_get_object

        with patch('dbus.SystemBus', return_value=mock_bus), \
             patch('dbus.Interface', side_effect=lambda obj, iface: obj):
            nm_form2 = f_mod.IndiAllskyNetworkManagerForm()
            assert len(nm_form2.CONNECTIONS_SELECT.choices) > 0


def test_drive_manager_form(flask_app):
    with flask_app.test_request_context():
        # 1. D-Bus exception
        with patch('dbus.SystemBus', side_effect=dbus.exceptions.DBusException('no dbus')):
            dm_form = f_mod.IndiAllskyDriveManagerForm()
            assert dm_form is not None

        # 2. Mocked D-Bus with drives and devices
        mock_bus = MagicMock()
        mock_obj_mgr = MagicMock()
        mock_obj_mgr.GetManagedObjects.return_value = {
            '/org/freedesktop/UDisks2/drives/drive1': {},
            '/org/freedesktop/UDisks2/block_devices/sda1': {},
        }

        mock_drive_props = MagicMock()
        mock_drive_props.GetAll.return_value = {
            'Id': 'drive-1-id',
            'Vendor': 'Kingston',
            'Model': 'DataTraveler',
            'Size': 32000000000,
            'ConnectionBus': 'usb',
            'Removable': 1,
            'CanPowerOff': 1,
        }

        mock_block_props = MagicMock()
        mock_block_props.GetAll.return_value = {
            'Id': 'sda1-id',
            'IdLabel': 'USB_DISK',
            'IdUUID': 'uuid-sda1',
            'Drive': '/org/freedesktop/UDisks2/drives/drive1',
            'Size': 32000000000,
            'IdType': 'vfat',
            'Device': '/dev/sda1',
            'ReadOnly': 0,
            'MountPoints': [b'/media/usb'],
        }

        def mock_get_obj(bus_name, object_path):
            if 'drives' in object_path:
                return mock_drive_props
            if 'block_devices' in object_path:
                return mock_block_props
            return mock_obj_mgr

        mock_bus.get_object.side_effect = mock_get_obj

        with patch('dbus.SystemBus', return_value=mock_bus), \
             patch('dbus.Interface', side_effect=lambda obj, dbus_interface=None: obj):
            dm_form2 = f_mod.IndiAllskyDriveManagerForm()
            assert dm_form2 is not None


# ==============================================================================
# Helper & Processing Forms
# ==============================================================================

def test_image_processing_form_and_helpers(flask_app):
    with flask_app.test_request_context():
        # IndiAllskyImageProcessingForm
        ip_form = f_mod.IndiAllskyImageProcessingForm(data={
            'PROCESSING_SELECT': '1',
            'CFA_PATTERN': 'RGGB',
            'IMAGE_COLORMAP': 'NONE',
            'WB_FACTOR_RED': 1.0,
            'WB_FACTOR_GREEN': 1.0,
            'WB_FACTOR_BLUE': 1.0,
        })
        assert ip_form is not None

        # IndiAllskyLongTermKeogramForm
        ltk_form = f_mod.IndiAllskyLongTermKeogramForm(data={
            'CAMERA_ID': 1,
            'DAYS_SELECT': '7',
            'HOURS_SELECT': '24',
        })
        assert ltk_form is not None

        # Circle helper, VirtualSky helper, Simulator forms
        ch = f_mod.IndiAllskyImageCircleHelperForm(data={
            'IMAGE_CIRCLE_DIAMETER': 800,
            'OFFSET_X': 0,
            'OFFSET_Y': 0,
            'LINE_WIDTH': 5,
            'LINE_COLOR': '#00ff00',
            'KEOGRAM_LINE': True,
            'KEOGRAM_ANGLE': 0.0,
            'AZIMUTH_ANGLE': 0.0,
        })
        assert ch.validate() is True

        vsh = f_mod.IndiAllskyVirtualSkyHelperForm(data={
            'AZIMUTH_ANGLE': 90.0,
            'LATITUDE_OFFSET': 0.0,
            'LONGITUDE_OFFSET': 0.0,
            'IMAGE_CIRCLE_DIAMETER': 800,
            'OFFSET_X': 0,
            'OFFSET_Y': 0,
            'MAGNITUDE': 5.0,
            'CONSTELLATIONS': True,
            'CONSTELLATIONLABELS': True,
            'SHOWSTARS': True,
            'SHOWSTARLABELS': True,
            'SHOWPLANETS': True,
            'SHOWPLANETLABELS': True,
        })
        assert vsh.validate() is True

        sim = f_mod.IndiAllskyCameraSimulatorForm(data={
            'SENSOR_SELECT': 'imx219',
            'LENS_SELECT': 'm12_f2.1_0.76mm_1-3.2',
            'OFFSET_X': 0,
            'OFFSET_Y': 0,
        })
        assert sim is not None
        assert sim.validate() is True
