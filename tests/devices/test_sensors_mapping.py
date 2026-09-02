import pytest
from indi_allsky.sensors_mapping import (
    DEFAULT_FIXED_SLOTS,
    build_slot_label_map,
    format_named_sensors,
    get_latest_sensors_payload,
)


def test_build_slot_label_map():
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'sensor_data_generator',
            'A_LABEL': 'Custom Test Sensor',
            'A_USER_VAR_SLOT': 'sensor_user_10',
            'A_TITLE_TEMPLATE': '{label:s} ({probe:s})',
        }
    }
    slot_map = build_slot_label_map(config)
    assert 0 in slot_map
    assert slot_map[0]['name'] == 'Camera Temperature'
    assert 10 in slot_map
    assert 'Custom Test Sensor' in slot_map[10]['name']


def test_format_named_sensors():
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'sensor_data_generator',
            'A_LABEL': 'Custom Test Sensor',
            'A_USER_VAR_SLOT': 'sensor_user_10',
        }
    }
    sensor_temp = [0.0] * 60
    sensor_user = [0.0] * 60
    sensor_user[0] = 25.5   # Camera temp
    sensor_user[10] = 42.0  # Custom sensor probe

    named = format_named_sensors(sensor_temp, sensor_user, config)
    assert 'camera_temp' in named
    assert named['camera_temp']['value'] == 25.5
    assert 10 in [meta['slot'] for meta in named.values()]


def test_get_latest_sensors_payload(flask_app, db):
    payload = get_latest_sensors_payload({})
    assert isinstance(payload, dict)
    assert 'sensors' in payload
    assert 'sensor_user' in payload
    assert 'sensor_temp' in payload
