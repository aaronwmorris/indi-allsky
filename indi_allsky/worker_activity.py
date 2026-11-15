"""Publish local worker activity with process-owned POSIX byte-range locks.

Each phase occupies one byte range in a small file. A lock changes in kernel
memory, even when the station stores its application data on an SD card.
Crashes release locks immediately, including when a forked child survives.
"""
from contextlib import contextmanager
import errno
import fcntl
import os
import stat
import struct
import tempfile
import time
from pathlib import Path


# The offsets are part of the on-disk protocol. Append new phases at the end.
PHASES = {
    'capture': ('Waiting for next exposure', 'Capturing an image', 'Capturing an SQM exposure',
                'Waiting for camera image', 'Recovering exposure', 'Configuring camera',
                'Waiting for external exposure'),
    'image': ('Analyzing image', 'Saving image', 'Measuring sky brightness'),
    'media': ('Generating daytime timelapse', 'Generating nighttime timelapse',
              'Generating daytime panorama timelapse', 'Generating nighttime panorama timelapse',
              'Generating mini timelapse', 'Generating panorama mini timelapse', 'Generating keogram',
              'Generating keogram and star trails', 'Generating star trails', 'Encoding star-trail timelapse',
              'Removing expired media', 'Backing up database', 'Checking system health',
              'Preparing end-of-night upload', 'Updating aurora data', 'Updating smoke data',
              'Updating satellite data', 'Contacting all-sky map'),
    'calibration': ('Calibrating ASI676MC images',),
}


def media_phase(action, kwargs):
    night = kwargs.get('night')
    if action == 'generateKeogramStarTrails':
        return 'Generating keogram and star trails' if night else 'Generating keogram'
    if action == 'generateVideo':
        return 'Generating nighttime timelapse' if night else 'Generating daytime timelapse'
    if action == 'generatePanoramaVideo':
        return 'Generating nighttime panorama timelapse' if night else 'Generating daytime panorama timelapse'
    if action in ('generateMiniVideo', 'generatePanoramaMiniVideo'):
        if action == 'generatePanoramaMiniVideo' or kwargs.get('panorama_image_id') is not None:
            return 'Generating panorama mini timelapse'
        return 'Generating mini timelapse'
    return {
        'expireData': 'Removing expired media', 'backupDatabase': 'Backing up database',
        'systemHealthCheck': 'Checking system health', 'uploadAllskyEndOfNight': 'Preparing end-of-night upload',
        'updateAuroraData': 'Updating aurora data', 'updateSmokeData': 'Updating smoke data',
        'updateSatelliteTleData': 'Updating satellite data', 'sendAllskyMapPing': 'Contacting all-sky map',
    }.get(action)


# Only these application stages cross the web boundary. A single fixed-size
# pread/pwrite transfers a snapshot; frames never write to VARLIB_FOLDER.
_STAGES = ('Checking source images', 'Preparing frames', 'Stacking frames', 'Encoding frames')
_PROGRESS = struct.Struct('!8sBQQdd')
_PUBLISH_INTERVAL = 1.0


def _progress_file(state_fd, phase_index):
    marker = os.fstat(state_fd)
    # Linux stations share /dev/shm across the capture and web service users.
    root = Path('/dev/shm') if os.uname().sysname == 'Linux' else Path(tempfile.gettempdir())
    return root / f'indi-allsky-progress-{marker.st_dev:x}-{marker.st_ino:x}-{phase_index}'


def _read_progress(state_fd, phase_index, token):
    if len(token) != 8:
        return {}  # Includes older stations with just a date in the marker.
    path = _progress_file(state_fd, phase_index)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if info.st_uid != os.fstat(state_fd).st_uid or not stat.S_ISREG(info.st_mode):
                return {}
            data = os.pread(fd, _PROGRESS.size, 0)
        finally:
            os.close(fd)
        if len(data) != _PROGRESS.size:
            return {}
        owner, stage, done, total, started, updated = _PROGRESS.unpack(data)
        if owner != token or stage >= len(_STAGES) or not 0 <= done <= total or not total:
            return {}
        now = time.monotonic()
        if not 0 <= started <= updated <= now:
            return {}
        elapsed = updated - started
        age = now - updated
        eta = None
        if done >= 2 and elapsed >= 1 and 0 <= age <= max(30, 3 * elapsed / done):
            eta = round(elapsed * (total - done) / done)
        return {'stage': _STAGES[stage], 'completed': done, 'total': total, 'eta_seconds': eta}
    except OSError:
        return {}


