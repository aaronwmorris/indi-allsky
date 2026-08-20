import pytest

from indi_allsky.camera_profiles import TEST_CAMERA_PROFILES
from indi_allsky.camera_profiles import get_test_camera_profile
from indi_allsky.camera_profiles import normalize_test_camera_gain
from indi_allsky.camera_profiles import test_camera_profile_choices as _profile_choices
from indi_allsky.camera_profiles import test_camera_profile_config_defaults as _profile_config_defaults
from indi_allsky.capture_state import CameraCapabilities
from indi_allsky.capture_state import GAIN_KIND_DISCRETE
from indi_allsky.capture_state import GAIN_KIND_NONE
from indi_allsky.capture_state import build_effective_capture_state
from indi_allsky.dark_library import build_dark_plan
from indi_allsky.gain import EXPOSURE_MODE_BASIC
from indi_allsky.gain import EXPOSURE_MODE_DB
from indi_allsky.gain import EXPOSURE_MODE_DB_1_10
from indi_allsky.gain import EXPOSURE_MODE_ISO
from indi_allsky.gain import EXPOSURE_MODE_ISO_1_100
from indi_allsky.gain import EXPOSURE_MODE_LEGACY


def _profile_config(profile):
    defaults = profile.config_defaults()
    return {
        'CAMERA_INTERFACE': 'test_rotating_stars',
        'CCD_CONFIG': {
            'EXPOSURE_CLASSNAME': defaults['exposure_mode'],
            'AUTO_GAIN_LEVELS': defaults['auto_gain_levels'],
            'DAY': {'GAIN': defaults['day_gain'], 'BINNING': 1},
            'MOONMODE': {'GAIN': defaults['moon_gain'], 'BINNING': 1},
            'NIGHT': {'GAIN': defaults['night_gain'], 'BINNING': 1},
        },
        'CAMERA_SQM': {
            'ENABLE': False,
            'ENABLE_DAY': False,
            'GAIN': defaults['sqm_gain'],
            'BINNING': 1,
        },
        'CCD_EXPOSURE_MAX': 1.0,
        'CCD_BIT_DEPTH': defaults['bit_depth'],
        'CCD_COOLING': False,
        'CCD_COOLING_DAY': False,
        'DAYTIME_CAPTURE': True,
    }


def _profile_capabilities(profile):
    return CameraCapabilities(
        gain_min=profile.gain_min,
        gain_max=profile.gain_max,
        gain_step=profile.gain_step,
        gain_format=profile.gain_format,
        gain_values=profile.gain_values,
        gain_values_known=True,
        binning_min=profile.binning_min,
        binning_max=profile.binning_max,
        exposure_min=profile.exposure_min,
        exposure_max=profile.exposure_max,
        width=1920,
        height=1080,
        bit_depth=profile.bit_depth,
    )


@pytest.mark.parametrize(
    'profile_name,exposure_mode',
    (
        ('fixed', EXPOSURE_MODE_BASIC),
        ('legacy_autogain', EXPOSURE_MODE_LEGACY),
        ('zwo_playerone', EXPOSURE_MODE_DB_1_10),
        ('qhy', EXPOSURE_MODE_DB),
        ('touptek', EXPOSURE_MODE_ISO),
        ('libcamera', EXPOSURE_MODE_ISO_1_100),
    ),
)
def test_gain_mode_profiles_build_executable_dark_plans(profile_name, exposure_mode):
    profile = get_test_camera_profile(profile_name)
    capabilities = _profile_capabilities(profile)
    capture_state = build_effective_capture_state(_profile_config(profile), capabilities)
    plan = build_dark_plan(capture_state, capabilities, camera_id=1)

    assert capture_state.exposure_mode == exposure_mode
    assert plan.targets
    assert all(
        target.gain == -1.0
        or profile.gain_min <= target.gain <= profile.gain_max
        for target in plan.targets
    )
    if profile.gain_step:
        assert all(
            target.gain == -1.0
            or abs(
                ((target.gain - profile.gain_min) / profile.gain_step)
                - round((target.gain - profile.gain_min) / profile.gain_step)
            ) <= 0.000001
            for target in plan.targets
        )


def test_discrete_iso_profile_uses_only_enumerated_values():
    profile = get_test_camera_profile('discrete_iso')
    capabilities = _profile_capabilities(profile)
    capture_state = build_effective_capture_state(_profile_config(profile), capabilities)
    plan = build_dark_plan(capture_state, capabilities, camera_id=1)

    assert all(item.gain_kind == GAIN_KIND_DISCRETE for item in capture_state.profiles)
    assert set(target.gain for target in plan.targets) == set(profile.gain_values)


def test_no_gain_profile_produces_one_no_gain_state():
    profile = get_test_camera_profile('no_gain')
    capabilities = _profile_capabilities(profile)
    capture_state = build_effective_capture_state(_profile_config(profile), capabilities)
    plan = build_dark_plan(capture_state, capabilities, camera_id=1)

    assert all(item.gain_kind == GAIN_KIND_NONE for item in capture_state.profiles)
    assert set(target.gain for target in plan.targets) == {-1.0}


def test_profile_choices_and_browser_defaults_cover_every_profile():
    choice_names = {name for name, label in _profile_choices()}
    browser_defaults = _profile_config_defaults()

    assert choice_names == set(TEST_CAMERA_PROFILES)
    assert set(browser_defaults) == set(TEST_CAMERA_PROFILES)
    assert all(label for name, label in _profile_choices())
    assert get_test_camera_profile('unknown') is TEST_CAMERA_PROFILES['legacy']


@pytest.mark.parametrize(
    'profile_name,requested_gain,expected_gain',
    (
        ('touptek', 9999.4, 9999.0),
        ('libcamera', 22.259, 22.26),
        ('qhy', 18.549, 18.5),
        ('discrete_iso', 750.0, 800.0),
        ('no_gain', -1.0, -1.0),
    ),
)
def test_synthetic_camera_gain_is_normalized_like_a_driver(
        profile_name,
        requested_gain,
        expected_gain,
):
    profile = get_test_camera_profile(profile_name)

    assert normalize_test_camera_gain(profile, requested_gain) == expected_gain


def test_synthetic_camera_gain_still_rejects_out_of_range_values():
    profile = get_test_camera_profile('zwo_playerone')

    with pytest.raises(ValueError, match='outside the supported range'):
        normalize_test_camera_gain(profile, 301.0)


def test_synthetic_camera_without_gain_rejects_a_numeric_gain():
    profile = get_test_camera_profile('no_gain')

    with pytest.raises(ValueError, match='does not support gain control'):
        normalize_test_camera_gain(profile, 0.0)
