"""Monitor the configured image archive without blocking the capture supervisor."""
import errno
import fcntl
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import time


logger = logging.getLogger('indi_allsky')
DEFERRED = 'Waiting for image archive'
OK, LOW, BLOCKED = range(3)
DISK_ERRORS = {errno.ENOSPC, errno.EROFS, errno.EDQUOT, errno.EIO, errno.ENODEV, errno.ESTALE}
MIB = 1024 * 1024
STATUS_FILE = 'archive-health.json'
VIDEO_ACTIONS = {'generateVideo', 'generateMiniVideo', 'generatePanoramaMiniVideo', 'generatePanoramaVideo',
                 'generateKeogramStarTrails', 'generateAsi676mcCalibration', 'uploadAllskyEndOfNight',
                 'backupDatabase'}


def image_dir(config):
    return str(Path(config.get('IMAGE_FOLDER') or Path(__file__).parent.parent / 'html' / 'images').absolute())


def state_file(config):
    return Path(config.get('VARLIB_FOLDER', '/var/lib/indi-allsky')) / STATUS_FILE


def archive_state(config):
    try:
        with state_file(config).open() as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            record = json.load(f)
        return record if record['path'] == image_dir(config) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, KeyError, TypeError):
        return {'level': BLOCKED, 'reason': 'unknown'}


def archive_paused(config):
    state = archive_state(config)
    return state.get('level', OK) != OK or bool(device_error(image_dir(config), state.get('device')))


class ArchiveUnavailable(Exception):
    """A destructive maintenance operation lost its verified archive."""


def space_failure(config, exc=None):
    """Recheck after a failed encoder: subprocesses often hide ENOSPC."""
    if storage_errno(exc) or archive_paused(config):
        return True
    try:
        level, _, _ = check_archive(image_dir(config), archive_state(config).get('mount', ''))
        return level != OK
    except OSError:
        return True


def require_writable_archive(config):
    state = archive_state(config)
    path = image_dir(config)
    if state.get('level', BLOCKED) == BLOCKED or state.get('device') is None or device_error(path, state['device']):
        raise ArchiveUnavailable('Image archive changed before cleanup')
    try:
        if os.statvfs(path).f_flag & os.ST_RDONLY:
            raise ArchiveUnavailable('Image archive is read-only')
    except OSError as exc:
        raise ArchiveUnavailable('Image archive is unavailable') from exc


def device_error(path, expected):
    if expected is None:
        return 0
    try:
        return 0 if os.stat(path).st_dev == expected else errno.ENODEV
    except OSError as exc:
        return exc.errno or errno.EIO


def _mount_paths(filename, column):
    paths = []
    try:
        with open(filename) as f:
            for line in f:
                fields = line.partition('#')[0].split()
                if len(fields) <= column:
                    continue
                mount = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), fields[column])
                if mount.startswith('/'):
                    paths.append(Path(mount))
    except FileNotFoundError:
        pass
    return paths


