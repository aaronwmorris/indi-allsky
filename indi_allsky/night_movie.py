"""Bounded repair of regular, locally recorded night timelapses."""
import hashlib
import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import tempfile

from PIL import Image

from .exceptions import TimelapseException

logger = logging.getLogger('indi_allsky')
LOOKBACK = 3


def attempt_key(camera_id, date):
    # Reuse slots. A state row outlives the task queue's three-day retention.
    return 'NIGHTMOVIE_{}_{}'.format(camera_id, date.toordinal() % (LOOKBACK + 1))


def prior_attempt(state, date):
    if state is None:
        return {}
    try:
        record = json.loads(state.value)
    except (TypeError, ValueError):
        return {}
    return record if isinstance(record, dict) and record.get('day') == date.isoformat() else {}


def suppress_repair(camera_id, date):
    # A user's explicit delete wins over both scheduled and running repairs.
    if not 0 <= (datetime.now().date() - date).days <= LOOKBACK + 1:
        return
    from .flask import db
    from .flask.models import IndiAllSkyDbStateTable as State
    key = attempt_key(camera_id, date)
    state = db.session.get(State, key)
    # An older deletion must not overwrite another recent date sharing this slot.
    if state:
        try:
            if json.loads(state.value).get('day', '') > date.isoformat():
                return
        except (ValueError, TypeError):
            pass
    else:
        state = State(key=key)
        db.session.add(state)
    state.value = json.dumps({'day': date.isoformat(), 'deleted': True})
    state.createDate = datetime.now()
    db.session.commit()


def lock_repair(camera_id, date, token):
    from .flask.models import IndiAllSkyDbStateTable as State
    # Hold the same state row that explicit deletion updates until the movie
    # row is committed. This also works on SQLite without SELECT FOR UPDATE.
    return State.query.filter_by(key=attempt_key(camera_id, date), value=token).update(
        {'value': token}, synchronize_session=False) == 1


def local_sources(entries, skip):
    digest = hashlib.sha256(str(skip).encode('ascii'))
    paths = []
    for entry in entries:
        path = Path(entry.getFilesystemPath())
        try:
            stamp = path.stat()
        except FileNotFoundError:
            continue
        if stamp.st_size:
            digest.update(str((entry.id, str(path), stamp.st_size, stamp.st_mtime_ns)).encode('utf-8'))
            paths.append(path)
    return digest.hexdigest(), paths


def readable_images(paths):
    for path in paths:
        try:
            with Image.open(path) as image:
                image.load()
        except (OSError, ValueError) as error:
            logger.warning('Skipping unreadable timelapse frame %s: %s', path, error)
            continue
        yield path


