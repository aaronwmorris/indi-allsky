"""Exercise the real task/asset database. The Flask instance is local to each test."""
from datetime import date, datetime, timedelta
from pathlib import Path
import shutil
from unittest.mock import Mock

from flask import Flask
from PIL import Image
import pytest

from indi_allsky import night_movie
from indi_allsky.flask import db
from indi_allsky.flask.miscDb import miscDb
from indi_allsky.flask.models import (IndiAllSkyDbCameraTable as Camera, IndiAllSkyDbImageTable as Frame,
    IndiAllSkyDbVideoTable as Movie, IndiAllSkyDbTaskQueueTable as Task, TaskQueueState)
from indi_allsky.video import VideoWorker


@pytest.fixture
def station(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', INDI_ALLSKY_IMAGE_FOLDER=str(tmp_path))
    db.init_app(app)
    business_day = date.today()
    monkeypatch.setattr('indi_allsky.utils.IndiAllSkyDateCalcs.getDayDate', lambda self: business_day)
    monkeypatch.setattr('indi_allsky.archive_health.archive_paused', lambda _: False)
    with app.app_context():
        db.create_all()
        camera = Camera(name='test local', uuid='movie-test-camera', latitude=0., longitude=0., local=True)
        db.session.add(camera)
        db.session.commit()
        worker = VideoWorker.__new__(VideoWorker)
        worker._shutdown = False
        worker.config = {'TIMELAPSE_SKIP_FRAMES': 0, 'NIGHT_SUN_ALT_DEG': -6, 'IMAGE_FOLDER': str(tmp_path),
                         'IMAGE_FILE_TYPE': 'jpg', 'FFMPEG_CODEC': 'libx264', 'TIMELAPSE_OVERWRITE': False,
                         'FFMPEG_FRAMERATE': 5}
        worker.image_dir = tmp_path
        worker._miscDb = miscDb(worker.config)
        worker._miscDb.setState('DB_CAMERA_ID', str(camera.id))
        worker._miscUpload = Mock()

        def add_frame(name, day=business_day - timedelta(days=1), *, exists=True):
            path = tmp_path / name
            if exists:
                Image.new('RGB', (64, 48), 'blue').save(path)
            db.session.add(Frame(camera_id=camera.id, dayDate=day, filename=name, createDate=datetime.now(),
                                 exposure=1, gain=1, adu=100, night=True))
            db.session.commit()
            return path

        yield worker, camera, business_day, add_frame


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='ffmpeg required')
def test_repair_replaces_corrupt_video_and_preserves_watch_id(station):
    worker, camera, today, add_frame = station
    day = today - timedelta(days=1)
    old = worker.image_dir / 'old.mp4'
    old.write_bytes(b'not a video')
    row = Movie(camera_id=camera.id, dayDate=day, filename=old.name, success=True, night=True)
    db.session.add(row)
    db.session.commit()
    old_id = row.id
    add_frame('frame1.jpg')
    add_frame('frame2.jpg')
    add_frame('ongoing.jpg', today)
    night_movie.reconcile(worker)
    assert Task.query.one().state == TaskQueueState.SUCCESS
    repaired = Movie.query.one()
    assert repaired.id == old_id and repaired.success and repaired.frames == 2
    assert not old.exists() and night_movie.playable(Path(repaired.getFilesystemPath()))
    night_movie.reconcile(worker)
    assert Task.query.count() == 1 and Movie.query.count() == 1


def test_no_sources_one_attempt_until_files_change_and_manual_delete_wins(station):
    worker, camera, today, add_frame = station
    path = add_frame('missing.jpg', exists=False)
    night_movie.reconcile(worker)
    assert Task.query.one().state == TaskQueueState.FAILED
    assert 'insufficient' in Task.query.one().result
    night_movie.reconcile(worker)
    assert Task.query.count() == 1
    day = today - timedelta(days=1)
    night_movie.suppress_repair(camera.id, day)
    Image.new('RGB', (64, 48)).save(path)
    night_movie.reconcile(worker)
    assert Task.query.count() == 1 and Movie.query.count() == 0


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='ffmpeg required')
def test_manual_deletion_while_encoder_runs_wins(station, monkeypatch):
    worker, camera, today, add_frame = station
    add_frame('frame.jpg')
    from indi_allsky.timelapse import TimelapseGenerator
    original = TimelapseGenerator.generate

    def cancel(self, filename, frames):
        original(self, filename, frames)
        night_movie.suppress_repair(camera.id, today - timedelta(days=1))

    monkeypatch.setattr(TimelapseGenerator, 'generate', cancel)
    night_movie.reconcile(worker)
    assert Task.query.one().state == TaskQueueState.EXPIRED and Movie.query.count() == 0
    assert not list(worker.image_dir.rglob('*.mp4'))
    night_movie.reconcile(worker)
    assert Task.query.count() == 1


def test_archive_pause_does_not_consume_repair_attempt(station, monkeypatch):
    worker, camera, today, add_frame = station
    add_frame('missing.jpg', exists=False)
    monkeypatch.setattr('indi_allsky.archive_health.archive_paused', lambda _: True)
    night_movie.reconcile(worker)
    assert Task.query.count() == 0
    monkeypatch.setattr('indi_allsky.archive_health.archive_paused', lambda _: False)
    night_movie.reconcile(worker)
    assert Task.query.count() == 1 and Task.query.one().state == TaskQueueState.FAILED


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='ffmpeg required')
def test_file_returning_after_a_missing_source_unblocks_same_night(station):
    worker, camera, today, add_frame = station
    path = add_frame('restored.jpg', exists=False)
    night_movie.reconcile(worker)
    assert Task.query.one().state == TaskQueueState.FAILED
    Image.new('RGB', (64, 48)).save(path)
    night_movie.reconcile(worker)
    assert [task.state for task in Task.query.order_by(Task.id)] == [TaskQueueState.FAILED, TaskQueueState.SUCCESS]
    assert night_movie.playable(Path(Movie.query.one().getFilesystemPath()))


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='ffmpeg required')
def test_upload_failure_does_not_mark_good_local_repair_as_failed(station):
    worker, camera, today, add_frame = station
    add_frame('source.jpg')
    worker._miscUpload.syncapi_video.side_effect = RuntimeError('remote upload unavailable')
    night_movie.reconcile(worker)
    assert Task.query.one().state == TaskQueueState.SUCCESS
    assert night_movie.playable(Path(Movie.query.one().getFilesystemPath()))
