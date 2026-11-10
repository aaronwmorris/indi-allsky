from types import SimpleNamespace
from queue import Queue
from flask import Flask
from indi_allsky.allsky import IndiAllSky
from indi_allsky.video import VideoWorker
from indi_allsky.uploader import FileUploader
from indi_allsky.archive_health import ArchiveMonitor, BLOCKED, DEFERRED, LOW, OK
from indi_allsky.flask import db
from indi_allsky.flask.models import IndiAllSkyDbTaskQueueTable as Task, TaskQueueQueue as Q, TaskQueueState as S


def test_video_and_upload_tasks_survive_low_space_and_restart(tmp_path):
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app)
    cfg = {'VARLIB_FOLDER': str(tmp_path), 'IMAGE_FOLDER': str(tmp_path)}
    archive = ArchiveMonitor(cfg)
    boss = SimpleNamespace(archive_monitor=archive, video_q=Queue(), upload_q=Queue())
    with app.app_context():
        Task.__table__.create(db.engine)
        video = Task(queue=Q.VIDEO, state=S.QUEUED, data={'action':'generateVideo'})
        upload = Task(queue=Q.UPLOAD, state=S.QUEUED, data={'action':1})
        db.session.add_all([video, upload])
        db.session.commit()
        archive.publish(LOW, 'reserve', '/')
        worker = SimpleNamespace(config=cfg)
        VideoWorker.processTask(worker, {'task_id':video.id})
        FileUploader.processUpload(worker, {'task_id':upload.id})
        assert all(t.state == S.MANUAL and t.result == DEFERRED for t in (video, upload))
        IndiAllSky._expireOrphanedTasks(boss)
        IndiAllSky._queueManualTasks(boss)
        assert boss.video_q.empty() and boss.upload_q.empty()
        archive.publish(OK, 'ok', '/')
        IndiAllSky._queueManualTasks(boss)
        assert boss.video_q.get_nowait()['task_id'] == video.id
        assert boss.upload_q.get_nowait()['task_id'] == upload.id
        assert all(t.state == S.QUEUED for t in (video, upload))


def test_cleanup_waits_if_archive_device_changes(tmp_path):
    from indi_allsky.archive_health import require_writable_archive, ArchiveUnavailable
    import os
    import pytest
    cfg = {'VARLIB_FOLDER': str(tmp_path), 'IMAGE_FOLDER': str(tmp_path)}
    monitor = ArchiveMonitor(cfg)
    monitor.device = os.stat(tmp_path).st_dev
    monitor.publish(LOW, 'reserve', '/')
    require_writable_archive(cfg)  # configured retention can free space
    monitor.device += 1  # same path now refers to a different device
    monitor.publish(OK, 'ok', '/')
    with pytest.raises(ArchiveUnavailable):
        require_writable_archive(cfg)
