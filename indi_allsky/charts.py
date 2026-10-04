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
    metadata = camera_data or {}
    definitions = [dict(definition) for definition in BUILTIN_CHARTS]
    for definition in custom_charts(config, None if is_local else metadata):
        definition = dict(definition)
        definition['label'] = definition['label'] or metadata.get(definition['source'], definition['source'])
        definitions.append(definition)
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
    ):
        selected = settings.get(key, default)
        if selected is None and key == 'VISIBLE_IDS':
            selected = default
        if not isinstance(selected, list) or any(not isinstance(identifier, str) or identifier not in available for identifier in selected):
            raise ValueError('Invalid chart selection')
        if len(selected) != len(set(selected)):
            raise ValueError('Select each chart only once')
        result[key] = selected
    for key, default, minimum, maximum in (
        ('OVERLAY_HISTORY_SECONDS', 900, 60, 86400),
        ('OVERLAY_TOP', 120, 0, 600),
        ('OVERLAY_WIDTH', 260, 180, 400),
        ('OVERLAY_OPACITY', 80, 20, 100),
    ):
        value = settings.get(key, default)
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
        for key in ('VISIBLE_IDS', 'OVERLAY_IDS'):
            if settings.get(key) is not None:
                settings[key] = list(dict.fromkeys(identifiers[identifier] for identifier in settings[key] if identifier in identifiers))
        settings['AXIS_LIMITS'] = {
            identifiers[identifier]: bounds
            for identifier, bounds in settings.get('AXIS_LIMITS', {}).items()
            if identifier in identifiers
        }
    return validate_chart_configuration(settings)


def build_chart_data(readings, definitions, temperature_display='c', selected_ids=None):
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
            result[definition['id']].append({'x': timestamp, 'y': chart_value(value)})
    return result