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
from indi_allsky.exceptions import TimelapseException, TimeOutException, KeogramMismatchException
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
def test_worker(app, base_config, tmp_path):
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        if not cam:
            cam = IndiAllSkyDbCameraTable(
                name='ZWO ASI676MC',
                uuid='cam-video-coverage',
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
            cam.uuid = 'cam-video-coverage'
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
            idx=1,
            config=config,
            error_q=error_q,
            video_q=video_q,
            upload_q=upload_q,
            night_av=night_av,
            binning_av=binning_av,
        )

        return worker


# --------------------------------------------------------------------------
# 1. Signals, Run, SafeRun, ProcessTask
# --------------------------------------------------------------------------

def test_worker_signals_and_run(test_worker):
    worker = test_worker

    worker.sigint_handler_worker(signal.SIGINT, None)
    assert worker._shutdown is True

    with pytest.raises(TimeOutException):
        worker.sigalarm_handler_worker(signal.SIGALRM, None)

    with patch('threading.Thread') as mock_thread, \
         patch('signal.signal') as mock_signal, \
         patch.object(worker, 'saferun') as mock_saferun:
        worker.run()
        mock_saferun.assert_called_once()
        mock_thread.assert_called_once()

    # Exception in saferun
    with patch('threading.Thread'), \
         patch('signal.signal'), \
         patch.object(worker, 'saferun', side_effect=ValueError("Boom")):
        with pytest.raises(ValueError):
            worker.run()
        err, tb = worker.error_q.get_nowait()
        assert "Boom" in err


def test_worker_saferun_loop(test_worker, app):
    worker = test_worker

    # Stop command
    worker.video_q.put({'stop': True})
    worker.saferun()

    # Shutdown flag
    worker._shutdown = True
    worker.video_q.put({'something': 1})
    worker.saferun()
    worker._shutdown = False

    # Process task inside saferun
    with app.app_context(), \
         patch.object(worker, 'processTask') as mock_process, \
         patch.object(worker.video_q, 'get', side_effect=[{'task_id': 123}, {'stop': True}]):
        worker.saferun()
        mock_process.assert_called_once_with({'task_id': 123})


def test_worker_process_task_unknown_action(test_worker, app):
    worker = test_worker
    with app.app_context():
        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=TaskQueueState.QUEUED,
            data={'action': 'non_existent_action_xyz', 'kwargs': {}},
        )
        db.session.add(task)
        db.session.commit()

        worker.processTask({'task_id': task.id})
        db.session.refresh(task)
        assert task.state == TaskQueueState.RUNNING


# --------------------------------------------------------------------------
# 2. ASI676MC Calibration
# --------------------------------------------------------------------------

def test_load_asi676mc_calibration_database_camera_checks(test_worker, app):
    worker = test_worker
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()

        # Camera mismatch
        with pytest.raises(RuntimeError, match='has changed'):
            worker._loadAsi676mcCalibrationDatabase({'camera_id': cam.id, 'camera_uuid': 'wrong-uuid'}, lambda x: None)

        # Camera name mismatch
        orig_name = cam.name
        cam.name = 'Generic Webcam'
        db.session.commit()
        try:
            with pytest.raises(RuntimeError, match='no longer an ASI676MC'):
                worker._loadAsi676mcCalibrationDatabase({'camera_id': cam.id, 'camera_uuid': cam.uuid}, lambda x: None)
        finally:
            cam.name = orig_name
            db.session.commit()


