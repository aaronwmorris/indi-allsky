import hashlib
import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from datetime import timezone
from pathlib import Path

from . import constants


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
MAX_MASTER_SETS = 2000
MIN_FRAME_COUNT = 3
MAX_FRAME_COUNT = 50
CAPTURE_ORDERS = ('long_first', 'short_first')
TEMPERATURE_POLICIES = ('recommended', 'ignore')
COVER_CONFIRMATION_MAX_AGE_SECONDS = 30 * 60
CONTROLLER_HEARTBEAT_MAX_AGE_SECONDS = 10 * 60
MIN_TEMPERATURE_DELTA = 0.1
MAX_TEMPERATURE_DELTA = 50.0
MIN_TEMPERATURE_TARGET = -100.0
MAX_TEMPERATURE_TARGET = 100.0
BITMAX_VALUES = (0, 8, 10, 12, 14, 16)
CAPTURE_RESTORE_RUNNING = 'running'
CAPTURE_RESTORE_PAUSED = 'paused'
CAPTURE_RESTORE_SLEEPING = 'sleeping'
CAPTURE_RESTORE_CONTROLLER = 'controller'


class DarkAutomationError(RuntimeError):
    pass


class DarkAutomationCancelled(DarkAutomationError):
    pass


class DarkAutomationReviewRequired(DarkAutomationError):
    pass


def capture_controller_available(watchdog, status=None, now=None):
    """Return whether the capture controller has a current heartbeat.

    This intentionally uses only application state, so it works for systemd,
    containers, and installations with another process supervisor.
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
    """Turn arbitrary target cells into exact CLI rectangles.

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
        temperature_delta=5.0,
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
        temperature_delta = 5.0
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
            request_data.get('temperature_delta', 5.0),
        )
        temperature_target = _validate_temperature_target(
            request_data.get('temperature_target'),
        )
        strategy = STRATEGY_CUSTOM
    else:
        temperature_delta = 5.0
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
    requested_groups = request_data.get('groups')
    if requested_groups is None:
        requested_groups = blueprint['groups']
    if not isinstance(requested_groups, list):
        raise DarkAutomationError('The selected capture groups are invalid')

    normalised_groups = []
    seen_group_ids = set()
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
            _validate_exposure(exposure, capture_state, capabilities)

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
    if camera_interface.startswith('test_'):
        # The rotating-stars and bubbles cameras produce RGB frames.  The
        # legacy sigma-clip path expects a single image plane, so make the
        # simulator-safe method the default for guided capture.
        return 'average'
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
    if camera_interface.startswith('test_'):
        if execution.get('method') != 'average':
            raise DarkAutomationError(
                'Average stacking is required for RGB test-camera frames'
            )
        return
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


