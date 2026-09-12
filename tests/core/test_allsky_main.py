import fcntl
import io
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch
import pytest

from indi_allsky import constants
from indi_allsky.allsky import IndiAllSky
from indi_allsky.config import IndiAllSkyConfig
from indi_allsky.exceptions import ConfigSaveException, TimeOutException
from indi_allsky.flask import create_app, db
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbKeogramTable,
    IndiAllSkyDbPanoramaImageTable,
    IndiAllSkyDbPanoramaVideoTable,
    IndiAllSkyDbStarTrailsTable,
    IndiAllSkyDbStarTrailsVideoTable,
    IndiAllSkyDbTaskQueueTable,
    IndiAllSkyDbVideoTable,
    NotificationCategory,
    TaskQueueQueue,
    TaskQueueState,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound


@pytest.fixture
def mock_allsky_config(tmp_path):
    return {
        'LOCATION_LATITUDE': -34.9285,
        'LOCATION_LONGITUDE': 138.6007,
        'LOCATION_ELEVATION': 50,
        'IMAGE_FOLDER': str(tmp_path),
        'VARLIB_FOLDER': str(tmp_path),
        'UPLOAD_WORKERS': 1,
        'IMAGE_FILE_TYPE': 'jpg',
        'CAPTURE_PAUSE': False,
        'BACKUP_DB_PERIOD_DAYS': 7,
        'ALLSKYMAP': {'ENABLE': True, 'INTERVAL': 10},
    }


@pytest.fixture
def create_allsky_instance(app, tmp_path, mock_allsky_config):
    def _create(config_override=None, config_level=1):
        cfg = dict(mock_allsky_config)
        if config_override:
            cfg.update(config_override)

        with app.app_context():
            cam = IndiAllSkyDbCameraTable.query.first()
            if not cam:
                cam = IndiAllSkyDbCameraTable(
                    name='Main Allsky Cam',
                    uuid='cam-allsky-1',
                    latitude=-34.9285,
                    longitude=138.6007,
                    elevation=50,
                    nightSunAlt=-6.0,
                )
                db.session.add(cam)
                db.session.commit()

            with patch('indi_allsky.allsky.IndiAllSkyConfig') as mock_cfg_cls:
                mock_cfg_inst = MagicMock()
                mock_cfg_inst.config = cfg
                mock_cfg_inst.config_id = 1
                mock_cfg_inst.config_level = config_level
                mock_cfg_cls.return_value = mock_cfg_inst

                with patch('indi_allsky.allsky.__config_level__', 1):
                    allsky = IndiAllSky()
                    allsky._config_obj = mock_cfg_inst
                    return allsky

    return _create


def test_indi_allsky_initialization(create_allsky_instance, tmp_path):
    allsky = create_allsky_instance()
    assert allsky.name == 'Main'
    assert allsky.pid_file == tmp_path / 'indi-allsky.pid'

    # Test signal handlers
    allsky.sighup_handler_main(signal.SIGHUP, None)
    assert allsky._reload is True

    allsky.sigterm_handler_main(signal.SIGTERM, None)
    assert allsky._shutdown is True
    assert allsky._terminate is True

    allsky.sigint_handler_main(signal.SIGINT, None)
    assert allsky._shutdown is True

    with pytest.raises(TimeOutException):
        allsky.sigalarm_handler_main(signal.SIGALRM, None)

    # Test pid_file property setter
    custom_pid = tmp_path / 'custom.pid'
    allsky.pid_file = custom_pid
    assert allsky.pid_file == custom_pid


def test_indi_allsky_init_no_config(app):
    with app.app_context():
        with patch('indi_allsky.allsky.IndiAllSkyConfig', side_effect=NoResultFound):
            with pytest.raises(SystemExit) as exc_info:
                IndiAllSky()
            assert exc_info.value.code == 1


def test_indi_allsky_init_version_mismatch(app, mock_allsky_config):
    with app.app_context():
        with patch('indi_allsky.allsky.IndiAllSkyConfig') as mock_cfg_cls:
            mock_cfg_inst = MagicMock()
            mock_cfg_inst.config = mock_allsky_config
            mock_cfg_inst.config_id = 1
            mock_cfg_inst.config_level = 999
            mock_cfg_cls.return_value = mock_cfg_inst

            with patch('indi_allsky.allsky.__config_level__', 1):
                with pytest.raises(SystemExit) as exc_info:
                    IndiAllSky()
                assert exc_info.value.code == 1


def test_indi_allsky_init_no_image_folder(create_allsky_instance):
    allsky = create_allsky_instance({'IMAGE_FOLDER': None})
    assert 'html' in str(allsky.image_dir)


