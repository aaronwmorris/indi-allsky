from datetime import datetime
from dataclasses import replace
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace

import pytest

from indi_allsky import constants
from indi_allsky.dark_library import COVERAGE_ACCEPTABLE
from indi_allsky.dark_library import COVERAGE_EXACT
from indi_allsky.dark_library import COVERAGE_INCOMPATIBLE
from indi_allsky.dark_library import COVERAGE_MISSING
from indi_allsky.dark_library import COVERAGE_TEMPERATURE
from indi_allsky.dark_library import DarkInventoryFrame
from indi_allsky.dark_library import analyze_dark_plan
from indi_allsky.dark_library import analysis_context
from indi_allsky.dark_library import build_dark_exposures
from indi_allsky.dark_library import build_dark_plan
from indi_allsky.dark_automation import DarkAutomationError
from indi_allsky.dark_automation import _log_error_summary
from indi_allsky.dark_automation import _mark_task_capture_restored
from indi_allsky.dark_automation import activation_changes
from indi_allsky.dark_automation import build_dark_command
from indi_allsky.dark_automation import build_execution_groups
from indi_allsky.dark_automation import capture_controller_available
from indi_allsky.dark_automation import determine_capture_restore_state
from indi_allsky.dark_automation import execution_preview
from indi_allsky.dark_automation import estimate_execution_storage
from indi_allsky.dark_automation import flush_camera_library
from indi_allsky.dark_automation import normalize_execution_request
from indi_allsky.dark_automation import recommended_stacking_method
from indi_allsky.dark_automation import task_public_status
from indi_allsky.dark_automation import temperature_thresholds
from indi_allsky.dark_automation import validate_execution_profiles
from indi_allsky.gain import EXPOSURE_MODE_BASIC
from indi_allsky.gain import EXPOSURE_MODE_DB
from indi_allsky.gain import EXPOSURE_MODE_DB_1_10
from indi_allsky.gain import EXPOSURE_MODE_ISO
from indi_allsky.gain import EXPOSURE_MODE_ISO_1_100
from indi_allsky.gain import EXPOSURE_MODE_LEGACY
from indi_allsky.gain import db_to_gain
from indi_allsky.gain import gain_to_db
from indi_allsky.capture_state import CameraCapabilities
from indi_allsky.capture_state import GAIN_KIND_CONTINUOUS
from indi_allsky.capture_state import GAIN_KIND_DISCRETE
from indi_allsky.capture_state import GAIN_KIND_NONE
from indi_allsky.capture_state import build_effective_capture_state


def _config(exposure_mode=EXPOSURE_MODE_BASIC, exposure_max=30.0):
    return {
        'CAMERA_INTERFACE': 'indi',
        'CCD_BIT_DEPTH': 0,
        'CCD_EXPOSURE_MAX': exposure_max,
        'DAYTIME_CAPTURE': True,
        'CCD_CONFIG': {
            'EXPOSURE_CLASSNAME': exposure_mode,
            'AUTO_GAIN_LEVELS': 8,
            'NIGHT': {'GAIN': 300, 'BINNING': 1},
            'MOONMODE': {'GAIN': 200, 'BINNING': 2},
            'DAY': {'GAIN': 0, 'BINNING': 1},
        },
        'CAMERA_SQM': {
            'ENABLE': False,
            'ENABLE_DAY': False,
            'GAIN': 100,
            'BINNING': 1,
        },
    }


def _capabilities(gain_min=0, gain_max=300, gain_step=1, gain_values=()):
    return CameraCapabilities(
        gain_min=gain_min,
        gain_max=gain_max,
        gain_step=gain_step,
        gain_format='%0.0f',
        gain_values=tuple(gain_values),
        gain_values_known=True,
        binning_min=1,
        binning_max=4,
        exposure_min=0.0001,
        exposure_max=60,
        width=3840,
        height=2160,
        bit_depth=16,
    )


def _inventory_pair(target, gain=None, exposure=None, temperature=20.0, active=True, exists=True):
    frames = []
    for frame_id, frame_type in enumerate(('dark', 'bpm'), start=1):
        frames.append(
            DarkInventoryFrame(
                frame_type=frame_type,
                frame_id=frame_id,
                camera_id=target.camera_id,
                active=active,
                exists=exists,
                bit_depth=target.bit_depth,
                exposure=target.exposure if exposure is None else exposure,
                gain=target.gain if gain is None else gain,
                binning=target.binning,
                temperature=temperature,
                width=target.width,
                height=target.height,
                create_date=datetime(2026, 8, 18, 12, 0, 0),
            )
        )
    return frames


@pytest.mark.parametrize(
    'exposure_mode,gain',
    (
        (EXPOSURE_MODE_DB_1_10, 237.0),
        (EXPOSURE_MODE_DB, 23.7),
        (EXPOSURE_MODE_ISO, 1534.0),
        (EXPOSURE_MODE_ISO_1_100, 15.34),
    ),
)
def test_gain_db_mappings_round_trip(exposure_mode, gain):
    assert db_to_gain(exposure_mode, gain_to_db(exposure_mode, gain)) == pytest.approx(gain)


def test_camera_capabilities_round_trip_ccd_info_and_database_snapshot():
    ccd_info = {
        'GAIN_INFO': {'min': 0, 'max': 300, 'step': 1, 'format': '%0.0f', 'values': [0, 100, 200, 300]},
        'BINNING_INFO': {'min': 1, 'max': 4},
        'CCD_EXPOSURE': {'CCD_EXPOSURE_VALUE': {'min': 0.0001, 'max': 60}},
        'CCD_FRAME': {'WIDTH': {'max': 3840}, 'HEIGHT': {'max': 2160}},
        'CCD_INFO': {'CCD_BITSPERPIXEL': {'current': 16}},
    }

    capabilities = CameraCapabilities.from_ccd_info(ccd_info)
    camera = SimpleNamespace(
        data={'camera_capabilities': capabilities.to_dict()},
        minGain=None,
        maxGain=None,
        minBinning=None,
        maxBinning=None,
        minExposure=None,
        maxExposure=None,
        width=None,
        height=None,
        bits=None,
    )

    assert CameraCapabilities.from_camera(camera) == capabilities


