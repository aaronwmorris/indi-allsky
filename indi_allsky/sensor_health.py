"""Validity of external sensor readings shared by capture workers."""
import time
from multiprocessing import RawArray


class SensorHealth:
    def __init__(self):
        # Access these under the lock of the associated sensors_user_av values.
        self.expires = RawArray('d', 110)
        self.last_good = RawArray('q', 6)

    def invalidate(self, slot, count):
        for i in range(slot, min(slot + count, len(self.expires))):
            self.expires[i] = 0

    def metadata(self, now):
        # 50 bits for external slots 10..59. Preserve legacy numeric fields
        # for other consumers, and carry the validity through ordinary sync.
        mask = sum(1 << (i - 10) for i in range(10, 60) if self.expires[i] > now)
        return {'sensor_valid_mask': mask, 'sensor_last_good': list(self.last_good)}


class SensorRetry:
    """Back off a single failed driver. A good measurement resets the delay."""
    def __init__(self):
        self.failures = 0
        self.delay = 15
        self.next_open = 0
        self.last_observed = 0
        self.previous_sample = None

    def retry_later(self, now):
        self.next_open = now + self.delay
        self.delay = min(300, self.delay * 2)
        self.failures = 0
        self.last_observed = 0
        self.previous_sample = None

    def success(self):
        self.delay = 15
        self.failures = 0


def ups_problem(path, now=None):
    """Status from the optional local UPS monitor. No file means not installed."""
    import json
    try:
        status = json.loads(path.read_text())
        age = (time.monotonic() if now is None else now) - float(status['last_good_mono'])
        return status['readable'] is not True or not 0 <= age <= 15
    except FileNotFoundError:
        return False
    except (OSError, ValueError, TypeError, KeyError):
        return True