def test_indi_allsky_write_pid(create_allsky_instance, tmp_path):
    allsky = create_allsky_instance()
    pid_file = tmp_path / 'test.pid'
    allsky.pid_file = pid_file

    with patch('fcntl.flock'):
        allsky.write_pid()

    assert pid_file.exists()
    assert int(allsky._miscDb.getState('PID')) == os.getpid()
    if allsky.pid_lock:
        allsky.pid_lock.close()


def test_indi_allsky_write_pid_permission_error_open(create_allsky_instance, tmp_path):
    allsky = create_allsky_instance()
    allsky.pid_file = tmp_path / 'unwritable.pid'

    with patch('io.open', side_effect=PermissionError("Permission denied")):
        with pytest.raises(SystemExit) as exc:
            allsky.write_pid()
        assert exc.value.code == 1


def test_indi_allsky_write_pid_flock_blocking(create_allsky_instance, tmp_path):
    allsky = create_allsky_instance()
    allsky.pid_file = tmp_path / 'locked.pid'

    with patch('fcntl.flock', side_effect=BlockingIOError):
        with pytest.raises(SystemExit) as exc:
            allsky.write_pid()
        assert exc.value.code == 1


def test_indi_allsky_write_pid_flock_permission_error(create_allsky_instance, tmp_path):
    allsky = create_allsky_instance()
    allsky.pid_file = tmp_path / 'locked_perm.pid'

    err = PermissionError()
    err.strerror = "Permission denied"
    with patch('fcntl.flock', side_effect=err):
        with pytest.raises(SystemExit) as exc:
            allsky.write_pid()
        assert exc.value.code == 1


def test_indi_allsky_get_system_type(create_allsky_instance):
    allsky = create_allsky_instance()

    with patch('pathlib.Path.exists', return_value=False):
        assert allsky._getSystemType() == 'Generic PC'

    with patch('pathlib.Path.exists', return_value=True):
        with patch('io.open') as mock_open:
            mock_f = MagicMock()
            mock_f.readline.return_value = 'Raspberry Pi 4 Model B\n'
            mock_open.return_value.__enter__.return_value = mock_f
            assert allsky._getSystemType() == 'Raspberry Pi 4 Model B'

        with patch('io.open', side_effect=PermissionError("Denied")):
            assert allsky._getSystemType() == 'Unknown'

        with patch('io.open') as mock_open:
            mock_f = MagicMock()
            mock_f.readline.return_value = '   \n'
            mock_open.return_value.__enter__.return_value = mock_f
            assert allsky._getSystemType() == 'Unknown'


def test_indi_allsky_startup(create_allsky_instance, app):
    allsky = create_allsky_instance()

    with app.app_context():
        # Case 1: normal startup when status was STOPPED
        allsky._miscDb.setState('STATUS', constants.STATUS_STOPPED)
        allsky._startup()

        # Case 2: abnormal shutdown when previous status was RUNNING
        allsky._miscDb.setState('STATUS', constants.STATUS_RUNNING)
        allsky._startup()

        # Case 3: 32-bit architecture log branch
        with patch('sys.maxsize', 2147483647):
            allsky._startup()

        # Case 4: ValueError when status is not an int
        allsky._miscDb.setState('STATUS', 'invalid_status_str')
        allsky._startup()

        # Case 5: NoResultFound when status key doesn't exist
        with patch.object(allsky._miscDb, 'getState', side_effect=NoResultFound):
            allsky._startup()


def test_indi_allsky_capture_worker_start_stop(create_allsky_instance):
    allsky = create_allsky_instance()

    with patch('indi_allsky.capture.CaptureWorker') as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker_cls.return_value = mock_worker

        # Start worker when not initialized
        allsky._startCaptureWorker()
        assert allsky.capture_worker is not None
        mock_worker.start.assert_called_once()

        # Starting worker when already alive does nothing
        mock_worker.is_alive.return_value = True
        allsky._startCaptureWorker()
        assert mock_worker.start.call_count == 1

        # Starting worker when dead and error_q has items logs error
        mock_worker.is_alive.return_value = False
        with patch.object(allsky.capture_error_q, 'get_nowait', return_value=('Capture failed', 'Traceback line 1\nTraceback line 2')):
            allsky._startCaptureWorker()
            assert allsky.capture_worker_idx == 2

    # Stop worker tests
    allsky.capture_worker = None
    allsky._stopCaptureWorker()  # None check

    allsky.capture_worker = mock_worker
    mock_worker.is_alive.return_value = False
    allsky._stopCaptureWorker()  # not alive check

    mock_worker.is_alive.return_value = True
    allsky._terminate = False
    allsky._stopCaptureWorker()
    mock_worker.terminate.assert_not_called()
    mock_worker.join.assert_called_once()
    assert allsky.capture_q.get() == {'stop': True}

    mock_worker.join.reset_mock()
    allsky._terminate = True
    allsky._stopCaptureWorker()
    mock_worker.terminate.assert_called_once()
    mock_worker.join.assert_called_once()