def playable(path, ffmpeg='ffmpeg'):
    try:
        if not path.stat().st_size:
            return False
    except FileNotFoundError:
        return False
    # Some corrupt inputs return exit status zero without emitting a frame.
    # One RGB pixel in stdout proves that an actual video frame was decoded.
    try:
        result = subprocess.run([
            ffmpeg, '-nostdin', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-threads', '1', '-i', str(path),
            '-map', '0:v:0', '-frames:v', '1', '-vf', 'scale=1:1', '-pix_fmt', 'rgb24',
            '-c:v', 'rawvideo', '-threads', '1', '-f', 'rawvideo', '-',
        ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        # A missing/unavailable decoder does not prove that an existing movie is corrupt.
        raise TimelapseException('Could not check timelapse with ffmpeg') from error
    return result.returncode == 0 and len(result.stdout) == 3


@contextmanager
def staged_movie(destination, ffmpeg='ffmpeg'):
    with tempfile.NamedTemporaryFile(prefix='.encode-', suffix=destination.suffix,
                                     dir=destination.parent, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        yield temporary
        if not playable(temporary, ffmpeg):
            raise TimelapseException('Encoded timelapse contains no decodable video frame')
        # The next database commit publishes this unique filename. Readers of
        # the old row keep their old movie until the replacement is complete.
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def reconcile(worker):
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm.exc import NoResultFound
    from .archive_health import archive_paused, DEFERRED
    from .flask import db
    from .flask.models import (
        IndiAllSkyDbCameraTable as Camera, IndiAllSkyDbImageTable as Frame,
        IndiAllSkyDbStateTable as State, IndiAllSkyDbTaskQueueTable as Task,
        IndiAllSkyDbVideoTable as Movie, TaskQueueQueue, TaskQueueState,
    )
    from .utils import IndiAllSkyDateCalcs

    config = worker.config
    if (not config.get('TIMELAPSE_ENABLE', True) or config.get('CAPTURE_PAUSE')
            or config.get('FOCUS_MODE') or archive_paused(config)):
        return
    try:
        camera_id = int(worker._miscDb.getState('DB_CAMERA_ID'))
    except (NoResultFound, ValueError, TypeError):
        return
    camera = Camera.query.filter_by(id=camera_id, local=True, hidden=False).first()
    if not camera or camera.latitude is None or camera.longitude is None:
        return
    today = IndiAllSkyDateCalcs(config, [camera.latitude, camera.longitude, camera.elevation or 0]).getDayDate()
    days = min(LOOKBACK, config.get('IMAGE_EXPIRE_DAYS', 10), config.get('TIMELAPSE_EXPIRE_DAYS', 365))
    outstanding = set()
    for task in Task.query.filter(Task.queue == TaskQueueQueue.VIDEO, Task.state.in_(
            (TaskQueueState.QUEUED, TaskQueueState.RUNNING, TaskQueueState.MANUAL))):
        data = task.data or {}
        if data.get('action') == 'generateVideo':
            args = data.get('kwargs', {})
            if args.get('camera_id') == camera.id and args.get('night'):
                outstanding.add(args.get('timespec'))

    for offset in range(1, days + 1):
        if worker._shutdown:
            return
        date = today - timedelta(days=offset)
        timespec = date.strftime('%Y%m%d')
        if timespec in outstanding:
            continue
        movies = Movie.query.filter_by(camera_id=camera.id, dayDate=date, night=True).all()
        # Remote-only assets and ambiguous duplicate rows need operator review.
        if len(movies) > 1 or any(movie.remote_url or movie.s3_key for movie in movies):
            continue
        if movies and playable(Path(movies[0].getFilesystemPath())):
            continue
        entries = Frame.query.filter_by(camera_id=camera.id, dayDate=date, night=True, exclude=False).order_by(Frame.id)
        skip = config.get('TIMELAPSE_SKIP_FRAMES', 4)
        signature, sources = local_sources(entries, skip)
        if not movies and not sources and not entries.first():
            # No evidence this camera ever recorded a night on this date.
            continue
        key = attempt_key(camera.id, date)
        state = db.session.get(State, key)
        prior = prior_attempt(state, date)
        if prior.get('deleted') or prior.get('source') == signature:
            continue
        if archive_paused(config):
            return
        args = dict(camera_id=camera.id, timespec=timespec, night=True, repair=True)
        task = Task(queue=TaskQueueQueue.VIDEO, state=TaskQueueState.RUNNING,
                    data={'action': 'generateVideo', 'kwargs': args})
        record = {'day': date.isoformat(), 'source': signature,
                  'result': 'Night timelapse repair started; no completed replacement has been published.'}
        token = json.dumps(record)
        if state is None:
            db.session.add(State(key=key, value=token))
        else:
            changed = State.query.filter_by(key=key, value=state.value).update(
                {'value': token, 'createDate': datetime.now()}, synchronize_session=False)
            if not changed:
                db.session.rollback()
                continue
        db.session.add(task)
        try:
            db.session.commit()  # remember the attempt even if the service dies during encoding
        except IntegrityError:
            db.session.rollback()
            continue
        try:
            if len(sources) <= skip:
                task.setFailed('Night {}: insufficient local source images ({} available, {} skipped).'.format(
                    date, len(sources), skip))
            else:
                worker.generateVideo(task, repair_token=token, **args)
        except Exception:
            logger.exception('Night timelapse repair failed for %s', date)
            db.session.rollback()
            # Publication is committed before upload/export. An export issue
            # must not mark the now-playable local recording as damaged.
            if task.state != TaskQueueState.SUCCESS:
                task.setFailed('Night {}: timelapse repair failed; inspect the video worker log.'.format(date))
        record['result'] = '' if task.state == TaskQueueState.SUCCESS else task.result
        if record['result'] and (record['result'] == DEFERRED or archive_paused(config)):
            record.pop('source')  # a storage outage is not a used encoding attempt
        State.query.filter_by(key=key, value=token).update({'value': json.dumps(record)}, synchronize_session=False)
        db.session.commit()
        if len(sources) > skip:
            break  # at most one expensive encode per pass, even on failure
