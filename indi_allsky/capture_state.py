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


FRAME_ALIGNMENT_BY_DRIVER = {
    # The INDI PlayerOne driver applies these constraints after binning.
    'indi_playerone_ccd': (4, 2),
}


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
    frame_width_multiple: int = 1
    frame_height_multiple: int = 1

    @property
    def gain_supported(self):
        if self.gain_min is None or self.gain_max is None:
            return True

        return not (self.gain_min < 0 and self.gain_max < 0)

    @classmethod
    def from_ccd_info(cls, ccd_info, camera_driver=None):
        gain_info = ccd_info.get('GAIN_INFO', {}) or {}
        binning_info = ccd_info.get('BINNING_INFO', {}) or {}
        exposure_info = ccd_info.get('CCD_EXPOSURE', {}).get('CCD_EXPOSURE_VALUE', {}) or {}
        ccd_frame = ccd_info.get('CCD_FRAME', {}) or {}
        ccd_sensor_info = ccd_info.get('CCD_INFO', {}) or {}
        frame_width_multiple, frame_height_multiple = _frame_alignment(camera_driver)

        return cls(
            gain_min=_optional_float(gain_info.get('min')),
            gain_max=_optional_float(gain_info.get('max')),
            gain_step=_positive_optional_float(gain_info.get('step')),
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
            frame_width_multiple=frame_width_multiple,
            frame_height_multiple=frame_height_multiple,
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
            driver_width_multiple, driver_height_multiple = _frame_alignment(
                getattr(camera, 'driver', None),
            )

            return cls(
                gain_min=_optional_float(gain_data.get('min')),
                gain_max=_optional_float(gain_data.get('max')),
                gain_step=_positive_optional_float(gain_data.get('step')),
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
                frame_width_multiple=_positive_int(
                    frame_data.get('width_multiple'),
                    default=driver_width_multiple,
                ),
                frame_height_multiple=_positive_int(
                    frame_data.get('height_multiple'),
                    default=driver_height_multiple,
                ),
            )

        frame_width_multiple, frame_height_multiple = _frame_alignment(
            getattr(camera, 'driver', None),
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
            frame_width_multiple=frame_width_multiple,
            frame_height_multiple=frame_height_multiple,
        )

    def to_dict(self):
        return {
            'gain': {
                'min': self.gain_min,
                'max': self.gain_max,
                'step': self.gain_step,
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
                'width_multiple': self.frame_width_multiple,
                'height_multiple': self.frame_height_multiple,
            },
        }

    @property
    def signature(self):
        return hashlib.sha256(
            json.dumps(self.to_dict(), sort_keys=True, separators=(',', ':')).encode('utf-8')
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
        elif self.gain_step and self.gain_min is not None:
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

    def binned_width(self, binning):
        return _binned_dimension(self.width, binning, self.frame_width_multiple)

    def binned_height(self, binning):
        return _binned_dimension(self.height, binning, self.frame_height_multiple)


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

    def to_dict(self):
        data = asdict(self)
        data['gain_values'] = list(self.gain_values)
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
                )
            )

    if sqm_config.get('ENABLE'):
        profiles.append(_fixed_profile(
            'sqm_night', 'Camera SQM (night)', bin_sqm, gain_sqm, exposure_mode, bit_depth_night, temperature_night,
        ))
    if sqm_config.get('ENABLE_DAY') and daytime_profiles_enabled:
        profiles.append(_fixed_profile(
            'sqm_day', 'Camera SQM (day)', bin_sqm, gain_sqm, exposure_mode, bit_depth_day, temperature_day,
        ))

    signature_data = {
        'exposure_mode': exposure_mode,
        'exposure_max': exposure_max,
        'exposure_step': float(exposure_step),
        'profiles': [profile.to_dict() for profile in profiles],
        'capabilities': capabilities.to_dict(),
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


def _fixed_profile(name, label, binning, gain, exposure_mode, bit_depth, temperature):
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
    )


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


def _positive_int(value, default=1):
    if value is None:
        value = default
    return max(1, int(value))


def _frame_alignment(camera_driver):
    driver_name = str(camera_driver or '').replace('\\', '/').rsplit('/', 1)[-1]
    return FRAME_ALIGNMENT_BY_DRIVER.get(driver_name, (1, 1))


def _binned_dimension(dimension, binning, multiple):
    if dimension is None:
        return None

    dimension = max(1, int(int(dimension) / int(binning)))
    multiple = _positive_int(multiple)
    if dimension >= multiple:
        dimension -= dimension % multiple
    return max(1, dimension)


def _normalise_float_values(values: Sequence[float]):
    if not values:
        return ()
    return tuple(sorted(set(float(value) for value in values)))


def _optional_string(value):
    if value is None:
        return None
    return str(value)
