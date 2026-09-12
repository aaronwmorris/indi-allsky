import ctypes
from multiprocessing import Array
from datetime import datetime
import pytest
import math

from indi_allsky.utils import IndiAllSkyExposureUtils, IndiAllSkyDateCalcs
from indi_allsky import constants


@pytest.fixture
def exposure_av():
    return Array(ctypes.c_int32, [-1, -1, -1, -1, -1, -1, -1])


@pytest.fixture
def gain_av():
    return Array(ctypes.c_int32, [-1, -1, -1, -1, -1, -1, -1, -1, -1, -1])


@pytest.fixture
def binning_av():
    return Array('i', [-1, -1, -1, -1, -1, -1])


def test_exposure_utils_properties(exposure_av, gain_av, binning_av):
    config = {}
    utils = IndiAllSkyExposureUtils(config, exposure_av, gain_av, binning_av)

    # Test Exposure getters and setters (stored in microseconds)
    utils.EXPOSURE_CURRENT = 1.5
    assert utils.EXPOSURE_CURRENT == 1.5
    assert exposure_av[constants.EXPOSURE_CURRENT] == 1500000

    utils.EXPOSURE_NEXT = 2.25
    assert utils.EXPOSURE_NEXT == 2.25

    utils.EXPOSURE_DELTA = 0.5
    assert utils.EXPOSURE_DELTA == 0.5

    utils.EXPOSURE_MIN_NIGHT = 0.001
    assert utils.EXPOSURE_MIN_NIGHT == 0.001

    utils.EXPOSURE_MIN_DAY = 0.00005
    assert utils.EXPOSURE_MIN_DAY == 0.00005

    utils.EXPOSURE_MAX = 60.0
    assert utils.EXPOSURE_MAX == 60.0

    utils.EXPOSURE_SQM = 10.0
    assert utils.EXPOSURE_SQM == 10.0

    # Test Gain getters and setters (stored in 1/1000 gain)
    utils.GAIN_CURRENT = 100.5
    assert utils.GAIN_CURRENT == 100.5
    assert gain_av[constants.GAIN_CURRENT] == 100500

    utils.GAIN_NEXT = 200.0
    assert utils.GAIN_NEXT == 200.0

    utils.GAIN_DELTA = -10.0
    assert utils.GAIN_DELTA == -10.0

    utils.GAIN_MIN_DAY = 0.0
    assert utils.GAIN_MIN_DAY == 0.0

    utils.GAIN_MAX_DAY = 50.0
    assert utils.GAIN_MAX_DAY == 50.0

    utils.GAIN_MIN_NIGHT = 100.0
    assert utils.GAIN_MIN_NIGHT == 100.0

    utils.GAIN_MAX_NIGHT = 400.0
    assert utils.GAIN_MAX_NIGHT == 400.0

    utils.GAIN_MIN_MOONMODE = 50.0
    assert utils.GAIN_MIN_MOONMODE == 50.0

    utils.GAIN_MAX_MOONMODE = 250.0
    assert utils.GAIN_MAX_MOONMODE == 250.0

    utils.GAIN_SQM = 150.0
    assert utils.GAIN_SQM == 150.0

    # Test Binning getters and setters
    utils.BINNING_CURRENT = 2
    assert utils.BINNING_CURRENT == 2
    assert binning_av[constants.BINNING_CURRENT] == 2

    utils.BINNING_NEXT = 1
    assert utils.BINNING_NEXT == 1

    utils.BINNING_DAY = 1
    assert utils.BINNING_DAY == 1

    utils.BINNING_NIGHT = 2
    assert utils.BINNING_NIGHT == 2

    utils.BINNING_MOONMODE = 1
    assert utils.BINNING_MOONMODE == 1

    utils.BINNING_SQM = 2
    assert utils.BINNING_SQM == 2


def test_date_calcs_all_branches():
    config = {'NIGHT_SUN_ALT_DEG': -6.0}
    # Adelaide, Australia
    position_av = Array('f', [-34.9285, 138.6007, 50.0, 0.0, 0.0])
    date_calcs = IndiAllSkyDateCalcs(config, position_av)

    # Test getDayDate returns today or adjacent day
    day_date = date_calcs.getDayDate()
    assert isinstance(day_date, datetime.now().date().__class__)

    # Test transitions
    next_transition = date_calcs.getNextDayNightTransition()
    assert isinstance(next_transition, datetime)

    # Test various times of day across meridian/antimeridian conditions
    dt_noon = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    res_noon = date_calcs.calcDayDate(dt_noon)
    assert res_noon is not None

    dt_midnight = datetime.now().replace(hour=0, minute=5, second=0, microsecond=0)
    res_midnight = date_calcs.calcDayDate(dt_midnight)
    assert res_midnight is not None

    dt_late = datetime.now().replace(hour=23, minute=55, second=0, microsecond=0)
    res_late = date_calcs.calcDayDate(dt_late)
    assert res_late is not None