def test_basic_state_uses_configured_profiles_and_camera_limits():
    config = _config()
    config['CCD_CONFIG']['NIGHT']['GAIN'] = 350
    config['CCD_CONFIG']['MOONMODE']['BINNING'] = 9
    config['CAMERA_SQM']['ENABLE'] = True

    state = build_effective_capture_state(config, _capabilities())
    profiles = {profile.name: profile for profile in state.profiles}

    assert state.exposure_mode == EXPOSURE_MODE_BASIC
    assert profiles['night'].gain_values == (300.0,)
    assert profiles['moon'].binning == 4
    assert profiles['day'].gain_values == (0.0,)
    assert profiles['sqm_night'].gain_values == (100.0,)
    assert len(state.warnings) == 2


def test_libcamera_profiles_preserve_day_night_bit_depth_and_cooling_targets():
    config = _config()
    config['CAMERA_INTERFACE'] = 'libcamera_imx477'
    config['LIBCAMERA'] = {
        'IMAGE_FILE_TYPE': 'dng',
        'IMAGE_FILE_TYPE_DAY': 'jpg',
    }
    config['CCD_COOLING'] = True
    config['CCD_TEMP'] = 15
    config['CCD_COOLING_DAY'] = True
    config['CCD_TEMP_DAY'] = 35
    config['CAMERA_SQM']['ENABLE'] = True
    config['CAMERA_SQM']['ENABLE_DAY'] = True

    state = build_effective_capture_state(config, _capabilities())
    profiles = {profile.name: profile for profile in state.profiles}

    assert profiles['night'].bit_depth == 16
    assert profiles['night'].temperature == 15
    assert profiles['day'].bit_depth == 8
    assert profiles['day'].temperature == 35
    assert profiles['sqm_night'].bit_depth == 16
    assert profiles['sqm_night'].temperature == 15
    assert profiles['sqm_day'].bit_depth == 8
    assert profiles['sqm_day'].temperature == 35


def test_libcamera_white_balance_omits_day_profiles_and_blocks_night_capture():
    config = _config()
    config['CAMERA_INTERFACE'] = 'libcamera_imx477'
    config['LIBCAMERA'] = {
        'IMAGE_FILE_TYPE': 'jpg',
        'IMAGE_FILE_TYPE_DAY': 'jpg',
        'AWB_ENABLE': True,
        'AWB_ENABLE_DAY': True,
    }
    config['CAMERA_SQM']['ENABLE_DAY'] = True

    state = build_effective_capture_state(config, _capabilities())

    assert all(profile.name not in ('day', 'sqm_day') for profile in state.profiles)
    assert any('Day darks were omitted' in warning for warning in state.warnings)
    assert any('Night dark capture requires' in warning for warning in state.warnings)
    groups = [{'capture_period': 'night'}]
    assert recommended_stacking_method(config, groups) == 'average'
    with pytest.raises(DarkAutomationError, match='nighttime white balance'):
        validate_execution_profiles(config, {'groups': groups, 'method': 'average'})


def test_libcamera_rgb_requires_average_but_raw_dng_allows_either_method():
    config = _config()
    config['CAMERA_INTERFACE'] = 'libcamera_imx477'
    config['LIBCAMERA'] = {
        'IMAGE_FILE_TYPE': 'dng',
        'IMAGE_FILE_TYPE_DAY': 'jpg',
    }

    night_groups = [{'capture_period': 'night'}]
    mixed_groups = [{'capture_period': 'night'}, {'capture_period': 'day'}]
    assert recommended_stacking_method(config, night_groups) == 'sigmaclip'
    assert recommended_stacking_method(config, mixed_groups) == 'average'
    validate_execution_profiles(config, {'groups': night_groups, 'method': 'average'})
    with pytest.raises(DarkAutomationError, match='Average stacking'):
        validate_execution_profiles(config, {'groups': mixed_groups, 'method': 'sigmaclip'})


@pytest.mark.parametrize('camera_interface', ('test_bubbles', 'test_rotating_stars'))
def test_rgb_test_cameras_require_average_stacking(camera_interface):
    config = _config()
    config['CAMERA_INTERFACE'] = camera_interface
    groups = [{'capture_period': 'night'}]

    assert recommended_stacking_method(config, groups) == 'average'
    validate_execution_profiles(config, {'groups': groups, 'method': 'average'})
    with pytest.raises(DarkAutomationError, match='RGB test-camera frames'):
        validate_execution_profiles(config, {'groups': groups, 'method': 'sigmaclip'})


def test_legacy_state_matches_capture_gain_levels():
    state = build_effective_capture_state(_config(EXPOSURE_MODE_LEGACY), _capabilities())

    assert all(profile.gain_kind == GAIN_KIND_DISCRETE for profile in state.profiles)
    assert state.profiles[0].gain_values == (
        0.0,
        43.0,
        86.0,
        129.0,
        171.0,
        214.0,
        257.0,
        300.0,
    )
    assert any('Legacy auto-gain levels were adjusted' in warning for warning in state.warnings)


@pytest.mark.parametrize(
    'exposure_mode,gain_min,gain_max,gain_step',
    (
        (EXPOSURE_MODE_BASIC, 0.0, 300.0, 1.0),
        (EXPOSURE_MODE_LEGACY, 0.0, 300.0, 1.0),
        (EXPOSURE_MODE_DB_1_10, 0.0, 300.0, 1.0),
        (EXPOSURE_MODE_DB, 0.0, 30.0, 0.1),
        (EXPOSURE_MODE_ISO, 100.0, 3200.0, 1.0),
        (EXPOSURE_MODE_ISO_1_100, 1.0, 32.0, 0.01),
    ),
)
def test_generated_default_plan_is_immediately_executable(
        exposure_mode,
        gain_min,
        gain_max,
        gain_step,
):
    config = _config(exposure_mode, exposure_max=1)
    config['CCD_CONFIG']['DAY']['GAIN'] = gain_min
    config['CCD_CONFIG']['MOONMODE']['GAIN'] = gain_max
    config['CCD_CONFIG']['NIGHT']['GAIN'] = gain_max
    capabilities = _capabilities(
        gain_min=gain_min,
        gain_max=gain_max,
        gain_step=gain_step,
    )
    state = build_effective_capture_state(config, capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=1)
    analysis = analyze_dark_plan(plan, (), temperature=20)
    preview = execution_preview(analysis, 'refresh', frame_count=3)

    execution = normalize_execution_request(
        analysis,
        capabilities,
        state,
        {
            'strategy': 'refresh',
            'method': 'average',
            'frame_count': 3,
            'config_signature': plan.config_signature,
            'groups': preview['groups'],
        },
    )

    assert execution['target_count'] == len(plan.targets)
    assert execution['target_count'] > 0


