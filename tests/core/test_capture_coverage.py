import ctypes
import json
import os
import signal
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from multiprocessing import Array, Queue
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, call, patch
import pytest

from indi_allsky import constants
from indi_allsky.capture import CaptureWorker
from indi_allsky.exceptions import CameraException, IndiServerException, TemperatureException, TimeOutException
from indi_allsky.flask import create_app, db
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbTaskQueueTable,
    TaskQueueQueue,
    TaskQueueState,
)
import dbus.exceptions
from tests.core.test_capture import capture_worker_setup


def make_mock_ccd_info():
    return {
        'CCD_CFA': {'CFA_TYPE': {'text': 'RGGB'}},
        'SERIALNUMBER_INFO': {'text': 'SIM-12345'},
        'CCD_EXPOSURE': {'CCD_EXPOSURE_VALUE': {'min': '0.0001', 'max': '60.0'}},
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
    client.telescope_device = MagicMock()
    client.telescope_device.getDeviceName.return_value = 'Telescope Simulator'
    client.gps_device = MagicMock()
    client.gps_device.getDeviceName.return_value = 'GPS Simulator'
    client.camera_id = 1
    client.ccd_temp = 20.0
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
    return capture_worker_setup


def test_update_sensor_slot_labels_all_sensors(capture_worker):
    worker = capture_worker

    class DummySensor:
        METADATA = {'name': 'Dummy', 'count': 2}
        @classmethod
        def get_labels(cls, pin):
            return ['probe1', 'probe2']

    worker.config['TEMP_SENSOR'] = {
        'A_CLASSNAME': 'DummySensorA',
        'A_USER_VAR_SLOT': 'sensor_user_10',
        'B_CLASSNAME': 'DummySensorB',
        'B_USER_VAR_SLOT': 'sensor_user_20',
        'C_CLASSNAME': 'DummySensorC',
        'C_USER_VAR_SLOT': 'sensor_user_30',
        'D_CLASSNAME': 'DummySensorD',
        'D_USER_VAR_SLOT': 'sensor_user_40',
        'E_CLASSNAME': 'DummySensorE',
        'E_USER_VAR_SLOT': 'sensor_user_50',
        'F_CLASSNAME': 'DummySensorF',
        'F_USER_VAR_SLOT': 'sensor_user_55',
        'A_PIN_1': 'pin1',
        'B_PIN_1': 'pin2',
        'C_PIN_1': 'pin3',
        'D_PIN_1': 'pin4',
        'E_PIN_1': 'pin5',
        'F_PIN_1': 'pin6',
    }

    from indi_allsky.devices import sensors

    with patch.object(sensors, 'DummySensorA', DummySensor, create=True), \
         patch.object(sensors, 'DummySensorB', DummySensor, create=True), \
         patch.object(sensors, 'DummySensorC', DummySensor, create=True), \
         patch.object(sensors, 'DummySensorD', DummySensor, create=True), \
         patch.object(sensors, 'DummySensorE', DummySensor, create=True), \
         patch.object(sensors, 'DummySensorF', DummySensor, create=True):
        worker.update_sensor_slot_labels()

    assert 'Dummy' in worker.SENSOR_SLOTS[10][1]
    assert 'Dummy' in worker.SENSOR_SLOTS[20][1]
    assert 'Dummy' in worker.SENSOR_SLOTS[30][1]
    assert 'Dummy' in worker.SENSOR_SLOTS[40][1]
    assert 'Dummy' in worker.SENSOR_SLOTS[50][1]
    assert 'Dummy' in worker.SENSOR_SLOTS[55][1]


def test_update_sensor_slot_labels_exceptions(capture_worker):
    worker = capture_worker

    worker.config['TEMP_SENSOR'] = {
        'A_CLASSNAME': 'NonExistentA',
        'B_CLASSNAME': 'NonExistentB',
        'C_CLASSNAME': 'NonExistentC',
        'D_CLASSNAME': 'NonExistentD',
        'E_CLASSNAME': 'NonExistentE',
        'F_CLASSNAME': 'NonExistentF',
    }
    worker.update_sensor_slot_labels()

    class OverflowSensor:
        METADATA = {'name': 'Overflow', 'count': 500}
        @classmethod
        def get_labels(cls, pin):
            return [f'p{i}' for i in range(500)]

    worker.config['TEMP_SENSOR'] = {
        'A_CLASSNAME': 'OverflowSensor',
        'A_USER_VAR_SLOT': 'sensor_user_10',
        'B_CLASSNAME': 'OverflowSensor',
        'B_USER_VAR_SLOT': 'sensor_user_20',
        'C_CLASSNAME': 'OverflowSensor',
        'C_USER_VAR_SLOT': 'sensor_user_30',
        'D_CLASSNAME': 'OverflowSensor',
        'D_USER_VAR_SLOT': 'sensor_user_40',
        'E_CLASSNAME': 'OverflowSensor',
        'E_USER_VAR_SLOT': 'sensor_user_50',
        'F_CLASSNAME': 'OverflowSensor',
        'F_USER_VAR_SLOT': 'sensor_user_55',
    }

    from indi_allsky.devices import sensors
    with patch.object(sensors, 'OverflowSensor', OverflowSensor, create=True):
        worker.update_sensor_slot_labels()


def test_gps_position_adjustments(capture_worker, app):
    worker = capture_worker
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        worker.camera_id = cam.id
        worker.config['GPS_ENABLE'] = True
        worker.indiclient = MagicMock()
        worker.indiclient.gps_device = True

        # GPS disabled
        worker.config['GPS_ENABLE'] = False
        assert worker.getGpsPosition() is None
        worker.config['GPS_ENABLE'] = True

        # No GPS device
        worker.indiclient.gps_device = None
        assert worker.getGpsPosition() is None
        worker.indiclient.gps_device = True

        # Longitude > 180 (e.g. 200 -> -160)
        worker.position_av[constants.POSITION_LATITUDE] = -34.9285
        worker.position_av[constants.POSITION_LONGITUDE] = 0.0
        worker.position_av[constants.POSITION_ELEVATION] = 50.0

        worker.indiclient.getGpsPosition.return_value = (-34.9285, 200.0, 50.0)
        worker.getGpsPosition()
        assert worker.position_av[constants.POSITION_LONGITUDE] == -160.0

        # Elevation diff > 30
        worker.indiclient.getGpsPosition.return_value = (-34.9285, -160.0, 100.0)
        worker.getGpsPosition()
        assert worker.position_av[constants.POSITION_ELEVATION] == 100.0


def test_get_ccd_temperature_branches(capture_worker):
    worker = capture_worker
    worker.indiclient = MagicMock()
    worker.indiclient.getCcdTemperature.return_value = 15.0

    # With external script success
    worker.config['CCD_TEMP_SCRIPT'] = '/usr/local/bin/temp.sh'
    with patch.object(worker, 'getExternalTemperature', return_value=12.5):
        temp = worker.getCcdTemperature()
        assert temp == 12.5
        assert worker.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP] == 12.5

    # With external script exception
    with patch.object(worker, 'getExternalTemperature', side_effect=TemperatureException('fail')):
        temp = worker.getCcdTemperature()
        assert temp == 15.0
        assert worker.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP] == 15.0