def test_load_asi676mc_calibration_database_success(test_worker, app, tmp_path):
    worker = test_worker
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()

        # Create dummy fits file
        fits_file = tmp_path / 'test_capture.fits'
        fits_file.write_bytes(b'SIMPLE  =                    T' + b' ' * 2854)

        now = datetime.now()
        fits_entry = IndiAllSkyDbFitsImageTable(
            camera_id=cam.id,
            filename=str(fits_file),
            dayDate=now.date(),
            createDate=now,
            exposure=1.0,
            gain=100.0,
            binmode=1,
            width=100,
            height=100,
            data={'signature': {'r': 1.0}, 'diagnostic': {'roles': [{'role': 'primary'}]}},
        )
        db.session.add(fits_entry)

        # Add a bad image with 'repaired'
        bad_img = IndiAllSkyDbImageTable(
            camera_id=cam.id,
            filename='bad.jpg',
            dayDate=now.date(),
            createDate=now,
            exposure=1.0,
            gain=100.0,
            adu=128.0,
            sqm=21.0,
            stars=10,
            data={'asi676mc_repair_status': 'repaired'},
        )
        db.session.add(bad_img)
        db.session.commit()

        source_details = {
            'camera_id': cam.id,
            'camera_uuid': cam.uuid,
            'retention_cutoff': (now - timedelta(days=1)).strftime('%Y-%m-%d'),
        }

        callback_calls = []
        with patch('indi_allsky.asi676mc_calibration.is_database_fits_path', return_value=True):
            res = worker._loadAsi676mcCalibrationDatabase(source_details, lambda p: callback_calls.append(p))

        assert len(res['fits_records']) >= 1
        assert len(res['bad_frames']) >= 1


def test_save_asi676mc_calibration_signatures(test_worker, app):
    worker = test_worker
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        fits_entry = IndiAllSkyDbFitsImageTable(
            camera_id=cam.id,
            filename='dummy.fits',
            dayDate=datetime.now().date(),
            createDate=datetime.now(),
            exposure=1.0,
            gain=100.0,
            binmode=1,
            width=100,
            height=100,
            data={},
        )
        db.session.add(fits_entry)
        db.session.commit()

        source_details = {'camera_id': cam.id}
        signature_updates = {fits_entry.id: {'purple': 1.8}}
        worker._saveAsi676mcCalibrationSignatures(source_details, signature_updates)

        db.session.refresh(fits_entry)
        assert fits_entry.data['asi676mc_signature'] == {'purple': 1.8}


def test_asi676mc_calibration_worker_and_run(test_worker, app):
    worker = test_worker
    worker._asi676mc_calibration_q = queue.Queue()

    with app.app_context():
        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=TaskQueueState.RUNNING,
            data={'action': 'generateAsi676mcCalibration', 'kwargs': {'session_id': 'sess-1'}},
        )
        db.session.add(task)
        db.session.commit()

        # Queue calibration
        worker.generateAsi676mcCalibration(task, session_id='sess-1')
        # Clear queue for isolated sub-tests
        while not worker._asi676mc_calibration_q.empty():
            worker._asi676mc_calibration_q.get()

        # Test _runAsi676mcCalibration outcomes
        # 1. Exception
        with patch('indi_allsky.asi676mc_calibration.run_calibration_session', side_effect=RuntimeError("Calib failed")):
            worker._runAsi676mcCalibration(task, 'sess-1')
            assert task.state == TaskQueueState.FAILED

        # 2. None result (cancellation)
        with patch('indi_allsky.asi676mc_calibration.run_calibration_session', return_value=None):
            worker._runAsi676mcCalibration(task, 'sess-1')
            assert task.state == TaskQueueState.EXPIRED

        # 3. Suggestion outcome
        res_sugg = {
            'outcome': 'threshold_suggestion',
            'quality': {'likely_purple_count': 5, 'likely_normal_count': 10},
        }
        with patch('indi_allsky.asi676mc_calibration.run_calibration_session', return_value=res_sugg):
            worker._runAsi676mcCalibration(task, 'sess-1')
            assert task.state == TaskQueueState.SUCCESS

        # 4. Standard outcome
        res_std = {
            'outcome': 'passed',
            'quality': {'matched_bad_count': 4, 'matched_normal_count': 8},
        }
        with patch('indi_allsky.asi676mc_calibration.run_calibration_session', return_value=res_std):
            worker._runAsi676mcCalibration(task, 'sess-1')
            assert task.state == TaskQueueState.SUCCESS

        # Test _asi676mcCalibrationWorker processing
        task_worker = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=TaskQueueState.RUNNING,
            data={'action': 'generateAsi676mcCalibration', 'kwargs': {'session_id': 'sess-worker'}},
        )
        db.session.add(task_worker)
        db.session.commit()

        worker._asi676mc_calibration_q.put((task_worker.id, 'sess-worker'))
        worker._asi676mc_calibration_q.put(None)  # Sentinel to stop

        with patch.object(worker, '_runAsi676mcCalibration') as mock_run_calib:
            worker._asi676mcCalibrationWorker()
            assert mock_run_calib.call_count == 1
            call_task, call_sess = mock_run_calib.call_args[0]
            assert call_task.id == task_worker.id
            assert call_sess == 'sess-worker'


