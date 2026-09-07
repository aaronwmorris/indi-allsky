import pytest

from indi_allsky.lens_solver.request import parseSolverRequestValues


VALUES = dict(AZIMUTH_ANGLE=200, LATITUDE_OFFSET=0, LONGITUDE_OFFSET=0,
              IMAGE_CIRCLE_DIAMETER=2951, OFFSET_X=7, OFFSET_Y=-135,
              LENS_ALTITUDE=54, POINTING_AZIMUTH=123)


@pytest.mark.parametrize('key', VALUES)
@pytest.mark.parametrize('value', [True, False, '', '54 degrees', [], {}, None, 'NaN', 'Infinity'])
@pytest.mark.parametrize('for_save', [False, True])
def test_bad_geometry_values_are_rejected(key, value, for_save):
    values, error = parseSolverRequestValues(dict(VALUES, **{key: value}), for_save=for_save)
    assert values is None
    assert error