def test_get_external_temperature_scenarios(capture_worker):
    worker = capture_worker

    # Normal success
    with patch('subprocess.Popen') as mock_popen, \
         patch('tempfile.NamedTemporaryFile') as mock_tempfile, \
         patch('io.open'), \
         patch('json.load', return_value={'temp': 22.5}), \
         patch.object(Path, 'is_file', return_value=True), \
         patch.object(Path, 'stat') as mock_stat, \
         patch('os.access', return_value=True):
        mock_stat.return_value.st_size = 100
        proc = MagicMock()
        proc.returncode = 0
        proc.wait.return_value = None
        mock_popen.return_value = proc
        tmp_mock = MagicMock()
        tmp_mock.name = '/tmp/fake_temp.json'
        mock_tempfile.return_value.__enter__.return_value = tmp_mock

        with patch.object(Path, 'unlink', return_value=None):
            val = worker.getExternalTemperature('/path/script.sh')
            assert val == 22.5

    # TimeoutExpired handling
    with patch('subprocess.Popen') as mock_popen, \
         patch('tempfile.NamedTemporaryFile') as mock_tempfile, \
         patch.object(Path, 'is_file', return_value=True), \
         patch.object(Path, 'stat') as mock_stat, \
         patch('os.access', return_value=True), \
         patch.object(Path, 'unlink', side_effect=PermissionError('denied')):
        mock_stat.return_value.st_size = 100
        proc = MagicMock()
        proc.wait.side_effect = subprocess.TimeoutExpired(cmd='foo', timeout=3.0)
        mock_popen.return_value = proc
        tmp_mock = MagicMock()
        tmp_mock.name = '/tmp/fake_temp.json'
        mock_tempfile.return_value.__enter__.return_value = tmp_mock

        with patch.object(worker, '_processRunning', side_effect=[True, True, True, True, True, True]), \
             patch('time.sleep'):
            with pytest.raises(TemperatureException, match='timed out'):
                worker.getExternalTemperature('/path/script.sh')
            proc.kill.assert_called_once()

    # Non-zero returncode
    with patch('subprocess.Popen') as mock_popen, \
         patch('tempfile.NamedTemporaryFile') as mock_tempfile, \
         patch.object(Path, 'is_file', return_value=True), \
         patch.object(Path, 'stat') as mock_stat, \
         patch('os.access', return_value=True), \
         patch.object(Path, 'unlink', side_effect=FileNotFoundError):
        mock_stat.return_value.st_size = 100
        proc = MagicMock()
        proc.returncode = 1
        proc.wait.return_value = None
        mock_popen.return_value = proc
        tmp_mock = MagicMock()
        tmp_mock.name = '/tmp/fake_temp.json'
        mock_tempfile.return_value.__enter__.return_value = tmp_mock

        with pytest.raises(TemperatureException, match='exited abnormally'):
            worker.getExternalTemperature('/path/script.sh')

    # JSONDecodeError
    with patch('subprocess.Popen') as mock_popen, \
         patch('tempfile.NamedTemporaryFile') as mock_tempfile, \
         patch.object(Path, 'is_file', return_value=True), \
         patch.object(Path, 'stat') as mock_stat, \
         patch('os.access', return_value=True), \
         patch('io.open'), \
         patch('json.load', side_effect=json.JSONDecodeError('msg', 'doc', 0)), \
         patch.object(Path, 'unlink'):
        mock_stat.return_value.st_size = 100
        proc = MagicMock()
        proc.returncode = 0
        mock_popen.return_value = proc
        tmp_mock = MagicMock()
        tmp_mock.name = '/tmp/fake_temp.json'
        mock_tempfile.return_value.__enter__.return_value = tmp_mock

        with pytest.raises(TemperatureException):
            worker.getExternalTemperature('/path/script.sh')

    # PermissionError on opening json
    with patch('subprocess.Popen') as mock_popen, \
         patch('tempfile.NamedTemporaryFile') as mock_tempfile, \
         patch.object(Path, 'is_file', return_value=True), \
         patch.object(Path, 'stat') as mock_stat, \
         patch('os.access', return_value=True), \
         patch('io.open', side_effect=PermissionError('denied')):
        mock_stat.return_value.st_size = 100
        proc = MagicMock()
        proc.returncode = 0
        mock_popen.return_value = proc
        tmp_mock = MagicMock()
        tmp_mock.name = '/tmp/fake_temp.json'
        mock_tempfile.return_value.__enter__.return_value = tmp_mock

        with pytest.raises(TemperatureException):
            worker.getExternalTemperature('/path/script.sh')


