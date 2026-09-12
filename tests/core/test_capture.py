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
from unittest.mock import MagicMock, call, patch
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
from sqlalchemy.orm.exc import MultipleResultsFound


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
def capture_worker_setup(app, base_config):
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        if not cam:
            cam = IndiAllSkyDbCameraTable(
                name='Test Capture Camera',
                uuid='cam-cap-test-1',
                latitude=-34.9285,
                longitude=138.6007,
                elevation=50,
                nightSunAlt=-6.0,
                lensFocalLength=2.5,
                lensFocalRatio=1.4,
                lensImageCircle=1000,
                width=1920,
                height=1080,
                pixelSize=2.9,
                cfa=constants.CFA_RGGB,
                owner='Admin',
            )
            db.session.add(cam)
            db.session.commit()

        config = dict(base_config)
        config['LOCATION_LATITUDE'] = -34.9285
        config['LOCATION_LONGITUDE'] = 138.6007
        config['LOCATION_ELEVATION'] = 50
        config['IMAGE_FOLDER'] = '/tmp/images'
        config['S3UPLOAD'] = {
            'HOST': 's3.example.com',
            'BUCKET': 'mybucket',
            'REGION': 'us-east-1',
            'NAMESPACE': 'allsky',
            'URL_TEMPLATE': 'https://{bucket}.{host}/{namespace}',
        }

        error_q = Queue()
        capture_q = Queue()
        image_q = Queue()
        video_q = Queue()
        upload_q = Queue()

        position_av = Array('d', [0.0] * 5)
        exposure_av = Array(ctypes.c_int32, [1000000, 1000000, 0, 1000, 100, 30000000, 5000000])
        gain_av = Array(ctypes.c_int32, [100000, 100000, 0, 0, 100000, 100000, 400000, 50000, 200000, 100000])
        binning_av = Array('i', [1, 1, 1, 2, 1, 1])
        sensors_temp_av = Array('f', [0.0] * 110)
        sensors_user_av = Array('f', [0.0] * 110)
        night_av = Array('i', [1, 0])
        astro_av = Array('f', [0.0] * 10)

        worker = CaptureWorker(
            idx=0,
            config=config,
            error_q=error_q,
            capture_q=capture_q,
            image_q=image_q,
            video_q=video_q,
            upload_q=upload_q,
            position_av=position_av,
            exposure_av=exposure_av,
            gain_av=gain_av,
            binning_av=binning_av,
            sensors_temp_av=sensors_temp_av,
            sensors_user_av=sensors_user_av,
            night_av=night_av,
            astro_av=astro_av,
        )

        return worker


def test_capture_worker_init(capture_worker_setup):
    worker = capture_worker_setup
    assert worker.name == 'Capture-0'
    assert worker._shutdown is False
    assert worker.periodic_tasks_offset == 300.0


def test_capture_worker_signals(capture_worker_setup):
    worker = capture_worker_setup

    worker.sighup_handler_worker(signal.SIGHUP, None)
    assert worker._shutdown is True

    worker._shutdown = False
    worker.sigterm_handler_worker(signal.SIGTERM, None)
    assert worker._shutdown is True

    worker._shutdown = False
    worker.sigint_handler_worker(signal.SIGINT, None)
    assert worker._shutdown is True

    with pytest.raises(TimeOutException):
        worker.sigalarm_handler_worker(signal.SIGALRM, None)


def test_capture_worker_run(capture_worker_setup):
    worker = capture_worker_setup

    # Test run success
    with patch.object(worker, 'saferun') as mock_safe:
        worker.run()
        mock_safe.assert_called_once()

    # Test run exception handling
    with patch.object(worker, 'saferun', side_effect=RuntimeError("Worker error")):
        with pytest.raises(RuntimeError):
            worker.run()
        err_msg, tb = worker.error_q.get()
        assert "Worker error" in err_msg


def test_capture_worker_no_image_folder(capture_worker_setup):
    worker = capture_worker_setup
    worker.config['IMAGE_FOLDER'] = None

    w2 = CaptureWorker(
        idx=1,
        config=worker.config,
        error_q=worker.error_q,
        capture_q=worker.capture_q,
        image_q=worker.image_q,
        video_q=worker.video_q,
        upload_q=worker.upload_q,
        position_av=worker.position_av,
        exposure_av=worker.exposure_av,
        gain_av=worker.gain_av,
        binning_av=worker.binning_av,
        sensors_temp_av=worker.sensors_temp_av,
        sensors_user_av=worker.sensors_user_av,
        night_av=worker.night_av,
        astro_av=worker.astro_av,
    )
    assert 'html' in str(w2.image_dir)


