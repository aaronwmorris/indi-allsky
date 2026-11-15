"""Rebuild only missing keograms and star-trail products of a completed period."""
from contextlib import contextmanager
from datetime import datetime
from importlib import import_module
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile
import uuid

import cv2
from PIL import Image, UnidentifiedImageError

from . import constants
from .archive_health import archive_paused, require_writable_archive, storage_errno
from . import night_movie
from .media_probe import verified_media
from .exceptions import KeogramMismatchException, TimelapseException

# A station with per-exposure orientation processes repairs in the same coordinates
# as scheduled products. Older installations stack their original camera pixels.
try:
    aligned_media = import_module('.aligned_media', __package__)
except ModuleNotFoundError as exc:
    if exc.name != __package__ + '.aligned_media':
        raise
    aligned_media = None

logger = logging.getLogger('indi_allsky')


def make_keogram(config, skip):
    from .keogram import KeogramGenerator
    kg = KeogramGenerator(config, skip_frames=skip)
    kg.angle = config.get('KEOGRAM_ANGLE', 0.0)
    kg.h_scale_factor = config.get('KEOGRAM_H_SCALE', 100)
    kg.v_scale_factor = config.get('KEOGRAM_V_SCALE', 33)
    kg.crop_top = config.get('KEOGRAM_CROP_TOP', 0)
    kg.crop_bottom = config.get('KEOGRAM_CROP_BOTTOM', 0)
    kg.label = config.get('KEOGRAM_LABEL', True)
    return kg


def make_startrails(config, skip, camera, mask):
    from .starTrails import StarTrailGenerator
    stg = StarTrailGenerator(config, skip_frames=skip, mask=mask)
    stg.max_adu = config['STARTRAILS_MAX_ADU']
    stg.mask_threshold = config['STARTRAILS_MASK_THOLD']
    stg.pixel_cutoff_threshold = config['STARTRAILS_PIXEL_THOLD']
    stg.min_stars = config.get('STARTRAILS_MIN_STARS', 0)
    stg.latitude = camera.latitude
    stg.longitude = camera.longitude
    stg.sun_alt_threshold = config['STARTRAILS_SUN_ALT_THOLD']
    if config['STARTRAILS_MOONMODE_THOLD']:
        stg.moonmode_alt = config['NIGHT_MOONMODE_ALT_DEG']
        stg.moonmode_phase = config['NIGHT_MOONMODE_PHASE']
    else:
        stg.moon_alt_threshold = config['STARTRAILS_MOON_ALT_THOLD']
        stg.moon_phase_threshold = config['STARTRAILS_MOON_PHASE_THOLD']
    return stg


def read_frame(path):
    if path.suffix.lower() in ('.jpg', '.jpeg'):
        import simplejpeg
        with path.open('rb') as stream:
            return simplejpeg.decode_jpeg(stream.read(), colorspace='BGR')
    if path.suffix.lower() == '.png':
        return cv2.imread(str(path), cv2.IMREAD_COLOR)
    import numpy
    with Image.open(path) as image:
        return cv2.cvtColor(numpy.array(image), cv2.COLOR_RGB2BGR)


def stack_entries(entries):
    """Select one coordinate system and count the rows before processing the stack."""
    if aligned_media is None:
        return entries, entries.count()
    from .flask.models import IndiAllSkyDbImageTable
    return aligned_media.stack_entries(entries, IndiAllSkyDbImageTable)


def process_frames(config, entries, kg, stg, checkpoint=None):
    """Use the same ordered sources, skip and quality filters as normal generation."""
    remap = aligned_media.SkyRemap() if aligned_media is not None else None
    for i, entry in enumerate(entries):
        if i % 50 == 0:
            logger.info('Processing frame %d for keogram / star trails', i)
            if checkpoint is not None:
                checkpoint()
        path = Path(entry.getFilesystemPath())
        try:
            if not path.stat().st_size:
                continue
            data = read_frame(path)
        except (OSError, ValueError, cv2.error) as exc:
            if isinstance(exc, OSError) and exc.errno is not None and not isinstance(exc, FileNotFoundError):
                raise
            logger.warning('Skipping unavailable image %s: %s', path, exc)
            continue
        if data is None:
            continue
        try:
            if remap is not None:
                aligned_media.process_stack_frame(entry, path, data, remap, kg, stg,
                                                  config.get('STARTRAILS_USE_DB_DATA', True))
                continue
            if kg is not None:
                try:
                    kg.processImage(data, path.stat().st_mtime)
                except KeogramMismatchException as exc:
                    logger.warning('Skipping incompatible keogram image: %s', exc)
            if stg is not None:
                saved = config.get('STARTRAILS_USE_DB_DATA', True)
                stg.processImage(path, data, entry.binmode, adu=entry.adu if saved else None,
                                 star_count=entry.stars if saved else None)
        except FileNotFoundError as exc:
            # A source may expire after decoding. Missing output or scratch
            # directories are storage errors and must still reach the caller.
            if exc.filename != str(path):
                raise
            logger.warning('Source image disappeared while stacking: %s', path)


