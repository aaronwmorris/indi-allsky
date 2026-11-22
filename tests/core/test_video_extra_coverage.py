import io
import os
import queue
import tempfile
from datetime import datetime, timedelta, timezone
from multiprocessing import Array
from pathlib import Path
from unittest.mock import MagicMock, patch
import cv2
import ephem
import numpy as np
import pytest

from indi_allsky import constants
from indi_allsky.exceptions import TimelapseException
from indi_allsky.video import VideoWorker
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbFitsImageTable,
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
    NotificationCategory,
)
from indi_allsky.flask import db


@pytest.fixture
def video_worker(app, base_config, tmp_path):
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        if not cam:
            cam = IndiAllSkyDbCameraTable(
                name='ZWO ASI676MC',
                uuid='cam-video-extra-coverage',
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
            cam.uuid = 'cam-video-extra-coverage'
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


def test_video_worker_init_no_image_folder(base_config):
    """Test line 131: VideoWorker fallback when IMAGE_FOLDER is absent."""
    config = dict(base_config)
    config.pop('IMAGE_FOLDER', None)

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

    expected_path = Path(__file__).parent.parent.parent.joinpath('html', 'images').absolute()
    assert worker.image_dir == expected_path


def test_video_worker_saferun_queue_empty(video_worker):
    """Test lines 198-199: saferun handles queue.Empty and continues until stop."""
    # First call raises Empty, second returns stop signal
    video_worker.video_q.get = MagicMock(side_effect=[queue.Empty, {'stop': True}])

    video_worker.saferun()
    assert video_worker.video_q.get.call_count == 2


def test_video_worker_process_task_action_dispatch(video_worker, app):
    """Test line 246: action_method(task, **kwargs) is executed in processTask."""
    with app.app_context():
        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=TaskQueueState.QUEUED,
            data={
                'action': 'custom_dummy_action',
                'kwargs': {'foo': 'bar'},
            },
        )
        db.session.add(task)
        db.session.commit()

        mock_action = MagicMock()
        video_worker.custom_dummy_action = mock_action

        video_worker.processTask({'task_id': task.id})

        mock_action.assert_called_once()
        called_task, kwargs = mock_action.call_args[0][0], mock_action.call_args[1]
        assert called_task.id == task.id
        assert kwargs == {'foo': 'bar'}


def test_load_asi676mc_calibration_database_oserror(video_worker, app, tmp_path):
    """Test lines 301-303: OSError when accessing local FITS file stats."""
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        now = datetime.now()

        fits_file = tmp_path / 'corrupted_stat.fits'
        fits_file.write_bytes(b'SIMPLE  =                    T' + b' ' * 2854)

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
        db.session.commit()

        source_details = {
            'camera_id': cam.id,
            'camera_uuid': cam.uuid,
            'retention_cutoff': (now - timedelta(days=1)).strftime('%Y-%m-%d'),
        }

        with patch('pathlib.Path.stat', side_effect=OSError("Disk read error")):
            res = video_worker._loadAsi676mcCalibrationDatabase(source_details, lambda p: None)
            assert res['source_details']['missing_local_count'] == 1


def test_timelapse_smoke_rating_value_error(video_worker, app, tmp_path):
    """Test line 633: ValueError when converting max_smoke_rating in generateVideo()."""
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        day_date = datetime(2026, 1, 1).date()

        # Add an image so timelapse proceeds
        img_p = Path(video_worker.image_dir) / 'tl_test.jpg'
        img_p.parent.mkdir(parents=True, exist_ok=True)
        img_p.write_bytes(b'fake image data')

        img = IndiAllSkyDbImageTable(
            camera_id=cam.id,
            filename=str(img_p),
            dayDate=day_date,
            createDate=datetime(2026, 1, 1, 22, 0, 0),
            night=True,
            exclude=False,
            exposure=1.0,
            gain=100.0,
            adu=100.0,
            smoke_rating=0,
        )
        db.session.add(img)
        db.session.commit()

        task = MagicMock()
        mock_data = MagicMock()
        mock_data.image_max_kpindex = 1.0
        mock_data.image_max_ovation_max = 10
        mock_data.image_max_stars = 20
        mock_data.image_avg_stars = 15.0
        mock_data.image_max_moonphase = 0.5
        mock_data.image_avg_sqm = 20.5
        mock_data.image_max_smoke_rating = 'invalid_string'  # Triggers line 633

        with patch('sqlalchemy.orm.query.Query.first', return_value=mock_data), \
             patch('indi_allsky.video.TimelapseGenerator') as mock_tg:
            mock_tg.return_value.generate.return_value = True
            video_worker.generateVideo(task, timespec='20260101', night=True, camera_id=cam.id)
            task.setSuccess.assert_called_once()


