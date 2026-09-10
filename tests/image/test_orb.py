import math
import datetime
from unittest.mock import MagicMock, patch
import numpy as np
import pytest
import ephem

from indi_allsky.overlay.orb import IndiAllskyOrbGenerator


@pytest.fixture
def base_config():
    return {
        'TEXT_PROPERTIES': {
            'FONT_FACE': 'FONT_HERSHEY_SIMPLEX',
            'FONT_AA': 'LINE_AA',
            'FONT_SCALE': 1.0,
            'FONT_THICKNESS': 1,
            'FONT_OUTLINE': True,
        },
        'ORB_PROPERTIES': {
            'RADIUS': 10,
            'SUN_COLOR': [255, 255, 0],
            'MOON_COLOR': [200, 200, 255],
        },
    }


def test_orb_generator_init_and_properties(base_config):
    gen = IndiAllskyOrbGenerator(base_config)

    # Defaults
    assert gen.sun_alt_deg == -6.0
    assert gen.azimuth_offset == 0.0
    assert gen.retrograde is False
    assert gen.text_color_rgb == [255, 255, 255]
    assert gen.text_color_bgr == [255, 255, 255]
    assert gen.sun_color_rgb == [255, 255, 255]
    assert gen.sun_color_bgr == [255, 255, 255]
    assert gen.moon_color_rgb == [255, 255, 255]
    assert gen.moon_color_bgr == [255, 255, 255]

    # Sun alt deg setter
    gen.sun_alt_deg = -12.5
    assert gen.sun_alt_deg == -12.5

    # Azimuth offset setter
    gen.azimuth_offset = 45.0
    assert gen.azimuth_offset == 45.0

    # Retrograde setter
    gen.retrograde = True
    assert gen.retrograde is True
    gen.retrograde = 0
    assert gen.retrograde is False

    # text_color_rgb setter and validation
    gen.text_color_rgb = [10, 20, 30]
    assert gen.text_color_rgb == [10, 20, 30]
    assert gen.text_color_bgr == [30, 20, 10]
    gen.text_color_rgb = [1, 2]  # invalid length
    assert gen.text_color_rgb == [10, 20, 30]  # unchanged

    # text_color_bgr setter and validation
    gen.text_color_bgr = [100, 150, 200]
    assert gen.text_color_rgb == [200, 150, 100]
    assert gen.text_color_bgr == [100, 150, 200]
    gen.text_color_bgr = [1, 2, 3, 4]  # invalid length
    assert gen.text_color_bgr == [100, 150, 200]  # unchanged

    # sun_color_rgb setter and validation
    gen.sun_color_rgb = [200, 210, 220]
    assert gen.sun_color_rgb == [200, 210, 220]
    assert gen.sun_color_bgr == [220, 210, 200]
    gen.sun_color_rgb = [1]  # invalid
    assert gen.sun_color_rgb == [200, 210, 220]

    # sun_color_bgr setter and validation
    gen.sun_color_bgr = [50, 60, 70]
    assert gen.sun_color_rgb == [70, 60, 50]
    assert gen.sun_color_bgr == [50, 60, 70]
    gen.sun_color_bgr = [50]  # invalid
    assert gen.sun_color_bgr == [50, 60, 70]

    # moon_color_rgb setter and validation
    gen.moon_color_rgb = [80, 90, 100]
    assert gen.moon_color_rgb == [80, 90, 100]
    assert gen.moon_color_bgr == [100, 90, 80]
    gen.moon_color_rgb = [80, 90]  # invalid
    assert gen.moon_color_rgb == [80, 90, 100]

    # moon_color_bgr setter and validation
    gen.moon_color_bgr = [110, 120, 130]
    assert gen.moon_color_rgb == [130, 120, 110]
    assert gen.moon_color_bgr == [110, 120, 130]
    gen.moon_color_bgr = [110, 120, 130, 140]  # invalid
    assert gen.moon_color_bgr == [110, 120, 130]


def test_remap(base_config):
    gen = IndiAllskyOrbGenerator(base_config)
    assert gen.remap(0.0, 0.0, 100.0, 0.0, 50.0) == 0.0
    assert gen.remap(50.0, 0.0, 100.0, 0.0, 50.0) == 25.0
    assert gen.remap(100.0, 0.0, 100.0, 0.0, 50.0) == 50.0