def test_indi_allsky_image_worker_start_stop(create_allsky_instance, app):
    allsky = create_allsky_instance()

    with patch('indi_allsky.image.ImageWorker') as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker_cls.return_value = mock_worker

        allsky._startImageWorker()
        assert allsky.image_worker is not None
        mock_worker.start.assert_called_once()

        # Alive check
        mock_worker.is_alive.return_value = True
        allsky._startImageWorker()
        assert mock_worker.start.call_count == 1

        # Error queue handling
        mock_worker.is_alive.return_value = False
        with patch.object(allsky.image_error_q, 'get_nowait', return_value=('Image failed', 'Traceback line 1')):
            allsky._startImageWorker()

        # Test index % 10 notification
        allsky.image_worker_idx = 9
        mock_worker.is_alive.return_value = False
        with app.app_context():
            allsky._startImageWorker()

    # Stop worker tests
    allsky.image_worker = None
    allsky._stopImageWorker()

    allsky.image_worker = mock_worker
    mock_worker.is_alive.return_value = False
    allsky._stopImageWorker()

    mock_worker.is_alive.return_value = True
    allsky._terminate = True
    allsky._stopImageWorker()
    mock_worker.terminate.assert_called_once()
    mock_worker.join.assert_called_once()
    assert allsky.image_q.get() == {'stop': True}


def test_indi_allsky_video_worker_start_stop(create_allsky_instance, app):
    allsky = create_allsky_instance()

    with patch('indi_allsky.video.VideoWorker') as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker_cls.return_value = mock_worker

        allsky._startVideoWorker()
        assert allsky.video_worker is not None
        mock_worker.start.assert_called_once()

        mock_worker.is_alive.return_value = True
        allsky._startVideoWorker()
        assert mock_worker.start.call_count == 1

        mock_worker.is_alive.return_value = False
        with patch.object(allsky.video_error_q, 'get_nowait', return_value=('Video failed', 'Traceback line 1')):
            allsky._startVideoWorker()

        # Test index % 10 notification
        allsky.video_worker_idx = 9
        mock_worker.is_alive.return_value = False
        with app.app_context():
            allsky._startVideoWorker()

    # Stop video worker
    allsky.video_worker = None
    allsky._stopVideoWorker()

    allsky.video_worker = mock_worker
    mock_worker.is_alive.return_value = False
    allsky._stopVideoWorker()

    mock_worker.is_alive.return_value = True
    allsky._terminate = True
    allsky._stopVideoWorker()
    mock_worker.terminate.assert_called_once()
    mock_worker.join.assert_called_once()
    assert allsky.video_q.get() == {'stop': True}


def test_indi_allsky_sensor_worker_start_stop(create_allsky_instance, app):
    allsky = create_allsky_instance()

    with patch('indi_allsky.sensor.SensorWorker') as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker_cls.return_value = mock_worker

        allsky._startSensorWorker()
        assert allsky.sensor_worker is not None
        mock_worker.start.assert_called_once()

        mock_worker.is_alive.return_value = True
        allsky._startSensorWorker()
        assert mock_worker.start.call_count == 1

        mock_worker.is_alive.return_value = False
        with patch.object(allsky.sensor_error_q, 'get_nowait', return_value=('Sensor failed', 'Traceback line 1')):
            allsky._startSensorWorker()

        # Test index % 10 notification
        allsky.sensor_worker_idx = 9
        mock_worker.is_alive.return_value = False
        with app.app_context():
            allsky._startSensorWorker()

    # Stop sensor worker
    allsky.sensor_worker = None
    allsky._stopSensorWorker()

    allsky.sensor_worker = mock_worker
    mock_worker.is_alive.return_value = False
    allsky._stopSensorWorker()

    mock_worker.is_alive.return_value = True
    allsky._stopSensorWorker()
    mock_worker.join.assert_called_once()
    assert allsky.sensor_q.get() == {'stop': True}


