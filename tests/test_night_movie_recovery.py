"""Exercise the real task/asset database. The Flask instance is local to each test."""
from datetime import date, datetime, timedelta
import os
from pathlib import Path
import shutil
import subprocess
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


def pano_frames(worker, camera, date, night, count, prefix='panorama'):
    from indi_allsky.flask.models import IndiAllSkyDbPanoramaImageTable as PanoFrame
    for i in range(count):
        name = f'{prefix}-{i}.jpg'
        Image.new('RGB', (128, 24), (20*i, 80, 100)).save(worker.image_dir / name)
        db.session.add(PanoFrame(camera_id=camera.id, dayDate=date, filename=name, createDate=datetime.now(),
                                 night=night, exposure=1, gain=1))
    db.session.commit()


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='ffmpeg and ffprobe required')
def test_panorama_day_night_are_distinct_and_existing_failed_id_has_priority(station):
    from indi_allsky.flask.models import IndiAllSkyDbPanoramaVideoTable as PanoMovie
    worker, camera, today, add_frame = station
    worker.config.update(FISH2PANO={'ENABLE': True}, TIMELAPSE_SKIP_FRAMES=4)
    date = today - timedelta(days=2)
    add_frame('more-recent-regular.jpg')
    missing = PanoMovie(camera_id=camera.id, dayDate=date, night=True, filename='broken.mp4', success=False)
    db.session.add(missing)
    db.session.commit()
    watch_id = missing.id
    for night in (False, True):
        pano_frames(worker, camera, date, night, 6, str(night))
    # Files restored from backup may have mtimes opposite to capture order.
    for index in range(6):
        stamp = 100 - index
        os.utime(worker.image_dir / f'True-{index}.jpg', (stamp, stamp))
    assert night_movie.reconcile(worker)
    fixed = db.session.get(PanoMovie, watch_id)
    assert fixed.success and fixed.frames == 2 and night_movie.playable(Path(fixed.getFilesystemPath()))
    pixels = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(fixed.getFilesystemPath()),
        '-vf', 'scale=1:1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'])
    assert len(pixels) == 6 and 65 < pixels[0] < pixels[3]
    assert not PanoMovie.query.filter_by(night=False).first()
    assert night_movie.reconcile(worker)
    daytime = PanoMovie.query.filter_by(night=False).one()
    assert daytime.frames == 2 and night_movie.playable(Path(daytime.getFilesystemPath()))
    assert not night_movie.reconcile(worker)
    assert PanoMovie.query.count() == 2


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='ffmpeg and ffprobe required')
def test_explicit_panorama_delete_during_repair_keeps_day_and_night_separate(station, monkeypatch):
    from indi_allsky.flask.models import IndiAllSkyDbPanoramaVideoTable as PanoMovie
    from indi_allsky.timelapse import TimelapseGenerator
    worker, camera, today, _ = station
    day = today - timedelta(days=2)
    worker.config.update(FISH2PANO={'ENABLE': True})
    pano_frames(worker, camera, day, False, 2)
    original = TimelapseGenerator.generate
    def cancel(self, path, frames, preserve_order=False):
        original(self, path, frames, preserve_order=preserve_order)
        night_movie.suppress_repair(camera.id, day, False, panorama=True)
    monkeypatch.setattr(TimelapseGenerator, 'generate', cancel)
    night_movie.reconcile(worker)
    assert PanoMovie.query.count() == 0
    assert Task.query.one().state == TaskQueueState.EXPIRED
    assert not list(worker.image_dir.rglob('*.mp4'))
    night_movie.reconcile(worker)
    assert Task.query.count() == 1
    monkeypatch.setattr(TimelapseGenerator, 'generate', original)
    pano_frames(worker, camera, day, True, 2, 'night')
    night_movie.reconcile(worker)
    assert PanoMovie.query.one().night


