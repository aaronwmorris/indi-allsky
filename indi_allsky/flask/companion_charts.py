"""Camera-bound measurements for the companion's two-hour charts."""
from collections import Counter
from datetime import timedelta, timezone
import math

from sqlalchemy import extract, func, or_

from ..sensors_mapping import build_slot_label_map, resolve_temp_unit
from .models import IndiAllSkyDbImageTable as Image


_LABELS = {
    'sky': 'Himmelstemperatur',
    'lux': 'Himmelshelligkeit (Lux)',
    'sqm': 'Himmelshelligkeit (Sensor-SQM)',
    'camera_sqm': 'Himmelshelligkeit (Kamera-SQM)',
    'jsqm': 'Relative Himmelshelligkeit (jSQM)',
    'air': 'Lufttemperatur',
    'humidity': 'Relative Luftfeuchte',
}
_UNITS = {'lux': 'lx', 'sqm': 'mag/arcsec²', 'camera_sqm': 'mag/arcsec²',
          'jsqm': 'rel.', 'humidity': '%'}
_TEMP_UNITS = {'c': '°C', 'f': '°F', 'k': 'K'}


def _probe_kind(probe, has_humidity):
    if probe == 'temperature' and has_humidity:
        return 'air'
    return {'sky temperature': 'sky', 'relative humidity': 'humidity',
            'lux': 'lux', 'sqm': 'sqm'}.get(probe)


def _slots(camera, config):
    """Use the capturing station's configuration/labels, never the receiver's sensors."""
    probes = {}
    if camera.local:
        for index, meta in build_slot_label_map(config).items():
            if not 10 <= index < 60:
                continue
            # The mapper derives its stable key from the sensor letter and probe metadata.
            parts = meta['key'].split('_', 2)
            if len(parts) == 3 and parts[0] == 'sensor':
                probes[index] = (parts[1], parts[2].replace('_', ' '))
    else:
        # capture.py publishes labels in camera.data, normally "device - label - probe".
        camera_data = camera.data or {}
        for index in range(10, 60):
            label = camera_data.get(f'sensor_user_{index}')
            if isinstance(label, str):
                device, _, probe = label.lower().rpartition(' - ')
                probes[index] = (device, probe.strip())

    humid_devices = {device for device, probe in probes.values() if probe == 'relative humidity' and device}
    slots = {}
    for index, (device, probe) in sorted(probes.items()):
        kind = _probe_kind(probe, device in humid_devices)
        if kind:
            slots[f'sensor_user_{index}'] = kind

    sqm_config = config.get('CAMERA_SQM', {}) if camera.local else {}
    if sqm_config.get('ENABLE') or sqm_config.get('ENABLE_DAY'):
        slots['sensor_user_8'] = 'camera_sqm'
    slots['jsqm'] = 'jsqm'
    return slots


def _sample(value, kind, stored_temp_unit, display_temp_unit):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or isinstance(value, bool):
        return None
    # Light sensors and the camera write zero to SQM when no magnitude was calculated.
    if kind in ('sqm', 'camera_sqm') and number == 0:
        return None
    if kind not in ('sky', 'air'):
        return number
    if stored_temp_unit not in _TEMP_UNITS:
        return None
    if _TEMP_UNITS[stored_temp_unit] == display_temp_unit:
        return number
    if stored_temp_unit == 'f':
        number = (number - 32) * 5 / 9
    elif stored_temp_unit == 'k':
        number -= 273.15
    if display_temp_unit == '°F':
        return number * 9 / 5 + 32
    if display_temp_unit == 'K':
        return number + 273.15
    return number


def _read_samples(camera, start, end, keys):
    # Read at most one real exposure per minute across the entire window. The inner
    # query uses timestamps/IDs only; JSON is projected solely for the selected keys.
    minute = (func.date(Image.createDate), extract('hour', Image.createDate), extract('minute', Image.createDate))
    rank = func.row_number().over(partition_by=minute, order_by=(Image.createDate.desc(), Image.id.desc()))
    recent = Image.query.with_entities(Image.id.label('id'), rank.label('position')).filter(
        Image.camera_id == camera.id, Image.exclude.is_(False),
        Image.createDate >= start, Image.createDate <= end,
    )
    if camera.web_nonlocal_images:
        recent = recent.filter(or_(Image.remote_url.isnot(None), Image.s3_key.isnot(None)))
    recent = recent.subquery()
    values = [Image.sqm if key == 'jsqm' else Image.data[key].as_string() for key in keys]
    return Image.query.with_entities(Image.createDate, Image.data['temp_display'].as_string(), *values).join(
        recent, recent.c.id == Image.id,
    ).filter(recent.c.position == 1).order_by(Image.createDate).all()


def companion_charts(camera, config, now, tz, requested):
    """Return available metrics, suggested IDs, and up to two selected series."""
    slots = _slots(camera, config)
    temp_code = (config if camera.local else camera.data or {}).get('TEMP_DISPLAY' if camera.local else 'temp_display')
    temp_unit = resolve_temp_unit({'TEMP_DISPLAY': temp_code})
    counts = Counter(slots.values())
    metrics = {}
    for key, kind in slots.items():
        label = _LABELS[kind]
        if counts[kind] > 1:
            label += f" (Slot {key.rsplit('_', 1)[-1]})"
        metrics[key] = {'id': key, 'label': label, 'unit': _UNITS.get(kind, temp_unit)}

    defaults = []
    for kinds in [('sky',), ('lux', 'sqm', 'camera_sqm', 'jsqm')]:
        for kind in kinds:
            match = next((key for key in slots if slots[key] == kind), None)
            if match is not None:
                defaults.append(match)
                break
    selected = list(dict.fromkeys(key for key in (requested or defaults)[:2] if key in slots))
    series = [dict(metrics[key], points=[]) for key in selected]
    if not selected:
        return list(metrics.values()), defaults, series

    end = now if now.tzinfo else now.replace(tzinfo=tz)
    end = end.astimezone(timezone.utc)
    start = end - timedelta(hours=2)
    start_wall = start.astimezone(tz).replace(tzinfo=None)
    end_wall = end.astimezone(tz).replace(tzinfo=None)
    for stamp, stored, *values in _read_samples(camera, start_wall, end_wall, selected):
        # Capture timestamps are stored in the camera's local wall time. Prefer the
        # occurrence inside this window when a clock change repeats an hour.
        dated = stamp.replace(tzinfo=tz)
        if not start <= dated.astimezone(timezone.utc) <= end:
            dated = dated.replace(fold=1)
            if not start <= dated.astimezone(timezone.utc) <= end:
                continue
        stored = stored or temp_code or ('c' if camera.local else None)
        for key, data, value in zip(selected, series, values):
            data['points'].append([dated.isoformat(), _sample(value, slots[key], stored, temp_unit)])
    return list(metrics.values()), defaults, series
