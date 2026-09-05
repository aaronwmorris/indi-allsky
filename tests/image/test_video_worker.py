import signal
from multiprocessing import Queue, Array
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky.video import VideoWorker
from indi_allsky.flask.models import IndiAllSkyDbCameraTable
from indi_allsky.flask import db


def test_video_worker_init(app, tmp_path):
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
            )
            db.session.add(cam)
            db.session.commit()

        config = {
            'LOCATION_LATITUDE': -34.9285,
            'LOCATION_LONGITUDE': 138.6007,
            'LOCATION_ELEVATION': 50,
            'IMAGE_FOLDER': str(tmp_path),
            'VARLIB_FOLDER': str(tmp_path),
            'FILETRANSFER': {'UPLOAD_IMAGE': False},
        }

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

        assert worker.name == 'Video-0'
        assert worker.thumbnail_keogram_width == 1000
        assert worker._shutdown is False

        # Test signal handlers
        worker.sighup_handler_worker(signal.SIGHUP, None)
        assert worker._shutdown is True

        worker._shutdown = False
        worker.sigterm_handler_worker(signal.SIGTERM, None)
        assert worker._shutdown is True


def test_video_worker_process_task_missing(app, base_config):
    with app.app_context():
        error_q = Queue()
        video_q = Queue()
        upload_q = Queue()
        night_av = Array('i', [-1, -1])
        binning_av = Array('i', [-1] * 6)

        worker = VideoWorker(
            idx=0,
            config=base_config,
            error_q=error_q,
            video_q=video_q,
            upload_q=upload_q,
            night_av=night_av,
            binning_av=binning_av,
        )

        # Missing task should log and return cleanly without uncaught exception
        worker.processTask({'task_id': 999999})


def test_video_worker_get_folder_files_by_ext(base_config, tmp_path):
    error_q = Queue()
    video_q = Queue()
    upload_q = Queue()
    night_av = Array('i', [-1, -1])
    binning_av = Array('i', [-1] * 6)

    worker = VideoWorker(
        idx=0,
        config=base_config,
        error_q=error_q,
        video_q=video_q,
        upload_q=upload_q,
        night_av=night_av,
        binning_av=binning_av,
    )

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

