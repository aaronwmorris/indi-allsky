"""Historical, camera-bound measurements and time-linear keogram sources."""
from datetime import datetime, time, timedelta, timezone
import logging
import math
import os
from pathlib import Path

try:
    from zoneinfo import TZPATH, ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # Python < 3.9
    from backports.zoneinfo import TZPATH, ZoneInfo, ZoneInfoNotFoundError

import cv2
import numpy as np
import ephem
from PIL import Image

from .keogram import KeogramGenerator
from .sensors_mapping import build_slot_label_map, resolve_temp_unit

logger = logging.getLogger('indi_allsky')


def camera_timezone(camera):
    """Use the camera's timezone rules when available, including DST changes."""
    if getattr(camera, 'local', False):
        system_zone = os.environ.get('TZ', '').lstrip(':')
        if system_zone and not os.path.isabs(system_zone):
            try:
                return ZoneInfo(system_zone)
            except (ZoneInfoNotFoundError, ValueError):
                pass

        zone_file = Path(system_zone if os.path.isabs(system_zone) else '/etc/localtime')
        try:
            # Raspberry Pi OS normally links /etc/localtime to an IANA TZif.
            # Preserve that key for future reports generated in another timezone.
            target = zone_file.resolve()
            key = None
            for root in TZPATH:
                database = Path(root).resolve()
                try:
                    key = target.relative_to(database).as_posix()
                except ValueError:
                    continue
                if key.startswith(('posix/', 'right/')):
                    key = key.split('/', 1)[1]
                break
            # For a copied /etc/localtime the transitions still work without a key.
            with zone_file.open('rb') as stream:
                return ZoneInfo.from_file(stream, key=key)
        except (OSError, ValueError, RuntimeError):
            pass

    # Capture commonly saves abbreviations like CET or CST. These do not
    # uniquely identify the remote location's DST rules.
    name = getattr(camera, 'tz', None) or ''
    if '/' in name or name in ('UTC', 'GMT'):
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass

    return timezone(timedelta(seconds=getattr(camera, 'utc_offset', 0) or 0))


def night_events(date, tz, location):
    """Calculate astronomical twilight and lunar crossings for a noon-to-noon night."""
    start = datetime.combine(date, time(12), tzinfo=tz).astimezone(timezone.utc)
    stop = datetime.combine(date + timedelta(days=1), time(12), tzinfo=tz).astimezone(timezone.utc)
    observer = ephem.Observer()
    observer.lat = math.radians(location[0])
    observer.lon = math.radians(location[1])
    observer.elevation = location[2]
    observer.pressure = 0
    sun, moon = ephem.Sun(), ephem.Moon()
    events = []
    # The lunar upper limb crosses the standard refracted horizon at -34 arcminutes.
    for body, horizon, crossing, kind, label in (
        (sun, '-12', observer.next_setting, 'dusk', 'Astronomical dusk begins'),
        (sun, '-18', observer.next_setting, 'dusk', 'Astronomical night begins'),
        (sun, '-18', observer.next_rising, 'dawn', 'Astronomical night ends'),
        (sun, '-12', observer.next_rising, 'dawn', 'Astronomical dawn ends'),
        (moon, '-0:34', observer.next_rising, 'moonrise', 'Moonrise'),
        (moon, '-0:34', observer.next_setting, 'moonset', 'Moonset'),
    ):
        observer.horizon = horizon
        try:
            event = crossing(body, start=ephem.Date(start), use_center=body is sun)
        except (ephem.AlwaysUpError, ephem.NeverUpError):
            continue
        utc = event.datetime().replace(tzinfo=timezone.utc)
        if utc < stop:
            events.append(dict(timestamp=utc.timestamp(), kind=kind, label=label))
    return events


