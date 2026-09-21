import io
import os
import queue
import signal
import tempfile
from datetime import datetime, timedelta, timezone
from multiprocessing import Array
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import ephem
import numpy as np
import pytest

from indi_allsky import constants
from indi_allsky.exceptions import TimelapseException, TimeOutException, BackupFailure
from indi_allsky.video import VideoWorker
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbFitsImageTable,
    IndiAllSkyDbRawImageTable,
    IndiAllSkyDbVideoTable,
    IndiAllSkyDbMiniVideoTable,
    IndiAllSkyDbKeogramTable,
    IndiAllSkyDbStarTrailsTable,
    IndiAllSkyDbStarTrailsVideoTable,
    IndiAllSkyDbPanoramaImageTable,
    IndiAllSkyDbPanoramaVideoTable,
    IndiAllSkyDbTaskQueueTable,
    TaskQueueQueue,
    TaskQueueState,
)
from indi_allsky.flask import db


@pytest.fixture
def more_worker(app, base_config, tmp_path):
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        if not cam:
            cam = IndiAllSkyDbCameraTable(
                name='ZWO ASI676MC',
                uuid='cam-more-coverage',
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
        else:
            cam.name = 'ZWO ASI676MC'
            cam.uuid = 'cam-more-coverage'
            db.session.commit()

        config = dict(base_config)
        config['LOCATION_LATITUDE'] = -34.9285
        config['LOCATION_LONGITUDE'] = 138.6007
        config['LOCATION_ELEVATION'] = 50
        config['IMAGE_DIR'] = str(tmp_path / 'images')
        config['IMAGE_FOLDER'] = str(tmp_path / 'images')
        config['VARLIB_FOLDER'] = str(tmp_path / 'varlib')
        config['FILETRANSFER'] = {
            'UPLOAD_IMAGE': False,
            'UPLOAD_ENDOFNIGHT': True,
            'REMOTE_ENDOFNIGHT_FOLDER': str(tmp_path / 'remote_eon'),
        }
        config['FFMPEG_CODEC'] = 'libx264'
        config['FFMPEG_FRAMERATE'] = 25
        config['IMAGE_FILE_TYPE'] = 'jpg'
        config['STARTRAILS_MAX_ADU'] = 60000
        config['STARTRAILS_MASK_THOLD'] = 100
        config['STARTRAILS_PIXEL_THOLD'] = 100
        config['STARTRAILS_SUN_ALT_THOLD'] = -6.0
        config['STARTRAILS_MOONMODE_THOLD'] = False
        config['STARTRAILS_MOON_ALT_THOLD'] = 0.0
        config['STARTRAILS_MOON_PHASE_THOLD'] = 0.5
        config['DAYTIME_CAPTURE'] = True

        Path(config['IMAGE_FOLDER']).mkdir(parents=True, exist_ok=True)
        Path(config['VARLIB_FOLDER']).mkdir(parents=True, exist_ok=True)

        error_q = queue.Queue()
        video_q = queue.Queue()
        upload_q = queue.Queue()
        night_av = Array('i', [-1, -1])
        binning_av = Array('i', [1, 2, -1, -1, -1, -1])

        worker = VideoWorker(
            idx=2,
            config=config,
            error_q=error_q,
            video_q=video_q,
            upload_q=upload_q,
            night_av=night_av,
            binning_av=binning_av,
        )

        return worker


# --------------------------------------------------------------------------
# 1. Calibration edge cases
# --------------------------------------------------------------------------

def test_load_asi676mc_calibration_database_missing_files_and_unsupported(more_worker, app, tmp_path):
    worker = more_worker
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        now = datetime.now()

        # 1. Non-existent file
        fits_non_existent = IndiAllSkyDbFitsImageTable(
            camera_id=cam.id,
            filename='does_not_exist.fits',
            dayDate=now.date(),
            createDate=now,
            exposure=1.0,
            gain=100.0,
            binmode=1,
            width=100,
            height=100,
            data={},
        )
        # 2. Unsupported fits path
        unsupported_file = tmp_path / 'unsupported.fits'
        unsupported_file.write_bytes(b'DUMMY' * 100)
        fits_unsupported = IndiAllSkyDbFitsImageTable(
            camera_id=cam.id,
            filename=str(unsupported_file),
            dayDate=now.date(),
            createDate=now,
            exposure=1.0,
            gain=100.0,
            binmode=1,
            width=100,
            height=100,
            data={},
        )
        db.session.add_all([fits_non_existent, fits_unsupported])
        db.session.commit()

        source_details = {
            'camera_id': cam.id,
            'camera_uuid': cam.uuid,
            'retention_cutoff': (now - timedelta(days=1)).strftime('%Y-%m-%d'),
        }

        with patch('indi_allsky.asi676mc_calibration.is_database_fits_path', return_value=False):
            res = worker._loadAsi676mcCalibrationDatabase(source_details, lambda p: None)

        assert res['source_details']['unsupported_count'] >= 1
        assert res['source_details']['missing_local_count'] >= 1


def test_asi676mc_calibration_worker_exceptions(more_worker, app):
    worker = more_worker
    worker._asi676mc_calibration_q = queue.Queue()

    with app.app_context():
        # Task ID 999999 does not exist -> tests NoResultFound
        worker._asi676mc_calibration_q.put((999999, 'sess-none'))

        # Running task that triggers an unexpected exception during _runAsi676mcCalibration
        task_fail = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=TaskQueueState.RUNNING,
            data={'action': 'generateAsi676mcCalibration', 'kwargs': {'session_id': 'sess-fail'}},
        )
        db.session.add(task_fail)
        db.session.commit()

        worker._asi676mc_calibration_q.put((task_fail.id, 'sess-fail'))
        worker._asi676mc_calibration_q.put(None)  # Sentinel

        with patch.object(worker, '_runAsi676mcCalibration', side_effect=Exception("Catastrophic error")):
            worker._asi676mcCalibrationWorker()