def test_capture_pre_hook_scenarios(capture_worker):
    worker = capture_worker
    worker.config['CAPTURE_HOOK_PRE'] = '/path/to/hook.sh'

    # Not a file
    with patch.object(Path, 'is_file', return_value=False):
        worker.capture_pre_hook()

    # Empty file
    with patch.object(Path, 'is_file', return_value=True), \
         patch.object(Path, 'stat') as mock_stat:
        mock_stat.return_value.st_size = 0
        worker.capture_pre_hook()

    # Not executable
    with patch.object(Path, 'is_file', return_value=True), \
         patch.object(Path, 'stat') as mock_stat, \
         patch('os.access', return_value=False):
        mock_stat.return_value.st_size = 10
        worker.capture_pre_hook()

    # OSError on Popen
    with patch.object(Path, 'is_file', return_value=True), \
         patch.object(Path, 'stat') as mock_stat, \
         patch('os.access', return_value=True), \
         patch('subprocess.Popen', side_effect=OSError('exec error')):
        mock_stat.return_value.st_size = 10
        worker.capture_pre_hook()

    # TimeoutExpired
    with patch.object(Path, 'is_file', return_value=True), \
         patch.object(Path, 'stat') as mock_stat, \
         patch('os.access', return_value=True), \
         patch('subprocess.Popen') as mock_popen, \
         patch.object(worker, '_processRunning', side_effect=[True, True, False, False, False, False, False]), \
         patch('time.sleep'):
        mock_stat.return_value.st_size = 10
        proc = MagicMock()
        proc.wait.side_effect = subprocess.TimeoutExpired(cmd='hook', timeout=5)
        mock_popen.return_value = proc
        worker.capture_pre_hook()
        proc.terminate.assert_called()