def sensor_slots(config):
    """Select ambient temperature and humidity from the SAME instrument."""
    probes = {}
    for slot, meta in build_slot_label_map(config).items():
        parts = meta['key'].split('_', 2)
        if 10 <= slot < 60 and len(parts) == 3 and parts[0] == 'sensor':
            probes[slot] = (parts[1], parts[2])
    humid = {device for device, probe in probes.values() if probe == 'relative_humidity'}
    result = {}
    for slot, (device, probe) in sorted(probes.items()):
        if probe == 'sky_temperature':
            result.setdefault('sky_temperature', 'sensor_user_' + str(slot))
        elif probe == 'lux':
            result.setdefault('lux', 'sensor_user_' + str(slot))
        elif probe == 'temperature' and device in humid and 'air_temperature' not in result:
            result['air_temperature'] = 'sensor_user_' + str(slot)
            humidity = next(s for s, p in probes.items() if p == (device, 'relative_humidity'))
            result['humidity'] = 'sensor_user_' + str(humidity)
    return result


def metric_catalog(config):
    """Stable report IDs with labels from the configured sensor metadata."""
    slots = sensor_slots(config)
    unit = resolve_temp_unit(config)
    metrics = []
    for key, label in (('sky_temperature', 'Sky temperature'), ('lux', 'Sky brightness'),
                       ('air_temperature', 'Air temperature'), ('dew_point', 'Dew point')):
        if key in slots or key == 'dew_point' and 'humidity' in slots:
            metrics.append(dict(id=key, label=label, unit='lx' if key == 'lux' else unit,
                                kind='lux' if key == 'lux' else 'temperature'))
    primary = {value for key, value in slots.items() if key != 'humidity'}
    for index, meta in sorted(build_slot_label_map(config).items()):
        key = 'sensor_user_' + str(index)
        if not 10 <= index < 60 or key in primary:
            continue
        # Lux-derived SQM is not a calibrated sky brightness measurement.
        if meta['key'].endswith('_sqm'):
            continue
        kind = 'temperature' if meta.get('device_class') == 'temperature' else 'number'
        metrics.append(dict(id=key, label=meta['name'], unit=meta.get('unit', ''), kind=kind))
    return metrics


def frame_time(frame, tz):
    """Prefer the offset saved with the exposure, never the file's mtime."""
    wall = frame.createDate
    if wall.tzinfo is not None:
        return wall
    data = frame.data or {}
    offset = finite(data.get('utc_offset'))
    if offset is not None and abs(offset) < 86400:
        return wall.replace(tzinfo=timezone(timedelta(seconds=offset)))
    if 'utc_offset' in data:
        return None
    # Ambiguous or nonexistent old wall times cannot be reliably reconstructed.
    options = {wall.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc) for fold in (0, 1)}
    valid = [t for t in options if t.astimezone(tz).replace(tzinfo=None) == wall]
    if len(valid) != 1:
        return None
    return valid[0].astimezone(tz)


def finite(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError, OverflowError):
        return None


def reading(data, key):
    if not isinstance(key, str) or not key.startswith('sensor_user_'):
        return None
    try:
        slot = int(key.rsplit('_', 1)[1])
        if not 10 <= slot < 60:
            return None
        mask = data.get('sensor_valid_mask')
        if mask is not None:
            if isinstance(mask, bool) or not isinstance(mask, (int, str)):
                return None
            if int(mask) < 0 or not int(mask) & (1 << (slot - 10)):
                return None
    except (ValueError, TypeError, OverflowError):
        return None
    return finite(data.get(key))


def celsius(value, unit):
    if value is None:
        return None
    if unit == 'c':
        return value
    if unit == 'f':
        return (value - 32) * 5 / 9
    if unit == 'k':
        return value - 273.15
    return None


def display_temperature(value, unit):
    if value is None:
        return None
    return value * 9 / 5 + 32 if unit == '°F' else value + 273.15 if unit == 'K' else value


