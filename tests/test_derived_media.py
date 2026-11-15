"""Recovery of only the absent products from a completed camera period."""
from datetime import datetime, date, timedelta
import errno
from pathlib import Path
import shutil
from unittest.mock import Mock

from flask import Flask
from PIL import Image
import pytest
from indi_allsky import derived_media as media
from indi_allsky.archive_health import ArchiveMonitor, OK, LOW
from indi_allsky.config import IndiAllSkyConfigBase
from indi_allsky.flask import db
from indi_allsky.flask.miscDb import miscDb
from indi_allsky.flask.models import (IndiAllSkyDbCameraTable as Camera, IndiAllSkyDbImageTable as Frame,
    IndiAllSkyDbKeogramTable as Keogram, IndiAllSkyDbStarTrailsTable as Startrail,
    IndiAllSkyDbStarTrailsVideoTable as StarMovie, IndiAllSkyDbTaskQueueTable as Task)
from indi_allsky.timelapse import TimelapseGenerator
from indi_allsky.video import VideoWorker


@pytest.fixture
def station(tmp_path, monkeypatch):
    if ffmpeg := shutil.which('ffmpeg'):
        monkeypatch.setattr(TimelapseGenerator, 'ffmpeg_bin', ffmpeg)
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', INDI_ALLSKY_IMAGE_FOLDER=str(tmp_path))
    db.init_app(app)
    with app.app_context():
        db.create_all()
        camera = Camera(name='local camera', uuid='test-local', latitude=40., longitude=2., local=True,
                        lensFocalLength=2.8, lensFocalRatio=1.4, lensName='Test')
        other = Camera(name='other', uuid='other-camera', local=False)
        db.session.add_all([camera,other])
        db.session.commit()
        worker = VideoWorker.__new__(VideoWorker)
        worker._shutdown = False
        worker.binning_av = [1,1,1]
        worker.config = dict(IndiAllSkyConfigBase._base_config, TIMELAPSE_SKIP_FRAMES=4,
            IMAGE_FOLDER=str(tmp_path), VARLIB_FOLDER=str(tmp_path), IMAGE_FILE_TYPE='jpg',
            KEOGRAM_ANGLE=0, KEOGRAM_LABEL=False, KEOGRAM_H_SCALE=100, KEOGRAM_V_SCALE=100,
            FFMPEG_CODEC='libx264', DAYTIME_TIMELAPSE=True, STARTRAILS_TIMELAPSE_MINFRAMES=250)
        worker.image_dir = tmp_path
        worker._miscDb = miscDb(worker.config)
        worker._miscUpload = Mock()
        monitor = ArchiveMonitor(worker.config)
        monitor.device = tmp_path.stat().st_dev
        monitor.publish(OK, 'ok', '/')
        day = date.today() - timedelta(days=2)
        def frames(n=6, cam=None, *, night=False):
            cam = cam or camera
            for i in range(n):
                name = f'{cam.id}-{night}-{i}.jpg'
                p = tmp_path/name
                Image.new('RGB', (240,160), (11+i,12,13)).save(p)
                db.session.add(Frame(camera_id=cam.id,dayDate=day,night=night,filename=name,
                    createDate=datetime.combine(day,datetime.min.time())+timedelta(seconds=i),
                    exposure=1,gain=1,adu=12,binmode=1,stars=10))
            db.session.commit()
        yield worker,camera,other,day,monitor,frames


def test_six_day_frames_generate_a_real_keogram_and_thumbnail(station, monkeypatch):
    w,c,other,day,monitor,frames=station
    samples = []
    original = w.activity.progress
    def progress(*args):
        samples.append(args)
        original(*args)
    monkeypatch.setattr(w.activity, 'progress', progress)
    frames(9, other)
    assert not media.reconcile(w,c,day,False)
    frames()
    assert media.reconcile(w,c,day,False)
    row=Keogram.query.one()
    assert row.camera_id==c.id and not row.night and row.success
    assert row.frames==2 and row.thumbnail_uuid
    assert ('Stacking frames', 0, 6) in samples
    assert ('Stacking frames', 6, 6) in samples
    with Image.open(row.getFilesystemPath()) as image: assert image.size[0]>=2
    assert not Startrail.query.count() and not StarMovie.query.count()
    assert not media.reconcile(w,c,day,False)