def test_capture_worker_initialize_server_failure(capture_worker_setup, app):
    worker = capture_worker_setup
    with app.app_context():
        mock_client = make_mock_indiclient()
        mock_client.connectServer.return_value = False
        worker.config['CAMERA_INTERFACE'] = 'indi'

        with patch('indi_allsky.camera.indi', return_value=mock_client):
            with pytest.raises(IndiServerException):
                worker._initialize()


def test_capture_worker_initialize_find_ccd_failure(capture_worker_setup, app):
    worker = capture_worker_setup
    with app.app_context():
        mock_client = make_mock_indiclient()
        mock_client.findCcd.side_effect = CameraException("CCD not found")
        worker.config['CAMERA_INTERFACE'] = 'indi'

        with patch('indi_allsky.camera.indi', return_value=mock_client):
            with patch('time.sleep'):
                with pytest.raises(CameraException):
                    worker._initialize()


def test_capture_worker_initialize_full(capture_worker_setup, app):
    worker = capture_worker_setup
    with app.app_context():
        mock_client = make_mock_indiclient()

        # Test GPS device timeout exception path
        mock_client.configureGpsDevice.side_effect = TimeOutException("GPS timeout")
        # Test optional camera calls raising TimeOutException
        mock_client.disableDebugCcd.side_effect = TimeOutException("Debug timeout")
        mock_client.setCcdFrameType.side_effect = TimeOutException("Frame timeout")
        mock_client.setCcdScopeInfo.side_effect = TimeOutException("Scope timeout")

        worker.config['CAMERA_INTERFACE'] = 'indi'
        worker.config['GPS_ENABLE'] = True
        worker.config['SYNCAPI'] = {'ENABLE': True}
        worker.config['S3UPLOAD']['URL_TEMPLATE'] = 'https://{bucket}.{invalid_key}'

        with patch('indi_allsky.camera.indi', return_value=mock_client):
            with patch('time.sleep'):
                worker._initialize()

        assert worker.camera_id is not None
        assert worker.indiclient == mock_client
        assert worker.upload_q.qsize() == 1  # Sync task queued


def test_capture_worker_initialize_multiple_cameras_found(capture_worker_setup, app):
    worker = capture_worker_setup
    with app.app_context():
        mock_client = make_mock_indiclient()
        worker.config['CAMERA_INTERFACE'] = 'indi'

        with patch('indi_allsky.camera.indi', return_value=mock_client):
            with patch('time.sleep'):
                with patch.object(worker._miscDb, 'addCamera', side_effect=MultipleResultsFound):
                    with pytest.raises(MultipleResultsFound):
                        worker._initialize()


