import math

import pytest

from indi_allsky.temperature import configured_temperature_sources
from indi_allsky.temperature import resolve_temperature
from indi_allsky.temperature import temperature_source_choices
from indi_allsky.temperature import temperature_source_signature


def temperature_config(display='c'):
    return {
        'TEMP_DISPLAY': display,
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'blinka_temp_sensor_bme280_i2c',
            'A_LABEL': 'Enclosure',
            'A_USER_VAR_SLOT': 'sensor_user_10',
            'B_CLASSNAME': 'blinka_temp_sensor_dht22',
            'B_LABEL': 'Outside',
            'B_USER_VAR_SLOT': 'sensor_user_20',
            'C_CLASSNAME': 'temp_api_openweathermap',
            'C_LABEL': 'Weather service',
            'C_USER_VAR_SLOT': 'sensor_user_30',
        },
        'DEW_HEATER': {
            'CLASSNAME': 'gpio_standard',
            'TEMP_USER_VAR_SLOT': 'sensor_user_10',
        },
        'FAN': {
            'CLASSNAME': 'gpio_standard',
            'TEMP_USER_VAR_SLOT': 'sensor_user_10',
        },
        'CCD_TEMP_SCRIPT': '',
    }


def test_automatic_temperature_priority():
    config = temperature_config()
    values = {
        'sensor_user_10': 8.0,
        'sensor_user_20': 6.0,
        'sensor_user_30': 4.0,
    }

    reading = resolve_temperature(config, 12.0, values)
    assert reading.value == 12.0
    assert reading.source.category == 'camera'

    reading = resolve_temperature(config, -273.15, values)
    assert reading.value == 8.0
    assert reading.source.category == 'enclosure'

    values['sensor_user_10'] = math.nan
    reading = resolve_temperature(config, -273.15, values)
    assert reading.value == 6.0
    assert reading.source.category == 'local'

    values['sensor_user_20'] = math.nan
    reading = resolve_temperature(config, -273.15, values)
    assert reading.value == 4.0
    assert reading.source.category == 'inferred'


def test_automatic_never_guesses_sensor_placement_from_labels():
    config = temperature_config()
    config['DEW_HEATER'] = {}
    config['FAN'] = {}
    config['TEMP_SENSOR']['A_LABEL'] = 'Case'
    config['TEMP_SENSOR']['B_LABEL'] = 'Box'
    values = {
        'sensor_user_10': 8.0,
        'sensor_user_20': 6.0,
        'sensor_user_30': 4.0,
    }

    sources = {
        source.key: source for source in configured_temperature_sources(config)
    }

    assert sources['sensor_user_10'].category == 'local'
    assert sources['sensor_user_20'].category == 'local'
    assert resolve_temperature(config, -273.15, values) is None
    explicit = resolve_temperature(
        config,
        -273.15,
        values,
        source='sensor_user_10',
    )
    assert explicit.value == 8.0
    assert explicit.source.label == 'Case: Temperature'


def test_automatic_uses_a_unique_local_sensor_regardless_of_its_name():
    config = temperature_config()
    config['DEW_HEATER'] = {}
    config['FAN'] = {}
    config['TEMP_SENSOR']['A_LABEL'] = 'Whatever the user calls it'
    config['TEMP_SENSOR']['B_CLASSNAME'] = ''

    reading = resolve_temperature(
        config,
        camera_temperature=-273.15,
        sensor_values={
            'sensor_user_10': 8.0,
            'sensor_user_30': 4.0,
        },
    )

    assert reading.value == 8.0
    assert reading.source.key == 'sensor_user_10'


def test_controller_link_is_an_explicit_enclosure_signal_with_arbitrary_label():
    config = temperature_config()
    config['TEMP_SENSOR']['A_LABEL'] = 'Box'
    values = {
        'sensor_user_10': 8.0,
        'sensor_user_20': 6.0,
        'sensor_user_30': 4.0,
    }

    reading = resolve_temperature(config, -273.15, values)

    assert reading.value == 8.0
    assert reading.source.category == 'enclosure'
    assert reading.source.label == 'Box: Temperature'


@pytest.mark.parametrize(
    ('display', 'stored', 'expected'),
    (
        ('c', 10.0, 10.0),
        ('f', 50.0, 10.0),
        ('k', 283.15, 10.0),
    ),
)
def test_sensor_values_are_normalised_to_celsius(display, stored, expected):
    config = temperature_config(display=display)
    reading = resolve_temperature(
        config,
        camera_temperature=-273.15,
        sensor_values={'sensor_user_10': stored},
        source='sensor_user_10',
    )
    assert reading.value == pytest.approx(expected)


def test_invalid_camera_sentinel_is_unavailable():
    config = temperature_config()
    reading = resolve_temperature(
        config,
        camera_temperature=-273.15,
        sensor_values={
            'sensor_user_10': math.nan,
            'sensor_user_20': math.nan,
            'sensor_user_30': math.nan,
        },
    )
    assert reading is None


def test_explicit_source_does_not_fall_back():
    config = temperature_config()
    reading = resolve_temperature(
        config,
        camera_temperature=12.0,
        sensor_values={'sensor_user_10': math.nan},
        source='sensor_user_10',
    )
    assert reading is None


def test_external_script_is_last_automatic_fallback():
    config = temperature_config()
    config['CCD_TEMP_SCRIPT'] = '/usr/local/bin/camera-temperature'
    reading = resolve_temperature(
        config,
        camera_temperature=-273.15,
        sensor_values={
            'sensor_user_10': math.nan,
            'sensor_user_20': math.nan,
            'sensor_user_30': math.nan,
            'external_script': -5.0,
        },
    )
    assert reading.value == -5.0
    assert reading.source.key == 'external_script'


def test_source_choices_and_signature_follow_configuration():
    config = temperature_config()
    choices = temperature_source_choices(config)
    assert choices[0]['label'] == 'Automatic (camera first; unambiguous fallback only)'
    assert [choice['key'] for choice in choices] == [
        'auto',
        'camera',
        'sensor_user_10',
        'sensor_user_20',
        'sensor_user_30',
    ]
    first_signature = temperature_source_signature(config)
    config['TEMP_SENSOR']['B_LABEL'] = 'Roof ambient'
    assert temperature_source_signature(config) != first_signature


def test_unknown_explicit_source_is_rejected():
    with pytest.raises(ValueError, match='no longer configured'):
        resolve_temperature(temperature_config(), source='sensor_user_59')


def test_non_temperature_sensor_is_not_offered():
    config = temperature_config()
    config['TEMP_SENSOR']['D_CLASSNAME'] = 'blinka_light_sensor_bh1750_i2c'
    config['TEMP_SENSOR']['D_USER_VAR_SLOT'] = 'sensor_user_40'
    assert 'sensor_user_40' not in {
        source.key for source in configured_temperature_sources(config)
    }
