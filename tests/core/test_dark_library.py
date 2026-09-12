from datetime import datetime
from datetime import timezone
from dataclasses import replace
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace

import pytest

from indi_allsky import constants
from indi_allsky import exposure as exposure_module
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
from indi_allsky.dark_library import camera_temperature_preferences
from indi_allsky.dark_library import frame_matches_plan_profile
from indi_allsky.dark_library import update_camera_temperature_preferences
from indi_allsky.dark_library import validate_temperature_range
from indi_allsky.dark_automation import DarkAutomationError
from indi_allsky.dark_automation import CANCEL_REQUESTED_MESSAGE
from indi_allsky.dark_automation import _log_error_summary
from indi_allsky.dark_automation import _mark_task_capture_restored
from indi_allsky.dark_automation import _overall_progress
from indi_allsky.dark_automation import _protect_cancel_requested_progress
from indi_allsky.dark_automation import _activate_generation
from indi_allsky.dark_automation import activation_changes
from indi_allsky.dark_automation import automation_master_filename
from indi_allsky.dark_automation import build_library_catalog
from indi_allsky.dark_automation import build_library_partner_index
from indi_allsky.dark_automation import build_dark_command
from indi_allsky.dark_automation import build_execution_groups
from indi_allsky.dark_automation import capture_controller_available
from indi_allsky.dark_automation import checkpoint_master_pair
from indi_allsky.dark_automation import cleanup_interrupted_capture_artifacts
from indi_allsky.dark_automation import determine_capture_restore_state
from indi_allsky.dark_automation import execution_preview
from indi_allsky.dark_automation import estimate_execution_storage
from indi_allsky.dark_automation import flush_camera_library
from indi_allsky.dark_automation import flush_library_batches
from indi_allsky.dark_automation import library_selection_batches_signature
from indi_allsky.dark_automation import normalize_execution_request
from indi_allsky.dark_automation import recommended_stacking_method
from indi_allsky.dark_automation import reject_task_for_config_drift
from indi_allsky.dark_automation import select_camera_library_entries
from indi_allsky.dark_automation import select_camera_master_sets
from indi_allsky.dark_automation import task_public_status
from indi_allsky.dark_automation import task_requires_progress
from indi_allsky.dark_automation import temperature_thresholds
from indi_allsky.dark_automation import validate_execution_profiles
from indi_allsky.dark_automation import library_entry_eligibility
from indi_allsky.dark_automation import update_library_entries_eligibility
from indi_allsky.dark_automation import utc_now_naive
from indi_allsky.capture_state import CameraCapabilities
from indi_allsky.capture_state import GAIN_KIND_CONTINUOUS
from indi_allsky.capture_state import GAIN_KIND_DISCRETE
from indi_allsky.capture_state import GAIN_KIND_NONE
from indi_allsky.capture_state import build_effective_capture_state
from indi_allsky.capture_state import camera_geometry_from_ccd_info
from indi_allsky.capture_state import record_binning_dimensions
from indi_allsky.capture_state import validate_captured_geometry


EXPOSURE_MODE_BASIC = 'exposure_basic'
EXPOSURE_MODE_DB = 'exposure_autogain_exp_prio_db'
EXPOSURE_MODE_DB_1_10 = 'exposure_autogain_exp_prio_db_1_10'
EXPOSURE_MODE_ISO = 'exposure_autogain_exp_prio_iso'
EXPOSURE_MODE_ISO_1_100 = 'exposure_autogain_exp_prio_iso_1_100'
EXPOSURE_MODE_LEGACY = 'exposure_legacy_autogain'


def test_utc_now_naive_uses_the_utc_database_clock():
    before = datetime.now(timezone.utc).replace(tzinfo=None)
    result = utc_now_naive()
    after = datetime.now(timezone.utc).replace(tzinfo=None)

    assert result.tzinfo is None
    assert before <= result <= after


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


def _capabilities(
        gain_min=0,
        gain_max=300,
        gain_step=1,
        gain_values=(),
        gain_step_is_quantum=False,
):
    return CameraCapabilities(
        gain_min=gain_min,
        gain_max=gain_max,
        gain_step=gain_step,
        gain_step_is_quantum=gain_step_is_quantum,
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
    'exposure_class,gain',
    (
        (exposure_module.exposure_autogain_exp_prio_db_1_10, 237.0),
        (exposure_module.exposure_autogain_exp_prio_db, 23.7),
        (exposure_module.exposure_autogain_exp_prio_iso, 1534.0),
        (exposure_module.exposure_autogain_exp_prio_iso_1_100, 15.34),
    ),
)
def test_gain_db_mappings_round_trip(exposure_class, gain):
    assert exposure_class.dB2gain(exposure_class.gain2dB(gain)) == pytest.approx(gain)


