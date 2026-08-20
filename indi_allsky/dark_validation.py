import numpy


class InvalidDarkMasterError(RuntimeError):
    pass


def validate_dark_master_data(data):
    """Reject a master dark that cannot provide any calibration signal."""
    data_array = numpy.asanyarray(data)
    if data_array.size and numpy.count_nonzero(data_array):
        return

    raise InvalidDarkMasterError(
        'Master dark contains only zero-valued pixels; '
        'the camera returned no usable calibration data.'
    )
