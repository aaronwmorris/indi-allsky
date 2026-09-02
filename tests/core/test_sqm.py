import ctypes
from multiprocessing import Array
import numpy as np
import pytest
from unittest.mock import MagicMock

from indi_allsky.sqm import IndiAllskySqm
from indi_allsky import constants


@pytest.fixture
def sqm_fixture():
    config = {
        'CAMERA_SQM': {'MAGNITUDE_OFFSET': 25.0},
        'CCD_EXPOSURE_MAX': 60.0,
        'SQM_ROI': [10, 10, 50, 50],
    }
    exposure_av = Array(ctypes.c_int32, [-1, -1, -1, -1, -1, -1, -1])
    gain_av = Array(ctypes.c_int32, [0, 0, 0, 0, 0, 100000, 400000, 0, 0, 0])
    binning_av = Array('i', [1, 1, 1, 1, 1, 1])

    # mask dict with binning 1 and 2
    mask = {1: np.ones((100, 100), dtype=np.uint8) * 255, 2: None}

    sqm = IndiAllskySqm(config, exposure_av, gain_av, binning_av, mask=mask)
    return sqm


def test_sqm_mono_and_color_average(sqm_fixture):
    # Test mono data (2D array)
    mono_data = np.full((100, 100), 50, dtype=np.uint8)
    i_ref_mono = MagicMock()
    i_ref_mono.hdulist = [MagicMock(data=mono_data)]
    i_ref_mono.binning = 1
    i_ref_mono.exposure = 30.0
    i_ref_mono.gain = 200.0

    avg = sqm_fixture.averageAdu(i_ref_mono)
    assert avg == pytest.approx(50.0)

    # Test color data (3D array, green is channel 1)
    color_data = np.zeros((3, 100, 100), dtype=np.uint8)
    color_data[1, :, :] = 80
    i_ref_color = MagicMock()
    i_ref_color.hdulist = [MagicMock(data=color_data)]
    i_ref_color.binning = 1

    avg_color = sqm_fixture.averageAdu(i_ref_color)
    assert avg_color == pytest.approx(80.0)


def test_sqm_jsqm_and_magnitude(sqm_fixture):
    mono_data = np.full((100, 100), 100, dtype=np.uint8)
    i_ref = MagicMock()
    i_ref.hdulist = [MagicMock(data=mono_data)]
    i_ref.binning = 1
    i_ref.exposure = 20.0
    i_ref.gain = 200.0

    # Test jSqm
    jsqm = sqm_fixture.jSqm(i_ref)
    assert isinstance(jsqm, float)
    assert jsqm > 0

    # Test magnitudeSqm
    mag_sqm, raw_mag, sqm_avg = sqm_fixture.magnitudeSqm(i_ref)
    assert sqm_avg == pytest.approx(100.0)
    # raw_mag = -1 * (log10(100) * 2.5) = -5.0
    assert raw_mag == pytest.approx(-5.0)
    assert mag_sqm == pytest.approx(20.0)


def test_sqm_mask_generation_fallback():
    # SQM without explicit SQM_ROI to test default central FOV
    config = {'SQM_FOV_DIV': 4}
    exposure_av = Array(ctypes.c_int32, [-1] * 7)
    gain_av = Array(ctypes.c_int32, [-1] * 10)
    binning_av = Array('i', [-1] * 6)
    mask = {1: None}

    sqm = IndiAllskySqm(config, exposure_av, gain_av, binning_av, mask=mask)
    mono_data = np.full((100, 100), 50, dtype=np.uint8)
    i_ref = MagicMock()
    i_ref.hdulist = [MagicMock(data=mono_data)]
    i_ref.binning = 1

    avg = sqm.averageAdu(i_ref)
    assert avg == pytest.approx(50.0)
    assert sqm._sqm_mask_dict[1] is not None
