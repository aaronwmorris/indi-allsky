import math
from collections import Counter
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from typing import Optional
from typing import Tuple

from .gain import CONTINUOUS_AUTO_GAIN_MODES
from .gain import EXPOSURE_MODE_LEGACY
from .gain import db_to_gain
from .gain import gain_to_db
from .capture_state import GAIN_KIND_CONTINUOUS
from .capture_state import GAIN_KIND_DISCRETE
from .capture_state import GAIN_KIND_NONE
from .capture_state import CALIBRATION_MODE_ALL_EXPOSURES
from .capture_state import CALIBRATION_MODE_EXPOSURE_PRIORITY
from .capture_state import CALIBRATION_MODE_FIXED_EXPOSURES
from .capture_state import binned_dimension


COVERAGE_EXACT = 'exact'
COVERAGE_ACCEPTABLE = 'acceptable'
COVERAGE_COARSE = 'coarse'
COVERAGE_TEMPERATURE = 'temperature'
COVERAGE_INCOMPATIBLE = 'incompatible'
COVERAGE_MISSING = 'missing'


COVERAGE_STATUSES = (
    COVERAGE_EXACT,
    COVERAGE_ACCEPTABLE,
    COVERAGE_COARSE,
    COVERAGE_TEMPERATURE,
    COVERAGE_INCOMPATIBLE,
    COVERAGE_MISSING,
)


DEFAULT_TEMPERATURE_RANGE = 5.0
MIN_TEMPERATURE_RANGE = 0.1
MAX_TEMPERATURE_RANGE = 50.0
DARK_LIBRARY_CAMERA_DATA_KEY = 'dark_library'
TEMPERATURE_RANGE_CAMERA_DATA_KEY = 'temperature_matching_distance'
TEMPERATURE_STEP_CAMERA_DATA_KEY = 'temperature_series_step'


@dataclass(frozen=True)
class DarkQualityPolicy:
    name: str
    label: str
    gain_step_db: float
    temperature_range: float = DEFAULT_TEMPERATURE_RANGE
    frame_count: int = 10
    overhead_seconds: float = 30.0


QUALITY_POLICIES = {
    'precise': DarkQualityPolicy('precise', 'Precise', 1.5),
    'balanced': DarkQualityPolicy('balanced', 'Balanced', 3.0),
    'fast': DarkQualityPolicy('fast', 'Fast', 6.0),
}


def validate_temperature_range(value):
    try:
        temperature_range = float(value)
    except (TypeError, ValueError):
        raise ValueError('Enter a valid temperature matching distance')
    if (
            not math.isfinite(temperature_range)
            or temperature_range < MIN_TEMPERATURE_RANGE
            or temperature_range > MAX_TEMPERATURE_RANGE
    ):
        raise ValueError(
            'Choose a temperature matching distance between {0:g} and {1:g}°C.'.format(
                MIN_TEMPERATURE_RANGE,
                MAX_TEMPERATURE_RANGE,
            )
        )
    return float(round(temperature_range, 3))


def camera_temperature_preferences(camera):
    camera_data = dict(getattr(camera, 'data', None) or {})
    library_data = dict(camera_data.get(DARK_LIBRARY_CAMERA_DATA_KEY) or {})
    try:
        temperature_range = validate_temperature_range(
            library_data.get(TEMPERATURE_RANGE_CAMERA_DATA_KEY),
        )
        range_source = 'saved_camera'
    except ValueError:
        temperature_range = DEFAULT_TEMPERATURE_RANGE
        range_source = 'legacy_default'
    try:
        temperature_step = validate_temperature_range(
            library_data.get(TEMPERATURE_STEP_CAMERA_DATA_KEY),
        )
    except ValueError:
        temperature_step = temperature_range
    return {
        'temperature_range': temperature_range,
        'temperature_step': temperature_step,
        'range_source': range_source,
    }


def update_camera_temperature_preferences(camera, temperature_range, temperature_step):
    camera_data = dict(getattr(camera, 'data', None) or {})
    library_data = dict(camera_data.get(DARK_LIBRARY_CAMERA_DATA_KEY) or {})
    library_data[TEMPERATURE_RANGE_CAMERA_DATA_KEY] = validate_temperature_range(
        temperature_range,
    )
    library_data[TEMPERATURE_STEP_CAMERA_DATA_KEY] = validate_temperature_range(
        temperature_step,
    )
    camera_data[DARK_LIBRARY_CAMERA_DATA_KEY] = library_data
    camera.data = camera_data
    return library_data