def check_archive(path, expected='', mounts=None, fstab=None):
    """Compare the deepest configured/previously observed mount before writing anything."""
    path = Path(path).resolve()
    parents = {path, *path.parents}
    if mounts is None:
        mounts = _mount_paths('/proc/self/mountinfo', 4)
    if fstab is None:
        fstab = _mount_paths('/etc/fstab', 1)
    actual = max((p for p in mounts if p in parents), key=lambda p: len(p.parts), default=Path('/'))
    targets = [p for p in fstab if p in parents]
    if expected:
        targets.append(Path(expected))
    required = max(targets, key=lambda p: len(p.parts), default=Path('/'))
    if required != actual and required not in actual.parents:
        return BLOCKED, 'mount', str(required)
    if not path.is_dir():
        return BLOCKED, 'missing', str(actual)
    stat = os.statvfs(path)
    free = stat.f_bavail * stat.f_frsize
    if stat.f_flag & os.ST_RDONLY:
        return BLOCKED, 'readonly', str(actual)
    if free < 32 * MIB or (stat.f_files and stat.f_favail < 64):
        return BLOCKED, 'full', str(actual)
    # statvfs alone cannot detect quota exhaustion or a failed network write.
    with tempfile.NamedTemporaryFile(dir=path, prefix='.allsky-write-check-') as probe:
        probe.write(b'indi-allsky\n')
        probe.flush()
        os.fsync(probe.fileno())
    reserve = min(512 * MIB, max(64 * MIB, stat.f_blocks * stat.f_frsize // 20))
    if free < reserve or (stat.f_files and stat.f_favail < 1024):
        return LOW, 'reserve', str(actual)
    return OK, 'ok', str(actual)


def reason_for_errno(number):
    if number in (errno.ENODEV, errno.ESTALE):
        return 'mount'
    if number == errno.EROFS:
        return 'readonly'
    if number in (errno.ENOSPC, errno.EDQUOT):
        return 'full'
    return 'write'


def storage_errno(error):
    if isinstance(error, OSError):
        return error.errno if error.errno in DISK_ERRORS else None
    original = getattr(error, 'orig', error)
    code = getattr(original, 'sqlite_errorcode', 0) or 0
    if not code and isinstance(original, sqlite3.Error):
        # Python < 3.11 did not expose SQLite error codes. Match only SQLite's
        # exact storage messages, never a lock, configuration or schema error.
        return {'database or disk is full': errno.ENOSPC, 'attempt to write a readonly database': errno.EROFS,
                'disk i/o error': errno.EIO}.get(str(original).lower())
    # SQLite extended result codes include the primary code in the low byte.
    return {13: errno.ENOSPC, 8: errno.EROFS, 10: errno.EIO}.get(code & 255)


class ArchiveMonitor:
    def __init__(self, config):
        self.config = config
        previous = archive_state(config)
        self.mount = os.getenv('INDI_ALLSKY_ARCHIVE_MOUNT') or previous.get('mount', '')
        self.device = None
        self.level = BLOCKED
        self.process = None
        self.next_check = 0
        self.started = 0
        self.last_saved = None
        self.discard_result = False

    def reconfigure(self, config):
        if (image_dir(config), state_file(config)) != (image_dir(self.config), state_file(self.config)):
            self.mount = os.getenv('INDI_ALLSKY_ARCHIVE_MOUNT') or archive_state(config).get('mount', '')
            self.device = None
            self.last_saved = None
            self.level = BLOCKED
            self.discard_result = self.process is not None
            self.next_check = 0
        self.config = config

    def publish(self, level, reason, mount):
        self.level = level
        if mount:
            self.mount = mount
        snapshot = (level, reason, self.mount, self.device)
        if self.last_saved == snapshot:
            return
        record = dict(level=level, reason=reason, mount=self.mount, device=self.device, path=image_dir(self.config),
                      changed=int(time.time()))
        data = json.dumps(record).encode()
        try:
            # Reserve one block on first use. Existing data can be updated even
            # when the archive and varlib share a nearly full filesystem.
            fd = os.open(state_file(self.config), os.O_CREAT | os.O_RDWR, 0o644)
            with os.fdopen(fd, 'r+b') as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                f.write(data.ljust(max(4096, os.fstat(f.fileno()).st_size), b' '))
                f.flush()
            self.last_saved = snapshot
        except OSError as exc:
            logger.error('Cannot publish archive state: %s', exc)
        logger.log(logging.INFO if level == OK else logging.WARNING, 'Image archive: %s', reason)

    def tick(self, io_error=0):
        now = time.monotonic()
        if io_error:
            self.publish(BLOCKED, reason_for_errno(io_error), self.mount)
            self.next_check = now + 30
            self.discard_result = self.process is not None
        if self.process is not None:
            if self.process.poll() is None:
                if now - self.started >= 15:
                    self.process.kill()
                    self.discard_result = True
                    self.publish(BLOCKED, 'timeout', self.mount)
                return self.level
            output, _ = self.process.communicate()
            self.process = None
            if not self.discard_result:
                try:
                    level, reason, mount, self.device = json.loads(output)
                    self.publish(level, reason, mount)
                except (ValueError, TypeError):
                    self.publish(BLOCKED, 'write', self.mount)
            self.discard_result = False
            self.next_check = now + (30 if self.level else 60)
        if now >= self.next_check and self.process is None:
            if self.last_saved is None:
                self.publish(BLOCKED, 'checking', self.mount)
            self.started = now
            try:
                self.process = subprocess.Popen(
                    [sys.executable, __file__, image_dir(self.config), self.mount],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, close_fds=True)
            except OSError:
                self.publish(BLOCKED, 'write', self.mount)
                self.next_check = now + 30
        return self.level


if __name__ == '__main__':
    try:
        before = os.stat(sys.argv[1]).st_dev
        result = check_archive(sys.argv[1], sys.argv[2])
        device = os.stat(sys.argv[1]).st_dev
        if before != device:
            result = BLOCKED, 'mount', sys.argv[2]
    except OSError as exc:
        device = None
        result = BLOCKED, 'missing' if exc.errno == errno.ENOENT else reason_for_errno(exc.errno), sys.argv[2]
    print(json.dumps((*result, device)))
