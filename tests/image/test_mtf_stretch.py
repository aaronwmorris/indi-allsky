import numpy
import pytest

from indi_allsky.stretch.mode2_mtf import (
    IndiAllSky_Mode2_MTF_Stretch,
    IndiAllSky_Mode2_MTF_Stretch_x2,
)


@pytest.mark.parametrize('stretch_class', [
    IndiAllSky_Mode2_MTF_Stretch,
    IndiAllSky_Mode2_MTF_Stretch_x2,
])
@pytest.mark.parametrize('bit_depths', [
    (10, 12, 16),
    (16, 14, 12, 10, 8, 16),
])
@pytest.mark.parametrize('config', [
    {},
    {'IMAGE_STRETCH': {
        'MODE2_SHADOWS': 0.05,
        'MODE2_MIDTONES': 0.25,
        'MODE2_HIGHLIGHTS': 0.95,
    }},
])
def test_mtf_matches_fresh_stretch_after_bit_depth_changes(stretch_class, bit_depths, config):
    stretch = stretch_class(config)

    for bit_depth in bit_depths:
        data_max = (2 ** bit_depth) - 1
        data = numpy.array([
            [0, 1, min(1081, data_max)],
            [data_max // 2, data_max - 1, data_max],
        ], dtype=numpy.uint16)

        expected = stretch_class(config).stretch(data, bit_depth, 1)
        actual = stretch.stretch(data, bit_depth, 1)

        numpy.testing.assert_array_equal(actual, expected)
        assert actual.dtype == expected.dtype


@pytest.mark.parametrize('stretch_class', [
    IndiAllSky_Mode2_MTF_Stretch,
    IndiAllSky_Mode2_MTF_Stretch_x2,
])
def test_mtf_reuses_lookup_table_at_unchanged_bit_depth(stretch_class):
    stretch = stretch_class({})
    data = numpy.array([[0, 1081, 65535]], dtype=numpy.uint16)

    expected = stretch.stretch(data, 16, 1)
    lookup_table = stretch._mtf_lut
    actual = stretch.stretch(data, 16, 1)

    numpy.testing.assert_array_equal(actual, expected)
    assert stretch._mtf_lut is lookup_table