def key(camera_id, date, night):
    return 'DERIVED_{}_{}_{}'.format(camera_id, date.strftime('%Y%m%d'), int(night))


KINDS = ('keogram', 'startrail', 'startrail_timelapse')


def suppress_repair(camera_id, date, night, kind=None):
    """Persist an explicit group or individual deletion before deleting its row."""
    from sqlalchemy.exc import IntegrityError
    from .flask import db
    from .flask.models import IndiAllSkyDbStateTable as State
    if kind is not None and kind not in KINDS:
        raise ValueError('Unknown derived media type')
    name = key(camera_id, date, night)
    for _ in range(5):
        row = db.session.get(State, name)
        record = night_movie.prior_attempt(row, date)
        record['day'] = date.isoformat()
        if kind is None:
            record['deleted'] = True
        else:
            record['deleted_kinds'] = sorted(set(record.get('deleted_kinds', [])) | {kind})
        # Cancel this publisher's token. Its other, unfinished products remain eligible.
        record['attempted'] = sorted(set(record.get('attempted', [])) - set(record.pop('pending', [])))
        token = json.dumps(record)
        if row is None:
            db.session.add(State(key=name, value=token))
        elif not State.query.filter_by(key=name, value=row.value).update(
                {'value':token, 'createDate':datetime.now()}, synchronize_session=False):
            db.session.rollback()
            continue
        try:
            db.session.commit()
            return
        except IntegrityError:
            db.session.rollback()  # a producer or another deletion claimed the slot
    raise RuntimeError('Could not record media deletion; retry')


def decodable_image(path):
    try:
        with Image.open(path) as image:
            image.load()
            return all(image.size)
    except (FileNotFoundError, UnidentifiedImageError, ValueError):
        return False
    except OSError as exc:
        if exc.errno is not None:
            raise  # EIO, permission failure etc. do not prove corruption
        return False  # e.g. PIL 'image file is truncated'


def eligible_assets(camera, date, night, config, source_count, suppressed):
    from .flask.models import (IndiAllSkyDbKeogramTable, IndiAllSkyDbStarTrailsTable,
                               IndiAllSkyDbStarTrailsVideoTable)
    models = {'keogram': IndiAllSkyDbKeogramTable}
    if night:
        models['startrail'] = IndiAllSkyDbStarTrailsTable
        maximum = source_count - config.get('TIMELAPSE_SKIP_FRAMES', 4)
        if config.get('STARTRAILS_TIMELAPSE', True) and maximum >= config.get('STARTRAILS_TIMELAPSE_MINFRAMES', 250):
            models['startrail_timelapse'] = IndiAllSkyDbStarTrailsVideoTable
    missing = {}
    for kind, model in models.items():
        if kind in suppressed:
            continue
        rows = model.query.filter_by(camera_id=camera.id, dayDate=date, night=night).limit(2).all()
        if len(rows) > 1 or any(entry.s3_key or entry.remote_url for entry in rows):
            continue
        row = rows[0] if rows else None
        if row:
            path = Path(row.getFilesystemPath())
            valid = verified_media(path, night_movie.playable if kind == 'startrail_timelapse' else decodable_image)
            if valid:
                if not row.success:  # repair just the registry flag, preserve the validated file
                    from .flask import db
                    model.query.filter_by(id=row.id, filename=row.filename, success=False).update(
                        {'success':True}, synchronize_session=False)
                    db.session.commit()
                continue
        missing[kind] = (model, row)
    return missing


@contextmanager
def independent_product(kind, config):
    try:
        yield
    except (OSError, ValueError, cv2.error, TimelapseException) as exc:
        if storage_errno(exc) or archive_paused(config):
            raise RepairPaused from exc
        logger.warning('Could not finish %s: %s', kind, exc)


