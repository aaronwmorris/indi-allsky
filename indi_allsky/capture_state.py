import hashlib
import json
import math
from dataclasses import asdict
from dataclasses import dataclass
from typing import Optional
from typing import Sequence
from typing import Tuple

from .gain import CONTINUOUS_AUTO_GAIN_MODES
from .gain import EXPOSURE_MODE_BASIC
from .gain import EXPOSURE_MODE_LABELS
from .gain import EXPOSURE_MODE_LEGACY


GAIN_KIND_FIXED = 'fixed'
GAIN_KIND_DISCRETE = 'discrete'
GAIN_KIND_CONTINUOUS = 'continuous'
GAIN_KIND_NONE = 'none'

CALIBRATION_MODE_ALL_EXPOSURES = 'all_exposures'
CALIBRATION_MODE_EXPOSURE_PRIORITY = 'exposure_priority'
CALIBRATION_MODE_FIXED_EXPOSURES = 'fixed_exposures'


@dataclass(frozen=True)
class CameraCapabilities:
    gain_min: Optional[float] = None
    gain_max: Optional[float] = None
    gain_step: Optional[float] = None
    gain_format: Optional[str] = None
    gain_values: Tuple[float, ...] = ()
    gain_values_known: bool = False
    binning_min: Optional[int] = None
    binning_max: Optional[int] = None
    exposure_min: Optional[float] = None
    exposure_max: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    bit_depth: Optional[int] = None
    gain_step_is_quantum: bool = False
    frame_x: Optional[int] = None
    frame_y: Optional[int] = None
    frame_width: Optional[int] = None
    frame_height: Optional[int] = None
    frame_width_step: Optional[int] = None
    frame_height_step: Optional[int] = None
    binning_dimensions: Tuple[Tuple[int, int, int, int, int, int, int], ...] = ()

    @property
    def capture_width(self):
        """Width of the active camera frame, falling back to the sensor maximum."""
        return self.frame_width if self.frame_width is not None else self.width

    @property
    def capture_height(self):
        """Height of the active camera frame, falling back to the sensor maximum."""
        return self.frame_height if self.frame_height is not None else self.height

    def binned_width(self, binning):
        learned = self._learned_binning_dimensions(binning)
        if learned is not None:
            return learned[0]
        return aligned_binned_dimension(self.capture_width, binning, self.frame_width_step)

    def binned_height(self, binning):
        learned = self._learned_binning_dimensions(binning)
        if learned is not None:
            return learned[1]
        return aligned_binned_dimension(self.capture_height, binning, self.frame_height_step)

    def _learned_binning_dimensions(self, binning):
        """Use a measured FITS size only for the exact ROI that produced it."""
        source_geometry = (
            self.frame_x,
            self.frame_y,
            self.capture_width,
            self.capture_height,
        )
        if any(value is None for value in source_geometry):
            return None
        for entry in self.binning_dimensions:
            if entry[:5] == (int(binning),) + source_geometry:
                return entry[5], entry[6]
        return None

    @property
    def gain_supported(self):
        if self.gain_min is None or self.gain_max is None:
            return True

        return not (self.gain_min < 0 and self.gain_max < 0)

    @classmethod
    def from_ccd_info(cls, ccd_info):
        gain_info = ccd_info.get('GAIN_INFO', {}) or {}
        binning_info = ccd_info.get('BINNING_INFO', {}) or {}
        exposure_info = ccd_info.get('CCD_EXPOSURE', {}).get('CCD_EXPOSURE_VALUE', {}) or {}
        ccd_frame = ccd_info.get('CCD_FRAME', {}) or {}
        ccd_sensor_info = ccd_info.get('CCD_INFO', {}) or {}

        return cls(
            gain_min=_optional_float(gain_info.get('min')),
            gain_max=_optional_float(gain_info.get('max')),
            gain_step=_positive_optional_float(gain_info.get('step')),
            gain_step_is_quantum=bool(gain_info.get('step_is_quantum', False)),
            gain_format=_optional_string(gain_info.get('format')),
            gain_values=_normalise_float_values(gain_info.get('values', ())),
            gain_values_known='values' in gain_info,
            binning_min=_optional_int(binning_info.get('min')),
            binning_max=_optional_int(binning_info.get('max')),
            exposure_min=_optional_float(exposure_info.get('min')),
            exposure_max=_optional_float(exposure_info.get('max')),
            width=_optional_int((ccd_frame.get('WIDTH') or {}).get('max')),
            height=_optional_int((ccd_frame.get('HEIGHT') or {}).get('max')),
            bit_depth=_optional_int((ccd_sensor_info.get('CCD_BITSPERPIXEL') or {}).get('current')),
            frame_x=_optional_int((ccd_frame.get('X') or {}).get('current')),
            frame_y=_optional_int((ccd_frame.get('Y') or {}).get('current')),
            frame_width=_optional_int((ccd_frame.get('WIDTH') or {}).get('current')),
            frame_height=_optional_int((ccd_frame.get('HEIGHT') or {}).get('current')),
            frame_width_step=_positive_optional_int((ccd_frame.get('WIDTH') or {}).get('step')),
            frame_height_step=_positive_optional_int((ccd_frame.get('HEIGHT') or {}).get('step')),
        )

    @classmethod
    def from_camera(cls, camera):
        camera_data = getattr(camera, 'data', None) or {}
        capability_data = camera_data.get('camera_capabilities', {}) or {}

        if capability_data:
            gain_data = capability_data.get('gain', {}) or {}
            binning_data = capability_data.get('binning', {}) or {}
            exposure_data = capability_data.get('exposure', {}) or {}
            frame_data = capability_data.get('frame', {}) or {}

            return cls(
                gain_min=_optional_float(gain_data.get('min')),
                gain_max=_optional_float(gain_data.get('max')),
                gain_step=_positive_optional_float(gain_data.get('step')),
                gain_step_is_quantum=bool(gain_data.get('step_is_quantum', False)),
                gain_format=_optional_string(gain_data.get('format')),
                gain_values=_normalise_float_values(gain_data.get('values', ())),
                gain_values_known=bool(gain_data.get('values_known', False)),
                binning_min=_optional_int(binning_data.get('min')),
                binning_max=_optional_int(binning_data.get('max')),
                exposure_min=_optional_float(exposure_data.get('min')),
                exposure_max=_optional_float(exposure_data.get('max')),
                width=_optional_int(frame_data.get('width')),
                height=_optional_int(frame_data.get('height')),
                bit_depth=_optional_int(frame_data.get('bit_depth')),
                frame_x=_optional_int(frame_data.get('x')),
                frame_y=_optional_int(frame_data.get('y')),
                frame_width=_optional_int(frame_data.get('active_width')),
                frame_height=_optional_int(frame_data.get('active_height')),
                frame_width_step=_positive_optional_int(frame_data.get('width_step')),
                frame_height_step=_positive_optional_int(frame_data.get('height_step')),
                binning_dimensions=_normalise_binning_dimensions(
                    frame_data.get('binning_dimensions', ()),
                ),
            )

        return cls(
            gain_min=_optional_float(getattr(camera, 'minGain', None)),
            gain_max=_optional_float(getattr(camera, 'maxGain', None)),
            binning_min=_optional_int(getattr(camera, 'minBinning', None)),
            binning_max=_optional_int(getattr(camera, 'maxBinning', None)),
            exposure_min=_optional_float(getattr(camera, 'minExposure', None)),
            exposure_max=_optional_float(getattr(camera, 'maxExposure', None)),
            width=_optional_int(getattr(camera, 'width', None)),
            height=_optional_int(getattr(camera, 'height', None)),
            bit_depth=_optional_int(getattr(camera, 'bits', None)),
        )

    def to_dict(self):
        return {
            'gain': {
                'min': self.gain_min,
                'max': self.gain_max,
                'step': self.gain_step,
                'step_is_quantum': self.gain_step_is_quantum,
                'format': self.gain_format,
                'values': list(self.gain_values),
                'values_known': self.gain_values_known,
                'supported': self.gain_supported,
            },
            'binning': {
                'min': self.binning_min,
                'max': self.binning_max,
            },
            'exposure': {
                'min': self.exposure_min,
                'max': self.exposure_max,
            },
            'frame': {
                'width': self.width,
                'height': self.height,
                'bit_depth': self.bit_depth,
                'x': self.frame_x,
                'y': self.frame_y,
                'active_width': self.frame_width,
                'active_height': self.frame_height,
                'width_step': self.frame_width_step,
                'height_step': self.frame_height_step,
                'binning_dimensions': [
                    {
                        'binning': entry[0],
                        'x': entry[1],
                        'y': entry[2],
                        'source_width': entry[3],
                        'source_height': entry[4],
                        'width': entry[5],
                        'height': entry[6],
                    }
                    for entry in self.binning_dimensions
                ],
            },
        }

    def configuration_dict(self):
        """Capability data that can invalidate an approved capture plan."""
        data = self.to_dict()
        # Measurements refine planning but do not describe a camera/config
        # change, so learning a size must not invalidate an accepted plan.
        data['frame'].pop('binning_dimensions', None)
        return data

    @property
    def signature(self):
        return hashlib.sha256(
            json.dumps(self.configuration_dict(), sort_keys=True, separators=(',', ':')).encode('utf-8')
        ).hexdigest()

    def clamp_gain(self, gain):
        gain = float(gain)

        if not self.gain_supported:
            return -1.0

        if self.gain_min is not None:
            gain = max(gain, self.gain_min)
        if self.gain_max is not None:
            gain = min(gain, self.gain_max)

        return float(gain)

    def snap_gain(self, gain):
        gain = self.clamp_gain(gain)
        if not self.gain_supported:
            return -1.0

        if self.gain_values:
            gain = min(self.gain_values, key=lambda value: abs(value - gain))
        elif self.gain_step_is_quantum and self.gain_step and self.gain_min is not None:
            step_count = (gain - self.gain_min) / self.gain_step
            step_count = math.floor(step_count + 0.5)
            gain = self.gain_min + (step_count * self.gain_step)
            gain = self.clamp_gain(gain)

        return float(round(gain, 3))

    def clamp_binning(self, binning):
        binning = int(binning)

        if self.binning_min is not None:
            binning = max(binning, self.binning_min)
        if self.binning_max is not None:
            binning = min(binning, self.binning_max)

        return binning