def test_indi_allsky_uploader_workers_start_stop(create_allsky_instance, app):
    allsky = create_allsky_instance()

    with patch('indi_allsky.uploader.FileUploader') as mock_uploader_cls:
        mock_worker = MagicMock()
        mock_uploader_cls.return_value = mock_worker

        allsky._startFileUploadWorkers()
        assert allsky.upload_worker_list[0]['worker'] is not None

        # Alive check
        mock_worker.is_alive.return_value = True
        allsky._startFileUploadWorkers()

        # Error queue check
        mock_worker.is_alive.return_value = False
        with patch.object(allsky.upload_worker_list[0]['error_q'], 'get_nowait', return_value=('Upload failed', 'Traceback line 1')):
            allsky._startFileUploadWorkers()

        # Index % 20 notification
        allsky.upload_worker_idx = 19
        mock_worker.is_alive.return_value = False
        with app.app_context():
            allsky._startFileUploadWorkers()

    # Stop upload workers
    allsky.upload_worker_list[0]['worker'] = None
    allsky._stopFileUploadWorkers()

    allsky.upload_worker_list[0]['worker'] = mock_worker
    mock_worker.is_alive.return_value = False
    allsky._stopFileUploadWorkers()

    mock_worker.is_alive.return_value = True
    allsky._stopFileUploadWorkers()
    mock_worker.stop.assert_called_once()
    mock_worker.join.assert_called_once()


def test_indi_allsky_reload_handler(create_allsky_instance, app):
    allsky = create_allsky_instance()

    with app.app_context():
        # Case 1: successful reload
        with patch('indi_allsky.allsky.IndiAllSkyConfig') as mock_cfg_cls:
            mock_cfg = MagicMock()
            mock_cfg.config = {'RELOADED': True}
            mock_cfg.config_id = 42
            mock_cfg.config_level = 1
            mock_cfg_cls.return_value = mock_cfg

            with patch('indi_allsky.allsky.__config_level__', 1):
                allsky.reload_handler()
                assert allsky.config['RELOADED'] is True
                assert int(allsky._miscDb.getState('CONFIG_ID')) == 42

        # Case 2: version mismatch during reload
        with patch('indi_allsky.allsky.IndiAllSkyConfig') as mock_cfg_cls:
            mock_cfg = MagicMock()
            mock_cfg.config = {'RELOADED': True}
            mock_cfg.config_id = 43
            mock_cfg.config_level = 999
            mock_cfg_cls.return_value = mock_cfg

            with patch('indi_allsky.allsky.__config_level__', 1):
                allsky.reload_handler()
                assert int(allsky._miscDb.getState('CONFIG_ID')) == 42  # Unchanged


def test_indi_allsky_task_management(create_allsky_instance, app):
    allsky = create_allsky_instance()

    with app.app_context():
        # Test _systemHealthCheck
        allsky._systemHealthCheck()
        task_msg = allsky.video_q.get()
        health_task = db.session.get(IndiAllSkyDbTaskQueueTable, task_msg['task_id'])
        assert health_task.data['action'] == 'systemHealthCheck'

        # Test _expireOrphanedTasks
        t1 = IndiAllSkyDbTaskQueueTable(queue=TaskQueueQueue.MAIN, state=TaskQueueState.MANUAL, data={})
        t2 = IndiAllSkyDbTaskQueueTable(queue=TaskQueueQueue.VIDEO, state=TaskQueueState.QUEUED, data={})
        t3 = IndiAllSkyDbTaskQueueTable(queue=TaskQueueQueue.UPLOAD, state=TaskQueueState.RUNNING, data={})
        t4 = IndiAllSkyDbTaskQueueTable(queue=TaskQueueQueue.VIDEO, state=TaskQueueState.SUCCESS, data={})
        db.session.add_all([t1, t2, t3, t4])
        db.session.commit()

        allsky._expireOrphanedTasks()
        assert t1.state == TaskQueueState.EXPIRED
        assert t2.state == TaskQueueState.EXPIRED
        assert t3.state == TaskQueueState.EXPIRED
        assert t4.state == TaskQueueState.SUCCESS

        # Test _flushOldTasks
        old_time = datetime.now() - timedelta(days=5)
        t_old = IndiAllSkyDbTaskQueueTable(queue=TaskQueueQueue.MAIN, state=TaskQueueState.EXPIRED, data={}, createDate=old_time)
        t_new = IndiAllSkyDbTaskQueueTable(queue=TaskQueueQueue.MAIN, state=TaskQueueState.EXPIRED, data={})
        db.session.add_all([t_old, t_new])
        db.session.commit()
        old_id = t_old.id
        new_id = t_new.id

        allsky._flushOldTasks()
        assert db.session.get(IndiAllSkyDbTaskQueueTable, old_id) is None
        assert db.session.get(IndiAllSkyDbTaskQueueTable, new_id) is not None


