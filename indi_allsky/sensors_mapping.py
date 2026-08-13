"""
Sensor Mapping Helper for indi-allsky.
Dynamically resolves configured sensor slots into named dictionary entries based on system configuration and sensor metadata.
"""
import logging
from typing import Dict, Any, List
from . import constants

logger = logging.getLogger('indi_allsky')


# Default fixed slot definitions for slots 0-9
DEFAULT_FIXED_SLOTS: List[Dict[str, Any]] = [
    {"key": "camera_temp", "slot": 0, "name": "Camera Temperature", "unit": "°C", "device_class": "temperature"},
    {"key": "dew_heater_level", "slot": 1, "name": "Dew Heater Output", "unit": "%", "device_class": "power_factor"},
    {"key": "dew_point", "slot": 2, "name": "Dew Point", "unit": "°C", "device_class": "temperature"},
    {"key": "frost_point", "slot": 3, "name": "Frost Point", "unit": "°C", "device_class": "temperature"},
    {"key": "fan_level", "slot": 4, "name": "Fan Speed Level", "unit": "%", "device_class": "power_factor"},
    {"key": "heat_index", "slot": 5, "name": "Heat Index", "unit": "°C", "device_class": "temperature"},
    {"key": "wind_direction", "slot": 6, "name": "Wind Direction", "unit": "°", "device_class": "wind_direction"},
    {"key": "device_sqm", "slot": 7, "name": "Device SQM Magnitude", "unit": "mag/arcsec²", "device_class": None},
    {"key": "camera_sqm", "slot": 8, "name": "Camera SQM Magnitude", "unit": "mag/arcsec²", "device_class": None},
    {"key": "camera_sqm_adu", "slot": 9, "name": "Camera SQM ADU", "unit": "ADU", "device_class": None},
]


# Units mapping for sensor types
TYPE_UNIT_MAP = {
    constants.SENSOR_TEMPERATURE: "°C",
    constants.SENSOR_RELATIVE_HUMIDITY: "%",
    constants.SENSOR_ATMOSPHERIC_PRESSURE: "hPa",
    constants.SENSOR_WIND_SPEED: "m/s",
    constants.SENSOR_PRECIPITATION: "mm",
    constants.SENSOR_LIGHT_LUX: "lx",
    constants.SENSOR_FAN_SPEED: "rpm",
    constants.SENSOR_PERCENTAGE: "%",
}

# Device class mapping for HA
TYPE_DEVICE_CLASS_MAP = {
    constants.SENSOR_TEMPERATURE: "temperature",
    constants.SENSOR_RELATIVE_HUMIDITY: "humidity",
    constants.SENSOR_ATMOSPHERIC_PRESSURE: "pressure",
    constants.SENSOR_WIND_SPEED: "wind_speed",
    constants.SENSOR_PRECIPITATION: "precipitation",
    constants.SENSOR_LIGHT_LUX: "illuminance",
}


def build_slot_label_map(config: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    """
    Builds a map of slot_index -> {name, unit, device_class, key} by inspecting TEMP_SENSOR configuration.
    """
    slot_map: Dict[int, Dict[str, Any]] = {}

    # Initialize fixed slots 0-9
    for fixed in DEFAULT_FIXED_SLOTS:
        slot_map[fixed["slot"]] = fixed

    from .devices import sensors as indi_allsky_sensors

    sensor_letters = ['A', 'B', 'C', 'D', 'E', 'F']
    temp_sensor_cfg = config.get('TEMP_SENSOR', {})

    for letter in sensor_letters:
        classname = temp_sensor_cfg.get(f'{letter}_CLASSNAME')
        if not classname:
            continue

        label = temp_sensor_cfg.get(f'{letter}_LABEL', f'Sensor {letter}')
        user_var_slot = temp_sensor_cfg.get(f'{letter}_USER_VAR_SLOT', f'sensor_user_{10 if letter=="A" else 20}')
        title_template = temp_sensor_cfg.get(f'{letter}_TITLE_TEMPLATE', '{label:s} ({probe:s})')
        pin_1_name = temp_sensor_cfg.get(f'{letter}_PIN_1', '')

        try:
            sensor_cls = getattr(indi_allsky_sensors, classname)
            base_index = constants.SENSOR_INDEX_MAP.get(str(user_var_slot), 10)
            labels = sensor_cls.get_labels(pin_1_name)
            count = sensor_cls.METADATA.get('count', 1)
            types = sensor_cls.METADATA.get('types', [constants.SENSOR_TEMPERATURE] * count)

            for x in range(count):
                slot_idx = base_index + x
                probe_label = labels[x] if x < len(labels) else f"Probe {x+1}"
                stype = types[x] if x < len(types) else None

                sensor_label_data = {
                    'name': sensor_cls.METADATA.get('name', classname),
                    'label': label,
                    'probe': probe_label,
                }
                display_name = title_template.format(**sensor_label_data) if '{' in title_template else f"{label} {probe_label}"
                sensor_key = f"sensor_{letter.lower()}_{probe_label.lower().replace(' ', '_')}"

                slot_map[slot_idx] = {
                    "key": sensor_key,
                    "slot": slot_idx,
                    "name": display_name,
                    "unit": TYPE_UNIT_MAP.get(stype, ""),
                    "device_class": TYPE_DEVICE_CLASS_MAP.get(stype),
                }
        except Exception as e:
            logger.error("Error building slot label for sensor %s (%s): %s", letter, classname, e)

    return slot_map


def format_named_sensors(sensor_temp: List[float], sensor_user: List[float], config: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Formats raw sensor arrays into a dictionary of named sensor objects.

    Returns:
        Dict of sensor_key -> { "name": ..., "value": ..., "unit": ..., "device_class": ..., "slot": ... }
    """
    config = config or {}
    slot_map = build_slot_label_map(config)
    named_sensors: Dict[str, Any] = {}

    for idx, val in enumerate(sensor_user):
        # Ignore unpopulated/zero slots unless explicitly configured
        if idx in slot_map:
            meta = slot_map[idx]
            # Include non-zero values or designated fixed slots
            if val != 0.0 or idx in (0, 1, 4):
                named_sensors[meta["key"]] = {
                    "name": meta["name"],
                    "value": round(val, 2) if isinstance(val, float) else val,
                    "unit": meta["unit"],
                    "device_class": meta["device_class"],
                    "slot": idx,
                }

    return named_sensors
