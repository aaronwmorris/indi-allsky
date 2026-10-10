import io
import os
import socket
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
import dbus
import pytest
from passlib.hash import argon2

from indi_allsky.flask import db
from indi_allsky.flask.models import (
    IndiAllSkyDbImageTable,
    IndiAllSkyDbTaskQueueTable,
    TaskQueueQueue,
    TaskQueueState,
)
from indi_allsky.flask.views import (
    ConfigView,
    AjaxConfigView,
    SystemInfoView,
    AjaxSystemInfoView,
    AjaxIndiServerChangeView,
    TimelapseGeneratorView,
    AjaxTimelapseGeneratorView,
    UserInfoView,
    AjaxUserInfoView,
    AjaxCustomCssView,
    AjaxConfigRestoreView,
    CameraLensView,
    NetworkManagerView,
    AjaxNetworkManagerView,
    DriveManagerView,
    AjaxDriveManagerView,
)


def _get_status(res):
    if isinstance(res, tuple):
        return res[1]
    return res.status_code


def test_config_view_and_ajax_config_view_branches(flask_app, system_db):
    """Test ConfigView and AjaxConfigView edge cases."""
    cam = system_db
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True
    mock_user.username = 'admin'

    with flask_app.test_request_context(f'/admin/config?camera_id={cam.id}'):
        with patch('flask_login.utils._get_user', return_value=mock_user):
            cview = ConfigView(template_name='config.html')
            cview.setupSession()
            cview._miscDb = MagicMock()
            cview._miscDb.getState.return_value = 'some_credentials'
            # Lines 3276, 3278, 3304, 3306, 3332, 3334, 3411
            cview.indi_allsky_config.update({
                'ADU_ROI': None,
                'SQM_ROI': False,
                'IMAGE_CROP_ROI': None,
                'YOUTUBE': {'TAGS': ['allsky', 'space']},
            })
            # Lines 3501-3503: invalid network address
            mock_addr = MagicMock()
            mock_addr.family = socket.AF_INET
            mock_addr.netmask = '255.255.255.0'
            mock_addr.address = '999.999.999.999'
            with patch('psutil.net_if_addrs', return_value={'eth0': [mock_addr]}):
                ctx = cview.get_context()
                assert ctx['form_config'] is not None

    # AjaxConfigView: Line 3551 (empty self.indi_allsky_config)
    with flask_app.test_request_context(f'/admin/ajax/config?camera_id={cam.id}', method='POST', json={'SOME_KEY': 1}):
        with patch('flask_login.utils._get_user', return_value=mock_user):
            mock_form_instance = MagicMock()
            mock_form_instance.validate.return_value = True
            mock_form_instance.errors = {}
            with patch('indi_allsky.flask.views.IndiAllskyConfigForm', return_value=mock_form_instance):
                acview = AjaxConfigView()
                acview.cameraSetup(cam.id)
                acview.indi_allsky_config = {}
                res = acview.dispatch_request()
                assert _get_status(res) == 400