def test_initialize_bounds_and_defaults(capture_worker, app):
    worker = capture_worker
    with app.app_context():
        mock_client = make_mock_indiclient()
        worker.config['CAMERA_INTERFACE'] = 'indi'
        worker.reparkTelescope = MagicMock()

        # SQM exposure < min, gains < min, binning < min
        worker.config['CAMERA_SQM'] = {'EXPOSURE': 0.000001, 'GAIN': -10.0, 'BINNING': 0}
        worker.config['CCD_CONFIG'] = {
            'NIGHT': {'EXPOSURE': 60.0, 'GAIN': -5.0, 'BINNING': 0},
            'MOONMODE': {'EXPOSURE': 10.0, 'GAIN': -5.0, 'BINNING': 0},
            'DAY': {'EXPOSURE': 0.001, 'GAIN': -5.0, 'BINNING': 0},
            'EXPOSURE_CLASSNAME': 'exposure_basic',
        }
        worker.config['CCD_EXPOSURE_MIN'] = 0.5
        worker.config['CCD_EXPOSURE_MIN_DAY'] = 0.5
        worker.config['CCD_EXPOSURE_MAX'] = 100.0

        with patch('indi_allsky.camera.indi', return_value=mock_client), \
             patch('time.sleep'):
            worker._initialize()

        # SQM exposure > max, gains > max, binning > max
        worker.config['CAMERA_SQM'] = {'EXPOSURE': 120.0, 'GAIN': 1000.0, 'BINNING': 10}
        worker.config['CCD_CONFIG'] = {
            'NIGHT': {'EXPOSURE': 60.0, 'GAIN': 1000.0, 'BINNING': 10},
            'MOONMODE': {'EXPOSURE': 10.0, 'GAIN': 1000.0, 'BINNING': 10},
            'DAY': {'EXPOSURE': 0.001, 'GAIN': 1000.0, 'BINNING': 10},
            'EXPOSURE_CLASSNAME': 'exposure_basic',
        }
        with patch('indi_allsky.camera.indi', return_value=mock_client), \
             patch('time.sleep'):
            worker._initialize()

        # CCD_EXPOSURE_DEF with moonmode and day
        worker.config['CCD_EXPOSURE_DEF'] = 2.5
        worker.night_av[constants.NIGHT_NIGHT] = 1
        worker.night_av[constants.NIGHT_MOONMODE] = 1
        with patch('indi_allsky.camera.indi', return_value=mock_client), \
             patch('time.sleep'):
            worker._initialize()

        worker.night_av[constants.NIGHT_NIGHT] = 0
        worker.night_av[constants.NIGHT_MOONMODE] = 0
        with patch('indi_allsky.camera.indi', return_value=mock_client), \
             patch('time.sleep'):
            worker._initialize()


