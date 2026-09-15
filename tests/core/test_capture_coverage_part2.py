import ctypes
from datetime import datetime, timedelta, timezone
from multiprocessing import Array, Queue
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky import constants
from indi_allsky.capture import CaptureWorker
from indi_allsky.exceptions import TemperatureException
from indi_allsky.flask import db
from indi_allsky.flask.models import IndiAllSkyDbCameraTable, IndiAllSkyDbImageTable
from tests.core.test_capture import capture_worker_setup


def make_mock_ccd_info():
    return {
        'CCD_CFA': {'CFA_TYPE': {'text': 'RGGB'}},
        'SERIALNUMBER_INFO': {'text': 'SIM-12345'},
        'CCD_EXPOSURE': {'CCD_EXPOSURE_VALUE': {'min': '0.001', 'max': '60.0'}},
        'GAIN_INFO': {'min': '0.0', 'max': '500.0'},
        'BINNING_INFO': {'min': '1', 'max': '4'},
        'CCD_FRAME': {'WIDTH': {'max': '1920'}, 'HEIGHT': {'max': '1080'}},
        'CCD_INFO': {'CCD_BITSPERPIXEL': {'current': '16'}, 'CCD_PIXEL_SIZE': {'current': '3.75'}},
    }


def make_mock_indiclient():
    client = MagicMock()
    client.disconnected = False
    client.ccd_removed = False
    client.ccd_device = MagicMock()
    client.ccd_device.getDeviceName.return_value = 'CCD Simulator'
    client.ccd_device.getDriverExec.return_value = 'indi_simulator_ccd'
    client.telescope_device = None
    client.gps_device = None
    client.camera_id = 1
    client.ccd_temp = 20.0
    client.findCcd.return_value = 'CCD Simulator'
    client.connectServer.return_value = True
    client.getHost.return_value = 'localhost'
    client.getPort.return_value = 7624
    client.getIndiAllskyCameraName.return_value = 'Test Simulator CCD'
    client.getCcdInfo.return_value = make_mock_ccd_info()
    client.getCcdTemperature.return_value = 20.0
    client.getGpsPosition.return_value = (-34.9285, 138.6007, 50.0)
    client.getTelescopeRaDec.return_value = (180.0, 45.0)
    client.getCcdExposureStatus.return_value = (True, 'Idle')
    return client


@pytest.fixture
def capture_worker(capture_worker_setup):
    worker = capture_worker_setup
    worker.night = True
    worker.moonmode = False
    worker.night_av[constants.NIGHT_NIGHT] = 1
    worker.night_av[constants.NIGHT_MOONMODE] = 0
    worker.config['DAYTIME_CAPTURE'] = True
    worker.config['NIGHT_CAPTURE'] = True
    worker._initialize = MagicMock()
    worker._pre_run_tasks = MagicMock()
    worker.detectNight = MagicMock()
    return worker


def test_saferun_moonmode_switch(capture_worker, app):
    """Cover line 470: self.reconfigure_camera = True on moonmode state change."""
    worker = capture_worker
    with app.app_context():
        worker.indiclient = make_mock_indiclient()
        worker.shoot = MagicMock()
        worker.reconfigureCcd = MagicMock()

        worker.night = True
        worker.moonmode = False
        worker.night_av[constants.NIGHT_NIGHT] = 1
        worker.night_av[constants.NIGHT_MOONMODE] = 0

        iteration = 0
        def mock_detect_night():
            nonlocal iteration
            iteration += 1
            if iteration >= 2:
                worker.night_av[constants.NIGHT_MOONMODE] = 1
                worker._shutdown = True

        worker.detectNight = MagicMock(side_effect=mock_detect_night)
        worker.saferun()

        assert worker.reconfigure_camera is True


