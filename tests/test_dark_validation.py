import numpy
import pytest

from indi_allsky.dark_validation import InvalidDarkMasterError
from indi_allsky.dark_validation import validate_dark_master_data


@pytest.mark.parametrize(
    'data',
    (
        numpy.zeros((4, 6), dtype=numpy.uint8),
        numpy.zeros((4, 6), dtype=numpy.uint16),
        numpy.zeros((3, 4, 6), dtype=numpy.uint16),
        numpy.zeros((4, 6), dtype=numpy.float32),
        numpy.array([], dtype=numpy.uint16),
    ),
)
def test_all_zero_master_dark_is_rejected(data):
    with pytest.raises(InvalidDarkMasterError, match='only zero-valued pixels'):
        validate_dark_master_data(data)


@pytest.mark.parametrize(
    'value',
    (
        1,
        -1,
        numpy.nextafter(numpy.float32(0), numpy.float32(1)),
    ),
)
def test_near_zero_master_dark_with_real_data_is_accepted(value):
    data = numpy.zeros((4, 6), dtype=numpy.asarray(value).dtype)
    data[2, 3] = value

    validate_dark_master_data(data)
