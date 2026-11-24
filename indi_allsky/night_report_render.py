"""Portable PNG/CSV night reports on an elapsed-time axis.

Only Pillow and NumPy are required. Sensor samples and keogram columns retain
separate timestamps: a missing exposure must not compress the observing night.
"""
import csv
import json
from datetime import datetime, timedelta, timezone
import math
import re
from pathlib import Path
from statistics import median
try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # Python 3.7 on Debian 10
    from backports.zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
from PIL import Image, ImageDraw, ImageFont


WIDTH, HEIGHT = 2400, 1620
LEFT, RIGHT = 205, 2310
BACKGROUND = '#101a17'
SURFACE = '#192620'
PLOT = '#121e19'
INK = '#e7eee9'
MUTED = '#a1b5a9'
GRID = '#32463b'
COLORS = {'sky_temperature': '#72cbe1', 'lux': '#e9c76a',
          'air_temperature': '#62d79b', 'dew_point': '#bf9fea'}
EVENT_COLORS = {'dusk': '#de9b75', 'dawn': '#de9b75',
                'moonrise': '#c4cce5', 'moonset': '#c4cce5'}
FIELDS = ('sky_temperature', 'lux', 'air_temperature', 'dew_point')
PANELS = ((292, 642, 358, 620), (662, 922, 718, 900),
          (942, 1202, 998, 1180), (1222, 1482, 1278, 1460))