def test_draw_edge_circle_and_line(base_config):
    img = np.zeros((200, 200, 3), dtype=np.uint8)
    gen = IndiAllskyOrbGenerator(base_config)

    # Circle with outline
    gen.drawEdgeCircle_opencv(img, (50, 50), [255, 0, 0])
    assert np.any(img > 0)

    # Circle without outline
    gen.config['TEXT_PROPERTIES']['FONT_OUTLINE'] = False
    img_no_outline = np.zeros((200, 200, 3), dtype=np.uint8)
    gen.drawEdgeCircle_opencv(img_no_outline, (50, 50), [255, 0, 0])
    assert np.any(img_no_outline > 0)

    # Line on left edge (x == 0) with outline
    gen.config['TEXT_PROPERTIES']['FONT_OUTLINE'] = True
    img_line = np.zeros((200, 200, 3), dtype=np.uint8)
    gen.drawEdgeLine_opencv(img_line, (0, 100), [0, 255, 0])
    assert np.any(img_line > 0)

    # Line on right edge (x == width)
    gen.drawEdgeLine_opencv(img_line, (200, 100), [0, 255, 0])

    # Line on top/bottom edge (0 < x < width)
    gen.drawEdgeLine_opencv(img_line, (100, 0), [0, 0, 255])

    # Line without outline
    gen.config['TEXT_PROPERTIES']['FONT_OUTLINE'] = False
    img_line_no_outline = np.zeros((200, 200, 3), dtype=np.uint8)
    gen.drawEdgeLine_opencv(img_line_no_outline, (100, 100), [0, 0, 255])
    assert np.any(img_line_no_outline > 0)


def test_get_orb_hour_angle_xy_sectors_and_wrapping(base_config):
    gen = IndiAllskyOrbGenerator(base_config)
    image_size = (100, 100)  # height=100, width=100, perimeter_half=200

    mock_obs = MagicMock()
    mock_sky = MagicMock()

    # Case 1: mapped_ha_deg < 50 and ha_deg < 0 (Top right)
    # ha_deg = -18 -> abs_ha_deg = 18 -> mapped = 18 * 200 / 180 = 20 < 50
    # x = 50 + 20 = 70, y = 0
    mock_obs.sidereal_time.return_value = 0.0
    mock_sky.ra = math.radians(18.0)
    x, y = gen.getOrbHourAngleXY(mock_sky, mock_obs, image_size)
    assert x == 70 and y == 0

    # Case 2: mapped_ha_deg < 50 and ha_deg > 0 (Top left)
    # ha_deg = 18 -> mapped = 20 < 50
    # x = 50 - 20 = 30, y = 0
    mock_sky.ra = math.radians(-18.0)
    x, y = gen.getOrbHourAngleXY(mock_sky, mock_obs, image_size)
    assert x == 30 and y == 0

    # Case 3: mapped_ha_deg > 150 and ha_deg < 0 (Bottom right)
    # ha_deg = -153 -> mapped = 153 * 200 / 180 = 170 > 150
    # x = 100 - (170 - 150) = 80, y = 100
    mock_sky.ra = math.radians(153.0)
    x, y = gen.getOrbHourAngleXY(mock_sky, mock_obs, image_size)
    assert x == 80 and y == 100

    # Case 4: mapped_ha_deg > 150 and ha_deg > 0 (Bottom left)
    # ha_deg = 153 -> mapped = 170 > 150
    # x = 170 - 150 = 20, y = 100
    mock_sky.ra = math.radians(-153.0)
    x, y = gen.getOrbHourAngleXY(mock_sky, mock_obs, image_size)
    assert x == 20 and y == 100

    # Case 5: ha_deg < 0, 50 <= mapped <= 150 (Right edge)
    # ha_deg = -90 -> mapped = 90 * 200 / 180 = 100
    # x = 100, y = 100 - 50 = 50
    mock_sky.ra = math.radians(90.0)
    x, y = gen.getOrbHourAngleXY(mock_sky, mock_obs, image_size)
    assert x == 100 and y == 50

    # Case 6: ha_deg > 0, 50 <= mapped <= 150 (Left edge)
    # ha_deg = 90 -> mapped = 100
    # x = 0, y = 100 - 50 = 50
    mock_sky.ra = math.radians(-90.0)
    x, y = gen.getOrbHourAngleXY(mock_sky, mock_obs, image_size)
    assert x == 0 and y == 50

    # Case 7: ha_deg == 0 -> raises Exception('This cannot happen')
    mock_sky.ra = 0.0
    with pytest.raises(Exception, match='This cannot happen'):
        gen.getOrbHourAngleXY(mock_sky, mock_obs, image_size)

    # Angle normalization tests:
    # ha_deg < -180: ha_deg = -200 -> -200 + 360 = 160 > 0 (Bottom left)
    mock_sky.ra = math.radians(200.0)
    x, y = gen.getOrbHourAngleXY(mock_sky, mock_obs, image_size)
    assert y == 100

    # ha_deg > 180: ha_deg = 200 -> 200 - 360 = -160 < 0 (Bottom right)
    mock_sky.ra = math.radians(-200.0)
    x, y = gen.getOrbHourAngleXY(mock_sky, mock_obs, image_size)
    assert y == 100

    # Retrograde and Azimuth Offset
    gen.retrograde = True
    gen.azimuth_offset = 10.0
    mock_sky.ra = math.radians(90.0)
    # ha_rad = -90 deg -> ha_deg = -80 deg with offset -> retrograde: 360 - (-80) = 440 -> normalized: 440 - 360 = 80 deg
    x, y = gen.getOrbHourAngleXY(mock_sky, mock_obs, image_size)
    assert x == 0  # Left edge because ha_deg > 0