# --------------------------------------------------------------------------
# 2. generateVideo edge cases
# --------------------------------------------------------------------------

def test_generate_video_more_branches(more_worker, app, tmp_path):
    worker = more_worker
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        day_date = datetime(2026, 2, 1).date()

        # 1. Codec libvpx -> webm format
        worker.config['FFMPEG_CODEC'] = 'libvpx'
        worker.config['TIMELAPSE_OVERWRITE'] = True
        worker.config['TIMELAPSE'] = {'USE_NIGHT_CONFIG': False}

        # Existing keogram
        kg = IndiAllSkyDbKeogramTable(
            camera_id=cam.id,
            filename='keo.jpg',
            dayDate=day_date,
            night=True,
        )
        db.session.add(kg)

        # Image entries: 1 missing, 1 zero-byte, 1 valid
        f_zero = tmp_path / 'zero.jpg'
        f_zero.touch()
        f_valid = tmp_path / 'valid.jpg'
        f_valid.write_bytes(b'valid-data')

        for f in [tmp_path / 'missing.jpg', f_zero, f_valid]:
            img = IndiAllSkyDbImageTable(
                camera_id=cam.id,
                filename=str(f),
                dayDate=day_date,
                createDate=datetime(2026, 2, 1, 20, 0, 0),
                night=True,
                exclude=False,
                exposure=1.0,
                gain=100.0,
                adu=100.0,
            )
            db.session.add(img)
        db.session.commit()

        now = datetime(2026, 2, 1, 12, 0, 0)
        vid_folder = worker._getVideoFolder(day_date, cam)
        orphan = vid_folder / f'allsky-timelapse_ccd{cam.id}_20260201_night_{int(now.timestamp())}.webm'
        orphan.write_bytes(b'old')

        task = MagicMock()
        with patch('indi_allsky.video.datetime') as mock_datetime, \
             patch('indi_allsky.video.TimelapseGenerator') as mock_tg, \
             patch.object(worker._miscUpload, 'syncapi_video'), \
             patch.object(worker._miscUpload, 's3_upload_video'), \
             patch.object(worker._miscUpload, 'upload_video'), \
             patch.object(worker._miscUpload, 'youtube_upload_video'):
            mock_datetime.now.return_value = now
            mock_datetime.strptime = datetime.strptime
            mock_tg.return_value.generate.return_value = True
            worker.generateVideo(task, timespec='20260201', night=True, camera_id=cam.id)
            task.setSuccess.assert_called_once()
            assert not orphan.exists()


