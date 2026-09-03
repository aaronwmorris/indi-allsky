import numpy


class InvalidDarkMasterError(RuntimeError):
    pass


def dark_adu_maximum(bitmax, image_bitpix):
    """Return the sensor maximum used for dark and BPM hot-pixel thresholds."""
    configured_bits = int(bitmax or 0)
    if configured_bits:
        return (2 ** configured_bits) - 1

    source_bits = int(image_bitpix)
    if source_bits in (-32, 32):
        # Floating-point and 32-bit containers commonly carry 16-bit sensor data.
        source_bits = 16
    return (2 ** source_bits) - 1


def validate_dark_master_data(data):
    """Reject a master dark that cannot provide any calibration signal."""
    data_array = numpy.asanyarray(data)
    if data_array.size and numpy.count_nonzero(data_array):
        return

    raise InvalidDarkMasterError(
        'Master dark contains only zero-valued pixels; '
        'the camera returned no usable calibration data.'
    )