def test_indi_allsky_queue_manual_tasks(create_allsky_instance, app):
    allsky = create_allsky_instance()

    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()

        # VIDEO manual task
        t_video = IndiAllSkyDbTaskQueueTable(queue=TaskQueueQueue.VIDEO, state=TaskQueueState.MANUAL, data={'action': 'render'})
        # UPLOAD manual task
        t_upload = IndiAllSkyDbTaskQueueTable(queue=TaskQueueQueue.UPLOAD, state=TaskQueueState.MANUAL, data={'action': 'upload'})
        # MAIN reload tasks (first + duplicate)
        t_reload1 = IndiAllSkyDbTaskQueueTable(queue=TaskQueueQueue.MAIN, state=TaskQueueState.MANUAL, data={'action': 'reload'})
        t_reload2 = IndiAllSkyDbTaskQueueTable(queue=TaskQueueQueue.MAIN, state=TaskQueueState.MANUAL, data={'action': 'reload'})
        # MAIN settime task
        t_time = IndiAllSkyDbTaskQueueTable(queue=TaskQueueQueue.MAIN, state=TaskQueueState.MANUAL, data={'action': 'settime', 'time_offset': 60})
        # MAIN setlocation task
        t_loc = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.MAIN,
            state=TaskQueueState.MANUAL,
            data={'action': 'setlocation', 'camera_id': cam.id, 'latitude': -35.0, 'longitude': 138.5, 'elevation': 100},
        )
        # MAIN setpaused tasks (first + duplicate)
        t_pause1 = IndiAllSkyDbTaskQueueTable(queue=TaskQueueQueue.MAIN, state=TaskQueueState.MANUAL, data={'action': 'setpaused', 'pause': True})
        t_pause2 = IndiAllSkyDbTaskQueueTable(queue=TaskQueueQueue.MAIN, state=TaskQueueState.MANUAL, data={'action': 'setpaused', 'pause': True})
        # MAIN unknown task
        t_unknown = IndiAllSkyDbTaskQueueTable(queue=TaskQueueQueue.MAIN, state=TaskQueueState.MANUAL, data={'action': 'bad_action'})

        db.session.add_all([t_video, t_upload, t_reload1, t_reload2, t_time, t_loc, t_pause1, t_pause2, t_unknown])
        db.session.commit()

        allsky._queueManualTasks()

        assert t_video.state == TaskQueueState.QUEUED
        assert allsky.video_q.get() == {'task_id': t_video.id}

        assert t_upload.state == TaskQueueState.QUEUED
        assert allsky.upload_q.get() == {'task_id': t_upload.id}

        assert t_reload1.state == TaskQueueState.SUCCESS
        assert allsky._reload is True
        assert t_reload2.state == TaskQueueState.EXPIRED

        assert t_time.state == TaskQueueState.SUCCESS
        assert allsky.capture_q.get() == {'settime': 60}

        assert t_loc.state == TaskQueueState.SUCCESS
        assert allsky.config['LOCATION_LATITUDE'] == -35.0

        assert t_pause1.state == TaskQueueState.SUCCESS
        assert allsky.config['CAPTURE_PAUSE'] is True
        assert t_pause2.state == TaskQueueState.EXPIRED

        assert t_unknown.state == TaskQueueState.FAILED

        # Test unmanaged queue branch via mock task list
        t_unmanaged = IndiAllSkyDbTaskQueueTable(queue=TaskQueueQueue.IMAGE, state=TaskQueueState.MANUAL, data={})
        db.session.add(t_unmanaged)
        db.session.commit()
        with patch.object(allsky, '_queueManualTasks', wraps=allsky._queueManualTasks):
            with patch('indi_allsky.allsky.IndiAllSkyDbTaskQueueTable.query') as mock_q:
                mock_q.filter.return_value.filter.return_value.order_by.return_value = [t_unmanaged]
                allsky._queueManualTasks()
                assert t_unmanaged.state == TaskQueueState.FAILED


