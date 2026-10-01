import io
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import ephem
import pytest
import simple_websocket
from sqlalchemy.exc import SQLAlchemyError

from indi_allsky.flask import db
from indi_allsky.flask.models import (
    IndiAllSkyDbFitsImageTable,
    IndiAllSkyDbBadPixelMapTable,
)
from indi_allsky.flask.views import (
    AjaxAsi676mcCalibrationDatabaseView,
    AjaxAsi676mcCalibrationStartView,
    AjaxAsi676mcCalibrationApplyView,
    ImageProcessingView,
    JsonImageProcessingView,
    FileSpaceUsageView,
    JsonLongTermKeogramView,
    AjaxAstroPanelView,
    WsShellView,
    WsEventsView,
    WsControlView,
)


def _always_valid(self, *args, **kwargs):
    return True


class DefaultDict(dict):
    def __getitem__(self, item):
        if item in self:
            return super().__getitem__(item)
        return 0


def test_asi676mc_calibration_error_paths(flask_app, system_db):
    """Test ASI676MC database search, calibration start, and apply failure paths."""
    cam = system_db
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    # ASI676MC Lines 8576-8577, 8595-8596
    with flask_app.test_request_context('/admin/ajax/asi676mc/database', method='POST', json={
        'session_id': 's1',
        'camera_id': cam.id,
        'target_groups': 20,
        'max_pair_seconds': 90.0,
    }):
        with patch('flask_login.utils._get_user', return_value=mock_user), \
             patch('indi_allsky.flask.views._supported_asi676mc_camera', return_value=cam), \
             patch('indi_allsky.asi676mc_calibration.database_search_checkpoint', return_value={'camera': {'id': 'not_an_int'}}):
            s_view = AjaxAsi676mcCalibrationDatabaseView()
            r_s, c_s = s_view.dispatch_request()
            assert c_s == 409

    with flask_app.test_request_context('/admin/ajax/asi676mc/database', method='POST', json={
        'session_id': 's1',
        'camera_id': cam.id,
        'target_groups': 20,
        'max_pair_seconds': 90.0,
    }):
        with patch('flask_login.utils._get_user', return_value=mock_user), \
             patch('indi_allsky.flask.views._supported_asi676mc_camera', return_value=cam), \
             patch('indi_allsky.asi676mc_calibration.database_search_checkpoint', return_value={'camera': {'id': cam.id, 'uuid': cam.uuid}}):
            s_view = AjaxAsi676mcCalibrationDatabaseView()
            s_view.indi_allsky_config = {'IMAGE_FITS_EXPIRE_DAYS': 'invalid_days'}
            r_ret, c_ret = s_view.dispatch_request()
            assert c_ret == 400

    # Lines 8844-8845: mark_failed raises CalibrationSessionError
    from indi_allsky import asi676mc_calibration
    with flask_app.test_request_context('/admin/ajax/asi676mc/start/s1', method='POST', json={'max_pair_seconds': 90.0}):
        with patch('flask_login.utils._get_user', return_value=mock_user), \
             patch('indi_allsky.flask.views._supported_asi676mc_camera', return_value=cam), \
             patch('indi_allsky.asi676mc_calibration.get_session', return_value=('/tmp', {'camera': {'id': cam.id, 'uuid': cam.uuid}})), \
             patch('indi_allsky.asi676mc_calibration.mark_queued', return_value={'status': 'queued'}), \
             patch('indi_allsky.flask.db.session.commit', side_effect=SQLAlchemyError('db error')), \
             patch('indi_allsky.asi676mc_calibration.mark_failed', side_effect=asi676mc_calibration.CalibrationSessionError('err')):
            c_start = AjaxAsi676mcCalibrationStartView()
            c_start.indi_allsky_config = {'IMAGE_ASI676MC_REPAIR': {}}
            r_cs, code_cs = c_start.dispatch_request('s1')
            assert code_cs == 500

    # Line 9091: original_repair_config is None on ConfigSaveException
    from indi_allsky.config import ConfigSaveException
    with flask_app.test_request_context('/admin/ajax/asi676mc/apply/s1', method='POST', json={
        'confirm_higher_population': True,
    }):
        with patch('flask_login.utils._get_user', return_value=mock_user), \
             patch('indi_allsky.flask.views._supported_asi676mc_camera', return_value=cam), \
             patch('indi_allsky.asi676mc_calibration.get_completed_result', return_value=({'camera': {'id': cam.id, 'uuid': cam.uuid}}, {'status': 'completed', 'outcome': 'standard'}, {'detection': {}})):
            apply_view = AjaxAsi676mcCalibrationApplyView()
            apply_view.indi_allsky_config = {}
            apply_view._indi_allsky_config_obj = MagicMock()
            apply_view._indi_allsky_config_obj.save.side_effect = ConfigSaveException('save err')
            r_ap, c_ap = apply_view.dispatch_request('s1')
            assert c_ap == 409


