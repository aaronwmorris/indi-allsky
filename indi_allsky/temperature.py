import hashlib
import json
import math
from dataclasses import dataclass

from . import constants


TEMPERATURE_SOURCE_AUTO = 'auto'
TEMPERATURE_SOURCE_CAMERA = 'camera'
TEMPERATURE_SOURCE_SCRIPT = 'external_script'


@dataclass(frozen=True)
class TemperatureSource:
    key: str
    label: str
    category: str
    priority: int
    slot: str = None

    def to_dict(self):
        return {
            'key': self.key,
            'label': self.label,
            'category': self.category,
            'slot': self.slot,
        }


@dataclass(frozen=True)
class TemperatureReading:
    value: float
    source: TemperatureSource

    def to_dict(self):
        data = self.source.to_dict()
        data['value'] = self.value
        return data


def configured_temperature_sources(config):
    """Return the temperature inputs that indi-allsky can identify safely.

    The camera is always offered. Configured sensor devices contribute their
    first value explicitly declared as a temperature. Physical enclosure
    sensors take precedence over other physical sensors, followed by weather
    or remote API values and finally the legacy external-temperature script.
    """
    sources = [TemperatureSource(
        key=TEMPERATURE_SOURCE_CAMERA,
        label='Camera sensor',
        category='camera',
        priority=0,
    )]
    temp_sensor_config = config.get('TEMP_SENSOR', {}) or {}
    enclosure_slots = set()
    for controller_name in ('DEW_HEATER', 'FAN'):
        controller = config.get(controller_name, {}) or {}
        if controller.get('CLASSNAME') or controller.get('THOLD_ENABLE'):
            enclosure_slots.add(str(controller.get('TEMP_USER_VAR_SLOT') or ''))

    try:
        from .devices import sensors as sensor_devices
    except Exception:
        sensor_devices = None

    seen_slots = set()
    for sensor_letter in 'ABCDEF':
        classname = str(temp_sensor_config.get('{0:s}_CLASSNAME'.format(sensor_letter)) or '')
        if not classname:
            continue
        temperature_offset = (
            0
            if ('temp_sensor' in classname or classname.startswith('temp_api_'))
            else None
        )
        metadata = {}
        try:
            sensor_class = getattr(sensor_devices, classname)
            metadata = sensor_class.METADATA
            temperature_offset = tuple(metadata.get('types') or ()).index(
                constants.SENSOR_TEMPERATURE,
            )
        except (AttributeError, TypeError, ValueError):
            pass
        if temperature_offset is None:
            continue

        base_slot = str(
            temp_sensor_config.get('{0:s}_USER_VAR_SLOT'.format(sensor_letter))
            or 'sensor_user_10'
        )
        try:
            base_index = int(base_slot.rsplit('_', 1)[1])
        except (IndexError, ValueError):
            continue
        slot = 'sensor_user_{0:d}'.format(base_index + temperature_offset)
        if slot in seen_slots:
            continue
        seen_slots.add(slot)

        sensor_label = str(
            temp_sensor_config.get('{0:s}_LABEL'.format(sensor_letter))
            or 'Sensor {0:s}'.format(sensor_letter)
        )
        probe_labels = tuple(metadata.get('labels') or ())
        probe_label = (
            str(probe_labels[temperature_offset])
            if temperature_offset < len(probe_labels)
            else 'Temperature'
        )
        label = '{0:s}: {1:s}'.format(sensor_label, probe_label)
        label_lower = label.lower()
        if classname.startswith('temp_api_') or classname == 'mqtt_broker_sensor':
            category = 'inferred'
            priority = 3
        elif (
                slot in enclosure_slots
                or any(word in label_lower for word in (
                    'camera', 'enclosure', 'housing', 'inside', 'internal',
                ))
        ):
            category = 'enclosure'
            priority = 1
        else:
            category = 'outside'
            priority = 2
        sources.append(TemperatureSource(
            key=slot,
            label=label,
            category=category,
            priority=priority,
            slot=slot,
        ))

    if config.get('CCD_TEMP_SCRIPT'):
        sources.append(TemperatureSource(
            key=TEMPERATURE_SOURCE_SCRIPT,
            label='External temperature script',
            category='external',
            priority=4,
        ))

    return tuple(sorted(sources, key=lambda source: (source.priority, source.label)))


def temperature_source_choices(config):
    choices = [{
        'key': TEMPERATURE_SOURCE_AUTO,
        'label': 'Automatic (camera, enclosure, outside, API)',
        'category': 'automatic',
        'slot': None,
    }]
    choices.extend(source.to_dict() for source in configured_temperature_sources(config))
    return choices


def temperature_source_signature(config):
    data = temperature_source_choices(config)
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()


def resolve_temperature(config, camera_temperature=None, sensor_values=None, source='auto'):
    sensor_values = sensor_values or {}
    sources = configured_temperature_sources(config)
    source_map = {candidate.key: candidate for candidate in sources}
    source_key = str(source or TEMPERATURE_SOURCE_AUTO)
    if source_key == TEMPERATURE_SOURCE_AUTO:
        candidates = sources
    else:
        try:
            candidates = (source_map[source_key],)
        except KeyError:
            raise ValueError('The selected temperature source is no longer configured')

    for candidate in candidates:
        if candidate.key == TEMPERATURE_SOURCE_CAMERA:
            value = _usable_temperature(camera_temperature)
        elif candidate.key == TEMPERATURE_SOURCE_SCRIPT:
            value = _usable_temperature(sensor_values.get(TEMPERATURE_SOURCE_SCRIPT))
        else:
            value = _display_temperature_to_celsius(
                sensor_values.get(candidate.slot),
                config.get('TEMP_DISPLAY'),
            )
            value = _usable_temperature(value)
        if value is not None:
            return TemperatureReading(
                value=float(round(value, 3)),
                source=candidate,
            )
    return None


def _display_temperature_to_celsius(value, display_unit):
    try:
        temperature = float(value)
    except (TypeError, ValueError):
        return None
    if str(display_unit).lower() == 'f':
        return (temperature - 32.0) * 5.0 / 9.0
    if str(display_unit).lower() == 'k':
        return temperature - 273.15
    return temperature


def _usable_temperature(value):
    try:
        temperature = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(temperature) or temperature < -100.0 or temperature > 100.0:
        return None
    return temperature