def _finite(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _samples(samples, keys=FIELDS):
    result = []
    metadata = ('camera_uuid', 'camera_id', 'night_date', 'image_id', 'exposure_seconds',
                'time_reference', 'sensor_validity', 'gap_before_seconds')
    for item in samples:
        stamp = _finite(item.get('timestamp'))
        if stamp is None:
            continue
        row = {'timestamp': stamp, 'utc_offset': _finite(item.get('utc_offset'))}
        row.update({key: item.get(key) for key in metadata})
        row.update({key: _finite(item.get(key)) for key in keys})
        if row.get('lux') is not None and row['lux'] < 0:
            row['lux'] = None
        result.append(row)
    # Distinct images with identical timestamps remain distinct CSV rows.
    return sorted(result, key=lambda row: row['timestamp'])


def _font(size, bold=False):
    name = 'LiberationSans-Bold.ttf' if bold else 'LiberationSans-Regular.ttf'
    source = Path(__file__).resolve().parent / 'fonts' / 'liberation2' / name
    try:
        return ImageFont.truetype(str(source), size)
    except OSError:
        for candidate in ('DejaVuSans.ttf', '/System/Library/Fonts/Supplemental/Arial.ttf'):
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                pass
        return ImageFont.load_default()


def _fitted(draw, value, font, width):
    value = ' '.join(str(value).split())
    while value and draw.textlength(value, font=font) > width:
        value = value[:-2]
    return value


def _zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return None


def _dated(stamp, samples, zone):
    if zone is not None:
        return datetime.fromtimestamp(stamp, zone)
    # An unknown historical zone is still unambiguous when each image has its
    # recorded UTC offset. Use the preceding exposure for chart ticks only.
    prior = next((row for row in reversed(samples) if row['timestamp'] <= stamp),
                 samples[0] if samples else {})
    offset = prior.get('utc_offset') or 0
    if not -86400 < offset < 86400:
        offset = 0
    return datetime.fromtimestamp(stamp, timezone(timedelta(seconds=offset)))


def _gap_limit(stamps):
    gaps = [b-a for a, b in zip(stamps, stamps[1:]) if b > a]
    return max(90., min(300., 3 * median(gaps))) if gaps else 90.


def _segments(samples, key, gap):
    """Yield contiguous valid observations; outages and invalid reads break lines."""
    segment = []
    for row in samples:
        value = row[key]
        if value is None or (segment and row['timestamp'] - segment[-1][0] > gap):
            if segment:
                yield segment
            segment = []
        if value is not None:
            segment.append((row['timestamp'], value))
    if segment:
        yield segment


def _keogram_pixels(rgb, frame_times, start, end, width, height):
    """Nearest-column reconstruction with bounded support around each exposure."""
    pixels = np.empty((height, width, 3), dtype=np.uint8)
    pixels[:] = tuple(bytes.fromhex(PLOT[1:]))
    if rgb is None or not len(frame_times):
        return pixels, 0
    source = np.asarray(rgb)
    if source.ndim != 3 or source.shape[2] != 3 or source.shape[1] != len(frame_times):
        raise ValueError('Keogram columns must match their capture timestamps')
    valid = [(float(stamp), i) for i, stamp in enumerate(frame_times) if _finite(stamp) is not None]
    if not valid or source.shape[0] == 0:
        return pixels, 0
    # Prefer the last column when an imported frame duplicates a timestamp.
    columns = dict(valid)
    stamps = np.array(sorted(columns), dtype=float)
    indices = [columns[stamp] for stamp in stamps]
    source = source[:, indices, :].astype(np.uint8)
    # Bound vertical memory by output height before expanding the time axis.
    source = np.asarray(Image.fromarray(source).resize((len(stamps), height), Image.Resampling.BILINEAR))
    positions = start + np.linspace(0, end-start, width)
    right = np.searchsorted(stamps, positions).clip(0, len(stamps)-1)
    left = (right-1).clip(0, len(stamps)-1)
    nearest = np.where(np.abs(positions-stamps[left]) <= np.abs(positions-stamps[right]), left, right)
    cadence = median(np.diff(stamps)) if len(stamps) > 1 else 30.
    support = min(_gap_limit(stamps), max(1., cadence * 1.5)) / 2
    visible = np.abs(stamps[nearest]-positions) <= support
    # At least one output pixel represents each genuine exposure, even when
    # the report compresses a long observing night to a small image.
    discrete = np.rint((stamps-start)/(end-start)*(width-1)).astype(int).clip(0, width-1)
    visible[discrete] = True
    pixels[:, visible] = source[:, nearest[visible], :]
    return pixels, len(stamps)


def _number(value):
    if value == 0:
        return '0'
    absolute = abs(value)
    if absolute < .001 or absolute >= 100000:
        return format(value, '.2g')
    if absolute < .1:
        return format(value, '.4f').rstrip('0').rstrip('.')
    if absolute < 10:
        return format(value, '.2f').rstrip('0').rstrip('.')
    return format(value, '.1f').rstrip('0').rstrip('.')


def _linear_scale(values, minimum_span=2.):
    low, high = min(values), max(values)
    span = max(high-low, minimum_span, abs(high)*.01)
    low, high = low-span*.12, high+span*.12
    rough = (high-low)/4
    power = 10 ** math.floor(math.log10(rough))
    step = next(factor*power for factor in (1, 2, 2.5, 5, 10) if factor*power >= rough)
    low = math.floor(low/step)*step
    high = math.ceil(high/step)*step
    ticks = list(np.arange(low, high+step*.1, step))
    return low, high, ticks, lambda value: value, ''


def _lux_scale(values):
    highest = max(values)
    positive = [value for value in values if value > 0]
    if not positive or highest/min(positive) < 100:
        high = max(highest*1.12, .001)
        return 0, high, list(np.linspace(0, high, 5)), lambda value: value, ''
    threshold = 10 ** math.floor(math.log10(min(positive)))
    def transform(value):
        if value <= threshold:
            return value/threshold
        return 1 + math.log10(value) - math.log10(threshold)
    high = transform(highest)*1.07
    decades = list(range(math.floor(math.log10(threshold)), math.ceil(math.log10(highest))+1))
    stride = max(1, math.ceil(len(decades)/5))
    ticks = [0.] + [10.**power for power in decades[::stride] if transform(10.**power) <= high]
    return 0, high, ticks, transform, 'Log scale; linear near zero'


def _ticks(start, end):
    duration = end-start
    steps = [60, 300, 600, 900, 1800, 3600, 7200, 10800, 14400, 21600, 43200, 86400]
    step = next((step for step in steps if duration/step <= 9), 86400)
    first = math.ceil(start/step)*step
    result = list(np.arange(first, end+1, step))
    return result if len(result) >= 2 else [start, end]


def _dashed(draw, x, top, bottom, fill):
    for y in range(top, bottom, 16):
        draw.line((x, y, x, min(y+7, bottom)), fill=fill, width=2)


def _catalog(metrics, temperature_unit):
    if metrics is None:
        metrics = [
            dict(id='sky_temperature', label='Sky temperature', unit=temperature_unit, kind='temperature'),
            dict(id='lux', label='Sky brightness', unit='lx', kind='lux'),
            dict(id='air_temperature', label='Air temperature', unit=temperature_unit, kind='temperature'),
            dict(id='dew_point', label='Dew point', unit=temperature_unit, kind='temperature'),
        ]
    result = {}
    for item in metrics:
        if not isinstance(item, dict):
            continue
        key = item.get('id')
        if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{0,63}', key):
            continue
        if key in ('timestamp', 'utc_offset'):
            continue
        kind = item.get('kind', 'number')
        result.setdefault(key, dict(id=key, label=str(item.get('label') or key),
                                    unit=str(item.get('unit') or ''),
                                    kind=kind if kind in ('temperature', 'lux', 'number') else 'number'))
    return list(result.values())


def _groups(catalog, selected):
    by_id = {item['id']: item for item in catalog}
    combine = (all(key in selected for key in ('air_temperature', 'dew_point'))
               and by_id['air_temperature']['unit'] == by_id['dew_point']['unit'])
    result, added = [], set()
    for key in selected:
        if key in added:
            continue
        keys = (['air_temperature', 'dew_point']
                if combine and key in ('air_temperature', 'dew_point') else [key])
        result.append([by_id[item] for item in keys])
        added.update(keys)
    return result


def _csv_header(metric):
    key, unit = metric['id'], metric['unit']
    if key == 'lux':
        return 'sky_brightness_lux'
    suffix = {'°C': 'c', '°F': 'f', 'K': 'k', '%': 'percent'}.get(unit)
    if suffix is None:
        suffix = re.sub(r'[^a-zA-Z0-9]+', '_', unit).strip('_').lower()
    return key + ('_' + suffix if suffix else '')


def _csv_text(value):
    text = '' if value is None else str(value)
    text = text.replace('\r', ' ').replace('\n', ' ')
    # CSV is also commonly opened directly in spreadsheets. Station metadata
    # must never become a spreadsheet formula, even for an imported camera.
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) else text