def test_image_processing_view_and_json_branches(flask_app, system_db):
    """Test ImageProcessingView and JsonImageProcessingView branches."""
    cam = system_db
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True
    mock_user.username = 'admin'
    now = datetime.now(timezone.utc)

    # Line 9196: ImageProcessingView default light frame last fits file
    fits_img = IndiAllSkyDbFitsImageTable(
        filename='proc.fits',
        dayDate=now,
        createDate=now,
        camera=cam,
        exposure=10.0,
        gain=100.0,
    )
    db.session.add(fits_img)
    db.session.commit()

    with flask_app.test_request_context(f'/image_processing?camera_id={cam.id}'):
        with patch('flask_login.utils._get_user', return_value=mock_user):
            ipv = ImageProcessingView(template_name='image_processing.html')
            ipv.setupSession()
            ipv.indi_allsky_config['SQM_ROI'] = True  # Line 9345
            ctx = ipv.get_context()
            assert ctx['form_image_processing'] is not None

    # Line 9446: bpm frame_type, Line 9725: run_detection=False, Lines 9818-9820, 9823, 9830-9831
    bpm = IndiAllSkyDbBadPixelMapTable(
        filename='test_bpm.fits',
        camera=cam,
        bitdepth=16,
        exposure=10,
        gain=100.0,
        binmode=1,
    )
    db.session.add(bpm)
    db.session.commit()

    req_json = DefaultDict({
        'DISABLE_PROCESSING': True,
        'OUTPUT_IMAGE_TYPE': 'jpg',
        'CAMERA_ID': cam.id,
        'FRAME_TYPE': 'bpm',
        'FITS_ID': bpm.id,
        'RUN_DETECTION': False,
    })

    with flask_app.test_request_context(f'/admin/ajax/image_processing?camera_id={cam.id}', method='POST'):
        mock_ipform = MagicMock()
        mock_ipform.validate.return_value = True
        mock_enc_arr = MagicMock()
        mock_enc_arr.tobytes.return_value = b'data'
        mock_file_path = MagicMock()
        mock_file_path.is_file.return_value = True
        mock_file_path.stat.return_value.st_mtime = now.timestamp()
        with patch('flask_login.utils._get_user', return_value=mock_user), \
             patch('flask.Request.json', new_callable=lambda: req_json), \
             patch('indi_allsky.flask.views.IndiAllskyImageProcessingForm', return_value=mock_ipform), \
             patch('astropy.io.fits.open') as mock_fits_open, \
             patch.object(IndiAllSkyDbBadPixelMapTable, 'getLocalOrCachedPath', return_value=mock_file_path):
            mock_hdulist = MagicMock()
            mock_hdulist[0].header = {'EXPTIME': 1.0, 'GAIN': 100.0, 'XBINNING': 1}
            mock_hdulist[0].data = None
            mock_fits_open.return_value = mock_hdulist
            jipv = JsonImageProcessingView()
            jipv.cameraSetup(cam.id)
            with patch('indi_allsky.processing.ImageProcessor.add', return_value=1), \
                 patch('indi_allsky.processing.ImageProcessor.debayer'), \
                 patch('indi_allsky.processing.ImageProcessor.stack'), \
                 patch('indi_allsky.processing.ImageProcessor.convert_16bit_to_8bit'), \
                 patch('indi_allsky.processing.ImageProcessor.rotate_90'), \
                 patch('indi_allsky.processing.ImageProcessor.rotate_angle'), \
                 patch('indi_allsky.processing.ImageProcessor.flip_v'), \
                 patch('indi_allsky.processing.ImageProcessor.flip_h'), \
                 patch('indi_allsky.processing.ImageProcessor.colorize'), \
                 patch('cv2.imencode', return_value=(True, mock_enc_arr)):
                resp = jipv.dispatch_request()
                assert resp.status_code == 200