# --------------------------------------------------------------------------
# 3. generateVideo
# --------------------------------------------------------------------------

def test_generate_video_validation(test_worker, app):
    worker = test_worker
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        task = MagicMock()

        # Invalid timespec
        worker.generateVideo(task, timespec='invalid', night=True, camera_id=cam.id)
        task.setFailed.assert_called_with('Invalid time spec')

        # Invalid codec
        task.reset_mock()
        worker.config['FFMPEG_CODEC'] = 'invalid_codec'
        worker.generateVideo(task, timespec='20260101', night=True, camera_id=cam.id)
        task.setFailed.assert_called_with('Invalid codec in config, timelapse generation failed')
        worker.config['FFMPEG_CODEC'] = 'libx264'


def test_generate_video_existing_entry_overwrite(test_worker, app, tmp_path):
    worker = test_worker
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        day_date = datetime(2026, 1, 1).date()

        # Add existing video
        old_vid = IndiAllSkyDbVideoTable(
            camera_id=cam.id,
            filename='old_video.mp4',
            dayDate=day_date,
            night=True,
        )
        db.session.add(old_vid)
        db.session.commit()

        task = MagicMock()
        # Overwrite disabled
        worker.config['TIMELAPSE_OVERWRITE'] = False
        worker.generateVideo(task, timespec='20260101', night=True, camera_id=cam.id)
        task.setFailed.assert_called_with('Timelapse already exists, overwrite not permitted')

        # Overwrite enabled
        worker.config['TIMELAPSE_OVERWRITE'] = True
        task.reset_mock()
        with patch('indi_allsky.video.TimelapseGenerator') as mock_tg:
            mock_tg.return_value.generate.return_value = True
            worker.generateVideo(task, timespec='20260101', night=True, camera_id=cam.id)
            task.setSuccess.assert_called_once()


def test_generate_video_success_and_timelapse_exception(test_worker, app, tmp_path):
    worker = test_worker
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        day_date = datetime(2026, 1, 2).date()

        # Add some images
        img_p = Path(worker.image_dir) / 'test.jpg'
        img_p.parent.mkdir(parents=True, exist_ok=True)
        img_p.write_bytes(b'fake image data')

        img = IndiAllSkyDbImageTable(
            camera_id=cam.id,
            filename=str(img_p),
            dayDate=day_date,
            createDate=datetime(2026, 1, 2, 12, 0, 0),
            night=False,
            exclude=False,
            exposure=1.0,
            gain=100.0,
            adu=100.0,
            stars=20,
            kpindex=2.0,
            ovation_max=10,
            smoke_rating=1,
            moonphase=0.2,
            sqm=20.5,
        )
        db.session.add(img)
        db.session.commit()

        task = MagicMock()
        worker.config['TIMELAPSE'] = {'USE_NIGHT_CONFIG': False}
        worker.config['TIMELAPSE_OVERWRITE'] = True

        # TimelapseException failure
        with patch('indi_allsky.video.TimelapseGenerator') as mock_tg:
            mock_tg.return_value.generate.side_effect = TimelapseException("Encoding error")
            worker.generateVideo(task, timespec='20260102', night=False, camera_id=cam.id)
            assert "Failed to generate timelapse" in task.setFailed.call_args[0][0]

        # Success path
        task.reset_mock()
        with patch('indi_allsky.video.TimelapseGenerator') as mock_tg, \
             patch.object(worker._miscUpload, 'syncapi_video') as mock_sync, \
             patch.object(worker._miscUpload, 's3_upload_video') as mock_s3, \
             patch.object(worker._miscUpload, 'upload_video') as mock_up, \
             patch.object(worker._miscUpload, 'youtube_upload_video') as mock_yt:
            mock_tg.return_value.generate.return_value = True
            worker.generateVideo(task, timespec='20260102', night=False, camera_id=cam.id)
            task.setSuccess.assert_called_once()
            mock_sync.assert_called_once()
            mock_s3.assert_called_once()
            mock_up.assert_called_once()
            mock_yt.assert_called_once()


