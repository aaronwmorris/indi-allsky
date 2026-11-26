'''The starlight list: sensors documented for low-light capture at 10 fps or more.

A sensor qualifies when its maker (1) puts it in a named low-light family
(Sony STARVIS or STARVIS 2) and (2) lists a frame rate of 10 a second or more.
Live video is only offered for cameras on this list.  There is no setting to
force it on for an unlisted camera.

read_by:
    'me'      the author read the driver source
    'builder' the implementer re-read the source
    'agent'   a research agent read it and nobody has rechecked
'''

from dataclasses import dataclass


_F = 'sony-semicon.com/files/62/flyer_security/'


@dataclass(frozen=True)
class Sensor:
    name: str
    family: str
    rate: str
    source: str
    read_by: str


@dataclass(frozen=True)
class CameraModel:
    match: str
    sensor: str
    source: str
    read_by: str


SENSORS = {
    s.name: s for s in (
        Sensor('IMX676', 'STARVIS 2', '3536 x 3536 at 60 a second (10-bit)', _F + 'IMX676-AACR1_Flyer.pdf', 'me'),
        Sensor('IMX462', 'STARVIS', '1080p at 120', _F + 'IMX462LQR_Flyer.pdf', 'me'),
        Sensor('IMX290', 'STARVIS', '1080p at 120', _F + 'IMX290_178_226_Flyer.pdf', 'builder'),
        Sensor('IMX327', 'STARVIS', '1080p at 60', _F + 'IMX327LQR_LQR1_Flyer.pdf', 'builder'),
        Sensor('IMX335', 'STARVIS', '2592 x 1944 at 60', _F + 'IMX335LQN_Flyer.pdf', 'builder'),
        Sensor('IMX678', 'STARVIS 2', '3840 x 2160 at 72', _F + 'IMX678-AAQR_AAQR1_Flyer.pdf', 'builder'),
        Sensor('IMX585', 'STARVIS 2', '3840 x 2160 at 90', _F + 'IMX585-AAQJ1_Flyer.pdf', 'builder'),
    )
}


# An indi camera reports only a device name, so models are mapped to sensors.
# match is a case-insensitive substring of the INDI device name.
CAMERA_MODELS = [
    CameraModel(
        'ASI676MC',
        'IMX676',
        'ZWO ASI676MC product page, zwoastro.com (names the sensor and STARVIS 2; exact URL not recorded)',
        'agent',
    ),
]


def sensor_for_device(device_name):
    '''Return the sensor name for an INDI device name, or None if unlisted.'''
    name = (device_name or '').lower()

    for model in CAMERA_MODELS:
        if model.match.lower() in name:
            return model.sensor

    return None


def video_allowed(sensor):
    '''Live video is allowed only for sensors on the starlight list.'''
    return sensor in SENSORS