def test_generated_default_plans_cover_camera_capability_variants():
    discrete_config = _config(EXPOSURE_MODE_ISO, exposure_max=1)
    discrete_config['CCD_CONFIG']['DAY']['GAIN'] = 100
    discrete_config['CCD_CONFIG']['MOONMODE']['GAIN'] = 400
    discrete_config['CCD_CONFIG']['NIGHT']['GAIN'] = 800
    discrete_capabilities = _capabilities(
        gain_min=100,
        gain_max=800,
        gain_step=None,
        gain_values=(100, 200, 400, 800),
    )

    sqm_config = _config(EXPOSURE_MODE_BASIC, exposure_max=1)
    sqm_config['CAMERA_SQM']['ENABLE'] = True
    sqm_config['CAMERA_SQM']['ENABLE_DAY'] = True

    reversed_config = _config(EXPOSURE_MODE_DB_1_10, exposure_max=1)
    reversed_config['CCD_CONFIG']['DAY']['GAIN'] = 250
    reversed_config['CCD_CONFIG']['NIGHT']['GAIN'] = 50

    unknown_mode_config = _config(exposure_max=1)
    unknown_mode_config['CCD_CONFIG']['EXPOSURE_CLASSNAME'] = 'unknown_mode'

    cases = (
        (discrete_config, discrete_capabilities),
        (
            _config(EXPOSURE_MODE_DB_1_10, exposure_max=1),
            _capabilities(gain_min=-1, gain_max=-1, gain_step=1),
        ),
        (_config(EXPOSURE_MODE_BASIC, exposure_max=1), CameraCapabilities()),
        (
            _config(EXPOSURE_MODE_DB_1_10, exposure_max=1),
            _capabilities(gain_step=25),
        ),
        (
            _config(EXPOSURE_MODE_BASIC, exposure_max=1),
            replace(_capabilities(gain_step=10), binning_min=2, binning_max=2),
        ),
        (sqm_config, _capabilities(gain_step=10)),
        (reversed_config, _capabilities(gain_step=10)),
        (unknown_mode_config, _capabilities(gain_step=10)),
    )

    for config, capabilities in cases:
        state = build_effective_capture_state(config, capabilities)
        plan = build_dark_plan(state, capabilities, camera_id=1)
        analysis = analyze_dark_plan(plan, (), temperature=20)
        preview = execution_preview(analysis, 'refresh', frame_count=3)
        execution = normalize_execution_request(
            analysis,
            capabilities,
            state,
            {
                'strategy': 'refresh',
                'method': 'average',
                'frame_count': 3,
                'config_signature': plan.config_signature,
                'groups': preview['groups'],
            },
        )

        assert execution['target_count'] == len(plan.targets)
        assert execution['target_count'] > 0


def test_plan_omits_exposures_outside_the_camera_whole_second_range():
    capabilities = _capabilities()
    capabilities = CameraCapabilities(
        **{
            **capabilities.__dict__,
            'exposure_min': 6,
            'exposure_max': 12,
        }
    )
    state = build_effective_capture_state(_config(exposure_max=30), capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=1)

    assert plan.exposures == (7.0, 12.0)
    assert all(target.exposure in plan.exposures for target in plan.targets)
    assert any('outside the camera range' in warning for warning in plan.warnings)


def test_plan_is_unavailable_when_camera_has_no_supported_whole_second_exposure():
    capabilities = _capabilities()
    capabilities = CameraCapabilities(
        **{
            **capabilities.__dict__,
            'exposure_max': 0.5,
        }
    )
    state = build_effective_capture_state(_config(exposure_max=30), capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=1)
    analysis = analyze_dark_plan(plan, (), temperature=20)

    assert plan.exposures == ()
    assert plan.targets == ()
    assert not analysis_context(state, capabilities, analysis)['available']
    assert any('whole-second dark exposure' in warning for warning in plan.warnings)


def test_zwo_balanced_plan_uses_three_db_gain_steps():
    capabilities = _capabilities()
    state = build_effective_capture_state(_config(EXPOSURE_MODE_DB_1_10), capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=7)
    analysis = analyze_dark_plan(plan, (), temperature=20)

    assert state.profiles[0].gain_kind == GAIN_KIND_CONTINUOUS
    assert analysis_context(state, capabilities, analysis)['continuous_gain'] is True
    assert sorted(set(target.gain for target in plan.targets)) == [
        0.0,
        30.0,
        60.0,
        90.0,
        120.0,
        150.0,
        180.0,
        210.0,
        240.0,
        270.0,
        300.0,
    ]
    assert plan.exposures == (1.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0)
    assert len(plan.targets) == 11 * 7 * 2  # two distinct configured binnings


@pytest.mark.parametrize(
    'exposure_mode,gain_min,gain_max',
    (
        (EXPOSURE_MODE_DB_1_10, 0.0, 300.0),
        (EXPOSURE_MODE_DB, 0.0, 30.0),
        (EXPOSURE_MODE_ISO, 100.0, 3162.2776601683795),
        (EXPOSURE_MODE_ISO_1_100, 1.0, 31.622776601683793),
    ),
)
def test_all_continuous_auto_gain_modes_build_meaningful_ladders(exposure_mode, gain_min, gain_max):
    config = _config(exposure_mode, exposure_max=1)
    config['CCD_CONFIG']['DAY']['GAIN'] = gain_min
    config['CCD_CONFIG']['NIGHT']['GAIN'] = gain_max
    capabilities = _capabilities(gain_min=gain_min, gain_max=gain_max, gain_step=None)

    state = build_effective_capture_state(config, capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=1)
    gains = sorted(set(target.gain for target in plan.targets))
    effective_gain_max = math.floor(gain_max * 1000) / 1000

    assert len(gains) >= 11
    assert gains[0] == pytest.approx(gain_min)
    assert gains[-1] == pytest.approx(effective_gain_max)
    assert all(
        gain_to_db(exposure_mode, next_gain) - gain_to_db(exposure_mode, gain) <= 3.001
        for gain, next_gain in zip(gains, gains[1:])
    )