def task_public_status(task):
    data = dict(task.data or {})
    progress = dict(data.get('progress') or {})
    per_set_total = int(data.get('target_count') or progress.get('total_master_sets') or 0)
    raw_completed = int(progress.get('completed_master_sets') or 0)
    planned_temperature_sets = (
        progress.get('planned_temperature_sets')
        or data.get('temperature_set_count')
    )
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
    if total > 0 and progress_units > 0 and estimate_elapsed > 0:
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
        'capture_mode': data.get('capture_mode', CAPTURE_MODE_SINGLE),
        'frame_count': data.get('frame_count'),
        'target_count': total,
        'completed_master_sets': completed,
        'percent': round(percent, 1),
        'current_gain': progress.get('current_gain'),
        'current_exposure': progress.get('current_exposure'),
        'current_frame': progress.get('current_frame'),
        'current_frame_count': progress.get('current_frame_count'),
        'current_binning': progress.get('current_binning'),
        'current_temperature': progress.get('current_temperature'),
        'next_temperature': progress.get('next_temperature'),
        'target_temperature': progress.get(
            'target_temperature',
            data.get('temperature_target'),
        ),
        'completed_temperature_sets': progress.get('completed_temperature_sets', 0),
        'planned_temperature_sets': planned_temperature_sets,
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
    child_script = repository_root.joinpath('darks.py')
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
            data['progress'] = current_progress
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
                raise DarkAutomationCancelled('Dark calibration was cancelled before capture started')

            if task_data.get('operation') == 'flush':
                update_data(
                    changes={
                        'status': 'running',
                        'started_utc': _utc_now_text(),
                        'error': None,
                    },
                    progress={
                        'phase': 'removing_library',
                        'message': 'Normal capture is paused; removing this camera’s dark library.',
                    },
                    state=TaskQueueState.RUNNING,
                )
                deletion = flush_camera_library(
                    db,
                    (IndiAllSkyDbDarkFrameTable, IndiAllSkyDbBadPixelMapTable),
                    int(task_data['camera_id']),
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
                        'message': 'Dark library removed; restarting normal capture.',
                    },
                    state=TaskQueueState.SUCCESS,
                    result='Dark library removed',
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
            config = IndiAllSkyConfig().config
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
                'exposure_max': float(task_data['exposure_max']),
                'exposure_step': float(task_data['exposure_step']),
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
                    'groups': list(task_data['groups']),
                })
                _write_json_file(manifest_path, manifest)
                command = build_temperature_dark_command(
                    sys.executable,
                    child_script,
                    task_data,
                    progress_path,
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
                            update_data(progress=_overall_progress(
                                last_progress,
                                0,
                                int(task_data['target_count']),
                                1,
                                1,
                            ))
                        last_published = now
                    time.sleep(0.5)

                return_code = child.returncode
                final_progress = _read_progress(progress_path)
                if final_progress:
                    last_progress = final_progress
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
                        'Temperature-series dark capture was stopped; completed temperature sets remain active.'
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
        groups = list(task_data['groups'])
        with tempfile.TemporaryDirectory(prefix='indi-allsky-dark-automation-') as temporary_dir:
            temporary_path = Path(temporary_dir)
            for group_index, group in enumerate(groups, start=1):
                if _task_cancelled(app, task_id) or stop_requested():
                    raise DarkAutomationCancelled('Dark calibration was cancelled')

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
                })
                _write_json_file(manifest_path, manifest)
                command = build_dark_command(
                    sys.executable,
                    child_script,
                    task_data,
                    group,
                    progress_path,
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
                            update_data(progress=_overall_progress(
                                last_progress,
                                completed_offset,
                                int(task_data['target_count']),
                                group_index,
                                len(groups),
                            ))
                        last_published = now
                    time.sleep(0.5)

                return_code = child.returncode
                final_progress = _read_progress(progress_path)
                if final_progress:
                    last_progress = final_progress
                group_count = int(group['target_count'])
                if return_code != 0:
                    if _task_cancelled(app, task_id) or stop_requested() or return_code == 130:
                        raise DarkAutomationCancelled('Dark calibration was cancelled')
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

                completed_offset += group_count
                with app.app_context():
                    update_data(progress={
                        'phase': 'capturing',
                        'message': 'Completed capture group {0:d} of {1:d}.'.format(
                            group_index,
                            len(groups),
                        ),
                        'completed_master_sets': completed_offset,
                        'total_master_sets': int(task_data['target_count']),
                        'current_gain': None,
                        'current_exposure': None,
                        'current_frame': None,
                        'current_frame_count': int(task_data['frame_count']),
                        'current_binning': None,
                        'current_temperature': None,
                    })

        with app.app_context():
            update_data(progress={
                'phase': 'activating_library',
                'message': 'Checking and activating the completed library generation.',
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
                    'message': 'Cancellation confirmed; restarting normal capture.',
                },
                state=TaskQueueState.EXPIRED,
                result='Dark library capture cancelled',
            )
        return 'cancelled'
    except DarkAutomationReviewRequired as error:
        with app.app_context():
            update_data(
                changes={
                    'status': 'review_required',
                    'completed_utc': _utc_now_text(),
                    'error': str(error)[:1000],
                    'requires_review': True,
                },
                progress={
                    'phase': 'restoring_capture',
                    'message': 'The camera changed; restarting normal capture before you review the plan.',
                },
                state=TaskQueueState.EXPIRED,
                result='Dark calibration plan requires review',
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
                    'message': 'Dark calibration stopped; restarting normal capture.',
                },
                state=TaskQueueState.FAILED,
                result=str(error),
            )
        return 'failed'


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
            progress['message'] = 'Dark library removed; {0:s}.'.format(restore_phrase)
        elif (
                data.get('capture_mode') == CAPTURE_MODE_TEMPERATURE_SERIES
                and data.get('temperature_target') is not None
        ):
            progress['message'] = (
                'Target sensor temperature reached; completed temperature sets are active '
                'and {0:s}.'.format(restore_phrase)
            )
        else:
            progress['message'] = 'Dark library complete; {0:s}.'.format(restore_phrase)
    elif data.get('status') == 'cancelled':
        if data.get('capture_mode') == CAPTURE_MODE_TEMPERATURE_SERIES:
            progress['message'] = (
                'Temperature series stopped; completed temperature sets remain active '
                'and {0:s}.'.format(restore_phrase)
            )
        else:
            progress['message'] = 'Dark calibration cancelled; {0:s}.'.format(restore_phrase)
    elif data.get('status') == 'review_required':
        progress['message'] = (
            '{0:s}. Review the revised camera plan before retrying.'.format(
                restore_phrase.capitalize(),
            )
        )
    else:
        progress['message'] = '{0:s} after the calibration error.'.format(
            restore_phrase.capitalize(),
        )
    progress['heartbeat_utc'] = _utc_now_text()
    data['progress'] = progress
    task.data = data