def _csv_number(value, *, integer=False):
    number = _finite(value)
    if number is None:
        return ''
    return str(int(number)) if integer and number.is_integer() else format(number, '.12g')


def _write_csv(path, samples, zone, catalog):
    with Path(path).open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['schema_version', 'camera_uuid', 'camera_id', 'night_date', 'image_id',
                         'timestamp_utc', 'timestamp_local', 'utc_offset_seconds', 'unix_time',
                         'exposure_seconds', 'time_reference', 'sensor_validity', 'gap_before_seconds', 'valid_fields',
                         'metric_catalog_json',
                         *[_csv_header(metric) for metric in catalog]])
        # The first observation carries its column definitions so the CSV is
        # self-describing without a separate manifest or hardware assumptions.
        definitions = json.dumps([dict(metric, csv_column=_csv_header(metric)) for metric in catalog],
                                 ensure_ascii=False, separators=(',', ':'))
        for index, row in enumerate(samples):
            stamp = row['timestamp']
            utc = datetime.fromtimestamp(stamp, timezone.utc)
            offset = row['utc_offset']
            if offset is not None and -86400 < offset < 86400:
                local = datetime.fromtimestamp(stamp, timezone(timedelta(seconds=offset)))
            else:
                local = _dated(stamp, samples, zone)
            writer.writerow([
                1, _csv_text(row.get('camera_uuid')), _csv_number(row.get('camera_id'), integer=True),
                _csv_text(row.get('night_date')), _csv_number(row.get('image_id'), integer=True),
                utc.isoformat(), local.isoformat(), int(local.utcoffset().total_seconds()),
                format(stamp, '.6f'), _csv_number(row.get('exposure_seconds')),
                _csv_text(row.get('time_reference')), _csv_text(row.get('sensor_validity')),
                _csv_number(row.get('gap_before_seconds')),
                ';'.join(metric['id'] for metric in catalog if row[metric['id']] is not None),
                definitions if index == 0 else '',
                *['' if row[metric['id']] is None else format(row[metric['id']], '.10g')
                  for metric in catalog],
            ])