def test_saferun_capture_pause_sleep_continue(capture_worker, app):
    """Cover lines 551-552: time.sleep(31); continue when capture is paused."""
    worker = capture_worker
    with app.app_context():
        worker.indiclient = make_mock_indiclient()

        worker.night = True
        worker.moonmode = False
        worker.night_av[constants.NIGHT_NIGHT] = 1
        worker.config['CAPTURE_PAUSE'] = True

        sleep_calls = []

        def sleep_stop(s):
            sleep_calls.append(s)
            worker._shutdown = True

        with patch('time.sleep', side_effect=sleep_stop):
            worker.saferun()

        assert 31 in sleep_calls


def test_saferun_daytime_capture_disabled_sleep_continue(capture_worker, app):
    """Cover lines 572-573: time.sleep(31); continue when daytime capture disabled."""
    worker = capture_worker
    with app.app_context():
        worker.indiclient = make_mock_indiclient()

        worker.night = False
        worker.moonmode = False
        worker.night_av[constants.NIGHT_NIGHT] = 0
        worker.config['DAYTIME_CAPTURE'] = False

        sleep_calls = []

        def sleep_stop(s):
            sleep_calls.append(s)
            worker._shutdown = True

        with patch('time.sleep', side_effect=sleep_stop):
            worker.saferun()

        assert 31 in sleep_calls


def test_saferun_exposure_hung_abort_and_reset(capture_worker, app):
    """Cover lines 582-590 and 610-614: camera hung abort and exposure_aborted reset."""
    worker = capture_worker
    with app.app_context():
        worker.indiclient = make_mock_indiclient()
        worker.shoot = MagicMock()
        worker.reconfigureCcd = MagicMock()

        worker.night = True
        worker.moonmode = False
        worker.night_av[constants.NIGHT_NIGHT] = 1
        worker.exposure_timeout = 5
        base_time = 100000.0

        time_seq = [
            base_time,        # next_check_exposure_state
            base_time,        # next_forced_transition_time calc
            base_time,        # logger
            base_time + 50.0, # loop_start_time
            base_time + 50.0, # camera_ready_time diff
            base_time + 50.0, # next_check_exposure_state update
            base_time + 50.0, # loop_end calc
            base_time + 50.0, # inner now_time check 1
            base_time + 50.0, # camera_ready_time = now_time
            base_time + 50.0, # periodic_tasks_time check
            base_time + 50.0, # next_frame_time check
            base_time + 50.0, # now_time in queue check
            base_time + 100.0,# inner now_time check 2 (exceeds loop_end)
            base_time + 100.0,# loop_elapsed
        ]

        def get_time():
            if time_seq:
                return time_seq.pop(0)
            worker._shutdown = True
            return base_time + 200.0

        def sleep_mock(s):
            pass

        with patch('time.time', side_effect=get_time), patch('time.sleep', side_effect=sleep_mock):
            worker.saferun()

        worker.indiclient.abortCcdExposure.assert_called()


def test_saferun_camera_not_ready_continue(capture_worker, app):
    """Cover line 618: if not camera_ready: continue."""
    worker = capture_worker
    with app.app_context():
        worker.indiclient = make_mock_indiclient()
        worker.shoot = MagicMock()
        worker.reconfigureCcd = MagicMock()

        worker.night = True
        worker.moonmode = False
        worker.night_av[constants.NIGHT_NIGHT] = 1

        worker.indiclient.getCcdExposureStatus.return_value = (False, 'Exposing')

        iteration = 0
        def sleep_stop(s):
            nonlocal iteration
            iteration += 1
            if iteration >= 2:
                worker._shutdown = True
                worker.indiclient.disconnected = True

        with patch('time.sleep', side_effect=sleep_stop):
            worker.saferun()

        assert worker.indiclient.getCcdExposureStatus.call_count >= 1


