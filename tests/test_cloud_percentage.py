from indi_allsky import sensors_mapping


def _values(mapping):
    return lambda idx: mapping.get(idx, 0.0)


def test_default_reference_readings_are_minus_10_and_18_5_celsius():
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'blinka_temp_sensor_mlx90614_i2c',
            'A_USER_VAR_SLOT': 'sensor_user_10',
        },
    }
    # Ambient = 0 C and sky = 4.25 C make the calculated delta 4.25 C,
    # halfway between the -10 C and 18.5 C default reference deltas.
    percentage = sensors_mapping.calculate_cloud_percentage(config, _values({10: 0.0, 11: 4.25}))

    assert percentage == 50.0


def test_real_world_calibration_reproduces_cloudy_reference():
    # Real MLX90614 sky reading (17.5 C) against a real SHT31D ground ambient
    # reading (27 C), captured on a day visually estimated at ~70% cloud
    # cover. Using that pair directly as the cloudy reference (exactly as a
    # user would type both raw numbers off their own overlay) must reproduce
    # 100% for that same live reading - no delta math exposed to the user.
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'blinka_temp_sensor_mlx90614_i2c',
            'A_USER_VAR_SLOT': 'sensor_user_10',
            'CLOUD_AMBIENT_SENSOR_REF': 'sensor_user_20',
            'CLOUD_REF_CLEAR_SKY_TEMP': -25.0,
            'CLOUD_REF_CLEAR_AMBIENT_TEMP': 10.0,
            'CLOUD_REF_CLOUDY_SKY_TEMP': 17.5,
            'CLOUD_REF_CLOUDY_AMBIENT_TEMP': 27.0,
        },
    }
    # slot 10/11 = MLX90614's own ambient/sky (unused, ref overrides ambient),
    # slot 20 = SHT31D ground ambient reference
    get_value = _values({10: 39.0, 11: 17.5, 20: 27.0})

    percentage = sensors_mapping.calculate_cloud_percentage(config, get_value)

    assert percentage == 100.0


def test_real_world_calibration_interpolates_intermediate_reading():
    # Same calibration pair as above, but a live reading roughly halfway
    # between the clear and cloudy reference deltas.
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'blinka_temp_sensor_mlx90614_i2c',
            'A_USER_VAR_SLOT': 'sensor_user_10',
            'CLOUD_AMBIENT_SENSOR_REF': 'sensor_user_20',
            'CLOUD_REF_CLEAR_SKY_TEMP': -25.0,
            'CLOUD_REF_CLEAR_AMBIENT_TEMP': 10.0,
            'CLOUD_REF_CLOUDY_SKY_TEMP': 17.5,
            'CLOUD_REF_CLOUDY_AMBIENT_TEMP': 27.0,
        },
    }
    # clear delta = -25 - 10 = -35, cloudy delta = 17.5 - 27 = -9.5, span = 25.5
    # midpoint delta = -35 + 12.75 = -22.25 -> sky=-2.25, ambient=20 -> delta=-22.25
    get_value = _values({10: 39.0, 11: -2.25, 20: 20.0})

    percentage = sensors_mapping.calculate_cloud_percentage(config, get_value)

    assert round(percentage) == 50


def test_mlx90614_uses_own_ambient_reading():
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'blinka_temp_sensor_mlx90614_i2c',
            'A_USER_VAR_SLOT': 'sensor_user_10',
            'CLOUD_REF_CLEAR_SKY_TEMP': -30.0,
            'CLOUD_REF_CLEAR_AMBIENT_TEMP': 0.0,
            'CLOUD_REF_CLOUDY_SKY_TEMP': 0.0,
            'CLOUD_REF_CLOUDY_AMBIENT_TEMP': 0.0,
            'CLOUD_CALIBRATION_COEFFICIENT': 1.0,
        },
    }
    # slot 10 = Temperature (ambient), slot 11 = Sky Temperature
    get_value = _values({10: 10.0, 11: -20.0})

    percentage = sensors_mapping.calculate_cloud_percentage(config, get_value)

    # delta = -20 - 10 = -30 -> exactly the clear-sky reference delta -> 0%
    assert percentage == 0.0