# --------------------------------------------------------------------------
# 3. generateMiniVideo edge cases
# --------------------------------------------------------------------------

def test_generate_mini_video_more_branches(more_worker, app, tmp_path):
    worker = more_worker
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        now = datetime.now()

        # Write valid images
        import cv2
        f1 = tmp_path / 'm1.jpg'
        f2 = tmp_path / 'm2.jpg'
        mat = np.zeros((100, 100, 3), dtype=np.uint8)
        cv2.imwrite(str(f1), mat)
        cv2.imwrite(str(f2), mat)

        img1 = IndiAllSkyDbImageTable(
            camera_id=cam.id,
            filename=str(f1),
            dayDate=now.date(),
            createDate=now,
            night=False,  # Daytime
            exclude=False,
            exposure=1.0,
            gain=100.0,
            adu=100.0,
        )
        img2 = IndiAllSkyDbImageTable(
            camera_id=cam.id,
            filename=str(f2),
            dayDate=now.date(),
            createDate=now + timedelta(seconds=1),
            night=False,
            exclude=False,
            exposure=1.0,
            gain=100.0,
            adu=100.0,
        )
        db.session.add_all([img1, img2])
        db.session.commit()

        # Day mini video with libvpx and bitrate override
        worker.config['FFMPEG_CODEC'] = 'libvpx'
        worker.config['TIMELAPSE'] = {'USE_NIGHT_CONFIG': False}
        worker.config['TIMELAPSE_OVERWRITE'] = True

        task = MagicMock()
        task.id = 111
        task.createDate = now

        mock_thumb = MagicMock()
        mock_thumb.fileSize = 100

        with patch('indi_allsky.video.TimelapseGenerator') as mock_tg, \
             patch.object(worker._miscDb, 'addThumbnail', return_value=mock_thumb), \
             patch.object(worker._miscUpload, 'syncapi_thumbnail'), \
             patch.object(worker._miscUpload, 's3_upload_thumbnail'), \
             patch.object(worker._miscUpload, 'syncapi_mini_video'), \
             patch.object(worker._miscUpload, 's3_upload_mini_video'), \
             patch.object(worker._miscUpload, 'upload_mini_video'), \
             patch.object(worker._miscUpload, 'youtube_upload_mini_video'):
            mock_tg.return_value.generate.return_value = True

            worker.generateMiniVideo(
                task,
                image_id=img1.id,
                camera_id=cam.id,
                pre_seconds=5,
                post_seconds=5,
                framerate=25,
                bitrate='2000k',
                note='day mini video',
            )
            task.setSuccess.assert_called_once()

        # Mini video TimelapseException
        task.reset_mock()
        with patch('indi_allsky.video.TimelapseGenerator') as mock_tg:
            mock_tg.return_value.generate.side_effect = TimelapseException("Fail")
            worker.generateMiniVideo(
                task,
                image_id=img1.id,
                camera_id=cam.id,
                pre_seconds=5,
                post_seconds=5,
                framerate=25,
                note='fail mini video',
            )
            assert 'Failed to generate mini timelapse' in task.setFailed.call_args[0][0]