# --------------------------------------------------------------------------
# 4. generateMiniVideo & generatePanoramaMiniVideo
# --------------------------------------------------------------------------

def test_generate_mini_video_validation_and_errors(test_worker, app, tmp_path):
    worker = test_worker
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        now = datetime.now()

        img_p = Path(worker.image_dir) / 'mv.jpg'
        img_p.write_bytes(b'mini video frame')

        img = IndiAllSkyDbImageTable(
            camera_id=cam.id,
            filename=str(img_p),
            dayDate=now.date(),
            createDate=now,
            night=True,
            exclude=False,
            exposure=1.0,
            gain=100.0,
            adu=100.0,
        )
        db.session.add(img)
        db.session.commit()

        task = MagicMock()

        # Invalid codec
        worker.config['FFMPEG_CODEC'] = 'bad_codec'
        worker.generateMiniVideo(
            task,
            image_id=img.id,
            camera_id=cam.id,
            pre_seconds=10,
            post_seconds=10,
            framerate=25,
            note='test',
        )
        task.setFailed.assert_called_with('Invalid codec in config, timelapse generation failed')
        worker.config['FFMPEG_CODEC'] = 'libx264'

        # Not enough images (only 1)
        task.reset_mock()
        worker.generateMiniVideo(
            task,
            image_id=img.id,
            camera_id=cam.id,
            pre_seconds=10,
            post_seconds=10,
            framerate=25,
            note='test',
        )
        assert 'Not enough all-sky images were found' in task.setFailed.call_args[0][0]