@dataclass(frozen=True)
class EffectiveGainProfile:
    name: str
    label: str
    binning: int
    gain_kind: str
    gain_min: float
    gain_max: float
    gain_values: Tuple[float, ...]
    exposure_mode: str
    bit_depth: Optional[int]
    temperature: Optional[float]
    calibration_mode: str = CALIBRATION_MODE_ALL_EXPOSURES
    calibration_exposures: Tuple[float, ...] = ()

    def to_dict(self):
        data = asdict(self)
        data['gain_values'] = list(self.gain_values)
        data['calibration_exposures'] = list(self.calibration_exposures)
        return data


@dataclass(frozen=True)
class EffectiveCaptureState:
    exposure_mode: str
    exposure_mode_label: str
    exposure_max: float
    exposure_step: float
    profiles: Tuple[EffectiveGainProfile, ...]
    warnings: Tuple[str, ...]
    config_signature: str

    def to_dict(self):
        return {
            'exposure_mode': self.exposure_mode,
            'exposure_mode_label': self.exposure_mode_label,
            'exposure_max': self.exposure_max,
            'exposure_step': self.exposure_step,
            'profiles': [profile.to_dict() for profile in self.profiles],
            'warnings': list(self.warnings),
            'config_signature': self.config_signature,
        }


def build_effective_capture_state(
        config,
        capabilities,
        exposure_step=5.0,
        exposure_max=None,
):
    warnings = []
    ccd_config = config.get('CCD_CONFIG', {}) or {}
    exposure_mode = ccd_config.get('EXPOSURE_CLASSNAME', EXPOSURE_MODE_BASIC)

    if exposure_mode not in EXPOSURE_MODE_LABELS:
        warnings.append('Unknown exposure mode; fixed-gain planning was used')
        exposure_mode = EXPOSURE_MODE_BASIC

    if capabilities.gain_supported and not capabilities.gain_values_known:
        warnings.append('Detailed gain capabilities are not stored yet; reconnect the camera to refresh them')

    if exposure_max is None:
        exposure_max = config.get('CCD_EXPOSURE_MAX', 15.0)
    configured_exposure_max = _floor_precision(exposure_max, 1000000)
    exposure_max = configured_exposure_max
    if capabilities.exposure_max is not None and exposure_max > capabilities.exposure_max:
        exposure_max = capabilities.exposure_max
        warnings.append('Maximum exposure was limited to the camera maximum')

    night_config = ccd_config.get('NIGHT', {}) or {}
    moon_config = ccd_config.get('MOONMODE', {}) or {}
    day_config = ccd_config.get('DAY', {}) or {}
    sqm_config = config.get('CAMERA_SQM', {}) or {}

    gain_night = _effective_gain(capabilities, night_config.get('GAIN', 0), 'night', warnings, round_up=False)
    gain_moon = _effective_gain(capabilities, moon_config.get('GAIN', gain_night), 'moon', warnings, round_up=False)
    gain_day = _effective_gain(capabilities, day_config.get('GAIN', 0), 'day', warnings, round_up=True)
    gain_sqm = _effective_gain(capabilities, sqm_config.get('GAIN', 10.0), 'SQM', warnings, round_up=False)

    bin_night = _effective_binning(capabilities, night_config.get('BINNING', 1), 'night', warnings)
    bin_moon = _effective_binning(capabilities, moon_config.get('BINNING', 1), 'moon', warnings)
    bin_day = _effective_binning(capabilities, day_config.get('BINNING', 1), 'day', warnings)
    bin_sqm = _effective_binning(capabilities, sqm_config.get('BINNING', 1), 'SQM', warnings)

    bit_depth_night = _effective_bit_depth(config, capabilities, daytime=False)
    bit_depth_day = _effective_bit_depth(config, capabilities, daytime=True)
    temperature_night = _configured_temperature(config, daytime=False)
    temperature_day = _configured_temperature(config, daytime=True)
    camera_interface = str(config.get('CAMERA_INTERFACE', ''))
    libcamera_style_interface = (
        camera_interface.startswith('libcamera_')
        or camera_interface.startswith('mqtt_')
    )
    daytime_profiles_enabled = bool(config.get('DAYTIME_CAPTURE', True))
    if (
            daytime_profiles_enabled
            and libcamera_style_interface
            and config.get('LIBCAMERA', {}).get('AWB_ENABLE_DAY')
    ):
        daytime_profiles_enabled = False
        warnings.append('Day darks were omitted because daytime white balance is enabled')
    if libcamera_style_interface and config.get('LIBCAMERA', {}).get('AWB_ENABLE'):
        warnings.append('Night dark capture requires nighttime white balance to be disabled')
    profiles = []

    if not capabilities.gain_supported:
        gain_night = gain_moon = gain_day = gain_sqm = -1.0

    if exposure_mode == EXPOSURE_MODE_BASIC:
        profiles.append(_fixed_profile(
            'night', 'Night', bin_night, gain_night, exposure_mode, bit_depth_night, temperature_night,
        ))
        profiles.append(_fixed_profile(
            'moon', 'Moon mode', bin_moon, gain_moon, exposure_mode, bit_depth_night, temperature_night,
        ))
        if daytime_profiles_enabled:
            profiles.append(_fixed_profile(
                'day', 'Day', bin_day, gain_day, exposure_mode, bit_depth_day, temperature_day,
            ))
    else:
        auto_gain_min = gain_day
        auto_gain_max = gain_night
        if auto_gain_min > auto_gain_max:
            warnings.append('Day gain is greater than night gain; the auto-gain range was reordered')
            auto_gain_min, auto_gain_max = auto_gain_max, auto_gain_min

        if not capabilities.gain_supported:
            gain_kind = GAIN_KIND_NONE
            gain_values = (-1.0,)
        elif exposure_mode == EXPOSURE_MODE_LEGACY:
            gain_kind = GAIN_KIND_DISCRETE
            requested_gain_values = _legacy_gain_values(
                auto_gain_min,
                auto_gain_max,
                ccd_config.get('AUTO_GAIN_LEVELS', 8),
            )
            gain_values = tuple(sorted(set(
                capabilities.snap_gain(gain)
                for gain in requested_gain_values
            )))
            if gain_values != requested_gain_values:
                warnings.append('Legacy auto-gain levels were adjusted to supported camera values')
        elif capabilities.gain_values:
            gain_kind = GAIN_KIND_DISCRETE
            gain_values = tuple(
                value for value in capabilities.gain_values
                if value >= auto_gain_min and value <= auto_gain_max
            )
            if not gain_values:
                gain_values = (auto_gain_min, auto_gain_max)
                warnings.append('No reported discrete camera gains fall inside the configured auto-gain range')
        elif exposure_mode in CONTINUOUS_AUTO_GAIN_MODES:
            gain_kind = GAIN_KIND_CONTINUOUS
            gain_values = ()
        else:
            gain_kind = GAIN_KIND_DISCRETE
            gain_values = (auto_gain_min, auto_gain_max)

        auto_profiles = (
            ('night', 'Night auto-gain', bin_night, bit_depth_night, temperature_night),
            ('moon', 'Moon auto-gain', bin_moon, bit_depth_night, temperature_night),
        )
        if daytime_profiles_enabled:
            auto_profiles += (('day', 'Day auto-gain', bin_day, bit_depth_day, temperature_day),)

        for profile_name, profile_label, binning, bit_depth, temperature in auto_profiles:
            profiles.append(
                EffectiveGainProfile(
                    name=profile_name,
                    label=profile_label,
                    binning=binning,
                    gain_kind=gain_kind,
                    gain_min=auto_gain_min,
                    gain_max=auto_gain_max,
                    gain_values=gain_values,
                    exposure_mode=exposure_mode,
                    bit_depth=bit_depth,
                    temperature=temperature,
                    calibration_mode=CALIBRATION_MODE_EXPOSURE_PRIORITY,
                )
            )

    sqm_exposure = ()
    if sqm_config.get('ENABLE') or sqm_config.get('ENABLE_DAY'):
        sqm_exposure = _fixed_calibration_exposure(
            sqm_config.get('EXPOSURE', 10.0),
            capabilities,
            'SQM',
            warnings,
        )
    if sqm_config.get('ENABLE'):
        profiles.append(_fixed_profile(
            'sqm_night', 'Camera SQM (night)', bin_sqm, gain_sqm, exposure_mode, bit_depth_night, temperature_night,
            calibration_mode=CALIBRATION_MODE_FIXED_EXPOSURES,
            calibration_exposures=sqm_exposure,
        ))
    if sqm_config.get('ENABLE_DAY') and daytime_profiles_enabled:
        profiles.append(_fixed_profile(
            'sqm_day', 'Camera SQM (day)', bin_sqm, gain_sqm, exposure_mode, bit_depth_day, temperature_day,
            calibration_mode=CALIBRATION_MODE_FIXED_EXPOSURES,
            calibration_exposures=sqm_exposure,
        ))

    signature_data = {
        'exposure_mode': exposure_mode,
        'exposure_max': exposure_max,
        'exposure_step': float(exposure_step),
        'profiles': [profile.to_dict() for profile in profiles],
        'capabilities': capabilities.configuration_dict(),
    }
    config_signature = hashlib.sha256(
        json.dumps(signature_data, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()

    return EffectiveCaptureState(
        exposure_mode=exposure_mode,
        exposure_mode_label=EXPOSURE_MODE_LABELS[exposure_mode],
        exposure_max=float(exposure_max),
        exposure_step=float(exposure_step),
        profiles=tuple(profiles),
        warnings=tuple(warnings),
        config_signature=config_signature,
    )


def binned_dimension(dimension, binning):
    if dimension is None:
        return None
    return max(1, int(int(dimension) / int(binning)))


def aligned_binned_dimension(dimension, binning, frame_step=None):
    """Predict a driver's binned size after respecting its unbinned ROI step."""
    if dimension is None:
        return None
    dimension = int(dimension)
    binning = int(binning)
    frame_step = max(1, int(frame_step or 1))
    alignment = math.lcm(frame_step, binning)
    aligned_dimension = dimension - (dimension % alignment)
    return max(1, int(aligned_dimension / binning))


def _current_int(property_data):
    if not isinstance(property_data, dict) or property_data.get('current') is None:
        return None
    return int(round(float(property_data['current'])))


def camera_geometry_from_ccd_info(ccd_info):
    """Return restorable INDI frame/binning state, or None when unavailable."""
    frame_info = (ccd_info or {}).get('CCD_FRAME', {}) or {}
    frame = {
        'x': _current_int(frame_info.get('X')),
        'y': _current_int(frame_info.get('Y')),
        'width': _current_int(frame_info.get('WIDTH')),
        'height': _current_int(frame_info.get('HEIGHT')),
    }
    if any(value is None for value in frame.values()):
        return None
    if frame['width'] <= 0 or frame['height'] <= 0:
        return None

    binning_info = (ccd_info or {}).get('BINNING_INFO', {}) or {}
    horizontal = binning_info.get('horizontal', binning_info.get('current', 1))
    vertical = binning_info.get('vertical', horizontal)
    try:
        frame['binning'] = (int(round(float(horizontal))), int(round(float(vertical))))
    except (TypeError, ValueError):
        return None
    if min(frame['binning']) < 1:
        return None
    return frame


def validate_captured_geometry(image_width, image_height, requested_binning, frame_info, binning_info):
    """Verify live INDI geometry while treating the received FITS shape as authoritative."""
    requested_binning = int(requested_binning)
    horizontal = (binning_info or {}).get('horizontal', (binning_info or {}).get('current'))
    vertical = (binning_info or {}).get('vertical', horizontal)
    if horizontal is not None and int(round(float(horizontal))) != requested_binning:
        raise RuntimeError('The camera did not apply the requested horizontal binning')
    if vertical is not None and int(round(float(vertical))) != requested_binning:
        raise RuntimeError('The camera did not apply the requested vertical binning')

    frame_width = _current_int((frame_info or {}).get('WIDTH'))
    frame_height = _current_int((frame_info or {}).get('HEIGHT'))
    if frame_width is not None and horizontal is not None:
        expected_width = binned_dimension(frame_width, int(round(float(horizontal))))
        if int(image_width) != expected_width:
            raise RuntimeError(
                'Captured width {0:d} does not match the camera frame readback {1:d}'.format(
                    int(image_width), expected_width,
                )
            )
    if frame_height is not None and vertical is not None:
        expected_height = binned_dimension(frame_height, int(round(float(vertical))))
        if int(image_height) != expected_height:
            raise RuntimeError(
                'Captured height {0:d} does not match the camera frame readback {1:d}'.format(
                    int(image_height), expected_height,
                )
            )
    return int(image_width), int(image_height)


def record_binning_dimensions(capability_data, geometry, binning, width, height):
    """Return camera capability data with one observed binned output recorded."""
    capability_data = dict(capability_data or {})
    frame_data = dict(capability_data.get('frame') or {})
    entries = list(frame_data.get('binning_dimensions') or ())
    key = (
        int(binning),
        int(geometry['x']),
        int(geometry['y']),
        int(geometry['width']),
        int(geometry['height']),
    )
    entries = [
        entry for entry in entries
        if _binning_dimension_key(entry) != key
    ]
    entries.append({
        'binning': key[0],
        'x': key[1],
        'y': key[2],
        'source_width': key[3],
        'source_height': key[4],
        'width': int(width),
        'height': int(height),
    })
    frame_data['binning_dimensions'] = entries
    capability_data['frame'] = frame_data
    return capability_data


def _fixed_profile(
        name,
        label,
        binning,
        gain,
        exposure_mode,
        bit_depth,
        temperature,
        calibration_mode=CALIBRATION_MODE_ALL_EXPOSURES,
        calibration_exposures=(),
):
    gain_kind = GAIN_KIND_FIXED
    if gain < 0:
        gain_kind = GAIN_KIND_NONE

    return EffectiveGainProfile(
        name=name,
        label=label,
        binning=binning,
        gain_kind=gain_kind,
        gain_min=gain,
        gain_max=gain,
        gain_values=(gain,),
        exposure_mode=exposure_mode,
        bit_depth=bit_depth,
        temperature=temperature,
        calibration_mode=calibration_mode,
        calibration_exposures=tuple(calibration_exposures),
    )


def _fixed_calibration_exposure(value, capabilities, label, warnings):
    """Choose one executable dark exposure that covers a fixed capture exposure."""
    configured_exposure = max(0.000001, _ceil_precision(value, 1000000))
    exposure = float(math.ceil(configured_exposure))

    if capabilities.exposure_max is not None and exposure > capabilities.exposure_max:
        if configured_exposure <= capabilities.exposure_max:
            exposure = configured_exposure
        else:
            exposure = float(capabilities.exposure_max)
            warnings.append('{0:s} exposure was limited to the camera maximum'.format(label))

    if capabilities.exposure_min is not None and exposure < capabilities.exposure_min:
        exposure = float(capabilities.exposure_min)
        warnings.append('{0:s} exposure was limited to the camera minimum'.format(label))

    return (float(round(exposure, 6)),)


def _effective_gain(capabilities, value, label, warnings, round_up):
    if round_up:
        configured_gain = _ceil_precision(value, 1000)
    else:
        configured_gain = _floor_precision(value, 1000)

    ranged_gain = capabilities.clamp_gain(configured_gain)
    if ranged_gain != configured_gain:
        warnings.append('{0:s} gain was limited to the camera range'.format(label.capitalize()))
    effective_gain = capabilities.snap_gain(ranged_gain)
    if effective_gain != ranged_gain:
        warnings.append('{0:s} gain was adjusted to a supported camera value'.format(label.capitalize()))

    return effective_gain


def _effective_binning(capabilities, value, label, warnings):
    configured_binning = int(value)
    effective_binning = capabilities.clamp_binning(configured_binning)
    if effective_binning != configured_binning:
        warnings.append('{0:s} binning was limited to the camera range'.format(label.capitalize()))

    return effective_binning


def _effective_bit_depth(config, capabilities, daytime):
    camera_interface = str(config.get('CAMERA_INTERFACE', ''))
    if camera_interface.startswith('libcamera_') or camera_interface.startswith('mqtt_'):
        libcamera_config = config.get('LIBCAMERA', {}) or {}
        image_type_key = 'IMAGE_FILE_TYPE_DAY' if daytime else 'IMAGE_FILE_TYPE'
        return 16 if libcamera_config.get(image_type_key, 'jpg') == 'dng' else 8

    configured_bit_depth = _optional_int(config.get('CCD_BIT_DEPTH'))
    if configured_bit_depth:
        return configured_bit_depth

    return capabilities.bit_depth


def _configured_temperature(config, daytime):
    cooling_key = 'CCD_COOLING_DAY' if daytime else 'CCD_COOLING'
    temperature_key = 'CCD_TEMP_DAY' if daytime else 'CCD_TEMP'
    default_temperature = 35.0 if daytime else 15.0

    if not config.get(cooling_key):
        return None

    return float(config.get(temperature_key, default_temperature))


def _legacy_gain_values(gain_min, gain_max, level_count):
    level_count = max(2, int(level_count))
    gain_step = (gain_max - gain_min) / (level_count - 1)
    gain_values = [float(round((gain_step * index) + gain_min, 3)) for index in range(level_count)]
    gain_values[-1] = float(round(gain_max, 3))
    return tuple(gain_values)


def _floor_precision(value, factor):
    return math.floor(float(value) * factor) / factor


def _ceil_precision(value, factor):
    return math.ceil(float(value) * factor) / factor


def _optional_float(value):
    if value is None:
        return None
    return float(value)


def _positive_optional_float(value):
    value = _optional_float(value)
    if value is None or value <= 0:
        return None
    return value


def _optional_int(value):
    if value is None:
        return None
    return int(value)


def _positive_optional_int(value):
    value = _optional_int(value)
    if value is None or value <= 0:
        return None
    return value


def _normalise_float_values(values: Sequence[float]):
    if not values:
        return ()
    return tuple(sorted(set(float(value) for value in values)))


def _binning_dimension_key(entry):
    if not isinstance(entry, dict):
        return None
    try:
        return (
            int(entry['binning']),
            int(entry['x']),
            int(entry['y']),
            int(entry['source_width']),
            int(entry['source_height']),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _normalise_binning_dimensions(entries):
    normalised = []
    for entry in entries or ():
        key = _binning_dimension_key(entry)
        if key is None:
            continue
        try:
            width = int(entry['width'])
            height = int(entry['height'])
        except (KeyError, TypeError, ValueError):
            continue
        if key[0] < 1 or key[3] < 1 or key[4] < 1 or width < 1 or height < 1:
            continue
        normalised.append(key + (width, height))
    return tuple(sorted(set(normalised)))


def _optional_string(value):
    if value is None:
        return None
    return str(value)