def render(worker, camera, date, night, entries, missing, scratch):
    from .timelapse import TimelapseGenerator
    cfg = worker.config
    skip = cfg.get('TIMELAPSE_SKIP_FRAMES', 4)
    kg = make_keogram(cfg, skip) if 'keogram' in missing else None
    # Generating the still alone does not need scratch movies for every frame.
    still_cfg = cfg if 'startrail_timelapse' in missing else dict(cfg, STARTRAILS_TIMELAPSE=False)
    stg = (make_startrails(still_cfg, skip, camera, worker._load_detection_mask())
           if {'startrail', 'startrail_timelapse'}.intersection(missing) else None)
    def checkpoint():
        if worker._shutdown or archive_paused(cfg):
            raise RepairPaused
    frames, count = stack_entries(entries)
    process_frames(cfg, worker.activity.track('Stacking frames', frames, count), kg, stg, checkpoint)
    checkpoint()
    completed = {}
    fmt = cfg['IMAGE_FILE_TYPE']
    if kg is not None and kg.keogram_data is not None:
        with independent_product('keogram', cfg):
            path = scratch / ('keogram.' + fmt)
            kg.finalize(path, camera)
            completed['keogram'] = (path, len(kg.timestamps))
    if 'startrail' in missing and stg is not None and stg.trail_count:
        with independent_product('startrail', cfg):
            path = scratch / ('startrail.' + fmt)
            stg.finalize(path, camera)
            completed['startrail'] = (path, stg.trail_count)
    if ('startrail_timelapse' in missing and stg is not None
            and stg.timelapse_frame_count >= cfg.get('STARTRAILS_TIMELAPSE_MINFRAMES', 250)):
        with independent_product('startrail_timelapse', cfg):
            encoder = TimelapseGenerator(cfg, skip_frames=0, activity=worker.activity)
            encoder.codec = cfg['FFMPEG_CODEC']
            encoder.framerate = cfg.get('FFMPEG_FRAMERATE', 25)
            encoder.bitrate = cfg['FFMPEG_BITRATE']
            encoder.vf_scale = cfg.get('FFMPEG_VFSCALE_STARTRAIL', '')
            encoder.ffmpeg_extra_options = cfg.get('FFMPEG_EXTRA_OPTIONS', '')
            path = scratch / ('startrail_timelapse.webm' if encoder.codec == 'libvpx' else 'startrail_timelapse.mp4')
            with worker.activity.during(camera.id, 'Encoding star-trail timelapse', date.strftime('%Y%m%d')):
                encoder.generate(path, stg.timelapse_frame_list)
            completed['startrail_timelapse'] = (path, stg.timelapse_frame_count)
    return completed


class RepairPaused(Exception):
    pass


def frame_summary(entries):
    from sqlalchemy import func
    from .flask.models import IndiAllSkyDbImageTable as Frame
    keys = ('max_kpindex', 'max_ovation_max', 'max_smoke_rating', 'max_stars',
            'avg_stars', 'max_moonphase', 'avg_sqm')
    stats = entries.order_by(None).with_entities(func.max(Frame.kpindex), func.max(Frame.ovation_max),
        func.max(Frame.smoke_rating), func.max(Frame.stars), func.avg(Frame.stars),
        func.max(Frame.moonphase), func.avg(Frame.sqm)).one()
    return {key: float(value) for key, value in zip(keys, stats) if value is not None}


def publish(worker, camera, date, night, missing, scratch, name, token, summary):
    from .flask import db
    from .flask.models import IndiAllSkyDbStateTable as State
    published = []
    for kind, (temp, count) in scratch.items():
        if kind == 'startrail_timelapse':
            if not night_movie.playable(temp):
                raise ValueError('Encoded star-trail video contains no decodable frame')
            size = (None, None)
        else:
            with Image.open(temp) as image:
                image.load()
                size = image.size
        if archive_paused(worker.config):
            raise RepairPaused
        require_writable_archive(worker.config)
        # An explicit deletion during encoding wins, even if the IDs are now absent.
        if State.query.filter_by(key=name, value=token).update({'value': token}, synchronize_session=False) != 1:
            db.session.rollback()
            return published
        model, before = missing[kind]
        rows = model.query.filter_by(camera_id=camera.id, dayDate=date, night=night).limit(2).all()
        row = rows[0] if rows else None
        if (len(rows) > 1 or (row and (row.remote_url or row.s3_key))
                or (before.id if before else None) != (row.id if row else None)):
            db.session.rollback()
            continue
        if row:
            current = Path(row.getFilesystemPath())
            if ((kind == 'startrail_timelapse' and night_movie.playable(current)) or
                    (kind != 'startrail_timelapse' and decodable_image(current))):
                db.session.rollback()
                continue
        prefix = 'allsky-{}_ccd{}_{}_{}_'.format(kind, camera.id, date.strftime('%Y%m%d'), 'night' if night else 'day')
        final = temp.parent.parent / (prefix + uuid.uuid4().hex + temp.suffix)
        os.replace(temp, final)
        if row is None:
            row = model(camera_id=camera.id, dayDate=date, night=night)
            db.session.add(row)
        row.filename = str(final.relative_to(worker.image_dir))
        row.createDate = datetime.now()
        row.frames = count
        row.fileSize = final.stat().st_size
        row.width, row.height = size
        row.success = True
        row.data = dict(row.data or {}, **summary)
        row.sync_id = None
        row.uploaded = False
        if kind == 'startrail_timelapse':
            row.framerate = worker.config.get('FFMPEG_FRAMERATE', 25)
        db.session.commit()  # retain existing ID, publish only the validated complete file
        published.append(kind)
        try:
            export(worker, camera, row, kind)
        except Exception:
            db.session.rollback()
            logger.exception('Thumbnail or export unavailable after publishing %s %d', kind, row.id)
    return published