def test_get_orb_azimuth_xy_sectors_and_wrapping(base_config):
    gen = IndiAllskyOrbGenerator(base_config)
    image_size = (100, 100)

    mock_obs = MagicMock()
    mock_sky = MagicMock()

    # az_deg < 180 -> az_deg = az_deg * -1 (negative)
    # E.g. sky.az = 18 deg -> az_deg = -18 (ha_deg < 0, mapped = 20 < 50 -> Top right)
    mock_sky.az = math.radians(18.0)
    x, y = gen.getOrbAzimuthXY(mock_sky, mock_obs, image_size)
    assert x == 70 and y == 0

    # az_deg > 180 -> az_deg = (-360 + az_deg) * -1 (positive)
    # E.g. sky.az = 342 deg -> az_deg = (-360 + 342) * -1 = 18 (ha_deg > 0, mapped = 20 < 50 -> Top left)
    mock_sky.az = math.radians(342.0)
    x, y = gen.getOrbAzimuthXY(mock_sky, mock_obs, image_size)
    assert x == 30 and y == 0

    # Bottom right: az_deg < 180, e.g. az = 153 -> az_deg = -153 -> mapped = 170 > 150
    mock_sky.az = math.radians(153.0)
    x, y = gen.getOrbAzimuthXY(mock_sky, mock_obs, image_size)
    assert x == 80 and y == 100

    # Bottom left: az_deg > 180, e.g. az = 207 -> az_deg = (-360 + 207) * -1 = 153 -> mapped = 170 > 150
    mock_sky.az = math.radians(207.0)
    x, y = gen.getOrbAzimuthXY(mock_sky, mock_obs, image_size)
    assert x == 20 and y == 100

    # Right edge: az = 90 -> az_deg = -90 -> mapped = 100
    mock_sky.az = math.radians(90.0)
    x, y = gen.getOrbAzimuthXY(mock_sky, mock_obs, image_size)
    assert x == 100 and y == 50

    # Left edge: az = 270 -> az_deg = (-360 + 270) * -1 = 90 -> mapped = 100
    mock_sky.az = math.radians(270.0)
    x, y = gen.getOrbAzimuthXY(mock_sky, mock_obs, image_size)
    assert x == 0 and y == 50

    # Retrograde and Azimuth Offset
    gen.retrograde = True
    gen.azimuth_offset = 15.0
    mock_sky.az = math.radians(90.0)
    x, y = gen.getOrbAzimuthXY(mock_sky, mock_obs, image_size)
    assert isinstance(x, int)
    assert isinstance(y, int)

    # az_deg == 0 -> 0 * -1 = 0 -> raises Exception('This cannot happen')
    gen.retrograde = False
    gen.azimuth_offset = 0.0
    mock_sky.az = 0.0
    with pytest.raises(Exception, match='This cannot happen'):
        gen.getOrbAzimuthXY(mock_sky, mock_obs, image_size)