def test_saferun_pycurl_and_indi_passive_delta(capture_worker, app):
    """Cover lines 641 and 644: camera does not obey exposure values branches."""
    for iface in ['pycurl_dummy', 'indi_passive']:
        worker = capture_worker
        with app.app_context():
            worker.indiclient = make_mock_indiclient()
            worker.shoot = MagicMock()
            worker.reconfigureCcd = MagicMock()

            worker.night = True
            worker.moonmode = False
            worker.night_av[constants.NIGHT_NIGHT] = 1
            worker.config['CAMERA_INTERFACE'] = iface
            worker._expUtils.EXPOSURE_CURRENT = 10.0
            worker._shutdown = False

            base_time = 100000.0
            time_seq = [
                base_time,        # init next_check
                base_time,        # init transition
                base_time,        # logger
                base_time + 1.0,  # loop_start
                base_time + 1.0,  # camera_ready_time diff
                base_time + 1.0,  # loop_end calc
                base_time + 1.0,  # now_time
                base_time + 1.0,  # periodic check
                base_time + 1.0,  # next_frame_time check
                base_time + 1.0,  # qsize check
                base_time + 1.05, # now_time (delta = 0.05 - 10 = -9.95 < -1)
                base_time + 1.05, # camera_ready_time = now_time
                base_time + 1.05, # periodic check
                base_time + 1.05, # next_frame_time check
                base_time + 50.0, # inner now_time (exceeds loop_end)
                base_time + 50.0, # loop_elapsed
            ]

            def get_time():
                if time_seq:
                    return time_seq.pop(0)
                worker._shutdown = True
                return base_time + 200.0

            with patch('time.time', side_effect=get_time), patch('time.sleep', return_value=None):
                worker.saferun()


def test_saferun_periodic_tasks_trigger(capture_worker, app):
    """Cover line 679: periodic_tasks execution."""
    worker = capture_worker
    with app.app_context():
        worker.indiclient = make_mock_indiclient()
        worker.shoot = MagicMock()
        worker.reconfigureCcd = MagicMock()
        worker._periodic_tasks = MagicMock()

        worker.night = True
        worker.moonmode = False
        worker.night_av[constants.NIGHT_NIGHT] = 1
        worker.periodic_tasks_time = 0.0  # in past

        iteration = 0
        def sleep_stop(s):
            nonlocal iteration
            iteration += 1
            if iteration >= 2:
                worker._shutdown = True

        with patch('time.sleep', side_effect=sleep_stop):
            worker.saferun()

        worker._periodic_tasks.assert_called()


def test_saferun_sqm_day_and_expired(capture_worker, app):
    """Cover lines 745-756, 758-764, and 771-776: SQM day exposures and non-SQM fallbacks."""
    worker = capture_worker
    with app.app_context():
        worker.indiclient = make_mock_indiclient()
        worker.shoot = MagicMock()
        worker.reconfigureCcd = MagicMock()

        # Case 1: SQM daytime exposure triggered (lines 745-756)
        worker.night = False
        worker.moonmode = False
        worker.night_av[constants.NIGHT_NIGHT] = 0
        worker.config['DAYTIME_CAPTURE'] = True
        worker.sqm_camera_enable = True
        worker.focus_mode = False
        worker.sqm_tasks_time = 0.0
        worker.astro_av[constants.ASTRO_SUN_ALT] = 5.0
        worker.sqm_camera_enable_day = True
        worker._shutdown = False

        iteration = 0
        def sleep_stop1(s):
            nonlocal iteration
            iteration += 1
            if iteration >= 2:
                worker._shutdown = True

        with patch('time.sleep', side_effect=sleep_stop1):
            worker.saferun()

        assert worker.shoot.called
        worker.shoot.reset_mock()

        # Case 2: SQM daytime disabled fallback (lines 758-764)
        worker.sqm_camera_enable_day = False
        worker.sqm_tasks_time = 0.0
        worker._shutdown = False
        iteration = 0

        with patch('time.sleep', side_effect=sleep_stop1):
            worker.saferun()

        assert worker.shoot.called
        worker.shoot.reset_mock()

        # Case 3: SQM tasks time in future fallback (lines 771-776)
        worker.sqm_tasks_time = 9999999999.0
        worker._shutdown = False
        iteration = 0

        with patch('time.sleep', side_effect=sleep_stop1):
            worker.saferun()

        assert worker.shoot.called