def export(worker, camera, row, kind):
    """Queue configured exports only after the repaired local file is available."""
    types = {'keogram': constants.KEOGRAM, 'startrail': constants.STARTRAIL,
             'startrail_timelapse': constants.STARTRAIL_VIDEO}
    metadata = dict(type=types[kind], createDate=int(row.createDate.timestamp()), dayDate=row.dayDate.strftime('%Y%m%d'),
                    utc_offset=int(row.createDate.astimezone().utcoffset().total_seconds()),
                    camera_uuid=camera.uuid, night=row.night, width=row.width, height=row.height,
                    frames=row.frames, fileSize=row.fileSize, data=row.data)
    if kind == 'startrail_timelapse':
        metadata['framerate'] = row.framerate
        worker._miscUpload.s3_upload_startrail_video(row, metadata)
        worker._miscUpload.syncapi_startrail_video(row, metadata)
        worker._miscUpload.upload_startrail_video(row)
        worker._miscUpload.youtube_upload_startrail_video(row, metadata)
        return
    if not row.thumbnail_uuid:
        thumb = dict(metadata, type=constants.THUMBNAIL, origin=types[kind])
        entry = worker._miscDb.addThumbnail(row, metadata, camera.id, thumb,
            new_width=getattr(worker, 'thumbnail_' + kind + '_width'),
            opt_height=getattr(worker, 'thumbnail_' + kind + '_height_opt'))
        if entry:
            thumb['fileSize'] = entry.fileSize
            worker._miscUpload.syncapi_thumbnail(entry, thumb)
            worker._miscUpload.s3_upload_thumbnail(entry)
    getattr(worker._miscUpload, 's3_upload_' + kind)(row, metadata)
    getattr(worker._miscUpload, 'syncapi_' + kind)(row, metadata)
    getattr(worker._miscUpload, 'upload_' + kind)(row)