def test_capture_worker_initialize_clamping_and_defaults(capture_worker_setup, app):
    worker = capture_worker_setup
    with app.app_context():
        mock_client = make_mock_indiclient()

        # Clamping exposures
        worker.config['CCD_EXPOSURE_MIN_DAY'] = 0.00001  # lower than 0.0001
        worker.config['CCD_EXPOSURE_MIN'] = 0.00001  # lower than 0.0001
        worker.config['CCD_EXPOSURE_MAX'] = 100.0  # higher than 60.0
        worker.config['CAMERA_SQM'] = {'EXPOSURE': 100.0, 'GAIN': 600.0, 'BINNING': 10}

        # Clamping gains
        worker.config['CCD_CONFIG']['NIGHT']['GAIN'] = 600.0  # > max 500
        worker.config['CCD_CONFIG']['MOONMODE']['GAIN'] = -10.0  # < min 0
        worker.config['CCD_CONFIG']['DAY']['GAIN'] = 600.0  # > max 500

        # Clamping binning
        worker.config['CCD_CONFIG']['NIGHT']['BINNING'] = 10  # > max 4
        worker.config['CCD_CONFIG']['MOONMODE']['BINNING'] = 0  # < min 1
        worker.config['CCD_CONFIG']['DAY']['BINNING'] = 10  # > max 4

        # Test CCD_EXPOSURE_DEF
        worker.config['CAMERA_INTERFACE'] = 'indi'
        worker.config['CCD_EXPOSURE_DEF'] = 5.0

        with patch('indi_allsky.camera.indi', return_value=mock_client):
            with patch('time.sleep'):
                worker._initialize()

        assert worker._expUtils.EXPOSURE_MAX == 60.0
        assert worker._expUtils.GAIN_MAX_NIGHT == 500.0
        assert worker._expUtils.GAIN_MAX_MOONMODE == 0.0

        # Now test fallback when CCD_EXPOSURE_DEF = 0 and previous image exists in DB
        worker.config['CCD_EXPOSURE_DEF'] = 0.0
        worker._expUtils.EXPOSURE_CURRENT = -1.0
        prev_img = IndiAllSkyDbImageTable(
            filename='test.jpg',
            camera_id=worker.camera_id,
            createDate=datetime.now(),
            dayDate=datetime.now().date(),
            exposure=2.5,
            gain=100.0,
            binmode=2,
            night=True,
            adu=1000.0,
            data={'sensor_user_8': 21.5, 'sensor_user_9': 150.0},
            temp=12.0,
        )
        db.session.add(prev_img)
        db.session.commit()

        with patch('indi_allsky.camera.indi', return_value=mock_client):
            with patch('time.sleep'):
                worker._initialize()

        assert worker._expUtils.EXPOSURE_CURRENT == 2.5
        assert worker.sensors_user_av[constants.SENSOR_USER_CAMERA_SQM_MAG] == 21.5

        # Test fallback when CCD_EXPOSURE_DEF = 0 and no previous image
        IndiAllSkyDbImageTable.query.delete()
        db.session.commit()
        worker.config['CCD_CONFIG']['EXPOSURE_CLASSNAME'] = 'auto_gain'
        with patch('indi_allsky.camera.indi', return_value=mock_client):
            with patch('time.sleep'):
                worker._initialize()


def test_capture_worker_pre_run_tasks(capture_worker_setup, app):
    worker = capture_worker_setup
    with app.app_context():
        worker.camera_server = 'indi_rpicam'
        worker.indiclient = make_mock_indiclient()

        worker._pre_run_tasks()
        assert int(worker._miscDb.getState('STATUS')) == constants.STATUS_RUNNING
        worker.indiclient.setCcdExposure.assert_called_once()


def test_capture_worker_periodic_tasks(capture_worker_setup, app):
    worker = capture_worker_setup
    with app.app_context():
        worker.indiclient = make_mock_indiclient()

        # Case 1: indi_asi_ccd
        worker.camera_server = 'indi_asi_ccd'
        worker.camera_name = 'ZWO CCD ASI120MC'
        worker._periodic_tasks()
        assert worker.indiclient.configureCcdDevice.called

        # Case 2: indi_asi_single_ccd
        worker.indiclient.configureCcdDevice.reset_mock()
        worker.camera_server = 'indi_asi_single_ccd'
        worker.camera_name = 'ZWO ASI120MM'
        worker._periodic_tasks()
        assert worker.indiclient.configureCcdDevice.called


