"""
Sensor Mapping Helper for indi-allsky.
Dynamically resolves configured sensor slots into named dictionary entries based on system configuration and sensor metadata.
"""
import logging
import math
import time
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


def get_cloudiness_ground_sensor_offsets(classname):
    from .devices import sensors as indi_allsky_sensors

    if not isinstance(classname, str) or not classname.startswith(('blinka_', 'cpads_', 'kernel_')):
        return ()

    try:
        metadata = getattr(indi_allsky_sensors, classname).METADATA
    except AttributeError:
        return ()

    return tuple(
        offset for offset, (sensor_type, label) in enumerate(zip(
            metadata.get('types', ()), metadata.get('labels', ())))
        if sensor_type == constants.SENSOR_TEMPERATURE and label == constants.CLOUD_AMBIENT_TEMP_LABEL
    )


def get_fresh_sensor_value(values, read_times, index, now=None, max_age=60.0):
    if read_times is None:
        return None

    if now is None:
        now = time.monotonic()

    try:
        read_time = read_times[index]
        value = values[index]
        if not math.isfinite(read_time) or read_time <= 0.0 or not 0.0 <= now - read_time <= max_age:
            return None
        if not math.isfinite(value):
            return None
    except (IndexError, TypeError, OverflowError):
        return None

    return value


def _display_temperature_to_celsius(value: float, temp_display: str) -> float:
    if temp_display == 'f':
        return (value - 32.0) * 5.0 / 9.0

    if temp_display == 'k':
        return value - 273.15

    return value


def _normalize_cloudiness_calibration(clear_sky_temp, cloudy_sky_temp,
                                     clear_ground_temp, cloudy_ground_temp, temp_unit='c',
                                     coefficient=1.0, offset=0.0):
    """Return the validated clear delta and span in Celsius, or None."""
    try:
        coefficient = float(coefficient)
        offset = float(offset)
        references = tuple(_display_temperature_to_celsius(float(value), temp_unit)
                           for value in (clear_sky_temp, cloudy_sky_temp,
                                         clear_ground_temp, cloudy_ground_temp))
    except (TypeError, ValueError, OverflowError):
        return None

    if (not all(math.isfinite(value) for value in references)
            or not math.isfinite(coefficient) or not 0.0 < coefficient <= 10.0
            or not math.isfinite(offset) or abs(offset) > 100.0):
        return None

    clear_sky_c, cloudy_sky_c, clear_ground_c, cloudy_ground_c = references
    clear_sky_c = clear_sky_c * coefficient + offset
    cloudy_sky_c = cloudy_sky_c * coefficient + offset
    clear_delta = clear_ground_c - clear_sky_c
    span = clear_delta - (cloudy_ground_c - cloudy_sky_c)
    if not math.isfinite(span) or span <= 2.0 or math.isclose(span, 2.0, rel_tol=0.0, abs_tol=1e-12):
        return None

    return clear_delta, span


def validate_cloudiness_calibration(clear_sky_temp, cloudy_sky_temp,
                                   clear_ground_temp, cloudy_ground_temp, temp_unit='c',
                                   coefficient=1.0, offset=0.0):
    """Require a finite calibration separation greater than 2 C in any reference unit."""
    return _normalize_cloudiness_calibration(
        clear_sky_temp, cloudy_sky_temp, clear_ground_temp, cloudy_ground_temp,
        temp_unit=temp_unit, coefficient=coefficient, offset=offset) is not None


