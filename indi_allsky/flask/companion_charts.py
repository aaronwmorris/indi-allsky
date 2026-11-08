"""Camera-bound measurements for the companion's two-hour charts."""
from collections import Counter
from datetime import timedelta, timezone
import math

from sqlalchemy import and_, extract, func, or_

from ..sensors_mapping import build_slot_label_map, resolve_temp_unit
from .models import IndiAllSkyDbImageTable as Image


_LABELS = {
    'sky': 'Sky Temperature',
    'lux': 'Sky Brightness (lux)',
    'sqm': 'Sky Brightness (sensor SQM)',
    'camera_sqm': 'Sky Brightness (camera SQM)',
    'jsqm': 'Relative Sky Brightness (jSQM)',
    'air': 'Air Temperature',
    'humidity': 'Relative Humidity',
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


def _utc_options(wall, tz):
    """Possible instants for a local timestamp (none in a spring-forward gap)."""
    instants = {
        wall.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc) for fold in (0, 1)
    }
    return sorted(t for t in instants if t.astimezone(tz).replace(tzinfo=None) == wall)


def _stored_zone(seconds):
    if seconds is None:
        return None
    try:
        return timezone(timedelta(seconds=float(seconds)))
    except (TypeError, ValueError, OverflowError):
        return None


def _last_per_minute(samples):
    """Keep the latest real exposure in each elapsed UTC minute."""
    latest = {}
    for dated, image_id, *values in samples:
        stamp = dated.timestamp()
        minute = int(stamp // 60)
        if minute not in latest or (stamp, image_id) > latest[minute][:2]:
            latest[minute] = (stamp, image_id, dated, *values)
    return [latest[minute][1:] for minute in sorted(latest)]


def _transition_samples(query, start, end, tz, offsets, camera, values, stored):
    # A fall-back window may end at 02:10 yet contain the FIRST 02:59. Include
    # the full repeated hour to find a clock reversal in older local recordings.
    shift = max(offsets) - min(offsets)
    lower = start.replace(tzinfo=None) + min(offsets) - shift
    upper = end.replace(tzinfo=None) + max(offsets) + shift
    refs = query.with_entities(Image.id, Image.createDate, stored).filter(
        Image.createDate.between(lower, upper),
    ).order_by(Image.id).all()
    prepared = [(image_id, wall, _stored_zone(offset), _utc_options(wall, tz)) for image_id, wall, offset in refs]
    # Local frames are inserted in capture order. Historically synced files
    # can arrive out of order; their IDs are not evidence of which fold applies.
    reversals = [right[0] for left, right in zip(prepared, prepared[1:])
                 if len(left[3]) == len(right[3]) == 2 and right[1] < left[1]]
    pivot = reversals[0] if camera.local and len(reversals) == 1 else None
    samples = []
    for image_id, wall, frame_zone, options in prepared:
        if frame_zone is not None:
            dated = wall.replace(tzinfo=frame_zone)
        elif len(options) == 1:
            dated = options[0].astimezone(tz)
        elif len(options) == 2:
            if pivot is not None:
                instant = options[int(image_id >= pivot)]
            elif end.astimezone(tz).fold == 0 and options[1] > end:
                # Before the fall-back, only the first occurrence has happened.
                instant = options[0]
            else:
                continue  # Both assignments are possible; do not invent one.
            dated = instant.astimezone(tz)
        else:
            continue
        if start <= dated.astimezone(timezone.utc) <= end:
            samples.append((dated, image_id))

    chosen = _last_per_minute(samples)
    if not chosen:
        return []
    # The first query reads only IDs and timestamps/offsets. Fetch sensor
    # values for at most one frame per UTC minute, irrespective of cadence.
    rows = query.with_entities(Image.id, *values).filter(
        Image.id.in_([image_id for image_id, dated in chosen]),
    ).all()
    by_id = {row[0]: row[1:] for row in rows}
    return [(dated, *by_id[image_id]) for image_id, dated in chosen if image_id in by_id]


def _read_samples(camera, start, end, tz, keys, *, local_images_allowed):
    query = Image.query.filter(Image.camera_id == camera.id, Image.exclude.is_(False))
    if not local_images_allowed:
        query = query.filter(or_(Image.remote_url.isnot(None), Image.s3_key.isnot(None)))
    stored = Image.data['utc_offset'].as_integer()
    values = [Image.data['temp_display'].as_string()]
    values.extend(Image.sqm if key == 'jsqm' else Image.data[key].as_string() for key in keys)
    local_start, local_end = start.astimezone(tz), end.astimezone(tz)
    offsets = {edge.replace(fold=fold).utcoffset() for edge in (local_start, local_end) for fold in (0, 1)}
    if len(offsets) != 1:
        return _transition_samples(query, start, end, tz, offsets, camera, values, stored)

    base_offset = local_start.utcoffset()
    possible = {base_offset}
    if isinstance(tz, timezone):
        # Without an IANA zone the camera supplies only its current offset.
        # Discover historical offsets in the bounded envelope of possible wall
        # times; the actual values query below uses exact indexed time ranges.
        envelope = Image.createDate.between(start.replace(tzinfo=None) - timedelta(days=1),
                                            end.replace(tzinfo=None) + timedelta(days=1))
        for (seconds,) in query.with_entities(stored).filter(envelope, stored.isnot(None)).distinct():
            frame_zone = _stored_zone(seconds)
            if frame_zone is not None:
                possible.add(frame_zone.utcoffset(None))

    ranges = []
    for offset in possible:
        match = stored == int(offset.total_seconds())
        # An old row on a fixed-offset-only station has no reliable timestamp
        # when the nearby records show multiple different offsets.
        if offset == base_offset and len(possible) == 1:
            match = or_(match, stored.is_(None))
        ranges.append(and_(match, Image.createDate.between(
            start.replace(tzinfo=None) + offset, end.replace(tzinfo=None) + offset)))
    effective = func.coalesce(stored, int(base_offset.total_seconds()))
    minute = (func.date(Image.createDate), extract('hour', Image.createDate),
              extract('minute', Image.createDate), effective)
    # Some historical offsets include seconds: a single civil minute can
    # straddle two UTC minutes; preserve each half, then merge by UTC below.
    if any(offset.total_seconds() % 60 for offset in possible):
        minute += (extract('second', Image.createDate) >= ((effective % 60 + 60) % 60),)
    rank = func.row_number().over(partition_by=minute, order_by=(Image.createDate.desc(), Image.id.desc()))
    recent = query.with_entities(Image.id.label('id'), rank.label('position')).filter(or_(*ranges)).subquery()
    rows = Image.query.with_entities(Image.id, Image.createDate, effective, *values).join(
        recent, recent.c.id == Image.id,
    ).filter(recent.c.position == 1)
    samples = [(wall.replace(tzinfo=timezone(timedelta(seconds=offset))), image_id, *data)
               for image_id, wall, offset, *data in rows]
    return [(dated, *data) for _, dated, *data in _last_per_minute(samples)]


def companion_charts(camera, config, now, tz, requested, *, local_images_allowed):
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
    for dated, stored, *values in _read_samples(camera, start, end, tz, selected,
                                               local_images_allowed=local_images_allowed):
        stored = stored or temp_code or ('c' if camera.local else None)
        for key, data, value in zip(selected, series, values):
            data['points'].append([dated.isoformat(), _sample(value, slots[key], stored, temp_unit)])
    return list(metrics.values()), defaults, series
