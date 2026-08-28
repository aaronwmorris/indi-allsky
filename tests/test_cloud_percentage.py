from indi_allsky import sensors_mapping


def _values(mapping):
    return lambda idx: mapping.get(idx, 0.0)


def test_mlx90614_uses_own_ambient_reading():
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'blinka_temp_sensor_mlx90614_i2c',
            'A_USER_VAR_SLOT': 'sensor_user_10',
            'CLOUD_SKY_TEMP_CLEAR': -30.0,
            'CLOUD_SKY_TEMP_CLOUDY': 0.0,
            'CLOUD_CALIBRATION_COEFFICIENT': 1.0,
        },
    }
    # slot 10 = Temperature (ambient), slot 11 = Sky Temperature
    get_value = _values({10: 10.0, 11: -20.0})

    percentage = sensors_mapping.calculate_cloud_percentage(config, get_value)

    # delta = -20 - 10 = -30 -> exactly the clear-sky boundary -> 0%
    assert percentage == 0.0


def test_mlx90640_falls_back_to_camera_temp_ambient():
    config = {
        'TEMP_SENSOR': {
            'B_CLASSNAME': 'blinka_temp_sensor_mlx90640_i2c',
            'B_USER_VAR_SLOT': 'sensor_user_20',
            'CLOUD_SKY_TEMP_CLEAR': -30.0,
            'CLOUD_SKY_TEMP_CLOUDY': 0.0,
            'CLOUD_CALIBRATION_COEFFICIENT': 1.0,
        },
    }
    # slot 0 = camera temp (ambient fallback), slot 20 = Sky Temperature (only offset for mlx90640)
    get_value = _values({0: 5.0, 20: 5.0})

    percentage = sensors_mapping.calculate_cloud_percentage(config, get_value)

    # delta = 5 - 5 = 0 -> at/above cloudy boundary -> 100%
    assert percentage == 100.0


def test_ambient_sensor_ref_overrides_own_ambient():
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'blinka_temp_sensor_mlx90615_i2c',
            'A_USER_VAR_SLOT': 'sensor_user_10',
            'CLOUD_AMBIENT_SENSOR_REF': 'sensor_user_0',
            'CLOUD_SKY_TEMP_CLEAR': -30.0,
            'CLOUD_SKY_TEMP_CLOUDY': 0.0,
            'CLOUD_CALIBRATION_COEFFICIENT': 1.0,
        },
    }
    # slot 10 = own Temperature/ambient (must be ignored), slot 0 = referenced ambient, slot 11 = Sky Temperature
    get_value = _values({10: 999.0, 0: 0.0, 11: -15.0})

    percentage = sensors_mapping.calculate_cloud_percentage(config, get_value)

    # delta = -15 - 0 = -15 -> halfway between -30 and 0 -> 50%
    assert percentage == 50.0


def test_calibration_coefficient_scales_delta():
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'blinka_temp_sensor_mlx90614_i2c',
            'A_USER_VAR_SLOT': 'sensor_user_10',
            'CLOUD_SKY_TEMP_CLEAR': -30.0,
            'CLOUD_SKY_TEMP_CLOUDY': 0.0,
            'CLOUD_CALIBRATION_COEFFICIENT': 2.0,
        },
    }
    # raw delta = -15 - 0 = -15, scaled by coefficient 2.0 -> -30 -> exactly clear boundary -> 0%
    get_value = _values({10: 0.0, 11: -15.0})

    percentage = sensors_mapping.calculate_cloud_percentage(config, get_value)

    assert percentage == 0.0


def test_no_configured_cloud_sensor_returns_none():
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'blinka_rain_sensor_fc37',
        },
    }

    assert sensors_mapping.calculate_cloud_percentage(config, _values({})) is None