class WorkerActivity:
    def __init__(self, config, role):
        self.directory = Path(config.get('VARLIB_FOLDER', '/var/lib/indi-allsky')) / 'worker-activity'
        self.role = role
        self.key = None
        self.fd = None
        self.token = b''
        self.progress_fd = None
        self.progress_path = None
        self.stage = None

    def finish_progress(self):
        """Stop reporting counts while a job finalizes or leaves its phase."""
        fd, self.progress_fd = self.progress_fd, None
        self.stage = None
        if fd is not None:
            try:
                self.progress_path.unlink()
            except OSError:
                pass
            finally:
                self.progress_path = None
                try:
                    os.close(fd)
                except OSError:
                    pass

    def progress(self, stage, completed, total):
        """Count actual work. Publish at most once a second, plus both endpoints."""
        if (self.role != 'media' or self.fd is None or stage not in _STAGES or
                type(completed) is not int or type(total) is not int or not 0 <= completed <= total
                or not 0 < total < 2**63):
            return
        now = time.monotonic()
        if self.stage != (stage, total) or (completed == 0 and self.last_done > 0):
            self.started = now
            self.last_done = -1
            self.published = float('-inf')
            self.stage = (stage, total)
        if completed <= self.last_done or (completed != total and now - self.published < _PUBLISH_INTERVAL):
            return
        self.published = now
        try:
            if self.progress_fd is None:
                path = _progress_file(self.fd, PHASES['media'].index(self.key[1]))
                fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o644)
                info = os.fstat(fd)
                if info.st_uid != os.geteuid() or not stat.S_ISREG(info.st_mode):
                    os.close(fd)
                    return
                self.progress_path = path
                self.progress_fd = fd
            snapshot = _PROGRESS.pack(self.token, _STAGES.index(stage), completed, total, self.started, now)
            os.pwrite(self.progress_fd, snapshot, 0)
            self.last_done = completed
        except OSError:
            pass  # Optional reporting must never interrupt generation.

    def track(self, stage, items, total):
        self.progress(stage, 0, total)
        try:
            for completed, item in enumerate(items, 1):
                yield item
                self.progress(stage, completed, total)
        finally:
            self.finish_progress()

    def clear(self):
        self.finish_progress()
        fd, self.fd = self.fd, None
        self.key = None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass  # A delayed write error must not break capture or media generation.

    def set(self, camera_id, phase, day=''):
        key = (camera_id, phase, day)
        if key == self.key:
            return
        self.clear()
        # Zero is reserved for station-wide maintenance without a camera ID.
        if type(camera_id) is not int or camera_id < 0 or phase not in PHASES[self.role]:
            return
        try:
            self.directory.mkdir(mode=0o755, exist_ok=True)
            path = self.directory / f'{camera_id}-{self.role}'
            self.fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o644)
            offset = PHASES[self.role].index(phase) + 16
            fcntl.lockf(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, offset)
            if self.role == 'media':
                # Only a session date may be exposed, never task payloads or paths.
                stamp = day if isinstance(day, str) and len(day) == 8 and day.isascii() and day.isdecimal() else ''
                self.token = os.urandom(8)
                os.pwrite(self.fd, stamp.ljust(8).encode('ascii') + self.token, 0)
            self.key = key
        except OSError:
            # Telemetry must not interrupt a frame, or block on another worker.
            self.clear()

    @contextmanager
    def during(self, camera_id, phase, day=''):
        previous = self.key
        self.set(camera_id, phase, day)
        try:
            yield
        finally:
            if previous is None:
                self.clear()
            else:
                self.set(*previous)


def read_worker_activity(config, camera_id, *, include_capture=True, detailed=False):
    """Read active phases from a separate process, in capture/image/media order."""
    if type(camera_id) is not int or camera_id <= 0:
        return []
    directory = Path(config.get('VARLIB_FOLDER', '/var/lib/indi-allsky')) / 'worker-activity'
    messages = []
    for role, phases in PHASES.items():
        if role == 'capture' and not include_capture:
            continue
        for owner in ((camera_id, 0) if role in ('media', 'calibration') else (camera_id,)):
            try:
                with (directory / f'{owner}-{role}').open('rb') as state:
                    for offset, phase in enumerate(phases, start=16):
                        # F_TEST probes without taking a lock, so readers never
                        # block a writer and concurrent web requests cannot collide.
                        os.lseek(state.fileno(), offset, os.SEEK_SET)
                        try:
                            os.lockf(state.fileno(), os.F_TEST, 1)
                        except OSError as exc:
                            if exc.errno not in (errno.EAGAIN, errno.EACCES):
                                raise
                            entry = {'role': role, 'label': phase}
                            if role == 'media':
                                header = os.pread(state.fileno(), 16, 0)
                                day = header[:8]
                                if len(day) == 8 and day.isdigit():
                                    entry['day'] = '{}-{}-{}'.format(day[:4].decode(), day[4:6].decode(), day[6:].decode())
                                if detailed:
                                    entry.update(_read_progress(state.fileno(), offset - 16, header[8:]))
                            messages.append(entry if detailed else activity_label(entry))
                            break
            except OSError:
                continue
    return messages


def activity_label(entry):
    return entry['label'] + (' · ' + entry['day'] if entry.get('day') else '')
