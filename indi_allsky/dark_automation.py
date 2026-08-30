import hashlib
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from datetime import timezone
from pathlib import Path

from . import constants
from .dark_library import DEFAULT_TEMPERATURE_RANGE
from .dark_library import camera_temperature_preferences


STRATEGY_COMPLETE = 'complete'
STRATEGY_REFRESH = 'refresh'
STRATEGY_REBUILD = 'rebuild'
STRATEGY_CUSTOM = 'custom'

STRATEGIES = (
    STRATEGY_COMPLETE,
    STRATEGY_REFRESH,
    STRATEGY_REBUILD,
    STRATEGY_CUSTOM,
)

METHODS = ('sigmaclip', 'average')
CAPTURE_MODE_SINGLE = 'single'
CAPTURE_MODE_TEMPERATURE_SERIES = 'temperature_series'
CAPTURE_MODES = (
    CAPTURE_MODE_SINGLE,
    CAPTURE_MODE_TEMPERATURE_SERIES,
)
ACTIVE_STATUSES = ('queued', 'preparing', 'running', 'cancel_requested')
TERMINAL_STATUSES = ('success', 'failed', 'cancelled', 'review_required')
CANCEL_REQUESTED_MESSAGE = 'Cancelling after the current camera operation finishes.'
MAX_MASTER_SETS = 2000
MIN_FRAME_COUNT = 3
MAX_FRAME_COUNT = 50
CAPTURE_ORDERS = ('long_first', 'short_first')
TEMPERATURE_POLICIES = ('recommended', 'ignore')
COVER_CONFIRMATION_MAX_AGE_SECONDS = 30 * 60
CONTROLLER_HEARTBEAT_MAX_AGE_SECONDS = 10 * 60
ETA_OVERHEAD_PRIOR_SETS = 3.0
MIN_TEMPERATURE_DELTA = 0.1
MAX_TEMPERATURE_DELTA = 50.0
MIN_TEMPERATURE_TARGET = -100.0
MAX_TEMPERATURE_TARGET = 100.0
BITMAX_VALUES = (0, 8, 10, 12, 14, 16)
CAPTURE_RESTORE_RUNNING = 'running'
CAPTURE_RESTORE_PAUSED = 'paused'
CAPTURE_RESTORE_SLEEPING = 'sleeping'
CAPTURE_RESTORE_CONTROLLER = 'controller'

ELIGIBILITY_STATE_ACTIVE = 'active'
ELIGIBILITY_STATE_INACTIVE = 'inactive'
ELIGIBILITY_STATE_STAGED = 'staged'
ELIGIBILITY_REASON_CAPTURE_COMPLETED = 'capture_completed'
ELIGIBILITY_REASON_CAPTURE_STAGING = 'capture_staging'
ELIGIBILITY_REASON_REFRESH_REPLACED = 'refresh_replaced'
ELIGIBILITY_REASON_REBUILD_REPLACED = 'rebuild_replaced'
ELIGIBILITY_REASON_MANUAL_EXCLUSION = 'manual_exclusion'
ELIGIBILITY_REASON_MANUAL_RESTORE = 'manual_restore'

ELIGIBILITY_REASON_LABELS = {
    ELIGIBILITY_REASON_CAPTURE_COMPLETED: 'Activated after capture',
    ELIGIBILITY_REASON_CAPTURE_STAGING: 'Being captured',
    ELIGIBILITY_REASON_REFRESH_REPLACED: 'Replaced by a recommended-set update',
    ELIGIBILITY_REASON_REBUILD_REPLACED: 'Replaced by a profile rebuild',
    ELIGIBILITY_REASON_MANUAL_EXCLUSION: 'Manually deactivated',
    ELIGIBILITY_REASON_MANUAL_RESTORE: 'Manually activated',
}

DARK_CAPTURE_TEMP_PREFIXES = (
    'indi-allsky-dark-automation-',
    'indi-allsky-dark-temperature-',
    'indi-allsky-dark-source-',
)
DARK_AUTOMATION_MASTER_FILE_PREFIXES = (
    'dark_automation_',
    'bpm_automation_',
    '.dark-automation-',
)


class DarkAutomationError(RuntimeError):
    pass


class DarkAutomationCancelled(DarkAutomationError):
    pass


class DarkAutomationReviewRequired(DarkAutomationError):
    pass


def automation_master_filename(filename):
    """Give builder-owned masters a namespace the legacy CLI never uses."""
    filename = str(filename)
    for legacy_prefix, automation_prefix in (
            ('dark_', 'dark_automation_'),
            ('bpm_', 'bpm_automation_'),
    ):
        if filename.startswith(legacy_prefix):
            return automation_prefix + filename[len(legacy_prefix):]
    raise DarkAutomationError('The builder produced an invalid master filename')


def reject_task_for_config_drift(task, active_config_id):
    """Expire a queued capture task when the controller has not loaded its config."""
    data = dict(task.data or {})
    if data.get('operation') == 'flush':
        return False
    expected_config_id = data.get('config_id')
    if expected_config_id is None:
        # Preserve compatibility with a task queued by an older web process.
        return False
    try:
        matches = int(expected_config_id) == int(active_config_id)
    except (TypeError, ValueError):
        matches = False
    if matches:
        return False

    message = (
        'The saved configuration used for this plan is not active in the '
        'indi-allsky service. Reload indi-allsky, then review the updated plan; '
        'no dark frames were taken.'
    )
    data.update({
        'status': 'review_required',
        'completed_utc': _utc_now_text(),
        'capture_restored': True,
        'error': message,
        'requires_review': True,
    })
    progress = dict(data.get('progress') or {})
    progress.update({
        'phase': 'review_required',
        'message': message,
        'heartbeat_utc': _utc_now_text(),
    })
    data['progress'] = progress
    task.data = data
    task.result = 'Reload indi-allsky before dark acquisition'
    task.setExpired()
    return True


def capture_controller_available(watchdog, status=None, now=None):
    """Return whether the capture controller has a current heartbeat.

    This intentionally uses only application state, independently of the
    process supervisor used by the installation.
    """
    try:
        watchdog_time = int(watchdog)
    except (TypeError, ValueError):
        return False

    now_time = time.time() if now is None else float(now)
    if now_time > (watchdog_time + CONTROLLER_HEARTBEAT_MAX_AGE_SECONDS):
        return False

    if status is None:
        return True
    try:
        status_value = int(status)
    except (TypeError, ValueError):
        return False
    return status_value not in (constants.STATUS_STOPPING, constants.STATUS_STOPPED)


def determine_capture_restore_state(config, status=None, night=None):
    """Describe the normal image-capture state to restore after maintenance."""
    if config.get('CAPTURE_PAUSE') or status == constants.STATUS_PAUSED:
        return CAPTURE_RESTORE_PAUSED
    if (
            status == constants.STATUS_SLEEPING
            or (night is False and not config.get('DAYTIME_CAPTURE'))
    ):
        return CAPTURE_RESTORE_SLEEPING
    if status == constants.STATUS_RUNNING:
        return CAPTURE_RESTORE_RUNNING
    return CAPTURE_RESTORE_CONTROLLER


def targets_for_strategy(analysis, strategy):
    if strategy == STRATEGY_COMPLETE:
        return tuple(analysis.completion_targets)
    if strategy in (STRATEGY_REFRESH, STRATEGY_REBUILD, STRATEGY_CUSTOM):
        return tuple(analysis.plan.targets)
    raise DarkAutomationError('Unknown dark-library strategy')


def build_execution_groups(analysis, strategy):
    """Turn arbitrary target settings into exact CLI rectangles.

    Completion plans can be irregular because one existing gain may cover only
    some exposure lengths.  Gains are grouped only when their exposure lists
    are identical, so execution never captures an accidental cross product.
    """
    targets = targets_for_strategy(analysis, strategy)
    grouped_cells = {}

    for target in targets:
        group_key = (
            target.capture_profile,
            target.binning,
            target.bit_depth,
            target.width,
            target.height,
            target.temperature,
            target.sources,
        )
        gains = grouped_cells.setdefault(group_key, {})
        gains.setdefault(target.gain, set()).add(target.exposure)

    result = []
    for group_key, gains in grouped_cells.items():
        (
            capture_profile,
            binning,
            bit_depth,
            width,
            height,
            temperature,
            sources,
        ) = group_key
        exposure_groups = {}
        for gain, exposures in gains.items():
            exposure_key = tuple(sorted(float(value) for value in exposures))
            exposure_groups.setdefault(exposure_key, []).append(float(gain))

        for exposures, gain_values in exposure_groups.items():
            gain_values = tuple(sorted(gain_values))
            identity = {
                'capture_profile': capture_profile,
                'binning': binning,
                'bit_depth': bit_depth,
                'width': width,
                'height': height,
                'temperature': temperature,
                'sources': list(sources),
                'gains': list(gain_values),
                'exposures': list(exposures),
            }
            group_id = hashlib.sha256(
                json.dumps(identity, sort_keys=True, separators=(',', ':')).encode('utf-8')
            ).hexdigest()[:16]
            result.append({
                'id': group_id,
                'capture_profile': capture_profile,
                'capture_period': _capture_period(capture_profile),
                'sources': list(sources),
                'source_label': ', '.join(sources),
                'binning': int(binning),
                'bit_depth': bit_depth,
                'width': width,
                'height': height,
                'temperature': temperature,
                'gains': list(gain_values),
                'exposures': list(exposures),
                'target_count': len(gain_values) * len(exposures),
                'enabled': True,
            })

    return sorted(
        result,
        key=lambda group: (
            group['capture_period'],
            group['binning'],
            group['bit_depth'] if group['bit_depth'] is not None else -1,
            group['source_label'],
            group['gains'],
        ),
    )


def execution_preview(
        analysis,
        strategy,
        frame_count=10,
        capture_order='long_first',
        temperature_policy='recommended',
        temperature_source='auto',
        capture_mode=CAPTURE_MODE_SINGLE,
        temperature_delta=DEFAULT_TEMPERATURE_RANGE,
        temperature_target=None,
):
    frame_count = _validate_frame_count(frame_count)
    capture_order = _validate_choice(
        capture_order,
        CAPTURE_ORDERS,
        'Select a valid capture order',
    )
    temperature_policy = _validate_choice(
        temperature_policy,
        TEMPERATURE_POLICIES,
        'Select a valid temperature policy',
    )
    temperature_source = str(temperature_source or 'auto')
    capture_mode = _validate_choice(
        capture_mode,
        CAPTURE_MODES,
        'Select a valid dark capture mode',
    )
    if capture_mode == CAPTURE_MODE_TEMPERATURE_SERIES:
        temperature_delta = _validate_temperature_delta(temperature_delta)
        temperature_target = _validate_temperature_target(temperature_target)
        strategy = STRATEGY_CUSTOM
        groups = [
            group for group in build_execution_groups(analysis, STRATEGY_CUSTOM)
            if group['capture_period'] == 'night'
        ]
    else:
        try:
            temperature_delta = _validate_temperature_delta(temperature_delta)
        except DarkAutomationError:
            temperature_delta = analysis.plan.quality.temperature_range
        temperature_target = None
        groups = build_execution_groups(analysis, strategy)
    for group in groups:
        bit_depth = int(group.get('bit_depth') or 0)
        group['bitmax'] = bit_depth if bit_depth in BITMAX_VALUES else 0
    target_count = sum(group['target_count'] for group in groups)
    temperature_set_count = estimate_temperature_set_count(
        getattr(analysis, 'temperature', None),
        (
            temperature_target
            if capture_mode == CAPTURE_MODE_TEMPERATURE_SERIES
            else None
        ),
        temperature_delta,
    )
    estimate_multiplier = temperature_set_count or 1
    estimated_seconds = (
        estimate_execution_seconds(groups, frame_count, analysis.plan.quality.overhead_seconds)
        * estimate_multiplier
    )
    storage = estimate_execution_storage(groups, frame_count)
    if temperature_set_count and temperature_set_count > 1 and storage['available']:
        working_bytes = storage['peak_bytes'] - storage['library_bytes']
        storage['library_bytes'] *= temperature_set_count
        storage['peak_bytes'] = storage['library_bytes'] + working_bytes
    execution = {
        'strategy': strategy,
        'groups': groups,
        'target_count': target_count,
        'frame_count': frame_count,
        'estimated_seconds': estimated_seconds,
        'estimated_time': format_duration(estimated_seconds),
        'estimated_library_bytes': storage['library_bytes'],
        'estimated_library_storage': format_bytes(storage['library_bytes']),
        'estimated_peak_bytes': storage['peak_bytes'],
        'estimated_peak_storage': format_bytes(storage['peak_bytes']),
        'config_signature': analysis.plan.config_signature,
        'quality': analysis.plan.quality.name,
        'exposure_max': analysis.plan.exposure_max,
        'exposure_step': analysis.plan.exposure_step,
        'capture_order': capture_order,
        'temperature_policy': temperature_policy,
        'temperature_range': analysis.plan.quality.temperature_range,
        'temperature_source': temperature_source,
        'capture_mode': capture_mode,
        'temperature_delta': temperature_delta,
        'temperature_target': temperature_target,
        'temperature_set_count': temperature_set_count,
        'estimate_scope': (
            'per_temperature_set'
            if (
                capture_mode == CAPTURE_MODE_TEMPERATURE_SERIES
                and temperature_set_count is None
            )
            else 'complete_task'
        ),
    }
    return execution