def test_reconfigure_ccd_cooling_and_libcamera(capture_worker):
    worker = capture_worker
    worker.indiclient = make_mock_indiclient()
    worker.reconfigure_camera = True

    # Night with cooling
    worker.night = True
    worker.moonmode = True
    worker.config['CCD_COOLING'] = True
    worker.config['CCD_TEMP'] = -10.0
    worker.config['CAMERA_INTERFACE'] = 'libcamera_dummy'
    worker.config['LIBCAMERA'] = {'IMAGE_FILE_TYPE': 'dng'}

    worker.reconfigureCcd()
    worker.indiclient.enableCcdCooler.assert_called_once()
    assert worker.indiclient.libcamera_bit_depth == 16

    # Reconfigure again with jpg
    worker.reconfigure_camera = True
    worker.moonmode = False
    worker.config['CCD_COOLING'] = False
    worker.config['LIBCAMERA'] = {'IMAGE_FILE_TYPE': 'jpg'}

    worker.reconfigureCcd()
    worker.indiclient.disableCcdCooler.assert_called_once()
    assert worker.indiclient.libcamera_bit_depth == 8

    # Day mode
    worker.reconfigure_camera = True
    worker.night = False
    worker.reconfigureCcd()


def test_initialize_branches(capture_worker, app):
    worker = capture_worker
    with app.app_context():
        worker.config['CAMERA_INTERFACE'] = 'indi'
        worker.config['GPS_ENABLE'] = True
        worker.config['CFA_PATTERN'] = 'GRBG'
        worker.config['S3UPLOAD'] = {
            'URL_TEMPLATE': 'https://{invalid_key}.s3.amazonaws.com/{bucket}/',
        }
        mock_client = make_mock_indiclient()
        mock_client.refreshGps = MagicMock()
        worker.reparkTelescope = MagicMock()

        with patch('indi_allsky.camera.indi', return_value=mock_client):
            worker._initialize()

        mock_client.refreshGps.assert_called_once()


def test_saferun_day_night_and_forced_transitions(capture_worker, app):
    worker = capture_worker
    with app.app_context():
        worker._initialize = MagicMock()
        worker._pre_run_tasks = MagicMock()
        worker.indiclient = make_mock_indiclient()
        worker.shoot = MagicMock()
        worker.reconfigureCcd = MagicMock()
        worker._expireData = MagicMock()
        worker._generateNightKeogram = MagicMock()
        worker._generateNightTimelapse = MagicMock()
        worker._generateDayKeogram = MagicMock()
        worker._generateDayTimelapse = MagicMock()
        worker._uploadAllskyEndOfNight = MagicMock()

        cam = IndiAllSkyDbCameraTable.query.first()
        worker.camera_id = cam.id

        # Transition 1: Night -> Day (starts night, detectNight sets day in loop)
        worker.night = True
        worker.moonmode = False
        worker.generate_timelapse_flag = True

        call_count = 0
        def toggle_to_day():
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                worker.night = False

        worker.detectNight = MagicMock(side_effect=toggle_to_day)

        iteration = 0
        def sleep_stop_1(s):
            nonlocal iteration
            iteration += 1
            if iteration >= 1:
                worker._shutdown = True

        with patch('time.sleep', side_effect=sleep_stop_1):
            worker.saferun()

        assert worker._generateNightTimelapse.called
        assert worker._uploadAllskyEndOfNight.called

        # Transition 2: Day -> Night (starts day, detectNight sets night in loop)
        worker._shutdown = False
        worker.night = False
        worker.moonmode = False
        worker.generate_timelapse_flag = True

        call_count = 0
        def toggle_to_night():
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                worker.night = True

        worker.detectNight = MagicMock(side_effect=toggle_to_night)

        iteration = 0
        with patch('time.sleep', side_effect=sleep_stop_1):
            worker.saferun()

        assert worker._generateDayTimelapse.called

        # Transition 3: Forced transition (loop_start_time > next_forced_transition_time)
        worker._shutdown = False
        worker.night = True
        worker.moonmode = False
        worker.detectNight = MagicMock()
        worker.next_forced_transition_time = 0  # in the past
        worker.generate_timelapse_flag = True

        iteration = 0
        with patch('time.sleep', side_effect=sleep_stop_1):
            worker.saferun()

        # Transition 4: Forced transition during day
        worker._shutdown = False
        worker.night = False
        worker.moonmode = False
        worker.detectNight = MagicMock()
        worker.next_forced_transition_time = 0
        worker.generate_timelapse_flag = True

        iteration = 0
        with patch('time.sleep', side_effect=sleep_stop_1):
            worker.saferun()