def test_discrete_camera_values_are_used_instead_of_interpolated_gains():
    config = _config(EXPOSURE_MODE_ISO, exposure_max=1)
    config['CCD_CONFIG']['DAY']['GAIN'] = 100
    config['CCD_CONFIG']['NIGHT']['GAIN'] = 800
    capabilities = _capabilities(
        gain_min=100,
        gain_max=800,
        gain_step=None,
        gain_values=(100, 200, 400, 800),
    )

    state = build_effective_capture_state(config, capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=1)
    analysis = analyze_dark_plan(plan, (), temperature=20)

    assert all(profile.gain_kind == GAIN_KIND_DISCRETE for profile in state.profiles)
    assert analysis_context(state, capabilities, analysis)['continuous_gain'] is False
    assert sorted(set(target.gain for target in plan.targets)) == [100.0, 200.0, 400.0, 800.0]


def test_camera_without_gain_control_uses_one_gain_state_per_binning():
    capabilities = _capabilities(gain_min=-1, gain_max=-1, gain_step=1)
    state = build_effective_capture_state(_config(EXPOSURE_MODE_DB_1_10, exposure_max=1), capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=1)

    assert all(profile.gain_kind == GAIN_KIND_NONE for profile in state.profiles)
    assert set(target.gain for target in plan.targets) == {-1.0}
    assert len(plan.targets) == 2


def test_fixed_gain_profiles_snap_to_the_reported_camera_step():
    config = _config(EXPOSURE_MODE_BASIC, exposure_max=1)
    config['CCD_CONFIG']['MOONMODE']['GAIN'] = 75
    capabilities = _capabilities(gain_step=10)

    state = build_effective_capture_state(config, capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=1)
    analysis = analyze_dark_plan(plan, (), temperature=20)
    preview = execution_preview(analysis, 'refresh', frame_count=3)
    execution = normalize_execution_request(
        analysis,
        capabilities,
        state,
        {
            'strategy': 'refresh',
            'method': 'average',
            'frame_count': 3,
            'config_signature': plan.config_signature,
            'groups': preview['groups'],
        },
    )

    moon_profile = next(profile for profile in state.profiles if profile.name == 'moon')
    assert moon_profile.gain_values == (80.0,)
    assert any('Moon gain was adjusted' in warning for warning in state.warnings)
    assert any(80.0 in group['gains'] for group in execution['groups'])


def test_exact_pair_is_covered_but_missing_bpm_requires_capture():
    config = _config(EXPOSURE_MODE_BASIC, exposure_max=1)
    config['DAYTIME_CAPTURE'] = False
    config['CCD_CONFIG']['NIGHT'] = {'GAIN': 100, 'BINNING': 1}
    config['CCD_CONFIG']['MOONMODE'] = {'GAIN': 100, 'BINNING': 1}
    state = build_effective_capture_state(config, _capabilities())
    plan = build_dark_plan(state, _capabilities(), camera_id=5)
    target = plan.targets[0]

    exact_analysis = analyze_dark_plan(plan, _inventory_pair(target), temperature=20)
    missing_bpm_analysis = analyze_dark_plan(plan, _inventory_pair(target)[:1], temperature=20)

    assert exact_analysis.target_coverages[0].status == COVERAGE_EXACT
    assert exact_analysis.suggested_action == 'none'
    assert missing_bpm_analysis.target_coverages[0].status == COVERAGE_MISSING
    assert missing_bpm_analysis.suggested_action == 'rebuild'


def test_temperature_direction_matches_runtime_selection():
    config = _config(EXPOSURE_MODE_BASIC, exposure_max=1)
    config['DAYTIME_CAPTURE'] = False
    config['CCD_CONFIG']['NIGHT'] = {'GAIN': 100, 'BINNING': 1}
    config['CCD_CONFIG']['MOONMODE'] = {'GAIN': 100, 'BINNING': 1}
    state = build_effective_capture_state(config, _capabilities())
    plan = build_dark_plan(state, _capabilities(), camera_id=5)
    target = plan.targets[0]

    analysis = analyze_dark_plan(plan, _inventory_pair(target, temperature=18), temperature=20)

    assert analysis.target_coverages[0].status == COVERAGE_TEMPERATURE


def test_configured_cooling_target_takes_priority_over_latest_image_temperature():
    config = _config(EXPOSURE_MODE_BASIC, exposure_max=1)
    config['DAYTIME_CAPTURE'] = False
    config['CCD_COOLING'] = True
    config['CCD_TEMP'] = 15
    config['CCD_CONFIG']['NIGHT'] = {'GAIN': 100, 'BINNING': 1}
    config['CCD_CONFIG']['MOONMODE'] = {'GAIN': 100, 'BINNING': 1}
    state = build_effective_capture_state(config, _capabilities())
    plan = build_dark_plan(state, _capabilities(), camera_id=5)
    target = plan.targets[0]

    analysis = analyze_dark_plan(plan, _inventory_pair(target, temperature=15), temperature=30)

    assert analysis.target_coverages[0].status == COVERAGE_EXACT


def test_partial_continuous_library_is_used_when_filling_gain_gaps():
    config = _config(EXPOSURE_MODE_DB_1_10, exposure_max=1)
    config['CCD_CONFIG']['MOONMODE']['BINNING'] = 1
    state = build_effective_capture_state(config, _capabilities())
    plan = build_dark_plan(state, _capabilities(), camera_id=5)
    template_target = plan.targets[0]
    inventory = _inventory_pair(template_target, gain=200, temperature=20)

    analysis = analyze_dark_plan(plan, inventory, temperature=20)
    suggested_gains = sorted(set(target.gain for target in analysis.suggested_targets))

    assert any(coverage.status == COVERAGE_ACCEPTABLE for coverage in analysis.target_coverages)
    assert analysis.suggested_action == 'complete'
    assert 200.0 not in suggested_gains
    assert suggested_gains == [0.0, 30.0, 60.0, 90.0, 120.0, 150.0, 180.0, 230.0, 260.0, 290.0, 300.0]