def test_generate_mini_video_panorama_exceptions(more_worker, app, tmp_path):
    worker = more_worker
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        now = datetime.now()

        img_dir = Path(worker.image_dir)
        img_dir.mkdir(parents=True, exist_ok=True)
        p1_file = img_dir / 'p1.jpg'
        p2_file = img_dir / 'p2.jpg'
        p1_file.write_bytes(b'dummy_data_p1')
        p2_file.write_bytes(b'dummy_data_p2')

        p_img1 = IndiAllSkyDbPanoramaImageTable(
            camera_id=cam.id,
            filename=str(p1_file),
            dayDate=now.date(),
            createDate=now,
            night=True,
            exclude=False,
            exposure=1.0,
            gain=100.0,
            width=200,
            height=100,
        )
        p_img2 = IndiAllSkyDbPanoramaImageTable(
            camera_id=cam.id,
            filename=str(p2_file),
            dayDate=now.date(),
            createDate=now + timedelta(seconds=2),
            night=True,
            exclude=False,
            exposure=1.0,
            gain=100.0,
            width=200,
            height=100,
        )
        base = IndiAllSkyDbImageTable(
            camera_id=cam.id,
            filename=str(p1_file),
            dayDate=now.date(),
            createDate=now,
            night=True,
            exclude=False,
            exposure=1.0,
            gain=100.0,
            adu=100.0,
        )
        db.session.add_all([p_img1, p_img2, base])
        db.session.commit()

        task = MagicMock()
        task.id = 222
        task.createDate = now

        # 1. Unsupported pan mode
        worker.generateMiniVideo(
            task,
            image_id=base.id,
            panorama_image_id=p_img1.id,
            camera_id=cam.id,
            pre_seconds=10,
            post_seconds=10,
            framerate=25,
            note='invalid mode',
            crop_x=0,
            crop_y=0,
            crop_width=50,
            crop_height=50,
            pan_mode='circular',  # Unsupported
        )
        assert 'Unsupported panorama pan mode' in task.setFailed.call_args[0][0]

        # 2. Changing panorama dimensions mid sequence
        p_img2.width = 400
        db.session.commit()
        task.reset_mock()
        worker.generateMiniVideo(
            task,
            image_id=base.id,
            panorama_image_id=p_img1.id,
            camera_id=cam.id,
            pre_seconds=10,
            post_seconds=10,
            framerate=25,
            note='changed dimensions',
            crop_x=0,
            crop_y=0,
            crop_width=50,
            crop_height=50,
        )
        assert 'Panorama dimensions changed' in task.setFailed.call_args[0][0]


# --------------------------------------------------------------------------
# 4. generatePanoramaVideo edge cases
# --------------------------------------------------------------------------

def test_generate_panorama_video_day_and_libvpx(more_worker, app, tmp_path):
    worker = more_worker
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        day_date = datetime(2026, 2, 2).date()

        worker.config['FFMPEG_CODEC'] = 'libvpx'
        worker.config['TIMELAPSE'] = {'USE_NIGHT_CONFIG': False}
        worker.config['TIMELAPSE_OVERWRITE'] = True

        # Add 2 panorama images
        p1 = tmp_path / 'pv1.jpg'
        p2 = tmp_path / 'pv2.jpg'
        p1.write_bytes(b'abc')
        p2.write_bytes(b'def')

        e1 = IndiAllSkyDbPanoramaImageTable(
            camera_id=cam.id,
            filename=str(p1),
            dayDate=day_date,
            createDate=datetime(2026, 2, 2, 10, 0, 0),
            night=False,
            exclude=False,
            exposure=1.0,
            gain=100.0,
            width=200,
            height=100,
        )
        e2 = IndiAllSkyDbPanoramaImageTable(
            camera_id=cam.id,
            filename=str(p2),
            dayDate=day_date,
            createDate=datetime(2026, 2, 2, 10, 1, 0),
            night=False,
            exclude=False,
            exposure=1.0,
            gain=100.0,
            width=200,
            height=100,
        )
        db.session.add_all([e1, e2])
        db.session.commit()

        task = MagicMock()
        # TimelapseException in generatePanoramaVideo
        with patch('indi_allsky.video.TimelapseGenerator') as mock_tg:
            mock_tg.return_value.generate.side_effect = TimelapseException("Fail")
            worker.generatePanoramaVideo(task, timespec='20260202', night=False, camera_id=cam.id)
            assert 'Failed to generate timelapse' in task.setFailed.call_args[0][0]

        # Success in generatePanoramaVideo with overwrite of existing
        task.reset_mock()
        with patch('indi_allsky.video.TimelapseGenerator') as mock_tg, \
             patch.object(worker._miscUpload, 'syncapi_panorama_video'), \
             patch.object(worker._miscUpload, 's3_upload_panorama_video'), \
             patch.object(worker._miscUpload, 'upload_panorama_video'), \
             patch.object(worker._miscUpload, 'youtube_upload_panorama_video'):
            mock_tg.return_value.generate.return_value = True
            worker.generatePanoramaVideo(task, timespec='20260202', night=False, camera_id=cam.id)
            task.setSuccess.assert_called_once()


# --------------------------------------------------------------------------
# 5. generateKeogramStarTrails edge cases
# --------------------------------------------------------------------------

