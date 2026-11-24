"""Durable Night Report products attached to local night keograms."""
from contextlib import suppress
from datetime import datetime, timezone, timedelta
import csv
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile
import time
import zipfile

import numpy as np

from PIL import Image

logger = logging.getLogger('indi_allsky')
REPORT_VERSION = 1


def report_paths(keogram):
    """Derive names from the keogram, never from mutable JSON metadata."""
    base = Path(keogram.getFilesystemPath())
    return {kind: base.with_suffix('.night-report.' + extension)
            for kind, extension in (('png', 'png'), ('csv', 'csv'), ('manifest', 'json'),
                                    ('source_json', 'source.json'), ('source_npz', 'source.npz'))}


def report_ready(keogram):
    """Cheap integrity check suitable for each archive card; no large-file reads."""
    if not keogram.night or not keogram.success:
        return False
    paths = report_paths(keogram)
    try:
        with paths['manifest'].open() as stream:
            manifest = json.load(stream)
        if manifest.get('version') != REPORT_VERSION:
            return False
        for kind in ('png', 'csv'):
            stat = paths[kind].stat()
            record = manifest['files'][kind]
            if not stat.st_size or (stat.st_size, stat.st_mtime_ns) != (record['size'], record['mtime_ns']):
                return False
        return True
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return False



def read_report_metadata(keogram):
    if not report_ready(keogram):
        return {}
    try:
        return json.loads(report_paths(keogram)['manifest'].read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return {}


def report_options(camera_id):
    from .flask import db
    from .flask.models import IndiAllSkyDbStateTable as State
    state = db.session.get(State, 'NIGHT_REPORT_OPTIONS_' + str(int(camera_id)))
    if state is None:
        return None
    try:
        selected = json.loads(state.value)['selected_metrics']
        if not isinstance(selected, list) or not all(isinstance(key, str) for key in selected):
            return None
        return list(dict.fromkeys(selected))
    except (ValueError, KeyError, TypeError):
        return None


def save_report_options(camera_id, selected, *, commit=True):
    from .flask import db
    from .flask.models import IndiAllSkyDbStateTable as State
    if (not isinstance(selected, list) or not 0 <= len(selected) <= 60
            or not all(isinstance(key, str) and 0 < len(key) <= 80 for key in selected)):
        raise ValueError('Invalid metric selection')
    selected = list(dict.fromkeys(selected))
    key = 'NIGHT_REPORT_OPTIONS_' + str(int(camera_id))
    state = db.session.get(State, key)
    if state is None:
        state = State(key=key)
        db.session.add(state)
    state.value = json.dumps({'selected_metrics': selected})
    state.createDate = datetime.now()
    if commit:
        db.session.commit()
    return selected


def _cached_source(paths):
    """Reuse scalar data and an explicitly non-pickle array archive after expiry."""
    try:
        if paths['source_json'].stat().st_size > 32 * 1024 ** 2 or paths['source_npz'].stat().st_size > 64 * 1024 ** 2:
            return None
        record = json.loads(paths['source_json'].read_text(encoding='utf-8'))
        if record.get('version') != REPORT_VERSION:
            return None
        if hashlib.sha256(paths['source_npz'].read_bytes()).hexdigest() != record.get('array_sha256'):
            return None
        with zipfile.ZipFile(paths['source_npz']) as archive:
            info = archive.infolist()
            if ({item.filename for item in info} != {'keogram_rgb.npy', 'frame_times.npy'}
                    or sum(item.file_size for item in info) > 128 * 1024 ** 2):
                return None
        with np.load(paths['source_npz'], allow_pickle=False) as arrays:
            rgb = arrays['keogram_rgb']
            times = arrays['frame_times']
            if (rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3
                    or times.ndim != 1 or times.dtype.kind not in 'fi'
                    or rgb.shape[1] != len(times) or not np.isfinite(times).all()):
                return None
        prepared = record['data']
        if (not isinstance(prepared, dict) or not isinstance(prepared.get('samples'), list)
                or not 0 < len(prepared['samples']) <= 250000):
            return None
        # Only renderer inputs may be restored, never paths or configuration.
        allowed = {'title', 'samples', 'events', 'timezone_name', 'temperature_unit', 'subtitle', 'metrics'}
        if not set(prepared).issubset(allowed):
            return None
        return dict(prepared, keogram_rgb=rgb, frame_times=times.tolist())
    except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile):
        return None


def _stage_source(scratch, prepared):
    arrays = scratch / 'source.npz'
    np.savez_compressed(arrays, keogram_rgb=prepared['keogram_rgb'],
                        frame_times=np.asarray(prepared['frame_times'], dtype=np.float64))
    scalars = {k: v for k, v in prepared.items() if k not in ('keogram_rgb', 'frame_times', 'selected_metrics')}
    record = {'version': REPORT_VERSION, 'array_sha256': hashlib.sha256(arrays.read_bytes()).hexdigest(),
              'data': scalars}
    document = scratch / 'source.json'
    document.write_text(json.dumps(record, allow_nan=False), encoding='utf-8')
    return {'source_json': document, 'source_npz': arrays}