def test_capture_worker_external_temperature(capture_worker_setup, tmp_path):
    worker = capture_worker_setup

    script = tmp_path / 'temp.sh'

    # 1. Not a file
    with pytest.raises(TemperatureException, match="not a file"):
        worker.getExternalTemperature(str(tmp_path / 'nonexistent.sh'))

    # 2. Empty file
    script.touch()
    with pytest.raises(TemperatureException, match="empty"):
        worker.getExternalTemperature(str(script))

    # 3. Not executable
    script.write_text("#!/bin/sh\n")
    script.chmod(0o444)
    with pytest.raises(TemperatureException, match="not readable or executable"):
        worker.getExternalTemperature(str(script))

    script.chmod(0o755)

    # 4. Popen OSError
    with patch('subprocess.Popen', side_effect=OSError("Exec error")):
        with pytest.raises(TemperatureException, match="failed to execute"):
            worker.getExternalTemperature(str(script))

    # 5. TimeoutExpired
    mock_proc = MagicMock()
    mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="temp.sh", timeout=3.0)
    mock_proc.poll.return_value = None
    with patch('subprocess.Popen', return_value=mock_proc):
        with patch.object(worker, '_processRunning', side_effect=[True] * 10):
            with patch('time.sleep'):
                with pytest.raises(TemperatureException, match="timed out"):
                    worker.getExternalTemperature(str(script))

    # 6. Returncode != 0
    mock_proc = MagicMock()
    mock_proc.wait.return_value = None
    mock_proc.returncode = 1
    with patch('subprocess.Popen', return_value=mock_proc):
        with pytest.raises(TemperatureException, match="abnormally"):
            worker.getExternalTemperature(str(script))

    # 7. Success with JSON output
    def fake_popen(cmd, env, **kwargs):
        json_file = env['TEMP_JSON']
        with open(json_file, 'w') as f:
            json.dump({'temp': 24.5}, f)
        p = MagicMock()
        p.wait.return_value = None
        p.returncode = 0
        return p

    with patch('subprocess.Popen', side_effect=fake_popen):
        val = worker.getExternalTemperature(str(script))
        assert val == 24.5

    # 8. Malformed JSON
    def fake_popen_bad_json(cmd, env, **kwargs):
        json_file = env['TEMP_JSON']
        with open(json_file, 'w') as f:
            f.write("bad json")
        p = MagicMock()
        p.wait.return_value = None
        p.returncode = 0
        return p

    with patch('subprocess.Popen', side_effect=fake_popen_bad_json):
        with pytest.raises(TemperatureException):
            worker.getExternalTemperature(str(script))

    # 9. Non-numerical temp value
    def fake_popen_non_num(cmd, env, **kwargs):
        json_file = env['TEMP_JSON']
        with open(json_file, 'w') as f:
            json.dump({'temp': 'warm'}, f)
        p = MagicMock()
        p.wait.return_value = None
        p.returncode = 0
        return p

    with patch('subprocess.Popen', side_effect=fake_popen_non_num):
        with pytest.raises(TemperatureException, match="non-numerical"):
            worker.getExternalTemperature(str(script))

    # 10. Missing 'temp' key
    def fake_popen_no_key(cmd, env, **kwargs):
        json_file = env['TEMP_JSON']
        with open(json_file, 'w') as f:
            json.dump({'wrong_key': 12}, f)
        p = MagicMock()
        p.wait.return_value = None
        p.returncode = 0
        return p

    with patch('subprocess.Popen', side_effect=fake_popen_no_key):
        with pytest.raises(TemperatureException, match="incorrect data"):
            worker.getExternalTemperature(str(script))


def test_capture_worker_ccd_temperature_display_units(capture_worker_setup):
    worker = capture_worker_setup
    worker.indiclient = make_mock_indiclient()
    worker.indiclient.getCcdTemperature.return_value = 25.0

    # Celsius
    worker.config['TEMP_DISPLAY'] = 'c'
    t = worker.getCcdTemperature()
    assert t == 25.0
    assert worker.sensors_user_av[constants.SENSOR_USER_CCD_TEMP] == 25.0

    # Fahrenheit
    worker.config['TEMP_DISPLAY'] = 'f'
    t = worker.getCcdTemperature()
    assert worker.sensors_user_av[constants.SENSOR_USER_CCD_TEMP] == 77.0

    # Kelvin
    worker.config['TEMP_DISPLAY'] = 'k'
    t = worker.getCcdTemperature()
    assert abs(worker.sensors_user_av[constants.SENSOR_USER_CCD_TEMP] - 298.15) < 0.01

    # External temperature exception fallback
    worker.config['CCD_TEMP_SCRIPT'] = '/tmp/fake_script.sh'
    with patch.object(worker, 'getExternalTemperature', side_effect=TemperatureException("fail")):
        t_fallback = worker.getCcdTemperature()
        assert t_fallback == 25.0