def test_dark_exposure_schedule_preserves_existing_script_behaviour():
    assert build_dark_exposures(31, 5) == (1.0, 6.0, 11.0, 16.0, 21.0, 26.0, 31.0)
    assert build_dark_exposures(0.5, 5) == (1.0,)

    with pytest.raises(ValueError, match='greater than zero'):
        build_dark_exposures(30, 0)


def test_targets_retain_the_camera_configuration_profile_used_for_capture():
    state = build_effective_capture_state(_config(), _capabilities())
    plan = build_dark_plan(state, _capabilities(), camera_id=1)

    profile_names = {target.capture_profile for target in plan.targets}

    assert profile_names == {'day', 'moon', 'night'}


def test_execution_groups_preserve_irregular_completion_cells():
    config = _config(EXPOSURE_MODE_DB_1_10, exposure_max=5)
    config['CCD_CONFIG']['MOONMODE']['BINNING'] = 1
    state = build_effective_capture_state(config, _capabilities())
    plan = build_dark_plan(state, _capabilities(), camera_id=1)
    targets = {
        (target.gain, target.exposure): target
        for target in plan.targets
        if target.capture_profile == 'night'
    }
    selected = (
        targets[(0.0, 1.0)],
        targets[(0.0, 5.0)],
        targets[(30.0, 1.0)],
    )
    analysis = SimpleNamespace(completion_targets=selected, plan=plan)

    groups = build_execution_groups(analysis, 'complete')

    assert sum(group['target_count'] for group in groups) == 3
    assert sorted((group['gains'], group['exposures']) for group in groups) == [
        ([0.0], [1.0, 5.0]),
        ([30.0], [1.0]),
    ]


def test_adjusted_execution_plan_is_validated_and_counted():
    config = _config(EXPOSURE_MODE_DB_1_10, exposure_max=5)
    config['CCD_CONFIG']['MOONMODE']['BINNING'] = 1
    capabilities = _capabilities()
    state = build_effective_capture_state(config, capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=1)
    analysis = analyze_dark_plan(plan, (), temperature=20)
    preview = execution_preview(analysis, 'refresh')
    source_group = preview['groups'][0]
    request_data = {
        'strategy': 'refresh',
        'method': 'sigmaclip',
        'frame_count': 12,
        'temperature_source': 'sensor_user_10',
        'config_signature': plan.config_signature,
        'groups': [{
            'id': source_group['id'],
            'enabled': True,
            'gains': [0, 100, 300],
            'exposures': [1, 5],
        }],
    }

    execution = normalize_execution_request(
        analysis,
        capabilities,
        state,
        request_data,
    )

    assert execution['target_count'] == 6
    assert execution['frame_count'] == 12
    assert execution['temperature_source'] == 'sensor_user_10'
    assert execution['groups'][0]['gains'] == [0.0, 100.0, 300.0]
    assert len(execution['plan_signature']) == 64


def test_manual_binning_and_bitmax_overrides_are_validated_and_normalised():
    config = _config(EXPOSURE_MODE_BASIC, exposure_max=1)
    capabilities = _capabilities()
    state = build_effective_capture_state(config, capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=1)
    analysis = analyze_dark_plan(plan, (), temperature=20)
    source_group = execution_preview(analysis, 'custom')['groups'][0]

    execution = normalize_execution_request(
        analysis,
        capabilities,
        state,
        {
            'strategy': 'custom',
            'method': 'average',
            'frame_count': 3,
            'config_signature': plan.config_signature,
            'groups': [{
                'id': source_group['id'],
                'enabled': True,
                'binning': 3,
                'bitmax': 12,
                'gains': source_group['gains'],
                'exposures': source_group['exposures'],
            }],
        },
    )

    group = execution['groups'][0]
    assert group['binning'] == 3
    assert group['bitmax'] == 12
    assert group['width'] == 1280
    assert group['height'] == 720

    with pytest.raises(DarkAutomationError, match='binning.*maximum'):
        normalize_execution_request(
            analysis,
            capabilities,
            state,
            {
                'strategy': 'custom',
                'method': 'average',
                'frame_count': 3,
                'config_signature': plan.config_signature,
                'groups': [{**source_group, 'binning': 5}],
            },
        )

    with pytest.raises(DarkAutomationError, match='0, 8, 10, 12, 14, or 16'):
        normalize_execution_request(
            analysis,
            capabilities,
            state,
            {
                'strategy': 'custom',
                'method': 'average',
                'frame_count': 3,
                'config_signature': plan.config_signature,
                'groups': [{**source_group, 'bitmax': 33}],
            },
        )


def test_temperature_series_uses_complete_night_plan_and_per_set_estimates():
    config = _config(EXPOSURE_MODE_BASIC, exposure_max=1)
    capabilities = _capabilities()
    state = build_effective_capture_state(config, capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=1)
    analysis = SimpleNamespace(completion_targets=(), plan=plan)

    preview = execution_preview(
        analysis,
        'complete',
        capture_mode='temperature_series',
        temperature_delta=2.5,
    )

    assert preview['strategy'] == 'custom'
    assert preview['capture_mode'] == 'temperature_series'
    assert preview['temperature_delta'] == 2.5
    assert preview['estimate_scope'] == 'per_temperature_set'
    assert preview['groups']
    assert all(group['capture_period'] == 'night' for group in preview['groups'])
    assert all(group['bitmax'] == group['bit_depth'] for group in preview['groups'])
    assert preview['target_count'] == sum(
        1 for target in plan.targets
        if target.capture_profile not in ('day', 'sqm_day')
    )


def test_temperature_target_thresholds_cover_aligned_unaligned_and_already_cold_cases():
    assert temperature_thresholds(20, 0, 5) == (15.0, 10.0, 5.0, 0.0)
    assert temperature_thresholds(20, -2, 5) == (15.0, 10.0, 5.0, 0.0, -2.0)
    assert temperature_thresholds(-5, 0, 5) == ()
    assert temperature_thresholds(20, None, 5) == ()