def test_generate_keogram_startrails_image_decode_exceptions(more_worker, app, tmp_path):
    worker = more_worker
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        day_date = datetime(2026, 2, 3).date()

        worker.config['TIMELAPSE_OVERWRITE'] = True
        worker.config['STARTRAILS_MOONMODE_THOLD'] = False
        worker.config['STARTRAILS_USE_DB_DATA'] = False

        # Files that trigger decode errors
        bad_jpg = tmp_path / 'bad.jpg'
        bad_jpg.write_bytes(b'not a valid jpeg')
        bad_png = tmp_path / 'bad.png'
        bad_png.write_bytes(b'not a valid png')
        bad_other = tmp_path / 'bad.bmp'
        bad_other.write_bytes(b'not a valid bmp')

        for f in [bad_jpg, bad_png, bad_other]:
            img = IndiAllSkyDbImageTable(
                camera_id=cam.id,
                filename=str(f),
                dayDate=day_date,
                createDate=datetime(2026, 2, 3, 22, 0, 0),
                night=True,
                exclude=False,
                exposure=1.0,
                gain=100.0,
                adu=100.0,
            )
            db.session.add(img)
        db.session.commit()

        task = MagicMock()
        mock_thumb = MagicMock()
        mock_thumb.fileSize = 100

        with patch('indi_allsky.video.KeogramGenerator') as mock_kg_cls, \
             patch('indi_allsky.video.StarTrailGenerator') as mock_stg_cls, \
             patch.object(worker._miscDb, 'addThumbnail', return_value=mock_thumb), \
             patch.object(worker._miscUpload, 'syncapi_thumbnail'), \
             patch.object(worker._miscUpload, 's3_upload_thumbnail'), \
             patch.object(worker._miscUpload, 'syncapi_keogram'), \
             patch.object(worker._miscUpload, 's3_upload_keogram'), \
             patch.object(worker._miscUpload, 'upload_keogram'), \
             patch.object(worker._miscUpload, 'syncapi_startrail'), \
             patch.object(worker._miscUpload, 's3_upload_startrail'), \
             patch.object(worker._miscUpload, 'upload_startrail'):

            mock_kg = mock_kg_cls.return_value
            mock_kg.shape = (50, 100, 3)

            mock_stg = mock_stg_cls.return_value
            mock_stg.shape = (50, 50, 3)
            mock_stg.trail_count = 0
            mock_stg.timelapse_frame_count = 10  # < 250 -> star trail video skipped

            worker.generateKeogramStarTrails(task, timespec='20260203', night=True, camera_id=cam.id)
            task.setSuccess.assert_called_once()


# --------------------------------------------------------------------------
# 6. System health check & Backup & Map ping & Folder helpers
# --------------------------------------------------------------------------

def test_system_health_check_branches(more_worker, app):
    worker = more_worker
    with app.app_context():
        task = MagicMock()

        mock_p1 = MagicMock(mountpoint='/boot')
        mock_p2 = MagicMock(mountpoint='/var')

        mock_disk_usage = MagicMock(percent=95.0)  # > 90%
        mock_swap = MagicMock(percent=95.0)        # > 90%

        with patch('psutil.disk_partitions', return_value=[mock_p1, mock_p2]), \
             patch('psutil.disk_usage', side_effect=[PermissionError("Denied"), mock_disk_usage]), \
             patch('psutil.swap_memory', return_value=mock_swap), \
             patch.object(worker._miscDb, 'addNotification') as mock_add_notif:
            worker.systemHealthCheck(task)
            task.setSuccess.assert_called_with('Health check complete')
            assert mock_add_notif.called


def test_backup_database_branches(more_worker, app):
    worker = more_worker
    with app.app_context():
        task = MagicMock()

        # 1. Non sqlite dialect
        with patch.object(db.engine.dialect, 'name', 'postgresql'):
            worker.backupDatabase(task)
            task.setFailed.assert_called_with('Only sqlite backups are supported')

        # 2. BackupFailure exception
        task.reset_mock()
        with patch('indi_allsky.video.IndiAllskyDatabaseBackup') as mock_backup_cls:
            mock_backup_cls.return_value.db_backup.side_effect = BackupFailure("Compression failed")
            worker.backupDatabase(task)
            assert 'Backup failed failed' in task.setFailed.call_args[0][0]