def test_saferun_queue_under_minimum_and_focus_mode_delay(capture_worker, app):
    """Cover lines 790-792, 811-812, and 819."""
    worker = capture_worker
    with app.app_context():
        worker.indiclient = make_mock_indiclient()
        worker.shoot = MagicMock()
        worker.reconfigureCcd = MagicMock()

        # Queue under minimum with delay (lines 790-792) + Focus mode (lines 811-812)
        worker.night = True
        worker.moonmode = False
        worker.night_av[constants.NIGHT_NIGHT] = 1
        worker.add_period_delay = 5.0
        worker.image_queue_min = 2
        worker.image_q.qsize = MagicMock(return_value=1)
        worker.focus_mode = True
        worker._shutdown = False

        iteration = 0
        def sleep_stop1(s):
            nonlocal iteration
            iteration += 1
            if iteration >= 2:
                worker._shutdown = True

        with patch('time.sleep', side_effect=sleep_stop1):
            worker.saferun()

        assert worker.add_period_delay == 0.0

        # Daytime next_frame_time (line 819)
        worker.focus_mode = False
        worker.night = False
        worker.moonmode = False
        worker.night_av[constants.NIGHT_NIGHT] = 0
        worker.config['DAYTIME_CAPTURE'] = True
        worker._shutdown = False
        iteration = 0

        with patch('time.sleep', side_effect=sleep_stop1):
            worker.saferun()


def test_initialize_s3_prefix_value_error(capture_worker_setup, app):
    """Cover lines 1012-1014: ValueError when formatting S3 prefix in _initialize()."""
    worker = capture_worker_setup
    with app.app_context():
        mock_client = make_mock_indiclient()
        worker.config['CAMERA_INTERFACE'] = 'indi'
        worker.config['S3UPLOAD'] = {
            'URL_TEMPLATE': '{unclosed_brace',
        }

        with patch('indi_allsky.camera.indi', return_value=mock_client):
            worker._initialize()


def test_initialize_exposure_and_gain_bounds(capture_worker_setup, app):
    """Cover lines 1472, 1474, and 1479: clamping exposure and gain in _initialize()."""
    worker = capture_worker_setup
    with app.app_context():
        mock_client = make_mock_indiclient()
        worker.config['CAMERA_INTERFACE'] = 'indi'
        worker.config['CCD_EXPOSURE_DEF'] = 99999.0
        with patch('indi_allsky.camera.indi', return_value=mock_client), patch('time.sleep'):
            worker._initialize()

        worker.config['CCD_EXPOSURE_DEF'] = 0.0001
        with patch('indi_allsky.camera.indi', return_value=mock_client), patch('time.sleep'):
            worker._initialize()

        worker.config['CCD_EXPOSURE_DEF'] = 0.0
        cams = IndiAllSkyDbCameraTable.query.all()
        now = datetime.now()
        for c in cams:
            img = IndiAllSkyDbImageTable(
                filename=f'test_image_{c.id}.jpg',
                camera_id=c.id,
                createDate=now,
                dayDate=now.date(),
                exposure=1.0,
                gain=99999.0,
                binmode=1,
                temp=20.0,
                adu=1000.0,
                night=True,
                data={},
            )
            db.session.add(img)
        db.session.commit()
        with patch('indi_allsky.camera.indi', return_value=mock_client), patch('time.sleep'):
            worker._initialize()


def test_get_external_temperature_unlink_permission_error(capture_worker, app, tmp_path):
    """Cover lines 1716-1717: PermissionError when unlinking temp file in getExternalTemperature."""
    worker = capture_worker
    with app.app_context():
        script_p = tmp_path / 'temp_script.sh'
        script_p.write_text('#!/bin/sh\necho hi\n')
        script_p.chmod(0o755)

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.wait = MagicMock()

        with patch('subprocess.Popen', return_value=mock_proc), \
             patch.object(Path, 'unlink', side_effect=PermissionError):
            with pytest.raises(TemperatureException):
                worker.getExternalTemperature(str(script_p))
