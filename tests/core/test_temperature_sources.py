import math

import pytest

from indi_allsky.temperature import NO_CAMERA_TEMPERATURE
from indi_allsky.temperature import configured_temperature_sources
from indi_allsky.temperature import resolve_temperature
from indi_allsky.temperature import temperature_source_choices
from indi_allsky.temperature import temperature_source_signature


def temperature_config():
    return {
        'TEMP_DISPLAY': 'c',
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'blinka_temp_sensor_bme280_i2c',
            'A_LABEL': 'Enclosure',
            'A_USER_VAR_SLOT': 'sensor_user_10',
            'B_CLASSNAME': 'blinka_temp_sensor_dht22',
            'B_LABEL': 'Outside',
            'B_USER_VAR_SLOT': 'sensor_user_20',
        },
        'CCD_TEMP_SCRIPT': '',
    }


def test_automatic_temperature_uses_camera_channel_only():
    reading = resolve_temperature(
        temperature_config(),
        camera_temperature=12.0,
        sensor_values={'sensor_user_10': 8.0, 'sensor_user_20': 6.0},
    )

    assert reading.value == 12.0
    assert reading.source.category == 'camera'


def test_general_temperature_sensors_are_ignored_for_sensorless_camera():
    reading = resolve_temperature(
        temperature_config(),
        camera_temperature=NO_CAMERA_TEMPERATURE,
        sensor_values={'sensor_user_10': 8.0, 'sensor_user_20': 6.0},
    )

    assert reading.value == NO_CAMERA_TEMPERATURE
    assert reading.source.key == 'camera_unavailable'
    assert reading.source.category == 'unavailable'


def test_missing_recent_camera_reading_stays_unknown():
    assert resolve_temperature(
        temperature_config(),
        camera_temperature=None,
        sensor_values={'sensor_user_10': 8.0},
    ) is None


def test_nonfinite_camera_reading_stays_unknown():
    assert resolve_temperature(
        temperature_config(),
        camera_temperature=math.nan,
    ) is None


def test_external_script_is_camera_temperature_fallback():
    config = temperature_config()
    config['CCD_TEMP_SCRIPT'] = '/usr/local/bin/camera-temperature'

    reading = resolve_temperature(
        config,
        camera_temperature=NO_CAMERA_TEMPERATURE,
        sensor_values={'external_script': -5.0},
    )

    assert reading.value == -5.0
    assert reading.source.key == 'external_script'


def test_source_choices_only_expose_automatic_camera_temperature():
    config = temperature_config()

    assert temperature_source_choices(config) == [{
        'key': 'auto',
        'label': 'Automatic camera temperature',
        'category': 'automatic',
        'slot': None,
    }]
    assert [source.key for source in configured_temperature_sources(config)] == ['camera']


def test_source_signature_tracks_camera_fallback_not_general_sensors():
    config = temperature_config()
    first_signature = temperature_source_signature(config)

    config['TEMP_SENSOR']['A_LABEL'] = 'Roof ambient'
    assert temperature_source_signature(config) == first_signature

    config['CCD_TEMP_SCRIPT'] = '/usr/local/bin/camera-temperature'
    assert temperature_source_signature(config) != first_signature


def test_explicit_camera_source_remains_available_internally():
    reading = resolve_temperature(
        temperature_config(),
        camera_temperature=7.5,
        source='camera',
    )

    assert reading.value == 7.5
    assert reading.source.key == 'camera'


def test_unknown_or_general_explicit_source_is_rejected():
    with pytest.raises(ValueError, match='no longer configured'):
        resolve_temperature(temperature_config(), source='sensor_user_10')