def normalize_execution_request(analysis, capabilities, capture_state, request_data):
    strategy = str(request_data.get('strategy') or STRATEGY_COMPLETE)
    if strategy not in STRATEGIES:
        raise DarkAutomationError('Select a valid capture strategy')

    method = str(request_data.get('method') or 'sigmaclip')
    if method not in METHODS:
        raise DarkAutomationError('Select sigma clipping or average stacking')

    frame_count = _validate_frame_count(request_data.get('frame_count', 10))
    capture_order = _validate_choice(
        request_data.get('capture_order', 'long_first'),
        CAPTURE_ORDERS,
        'Select a valid capture order',
    )
    temperature_policy = _validate_choice(
        request_data.get('temperature_policy', 'recommended'),
        TEMPERATURE_POLICIES,
        'Select a valid temperature policy',
    )
    temperature_source = str(request_data.get('temperature_source') or 'auto')
    capture_mode = _validate_choice(
        request_data.get('capture_mode', CAPTURE_MODE_SINGLE),
        CAPTURE_MODES,
        'Select a valid dark capture mode',
    )
    if capture_mode == CAPTURE_MODE_TEMPERATURE_SERIES:
        temperature_delta = _validate_temperature_delta(
            request_data.get(
                'temperature_delta',
                analysis.plan.quality.temperature_range,
            ),
        )
        temperature_target = _validate_temperature_target(
            request_data.get('temperature_target'),
        )
        strategy = STRATEGY_CUSTOM
    else:
        try:
            temperature_delta = _validate_temperature_delta(
                request_data.get(
                    'temperature_delta',
                    analysis.plan.quality.temperature_range,
                ),
            )
        except DarkAutomationError:
            temperature_delta = analysis.plan.quality.temperature_range
        temperature_target = None
    expected_signature = str(request_data.get('config_signature') or '')
    if expected_signature != analysis.plan.config_signature:
        raise DarkAutomationError(
            'Camera settings changed after this plan was prepared. Refresh the plan and review it again.'
        )

    blueprint = execution_preview(
        analysis,
        strategy,
        frame_count=frame_count,
        capture_order=capture_order,
        temperature_policy=temperature_policy,
        temperature_source=temperature_source,
        capture_mode=capture_mode,
        temperature_delta=temperature_delta,
        temperature_target=temperature_target,
    )
    groups_by_id = {group['id']: group for group in blueprint['groups']}
    if strategy == STRATEGY_CUSTOM and capture_mode == CAPTURE_MODE_SINGLE:
        # A one-run completion plan may contain irregular subsets whose IDs
        # differ from the full custom grid.  Once the user edits one of those
        # rows the UI correctly changes the strategy to custom, but the
        # submitted subset is still a valid part of the current plan.
        completion_blueprint = execution_preview(
            analysis,
            STRATEGY_COMPLETE,
            frame_count=frame_count,
            capture_order=capture_order,
            temperature_policy=temperature_policy,
            temperature_source=temperature_source,
            capture_mode=capture_mode,
            temperature_delta=temperature_delta,
            temperature_target=temperature_target,
        )
        for group in completion_blueprint['groups']:
            groups_by_id.setdefault(group['id'], group)
    requested_groups = request_data.get('groups')
    if requested_groups is None:
        requested_groups = blueprint['groups']
    if not isinstance(requested_groups, list):
        raise DarkAutomationError('The selected capture groups are invalid')

    normalised_groups = []
    seen_group_ids = set()
    planned_exposure_max = max(
        (target.exposure for target in analysis.plan.targets),
        default=capture_state.exposure_max,
    )
    for requested_group in requested_groups:
        if not isinstance(requested_group, dict):
            raise DarkAutomationError('The selected capture groups are invalid')
        if not requested_group.get('enabled', True):
            continue

        group_id = str(requested_group.get('id') or '')
        if group_id in seen_group_ids:
            raise DarkAutomationError('A capture group was submitted more than once')
        seen_group_ids.add(group_id)

        try:
            source_group = groups_by_id[group_id]
        except KeyError:
            raise DarkAutomationError(
                'The capture plan changed. Refresh the plan and review it again.'
            )

        gains = _normalise_numbers(requested_group.get('gains', source_group['gains']), 'gain')
        exposures = _normalise_numbers(
            requested_group.get('exposures', source_group['exposures']),
            'exposure',
        )
        if not gains or not exposures:
            raise DarkAutomationError('Every enabled group needs at least one gain and exposure')

        for gain in gains:
            _validate_gain(gain, capabilities)
        for exposure in exposures:
            _validate_exposure(
                exposure,
                capture_state,
                capabilities,
                planned_exposure_max,
            )

        binning = _validate_binning(
            requested_group.get('binning', source_group['binning']),
            capabilities,
        )
        bitmax = _validate_bitmax(
            requested_group.get('bitmax', source_group.get('bitmax', 0)),
        )

        normalised_group = dict(source_group)
        normalised_group['binning'] = binning
        normalised_group['width'] = capabilities.binned_width(binning)
        normalised_group['height'] = capabilities.binned_height(binning)
        normalised_group['bitmax'] = bitmax
        normalised_group['gains'] = gains
        normalised_group['exposures'] = exposures
        normalised_group['target_count'] = len(gains) * len(exposures)
        normalised_group['enabled'] = True
        normalised_groups.append(normalised_group)

    _validate_unique_targets(normalised_groups)

    target_count = sum(group['target_count'] for group in normalised_groups)
    if target_count < 1:
        if strategy == STRATEGY_COMPLETE and not blueprint['groups']:
            raise DarkAutomationError('The current dark library already covers this recommendation')
        raise DarkAutomationError('Select at least one dark master set to capture')
    if target_count > MAX_MASTER_SETS:
        raise DarkAutomationError(
            'The plan contains more than {0:d} master sets. Reduce the selected gains or exposures.'.format(
                MAX_MASTER_SETS,
            )
        )

    estimated_seconds = estimate_execution_seconds(
        normalised_groups,
        frame_count,
        analysis.plan.quality.overhead_seconds,
    )
    estimate_multiplier = blueprint['temperature_set_count'] or 1
    estimated_seconds *= estimate_multiplier
    storage = estimate_execution_storage(normalised_groups, frame_count)
    if estimate_multiplier > 1 and storage['available']:
        working_bytes = storage['peak_bytes'] - storage['library_bytes']
        storage['library_bytes'] *= estimate_multiplier
        storage['peak_bytes'] = storage['library_bytes'] + working_bytes
    execution = {
        'strategy': strategy,
        'quality': analysis.plan.quality.name,
        'method': method,
        'frame_count': frame_count,
        'config_signature': analysis.plan.config_signature,
        'groups': normalised_groups,
        'target_count': target_count,
        'estimated_seconds': estimated_seconds,
        'estimated_time': format_duration(estimated_seconds),
        'estimated_library_bytes': storage['library_bytes'],
        'estimated_library_storage': format_bytes(storage['library_bytes']),
        'estimated_peak_bytes': storage['peak_bytes'],
        'estimated_peak_storage': format_bytes(storage['peak_bytes']),
        'exposure_max': analysis.plan.exposure_max,
        'exposure_step': analysis.plan.exposure_step,
        'capture_order': capture_order,
        'temperature_policy': temperature_policy,
        'temperature_range': analysis.plan.quality.temperature_range,
        'temperature_source': temperature_source,
        'capture_mode': capture_mode,
        'temperature_delta': temperature_delta,
        'temperature_target': temperature_target,
        'temperature_set_count': blueprint['temperature_set_count'],
        'estimate_scope': blueprint['estimate_scope'],
    }
    execution['plan_signature'] = _execution_signature(execution)
    return execution


def estimate_execution_seconds(groups, frame_count, overhead_seconds=30.0):
    total = 0.0
    for group in groups:
        for exposure in group['exposures']:
            total += len(group['gains']) * (
                (float(exposure) * int(frame_count)) + float(overhead_seconds)
            )
    return total


def recommended_stacking_method(config, groups):
    camera_interface = str(config.get('CAMERA_INTERFACE', ''))
    if not (
            camera_interface.startswith('libcamera_')
            or camera_interface.startswith('mqtt_')
    ):
        return 'sigmaclip'
    libcamera_config = config.get('LIBCAMERA', {}) or {}
    for group in groups:
        if group.get('capture_period') == 'day':
            image_type = str(libcamera_config.get('IMAGE_FILE_TYPE_DAY', 'jpg')).lower()
        else:
            image_type = str(libcamera_config.get('IMAGE_FILE_TYPE', 'jpg')).lower()
        if image_type != 'dng':
            return 'average'
    return 'sigmaclip'


def validate_execution_profiles(config, execution):
    camera_interface = str(config.get('CAMERA_INTERFACE', ''))
    groups = execution.get('groups') or ()
    if not (
            camera_interface.startswith('libcamera_')
            or camera_interface.startswith('mqtt_')
    ):
        return
    libcamera_config = config.get('LIBCAMERA', {}) or {}
    if (
            any(group.get('capture_period') == 'night' for group in groups)
            and libcamera_config.get('AWB_ENABLE')
    ):
        raise DarkAutomationError(
            'Disable nighttime white balance before capturing night darks'
        )
    if (
            recommended_stacking_method(config, groups) == 'average'
            and execution.get('method') != 'average'
    ):
        raise DarkAutomationError(
            'Average stacking is required when any selected libcamera profile uses RGB/JPEG data'
        )


