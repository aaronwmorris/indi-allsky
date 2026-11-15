from math import radians

import pytest

from indi_allsky.aligned_media import frame_geometry, horizon_edge


def geometry(roll=0):
    return {'image_size': [200, 100], 'values': {
        'AZIMUTH_ANGLE': roll, 'IMAGE_CIRCLE_DIAMETER': 80, 'LENS_ALTITUDE': 90,
        'POINTING_AZIMUTH': 0, 'OFFSET_X': 0, 'OFFSET_Y': 0, 'RADIAL_DISTORTION': 0,
    }}


@pytest.mark.parametrize(('roll', 'azimuth', 'edge'), [
    (0, 0, (100, 0)), (0, 90, (0, 50)), (0, 180, (100, 99)),
    (0, 270, (199, 50)), (90, 0, (199, 50)), (90, 90, (100, 0)),
])
def test_sun_moon_azimuth_uses_same_north_as_photo(roll, azimuth, edge):
    assert horizon_edge(geometry(roll), radians(azimuth), 200, 100) == edge


def test_foreign_or_invalid_frame_geometry_cannot_be_applied():
    solution = geometry()
    data = {'star_alignment': solution}
    assert frame_geometry(data, (200, 100)) is solution
    assert frame_geometry(data, (100, 200)) is None
    solution['values']['OFFSET_X'] = float('nan')
    assert frame_geometry(data, (200, 100)) is None
