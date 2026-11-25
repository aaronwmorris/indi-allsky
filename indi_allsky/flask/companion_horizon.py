"""Request-driven horizon references shared by the Companion's web workers."""
from collections import OrderedDict
from functools import lru_cache
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
from threading import Lock
import time

from flask import current_app


PROBE_INTERVAL = 15 * 60
CONFIRM_INTERVAL = 2 * 60
_BATCH = 8
_fallback_lock = Lock()


def setup_id(entry, model):
    # The stellar solver issues a new solution ID after an installation change
    # or a new observing night. Individual exposure times do not identify a pose.
    identity = [entry.camera_id, str(entry.dayDate), model['id'], model['location'], model['image_size'], model['values']]
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:32]


def _profile_at(state, frame_id, stamp):
    return next((p for p in reversed(state.get('profiles', []))
                 if p['source_frame_id'] <= frame_id and p['source_at'] <= stamp), None)


def _due(state, entry, stamp):
    if state.get('profiles'):
        interval = CONFIRM_INTERVAL if state.get('pending') else PROBE_INTERVAL
        return stamp >= state['checked'] + interval and entry.id > state['checked_id']
    wait = state.get('retry', 0) - time.time()
    return entry.id > state.get('exhausted_id', 0) and not 0 < wait <= 10.


def _eligible(view, candidate, key, stamp, archive_path):
    from .views import virtualsky_frame_alignment
    if candidate is None or not isinstance(candidate.data, dict):
        return None
    pose = virtualsky_frame_alignment(view, candidate)
    if not pose or pose.get('observed_at') is None or pose['observed_at'] > stamp or setup_id(candidate, pose) != key:
        return None
    path = archive_path(candidate)
    return (path, pose) if path is not None else None


def _record(state, profile, frame_id, stamp, signature):
    profile = dict(profile, source_frame_id=frame_id, source_at=stamp)
    # Preserve preceding reference versions for requests arriving out of order.
    profiles = (state.get('profiles', []) + [profile])[-4:]
    return dict(profiles=profiles, checked=stamp, checked_id=frame_id, signature=signature)


def _advance(view, entry, model, key, state, archive_path):
    from ..companion_visible_horizon import horizon_signature, measure_horizon, significant_horizon_change
    stamp = model['observed_at']
    if not state.get('profiles'):
        # Query the first registered exposures, even when the Companion opens
        # hours later. Continue from this cursor after cloudy or missing frames.
        image = view.model
        rows = image.query.filter_by(camera_id=entry.camera_id, dayDate=entry.dayDate, night=True, exclude=False,
                                     width=entry.width, height=entry.height).filter(
            image.id > state.get('cursor', 0), image.id <= entry.id,
            image.data['star_alignment']['id'].as_string() == model['id'],
        ).order_by(image.id).limit(_BATCH).all()
        state = dict(state)
        for candidate in rows:
            state['cursor'] = candidate.id
            source = _eligible(view, candidate, key, stamp, archive_path)
            if source is None:
                continue
            signature = horizon_signature(*source)
            if signature is None:
                continue
            profile = measure_horizon([source])
            if profile and profile.get('envelope') is not None:
                return _record(state, profile, candidate.id, source[1]['observed_at'], signature)
            break  # At most one full-resolution attempt per visible request.
        if not rows or (state['cursor'] == rows[-1].id and len(rows) < _BATCH):
            state['exhausted_id'] = entry.id
        # Keep acquisition bounded during the first unsuccessful exposures.
        state['retry'] = time.time() + 10
        return state

    state = dict(state, checked=stamp, checked_id=entry.id)
    source = _eligible(view, entry, key, stamp, archive_path)
    signature = horizon_signature(*source) if source else None
    if signature is None:
        return state
    changed = significant_horizon_change(state['signature'], signature)
    if changed is not True:
        if changed is False:
            state.pop('pending', None)
        return state
    pending = state.get('pending')
    if (pending and CONFIRM_INTERVAL <= stamp - pending['at'] <= 7200
            and significant_horizon_change(pending['signature'], signature) is False):
        candidate = view.model.query.filter_by(id=pending['id'], camera_id=entry.camera_id,
                                               dayDate=entry.dayDate, night=True, exclude=False).first()
        previous = _eligible(view, candidate, key, stamp, archive_path)
        if previous:
            profile = measure_horizon([previous, source])
            if profile and profile.get('envelope') is not None:
                return _record(state, profile, entry.id, stamp, signature)
    state['pending'] = dict(id=entry.id, at=stamp, signature=signature)
    return state


@lru_cache(maxsize=24)
def _read_version(path, inode, mtime_ns):
    with path.open(encoding='utf-8') as stream:
        state = json.load(stream)
    return state if isinstance(state, dict) else {}


def _read(path):
    try:
        info = path.stat()
        return _read_version(path, info.st_ino, info.st_mtime_ns)
    except (OSError, ValueError):
        return {}


def _write(path, state):
    with tempfile.NamedTemporaryFile('w', dir=path.parent, prefix='.horizon-', delete=False) as stream:
        stage = Path(stream.name)
        try:
            json.dump(state, stream, separators=(',', ':'), allow_nan=False)
            stream.flush()
            stage.replace(path)
        finally:
            stage.unlink(missing_ok=True)


def observed_horizon(view, entry, model, archive_path):
    stamp = model['observed_at']
    key = setup_id(entry, model)
    scope = hashlib.sha256(str(current_app.config['INDI_ALLSKY_IMAGE_FOLDER']).encode()).hexdigest()[:12]
    # Replaying an old photograph must never replace a live station's reference.
    replay = abs(time.time() - stamp) > max(180, 3 * (entry.exposure or 0) + 60)
    root = Path(tempfile.gettempdir()) / 'indi_allsky_cache' / f'companion-horizons-{os.getuid()}'
    path = root / f'{scope}-{key}{"-replay" if replay else ""}.json'
    memory = current_app.extensions.setdefault('companion_horizon_fallback', OrderedDict())
    state = memory.get(path) or _read(path)
    if not _due(state, entry, stamp):
        return _profile_at(state, entry.id, stamp)

    lock = None
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock = path.with_suffix('.lock').open('a')
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        if lock:
            lock.close()
        return _profile_at(state, entry.id, stamp)
    except OSError:
        if lock:
            lock.close()
        lock = None
    if lock is None and not _fallback_lock.acquire(blocking=False):
        return _profile_at(state, entry.id, stamp)
    try:
        state = memory.get(path) or _read(path)
        if _due(state, entry, stamp):
            state = _advance(view, entry, model, key, state, archive_path)
            try:
                if lock is None:
                    raise OSError('Shared horizon cache unavailable')
                _write(path, state)
                memory.pop(path, None)
            except OSError:
                memory[path] = state
                if len(memory) > 16:
                    memory.popitem(last=False)
        return _profile_at(state, entry.id, stamp)
    finally:
        if lock:
            lock.close()
        else:
            _fallback_lock.release()