@dataclass(frozen=True)
class DarkTarget:
    camera_id: int
    sources: Tuple[str, ...]
    capture_profile: str
    exposure_mode: str
    continuous_gain: bool
    gain: float
    exposure: float
    binning: int
    bit_depth: Optional[int]
    width: Optional[int]
    height: Optional[int]
    temperature: Optional[float]

    @property
    def key(self):
        return (
            self.camera_id,
            self.bit_depth,
            round(self.exposure, 6),
            round(self.gain, 6),
            self.binning,
            self.width,
            self.height,
            None if self.temperature is None else round(self.temperature, 3),
        )


@dataclass(frozen=True)
class DarkPlan:
    quality: DarkQualityPolicy
    config_signature: str
    exposure_max: float
    exposure_step: float
    exposures: Tuple[float, ...]
    targets: Tuple[DarkTarget, ...]
    warnings: Tuple[str, ...]


@dataclass(frozen=True)
class DarkInventoryFrame:
    frame_type: str
    frame_id: int
    camera_id: int
    active: bool
    exists: bool
    bit_depth: Optional[int]
    exposure: float
    gain: float
    binning: int
    temperature: Optional[float]
    width: Optional[int]
    height: Optional[int]
    create_date: Optional[datetime] = None


@dataclass(frozen=True)
class FrameCoverage:
    status: str
    frame_id: Optional[int] = None
    gain_delta: Optional[float] = None
    exposure_delta: Optional[float] = None


@dataclass(frozen=True)
class TargetCoverage:
    target: DarkTarget
    status: str
    dark: FrameCoverage
    bpm: FrameCoverage


@dataclass(frozen=True)
class DarkCoverageAnalysis:
    plan: DarkPlan
    target_coverages: Tuple[TargetCoverage, ...]
    structural_target_coverages: Tuple[TargetCoverage, ...]
    suggested_action: str
    suggested_targets: Tuple[DarkTarget, ...]
    completion_targets: Tuple[DarkTarget, ...]
    structural_completion_targets: Tuple[DarkTarget, ...]
    temperature: Optional[float]

    @property
    def counts(self):
        status_counts = Counter(coverage.status for coverage in self.target_coverages)
        return {status: status_counts.get(status, 0) for status in COVERAGE_STATUSES}

    @property
    def structural_counts(self):
        status_counts = Counter(
            coverage.status for coverage in self.structural_target_coverages
        )
        return {status: status_counts.get(status, 0) for status in COVERAGE_STATUSES}

    @property
    def structurally_complete(self):
        return not self.structural_completion_targets

    @property
    def temperature_ready(self):
        return not self.completion_targets

    @property
    def estimated_seconds(self):
        total_seconds = 0.0
        for target in self.suggested_targets:
            total_seconds += target.exposure * self.plan.quality.frame_count
            total_seconds += self.plan.quality.overhead_seconds
        return total_seconds


def build_dark_exposures(exposure_max, exposure_step=5.0):
    if exposure_step <= 0:
        raise ValueError('Exposure step must be greater than zero')

    exposures = {1.0}
    exposure = float(math.ceil(float(exposure_max)))
    while exposure > 1:
        exposures.add(float(int(exposure)))
        exposure -= float(exposure_step)

    return tuple(sorted(exposures))