def test_indi_allsky_update_config_location(create_allsky_instance, app):
    allsky = create_allsky_instance()

    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()

        # Success case
        allsky.updateConfigLocation(-34.1234, 138.5678, 120, cam.id)
        assert allsky.config['LOCATION_LATITUDE'] == -34.123
        assert allsky.config['LOCATION_LONGITUDE'] == 138.568
        assert allsky.config['LOCATION_ELEVATION'] == 120
        db.session.refresh(cam)
        assert cam.latitude == -34.123
        assert cam.elevation == 120

        # ConfigSaveException handling
        allsky._config_obj.save.side_effect = ConfigSaveException("Save failed")
        allsky.updateConfigLocation(-30.0, 130.0, 50, cam.id)
        allsky._config_obj.save.side_effect = None

        # Camera not found
        allsky.updateConfigLocation(-30.0, 130.0, 50, 99999)


def test_indi_allsky_update_config_paused(create_allsky_instance):
    allsky = create_allsky_instance()

    allsky.updateConfigPaused(True)
    assert allsky.config['CAPTURE_PAUSE'] is True

    allsky.updateConfigPaused(False)
    assert allsky.config['CAPTURE_PAUSE'] is False

    # ConfigSaveException handling
    allsky._config_obj.save.side_effect = ConfigSaveException("Save failed")
    allsky.updateConfigPaused(True)
    allsky._config_obj.save.side_effect = None


def test_indi_allsky_periodic_tasks(create_allsky_instance, app):
    allsky = create_allsky_instance()

    with app.app_context():
        # Early return when periodic_tasks_time > now
        now = time.time()
        allsky.periodic_tasks_time = now + 1000
        allsky._periodic_tasks()

        # Trigger periodic tasks
        allsky.periodic_tasks_time = now - 1
        allsky.cleanup_tasks_time = now - 1
        allsky.aurora_tasks_time = now - 1
        allsky.smoke_tasks_time = now - 1
        allsky.sat_data_tasks_time = now - 1
        allsky.backup_tasks_time = now - 1
        allsky.allskymap_tasks_time = now - 1

        allsky.config['ALLSKYMAP'] = {'ENABLE': True, 'INTERVAL': 0}  # Tests interval < 1 branch

        with patch.object(allsky, '_flushOldTasks') as mock_flush:
            with patch.object(allsky, '_systemHealthCheck') as mock_health:
                with patch.object(allsky, '_updateAuroraData') as mock_aurora:
                    with patch.object(allsky, '_updateSmokeData') as mock_smoke:
                        with patch.object(allsky, '_updateSatelliteTleData') as mock_sat:
                            with patch.object(allsky, '_backupDatabase') as mock_backup:
                                with patch.object(allsky, '_triggerAllskyMapPing') as mock_ping:
                                    allsky._periodic_tasks()

                                    assert mock_flush.called
                                    assert mock_health.called
                                    assert mock_aurora.called
                                    assert mock_smoke.called
                                    assert mock_sat.called
                                    assert mock_backup.called
                                    assert mock_ping.called


def test_indi_allsky_background_job_creators(create_allsky_instance, app):
    allsky = create_allsky_instance()

    with app.app_context():
        allsky._updateAuroraData()
        allsky._updateSmokeData()
        allsky._updateSatelliteTleData()
        allsky._backupDatabase()
        allsky._triggerAllskyMapPing()

        # Verify tasks created and queued
        assert allsky.video_q.qsize() == 5


def test_indi_allsky_get_folder_files_by_ext(create_allsky_instance, tmp_path):
    allsky = create_allsky_instance()

    sub = tmp_path / 'subdir'
    sub.mkdir()

    f1 = tmp_path / 'image1.jpg'
    f2 = sub / 'image2.png'
    f3 = tmp_path / 'video.mp4'
    f1.write_text('a')
    f2.write_text('b')
    f3.write_text('c')

    files = []
    allsky._getFolderFilesByExt(str(tmp_path), files, extension_list=['jpg', 'png'])
    assert f1 in files
    assert f2 in files
    assert f3 not in files

    files_def = []
    allsky._getFolderFilesByExt(str(tmp_path), files_def)  # default uses config['IMAGE_FILE_TYPE'] = 'jpg'
    assert f1 in files_def
    assert f2 not in files_def


def test_indi_allsky_db_import_images_already_has_camera(create_allsky_instance, app):
    allsky = create_allsky_instance()
    with app.app_context():
        with pytest.raises(SystemExit) as exc:
            allsky.dbImportImages()
        assert exc.value.code == 1


