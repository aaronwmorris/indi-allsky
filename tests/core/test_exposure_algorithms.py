import ctypes
from multiprocessing import Array
import pytest

from indi_allsky import constants
from indi_allsky.exposure.basic import IndiAllSky_Exposure_Basic
from indi_allsky.exposure.legacy_autogain import IndiAllSky_Exposure_Legacy_AutoGain
from indi_allsky.exposure.autogain_exposurepriority_dB import (
    IndiAllSky_Exposure_AutoGain_ExposurePriority_dB,
    IndiAllSky_Exposure_AutoGain_ExposurePriority_dB_1_10,
    IndiAllSky_Exposure_AutoGain_ExposurePriority_ISO,
    IndiAllSky_Exposure_AutoGain_ExposurePriority_ISO_1_100,
)


@pytest.fixture
def exposure_setup():
    config = {
        'TARGET_ADU': 100,
        'TARGET_ADU_DAY': 80,
        'TARGET_ADU_DEV': 10,
        'TARGET_ADU_DEV_DAY': 15,
        'CCD_CONFIG': {'AUTO_GAIN_LEVELS': 5},
    }
    # exposure_av in microseconds: [cur, next, delta, min_night, min_day, max, sqm]
    exposure_av = Array(ctypes.c_int32, [
        1000000, 1000000, 0,
        1000,    # min night (0.001s)
        100,     # min day (0.0001s)
        30000000,# max (30s)
        5000000, # sqm (5s)
    ])
    # gain_av in 1/1000 gain
    gain_av = Array(ctypes.c_int32, [
        100000, 100000, 0, # cur, next, delta (100.0)
        0, 100000,         # day min/max (0 to 100)
        100000, 400000,    # night min/max (100 to 400)
        50000, 200000,     # moonmode min/max (50 to 200)
        100000,            # sqm
    ])
    binning_av = Array('i', [1, 1, 1, 2, 1, 1])
    night_av = Array('i', [1, 0])  # night=1, moonmode=0

    return config, exposure_av, gain_av, binning_av, night_av


def test_exposure_basic(exposure_setup):
    config, exp_av, gain_av, bin_av, night_av = exposure_setup
    exp_calc = IndiAllSky_Exposure_Basic(config, exp_av, gain_av, bin_av, night_av)

    assert exp_calc.exposure_min == 0.001
    assert exp_calc.exposure_max == 30.0
    assert exp_calc.gain_min == 100.0
    assert exp_calc.gain_max == 400.0

    # Compare exposure with target ADU
    adu, avg = exp_calc.compare_exposure(50.0, 1.0, 100.0)
    assert adu == 50.0

    # Adjust exposure gain
    next_exp, next_gain, exp_delta, gain_delta = exp_calc.adjust_exposure_gain(1.0, 100.0, 2.0)
    assert next_exp == 2.0
    assert next_gain == 400.0
    assert exp_delta == 1.0


def test_exposure_legacy_autogain(exposure_setup):
    config, exp_av, gain_av, bin_av, night_av = exposure_setup
    exp_calc = IndiAllSky_Exposure_Legacy_AutoGain(config, exp_av, gain_av, bin_av, night_av)

    exp_calc.post_init()
    assert len(exp_calc.auto_gain_step_list) == 5
    assert exp_calc.gain_min == 100.0
    assert exp_calc.gain_max == 400.0

    # Test increasing exposure
    next_exp, next_gain, exp_d, gain_d = exp_calc.adjust_exposure_gain(1.0, 100.0, 5.0)
    assert next_exp > 1.0

    # Test decreasing exposure
    next_exp, next_gain, exp_d, gain_d = exp_calc.adjust_exposure_gain(10.0, 100.0, 2.0)
    assert next_exp < 10.0


def test_exposure_autogain_priority_db_variants(exposure_setup):
    config, exp_av, gain_av, bin_av, night_av = exposure_setup

    # Test 1_10 (e.g. ZWO)
    calc_1_10 = IndiAllSky_Exposure_AutoGain_ExposurePriority_dB_1_10(config, exp_av, gain_av, bin_av, night_av)
    assert calc_1_10.gain2dB(100.0) == 10.0
    assert calc_1_10.dB2gain(10.0) == 100.0

    # Test dB 1:1 (e.g. QHY)
    calc_db = IndiAllSky_Exposure_AutoGain_ExposurePriority_dB(config, exp_av, gain_av, bin_av, night_av)
    assert calc_db.gain2dB(20.0) == 20.0
    assert calc_db.dB2gain(20.0) == 20.0

    # Test ISO
    calc_iso = IndiAllSky_Exposure_AutoGain_ExposurePriority_ISO(config, exp_av, gain_av, bin_av, night_av)
    db_val = calc_iso.gain2dB(200.0)
    assert calc_iso.dB2gain(db_val) == pytest.approx(200.0)

    # Test ISO 1_100
    calc_iso_100 = IndiAllSky_Exposure_AutoGain_ExposurePriority_ISO_1_100(config, exp_av, gain_av, bin_av, night_av)
    db_val = calc_iso_100.gain2dB(2.0)
    assert calc_iso_100.dB2gain(db_val) == pytest.approx(2.0)

    # Test adjust_exposure_gain increase & reduce
    next_exp, next_gain, _, _ = calc_1_10.adjust_exposure_gain(1.0, 100.0, 2.0)
    assert next_exp == 2.0

    next_exp, next_gain, _, _ = calc_1_10.adjust_exposure_gain(30.0, 100.0, 40.0)
    assert next_exp == 30.0
    assert next_gain > 100.0
