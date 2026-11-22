import pytest
from wtforms.validators import ValidationError
from collections import namedtuple
from unittest.mock import MagicMock

from indi_allsky.flask.forms import (
    CIRCULAR_DISPLAY__IMAGE_CIRCLE_DIAMETER_validator,
    DEW_HEATER__LEVEL_validator,
    DEW_HEATER__THOLD_DIFF_validator,
    DEW_HEATER__HOLD_SECONDS_validator,
    PWM_FREQUENCY_validator,
    FAN__LEVEL_validator,
    FAN__THOLD_DIFF_validator,
    FAN__HOLD_SECONDS_validator,
    TEMP_SENSOR__MACADDRESS_validator,
    TEMP_SENSOR__AS3935_NOISE_LEVEL_validator,
    TEMP_SENSOR__AS3935_SPIKE_REJECTION_validator,
    HEALTHCHECK__DISK_USAGE_validator,
    HEALTHCHECK__SWAP_USAGE_validator,
    ADSB__ALT_DEG_MIN_validator,
    ADSB__LABEL_LIMIT_validator,
    SATELLITE_TRACK__ALT_DEG_MIN_validator,
    SATELLITE_TRACK__LABEL_LIMIT_validator,
    INDI_CONFIG_DEFAULTS_validator,
    INDI_CONFIG_DAY_validator,
    VIRTUALSKY__IMAGE_CIRCLE_DIAMETER_validator,
)

Field = namedtuple('Field', ['data'])


def test_group9_circular_and_heater_and_fan_ranges():
    form = MagicMock()

    # VIRTUALSKY__IMAGE_CIRCLE_DIAMETER_validator
    with pytest.raises(ValidationError, match='0 or greater'):
        VIRTUALSKY__IMAGE_CIRCLE_DIAMETER_validator(form, Field(-1))

    # CIRCULAR_DISPLAY__IMAGE_CIRCLE_DIAMETER_validator
    with pytest.raises(ValidationError, match='Value must be 100 or greater'):
        CIRCULAR_DISPLAY__IMAGE_CIRCLE_DIAMETER_validator(form, Field(50))

    # DEW_HEATER__LEVEL_validator
    with pytest.raises(ValidationError, match='Level must be 0 or greater'):
        DEW_HEATER__LEVEL_validator(form, Field(-1))
    with pytest.raises(ValidationError, match='Level must be 100 or less'):
        DEW_HEATER__LEVEL_validator(form, Field(101))

    # DEW_HEATER__THOLD_DIFF_validator
    with pytest.raises(ValidationError, match='Please enter a valid number'):
        DEW_HEATER__THOLD_DIFF_validator(form, Field('invalid_int'))

    # DEW_HEATER__HOLD_SECONDS_validator
    with pytest.raises(ValidationError, match='Must be 0 or greater'):
        DEW_HEATER__HOLD_SECONDS_validator(form, Field(-1))
    with pytest.raises(ValidationError, match='Must be 600 or less'):
        DEW_HEATER__HOLD_SECONDS_validator(form, Field(601))

    # PWM_FREQUENCY_validator
    with pytest.raises(ValidationError, match='Must be 1 or greater'):
        PWM_FREQUENCY_validator(form, Field(0))
    with pytest.raises(ValidationError, match='Must be 10000 or less'):
        PWM_FREQUENCY_validator(form, Field(10001))

    # FAN__LEVEL_validator
    with pytest.raises(ValidationError, match='Level must be 0 or greater'):
        FAN__LEVEL_validator(form, Field(-1))
    with pytest.raises(ValidationError, match='Level must be 100 or less'):
        FAN__LEVEL_validator(form, Field(101))

    # FAN__THOLD_DIFF_validator
    with pytest.raises(ValidationError, match='Please enter a valid number'):
        FAN__THOLD_DIFF_validator(form, Field('bad_value'))

    # FAN__HOLD_SECONDS_validator
    with pytest.raises(ValidationError, match='Must be 0 or greater'):
        FAN__HOLD_SECONDS_validator(form, Field(-1))
    with pytest.raises(ValidationError, match='Must be 600 or less'):
        FAN__HOLD_SECONDS_validator(form, Field(601))


