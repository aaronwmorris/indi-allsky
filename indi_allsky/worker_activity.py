"""Publish local worker activity with process-owned POSIX byte-range locks.

Each phase occupies one byte range in a small file. A lock changes in kernel
memory, even when the station stores its application data on an SD card.
Crashes release locks immediately, including when a forked child survives.
"""
from contextlib import contextmanager
import errno
import fcntl
import os
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


class WorkerActivity:
    def __init__(self, config, role):
        self.directory = Path(config.get('VARLIB_FOLDER', '/var/lib/indi-allsky')) / 'worker-activity'
        self.role = role
        self.key = None
        self.fd = None

    def clear(self):
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
                os.pwrite(self.fd, stamp.ljust(8).encode('ascii'), 0)
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


def read_worker_activity(config, camera_id, *, include_capture=True):
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
                            if role == 'media':
                                day = os.pread(state.fileno(), 8, 0)
                                if len(day) == 8 and day.isdigit():
                                    phase += ' · {}-{}-{}'.format(day[:4].decode(), day[4:6].decode(), day[6:].decode())
                            messages.append(phase)
                            break
            except OSError:
                continue
    return messages