def test_mini_timelapse_coverage_branches(video_worker, app, tmp_path):
    """Test lines 920-922, 936-937, 976-980, 993, 1007-1010, 1055-1058, 1133, 1137, 1147-1148, 1174-1176, 1208-1216, 1262-1263 in mini_timelapse."""
    now = datetime(2026, 1, 15, 12, 0, 0)
    class MockDt(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    with patch('indi_allsky.video.datetime', MockDt):
        with app.app_context():
            cam = IndiAllSkyDbCameraTable.query.first()

        # Create target image
        target_img_p = Path(video_worker.image_dir) / 'target.jpg'
        target_img_p.write_bytes(b'target_img')
        target_img = IndiAllSkyDbImageTable(
            camera_id=cam.id,
            filename=str(target_img_p),
            dayDate=now.date(),
            createDate=now,
            night=True,
            exclude=False,
            exposure=1.0,
            gain=100.0,
            adu=100.0,
            width=200,
            height=100,
        )
        db.session.add(target_img)
        db.session.commit()

        # 1. Lines 920-922: TIMELAPSE_OVERWRITE False with existing mini video
        vid_folder = video_worker._getVideoFolder(now.date(), cam)
        expected_filename = vid_folder / f'allsky-minitimelapse_ccd{cam.id}_{now.strftime("%Y%m%d")}_night_{int(now.timestamp())}.mp4'
        old_mini = IndiAllSkyDbMiniVideoTable(
            camera_id=cam.id,
            filename=str(expected_filename),
            dayDate=now.date(),
            targetDate=now,
            startDate=now,
            endDate=now,
            note='test',
            night=True,
        )
        db.session.add(old_mini)
        db.session.commit()

        task = MagicMock()
        task.id = 123
        task.createDate = now
        video_worker.config['TIMELAPSE_OVERWRITE'] = False
        video_worker.generateMiniVideo(
            task,
            image_id=target_img.id,
            camera_id=cam.id,
            pre_seconds=10,
            post_seconds=10,
            framerate=25,
            note='test',
        )
        task.setFailed.assert_called_with('Mini Timelapse already exists, overwrite not permitted')

        # Clean up old_mini
        db.session.delete(old_mini)
        db.session.commit()
        video_worker.config['TIMELAPSE_OVERWRITE'] = True

        # 2. Add multiple panorama images for panorama mode
        pano_files = []
        pano_entries = []
        for i in range(3):
            p_file = Path(video_worker.image_dir) / f'pano_extra_{i}.jpg'
            cv2.imwrite(str(p_file), np.zeros((100, 200, 3), dtype=np.uint8))
            pano_files.append(p_file)

            p_entry = IndiAllSkyDbPanoramaImageTable(
                camera_id=cam.id,
                filename=str(p_file),
                dayDate=now.date(),
                createDate=now + timedelta(seconds=i * 2),
                night=True,
                exclude=False,
                exposure=1.0,
                gain=100.0,
                width=200,
                height=100,
            )
            db.session.add(p_entry)
            pano_entries.append(p_entry)
        db.session.commit()

        pano_target = pano_entries[0]

        # Pre-create orphan video file to trigger lines 936-937
        vid_folder = video_worker._getVideoFolder(now.date(), cam)
        orphan_vid = vid_folder.joinpath(f'allsky-panorama_minitimelapse_ccd{cam.id}_{now.strftime("%Y%m%d")}_night_{int(now.timestamp())}.mp4')
        orphan_vid.parent.mkdir(parents=True, exist_ok=True)
        orphan_vid.touch()

        # Mock timelapse_data to hit lines 976-980 and line 993 (invalid smoke rating)
        mock_tl_data = MagicMock()
        mock_tl_data.image_max_kpindex = 2.0
        mock_tl_data.image_max_ovation_max = 50
        mock_tl_data.image_max_stars = 100
        mock_tl_data.image_avg_stars = 80.0
        mock_tl_data.image_max_moonphase = 0.25
        mock_tl_data.image_avg_sqm = 21.2
        mock_tl_data.image_max_smoke_rating = 'invalid_smoke'  # line 993

        # Configure USE_NIGHT_CONFIG False and night True to trigger lines 1174-1176
        video_worker.config['TIMELAPSE'] = {'USE_NIGHT_CONFIG': False}

        # 3. Test buildPanoramaPanFilter ValueError (lines 1055-1058)
        task.reset_mock()
        with patch('sqlalchemy.orm.query.Query.first', return_value=mock_tl_data), \
             patch('indi_allsky.video.buildPanoramaPanFilter', side_effect=ValueError("Invalid pan")):
            video_worker.generateMiniVideo(
                task,
                image_id=target_img.id,
                panorama_image_id=pano_target.id,
                camera_id=cam.id,
                pre_seconds=10,
                post_seconds=10,
                framerate=25,
                crop_x=0,
                crop_y=0,
                crop_width=100,
                crop_height=100,
                pan_mode='linear',
                note='test',
            )
            assert 'Invalid panorama pan' in task.setFailed.call_args[0][0]

        # 4. Test lines 1133, 1137 (pan_mode != 'linear', cv2.imread None)
        task.reset_mock()
        with patch('sqlalchemy.orm.query.Query.first', return_value=mock_tl_data), \
             patch('cv2.imread', return_value=None), \
             patch('indi_allsky.video.TimelapseGenerator') as mock_tg:
            mock_tg.return_value.generate.return_value = True
            video_worker.generateMiniVideo(
                task,
                image_id=target_img.id,
                panorama_image_id=pano_target.id,
                camera_id=cam.id,
                pre_seconds=10,
                post_seconds=10,
                framerate=25,
                crop_x=0,
                crop_y=0,
                crop_width=100,
                crop_height=100,
                pan_mode='static',
                note='test',
            )
            task.setSuccess.assert_called_once()

        # 5. Test cropPanoramaArray ValueError (lines 1147-1148)
        task.reset_mock()
        fake_img = np.zeros((100, 200, 3), dtype=np.uint8)
        with patch('sqlalchemy.orm.query.Query.first', return_value=mock_tl_data), \
             patch('cv2.imread', return_value=fake_img), \
             patch('indi_allsky.video.cropPanoramaArray', side_effect=ValueError("Crop failed")), \
             patch('indi_allsky.video.TimelapseGenerator') as mock_tg:
            mock_tg.return_value.generate.return_value = True
            video_worker.generateMiniVideo(
                task,
                image_id=target_img.id,
                panorama_image_id=pano_target.id,
                camera_id=cam.id,
                pre_seconds=10,
                post_seconds=10,
                framerate=25,
                crop_x=0,
                crop_y=0,
                crop_width=100,
                crop_height=100,
                pan_mode='static',
                note='test',
            )
            task.setSuccess.assert_called_once()

        # 6. Test buildPanoramaTimedPanFilter ValueError (lines 1208-1216)
        task.reset_mock()
        def fail_pan_filter(s_w, s_h, c_x, c_y, ec_x, ec_y, cw, ch, pts, fps, cmd_f, direction='shortest'):
            if cmd_f and cmd_f.exists():
                cmd_f.unlink()
            raise ValueError("Filter error")

        with patch('sqlalchemy.orm.query.Query.first', return_value=mock_tl_data), \
             patch('indi_allsky.video.buildPanoramaTimedPanFilter', side_effect=fail_pan_filter):
            video_worker.generateMiniVideo(
                task,
                image_id=target_img.id,
                panorama_image_id=pano_target.id,
                camera_id=cam.id,
                pre_seconds=10,
                post_seconds=10,
                framerate=25,
                crop_x=0,
                crop_y=0,
                crop_width=100,
                crop_height=100,
                pan_mode='linear',
                note='test',
            )
            assert 'Invalid panorama pan' in task.setFailed.call_args[0][0]

        # 7. Test pan_command_file.unlink() FileNotFoundError in finally (lines 1262-1263)
        task.reset_mock()
        with patch('sqlalchemy.orm.query.Query.first', return_value=mock_tl_data), \
             patch('indi_allsky.video.buildPanoramaTimedPanFilter', return_value='filter_str'), \
             patch('pathlib.Path.unlink', side_effect=FileNotFoundError), \
             patch('indi_allsky.video.TimelapseGenerator') as mock_tg:
            mock_tg.return_value.generate.return_value = True
            video_worker.generateMiniVideo(
                task,
                image_id=target_img.id,
                panorama_image_id=pano_target.id,
                camera_id=cam.id,
                pre_seconds=10,
                post_seconds=10,
                framerate=25,
                crop_x=0,
                crop_y=0,
                crop_width=100,
                crop_height=100,
                pan_mode='linear',
                note='test',
            )
            task.setSuccess.assert_called_once()

        # 8. Test lines 1007-1010 (size 0 continue and stat OSError)
        empty_pano = Path(video_worker.image_dir) / 'empty_pano.jpg'
        empty_pano.touch()  # size 0
        empty_entry = IndiAllSkyDbPanoramaImageTable(
            camera_id=cam.id,
            filename=str(empty_pano),
            dayDate=now.date(),
            createDate=now + timedelta(seconds=1),
            night=True,
            exclude=False,
            exposure=1.0,
            gain=100.0,
            width=200,
            height=100,
        )
        db.session.add(empty_entry)

        missing_pano = Path(video_worker.image_dir) / 'missing_pano.jpg'
        missing_entry = IndiAllSkyDbPanoramaImageTable(
            camera_id=cam.id,
            filename=str(missing_pano),
            dayDate=now.date(),
            createDate=now + timedelta(seconds=2),
            night=True,
            exclude=False,
            exposure=1.0,
            gain=100.0,
            width=200,
            height=100,
        )
        db.session.add(missing_entry)
        db.session.commit()

        task.reset_mock()
        with patch('sqlalchemy.orm.query.Query.first', return_value=mock_tl_data), \
             patch('indi_allsky.video.TimelapseGenerator') as mock_tg:
            mock_tg.return_value.generate.return_value = True
            video_worker.generateMiniVideo(
                task,
                image_id=target_img.id,
                panorama_image_id=pano_target.id,
                camera_id=cam.id,
                pre_seconds=10,
                post_seconds=10,
                framerate=25,
                crop_x=0,
                crop_y=0,
                crop_width=100,
                crop_height=100,
                pan_mode='static',
                note='test',
            )
            task.setSuccess.assert_called_once()


def test_timelapse_panorama_extra_coverage(video_worker, app, tmp_path):
    """Test lines 1374-1375, 1413-1417, 1430, 1443-1444, 1447, 1490-1492 in generatePanoramaVideo."""
    now = datetime(2026, 1, 10, 12, 0, 0)
    class MockDt(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    with patch('indi_allsky.video.datetime', MockDt):
        with app.app_context():
            cam = IndiAllSkyDbCameraTable.query.first()
            day_date = datetime(2026, 1, 10).date()

        # Add panorama images (valid, nonexistent, and zero-byte)
        p_valid = Path(video_worker.image_dir) / 'pano_p_valid.jpg'
        cv2.imwrite(str(p_valid), np.zeros((100, 200, 3), dtype=np.uint8))

        p_missing = Path(video_worker.image_dir) / 'pano_p_missing.jpg'  # does not exist

        p_empty = Path(video_worker.image_dir) / 'pano_p_empty.jpg'
        p_empty.touch()  # size 0

        for idx, p_f in enumerate([p_valid, p_missing, p_empty]):
            e = IndiAllSkyDbPanoramaImageTable(
                camera_id=cam.id,
                filename=str(p_f),
                dayDate=day_date,
                createDate=datetime(2026, 1, 10, 22, 0, idx),
                night=True,
                exclude=False,
                exposure=1.0,
                gain=100.0,
                width=200,
                height=100,
            )
            db.session.add(e)
        db.session.commit()

        # Pre-create orphan panorama video file for lines 1374-1375
        vid_folder = video_worker._getVideoFolder(day_date, cam)
        orphan_file = vid_folder / f'allsky-panorama_timelapse_ccd{cam.id}_{day_date.strftime("%Y%m%d")}_night_{int(now.timestamp())}.mp4'
        orphan_file.parent.mkdir(parents=True, exist_ok=True)
        orphan_file.touch()

        # Mock timelapse_data for lines 1413-1417 and line 1430
        mock_tl_data = MagicMock()
        mock_tl_data.image_max_kpindex = 3.0
        mock_tl_data.image_max_ovation_max = 60
        mock_tl_data.image_max_stars = 120
        mock_tl_data.image_avg_stars = 95.0
        mock_tl_data.image_max_moonphase = 0.8
        mock_tl_data.image_avg_sqm = 20.8
        mock_tl_data.image_max_smoke_rating = 'invalid_smoke'  # line 1430

        # Lines 1490-1492: USE_NIGHT_CONFIG False and night True
        video_worker.config['TIMELAPSE'] = {'USE_NIGHT_CONFIG': False}
        video_worker.config['TIMELAPSE_SKIP_FRAMES'] = 0

        task = MagicMock()
        with patch('sqlalchemy.orm.query.Query.first', return_value=mock_tl_data), \
             patch('indi_allsky.video.TimelapseGenerator') as mock_tg:
            mock_tg.return_value.generate.return_value = True
            video_worker.generatePanoramaVideo(task, timespec='20260110', night=True, camera_id=cam.id)
            task.setSuccess.assert_called_once()


def test_timelapse_keogram_startrail_extra_coverage(video_worker, app, tmp_path):
    """Test lines 1581, 1760-1764, 1777, 1924-1925, 1928, 1975, 2130-2133, 2156-2158, 2172-2174, 2182-2185."""
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        day_date = datetime(2026, 1, 15).date()

        # Add images: valid, missing, empty
        f_valid = Path(video_worker.image_dir) / 'keo_valid.jpg'
        cv2.imwrite(str(f_valid), np.zeros((100, 100, 3), dtype=np.uint8))

        f_missing = Path(video_worker.image_dir) / 'keo_missing.jpg'  # doesn't exist

        f_empty = Path(video_worker.image_dir) / 'keo_empty.jpg'
        f_empty.touch()  # size 0

        for idx, f in enumerate([f_valid, f_missing, f_empty]):
            e = IndiAllSkyDbImageTable(
                camera_id=cam.id,
                filename=str(f),
                dayDate=day_date,
                createDate=datetime(2026, 1, 15, 22, 0, idx),
                night=True,
                exclude=False,
                exposure=1.0,
                gain=100.0,
                adu=150.0,
                stars=30,
                binmode=1,
            )
            db.session.add(e)
        db.session.commit()

        # Mock image_data for lines 1760-1764 and 1777
        mock_img_data = MagicMock()
        mock_img_data.image_max_kpindex = 1.5
        mock_img_data.image_max_ovation_max = 25
        mock_img_data.image_max_stars = 50
        mock_img_data.image_avg_stars = 40.0
        mock_img_data.image_max_moonphase = 0.1
        mock_img_data.image_avg_sqm = 21.5
        mock_img_data.image_max_smoke_rating = 'invalid_val'  # line 1777

        # 1. Line 1581: libvpx codec -> 'webm'
        video_worker.config['FFMPEG_CODEC'] = 'libvpx'
        # Line 1975: STARTRAILS_USE_DB_DATA = False
        video_worker.config['STARTRAILS_USE_DB_DATA'] = False

        task = MagicMock()
        mock_thumb = MagicMock()
        mock_thumb.fileSize = 50

        with patch('sqlalchemy.orm.query.Query.first', return_value=mock_img_data), \
             patch('indi_allsky.video.KeogramGenerator') as mock_kg_cls, \
             patch('indi_allsky.video.StarTrailGenerator') as mock_stg_cls, \
             patch('indi_allsky.video.TimelapseGenerator') as mock_tg_cls, \
             patch.object(video_worker._miscDb, 'addThumbnail', return_value=mock_thumb), \
             patch.object(video_worker._miscUpload, 'syncapi_thumbnail'), \
             patch.object(video_worker._miscUpload, 's3_upload_thumbnail'), \
             patch.object(video_worker._miscUpload, 'syncapi_keogram'), \
             patch.object(video_worker._miscUpload, 's3_upload_keogram'), \
             patch.object(video_worker._miscUpload, 'upload_keogram'), \
             patch.object(video_worker._miscUpload, 'syncapi_startrail'), \
             patch.object(video_worker._miscUpload, 's3_upload_startrail'), \
             patch.object(video_worker._miscUpload, 'upload_startrail'), \
             patch.object(video_worker._miscUpload, 'syncapi_startrail_video'), \
             patch.object(video_worker._miscUpload, 's3_upload_startrail_video'), \
             patch.object(video_worker._miscUpload, 'upload_startrail_video'), \
             patch.object(video_worker._miscUpload, 'youtube_upload_startrail_video'):

            mock_kg = mock_kg_cls.return_value
            mock_kg.shape = (50, 100, 3)

            mock_stg = mock_stg_cls.return_value
            mock_stg.shape = (50, 50, 3)
            mock_stg.trail_count = 3
            mock_stg.timelapse_frame_count = 300
            mock_stg.timelapse_frame_list = [f_valid]

            # Trigger TimelapseException for startrail video (lines 2130-2133)
            mock_tg = mock_tg_cls.return_value
            mock_tg.generate.side_effect = TimelapseException("Startrail video failed")

            # Create destination files to trigger lines 2156-2158, 2172-2174
            vid_folder = video_worker._getVideoFolder(day_date, cam)
            keo_f = vid_folder / f'allsky-keogram_ccd{cam.id}_{day_date.strftime("%Y%m%d")}_night_{int(datetime.now().timestamp())}.jpg'
            # Let finalize touch the file so exists() returns True
            def mock_finalize(target_file, camera):
                target_file.touch()
            mock_kg.finalize.side_effect = mock_finalize

            def mock_finalize_stg(target_file, camera):
                target_file.touch()
            mock_stg.finalize.side_effect = mock_finalize_stg

            video_worker.generateKeogramStarTrails(task, timespec='20260115', night=True, camera_id=cam.id)
            task.setSuccess.assert_called_once()

            # Now test lines 2182-2185 with successful startrail video generation
            task.reset_mock()
            mock_tg.generate.side_effect = None
            mock_tg.generate.return_value = True
            video_worker.config['TIMELAPSE_OVERWRITE'] = True

            def mock_generate_video(target_file, file_list, **kwargs):
                target_file.touch()
            mock_tg.generate.side_effect = mock_generate_video

            video_worker.generateKeogramStarTrails(task, timespec='20260115', night=True, camera_id=cam.id)
            task.setSuccess.assert_called_once()


def test_upload_allsky_end_of_night_ephem_rising(video_worker, app):
    """Test lines 2240 and 2245: math.degrees(sun.alt) < 0 and NeverUpError in uploadAllskyEndOfNight."""
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        task = MagicMock()

        # sun.alt < 0 (line 2240) and next_rising raising NeverUpError (line 2245)
        with patch.object(ephem.Sun, 'alt', -0.5), \
             patch('ephem.Observer.next_rising', side_effect=ephem.NeverUpError), \
             patch('ephem.Observer.next_setting', side_effect=ephem.AlwaysUpError):
            video_worker.uploadAllskyEndOfNight(task, night=True, camera_id=cam.id)
            task.setSuccess.assert_called_with('Uploaded EndOfNight data')


def test_disk_space_notification_threshold_exceeded(video_worker, app):
    """Test line 2333 (/boot/efi skip) and line 2350 (disk_usage threshold) in systemHealthCheck."""
    with app.app_context():
        task = MagicMock()
        mock_boot = MagicMock(mountpoint='/boot/efi')
        mock_part = MagicMock(mountpoint='/var/log')
        mock_usage = MagicMock(percent=95.0)
        mock_swap = MagicMock(percent=10.0)

        video_worker.config['DISK_USAGE_WARNING'] = 90.0

        with patch('psutil.disk_partitions', return_value=[mock_boot, mock_part]), \
             patch('psutil.disk_usage', return_value=mock_usage), \
             patch('psutil.swap_memory', return_value=mock_swap), \
             patch.object(video_worker._miscDb, 'addNotification') as mock_notify:
            video_worker.systemHealthCheck(task)
            mock_notify.assert_called_once()
            args = mock_notify.call_args[0]
            assert args[0] == NotificationCategory.DISK
            assert args[1] == '/var/log'


def test_allsky_map_ping_db_notify_invoked(video_worker, app):
    """Test line 2461: db_notify is invoked during send_allsky_map_ping in sendAllskyMapPing."""
    with app.app_context():
        task = MagicMock()

        def fake_send_ping(config, logger, db_notify):
            db_notify(NotificationCategory.STATE, 'allskymap_test', 'Test message', timedelta(minutes=60))
            return True, 'Ping OK'

        with patch('indi_allsky.allsky_map.send_allsky_map_ping', side_effect=fake_send_ping), \
             patch.object(video_worker._miscDb, 'addNotification') as mock_notify, \
             patch.object(video_worker._miscDb, 'clearNotification'):
            video_worker.sendAllskyMapPing(task)
            mock_notify.assert_called_once_with(
                NotificationCategory.STATE,
                'allskymap_test',
                'Test message',
                expire=timedelta(minutes=60),
            )
            task.setSuccess.assert_called_once()


def test_expire_data_sessions_expired_info(video_worker, app):
    """Test line 2618: calibration_session_count > 0 logs info."""
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        task = MagicMock()

        with patch('indi_allsky.asi676mc_calibration.cleanup_expired_sessions', return_value=3):
            video_worker.expireData(task, camera_id=cam.id)
            task.setSuccess.assert_called_once()
            assert '3 calibration sessions' in task.setSuccess.call_args[0][0]


def test_video_worker_signals_and_missing_task(video_worker, app):
    """Test lines 138-141, 145-148, and 226-228."""
    video_worker.sighup_handler_worker(1, None)
    assert video_worker._shutdown is True

    video_worker._shutdown = False
    video_worker.sigterm_handler_worker(15, None)
    assert video_worker._shutdown is True

    with app.app_context():
        # Non-existent task ID triggers lines 226-228
        video_worker.processTask({'task_id': 999999})


def test_expire_data_rmdir_exceptions(video_worker, app):
    """Test lines 2598-2601: PermissionError and OSError on rmdir."""
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        task = MagicMock()

        dir_perm = MagicMock()
        dir_perm.iterdir.return_value = []
        dir_perm.rmdir.side_effect = PermissionError("Permission denied")

        dir_os = MagicMock()
        dir_os.iterdir.return_value = []
        dir_os.rmdir.side_effect = OSError("Directory not empty")

        def mock_get_folders(image_dir, dir_list):
            dir_list.extend([dir_perm, dir_os])

        with patch.object(video_worker, '_getFolderFolders', side_effect=mock_get_folders):
            video_worker.expireData(task, camera_id=cam.id)
            dir_perm.rmdir.assert_called_once()
            dir_os.rmdir.assert_called_once()

