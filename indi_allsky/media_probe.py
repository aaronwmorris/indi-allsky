"""Reuse successful decoder checks during successive archive repair passes."""
from collections import OrderedDict
from time import monotonic


_healthy = OrderedDict()
_max_entries = 256
_max_age = 1800


def verified_media(path, decode):
    """A replaced or edited file must pass its own decode check."""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return False
    if not stat.st_size:
        return False
    key = (path, decode, stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    now = monotonic()
    if key in _healthy and now - _healthy[key] < _max_age:
        _healthy.move_to_end(key)
        return True
    if not decode(path):
        _healthy.pop(key, None)
        return False
    _healthy[key] = now
    _healthy.move_to_end(key)
    if len(_healthy) > _max_entries:
        _healthy.popitem(last=False)
    return True