def test_saferun_more_branches(capture_worker, app):
    worker = capture_worker
    with app.app_context():
        worker._initialize = MagicMock()
        worker._pre_run_tasks = MagicMock()
        worker.detectNight = MagicMock()
        worker.indiclient = make_mock_indiclient()
        worker.shoot = MagicMock()
        worker.reconfigureCcd = MagicMock()

        # Moonmode change
        worker.night = True
        worker.moonmode = False
        worker.night_av[constants.NIGHT_NIGHT] = 1
        worker.night_av[constants.NIGHT_MOONMODE] = 1

        # Camera interface pycurl & exposure abort
        worker.config['CAMERA_INTERFACE'] = 'pycurl'
        worker.exposure_timeout = 0.001

        # Queue depth below min with add_period_delay
        worker.add_period_delay = 5.0
        worker.focus_mode = True

        # Day SQM exposure
        worker.sqm_camera_enable = True
        worker.sqm_camera_enable_day = True
        worker.astro_av[constants.ASTRO_SUN_ALT] = 10.0
        worker.sqm_tasks_time = 0

        # Time offset with DBusException
        worker.update_time_offset = 30
        worker.setTimeSystemd = MagicMock(side_effect=dbus.exceptions.DBusException('mock dbus error'))

        iteration = 0
        def sleep_stop(s):
            nonlocal iteration
            iteration += 1
            if iteration == 1:
                worker._expUtils.EXPOSURE_CURRENT = 10.0
            elif iteration >= 3:
                worker._shutdown = True

        with patch('time.sleep', side_effect=sleep_stop):
            worker.saferun()

        assert worker.reconfigure_camera is True


def test_saferun_daytime_normal_exposure_sqm_branch(capture_worker, app):
    worker = capture_worker
    with app.app_context():
        worker._initialize = MagicMock()
        worker._pre_run_tasks = MagicMock()
        worker.detectNight = MagicMock()
        worker.indiclient = make_mock_indiclient()
        worker.shoot = MagicMock()
        worker.reconfigureCcd = MagicMock()

        worker.night = False
        worker.moonmode = False
        worker.night_av[constants.NIGHT_NIGHT] = 0
        worker.config['CAMERA_INTERFACE'] = 'indi_passive'
        worker.sqm_camera_enable = True
        worker.sqm_camera_enable_day = False
        worker.astro_av[constants.ASTRO_SUN_ALT] = 10.0
        worker.sqm_tasks_time = 0

        iteration = 0
        def sleep_stop(s):
            nonlocal iteration
            iteration += 1
            if iteration >= 1:
                worker._shutdown = True

        with patch('time.sleep', side_effect=sleep_stop):
            worker.saferun()