def flush_camera_library(db, models, camera_id):
    """Remove one camera's dark/BPM rows before unlinking their files.

    Committing the database first avoids leaving live calibration rows pointing
    at missing files after a transaction failure or process interruption.  A
    later file error can only leave an unused orphan, which is reported.
    """
    entries = []
    counts = {'dark_frames': 0, 'bad_pixel_maps': 0}
    for model in models:
        model_entries = model.query.filter(model.camera_id == int(camera_id)).all()
        entries.extend(model_entries)
        if 'DarkFrame' in model.__name__:
            counts['dark_frames'] += len(model_entries)
        else:
            counts['bad_pixel_maps'] += len(model_entries)

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

    counts.update({
        'files': removed_files,
        'warnings': warnings,
    })
    return counts


def build_dark_command(
        python_executable,
        child_script,
        task_data,
        group,
        progress_path,
        manifest_path=None,
):
    command = [
        str(python_executable),
        str(child_script),
        str(task_data['method']),
        '--Count',
        str(int(task_data['frame_count'])),
        '--Binning',
        str(int(group['binning'])),
        '--capture-profile',
        str(group['capture_period']),
        '--progress-file',
        str(progress_path),
        '--gains',
    ]
    command.extend(_format_number(value) for value in group['gains'])
    command.append('--exposures')
    command.extend(_format_number(value) for value in group['exposures'])

    bitmax = int(group.get('bitmax', group.get('bit_depth') or 0) or 0)
    if bitmax in BITMAX_VALUES and bitmax > 0:
        command.extend(('--bitmax', str(bitmax)))
    if manifest_path is not None:
        command.extend(('--automation-manifest', str(manifest_path)))
    if task_data.get('capture_order', 'long_first') == 'short_first':
        command.append('--no-reverse')
    else:
        command.append('--reverse')
    return command


def build_temperature_dark_command(
        python_executable,
        child_script,
        task_data,
        progress_path,
        manifest_path,
):
    command = [
        str(python_executable),
        str(child_script),
        'temp{0:s}'.format(str(task_data['method'])),
        '--Count',
        str(int(task_data['frame_count'])),
        '--temp_delta',
        _format_number(task_data['temperature_delta']),
        '--progress-file',
        str(progress_path),
        '--automation-manifest',
        str(manifest_path),
    ]
    if task_data.get('temperature_target') is not None:
        command.extend((
            '--temp_target',
            _format_number(task_data['temperature_target']),
        ))
    if task_data.get('capture_order', 'long_first') == 'short_first':
        command.append('--no-reverse')
    else:
        command.append('--reverse')
    return command


def _overall_progress(child_progress, offset, total, group_index, group_count):
    completed = offset + int(child_progress.get('completed_master_sets') or 0)
    message = child_progress.get('message') or 'Capturing group {0:d} of {1:d}.'.format(
        group_index,
        group_count,
    )
    return {
        'phase': child_progress.get('phase', 'capturing'),
        'message': message,
        'completed_master_sets': min(completed, total),
        'total_master_sets': total,
        'current_gain': child_progress.get('current_gain'),
        'current_exposure': child_progress.get('current_exposure'),
        'current_frame': child_progress.get('current_frame'),
        'current_frame_count': child_progress.get('current_frame_count'),
        'current_binning': child_progress.get('current_binning'),
        'current_temperature': child_progress.get('current_temperature'),
        'temperature_source': child_progress.get('temperature_source'),
        'next_temperature': child_progress.get('next_temperature'),
        'target_temperature': child_progress.get('target_temperature'),
        'temperature_set': child_progress.get('temperature_set'),
        'planned_temperature_sets': child_progress.get('planned_temperature_sets'),
        'completed_temperature_sets': child_progress.get('completed_temperature_sets', 0),
        'activated_master_files': child_progress.get('activated_master_files', 0),
        'temperature_set_started_utc': child_progress.get('temperature_set_started_utc'),
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
        )
        for frame in to_activate:
            frame.active = True
        for frame in to_deactivate:
            frame.active = False
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return {
        'activated': len(to_activate),
        'deactivated': len(to_deactivate),
    }


def activation_changes(strategy, new_frames, old_frames, groups, temperature_range=5.0):
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
        return (
            float(frame_temperature) >= float(target_temperature)
            and float(frame_temperature) <= float(target_temperature) + float(temperature_range)
        )

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
            'Choose between {0:d} and {1:d} source frames per master.'.format(
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
    elif capabilities.gain_step and capabilities.gain_min is not None:
        step_count = (gain - capabilities.gain_min) / capabilities.gain_step
        if abs(step_count - round(step_count)) > 0.0001:
            raise DarkAutomationError('A selected gain does not match the camera gain step')


def _validate_exposure(exposure, capture_state, capabilities):
    if exposure < 1.0:
        raise DarkAutomationError('Dark exposure lengths must be at least 1 second')
    if abs(exposure - round(exposure)) > 0.000001:
        raise DarkAutomationError('Dark exposure lengths must use whole seconds')
    maximum = max(1.0, float(capture_state.exposure_max))
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


def _format_number(value):
    return '{0:g}'.format(float(value))


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
