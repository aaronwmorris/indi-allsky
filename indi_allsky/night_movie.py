"""Repair local night timelapses and panorama movies for completed capture dates."""
import hashlib
import json
import logging
import os
from fractions import Fraction
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import tempfile
import time

from PIL import Image

from .exceptions import TimelapseException
from .media_probe import verified_media

logger = logging.getLogger('indi_allsky')
RECENT_DAYS = 3
OLDER_DATES_PER_SCAN = 2


def attempt_key(camera_id, date, night=True, panorama=False):
    # Date-specific keys preserve independent deletion and retry decisions.
    kind = ('NIGHT' if night else 'DAY') + ('PANO' if panorama else 'MOVIE')
    return '{}_{}_{}'.format(kind, camera_id, date.strftime('%Y%m%d'))


def prior_attempt(state, date):
    if state is None:
        return {}
    try:
        record = json.loads(state.value)
    except (TypeError, ValueError):
        return {}
    return record if isinstance(record, dict) and record.get('day') == date.isoformat() else {}


def _legacy_record(camera_id, date):
    # The previous release used four rotating slots for regular nights. A
    # recorded deletion must remain effective when upgrading the station.
    from .flask import db
    from .flask.models import IndiAllSkyDbStateTable as State
    old = db.session.get(State, 'NIGHTMOVIE_{}_{}'.format(camera_id, date.toordinal() % 4))
    return prior_attempt(old, date)


def suppress_repair(camera_id, date, night=True, panorama=False):
    # A user's explicit delete wins over both scheduled and running repairs.
    from .flask import db
    from .flask.models import IndiAllSkyDbStateTable as State
    key = attempt_key(camera_id, date, night, panorama)
    state = db.session.get(State, key)
    if state is None:
        state = State(key=key)
        db.session.add(state)
    state.value = json.dumps({'day': date.isoformat(), 'deleted': True})
    state.createDate = datetime.now()
    db.session.commit()