def test_corrupt_keogram_repaired_without_touching_valid_sibling(station):
    w,c,_,day,monitor,frames=station
    frames(night=True)
    old=w.image_dir/'broken.jpg'
    old.write_bytes(b'bad')
    kg=Keogram(camera_id=c.id,dayDate=day,night=True,filename=old.name)
    good=w.image_dir/'trail.jpg'
    Image.new('RGB',(24,24),'green').save(good)
    trail=Startrail(camera_id=c.id,dayDate=day,night=True,filename=good.name,success=True)
    db.session.add_all([kg,trail])
    db.session.commit()
    k_id,old_bytes=kg.id,good.read_bytes()
    assert media.reconcile(w,c,day,True)
    kg=Keogram.query.one()
    assert kg.id==k_id and kg.success and kg.filename!=old.name
    assert Startrail.query.one().filename==good.name and good.read_bytes()==old_bytes
    assert not StarMovie.query.count()  # less than configured minimum


def test_user_deletion_during_encoding_and_storage_pause(station,monkeypatch):
    w,c,_,day,monitor,frames=station
    frames()
    monitor.publish(LOW,'reserve','/')
    assert not media.reconcile(w,c,day,False)
    assert not Task.query.count()
    monitor.publish(OK,'ok','/')
    render=media.render
    def deleted(*args):
        finished=render(*args)
        media.suppress_repair(c.id,day,False)
        return finished
    monkeypatch.setattr(media,'render',deleted)
    media.reconcile(w,c,day,False)
    assert not Keogram.query.count()
    assert not media.reconcile(w,c,day,False)


def test_unusable_sources_retry_only_when_changed(station):
    w,c,_,day,monitor,frames=station
    frames(1)
    assert not media.reconcile(w,c,day,False)
    assert Task.query.count()==1
    assert not media.reconcile(w,c,day,False)
    assert Task.query.count()==1


def test_dead_worker_resumes_one_interrupted_render(station,monkeypatch):
    w,c,_,day,monitor,frames=station
    frames()
    render=media.render
    def interrupted(*args):
        raise KeyboardInterrupt
    monkeypatch.setattr(media,'render',interrupted)
    with pytest.raises(KeyboardInterrupt):
        media.reconcile(w,c,day,False)
    assert not Keogram.query.count()
    monkeypatch.setattr(media,'render',render)
    assert media.reconcile(w,c,day,False)
    assert Keogram.query.one().success
    assert not media.reconcile(w,c,day,False)



def test_deleting_one_asset_still_repairs_its_sibling(station):
    w,c,_,day,_,frames=station
    frames(night=True)
    media.suppress_repair(c.id,day,True,'startrail')
    assert media.reconcile(w,c,day,True)
    assert Keogram.query.one().success and not Startrail.query.count()
    assert not media.reconcile(w,c,day,True)


def test_eligible_sky_frames_produce_a_decodable_startrail_movie(station):
    from indi_allsky import night_movie
    w,c,_,day,_,frames=station
    w.config.update(STARTRAILS_SUN_ALT_THOLD=91, STARTRAILS_MOONMODE_THOLD=False,
                    STARTRAILS_MOON_ALT_THOLD=91, STARTRAILS_MOON_PHASE_THOLD=101,
                    STARTRAILS_MAX_ADU=255, STARTRAILS_MIN_STARS=0, STARTRAILS_PIXEL_THOLD=100,
                    STARTRAILS_TIMELAPSE=True, STARTRAILS_TIMELAPSE_MINFRAMES=2)
    frames(8,night=True)
    assert media.reconcile(w,c,day,True)
    trail=Startrail.query.one()
    movie=StarMovie.query.one()
    assert trail.frames==movie.frames==4 and movie.success
    assert night_movie.playable(Path(movie.getFilesystemPath()))
    assert not media.reconcile(w,c,day,True)