def calculate_cloudiness_index(config: Dict[str, Any], get_sensor_value) -> Any:
    """
    Scans configured TEMP_SENSOR slots (A-F) for an MLX90614/90615/90640
    family sensor and derives a 0-100 local cloudiness index from the
    difference between the ground and sky temperatures.

    Physical basis: under a clear sky the 8-14 micron atmospheric window lets
    a zenith-pointed IR sensor see through to the cold effective sky
    temperature, so its reading falls well below the ambient air temperature
    (low atmospheric emissivity - Staley & Jurica, 1972, J. Appl. Meteorol.,
    11(2), 349-356, "Effective atmospheric emissivity under clear skies").
    Cloud closes that window; clouds radiate close to a blackbody near
    ambient temperature (emissivity approaching 1 - Mendoza et al., 2017,
    Atmos. Environ., 155, 174-188), so the sky reading converges toward
    ambient as cloud cover increases. That is why the cloudiness index here is a
    linear scaling between local clear-sky and overcast ground-to-sky
    temperature-difference references. This is an empirical, installation-specific cloudiness index,
    not a measured sky fraction. A narrow-field IR thermometer cannot
    distinguish all cloud types or measure coverage outside its field of view.

    Equation (all temperatures in Celsius)::

        index = clamp(0, 100,
                      (D_clear - D_live) / (D_clear - D_cloudy) * 100)

        T_sky_corrected = T_sky_raw * coefficient + offset
        D = T_ground - T_sky_corrected

    The two references contain paired sky and ground readings from this
    installation under known clear and overcast conditions. When no ground
    sensor is selected, the paired ambient output of an MLX90614/90615 is used.
    Their unit is declared explicitly via CLOUDINESS_INDEX_TEMP_UNIT rather
    than assumed to match TEMP_DISPLAY. Sky readings in both references and
    live data are corrected in Celsius; ambient readings are unchanged.
    The offset is in Celsius and cancels from the relative index when applied
    consistently to raw reference and live sky readings.

    ``get_sensor_value`` is a callable accepting a sensor_user index and
    returning its current float value, so this works against either the
    live shared sensor array or persisted image metadata.

    Returns ``None`` when no matching sensor is configured.
    """
    temp_sensor_cfg = config.get('TEMP_SENSOR', {})

    if not temp_sensor_cfg.get('CLOUDINESS_INDEX_ENABLE', False):
        return None

    from .devices import sensors as indi_allsky_sensors

    candidates = list()

    for letter in ('A', 'B', 'C', 'D', 'E', 'F'):
        classname = temp_sensor_cfg.get('{0:s}_CLASSNAME'.format(letter))
        if classname not in constants.CLOUD_SENSOR_CLASSNAMES:
            continue

        user_var_slot = temp_sensor_cfg.get('{0:s}_USER_VAR_SLOT'.format(letter))
        base_index = constants.SENSOR_INDEX_MAP.get(str(user_var_slot))
        if base_index is None:
            continue

        try:
            sensor_cls = getattr(indi_allsky_sensors, classname)
            labels = sensor_cls.METADATA.get('labels', ())
            sky_offset = labels.index(CLOUD_SKY_TEMP_LABEL)
        except (AttributeError, ValueError):
            continue

        try:
            ambient_offset = labels.index(constants.CLOUD_AMBIENT_TEMP_LABEL)
        except ValueError:
            ambient_offset = None

        candidates.append({
            'slot': str(user_var_slot),
            'sky_index': base_index + sky_offset,
            'ambient_index': base_index + ambient_offset if ambient_offset is not None else None,
        })

    selected_slot = temp_sensor_cfg.get('CLOUDINESS_INDEX_SENSOR', '')
    if selected_slot:
        candidates = [candidate for candidate in candidates if candidate['slot'] == selected_slot]

    if len(candidates) != 1:
        if candidates:
            logger.error('Select one MLX cloud sensor when multiple supported sensors are configured')
        return None

    candidate = candidates[0]
    sky_temp = get_sensor_value(candidate['sky_index'])

    if sky_temp is None:
        return None

    temp_display = config.get('TEMP_DISPLAY', 'c')
    ref_unit = temp_sensor_cfg.get('CLOUDINESS_INDEX_TEMP_UNIT', 'c')

    selected_ground_slot = temp_sensor_cfg.get('CLOUDINESS_INDEX_GROUND_SENSOR', '')
    use_ground_sensor = temp_sensor_cfg.get('CLOUDINESS_INDEX_USE_GROUND_SENSOR', False)
    if use_ground_sensor or candidate['ambient_index'] is None:
        ground_index = constants.SENSOR_INDEX_MAP.get(str(selected_ground_slot))
    else:
        ground_index = candidate['ambient_index']

    if ground_index is None:
        logger.error('Select a ground temperature sensor for this cloudiness index')
        return None

    if ground_index == candidate['sky_index']:
        logger.error('The cloudiness ambient reference cannot be the selected sky-temperature channel')
        return None

    if use_ground_sensor or candidate['ambient_index'] is None:
        ground_indices = set()
        for letter in ('A', 'B', 'C', 'D', 'E', 'F'):
            base_index = constants.SENSOR_INDEX_MAP.get(str(temp_sensor_cfg.get('{0:s}_USER_VAR_SLOT'.format(letter))))
            if base_index is None:
                continue
            for offset in get_cloudiness_ground_sensor_offsets(temp_sensor_cfg.get('{0:s}_CLASSNAME'.format(letter))):
                ground_indices.add(base_index + offset)

        if ground_index not in ground_indices:
            logger.error('Cloudiness requires a configured hardware ambient temperature sensor; '
                         'cached/API and sky-temperature readings are not supported')
            return None

    ground_temp = get_sensor_value(ground_index)
    if ground_temp is None:
        return None

    try:
        coefficient = float(temp_sensor_cfg.get('CLOUDINESS_INDEX_COEFFICIENT', 1.0))
        offset = float(temp_sensor_cfg.get('CLOUDINESS_INDEX_OFFSET', 0.0))
    except (TypeError, ValueError, OverflowError):
        logger.error('Sky temperature correction coefficient or offset is invalid')
        return None

    if (not math.isfinite(coefficient) or not 0.0 < coefficient <= 10.0
            or not math.isfinite(offset) or abs(offset) > 100.0):
        return None

    try:
        calibration = _normalize_cloudiness_calibration(
            temp_sensor_cfg['CLOUDINESS_INDEX_CLEAR_TEMP'],
            temp_sensor_cfg['CLOUDINESS_INDEX_CLOUDY_TEMP'],
            temp_sensor_cfg['CLOUDINESS_INDEX_CLEAR_GROUND_TEMP'],
            temp_sensor_cfg['CLOUDINESS_INDEX_CLOUDY_GROUND_TEMP'],
            temp_unit=ref_unit, coefficient=coefficient, offset=offset)
        sky_temp_c = _display_temperature_to_celsius(float(sky_temp), temp_display) * coefficient + offset
        ground_temp_c = _display_temperature_to_celsius(float(ground_temp), temp_display)
    except (KeyError, TypeError, ValueError, OverflowError):
        logger.error('Cloud calibration or live sensor readings are invalid')
        return None

    if not all(math.isfinite(value) for value in (sky_temp_c, ground_temp_c)):
        return None

    if calibration is None:
        logger.error('Calculated delta between cloudy and clear references is insufficient; '
                     'the ground-to-sky temperature difference under clear skies must be more than '
                     '2.0 C greater than under cloudy skies. '
                     'If these readings are correct, the sensor may be having problems.')
        return None

    clear_delta, span = calibration

    cloudiness_index = ((clear_delta - (ground_temp_c - sky_temp_c)) / span) * 100.0
    if not math.isfinite(cloudiness_index):
        return None
    return max(0.0, min(100.0, cloudiness_index))


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