def test_system_info_fans_and_flush_deletions(flask_app, system_db):
    """Test SystemInfoView fan errors, AjaxSystemInfoView mountpoints, and Admin flush operations."""
    cam = system_db
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True
    mock_user.username = 'admin'

    with flask_app.test_request_context(f'/admin/system_info?camera_id={cam.id}'):
        with patch('flask_login.utils._get_user', return_value=mock_user):
            siv = SystemInfoView(template_name='system_info.html')
            siv.setupSession()
            # Lines 6090-6091, 6093-6094: Exception reading fan file and globbing
            mock_fan_p = MagicMock()
            mock_fan_p.read_text.side_effect = Exception('read error')
            with patch('psutil.sensors_fans', return_value={}), \
                 patch('pathlib.Path.glob', return_value=[mock_fan_p]):
                fans = siv.getFans()
                assert isinstance(fans, list)

            with patch('psutil.sensors_fans', return_value={}), \
                 patch('pathlib.Path.glob', side_effect=Exception('sysfs glob error')):
                fans2 = siv.getFans()
                assert isinstance(fans2, list)

    # AjaxSystemInfoView Line 6318: filesystem mountpoint not in ('/', '/var')
    with flask_app.test_request_context(f'/admin/ajax/system_info?camera_id={cam.id}', method='POST', json={
        'CAMERA_ID': cam.id,
        'SERVICE_HIDDEN': flask_app.config['UPGRADE_ALLSKY_SERVICE_NAME'],
        'COMMAND_HIDDEN': 'start',
    }):
        mock_form_sys = MagicMock()
        mock_form_sys.validate.return_value = True
        with patch('flask_login.utils._get_user', return_value=mock_user), \
             patch('indi_allsky.flask.views.IndiAllskySystemInfoForm', return_value=mock_form_sys):
            asiv = AjaxSystemInfoView()
            asiv.cameraSetup(cam.id)
            mock_part = MagicMock()
            mock_part.mountpoint = '/mnt/custom_disk'
            with patch('psutil.disk_partitions', return_value=[mock_part]), \
                 patch.object(asiv, 'startSystemdUnit'):
                res = asiv.dispatch_request()
                assert _get_status(res) == 200

    # Flush operations: Lines 6596, 6657, 6748
    now = datetime.now(timezone.utc)
    img = IndiAllSkyDbImageTable(
        filename='flush_img.jpg',
        dayDate=now,
        createDate=now,
        camera=cam,
        exposure=10.0,
        gain=100.0,
        adu=1000.0,
        night=False,
    )
    db.session.add(img)
    db.session.commit()

    def mock_delete_assets(asset_table, ids):
        for i in ids:
            item = db.session.get(asset_table, i)
            if item:
                db.session.delete(item)
        db.session.commit()
        return len(ids)

    with flask_app.test_request_context(f'/admin/ajax/system_info?camera_id={cam.id}'):
        asiv = AjaxSystemInfoView()
        asiv.cameraSetup(cam.id)
        with patch.object(asiv, '_deleteAssets', side_effect=mock_delete_assets):
            c1 = asiv.flush16MinutesImages(cam.id)
            assert c1 >= 0
            c2 = asiv.flushTimelapses(cam.id)
            assert c2 >= 0
            c3 = asiv.flushDaytime(cam.id)
            assert c3 >= 0


def test_system_services_and_timelapse_generator(flask_app, system_db):
    """Test indiserver lookup, tasklist, action generate_video."""
    cam = system_db
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True
    mock_user.username = 'admin'

    # Line 7165: indiserver found in PATH via shutil.which
    with flask_app.test_request_context(f'/admin/ajax/indiserver_change?camera_id={cam.id}', method='POST', json={
        'CAMERA_SERVER_SELECT': 'indi_simulator_ccd',
        'GPS_SERVER_SELECT': '',
        'RESTART_INDISERVER': False,
    }):
        mock_form_instance = MagicMock()
        mock_form_instance.validate.return_value = True
        with patch('flask_login.utils._get_user', return_value=mock_user), \
             patch('indi_allsky.flask.views.IndiAllskyIndiServerChangeForm', return_value=mock_form_instance), \
             patch('pathlib.Path.exists', side_effect=lambda: False), \
             patch('shutil.which', return_value='/opt/local/bin/indiserver'), \
             patch('io.open', side_effect=lambda *a, **k: io.StringIO('[Unit]\nDescription=INDI\n')), \
             patch('os.getlogin', return_value='indi'), \
             patch('pathlib.Path.chmod'), \
             patch('indi_allsky.flask.views.AjaxIndiServerChangeView.reloadSystemdUnits'):
            aiscv = AjaxIndiServerChangeView()
            aiscv.cameraSetup(cam.id)
            aiscv.indi_allsky_config = {'INDI_PORT': 7624}
            res = aiscv.dispatch_request()
            assert _get_status(res) == 200

    # Line 7272: TimelapseGeneratorView with task.data = None
    task_none = IndiAllSkyDbTaskQueueTable(
        queue=TaskQueueQueue.VIDEO,
        state=TaskQueueState.QUEUED,
        priority=100,
        data=None,
    )
    db.session.add(task_none)
    db.session.commit()

    with flask_app.test_request_context(f'/timelapse_generator?camera_id={cam.id}'):
        with patch('flask_login.utils._get_user', return_value=mock_user):
            tgv = TimelapseGeneratorView(template_name='timelapse_generator.html')
            tgv.setupSession()
            ctx = tgv.get_context()
            assert len(ctx['task_list']) > 0

    # Line 7619: AjaxTimelapseGeneratorView action generate_video with night=True
    with flask_app.test_request_context(f'/admin/ajax/timelapse_generator?camera_id={cam.id}', method='POST', json={
        'ACTION_SELECT': 'generate_video',
        'CAMERA_ID': cam.id,
        'DAY_SELECT': '2026-09-20_night',
    }):
        mock_form_tg = MagicMock()
        mock_form_tg.validate.return_value = True
        with patch('flask_login.utils._get_user', return_value=mock_user), \
             patch('indi_allsky.flask.views.IndiAllskyTimelapseGeneratorForm', return_value=mock_form_tg):
            atgv = AjaxTimelapseGeneratorView()
            atgv.cameraSetup(cam.id)
            with patch.object(atgv, 'verify_admin_network', return_value=True):
                res = atgv.dispatch_request()
                assert _get_status(res) == 200