def test_generate_mini_video_panorama_flow(test_worker, app, tmp_path):
    worker = test_worker
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        now = datetime.now()

        # Add panorama images
        pano_files = []
        pano_entries = []
        for i in range(3):
            p_file = Path(worker.image_dir) / f'pano_{i}.jpg'
            # Write a small valid image via OpenCV
            test_mat = np.zeros((100, 200, 3), dtype=np.uint8)
            import cv2
            cv2.imwrite(str(p_file), test_mat)
            pano_files.append(p_file)

            p_entry = IndiAllSkyDbPanoramaImageTable(
                camera_id=cam.id,
                filename=str(p_file),
                dayDate=now.date(),
                createDate=now + timedelta(seconds=i * 5),
                night=True,
                exclude=False,
                exposure=1.0,
                gain=100.0,
                width=200,
                height=100,
            )
            db.session.add(p_entry)
            pano_entries.append(p_entry)

        # Standard image entry for target
        base_img = IndiAllSkyDbImageTable(
            camera_id=cam.id,
            filename=str(pano_files[0]),
            dayDate=now.date(),
            createDate=now,
            night=True,
            exclude=False,
            exposure=1.0,
            gain=100.0,
            adu=100.0,
        )
        db.session.add(base_img)
        db.session.commit()

        task = MagicMock()
        task.id = 999
        task.createDate = now

        # Invalid panorama crop
        worker.generateMiniVideo(
            task,
            image_id=base_img.id,
            panorama_image_id=pano_entries[0].id,
            camera_id=cam.id,
            pre_seconds=60,
            post_seconds=60,
            framerate=25,
            note='test pano',
            crop_x=-5,  # Invalid
            crop_y=0,
            crop_width=50,
            crop_height=50,
        )
        assert 'Invalid panorama crop' in task.setFailed.call_args[0][0]

        # Valid panorama mini video linear pan
        task.reset_mock()
        worker.config['FFMPEG_CODEC'] = 'h264_qsv'  # Test QSV fallback branch
        with patch('indi_allsky.video.TimelapseGenerator') as mock_tg, \
             patch.object(worker._miscUpload, 'syncapi_mini_video'), \
             patch.object(worker._miscUpload, 's3_upload_mini_video'), \
             patch.object(worker._miscUpload, 'upload_mini_video'), \
             patch.object(worker._miscUpload, 'youtube_upload_mini_video'):
            mock_tg.return_value.generate.return_value = True

            worker.generatePanoramaMiniVideo(
                task,
                image_id=base_img.id,
                panorama_image_id=pano_entries[0].id,
                camera_id=cam.id,
                pre_seconds=60,
                post_seconds=60,
                framerate=25,
                note='test pano success',
                crop_x=0,
                crop_y=0,
                crop_width=50,
                crop_height=50,
                pan_mode='linear',
                end_crop_x=20,
                end_crop_y=0,
            )
            task.setSuccess.assert_called_once()

        worker.config['FFMPEG_CODEC'] = 'libx264'


# --------------------------------------------------------------------------
# 5. generatePanoramaVideo
# --------------------------------------------------------------------------

def test_generate_panorama_video(test_worker, app, tmp_path):
    worker = test_worker
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        day_date = datetime(2026, 1, 3).date()

        task = MagicMock()
        # Invalid timespec
        worker.generatePanoramaVideo(task, timespec='bad', night=True, camera_id=cam.id)
        task.setFailed.assert_called_with('Invalid time spec')

        # Invalid codec
        task.reset_mock()
        worker.config['FFMPEG_CODEC'] = 'bad_codec'
        worker.generatePanoramaVideo(task, timespec='20260103', night=True, camera_id=cam.id)
        task.setFailed.assert_called_with('Invalid codec in config, timelapse generation failed')
        worker.config['FFMPEG_CODEC'] = 'h264_qsv'  # Tests fallback to libx264

        # Add an existing panorama video to test overwrite check
        old_pano_vid = IndiAllSkyDbPanoramaVideoTable(
            camera_id=cam.id,
            filename='old_pano.mp4',
            dayDate=day_date,
            night=True,
        )
        db.session.add(old_pano_vid)
        db.session.commit()

        task.reset_mock()
        worker.config['TIMELAPSE_OVERWRITE'] = False
        worker.generatePanoramaVideo(task, timespec='20260103', night=True, camera_id=cam.id)
        task.setFailed.assert_called_with('Panorama Timelapse already exists, overwrite not permitted')

        # Overwrite enabled & success
        worker.config['TIMELAPSE_OVERWRITE'] = True
        task.reset_mock()
        with patch('indi_allsky.video.TimelapseGenerator') as mock_tg, \
             patch.object(worker._miscUpload, 'syncapi_panorama_video'), \
             patch.object(worker._miscUpload, 's3_upload_panorama_video'), \
             patch.object(worker._miscUpload, 'upload_panorama_video'), \
             patch.object(worker._miscUpload, 'youtube_upload_panorama_video'):
            mock_tg.return_value.generate.return_value = True
            worker.generatePanoramaVideo(task, timespec='20260103', night=True, camera_id=cam.id)
            task.setSuccess.assert_called_once()

        worker.config['FFMPEG_CODEC'] = 'libx264'