def lock_repair(camera_id, date, token, night=True, panorama=False):
    from .flask.models import IndiAllSkyDbStateTable as State
    # Hold the same state row that explicit deletion updates until the movie
    # row is committed. This also works on SQLite without SELECT FOR UPDATE.
    return State.query.filter_by(key=attempt_key(camera_id, date, night, panorama), value=token).update(
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


def movie_inputs(source_signature, config, panorama=False):
    # A corrected codec/filter or a changed preprocessor is also a new attempt,
    # even if the source files themselves have not changed.
    options = {k: v for k, v in config.items() if k.startswith('FFMPEG_') or k in
               ('TIMELAPSE', 'TIMELAPSE_SKIP_FRAMES', 'IMAGE_FILE_TYPE')}
    if panorama:
        # Retry previous failures after upgrading the panorama encoder and checks.
        options['panorama_encoder_version'] = 1
    data = json.dumps(options, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(source_signature.encode('ascii') + b'\0' + data).hexdigest()


def readable_images(paths):
    for path in paths:
        try:
            with Image.open(path) as image:
                image.load()
        except (OSError, ValueError) as error:
            logger.warning('Skipping unreadable timelapse frame %s: %s', path, error)
            continue
        yield path


def playable(path, ffmpeg='ffmpeg', *, seek=None):
    try:
        if not path.stat().st_size:
            return False
    except FileNotFoundError:
        return False
    # Some corrupt inputs return exit status zero without emitting a frame.
    # One RGB pixel in stdout proves that an actual video frame was decoded.
    seek_options = ['-xerror', '-ss', '{:.6f}'.format(seek)] if seek is not None else []
    try:
        result = subprocess.run([
            ffmpeg, '-nostdin', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-threads', '1',
            *seek_options, '-i', str(path),
            '-map', '0:v:0', '-frames:v', '1', '-vf', 'scale=1:1', '-pix_fmt', 'rgb24',
            '-c:v', 'rawvideo', '-threads', '1', '-f', 'rawvideo', '-',
        ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        # A missing/unavailable decoder does not prove that an existing movie is corrupt.
        raise TimelapseException('Could not check timelapse with ffmpeg') from error
    return result.returncode == 0 and len(result.stdout) == 3


# H.264 Annex A limits, expressed in macroblocks per frame and per second.
_H264_LEVELS = {
    9: (99, 1485), 10: (99, 1485), 11: (396, 3000), 12: (396, 6000),
    13: (396, 11880), 20: (396, 11880), 21: (792, 19800), 22: (1620, 20250),
    30: (1620, 40500), 31: (3600, 108000), 32: (5120, 216000), 40: (8192, 245760),
    41: (8192, 245760), 42: (8704, 522240), 50: (22080, 589824), 51: (36864, 983040),
    52: (36864, 2073600), 60: (139264, 4177920), 61: (139264, 8355840), 62: (139264, 16711680),
}


def _panorama_stream(path, ffmpeg, *, count_frames=False, timeout=30):
    if not path.exists():
        return {}
    try:
        result = subprocess.run([
            str(Path(ffmpeg).with_name('ffprobe')), '-v', 'error', '-protocol_whitelist', 'file,pipe',
            '-threads', '1', '-select_streams', 'v:0', *(['-count_frames'] if count_frames else []),
            '-show_entries', 'stream=width,height,codec_name,level,avg_frame_rate,duration,nb_frames,nb_read_frames:format=duration',
            '-of', 'json', str(path),
        ], capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise TimelapseException('Could not inspect panorama with ffprobe') from error
    if result.returncode or (count_frames and result.stderr.strip()):
        return {}
    try:
        probe = json.loads(result.stdout)
        stream = probe['streams'][0]
        if not stream.get('duration') or stream['duration'] == 'N/A':
            stream['duration'] = probe['format']['duration']
        return stream
    except (KeyError, IndexError, TypeError, ValueError):
        return {}


def panorama_frames(path, ffmpeg='ffmpeg'):
    """Read the original frame count, including WebM files without a stored count."""
    stream = _panorama_stream(path, ffmpeg)
    if not stream:
        return None
    try:
        if int(stream.get('nb_frames') or 0) > 0:
            return int(stream['nb_frames'])
    except (TypeError, ValueError):
        pass
    counted = _panorama_stream(path, ffmpeg, count_frames=True, timeout=600)
    try:
        frames = int(counted['nb_read_frames'])
    except (KeyError, TypeError, ValueError):
        return None
    return frames if frames > 0 else None


def panorama_playable(path, ffmpeg='ffmpeg', *, expected_frames=None):
    """Check browser dimensions, H.264 level and the movie timeline.

    A newly encoded file must decode one frame for each retained source image.
    Existing movies use inexpensive seek checks during regular archive scans.
    """
    from .panorama import PANORAMA_VIDEO_MAX_WIDTH, PANORAMA_VIDEO_MAX_HEIGHT
    if expected_frames is None:
        stream = _panorama_stream(path, ffmpeg)
    else:
        # Count decoded frames, not just the MP4 index. WebM commonly omits nb_frames.
        stream = _panorama_stream(path, ffmpeg, count_frames=True, timeout=max(120, expected_frames // 2))
    try:
        if expected_frames is not None and int(stream['nb_read_frames']) != expected_frames:
            return False
        width, height = stream['width'], stream['height']
        if not (0 < width <= PANORAMA_VIDEO_MAX_WIDTH and 0 < height <= PANORAMA_VIDEO_MAX_HEIGHT):
            return False
        fps = Fraction(stream['avg_frame_rate'])
        duration = Fraction(stream['duration'])
        if fps <= 0 or duration <= 0:
            return False
        if stream['codec_name'] == 'h264' and stream.get('level') in _H264_LEVELS:
            max_frame, max_rate = _H264_LEVELS[stream['level']]
            mb_width, mb_height = (width + 15) // 16, (height + 15) // 16
            macroblocks = mb_width * mb_height
            if (max(mb_width, mb_height) ** 2 > 8 * max_frame or
                    macroblocks > max_frame or macroblocks * fps > max_rate):
                return False
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError):
        return False

    # Seek just before the final frame. Seeking past its presentation timestamp
    # would report no image even for a valid two-frame panorama.
    last = max(0, duration - Fraction(3, 2) / fps)
    for offset in sorted({0, min(duration / 2, last), last}):
        if not playable(path, ffmpeg, seek=float(offset)):
            return False
    return True


@contextmanager
def staged_movie(destination, ffmpeg='ffmpeg', *, panorama_frames=None):
    with tempfile.NamedTemporaryFile(prefix='.encode-', suffix=destination.suffix,
                                     dir=destination.parent, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        yield temporary
        verified = (playable(temporary, ffmpeg) if panorama_frames is None else
                    panorama_playable(temporary, ffmpeg, expected_frames=panorama_frames))
        if not verified:
            raise TimelapseException('Encoded timelapse failed video validation')
        # The next database commit publishes this unique filename. Readers of
        # the old row keep their old movie until the replacement is complete.
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _repair_movie(worker, camera, date, night, panorama, frame_model, movie_model):
    from sqlalchemy.exc import IntegrityError
    from .archive_health import archive_paused, DEFERRED
    from .flask import db
    from .flask.models import (IndiAllSkyDbStateTable as State, IndiAllSkyDbTaskQueueTable as Task,
                               TaskQueueQueue, TaskQueueState)

    movies = movie_model.query.filter_by(camera_id=camera.id, dayDate=date, night=night).all()
    # Remote-only assets and ambiguous duplicate rows need operator review.
    if len(movies) > 1 or any(movie.remote_url or movie.s3_key for movie in movies):
        return False
    if movies:
        path = Path(movies[0].getFilesystemPath())
        if verified_media(path, panorama_playable if panorama else playable):
            if not movies[0].success:
                movies[0].success = True
                movies[0].fileSize = path.stat().st_size
                db.session.commit()
            return False
    key = attempt_key(camera.id, date, night, panorama)
    state = db.session.get(State, key)
    prior = prior_attempt(state, date)
    if not prior and night and not panorama:
        prior = _legacy_record(camera.id, date)
    if prior.get('deleted'):
        return False

    entries = frame_model.query.filter_by(camera_id=camera.id, dayDate=date, night=night, exclude=False)
    skip = worker.config.get('TIMELAPSE_SKIP_FRAMES', 4)
    signature, sources = local_sources(entries.order_by(frame_model.id), skip)
    signature = movie_inputs(signature, worker.config, panorama=panorama)
    if not movies and not sources and not entries.first():
        return False  # there is no evidence this camera recorded this product
    failures = 0
    if prior.get('source') == signature and prior.get('result'):
        # A normal failure is final until the sources change. Only an interrupted
        # encode gets one extra attempt once the supervisor expires its task.
        previous = db.session.get(Task, prior['task_id']) if prior.get('task_id') else None
        failures = prior.get('attempt', 1)
        interrupted = (previous.state == TaskQueueState.EXPIRED if previous else
                       'repair started;' in prior.get('result', ''))
        elapsed = time.time() - prior.get('started_at', 0)
        if not interrupted or failures >= 2:
            return False
        if 0 <= elapsed < 120:
            return True  # recheck in a minute, after the short restart cooldown
    if archive_paused(worker.config):
        return False

    action = 'generatePanoramaVideo' if panorama else 'generateVideo'
    label = ('Night' if night else 'Day') + (' panorama' if panorama else ' timelapse')
    args = dict(camera_id=camera.id, timespec=date.strftime('%Y%m%d'), night=night, repair=True)
    task = Task(queue=TaskQueueQueue.VIDEO, state=TaskQueueState.RUNNING,
                data={'action': action, 'kwargs': args})
    db.session.add(task)
    db.session.flush()
    record = {'day': date.isoformat(), 'source': signature, 'task_id': task.id, 'attempt': failures + 1,
              'started_at': int(time.time()),
              'result': '{} repair started; no completed replacement has been published.'.format(label)}
    token = json.dumps(record)
    if state is None:
        db.session.add(State(key=key, value=token))
    else:
        changed = State.query.filter_by(key=key, value=state.value).update(
            {'value': token, 'createDate': datetime.now()}, synchronize_session=False)
        if not changed:
            db.session.rollback()
            return False
    try:
        db.session.commit()  # reserve the attempt before encoding
    except IntegrityError:
        db.session.rollback()
        return False
    try:
        if len(sources) <= skip:
            task.setFailed('{} {}: insufficient local source images ({} available, {} skipped).'.format(
                label, date, len(sources), skip))
        else:
            getattr(worker, action)(task, repair_token=token, **args)
    except Exception:
        logger.exception('%s repair failed for %s', label, date)
        db.session.rollback()
        # Publication commits before export. Do not downgrade an already-published movie.
        if task.state != TaskQueueState.SUCCESS:
            task.setFailed('{} {}: repair failed; inspect the video worker log.'.format(label, date))
    record['result'] = '' if task.state == TaskQueueState.SUCCESS else task.result
    if record['result'] and (record['result'] == DEFERRED or archive_paused(worker.config)):
        record.pop('source')  # storage outages do not consume an encoding attempt
    State.query.filter_by(key=key, value=token).update({'value': json.dumps(record)}, synchronize_session=False)
    db.session.commit()
    return len(sources) > skip


def reconcile(worker):
    """Process at most one expensive product. Return true to revisit a backlog soon."""
    from sqlalchemy.orm.exc import NoResultFound
    from .archive_health import archive_paused
    from .flask.models import (IndiAllSkyDbCameraTable as Camera, IndiAllSkyDbImageTable as Frame,
        IndiAllSkyDbVideoTable as Movie, IndiAllSkyDbPanoramaImageTable as PanoFrame,
        IndiAllSkyDbPanoramaVideoTable as PanoMovie, IndiAllSkyDbTaskQueueTable as Task,
        TaskQueueQueue, TaskQueueState)
    from .utils import IndiAllSkyDateCalcs

    config = worker.config
    if (not config.get('TIMELAPSE_ENABLE', True) or config.get('CAPTURE_PAUSE')
            or config.get('FOCUS_MODE') or archive_paused(config)):
        return False
    try:
        camera_id = int(worker._miscDb.getState('DB_CAMERA_ID'))
    except (NoResultFound, ValueError, TypeError):
        return False
    camera = Camera.query.filter_by(id=camera_id, local=True, hidden=False).first()
    if not camera or camera.latitude is None or camera.longitude is None:
        return False
    today = IndiAllSkyDateCalcs(config, [camera.latitude, camera.longitude, camera.elevation or 0]).getDayDate()
    days = min(config.get('IMAGE_EXPIRE_DAYS', 10), config.get('TIMELAPSE_EXPIRE_DAYS', 365))
    if days <= 0:
        return False
    cutoff = today - timedelta(days=days)
    outstanding = set()
    for task in Task.query.filter(Task.queue == TaskQueueQueue.VIDEO, Task.state.in_(
            (TaskQueueState.QUEUED, TaskQueueState.RUNNING, TaskQueueState.MANUAL))):
        data = task.data or {}
        args = data.get('kwargs', {})
        if args.get('camera_id') == camera.id:
            outstanding.add((data.get('action'), args.get('timespec'), bool(args.get('night'))))

    pano_enabled = config.get('FISH2PANO', {}).get('ENABLE', False)
    day_pano = (config.get('DAYTIME_CAPTURE', True) and config.get('DAYTIME_CAPTURE_SAVE', True)
                and config.get('DAYTIME_TIMELAPSE', True))
    checked = set()

    def check(date, night, panorama):
        identity = (date, night, panorama)
        if identity in checked:
            return False
        checked.add(identity)
        action = 'generatePanoramaVideo' if panorama else 'generateVideo'
        if (action, date.strftime('%Y%m%d'), night) in outstanding:
            return False
        if worker._shutdown or archive_paused(config):
            return False
        return _repair_movie(worker, camera, date, night, panorama,
                             PanoFrame if panorama else Frame, PanoMovie if panorama else Movie)

    def check_panoramas(date):
        return check(date, True, True) or (day_pano and check(date, False, True))

    if pano_enabled:
        # Reuse a failed panorama's watch ID before creating missing movies.
        failed = PanoMovie.query.filter_by(camera_id=camera.id, success=False).filter(
            PanoMovie.dayDate >= cutoff, PanoMovie.dayDate < today)
        if not day_pano:
            failed = failed.filter(PanoMovie.night.is_(True))
        for candidate in failed.order_by(PanoMovie.dayDate.desc()).limit(2):
            if check(candidate.dayDate, candidate.night, True):
                return True

    for offset in range(1, min(RECENT_DAYS, days) + 1):
        if worker._shutdown or archive_paused(config):
            return False
        date = today - timedelta(days=offset)
        if check(date, True, False) or (pano_enabled and check_panoramas(date)):
            return True

    if not pano_enabled or days <= RECENT_DAYS or worker._shutdown:
        return False

    # Rotate through older panorama dates with known sources or movies. The
    # regular night timelapse recovery above keeps its three-night window.
    from .flask import db
    from .flask.models import IndiAllSkyDbStateTable as State
    cursor_key = 'PANOSCAN_' + str(camera.id)
    cursor = db.session.get(State, cursor_key)
    end = today - timedelta(days=RECENT_DAYS)

    def older_dates(before):
        dates = set()
        for model in (PanoMovie, PanoFrame):
            query = model.query.with_entities(model.dayDate).filter(
                model.camera_id == camera.id, model.dayDate >= cutoff, model.dayDate < before)
            if not day_pano:
                query = query.filter(model.night.is_(True))
            dates.update(row[0] for row in query.distinct().order_by(model.dayDate.desc()).limit(OLDER_DATES_PER_SCAN))
        return sorted(dates, reverse=True)[:OLDER_DATES_PER_SCAN]

    before = end
    if cursor is not None:
        try:
            before = min(end, datetime.strptime(cursor.value, '%Y%m%d').date())
        except (TypeError, ValueError):
            pass
    older = older_dates(before)
    if not older and before != end:
        older = older_dates(end)
    for date in older:
        if worker._shutdown or archive_paused(config):
            return False
        if cursor is None:
            cursor = State(key=cursor_key)
            db.session.add(cursor)
        cursor.value = date.strftime('%Y%m%d')
        cursor.createDate = datetime.now()
        db.session.commit()
        if check_panoramas(date):
            return True
    return False