def test_capture_worker_capture_pre_hook(capture_worker_setup, tmp_path):
    worker = capture_worker_setup

    # Not configured -> early return
    worker.config['CAPTURE_HOOK_PRE'] = None
    worker.capture_pre_hook()

    # Configured but invalid file
    hook_file = tmp_path / 'prehook.sh'
    worker.config['CAPTURE_HOOK_PRE'] = str(hook_file)
    worker.capture_pre_hook()

    # Empty file
    hook_file.touch()
    worker.capture_pre_hook()

    # Not executable
    hook_file.write_text("#!/bin/sh\n")
    hook_file.chmod(0o444)
    worker.capture_pre_hook()

    hook_file.chmod(0o755)

    # Popen OSError
    with patch('subprocess.Popen', side_effect=OSError("Exec error")):
        worker.capture_pre_hook()

    # TimeoutExpired
    mock_proc = MagicMock()
    mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="prehook.sh", timeout=5)
    mock_proc.poll.return_value = None
    with patch('subprocess.Popen', return_value=mock_proc):
        with patch.object(worker, '_processRunning', side_effect=[True] * 10):
            with patch('time.sleep'):
                worker.capture_pre_hook()
                mock_proc.terminate.assert_called()

    # Non-zero return code
    mock_proc = MagicMock()
    mock_proc.wait.return_value = None
    mock_proc.returncode = 1
    mock_proc.communicate.return_value = (b"Hook output line 1\nLine 2", b"")
    with patch('subprocess.Popen', return_value=mock_proc):
        worker.capture_pre_hook()

    # Success
    mock_proc.returncode = 0
    with patch('subprocess.Popen', return_value=mock_proc):
        worker.capture_pre_hook()


def test_capture_worker_process_running(capture_worker_setup):
    worker = capture_worker_setup
    assert worker._processRunning(None) is False

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    assert worker._processRunning(mock_proc) is True

    mock_proc.poll.return_value = 0
    assert worker._processRunning(mock_proc) is False


def test_capture_worker_gps_position_variations(capture_worker_setup, app):
    worker = capture_worker_setup
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        worker.camera_id = cam.id

        # GPS disabled
        worker.config['GPS_ENABLE'] = False
        assert worker.getGpsPosition() is None

        # GPS device None
        worker.config['GPS_ENABLE'] = True
        worker.indiclient = make_mock_indiclient()
        worker.indiclient.gps_device = None
        assert worker.getGpsPosition() is None

        # GPS longitude > 180 (needs 360 normalization) and difference > 0.1 deg
        worker.indiclient.gps_device = MagicMock()
        worker.indiclient.getGpsPosition.return_value = (-35.5, 200.0, 100.0)  # 200 -> -160

        lat, lon, elev = worker.getGpsPosition()
        assert lon == -160.0
        assert worker.position_av[constants.POSITION_LATITUDE] == -35.5
        assert worker.position_av[constants.POSITION_LONGITUDE] == -160.0
        assert worker.position_av[constants.POSITION_ELEVATION] == 100.0

        # GPS small difference (no update)
        with patch.object(worker, 'updateConfigLocation') as mock_update:
            worker.indiclient.getGpsPosition.return_value = (-35.52, -160.02, 105.0)
            worker.getGpsPosition()
            mock_update.assert_not_called()


def test_capture_worker_telescope_and_repark_none(capture_worker_setup):
    worker = capture_worker_setup
    worker.indiclient = make_mock_indiclient()
    worker.indiclient.telescope_device = None

    assert worker.getTelescopeRaDec() is None
    assert worker.reparkTelescope() is None


def test_capture_worker_reconfigure_ccd(capture_worker_setup):
    worker = capture_worker_setup
    worker.indiclient = make_mock_indiclient()

    # reconfigure_camera False -> early return
    worker.reconfigure_camera = False
    worker.reconfigureCcd()
    assert not worker.indiclient.configureCcdDevice.called

    # Night mode with cooling and libcamera interface
    worker.reconfigure_camera = True
    worker.night = True
    worker.moonmode = True
    worker.config['CCD_COOLING'] = True
    worker.config['CCD_TEMP'] = -10.0
    worker.config['CAMERA_INTERFACE'] = 'libcamera_ccd'
    worker.config['LIBCAMERA'] = {'IMAGE_FILE_TYPE': 'dng'}

    worker.reconfigureCcd()
    worker.indiclient.enableCcdCooler.assert_called_once()
    worker.indiclient.setCcdTemperature.assert_called_with(-10.0)
    assert worker.indiclient.libcamera_bit_depth == 16
    assert worker.night_av[constants.NIGHT_NIGHT] == 1
    assert worker.night_av[constants.NIGHT_MOONMODE] == 1

    # Night mode without cooling
    worker.reconfigure_camera = True
    worker.moonmode = False
    worker.config['CCD_COOLING'] = False
    worker.config['LIBCAMERA']['IMAGE_FILE_TYPE'] = 'jpg'
    worker.reconfigureCcd()
    worker.indiclient.disableCcdCooler.assert_called_once()
    assert worker.indiclient.libcamera_bit_depth == 8

    # Day mode with cooling and day config
    worker.reconfigure_camera = True
    worker.night = False
    worker.config['DAYTIME_CAPTURE'] = True
    worker.config['DAYTIME_CAPTURE_SAVE'] = True
    worker.config['CCD_COOLING_DAY'] = True
    worker.config['CCD_TEMP_DAY'] = 30.0
    worker.config['INDI_CONFIG_DAY'] = {'DAY_SETTING': 1}
    worker.config['LIBCAMERA']['IMAGE_FILE_TYPE_DAY'] = 'dng'

    worker.reconfigureCcd()
    assert worker.generate_timelapse_flag is True
    assert worker.indiclient.libcamera_bit_depth == 16

    # Day mode without cooling and daytime capture disabled
    worker.reconfigure_camera = True
    worker.config['DAYTIME_CAPTURE'] = False
    worker.config['CCD_COOLING_DAY'] = False
    worker.config['INDI_CONFIG_DAY'] = {}
    worker.config['LIBCAMERA']['IMAGE_FILE_TYPE_DAY'] = 'jpg'

    worker.reconfigureCcd()
    assert worker.generate_timelapse_flag is False
    assert worker.indiclient.libcamera_bit_depth == 8