# --------------------------------------------------------------------------
# 6. generateKeogramStarTrails
# --------------------------------------------------------------------------

def test_generate_keogram_startrails_validation_and_overwrite(test_worker, app):
    worker = test_worker
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        task = MagicMock()

        # Invalid timespec
        worker.generateKeogramStarTrails(task, timespec='bad', night=True, camera_id=cam.id)
        task.setFailed.assert_called_with('Invalid time spec')

        # Invalid codec
        task.reset_mock()
        worker.config['FFMPEG_CODEC'] = 'bad_codec'
        worker.generateKeogramStarTrails(task, timespec='20260104', night=True, camera_id=cam.id)
        task.setFailed.assert_called_with('Invalid codec in config, timelapse generation failed')
        worker.config['FFMPEG_CODEC'] = 'libx264'

        # Existing entries overwrite test
        day_date = datetime(2026, 1, 4).date()
        kg_entry = IndiAllSkyDbKeogramTable(camera_id=cam.id, filename='k.jpg', dayDate=day_date, night=True)
        st_entry = IndiAllSkyDbStarTrailsTable(camera_id=cam.id, filename='st.jpg', dayDate=day_date, night=True)
        stv_entry = IndiAllSkyDbStarTrailsVideoTable(camera_id=cam.id, filename='stv.mp4', dayDate=day_date, night=True)
        db.session.add_all([kg_entry, st_entry, stv_entry])
        db.session.commit()

        task.reset_mock()
        worker.config['TIMELAPSE_OVERWRITE'] = False
        worker.generateKeogramStarTrails(task, timespec='20260104', night=True, camera_id=cam.id)
        assert 'already exists, overwrite not permitted' in task.setFailed.call_args[0][0]


def test_generate_keogram_startrails_day_and_night(test_worker, app, tmp_path):
    worker = test_worker
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        day_date = datetime(2026, 1, 5).date()
        worker.config['TIMELAPSE_OVERWRITE'] = True
        worker.config['STARTRAILS_MOONMODE_THOLD'] = True
        worker.config['NIGHT_MOONMODE_ALT_DEG'] = 10.0
        worker.config['NIGHT_MOONMODE_PHASE'] = 50.0

        # Create images with different formats: jpg, png, tif
        import cv2
        img_mat = np.zeros((50, 50, 3), dtype=np.uint8)

        jpg_file = tmp_path / 'frame1.jpg'
        png_file = tmp_path / 'frame2.png'
        tif_file = tmp_path / 'frame3.tif'
        cv2.imwrite(str(jpg_file), img_mat)
        cv2.imwrite(str(png_file), img_mat)
        cv2.imwrite(str(tif_file), img_mat)

        now = datetime(2026, 1, 5, 22, 0, 0)
        for idx, f in enumerate([jpg_file, png_file, tif_file]):
            img_entry = IndiAllSkyDbImageTable(
                camera_id=cam.id,
                filename=str(f),
                dayDate=day_date,
                createDate=now + timedelta(minutes=idx),
                night=True,
                exclude=False,
                binmode=1,
                exposure=1.0,
                gain=100.0,
                adu=150.0,
                stars=25,
            )
            db.session.add(img_entry)
        db.session.commit()

        mock_thumb = MagicMock()
        mock_thumb.fileSize = 100

        task = MagicMock()
        with patch('indi_allsky.video.KeogramGenerator') as mock_kg_cls, \
             patch('indi_allsky.video.StarTrailGenerator') as mock_stg_cls, \
             patch('indi_allsky.video.TimelapseGenerator') as mock_tg_cls, \
             patch.object(worker._miscDb, 'addThumbnail', return_value=mock_thumb), \
             patch.object(worker._miscUpload, 'syncapi_thumbnail'), \
             patch.object(worker._miscUpload, 's3_upload_thumbnail'), \
             patch.object(worker._miscUpload, 'syncapi_keogram'), \
             patch.object(worker._miscUpload, 's3_upload_keogram'), \
             patch.object(worker._miscUpload, 'upload_keogram'), \
             patch.object(worker._miscUpload, 'syncapi_startrail'), \
             patch.object(worker._miscUpload, 's3_upload_startrail'), \
             patch.object(worker._miscUpload, 'upload_startrail'), \
             patch.object(worker._miscUpload, 'syncapi_startrail_video'), \
             patch.object(worker._miscUpload, 's3_upload_startrail_video'), \
             patch.object(worker._miscUpload, 'upload_startrail_video'), \
             patch.object(worker._miscUpload, 'youtube_upload_startrail_video'):

            mock_kg = mock_kg_cls.return_value
            mock_kg.shape = (50, 100, 3)
            mock_kg.processImage.side_effect = [None, KeogramMismatchException("Mismatch"), None]

            mock_stg = mock_stg_cls.return_value
            mock_stg.shape = (50, 50, 3)
            mock_stg.trail_count = 3
            mock_stg.timelapse_frame_count = 300  # >= 250 to trigger video generation
            mock_stg.timelapse_frame_list = [jpg_file, png_file]

            mock_tg = mock_tg_cls.return_value
            mock_tg.generate.return_value = True

            # Night run
            worker.generateKeogramStarTrails(task, timespec='20260105', night=True, camera_id=cam.id)
            task.setSuccess.assert_called_once()

            # Day run
            task.reset_mock()
            worker.generateKeogramStarTrails(task, timespec='20260105', night=False, camera_id=cam.id)
            task.setSuccess.assert_called_once()