def test_panorama_disabled_day_and_active_period_are_skipped(station):
    from indi_allsky.flask.models import IndiAllSkyDbPanoramaVideoTable as PanoMovie
    worker, camera, today, _ = station
    day = today - timedelta(days=1)
    pano_frames(worker, camera, day, False, 2)
    pano_frames(worker, camera, today, True, 2, 'active')
    night_movie.reconcile(worker)
    worker.config.update(FISH2PANO={'ENABLE': True}, DAYTIME_TIMELAPSE=False)
    night_movie.reconcile(worker)
    assert Task.query.count() == 0 and PanoMovie.query.count() == 0


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='ffmpeg and ffprobe required')
def test_pending_panorama_task_prevents_a_duplicate_repair(station):
    from indi_allsky.flask.models import IndiAllSkyDbPanoramaVideoTable as PanoMovie, TaskQueueQueue
    worker, camera, today, _ = station
    worker.config.update(FISH2PANO={'ENABLE': True})
    day = today - timedelta(days=1)
    pano_frames(worker, camera, day, True, 2)
    pending = Task(queue=TaskQueueQueue.VIDEO, state=TaskQueueState.QUEUED,
                   data={'action': 'generatePanoramaVideo', 'kwargs': {
                       'camera_id': camera.id, 'timespec': day.strftime('%Y%m%d'), 'night': True}})
    db.session.add(pending)
    db.session.commit()
    assert not night_movie.reconcile(worker)
    assert Task.query.count() == 1 and PanoMovie.query.count() == 0
    pending.setExpired()
    assert night_movie.reconcile(worker)
    assert not night_movie.reconcile(worker)
    assert Task.query.count() == 2 and PanoMovie.query.count() == 1


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='ffmpeg and ffprobe required')
def test_retained_panorama_is_repaired_without_extending_regular_video_lookback(station):
    from indi_allsky.flask.models import IndiAllSkyDbPanoramaVideoTable as PanoMovie, IndiAllSkyDbStateTable as State
    import json
    worker, camera, today, add_frame = station
    worker.config.update(FISH2PANO={'ENABLE': True}, IMAGE_EXPIRE_DAYS=10)
    recent = today - timedelta(days=2)
    older = today - timedelta(days=6)
    outside = today - timedelta(days=11)
    add_frame('deleted-regular.jpg', recent)
    add_frame('old-regular.jpg', older)
    add_frame('daytime-regular.jpg', recent)
    Frame.query.filter_by(filename='daytime-regular.jpg').one().night = False
    db.session.add(State(key=f'NIGHTMOVIE_{camera.id}_{recent.toordinal() % 4}',
                         value=json.dumps({'day': recent.isoformat(), 'deleted': True})))
    db.session.commit()
    pano_frames(worker, camera, older, True, 2, 'old')
    pano_frames(worker, camera, outside, True, 2, 'expired')
    # Advance past all dates in the rotating scan, including periods with no media.
    for _ in range(10):
        night_movie.reconcile(worker)
    assert PanoMovie.query.one().dayDate == older
    assert Movie.query.count() == 0
    assert Task.query.count() == 1


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='ffmpeg and ffprobe required')
def test_interrupted_panorama_encode_retries_once_after_cooldown(station, monkeypatch):
    import json
    from indi_allsky.flask.models import IndiAllSkyDbStateTable as State
    worker, camera, today, _ = station
    worker.config.update(FISH2PANO={'ENABLE': True})
    day = today - timedelta(days=1)
    pano_frames(worker, camera, day, True, 2)
    real_time = night_movie.time.time
    start = real_time()
    def stop_task(task, **kwargs):
        raise KeyboardInterrupt  # simulate power loss after committing reservation
    worker.generatePanoramaVideo = stop_task
    with pytest.raises(KeyboardInterrupt):
        night_movie.reconcile(worker)
    first = Task.query.one()
    first.setExpired()
    night_movie.reconcile(worker)
    assert Task.query.count() == 1  # cooldown
    monkeypatch.setattr(night_movie.time, 'time', lambda:start+121)
    with pytest.raises(KeyboardInterrupt):
        night_movie.reconcile(worker)
    second = Task.query.order_by(Task.id.desc()).first()
    second.setExpired()
    monkeypatch.setattr(night_movie.time, 'time', lambda:start+242)
    night_movie.reconcile(worker)
    assert Task.query.count() == 2
    record = db.session.get(State, night_movie.attempt_key(camera.id, day, True, panorama=True))
    assert json.loads(record.value)['attempt'] == 2


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='ffmpeg and ffprobe required')
@pytest.mark.parametrize('corrupt_header', [False, True])
def test_incompatible_or_corrupt_panorama_is_repaired_once(station, corrupt_header):
    from indi_allsky.flask.models import IndiAllSkyDbPanoramaVideoTable as PanoMovie
    worker, camera, today, _ = station
    worker.config.update(FISH2PANO={'ENABLE': True})
    day = today - timedelta(days=1)
    legacy = worker.image_dir / 'legacy-panorama.mp4'
    if corrupt_header:
        legacy.write_bytes(b'broken MP4')
    else:
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=s=2048x96:r=5',
                    '-frames:v', '4', '-c:v', 'libx264', '-threads', '1', str(legacy)], check=True)
    assert night_movie.playable(legacy) == (not corrupt_header)
    existing = PanoMovie(camera_id=camera.id, dayDate=day, night=True, filename=legacy.name,
                         frames=8 if corrupt_header else 4, success=True)
    db.session.add(existing)
    db.session.commit()
    watch_id = existing.id
    pano_frames(worker, camera, day, True, 4)
    assert night_movie.reconcile(worker)
    published = PanoMovie.query.one()
    assert published.id == watch_id and published.success and published.frames == 4
    assert night_movie.panorama_playable(Path(published.getFilesystemPath()))
    assert not legacy.exists()
    assert not night_movie.reconcile(worker)
    assert Task.query.count() == 1


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='ffmpeg and ffprobe required')
def test_partial_source_archive_preserves_the_longer_existing_panorama(station):
    from indi_allsky.flask.models import IndiAllSkyDbPanoramaVideoTable as PanoMovie
    worker, camera, today, _ = station
    worker.config.update(FISH2PANO={'ENABLE': True}, TIMELAPSE_SKIP_FRAMES=1)
    day = today - timedelta(days=1)
    legacy = worker.image_dir / 'original.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=s=2048x96:r=5',
                    '-frames:v', '4', '-c:v', 'libx264', '-threads', '1', str(legacy)], check=True)
    original = legacy.read_bytes()
    # Some older rows have a negative frame count; the file itself records four.
    existing = PanoMovie(camera_id=camera.id, dayDate=day, night=True, filename=legacy.name, frames=-4, success=True)
    db.session.add(existing)
    db.session.commit()
    watch_id = existing.id
    pano_frames(worker, camera, day, True, 4)
    assert night_movie.reconcile(worker)
    assert Task.query.one().state == TaskQueueState.FAILED
    assert 'Existing panorama retained' in Task.query.one().result
    assert PanoMovie.query.one().id == watch_id and PanoMovie.query.one().filename == legacy.name
    assert legacy.read_bytes() == original
    assert not night_movie.reconcile(worker)
    pano_frames(worker, camera, day, True, 1, 'restored')
    assert night_movie.reconcile(worker)
    assert PanoMovie.query.one().id == watch_id and PanoMovie.query.one().frames == 4
    assert night_movie.panorama_playable(Path(PanoMovie.query.one().getFilesystemPath()), expected_frames=4)
    assert not legacy.exists()