def test_saferun_forced_transition_night(capture_worker, app):
    worker = capture_worker
    with app.app_context():
        worker._initialize = MagicMock()
        worker._pre_run_tasks = MagicMock()
        worker.detectNight = MagicMock()
        worker.indiclient = make_mock_indiclient()
        worker.shoot = MagicMock()
        worker.reconfigureCcd = MagicMock()
        worker._expireData = MagicMock()
        worker._generateNightKeogram = MagicMock()
        worker._generateNightTimelapse = MagicMock()
        worker._uploadAllskyEndOfNight = MagicMock()

        worker.night = True
        worker.night_av[constants.NIGHT_NIGHT] = 1
        worker.moonmode = False
        worker.night_av[constants.NIGHT_MOONMODE] = 0
        worker.generate_timelapse_flag = True

        mock_prev = MagicMock()
        mock_prev.timestamp.return_value = time.time() - 100
        mock_next = MagicMock()
        mock_next.timestamp.return_value = time.time() + 3600
        worker._dateCalcs.getNextDayNightTransition = MagicMock(side_effect=[mock_prev, mock_next])
        worker._dateCalcs.getDayDate = MagicMock(return_value=datetime(2025, 1, 2, 12, 0, 0))

        iteration = 0
        def sleep_stop(s):
            nonlocal iteration
            iteration += 1
            if iteration >= 1:
                worker._shutdown = True

        with patch('time.sleep', side_effect=sleep_stop):
            worker.saferun()

        assert worker.reconfigure_camera is True
        assert worker.generate_timelapse_flag is False
        assert worker._expireData.call_count == 1
        worker._generateNightKeogram.assert_called_once_with('20250101', worker.camera_id)
        worker._generateNightTimelapse.assert_called_once_with('20250101', worker.camera_id)
        worker._uploadAllskyEndOfNight.assert_called_once_with(worker.camera_id)


def test_saferun_forced_transition_day(capture_worker, app):
    worker = capture_worker
    with app.app_context():
        worker._initialize = MagicMock()
        worker._pre_run_tasks = MagicMock()
        worker.detectNight = MagicMock()
        worker.indiclient = make_mock_indiclient()
        worker.shoot = MagicMock()
        worker.reconfigureCcd = MagicMock()
        worker._expireData = MagicMock()
        worker._generateDayKeogram = MagicMock()
        worker._generateDayTimelapse = MagicMock()

        worker.night = False
        worker.night_av[constants.NIGHT_NIGHT] = 0
        worker.moonmode = False
        worker.night_av[constants.NIGHT_MOONMODE] = 0
        worker.generate_timelapse_flag = True

        mock_prev = MagicMock()
        mock_prev.timestamp.return_value = time.time() - 100
        mock_next = MagicMock()
        mock_next.timestamp.return_value = time.time() + 3600
        worker._dateCalcs.getNextDayNightTransition = MagicMock(side_effect=[mock_prev, mock_next])
        worker._dateCalcs.getDayDate = MagicMock(return_value=datetime(2025, 1, 2, 12, 0, 0))

        iteration = 0
        def sleep_stop(s):
            nonlocal iteration
            iteration += 1
            if iteration >= 1:
                worker._shutdown = True

        with patch('time.sleep', side_effect=sleep_stop):
            worker.saferun()

        assert worker.reconfigure_camera is True
        assert worker.generate_timelapse_flag is False
        assert worker._expireData.call_count == 2
        worker._generateDayKeogram.assert_called_once_with('20250101', worker.camera_id)
        worker._generateDayTimelapse.assert_called_once_with('20250101', worker.camera_id)


def test_saferun_capture_q_variants(capture_worker, app):
    worker = capture_worker
    with app.app_context():
        worker._initialize = MagicMock()
        worker._pre_run_tasks = MagicMock()
        worker.detectNight = MagicMock()
        worker.indiclient = make_mock_indiclient()
        worker.shoot = MagicMock()
        worker.reconfigureCcd = MagicMock()
        worker.setTimeSystemd = MagicMock()

        worker.night = True
        worker.night_av[constants.NIGHT_NIGHT] = 1
        worker.moonmode = False
        worker.night_av[constants.NIGHT_MOONMODE] = 0

        # Put settime into capture_q
        worker.capture_q.put({'settime': 1234})
        # Put unknown action
        worker.capture_q.put({'something_random': True})
        # Put stop action
        worker.capture_q.put({'stop': True})

        with patch('time.sleep'):
            worker.saferun()

        assert worker._shutdown is True
        assert worker.setTimeSystemd.called


