"""
Sensor Mapping Helper for indi-allsky.
Dynamically resolves configured sensor slots into named dictionary entries based on system configuration and sensor metadata.
"""
import logging
from typing import Dict, Any, List
from datetime import datetime
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


# labels used by the MLX90614/90615/90640 family to identify sky vs ambient readings
CLOUD_SKY_TEMP_LABEL = 'Sky Temperature'
CLOUD_AMBIENT_TEMP_LABEL = 'Temperature'


def _display_temperature_to_celsius(value: float, temp_display: str) -> float:
    if temp_display == 'f':
        return (value - 32.0) * 5.0 / 9.0

    if temp_display == 'k':
        return value - 273.15

    return value


def calculate_cloud_percentage(config: Dict[str, Any], get_sensor_value) -> Any:
    """
    Scans configured TEMP_SENSOR slots (A-F) for an MLX90614/90615/90640
    family sensor and derives a 0-100 cloud percentage from its sky
    temperature relative to an ambient reference.

    Physical basis: under a clear sky the 8-14 micron atmospheric window lets
    a zenith-pointed IR sensor see through to the cold effective sky
    temperature, so its reading falls well below the ambient air temperature
    (low atmospheric emissivity - Staley & Jurica, 1972, J. Appl. Meteorol.,
    11(2), 349-356, "Effective atmospheric emissivity under clear skies").
    Cloud closes that window; clouds radiate close to a blackbody near
    ambient temperature (emissivity approaching 1 - Mendoza et al., 2017,
    Atmos. Environ., 155, 174-188), so the sky reading converges toward
    ambient as cloud cover increases. That is why cloud percentage here is a
    linear scaling of the sky-minus-ambient delta between a clear-sky
    (large negative) and cloudy (near-zero/positive) threshold, rather than
    the raw sky temperature alone.

    Equation (all temperatures in Celsius, T_clear < T_cloudy)::

        delta   = (T_sky + offset - T_ambient) * coefficient
        percent = clamp(0, 100, (delta - T_clear) / (T_cloudy - T_clear) * 100)

    ``get_sensor_value`` is a callable accepting a sensor_user index and
    returning its current float value, so this works against either the
    live shared sensor array or persisted image metadata.

    Returns ``None`` when no matching sensor is configured.
    """
    from .devices import sensors as indi_allsky_sensors

    temp_sensor_cfg = config.get('TEMP_SENSOR', {})

    sky_temp = None
    ambient_temp = None

    for letter in ('A', 'B', 'C', 'D', 'E', 'F'):
        classname = temp_sensor_cfg.get('{0:s}_CLASSNAME'.format(letter))
        if classname not in constants.CLOUD_SENSOR_CLASSNAMES:
            continue

        user_var_slot = temp_sensor_cfg.get('{0:s}_USER_VAR_SLOT'.format(letter), 'sensor_user_10')
        base_index = constants.SENSOR_INDEX_MAP.get(str(user_var_slot), 10)

        try:
            sensor_cls = getattr(indi_allsky_sensors, classname)
            labels = sensor_cls.METADATA.get('labels', ())
            sky_offset = labels.index(CLOUD_SKY_TEMP_LABEL)
        except (AttributeError, ValueError):
            continue

        sky_temp = get_sensor_value(base_index + sky_offset)

        try:
            ambient_offset = labels.index(CLOUD_AMBIENT_TEMP_LABEL)
            ambient_temp = get_sensor_value(base_index + ambient_offset)
        except ValueError:
            ambient_temp = None

        break

    if sky_temp is None:
        # no configured sensor from the supported family
        return None

    ambient_ref = temp_sensor_cfg.get('CLOUD_AMBIENT_SENSOR_REF', '')
    if ambient_ref:
        ambient_index = constants.SENSOR_INDEX_MAP.get(str(ambient_ref))
        if ambient_index is not None:
            ambient_temp = get_sensor_value(ambient_index)

    if ambient_temp is None:
        # sensor has no ambient reading of its own (e.g. MLX90640) and no reference configured -
        # camera temperature is not a valid ambient-air proxy, so this is left unavailable
        return None

    # Cloud thresholds are configured in Celsius regardless of display units.
    sky_temp_c = _display_temperature_to_celsius(float(sky_temp), config.get('TEMP_DISPLAY', 'c'))
    ambient_temp_c = _display_temperature_to_celsius(float(ambient_temp), config.get('TEMP_DISPLAY', 'c'))

    # fixed offset corrects a sensor known to read a set amount high/low, before scaling
    offset = float(temp_sensor_cfg.get('CLOUD_CALIBRATION_OFFSET', 0.0))
    sky_temp_c += offset

    clear_temp = float(temp_sensor_cfg.get('CLOUD_SKY_TEMP_CLEAR', -10.0))
    cloudy_temp = float(temp_sensor_cfg.get('CLOUD_SKY_TEMP_CLOUDY', 15.0))
    span = cloudy_temp - clear_temp
    if span <= 0:
        logger.error('CLOUD_SKY_TEMP_CLOUDY must be greater than CLOUD_SKY_TEMP_CLEAR')
        return None

    coefficient = float(temp_sensor_cfg.get('CLOUD_CALIBRATION_COEFFICIENT', 1.0))
    corrected_delta = (sky_temp_c - ambient_temp_c) * coefficient

    percentage = ((corrected_delta - clear_temp) / span) * 100.0
    return max(0.0, min(100.0, percentage))


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
    """
    config = config or {}
    slot_map = build_slot_label_map(config)
    named_sensors: Dict[str, Any] = {}

    for idx, val in enumerate(sensor_user):
        if idx in slot_map:
            meta = slot_map[idx]
            if val != 0.0 or idx in (0, 1, 4):
                named_sensors[meta["key"]] = {
                    "name": meta["name"],
                    "value": round(val, 2) if isinstance(val, float) else val,
                    "unit": meta["unit"],
                    "device_class": meta["device_class"],
                    "slot": idx,
                }

    return named_sensors


def get_latest_sensors_payload(config: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Queries the latest sensor data from the database and returns a formatted payload.
    """
    from .flask.models import IndiAllSkyDbImageTable

    config = config or {}
    sensor_user = [0.0] * 60
    sensor_temp = [0.0] * 60
    last_update = None
    last_update_age_s = None

    try:
        latest_img = IndiAllSkyDbImageTable.query.order_by(IndiAllSkyDbImageTable.createDate.desc()).first()

        if latest_img:
            last_update = str(latest_img.createDate)
            last_update_age_s = int((datetime.now() - latest_img.createDate).total_seconds())

            data = dict(latest_img.data) if hasattr(latest_img, 'data') and latest_img.data else {}

            sensor_user = [float(data.get(f'sensor_user_{i}', 0.0)) for i in range(60)]
            sensor_temp = [float(data.get(f'sensor_temp_{i}', 0.0)) for i in range(60)]
    except Exception as e:
        logger.error("Error querying latest sensor image data: %s", e)

    named_sensors = format_named_sensors(sensor_temp, sensor_user, config)

    return {
        'last_update': last_update,
        'last_update_age_s': last_update_age_s,
        'sensor_user': sensor_user,
        'sensor_temp': sensor_temp,
        'sensors': named_sensors,
    }
