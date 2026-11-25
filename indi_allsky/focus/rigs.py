"""Rig table: which focus page, which picture mode and which reason for each camera type."""

from __future__ import annotations

from dataclasses import dataclass

from .starlight import sensor_for_device
from .starlight import video_allowed


@dataclass(frozen=True)
class RigDecision:
    page: str  # 'new' | 'classic'
    picture: str | None  # 'video' | 'stills' | None (today's page, or not yet known)
    reason: str


RIGS = {
    'indi': 'indi',

    'libcamera_imx477': 'libcamera',
    'libcamera_imx378': 'libcamera',
    'libcamera_imx708': 'libcamera',
    'libcamera_imx519': 'libcamera',
    'libcamera_imx462': 'libcamera',
    'libcamera_imx327': 'libcamera',
    'libcamera_imx678': 'libcamera',
    'libcamera_imx335': 'libcamera',
    'libcamera_imx500_ai': 'libcamera',
    'libcamera_imx283': 'libcamera',
    'libcamera_imx296_gs': 'libcamera',
    'libcamera_imx296_gs_color': 'libcamera',
    'libcamera_imx290': 'libcamera',
    'libcamera_imx298': 'libcamera',
    'libcamera_imx219': 'libcamera',
    'libcamera_ov5647': 'libcamera',
    'libcamera_64mp_hawkeye': 'libcamera',
    'libcamera_64mp_owlsight': 'libcamera',

    'indi_accumulator': 'stills_only',
    'mqtt_imx477': 'stills_only',
    'mqtt_imx378': 'stills_only',
    'mqtt_imx708': 'stills_only',
    'mqtt_64mp_owlsight': 'stills_only',

    'indi_passive': 'cannot_command',
    'pycurl_camera': 'cannot_command',

    'test_rotating_stars': 'test',
    'test_bubbles': 'test',
}

# Sensor named by each libcamera value. Sensors not on the starlight list
# (IMX500, IMX296, the 64mp cameras, ...) have no SENSORS entry, so they get stills.
LIBCAMERA_SENSOR = {
    value: value.split('_')[1].upper()
    for value, kind in RIGS.items()
    if kind == 'libcamera'
}
LIBCAMERA_SENSOR['libcamera_64mp_hawkeye'] = 'IMX682'
LIBCAMERA_SENSOR['libcamera_64mp_owlsight'] = 'OV64A40'

_UNREACHABLE = (
    'The live focus page cannot reach the capture program. '
    'It may be stopped, or running in another container or on another machine.'
)
_CANNOT_COMMAND = 'Live focus and autofocus need a camera this program can command.'


def decide(camera_interface, device_name, driver_has_video, link_ok):
    """driver_has_video=None means not yet known: the page is 'new' and the picture is decided at session start."""
    if not link_ok:
        return RigDecision('classic', None, _UNREACHABLE)

    kind = RIGS.get(camera_interface, 'cannot_command')  # an unknown type keeps today's page

    if kind == 'indi':
        if not video_allowed(sensor_for_device(device_name)):
            return RigDecision('new', 'stills', 'this camera model is not on the starlight list yet')
        if driver_has_video is None:
            return RigDecision('new', None, '')
        if not driver_has_video:
            return RigDecision('new', 'stills', "this camera's driver does not offer video")
        return RigDecision('new', 'video', 'Live video · 10 fps')

    if kind == 'libcamera':
        if video_allowed(LIBCAMERA_SENSOR[camera_interface]):
            return RigDecision('new', 'stills', 'video for Pi cameras is not built yet')
        return RigDecision('new', 'stills', 'this sensor is not on the starlight list')

    if kind == 'stills_only':
        return RigDecision('new', 'stills', 'live video is not available for this camera type')

    if kind == 'test':
        return RigDecision('new', 'video', 'Simulated camera')

    return RigDecision('classic', None, _CANNOT_COMMAND)