def test_file_space_usage_and_longterm_keogram(flask_app, system_db):
    """Test FileSpaceUsageView and LongTermKeogram file write."""
    cam = system_db
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True
    mock_user.username = 'admin'

    # FileSpaceUsageView Line 12126: mysql dialect date parsing
    with flask_app.test_request_context(f'/filespaceusage?camera_id={cam.id}'):
        with patch('flask_login.utils._get_user', return_value=mock_user):
            fsu = FileSpaceUsageView(template_name='filespaceusage.html')
            fsu.setupSession()
            mock_row = MagicMock()
            mock_row.dayDate_distinct = datetime.now().date()
            mock_row.night = True
            mock_row.dayDate_sum = 1024
            mock_row.file_count = 1
            mock_row.thumbnail_sum = 256
            mock_row.thumbnail_count = 1
            with patch.object(db.engine.dialect, 'name', 'mysql'):
                tot_size, tot_cnt = fsu.update_dict(dict(), [mock_row], 'Images')
                assert tot_cnt == 2

    # JsonLongTermKeogramView Lines 12343-12344
    with flask_app.test_request_context(f'/admin/ajax/longterm_keogram?camera_id={cam.id}', method='POST', json={
        'CAMERA_ID': cam.id,
        'END_SELECT': 'today',
        'DAYS_SELECT': 5,
        'PIXELS_SELECT': 2,
        'ALIGNMENT_SELECT': 60,
        'OFFSET_SELECT': 0,
        'REVERSE': False,
        'LABEL': False,
    }):
        mock_form_ltk = MagicMock()
        mock_form_ltk.validate.return_value = True
        with patch('flask_login.utils._get_user', return_value=mock_user), \
             patch('indi_allsky.flask.views.IndiAllskyLongTermKeogramForm', return_value=mock_form_ltk), \
             patch('indi_allsky.longTermKeogram.LongTermKeogramGenerator.generate', return_value=b'\x00' * 100), \
             patch('cv2.cvtColor', return_value=MagicMock()), \
             patch('PIL.Image.fromarray') as mock_img_arr, \
             patch('builtins.open', MagicMock()), \
             patch('io.open', MagicMock()):
            mock_pil = MagicMock()
            mock_img_arr.return_value = mock_pil
            jltv = JsonLongTermKeogramView()
            jltv.cameraSetup(cam.id)
            r_lt = jltv.dispatch_request()
            assert r_lt.status_code == 200


def test_astro_view_calculations(flask_app, system_db):
    """Test AjaxAstroPanelView astronomy calculations and moon phase branches."""
    with flask_app.test_request_context('/ajax/astropanel?camera_id=1'):
        astro = AjaxAstroPanelView()
        obs = ephem.Observer()
        obs.lat = '0.0'
        obs.lon = '0.0'
        obs.elevation = 0
        obs.date = ephem.Date('2026/09/21 12:00:00')

        # Test astropanel_get_moon_phase branches
        with patch('ephem.localtime') as mock_local:
            mock_d = MagicMock()
            mock_d.date.return_value = datetime(2026, 9, 21).date()
            mock_local.return_value = mock_d
            phase = astro.astropanel_get_moon_phase(obs)
            assert isinstance(phase, (str, type(None)))

        # Test astropanel_get_polaris_data with normalized pha
        with patch('math.degrees', return_value=-50.0):
            pdata = astro.astropanel_get_polaris_data(obs)
            assert len(pdata) == 3