def test_send_allsky_map_ping_failure(more_worker, app):
    worker = more_worker
    with app.app_context():
        task = MagicMock()
        with patch('indi_allsky.allsky_map.send_allsky_map_ping', return_value=(False, 'Unauthorized')):
            worker.sendAllskyMapPing(task)
            task.setFailed.assert_called_with('Allsky Map Ping failed: Unauthorized')


def test_get_folder_files_by_ext_default(more_worker, tmp_path):
    worker = more_worker
    worker.config['IMAGE_FILE_TYPE'] = 'png'
    f_png = tmp_path / 'default_test.png'
    f_png.touch()

    file_list = []
    worker._getFolderFilesByExt(str(tmp_path), file_list)
    assert f_png in file_list


def test_task_routing_helpers(more_worker, app):
    worker = more_worker
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        task = MagicMock()

        # 1. updateAuroraData
        with patch('indi_allsky.video.IndiAllskyAuroraUpdate') as mock_aurora:
            worker.updateAuroraData(task, camera_id=cam.id)
            task.setRunning.assert_called_once()
            task.setSuccess.assert_called_with('Aurora data updated')
            mock_aurora.return_value.update.assert_called_once_with(cam)

        # 2. updateSmokeData
        task.reset_mock()
        with patch('indi_allsky.video.IndiAllskySmokeUpdate') as mock_smoke:
            worker.updateSmokeData(task, camera_id=cam.id)
            task.setRunning.assert_called_once()
            task.setSuccess.assert_called_with('Smoke data updated')
            mock_smoke.return_value.update.assert_called_once_with(cam)

        # 3. updateSatelliteTleData
        task.reset_mock()
        with patch('indi_allsky.video.IndiAllskyUpdateSatelliteData') as mock_sat:
            worker.updateSatelliteTleData(task)
            task.setRunning.assert_called_once()
            task.setSuccess.assert_called_with('Satellite data updated')
            mock_sat.return_value.update.assert_called_once()

        # 4. backupDatabase success
        task.reset_mock()
        with patch.object(db.engine.dialect, 'name', 'sqlite'), \
             patch('indi_allsky.video.IndiAllskyDatabaseBackup') as mock_backup, \
             patch.object(worker._miscUpload, 'upload_db_backup') as mock_upload_db:
            mock_backup.return_value.db_backup.return_value = '/tmp/backup.tar.gz'
            worker.backupDatabase(task)
            task.setSuccess.assert_called_with('Backup complete')
            mock_upload_db.assert_called_once_with('/tmp/backup.tar.gz')

        # 5. sendAllskyMapPing success
        task.reset_mock()
        with patch('indi_allsky.allsky_map.send_allsky_map_ping', return_value=(True, 'Success')):
            worker.sendAllskyMapPing(task)
            task.setSuccess.assert_called_with('Allsky Map Ping successful: Success')


def test_generate_keogram_startrails_overwrite_false(more_worker, app, tmp_path):
    worker = more_worker
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        task = MagicMock()
        day_date = datetime.strptime('20260205', '%Y%m%d').date()

        # Add existing startrail entry
        from indi_allsky.flask.models import IndiAllSkyDbStarTrailsTable, IndiAllSkyDbStarTrailsVideoTable
        st = IndiAllSkyDbStarTrailsTable(
            camera_id=cam.id,
            filename='st.jpg',
            dayDate=day_date,
            night=True,
        )
        db.session.add(st)
        db.session.commit()

        worker.config['TIMELAPSE_OVERWRITE'] = False
        worker.generateKeogramStarTrails(task, timespec='20260205', night=True, camera_id=cam.id)
        task.setFailed.assert_called_with('Star trail already exists, overwrite not permitted')

        # Allow startrail overwrite, but test existing video entry
        db.session.delete(st)
        st_vid = IndiAllSkyDbStarTrailsVideoTable(
            camera_id=cam.id,
            filename='st_vid.webm',
            dayDate=day_date,
            night=True,
        )
        db.session.add(st_vid)
        db.session.commit()

        task.reset_mock()
        worker.config['TIMELAPSE_OVERWRITE'] = False
        worker.generateKeogramStarTrails(task, timespec='20260205', night=True, camera_id=cam.id)
        task.setFailed.assert_called_with('Star trail timelapse already exists, overwrite not permitted')