def reconcile(worker, camera, date, night):
    """An OS-released lock distinguishes a dead worker from an ongoing build."""
    if not camera.local or camera.hidden or worker._shutdown or archive_paused(worker.config):
        return False
    state_dir = Path(worker.config.get('VARLIB_FOLDER', '/var/lib/indi-allsky'))
    with (state_dir / 'derived-media-repair.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return reconcile_locked(worker, camera, date, night)


def reconcile_locked(worker, camera, date, night):
    from sqlalchemy.exc import IntegrityError
    from .flask import db
    from .flask.models import (IndiAllSkyDbImageTable as Frame, IndiAllSkyDbTaskQueueTable as Task,
                               IndiAllSkyDbStateTable as State, TaskQueueQueue, TaskQueueState)
    from .archive_health import DEFERRED
    cfg = worker.config
    if (not cfg.get('TIMELAPSE_ENABLE', True) or (not night and not cfg.get('DAYTIME_TIMELAPSE', True))
            or cfg.get('FOCUS_MODE') or cfg.get('CAPTURE_PAUSE') or archive_paused(cfg) or worker._shutdown):
        return False
    for task in Task.query.filter(Task.queue == TaskQueueQueue.VIDEO,
                                  Task.state.in_((TaskQueueState.MANUAL, TaskQueueState.QUEUED, TaskQueueState.RUNNING))):
        data = task.data or {}
        args = data.get('kwargs', {})
        if (data.get('action') == 'generateKeogramStarTrails' and args.get('camera_id') == camera.id and
                bool(args.get('night')) == night and args.get('timespec') == date.strftime('%Y%m%d')):
            if not args.get('repair'):
                return False
            # We hold the process lock. A previous auto-repair cannot still own this job.
            task.setExpired()
    name = key(camera.id, date, night)
    row = db.session.get(State, name)
    prior = night_movie.prior_attempt(row, date)
    if prior.get('deleted'):
        return False
    entries = Frame.query.filter_by(camera_id=camera.id, dayDate=date, night=night, exclude=False).order_by(
        Frame.createDate, Frame.id)
    missing = eligible_assets(camera, date, night, cfg, entries.count(), prior.get('deleted_kinds', []))
    if not missing:
        return False
    signature, sources = night_movie.local_sources(entries, cfg.get('TIMELAPSE_SKIP_FRAMES', 4))
    if not sources and not entries.first() and not any(row for _, row in missing.values()):
        return False
    # A changed setting may make previously rejected frames eligible.
    options = {k:v for k,v in cfg.items() if k.startswith(('STARTRAILS_', 'KEOGRAM_'))}
    digest = hashlib.sha256(json.dumps([signature, options], sort_keys=True).encode()).hexdigest()
    same = prior.get('source') == digest
    attempted = set(prior.get('attempted', [])) if same else set()
    interrupted = (int(prior.get('interrupted', 0)) + 1
                   if same and prior.get('pending') else 0)
    if interrupted and interrupted <= 2:
        attempted.difference_update(prior['pending'])
    missing = {kind:pair for kind,pair in missing.items() if kind not in attempted}
    wanted = sorted(missing)
    if not wanted:
        return False
    record = {'day': date.isoformat(), 'source': digest, 'attempted': sorted(attempted.union(wanted)),
              'pending': wanted, 'interrupted': interrupted, 'deleted_kinds': prior.get('deleted_kinds', [])}
    token = json.dumps(record)
    if row is None:
        db.session.add(State(key=name, value=token))
    elif not State.query.filter_by(key=name, value=row.value).update({'value':token, 'createDate':datetime.now()},
                                                                     synchronize_session=False):
        db.session.rollback()
        return False
    args = dict(timespec=date.strftime('%Y%m%d'), night=night, camera_id=camera.id)
    task = Task(queue=TaskQueueQueue.VIDEO, state=TaskQueueState.RUNNING,
                data={'action':'generateKeogramStarTrails', 'kwargs':dict(args, repair=True)})
    db.session.add(task)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return False
    published = []
    try:
        if len(sources) <= cfg.get('TIMELAPSE_SKIP_FRAMES', 4):
            task.setFailed('Insufficient local source images for ' + ', '.join(wanted))
        else:
            folder = worker._getVideoFolder(date, camera)
            with tempfile.TemporaryDirectory(prefix='.derived-', dir=folder) as tmp:
                trails = bool({'startrail', 'startrail_timelapse'}.intersection(missing))
                if 'keogram' in missing:
                    phase = 'Generating keogram and star trails' if trails else 'Generating keogram'
                else:
                    phase = 'Generating star trails'
                with worker.activity.during(camera.id, phase, args['timespec']):
                    complete = render(worker, camera, date, night, entries, missing, Path(tmp))
                published = publish(worker, camera, date, night, missing, complete, name, token, frame_summary(entries))
            omitted = sorted(set(wanted) - set(published))
            message = f'{date} {"night" if night else "day"}: generated {", ".join(published) or "none"}.'
            if omitted:
                message += ' No eligible frames or cancelled: ' + ', '.join(omitted)
            if published:
                task.setSuccess(message[:255])
            else:
                task.setFailed(message[:255])
    except Exception as exc:
        db.session.rollback()
        paused = isinstance(exc, RepairPaused) or archive_paused(cfg)
        task.setFailed(DEFERRED if paused else str(exc)[:255])
        if paused:
            record.pop('source', None)
        logger.exception('Derived media repair interrupted for %s', date)
    # A newly lost asset can be restored again; a failed/unsuitable one is not retried hourly.
    record.pop('pending', None)
    record['attempted'] = sorted(set(record['attempted']) - set(published))
    record['result'] = task.result
    State.query.filter_by(key=name, value=token).update({'value':json.dumps(record)}, synchronize_session=False)
    db.session.commit()
    return bool(len(sources) > cfg.get('TIMELAPSE_SKIP_FRAMES', 4))