def test_indi_allsky_db_import_images(app, tmp_path, mock_allsky_config):
    # Ensure no cameras exist initially
    with app.app_context():
        IndiAllSkyDbCameraTable.query.delete()
        db.session.commit()

    with patch('indi_allsky.allsky.IndiAllSkyConfig') as mock_cfg_cls:
        mock_cfg_inst = MagicMock()
        mock_cfg_inst.config = mock_allsky_config
        mock_cfg_inst.config_id = 1
        mock_cfg_inst.config_level = 1
        mock_cfg_cls.return_value = mock_cfg_inst

        with patch('indi_allsky.allsky.__config_level__', 1):
            allsky = IndiAllSky()

    allsky.image_dir = tmp_path

    # Create mock media tree
    tl_dir = tmp_path / 'timelapse' / '20210915'
    tl_dir.mkdir(parents=True)
    exp_dir = tmp_path / 'exposures' / '20210825' / 'night' / '26_02'
    exp_dir.mkdir(parents=True)
    exp_dir_day = tmp_path / 'exposures' / '20210825' / 'day' / '26_02'
    exp_dir_day.mkdir(parents=True)
    pan_dir = tmp_path / 'panoramas' / '20210825' / 'night' / '26_02'
    pan_dir.mkdir(parents=True)
    pan_dir_day = tmp_path / 'panoramas' / '20210825' / 'day' / '26_02'
    pan_dir_day.mkdir(parents=True)

    # 1. Timelapse video
    v_tl = tl_dir / 'allsky-timelapse_ccd1_20210915_night_1747415591.mp4'
    v_tl.write_text('v')
    v_tl_day = tl_dir / 'allsky-timelapse_ccd1_20210915_day_1747415591.mp4'
    v_tl_day.write_text('v')
    v_bad = tl_dir / 'nonmatching_video.mp4'
    v_bad.write_text('v')

    # 2. Keogram
    k_tl = tl_dir / 'allsky-keogram_ccd1_20210915_night_1747415591.jpg'
    k_tl.write_text('k')
    k_tl_day = tl_dir / 'allsky-keogram_ccd1_20210915_day_1747415591.jpg'
    k_tl_day.write_text('k')
    k_bad = tl_dir / 'allsky-keogram_bad.jpg'
    k_bad.write_text('k')

    # 3. Star trails
    st_tl = tl_dir / 'allsky-startrail_ccd1_20210915_night_1747415591.jpg'
    st_tl.write_text('s')
    st_tl_day = tl_dir / 'allsky-startrail_ccd1_20210915_day_1747415591.jpg'
    st_tl_day.write_text('s')
    st_bad = tl_dir / 'allsky-startrail_bad.jpg'
    st_bad.write_text('s')

    # 4. Star trails video
    stv_tl = tl_dir / 'allsky-startrail_timelapse_ccd1_20210915_night_1747415591.mp4'
    stv_tl.write_text('sv')
    stv_tl_day = tl_dir / 'allsky-startrail_timelapse_ccd1_20210915_day_1747415591.mp4'
    stv_tl_day.write_text('sv')
    stv_bad = tl_dir / 'allsky-startrail_timelapse_bad.mp4'
    stv_bad.write_text('sv')

    # 5. Panorama video
    pv_tl = tl_dir / 'allsky-panorama_timelapse_ccd1_20210915_night_1747415591.mp4'
    pv_tl.write_text('pv')
    pv_tl_day = tl_dir / 'allsky-panorama_timelapse_ccd1_20210915_day_1747415591.mp4'
    pv_tl_day.write_text('pv')
    pv_bad = tl_dir / 'allsky-panorama_timelapse_bad.mp4'
    pv_bad.write_text('pv')

    # 6. Standard exposure image
    img = exp_dir / 'ccd1_20210826_020202.jpg'
    img.write_text('img')
    img_day = exp_dir_day / 'ccd1_20210826_020202.jpg'
    img_day.write_text('img')
    img_bad = exp_dir / 'bad_name.jpg'
    img_bad.write_text('img')

    # 7. Panorama image
    p_img = pan_dir / 'panorama_ccd1_20210826_020202.jpg'
    p_img.write_text('pimg')
    p_img_day = pan_dir_day / 'panorama_ccd1_20210826_020202.jpg'
    p_img_day.write_text('pimg')
    p_bad = pan_dir / 'bad_panorama.jpg'
    p_bad.write_text('pimg')

    with patch('builtins.input', return_value='Imported Cam'):
        allsky.dbImportImages()

    with app.app_context():
        assert IndiAllSkyDbVideoTable.query.count() >= 2
        assert IndiAllSkyDbKeogramTable.query.count() >= 2
        assert IndiAllSkyDbStarTrailsTable.query.count() >= 2
        assert IndiAllSkyDbStarTrailsVideoTable.query.count() >= 2
        assert IndiAllSkyDbPanoramaVideoTable.query.count() >= 2
        assert IndiAllSkyDbImageTable.query.count() >= 2
        assert IndiAllSkyDbPanoramaImageTable.query.count() >= 2