def test_settings_user_info_and_lens_branches(flask_app, system_db):
    """Test custom themes parsing, user info password failure, restore validation, and camera lens math."""
    cam = system_db
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True
    mock_user.username = 'admin'
    mock_user.password = argon2.hash('secret123')

    # UserInfoView Lines 10615-10616: user_custom_themes regex
    with flask_app.test_request_context(f'/userinfo?camera_id={cam.id}'):
        orig_open = io.open
        def custom_open(path, *args, **kwargs):
            if 'custom.css' in str(path):
                return io.StringIO('/* [data-theme=mytheme] { name: "my-dark-theme"; } */')
            return orig_open(path, *args, **kwargs)

        with patch('flask_login.utils._get_user', return_value=mock_user), \
             patch('psutil.boot_time', return_value=1000.0), \
             patch('os.path.exists', return_value=True), \
             patch('builtins.open', side_effect=custom_open):
            sv = UserInfoView(template_name='user_info.html')
            sv.setupSession()
            ctx = sv.get_context()
            assert 'my-dark-theme' in ctx['user_custom_themes']

    # AjaxUserInfoView Lines 10694-10697: wrong current password
    with flask_app.test_request_context(f'/admin/ajax/userinfo?camera_id={cam.id}', method='POST', json={
        'CURRENT_PASSWORD': 'wrong_password',
        'NAME': 'New Name',
        'NEW_PASSWORD': '',
    }):
        mock_uform = MagicMock()
        mock_uform.validate.return_value = True
        with patch('flask_login.utils._get_user', return_value=mock_user), \
             patch('indi_allsky.flask.views.IndiAllskyUserInfoForm', return_value=mock_uform):
            u_view = AjaxUserInfoView()
            u_view.cameraSetup(cam.id)
            res = u_view.dispatch_request()
            assert _get_status(res) == 400
            assert 'CURRENT_PASSWORD' in res[0].get_json()

    # AjaxConfigRestoreView Lines 10911-10912: invalid restore form
    with flask_app.test_request_context(f'/admin/ajax/config_restore?camera_id={cam.id}', method='POST', data={}):
        mock_crform = MagicMock()
        mock_crform.validate.return_value = False
        mock_crform.errors = {'RESTORE_FILE': ['File required']}
        with patch('flask_login.utils._get_user', return_value=mock_user), \
             patch('indi_allsky.flask.views.IndiAllskyConfigRestoreForm', return_value=mock_crform):
            cr_view = AjaxConfigRestoreView()
            cr_view.cameraSetup(cam.id)
            res = cr_view.dispatch_request()
            assert _get_status(res) == 400

    # CameraLensView Lines 11151, 11156, 11162: large image circle diameter
    cam.lensImageCircle = 50000  # greater than camera.width, height, diagonal
    cam.pixelSize = 3.75
    cam.lensFocalLength = 2.5
    cam.lensFocalRatio = 1.4
    db.session.commit()

    with flask_app.test_request_context(f'/cameralens?camera_id={cam.id}'):
        with patch('flask_login.utils._get_user', return_value=mock_user):
            clv = CameraLensView(template_name='cameralens.html')
            clv.setupSession()
            cl_ctx = clv.get_context()
            assert cl_ctx['deg_fov_diagonal'] > 0