# --------------------------------------------------------------------------
# 7. uploadAllskyEndOfNight
# --------------------------------------------------------------------------

def test_upload_allsky_end_of_night(test_worker, app, tmp_path):
    worker = test_worker
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        task = MagicMock()

        # Daytime: should do nothing
        worker.uploadAllskyEndOfNight(task, night=False, camera_id=cam.id)
        task.setRunning.assert_called_once()
        task.setSuccess.assert_not_called()
        task.setFailed.assert_not_called()

        # UPLOAD_ENDOFNIGHT disabled
        task.reset_mock()
        worker.config['FILETRANSFER']['UPLOAD_ENDOFNIGHT'] = False
        worker.uploadAllskyEndOfNight(task, night=True, camera_id=cam.id)
        task.setFailed.assert_called_with('End of Night uploading disabled')

        # Folder not configured
        task.reset_mock()
        worker.config['FILETRANSFER']['UPLOAD_ENDOFNIGHT'] = True
        worker.config['FILETRANSFER']['REMOTE_ENDOFNIGHT_FOLDER'] = ''
        worker.uploadAllskyEndOfNight(task, night=True, camera_id=cam.id)
        task.setFailed.assert_called_with('End of Night folder not configured')

        # Success path with ephem NeverUp and AlwaysUp error branches
        worker.config['FILETRANSFER']['REMOTE_ENDOFNIGHT_FOLDER'] = str(tmp_path / 'eon_{camera_uuid}')
        task.reset_mock()

        with patch('ephem.Observer.next_rising', side_effect=ephem.NeverUpError), \
             patch('ephem.Observer.next_setting', side_effect=ephem.AlwaysUpError):
            worker.uploadAllskyEndOfNight(task, night=True, camera_id=cam.id)
            task.setSuccess.assert_called_with('Uploaded EndOfNight data')

        task.reset_mock()
        with patch('ephem.Observer.previous_rising', side_effect=ephem.AlwaysUpError), \
             patch('ephem.Observer.next_setting', side_effect=ephem.NeverUpError):
            with patch.object(ephem.Sun, 'alt', 1.0):
                worker.uploadAllskyEndOfNight(task, night=True, camera_id=cam.id)
                task.setSuccess.assert_called_with('Uploaded EndOfNight data')


# --------------------------------------------------------------------------
# 8. expireData & _deleteAssets & folder handling
# --------------------------------------------------------------------------