def build_dark_plan(
        capture_state,
        capabilities,
        camera_id,
        quality='balanced',
        temperature_range=DEFAULT_TEMPERATURE_RANGE,
):
    try:
        quality_policy = QUALITY_POLICIES[quality]
    except KeyError:
        raise ValueError('Unknown dark quality policy: {0:s}'.format(quality))
    quality_policy = replace(
        quality_policy,
        temperature_range=validate_temperature_range(temperature_range),
    )

    warnings = list(capture_state.warnings)
    requested_exposures = build_dark_exposures(
        capture_state.exposure_max,
        capture_state.exposure_step,
    )
    minimum_exposure = 0.000001
    if capabilities.exposure_min is not None:
        minimum_exposure = max(minimum_exposure, float(capabilities.exposure_min))
    maximum_exposure = float(math.ceil(capture_state.exposure_max))
    if capabilities.exposure_max is not None and maximum_exposure > capabilities.exposure_max:
        maximum_exposure = min(
            float(capture_state.exposure_max),
            float(capabilities.exposure_max),
        )
    exposures = tuple(
        exposure for exposure in requested_exposures
        if exposure >= minimum_exposure and exposure <= maximum_exposure
    )
    if maximum_exposure >= minimum_exposure:
        # Targeted automation accepts fractional exposures.  Retain the exact
        # reachable maximum when a camera cannot accept its rounded-up value.
        exposures = tuple(sorted(set(exposures + (float(round(maximum_exposure, 6)),))))
    if exposures != requested_exposures:
        warnings.append('Exposure lengths outside the camera range were omitted')
    if not exposures:
        warnings.append(
            'The camera does not support a whole-second dark exposure within the configured range'
        )
    targets_by_key = {}

    for profile in capture_state.profiles:
        gains = _profile_gains(profile, capabilities, quality_policy, warnings)
        pairs = _profile_gain_exposure_pairs(profile, gains, exposures, capabilities, warnings)
        width = binned_dimension(capabilities.width, profile.binning)
        height = binned_dimension(capabilities.height, profile.binning)

        for gain, exposure in pairs:
            target = DarkTarget(
                camera_id=int(camera_id),
                sources=(profile.label,),
                capture_profile=profile.name,
                exposure_mode=profile.exposure_mode,
                continuous_gain=profile.gain_kind == GAIN_KIND_CONTINUOUS,
                gain=float(gain),
                exposure=float(exposure),
                binning=int(profile.binning),
                bit_depth=profile.bit_depth,
                width=width,
                height=height,
                temperature=profile.temperature,
            )

            old_target = targets_by_key.get(target.key)
            if old_target:
                sources = tuple(sorted(set(old_target.sources + target.sources)))
                targets_by_key[target.key] = replace(old_target, sources=sources)
            else:
                targets_by_key[target.key] = target

    targets = tuple(sorted(
        targets_by_key.values(),
        key=lambda target: (
            target.binning,
            target.bit_depth if target.bit_depth is not None else -1,
            target.gain,
            target.exposure,
        ),
    ))
    target_exposures = tuple(sorted(set(target.exposure for target in targets)))

    return DarkPlan(
        quality=quality_policy,
        config_signature=capture_state.config_signature,
        exposure_max=capture_state.exposure_max,
        exposure_step=capture_state.exposure_step,
        exposures=target_exposures,
        targets=targets,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def analyze_dark_plan(plan, inventory, temperature=None):
    inventory = tuple(inventory)
    target_coverages = tuple(
        _coverage_for_target(plan, target, inventory, temperature)
        for target in plan.targets
    )
    structural_target_coverages = tuple(
        _coverage_for_target(
            plan,
            target,
            inventory,
            temperature=None,
            ignore_temperature=True,
        )
        for target in plan.targets
    )

    complete_targets = _build_complete_targets(plan, inventory, temperature, target_coverages)
    structural_complete_targets = _build_complete_targets(
        plan,
        inventory,
        temperature=None,
        target_coverages=structural_target_coverages,
        ignore_temperature=True,
    )
    structurally_usable_count = sum(
        1 for coverage in structural_target_coverages
        if coverage.status in (COVERAGE_EXACT, COVERAGE_ACCEPTABLE)
    )

    if not complete_targets:
        suggested_action = 'none'
        suggested_targets = ()
    elif not structural_complete_targets:
        suggested_action = 'temperature'
        suggested_targets = complete_targets
    elif structurally_usable_count:
        suggested_action = 'complete'
        suggested_targets = complete_targets
    else:
        suggested_action = 'rebuild'
        suggested_targets = plan.targets

    return DarkCoverageAnalysis(
        plan=plan,
        target_coverages=target_coverages,
        structural_target_coverages=structural_target_coverages,
        suggested_action=suggested_action,
        suggested_targets=tuple(suggested_targets),
        completion_targets=tuple(complete_targets),
        structural_completion_targets=tuple(structural_complete_targets),
        temperature=_optional_float(temperature),
    )


def analysis_context(capture_state, capabilities, analysis):
    action_labels = {
        'none': 'Library covers the recommendation',
        'temperature': 'Library complete; add a temperature layer',
        'complete': 'Complete the recommended library',
        'rebuild': 'Build the recommended library',
    }
    action_descriptions = {
        'none': (
            'All recommended gain and exposure pairs are present and suitable for the '
            'configured or current temperature.'
        ),
        'temperature': (
            'The gain and exposure library is complete. Capture another temperature layer '
            'for better seasonal matching; existing layers remain active.'
        ),
        'complete': (
            'Some recommended gain or exposure pairs are genuinely missing. Keep compatible '
            'masters and capture the remaining structural and current-temperature gaps.'
        ),
        'rebuild': (
            'No useful gain and exposure coverage was found for the current settings; '
            'capture the complete recommendation.'
        ),
    }

    gain_values = sorted(set(round(target.gain, 6) for target in analysis.plan.targets))
    binnings = sorted(set(target.binning for target in analysis.plan.targets))
    bit_depths = sorted(set(
        target.bit_depth for target in analysis.plan.targets
        if target.bit_depth is not None
    ))
    target_temperatures = sorted(set(
        target.temperature for target in analysis.plan.targets
        if target.temperature is not None
    ))
    continuous_gain = any(target.continuous_gain for target in analysis.plan.targets)
    target_count = len(analysis.plan.targets)
    structural_missing_count = len(analysis.structural_completion_targets)
    temperature_addition_count = len(analysis.completion_targets)
    structural_ready_count = sum(
        1 for coverage in analysis.structural_target_coverages
        if coverage.status in (COVERAGE_EXACT, COVERAGE_ACCEPTABLE)
    )
    temperature_ready_count = sum(
        1 for coverage in analysis.target_coverages
        if coverage.status in (COVERAGE_EXACT, COVERAGE_ACCEPTABLE)
    )
    if continuous_gain:
        gain_policy_summary = '{0:s} · maximum {1:g} dB gain gap'.format(
            analysis.plan.quality.label,
            analysis.plan.quality.gain_step_db,
        )
    elif gain_values == [-1.0]:
        gain_policy_summary = 'Camera does not expose gain control'
    else:
        gain_policy_summary = 'Exact configured or supported gains'

    return {
        'available': bool(analysis.plan.targets),
        'mode': capture_state.exposure_mode_label,
        'mode_description': _camera_strategy_description(capture_state),
        'quality': analysis.plan.quality.label,
        'gain_step_db': analysis.plan.quality.gain_step_db,
        'temperature_range': analysis.plan.quality.temperature_range,
        'continuous_gain': continuous_gain,
        'gain_policy_summary': gain_policy_summary,
        'gain_values': gain_values,
        'gain_summary': _number_list_summary(gain_values),
        'exposures': list(analysis.plan.exposures),
        'exposure_summary': _number_list_summary(analysis.plan.exposures, suffix='s'),
        'binnings': binnings,
        'bit_depths': bit_depths,
        'target_count': target_count,
        'suggested_target_count': len(analysis.suggested_targets),
        'completion_target_count': len(analysis.completion_targets),
        'structural_missing_target_count': structural_missing_count,
        'structural_ready_target_count': structural_ready_count,
        'structurally_complete': analysis.structurally_complete,
        'structural_status_label': (
            'Complete' if analysis.structurally_complete else 'Incomplete'
        ),
        'temperature_addition_target_count': temperature_addition_count,
        'temperature_ready_target_count': temperature_ready_count,
        'temperature_ready': analysis.temperature_ready,
        'temperature_status_label': (
            'Covered'
            if analysis.temperature_ready
            else 'Additional layer recommended'
        ),
        'refresh_target_count': len(analysis.plan.targets),
        'rebuild_target_count': len(analysis.plan.targets),
        'counts': analysis.counts,
        'structural_counts': analysis.structural_counts,
        'suggested_action': analysis.suggested_action,
        'suggested_action_label': action_labels[analysis.suggested_action],
        'suggested_action_description': action_descriptions[analysis.suggested_action],
        'estimated_time': _format_duration(analysis.estimated_seconds),
        'temperature': analysis.temperature,
        'temperature_checked': analysis.temperature is not None or bool(target_temperatures),
        'target_temperatures': target_temperatures,
        'warnings': list(analysis.plan.warnings),
        'groups': _analysis_groups(analysis),
        'config_signature': analysis.plan.config_signature,
        'capabilities': capabilities.to_dict(),
    }


def _camera_strategy_description(capture_state):
    profiles = tuple(capture_state.profiles)
    exposure_priority_profiles = tuple(
        profile for profile in profiles
        if profile.calibration_mode == CALIBRATION_MODE_EXPOSURE_PRIORITY
    )
    all_exposure_profiles = tuple(
        profile for profile in profiles
        if profile.calibration_mode == CALIBRATION_MODE_ALL_EXPOSURES
    )
    fixed_exposure_profiles = tuple(
        profile for profile in profiles
        if profile.calibration_mode == CALIBRATION_MODE_FIXED_EXPOSURES
    )
    descriptions = []

    if exposure_priority_profiles:
        gain_kinds = {profile.gain_kind for profile in exposure_priority_profiles}
        if GAIN_KIND_CONTINUOUS in gain_kinds:
            descriptions.append(
                'indi-allsky first lengthens exposure at the lowest configured auto-gain. '
                'At the maximum exposure it holds exposure steady and raises or lowers gain '
                'to control brightness. The plan mirrors this with an exposure ladder at the '
                'lowest gain and a spaced gain ladder at maximum exposure.'
            )
        elif GAIN_KIND_DISCRETE in gain_kinds:
            if capture_state.exposure_mode == EXPOSURE_MODE_LEGACY:
                descriptions.append(
                    'indi-allsky first lengthens exposure at the lowest configured auto-gain. '
                    'At the maximum exposure it holds exposure steady and moves through the '
                    'configured legacy auto-gain levels. The plan uses the exposure ladder at '
                    'the lowest gain and those gain levels at maximum exposure.'
                )
            else:
                descriptions.append(
                    'indi-allsky first lengthens exposure at the lowest configured auto-gain. '
                    'At the maximum exposure it holds exposure steady and moves among the '
                    'camera\'s reported discrete gain values. The plan uses the exposure ladder '
                    'at the lowest gain and each reported gain at maximum exposure.'
                )
        else:
            descriptions.append(
                'This camera does not expose gain control, so indi-allsky varies exposure '
                'only. The plan captures the exposure ladder once for each required binning '
                'and data depth.'
            )

    if all_exposure_profiles:
        if all(profile.gain_kind == GAIN_KIND_NONE for profile in all_exposure_profiles):
            descriptions.append(
                'The fixed capture profiles have no gain control, so each required exposure '
                'is captured once per binning and data depth.'
            )
        else:
            descriptions.append(
                'Fixed capture profiles use their configured day, night and moon gains. The '
                'plan captures every required exposure at each distinct configured gain and '
                'captures settings shared by several profiles only once.'
            )

    if fixed_exposure_profiles:
        descriptions.append(
            'Enabled camera-SQM profiles are added separately at their configured fixed exposure.'
        )

    return ' '.join(descriptions)


def _profile_gains(profile, capabilities, quality_policy, warnings):
    if profile.gain_kind == GAIN_KIND_NONE:
        return (-1.0,)

    if profile.gain_values:
        return tuple(sorted(set(float(gain) for gain in profile.gain_values)))

    if profile.exposure_mode not in CONTINUOUS_AUTO_GAIN_MODES:
        return (profile.gain_min, profile.gain_max)

    gain_min_db = gain_to_db(profile.exposure_mode, profile.gain_min)
    gain_max_db = gain_to_db(profile.exposure_mode, profile.gain_max)
    gain_values = []
    gain_db = gain_min_db

    while gain_db < gain_max_db:
        gain = db_to_gain(profile.exposure_mode, gain_db)
        gain_values.append(_snap_continuous_gain(gain, capabilities))
        gain_db += quality_policy.gain_step_db

    gain_values.append(_snap_continuous_gain(profile.gain_max, capabilities))
    gain_values = sorted(set(float(round(gain, 3)) for gain in gain_values))

    # Snapping to the precision actually accepted by capture can make a
    # nominal interval fractionally wider than its policy. Insert a midpoint
    # in that rare case instead of approving a gap the executor cannot match.
    while True:
        expanded_values = [gain_values[0]]
        expanded = False
        for previous_gain, next_gain in zip(gain_values, gain_values[1:]):
            db_gap = gain_to_db(profile.exposure_mode, next_gain) - gain_to_db(
                profile.exposure_mode,
                previous_gain,
            )
            if db_gap > quality_policy.gain_step_db + 0.001:
                midpoint_db = gain_to_db(profile.exposure_mode, previous_gain) + (db_gap / 2.0)
                midpoint_gain = _snap_continuous_gain(
                    db_to_gain(profile.exposure_mode, midpoint_db),
                    capabilities,
                )
                if midpoint_gain not in (previous_gain, next_gain):
                    expanded_values.append(midpoint_gain)
                    expanded = True
            expanded_values.append(next_gain)
        gain_values = sorted(set(expanded_values))
        if not expanded:
            break

    gain_values = tuple(gain_values)

    for previous_gain, next_gain in zip(gain_values, gain_values[1:]):
        db_gap = gain_to_db(profile.exposure_mode, next_gain) - gain_to_db(profile.exposure_mode, previous_gain)
        if db_gap > quality_policy.gain_step_db + 0.001:
            warnings.append(
                'The camera gain step creates a {0:0.2f} dB gap, larger than the {1:s} policy'.format(
                    db_gap,
                    quality_policy.label.lower(),
                )
            )
            break

    return gain_values


def _profile_gain_exposure_pairs(profile, gains, exposures, capabilities, warnings):
    """Return only gain/exposure combinations the configured controller can use."""
    if profile.calibration_mode == CALIBRATION_MODE_FIXED_EXPOSURES:
        fixed_exposures = _supported_fixed_exposures(
            profile.calibration_exposures,
            capabilities,
        )
        if fixed_exposures != profile.calibration_exposures:
            warnings.append(
                '{0:s} exposure lengths outside the camera range were omitted'.format(profile.label)
            )
        return tuple(
            (float(gain), float(exposure))
            for gain in gains
            for exposure in fixed_exposures
        )

    if profile.calibration_mode == CALIBRATION_MODE_EXPOSURE_PRIORITY:
        if not exposures:
            return ()
        maximum_exposure = max(exposures)
        pairs = {
            (float(profile.gain_min), float(exposure))
            for exposure in exposures
        }
        pairs.update((float(gain), float(maximum_exposure)) for gain in gains)
        return tuple(sorted(pairs, key=lambda pair: (pair[0], pair[1])))

    return tuple(
        (float(gain), float(exposure))
        for gain in gains
        for exposure in exposures
    )


def _supported_fixed_exposures(exposures, capabilities):
    result = []
    for exposure in exposures:
        exposure = float(round(exposure, 6))
        if exposure <= 0:
            continue
        if capabilities.exposure_min is not None and exposure < capabilities.exposure_min:
            continue
        if capabilities.exposure_max is not None and exposure > capabilities.exposure_max:
            continue
        result.append(exposure)
    return tuple(sorted(set(result)))


def _snap_continuous_gain(gain, capabilities):
    # Capture shares gain values in 1/1000-unit integers, and darks.py uses
    # the same precision for direct gain lists.
    return capabilities.snap_gain(gain)


def _coverage_for_target(plan, target, inventory, temperature, ignore_temperature=False):
    if ignore_temperature:
        target_temperature = None
    else:
        target_temperature = target.temperature if target.temperature is not None else temperature
    dark_coverage = _coverage_for_frame_type(plan, target, inventory, 'dark', target_temperature)
    bpm_coverage = _coverage_for_frame_type(plan, target, inventory, 'bpm', target_temperature)
    combined_status = _combine_statuses(dark_coverage.status, bpm_coverage.status)

    return TargetCoverage(
        target=target,
        status=combined_status,
        dark=dark_coverage,
        bpm=bpm_coverage,
    )


def _coverage_for_frame_type(plan, target, inventory, frame_type, temperature):
    frames = [frame for frame in inventory if frame.frame_type == frame_type]
    compatible_frames = [frame for frame in frames if _base_compatible(target, frame)]
    directional_frames = [frame for frame in compatible_frames if _directionally_compatible(target, frame)]

    if temperature is not None:
        temperature_frames = [
            frame for frame in directional_frames
            if _temperature_compatible(frame, temperature, plan.quality.temperature_range)
        ]
    else:
        temperature_frames = directional_frames

    if not temperature_frames:
        if temperature is not None and directional_frames:
            return FrameCoverage(COVERAGE_TEMPERATURE)

        if any(_same_capture_cell(target, frame) for frame in frames):
            return FrameCoverage(COVERAGE_INCOMPATIBLE)

        return FrameCoverage(COVERAGE_MISSING)

    selected_frame = sorted(
        temperature_frames,
        key=lambda frame: _runtime_frame_order(frame, temperature),
    )[0]
    gain_delta = selected_frame.gain - target.gain
    exposure_delta = selected_frame.exposure - target.exposure

    if abs(gain_delta) <= 0.000001 and abs(exposure_delta) <= 0.000001:
        status = COVERAGE_EXACT
    elif target.continuous_gain and abs(exposure_delta) <= 0.000001:
        gain_delta_db = gain_to_db(target.exposure_mode, selected_frame.gain) - gain_to_db(
            target.exposure_mode,
            target.gain,
        )
        if gain_delta_db <= plan.quality.gain_step_db + 0.001:
            status = COVERAGE_ACCEPTABLE
        else:
            status = COVERAGE_COARSE
    else:
        status = COVERAGE_COARSE

    return FrameCoverage(
        status=status,
        frame_id=selected_frame.frame_id,
        gain_delta=gain_delta,
        exposure_delta=exposure_delta,
    )


def _build_complete_targets(
        plan,
        inventory,
        temperature,
        target_coverages,
        ignore_temperature=False,
):
    suggested_targets = []
    continuous_groups = {}

    for target in plan.targets:
        if not target.continuous_gain:
            continue
        group_key = (
            target.camera_id,
            target.exposure_mode,
            target.exposure,
            target.binning,
            target.bit_depth,
            target.width,
            target.height,
            target.temperature,
        )
        continuous_groups.setdefault(group_key, []).append(target)

    continuous_target_keys = {
        target.key
        for grouped_targets in continuous_groups.values()
        for target in grouped_targets
    }

    for coverage in target_coverages:
        if coverage.target.key in continuous_target_keys:
            continue
        if coverage.status not in (COVERAGE_EXACT, COVERAGE_ACCEPTABLE):
            suggested_targets.append(coverage.target)

    for grouped_targets in continuous_groups.values():
        grouped_targets = sorted(grouped_targets, key=lambda target: target.gain)
        template_target = grouped_targets[0]
        gain_min = grouped_targets[0].gain
        gain_max = grouped_targets[-1].gain
        if ignore_temperature:
            target_temperature = None
        else:
            target_temperature = template_target.temperature
            if target_temperature is None:
                target_temperature = temperature
        existing_gains = _paired_existing_gains(
            plan,
            template_target,
            inventory,
            target_temperature,
            gain_min,
            gain_max,
        )
        missing_gains = _continuous_missing_gains(
            template_target.exposure_mode,
            gain_min,
            gain_max,
            existing_gains,
            plan.quality.gain_step_db,
        )

        for gain in missing_gains:
            suggested_targets.append(replace(template_target, gain=gain))

    targets_by_key = {}
    for target in suggested_targets:
        old_target = targets_by_key.get(target.key)
        if old_target:
            sources = tuple(sorted(set(old_target.sources + target.sources)))
            targets_by_key[target.key] = replace(old_target, sources=sources)
        else:
            targets_by_key[target.key] = target

    return tuple(sorted(
        targets_by_key.values(),
        key=lambda target: (target.binning, target.gain, target.exposure),
    ))


def _paired_existing_gains(plan, target, inventory, temperature, gain_min, gain_max):
    gains_by_type = {}
    for frame_type in ('dark', 'bpm'):
        gains = set()
        for frame in inventory:
            if frame.frame_type != frame_type:
                continue
            if not _base_compatible_except_gain(target, frame):
                continue
            if abs(frame.exposure - target.exposure) > 0.000001:
                continue
            if frame.gain < gain_min or frame.gain > gain_max:
                continue
            if temperature is not None and not _temperature_compatible(
                    frame,
                    temperature,
                    plan.quality.temperature_range,
            ):
                continue
            gains.add(float(round(frame.gain, 6)))
        gains_by_type[frame_type] = gains

    return tuple(sorted(gains_by_type['dark'].intersection(gains_by_type['bpm'])))


def _continuous_missing_gains(exposure_mode, gain_min, gain_max, existing_gains, maximum_gap_db):
    gain_min_db = gain_to_db(exposure_mode, gain_min)
    gain_max_db = gain_to_db(exposure_mode, gain_max)
    existing_db = sorted(
        gain_to_db(exposure_mode, gain)
        for gain in existing_gains
        if gain >= gain_min and gain <= gain_max
    )
    missing_db = []

    if not any(abs(value - gain_min_db) <= 0.000001 for value in existing_db):
        missing_db.append(gain_min_db)
    current_db = gain_min_db

    while current_db < gain_max_db - 0.000001:
        reachable_existing = [
            value for value in existing_db
            if value > current_db + 0.000001 and value <= current_db + maximum_gap_db + 0.000001
        ]
        if reachable_existing:
            current_db = max(reachable_existing)
            continue

        next_db = min(current_db + maximum_gap_db, gain_max_db)
        missing_db.append(next_db)
        current_db = next_db

    missing_gains = tuple(sorted(set(
        float(round(db_to_gain(exposure_mode, gain_db), 6))
        for gain_db in missing_db
    )))
    return missing_gains


def _base_compatible(target, frame):
    if not _base_compatible_except_gain(target, frame):
        return False
    return True


def _base_compatible_except_gain(target, frame):
    if not frame.active or not frame.exists:
        return False
    if frame.camera_id != target.camera_id:
        return False
    if target.bit_depth is not None and frame.bit_depth != target.bit_depth:
        return False
    if frame.binning != target.binning:
        return False
    if target.width is not None and frame.width is not None and frame.width != target.width:
        return False
    if target.height is not None and frame.height is not None and frame.height != target.height:
        return False
    return True


def _directionally_compatible(target, frame):
    return frame.gain >= target.gain and frame.exposure >= target.exposure


def _same_capture_cell(target, frame):
    if frame.camera_id != target.camera_id:
        return False
    if frame.binning != target.binning:
        return False
    if abs(frame.gain - target.gain) > 0.000001:
        return False
    if abs(frame.exposure - target.exposure) > 0.000001:
        return False
    return True


def _temperature_compatible(frame, temperature, temperature_range):
    if frame.temperature is None:
        return False
    return abs(frame.temperature - temperature) <= temperature_range


def _runtime_frame_order(frame, current_temperature=None):
    if frame.temperature is None:
        temperature_distance = float('inf')
    elif current_temperature is None:
        temperature_distance = frame.temperature
    else:
        temperature_distance = abs(frame.temperature - current_temperature)

    if frame.create_date is None:
        create_timestamp = 0.0
    else:
        create_timestamp = frame.create_date.timestamp()

    return frame.gain, frame.exposure, temperature_distance, create_timestamp * -1


def _combine_statuses(*statuses):
    status_priority = {
        COVERAGE_EXACT: 0,
        COVERAGE_ACCEPTABLE: 1,
        COVERAGE_COARSE: 2,
        COVERAGE_TEMPERATURE: 3,
        COVERAGE_INCOMPATIBLE: 4,
        COVERAGE_MISSING: 5,
    }
    return max(statuses, key=lambda status: status_priority[status])


def _analysis_groups(analysis):
    cells = {}

    for target_kind, targets in (
            ('planned', analysis.plan.targets),
            ('suggested', analysis.suggested_targets),
    ):
        for target in targets:
            structural_key = (
                target.binning,
                target.bit_depth,
                target.temperature,
                target.sources,
            )
            gains = cells.setdefault(structural_key, {})
            gain_cells = gains.setdefault(target.gain, {
                'planned': set(),
                'suggested': set(),
            })
            gain_cells[target_kind].add(target.exposure)

    groups = []
    for structural_key, gains in cells.items():
        binning, bit_depth, temperature, sources = structural_key
        matching_gain_shapes = {}
        for gain, gain_cells in gains.items():
            shape = (
                tuple(sorted(gain_cells['planned'])),
                tuple(sorted(gain_cells['suggested'])),
            )
            matching_gain_shapes.setdefault(shape, []).append(gain)

        for shape, shape_gains in matching_gain_shapes.items():
            planned_exposures, suggested_exposures = shape
            groups.append({
                'sources': sources,
                'binning': binning,
                'bit_depth': bit_depth,
                'temperature': temperature,
                'gains': set(shape_gains),
                'suggested_gains': {
                    gain for gain in shape_gains if suggested_exposures
                },
                'exposures': set(planned_exposures + suggested_exposures),
                'target_count': len(shape_gains) * len(planned_exposures),
                'suggested_target_count': len(shape_gains) * len(suggested_exposures),
            })

    context_groups = []
    for group in groups:
        gains = sorted(group['gains'])
        suggested_gains = sorted(group['suggested_gains'])
        exposures = sorted(group['exposures'])
        context_groups.append({
            'sources': ', '.join(group['sources']),
            'binning': group['binning'],
            'bit_depth': group['bit_depth'],
            'temperature': group['temperature'],
            'gains': _number_list_summary(gains),
            'suggested_gains': _number_list_summary(suggested_gains) if suggested_gains else '—',
            'exposures': _number_list_summary(exposures, suffix='s'),
            'target_count': group['target_count'],
            'suggested_target_count': group['suggested_target_count'],
        })

    return sorted(context_groups, key=lambda group: (group['binning'], group['sources']))


def _number_list_summary(values, suffix=''):
    return ', '.join('{0:g}{1:s}'.format(value, suffix) for value in values)


def _format_duration(seconds):
    seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return '{0:d}h {1:02d}m {2:02d}s'.format(hours, minutes, seconds)


def _optional_float(value):
    if value is None:
        return None
    return float(value)