def _execution_signature(execution):
    signature_data = {
        'strategy': execution['strategy'],
        'quality': execution['quality'],
        'method': execution['method'],
        'frame_count': execution['frame_count'],
        'config_signature': execution['config_signature'],
        'exposure_max': execution['exposure_max'],
        'exposure_step': execution['exposure_step'],
        'capture_order': execution['capture_order'],
        'temperature_policy': execution['temperature_policy'],
        'temperature_range': execution['temperature_range'],
        'temperature_source': execution.get('temperature_source', 'auto'),
        'capture_mode': execution['capture_mode'],
        'temperature_delta': execution['temperature_delta'],
        'temperature_target': execution['temperature_target'],
        'groups': [
            {
                'id': group['id'],
                'capture_profile': group['capture_profile'],
                'binning': group['binning'],
                'bit_depth': group.get('bit_depth'),
                'width': group.get('width'),
                'height': group.get('height'),
                'temperature': group.get('temperature'),
                'bitmax': group.get('bitmax', 0),
                'gains': list(group['gains']),
                'exposures': list(group['exposures']),
            }
            for group in execution['groups']
        ],
    }
    return hashlib.sha256(
        json.dumps(signature_data, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()


def estimate_execution_storage(groups, frame_count):
    library_bytes = 0
    largest_temporary_cell = 0
    available = True
    for group in groups:
        if group.get('width') is None or group.get('height') is None:
            available = False
            continue
        width = max(1, int(group['width']))
        height = max(1, int(group['height']))
        bit_depth = int(group.get('bit_depth') or 16)
        bytes_per_pixel = max(1, int(math.ceil(bit_depth / 8.0)))
        # FITS headers and alignment are small relative to image data; 5% is
        # a deliberately simple, conservative allowance for the UI estimate.
        image_bytes = int(math.ceil(width * height * bytes_per_pixel * 1.05))
        target_count = len(group.get('gains') or ()) * len(group.get('exposures') or ())
        library_bytes += target_count * image_bytes * 2  # dark + BPM
        largest_temporary_cell = max(
            largest_temporary_cell,
            image_bytes * (int(frame_count) + 2),
        )
    return {
        'library_bytes': library_bytes if available else None,
        'peak_bytes': (library_bytes + largest_temporary_cell) if available else None,
        'available': available,
    }


def format_duration(seconds):
    seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return '{0:d}h {1:02d}m {2:02d}s'.format(hours, minutes, seconds)


def format_bytes(byte_count):
    if byte_count is None:
        return 'Unavailable'
    value = float(max(0, int(byte_count)))
    units = ('B', 'KiB', 'MiB', 'GiB', 'TiB')
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit == 'B':
                return '{0:d} {1:s}'.format(int(value), unit)
            return '{0:0.1f} {1:s}'.format(value, unit)
        value /= 1024.0


def build_library_catalog(cameras, dark_frames, bad_pixel_maps, current_camera_id=None):
    """Group calibration files into camera, sensor-profile, and temperature layers."""
    camera_frames = {}
    for frame_type, frames in (('dark', dark_frames), ('bpm', bad_pixel_maps)):
        for frame in frames:
            camera_frames.setdefault(int(frame.camera_id), []).append((frame_type, frame))

    catalog = []
    total_bytes = 0
    total_entries = 0
    for camera in cameras:
        typed_frames = camera_frames.get(int(camera.id), [])
        if not typed_frames:
            continue

        temperature_range = camera_temperature_preferences(camera)['temperature_range']
        layer_assignments = _library_layer_assignments(
            typed_frames,
            temperature_range,
        )
        profiles = {}
        active_selection = {'dark_ids': [], 'bpm_ids': []}
        inactive_selection = {'dark_ids': [], 'bpm_ids': []}
        activatable_selection = {'dark_ids': [], 'bpm_ids': []}
        camera_selection = {'dark_ids': [], 'bpm_ids': []}
        camera_bytes = 0
        camera_latest = None
        for frame_type, frame in typed_frames:
            frame_id = int(frame.id)
            selection_key = '{0:s}_ids'.format(frame_type)
            camera_selection[selection_key].append(frame_id)
            eligibility = library_entry_eligibility(frame)
            if bool(frame.active):
                active_selection[selection_key].append(frame_id)
            else:
                inactive_selection[selection_key].append(frame_id)
                if not eligibility['staged']:
                    activatable_selection[selection_key].append(frame_id)

            frame_bytes = _library_frame_bytes(frame)
            camera_bytes += frame_bytes
            create_date = getattr(frame, 'createDate', None)
            if create_date is not None and (
                    camera_latest is None or create_date > camera_latest
            ):
                camera_latest = create_date

            profile_key = _library_profile_key(frame)
            profile = profiles.setdefault(profile_key, {
                'entries': [],
                'layers': {},
                'selection': {'dark_ids': [], 'bpm_ids': []},
                'active_selection': {'dark_ids': [], 'bpm_ids': []},
                'inactive_selection': {'dark_ids': [], 'bpm_ids': []},
                'activatable_selection': {'dark_ids': [], 'bpm_ids': []},
                'size_bytes': 0,
            })
            profile['entries'].append((frame_type, frame))
            profile['selection'][selection_key].append(frame_id)
            if bool(frame.active):
                profile['active_selection'][selection_key].append(frame_id)
            else:
                profile['inactive_selection'][selection_key].append(frame_id)
                if not eligibility['staged']:
                    profile['activatable_selection'][selection_key].append(frame_id)
            profile['size_bytes'] += frame_bytes

            automation_data = _frame_automation_data(frame)
            layer_assignment = layer_assignments[(frame_type, frame_id)]
            layer_key = layer_assignment['key']
            layer = profile['layers'].setdefault(layer_key, {
                'entries': [],
                'master_sets': {},
                'selection': {'dark_ids': [], 'bpm_ids': []},
                'active_selection': {'dark_ids': [], 'bpm_ids': []},
                'inactive_selection': {'dark_ids': [], 'bpm_ids': []},
                'activatable_selection': {'dark_ids': [], 'bpm_ids': []},
                'size_bytes': 0,
                'temperatures': [],
                'latest_date': None,
                'automation': bool(layer_assignment['automation']),
            })
            layer['entries'].append((frame_type, frame))
            layer['selection'][selection_key].append(frame_id)
            if bool(frame.active):
                layer['active_selection'][selection_key].append(frame_id)
            else:
                layer['inactive_selection'][selection_key].append(frame_id)
                if not eligibility['staged']:
                    layer['activatable_selection'][selection_key].append(frame_id)
            layer['size_bytes'] += frame_bytes
            if frame.temp is not None:
                layer['temperatures'].append(float(frame.temp))
            if create_date is not None and (
                    layer['latest_date'] is None or create_date > layer['latest_date']
            ):
                layer['latest_date'] = create_date

            master_key = _library_master_key(frame, automation_data)
            master = layer['master_sets'].setdefault(master_key, {
                'entries': [],
                'selection': {'dark_ids': [], 'bpm_ids': []},
                'active_selection': {'dark_ids': [], 'bpm_ids': []},
                'inactive_selection': {'dark_ids': [], 'bpm_ids': []},
                'activatable_selection': {'dark_ids': [], 'bpm_ids': []},
                'size_bytes': 0,
                'gain': float(frame.gain),
                'exposure': float(frame.exposure),
                'temperature': frame.temp,
                'active': False,
                'active_entry_count': 0,
                'eligibility_reasons': set(),
                'staged_entry_count': 0,
                'latest_date': None,
            })
            master['entries'].append((frame_type, frame))
            master['selection'][selection_key].append(frame_id)
            if bool(frame.active):
                master['active_selection'][selection_key].append(frame_id)
            else:
                master['inactive_selection'][selection_key].append(frame_id)
                if not eligibility['staged']:
                    master['activatable_selection'][selection_key].append(frame_id)
            master['size_bytes'] += frame_bytes
            master['active'] = master['active'] or bool(frame.active)
            if bool(frame.active):
                master['active_entry_count'] += 1
            if eligibility['reason']:
                master['eligibility_reasons'].add(eligibility['reason'])
            if eligibility['staged']:
                master['staged_entry_count'] += 1
            if create_date is not None and (
                    master['latest_date'] is None or create_date > master['latest_date']
            ):
                master['latest_date'] = create_date

        context_profiles = []
        for profile_key, profile in profiles.items():
            bit_depth, binning, width, height = profile_key
            context_layers = []
            for layer in profile['layers'].values():
                master_sets = []
                for master in layer['master_sets'].values():
                    dark_count = len(master['selection']['dark_ids'])
                    bpm_count = len(master['selection']['bpm_ids'])
                    entry_count = dark_count + bpm_count
                    if master['active_entry_count'] == 0:
                        status = 'inactive'
                    elif master['active_entry_count'] == entry_count:
                        status = 'active'
                    else:
                        status = 'mixed'
                    eligibility_reasons = sorted(master['eligibility_reasons'])
                    if len(eligibility_reasons) == 1:
                        eligibility_reason = eligibility_reasons[0]
                        eligibility_reason_label = ELIGIBILITY_REASON_LABELS.get(
                            eligibility_reason,
                            'Eligibility changed',
                        )
                    elif eligibility_reasons:
                        eligibility_reason = 'mixed'
                        eligibility_reason_label = 'Mixed eligibility history'
                    else:
                        eligibility_reason = None
                        eligibility_reason_label = None
                    master_sets.append({
                        'gain': master['gain'],
                        'exposure': master['exposure'],
                        'temperature': master['temperature'],
                        'active': master['active'],
                        'status': status,
                        'staged': master['staged_entry_count'] > 0,
                        'eligibility_reason': eligibility_reason,
                        'eligibility_reason_label': eligibility_reason_label,
                        'paired': dark_count > 0 and bpm_count > 0,
                        'dark_count': dark_count,
                        'bpm_count': bpm_count,
                        'entry_count': entry_count,
                        'size_bytes': master['size_bytes'],
                        'size': format_bytes(master['size_bytes']),
                        'latest_date': master['latest_date'],
                        'selection': _sorted_library_selection(master['selection']),
                        'active_selection': _sorted_library_selection(
                            master['active_selection'],
                        ),
                        'inactive_selection': _sorted_library_selection(
                            master['inactive_selection'],
                        ),
                        'activatable_selection': _sorted_library_selection(
                            master['activatable_selection'],
                        ),
                    })
                master_sets.sort(key=lambda item: (
                    item['gain'],
                    item['exposure'],
                    float('inf') if item['temperature'] is None else item['temperature'],
                ))
                temperatures = layer['temperatures']
                active_master_set_count = sum(
                    1 for item in master_sets if item['status'] == 'active'
                )
                inactive_master_set_count = sum(
                    1 for item in master_sets if item['status'] == 'inactive'
                )
                mixed_master_set_count = sum(
                    1 for item in master_sets if item['status'] == 'mixed'
                )
                context_layers.append({
                    'temperature_label': _library_temperature_label(temperatures),
                    'automation': layer['automation'],
                    'active_count': sum(
                        1 for _frame_type, frame in layer['entries'] if bool(frame.active)
                    ),
                    'entry_count': len(layer['entries']),
                    'master_set_count': len(master_sets),
                    'active_master_set_count': active_master_set_count,
                    'inactive_master_set_count': inactive_master_set_count,
                    'mixed_master_set_count': mixed_master_set_count,
                    'paired_set_count': sum(1 for item in master_sets if item['paired']),
                    'size_bytes': layer['size_bytes'],
                    'size': format_bytes(layer['size_bytes']),
                    'latest_date': layer['latest_date'],
                    'selection': _sorted_library_selection(layer['selection']),
                    'active_selection': _sorted_library_selection(
                        layer['active_selection'],
                    ),
                    'inactive_selection': _sorted_library_selection(
                        layer['inactive_selection'],
                    ),
                    'activatable_selection': _sorted_library_selection(
                        layer['activatable_selection'],
                    ),
                    'master_sets': master_sets,
                })
            context_layers.sort(key=lambda item: (
                -_library_datetime_timestamp(item['latest_date']),
                item['temperature_label'],
            ))
            context_profiles.append({
                'bit_depth': bit_depth,
                'binning': binning,
                'width': width,
                'height': height,
                'entry_count': len(profile['entries']),
                'master_set_count': sum(
                    layer['master_set_count'] for layer in context_layers
                ),
                'active_master_set_count': sum(
                    layer['active_master_set_count'] for layer in context_layers
                ),
                'inactive_master_set_count': sum(
                    layer['inactive_master_set_count'] for layer in context_layers
                ),
                'mixed_master_set_count': sum(
                    layer['mixed_master_set_count'] for layer in context_layers
                ),
                'size_bytes': profile['size_bytes'],
                'size': format_bytes(profile['size_bytes']),
                'selection': _sorted_library_selection(profile['selection']),
                'active_selection': _sorted_library_selection(
                    profile['active_selection'],
                ),
                'inactive_selection': _sorted_library_selection(
                    profile['inactive_selection'],
                ),
                'activatable_selection': _sorted_library_selection(
                    profile['activatable_selection'],
                ),
                'layers': context_layers,
            })
        context_profiles.sort(key=lambda item: (
            item['binning'],
            -int(item['bit_depth'] or 0),
            -(item['width'] or 0),
            -(item['height'] or 0),
        ))

        active_selection = _sorted_library_selection(active_selection)
        inactive_selection = _sorted_library_selection(inactive_selection)
        activatable_selection = _sorted_library_selection(activatable_selection)
        camera_selection = _sorted_library_selection(camera_selection)
        camera_master_set_count = sum(
            profile['master_set_count'] for profile in context_profiles
        )
        total_bytes += camera_bytes
        total_entries += len(typed_frames)
        catalog.append({
            'id': int(camera.id),
            'name': str(camera.name),
            'friendly_name': str(getattr(camera, 'friendlyName', None) or camera.name),
            'current': int(camera.id) == int(current_camera_id or -1),
            'entry_count': len(typed_frames),
            'dark_count': len(camera_selection['dark_ids']),
            'bpm_count': len(camera_selection['bpm_ids']),
            'active_count': sum(1 for _frame_type, frame in typed_frames if bool(frame.active)),
            'inactive_count': (
                len(inactive_selection['dark_ids']) + len(inactive_selection['bpm_ids'])
            ),
            'master_set_count': camera_master_set_count,
            'active_master_set_count': sum(
                profile['active_master_set_count'] for profile in context_profiles
            ),
            'inactive_master_set_count': sum(
                profile['inactive_master_set_count'] for profile in context_profiles
            ),
            'mixed_master_set_count': sum(
                profile['mixed_master_set_count'] for profile in context_profiles
            ),
            'temperature_range': temperature_range,
            'size_bytes': camera_bytes,
            'size': format_bytes(camera_bytes),
            'latest_date': camera_latest,
            'selection': camera_selection,
            'active_selection': active_selection,
            'inactive_selection': inactive_selection,
            'activatable_selection': activatable_selection,
            'profiles': context_profiles,
        })

    catalog.sort(key=lambda item: (
        not item['current'],
        -_library_datetime_timestamp(item['latest_date']),
        item['name'].lower(),
    ))
    return {
        'cameras': catalog,
        'camera_count': len(catalog),
        'entry_count': total_entries,
        'size_bytes': total_bytes,
        'size': format_bytes(total_bytes),
        'selection_batches': [
            {'camera_id': item['id'], 'selection': item['selection']}
            for item in catalog
        ],
        'active_selection_batches': [
            {'camera_id': item['id'], 'selection': item['active_selection']}
            for item in catalog
            if item['active_selection']['dark_ids']
            or item['active_selection']['bpm_ids']
        ],
        'inactive_selection_batches': [
            {'camera_id': item['id'], 'selection': item['inactive_selection']}
            for item in catalog
            if item['inactive_selection']['dark_ids']
            or item['inactive_selection']['bpm_ids']
        ],
        'activatable_selection_batches': [
            {'camera_id': item['id'], 'selection': item['activatable_selection']}
            for item in catalog
            if item['activatable_selection']['dark_ids']
            or item['activatable_selection']['bpm_ids']
        ],
    }


def build_library_partner_index(dark_frames, bad_pixel_maps):
    """Return exact dark/map partners using the same master-set identity as maintenance."""
    groups = {}
    for frame_type, frames in (('dark', dark_frames), ('bpm', bad_pixel_maps)):
        for frame in frames:
            automation_data = _frame_automation_data(frame)
            master_key = (
                int(frame.camera_id),
                _library_master_key(frame, automation_data),
            )
            group = groups.setdefault(master_key, {'dark': [], 'bpm': []})
            group[frame_type].append(int(frame.id))

    partner_index = {}
    for group in groups.values():
        dark_ids = tuple(sorted(set(group['dark'])))
        bpm_ids = tuple(sorted(set(group['bpm'])))
        for frame_id in dark_ids:
            partner_index[('dark', frame_id)] = {
                'partner_type': 'bpm',
                'partner_ids': bpm_ids,
            }
        for frame_id in bpm_ids:
            partner_index[('bpm', frame_id)] = {
                'partner_type': 'dark',
                'partner_ids': dark_ids,
            }
    return partner_index


def select_camera_library_entries(
        models,
        camera_id,
        selection=None,
        expand_master_sets=False,
):
    """Resolve an explicit selection without ever crossing camera boundaries."""
    camera_id = int(camera_id)
    requested = None
    if selection is not None:
        if not isinstance(selection, dict):
            raise DarkAutomationError('The selected library records are invalid')
        requested = {}
        for key in ('dark_ids', 'bpm_ids'):
            values = selection.get(key, ())
            if not isinstance(values, (list, tuple)):
                raise DarkAutomationError('The selected library records are invalid')
            try:
                requested[key] = {int(value) for value in values if int(value) > 0}
            except (TypeError, ValueError):
                raise DarkAutomationError('The selected library records are invalid')
            if len(requested[key]) > 100000:
                raise DarkAutomationError('The selected library contains too many records')

    model_entries_by_type = []
    for model in models:
        model_entries = model.query.filter(model.camera_id == camera_id).all()
        model_entries = [
            entry for entry in model_entries
            if int(getattr(entry, 'camera_id', camera_id)) == camera_id
        ]
        is_dark = 'DarkFrame' in model.__name__
        selection_key = 'dark_ids' if is_dark else 'bpm_ids'
        count_key = 'dark_frames' if is_dark else 'bad_pixel_maps'
        model_entries_by_type.append((selection_key, count_key, model_entries))

    selected_master_keys = None
    if expand_master_sets and requested is not None:
        selected_master_keys = set()
        for selection_key, _count_key, model_entries in model_entries_by_type:
            selected_master_keys.update(
                _library_master_key(entry, _frame_automation_data(entry))
                for entry in model_entries
                if int(getattr(entry, 'id', 0)) in requested[selection_key]
            )

    entries = []
    identities = []
    counts = {'dark_frames': 0, 'bad_pixel_maps': 0}
    resolved_selection = {'dark_ids': [], 'bpm_ids': []}
    for selection_key, count_key, model_entries in model_entries_by_type:
        if requested is not None:
            if selected_master_keys is None:
                model_entries = [
                    entry for entry in model_entries
                    if int(getattr(entry, 'id', 0)) in requested[selection_key]
                ]
            else:
                model_entries = [
                    entry for entry in model_entries
                    if _library_master_key(
                        entry,
                        _frame_automation_data(entry),
                    ) in selected_master_keys
                ]
        entries.extend(model_entries)
        identities.extend(
            _library_entry_identity(entry, selection_key) for entry in model_entries
        )
        resolved_selection[selection_key].extend(
            int(entry.id) for entry in model_entries if getattr(entry, 'id', None) is not None
        )
        counts[count_key] += len(model_entries)

    counts['entries'] = entries
    counts['selection'] = _sorted_library_selection(resolved_selection)
    counts['size_bytes'] = sum(_library_frame_bytes(entry) for entry in entries)
    counts['size'] = format_bytes(counts['size_bytes'])
    counts['signature'] = hashlib.sha256(
        json.dumps(
            sorted(identities, key=lambda item: (item['type'], item['id'])),
            sort_keys=True,
            separators=(',', ':'),
        ).encode('utf-8')
    ).hexdigest()
    return counts


def select_camera_master_sets(models, camera_id, selection):
    """Expand any selected file to its complete camera-scoped master set."""
    return select_camera_library_entries(
        models,
        camera_id,
        selection=selection,
        expand_master_sets=True,
    )


def library_selection_batches_signature(resolved_batches):
    """Sign a normalized set of camera-scoped library selections."""
    identities = [
        {
            'camera_id': int(batch['camera_id']),
            'signature': str(batch['signature']),
        }
        for batch in resolved_batches
    ]
    # Browser selections may arrive in any hierarchy order. Sorting makes the
    # preview signature describe the selection itself, not its click order.
    identities.sort(key=lambda item: item['camera_id'])
    return hashlib.sha256(
        json.dumps(
            identities,
            sort_keys=True,
            separators=(',', ':'),
        ).encode('utf-8')
    ).hexdigest()


def library_entry_eligibility(frame):
    """Return explicit eligibility history while preserving legacy records."""
    automation_data = _frame_automation_data(frame)
    eligibility = dict(automation_data.get('eligibility') or {})
    state = str(eligibility.get('state') or '')
    reason = str(eligibility.get('reason') or '')
    return {
        'state': state or (
            ELIGIBILITY_STATE_ACTIVE if bool(getattr(frame, 'active', False))
            else ELIGIBILITY_STATE_INACTIVE
        ),
        'reason': reason or None,
        'reason_label': ELIGIBILITY_REASON_LABELS.get(reason),
        'source': eligibility.get('source'),
        'changed_utc': eligibility.get('changed_utc'),
        'staged': state == ELIGIBILITY_STATE_STAGED,
    }


def update_library_entries_eligibility(entries, active, changed_utc=None):
    """Apply a manual, reversible eligibility change to resolved master sets."""
    active = bool(active)
    entries = tuple(entries)
    if active and any(library_entry_eligibility(frame)['staged'] for frame in entries):
        raise DarkAutomationError(
            'Files being captured cannot be activated manually. Finish the run or delete them first.'
        )
    changed_utc = changed_utc or _utc_now_text()
    changed = []
    for frame in entries:
        if bool(getattr(frame, 'active', False)) == active:
            continue
        _set_frame_eligibility(
            frame,
            active,
            ELIGIBILITY_REASON_MANUAL_RESTORE if active else ELIGIBILITY_REASON_MANUAL_EXCLUSION,
            source='manual',
            changed_utc=changed_utc,
        )
        changed.append(frame)
    return tuple(changed)


def _library_frame_bytes(frame):
    try:
        file_path = Path(frame.getFilesystemPath())
    except (AttributeError, TypeError, ValueError):
        file_path = None
    if file_path is not None:
        try:
            if not file_path.is_file():
                return 0
            return max(0, int(file_path.stat().st_size))
        except OSError:
            return 0

    try:
        stored_size = int(getattr(frame, 'fileSize', None) or 0)
    except (TypeError, ValueError):
        stored_size = 0
    return max(0, stored_size)


def _library_profile_key(frame):
    return (
        getattr(frame, 'bitdepth', None),
        int(getattr(frame, 'binmode', 1)),
        getattr(frame, 'width', None),
        getattr(frame, 'height', None),
    )


def _library_layer_assignments(typed_frames, temperature_range):
    """Combine nearby capture batches without splitting one run at a fixed boundary."""
    try:
        matching_distance = float(temperature_range)
    except (TypeError, ValueError):
        matching_distance = DEFAULT_TEMPERATURE_RANGE
    if not math.isfinite(matching_distance) or matching_distance <= 0:
        matching_distance = DEFAULT_TEMPERATURE_RANGE

    profile_batches = {}
    for frame_type, frame in typed_frames:
        automation_data = _frame_automation_data(frame)
        generation_id = str(automation_data.get('generation_id') or '')
        if generation_id:
            batch_key = ('generation', generation_id)
        else:
            batch_key = ('legacy',) + _library_master_key(frame, automation_data)
        profile_key = _library_profile_key(frame)
        batch = profile_batches.setdefault(profile_key, {}).setdefault(batch_key, {
            'entries': [],
            'temperatures': [],
            'automation': bool(generation_id),
        })
        batch['entries'].append((frame_type, frame))
        if getattr(frame, 'temp', None) is not None:
            batch['temperatures'].append(float(frame.temp))

    assignments = {}
    for profile_index, batches in enumerate(profile_batches.values()):
        recorded_batches = [batch for batch in batches.values() if batch['temperatures']]
        recorded_batches.sort(key=lambda batch: (
            min(batch['temperatures']),
            max(batch['temperatures']),
        ))
        clusters = []
        for batch in recorded_batches:
            batch_minimum = min(batch['temperatures'])
            batch_maximum = max(batch['temperatures'])
            if clusters:
                cluster = clusters[-1]
                combined_minimum = min(cluster['minimum'], batch_minimum)
                combined_maximum = max(cluster['maximum'], batch_maximum)
            else:
                combined_minimum = batch_minimum
                combined_maximum = batch_maximum
            if clusters and (combined_maximum - combined_minimum) < matching_distance:
                cluster['batches'].append(batch)
                cluster['minimum'] = combined_minimum
                cluster['maximum'] = combined_maximum
            else:
                clusters.append({
                    'batches': [batch],
                    'minimum': batch_minimum,
                    'maximum': batch_maximum,
                })

        unrecorded_batches = [
            batch for batch in batches.values() if not batch['temperatures']
        ]
        if unrecorded_batches:
            clusters.append({
                'batches': unrecorded_batches,
                'minimum': None,
                'maximum': None,
            })

        for cluster_index, cluster in enumerate(clusters):
            cluster_key = ('temperature-group', profile_index, cluster_index)
            automation = any(batch['automation'] for batch in cluster['batches'])
            for batch in cluster['batches']:
                for frame_type, frame in batch['entries']:
                    assignments[(frame_type, int(frame.id))] = {
                        'key': cluster_key,
                        'automation': automation,
                    }
    return assignments


def _library_temperature_label(temperatures):
    if not temperatures:
        return 'Temperature not recorded'
    minimum = min(temperatures)
    maximum = max(temperatures)
    if abs(maximum - minimum) <= 0.05:
        return '{0:0.1f}°C'.format(minimum)
    return '{0:0.1f} to {1:0.1f}°C'.format(minimum, maximum)


def _library_master_key(frame, automation_data):
    generation_id = str(automation_data.get('generation_id') or '')
    common = (
        getattr(frame, 'bitdepth', None),
        int(getattr(frame, 'binmode', 1)),
        getattr(frame, 'width', None),
        getattr(frame, 'height', None),
        round(float(frame.gain), 6),
        round(float(frame.exposure), 6),
    )
    if generation_id:
        return ('automation', generation_id) + common
    create_date = getattr(frame, 'createDate', None)
    create_key = create_date.isoformat() if create_date is not None else ''
    temperature = getattr(frame, 'temp', None)
    temperature_key = None if temperature is None else round(float(temperature), 3)
    return ('legacy', create_key, temperature_key) + common


def _sorted_library_selection(selection):
    return {
        'dark_ids': sorted(set(int(value) for value in selection.get('dark_ids', ()))),
        'bpm_ids': sorted(set(int(value) for value in selection.get('bpm_ids', ()))),
    }


def _library_datetime_timestamp(value):
    if value is None:
        return 0.0
    try:
        return float(value.timestamp())
    except (AttributeError, OSError, OverflowError, ValueError):
        return 0.0


def _library_entry_identity(entry, selection_key):
    create_date = getattr(entry, 'createDate', None)
    return {
        'type': selection_key,
        'id': int(getattr(entry, 'id', 0)),
        'camera_id': int(getattr(entry, 'camera_id', 0)),
        'filename': str(getattr(entry, 'filename', '') or ''),
        'create_date': create_date.isoformat() if create_date is not None else '',
        'active': bool(getattr(entry, 'active', False)),
        'bit_depth': getattr(entry, 'bitdepth', None),
        'gain': float(getattr(entry, 'gain', 0.0)),
        'exposure': float(getattr(entry, 'exposure', 0.0)),
        'binning': int(getattr(entry, 'binmode', 1)),
        'temperature': getattr(entry, 'temp', None),
        'width': getattr(entry, 'width', None),
        'height': getattr(entry, 'height', None),
    }


def _completed_master_details(value):
    """Return compact, ordered details for committed dark/BPM master pairs."""
    if not isinstance(value, (list, tuple)):
        return []

    details = []
    for raw_detail in value:
        if not isinstance(raw_detail, dict):
            continue
        detail = {
            'sequence': len(details) + 1,
            'capture_profile': str(raw_detail.get('capture_profile') or ''),
            'gain': raw_detail.get('gain'),
            'exposure': raw_detail.get('exposure'),
            'binning': raw_detail.get('binning'),
            'temperature': raw_detail.get('temperature'),
            'frame_count': raw_detail.get('frame_count'),
            'temperature_set': raw_detail.get('temperature_set'),
            'completed_utc': str(raw_detail.get('completed_utc') or ''),
            'duration_seconds': raw_detail.get('duration_seconds'),
        }
        details.append(detail)
    return details


def _planned_remaining_seconds(
        task_data,
        progress,
        completed_details,
        total,
        completed,
        frame_count,
        fractional_cell,
):
    """Estimate remaining work without treating long and short masters equally."""
    estimated_seconds = float(task_data.get('estimated_seconds') or 0.0)
    if total <= 0 or frame_count <= 0 or estimated_seconds <= 0:
        return None

    per_cycle_sets = 0
    per_cycle_capture_seconds = 0.0
    for group in task_data.get('groups') or ():
        if not isinstance(group, dict):
            return None
        gains = group.get('gains') or ()
        try:
            exposures = {float(exposure) for exposure in group.get('exposures') or ()}
        except (AttributeError, TypeError, ValueError):
            return None
        if not gains or not exposures or any(
                not math.isfinite(exposure) or exposure <= 0
                for exposure in exposures
        ):
            return None
        per_cycle_sets += len(gains) * len(exposures)
        per_cycle_capture_seconds += len(gains) * sum(exposures) * frame_count
    if per_cycle_sets <= 0 or total % per_cycle_sets != 0:
        return None

    planned_capture_seconds = (
        per_cycle_capture_seconds * (total // per_cycle_sets)
    )
    nominal_overhead = max(
        0.0,
        (estimated_seconds - planned_capture_seconds) / total,
    )
    completed_count = min(max(0, int(completed)), total)
    if len(completed_details) < completed_count:
        return None

    completed_capture_seconds = 0.0
    observed_overheads = []
    completed_detail_start = len(completed_details) - completed_count
    for detail_index, detail in enumerate(completed_details):
        try:
            exposure = float(detail.get('exposure'))
            detail_frame_count = int(detail.get('frame_count') or frame_count)
        except (TypeError, ValueError):
            return None
        if (
                not math.isfinite(exposure)
                or exposure <= 0
                or detail_frame_count <= 0
        ):
            return None
        capture_seconds = exposure * detail_frame_count
        if detail_index >= completed_detail_start:
            completed_capture_seconds += capture_seconds
        try:
            duration = float(detail.get('duration_seconds'))
        except (TypeError, ValueError):
            continue
        if math.isfinite(duration) and duration >= 0:
            observed_overheads.append(max(0.0, duration - capture_seconds))

    adjusted_overhead = (
        (nominal_overhead * ETA_OVERHEAD_PRIOR_SETS) + sum(observed_overheads)
    ) / (ETA_OVERHEAD_PRIOR_SETS + len(observed_overheads))
    current_capture_seconds = 0.0
    if completed_count < total and fractional_cell > 0:
        try:
            current_exposure = float(progress.get('current_exposure'))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(current_exposure) or current_exposure <= 0:
            return None
        current_capture_seconds = current_exposure * frame_count * fractional_cell

    remaining_capture_seconds = max(
        0.0,
        planned_capture_seconds - completed_capture_seconds - current_capture_seconds,
    )
    remaining_master_sets = max(0.0, total - completed_count - fractional_cell)
    remaining_seconds = (
        remaining_capture_seconds + (remaining_master_sets * adjusted_overhead)
    )
    return max(0, int(round(remaining_seconds)))


def task_requires_progress(task_data):
    """Return whether a task should replace the normal page with progress."""
    task_data = task_data or {}
    task_status = task_data.get('status')
    if task_status in ACTIVE_STATUSES:
        return True
    return (
        task_status in TERMINAL_STATUSES
        and not task_data.get('capture_restored')
    )


def _protect_cancel_requested_progress(data, progress):
    """Keep accepted cancellation authoritative over stale child progress."""
    progress = dict(progress or {})
    if data.get('status') == 'cancel_requested':
        progress['phase'] = 'cancel_requested'
        progress['message'] = CANCEL_REQUESTED_MESSAGE
    return progress


def task_public_status(task):
    data = dict(task.data or {})
    progress = _protect_cancel_requested_progress(data, data.get('progress'))
    completed_master_details = _completed_master_details(
        progress.get('completed_master_details')
    )
    per_set_total = int(data.get('target_count') or progress.get('total_master_sets') or 0)
    raw_completed = int(progress.get('completed_master_sets') or 0)
    planned_temperature_sets = progress.get('planned_temperature_sets')
    if planned_temperature_sets is None:
        planned_temperature_sets = data.get('temperature_set_count')
    target_temperature = progress.get('target_temperature')
    if target_temperature is None:
        target_temperature = data.get('temperature_target')
    if (
            data.get('capture_mode') == CAPTURE_MODE_TEMPERATURE_SERIES
            and planned_temperature_sets
    ):
        planned_temperature_sets = int(planned_temperature_sets)
        temperature_set = max(1, int(progress.get('temperature_set') or 1))
        total = per_set_total * planned_temperature_sets
        completed = min(total, ((temperature_set - 1) * per_set_total) + raw_completed)
    else:
        total = per_set_total
        completed = raw_completed
    frame_count = int(progress.get('current_frame_count') or data.get('frame_count') or 0)
    current_frame = int(progress.get('current_frame') or 0)
    fractional_cell = 0.0
    if frame_count > 0 and current_frame > 0 and progress.get('phase') in ('capturing', 'stacking'):
        fractional_cell = min(0.95, current_frame / frame_count)
    progress_units = min(float(total), completed + fractional_cell)
    if data.get('status') == 'success':
        percent = 100.0
    elif total <= 0:
        percent = 0.0
    else:
        percent = min(100.0, (progress_units / total) * 100.0)

    elapsed_seconds = _elapsed_seconds(data.get('started_utc'))
    estimated_seconds = float(data.get('estimated_seconds') or 0.0)
    estimate_elapsed = elapsed_seconds
    if (
            data.get('capture_mode') == CAPTURE_MODE_TEMPERATURE_SERIES
            and not planned_temperature_sets
    ):
        estimate_elapsed = _elapsed_seconds(progress.get('temperature_set_started_utc'))
    planned_remaining_seconds = _planned_remaining_seconds(
        data,
        progress,
        completed_master_details,
        total,
        completed,
        frame_count,
        fractional_cell,
    )
    if data.get('status') == 'success':
        remaining_seconds = 0
    elif planned_remaining_seconds is not None:
        remaining_seconds = planned_remaining_seconds
    elif total > 0 and progress_units > 0 and estimate_elapsed > 0:
        remaining_seconds = max(
            0,
            int(round(estimate_elapsed * (total - progress_units) / progress_units)),
        )
    else:
        remaining_seconds = max(0, int(round(estimated_seconds - estimate_elapsed)))
    return {
        'task_id': task.id,
        'status': data.get('status', str(task.state.value).lower()),
        'phase': progress.get('phase', data.get('status', 'queued')),
        'message': progress.get('message') or data.get('message') or '',
        'error': data.get('error'),
        'strategy': data.get('strategy'),
        'quality': data.get('quality'),
        'method': data.get('method'),
        'operation': data.get('operation', 'capture'),
        'removal_label': data.get('removal_label'),
        'removal_entry_count': data.get('removal_entry_count'),
        'removal_size_bytes': data.get('removal_size_bytes'),
        'capture_mode': data.get('capture_mode', CAPTURE_MODE_SINGLE),
        'frame_count': data.get('frame_count'),
        'target_count': total,
        'completed_master_sets': completed,
        'completed_master_details': completed_master_details,
        'percent': round(percent, 1),
        'current_gain': progress.get('current_gain'),
        'current_exposure': progress.get('current_exposure'),
        'current_frame': progress.get('current_frame'),
        'current_frame_count': progress.get('current_frame_count'),
        'current_binning': progress.get('current_binning'),
        'resolved_width': progress.get('resolved_width'),
        'resolved_height': progress.get('resolved_height'),
        'current_temperature': progress.get('current_temperature'),
        'next_temperature': progress.get('next_temperature'),
        'target_temperature': target_temperature,
        'completed_temperature_sets': progress.get('completed_temperature_sets', 0),
        'planned_temperature_sets': planned_temperature_sets,
        'temperature_range': data.get('temperature_range', DEFAULT_TEMPERATURE_RANGE),
        'temperature_delta': data.get('temperature_delta'),
        'temperature_source': data.get('temperature_source', 'auto'),
        'temperature_source_label': progress.get('temperature_source'),
        'estimated_time': data.get('estimated_time'),
        'estimated_library_storage': data.get('estimated_library_storage'),
        'estimated_peak_storage': data.get('estimated_peak_storage'),
        'elapsed_seconds': elapsed_seconds,
        'elapsed_time': format_duration(elapsed_seconds),
        'remaining_seconds': remaining_seconds,
        'remaining_time': format_duration(remaining_seconds),
        'started_utc': data.get('started_utc'),
        'completed_utc': data.get('completed_utc'),
        'capture_restored': data.get('capture_restored', False),
        'generation_id': data.get('generation_id'),
        'review_required': data.get('status') == 'review_required',
        'diagnostic_log': data.get('diagnostic_log'),
        'failed_group': data.get('failed_group'),
        'deleted_dark_frames': data.get('deleted_dark_frames'),
        'deleted_bad_pixel_maps': data.get('deleted_bad_pixel_maps'),
        'deleted_master_files': data.get('deleted_master_files'),
        'cleanup_warnings': data.get('cleanup_warnings') or [],
    }


def _monitor_capture_child(
        app,
        task_id,
        child,
        progress_path,
        update_data,
        progress_context,
        stop_requested,
):
    cancel_sent_at = None
    last_published = 0.0
    last_progress = {}
    while child.poll() is None:
        cancelled = _task_cancelled(app, task_id) or stop_requested()
        if cancelled and cancel_sent_at is None:
            child.send_signal(signal.SIGINT)
            cancel_sent_at = time.monotonic()
        elif cancelled and time.monotonic() - cancel_sent_at > 60.0:
            _kill_process_group(child)
        elif cancelled and time.monotonic() - cancel_sent_at > 30.0:
            _terminate_process_group(child)

        child_progress = _read_progress(progress_path)
        if child_progress:
            last_progress = child_progress
        now = time.monotonic()
        if now - last_published >= 1.0:
            with app.app_context():
                update_data(progress=_overall_progress(last_progress, *progress_context))
            last_published = now
        time.sleep(0.5)

    final_progress = _read_progress(progress_path)
    if final_progress:
        last_progress = final_progress
    return child.returncode, last_progress


def run_task(app, task_id, repository_root, stop_requested=None):
    """Execute one validated task inside the capture controller.

    The controller has already stopped its workers before calling this
    function.  Each child invocation receives one exact rectangular target
    group, while this process remains responsible for cancellation, durable
    progress, and the final task state.
    """
    from .capture_state import CameraCapabilities
    from .capture_state import build_effective_capture_state
    from .config import IndiAllSkyConfig
    from .temperature import temperature_source_signature
    from .flask import db
    from .flask.models import IndiAllSkyDbBadPixelMapTable
    from .flask.models import IndiAllSkyDbCameraTable
    from .flask.models import IndiAllSkyDbDarkFrameTable
    from .flask.models import IndiAllSkyDbTaskQueueTable
    from .flask.models import TaskQueueState

    repository_root = Path(repository_root).resolve()
    child_script = repository_root.joinpath('darks_automation.py')
    darks_dir = repository_root.joinpath('indi_allsky', 'html', 'images', 'darks')
    stop_requested = stop_requested or (lambda: False)
    def load_task():
        db.session.expire_all()
        task = IndiAllSkyDbTaskQueueTable.query.filter_by(id=int(task_id)).one()
        return task, dict(task.data or {})

    def update_data(changes=None, progress=None, state=None, result=None):
        task, data = load_task()
        if changes:
            data.update(changes)
        if progress:
            current_progress = dict(data.get('progress') or {})
            current_progress.update(progress)
            current_progress['heartbeat_utc'] = _utc_now_text()
            data['progress'] = _protect_cancel_requested_progress(
                data,
                current_progress,
            )
        task.data = data
        if state is not None:
            task.state = state
        if result is not None:
            task.result = str(result)[:255]
        db.session.commit()
        return data

    try:
        with app.app_context():
            task, task_data = load_task()
            if task_data.get('cancel_requested'):
                raise DarkAutomationCancelled('Dark capture was cancelled before it started')

            if task_data.get('operation') == 'flush':
                removal_label = str(
                    task_data.get('removal_label') or 'selected dark-library records'
                )
                update_data(
                    changes={
                        'status': 'running',
                        'started_utc': _utc_now_text(),
                        'error': None,
                    },
                    progress={
                        'phase': 'removing_library',
                        'message': 'Normal capture is paused; deleting {0:s}.'.format(
                            removal_label,
                        ),
                    },
                    state=TaskQueueState.RUNNING,
                )
                removal_batches = task_data.get('removal_batches')
                if removal_batches:
                    deletion = flush_library_batches(
                        db,
                        (IndiAllSkyDbDarkFrameTable, IndiAllSkyDbBadPixelMapTable),
                        removal_batches,
                    )
                else:
                    deletion = flush_camera_library(
                        db,
                        (IndiAllSkyDbDarkFrameTable, IndiAllSkyDbBadPixelMapTable),
                        int(task_data['camera_id']),
                        selection=task_data.get('removal_selection'),
                        expected_signature=task_data.get('removal_selection_signature'),
                    )
                update_data(
                    changes={
                        'status': 'success',
                        'completed_utc': _utc_now_text(),
                        'capture_restored': False,
                        'deleted_dark_frames': deletion['dark_frames'],
                        'deleted_bad_pixel_maps': deletion['bad_pixel_maps'],
                        'deleted_master_files': deletion['files'],
                        'cleanup_warnings': deletion['warnings'],
                    },
                    progress={
                        'phase': 'restoring_capture',
                        'message': 'Selected library records deleted; restarting normal capture.',
                    },
                    state=TaskQueueState.SUCCESS,
                    result='Selected dark-library records deleted',
                )
                return 'success'

            cover_confirmed_utc = task_data.get('camera_covered_confirmed_utc')
            if (
                    not cover_confirmed_utc
                    or _elapsed_seconds(cover_confirmed_utc) > COVER_CONFIRMATION_MAX_AGE_SECONDS
            ):
                raise DarkAutomationError(
                    'The camera-cover confirmation expired before capture started. '
                    'Confirm that the camera is still fully covered and start again.'
                )

            camera_id = int(task_data['camera_id'])
            camera = IndiAllSkyDbCameraTable.query.filter_by(id=camera_id).one()
            expected_camera_uuid = str(task_data.get('camera_uuid') or '')
            if expected_camera_uuid and str(camera.uuid or '') != expected_camera_uuid:
                raise DarkAutomationReviewRequired(
                    'The selected camera changed before capture started. Review the revised plan.'
                )
            config_obj = IndiAllSkyConfig()
            if (
                    task_data.get('config_id') is not None
                    and int(config_obj.config_id) != int(task_data['config_id'])
            ):
                raise DarkAutomationReviewRequired(
                    'The saved configuration changed before capture started. '
                    'Reload indi-allsky, then review the updated plan; no dark frames were taken.'
                )
            config = config_obj.config
            if config.get('IMAGE_FOLDER'):
                darks_dir = Path(config['IMAGE_FOLDER']).absolute().joinpath('darks')
            if (
                    task_data.get('temperature_source_signature')
                    and temperature_source_signature(config)
                    != task_data.get('temperature_source_signature')
            ):
                raise DarkAutomationReviewRequired(
                    'The configured temperature sources changed before capture started. '
                    'Review the revised plan; no dark frames were taken.'
                )
            capabilities = CameraCapabilities.from_camera(camera)
            if (
                    task_data.get('capability_signature')
                    and capabilities.signature != task_data.get('capability_signature')
            ):
                raise DarkAutomationReviewRequired(
                    'Stored camera capabilities changed before capture started. Review the revised plan.'
                )
            capture_state = build_effective_capture_state(
                config,
                capabilities,
                exposure_step=task_data.get('exposure_step', 5.0),
                exposure_max=task_data.get('exposure_max'),
            )
            if capture_state.config_signature != task_data.get('config_signature'):
                raise DarkAutomationReviewRequired(
                    'Camera settings changed before capture started. Review the revised plan; no dark frames were taken.'
                )

            manifest_base = {
                'automation': True,
                'task_id': int(task_id),
                'generation_id': str(task_data['generation_id']),
                'config_signature': str(task_data['config_signature']),
                'plan_signature': str(task_data['plan_signature']),
                'capability_signature': capabilities.signature,
                'expected_capabilities': capabilities.to_dict(),
                'expected_camera_uuid': expected_camera_uuid,
                'expected_camera_name': str(camera.name or ''),
                'expected_camera_driver': str(camera.driver or ''),
                'strategy': str(task_data['strategy']),
                'quality': str(task_data['quality']),
                'method': str(task_data['method']),
                'frame_count': int(task_data['frame_count']),
                'capture_order': str(task_data.get('capture_order') or 'long_first'),
                'exposure_max': float(task_data['exposure_max']),
                'exposure_step': float(task_data['exposure_step']),
                'temperature_range': float(
                    task_data.get('temperature_range', DEFAULT_TEMPERATURE_RANGE)
                ),
                'temperature_delta': float(
                    task_data.get('temperature_delta', DEFAULT_TEMPERATURE_RANGE)
                ),
                'temperature_source': str(task_data.get('temperature_source') or 'auto'),
                'stage_inactive': True,
            }

            update_data(
                changes={
                    'status': 'running',
                    'started_utc': _utc_now_text(),
                    'error': None,
                },
                progress={
                    'phase': 'preparing_camera',
                    'message': 'Capture is paused; preparing the camera.',
                    'completed_master_sets': 0,
                    'completed_master_details': [],
                    'total_master_sets': int(task_data['target_count']),
                },
                state=TaskQueueState.RUNNING,
            )

        if task_data.get('capture_mode') == CAPTURE_MODE_TEMPERATURE_SERIES:
            with tempfile.TemporaryDirectory(prefix='indi-allsky-dark-temperature-') as temporary_dir:
                temporary_path = Path(temporary_dir)
                progress_path = temporary_path.joinpath('progress.json')
                log_path = temporary_path.joinpath('capture.log')
                manifest_path = temporary_path.joinpath('manifest.json')
                manifest = dict(manifest_base)
                manifest.update({
                    'temperature_series': True,
                    'temperature_delta': float(task_data['temperature_delta']),
                    'temperature_target': task_data.get('temperature_target'),
                    'progress_file': str(progress_path),
                    'groups': list(task_data['groups']),
                })
                _write_json_file(manifest_path, manifest)
                command = build_dark_command(
                    sys.executable,
                    child_script,
                    manifest_path,
                )

                with log_path.open('w', encoding='utf-8', errors='replace') as log_file:
                    child = subprocess.Popen(
                        command,
                        cwd=str(repository_root),
                        stdout=log_file,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )

                return_code, last_progress = _monitor_capture_child(
                    app, task_id, child, progress_path, update_data,
                    (0, int(task_data['target_count']), 1, 1),
                    stop_requested,
                )
                with app.app_context():
                    update_data(progress=_overall_progress(
                        last_progress,
                        0,
                        int(task_data['target_count']),
                        1,
                        1,
                    ))
                if _task_cancelled(app, task_id) or stop_requested() or return_code == 130:
                    raise DarkAutomationCancelled(
                        'Temperature-series dark capture was stopped; completed master sets remain active.'
                    )
                if return_code == 75 or last_progress.get('phase') == 'review_required':
                    raise DarkAutomationReviewRequired(
                        last_progress.get('message')
                        or 'Live camera capabilities changed. Review the revised plan.'
                    )
                if return_code == 0 and task_data.get('temperature_target') is not None:
                    with app.app_context():
                        update_data(
                            changes={
                                'status': 'success',
                                'completed_utc': _utc_now_text(),
                                'capture_restored': False,
                                'activated_master_files': int(
                                    last_progress.get('activated_master_files') or 0
                                ),
                            },
                            progress={
                                'phase': 'restoring_capture',
                                'message': (
                                    'Target sensor temperature reached; restarting normal capture.'
                                ),
                            },
                            state=TaskQueueState.SUCCESS,
                            result='Temperature-series dark library complete',
                        )
                    return 'success'
                diagnostic_log = _read_log_tail(log_path, line_count=40, max_chars=8000)
                with app.app_context():
                    update_data(changes={
                        'diagnostic_log': diagnostic_log,
                        'failed_group': 'temperature_series',
                    })
                if return_code == 0:
                    raise DarkAutomationError('Temperature-series capture ended unexpectedly')
                raise DarkAutomationError(
                    'Temperature-series dark capture stopped: {0:s}'.format(
                        _log_error_summary(diagnostic_log),
                    )
                )

        completed_offset = 0
        completed_master_details = []
        groups = list(task_data['groups'])
        with tempfile.TemporaryDirectory(prefix='indi-allsky-dark-automation-') as temporary_dir:
            temporary_path = Path(temporary_dir)
            for group_index, group in enumerate(groups, start=1):
                if _task_cancelled(app, task_id) or stop_requested():
                    raise DarkAutomationCancelled('Dark capture was cancelled')

                progress_path = temporary_path.joinpath('progress-{0:d}.json'.format(group_index))
                log_path = temporary_path.joinpath('capture-{0:d}.log'.format(group_index))
                manifest_path = temporary_path.joinpath('manifest-{0:d}.json'.format(group_index))
                manifest = dict(manifest_base)
                manifest.update({
                    'group_id': str(group['id']),
                    'capture_profile': str(group['capture_profile']),
                    'capture_period': str(group['capture_period']),
                    'binning': int(group['binning']),
                    'bit_depth': group.get('bit_depth'),
                    'width': group.get('width'),
                    'height': group.get('height'),
                    'temperature': group.get('temperature'),
                    'bitmax': int(group.get('bitmax') or 0),
                    'gains': list(group['gains']),
                    'exposures': list(group['exposures']),
                    'progress_file': str(progress_path),
                })
                _write_json_file(manifest_path, manifest)
                command = build_dark_command(
                    sys.executable,
                    child_script,
                    manifest_path,
                )

                with log_path.open('w', encoding='utf-8', errors='replace') as log_file:
                    child = subprocess.Popen(
                        command,
                        cwd=str(repository_root),
                        stdout=log_file,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )

                return_code, last_progress = _monitor_capture_child(
                    app, task_id, child, progress_path, update_data,
                    (
                        completed_offset,
                        int(task_data['target_count']),
                        group_index,
                        len(groups),
                        tuple(completed_master_details),
                    ),
                    stop_requested,
                )
                group_progress = _overall_progress(
                    last_progress,
                    completed_offset,
                    int(task_data['target_count']),
                    group_index,
                    len(groups),
                    completed_master_details,
                )
                with app.app_context():
                    update_data(progress=group_progress)
                completed_master_details = list(
                    group_progress.get('completed_master_details') or ()
                )
                group_count = int(group['target_count'])
                if return_code != 0:
                    if _task_cancelled(app, task_id) or stop_requested() or return_code == 130:
                        raise DarkAutomationCancelled('Dark capture was cancelled')
                    if return_code == 75 or last_progress.get('phase') == 'review_required':
                        raise DarkAutomationReviewRequired(
                            last_progress.get('message')
                            or 'Live camera capabilities changed. Review the revised plan.'
                        )
                    diagnostic_log = _read_log_tail(log_path, line_count=40, max_chars=8000)
                    with app.app_context():
                        update_data(changes={
                            'diagnostic_log': diagnostic_log,
                            'failed_group': group_index,
                        })
                    raise DarkAutomationError(
                        'Dark capture stopped in group {0:d}: {1:s}'.format(
                            group_index,
                            _log_error_summary(diagnostic_log),
                        )
                    )

                resolved_width = last_progress.get('resolved_width')
                resolved_height = last_progress.get('resolved_height')
                if resolved_width is None or resolved_height is None:
                    raise DarkAutomationError(
                        'The camera did not report the captured frame dimensions for group {0:d}'.format(
                            group_index,
                        )
                    )
                group['width'] = int(resolved_width)
                group['height'] = int(resolved_height)
                task_data['groups'] = groups

                completed_offset += group_count
                with app.app_context():
                    update_data(changes={'groups': groups}, progress={
                        'phase': 'capturing',
                        'message': 'Completed capture group {0:d} of {1:d}.'.format(
                            group_index,
                            len(groups),
                        ),
                        'completed_master_sets': completed_offset,
                        'completed_master_details': list(completed_master_details),
                        'total_master_sets': int(task_data['target_count']),
                        'current_gain': None,
                        'current_exposure': None,
                        'current_frame': None,
                        'current_frame_count': int(task_data['frame_count']),
                        'current_binning': None,
                        'resolved_width': int(resolved_width),
                        'resolved_height': int(resolved_height),
                        'current_temperature': None,
                    })

        with app.app_context():
            update_data(progress={
                'phase': 'activating_library',
                'message': 'Verifying the completed library generation.',
            })
            activation = _activate_generation(
                db,
                (IndiAllSkyDbDarkFrameTable, IndiAllSkyDbBadPixelMapTable),
                task_data,
            )

            update_data(
                changes={
                    'status': 'success',
                    'completed_utc': _utc_now_text(),
                    'capture_restored': False,
                    'activated_master_files': activation['activated'],
                    'retired_master_files': activation['deactivated'],
                },
                progress={
                    'phase': 'restoring_capture',
                    'message': 'Dark library complete; restarting normal capture.',
                    'completed_master_sets': int(task_data['target_count']),
                    'total_master_sets': int(task_data['target_count']),
                },
                state=TaskQueueState.SUCCESS,
                result='Dark library capture complete',
            )
        return 'success'
    except DarkAutomationCancelled as error:
        with app.app_context():
            update_data(
                changes={
                    'status': 'cancelled',
                    'completed_utc': _utc_now_text(),
                    'error': None,
                    'message': str(error),
                },
                progress={
                    'phase': 'restoring_capture',
                    'message': (
                        'Cancellation confirmed; completed master sets remain active; '
                        'restarting normal capture.'
                    ),
                },
                state=TaskQueueState.EXPIRED,
                result='Dark library capture cancelled',
            )
        return 'cancelled'
    except DarkAutomationReviewRequired as error:
        with app.app_context():
            _review_task, review_data = load_task()
            removal_review = review_data.get('operation') == 'flush'
            update_data(
                changes={
                    'status': 'review_required',
                    'completed_utc': _utc_now_text(),
                    'error': str(error)[:1000],
                    'requires_review': True,
                },
                progress={
                    'phase': 'restoring_capture',
                    'message': (
                        'The selected library records changed; restarting normal capture '
                        'before you preview the deletion again.'
                        if removal_review else
                        'The camera changed; restarting normal capture before you review the plan.'
                    ),
                },
                state=TaskQueueState.EXPIRED,
                result=(
                    'Dark-library deletion requires review'
                    if removal_review else 'Dark capture plan requires review'
                ),
            )
        return 'review_required'
    except Exception as error:
        with app.app_context():
            update_data(
                changes={
                    'status': 'failed',
                    'completed_utc': _utc_now_text(),
                    'error': str(error)[:1000],
                },
                progress={
                    'phase': 'restoring_capture',
                    'message': (
                        'Dark capture stopped; completed master sets remain active; '
                        'restarting normal capture.'
                    ),
                },
                state=TaskQueueState.FAILED,
                result=str(error),
            )
        return 'failed'
    finally:
        try:
            with app.app_context():
                cleanup = cleanup_interrupted_capture_artifacts(
                    db,
                    (IndiAllSkyDbDarkFrameTable, IndiAllSkyDbBadPixelMapTable),
                    darks_dir,
                    task_ids=(task_id,),
                )
                cleanup_changes = {}
                if cleanup['database_rows']:
                    cleanup_changes['discarded_incomplete_database_rows'] = cleanup[
                        'database_rows'
                    ]
                if cleanup['files']:
                    cleanup_changes['discarded_incomplete_files'] = cleanup['files']
                if cleanup['temporary_directories']:
                    cleanup_changes['discarded_temporary_directories'] = cleanup[
                        'temporary_directories'
                    ]
                if cleanup['warnings']:
                    _cleanup_task, cleanup_task_data = load_task()
                    cleanup_changes['cleanup_warnings'] = list(
                        cleanup_task_data.get('cleanup_warnings') or ()
                    ) + list(cleanup['warnings'])
                if cleanup_changes:
                    update_data(changes=cleanup_changes)
        except Exception:
            app.logger.exception('Unable to clean interrupted dark-capture artifacts')


def mark_capture_restored(app, task_id):
    from .flask import db
    from .flask.models import IndiAllSkyDbTaskQueueTable

    with app.app_context():
        task = IndiAllSkyDbTaskQueueTable.query.filter_by(id=int(task_id)).one()
        _mark_task_capture_restored(task)
        db.session.commit()


def mark_pending_capture_restored(app):
    """Close terminal jobs left unrestored by a capture-service restart.

    The controller calls this only after its normal worker set has started, so
    the durable UI state reflects the real recovery point rather than merely
    the process startup.
    """
    from .flask import db
    from .flask.models import IndiAllSkyDbTaskQueueTable

    restored_count = 0
    with app.app_context():
        tasks = IndiAllSkyDbTaskQueueTable.query\
            .order_by(IndiAllSkyDbTaskQueueTable.createDate.desc())\
            .all()
        for task in tasks:
            data = dict(task.data or {})
            if data.get('action') != 'dark_automation':
                continue
            if data.get('status') not in TERMINAL_STATUSES:
                continue
            if data.get('capture_restored'):
                continue
            _mark_task_capture_restored(task)
            restored_count += 1

        if restored_count:
            db.session.commit()
    return restored_count


def _mark_task_capture_restored(task):
    data = dict(task.data or {})
    data['capture_restored'] = True
    progress = dict(data.get('progress') or {})
    progress['phase'] = data.get('status', 'complete')
    restore_state = data.get('capture_restore_state', CAPTURE_RESTORE_RUNNING)
    if restore_state == CAPTURE_RESTORE_PAUSED:
        restore_phrase = 'image capture remains paused as configured'
    elif restore_state == CAPTURE_RESTORE_SLEEPING:
        restore_phrase = 'image capture remains in daytime sleep until its configured schedule resumes'
    elif restore_state == CAPTURE_RESTORE_CONTROLLER:
        restore_phrase = 'the capture controller and its worker set have been restored'
    else:
        restore_phrase = 'normal capture has resumed'
    if data.get('status') == 'success':
        if data.get('operation') == 'flush':
            progress['message'] = 'Selected library records deleted; {0:s}.'.format(
                restore_phrase,
            )
        elif (
                data.get('capture_mode') == CAPTURE_MODE_TEMPERATURE_SERIES
                and data.get('temperature_target') is not None
        ):
            progress['message'] = (
                'Target sensor temperature reached; completed master sets are active '
                'and {0:s}.'.format(restore_phrase)
            )
        else:
            progress['message'] = 'Dark library complete; {0:s}.'.format(restore_phrase)
    elif data.get('status') == 'cancelled':
        if data.get('capture_mode') == CAPTURE_MODE_TEMPERATURE_SERIES:
            progress['message'] = (
                'Temperature series stopped; completed master sets remain active '
                'and {0:s}.'.format(restore_phrase)
            )
        else:
            progress['message'] = (
                'Dark capture cancelled; completed master sets remain active '
                'and {0:s}.'.format(restore_phrase)
            )
    elif data.get('status') == 'review_required':
        if data.get('operation') == 'flush':
            progress['message'] = (
                '{0:s}. Preview the library deletion again before retrying.'.format(
                    restore_phrase.capitalize(),
                )
            )
        else:
            progress['message'] = (
                '{0:s}. Review the revised camera plan before retrying.'.format(
                    restore_phrase.capitalize(),
                )
            )
    else:
        progress['message'] = (
            'Completed master sets remain active; {0:s} after the capture error.'.format(
                restore_phrase,
            )
        )
    progress['heartbeat_utc'] = _utc_now_text()
    data['progress'] = progress
    task.data = data


def _delete_library_entries(db, entries):
    """Commit row deletion before unlinking unique files from disk.

    A database failure therefore leaves the live library untouched. A later
    filesystem failure can only leave an unused orphan and is returned as a
    warning for the operator.
    """
    entries = tuple(entries)
    file_paths = []
    seen_paths = set()
    for entry in entries:
        file_path = Path(entry.getFilesystemPath())
        path_key = str(file_path.resolve())
        if path_key in seen_paths:
            continue
        seen_paths.add(path_key)
        file_paths.append(file_path)

    try:
        for entry in entries:
            db.session.delete(entry)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    warnings = []
    removed_files = 0
    for file_path in file_paths:
        if not file_path.exists():
            continue
        try:
            file_path.unlink()
            removed_files += 1
        except OSError as error:
            warnings.append('{0:s}: {1:s}'.format(str(file_path), str(error)))

    return {
        'files': removed_files,
        'warnings': warnings,
    }


def flush_camera_library(
        db,
        models,
        camera_id,
        selection=None,
        expected_signature=None,
):
    """Delete one camera's selected dark/BPM rows and their unique files."""
    resolved = select_camera_library_entries(models, camera_id, selection=selection)
    if expected_signature is not None and resolved['signature'] != str(expected_signature):
        raise DarkAutomationReviewRequired(
            'The selected library records changed after preview. Preview the deletion again.'
        )
    entries = resolved.pop('entries')
    resolved.pop('selection')
    resolved.pop('size_bytes')
    resolved.pop('size')
    resolved.pop('signature')
    counts = resolved
    counts.update(_delete_library_entries(db, entries))
    return counts


def flush_library_batches(db, models, batches):
    """Delete previewed selections from one or more camera libraries atomically."""
    resolved_batches = []
    for batch in batches:
        camera_id = int(batch['camera_id'])
        resolved = select_camera_library_entries(
            models,
            camera_id,
            selection=batch.get('selection'),
        )
        expected_signature = batch.get('selection_signature')
        if (
                expected_signature is not None
                and resolved['signature'] != str(expected_signature)
        ):
            raise DarkAutomationReviewRequired(
                'The selected library records changed after preview. '
                'Preview the deletion again.'
            )
        resolved_batches.append(resolved)

    entries = []
    for resolved in resolved_batches:
        entries.extend(resolved['entries'])
    cleanup = _delete_library_entries(db, entries)

    return {
        'dark_frames': sum(batch['dark_frames'] for batch in resolved_batches),
        'bad_pixel_maps': sum(
            batch['bad_pixel_maps'] for batch in resolved_batches
        ),
        'files': cleanup['files'],
        'warnings': cleanup['warnings'],
    }


def build_dark_command(
        python_executable,
        child_script,
        manifest_path,
):
    return [
        str(python_executable),
        str(child_script),
        '--manifest',
        str(manifest_path),
    ]


def _overall_progress(
        child_progress,
        offset,
        total,
        group_index,
        group_count,
        completed_master_details=(),
):
    completed = offset + int(child_progress.get('completed_master_sets') or 0)
    message = child_progress.get('message') or 'Capturing group {0:d} of {1:d}.'.format(
        group_index,
        group_count,
    )
    combined_master_details = _completed_master_details(
        list(completed_master_details)
        + list(child_progress.get('completed_master_details') or ())
    )
    return {
        'phase': child_progress.get('phase', 'capturing'),
        'message': message,
        'completed_master_sets': min(completed, total),
        'completed_master_details': combined_master_details,
        'total_master_sets': total,
        'current_gain': child_progress.get('current_gain'),
        'current_exposure': child_progress.get('current_exposure'),
        'current_frame': child_progress.get('current_frame'),
        'current_frame_count': child_progress.get('current_frame_count'),
        'current_binning': child_progress.get('current_binning'),
        'resolved_width': child_progress.get('resolved_width'),
        'resolved_height': child_progress.get('resolved_height'),
        'current_temperature': child_progress.get('current_temperature'),
        'temperature_source': child_progress.get('temperature_source'),
        'next_temperature': child_progress.get('next_temperature'),
        'target_temperature': child_progress.get('target_temperature'),
        'temperature_set': child_progress.get('temperature_set'),
        'planned_temperature_sets': child_progress.get('planned_temperature_sets'),
        'completed_temperature_sets': child_progress.get('completed_temperature_sets', 0),
        'activated_master_files': min(
            (int(offset) * 2)
            + int(child_progress.get('activated_master_files') or 0),
            int(total) * 2,
        ),
        'temperature_set_started_utc': child_progress.get('temperature_set_started_utc'),
    }


def checkpoint_master_pair(db, models, new_frames, task_data):
    """Activate one completed dark/BPM pair inside the caller's transaction."""
    new_frames = tuple(new_frames)
    if len(new_frames) != 2:
        raise DarkAutomationError('A completed master set must contain one dark and one bad-pixel map')

    frame_types = set()
    for frame in new_frames:
        model_name = type(frame).__name__
        if 'DarkFrame' in model_name:
            frame_types.add('dark')
        elif 'BadPixelMap' in model_name:
            frame_types.add('bpm')
    if frame_types != {'dark', 'bpm'}:
        raise DarkAutomationError('A completed master set must contain one dark and one bad-pixel map')

    automation_rows = [_frame_automation_data(frame) for frame in new_frames]
    expected_generation = str(task_data.get('generation_id') or '')
    expected_task_id = task_data.get('task_id')
    expected_group_id = str(task_data.get('group_id') or task_data.get('id') or '')
    if not expected_generation or any(
            str(data.get('generation_id') or '') != expected_generation
            for data in automation_rows
    ):
        raise DarkAutomationError('The completed master set does not match its capture generation')
    if expected_task_id is not None and any(
            str(data.get('task_id')) != str(expected_task_id)
            for data in automation_rows
    ):
        raise DarkAutomationError('The completed master set does not match its capture task')
    if expected_group_id and any(
            str(data.get('group_id') or '') != expected_group_id
            for data in automation_rows
    ):
        raise DarkAutomationError('The completed master set does not match its capture group')

    master_keys = {
        _library_master_key(frame, automation_data)
        for frame, automation_data in zip(new_frames, automation_rows)
    }
    if len(master_keys) != 1:
        raise DarkAutomationError('The completed dark and bad-pixel map do not describe the same master set')
    if any(not _frame_matches_approved_target(frame, task_data) for frame in new_frames):
        raise DarkAutomationError('The completed master set does not match the approved capture target')

    camera_ids = {int(frame.camera_id) for frame in new_frames}
    if len(camera_ids) != 1:
        raise DarkAutomationError('The completed dark and bad-pixel map belong to different cameras')
    camera_id = camera_ids.pop()
    old_frames = []
    for model in models:
        old_frames.extend(
            frame for frame in model.query.filter(model.camera_id == camera_id).all()
            if all(frame is not new_frame for new_frame in new_frames)
            and bool(frame.active)
        )

    strategy = str(task_data.get('strategy') or STRATEGY_COMPLETE)
    if strategy in (STRATEGY_COMPLETE, STRATEGY_CUSTOM):
        to_deactivate = ()
    elif strategy in (STRATEGY_REFRESH, STRATEGY_REBUILD):
        temperature_range = float(
            task_data.get('temperature_range', DEFAULT_TEMPERATURE_RANGE)
        )
        to_deactivate = tuple(
            old_frame for old_frame in old_frames
            if any(
                _frames_equivalent(old_frame, new_frame, temperature_range)
                for new_frame in new_frames
            )
        )
    else:
        raise DarkAutomationError('Unknown dark-library activation strategy')

    for frame in new_frames:
        _set_frame_eligibility(
            frame,
            True,
            ELIGIBILITY_REASON_CAPTURE_COMPLETED,
            source='automation',
        )
    retirement_reason = (
        ELIGIBILITY_REASON_REFRESH_REPLACED
        if strategy == STRATEGY_REFRESH else ELIGIBILITY_REASON_REBUILD_REPLACED
    )
    for frame in to_deactivate:
        _set_frame_eligibility(
            frame,
            False,
            retirement_reason,
            source='automation',
        )

    flush = getattr(db.session, 'flush', None)
    if flush is not None:
        flush()
    return {
        'activated': len(new_frames),
        'deactivated': len(to_deactivate),
    }


def cleanup_dark_capture_tempdirs(temp_root=None):
    """Remove abandoned automation scratch directories after no child is running."""
    root = Path(temp_root or tempfile.gettempdir())
    removed = 0
    warnings = []
    try:
        children = tuple(root.iterdir())
    except OSError as error:
        return {'directories': 0, 'warnings': [str(error)]}

    for child in children:
        if not child.name.startswith(DARK_CAPTURE_TEMP_PREFIXES):
            continue
        try:
            if child.is_symlink():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
            removed += 1
        except OSError as error:
            warnings.append('{0:s}: {1:s}'.format(str(child), str(error)))
    return {'directories': removed, 'warnings': warnings}


def cleanup_interrupted_capture_artifacts(
        db,
        models,
        darks_dir,
        task_ids=None,
        temp_root=None,
):
    """Keep complete active/inactive pairs and delete every interrupted artifact."""
    darks_path = Path(darks_dir)
    try:
        resolved_darks_path = darks_path.resolve()
    except (OSError, RuntimeError):
        resolved_darks_path = darks_path.absolute()
    warnings = []
    requested_task_ids = None
    if task_ids is not None:
        requested_task_ids = {str(value) for value in task_ids}

    typed_entries = []
    for model in models:
        frame_type = 'dark' if 'DarkFrame' in model.__name__ else 'bpm'
        typed_entries.extend((frame_type, frame) for frame in model.query.all())

    groups = {}
    invalid_entries = []
    for frame_type, frame in typed_entries:
        automation_data = _frame_automation_data(frame)
        generation_id = str(automation_data.get('generation_id') or '')
        if not generation_id:
            continue
        task_id = str(automation_data.get('task_id'))
        if requested_task_ids is not None and task_id not in requested_task_ids:
            continue
        try:
            group_key = (
                int(frame.camera_id),
                _library_master_key(frame, automation_data),
            )
        except (AttributeError, TypeError, ValueError):
            invalid_entries.append(frame)
            continue
        group = groups.setdefault(group_key, {'dark': [], 'bpm': []})
        group[frame_type].append(frame)

    for group in groups.values():
        entries = group['dark'] + group['bpm']
        complete_pair = len(group['dark']) == 1 and len(group['bpm']) == 1
        eligibility_states = [
            library_entry_eligibility(frame)['state'] for frame in entries
        ]
        eligible_pair = (
            complete_pair
            and len(set(eligibility_states)) == 1
            and eligibility_states[0]
            in (ELIGIBILITY_STATE_ACTIVE, ELIGIBILITY_STATE_INACTIVE)
            and all(
                bool(frame.active)
                == (eligibility_states[0] == ELIGIBILITY_STATE_ACTIVE)
                for frame in entries
            )
        )
        automation_identities = {
            (
                str(_frame_automation_data(frame).get('task_id')),
                str(_frame_automation_data(frame).get('group_id') or ''),
            )
            for frame in entries
        }
        eligible_pair = eligible_pair and len(automation_identities) == 1
        existing_pair = eligible_pair
        if existing_pair:
            for frame in entries:
                try:
                    if not Path(frame.getFilesystemPath()).is_file():
                        existing_pair = False
                        break
                except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                    existing_pair = False
                    break
        if existing_pair:
            continue
        invalid_entries.extend(entries)

    invalid_paths = []
    for frame in invalid_entries:
        try:
            file_path = Path(frame.getFilesystemPath()).resolve()
            file_path.relative_to(resolved_darks_path)
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            continue
        invalid_paths.append(file_path)

    invalid_identities = {id(frame) for frame in invalid_entries}
    if invalid_entries:
        try:
            for frame in invalid_entries:
                db.session.delete(frame)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    removed_files = 0
    for file_path in invalid_paths:
        try:
            file_path.unlink()
            removed_files += 1
        except FileNotFoundError:
            pass
        except OSError as error:
            warnings.append('{0:s}: {1:s}'.format(str(file_path), str(error)))

    referenced_paths = set()
    for _frame_type, frame in typed_entries:
        if id(frame) in invalid_identities:
            continue
        try:
            referenced_paths.add(Path(frame.getFilesystemPath()).resolve())
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            continue

    try:
        master_files = tuple(darks_path.iterdir()) if darks_path.is_dir() else ()
    except OSError as error:
        master_files = ()
        warnings.append('{0:s}: {1:s}'.format(str(darks_path), str(error)))
    for file_path in master_files:
        if not file_path.is_file() or not file_path.name.lower().startswith(
                DARK_AUTOMATION_MASTER_FILE_PREFIXES
        ):
            continue
        try:
            resolved_path = file_path.resolve()
        except OSError:
            resolved_path = file_path.absolute()
        if resolved_path in referenced_paths:
            continue
        try:
            file_path.unlink()
            removed_files += 1
        except FileNotFoundError:
            pass
        except OSError as error:
            warnings.append('{0:s}: {1:s}'.format(str(file_path), str(error)))

    temp_cleanup = cleanup_dark_capture_tempdirs(temp_root=temp_root)
    warnings.extend(temp_cleanup['warnings'])
    return {
        'database_rows': len(invalid_entries),
        'files': removed_files,
        'temporary_directories': temp_cleanup['directories'],
        'warnings': warnings,
    }


def _activate_generation(db, models, task_data):
    generation_id = str(task_data['generation_id'])
    camera_id = int(task_data['camera_id'])
    expected_count = int(task_data['target_count'])
    all_new_frames = []
    all_old_frames = []

    try:
        for model in models:
            camera_frames = model.query.filter(model.camera_id == camera_id).all()
            new_frames = [
                frame for frame in camera_frames
                if _frame_automation_data(frame).get('generation_id') == generation_id
            ]
            if len(new_frames) != expected_count:
                raise DarkAutomationError(
                    'The staged generation is incomplete: expected {0:d} {1:s} files, found {2:d}.'.format(
                        expected_count,
                        'dark' if 'DarkFrame' in model.__name__ else 'bad-pixel-map',
                        len(new_frames),
                    )
                )
            _validate_generation_groups(new_frames, task_data['groups'])
            all_new_frames.extend(new_frames)
            all_old_frames.extend(
                frame for frame in camera_frames
                if frame not in new_frames and bool(frame.active)
            )

        to_activate, to_deactivate = activation_changes(
            task_data['strategy'],
            all_new_frames,
            all_old_frames,
            task_data['groups'],
            temperature_range=task_data.get(
                'temperature_range',
                DEFAULT_TEMPERATURE_RANGE,
            ),
        )
        for frame in to_activate:
            _set_frame_eligibility(
                frame,
                True,
                ELIGIBILITY_REASON_CAPTURE_COMPLETED,
                source='automation',
            )
        retirement_reason = (
            ELIGIBILITY_REASON_REFRESH_REPLACED
            if task_data['strategy'] == STRATEGY_REFRESH
            else ELIGIBILITY_REASON_REBUILD_REPLACED
        )
        for frame in to_deactivate:
            _set_frame_eligibility(
                frame,
                False,
                retirement_reason,
                source='automation',
            )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return {
        'activated': len(to_activate),
        'deactivated': len(to_deactivate),
    }


def activation_changes(
        strategy,
        new_frames,
        old_frames,
        groups,
        temperature_range=DEFAULT_TEMPERATURE_RANGE,
):
    new_frames = tuple(new_frames)
    old_frames = tuple(old_frames)
    if strategy in (STRATEGY_COMPLETE, STRATEGY_CUSTOM):
        to_deactivate = ()
    elif strategy == STRATEGY_REFRESH:
        to_deactivate = tuple(
            old_frame for old_frame in old_frames
            if any(
                _frames_equivalent(old_frame, new_frame, temperature_range)
                for new_frame in new_frames
            )
        )
    elif strategy == STRATEGY_REBUILD:
        to_deactivate = tuple(
            old_frame for old_frame in old_frames
            if any(
                _frame_matches_group_scope(
                    old_frame,
                    group,
                    new_frames,
                    temperature_range,
                )
                for group in groups
            )
        )
    else:
        raise DarkAutomationError('Unknown dark-library activation strategy')
    return new_frames, to_deactivate


def _validate_generation_groups(frames, groups):
    groups_by_id = {str(group['id']): group for group in groups}
    actual_counts = {}
    for frame in frames:
        group_id = str(_frame_automation_data(frame).get('group_id') or '')
        actual_counts[group_id] = actual_counts.get(group_id, 0) + 1
        group = groups_by_id.get(group_id)
        if group is None or not _frame_matches_approved_target(frame, group):
            raise DarkAutomationError(
                'A staged master does not match the approved camera, gain, exposure, or binning plan.'
            )
    expected_counts = {
        str(group['id']): int(group['target_count'])
        for group in groups
    }
    if actual_counts != expected_counts:
        raise DarkAutomationError(
            'The staged generation does not match the approved gain and exposure groups.'
        )


def _frame_matches_approved_target(frame, group):
    if int(getattr(frame, 'binmode')) != int(group['binning']):
        return False
    for frame_field, group_field in (
            ('bitdepth', 'bit_depth'),
            ('width', 'width'),
            ('height', 'height'),
    ):
        expected = group.get(group_field)
        if expected is not None and getattr(frame, frame_field, None) != expected:
            return False
    if not any(
            abs(float(getattr(frame, 'gain')) - float(value)) <= 0.0001
            for value in group.get('gains', ())
    ):
        return False
    return any(
        abs(float(getattr(frame, 'exposure')) - float(value)) <= 0.0001
        for value in group.get('exposures', ())
    )


def _frame_automation_data(frame):
    return dict((getattr(frame, 'data', None) or {}).get('dark_automation') or {})


def _set_frame_eligibility(frame, active, reason, source, changed_utc=None):
    frame_data = dict(getattr(frame, 'data', None) or {})
    automation_data = dict(frame_data.get('dark_automation') or {})
    automation_data['eligibility'] = {
        'state': ELIGIBILITY_STATE_ACTIVE if active else ELIGIBILITY_STATE_INACTIVE,
        'reason': str(reason),
        'source': str(source),
        'changed_utc': changed_utc or _utc_now_text(),
    }
    frame_data['dark_automation'] = automation_data
    frame.data = frame_data
    frame.active = bool(active)


def _frames_equivalent(left, right, temperature_range):
    if _frame_structural_key(left) != _frame_structural_key(right):
        return False
    left_temperature = getattr(left, 'temp', None)
    right_temperature = getattr(right, 'temp', None)
    if left_temperature is None or right_temperature is None:
        return left_temperature is None and right_temperature is None
    return abs(float(left_temperature) - float(right_temperature)) <= float(temperature_range)


def _frame_structural_key(frame):
    return (
        getattr(frame, 'bitdepth', None),
        round(float(getattr(frame, 'exposure')), 6),
        round(float(getattr(frame, 'gain')), 6),
        int(getattr(frame, 'binmode')),
        getattr(frame, 'width', None),
        getattr(frame, 'height', None),
    )


def _frame_matches_group_scope(frame, group, new_frames, temperature_range):
    if int(getattr(frame, 'binmode')) != int(group['binning']):
        return False
    for frame_field, group_field in (
            ('bitdepth', 'bit_depth'),
            ('width', 'width'),
            ('height', 'height'),
    ):
        expected = group.get(group_field)
        if expected is not None and getattr(frame, frame_field, None) != expected:
            return False

    frame_temperature = getattr(frame, 'temp', None)
    target_temperature = group.get('temperature')
    if target_temperature is not None:
        if frame_temperature is None:
            return False
        return abs(
            float(frame_temperature) - float(target_temperature)
        ) <= float(temperature_range)

    group_new_temperatures = [
        getattr(new_frame, 'temp', None)
        for new_frame in new_frames
        if _frame_automation_data(new_frame).get('group_id') == group.get('id')
    ]
    if not group_new_temperatures:
        return False
    if frame_temperature is None:
        return any(value is None for value in group_new_temperatures)
    return any(
        value is not None
        and abs(float(frame_temperature) - float(value)) <= float(temperature_range)
        for value in group_new_temperatures
    )


def _task_cancelled(app, task_id):
    from .flask import db
    from .flask.models import IndiAllSkyDbTaskQueueTable

    with app.app_context():
        db.session.expire_all()
        task = IndiAllSkyDbTaskQueueTable.query.filter_by(id=int(task_id)).one()
        return bool((task.data or {}).get('cancel_requested'))


def _read_progress(progress_path):
    try:
        return json.loads(Path(progress_path).read_text(encoding='utf-8'))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return {}


def _write_json_file(path, data):
    Path(path).write_text(
        json.dumps(data, sort_keys=True, separators=(',', ':')),
        encoding='utf-8',
    )


def _read_log_tail(log_path, line_count=8, max_chars=1000):
    try:
        lines = Path(log_path).read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return ''
    useful = [line.strip() for line in lines if line.strip()]
    return '\n'.join(useful[-line_count:])[-int(max_chars):]


def _log_error_summary(diagnostic_log):
    lines = [line.strip() for line in str(diagnostic_log or '').splitlines() if line.strip()]
    if not lines:
        return 'the camera process returned an error'

    last_line = lines[-1]
    exception_name, separator, message = last_line.partition(': ')
    short_name = exception_name.rsplit('.', 1)[-1]
    if separator and short_name.endswith(('Error', 'Exception')) and message:
        return message[-1000:]
    return last_line[-1000:]


def _terminate_process_group(child):
    try:
        os.killpg(os.getpgid(child.pid), signal.SIGTERM)
    except (AttributeError, OSError, ProcessLookupError):
        child.terminate()


def _kill_process_group(child):
    try:
        os.killpg(os.getpgid(child.pid), signal.SIGKILL)
    except (AttributeError, OSError, ProcessLookupError):
        child.kill()


def _validate_frame_count(value):
    try:
        frame_count = int(value)
    except (TypeError, ValueError):
        raise DarkAutomationError('Enter a valid source-frame count')
    if frame_count < MIN_FRAME_COUNT or frame_count > MAX_FRAME_COUNT:
        raise DarkAutomationError(
            'Choose {0:d} to {1:d} images per master set.'.format(
                MIN_FRAME_COUNT,
                MAX_FRAME_COUNT,
            )
        )
    return frame_count


def _validate_choice(value, choices, message):
    value = str(value or '')
    if value not in choices:
        raise DarkAutomationError(message)
    return value


def _normalise_numbers(values, label):
    if not isinstance(values, (list, tuple)):
        raise DarkAutomationError('Enter {0:s} values as a comma-separated list'.format(label))
    result = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise DarkAutomationError('One or more {0:s} values are invalid'.format(label))
        if not math.isfinite(number):
            raise DarkAutomationError('One or more {0:s} values are invalid'.format(label))
        precision = 3 if label == 'gain' else 6
        result.append(float(round(number, precision)))
    return sorted(set(result))


def _validate_gain(gain, capabilities):
    if not capabilities.gain_supported:
        if abs(gain + 1.0) > 0.000001:
            raise DarkAutomationError('This camera does not provide adjustable gain')
        return
    if capabilities.gain_min is not None and gain < capabilities.gain_min - 0.000001:
        raise DarkAutomationError('A selected gain is below the camera minimum')
    if capabilities.gain_max is not None and gain > capabilities.gain_max + 0.000001:
        raise DarkAutomationError('A selected gain is above the camera maximum')
    if capabilities.gain_values:
        if not any(abs(gain - value) <= 0.000001 for value in capabilities.gain_values):
            raise DarkAutomationError('A selected gain is not supported by this camera')
    elif (
            capabilities.gain_step_is_quantum
            and capabilities.gain_step
            and capabilities.gain_min is not None
    ):
        step_count = (gain - capabilities.gain_min) / capabilities.gain_step
        if abs(step_count - round(step_count)) > 0.0001:
            raise DarkAutomationError('A selected gain does not match the camera gain step')


def _validate_exposure(exposure, capture_state, capabilities, planned_maximum=None):
    if exposure <= 0:
        raise DarkAutomationError('Dark exposure lengths must be greater than zero')
    if capabilities.exposure_min is not None and exposure < capabilities.exposure_min - 0.000001:
        raise DarkAutomationError('A selected exposure is below the camera minimum')
    maximum = float(math.ceil(capture_state.exposure_max))
    if planned_maximum is not None:
        maximum = max(maximum, float(planned_maximum))
    if capabilities.exposure_max is not None:
        maximum = min(maximum, float(capabilities.exposure_max))
    if exposure > maximum + 0.000001:
        raise DarkAutomationError('A selected exposure exceeds the configured camera maximum')


def _validate_binning(value, capabilities):
    try:
        binning = int(value)
    except (TypeError, ValueError):
        raise DarkAutomationError('Select a valid camera binning value')
    if binning < 1:
        raise DarkAutomationError('Camera binning must be at least 1')
    if capabilities.binning_min is not None and binning < int(capabilities.binning_min):
        raise DarkAutomationError('The selected binning is below the camera minimum')
    if capabilities.binning_max is not None and binning > int(capabilities.binning_max):
        raise DarkAutomationError('The selected binning is above the camera maximum')
    return binning


def _validate_bitmax(value):
    try:
        bitmax = int(value)
    except (TypeError, ValueError):
        raise DarkAutomationError('Enter a valid maximum data bit depth')
    if bitmax not in BITMAX_VALUES:
        raise DarkAutomationError('Maximum data bit depth must be 0, 8, 10, 12, 14, or 16 bits')
    return bitmax


def _validate_temperature_delta(value):
    try:
        temperature_delta = float(value)
    except (TypeError, ValueError):
        raise DarkAutomationError('Enter a valid temperature step')
    if not math.isfinite(temperature_delta):
        raise DarkAutomationError('Enter a valid temperature step')
    if temperature_delta < MIN_TEMPERATURE_DELTA or temperature_delta > MAX_TEMPERATURE_DELTA:
        raise DarkAutomationError(
            'Choose a temperature step between {0:g} and {1:g}°C.'.format(
                MIN_TEMPERATURE_DELTA,
                MAX_TEMPERATURE_DELTA,
            )
        )
    return float(round(temperature_delta, 3))


def _validate_temperature_target(value):
    if value is None or value == '':
        return None
    try:
        temperature_target = float(value)
    except (TypeError, ValueError):
        raise DarkAutomationError('Enter a valid target sensor temperature')
    if not math.isfinite(temperature_target):
        raise DarkAutomationError('Enter a valid target sensor temperature')
    if (
            temperature_target < MIN_TEMPERATURE_TARGET
            or temperature_target > MAX_TEMPERATURE_TARGET
    ):
        raise DarkAutomationError(
            'Target sensor temperature must be between {0:g} and {1:g}°C.'.format(
                MIN_TEMPERATURE_TARGET,
                MAX_TEMPERATURE_TARGET,
            )
        )
    return float(round(temperature_target, 3))


def temperature_thresholds(start_temperature, target_temperature, temperature_delta):
    """Return the falling thresholds after the immediate initial set."""
    target_temperature = _validate_temperature_target(target_temperature)
    temperature_delta = _validate_temperature_delta(temperature_delta)
    if target_temperature is None:
        return ()
    try:
        start_temperature = float(start_temperature)
    except (TypeError, ValueError):
        return ()
    if not math.isfinite(start_temperature) or start_temperature <= target_temperature:
        return ()

    thresholds = []
    next_temperature = start_temperature - temperature_delta
    while next_temperature > target_temperature + 0.000001:
        thresholds.append(float(round(next_temperature, 3)))
        next_temperature -= temperature_delta
    thresholds.append(target_temperature)
    return tuple(thresholds)


def estimate_temperature_set_count(start_temperature, target_temperature, temperature_delta):
    if target_temperature is None or start_temperature is None:
        return None
    return 1 + len(temperature_thresholds(
        start_temperature,
        target_temperature,
        temperature_delta,
    ))


def _validate_unique_targets(groups):
    seen = set()
    for group in groups:
        structural = (
            group['capture_period'],
            int(group['binning']),
            group.get('bit_depth'),
            group.get('width'),
            group.get('height'),
        )
        for gain in group['gains']:
            for exposure in group['exposures']:
                target = structural + (round(float(gain), 6), round(float(exposure), 6))
                if target in seen:
                    raise DarkAutomationError(
                        'Two enabled groups contain the same gain, exposure, binning, and profile target'
                    )
                seen.add(target)


def _capture_period(capture_profile):
    return 'day' if capture_profile in ('day', 'sqm_day') else 'night'


def _utc_now_text():
    return datetime.now(timezone.utc).isoformat()


def _elapsed_seconds(started_utc):
    if not started_utc:
        return 0
    try:
        started = datetime.fromisoformat(str(started_utc))
    except (TypeError, ValueError):
        return 0
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - started).total_seconds()))