def test_ws_shell_events_and_control_exception_branches(flask_app, system_db):
    """Test websocket exception and error handling branches."""
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    # WsShellView Lines 14251-14252, 14256-14257, 14282-14283, 14288-14289, 14296-14297
    def mock_close(fd):
        if fd == 10:  # master fd closing in finally
            raise OSError('master close err')
        return None

    with flask_app.test_request_context('/ws/shell'):
        with patch('flask_login.utils._get_user', return_value=mock_user), \
             patch('simple_websocket.Server.accept') as mock_ws_accept, \
             patch('pty.openpty', return_value=(10, 11)), \
             patch('subprocess.Popen') as mock_popen, \
             patch('os.close', side_effect=mock_close):
            mock_ws = MagicMock()
            mock_ws.receive.side_effect = [json.dumps({'type': 'invalid_json_action'}), None]
            mock_ws.close.side_effect = Exception('ws close err')
            mock_ws_accept.return_value = mock_ws
            proc_mock = MagicMock()
            proc_mock.terminate.side_effect = Exception('term err')
            proc_mock.kill.side_effect = Exception('kill err')
            mock_popen.return_value = proc_mock

            ws_shell = WsShellView()
            with patch.object(ws_shell, 'verify_admin_network', return_value=True):
                res = ws_shell.dispatch_request()
                assert res == ''

    # WsEventsView Lines 14399-14400, 14407-14408
    with flask_app.test_request_context('/ws/events'):
        with patch('simple_websocket.Server.accept') as mock_ws_accept:
            mock_ws = MagicMock()
            # Send one message that throws in json processing, then end loop
            mock_ws.receive.side_effect = ['{"type": "sensors"}', None]
            mock_ws.close.side_effect = Exception('close err')
            mock_ws_accept.return_value = mock_ws
            wsev = WsEventsView()
            with patch('indi_allsky.events.event_manager.unregister'), \
                 patch('indi_allsky.sensors_mapping.get_latest_sensors_payload', side_effect=Exception('sensor fetch err')):
                res = wsev.dispatch_request()
                assert res == ''

    # WsControlView Lines 14477-14480, 14609-14610, 14617-14618
    with flask_app.test_request_context('/ws/control?api_key=valid_key'):
        with patch('flask_login.utils._get_user', return_value=mock_user), \
             patch('simple_websocket.Server.accept') as mock_ws_accept:
            mock_ws = MagicMock()
            mock_ws.send.side_effect = Exception('handshake send err')
            mock_ws_accept.return_value = mock_ws
            wsc = WsControlView()
            flask_app.config['WEBSOCKET_API_KEY'] = 'valid_key'
            res = wsc.dispatch_request()
            assert res == ''

    with flask_app.test_request_context('/ws/control?api_key=valid_key'):
        with patch('flask_login.utils._get_user', return_value=mock_user), \
             patch('simple_websocket.Server.accept') as mock_ws_accept:
            mock_ws = MagicMock()
            mock_ws.receive.side_effect = ['{"type": "pause"}', None]
            mock_ws.close.side_effect = Exception('close err')
            mock_ws_accept.return_value = mock_ws
            wsc = WsControlView()
            flask_app.config['WEBSOCKET_API_KEY'] = 'valid_key'
            with patch('indi_allsky.events.event_manager.unregister'), \
                 patch('indi_allsky.flask.db.session.add', side_effect=Exception('db err')):
                res = wsc.dispatch_request()
                assert res == ''