def test_capture_worker_detect_night_moonmode(capture_worker_setup):
    worker = capture_worker_setup
    worker.config['NIGHT_SUN_ALT_DEG'] = 90.0  # Force night = True
    worker.night_sun_radians = 3.14
    worker.config['NIGHT_MOONMODE_ALT_DEG'] = -90.0
    worker.night_moonmode_radians = -3.14
    worker.config['NIGHT_MOONMODE_PHASE'] = 0.0  # Moonmode phase met

    worker.detectNight()
    assert worker.night is True
    assert worker.moonmode is True


def test_capture_worker_helpers_disabled_and_pano(capture_worker_setup, app):
    worker = capture_worker_setup
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()

        # When TIMELAPSE_ENABLE is False
        worker.config['TIMELAPSE_ENABLE'] = False
        worker._generateDayTimelapse('20260906', cam.id)
        worker._generateNightTimelapse('20260906', cam.id)
        worker._generateNightKeogram('20260906', cam.id)
        worker._generateDayKeogram('20260906', cam.id)

        # When DAYTIME_TIMELAPSE is False
        worker.config['TIMELAPSE_ENABLE'] = True
        worker.config['DAYTIME_TIMELAPSE'] = False
        worker._generateDayTimelapse('20260906', cam.id)
        worker._generateDayKeogram('20260906', cam.id)

        # When FISH2PANO is True
        worker.config['DAYTIME_TIMELAPSE'] = True
        worker.config['FISH2PANO'] = {'ENABLE': True}
        worker._generateDayTimelapse('20260906', cam.id)
        worker._generateNightTimelapse('20260906', cam.id)

        tasks = IndiAllSkyDbTaskQueueTable.query.all()
        assert len(tasks) >= 2


def test_capture_worker_shoot(capture_worker_setup):
    worker = capture_worker_setup
    worker.indiclient = make_mock_indiclient()

    worker.shoot(1.5, 200.0, 1)
    worker.indiclient.setCcdExposure.assert_called_once_with(1.5, 200.0, 1, sync=True, timeout=None, sqm_exposure=False)


def test_capture_worker_set_time_systemd(capture_worker_setup):
    worker = capture_worker_setup

    mock_manager = MagicMock()
    mock_bus = MagicMock()
    mock_bus.get_object.return_value = MagicMock()

    with patch('dbus.SystemBus', return_value=mock_bus):
        with patch('dbus.Interface', return_value=mock_manager):
            with patch('time.sleep'):
                now_utc = datetime.now(tz=timezone.utc)
                worker.setTimeSystemd(now_utc)
                mock_manager.SetNTP.assert_called_once_with(False, False)
                assert mock_manager.SetTime.called


