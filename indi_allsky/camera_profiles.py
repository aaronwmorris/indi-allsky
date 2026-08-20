from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional
from typing import Tuple

from .gain import EXPOSURE_MODE_BASIC
from .gain import EXPOSURE_MODE_DB
from .gain import EXPOSURE_MODE_DB_1_10
from .gain import EXPOSURE_MODE_ISO
from .gain import EXPOSURE_MODE_ISO_1_100
from .gain import EXPOSURE_MODE_LEGACY


DEFAULT_TEST_CAMERA_PROFILE = 'legacy'


@dataclass(frozen=True)
class TestCameraProfile:
    label: str
    camera_name: str
    exposure_mode: str
    gain_min: float
    gain_max: float
    gain_step: Optional[float]
    gain_format: str
    gain_values: Tuple[float, ...]
    day_gain: float
    moon_gain: float
    night_gain: float
    sqm_gain: float
    exposure_min: float = 0.000032
    exposure_max: float = 60.0
    binning_min: int = 1
    binning_max: int = 4
    bit_depth: int = 16

    @property
    def gain_supported(self):
        return not (self.gain_min < 0 and self.gain_max < 0)

    def config_defaults(self):
        return {
            'exposure_mode': self.exposure_mode,
            'day_gain': self.day_gain,
            'moon_gain': self.moon_gain,
            'night_gain': self.night_gain,
            'sqm_gain': self.sqm_gain,
            'bit_depth': self.bit_depth,
            'auto_gain_levels': 8,
        }


TEST_CAMERA_PROFILES = OrderedDict((
    (
        'legacy',
        TestCameraProfile(
            label='Legacy synthetic camera (gain 0 only)',
            camera_name='Legacy Synthetic Test Camera',
            exposure_mode=EXPOSURE_MODE_BASIC,
            gain_min=0.0,
            gain_max=0.0,
            gain_step=1.0,
            gain_format='%0.0f',
            gain_values=(),
            day_gain=0.0,
            moon_gain=0.0,
            night_gain=0.0,
            sqm_gain=0.0,
        ),
    ),
    (
        'fixed',
        TestCameraProfile(
            label='Generic fixed gains (0-300)',
            camera_name='Fixed-Gain Synthetic Camera',
            exposure_mode=EXPOSURE_MODE_BASIC,
            gain_min=0.0,
            gain_max=300.0,
            gain_step=1.0,
            gain_format='%0.0f',
            gain_values=(),
            day_gain=0.0,
            moon_gain=150.0,
            night_gain=300.0,
            sqm_gain=100.0,
        ),
    ),
    (
        'legacy_autogain',
        TestCameraProfile(
            label='Generic legacy auto-gain (0-300)',
            camera_name='Legacy Auto-Gain Synthetic Camera',
            exposure_mode=EXPOSURE_MODE_LEGACY,
            gain_min=0.0,
            gain_max=300.0,
            gain_step=1.0,
            gain_format='%0.0f',
            gain_values=(),
            day_gain=0.0,
            moon_gain=150.0,
            night_gain=300.0,
            sqm_gain=100.0,
        ),
    ),
    (
        'zwo_playerone',
        TestCameraProfile(
            label='ZWO / Player One family (1/10 dB, 0-300)',
            camera_name='ZWO-Player One Synthetic Camera',
            exposure_mode=EXPOSURE_MODE_DB_1_10,
            gain_min=0.0,
            gain_max=300.0,
            gain_step=1.0,
            gain_format='%0.0f',
            gain_values=(),
            day_gain=0.0,
            moon_gain=150.0,
            night_gain=300.0,
            sqm_gain=100.0,
        ),
    ),
    (
        'qhy',
        TestCameraProfile(
            label='QHY family (native dB, 0-30)',
            camera_name='QHY Synthetic Camera',
            exposure_mode=EXPOSURE_MODE_DB,
            gain_min=0.0,
            gain_max=30.0,
            gain_step=0.1,
            gain_format='%0.1f',
            gain_values=(),
            day_gain=0.0,
            moon_gain=15.0,
            night_gain=30.0,
            sqm_gain=10.0,
        ),
    ),
    (
        'touptek',
        TestCameraProfile(
            label='ToupTek / Altair family (native ISO, 100-10000)',
            camera_name='ToupTek Synthetic Camera',
            exposure_mode=EXPOSURE_MODE_ISO,
            gain_min=100.0,
            gain_max=10000.0,
            gain_step=1.0,
            gain_format='%0.0f',
            gain_values=(),
            day_gain=100.0,
            moon_gain=1000.0,
            night_gain=10000.0,
            sqm_gain=400.0,
        ),
    ),
    (
        'libcamera',
        TestCameraProfile(
            label='libcamera family (1/100 ISO, 1-22.26)',
            camera_name='libcamera-Style Synthetic Camera',
            exposure_mode=EXPOSURE_MODE_ISO_1_100,
            gain_min=1.0,
            gain_max=22.26,
            gain_step=0.01,
            gain_format='%0.2f',
            gain_values=(),
            day_gain=1.0,
            moon_gain=8.0,
            night_gain=22.26,
            sqm_gain=4.0,
        ),
    ),
    (
        'discrete_iso',
        TestCameraProfile(
            label='Discrete ISO camera',
            camera_name='Discrete-ISO Synthetic Camera',
            exposure_mode=EXPOSURE_MODE_ISO,
            gain_min=100.0,
            gain_max=12800.0,
            gain_step=None,
            gain_format='%0.0f',
            gain_values=(100.0, 200.0, 400.0, 800.0, 1600.0, 3200.0, 6400.0, 12800.0),
            day_gain=100.0,
            moon_gain=800.0,
            night_gain=12800.0,
            sqm_gain=400.0,
        ),
    ),
    (
        'no_gain',
        TestCameraProfile(
            label='Camera without gain control',
            camera_name='No-Gain Synthetic Camera',
            exposure_mode=EXPOSURE_MODE_BASIC,
            gain_min=-1.0,
            gain_max=-1.0,
            gain_step=1.0,
            gain_format='',
            gain_values=(),
            day_gain=0.0,
            moon_gain=0.0,
            night_gain=0.0,
            sqm_gain=0.0,
        ),
    ),
))