def render_report(png_path, csv_path, *, title, samples, keogram_rgb, frame_times,
                  events, timezone_name='UTC', temperature_unit='°C', subtitle='',
                  metrics=None, selected_metrics=None):
    """Write a self-contained report; invalid measurements remain blank in CSV.

    The caller publishes the two files atomically after both have been written.
    Timestamps must be UTC epoch seconds, not naive local datetimes. Output
    temperatures are already converted by the data provider to temperature_unit.
    """
    catalog = _catalog(metrics, temperature_unit)
    available = {item['id'] for item in catalog}
    requested = FIELDS if selected_metrics is None else selected_metrics
    selected = list(dict.fromkeys(key for key in requested if key in available))
    groups = _groups(catalog, selected)
    panels = [PANELS[0]] + [(662+i*280, 922+i*280, 718+i*280, 900+i*280)
                             for i in range(len(groups))]
    report_height = panels[-1][1] + 138
    samples = _samples(samples, [metric['id'] for metric in catalog])
    for row in samples:
        for metric in catalog:
            if metric['kind'] == 'lux' and row[metric['id']] is not None and row[metric['id']] < 0:
                row[metric['id']] = None
    frame_times = list(frame_times)
    stamps = [row['timestamp'] for row in samples]
    stamps.extend(stamp for stamp in (_finite(t) for t in frame_times) if stamp is not None)
    if not stamps:
        raise ValueError('Night report requires timestamped observations')
    start, end = min(stamps), max(stamps)
    if end <= start:
        start, end = start-30, end+30
    zone = _zone(timezone_name)
    x_position = lambda stamp: LEFT + (stamp-start)/(end-start)*(RIGHT-LEFT)
    ticks = _ticks(start, end)
    events = [dict(item, timestamp=_finite(item.get('timestamp'))) for item in events
              if _finite(item.get('timestamp')) is not None]
    events = sorted((event for event in events if start <= event['timestamp'] <= end),
                    key=lambda event: event['timestamp'])
    canvas = Image.new('RGB', (WIDTH, report_height), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    small, regular, heading, large = _font(23), _font(28), _font(30, True), _font(50, True)
    draw.text((72, 42), 'INDI-ALLSKY  /  NIGHT REPORT', font=_font(23, True), fill=COLORS['air_temperature'])
    draw.text((72, 82), _fitted(draw, title, large, WIDTH-144), font=large, fill=INK)
    local_start, local_end = _dated(start, samples, zone), _dated(end, samples, zone)
    duration = f'{local_start:%d %b %Y, %H:%M} — {local_end:%d %b %Y, %H:%M}'
    caption = duration + '  ·  ' + str(timezone_name)
    if subtitle:
        caption += '  ·  ' + str(subtitle)
    draw.text((74, 150), _fitted(draw, caption, regular, WIDTH-148), font=regular, fill=MUTED)

    # The exact times remain readable even when several vertical markers fall
    # near one another (e.g. moonrise shortly before astronomical dawn).
    legend_x, legend_y = 74, 205
    for event in events:
        dated = _dated(event['timestamp'], samples, zone)
        label = str(event.get('label') or event.get('kind', 'Event'))
        text = f'{label}  {dated:%H:%M}'
        label_width = min(draw.textlength(text, font=small)+48, 1050)
        if legend_x + label_width > WIDTH-74:
            legend_x, legend_y = 74, legend_y+38
        if legend_y > 250:
            break
        color = EVENT_COLORS.get(event.get('kind'), MUTED)
        draw.line((legend_x, legend_y+13, legend_x+18, legend_y+13), fill=color, width=3)
        draw.text((legend_x+28, legend_y), _fitted(draw, text, small, label_width-30), font=small, fill=INK)
        legend_x += label_width
    if not events:
        draw.text((74, 205), 'No twilight or moonrise/moonset events within this recording', font=small, fill=MUTED)

    titles = ['Keogram']
    for group in groups:
        label = ('Air temperature & dew point' if len(group) == 2 else group[0]['label'])
        unit = group[0]['unit']
        titles.append(label + (f' ({unit})' if unit else ''))
    for index, (top, bottom, chart_top, chart_bottom) in enumerate(panels):
        draw.rounded_rectangle((64, top, WIDTH-64, bottom), radius=16, fill=SURFACE)
        draw.text((86, top+17), _fitted(draw, titles[index], heading, 1400), font=heading, fill=INK)
        draw.rectangle((LEFT, chart_top, RIGHT, chart_bottom), fill=PLOT)
        for tick in ticks:
            draw.line((round(x_position(tick)), chart_top, round(x_position(tick)), chart_bottom), fill=GRID)

    # Keogram uses actual capture times, irrespective of source file mtimes or
    # changing exposure periods; the unobserved interval remains dark.
    _, _, top, bottom = panels[0]
    strip, frame_count = _keogram_pixels(keogram_rgb, frame_times, start, end,
                                         RIGHT-LEFT+1, bottom-top+1)
    canvas.paste(Image.fromarray(strip), (LEFT, top))
    if not frame_count:
        draw.text((LEFT+30, (top+bottom)//2-15), 'No usable image slices', font=regular, fill=MUTED)
    detail = f'{frame_count:,} image slices  ·  Capture times preserved'
    draw.text((RIGHT-draw.textlength(detail, font=small), panels[0][0]+22), detail, font=small, fill=MUTED)

    gaps = _gap_limit([row['timestamp'] for row in samples])
    palette = ('#72cbe1', '#e9c76a', '#62d79b', '#bf9fea', '#e99fb8', '#84b4ed', '#dfb18a')
    for index, group in enumerate(groups, 1):
        keys = [metric['id'] for metric in group]
        unit = group[0]['unit']
        panel_top, _, top, bottom = panels[index]
        values = [row[key] for row in samples for key in keys if row[key] is not None]
        if not values:
            draw.text((LEFT+30, (top+bottom)//2-15), 'No valid sensor readings', font=regular, fill=MUTED)
            continue
        if group[0]['kind'] == 'lux':
            low, high, y_ticks, transform, note = _lux_scale(values)
        else:
            low, high, y_ticks, transform, note = _linear_scale(
                values, 2. if group[0]['kind'] == 'temperature' else 1e-6)
        y_position = lambda value: bottom-(transform(value)-low)/(high-low)*(bottom-top)
        for tick in y_ticks:
            y = round(y_position(tick))
            label = _number(tick)
            draw.line((LEFT, y, RIGHT, y), fill=GRID)
            draw.text((LEFT-18-draw.textlength(label, font=small), y-13), label, font=small, fill=MUTED)
        for key in keys:
            color = COLORS.get(key, palette[(index-1) % len(palette)])
            for segment in _segments(samples, key, gaps):
                points = [(round(x_position(stamp)), round(y_position(value))) for stamp, value in segment]
                if len(points) == 1:
                    x, y = points[0]
                    draw.ellipse((x-3, y-3, x+3, y+3), fill=color)
                else:
                    draw.line(points, fill=color, width=4, joint='curve')
        if len(group) == 2:
            legend = [('Air', 'air_temperature'), ('Dew point', 'dew_point')]
            x = RIGHT-320
            for label, key in legend:
                draw.line((x, panel_top+35, x+28, panel_top+35), fill=COLORS[key], width=4)
                draw.text((x+37, panel_top+21), label, font=small, fill=INK)
                x += 140
        else:
            label = f'{_number(min(values))} – {_number(max(values))} {unit}'
            if note:
                label += '  ·  ' + note
            draw.text((RIGHT-draw.textlength(label, font=small), panel_top+22), label, font=small, fill=MUTED)

    for event in events:
        x = round(x_position(event['timestamp']))
        for _, _, top, bottom in panels:
            _dashed(draw, x, top, bottom, EVENT_COLORS.get(event.get('kind'), MUTED))
    labels = [_dated(tick, samples, zone).strftime('%H:%M') for tick in ticks]
    duplicate_times = len(set(labels)) != len(labels)
    for tick, label in zip(ticks, labels):
        dated = _dated(tick, samples, zone)
        if duplicate_times:
            label += ' ' + dated.strftime('%z')
        width = draw.textlength(label, font=small)
        x = min(WIDTH-72-width, max(72, x_position(tick)-width/2))
        draw.text((x, panels[-1][1]+15), label, font=small, fill=INK)
    footer = 'Gaps indicate missing observations. Curves and image slices share the same capture-time axis.'
    draw.text((74, panels[-1][1]+78), footer, font=small, fill=MUTED)
    credit = 'indi-allsky'
    draw.text((WIDTH-74-draw.textlength(credit, font=small), panels[-1][1]+78), credit, font=small, fill=MUTED)
    canvas.save(str(png_path), format='PNG', optimize=True)
    _write_csv(csv_path, samples, zone, catalog)
    return {'width': WIDTH, 'height': report_height, 'samples': len(samples), 'frames': frame_count,
            'start': start, 'end': end, 'events': events, 'timezone': timezone_name,
            'temperature_unit': temperature_unit, 'metrics': catalog, 'selected_metrics': selected,
            'csv_schema_version': 1}