def sample(frame, dated, slots, temperature_unit, metrics=()):
    data = frame.data or {}
    saved = data.get('night_report_context', {})
    if isinstance(saved, dict) and isinstance(saved.get('sensors'), dict):
        slots = saved['sensors']
    # The current setting is not evidence of the units used by an older frame.
    stored_unit = data.get('temp_display')
    sky = celsius(reading(data, slots.get('sky_temperature')), stored_unit)
    air = celsius(reading(data, slots.get('air_temperature')), stored_unit)
    lux = reading(data, slots.get('lux'))
    humidity = reading(data, slots.get('humidity'))
    dew = None
    # Derived shared slots can retain stale values after a failed sensor. Derive
    # dew point only from this frame's valid paired ambient measurements.
    if air is not None and humidity is not None and 0 < humidity <= 100 and -100 <= air <= 100:
        alpha = 17.27 * air / (237.7 + air) + math.log(humidity / 100.)
        dew = 237.7 * alpha / (17.27 - alpha)
    result = dict(timestamp=dated.timestamp(), utc_offset=dated.utcoffset().total_seconds(),
                image_id=getattr(frame, 'id', None),
                exposure_seconds=finite(getattr(frame, 'exposure', None)),
                sensor_validity='tracked' if data.get('sensor_valid_mask') is not None else 'legacy_unverified',
                sky_temperature=display_temperature(sky, temperature_unit),
                lux=lux if lux is not None and lux >= 0 else None,
                air_temperature=display_temperature(air, temperature_unit),
                dew_point=display_temperature(dew, temperature_unit))
    for metric in metrics:
        key = metric['id']
        if not key.startswith('sensor_user_'):
            continue
        if isinstance(saved, dict) and isinstance(saved.get('metrics'), list):
            old = next((m for m in saved['metrics'] if m.get('id') == key), None)
            if old is None or any(old.get(k) != metric.get(k) for k in ('label', 'kind')):
                result[key] = None
                continue
        value = reading(data, key)
        if metric['kind'] == 'temperature':
            value = display_temperature(celsius(value, stored_unit), temperature_unit)
        elif metric['unit'] in ('hPa', 'psi', 'inHg', 'mmHg'):
            factors = {'hpa': 1., 'psi': 68.9475729, 'inhg': 33.8638867, 'mmhg': 1.33322387}
            before, after = str(data.get('pressure_display', '')).lower(), metric['unit'].lower()
            value = (value * factors[before] / factors[after]
                     if value is not None and before in factors else None)
        elif metric['unit'] in ('m/s', 'mph', 'kn', 'km/h'):
            factors = {'ms': 1., 'mph': .44704, 'knots': .514444444, 'kph': 1/3.6}
            after = {'m/s': 'ms', 'mph': 'mph', 'kn': 'knots', 'km/h': 'kph'}[metric['unit']]
            before = data.get('windspeed_display')
            value = (value * factors[before] / factors[after]
                     if value is not None and before in factors else None)
        result[key] = value
    return result


