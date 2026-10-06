"""Shared chart definitions for history pages and latest-image overlays."""

import math
import re


MAX_CUSTOM_CHARTS = 64
BUILTIN_CHARTS = (
    {'id': 'jsqm', 'source': 'jsqm', 'label': 'jSQM', 'min': None},
    {'id': 'stars', 'source': 'stars', 'label': 'Stars', 'min': 0.0},
    {'id': 'temp', 'source': 'temp', 'label': 'Camera temperature', 'min': None},
    {'id': 'exp', 'source': 'exp', 'label': 'Exposure', 'min': 0.0},
    {'id': 'gain', 'source': 'gain', 'label': 'Gain', 'min': 0.0},
    {'id': 'detection', 'source': 'detection', 'label': 'Detection', 'min': 0.0},
)
SENSOR_SOURCES = tuple('sensor_user_{0}'.format(index) for index in range(110)) + tuple(
    'sensor_temp_{0}'.format(index) for index in range(60))
METADATA_SOURCES = ('kpindex', 'ovation_max', 'aurora_mag_bt', 'aurora_mag_gsm_bz',
                    'aurora_plasma_density', 'aurora_plasma_speed', 'aurora_plasma_temp',
                    'aurora_n_hemi_gw', 'aurora_s_hemi_gw', 'camera_sqm_raw_mag')
NONNEGATIVE_SOURCES = {'stars', 'exp', 'detection', 'kpindex', 'ovation_max', 'aurora_mag_bt',
                       'aurora_plasma_density', 'aurora_plasma_speed', 'aurora_plasma_temp',
                       'aurora_n_hemi_gw', 'aurora_s_hemi_gw'}
NONNEGATIVE_SENSOR_UNITS = {'%', 'hPa', 'm/s', 'mm', 'lx', 'rpm', 'ADU'}