def test_finite_temperature_series_estimates_the_complete_sweep():
    config = _config(EXPOSURE_MODE_BASIC, exposure_max=1)
    capabilities = _capabilities()
    state = build_effective_capture_state(config, capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=1)
    analysis = SimpleNamespace(completion_targets=(), plan=plan, temperature=20.0)

    per_set = execution_preview(
        analysis,
        'complete',
        capture_mode='temperature_series',
        temperature_delta=5,
    )
    finite = execution_preview(
        analysis,
        'complete',
        capture_mode='temperature_series',
        temperature_delta=5,
        temperature_target=8,
    )

    assert finite['temperature_set_count'] == 4  # immediate, 15°C, 10°C, 8°C
    assert finite['estimate_scope'] == 'complete_task'
    assert finite['estimated_seconds'] == per_set['estimated_seconds'] * 4
    assert finite['estimated_library_bytes'] == per_set['estimated_library_bytes'] * 4


def test_single_capture_ignores_hidden_temperature_series_values():
    config = _config(EXPOSURE_MODE_BASIC, exposure_max=1)
    capabilities = _capabilities()
    state = build_effective_capture_state(config, capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=1)
    analysis = analyze_dark_plan(plan, (), temperature=20)

    preview = execution_preview(
        analysis,
        'complete',
        capture_mode='single',
        temperature_delta='invalid',
        temperature_target=1000,
    )
    execution = normalize_execution_request(
        analysis,
        capabilities,
        state,
        {
            'strategy': 'complete',
            'method': 'average',
            'frame_count': 3,
            'capture_mode': 'single',
            'temperature_delta': 'invalid',
            'temperature_target': 1000,
            'config_signature': plan.config_signature,
        },
    )

    assert preview['temperature_delta'] == 5.0
    assert preview['temperature_target'] is None
    assert execution['temperature_delta'] == 5.0
    assert execution['temperature_target'] is None


def test_adjusted_gain_must_match_camera_step():
    config = _config(EXPOSURE_MODE_DB_1_10, exposure_max=1)
    capabilities = _capabilities(gain_step=5)
    state = build_effective_capture_state(config, capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=1)
    analysis = analyze_dark_plan(plan, (), temperature=20)
    preview = execution_preview(analysis, 'refresh')

    with pytest.raises(DarkAutomationError, match='gain step'):
        normalize_execution_request(
            analysis,
            capabilities,
            state,
            {
                'strategy': 'refresh',
                'method': 'average',
                'frame_count': 10,
                'config_signature': plan.config_signature,
                'groups': [{
                    'id': preview['groups'][0]['id'],
                    'enabled': True,
                    'gains': [3],
                    'exposures': [1],
                }],
            },
        )


def test_supervised_dark_command_uses_only_private_manifest():
    command = build_dark_command(
        '/venv/bin/python',
        Path('/app/darks.py'),
        'sigmaclip',
        Path('/tmp/manifest.json'),
    )

    assert command == [
        '/venv/bin/python',
        str(Path('/app/darks.py')),
        'sigmaclip',
        '--automation-manifest',
        str(Path('/tmp/manifest.json')),
    ]


def test_temperature_series_uses_same_private_command_path():
    command = build_dark_command(
        '/venv/bin/python',
        Path('/app/darks.py'),
        'tempsigmaclip',
        Path('/tmp/manifest.json'),
    )

    assert command == [
        '/venv/bin/python',
        str(Path('/app/darks.py')),
        'tempsigmaclip',
        '--automation-manifest',
        str(Path('/tmp/manifest.json')),
    ]


@pytest.mark.parametrize(
    'status,expected_message',
    (
        ('success', 'Dark library complete; normal capture has resumed.'),
        ('cancelled', 'Dark calibration cancelled; normal capture has resumed.'),
        (
            'review_required',
            'Normal capture has resumed. Review the revised camera plan before retrying.',
        ),
        ('failed', 'Normal capture has resumed after the calibration error.'),
    ),
)
def test_capture_restore_closes_terminal_progress(status, expected_message):
    task = SimpleNamespace(data={
        'action': 'dark_automation',
        'status': status,
        'capture_restored': False,
        'progress': {'phase': 'restoring_capture'},
    })

    _mark_task_capture_restored(task)

    assert task.data['capture_restored'] is True
    assert task.data['progress']['phase'] == status
    assert task.data['progress']['message'] == expected_message
    assert task.data['progress']['heartbeat_utc']


@pytest.mark.parametrize(
    'watchdog,status,now,expected',
    (
        (1000, constants.STATUS_RUNNING, 1001, True),
        ('1000', constants.STATUS_PAUSED, 1599, True),
        (1000, None, 1600, True),
        (1000, constants.STATUS_STOPPING, 1001, False),
        (1000, constants.STATUS_STOPPED, 1001, False),
        (1000, constants.STATUS_RUNNING, 1601, False),
        ('invalid', constants.STATUS_RUNNING, 1001, False),
        (1000, 'invalid', 1001, False),
    ),
)
def test_capture_controller_availability_is_supervisor_independent(
        watchdog,
        status,
        now,
        expected,
):
    assert capture_controller_available(watchdog, status=status, now=now) is expected


@pytest.mark.parametrize(
    'config,status,night,expected',
    (
        ({'CAPTURE_PAUSE': True}, constants.STATUS_RUNNING, True, 'paused'),
        ({}, constants.STATUS_PAUSED, True, 'paused'),
        ({'DAYTIME_CAPTURE': False}, constants.STATUS_RUNNING, False, 'sleeping'),
        ({'DAYTIME_CAPTURE': True}, constants.STATUS_SLEEPING, False, 'sleeping'),
        ({'DAYTIME_CAPTURE': False}, constants.STATUS_RUNNING, True, 'running'),
        ({}, constants.STATUS_STARTING, None, 'controller'),
    ),
)
def test_capture_restore_state_preserves_configured_behavior(config, status, night, expected):
    assert determine_capture_restore_state(config, status=status, night=night) == expected


@pytest.mark.parametrize(
    'restore_state,expected_text',
    (
        ('paused', 'image capture remains paused as configured'),
        ('sleeping', 'image capture remains in daytime sleep'),
        ('controller', 'capture controller and its worker set have been restored'),
    ),
)
def test_capture_restore_message_does_not_claim_paused_capture_resumed(
        restore_state,
        expected_text,
):
    task = SimpleNamespace(data={
        'action': 'dark_automation',
        'status': 'success',
        'capture_restore_state': restore_state,
        'capture_restored': False,
        'progress': {'phase': 'restoring_capture'},
    })

    _mark_task_capture_restored(task)

    assert expected_text in task.data['progress']['message']
    assert 'normal capture has resumed' not in task.data['progress']['message']


