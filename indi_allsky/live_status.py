"""Frame identity, camera time and read-only diagnostics for the live view."""
import json
import os
from datetime import timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import constants
from .archive_health import BLOCKED


# The capture supervisor publishes these STATUS values. The sidebar and the
# live image must describe that same state even when the web server responds.
CAPTURE_STATES = {
    constants.STATUS_RUNNING: ('running', 'RUNNING', 'tw:text-success'),
    constants.STATUS_SLEEPING: ('sleeping', 'SLEEPING', 'tw:text-base-content/60'),
    constants.STATUS_RELOADING: ('reloading', 'RELOADING', 'tw:text-warning'),
    constants.STATUS_STARTING: ('starting', 'STARTING', 'tw:text-info'),
    constants.STATUS_STOPPING: ('stopping', 'STOPPING', 'tw:text-primary'),
    constants.STATUS_STOPPED: ('stopped', 'STOPPED', 'tw:text-primary'),
    constants.STATUS_PAUSED: ('paused', 'PAUSED', 'tw:text-base-content/60'),
    constants.STATUS_NOCAMERA: ('no_camera', 'NO CAMERA', 'tw:text-error'),
    constants.STATUS_CAMERAERROR: ('camera_error', 'CAMERA ERROR', 'tw:text-error'),
    constants.STATUS_NOINDISERVER: ('no_indiserver', 'NO INDISERVER', 'tw:text-error'),
}


def station_status(code, label, class_name):
    return {'code': code, 'label': label, 'class_name': class_name}


def camera_timezone(camera):
    """Use the camera's timezone rules when available, including DST changes."""
    if camera.local:
        system_zone = os.environ.get('TZ', '').lstrip(':')
        if system_zone and not os.path.isabs(system_zone):
            try:
                return ZoneInfo(system_zone)
            except (ZoneInfoNotFoundError, ValueError):
                pass

        zone_file = Path(system_zone if os.path.isabs(system_zone) else '/etc/localtime')
        try:
            with zone_file.open('rb') as stream:
                return ZoneInfo.from_file(stream)
        except (OSError, ValueError, RuntimeError):
            pass

    # Capture commonly saves abbreviations like CET or CST. These do not
    # uniquely identify the remote location's DST rules.
    name = camera.tz or ''
    if '/' in name or name in ('UTC', 'GMT'):
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass

    return timezone(timedelta(seconds=camera.utc_offset or 0))


def capture_time(wall, offset, now):
    """Return the camera time of a stored frame if it is unambiguous."""
    if isinstance(offset, (int, float)) and not isinstance(offset, bool) and -86400 < offset < 86400:
        return wall.replace(tzinfo=timezone(timedelta(seconds=offset)))
    zone = now.tzinfo
    candidates = {wall.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc) for fold in (0, 1)}
    valid = [t for t in candidates if t.astimezone(zone).replace(tzinfo=None) == wall
             and t.timestamp() <= now.timestamp()]
    return valid[0].astimezone(zone) if len(valid) == 1 else None


def latest_live_row(query, model, now):
    """Most recent eligible exposure, including across a repeated local hour."""
    wall = now.replace(tzinfo=None)
    overlap = abs(now.replace(fold=0).utcoffset() - now.replace(fold=1).utcoffset())
    ordered = query.filter(model.createDate <= wall + overlap).order_by(model.createDate.desc(), model.id.desc())

    def row_time(row):
        offset = row.data.get('utc_offset') if isinstance(row.data, dict) else None
        return capture_time(row.createDate, offset, now)

    def fold_span(date):
        return abs(date.replace(tzinfo=now.tzinfo, fold=0).utcoffset()
                   - date.replace(tzinfo=now.tzinfo, fold=1).utcoffset())


    first = ordered.first()
    if first is None:
        return None
    if not fold_span(first.createDate):
        first_time = row_time(first)
        if first.createDate <= wall and (first_time is None or first_time.timestamp() <= now.timestamp()):
            return first  # A normal poll needs only the most recent row.

    best = uncertain = None
    best_stamp = None
    window_start = None
    for row in ordered.yield_per(32):
        if window_start is not None and row.createDate < window_start:
            break
        date = row.createDate
        captured = row_time(row)
        if captured is not None and captured.timestamp() > now.timestamp():
            continue
        if captured is None and date > wall:
            continue
        repeated = fold_span(date)
        if not repeated and window_start is None:
            return row
        if window_start is None:
            window_start = date - repeated
        if captured is None:
            if uncertain is None:
                uncertain = row
        elif best_stamp is None or captured.timestamp() > best_stamp:
            best, best_stamp = row, captured.timestamp()
    return best if best is not None else uncertain


def health_reason(health, archive, now):
    """Use the current supervisor report, never an old process's diagnosis."""
    try:
        record = json.loads(health.value)
        updated = record['updated']
        if not (0 <= now.timestamp() - updated <= 90):
            return 'capture_status_stale'
    except (AttributeError, TypeError, KeyError, ValueError):
        return 'capture_status_stale'
    if archive.get('level') == BLOCKED:
        return {'full': 'archive_full', 'readonly': 'archive_readonly'}.get(
            archive.get('reason'), 'archive_unavailable')
    recovery = record.get('recovery')
    if recovery in ('capture', 'image', 'capture_backoff', 'image_backoff'):
        return {'capture': 'capture_recovering', 'image': 'processing_recovering',
                'capture_backoff': 'capture_backoff', 'image_backoff': 'processing_backoff'}[recovery]
    stage = record.get('stage')
    if stage in ('paused', 'daytime_disabled', 'aborting'):
        return {'paused': 'paused', 'daytime_disabled': 'daytime_disabled', 'aborting': 'capture_retrying'}[stage]
    if record.get('image_processing'):
        return 'processing'
    if stage == 'exposing':
        return 'awaiting_frame'
    return None