def validate_custom_charts(definitions):
    if not isinstance(definitions, list) or len(definitions) > MAX_CUSTOM_CHARTS:
        raise ValueError('Configure no more than {0} custom charts'.format(MAX_CUSTOM_CHARTS))
    result = []
    identifiers = {definition['id'] for definition in BUILTIN_CHARTS}
    for definition in definitions:
        if not isinstance(definition, dict):
            raise ValueError('Invalid chart definition')
        identifier = definition.get('id', '')
        if not isinstance(identifier, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', identifier):
            raise ValueError('Invalid chart identifier')
        if identifier in identifiers or identifier == 'histogram':
            raise ValueError('Chart identifiers must be unique')
        identifiers.add(identifier)
        source = definition.get('source')
        if source not in SENSOR_SOURCES + METADATA_SOURCES:
            raise ValueError('Select an available sensor source')
        label = definition.get('label', '')
        if not isinstance(label, str) or len(label) > 80:
            raise ValueError('Chart names must be 80 characters or fewer')
        minimum = definition.get('min')
        if minimum is not None:
            if isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or not math.isfinite(minimum):
                raise ValueError('Chart minimum must be a finite number or automatic')
            minimum = float(minimum)
        result.append({'id': identifier, 'source': source, 'label': label.strip(), 'min': minimum})
    return result


def custom_charts(config, camera_data=None):
    settings = config.get('CHARTS', {})
    metadata = camera_data or {}
    definitions = metadata.get('chart_definitions', settings.get('CUSTOM'))
    if definitions is not None:
        return validate_custom_charts(definitions)
    return [
        {'id': 'custom_{0}'.format(index),
         'source': metadata.get('custom_chart_{0}_key'.format(index),
                                settings.get('CUSTOM_SLOT_{0}'.format(index), 'sensor_user_{0}'.format(index + 9))),
         'label': '',
         'min': metadata.get('custom_chart_{0}_min'.format(index), settings.get('CUSTOM_SLOT_{0}_MIN'.format(index), 0.0))}
        for index in range(1, 10)
    ]


def chart_definitions(config, camera_data=None, is_local=False):
    from .sensors_mapping import DEFAULT_FIXED_SLOTS, build_slot_label_map

    metadata = camera_data or {}
    definitions = [dict(definition) for definition in BUILTIN_CHARTS]
    for definition in custom_charts(config, None if is_local else metadata):
        definition = dict(definition)
        definition['label'] = definition['label'] or metadata.get(definition['source'], definition['source'])
        definitions.append(definition)
    slot_map = {sensor['slot']: sensor for sensor in DEFAULT_FIXED_SLOTS}
    if is_local and config.get('TEMP_SENSOR'):
        slot_map.update(build_slot_label_map(config))
    published = {definition['id']: definition.get('nonnegative') is True
                 for definition in metadata.get('chart_definitions', []) or []}
    for definition in definitions:
        source = definition['source']
        sensor = slot_map.get(int(source.rsplit('_', 1)[1]), {}) if source.startswith('sensor_user_') else {}
        if (source in NONNEGATIVE_SOURCES or sensor.get('unit') in NONNEGATIVE_SENSOR_UNITS
                or not is_local and published.get(definition['id'], False)):
            definition['nonnegative'] = True
    return definitions


def chart_value(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value


def validate_chart_configuration(settings):
    if not isinstance(settings, dict):
        raise ValueError('Invalid chart configuration')
    definitions = validate_custom_charts(settings.get('CUSTOM', []))
    identifiers = [definition['id'] for definition in BUILTIN_CHARTS + tuple(definitions)]
    result = {'CUSTOM': definitions}
    limits = settings.get('AXIS_LIMITS', {})
    if not isinstance(limits, dict) or any(identifier not in identifiers for identifier in limits):
        raise ValueError('Invalid chart axis selection')
    result['AXIS_LIMITS'] = {}
    for identifier, bounds in limits.items():
        if not isinstance(bounds, dict):
            raise ValueError('Invalid chart axis limits')
        normalized = {}
        for key in ('min', 'max'):
            value = bounds.get(key)
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError('Chart axis limits must be finite numbers or automatic')
                try:
                    value = float(value)
                except OverflowError:
                    raise ValueError('Chart axis limits must be finite numbers or automatic')
                if not math.isfinite(value):
                    raise ValueError('Chart axis limits must be finite numbers or automatic')
            normalized[key] = value
        if normalized['min'] is not None and normalized['max'] is not None and normalized['min'] >= normalized['max']:
            raise ValueError('Chart axis minimum must be below its maximum')
        if any(value is not None for value in normalized.values()):
            result['AXIS_LIMITS'][identifier] = normalized
    for key, available, default in (
        ('VISIBLE_IDS', identifiers + ['histogram'], identifiers + ['histogram']),
        ('OVERLAY_IDS', identifiers, []),
        ('SAVED_IMAGE_IDS', identifiers, []),
    ):
        selected = settings.get(key, default)
        if selected is None and key == 'VISIBLE_IDS':
            selected = default
        if not isinstance(selected, list) or any(not isinstance(identifier, str) or identifier not in available for identifier in selected):
            raise ValueError('Invalid chart selection')
        if len(selected) != len(set(selected)):
            raise ValueError('Select each chart only once')
        if key != 'VISIBLE_IDS' and len(selected) > 4:
            destination = 'Browser' if key == 'OVERLAY_IDS' else 'Saved image'
            raise ValueError('Only 4 charts are allowed for {0}.'.format(destination))
        result[key] = selected
    for key, default, minimum, maximum in (
        ('OVERLAY_HISTORY_SECONDS', 900, 60, 86400),
        ('SAVED_IMAGE_HISTORY_SECONDS', settings.get('OVERLAY_HISTORY_SECONDS', 900), 60, 86400),
        ('OVERLAY_TOP', 120, 0, 600),
        ('OVERLAY_WIDTH', 260, 180, 400),
        ('OVERLAY_OPACITY', 30, 20, 100),
    ):
        value = settings.get(key, default)
        if key == 'SAVED_IMAGE_HISTORY_SECONDS' and value is None:
            value = default
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError('Invalid {0}'.format(key.lower().replace('_', ' ')))
        result[key] = value
    return result


def chart_configuration(config, camera_data=None, is_local=True):
    settings = dict(config.get('CHARTS', {}))
    local_definitions = custom_charts(config)
    settings['CUSTOM'] = custom_charts(config, None if is_local else camera_data)
    if not is_local:
        remote_ids = {definition['id'] for definition in settings['CUSTOM']}
        identifiers = {definition['id']: definition['id'] for definition in BUILTIN_CHARTS}
        identifiers['histogram'] = 'histogram'
        for definition in local_definitions:
            match = next((remote for remote in settings['CUSTOM'] if remote['source'] == definition['source']), None)
            if definition['id'] in remote_ids:
                identifiers[definition['id']] = definition['id']
            elif match:
                identifiers[definition['id']] = match['id']
        for key in ('VISIBLE_IDS', 'OVERLAY_IDS', 'SAVED_IMAGE_IDS'):
            if settings.get(key) is not None:
                settings[key] = list(dict.fromkeys(identifiers[identifier] for identifier in settings[key] if identifier in identifiers))
        settings['AXIS_LIMITS'] = {
            identifiers[identifier]: bounds
            for identifier, bounds in settings.get('AXIS_LIMITS', {}).items()
            if identifier in identifiers
        }
    return validate_chart_configuration(settings)


def build_chart_data(readings, definitions, temperature_display='c', selected_ids=None, include_timestamp=False):
    definitions = [definition for definition in definitions
                   if selected_ids is None or definition['id'] in selected_ids]
    result = {definition['id']: [] for definition in definitions}
    for reading in readings:
        timestamp = reading.createDate.strftime('%H:%M:%S')
        temperature = chart_value(reading.temp)
        if temperature is not None:
            if temperature_display == 'f':
                temperature = temperature * 9.0 / 5.0 + 32
            elif temperature_display == 'k':
                temperature += 273.15
        stars = chart_value(reading.stars_rolling)
        values = {'jsqm': reading.jsqm, 'stars': int(stars) if stars is not None else None,
                  'temp': temperature, 'exp': reading.exposure, 'gain': reading.gain,
                  'detection': int(reading.detections > 0) if reading.detections is not None else None}
        metadata = reading.data or {}
        for definition in definitions:
            source = definition['source']
            value = values.get(source) if source in values else metadata.get(source)
            point = {'x': timestamp, 'y': chart_value(value)}
            if include_timestamp:
                point['timestamp'] = reading.createDate.timestamp()
            result[definition['id']].append(point)
    return result


def render_saved_charts(image, config, readings, camera_data=None, label_bounds=()):
    if not config.get('CHARTS', {}).get('SAVED_IMAGE_IDS'):
        return image

    import logging
    import textwrap
    import numpy
    from datetime import datetime, timedelta
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.ticker import LinearLocator

    settings = chart_configuration(config)
    definitions = [definition for definition in chart_definitions(config, camera_data, is_local=True)
                   if definition['id'] in settings['SAVED_IMAGE_IDS']]
    readings = list(readings)
    data = build_chart_data(readings, definitions, config.get('TEMP_DISPLAY'))
    history = settings['SAVED_IMAGE_HISTORY_SECONDS']
    end = readings[-1].createDate if readings else datetime.now()
    start = end - timedelta(seconds=history)
    positions = [(reading.createDate - start).total_seconds() for reading in readings]
    if image.ndim == 2:
        image = numpy.repeat(image[:, :, None], 3, axis=2)
    image_height, image_width = image.shape[:2]
    single_chart = len(definitions) == 1
    width = min(int(settings['OVERLAY_WIDTH'] * 2.25), image_width - 32)
    height = 336
    remaining = iter(definitions)
    definition = next(remaining, None)
    columns = 2 if not single_chart and width * 2 <= image_width - 32 else 1
    labels = sorted((bounds for bounds in label_bounds
                     if bounds[0] < 16 + columns * width and bounds[2] > 16), key=lambda bounds: bounds[1])
    top = max(16, settings['OVERLAY_TOP'])
    for bounds in labels:
        if bounds[1] < max(top, image_height // 2):
            top = max(top, bounds[3] + 8)
    bottom = min([image_height - 16] + [bounds[1] - 8 for bounds in labels if bounds[1] >= top])
    if width >= 160:
        for row in range(2 if columns == 2 else 4):
            if top + height > bottom:
                break
            for left in range(16, 16 + columns * width, width):
                if definition is None:
                    break
                figure = Figure(figsize=(width / 100, height / 100), dpi=100,
                                facecolor=(12 / 255, 18 / 255, 20 / 255, settings['OVERLAY_OPACITY'] / 100))
                canvas = FigureCanvasAgg(figure)
                try:
                    points = data[definition['id']]
                    values = [point['y'] if point['y'] is not None else numpy.nan for point in points]
                    latest = points[-1]['y'] if points else None
                    value_text = figure.text(.96, .95, format(latest, '.4g') if latest is not None else '---',
                                             color='#f4f7f6', fontsize=16, ha='right', va='top')
                    title_text = figure.text(.04, .95, '', color='#f4f7f6', fontsize=14,
                                             fontweight='bold', va='top', parse_math=False, linespacing=1.1)
                    renderer = canvas.get_renderer()
                    title_right = value_text.get_window_extent(renderer).x0 - 12
                    for caption_width in range(max(1, int(width / 8)), 0, -1):
                        lines = textwrap.wrap(definition['label'], width=caption_width)
                        caption = '\n'.join(lines[:2])
                        if len(lines) > 2:
                            caption = lines[0] + '\n' + textwrap.shorten(' '.join(lines[1:]),
                                                                        width=max(3, caption_width), placeholder='...')
                        title_text.set_text(caption)
                        if title_text.get_window_extent(renderer).x1 <= title_right:
                            break
                    plot_left = max(.17, 66 / width)
                    axes = figure.add_axes((plot_left, .17, .96 - plot_left, .55), facecolor='none')
                    if definition['id'] == 'detection':
                        interval = min((second - first for first, second in zip(positions, positions[1:]) if second > first), default=1)
                        axes.bar(positions, values, color='#38bdf8', width=interval * .8)
                    else:
                        axes.plot(positions, values, color='#38bdf8', linewidth=1.8,
                                  marker='o', markersize=2.7)
                    axes.yaxis.set_major_locator(LinearLocator(numticks=5))
                    axes.ticklabel_format(axis='y', style='sci', scilimits=(-3, 4), useOffset=False)
                    axes.yaxis.get_offset_text().set_fontsize(11)
                    axes.yaxis.get_offset_text().set_color('#b9c4c4')
                    axes.yaxis.get_offset_text().set_horizontalalignment('right')
                    axes.yaxis.get_offset_text().set_x(1)
                    lower, upper = axes.get_ylim()
                    if definition['id'] == 'detection':
                        lower = 0
                        upper = max(upper, 1.05)
                    if definition.get('nonnegative'):
                        lower = max(0, lower)
                        if upper <= lower:
                            upper = lower + max(abs(lower) * .05, .05)
                    bounds = settings['AXIS_LIMITS'].get(definition['id'], {})
                    if bounds.get('min') is not None:
                        lower = bounds['min']
                        if bounds.get('max') is None and upper <= lower:
                            upper = lower + max(abs(lower) * .05, 1)
                    if bounds.get('max') is not None:
                        upper = bounds['max']
                        if bounds.get('min') is None and lower >= upper:
                            lower = upper - max(abs(upper) * .05, 1)
                    axes.set_ylim(lower, upper)
                    axes.tick_params(colors='#b9c4c4', labelsize=11, length=3, width=.6, pad=3)
                    axis_label_width = max(text.get_window_extent(renderer).width for text in axes.get_yticklabels())
                    plot_left = max(plot_left, (axis_label_width + 14) / width)
                    axes.set_xlim(0, history)
                    tick_count = max(2, int(width * (.96 - plot_left) // 72))
                    ticks = numpy.linspace(0, history, tick_count).tolist()
                    axes.set_xticks(ticks)
                    axes.set_xticklabels([(start + timedelta(seconds=offset)).strftime('%H:%M') for offset in ticks], rotation=0, ha='center')
                    if len(ticks) > 1:
                        axes.get_xticklabels()[0].set_horizontalalignment('left')
                        axes.get_xticklabels()[-1].set_horizontalalignment('right')
                    label_depth = max((text.get_window_extent(renderer).height for text in axes.get_xticklabels()),
                                      default=0)
                    plot_bottom = max(.17, (label_depth + 14) / height)
                    header_bottom = min(title_text.get_window_extent(renderer).y0,
                                        value_text.get_window_extent(renderer).y0)
                    plot_top = (header_bottom - 26) / height
                    axes.set_position((plot_left, plot_bottom, .96 - plot_left, plot_top - plot_bottom))
                    axes.set_axisbelow(True)
                    axes.grid(axis='y', color='#cbd5d3', alpha=.17, linewidth=.5)
                    for name, spine in axes.spines.items():
                        spine.set_visible(name in ('left', 'bottom'))
                        spine.set_color('#536564')
                        spine.set_linewidth(.4)
                    if not any(point['y'] is not None for point in points):
                        axes.text(.5, .5, 'No data', transform=axes.transAxes, ha='center', va='center',
                                  fontsize=12, color='#b9c4c4')
                    canvas.draw()
                    rgba = numpy.asarray(canvas.buffer_rgba())
                    alpha = rgba[:, :, 3:4].astype(numpy.float32) / 255
                    region = image[top:top + height, left:left + width]
                    region[:] = numpy.rint(rgba[:, :, :3][:, :, ::-1] * alpha + region * (1 - alpha)).astype(numpy.uint8)
                finally:
                    figure.clear()
                definition = next(remaining, None)
            top += height
            if definition is None:
                break
    if definition is not None:
        logging.getLogger('indi_allsky').warning('Not all saved-image charts fit; reduce chart width or top offset')
    return image