def test_mlx90640_without_ambient_reference_returns_none():
    config = {
        'TEMP_SENSOR': {
            'B_CLASSNAME': 'blinka_temp_sensor_mlx90640_i2c',
            'B_USER_VAR_SLOT': 'sensor_user_20',
            'CLOUD_REF_CLEAR_SKY_TEMP': -30.0,
            'CLOUD_REF_CLEAR_AMBIENT_TEMP': 0.0,
            'CLOUD_REF_CLOUDY_SKY_TEMP': 1.0,
            'CLOUD_REF_CLOUDY_AMBIENT_TEMP': 0.0,
            'CLOUD_CALIBRATION_COEFFICIENT': 1.0,
        },
    }
    # slot 0 = camera temp, present but must not be used as an ambient-air proxy;
    # slot 20 = Sky Temperature (only offset for mlx90640)
    get_value = _values({0: 5.0, 20: 5.0})

    percentage = sensors_mapping.calculate_cloud_percentage(config, get_value)

    assert percentage is None


def test_mlx90640_uses_configured_ambient_reference():
    config = {
        'TEMP_SENSOR': {
            'B_CLASSNAME': 'blinka_temp_sensor_mlx90640_i2c',
            'B_USER_VAR_SLOT': 'sensor_user_20',
            'CLOUD_AMBIENT_SENSOR_REF': 'sensor_user_11',
            'CLOUD_REF_CLEAR_SKY_TEMP': -30.0,
            'CLOUD_REF_CLEAR_AMBIENT_TEMP': 0.0,
            'CLOUD_REF_CLOUDY_SKY_TEMP': 0.0,
            'CLOUD_REF_CLOUDY_AMBIENT_TEMP': 0.0,
            'CLOUD_CALIBRATION_COEFFICIENT': 1.0,
        },
    }
    # slot 0 = camera temp (must be ignored), slot 11 = referenced ambient, slot 20 = Sky Temperature
    get_value = _values({0: 999.0, 11: 5.0, 20: 5.0})

    percentage = sensors_mapping.calculate_cloud_percentage(config, get_value)

    # delta = 5 - 5 = 0 -> at/above cloudy reference delta -> 100%
    assert percentage == 100.0


def test_ambient_sensor_ref_overrides_own_ambient():
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'blinka_temp_sensor_mlx90615_i2c',
            'A_USER_VAR_SLOT': 'sensor_user_10',
            'CLOUD_AMBIENT_SENSOR_REF': 'sensor_user_12',
            'CLOUD_REF_CLEAR_SKY_TEMP': -30.0,
            'CLOUD_REF_CLEAR_AMBIENT_TEMP': 0.0,
            'CLOUD_REF_CLOUDY_SKY_TEMP': 0.0,
            'CLOUD_REF_CLOUDY_AMBIENT_TEMP': 0.0,
            'CLOUD_CALIBRATION_COEFFICIENT': 1.0,
        },
    }
    # slot 10 = own Temperature/ambient (must be ignored), slot 12 = referenced ambient, slot 11 = Sky Temperature
    get_value = _values({10: 999.0, 12: 0.0, 11: -15.0})

    percentage = sensors_mapping.calculate_cloud_percentage(config, get_value)

    # delta = -15 - 0 = -15 -> halfway between -30 and 0 -> 50%
    assert percentage == 50.0


def test_camera_temperature_cannot_be_used_as_ambient_reference():
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'blinka_temp_sensor_mlx90614_i2c',
            'A_USER_VAR_SLOT': 'sensor_user_10',
            'CLOUD_AMBIENT_SENSOR_REF': 'sensor_user_0',
        },
    }

    assert sensors_mapping.calculate_cloud_percentage(config, _values({0: 0.0, 10: 10.0, 11: -15.0})) is None