def get_test_camera_profile(profile_name):
    return TEST_CAMERA_PROFILES.get(
        str(profile_name or DEFAULT_TEST_CAMERA_PROFILE),
        TEST_CAMERA_PROFILES[DEFAULT_TEST_CAMERA_PROFILE],
    )


def normalize_test_camera_gain(profile, gain):
    """Emulate how a camera driver applies its advertised gain controls."""
    gain = float(gain)

    if not profile.gain_supported:
        if abs(gain - (-1.0)) > 0.000001:
            raise ValueError('Synthetic camera profile does not support gain control')
        return -1.0

    if gain < profile.gain_min or gain > profile.gain_max:
        raise ValueError(
            'Synthetic camera gain {0:g} is outside the supported range {1:g}-{2:g}'.format(
                gain,
                profile.gain_min,
                profile.gain_max,
            )
        )

    if profile.gain_values:
        return float(min(
            profile.gain_values,
            key=lambda supported_gain: abs(gain - supported_gain),
        ))

    if profile.gain_step:
        step_count = round((gain - profile.gain_min) / profile.gain_step)
        gain = profile.gain_min + (step_count * profile.gain_step)
        gain = min(max(gain, profile.gain_min), profile.gain_max)
        return float(round(gain, 9))

    return gain


def test_camera_profile_choices():
    return tuple(
        (profile_name, profile.label)
        for profile_name, profile in TEST_CAMERA_PROFILES.items()
    )


def test_camera_profile_config_defaults():
    return {
        profile_name: profile.config_defaults()
        for profile_name, profile in TEST_CAMERA_PROFILES.items()
    }
