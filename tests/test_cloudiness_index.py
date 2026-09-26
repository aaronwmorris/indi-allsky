from indi_allsky import sensors_mapping


def _values(mapping):
    return lambda index: mapping.get(index)


def _config(**temp_sensor):
    settings = {
        'A_CLASSNAME': 'blinka_temp_sensor_mlx90614_i2c',
        'A_USER_VAR_SLOT': 'sensor_user_10',
        'CLOUDINESS_INDEX_ENABLE': True,
        'CLOUDINESS_INDEX_TEMP_UNIT': 'c',
        'CLOUDINESS_INDEX_CLEAR_TEMP': -20.0,
        'CLOUDINESS_INDEX_CLOUDY_TEMP': 10.0,
    }
    settings.update(temp_sensor)
    return {'TEMP_SENSOR': settings}


def test_returns_none_until_calibration_is_enabled():
    config = _config(CLOUDINESS_INDEX_ENABLE=False)

    assert sensors_mapping.calculate_cloudiness_index(config, _values({10: 10.0, 11: -20.0})) is None


def test_raw_sky_calibration_interpolates_live_sky_temperature():
    # -5 C is halfway between the -20 C clear and 10 C cloudy references.
    cloudiness_index = sensors_mapping.calculate_cloudiness_index(
        _config(),
        _values({10: 10.0, 11: -5.0}),
    )

    assert cloudiness_index == 50.0


def test_clamps_values_outside_calibrated_range():
    config = _config()

    assert sensors_mapping.calculate_cloudiness_index(config, _values({10: 10.0, 11: -25.0})) == 0.0
    assert sensors_mapping.calculate_cloudiness_index(config, _values({10: 10.0, 11: 15.0})) == 100.0


def test_rejects_equal_calibration_references():
    config = _config(CLOUDINESS_INDEX_CLOUDY_TEMP=-20.0)

    assert sensors_mapping.calculate_cloudiness_index(config, _values({10: 10.0, 11: -5.0})) is None


def test_coefficient_and_offset_tune_the_normalized_index():
    cloudiness_index = sensors_mapping.calculate_cloudiness_index(
        _config(CLOUDINESS_INDEX_COEFFICIENT=0.5, CLOUDINESS_INDEX_OFFSET=10.0),
        _values({10: 10.0, 11: -5.0}),
    )

    assert cloudiness_index == 35.0


def test_mlx90640_uses_its_sky_temperature_without_an_ambient_reference():
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'blinka_temp_sensor_mlx90640_i2c',
            'A_USER_VAR_SLOT': 'sensor_user_10',
            'CLOUDINESS_INDEX_ENABLE': True,
            'CLOUDINESS_INDEX_CLEAR_TEMP': -20.0,
            'CLOUDINESS_INDEX_CLOUDY_TEMP': 10.0,
        },
    }

    assert sensors_mapping.calculate_cloudiness_index(config, _values({10: -5.0})) == 50.0


def test_multiple_cloud_sensors_require_an_explicit_selection():
    config = _config(
        B_CLASSNAME='blinka_temp_sensor_mlx90615_i2c',
        B_USER_VAR_SLOT='sensor_user_20',
    )

    assert sensors_mapping.calculate_cloudiness_index(config, _values({10: 10.0, 11: -5.0, 20: 10.0, 21: -5.0})) is None


def test_selected_cloud_sensor_is_used_when_multiple_are_configured():
    config = _config(
        B_CLASSNAME='blinka_temp_sensor_mlx90615_i2c',
        B_USER_VAR_SLOT='sensor_user_20',
        CLOUDINESS_INDEX_SENSOR='sensor_user_20',
    )

    cloudiness_index = sensors_mapping.calculate_cloudiness_index(
        config,
        _values({10: 10.0, 11: -20.0, 20: 10.0, 21: -5.0}),
    )

    assert cloudiness_index == 50.0


def test_reference_units_are_independent_of_live_display_units():
    config = _config()
    config['TEMP_DISPLAY'] = 'f'

    # The live sky reading is 23 F, or -5 C.
    cloudiness_index = sensors_mapping.calculate_cloudiness_index(config, _values({10: 50.0, 11: 23.0}))

    assert cloudiness_index == 50.0