def test_generate_keogram_startrails_overwrite_true_and_orphans(more_worker, app, tmp_path):
    worker = more_worker
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        task = MagicMock()
        day_date = datetime.strptime('20260206', '%Y%m%d').date()
        now = datetime(2026, 2, 6, 12, 0, 0)

        from indi_allsky.flask.models import (
            IndiAllSkyDbKeogramTable,
            IndiAllSkyDbStarTrailsTable,
            IndiAllSkyDbStarTrailsVideoTable,
        )

        kg = IndiAllSkyDbKeogramTable(camera_id=cam.id, filename='kg.jpg', dayDate=day_date, night=True)
        st = IndiAllSkyDbStarTrailsTable(camera_id=cam.id, filename='st.jpg', dayDate=day_date, night=True)
        st_vid = IndiAllSkyDbStarTrailsVideoTable(camera_id=cam.id, filename='st_vid.webm', dayDate=day_date, night=True)
        db.session.add_all([kg, st, st_vid])
        db.session.commit()

        worker.config['TIMELAPSE_OVERWRITE'] = True
        vid_folder = worker._getVideoFolder(day_date, cam)
        vid_folder.mkdir(parents=True, exist_ok=True)

        k_file = vid_folder / f'allsky-keogram_ccd{cam.id}_20260206_night_{int(now.timestamp())}.jpg'
        s_file = vid_folder / f'allsky-startrail_ccd{cam.id}_20260206_night_{int(now.timestamp())}.jpg'
        sv_file = vid_folder / f'allsky-startrail_timelapse_ccd{cam.id}_20260206_night_{int(now.timestamp())}.mp4'
        k_file.touch()
        s_file.touch()
        sv_file.touch()

        mock_thumb = MagicMock()
        mock_thumb.fileSize = 123

        with patch('indi_allsky.video.datetime') as mock_datetime, \
             patch('indi_allsky.video.KeogramGenerator') as mock_kg_cls, \
             patch('indi_allsky.video.StarTrailGenerator') as mock_stg_cls, \
             patch.object(kg, 'deleteAsset'), \
             patch.object(st, 'deleteAsset'), \
             patch.object(st_vid, 'deleteAsset'), \
             patch.object(worker._miscDb, 'addThumbnail', return_value=mock_thumb), \
             patch.object(worker._miscUpload, 'syncapi_thumbnail'), \
             patch.object(worker._miscUpload, 's3_upload_thumbnail'), \
             patch.object(worker._miscUpload, 'syncapi_keogram'), \
             patch.object(worker._miscUpload, 's3_upload_keogram'), \
             patch.object(worker._miscUpload, 'upload_keogram'), \
             patch.object(worker._miscUpload, 'syncapi_startrail'), \
             patch.object(worker._miscUpload, 's3_upload_startrail'), \
             patch.object(worker._miscUpload, 'upload_startrail'):
            mock_datetime.now.return_value = now
            mock_datetime.strptime = datetime.strptime

            mock_kg = mock_kg_cls.return_value
            mock_kg.shape = (50, 100, 3)

            mock_stg = mock_stg_cls.return_value
            mock_stg.shape = (50, 50, 3)
            mock_stg.trail_count = 0
            mock_stg.timelapse_frame_count = 0

            worker.generateKeogramStarTrails(task, timespec='20260206', night=True, camera_id=cam.id)
            task.setSuccess.assert_called_once()
            assert not k_file.exists()
            assert not s_file.exists()
            assert not sv_file.exists()


def test_update_satellite_data_failed(more_worker, app):
    """Cover line 2412: task.setFailed in updateSatelliteTleData when satellite.update() returns False."""
    worker = more_worker
    with app.app_context():
        task = MagicMock()
        with patch('indi_allsky.video.IndiAllskyUpdateSatelliteData') as mock_sat_cls:
            mock_sat_cls.return_value.update.return_value = False
            worker.updateSatelliteTleData(task)
            task.setFailed.assert_called_with('Satellite data update deferred or failed')