def test_capture_worker_sensor_labels_errors_and_temps(capture_worker_setup):
    worker = capture_worker_setup

    # Unknown sensor class triggers AttributeError
    worker.config['TEMP_SENSOR'] = {
        'A_CLASSNAME': 'NonExistentSensorClass',
        'A_USER_VAR_SLOT': 'sensor_user_10',
    }
    worker.update_sensor_slot_labels()

    # Valid sensor class with labels and psutil temps with and without label
    mock_sensor_cls = MagicMock()
    mock_sensor_cls.METADATA = {'count': 1, 'name': 'MockSensor'}
    mock_sensor_cls.get_labels.return_value = ['Probe A']

    mock_temp_item1 = MagicMock(label='Core 0')
    mock_temp_item2 = MagicMock(label='')  # Empty label tests str(i) fallback

    with patch('indi_allsky.devices.sensors.MockSensorClass', mock_sensor_cls, create=True):
        worker.config['TEMP_SENSOR'] = {
            'A_CLASSNAME': 'MockSensorClass',
            'A_LABEL': 'Custom Label',
            'A_USER_VAR_SLOT': 'sensor_user_10',
            'A_TITLE_TEMPLATE': '{name:s}-{label:s}-{probe:s}',
            'A_PIN_1': 'pin1',
        }
        with patch('psutil.sensors_temperatures', return_value={'cpu_thermal': [mock_temp_item1, mock_temp_item2]}):
            worker.update_sensor_slot_labels()

    assert 'MockSensor-Custom Label-Probe A' in worker.SENSOR_SLOTS[10][1]
    assert 'cpu_thermal/Core 0' in worker.SENSOR_SLOTS[80][1]
    assert 'cpu_thermal/1' in worker.SENSOR_SLOTS[81][1]


def test_capture_worker_saferun_disconnected_and_removed(capture_worker_setup, app):
    worker = capture_worker_setup
    with app.app_context():
        worker._initialize = MagicMock()
        worker._pre_run_tasks = MagicMock()
        worker.night = True
        worker.moonmode = False
        worker.detectNight = MagicMock()

        # Case 1: disconnected
        worker.indiclient = make_mock_indiclient()
        worker.indiclient.disconnected = True
        worker.saferun()

        # Case 2: ccd_removed
        worker.indiclient.disconnected = False
        worker.indiclient.ccd_removed = True
        worker.saferun()


def test_capture_worker_saferun_capture_pause_and_daytime_disabled(capture_worker_setup, app):
    worker = capture_worker_setup
    with app.app_context():
        worker._initialize = MagicMock()
        worker._pre_run_tasks = MagicMock()
        worker.night = True
        worker.moonmode = False
        worker.detectNight = MagicMock()
        worker.indiclient = make_mock_indiclient()

        # Case 1: CAPTURE_PAUSE and shutdown
        worker.config['CAPTURE_PAUSE'] = True
        worker._shutdown = True
        with patch('time.sleep'):
            worker.saferun()
        worker.indiclient.disableCcdCooler.assert_called_once()
        worker.indiclient.disconnectServer.assert_called_once()

        # Case 2: Daytime capture disabled, day mode, shutdown
        worker.config['CAPTURE_PAUSE'] = False
        worker.config['DAYTIME_CAPTURE'] = False
        worker.night = False
        worker._shutdown = True
        with patch('time.sleep'):
            worker.saferun()


def test_capture_worker_saferun_queue_commands_and_exposure_timeout(capture_worker_setup, app):
    worker = capture_worker_setup
    with app.app_context():
        worker._initialize = MagicMock()
        worker._pre_run_tasks = MagicMock()
        worker.night = True
        worker.moonmode = False
        worker.detectNight = MagicMock()
        worker.indiclient = make_mock_indiclient()

        # Put stop in capture_q
        worker.capture_q.put({'stop': True})
        # Put settime in capture_q
        worker.capture_q.put({'settime': 120})
        # Put unknown in capture_q
        worker.capture_q.put({'unknown': 'val'})

        # Trigger exposure timeout in outer loop
        worker.exposure_timeout = 5

        def fake_sleep(secs):
            worker._shutdown = True

        with patch('time.sleep', side_effect=fake_sleep):
            worker.saferun()

        assert worker.indiclient.disconnectServer.called