def remove_report(keogram):
    """Invalidate the manifest before removing its two attached products."""
    from flask import current_app
    # Sidecars only belong to products created inside this local archive.
    try:
        parent = Path(keogram.getFilesystemPath()).parent.resolve()
        parent.relative_to(Path(current_app.config['INDI_ALLSKY_IMAGE_FOLDER']).resolve())
    except (OSError, ValueError):
        return
    paths = report_paths(keogram)
    for kind in ('manifest', 'png', 'csv', 'source_json', 'source_npz'):
        with suppress(FileNotFoundError):
            paths[kind].unlink()


def _suppressed(keogram):
    return ((keogram.data or {}).get('night_report') or {}).get('deleted', False)


def _paused(worker):
    return worker._shutdown or worker.config.get('CAPTURE_PAUSE') or worker.config.get('FOCUS_MODE')


def _eligible(worker, camera, keogram):
    if (not camera.local or camera.hidden or not keogram.night or not keogram.success
            or keogram.camera_id != camera.id or _paused(worker) or _suppressed(keogram)):
        return False
    try:
        path = Path(keogram.getFilesystemPath())
        path.resolve().relative_to(Path(worker.config.get('IMAGE_FOLDER') or worker.image_dir).resolve())
        return path.is_file() and path.stat().st_size > 0
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _record(keogram, **values):
    data = dict(keogram.data or {})
    prior = dict(data.get('night_report') or {})
    prior.update(values)
    data['night_report'] = prior
    keogram.data = data


def _due(keogram, now):
    record = (keogram.data or {}).get('night_report') or {}
    if record.get('version') != REPORT_VERSION:
        return True
    try:
        return float(record.get('next_retry', 0)) <= now
    except (ValueError, TypeError):
        return True


def _needs_report(keogram, now):
    if not _due(keogram, now):
        return False
    status = ((keogram.data or {}).get('night_report') or {}).get('status')
    return status in ('waiting', 'generating') or not report_ready(keogram)


def _validate(staged):
    with Image.open(staged['png']) as image:
        if image.format != 'PNG' or min(image.size) < 100:
            raise ValueError('Night Report PNG is invalid')
        image.verify()
    with staged['csv'].open(newline='', encoding='utf-8-sig') as stream:
        rows = csv.reader(stream)
        if len(next(rows, [])) < 3 or not next(rows, None):
            raise ValueError('Night Report CSV has no measurements')


