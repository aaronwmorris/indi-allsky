# (key, cast, min, max) -- ranges match the config form validators.
SOLVER_REQUEST_FIELDS = (
    ('AZIMUTH_ANGLE', float, 0.0, 360.0),
    ('LATITUDE_OFFSET', float, -30.0, 30.0),
    ('LONGITUDE_OFFSET', float, -30.0, 30.0),
    ('IMAGE_CIRCLE_DIAMETER', int, 100, 20000),
    ('OFFSET_X', int, -10000, 10000),
    ('OFFSET_Y', int, -10000, 10000),
)


def parseSolverRequestValues(data):
    """Validate and coerce the six solver form values from request JSON.
    Returns (values, None) or (None, error); only the six known keys are
    ever passed through.
    """
    values = {}
    for key, cast, vmin, vmax in SOLVER_REQUEST_FIELDS:
        if key not in data:
            return None, 'Missing field: {0:s}'.format(key)
        try:
            # json accepts literal Infinity/NaN; int(inf) raises OverflowError
            v = cast(float(data[key]))
        except (TypeError, ValueError, OverflowError):
            return None, 'Invalid value for {0:s}'.format(key)
        # NaN comparisons are always False, so this also rejects NaN
        if not vmin <= v <= vmax:
            return None, '{0:s} out of range'.format(key)
        values[key] = v

    return values, None


def applySolvedValuesToConfig(config, values):
    """Write exactly LENS_AZIMUTH and the five VIRTUALSKY offset/diameter
    keys, in place -- never LENS_ALTITUDE or the LENS_IMAGE_CIRCLE family,
    which drive unrelated behavior.
    """
    config['LENS_AZIMUTH'] = values['AZIMUTH_ANGLE']

    if 'VIRTUALSKY' not in config:
        config['VIRTUALSKY'] = {}

    virtualsky = config['VIRTUALSKY']
    virtualsky['LATITUDE_OFFSET'] = values['LATITUDE_OFFSET']
    virtualsky['LONGITUDE_OFFSET'] = values['LONGITUDE_OFFSET']
    virtualsky['IMAGE_CIRCLE_DIAMETER'] = values['IMAGE_CIRCLE_DIAMETER']
    virtualsky['OFFSET_X'] = values['OFFSET_X']
    virtualsky['OFFSET_Y'] = values['OFFSET_Y']

    return config
