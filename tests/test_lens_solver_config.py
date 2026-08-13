from indi_allsky.lens_solver import applySolvedValuesToConfig


VALUES = {
    'AZIMUTH_ANGLE': 37.5,
    'LATITUDE_OFFSET': 2.25,
    'LONGITUDE_OFFSET': -1.5,
    'IMAGE_CIRCLE_DIAMETER': 1700,
    'OFFSET_X': 25,
    'OFFSET_Y': -12,
}


def _base_config():
    # pre-existing values on every key the function must NOT touch, plus an unrelated leaf
    return {
        'OWNER': 'someone',
        'LENS_NAME': 'a lens',
        'LENS_AZIMUTH': 0.0,
        'LENS_ALTITUDE': 45.0,
        'LENS_IMAGE_CIRCLE': 3000,
        'LENS_OFFSET_X': 111,
        'LENS_OFFSET_Y': -222,
        'VIRTUALSKY': {
            'LATITUDE_OFFSET': 0.0,
            'LONGITUDE_OFFSET': 0.0,
            'IMAGE_CIRCLE_DIAMETER': 3500,
            'OFFSET_X': 0,
            'OFFSET_Y': 0,
            'MAGNITUDE': 6.0,  # unrelated VIRTUALSKY leaf -- must survive
        },
    }


def test_writes_exactly_the_six_keys():
    config = _base_config()

    applySolvedValuesToConfig(config, VALUES)

    assert config['LENS_AZIMUTH'] == VALUES['AZIMUTH_ANGLE']
    assert config['VIRTUALSKY']['LATITUDE_OFFSET'] == VALUES['LATITUDE_OFFSET']
    assert config['VIRTUALSKY']['LONGITUDE_OFFSET'] == VALUES['LONGITUDE_OFFSET']
    assert config['VIRTUALSKY']['IMAGE_CIRCLE_DIAMETER'] == VALUES['IMAGE_CIRCLE_DIAMETER']
    assert config['VIRTUALSKY']['OFFSET_X'] == VALUES['OFFSET_X']
    assert config['VIRTUALSKY']['OFFSET_Y'] == VALUES['OFFSET_Y']


def test_lens_altitude_and_lens_image_circle_family_untouched():
    config = _base_config()

    applySolvedValuesToConfig(config, VALUES)

    assert config['LENS_ALTITUDE'] == 45.0
    assert config['LENS_IMAGE_CIRCLE'] == 3000
    assert config['LENS_OFFSET_X'] == 111
    assert config['LENS_OFFSET_Y'] == -222


def test_unrelated_keys_preserved():
    config = _base_config()

    applySolvedValuesToConfig(config, VALUES)

    assert config['OWNER'] == 'someone'
    assert config['LENS_NAME'] == 'a lens'
    assert config['VIRTUALSKY']['MAGNITUDE'] == 6.0


def test_mutates_in_place_and_returns_same_object():
    config = _base_config()
    virtualsky_ref = config['VIRTUALSKY']

    returned = applySolvedValuesToConfig(config, VALUES)

    assert returned is config
    # VIRTUALSKY itself must be mutated in place, never reassigned
    assert config['VIRTUALSKY'] is virtualsky_ref


def test_creates_missing_virtualsky_section():
    config = _base_config()
    del config['VIRTUALSKY']

    applySolvedValuesToConfig(config, VALUES)

    assert config['VIRTUALSKY'] == {
        'LATITUDE_OFFSET': VALUES['LATITUDE_OFFSET'],
        'LONGITUDE_OFFSET': VALUES['LONGITUDE_OFFSET'],
        'IMAGE_CIRCLE_DIAMETER': VALUES['IMAGE_CIRCLE_DIAMETER'],
        'OFFSET_X': VALUES['OFFSET_X'],
        'OFFSET_Y': VALUES['OFFSET_Y'],
    }


def test_builtin_types_only():
    config = _base_config()

    applySolvedValuesToConfig(config, VALUES)

    assert type(config['LENS_AZIMUTH']) is float
    assert type(config['VIRTUALSKY']['LATITUDE_OFFSET']) is float
    assert type(config['VIRTUALSKY']['LONGITUDE_OFFSET']) is float
    assert type(config['VIRTUALSKY']['IMAGE_CIRCLE_DIAMETER']) is int
    assert type(config['VIRTUALSKY']['OFFSET_X']) is int
    assert type(config['VIRTUALSKY']['OFFSET_Y']) is int