def test_calibration_coefficient_scales_delta():
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'blinka_temp_sensor_mlx90614_i2c',
            'A_USER_VAR_SLOT': 'sensor_user_10',
            'CLOUD_REF_CLEAR_SKY_TEMP': -30.0,
            'CLOUD_REF_CLEAR_AMBIENT_TEMP': 0.0,
            'CLOUD_REF_CLOUDY_SKY_TEMP': 0.0,
            'CLOUD_REF_CLOUDY_AMBIENT_TEMP': 0.0,
            'CLOUD_CALIBRATION_COEFFICIENT': 2.0,
        },
    }
    # raw delta = -15 - 0 = -15, scaled by coefficient 2.0 -> -30 -> exactly clear reference delta -> 0%
    get_value = _values({10: 0.0, 11: -15.0})

    percentage = sensors_mapping.calculate_cloud_percentage(config, get_value)

    assert percentage == 0.0


def test_calibration_offset_corrects_sensor_bias():
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'blinka_temp_sensor_mlx90614_i2c',
            'A_USER_VAR_SLOT': 'sensor_user_10',
            'CLOUD_REF_CLEAR_SKY_TEMP': -30.0,
            'CLOUD_REF_CLEAR_AMBIENT_TEMP': 0.0,
            'CLOUD_REF_CLOUDY_SKY_TEMP': 0.0,
            'CLOUD_REF_CLOUDY_AMBIENT_TEMP': 0.0,
            'CLOUD_CALIBRATION_COEFFICIENT': 1.0,
            'CLOUD_CALIBRATION_OFFSET': -5.0,
        },
    }
    # sensor reads 5 C hot: raw delta = -10 - 0 = -10, offset -5 -> -15 -> halfway -> 50%
    get_value = _values({10: 0.0, 11: -10.0})

    percentage = sensors_mapping.calculate_cloud_percentage(config, get_value)

    assert percentage == 50.0


def test_invalid_reference_order_returns_none():
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'blinka_temp_sensor_mlx90614_i2c',
            'A_USER_VAR_SLOT': 'sensor_user_10',
            'CLOUD_REF_CLEAR_SKY_TEMP': 0.0,
            'CLOUD_REF_CLEAR_AMBIENT_TEMP': 0.0,
            'CLOUD_REF_CLOUDY_SKY_TEMP': 0.0,
            'CLOUD_REF_CLOUDY_AMBIENT_TEMP': 0.0,
        },
    }

    assert sensors_mapping.calculate_cloud_percentage(config, _values({10: 10.0, 11: -20.0})) is None


def test_temperatures_are_normalized_before_celsius_references_are_applied():
    config = {
        'TEMP_DISPLAY': 'f',
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'blinka_temp_sensor_mlx90614_i2c',
            'A_USER_VAR_SLOT': 'sensor_user_10',
            # reference readings are raw values in the same display units as
            # everything else - -22 F/32 F = -30 C/0 C, 33.8 F/32 F = 1 C/0 C
            'CLOUD_REF_CLEAR_SKY_TEMP': -22.0,
            'CLOUD_REF_CLEAR_AMBIENT_TEMP': 32.0,
            'CLOUD_REF_CLOUDY_SKY_TEMP': 33.8,
            'CLOUD_REF_CLOUDY_AMBIENT_TEMP': 32.0,
            'CLOUD_CALIBRATION_COEFFICIENT': 1.0,
        },
    }
    # 50 F ambient and 23.9 F sky are 10 C and -4.5 C: a -14.5 C delta,
    # halfway between the -30 C and 1 C reference deltas.
    get_value = _values({10: 50.0, 11: 23.9})

    percentage = sensors_mapping.calculate_cloud_percentage(config, get_value)

    assert percentage == 50.0


def test_unavailable_sky_temperature_returns_none():
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'blinka_temp_sensor_mlx90614_i2c',
            'A_USER_VAR_SLOT': 'sensor_user_10',
        },
    }

    assert sensors_mapping.calculate_cloud_percentage(config, lambda idx: None) is None


def test_unavailable_ambient_temperature_returns_none():
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'blinka_temp_sensor_mlx90640_i2c',
            'A_USER_VAR_SLOT': 'sensor_user_10',
        },
    }

    get_value = {10: -20.0}.get

    assert sensors_mapping.calculate_cloud_percentage(config, get_value) is None


def test_no_configured_cloud_sensor_returns_none():
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'blinka_rain_sensor_fc37',
        },
    }

    assert sensors_mapping.calculate_cloud_percentage(config, _values({})) is None