def test_public_task_status_combines_child_and_overall_progress():
    task = SimpleNamespace(
        id=42,
        state=SimpleNamespace(value='RUNNING'),
        data={
            'status': 'running',
            'target_count': 8,
            'capture_restored': False,
            'progress': {
                'phase': 'capturing',
                'completed_master_sets': 3,
                'current_gain': 150,
                'current_exposure': 10,
                'current_frame': 7,
                'current_frame_count': 10,
            },
        },
    )

    status = task_public_status(task)

    assert status['task_id'] == 42
    assert status['percent'] == 46.2
    assert status['completed_master_sets'] == 3
    assert status['current_gain'] == 150
    assert status['current_exposure'] == 10
    assert status['current_frame'] == 7


def test_temperature_series_status_exposes_completed_sets_and_next_threshold():
    task = SimpleNamespace(
        id=43,
        state=SimpleNamespace(value='RUNNING'),
        data={
            'status': 'running',
            'capture_mode': 'temperature_series',
            'temperature_delta': 5,
            'target_count': 4,
            'progress': {
                'phase': 'temperature_wait',
                'completed_master_sets': 4,
                'total_master_sets': 4,
                'current_temperature': 12.3,
                'next_temperature': 10.0,
                'completed_temperature_sets': 2,
            },
        },
    )

    status = task_public_status(task)

    assert status['capture_mode'] == 'temperature_series'
    assert status['completed_temperature_sets'] == 2
    assert status['next_temperature'] == 10.0
    assert status['percent'] == 100.0


def test_finite_temperature_series_status_counts_across_temperature_sets():
    task = SimpleNamespace(
        id=44,
        state=SimpleNamespace(value='RUNNING'),
        data={
            'status': 'running',
            'capture_mode': 'temperature_series',
            'temperature_target': 0,
            'temperature_set_count': 5,
            'target_count': 4,
            'progress': {
                'phase': 'capturing',
                'temperature_set': 3,
                'planned_temperature_sets': 5,
                'completed_temperature_sets': 2,
                'completed_master_sets': 1,
                'total_master_sets': 4,
                'target_temperature': 0,
            },
        },
    )

    status = task_public_status(task)

    assert status['target_count'] == 20
    assert status['completed_master_sets'] == 9
    assert status['percent'] == 45.0
    assert status['planned_temperature_sets'] == 5
    assert status['target_temperature'] == 0


def test_temperature_series_restore_message_preserves_completed_sets():
    task = SimpleNamespace(data={
        'action': 'dark_automation',
        'status': 'cancelled',
        'capture_mode': 'temperature_series',
        'capture_restored': False,
        'progress': {'phase': 'restoring_capture'},
    })

    _mark_task_capture_restored(task)

    assert 'completed temperature sets remain active' in task.data['progress']['message']


class _FakeColumn:
    def __eq__(self, _value):
        return True


class _FakeQuery:
    def __init__(self, entries):
        self.entries = entries

    def filter(self, _condition):
        return self

    def all(self):
        return list(self.entries)


class _FakeSession:
    def __init__(self, fail_commit=False):
        self.fail_commit = fail_commit
        self.deleted = []
        self.committed = False
        self.rolled_back = False

    def delete(self, entry):
        self.deleted.append(entry)

    def commit(self):
        if self.fail_commit:
            raise RuntimeError('database commit failed')
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _flush_model(name, entries):
    return type(name, (), {
        'camera_id': _FakeColumn(),
        'query': _FakeQuery(entries),
    })


def test_flush_commits_database_before_deleting_files():
    with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary_dir:
        temporary_path = Path(temporary_dir)
        dark_path = temporary_path.joinpath('dark.fit')
        bpm_path = temporary_path.joinpath('bpm.fit')
        dark_path.write_bytes(b'dark')
        bpm_path.write_bytes(b'bpm')
        dark_entry = SimpleNamespace(getFilesystemPath=lambda: dark_path)
        bpm_entry = SimpleNamespace(getFilesystemPath=lambda: bpm_path)
        dark_model = _flush_model('IndiAllSkyDbDarkFrameTable', [dark_entry])
        bpm_model = _flush_model('IndiAllSkyDbBadPixelMapTable', [bpm_entry])
        session = _FakeSession()

        result = flush_camera_library(
            SimpleNamespace(session=session),
            (dark_model, bpm_model),
            camera_id=1,
        )

        assert session.committed is True
        assert session.deleted == [dark_entry, bpm_entry]
        assert not dark_path.exists()
        assert not bpm_path.exists()
        assert result == {
            'dark_frames': 1,
            'bad_pixel_maps': 1,
            'files': 2,
            'warnings': [],
        }


def test_flush_keeps_files_when_database_commit_fails():
    with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary_dir:
        temporary_path = Path(temporary_dir)
        dark_path = temporary_path.joinpath('dark.fit')
        dark_path.write_bytes(b'dark')
        dark_entry = SimpleNamespace(getFilesystemPath=lambda: dark_path)
        dark_model = _flush_model('IndiAllSkyDbDarkFrameTable', [dark_entry])
        bpm_model = _flush_model('IndiAllSkyDbBadPixelMapTable', [])
        session = _FakeSession(fail_commit=True)

        with pytest.raises(RuntimeError, match='database commit failed'):
            flush_camera_library(
                SimpleNamespace(session=session),
                (dark_model, bpm_model),
                camera_id=1,
            )

        assert session.rolled_back is True
        assert dark_path.read_bytes() == b'dark'
        assert not list(temporary_path.glob('.*.dark-flush-*'))


def _generation_frame(
        generation,
        group_id='group-1',
        active=False,
        gain=100,
        exposure=5,
        binning=1,
        bit_depth=16,
        width=100,
        height=50,
        temperature=20,
):
    return SimpleNamespace(
        active=active,
        gain=float(gain),
        exposure=float(exposure),
        binmode=int(binning),
        bitdepth=bit_depth,
        width=width,
        height=height,
        temp=temperature,
        data={
            'dark_automation': {
                'generation_id': generation,
                'group_id': group_id,
            },
        },
    )


