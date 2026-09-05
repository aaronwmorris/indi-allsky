import signal
from datetime import datetime, timedelta
from multiprocessing import Queue, Array
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky import constants
from indi_allsky.video import VideoWorker
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbTaskQueueTable,
    TaskQueueQueue,
    TaskQueueState,
)
from indi_allsky.flask import db


@pytest.fixture
def video_worker_fixture(app, base_config, tmp_path):
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        if not cam:
            cam = IndiAllSkyDbCameraTable(
                name='VideoWorker Cam',
                uuid='cam-video-1',
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
        config['IMAGE_DIR'] = str(tmp_path / 'images')
        config['VARLIB_FOLDER'] = str(tmp_path / 'varlib')
        config['FILETRANSFER'] = {'UPLOAD_IMAGE': False}
        Path(config['IMAGE_DIR']).mkdir(parents=True, exist_ok=True)
        Path(config['VARLIB_FOLDER']).mkdir(parents=True, exist_ok=True)

        error_q = Queue()
        video_q = Queue()
        upload_q = Queue()

        night_av = Array('i', [-1, -1])
        binning_av = Array('i', [-1] * 6)

        worker = VideoWorker(
            idx=0,
            config=config,
            error_q=error_q,
            video_q=video_q,
            upload_q=upload_q,
            night_av=night_av,
            binning_av=binning_av,
        )

        return worker


def test_video_worker_init(video_worker_fixture):
    worker = video_worker_fixture
    assert worker.name == 'Video-0'
    assert worker.thumbnail_keogram_width == 1000
    assert worker._shutdown is False

    # Test signal handlers
    worker.sighup_handler_worker(signal.SIGHUP, None)
    assert worker._shutdown is True

    worker._shutdown = False
    worker.sigterm_handler_worker(signal.SIGTERM, None)
    assert worker._shutdown is True


def test_video_worker_process_task_missing(video_worker_fixture, app):
    worker = video_worker_fixture
    with app.app_context():
        # Missing task should log and return cleanly without uncaught exception
        worker.processTask({'task_id': 999999})


def test_video_worker_get_folder_files_by_ext(video_worker_fixture, tmp_path):
    worker = video_worker_fixture

    f1 = tmp_path / "img1.jpg"
    f2 = tmp_path / "img2.png"
    f3 = tmp_path / "video.mp4"
    f1.touch()
    f2.touch()
    f3.touch()

    file_list = []
    worker._getFolderFilesByExt(str(tmp_path), file_list, extension_list=['jpg', 'png'])
    filenames = [Path(f).name for f in file_list]
    assert 'img1.jpg' in filenames
    assert 'img2.png' in filenames
    assert 'video.mp4' not in filenames


def test_video_worker_system_health_check(video_worker_fixture, app):
    worker = video_worker_fixture
    with app.app_context():
        mock_task = MagicMock()
        worker.systemHealthCheck(mock_task)
        mock_task.setRunning.assert_called_once()
        mock_task.setSuccess.assert_called_once_with('Health check complete')


def test_video_worker_update_aurora_data(video_worker_fixture, app):
    worker = video_worker_fixture
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        mock_task = MagicMock()

        with patch('indi_allsky.video.IndiAllskyAuroraUpdate') as mock_aurora:
            worker.updateAuroraData(mock_task, camera_id=cam.id)
            mock_task.setRunning.assert_called_once()
            mock_task.setSuccess.assert_called_once_with('Aurora data updated')


def test_video_worker_update_smoke_data(video_worker_fixture, app):
    worker = video_worker_fixture
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        mock_task = MagicMock()

        with patch('indi_allsky.video.IndiAllskySmokeUpdate') as mock_smoke:
            worker.updateSmokeData(mock_task, camera_id=cam.id)
            mock_task.setRunning.assert_called_once()
            mock_task.setSuccess.assert_called_once_with('Smoke data updated')


def test_video_worker_update_satellite_tle_data(video_worker_fixture, app):
    worker = video_worker_fixture
    with app.app_context():
        mock_task = MagicMock()

        with patch('indi_allsky.video.IndiAllskyUpdateSatelliteData') as mock_sat:
            worker.updateSatelliteTleData(mock_task)
            mock_task.setRunning.assert_called_once()
            mock_task.setSuccess.assert_called_once_with('Satellite data updated')


def test_video_worker_backup_database(video_worker_fixture, app):
    worker = video_worker_fixture
    with app.app_context():
        mock_task = MagicMock()

        with patch('indi_allsky.video.IndiAllskyDatabaseBackup') as mock_backup:
            mock_backup.return_value.db_backup.return_value = '/tmp/fake_backup.tar.gz'
            worker.backupDatabase(mock_task)
            mock_task.setRunning.assert_called_once()
            mock_task.setSuccess.assert_called_once_with('Backup complete')


def test_video_worker_send_allsky_map_ping(video_worker_fixture, app):
    worker = video_worker_fixture
    with app.app_context():
        mock_task = MagicMock()

        with patch('indi_allsky.allsky_map.send_allsky_map_ping', return_value=(True, 'OK')):
            worker.sendAllskyMapPing(mock_task)
            mock_task.setRunning.assert_called_once()


def test_video_worker_expire_data(video_worker_fixture, app):
    worker = video_worker_fixture
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        mock_task = MagicMock()

        # Add old image to prune
        old_date = datetime.now() - timedelta(days=30)
        old_img = IndiAllSkyDbImageTable(
            camera_id=cam.id,
            filename='old.jpg',
            dayDate=old_date.date(),
            createDate=old_date,
            exposure=1.0,
            gain=100.0,
            adu=128.0,
            sqm=21.0,
            stars=10,
        )
        db.session.add(old_img)
        db.session.commit()

        worker.expireData(mock_task, camera_id=cam.id)
        mock_task.setRunning.assert_called_once()