def test_get_orb_altitude_xy(base_config):
    gen = IndiAllskyOrbGenerator(base_config)
    image_size = (100, 100)
    utcnow = datetime.datetime(2026, 1, 1, 12, 0, 0)

    mock_obs = MagicMock()
    mock_sky = MagicMock()
    mock_sky.alt = math.radians(45.0)  # 45 deg altitude

    # Case 1: transit in < 12 hours (rising -> x = image_width)
    mock_transit = MagicMock()
    mock_transit.datetime.return_value = utcnow + datetime.timedelta(hours=2)
    mock_obs.next_transit.return_value = mock_transit

    x, y = gen.getOrbAltitudeXY(mock_sky, mock_obs, image_size, utcnow)
    assert x == 100
    # 45 deg remapped between -90 and 90 -> 75% -> y = 100 - 75 = 25
    assert y == 25

    # Case 2: transit >= 12 hours (setting -> x = 0)
    mock_transit.datetime.return_value = utcnow + datetime.timedelta(hours=14)
    x, y = gen.getOrbAltitudeXY(mock_sky, mock_obs, image_size, utcnow)
    assert x == 0
    assert y == 25


def test_draw_orbs_altitude_opencv(base_config):
    gen = IndiAllskyOrbGenerator(base_config)
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    utcnow = datetime.datetime(2026, 1, 1, 12, 0, 0)

    obs = MagicMock()
    sun = MagicMock()
    moon = MagicMock()

    sun.alt = math.radians(10.0)
    moon.alt = math.radians(-10.0)

    transit = MagicMock()
    transit.datetime.return_value = utcnow + datetime.timedelta(hours=3)
    obs.next_transit.return_value = transit

    gen.drawOrbsAltitude_opencv(img, utcnow, obs, sun, moon)
    assert np.any(img > 0)


def test_draw_orbs_hour_angle_and_azimuth_success(base_config):
    gen = IndiAllskyOrbGenerator(base_config)
    utcnow = datetime.datetime(2026, 1, 1, 12, 0, 0)

    # Real ephem Observer, Sun, Moon in Sydney (where rising and setting both exist)
    obs = ephem.Observer()
    obs.lat = '-33.8688'
    obs.lon = '151.2093'
    obs.elevation = 50
    obs.date = utcnow

    sun = ephem.Sun()
    moon = ephem.Moon()

    img_ha = np.zeros((200, 200, 3), dtype=np.uint8)
    gen.drawOrbsHourAngle_opencv(img_ha, utcnow, obs, sun, moon)
    assert np.any(img_ha > 0)

    img_az = np.zeros((200, 200, 3), dtype=np.uint8)
    gen.drawOrbsAzimuth_opencv(img_az, utcnow, obs, sun, moon)
    assert np.any(img_az > 0)


def test_draw_orbs_hour_angle_exceptions(base_config):
    gen = IndiAllskyOrbGenerator(base_config)
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    utcnow = datetime.datetime(2026, 1, 1, 12, 0, 0)

    obs = MagicMock()
    sun = MagicMock()
    moon = MagicMock()

    # Default getOrbHourAngleXY returns safe coords
    with patch.object(gen, 'getOrbHourAngleXY', return_value=(50, 50)):
        # 1. Test NeverUpError on next_rising and AlwaysUpError on next_setting
        obs.next_rising.side_effect = ephem.NeverUpError
        obs.next_setting.side_effect = ephem.AlwaysUpError
        gen.drawOrbsHourAngle_opencv(img, utcnow, obs, sun, moon)

        # 2. Test AlwaysUpError on next_rising and NeverUpError on next_setting
        obs.next_rising.side_effect = ephem.AlwaysUpError
        obs.next_setting.side_effect = ephem.NeverUpError
        gen.drawOrbsHourAngle_opencv(img, utcnow, obs, sun, moon)


def test_draw_orbs_azimuth_exceptions(base_config):
    gen = IndiAllskyOrbGenerator(base_config)
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    utcnow = datetime.datetime(2026, 1, 1, 12, 0, 0)

    obs = MagicMock()
    sun = MagicMock()
    moon = MagicMock()

    with patch.object(gen, 'getOrbAzimuthXY', return_value=(50, 50)):
        # 1. Test NeverUpError on next_rising and AlwaysUpError on next_setting
        obs.next_rising.side_effect = ephem.NeverUpError
        obs.next_setting.side_effect = ephem.AlwaysUpError
        gen.drawOrbsAzimuth_opencv(img, utcnow, obs, sun, moon)

        # 2. Test AlwaysUpError on next_rising and NeverUpError on next_setting
        obs.next_rising.side_effect = ephem.AlwaysUpError
        obs.next_setting.side_effect = ephem.NeverUpError
        gen.drawOrbsAzimuth_opencv(img, utcnow, obs, sun, moon)