def test_delete_assets_and_expire_data_error_handling(test_worker, app, tmp_path):
    worker = test_worker
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()

        # Add image with deleteAsset raising OSError
        img = IndiAllSkyDbImageTable(
            camera_id=cam.id,
            filename='corrupted.jpg',
            dayDate=datetime(2020, 1, 1).date(),
            createDate=datetime(2020, 1, 1),
            exposure=1.0,
            gain=1.0,
            adu=1.0,
            sqm=1.0,
            stars=1,
        )
        db.session.add(img)
        db.session.commit()

        with patch.object(IndiAllSkyDbImageTable, 'deleteAsset', side_effect=OSError("Disk error")):
            count = worker._deleteAssets(IndiAllSkyDbImageTable, [img.id])
            assert count == 0

        # Empty directory removal error handling
        empty_dir = Path(worker.image_dir) / 'empty_sub'
        empty_dir.mkdir(parents=True, exist_ok=True)

        task = MagicMock()
        with patch.object(Path, 'rmdir', side_effect=PermissionError("Denied")), \
             patch('indi_allsky.asi676mc_calibration.cleanup_expired_sessions', side_effect=OSError("Session err")):
            worker.expireData(task, camera_id=cam.id)
            task.setSuccess.assert_called_once()


def test_video_folder_and_folder_folders(test_worker, tmp_path):
    worker = test_worker
    cam = MagicMock()
    cam.uuid = 'test-cam-uuid'

    folder = worker._getVideoFolder(datetime(2026, 1, 1), cam)
    assert folder.exists()
    assert 'timelapse/20260101' in str(folder)

    # Directory recursion
    sub1 = tmp_path / 'sub1'
    sub2 = sub1 / 'sub2'
    sub2.mkdir(parents=True)

    dir_list = []
    worker._getFolderFolders(tmp_path, dir_list)
    assert sub1 in dir_list
    assert sub2 in dir_list


# --------------------------------------------------------------------------
# 9. _load_detection_mask
# --------------------------------------------------------------------------

def test_load_detection_mask_branches(test_worker, tmp_path):
    worker = test_worker

    # 1. No mask defined
    worker.config['DETECT_MASK'] = ''
    m = worker._load_detection_mask()
    assert all(v is None for v in m.values())

    # 2. Mask does not exist
    worker.config['DETECT_MASK'] = str(tmp_path / 'non_existent.png')
    m = worker._load_detection_mask()
    assert all(v is None for v in m.values())

    # 3. Mask is directory, not file
    mask_dir = tmp_path / 'mask_dir'
    mask_dir.mkdir()
    worker.config['DETECT_MASK'] = str(mask_dir)
    m = worker._load_detection_mask()
    assert all(v is None for v in m.values())

    # 4. PermissionError
    with patch.object(Path, 'exists', side_effect=PermissionError("Forbidden")):
        m = worker._load_detection_mask()
        assert all(v is None for v in m.values())

    # 5. Invalid image (cv2.imread returns None)
    dummy_file = tmp_path / 'dummy.png'
    dummy_file.write_bytes(b'not an image')
    worker.config['DETECT_MASK'] = str(dummy_file)
    m = worker._load_detection_mask()
    assert all(v is None for v in m.values())

    # 6. Valid mask
    import cv2
    valid_mask = tmp_path / 'valid_mask.png'
    cv2.imwrite(str(valid_mask), np.full((100, 100), 128, dtype=np.uint8))
    worker.config['DETECT_MASK'] = str(valid_mask)
    worker.binning_av = [1, 2]

    with patch('indi_allsky.video.MaskProcessor') as mock_mp_cls:
        mock_mp = mock_mp_cls.return_value
        mock_mp.image = np.zeros((100, 100), dtype=np.uint8)
        m = worker._load_detection_mask()
        assert mock_mp.rotate_90.called
        assert mock_mp.crop_image.called
