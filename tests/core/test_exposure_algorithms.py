import ctypes
from multiprocessing import Array
import pytest

from indi_allsky import constants
from indi_allsky.exposure.exposureBase import IndiAllSky_Exposure_Base
from indi_allsky.exposure.basic import IndiAllSky_Exposure_Basic
from indi_allsky.exposure.legacy_autogain import IndiAllSky_Exposure_Legacy_AutoGain
from indi_allsky.exposure.autogain_exposurepriority_dB import (
    IndiAllSky_Exposure_AutoGain_ExposurePriority_dB_Base,
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

    # Test clamping below min and above max
    next_exp_low, _, _, _ = exp_calc.adjust_exposure_gain(1.0, 100.0, 0.00001)
    assert next_exp_low == exp_calc.exposure_min

    next_exp_high, _, _, _ = exp_calc.adjust_exposure_gain(1.0, 100.0, 999.0)
    assert next_exp_high == exp_calc.exposure_max

    # Test moon mode
    night_av[constants.NIGHT_MOONMODE] = 1
    assert exp_calc.gain_min == 50.0
    assert exp_calc.gain_max == 200.0

    # Test day mode
    night_av[constants.NIGHT_NIGHT] = 0
    night_av[constants.NIGHT_MOONMODE] = 0
    assert exp_calc.exposure_min == 0.0001
    assert exp_calc.gain_min == 0.0
    assert exp_calc.gain_max == 100.0




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


def test_exposure_base_properties_and_not_implemented(exposure_setup):
    config, exp_av, gain_av, bin_av, night_av = exposure_setup
    base = IndiAllSky_Exposure_Base(config, exp_av, gain_av, bin_av, night_av)

    assert base.target_adu_found is False
    base.target_adu_found = True
    assert base.target_adu_found is True
    assert base.current_adu_target == 0

    with pytest.raises(Exception, match='Not implemented'):
        base.adjust_exposure_gain(1.0, 100.0, 2.0)


def test_exposure_base_compare_exposure_zero_adu(exposure_setup):
    config, exp_av, gain_av, bin_av, night_av = exposure_setup
    base = IndiAllSky_Exposure_Base(config, exp_av, gain_av, bin_av, night_av)
    base.gain_min = 100.0
    base.gain_max = 400.0
    base.adjust_exposure_gain = lambda cur_e, cur_g, next_e: (next_e, cur_g, next_e - cur_e, 0.0)

    # When adu <= 0.0, it sets adu = 0.1
    adu, avg = base.compare_exposure(0.0, 1.0, 100.0)
    assert adu == 0.1
    assert avg == 0.0


def test_exposure_base_daytime_short_exposure(exposure_setup):
    config, exp_av, gain_av, bin_av, night_av = exposure_setup
    night_av[constants.NIGHT_NIGHT] = 0  # DAY
    base = IndiAllSky_Exposure_Base(config, exp_av, gain_av, bin_av, night_av)
    base.gain_min = 100.0
    base.gain_max = 400.0
    base.adjust_exposure_gain = lambda cur_e, cur_g, next_e: (next_e, cur_g, next_e - cur_e, 0.0)

    # Exposure < 0.001 uses day settings and exp_scale_factor 0.5
    adu, avg = base.compare_exposure(50.0, 0.0005, 50.0)
    assert adu == 50.0
    assert avg == 0.0


def test_exposure_base_moving_average_and_limits(exposure_setup):
    config, exp_av, gain_av, bin_av, night_av = exposure_setup
    base = IndiAllSky_Exposure_Base(config, exp_av, gain_av, bin_av, night_av)
    base.gain_min = 100.0
    base.gain_max = 400.0
    base.adjust_exposure_gain = lambda cur_e, cur_g, next_e: (next_e, cur_g, next_e - cur_e, 0.0)

    # Initial exposure matches target (100 +/- 10) -> target_adu_found becomes True
    adu, avg = base.compare_exposure(100.0, 1.0, 100.0)
    assert base.target_adu_found is True
    assert base.current_adu_target == 100.0
    assert avg == 0.0

    # Feed 5 more values (total 5 < 6)
    for _ in range(5):
        adu, avg = base.compare_exposure(100.0, 1.0, 100.0)
        assert avg == 0.0

    # 6th value -> moving average calculated and returned
    adu, avg = base.compare_exposure(100.0, 1.0, 100.0)
    assert avg == 100.0
    assert base.target_adu_found is True

    # Now simulate increasing adu beyond current_adu_target_max (100 + 10 = 110)
    for _ in range(6):
        base.compare_exposure(120.0, 1.0, 100.0)
    assert base.target_adu_found is False

    # Reset target_adu_found
    base.compare_exposure(100.0, 1.0, 100.0)
    assert base.target_adu_found is True

    # Simulate decreasing adu below current_adu_target_min (100 - 10 = 90)
    for _ in range(6):
        base.compare_exposure(80.0, 1.0, 100.0)
    assert base.target_adu_found is False


def test_exposure_base_recalculate_gain_clamping_and_binning(exposure_setup):
    config, exp_av, gain_av, bin_av, night_av = exposure_setup
    base = IndiAllSky_Exposure_Base(config, exp_av, gain_av, bin_av, night_av)

    # Test next_gain > gain_max clamping
    base.gain_min = 100.0
    base.gain_max = 400.0
    base.adjust_exposure_gain = lambda cur_e, cur_g, next_e: (next_e, 500.0, 0.0, 100.0)

    # adu < target_adu_min (50 < 90)
    base.recalculate_exposure(1.0, 100.0, 50.0, 100.0, 90.0, 110.0, 1.0)
    assert base._expUtils.GAIN_NEXT == 400.0
    assert base._expUtils.BINNING_NEXT == base._expUtils.BINNING_NIGHT

    # Test next_gain < gain_min clamping & moonmode binning
    night_av[constants.NIGHT_MOONMODE] = 1
    base.adjust_exposure_gain = lambda cur_e, cur_g, next_e: (next_e, 50.0, 0.0, -50.0)
    # adu > target_adu_max (150 > 110)
    base.recalculate_exposure(1.0, 100.0, 150.0, 100.0, 90.0, 110.0, 1.0)
    assert base._expUtils.GAIN_NEXT == 100.0
    assert base._expUtils.BINNING_NEXT == base._expUtils.BINNING_MOONMODE

    # Test daytime binning & target in range branch
    night_av[constants.NIGHT_NIGHT] = 0
    night_av[constants.NIGHT_MOONMODE] = 0
    base.adjust_exposure_gain = lambda cur_e, cur_g, next_e: (next_e, 200.0, 0.0, 0.0)
    base.recalculate_exposure(1.0, 100.0, 100.0, 100.0, 90.0, 110.0, 1.0)
    assert base.target_adu_found is True
    assert base._current_adu_target == 100.0

    # Test nan adu reaching else: next_exposure = current_exposure
    base.recalculate_exposure(1.0, 100.0, float('nan'), 100.0, 90.0, 110.0, 1.0)
    assert base._expUtils.EXPOSURE_NEXT == 1.0


def test_exposure_legacy_autogain_branches(exposure_setup):
    config, exp_av, gain_av, bin_av, night_av = exposure_setup
    exp_calc = IndiAllSky_Exposure_Legacy_AutoGain(config, exp_av, gain_av, bin_av, night_av)

    # Test daytime exposure_min
    night_av[constants.NIGHT_NIGHT] = 0
    assert exp_calc.exposure_min == 0.0001
    night_av[constants.NIGHT_NIGHT] = 1

    assert exp_calc.exposure_max == 30.0
    assert exp_calc.gain_step is None

    # Call adjust_exposure_gain with uninitialized gain_step (tests auto post_init)
    # Next exposure == current exposure -> no changes
    e, g, de, dg = exp_calc.adjust_exposure_gain(1.0, 100.0, 1.0)
    assert e == 1.0
    assert g == 100.0
    assert de == 0.0
    assert dg == 0.0
    assert exp_calc.gain_step is not None

    # current_gain not in step list with current_exposure >= cutoff_high -> reset to auto_gain_step_list[1]
    e, g, de, dg = exp_calc.adjust_exposure_gain(29.8, 999.0, 35.0)
    assert g == exp_calc.auto_gain_step_list[1]

    # next_exposure < exposure_min clamp
    e, g, de, dg = exp_calc.adjust_exposure_gain(1.0, 100.0, 0.00001)
    assert e == exp_calc.exposure_min

    # next_exposure > exposure_max with current_exposure < cutoff_high
    e, g, de, dg = exp_calc.adjust_exposure_gain(1.0, 100.0, 50.0)
    assert e == exp_calc.auto_gain_exposure_cutoff_high

    # Increase exposure when already at max gain (400.0) and clamped to exposure_max
    e, g, de, dg = exp_calc.adjust_exposure_gain(1.0, 400.0, 50.0)
    assert e == exp_calc.exposure_max
    assert g == 400.0
    assert dg == 0.0

    # Increase exposure when current_exposure >= cutoff_high (increases gain, keeps exposure)
    e, g, de, dg = exp_calc.adjust_exposure_gain(29.8, 100.0, 35.0)
    assert g > 100.0
    assert dg > 0.0

    # Decrease exposure when already at min gain (100.0)
    e, g, de, dg = exp_calc.adjust_exposure_gain(5.0, 100.0, 2.0)
    assert e == 2.0
    assert g == 100.0
    assert dg == 0.0

    # Decrease exposure when current_exposure <= cutoff_low (decreases gain, keeps exposure)
    e, g, de, dg = exp_calc.adjust_exposure_gain(10.0, 250.0, 5.0)
    assert g < 250.0
    assert dg < 0.0

    # Decrease exposure when current_exposure > cutoff_low (maintains gain, decreases exposure)
    cutoff_low = exp_calc.auto_gain_exposure_cutoff_low
    e, g, de, dg = exp_calc.adjust_exposure_gain(cutoff_low + 2.0, 250.0, cutoff_low + 1.0)
    assert g == 250.0
    assert e == cutoff_low + 1.0

    # Test compare_exposure and recalculate_exposure delegation
    adu, avg = exp_calc.compare_exposure(100.0, 1.0, 100.0)
    assert adu == 100.0
    exp_calc.recalculate_exposure(1.0, 100.0, 100.0, 100.0, 90.0, 110.0, 1.0)


def test_exposure_legacy_autogain_cutoff_large_max_exposure(exposure_setup):
    config, exp_av, gain_av, bin_av, night_av = exposure_setup
    # Set EXPOSURE_MAX to 100s (100000000 us) to trigger line 155
    exp_av[constants.EXPOSURE_MAX] = 100000000
    exp_calc = IndiAllSky_Exposure_Legacy_AutoGain(config, exp_av, gain_av, bin_av, night_av)
    exp_calc.post_init()
    assert exp_calc.auto_gain_exposure_cutoff_low == 90.0


def test_exposure_autogain_priority_db_base_methods(exposure_setup):
    config, exp_av, gain_av, bin_av, night_av = exposure_setup
    base = IndiAllSky_Exposure_AutoGain_ExposurePriority_dB_Base(config, exp_av, gain_av, bin_av, night_av)

    # Base gain2dB and dB2gain raise
    with pytest.raises(Exception, match='Not Implemented'):
        base.gain2dB(10.0)
    with pytest.raises(Exception, match='Not Implemented'):
        base.dB2gain(10.0)

    # Daytime exposure_min
    night_av[constants.NIGHT_NIGHT] = 0
    assert base.exposure_min == 0.0001
    night_av[constants.NIGHT_NIGHT] = 1

    assert base.exposure_max == 30.0
    assert base.gain_min == 100.0
    assert base.gain_max == 400.0

    base.post_init()


def test_exposure_autogain_priority_db_full_paths(exposure_setup):
    config, exp_av, gain_av, bin_av, night_av = exposure_setup
    calc = IndiAllSky_Exposure_AutoGain_ExposurePriority_dB(config, exp_av, gain_av, bin_av, night_av)

    assert calc.gain_min_db == 100.0
    assert calc.gain_max_db == 400.0

    # Daytime exposure_min
    night_av[constants.NIGHT_NIGHT] = 0
    assert calc.exposure_min == 0.0001
    night_av[constants.NIGHT_NIGHT] = 1

    # Delegation of compare_exposure and recalculate_exposure
    adu, avg = calc.compare_exposure(100.0, 1.0, 100.0)
    assert adu == 100.0
    calc.recalculate_exposure(1.0, 100.0, 100.0, 100.0, 90.0, 110.0, 1.0)

    # next_exposure == current_exposure
    e, g, de, dg = calc.adjust_exposure_gain(5.0, 100.0, 5.0)
    assert e == 5.0
    assert g == 100.0
    assert de == 0.0
    assert dg == 0.0

    # increase_exposure: next_exposure <= exposure_max (maintain gain)
    e, g, de, dg = calc.adjust_exposure_gain(10.0, 200.0, 20.0)
    assert e == 20.0
    assert g == 200.0

    # increase_exposure: next_exposure > exposure_max (30.0), gain clamped to max (400.0)
    e, g, de, dg = calc.adjust_exposure_gain(10.0, 395.0, 150.0)
    assert e == 30.0
    assert g == 400.0

    # increase_gain: current_exposure == exposure_max (30.0), next_exposure > current_exposure
    # Case 1: next_gain_dB <= gain_max
    e, g, de, dg = calc.adjust_exposure_gain(30.0, 200.0, 35.0)
    assert e == 30.0
    assert g > 200.0

    # Case 2: next_gain_dB > gain_max -> clamped to max gain and exposure clamped to max
    e, g, de, dg = calc.adjust_exposure_gain(30.0, 395.0, 150.0)
    assert e == 30.0
    assert g == 400.0

    # reduce_exposure: current_gain <= gain_min (100.0), next_exposure < current_exposure
    # Case 1: next_exposure >= exposure_low_cutoff (0.001)
    e, g, de, dg = calc.adjust_exposure_gain(5.0, 100.0, 2.0)
    assert e == 2.0
    assert g == 100.0

    # Case 2: next_exposure < exposure_low_cutoff
    e, g, de, dg = calc.adjust_exposure_gain(0.002, 100.0, 0.0001)
    assert e == 0.001
    assert g == 100.0

    # Case 3: next_exposure < exposure_low_cutoff and next_gain_dB clamped to gain_min
    e, g, de, dg = calc.adjust_exposure_gain(0.002, 100.0, 0.000000001)
    assert e == 0.001
    assert g == 100.0

    # reduce_gain: current_gain > gain_min (200.0 > 100.0), next_exposure < current_exposure
    # Case 1: reduced gain stays >= gain_min
    e, g, de, dg = calc.adjust_exposure_gain(5.0, 300.0, 4.0)
    assert e == 5.0
    assert g < 300.0

    # Case 2: reduced gain drops below gain_min -> clamped to min and reduces exposure
    e, g, de, dg = calc.adjust_exposure_gain(5.0, 105.0, 1e-10)
    assert g == 100.0
    assert e <= 5.0

    # Case 3: reduced gain drops below gain_min and next_exposure clamped to exposure_min
    e, g, de, dg = calc.adjust_exposure_gain(5.0, 105.0, 1e-15)
    assert g == 100.0
    assert e == calc.exposure_min