def test_saferun_queue_depth_and_delays(capture_worker, app):
    worker = capture_worker
    with app.app_context():
        worker._initialize = MagicMock()
        worker._pre_run_tasks = MagicMock()
        worker.detectNight = MagicMock()
        worker.indiclient = make_mock_indiclient()
        worker.reconfigureCcd = MagicMock()

        worker.night = True
        worker.night_av[constants.NIGHT_NIGHT] = 1
        worker.moonmode = False
        worker.night_av[constants.NIGHT_MOONMODE] = 0
        worker.focus_mode = False
        worker.config['CAMERA_INTERFACE'] = 'indi_passive'
        worker.config['EXPOSURE_PERIOD'] = 10
        worker.config['EXPOSURE_PERIOD_DAY'] = 5
        worker.image_queue_max = 5
        worker.image_queue_backoff = 2.0

        def shoot_stop(*a, **kw):
            worker._shutdown = True

        worker.shoot = MagicMock(side_effect=shoot_stop)

        with patch.object(worker.image_q, 'qsize', return_value=10):
            with patch('time.sleep'):
                worker.saferun()

            assert worker.add_period_delay > 0


def test_get_system_temperature_exceptions(capture_worker, tmp_path):
    worker = capture_worker
    fake_script = str(tmp_path / 'fake_temp.sh')
    Path(fake_script).write_text('#!/bin/sh\nexit 0\n')
    os.chmod(fake_script, 0o755)

    # 1. Process timeout expired and not running
    mock_proc = MagicMock()
    mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd='fake', timeout=3.0)
    with patch('subprocess.Popen', return_value=mock_proc), \
         patch.object(worker, '_processRunning', return_value=False):
        with pytest.raises(TemperatureException, match='Temperature script timed out'):
            worker.getExternalTemperature(fake_script)

    # 2. Process returncode != 0
    mock_proc = MagicMock()
    mock_proc.wait.return_value = None
    mock_proc.returncode = 1
    with patch('subprocess.Popen', return_value=mock_proc):
        with pytest.raises(TemperatureException, match='Temperature script returned exited abnormally'):
            worker.getExternalTemperature(fake_script)

    # 3. JSON decode error
    def write_invalid_json(*args, **kwargs):
        temp_file = kwargs['env']['TEMP_JSON']
        Path(temp_file).write_text('bad json', encoding='utf-8')
        mock_p = MagicMock()
        mock_p.returncode = 0
        mock_p.wait.return_value = None
        return mock_p

    with patch('subprocess.Popen', side_effect=write_invalid_json):
        with pytest.raises(TemperatureException):
            worker.getExternalTemperature(fake_script)

    # 4. Non-numerical value
    def write_nan_json(*args, **kwargs):
        temp_file = kwargs['env']['TEMP_JSON']
        Path(temp_file).write_text('{"temp": "not-a-number"}', encoding='utf-8')
        mock_p = MagicMock()
        mock_p.returncode = 0
        mock_p.wait.return_value = None
        return mock_p

    with patch('subprocess.Popen', side_effect=write_nan_json):
        with pytest.raises(TemperatureException, match='non-numerical'):
            worker.getExternalTemperature(fake_script)

    # 5. FileNotFoundError during open (TEMP_JSON deleted/missing)
    mock_proc = MagicMock()
    mock_proc.wait.return_value = None
    mock_proc.returncode = 0
    with patch('subprocess.Popen', return_value=mock_proc):
        with pytest.raises(TemperatureException):
            worker.getExternalTemperature(fake_script)