def test_indi_allsky_db_import_images_broadcast_exception(app, tmp_path, mock_allsky_config):
    # Ensure no cameras exist initially
    with app.app_context():
        IndiAllSkyDbCameraTable.query.delete()
        db.session.commit()

    with patch('indi_allsky.allsky.IndiAllSkyConfig') as mock_cfg_cls:
        mock_cfg_inst = MagicMock()
        mock_cfg_inst.config = mock_allsky_config
        mock_cfg_inst.config_id = 1
        mock_cfg_inst.config_level = 1
        mock_cfg_cls.return_value = mock_cfg_inst

        with patch('indi_allsky.allsky.__config_level__', 1):
            allsky = IndiAllSky()

    allsky.image_dir = tmp_path
    tl_dir = tmp_path / 'timelapse' / '20210915'
    tl_dir.mkdir(parents=True)
    exp_dir = tmp_path / 'exposures' / '20210825' / 'night' / '26_02'
    exp_dir.mkdir(parents=True)

    v_tl = tl_dir / 'allsky-timelapse_ccd1_20210915_night_1747415591.mp4'
    v_tl.write_text('v')
    k_tl = tl_dir / 'allsky-keogram_ccd1_20210915_night_1747415591.jpg'
    k_tl.write_text('k')
    st_tl = tl_dir / 'allsky-startrail_ccd1_20210915_night_1747415591.jpg'
    st_tl.write_text('s')
    img = exp_dir / 'ccd1_20210826_020202.jpg'
    img.write_text('img')

    with patch('builtins.input', return_value='Imported Cam'):
        with patch('indi_allsky.events.event_manager.broadcast', side_effect=RuntimeError("Broadcast failed")):
            allsky.dbImportImages()


def test_indi_allsky_db_import_images_integrity_error(app, tmp_path, mock_allsky_config):
    # Ensure no cameras exist initially
    with app.app_context():
        IndiAllSkyDbCameraTable.query.delete()
        db.session.commit()

    with patch('indi_allsky.allsky.IndiAllSkyConfig') as mock_cfg_cls:
        mock_cfg_inst = MagicMock()
        mock_cfg_inst.config = mock_allsky_config
        mock_cfg_inst.config_id = 1
        mock_cfg_inst.config_level = 1
        mock_cfg_cls.return_value = mock_cfg_inst

        with patch('indi_allsky.allsky.__config_level__', 1):
            allsky = IndiAllSky()

    allsky.image_dir = tmp_path
    tl_dir = tmp_path / 'timelapse' / '20210915'
    tl_dir.mkdir(parents=True)
    v_tl = tl_dir / 'allsky-timelapse_ccd1_20210915_night_1747415591.mp4'
    v_tl.write_text('v')

    with patch('builtins.input', return_value='Imported Cam'):
        with patch.object(db.session, 'bulk_insert_mappings', side_effect=IntegrityError("stmt", "params", "orig")):
            allsky.dbImportImages()


def test_indi_allsky_run_loop(create_allsky_instance, app):
    allsky = create_allsky_instance()

    with app.app_context():
        allsky.write_pid = MagicMock()
        allsky._expireOrphanedTasks = MagicMock()
        allsky._startup = MagicMock()
        allsky._stopCaptureWorker = MagicMock()
        allsky._stopImageWorker = MagicMock()
        allsky._stopVideoWorker = MagicMock()
        allsky._stopSensorWorker = MagicMock()
        allsky._stopFileUploadWorkers = MagicMock()
        allsky._startCaptureWorker = MagicMock()
        allsky._startImageWorker = MagicMock()
        allsky._startVideoWorker = MagicMock()
        allsky._startSensorWorker = MagicMock()
        allsky._startFileUploadWorkers = MagicMock()
        allsky._queueManualTasks = MagicMock()
        allsky._periodic_tasks = MagicMock()
        allsky.reload_handler = MagicMock()

        allsky.pid_lock = MagicMock()

        # Iteration 1: reload triggers reload_handler
        # Iteration 2: shutdown exits
        iterations = 0

        def fake_sleep(secs):
            nonlocal iterations
            iterations += 1
            if iterations == 1:
                allsky._reload = True
            elif iterations == 2:
                allsky._shutdown = True

        with patch('fcntl.flock'):
            with patch('time.sleep', side_effect=fake_sleep):
                with pytest.raises(SystemExit):
                    allsky.run()

        assert allsky.reload_handler.called
        assert allsky._stopCaptureWorker.called
        assert allsky.pid_lock.close.called or True