def test_a_failed_startrail_encode_preserves_the_finished_stills(station,monkeypatch):
    from indi_allsky.exceptions import TimelapseException
    from indi_allsky.timelapse import TimelapseGenerator
    w,c,_,day,_,frames=station
    w.config.update(STARTRAILS_SUN_ALT_THOLD=91, STARTRAILS_MOONMODE_THOLD=False,
                    STARTRAILS_MOON_ALT_THOLD=91, STARTRAILS_MOON_PHASE_THOLD=101,
                    STARTRAILS_MAX_ADU=255, STARTRAILS_MIN_STARS=0, STARTRAILS_PIXEL_THOLD=100,
                    STARTRAILS_TIMELAPSE=True, STARTRAILS_TIMELAPSE_MINFRAMES=2)
    frames(8,night=True)
    def fail_encode(self, *args):
        raise TimelapseException('synthetic encoder failure')
    monkeypatch.setattr(TimelapseGenerator, 'generate', fail_encode)
    assert media.reconcile(w,c,day,True)
    assert Keogram.query.one().success and Startrail.query.one().success and not StarMovie.query.count()
    assert not media.reconcile(w,c,day,True)

@pytest.mark.parametrize('remove_all', [False, True])
def test_scheduled_stack_survives_sources_expiring_after_decode(station, monkeypatch, remove_all):
    worker, camera, _, day, _, add_frames = station
    add_frames(8)
    task = Mock()
    original_read = media.read_frame
    keogram = media.make_keogram(worker.config, worker.config['TIMELAPSE_SKIP_FRAMES'])
    monkeypatch.setattr(media, 'make_keogram', lambda *args: keogram)
    expired = worker.image_dir / f'{camera.id}-False-4.jpg'
    progress = []
    original_progress = worker.activity.progress

    def remove_after_read(path):
        image = original_read(path)
        if remove_all or path == expired:
            path.unlink()
        return image

    def record_progress(*sample):
        progress.append(sample)
        original_progress(*sample)

    monkeypatch.setattr(media, 'read_frame', remove_after_read)
    monkeypatch.setattr(worker.activity, 'progress', record_progress)
    worker.generateKeogramStarTrails(task, camera_id=camera.id, timespec=day.strftime('%Y%m%d'), night=False)
    assert ('Stacking frames', 0, 8) in progress and ('Stacking frames', 8, 8) in progress
    product = Keogram.query.one()
    if remove_all:
        task.setFailed.assert_called_once()
        assert not product.success
    else:
        task.setSuccess.assert_called_once()
        # Four valid inputs are skipped and the fifth expired after decoding.
        assert product.success and len(keogram.timestamps) == 3
        with Image.open(product.getFilesystemPath()) as image:
            image.verify()


def test_scheduled_stack_reports_storage_error_after_decode(station, monkeypatch):
    worker, camera, _, day, _, add_frames = station
    add_frames(6)
    original_read, original_stat = media.read_frame, Path.stat
    failed = None

    def fail_next_stat(path):
        nonlocal failed
        image = original_read(path)
        failed = path
        return image

    def stat(path, *args, **kwargs):
        if path == failed:
            raise OSError(errno.EIO, 'archive read failed', str(path))
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(media, 'read_frame', fail_next_stat)
    monkeypatch.setattr(Path, 'stat', stat)
    with pytest.raises(OSError) as exc:
        worker.generateKeogramStarTrails(Mock(), camera_id=camera.id, timespec=day.strftime('%Y%m%d'), night=False)
    assert exc.value.errno == errno.EIO