def test_network_and_drive_management_branches(flask_app, system_db):
    """Test NetworkManager and DriveManager error and edge branches."""
    cam = system_db
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True
    mock_user.username = 'admin'

    # NetworkManagerView Lines 12401-12402: socket.gethostname split error
    with flask_app.test_request_context(f'/admin/network?camera_id={cam.id}'):
        mock_hostname = MagicMock()
        mock_hostname.split.side_effect = IndexError('empty hostname')
        with patch('flask_login.utils._get_user', return_value=mock_user), \
             patch('indi_allsky.flask.views.IndiAllskyNetworkManagerForm') as mock_nm_cls, \
             patch('socket.gethostname', return_value=mock_hostname):
            mock_nm_cls.return_value = MagicMock()
            nmv = NetworkManagerView(template_name='network.html')
            nmv.setupSession()
            ctx_nm = nmv.get_context()
            assert ctx_nm['hostname'] == 'UNKNOWN'

    # AjaxNetworkManagerView Lines 12627-12628, 12730-12732, 12795-12797
    with flask_app.test_request_context(f'/admin/ajax/network?camera_id={cam.id}', method='POST', json={'COMMAND': 'delete', 'CONNECTION': 'uuid-1'}):
        with patch('flask_login.utils._get_user', return_value=mock_user), \
             patch('dbus.SystemBus.get_object', side_effect=dbus.exceptions.DBusException('dbus failure')):
            anmv = AjaxNetworkManagerView()
            anmv.cameraSetup(cam.id)
            r_del, c_del = anmv.deleteConnection('uuid-1')
            assert c_del == 400

    with flask_app.test_request_context(f'/admin/ajax/network?camera_id={cam.id}', method='POST', json={'COMMAND': 'autostart', 'CONNECTION': 'uuid-1'}):
        with patch('flask_login.utils._get_user', return_value=mock_user), \
             patch('dbus.SystemBus.get_object', side_effect=dbus.exceptions.DBusException('dbus failure')):
            anmv = AjaxNetworkManagerView()
            anmv.cameraSetup(cam.id)
            r_auto, c_auto = anmv.setAutostartConnection('uuid-1')
            assert c_auto == 400

    # DriveManagerView Line 13382: udisks2_installed True
    with flask_app.test_request_context(f'/admin/drives?camera_id={cam.id}'):
        with patch('flask_login.utils._get_user', return_value=mock_user), \
             patch('dbus.SystemBus.get_object', return_value=MagicMock()):
            dmv = DriveManagerView(template_name='drives.html')
            dmv.setupSession()
            ctx_dm = dmv.get_context()
            assert ctx_dm['udisks2_installed'] is True

    # AjaxDriveManagerView Lines 13541, 13559, 13625, 13697
    with flask_app.test_request_context(f'/admin/ajax/drives?camera_id={cam.id}', method='POST', json={'COMMAND': 'poweroff', 'DRIVE_ID': 'drive-target'}):
        with patch('flask_login.utils._get_user', return_value=mock_user):
            mock_iface = MagicMock()
            mock_iface.GetManagedObjects.return_value = ['/org/freedesktop/UDisks2/drives/other_drive']
            mock_props = MagicMock()
            mock_props.GetAll.return_value = {'Id': 'other_drive', 'CanPowerOff': True}
            with patch('dbus.Interface', return_value=mock_iface), \
                 patch('dbus.SystemBus.get_object'):
                adm = AjaxDriveManagerView()
                adm.cameraSetup(cam.id)
                r_po, c_po = adm.powerOffDrive('drive-target')
                assert c_po == 400
