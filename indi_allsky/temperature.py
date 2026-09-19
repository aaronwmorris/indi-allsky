import hashlib
import json
import math
from dataclasses import dataclass

TEMPERATURE_SOURCE_AUTO = 'auto'
TEMPERATURE_SOURCE_CAMERA = 'camera'
TEMPERATURE_SOURCE_SCRIPT = 'external_script'
TEMPERATURE_SOURCE_UNAVAILABLE = 'camera_unavailable'
NO_CAMERA_TEMPERATURE = -273.15


def database_temperature(value, preserve_zero=False):
    """Normalize stored temperatures while retaining the legacy zero rule."""
    if value is None or (not preserve_zero and not value):
        return None
    return float(value)


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
    """Return the camera-temperature inputs used by normal image processing."""
    sources = [TemperatureSource(
        key=TEMPERATURE_SOURCE_CAMERA,
        label='Camera sensor',
        category='camera',
        priority=0,
    )]
    # CCD_TEMP_SCRIPT already replaces an unavailable camera value during
    # normal capture, so it remains the one safe non-hardware fallback here.
    if config.get('CCD_TEMP_SCRIPT'):
        sources.append(TemperatureSource(
            key=TEMPERATURE_SOURCE_SCRIPT,
            label='External temperature script',
            category='external',
            priority=4,
        ))

    return tuple(sorted(sources, key=lambda source: (source.priority, source.label)))


def temperature_source_choices(config):
    return [{
        'key': TEMPERATURE_SOURCE_AUTO,
        'label': 'Automatic camera temperature',
        'category': 'automatic',
        'slot': None,
    }]


def temperature_source_signature(config):
    data = [source.to_dict() for source in configured_temperature_sources(config)]
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()


def resolve_temperature(config, camera_temperature=None, sensor_values=None, source='auto'):
    sensor_values = sensor_values or {}
    sources = configured_temperature_sources(config)
    source_map = {candidate.key: candidate for candidate in sources}
    source_key = str(source or TEMPERATURE_SOURCE_AUTO)
    if source_key == TEMPERATURE_SOURCE_AUTO:
        for candidate in sources:
            reading = _reading_for_source(
                candidate,
                camera_temperature,
                sensor_values,
            )
            if reading is not None:
                return reading
        # Keep the original CLI's canonical no-sensor value. Normal image
        # processing uses the same value, so its existing nearest-temperature
        # ordering continues to select the corresponding library layer.
        try:
            unsupported_temperature = float(camera_temperature)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(unsupported_temperature):
            return None
        return TemperatureReading(
            value=NO_CAMERA_TEMPERATURE,
            source=TemperatureSource(
                key=TEMPERATURE_SOURCE_UNAVAILABLE,
                label='No camera temperature sensor found',
                category='unavailable',
                priority=99,
            ),
        )
    else:
        try:
            candidate = source_map[source_key]
        except KeyError:
            raise ValueError('The selected temperature source is no longer configured')
        return _reading_for_source(
            candidate,
            camera_temperature,
            sensor_values,
        )


def _reading_for_source(source, camera_temperature, sensor_values):
    if source.key == TEMPERATURE_SOURCE_CAMERA:
        value = usable_temperature(camera_temperature)
    elif source.key == TEMPERATURE_SOURCE_SCRIPT:
        value = usable_temperature(sensor_values.get(TEMPERATURE_SOURCE_SCRIPT))
    else:
        return None
    if value is None:
        return None
    return TemperatureReading(
        value=float(round(value, 3)),
        source=source,
    )


def usable_temperature(value):
    try:
        temperature = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(temperature) or temperature < -100.0 or temperature > 100.0:
        return None
    return temperature


def master_capture_temperature(value, preserve_legacy_value=False):
    """Return a master-file temperature without breaking the original CLI.

    The legacy CLI and sensorless-camera matching use a finite unsupported-
    temperature sentinel (usually -273.15) in filenames and metadata. Retain
    that value only when its caller opts in explicitly.
    """
    temperature = usable_temperature(value)
    if temperature is not None:
        return temperature
    if not preserve_legacy_value:
        return None

    try:
        legacy_temperature = float(value)
    except (TypeError, ValueError):
        return None
    return legacy_temperature if math.isfinite(legacy_temperature) else None
