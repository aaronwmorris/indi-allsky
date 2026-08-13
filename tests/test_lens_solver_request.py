import json
import math

import pytest

from indi_allsky.lens_solver import parseSolverRequestValues


GOOD = {
    'AZIMUTH_ANGLE': '37.5', 'LATITUDE_OFFSET': 2, 'LONGITUDE_OFFSET': -1.5,
    'IMAGE_CIRCLE_DIAMETER': '1700', 'OFFSET_X': 25, 'OFFSET_Y': -12,
}

SIX_KEYS = {
    'AZIMUTH_ANGLE', 'LATITUDE_OFFSET', 'LONGITUDE_OFFSET',
    'IMAGE_CIRCLE_DIAMETER', 'OFFSET_X', 'OFFSET_Y',
}


def test_valid_values_coerced():
    values, error = parseSolverRequestValues(GOOD)
    assert error is None
    assert values['AZIMUTH_ANGLE'] == 37.5
    assert values['IMAGE_CIRCLE_DIAMETER'] == 1700
    assert isinstance(values['IMAGE_CIRCLE_DIAMETER'], int)


def test_missing_key_rejected():
    bad = dict(GOOD)
    del bad['OFFSET_X']
    values, error = parseSolverRequestValues(bad)
    assert values is None
    assert 'OFFSET_X' in error


def test_non_numeric_rejected():
    bad = dict(GOOD, AZIMUTH_ANGLE='north')
    values, error = parseSolverRequestValues(bad)
    assert values is None


def test_out_of_range_rejected():
    for key, val in (
            ('AZIMUTH_ANGLE', 400), ('LATITUDE_OFFSET', 45),
            ('IMAGE_CIRCLE_DIAMETER', -100), ('OFFSET_X', 99999)):
        bad = dict(GOOD, **{key: val})
        values, error = parseSolverRequestValues(bad)
        assert values is None, key


# --- Inclusive boundaries accepted, one-past rejected ----------------------

BOUNDARY_CASES = (
    ('AZIMUTH_ANGLE', 0.0, 360.0),
    ('LATITUDE_OFFSET', -30.0, 30.0),
    ('LONGITUDE_OFFSET', -30.0, 30.0),
    ('IMAGE_CIRCLE_DIAMETER', 100, 20000),
    ('OFFSET_X', -10000, 10000),
    ('OFFSET_Y', -10000, 10000),
)


@pytest.mark.parametrize('key,lo,hi', BOUNDARY_CASES)
def test_inclusive_boundaries_accepted(key, lo, hi):
    for boundary in (lo, hi):
        candidate = dict(GOOD, **{key: boundary})
        values, error = parseSolverRequestValues(candidate)
        assert error is None, (key, boundary, error)
        assert values[key] == boundary


@pytest.mark.parametrize('key,lo,hi', BOUNDARY_CASES)
def test_one_past_boundary_rejected(key, lo, hi):
    step = 1 if isinstance(lo, int) else 0.001
    for boundary in (lo - step, hi + step):
        candidate = dict(GOOD, **{key: boundary})
        values, error = parseSolverRequestValues(candidate)
        assert values is None, (key, boundary)
        assert error is not None


# --- nan/inf produce a structured error, never an uncaught exception -------

@pytest.mark.parametrize('key,_lo,_hi', BOUNDARY_CASES)
@pytest.mark.parametrize('bad_value', [float('nan'), float('inf'), float('-inf')])
def test_nan_inf_rejected_structured(key, _lo, _hi, bad_value):
    candidate = dict(GOOD, **{key: bad_value})
    values, error = parseSolverRequestValues(candidate)
    assert values is None
    assert error is not None


def test_json_infinity_literal_rejected():
    # json.loads() accepts bare Infinity/NaN by default -- confirm the
    # round trip through JSON also produces a structured error, not a 500.
    payload = json.loads('{"AZIMUTH_ANGLE": Infinity, "LATITUDE_OFFSET": 2, '
                          '"LONGITUDE_OFFSET": -1.5, "IMAGE_CIRCLE_DIAMETER": 1700, '
                          '"OFFSET_X": 25, "OFFSET_Y": -12}')
    values, error = parseSolverRequestValues(payload)
    assert values is None
    assert error is not None


def test_extra_keys_stripped():
    extra = dict(GOOD, EXTRA_KEY='sneaky', csrf_token='irrelevant-here')
    values, error = parseSolverRequestValues(extra)
    assert error is None
    assert set(values.keys()) == SIX_KEYS


def test_builtin_types_exact():
    values, error = parseSolverRequestValues(GOOD)
    assert error is None
    for key in ('AZIMUTH_ANGLE', 'LATITUDE_OFFSET', 'LONGITUDE_OFFSET'):
        assert type(values[key]) is float, key
    for key in ('IMAGE_CIRCLE_DIAMETER', 'OFFSET_X', 'OFFSET_Y'):
        assert type(values[key]) is int, key
    json.dumps(values)