def _crop_strip(kg, data):
    trimmed = kg.trimEdges(data)
    h = trimmed.shape[0]
    top, bottom = int(h * kg.crop_top / 100), int(h * kg.crop_bottom / 100)
    cropped = trimmed[top:h-bottom]
    if not cropped.size:
        raise ValueError('Keogram crop leaves no image for the night report')
    return cv2.cvtColor(cv2.resize(cropped, (cropped.shape[1], 320),
                                   interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)


def _strips(config, timed, keogram_source=None):
    if keogram_source is not None and getattr(keogram_source, 'report_entries', None):
        entries = keogram_source.report_entries
        raw = keogram_source.keogram_data
        if raw is not None and raw.shape[1] == len(entries) + 1:
            # The legacy generator begins with one unused column.
            timestamps = {entry.id: dated.timestamp() for entry, dated in timed}
            columns = [i for i, entry in enumerate(entries) if entry.id in timestamps]
            if columns:
                return (_crop_strip(keogram_source, raw[:, [i+1 for i in columns]]),
                        [timestamps[entries[i].id] for i in columns])
    # Report-only backfills need no complete new timelapse. Bound image I/O to
    # one real exposure per minute; CSV retains all valid exposure samples.
    selected = {}
    for entry, dated in timed:
        if not getattr(entry, 'exclude', False):
            selected.setdefault(int(dated.timestamp() // 60), []).append((entry, dated))
    kg = KeogramGenerator(config)
    kg.crop_top = config.get('KEOGRAM_CROP_TOP', 0)
    kg.crop_bottom = config.get('KEOGRAM_CROP_BOTTOM', 0)
    strips, times = [], []
    for candidates in selected.values():
        for entry, dated in candidates:
            path = Path(entry.getFilesystemPath())
            try:
                with Image.open(path) as source:
                    data = cv2.cvtColor(np.asarray(source.convert('RGB')), cv2.COLOR_RGB2BGR)
                kg.keogram_data = None
                kg.timestamps = []
                kg.processImage(data, dated.timestamp())
                strips.append(_crop_strip(kg, kg.keogram_data[:, -1:]))
                times.append(dated.timestamp())
                break
            except (OSError, ValueError, cv2.error) as exc:
                if isinstance(exc, OSError) and exc.errno is not None and not isinstance(exc, FileNotFoundError):
                    raise
                logger.warning('Night report skipped image %s: %s', path, exc)
    if not strips:
        raise ValueError('No readable source images for the night report')
    return np.concatenate(strips, axis=1), times


def _location(camera, timed):
    locations = []
    for entry, _ in timed:
        data = entry.data or {}
        context = data.get('night_report_context') or {}
        raw = context.get('location') if isinstance(context, dict) else None
        if isinstance(raw, (tuple, list)) and len(raw) >= 2:
            lat, lon = finite(raw[0]), finite(raw[1])
            if lat is not None and lon is not None and abs(lat) <= 90 and abs(lon) <= 180:
                locations.append((lat, lon, (finite(raw[2]) or 0) if len(raw) > 2 else 0))
    if locations:
        lat, lon, elev = locations[0]
        if any(abs(a-lat) > .1 or abs(b-lon) > .1 for a,b,_ in locations):
            return None, 'Location changed; astronomical events omitted'
        return (lat, lon, elev), 'Location recorded with exposures'
    if camera.latitude is None or camera.longitude is None:
        return None, 'Location unknown; astronomical events omitted'
    return (camera.latitude, camera.longitude, camera.elevation or 0), 'Events use camera location (legacy exposures)'


def prepare_report(config, camera, date, entries, keogram_source=None):
    """Prepare one local observing night's report without consulting live sensors."""
    entries = list(entries)
    tz = camera_timezone(camera)
    for entry in entries:
        name = ((entry.data or {}).get('night_report_context') or {}).get('timezone')
        if name:
            try:
                tz = ZoneInfo(name)
                break
            except (ZoneInfoNotFoundError, ValueError, TypeError):
                pass
    timed = []
    for entry in entries:
        dated = frame_time(entry, tz)
        if dated is not None:
            timed.append((entry, dated))
    timed.sort(key=lambda pair: (pair[1].timestamp(), pair[0].id))
    if not timed:
        raise ValueError('No unambiguous exposure timestamps for the night report')
    unit = resolve_temp_unit(config)
    slots = sensor_slots(config)
    metrics = metric_catalog(config)
    # Prefer recorded assignments when revisiting an old night after a sensor
    # was unplugged or replaced. Do not reinterpret its slots using new names.
    recorded = [(e.data or {}).get('night_report_context', {}) for e, _ in timed]
    recorded_catalogs = [ctx['metrics'] for ctx in recorded
                         if isinstance(ctx, dict) and isinstance(ctx.get('metrics'), list)]
    if recorded_catalogs:
        by_id = {}
        for catalog in recorded_catalogs:
            for metric in catalog:
                if metric['id'] not in by_id:
                    item = dict(metric)
                    if item['kind'] == 'temperature':
                        item['unit'] = unit
                    by_id[item['id']] = item
        metrics = list(by_id.values())
    samples = [sample(e, t, slots, unit, metrics) for e, t in timed]
    for index, row in enumerate(samples):
        row.update(camera_uuid=getattr(camera, 'uuid', ''), camera_id=getattr(camera, 'id', None),
                   night_date=date.isoformat(), time_reference='recorded_capture_time',
                   gap_before_seconds=None if not index else row['timestamp']-samples[index-1]['timestamp'])
    metrics = [m for m in metrics if any(row.get(m['id']) is not None for row in samples)]
    keogram_rgb, frame_times = _strips(config, timed, keogram_source)
    location, location_note = _location(camera, timed)
    events = night_events(date, tz, location) if location else []
    zone = getattr(tz, 'key', None) or str(tz)
    return dict(title='Night Report · ' + date.isoformat(), samples=samples,
                keogram_rgb=keogram_rgb, frame_times=frame_times, events=events,
                timezone_name=zone, temperature_unit=unit,
                metrics=metrics,
                subtitle='{} · {} exposures · {}'.format(camera.name, len(samples), location_note))
