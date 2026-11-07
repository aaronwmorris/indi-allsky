"""Progress of the local capture and image workers, shared with their supervisor."""
import time
from multiprocessing import RawValue
from pathlib import Path


class ExposureDeadline:
    """Watch one issued request. A driver READY signal can precede its image."""
    def __init__(self, timeout):
        self.timeout = timeout
        self.until = None
        self.previous_until = None
        self.aborting = False
        self.failures = 0

    def start(self, now, seconds, frames):
        self.until = now + max(self.timeout, seconds + 30)
        self.initial_frames = frames
        self.aborting = False

    def poll(self, now, ready, frames, failed=False, *, stopping=False, unfinished=False):
        if stopping:
            if self.until is None:
                return 'stop_abort' if unfinished and not ready else 'stop'
            if ready and (self.aborting or frames != self.initial_frames):
                return 'stop'
            return 'stop_abort' if failed or now >= self.until else 'wait'
        if unfinished:
            # Only a BUSY state left by our own unsuccessful abort can be
            # retried on reconnect. Leave unrelated exposures alone.
            if ready:
                self.previous_until = None
                return 'ready'
            if self.previous_until is None:
                self.previous_until = now + self.timeout
            return 'reconnect' if now >= self.previous_until else 'wait'
        if self.until is None:
            return 'ready' if ready else 'wait'
        if self.aborting:
            if ready and self.failures < 2:
                self.until = None
                return 'retry'
            if ready or now >= self.until:
                return 'reconnect'
            return 'wait'
        if ready and frames != self.initial_frames:
            self.until = None
            self.failures = 0
            return 'ready'
        if failed or now >= self.until:
            self.failures += 1
            self.aborting = True
            self.until = now + 15
            return 'abort'
        return 'wait'


class CaptureHealth:
    stages = ('starting', 'idle', 'paused', 'daytime_disabled', 'exposing', 'aborting')

    def __init__(self):
        # Each field is an aligned, single-word observation. Do not take a
        # multiprocessing lock from a worker that may be blocked or dying.
        for name in ('stage', 'pulse', 'exposure_started', 'raw_received', 'frames', 'image_started',
                     'image_busy', 'image_pulse', 'image_published', 'last_failure', 'unreaped', 'unfinished',
                     'misses', 'first_miss', 'last_miss', 'publications'):
            setattr(self, name, RawValue('I', 0))

    def capture_stage(self, name):
        self.stage.value = self.stages.index(name)
        self.pulse.value = int(time.monotonic())

    def publication_result(self, published, now, limit):
        if published:
            self.misses.value = 0
        else:
            # A long gap (daytime off, pause, long exposure) begins a new
            # observation window; no assumption about camera frame rate.
            if not self.misses.value or now - self.last_miss.value > limit:
                self.first_miss.value = int(now)
                self.misses.value = 0
            self.misses.value += 1
            self.last_miss.value = int(now)

    def stalled(self, now, timeout):
        # Both idle and active workers have a loop pulse. Long exposures
        # continue polling. Sleeping/paused capture has no frame requirement.
        limit = max(300, timeout + 60)
        if self.unreaped.value or (self.pulse.value and now - self.pulse.value > limit):
            return 'capture'
        if self.image_pulse.value and now - self.image_pulse.value > limit:
            return 'image'
        if (self.stages[self.stage.value] not in ('paused', 'daytime_disabled')
                and self.misses.value >= 3 and now - self.last_miss.value <= limit
                and self.last_miss.value - self.first_miss.value >= limit):
            return 'image'
        return None

    def status(self, recovery):
        return {
            'updated': int(time.time()), 'stage': self.stages[self.stage.value],
            'exposure_started': self.exposure_started.value or None,
            'raw_received': self.raw_received.value or None,
            'image_started': self.image_started.value or None,
            'image_processing': bool(self.image_busy.value),
            'unpublished_attempts': self.misses.value,
            'image_published': self.image_published.value or None,
            'last_failure': self.last_failure.value or None, 'recovery': recovery,
        }


class CameraImageQueue:
    """Observe actual files submitted by all capture interfaces, including INDI callbacks."""
    def __init__(self, queue, health):
        self.queue = queue
        self.health = health

    def put(self, job):
        try:
            valid = Path(job['filename']).stat().st_size > 0
        except OSError:
            valid = False
        self.queue.put(dict(job, capture_file_present=valid))
        if valid:
            self.health.raw_received.value = int(time.time())
            self.health.frames.value += 1


class RestartDelay:
    """Back off once per exited PID, even if SIGTERM or OOM bypassed its cleanup."""
    def __init__(self):
        self.last_pid = None
        self.failures = 0
        self.after = 0
        self.initial_progress = 0

    def ready(self, worker, now, progress):
        if worker is None:
            self.failures = 0  # initial start or planned service reload
        elif self.last_pid != worker.pid:
            if progress != self.initial_progress:
                self.failures = 0
            self.failures = min(self.failures + 1, 6)
            self.after = now + min(300, 15 * 2 ** (self.failures - 1))
            self.last_pid = worker.pid
        if worker is not None and now < self.after:
            return False
        self.initial_progress = progress
        return True