def test_capture_worker_saferun_inner_loop_exposures(capture_worker_setup, app):
    worker = capture_worker_setup
    with app.app_context():
        worker._initialize = MagicMock()
        worker._pre_run_tasks = MagicMock()
        worker.night = False
        worker.moonmode = False
        worker.detectNight = MagicMock()
        worker.indiclient = make_mock_indiclient()
        worker.shoot = MagicMock()
        worker.setTimeSystemd = MagicMock()

        # Configure transitions and queue depths
        worker.generate_timelapse_flag = True
        worker.night_av[constants.NIGHT_NIGHT] = 1

        # Queue depth backoff
        for i in range(5):
            worker.image_q.put(i)

        worker.sqm_camera_enable = True
        worker.astro_av[constants.ASTRO_SUN_ALT] = -20.0  # Night SQM
        worker.sqm_tasks_time = time.time() - 10

        worker.update_time_offset = None

        iterations = 0

        def fake_sleep(secs):
            nonlocal iterations
            iterations += 1
            if iterations == 1:
                # Camera ready with frame delta < -1 warning
                worker._expUtils.EXPOSURE_CURRENT = 10.0
            elif iterations == 2:
                worker.update_time_offset = 60
            elif iterations >= 3:
                worker._shutdown = True

        with patch('time.sleep', side_effect=fake_sleep):
            worker.saferun()

        assert worker.shoot.called
        assert worker.setTimeSystemd.called


def test_capture_worker_detect_night(capture_worker_setup):
    worker = capture_worker_setup
    worker.detectNight()
    assert -90.0 <= worker.astro_av[constants.ASTRO_SUN_ALT] <= 90.0
    assert -90.0 <= worker.astro_av[constants.ASTRO_MOON_ALT] <= 90.0
    assert 0.0 <= worker.astro_av[constants.ASTRO_MOON_PHASE] <= 100.0


def test_capture_worker_update_sensor_slot_labels(capture_worker_setup):
    worker = capture_worker_setup
    worker.update_sensor_slot_labels()
    assert len(worker.SENSOR_SLOTS) > 0


def test_capture_worker_get_ccd_temperature(capture_worker_setup):
    worker = capture_worker_setup
    worker.indiclient = MagicMock()
    worker.indiclient.getCcdTemperature.return_value = 18.5

    temp = worker.getCcdTemperature()
    assert temp == 18.5
    assert worker.sensors_temp_av[constants.SENSOR_TEMP_CCD_TEMP] == 18.5


def test_capture_worker_update_config_location(capture_worker_setup, app):
    worker = capture_worker_setup
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        worker.camera_id = cam.id

        worker.updateConfigLocation(-34.95, 138.62, 75)
        assert worker.config['LOCATION_LATITUDE'] == -34.95
        assert worker.config['LOCATION_LONGITUDE'] == 138.62
        assert worker.config['LOCATION_ELEVATION'] == 75

        task = IndiAllSkyDbTaskQueueTable.query.order_by(IndiAllSkyDbTaskQueueTable.id.desc()).first()
        assert task is not None
        assert task.data['action'] == 'setlocation'
        assert task.data['latitude'] == -34.95


def test_capture_worker_get_gps_position(capture_worker_setup, app):
    worker = capture_worker_setup
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        worker.camera_id = cam.id
        worker.config['GPS_ENABLE'] = True

        worker.indiclient = MagicMock()
        worker.indiclient.gps_device = True
        worker.indiclient.getGpsPosition.return_value = (-34.9285, 138.6007, 50.0)

        lat, lon, elev = worker.getGpsPosition()
        assert lat == -34.9285
        assert lon == 138.6007
        assert elev == 50.0


def test_capture_worker_get_telescope_ra_dec(capture_worker_setup):
    worker = capture_worker_setup
    worker.indiclient = MagicMock()
    worker.indiclient.telescope_device = True
    worker.indiclient.getTelescopeRaDec.return_value = (180.5, 45.2)

    ra, dec = worker.getTelescopeRaDec()
    assert ra == 180.5
    assert dec == 45.2
    assert worker.position_av[constants.POSITION_RA] == 180.5
    assert worker.position_av[constants.POSITION_DEC] == 45.2


def test_capture_worker_task_queue_generators(capture_worker_setup, app):
    worker = capture_worker_setup
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()

        worker._generateDayTimelapse('20260906', cam.id)
        worker._generateNightTimelapse('20260906', cam.id)
        worker._generateNightKeogram('20260906', cam.id)
        worker._generateDayKeogram('20260906', cam.id)
        worker._uploadAllskyEndOfNight(cam.id)
        worker._expireData(cam.id)

        tasks = IndiAllSkyDbTaskQueueTable.query.all()
        assert len(tasks) >= 6