def build_report(worker, camera, keogram, entries=None, *, force=False, keogram_source=None, cached_only=False):
    """Build independently, publishing only a validated PNG/CSV pair.

    A process lock prevents concurrent builds. A persisted retry deadline also
    recovers from killed workers. Failure never invalidates a usable keogram.
    """
    from .flask import db
    from .flask.models import IndiAllSkyDbImageTable as Frame, IndiAllSkyDbKeogramTable as Keogram
    identity = keogram.id, keogram.filename
    try:
        if not _eligible(worker, camera, keogram):
            return False
        now = time.time()
        if not force and not _needs_report(keogram, now):
            return False
        state_dir = Path(worker.config.get('VARLIB_FOLDER', '/var/lib/indi-allsky'))
        with (state_dir / 'night-report.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            db.session.refresh(keogram)
            if not _eligible(worker, camera, keogram):
                return False
            if not force and not _needs_report(keogram, now):
                return False
            _record(keogram, version=REPORT_VERSION, status='generating', attempted_at=now,
                    next_retry=now + 1800)
            db.session.commit()
            paths = report_paths(keogram)
            from .night_report_data import prepare_report
            from .night_report_render import render_report
            with tempfile.TemporaryDirectory(prefix='.night-report-', dir=paths['png'].parent) as scratch:
                staged = {kind: Path(scratch) / ('report.' + kind) for kind in ('png', 'csv')}
                # Force redraws may happen after raw exposures have expired.
                # A fresh keogram always supplies new source data instead.
                prepared = _cached_source(paths) if keogram_source is None else None
                if prepared is None:
                    if cached_only:
                        raise ValueError('No valid retained Night Report source cache')
                    if entries is None:
                        entries = Frame.query.filter_by(camera_id=camera.id, dayDate=keogram.dayDate,
                                                        night=True, exclude=False).order_by(Frame.createDate, Frame.id)
                    prepared = prepare_report(worker.config, camera, keogram.dayDate, entries,
                                              keogram_source=keogram_source)
                    if not prepared.get('samples') or prepared.get('keogram_rgb') is None:
                        raise ValueError('No local frames available for Night Report')
                    source_files = _stage_source(Path(scratch), prepared)
                else:
                    source_files = {}
                selected = report_options(camera.id)
                if _paused(worker):
                    raise InterruptedError('Night Report paused')
                result = render_report(staged['png'], staged['csv'], **prepared, selected_metrics=selected)
                _validate(staged)
                if _paused(worker):
                    raise InterruptedError('Night Report paused')
                # Serialize with deletion/retention. A replaced or deleted
                # keogram must never acquire orphaned report files.
                db.session.expire_all()
                current_row = Keogram.query.filter_by(id=identity[0], filename=identity[1])
                if current_row.update({'filename': identity[1]}, synchronize_session=False) != 1:
                    db.session.rollback()
                    return False
                current = current_row.one()
                if _suppressed(current):
                    db.session.rollback()
                    return False
                if report_options(camera.id) != selected:
                    _record(current, status='waiting', next_retry=0)
                    db.session.commit()
                    return False  # A newer selection supersedes this render.
                with suppress(FileNotFoundError):
                    paths['manifest'].unlink()
                result = result if isinstance(result, dict) else {}
                manifest = {'version': REPORT_VERSION,
                            'created_at': datetime.now(timezone.utc).isoformat(), 'files': {},
                            'metrics': result.get('metrics', prepared.get('metrics', [])),
                            'selected_metrics': result.get('selected_metrics', selected),
                            'events': prepared.get('events', [])}
                for kind, path in source_files.items():
                    path.chmod(0o644)
                    os.replace(path, paths[kind])
                for kind in ('png', 'csv'):
                    staged[kind].chmod(0o644)
                    os.replace(staged[kind], paths[kind])
                    stat = paths[kind].stat()
                    manifest['files'][kind] = {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
                                              'sha256': hashlib.sha256(paths[kind].read_bytes()).hexdigest()}
                manifest_path = Path(scratch) / 'report.json'
                manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
                manifest_path.chmod(0o644)
                os.replace(manifest_path, paths['manifest'])
                _record(current, version=REPORT_VERSION, status='ready', failures=0, next_retry=0,
                        created_at=manifest['created_at'], error=None)
                event_data = {
                    'camera_id': current.camera_id,
                    'keogram_id': current.id,
                    'dayDate': current.dayDate.isoformat(),
                    'created_at': manifest['created_at'],
                }
                db.session.commit()
            try:
                from .events import event_manager
                event_manager.broadcast('night_report_complete', event_data)
            except Exception:
                logger.exception('Could not broadcast night_report_complete for keogram %s', identity[0])
            logger.info('Night Report created for camera %s, %s', event_data['camera_id'], event_data['dayDate'])
            return True
    except Exception as exc:
        db.session.rollback()
        logger.exception('Night Report creation failed for keogram %s; will retry', identity[0])
        try:
            current = Keogram.query.filter_by(id=identity[0], filename=identity[1]).first()
            if current is not None:
                prior = (current.data or {}).get('night_report') or {}
                failures = min(16, int(prior.get('failures', 0)) + 1)
                delay = min(21600, 900 * 2 ** (failures - 1))
                _record(current, version=REPORT_VERSION, status='waiting', failures=failures,
                        next_retry=time.time() + delay, error=type(exc).__name__)
                db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception('Could not record Night Report retry')
        return False


def backfill_reports(worker, today):
    """During idle time, visit two retained keograms and build at most one report."""
    from .flask import db
    from .flask.models import (IndiAllSkyDbCameraTable as Camera, IndiAllSkyDbKeogramTable as Keogram,
                               IndiAllSkyDbStateTable as State)

    if _paused(worker):
        return False
    image_cutoff = today - timedelta(days=int(worker.config.get('IMAGE_EXPIRE_DAYS', 10)))
    keogram_cutoff = today - timedelta(days=int(worker.config.get('TIMELAPSE_EXPIRE_DAYS', 365)))
    candidates = Keogram.query.join(Keogram.camera).filter(
        Camera.local.is_(True), Camera.hidden.is_(False), Keogram.success.is_(True),
        Keogram.night.is_(True), Keogram.dayDate >= keogram_cutoff,
    ).order_by(Keogram.id.desc())

    state = db.session.get(State, 'NIGHT_REPORT_SCAN')
    rows = []
    if state is not None and state.value.isdecimal():
        rows = candidates.filter(Keogram.id < int(state.value)).limit(2).all()
    if not rows:
        rows = candidates.limit(2).all()
    if not rows:
        return False
    if state is None:
        state = State(key='NIGHT_REPORT_SCAN')
        db.session.add(state)
    for entry in rows:
        state.value = str(entry.id)
        state.createDate = datetime.now()
        db.session.commit()
        if not _eligible(worker, entry.camera, entry) or not _needs_report(entry, time.time()):
            continue
        cached_only = entry.dayDate < image_cutoff
        if cached_only:
            paths = report_paths(entry)
            if not all(paths[key].is_file() for key in ('source_json', 'source_npz')):
                continue
        build_report(worker, entry.camera, entry, cached_only=cached_only)
        return True
    return False