def test_group9_sensors_and_healthcheck_and_tracking():
    form = MagicMock()

    # TEMP_SENSOR__MACADDRESS_validator
    with pytest.raises(ValidationError, match='Invalid MAC address'):
        TEMP_SENSOR__MACADDRESS_validator(form, Field('00:11:22:33:44:GG'))

    # TEMP_SENSOR__AS3935_NOISE_LEVEL_validator
    with pytest.raises(ValidationError, match='Noise Level must be 1 to 7'):
        TEMP_SENSOR__AS3935_NOISE_LEVEL_validator(form, Field(0))
    with pytest.raises(ValidationError, match='Noise Level must be 1 to 7'):
        TEMP_SENSOR__AS3935_NOISE_LEVEL_validator(form, Field(8))

    # TEMP_SENSOR__AS3935_SPIKE_REJECTION_validator
    with pytest.raises(ValidationError, match='Spike Rejection must be 1 to 11'):
        TEMP_SENSOR__AS3935_SPIKE_REJECTION_validator(form, Field(0))
    with pytest.raises(ValidationError, match='Spike Rejection must be 1 to 11'):
        TEMP_SENSOR__AS3935_SPIKE_REJECTION_validator(form, Field(12))

    # HEALTHCHECK__DISK_USAGE_validator
    with pytest.raises(ValidationError, match='Percentage must be 0 or greater'):
        HEALTHCHECK__DISK_USAGE_validator(form, Field(-1))
    with pytest.raises(ValidationError, match='Percentage must be 101 or less'):
        HEALTHCHECK__DISK_USAGE_validator(form, Field(102))

    # HEALTHCHECK__SWAP_USAGE_validator
    with pytest.raises(ValidationError, match='Percentage must be 0 or greater'):
        HEALTHCHECK__SWAP_USAGE_validator(form, Field(-1))
    with pytest.raises(ValidationError, match='Percentage must be 101 or less'):
        HEALTHCHECK__SWAP_USAGE_validator(form, Field(102))

    # ADSB__ALT_DEG_MIN_validator
    with pytest.raises(ValidationError, match='Minimum altitude must be greater than 5'):
        ADSB__ALT_DEG_MIN_validator(form, Field(4))
    with pytest.raises(ValidationError, match='Minimum altitude must be less than 90'):
        ADSB__ALT_DEG_MIN_validator(form, Field(91))

    # ADSB__LABEL_LIMIT_validator
    with pytest.raises(ValidationError, match='Limit must be greater than 0'):
        ADSB__LABEL_LIMIT_validator(form, Field(0))
    with pytest.raises(ValidationError, match='Limit must be 20 or less'):
        ADSB__LABEL_LIMIT_validator(form, Field(21))

    # SATELLITE_TRACK__ALT_DEG_MIN_validator
    with pytest.raises(ValidationError, match='Minimum altitude must be 0 or more'):
        SATELLITE_TRACK__ALT_DEG_MIN_validator(form, Field(-1))
    with pytest.raises(ValidationError, match='Minimum altitude must be less than 90'):
        SATELLITE_TRACK__ALT_DEG_MIN_validator(form, Field(91))

    # SATELLITE_TRACK__LABEL_LIMIT_validator
    with pytest.raises(ValidationError, match='Limit must be greater than 0'):
        SATELLITE_TRACK__LABEL_LIMIT_validator(form, Field(0))
    with pytest.raises(ValidationError, match='Limit must be 20 or less'):
        SATELLITE_TRACK__LABEL_LIMIT_validator(form, Field(21))


def test_group9_indi_config_defaults_and_day():
    form = MagicMock()

    # Invalid JSON string
    with pytest.raises(ValidationError):
        INDI_CONFIG_DEFAULTS_validator(form, Field('not valid json {['))

    # Non-allowed top-level key
    with pytest.raises(ValidationError, match='Only PROPERTIES, TEXT, and SWITCHES'):
        INDI_CONFIG_DEFAULTS_validator(form, Field('{"INVALID_KEY": {}}'))

    # PROPERTIES not dict
    with pytest.raises(ValidationError, match='Number property.*must be a dict'):
        INDI_CONFIG_DEFAULTS_validator(form, Field('{"PROPERTIES": {"foo": "not_dict"}}'))

    # TEXT not dict
    with pytest.raises(ValidationError, match='Text property.*must be a dict'):
        INDI_CONFIG_DEFAULTS_validator(form, Field('{"TEXT": {"bar": 123}}'))

    # SWITCHES not dict
    with pytest.raises(ValidationError, match='Switch.*must be a dict'):
        INDI_CONFIG_DEFAULTS_validator(form, Field('{"SWITCHES": {"baz": 123}}'))

    # Switch key not in ('on', 'off')
    with pytest.raises(ValidationError, match='Invalid switch configuration'):
        INDI_CONFIG_DEFAULTS_validator(form, Field('{"SWITCHES": {"baz": {"bad_switch": []}}}'))

    # Switch value not list
    with pytest.raises(ValidationError, match='must be a list'):
        INDI_CONFIG_DEFAULTS_validator(form, Field('{"SWITCHES": {"baz": {"on": "not_a_list"}}}'))

    # Valid config with comments (#) tested via INDI_CONFIG_DAY_validator
    valid_cfg = {
        "#comment1": "hello",
        "PROPERTIES": {
            "prop1": {
                "#inner": "val",
                "val": 1
            }
        },
        "TEXT": {
            "text1": {
                "#inner": "val",
                "val": "abc"
            }
        },
        "SWITCHES": {
            "sw1": {
                "#inner": "val",
                "on": ["val1"],
                "off": ["val2"]
            }
        }
    }
    INDI_CONFIG_DAY_validator(form, Field(valid_cfg))