def test_camera_capabilities_round_trip_ccd_info_and_database_snapshot():
    ccd_info = {
        'GAIN_INFO': {'min': 0, 'max': 300, 'step': 1, 'format': '%0.0f', 'values': [0, 100, 200, 300]},
        'BINNING_INFO': {
            'current': 1,
            'horizontal': 1,
            'vertical': 1,
            'min': 1,
            'max': 4,
        },
        'CCD_EXPOSURE': {'CCD_EXPOSURE_VALUE': {'min': 0.0001, 'max': 60}},
        'CCD_FRAME': {
            'X': {'current': 8},
            'Y': {'current': 4},
            'WIDTH': {'current': 3824, 'max': 3840, 'step': 8},
            'HEIGHT': {'current': 2152, 'max': 2160, 'step': 2},
        },
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
    assert capabilities.capture_width == 3824
    assert capabilities.capture_height == 2152


def test_binned_dimensions_respect_the_camera_roi_alignment():
    capabilities = replace(
        _capabilities(),
        frame_width=3856,
        frame_height=2180,
        frame_width_step=8,
        frame_height_step=2,
    )

    assert capabilities.binned_width(3) == 1280
    assert capabilities.binned_height(3) == 726
    assert capabilities.binned_width(4) == 964
    assert capabilities.binned_height(4) == 545


def test_observed_binned_dimensions_are_reused_for_the_same_source_frame():
    capabilities = replace(
        _capabilities(),
        frame_x=0,
        frame_y=0,
        frame_width=3856,
        frame_height=2180,
    )
    capability_data = record_binning_dimensions(
        capabilities.to_dict(),
        {'x': 0, 'y': 0, 'width': 3856, 'height': 2180},
        4,
        964,
        544,
    )
    learned = CameraCapabilities.from_camera(SimpleNamespace(data={
        'camera_capabilities': capability_data,
    }))

    assert learned.binned_width(4) == 964
    assert learned.binned_height(4) == 544
    stored_without_observation = CameraCapabilities.from_camera(SimpleNamespace(data={
        'camera_capabilities': capabilities.to_dict(),
    }))
    assert learned.signature == stored_without_observation.signature
    assert CameraCapabilities.from_camera(SimpleNamespace(data={
        'camera_capabilities': learned.to_dict(),
    })) == learned

    other_roi = replace(learned, frame_width=3840, frame_height=2176)
    assert other_roi.binned_width(4) == 960
    assert other_roi.binned_height(4) == 544


def test_dark_plan_uses_the_active_camera_frame_instead_of_sensor_maximum():
    capabilities = replace(
        _capabilities(),
        frame_x=8,
        frame_y=4,
        frame_width=3824,
        frame_height=2152,
    )
    state = build_effective_capture_state(_config(), capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=1)

    dimensions_by_binning = {
        target.binning: (target.width, target.height)
        for target in plan.targets
    }
    assert dimensions_by_binning[1] == (3824, 2152)
    assert dimensions_by_binning[2] == (1912, 1076)


def test_camera_geometry_snapshot_and_live_capture_validation():
    ccd_info = {
        'CCD_FRAME': {
            'X': {'current': 0},
            'Y': {'current': 0},
            'WIDTH': {'current': 3840},
            'HEIGHT': {'current': 2176},
        },
        'BINNING_INFO': {'current': 3, 'horizontal': 3, 'vertical': 3},
    }

    assert camera_geometry_from_ccd_info(ccd_info) == {
        'x': 0,
        'y': 0,
        'width': 3840,
        'height': 2176,
        'binning': (3, 3),
    }
    assert validate_captured_geometry(
        1280,
        725,
        3,
        ccd_info['CCD_FRAME'],
        ccd_info['BINNING_INFO'],
    ) == (1280, 725)

    with pytest.raises(RuntimeError, match='horizontal binning'):
        validate_captured_geometry(
            1280,
            725,
            2,
            ccd_info['CCD_FRAME'],
            ccd_info['BINNING_INFO'],
        )
    with pytest.raises(RuntimeError, match='Captured height'):
        validate_captured_geometry(
            1280,
            724,
            3,
            ccd_info['CCD_FRAME'],
            ccd_info['BINNING_INFO'],
        )


def test_incomplete_camera_geometry_is_not_treated_as_restorable():
    assert camera_geometry_from_ccd_info({
        'CCD_FRAME': {
            'WIDTH': {'current': 3840},
            'HEIGHT': {'current': 2160},
        },
        'BINNING_INFO': {'current': 1},
    }) is None


def test_camera_temperature_preferences_use_legacy_fallback_then_persist_override():
    camera = SimpleNamespace(data={'camera_capabilities': {'gain': {'min': 0}}})

    initial = camera_temperature_preferences(camera)

    assert initial == {
        'temperature_range': 5.0,
        'temperature_step': 5.0,
        'range_source': 'legacy_default',
    }

    update_camera_temperature_preferences(camera, 3.5, 2.0)
    saved = camera_temperature_preferences(camera)

    assert saved == {
        'temperature_range': 3.5,
        'temperature_step': 2.0,
        'range_source': 'saved_camera',
    }
    assert camera.data['camera_capabilities'] == {'gain': {'min': 0}}


@pytest.mark.parametrize('value', (None, 'invalid', 0, 50.1, float('nan')))
def test_temperature_matching_distance_rejects_invalid_values(value):
    with pytest.raises(ValueError, match='temperature matching distance'):
        validate_temperature_range(value)


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


def test_legacy_state_matches_capture_gain_levels():
    state = build_effective_capture_state(_config(EXPOSURE_MODE_LEGACY), _capabilities())

    assert all(profile.gain_kind == GAIN_KIND_DISCRETE for profile in state.profiles)
    assert state.profiles[0].gain_values == (
        0.0,
        42.857,
        85.714,
        128.571,
        171.429,
        214.286,
        257.143,
        300.0,
    )
    assert not any('Legacy auto-gain levels were adjusted' in warning for warning in state.warnings)


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


def test_subsecond_only_camera_uses_its_maximum_supported_exposure():
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

    assert plan.exposures == (0.5,)
    assert plan.targets
    assert analysis_context(state, capabilities, analysis)['available']


def test_fractional_configured_max_is_retained_when_rounded_value_is_unsupported():
    capabilities = replace(_capabilities(), exposure_max=30.5)
    state = build_effective_capture_state(
        _config(EXPOSURE_MODE_DB_1_10, exposure_max=30.2),
        capabilities,
    )
    plan = build_dark_plan(state, capabilities, camera_id=1)

    assert plan.exposures[-1] == 30.2
    assert all(target.exposure == 30.2 for target in plan.targets if target.gain > 0)


def test_zwo_balanced_plan_uses_three_db_gain_steps():
    capabilities = _capabilities()
    state = build_effective_capture_state(_config(EXPOSURE_MODE_DB_1_10), capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=7)
    analysis = analyze_dark_plan(plan, (), temperature=20)

    assert state.profiles[0].gain_kind == GAIN_KIND_CONTINUOUS
    context = analysis_context(state, capabilities, analysis)
    assert context['continuous_gain'] is True
    assert 'first lengthens exposure at the lowest configured auto-gain' in context['mode_description']
    assert 'spaced gain ladder at maximum exposure' in context['mode_description']
    assert context['temperature_range'] == 5.0
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
    # At shorter exposures only minimum gain is reachable.  The complete gain
    # ladder is needed only where exposure has already reached its maximum.
    assert len(plan.targets) == 17 * 2  # two distinct configured binnings
    assert sorted(group['target_count'] for group in analysis_context(
        state,
        capabilities,
        analysis,
    )['groups']) == [7, 7, 10, 10]


def test_exposure_priority_plan_matches_reachable_controller_states_and_existing_library():
    config = _config(EXPOSURE_MODE_DB_1_10, exposure_max=30)
    config['CCD_CONFIG']['MOONMODE']['BINNING'] = 1
    capabilities = _capabilities(
        gain_min=0,
        gain_max=600,
        gain_step=60,
    )

    state = build_effective_capture_state(config, capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=7)

    assert capabilities.snap_gain(76) == 76.0
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
    assert len(plan.targets) == 17
    assert all(target.gain == 0.0 for target in plan.targets if target.exposure < 30)
    assert sorted(target.exposure for target in plan.targets if target.gain == 0.0) == [
        1.0,
        5.0,
        10.0,
        15.0,
        20.0,
        25.0,
        30.0,
    ]

    template = plan.targets[0]
    inventory = []
    for gain in (0, 10, 100, 220):
        for exposure in (1, 5, 10, 15, 20):
            inventory.extend(
                _inventory_pair(
                    template,
                    gain=gain,
                    exposure=exposure,
                    temperature=42,
                )
            )

    analysis = analyze_dark_plan(plan, inventory, temperature=38)
    preview = execution_preview(analysis, 'complete')
    execution = normalize_execution_request(
        analysis,
        capabilities,
        state,
        {
            'strategy': 'complete',
            'method': 'average',
            'frame_count': 10,
            'config_signature': plan.config_signature,
            'groups': preview['groups'],
        },
    )

    assert analysis.counts[COVERAGE_EXACT] == 5
    assert len(analysis.completion_targets) == 12
    assert preview['target_count'] == 12
    assert execution['target_count'] == 12


def test_advertised_gain_step_is_advisory_for_advanced_overrides():
    config = _config(EXPOSURE_MODE_DB_1_10, exposure_max=30)
    config['CCD_CONFIG']['MOONMODE']['BINNING'] = 1
    capabilities = _capabilities(gain_max=600, gain_step=60)
    state = build_effective_capture_state(config, capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=1)
    analysis = analyze_dark_plan(plan, (), temperature=20)
    source_group = next(
        group for group in execution_preview(analysis, 'refresh')['groups']
        if group['exposures'] == [30.0] and 30.0 in group['gains']
    )

    execution = normalize_execution_request(
        analysis,
        capabilities,
        state,
        {
            'strategy': 'refresh',
            'method': 'average',
            'frame_count': 3,
            'config_signature': plan.config_signature,
            'groups': [{
                'id': source_group['id'],
                'enabled': True,
                'gains': [76, 219],
                'exposures': [30],
            }],
        },
    )

    assert execution['groups'][0]['gains'] == [76.0, 219.0]
    assert execution['target_count'] == 2


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
    exposure_class = getattr(exposure_module, exposure_mode)

    assert len(gains) >= 11
    assert gains[0] == pytest.approx(gain_min)
    assert gains[-1] == pytest.approx(effective_gain_max)
    assert all(
        exposure_class.gain2dB(next_gain) - exposure_class.gain2dB(gain) <= 3.001
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
    context = analysis_context(state, capabilities, analysis)
    assert context['continuous_gain'] is False
    assert 'camera\'s reported discrete gain values' in context['mode_description']
    assert sorted(set(target.gain for target in plan.targets)) == [100.0, 200.0, 400.0, 800.0]


@pytest.mark.parametrize(
    'exposure_mode,gain_values',
    (
        (EXPOSURE_MODE_LEGACY, None),
        (EXPOSURE_MODE_ISO, (100, 200, 400, 800)),
    ),
)
def test_discrete_auto_gain_modes_only_expand_gain_at_maximum_exposure(
        exposure_mode,
        gain_values,
):
    config = _config(exposure_mode, exposure_max=5)
    config['CCD_CONFIG']['MOONMODE']['BINNING'] = 1
    if gain_values:
        config['CCD_CONFIG']['DAY']['GAIN'] = 100
        config['CCD_CONFIG']['NIGHT']['GAIN'] = 800
        capabilities = _capabilities(
            gain_min=100,
            gain_max=800,
            gain_step=None,
            gain_values=gain_values,
        )
    else:
        capabilities = _capabilities()

    state = build_effective_capture_state(config, capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=1)

    minimum_gain = min(target.gain for target in plan.targets)
    assert all(target.gain == minimum_gain for target in plan.targets if target.exposure < 5)
    assert sorted(set(target.gain for target in plan.targets if target.exposure == 5)) == sorted(
        set(state.profiles[0].gain_values)
    )
    description = analysis_context(
        state,
        capabilities,
        analyze_dark_plan(plan, (), temperature=20),
    )['mode_description']
    if exposure_mode == EXPOSURE_MODE_LEGACY:
        assert 'configured legacy auto-gain levels' in description
    else:
        assert 'reported discrete gain values' in description


def test_camera_without_gain_control_uses_one_gain_state_per_binning():
    capabilities = _capabilities(gain_min=-1, gain_max=-1, gain_step=1)
    state = build_effective_capture_state(_config(EXPOSURE_MODE_DB_1_10, exposure_max=1), capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=1)
    analysis = analyze_dark_plan(plan, (), temperature=20)

    assert all(profile.gain_kind == GAIN_KIND_NONE for profile in state.profiles)
    assert set(target.gain for target in plan.targets) == {-1.0}
    assert len(plan.targets) == 2
    assert 'does not expose gain control' in analysis_context(
        state,
        capabilities,
        analysis,
    )['mode_description']


def test_fixed_gain_strategy_description_explains_profile_deduplication():
    capabilities = _capabilities()
    state = build_effective_capture_state(_config(EXPOSURE_MODE_BASIC, exposure_max=5), capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=1)
    analysis = analyze_dark_plan(plan, (), temperature=20)

    description = analysis_context(state, capabilities, analysis)['mode_description']

    assert 'configured day, night and moon gains' in description
    assert 'shared by several profiles only once' in description


def test_fixed_gain_profiles_snap_to_an_explicit_camera_gain_quantum():
    config = _config(EXPOSURE_MODE_BASIC, exposure_max=1)
    config['CCD_CONFIG']['MOONMODE']['GAIN'] = 75
    capabilities = _capabilities(gain_step=10, gain_step_is_quantum=True)

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


def test_basic_mode_keeps_each_fixed_gain_across_the_exposure_ladder():
    config = _config(EXPOSURE_MODE_BASIC, exposure_max=5)
    config['CCD_CONFIG']['MOONMODE']['BINNING'] = 1
    capabilities = _capabilities()
    state = build_effective_capture_state(config, capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=1)

    assert {
        (target.gain, target.exposure)
        for target in plan.targets
    } == {
        (0.0, 1.0),
        (0.0, 5.0),
        (200.0, 1.0),
        (200.0, 5.0),
        (300.0, 1.0),
        (300.0, 5.0),
    }


def test_camera_sqm_uses_one_covering_exposure_even_above_normal_capture_maximum():
    config = _config(EXPOSURE_MODE_BASIC, exposure_max=1)
    config['CAMERA_SQM'].update({
        'ENABLE': True,
        'ENABLE_DAY': True,
        'EXPOSURE': 7.2,
        'GAIN': 100,
        'BINNING': 1,
    })
    capabilities = _capabilities()
    state = build_effective_capture_state(config, capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=1)
    analysis = analyze_dark_plan(plan, (), temperature=20)

    sqm_targets = [target for target in plan.targets if 'Camera SQM (night)' in target.sources]
    assert len(sqm_targets) == 1
    assert sqm_targets[0].gain == 100.0
    assert sqm_targets[0].exposure == 8.0
    assert set(sqm_targets[0].sources) == {'Camera SQM (day)', 'Camera SQM (night)'}
    assert plan.exposures == (1.0, 8.0)

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


def test_temperature_coverage_accepts_nearest_layer_in_either_direction():
    config = _config(EXPOSURE_MODE_BASIC, exposure_max=1)
    config['DAYTIME_CAPTURE'] = False
    config['CCD_CONFIG']['NIGHT'] = {'GAIN': 100, 'BINNING': 1}
    config['CCD_CONFIG']['MOONMODE'] = {'GAIN': 100, 'BINNING': 1}
    state = build_effective_capture_state(config, _capabilities())
    plan = build_dark_plan(state, _capabilities(), camera_id=5)
    target = plan.targets[0]

    colder_layer = analyze_dark_plan(
        plan,
        _inventory_pair(target, temperature=18),
        temperature=20,
    )
    warmer_layer = analyze_dark_plan(
        plan,
        _inventory_pair(target, temperature=22),
        temperature=20,
    )

    assert colder_layer.target_coverages[0].status == COVERAGE_EXACT
    assert warmer_layer.target_coverages[0].status == COVERAGE_EXACT


def test_warm_seasonal_library_is_covered_through_five_degree_boundary():
    config = _config(EXPOSURE_MODE_BASIC, exposure_max=1)
    config['DAYTIME_CAPTURE'] = False
    config['CCD_CONFIG']['NIGHT'] = {'GAIN': 100, 'BINNING': 1}
    config['CCD_CONFIG']['MOONMODE'] = {'GAIN': 100, 'BINNING': 1}
    capabilities = _capabilities()
    state = build_effective_capture_state(config, capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=5)
    inventory = _inventory_pair(plan.targets[0], temperature=40)

    colder_boundary = analyze_dark_plan(plan, inventory, temperature=35)
    warmer_boundary = analyze_dark_plan(plan, inventory, temperature=45)
    colder = analyze_dark_plan(plan, inventory, temperature=34.9)
    warmer = analyze_dark_plan(plan, inventory, temperature=45.1)

    assert colder_boundary.target_coverages[0].status == COVERAGE_EXACT
    assert colder_boundary.suggested_action == 'none'
    assert warmer_boundary.target_coverages[0].status == COVERAGE_EXACT
    assert warmer_boundary.suggested_action == 'none'
    assert colder.target_coverages[0].status == COVERAGE_TEMPERATURE
    assert colder.structurally_complete is True
    assert colder.temperature_ready is False
    assert colder.suggested_action == 'temperature'
    assert colder.completion_targets == plan.targets
    assert warmer.target_coverages[0].status == COVERAGE_TEMPERATURE
    assert warmer.suggested_action == 'temperature'
    assert warmer.completion_targets == plan.targets

    context = analysis_context(state, capabilities, colder)
    assert context['structural_status_label'] == 'Complete'
    assert context['structural_missing_target_count'] == 0
    assert context['temperature_addition_target_count'] == 1
    assert context['suggested_action_label'] == 'Library complete; add a temperature layer'


def test_temperature_recommendation_uses_selected_matching_distance():
    config = _config(EXPOSURE_MODE_BASIC, exposure_max=1)
    config['DAYTIME_CAPTURE'] = False
    config['CCD_CONFIG']['NIGHT'] = {'GAIN': 100, 'BINNING': 1}
    config['CCD_CONFIG']['MOONMODE'] = {'GAIN': 100, 'BINNING': 1}
    capabilities = _capabilities()
    state = build_effective_capture_state(config, capabilities)
    narrow_plan = build_dark_plan(
        state,
        capabilities,
        camera_id=5,
        temperature_range=4.0,
    )
    wide_plan = build_dark_plan(
        state,
        capabilities,
        camera_id=5,
        temperature_range=6.0,
    )
    inventory = _inventory_pair(narrow_plan.targets[0], temperature=40.0)

    narrow = analyze_dark_plan(narrow_plan, inventory, temperature=35.0)
    wide = analyze_dark_plan(wide_plan, inventory, temperature=35.0)

    assert narrow.suggested_action == 'temperature'
    assert wide.suggested_action == 'none'
    assert analysis_context(state, capabilities, narrow)['temperature_range'] == 4.0
    assert execution_preview(wide, 'complete')['temperature_range'] == 6.0


def test_capture_temperature_drift_is_checked_per_gain_exposure_setting():
    config = _config(EXPOSURE_MODE_BASIC, exposure_max=30)
    config['DAYTIME_CAPTURE'] = False
    config['CCD_CONFIG']['NIGHT'] = {'GAIN': 0, 'BINNING': 1}
    config['CCD_CONFIG']['MOONMODE'] = {'GAIN': 0, 'BINNING': 1}
    capabilities = _capabilities()
    state = build_effective_capture_state(
        config,
        capabilities,
        exposure_max=30,
        exposure_step=5,
    )
    complete_plan = build_dark_plan(state, capabilities, camera_id=5)
    selected_targets = tuple(
        target for target in complete_plan.targets
        if target.gain == 0 and target.exposure in (25, 30)
    )
    assert {target.exposure for target in selected_targets} == {25, 30}
    plan = replace(
        complete_plan,
        exposures=(25.0, 30.0),
        targets=selected_targets,
    )
    targets_by_exposure = {target.exposure: target for target in plan.targets}
    inventory = (
        _inventory_pair(targets_by_exposure[25.0], temperature=39.6)
        + _inventory_pair(targets_by_exposure[30.0], temperature=40.0)
    )

    analysis = analyze_dark_plan(plan, inventory, temperature=34.8)
    coverage_by_exposure = {
        coverage.target.exposure: coverage.status
        for coverage in analysis.target_coverages
    }

    assert coverage_by_exposure == {
        25.0: COVERAGE_EXACT,
        30.0: COVERAGE_TEMPERATURE,
    }
    assert analysis.structurally_complete is True
    assert analysis.suggested_action == 'temperature'
    assert tuple(target.exposure for target in analysis.completion_targets) == (30.0,)


def test_temperature_recommendation_fills_gap_between_existing_layers():
    config = _config(EXPOSURE_MODE_BASIC, exposure_max=1)
    config['DAYTIME_CAPTURE'] = False
    config['CCD_CONFIG']['NIGHT'] = {'GAIN': 100, 'BINNING': 1}
    config['CCD_CONFIG']['MOONMODE'] = {'GAIN': 100, 'BINNING': 1}
    capabilities = _capabilities()
    state = build_effective_capture_state(config, capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=5)
    target = plan.targets[0]
    separated_layers = (
        _inventory_pair(target, temperature=40.0)
        + _inventory_pair(target, temperature=28.9)
    )

    upper_edge = analyze_dark_plan(plan, separated_layers, temperature=35.0)
    lower_edge = analyze_dark_plan(plan, separated_layers, temperature=33.9)
    gap = analyze_dark_plan(plan, separated_layers, temperature=34.9)

    assert upper_edge.suggested_action == 'none'
    assert lower_edge.suggested_action == 'none'
    assert gap.suggested_action == 'temperature'
    assert gap.completion_targets == plan.targets

    bridged_layers = separated_layers + _inventory_pair(target, temperature=34.9)
    for temperature in (33.9, 34.0, 34.5, 34.9, 35.0):
        bridged = analyze_dark_plan(plan, bridged_layers, temperature=temperature)
        assert bridged.suggested_action == 'none'


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
        targets[(30.0, 5.0)],
    )
    analysis = SimpleNamespace(completion_targets=selected, plan=plan)

    groups = build_execution_groups(analysis, 'complete')

    assert sum(group['target_count'] for group in groups) == 3
    assert sorted((group['gains'], group['exposures']) for group in groups) == [
        ([0.0], [1.0, 5.0]),
        ([30.0], [5.0]),
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
        'temperature_source': 'auto',
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
    assert execution['temperature_source'] == 'auto'
    assert execution['groups'][0]['gains'] == [0.0, 100.0, 300.0]
    assert len(execution['plan_signature']) == 64


def test_manual_edit_accepts_an_irregular_fill_gaps_group():
    config = _config(EXPOSURE_MODE_DB_1_10, exposure_max=5)
    config['CCD_CONFIG']['MOONMODE']['BINNING'] = 1
    capabilities = _capabilities()
    state = build_effective_capture_state(config, capabilities)
    plan = build_dark_plan(state, capabilities, camera_id=1)
    targets = {
        (target.gain, target.exposure): target
        for target in plan.targets
        if target.capture_profile == 'night'
    }
    analysis = SimpleNamespace(
        completion_targets=(
            targets[(0.0, 1.0)],
            targets[(0.0, 5.0)],
            targets[(30.0, 5.0)],
        ),
        plan=plan,
    )
    completion_groups = execution_preview(analysis, 'complete')['groups']
    custom_group_ids = {
        group['id'] for group in execution_preview(analysis, 'custom')['groups']
    }
    completion_group = next(
        group for group in completion_groups
        if group['id'] not in custom_group_ids
    )

    execution = normalize_execution_request(
        analysis,
        capabilities,
        state,
        {
            'strategy': 'custom',
            'method': 'sigmaclip',
            'frame_count': 10,
            'config_signature': plan.config_signature,
            'groups': [{**completion_group, 'enabled': True}],
        },
    )

    assert execution['strategy'] == 'custom'
    assert execution['groups'][0]['id'] == completion_group['id']
    assert execution['target_count'] == completion_group['target_count']


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
    capabilities = _capabilities(gain_step=5, gain_step_is_quantum=True)
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


def test_supervised_dark_command_uses_only_private_launcher_and_manifest():
    command = build_dark_command(
        '/venv/bin/python',
        Path('/app/darks_automation.py'),
        Path('/tmp/manifest.json'),
    )

    assert command == [
        '/venv/bin/python',
        str(Path('/app/darks_automation.py')),
        '--manifest',
        str(Path('/tmp/manifest.json')),
    ]


@pytest.mark.parametrize(
    'status,expected_message',
    (
        ('success', 'Dark library complete; normal capture has resumed.'),
        (
            'cancelled',
            'Dark capture cancelled; completed master sets remain active '
            'and normal capture has resumed.',
        ),
        (
            'review_required',
            'Normal capture has resumed. Review the revised camera plan before retrying.',
        ),
        (
            'failed',
            'Completed master sets remain active; normal capture has resumed '
            'after the capture error.',
        ),
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


def test_unrestored_terminal_task_remains_the_visible_progress_task():
    restoring_task = {
        'action': 'dark_automation',
        'status': 'success',
        'capture_restored': False,
        'owner': 'test-owner',
        'camera_id': 7,
    }

    assert task_requires_progress(restoring_task) is True
    restoring_task['capture_restored'] = True
    assert task_requires_progress(restoring_task) is False
    assert task_requires_progress({'status': 'running'}) is True


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


def test_config_drift_expires_capture_task_before_workers_are_touched():
    class QueuedTask:
        def __init__(self, config_id=12, operation=None):
            self.data = {
                'action': 'dark_automation',
                'status': 'queued',
                'config_id': config_id,
                'operation': operation,
                'progress': {'phase': 'queued'},
            }
            self.result = None
            self.expired = False

        def setExpired(self):
            self.expired = True

    current = QueuedTask()
    stale = QueuedTask()
    removal = QueuedTask(operation='flush')

    assert reject_task_for_config_drift(current, active_config_id=12) is False
    assert current.expired is False
    assert reject_task_for_config_drift(removal, active_config_id=99) is False
    assert removal.expired is False

    assert reject_task_for_config_drift(stale, active_config_id=13) is True
    assert stale.expired is True
    assert stale.data['status'] == 'review_required'
    assert stale.data['requires_review'] is True
    assert stale.data['capture_restored'] is True
    assert stale.data['progress']['phase'] == 'review_required'
    assert 'no dark frames were taken' in stale.data['error']
    assert stale.result == 'Reload indi-allsky before dark acquisition'


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
                'completed_master_details': [{
                    'capture_profile': 'night',
                    'gain': 150,
                    'exposure': 10,
                    'binning': 1,
                    'temperature': 20.5,
                    'frame_count': 10,
                    'completed_utc': '2026-08-29T09:00:00+02:00',
                    'duration_seconds': 132.5,
                }],
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
    assert status['completed_master_details'] == [{
        'sequence': 1,
        'capture_profile': 'night',
        'gain': 150,
        'exposure': 10,
        'binning': 1,
        'temperature': 20.5,
        'frame_count': 10,
        'temperature_set': None,
        'completed_utc': '2026-08-29T09:00:00+02:00',
        'duration_seconds': 132.5,
    }]


def test_cancel_requested_status_keeps_cancellation_authoritative_over_child_progress():
    task = SimpleNamespace(
        id=43,
        state=SimpleNamespace(value='RUNNING'),
        data={
            'status': 'cancel_requested',
            'target_count': 1,
            'progress': {
                'phase': 'capturing',
                'message': 'Capturing source frame 1 of 3 at gain 0, exposure 10s.',
                'current_gain': 0,
                'current_exposure': 10,
                'current_frame': 1,
                'current_frame_count': 3,
            },
        },
    )

    protected = _protect_cancel_requested_progress(task.data, task.data['progress'])
    status = task_public_status(task)

    assert protected['phase'] == 'cancel_requested'
    assert protected['message'] == CANCEL_REQUESTED_MESSAGE
    assert protected['current_frame'] == 1
    assert status['status'] == 'cancel_requested'
    assert status['phase'] == 'cancel_requested'
    assert status['message'] == CANCEL_REQUESTED_MESSAGE
    assert status['current_gain'] == 0
    assert status['current_exposure'] == 10
    assert status['current_frame'] == 1


def test_remaining_time_weights_long_and_short_master_exposures():
    task = SimpleNamespace(
        id=45,
        state=SimpleNamespace(value='RUNNING'),
        data={
            'status': 'running',
            'capture_mode': 'single',
            'capture_order': 'long_first',
            'frame_count': 10,
            'target_count': 21,
            'estimated_seconds': 3810,
            'groups': [{
                'gains': [0, 100, 200],
                'exposures': [1, 5, 10, 15, 20, 25, 30],
            }],
            'progress': {
                'phase': 'capturing',
                'completed_master_sets': 1,
                'current_exposure': 25,
                'current_frame': 0,
                'current_frame_count': 10,
                'completed_master_details': [{
                    'capture_profile': 'night',
                    'gain': 200,
                    'exposure': 30,
                    'binning': 1,
                    'temperature': 20.0,
                    'frame_count': 10,
                    'completed_utc': '2026-08-29T09:00:00+02:00',
                    'duration_seconds': 340,
                }],
            },
        },
    )

    after_long_master = task_public_status(task)

    assert after_long_master['remaining_seconds'] == 3530
    assert after_long_master['remaining_seconds'] < 70 * 60

    task.data['progress']['current_frame'] = 5
    midway_through_next_master = task_public_status(task)

    assert midway_through_next_master['remaining_seconds'] == 3389
    assert (
        midway_through_next_master['remaining_seconds']
        < after_long_master['remaining_seconds']
    )


def test_overall_progress_keeps_completed_details_across_capture_groups():
    earlier = [{
        'capture_profile': 'day',
        'gain': 0,
        'exposure': 1,
        'binning': 1,
        'temperature': 19.0,
        'frame_count': 10,
        'completed_utc': '2026-08-29T09:00:00+02:00',
    }]
    child_progress = {
        'phase': 'capturing',
        'completed_master_sets': 1,
        'resolved_width': 1280,
        'resolved_height': 725,
        'completed_master_details': [{
            'capture_profile': 'night',
            'gain': 30,
            'exposure': 30,
            'binning': 1,
            'temperature': 20.0,
            'frame_count': 10,
            'temperature_set': 2,
            'completed_utc': '2026-08-29T09:05:00+02:00',
        }],
    }

    progress = _overall_progress(child_progress, 1, 4, 2, 3, earlier)

    assert progress['completed_master_sets'] == 2
    assert [detail['sequence'] for detail in progress['completed_master_details']] == [1, 2]
    assert [
        detail['capture_profile'] for detail in progress['completed_master_details']
    ] == ['day', 'night']
    assert progress['completed_master_details'][1]['temperature_set'] == 2
    assert progress['resolved_width'] == 1280
    assert progress['resolved_height'] == 725


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


def test_finite_temperature_series_status_keeps_plan_during_child_handoff():
    task = SimpleNamespace(
        id=45,
        state=SimpleNamespace(value='RUNNING'),
        data={
            'status': 'running',
            'capture_mode': 'temperature_series',
            'temperature_target': 5,
            'temperature_set_count': 4,
            'target_count': 3,
            'progress': _overall_progress({}, 0, 3, 1, 1),
        },
    )

    status = task_public_status(task)

    assert status['target_temperature'] == 5
    assert status['planned_temperature_sets'] == 4
    assert status['target_count'] == 12


def test_temperature_series_restore_message_preserves_completed_sets():
    task = SimpleNamespace(data={
        'action': 'dark_automation',
        'status': 'cancelled',
        'capture_mode': 'temperature_series',
        'capture_restored': False,
        'progress': {'phase': 'restoring_capture'},
    })

    _mark_task_capture_restored(task)

    assert 'completed master sets remain active' in task.data['progress']['message']


class _FakeColumn:
    def __eq__(self, _value):
        return True


class _FakeQuery:
    def __init__(self, entries):
        self.entries = entries
        self.all_calls = 0

    def filter(self, _condition):
        return self

    def all(self):
        self.all_calls += 1
        return list(self.entries)


class _FakeSession:
    def __init__(self, fail_commit=False):
        self.fail_commit = fail_commit
        self.deleted = []
        self.committed = False
        self.rolled_back = False
        self.flushed = False

    def delete(self, entry):
        self.deleted.append(entry)

    def commit(self):
        if self.fail_commit:
            raise RuntimeError('database commit failed')
        self.committed = True

    def flush(self):
        self.flushed = True

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


def _catalog_frame(
        frame_id,
        camera_id,
        create_date,
        active=True,
        generation_id=None,
        temperature=20.0,
        file_size=1024,
        gain=100.0,
        exposure=30.0,
):
    automation_data = {}
    if generation_id:
        automation_data = {
            'dark_automation': {
                'generation_id': generation_id,
                'group_id': 'group-1',
            },
        }
    return SimpleNamespace(
        id=frame_id,
        camera_id=camera_id,
        active=active,
        bitdepth=16,
        exposure=exposure,
        gain=gain,
        binmode=1,
        temp=temperature,
        width=3840,
        height=2160,
        createDate=create_date,
        fileSize=file_size,
        data=automation_data,
    )


def test_library_partner_index_uses_exact_master_set_identity():
    create_date = datetime(2026, 8, 21, 12, 0, 0)
    dark_frames = [
        _catalog_frame(1, 1, create_date, generation_id='summer', gain=100),
        _catalog_frame(2, 1, create_date, generation_id='summer', gain=200),
        _catalog_frame(3, 1, create_date, generation_id='winter', gain=100),
    ]
    bad_pixel_maps = [
        _catalog_frame(101, 1, create_date, generation_id='summer', gain=100),
        _catalog_frame(102, 1, create_date, generation_id='summer', gain=200),
    ]

    partners = build_library_partner_index(dark_frames, bad_pixel_maps)

    assert partners[('dark', 1)] == {
        'partner_type': 'bpm',
        'partner_ids': (101,),
    }
    assert partners[('bpm', 102)] == {
        'partner_type': 'dark',
        'partner_ids': (2,),
    }
    assert partners[('dark', 3)] == {
        'partner_type': 'bpm',
        'partner_ids': (),
    }


def test_library_partner_index_keeps_identical_legacy_pairing_conservative():
    first_date = datetime(2026, 8, 21, 12, 0, 0)
    later_date = datetime(2026, 8, 21, 12, 1, 0)
    dark = _catalog_frame(1, 1, first_date, temperature=20.0)
    exact_map = _catalog_frame(101, 1, first_date, temperature=20.0)
    later_map = _catalog_frame(102, 1, later_date, temperature=20.0)

    partners = build_library_partner_index([dark], [exact_map, later_map])

    assert partners[('dark', 1)]['partner_ids'] == (101,)
    assert partners[('bpm', 102)]['partner_ids'] == ()


def test_frame_profile_fit_uses_current_structural_capture_profiles():
    plan = SimpleNamespace(targets=(SimpleNamespace(
        camera_id=1,
        bit_depth=16,
        binning=2,
        width=100,
        height=50,
    ),))
    frame = SimpleNamespace(
        camera_id=1,
        bit_depth=16,
        binning=2,
        width=100,
        height=50,
        active=False,
        exists=False,
    )

    assert frame_matches_plan_profile(plan, frame) is True
    assert frame_matches_plan_profile(
        plan,
        SimpleNamespace(**{**frame.__dict__, 'width': 101}),
    ) is False
    assert frame_matches_plan_profile(
        plan,
        SimpleNamespace(**{**frame.__dict__, 'camera_id': 2}),
    ) is False


def test_library_catalog_groups_cameras_profiles_layers_and_pairs():
    current_camera = SimpleNamespace(id=1, name='Current camera', friendlyName='Current')
    old_camera = SimpleNamespace(id=2, name='Old camera', friendlyName=None)
    recent_date = datetime(2026, 8, 21, 12, 0, 0)
    old_date = datetime(2025, 1, 1, 12, 0, 0)
    dark_frames = [
        _catalog_frame(1, 1, recent_date, generation_id='summer'),
        _catalog_frame(3, 1, old_date, active=False, temperature=5.0),
        _catalog_frame(5, 2, old_date, temperature=-10.0),
    ]
    bad_pixel_maps = [
        _catalog_frame(2, 1, recent_date, generation_id='summer'),
        _catalog_frame(4, 1, old_date, active=False, temperature=5.0),
        _catalog_frame(6, 2, old_date, temperature=-10.0),
    ]

    catalog = build_library_catalog(
        (old_camera, current_camera),
        dark_frames,
        bad_pixel_maps,
        current_camera_id=1,
    )

    assert catalog['camera_count'] == 2
    assert catalog['entry_count'] == 6
    assert catalog['size_bytes'] == 6 * 1024
    assert [camera['id'] for camera in catalog['cameras']] == [1, 2]
    current = catalog['cameras'][0]
    assert current['current'] is True
    assert current['active_selection'] == {'dark_ids': [1], 'bpm_ids': [2]}
    assert current['inactive_selection'] == {'dark_ids': [3], 'bpm_ids': [4]}
    assert current['activatable_selection'] == {'dark_ids': [3], 'bpm_ids': [4]}
    assert len(current['profiles']) == 1
    assert len(current['profiles'][0]['layers']) == 2
    assert all(
        layer['paired_set_count'] == 1
        for layer in current['profiles'][0]['layers']
    )
    assert current['active_master_set_count'] == 1
    assert current['inactive_master_set_count'] == 1
    assert catalog['selection_batches'][0]['camera_id'] == 1
    assert catalog['active_selection_batches'][0]['selection'] == {
        'dark_ids': [1],
        'bpm_ids': [2],
    }
    assert catalog['inactive_selection_batches'][0]['selection'] == {
        'dark_ids': [3],
        'bpm_ids': [4],
    }


def test_library_catalog_reuses_prechecked_frame_sizes():
    camera = SimpleNamespace(id=1, name='Camera', friendlyName=None)
    create_date = datetime(2026, 8, 21, 12, 0, 0)
    dark = _catalog_frame(1, 1, create_date, file_size=1)
    bpm = _catalog_frame(2, 1, create_date, file_size=1)

    def unexpected_filesystem_check():
        raise AssertionError('Cached frame sizes should avoid another filesystem check')

    dark.getFilesystemPath = unexpected_filesystem_check
    bpm.getFilesystemPath = unexpected_filesystem_check

    catalog = build_library_catalog(
        (camera,),
        (dark,),
        (bpm,),
        current_camera_id=1,
        frame_sizes={('dark', 1): 2048, ('bpm', 2): 1024},
    )

    assert catalog['size_bytes'] == 3072


def test_library_catalog_groups_nearby_legacy_temperatures_across_old_bucket_boundary():
    camera = SimpleNamespace(
        id=1,
        name='Camera',
        friendlyName=None,
        data={
            'dark_library': {
                'temperature_matching_distance': 5.0,
            },
        },
    )
    temperatures = (42.1, 42.3, 42.5, 43.2)
    dark_frames = []
    bad_pixel_maps = []
    for index, temperature in enumerate(temperatures, start=1):
        create_date = datetime(2026, 8, 21, 12, index, 0)
        frame_kwargs = {
            'camera_id': 1,
            'create_date': create_date,
            'temperature': temperature,
            'gain': index * 10,
        }
        dark_frames.append(_catalog_frame(index, **frame_kwargs))
        bad_pixel_maps.append(_catalog_frame(index + 100, **frame_kwargs))

    catalog = build_library_catalog(
        (camera,),
        dark_frames,
        bad_pixel_maps,
        current_camera_id=1,
    )

    layers = catalog['cameras'][0]['profiles'][0]['layers']
    assert len(layers) == 1
    assert layers[0]['temperature_label'] == '42.1 to 43.2°C'
    assert layers[0]['master_set_count'] == 4


def test_library_catalog_labels_sensorless_camera_group_without_sentinel_value():
    camera = SimpleNamespace(id=1, name='Camera', friendlyName=None)
    create_date = datetime(2026, 8, 21, 12, 0, 0)
    dark_frames = [
        _catalog_frame(1, 1, create_date, temperature=-273.15),
    ]
    bad_pixel_maps = [
        _catalog_frame(101, 1, create_date, temperature=-273.15),
    ]

    catalog = build_library_catalog(
        (camera,),
        dark_frames,
        bad_pixel_maps,
        current_camera_id=1,
    )

    layers = catalog['cameras'][0]['profiles'][0]['layers']
    assert layers[0]['temperature_label'] == 'No camera temperature'


def test_library_catalog_starts_a_new_group_at_saved_matching_distance():
    camera = SimpleNamespace(
        id=1,
        name='Camera',
        friendlyName=None,
        data={
            'dark_library': {
                'temperature_matching_distance': 5.0,
            },
        },
    )
    first_date = datetime(2026, 8, 21, 12, 0, 0)
    second_date = datetime(2026, 8, 21, 13, 0, 0)
    dark_frames = [
        _catalog_frame(1, 1, first_date, generation_id='warm', temperature=42.5),
        _catalog_frame(2, 1, second_date, generation_id='cool', temperature=37.5),
    ]
    bad_pixel_maps = [
        _catalog_frame(101, 1, first_date, generation_id='warm', temperature=42.5),
        _catalog_frame(102, 1, second_date, generation_id='cool', temperature=37.5),
    ]

    catalog = build_library_catalog(
        (camera,),
        dark_frames,
        bad_pixel_maps,
        current_camera_id=1,
    )

    layers = catalog['cameras'][0]['profiles'][0]['layers']
    assert len(layers) == 2
    assert {layer['temperature_label'] for layer in layers} == {'37.5°C', '42.5°C'}


def test_library_catalog_reports_active_inactive_and_mixed_master_sets():
    camera = SimpleNamespace(id=1, name='Camera', friendlyName=None)
    create_dates = [
        datetime(2026, 8, 21, 12, minute, 0)
        for minute in range(3)
    ]
    dark_frames = [
        _catalog_frame(1, 1, create_dates[0], active=True, gain=10),
        _catalog_frame(2, 1, create_dates[1], active=False, gain=20),
        _catalog_frame(3, 1, create_dates[2], active=True, gain=30),
    ]
    bad_pixel_maps = [
        _catalog_frame(101, 1, create_dates[0], active=True, gain=10),
        _catalog_frame(102, 1, create_dates[1], active=False, gain=20),
        _catalog_frame(103, 1, create_dates[2], active=False, gain=30),
    ]

    catalog = build_library_catalog(
        (camera,),
        dark_frames,
        bad_pixel_maps,
        current_camera_id=1,
    )

    library = catalog['cameras'][0]
    assert library['active_master_set_count'] == 1
    assert library['inactive_master_set_count'] == 1
    assert library['mixed_master_set_count'] == 1
    assert library['inactive_selection'] == {
        'dark_ids': [2],
        'bpm_ids': [102, 103],
    }
    statuses = {
        master['gain']: master['status']
        for master in library['profiles'][0]['layers'][0]['master_sets']
    }
    assert statuses == {10.0: 'active', 20.0: 'inactive', 30.0: 'mixed'}


def test_selected_library_entries_never_cross_camera_boundary():
    dark_entries = [
        SimpleNamespace(id=1, camera_id=1, fileSize=10),
        SimpleNamespace(id=2, camera_id=2, fileSize=20),
    ]
    bpm_entries = [
        SimpleNamespace(id=3, camera_id=1, fileSize=30),
        SimpleNamespace(id=4, camera_id=2, fileSize=40),
    ]
    dark_model = _flush_model('IndiAllSkyDbDarkFrameTable', dark_entries)
    bpm_model = _flush_model('IndiAllSkyDbBadPixelMapTable', bpm_entries)

    selected = select_camera_library_entries(
        (dark_model, bpm_model),
        camera_id=1,
        selection={'dark_ids': [1, 2], 'bpm_ids': [3, 4]},
    )

    assert selected['dark_frames'] == 1
    assert selected['bad_pixel_maps'] == 1
    assert selected['size_bytes'] == 40
    assert selected['selection'] == {'dark_ids': [1], 'bpm_ids': [3]}


def test_master_set_selection_expands_to_matching_dark_and_map_only():
    create_date = datetime(2026, 8, 21, 12, 0, 0)
    dark_entries = [
        _catalog_frame(1, 1, create_date, generation_id='first', gain=100),
        _catalog_frame(2, 1, create_date, generation_id='second', gain=200),
        _catalog_frame(3, 2, create_date, generation_id='first', gain=100),
    ]
    bpm_entries = [
        _catalog_frame(101, 1, create_date, generation_id='first', gain=100),
        _catalog_frame(102, 1, create_date, generation_id='second', gain=200),
        _catalog_frame(103, 2, create_date, generation_id='first', gain=100),
    ]
    dark_model = _flush_model('IndiAllSkyDbDarkFrameTable', dark_entries)
    bpm_model = _flush_model('IndiAllSkyDbBadPixelMapTable', bpm_entries)

    selected = select_camera_master_sets(
        (dark_model, bpm_model),
        camera_id=1,
        selection={'dark_ids': [1, 3], 'bpm_ids': []},
    )

    assert selected['selection'] == {'dark_ids': [1], 'bpm_ids': [101]}
    assert dark_model.query.all_calls == 1
    assert bpm_model.query.all_calls == 1


def test_manual_eligibility_changes_are_reversible_and_recorded():
    frames = [
        SimpleNamespace(active=True, data={}),
        SimpleNamespace(active=True, data={}),
    ]

    excluded = update_library_entries_eligibility(frames, False, changed_utc='now')

    assert excluded == tuple(frames)
    assert all(frame.active is False for frame in frames)
    assert all(
        library_entry_eligibility(frame)['reason_label'] == 'Manually deactivated'
        for frame in frames
    )
    restored = update_library_entries_eligibility(frames, True, changed_utc='later')
    assert restored == tuple(frames)
    assert all(frame.active is True for frame in frames)
    assert all(
        library_entry_eligibility(frame)['reason_label'] == 'Manually activated'
        for frame in frames
    )


def test_manual_eligibility_change_skips_entries_already_in_the_target_state():
    active_frame = SimpleNamespace(active=True, data={})
    inactive_frame = SimpleNamespace(active=False, data={})

    changed = update_library_entries_eligibility(
        [active_frame, inactive_frame],
        False,
        changed_utc='now',
    )

    assert changed == (active_frame,)
    assert active_frame.active is False
    assert inactive_frame.active is False
    assert library_entry_eligibility(active_frame)['reason_label'] == 'Manually deactivated'
    assert library_entry_eligibility(inactive_frame)['reason_label'] is None


def test_capture_staging_cannot_be_manually_activated():
    frame = SimpleNamespace(active=False, data={
        'dark_automation': {
            'eligibility': {
                'state': 'staged',
                'reason': 'capture_staging',
            },
        },
    })

    with pytest.raises(DarkAutomationError, match='Files being captured'):
        update_library_entries_eligibility([frame], True)

    assert frame.active is False


def test_flush_removes_only_explicitly_selected_records():
    with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary_dir:
        temporary_path = Path(temporary_dir)
        selected_path = temporary_path.joinpath('selected.fit')
        retained_path = temporary_path.joinpath('retained.fit')
        selected_path.write_bytes(b'selected')
        retained_path.write_bytes(b'retained')
        selected_entry = SimpleNamespace(
            id=1,
            camera_id=1,
            fileSize=8,
            getFilesystemPath=lambda: selected_path,
        )
        retained_entry = SimpleNamespace(
            id=2,
            camera_id=1,
            fileSize=8,
            getFilesystemPath=lambda: retained_path,
        )
        dark_model = _flush_model(
            'IndiAllSkyDbDarkFrameTable',
            [selected_entry, retained_entry],
        )
        bpm_model = _flush_model('IndiAllSkyDbBadPixelMapTable', [])
        session = _FakeSession()

        result = flush_camera_library(
            SimpleNamespace(session=session),
            (dark_model, bpm_model),
            camera_id=1,
            selection={'dark_ids': [1], 'bpm_ids': []},
        )

        assert session.deleted == [selected_entry]
        assert not selected_path.exists()
        assert retained_path.read_bytes() == b'retained'
        assert result['dark_frames'] == 1
        assert result['bad_pixel_maps'] == 0


def test_flush_library_batches_preflights_and_deletes_across_cameras():
    with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary_dir:
        temporary_path = Path(temporary_dir)
        first_path = temporary_path.joinpath('camera-1.fit')
        second_path = temporary_path.joinpath('camera-2.fit')
        first_path.write_bytes(b'first')
        second_path.write_bytes(b'second')
        first_entry = SimpleNamespace(
            id=1,
            camera_id=1,
            fileSize=5,
            filename='camera-1.fit',
            createDate=datetime(2026, 8, 21, 12, 0, 0),
            getFilesystemPath=lambda: first_path,
        )
        second_entry = SimpleNamespace(
            id=2,
            camera_id=2,
            fileSize=6,
            filename='camera-2.fit',
            createDate=datetime(2026, 8, 21, 12, 1, 0),
            getFilesystemPath=lambda: second_path,
        )
        dark_model = _flush_model(
            'IndiAllSkyDbDarkFrameTable',
            [first_entry, second_entry],
        )
        bpm_model = _flush_model('IndiAllSkyDbBadPixelMapTable', [])
        models = (dark_model, bpm_model)
        first_preview = select_camera_library_entries(
            models,
            camera_id=1,
            selection={'dark_ids': [1], 'bpm_ids': []},
        )
        second_preview = select_camera_library_entries(
            models,
            camera_id=2,
            selection={'dark_ids': [2], 'bpm_ids': []},
        )
        batches = [{
            'camera_id': 1,
            'selection': first_preview['selection'],
            'selection_signature': first_preview['signature'],
        }, {
            'camera_id': 2,
            'selection': second_preview['selection'],
            'selection_signature': second_preview['signature'],
        }]
        signature = library_selection_batches_signature([
            {'camera_id': 2, 'signature': second_preview['signature']},
            {'camera_id': 1, 'signature': first_preview['signature']},
        ])
        assert signature == library_selection_batches_signature([
            {'camera_id': 1, 'signature': first_preview['signature']},
            {'camera_id': 2, 'signature': second_preview['signature']},
        ])

        session = _FakeSession()
        result = flush_library_batches(
            SimpleNamespace(session=session),
            models,
            batches,
        )

        assert session.deleted == [first_entry, second_entry]
        assert session.committed is True
        assert not first_path.exists()
        assert not second_path.exists()
        assert result == {
            'dark_frames': 2,
            'bad_pixel_maps': 0,
            'files': 2,
            'warnings': [],
        }


def test_flush_requires_a_fresh_selection_signature():
    selected_entry = SimpleNamespace(
        id=1,
        camera_id=1,
        filename='original.fit',
        createDate=datetime(2026, 8, 21, 12, 0, 0),
        fileSize=8,
        getFilesystemPath=lambda: Path('original.fit'),
    )
    dark_model = _flush_model('IndiAllSkyDbDarkFrameTable', [selected_entry])
    bpm_model = _flush_model('IndiAllSkyDbBadPixelMapTable', [])
    selection = {'dark_ids': [1], 'bpm_ids': []}
    preview = select_camera_library_entries(
        (dark_model, bpm_model),
        camera_id=1,
        selection=selection,
    )
    selected_entry.filename = 'replacement.fit'
    session = _FakeSession()

    with pytest.raises(DarkAutomationError, match='changed after preview'):
        flush_camera_library(
            SimpleNamespace(session=session),
            (dark_model, bpm_model),
            camera_id=1,
            selection=selection,
            expected_signature=preview['signature'],
        )

    assert session.deleted == []


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


def _automation_model(name):
    return type(name, (), {'camera_id': _FakeColumn()})


def _automation_model_frame(
        model,
        path,
        generation,
        frame_task_id=42,
        group_id='group-1',
        active=False,
        eligibility_state='staged',
        gain=100,
        exposure=5,
        temperature=20,
):
    frame = model()
    frame.camera_id = 1
    frame.active = bool(active)
    frame.gain = float(gain)
    frame.exposure = float(exposure)
    frame.binmode = 1
    frame.bitdepth = 16
    frame.width = 100
    frame.height = 50
    frame.temp = temperature
    frame.data = {
        'dark_automation': {
            'generation_id': generation,
            'task_id': frame_task_id,
            'group_id': group_id,
            'eligibility': {
                'state': eligibility_state,
                'reason': 'capture_staging',
                'source': 'automation',
            },
        },
    }
    frame.getFilesystemPath = lambda: Path(path)
    return frame


def test_completed_master_pair_is_checkpointed_atomically():
    dark_model = _automation_model('IndiAllSkyDbDarkFrameTable')
    bpm_model = _automation_model('IndiAllSkyDbBadPixelMapTable')
    new_dark = _automation_model_frame(dark_model, 'new-dark.fit', 'new')
    new_bpm = _automation_model_frame(bpm_model, 'new-bpm.fit', 'new')
    old_dark = _automation_model_frame(
        dark_model,
        'old-dark.fit',
        'old-dark',
        active=True,
        eligibility_state='active',
    )
    old_bpm = _automation_model_frame(
        bpm_model,
        'old-bpm.fit',
        'old-bpm',
        active=True,
        eligibility_state='active',
    )
    dark_model.query = _FakeQuery([new_dark, old_dark])
    bpm_model.query = _FakeQuery([new_bpm, old_bpm])
    session = _FakeSession()

    result = checkpoint_master_pair(
        SimpleNamespace(session=session),
        (dark_model, bpm_model),
        (new_dark, new_bpm),
        {
            'generation_id': 'new',
            'task_id': 42,
            'group_id': 'group-1',
            'strategy': 'refresh',
            'temperature_range': 5.0,
            'binning': 1,
            'bit_depth': 16,
            'width': 100,
            'height': 50,
            'gains': [100.0],
            'exposures': [5.0],
        },
    )

    assert result == {'activated': 2, 'deactivated': 2}
    assert session.flushed is True
    assert session.committed is False
    assert new_dark.active is True
    assert new_bpm.active is True
    assert old_dark.active is False
    assert old_bpm.active is False
    assert library_entry_eligibility(new_dark)['state'] == 'active'
    assert library_entry_eligibility(new_bpm)['state'] == 'active'


def test_builder_master_filenames_use_a_legacy_independent_namespace():
    assert automation_master_filename('dark_ccd1.fit') == 'dark_automation_ccd1.fit'
    assert automation_master_filename('bpm_ccd1.fit') == 'bpm_automation_ccd1.fit'
    with pytest.raises(DarkAutomationError, match='invalid master filename'):
        automation_master_filename('legacy.fit')


def test_interrupted_artifact_cleanup_preserves_only_complete_eligible_pairs(tmp_path):
    darks_dir = tmp_path.joinpath('darks')
    darks_dir.mkdir()
    scratch_dir = tmp_path.joinpath('indi-allsky-dark-source-abandoned')
    scratch_dir.mkdir()
    scratch_dir.joinpath('source.fit').write_bytes(b'source')

    dark_model = _automation_model('IndiAllSkyDbDarkFrameTable')
    bpm_model = _automation_model('IndiAllSkyDbBadPixelMapTable')

    def master_path(name):
        path = darks_dir.joinpath(name)
        path.write_bytes(b'master')
        return path

    valid_dark = _automation_model_frame(
        dark_model,
        master_path('dark_valid.fit'),
        'valid',
        active=True,
        eligibility_state='active',
    )
    valid_bpm = _automation_model_frame(
        bpm_model,
        master_path('bpm_valid.fit'),
        'valid',
        active=True,
        eligibility_state='active',
    )
    inactive_dark = _automation_model_frame(
        dark_model,
        master_path('dark_inactive.fit'),
        'inactive',
        active=False,
        eligibility_state='inactive',
    )
    inactive_bpm = _automation_model_frame(
        bpm_model,
        master_path('bpm_inactive.fit'),
        'inactive',
        active=False,
        eligibility_state='inactive',
    )
    staged_dark = _automation_model_frame(
        dark_model,
        master_path('dark_staged.fit'),
        'staged',
    )
    staged_bpm = _automation_model_frame(
        bpm_model,
        master_path('bpm_staged.fit'),
        'staged',
    )
    incomplete_dark = _automation_model_frame(
        dark_model,
        master_path('dark_incomplete.fit'),
        'incomplete',
        active=True,
        eligibility_state='active',
    )
    orphan_path = master_path('bpm_automation_orphan.fit')
    legacy_orphan_path = master_path('dark_legacy_orphan.fit')
    dark_model.query = _FakeQuery([
        valid_dark,
        inactive_dark,
        staged_dark,
        incomplete_dark,
    ])
    bpm_model.query = _FakeQuery([valid_bpm, inactive_bpm, staged_bpm])
    session = _FakeSession()

    result = cleanup_interrupted_capture_artifacts(
        SimpleNamespace(session=session),
        (dark_model, bpm_model),
        darks_dir,
        temp_root=tmp_path,
    )

    assert result == {
        'database_rows': 3,
        'files': 4,
        'temporary_directories': 1,
        'warnings': [],
    }
    assert session.committed is True
    assert set(session.deleted) == {staged_dark, staged_bpm, incomplete_dark}
    assert Path(valid_dark.getFilesystemPath()).is_file()
    assert Path(valid_bpm.getFilesystemPath()).is_file()
    assert Path(inactive_dark.getFilesystemPath()).is_file()
    assert Path(inactive_bpm.getFilesystemPath()).is_file()
    assert not Path(staged_dark.getFilesystemPath()).exists()
    assert not Path(staged_bpm.getFilesystemPath()).exists()
    assert not Path(incomplete_dark.getFilesystemPath()).exists()
    assert not orphan_path.exists()
    assert legacy_orphan_path.is_file()
    assert not scratch_dir.exists()


def test_interrupted_cleanup_keeps_files_when_database_cleanup_cannot_commit(tmp_path):
    darks_dir = tmp_path.joinpath('darks')
    darks_dir.mkdir()
    dark_path = darks_dir.joinpath('dark_staged.fit')
    bpm_path = darks_dir.joinpath('bpm_staged.fit')
    dark_path.write_bytes(b'dark')
    bpm_path.write_bytes(b'bpm')
    dark_model = _automation_model('IndiAllSkyDbDarkFrameTable')
    bpm_model = _automation_model('IndiAllSkyDbBadPixelMapTable')
    dark_model.query = _FakeQuery([
        _automation_model_frame(dark_model, dark_path, 'staged'),
    ])
    bpm_model.query = _FakeQuery([
        _automation_model_frame(bpm_model, bpm_path, 'staged'),
    ])
    session = _FakeSession(fail_commit=True)

    with pytest.raises(RuntimeError, match='database commit failed'):
        cleanup_interrupted_capture_artifacts(
            SimpleNamespace(session=session),
            (dark_model, bpm_model),
            darks_dir,
            temp_root=tmp_path,
        )

    assert session.rolled_back is True
    assert dark_path.is_file()
    assert bpm_path.is_file()


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


def test_successful_refresh_records_activation_and_retirement_reasons():
    new_dark = _generation_frame('new')
    new_map = _generation_frame('new')
    old_dark = _generation_frame('old-dark', active=True)
    old_map = _generation_frame('old-map', active=True)
    dark_model = _flush_model(
        'IndiAllSkyDbDarkFrameTable',
        [new_dark, old_dark],
    )
    bpm_model = _flush_model(
        'IndiAllSkyDbBadPixelMapTable',
        [new_map, old_map],
    )
    session = _FakeSession()

    result = _activate_generation(
        SimpleNamespace(session=session),
        (dark_model, bpm_model),
        {
            'generation_id': 'new',
            'camera_id': 1,
            'target_count': 1,
            'strategy': 'refresh',
            'temperature_range': 5.0,
            'groups': [_activation_group()],
        },
    )

    assert result == {'activated': 2, 'deactivated': 2}
    assert session.committed is True
    assert library_entry_eligibility(new_dark)['reason_label'] == 'Activated after capture'
    assert library_entry_eligibility(new_map)['reason_label'] == 'Activated after capture'
    assert library_entry_eligibility(old_dark)['reason_label'] == 'Replaced by a recommended-set update'
    assert library_entry_eligibility(old_map)['reason_label'] == 'Replaced by a recommended-set update'


def test_refresh_uses_selected_temperature_distance_for_equivalent_layers():
    new_frame = _generation_frame('new', temperature=20)
    four_degrees_away = _generation_frame('old', active=True, temperature=24)

    _activate, narrow_deactivate = activation_changes(
        'refresh',
        [new_frame],
        [four_degrees_away],
        [_activation_group()],
        temperature_range=3.9,
    )
    _activate, wide_deactivate = activation_changes(
        'refresh',
        [new_frame],
        [four_degrees_away],
        [_activation_group()],
        temperature_range=4.0,
    )

    assert narrow_deactivate == ()
    assert wide_deactivate == (four_degrees_away,)


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


def test_rebuild_uses_symmetric_matching_around_cooled_target():
    new_frame = _generation_frame('new', temperature=20)
    colder = _generation_frame('old-cold', active=True, temperature=16)
    warmer = _generation_frame('old-warm', active=True, temperature=24)
    outside = _generation_frame('old-outside', active=True, temperature=25.1)
    group = _activation_group(temperature=20)

    _activate, deactivate = activation_changes(
        'rebuild',
        [new_frame],
        [colder, warmer, outside],
        [group],
        temperature_range=5.0,
    )

    assert deactivate == (colder, warmer)


def test_capability_signature_detects_material_live_camera_change():
    capabilities = _capabilities()
    changed = _capabilities(gain_step=5)
    changed_frame = replace(capabilities, frame_height=2152)

    assert capabilities.signature == CameraCapabilities(**capabilities.__dict__).signature
    assert capabilities.signature != changed.signature
    assert capabilities.signature != changed_frame.signature


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