def _activation_group(**overrides):
    group = {
        'id': 'group-1',
        'binning': 1,
        'bit_depth': 16,
        'width': 100,
        'height': 50,
        'temperature': None,
        'gains': [100.0],
        'exposures': [5.0],
        'target_count': 1,
    }
    group.update(overrides)
    return group


@pytest.mark.parametrize('strategy', ('complete', 'custom'))
def test_additive_activation_preserves_every_old_master(strategy):
    new_frame = _generation_frame('new')
    old_frame = _generation_frame('old', active=True)

    activate, deactivate = activation_changes(
        strategy,
        [new_frame],
        [old_frame],
        [_activation_group()],
    )

    assert activate == (new_frame,)
    assert deactivate == ()


def test_refresh_retires_only_equivalent_temperature_generation():
    new_frame = _generation_frame('new', temperature=20)
    equivalent = _generation_frame('old-a', active=True, temperature=22)
    seasonal = _generation_frame('old-b', active=True, temperature=5)
    different_resolution = _generation_frame('old-c', active=True, width=200, temperature=20)

    _activate, deactivate = activation_changes(
        'refresh',
        [new_frame],
        [equivalent, seasonal, different_resolution],
        [_activation_group()],
    )

    assert deactivate == (equivalent,)


def test_rebuild_retires_displayed_scope_but_preserves_unrelated_library():
    new_frame = _generation_frame('new', gain=100, exposure=5, temperature=20)
    same_scope_other_cell = _generation_frame(
        'old-a', active=True, gain=300, exposure=30, temperature=24,
    )
    other_binning = _generation_frame(
        'old-b', active=True, gain=300, exposure=30, binning=2, temperature=20,
    )
    other_temperature = _generation_frame(
        'old-c', active=True, gain=300, exposure=30, temperature=35,
    )

    _activate, deactivate = activation_changes(
        'rebuild',
        [new_frame],
        [same_scope_other_cell, other_binning, other_temperature],
        [_activation_group()],
    )

    assert deactivate == (same_scope_other_cell,)


def test_capability_signature_detects_material_live_camera_change():
    capabilities = _capabilities()
    changed = _capabilities(gain_step=5)

    assert capabilities.signature == CameraCapabilities(**capabilities.__dict__).signature
    assert capabilities.signature != changed.signature


def test_exposure_overrides_are_part_of_the_plan_signature():
    config = _config(exposure_max=30)
    capabilities = _capabilities()
    default_state = build_effective_capture_state(config, capabilities)
    shorter_state = build_effective_capture_state(
        config,
        capabilities,
        exposure_max=10,
        exposure_step=2,
    )

    assert shorter_state.exposure_max == 10
    assert shorter_state.exposure_step == 2
    assert shorter_state.config_signature != default_state.config_signature
    assert build_dark_plan(shorter_state, capabilities, camera_id=1).exposures == (1.0, 2.0, 4.0, 6.0, 8.0, 10.0)


def test_storage_estimate_includes_two_masters_and_temporary_frames():
    storage = estimate_execution_storage(
        [{
            'width': 100,
            'height': 50,
            'bit_depth': 16,
            'gains': [0, 100],
            'exposures': [1, 5],
        }],
        frame_count=10,
    )

    assert storage['library_bytes'] > 100 * 50 * 2 * 2 * 4
    assert storage['peak_bytes'] > storage['library_bytes']


def test_unreported_temperature_can_still_match_uncooled_legacy_library():
    config = _config(EXPOSURE_MODE_BASIC, exposure_max=1)
    config['DAYTIME_CAPTURE'] = False
    config['CCD_CONFIG']['NIGHT'] = {'GAIN': 100, 'BINNING': 1}
    config['CCD_CONFIG']['MOONMODE'] = {'GAIN': 100, 'BINNING': 1}
    state = build_effective_capture_state(config, _capabilities())
    plan = build_dark_plan(state, _capabilities(), camera_id=5)
    target = plan.targets[0]

    analysis = analyze_dark_plan(plan, _inventory_pair(target, temperature=None), temperature=None)

    assert analysis.target_coverages[0].status == COVERAGE_EXACT


def test_missing_and_wrong_resolution_files_are_not_accepted():
    config = _config(EXPOSURE_MODE_BASIC, exposure_max=1)
    config['DAYTIME_CAPTURE'] = False
    config['CCD_CONFIG']['NIGHT'] = {'GAIN': 100, 'BINNING': 1}
    config['CCD_CONFIG']['MOONMODE'] = {'GAIN': 100, 'BINNING': 1}
    state = build_effective_capture_state(config, _capabilities())
    plan = build_dark_plan(state, _capabilities(), camera_id=5)
    target = plan.targets[0]
    missing_files = _inventory_pair(target, exists=False)
    wrong_resolution = _inventory_pair(target)
    wrong_resolution = [
        SimpleNamespace(**{**frame.__dict__, 'width': target.width + 1})
        for frame in wrong_resolution
    ]

    assert analyze_dark_plan(plan, missing_files).target_coverages[0].status == COVERAGE_INCOMPATIBLE
    assert analyze_dark_plan(plan, wrong_resolution).target_coverages[0].status == COVERAGE_INCOMPATIBLE


def test_error_summary_separates_exception_message_from_diagnostic_traceback():
    diagnostic_log = '\n'.join((
        'Traceback (most recent call last):',
        '  File "/home/allsky/indi-allsky/darks.py", line 1, in run',
        'indi_allsky.exceptions.CameraException: Camera server disconnected while changing property CCD_EXPOSURE',
    ))

    assert _log_error_summary(diagnostic_log) == (
        'Camera server disconnected while changing property CCD_EXPOSURE'
    )


def test_error_summary_surfaces_zero_master_validation_failure():
    diagnostic_log = (
        'indi_allsky.dark_validation.InvalidDarkMasterError: '
        'Master dark contains only zero-valued pixels; '
        'the camera returned no usable calibration data.'
    )

    assert _log_error_summary(diagnostic_log) == (
        'Master dark contains only zero-valued pixels; '
        'the camera returned no usable calibration data.'
    )


def test_error_summary_keeps_plain_final_log_line_and_has_a_fallback():
    assert _log_error_summary('setup detail\ncamera process failed') == 'camera process failed'
    assert _log_error_summary('') == 'the camera process returned an error'
