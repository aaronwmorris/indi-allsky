import ctypes
from datetime import datetime
from multiprocessing import Array
from pathlib import Path
from unittest.mock import MagicMock, patch
from astropy.io import fits
import cv2
import numpy as np
import pytest

from indi_allsky import constants
from indi_allsky.processing import ImageProcessor, ImageData
from indi_allsky.flask.models import IndiAllSkyDbTleDataTable


@pytest.fixture
def ol_processor(base_config, tmp_path):
    config = dict(base_config)
    config['VARLIB_FOLDER'] = str(tmp_path)
    config['LOCATION_LATITUDE'] = -34.9285
    config['LOCATION_LONGITUDE'] = 138.6007
    config['LOCATION_ELEVATION'] = 50.0
    config['NIGHT_SUN_ALT_DEG'] = -6.0
    config['TEXT_PROPERTIES'] = {
        'FONT_COLOR': [255, 255, 255],
        'FONT_X': 10,
        'FONT_Y': 20,
        'PIL_FONT_SIZE': 14,
        'FONT_HEIGHT': 18,
        'FONT_FACE': 'FONT_HERSHEY_SIMPLEX',
        'FONT_AA': 'LINE_AA',
        'FONT_SCALE': 0.5,
        'FONT_THICKNESS': 1,
        'FONT_OUTLINE': True,
        'PIL_FONT_FILE': 'DejaVuSans.ttf',
    }

    position_av = Array('d', [0.0] * 5)
    exposure_av = Array(ctypes.c_int32, [1000000, 1000000, 0, 1000, 100, 30000000, 5000000])
    gain_av = Array(ctypes.c_int32, [100000, 100000, 0, 0, 100000, 100000, 400000, 50000, 200000, 100000])
    binning_av = Array('i', [1, 1, 1, 2, 1, 1])
    sensors_temp_av = Array('f', [0.0] * 110)
    sensors_user_av = Array('f', [0.0] * 110)
    night_av = Array('i', [1, 0])
    astro_av = Array('f', [0.0] * 10)

    ip = ImageProcessor(
        config=config,
        position_av=position_av,
        exposure_av=exposure_av,
        gain_av=gain_av,
        binning_av=binning_av,
        sensors_temp_av=sensors_temp_av,
        sensors_user_av=sensors_user_av,
        night_av=night_av,
        astro_av=astro_av,
    )
    # Populate mock astrometric data
    ip._astrometric_data.update({

        'sun_alt': 10.0,
        'sun_up': 'Yes',
        'sun_next_rise': '06:00',
        'sun_next_rise_h': 12.0,
        'sun_next_set': '18:00',
        'sun_next_set_h': 6.0,
        'sun_next_astro_twilight_rise': '05:00',
        'sun_next_astro_twilight_rise_h': 11.0,
        'sun_next_astro_twilight_set': '19:00',
        'sun_next_astro_twilight_set_h': 7.0,
        'moon_alt': 30.0,
        'moon_phase': 50.0,
        'moon_cycle': 25.0,
        'moon_up': 'Yes',
        'moon_next_rise': '20:00',
        'moon_next_rise_h': 4.0,
        'moon_next_set': '08:00',
        'moon_next_set_h': 16.0,
        'sun_moon_sep': 90.0,
        'mercury_alt': 15.0,
        'mercury_up': 'Yes',
        'venus_alt': 20.0,
        'venus_phase': 75.0,
        'venus_up': 'Yes',
        'mars_alt': 5.0,
        'mars_up': 'Yes',
        'jupiter_alt': 40.0,
        'jupiter_up': 'Yes',
        'saturn_alt': 25.0,
        'saturn_up': 'Yes',
        'iss_alt': 45.0,
        'iss_up': '45°',
        'iss_next_h': 2.5,
        'iss_next_alt': 60.0,
        'hst_alt': 10.0,
        'hst_up': '10°',
        'hst_next_h': 5.0,
        'hst_next_alt': 30.0,
        'tiangong_alt': 0.0,
        'tiangong_up': 'No data',
        'tiangong_next_h': 0.0,
        'tiangong_next_alt': 0.0,
        'sidereal_time': '12:34:56',
    })
    return ip



def make_ref(ip, data, exposure=2.5):
    hdu = fits.PrimaryHDU(data)
    hdulist = fits.HDUList([hdu])
    i_ref = ImageData(
        config=ip.config,
        hdulist=hdulist,
        exposure=exposure,
        gain=100.0,
        binning=1,
        exp_date=datetime(2026, 9, 13, 2, 0, 0),
        exp_elapsed=exposure,
        day_date=datetime(2026, 9, 13).date(),
        camera_id=1,
        camera_name="TestCam",
        camera_uuid="uuid",
        owner="Admin",
        location="Lab",
        image_bitpix=8,
        image_bayerpat='RGGB',
        target_adu=10000,
    )
    i_ref.opencv_data = data
    return i_ref


def test_get_image_label_variations(ol_processor):
    ip = ol_processor
    data = np.full((64, 64, 3), 100, dtype=np.uint8)
    i_ref = make_ref(ip, data, exposure=2.5)

    # 1. Temperature displays: 'f', 'k', 'c'
    ip.config['TEMP_DISPLAY'] = 'f'
    lbl_f = ip.get_image_label(i_ref, [], {})
    assert 'F' in lbl_f

    ip.config['TEMP_DISPLAY'] = 'k'
    lbl_k = ip.get_image_label(i_ref, [], {})
    assert 'K' in lbl_k

    ip.config['TEMP_DISPLAY'] = 'c'
    lbl_c = ip.get_image_label(i_ref, [], {})
    assert 'C' in lbl_c

    # 2. Rational exposures:
    # 2.5 -> '2 1/2'
    # 2.0 -> '2'
    i_ref_whole = make_ref(ip, data, exposure=2.0)
    lbl_whole = ip.get_image_label(i_ref_whole, [], {})
    assert 'Exposure 2.000000' in lbl_whole

    # 0.25 -> '1/4'
    i_ref_frac = make_ref(ip, data, exposure=0.25)
    lbl_frac = ip.get_image_label(i_ref_frac, [], {})
    assert 'Exposure 0.250000' in lbl_frac

    # 3. Privacy mode
    ip.config['PRIVACY_MODE'] = True
    lbl_priv = ip.get_image_label(i_ref, [], {})
    ip.config['PRIVACY_MODE'] = False
    lbl_nopriv = ip.get_image_label(i_ref, [], {})

    # 4. Stacking data labels
    ip.night_av[constants.NIGHT_MOONMODE] = 1
    ip.config['IMAGE_STACK_MOONMODE'] = False
    lbl_sm = ip.get_image_label(i_ref, [], {})

    ip.night_av[constants.NIGHT_MOONMODE] = 0
    ip.night_av[constants.NIGHT_NIGHT] = 0
    ip.config['IMAGE_STACK_DAY'] = False
    lbl_sd = ip.get_image_label(i_ref, [], {})

    ip.night_av[constants.NIGHT_NIGHT] = 1
    ip.stack_count = 5
    ip.config['IMAGE_STACK_COUNT'] = 5
    ip.config['IMAGE_STACK_METHOD'] = 'average'
    lbl_stack5 = ip.get_image_label(i_ref, [], {})

    ip.stack_count = 1
    lbl_stack1 = ip.get_image_label(i_ref, [], {})

    # 5. Stretching data labels
    ip.config['IMAGE_STRETCH'] = {'CLASSNAME': 'Mode1', 'MOONMODE': False}
    ip.night_av[constants.NIGHT_MOONMODE] = 1
    lbl_str_mm = ip.get_image_label(i_ref, [], {})

    ip.night_av[constants.NIGHT_MOONMODE] = 0
    ip.night_av[constants.NIGHT_NIGHT] = 0
    ip.config['IMAGE_STRETCH'] = {'CLASSNAME': 'Mode1', 'DAYTIME': True}
    lbl_str_day = ip.get_image_label(i_ref, [], {})

    ip.config['IMAGE_STRETCH'] = {'CLASSNAME': 'Mode1', 'DAYTIME': False}
    lbl_str_noday = ip.get_image_label(i_ref, [], {})

    # 6. Rain, Dew heater, Fan, Wind direction
    ip.sensors_user_av[constants.SENSOR_USER_RAIN] = 999.0  # triggers KeyError -> 'Error'
    ip.sensors_user_av[constants.SENSOR_USER_DEW_HEATER_LEVEL] = 1.0  # 'On'
    ip.sensors_user_av[constants.SENSOR_USER_FAN_LEVEL] = 1.0  # 'On'
    ip.sensors_user_av[constants.SENSOR_USER_WIND_DIR] = 99999.0  # triggers IndexError -> 'Error'
    lbl_sensors_err = ip.get_image_label(i_ref, [], {})

    ip.sensors_user_av[constants.SENSOR_USER_RAIN] = 0.0
    ip.sensors_user_av[constants.SENSOR_USER_DEW_HEATER_LEVEL] = 0.0
    ip.sensors_user_av[constants.SENSOR_USER_FAN_LEVEL] = 0.0
    ip.sensors_user_av[constants.SENSOR_USER_WIND_DIR] = 180.0
    lbl_sensors_ok = ip.get_image_label(i_ref, [], {'custom_1': 'val1'})

    # 7. Eclipses and moon mode
    ip.night_av[constants.NIGHT_MOONMODE] = 1
    ip.night_av[constants.NIGHT_NIGHT] = 1
    ip.astrometric_data['sun_moon_sep'] = 0.5  # Lunar eclipse
    lbl_lunar = ip.get_image_label(i_ref, [], {})
    assert '* LUNAR ECLIPSE *' in lbl_lunar
    assert '* Moon Mode *' in lbl_lunar

    ip.night_av[constants.NIGHT_MOONMODE] = 0
    ip.night_av[constants.NIGHT_NIGHT] = 0
    ip.astrometric_data['sun_moon_sep'] = 180.0  # Solar eclipse
    lbl_solar = ip.get_image_label(i_ref, [], {})
    assert '* SOLAR ECLIPSE *' in lbl_solar


def test_label_image_pillow_and_opencv(ol_processor, tmp_path):
    ip = ol_processor
    data = np.full((64, 64, 3), 100, dtype=np.uint8)
    i_ref = make_ref(ip, data)
    ip.image_list = [i_ref]
    ip.image = data.copy()

    # 1. Unknown label system
    ip.config['IMAGE_LABEL_SYSTEM'] = 'none'
    ip.label_image()

    # 2. OpenCV labels (normal & focus mode)
    ip.config['IMAGE_LABEL_SYSTEM'] = 'opencv'
    ip.focus_mode = True
    ip.image_xy = [10, 10]
    ip.label_image()
    assert ip.image is not None

    ip.focus_mode = False
    ip.config['IMAGE_LABEL_TEMPLATE'] = '#color:10,20,30\n#xy:5,5\n#anchor:lt\n#size:12\nTest Opencv'
    ip.label_image()
    assert ip.text_color_rgb == [10, 20, 30]
    assert ip.text_xy == [5, 5 + ip.text_font_height]
    assert ip.text_anchor_pillow == 'lt'
    assert ip.text_size_pillow == 12

    # 3. Pillow labels (normal & focus mode & custom font)
    ip.config['IMAGE_LABEL_SYSTEM'] = 'pillow'
    ip.focus_mode = True
    ip.label_image()

    ip.focus_mode = False
    font_file = ip.font_path / 'DejaVuSans.ttf'
    ip.config['TEXT_PROPERTIES']['PIL_FONT_FILE'] = 'custom'
    ip.config['TEXT_PROPERTIES']['PIL_FONT_CUSTOM'] = str(font_file)
    ip.config['TEXT_PROPERTIES']['FONT_OUTLINE'] = False
    ip.label_image()
    assert ip.image is not None


def test_extra_text_and_adsb_and_satellites(ol_processor, tmp_path):
    ip = ol_processor

    # 1. get_extra_text
    ip.config['IMAGE_EXTRA_TEXT'] = ''
    assert ip.get_extra_text() == []

    ip.config['IMAGE_EXTRA_TEXT'] = str(tmp_path / 'nonexistent.txt')
    assert ip.get_extra_text() == []

    ip.config['IMAGE_EXTRA_TEXT'] = str(tmp_path)  # is a directory
    assert ip.get_extra_text() == []

    large_file = tmp_path / 'large.txt'
    large_file.write_bytes(b'A' * 15000)
    ip.config['IMAGE_EXTRA_TEXT'] = str(large_file)
    assert ip.get_extra_text() == []

    normal_file = tmp_path / 'normal.txt'
    normal_file.write_text("Line 1\nLine 2\n")
    ip.config['IMAGE_EXTRA_TEXT'] = str(normal_file)
    lines = ip.get_extra_text()
    assert lines == ["Line 1", "Line 2"]

    # 2. get_adsb_aircraft_text
    ip.config['ADSB'] = {'ENABLE': False}
    assert ip.get_adsb_aircraft_text([]) == []

    ip.config['ADSB'] = {
        'ENABLE': True,
        'LABEL_ENABLE': True,
        'IMAGE_LABEL_TEMPLATE_PREFIX': 'Aircraft:\n',
        'LABEL_LIMIT': 5,
        'AIRCRAFT_LABEL_TEMPLATE': '{flight:s} {squawk:s} {hex:s} {dir:s}',
    }
    aircraft_list = [
        {'flight': 'FL123', 'squawk': '1200', 'hex': 'ABC', 'az': 90.0},
        {'flight': None, 'squawk': None, 'hex': None, 'az': 5000.0},  # IndexError -> 'Error'
    ]
    adsb_lines = ip.get_adsb_aircraft_text(aircraft_list)
    assert len(adsb_lines) >= 3

    # 3. get_satellite_tracking_text
    ip.config['SATELLITE_TRACK'] = {'ENABLE': False}
    assert ip.get_satellite_tracking_text() == []

    ip.config['SATELLITE_TRACK'] = {'ENABLE': True, 'LABEL_ENABLE': False}
    assert ip.get_satellite_tracking_text() == []

    ip.night_av[constants.NIGHT_NIGHT] = 0
    ip.config['SATELLITE_TRACK'] = {'ENABLE': True, 'LABEL_ENABLE': True, 'DAYTIME_TRACK': False}
    assert ip.get_satellite_tracking_text() == []

    ip.night_av[constants.NIGHT_NIGHT] = 1
    ip.config['SATELLITE_TRACK'] = {
        'ENABLE': True,
        'LABEL_ENABLE': True,
        'DAYTIME_TRACK': True,
        'IMAGE_LABEL_TEMPLATE_PREFIX': 'Satellites:\n',
        'ALT_DEG_MIN': 10,
        'LABEL_LIMIT': 5,
        'SAT_LABEL_TEMPLATE': '{title:s} {alt:0.1f} {az:0.1f} {dir:s}',
    }

    dummy_tle1 = MagicMock(title="ISS", line1="1 25544U ...", line2="2 25544 ...")
    dummy_tle2 = MagicMock(title="BAD", line1="invalid", line2="invalid")
    with patch('indi_allsky.flask.models.IndiAllSkyDbTleDataTable.query') as mock_q:
        mock_q.filter.return_value.order_by.return_value.limit.return_value = [dummy_tle1, dummy_tle2]
        sat_lines = ip.get_satellite_tracking_text()
        assert len(sat_lines) >= 1


def test_cardinal_dirs_orbs_and_overlays(ol_processor):
    ip = ol_processor
    data = np.full((64, 64, 3), 100, dtype=np.uint8)
    i_ref = make_ref(ip, data)
    ip.image_list = [i_ref]
    ip.image = data.copy()

    # 1. cardinal_dirs_label
    ip.focus_mode = True
    ip.cardinal_dirs_label()

    ip.focus_mode = False
    ip.config['CARDINAL_DIRS'] = {'ENABLE': False}
    ip.cardinal_dirs_label()

    ip.config['CARDINAL_DIRS'] = {'ENABLE': True}
    ip._cardinal_dirs_label = MagicMock()
    ip._cardinal_dirs_label.main.return_value = data
    ip.cardinal_dirs_label()
    ip._cardinal_dirs_label.main.assert_called_once()

    # 2. orb_image
    ip.focus_mode = True
    ip.orb_image()

    ip.focus_mode = False
    ip.config['ORB_PROPERTIES']['MODE'] = 'off'
    ip.orb_image()

    ip.config['ORB_PROPERTIES']['MODE'] = 'ha'
    ip.orb_image()

    ip.config['ORB_PROPERTIES']['MODE'] = 'az'
    ip.orb_image()

    ip.config['ORB_PROPERTIES']['MODE'] = 'alt'
    ip.orb_image()

    ip.config['ORB_PROPERTIES']['MODE'] = 'unknown'
    ip.orb_image()

    # 3. moon, lightgraph, image overlays
    ip.focus_mode = True
    ip.moon_overlay()
    ip.lightgraph_overlay()
    ip.image_overlay()

    ip.focus_mode = False
    ip.config['MOON_OVERLAY'] = {'ENABLE': True}
    ip._moon_overlay = MagicMock()
    ip.moon_overlay()
    ip._moon_overlay.apply.assert_called_once()

    ip.config['LIGHTGRAPH_OVERLAY'] = {'ENABLE': True}
    ip._lightgraph_overlay = MagicMock()
    ip.lightgraph_overlay()
    ip._lightgraph_overlay.apply.assert_called_once()

    ip.config['IMAGE_OVERLAY'] = {'ENABLE': True}
    ip._image_overlay_o = MagicMock()
    ip.image_overlay()
    ip._image_overlay_o.apply.assert_called_once()


def test_add_border_and_colormap(ol_processor):
    ip = ol_processor
    data = np.full((32, 32, 3), 100, dtype=np.uint8)
    ip.image = data.copy()

    # 1. add_border
    ip.focus_mode = True
    ip.add_border()

    ip.focus_mode = False
    ip.config['IMAGE_BORDER'] = {'TOP': 0, 'LEFT': 0, 'RIGHT': 0, 'BOTTOM': 0}
    ip.add_border()

    ip.config['IMAGE_BORDER'] = {'TOP': 5, 'LEFT': 5, 'RIGHT': 5, 'BOTTOM': 5, 'COLOR': [0, 0, 0]}
    ip.add_border()
    assert ip.image.shape == (42, 42, 3)

    # 2. colormap
    ip.focus_mode = True
    ip.colormap()

    ip.focus_mode = False
    ip.config['IMAGE_COLORMAP'] = ''
    ip.colormap()

    # 2D mono colormap
    ip.image = np.linspace(0, 255, 32 * 32, dtype=np.uint8).reshape((32, 32))
    ip.config['IMAGE_COLORMAP'] = 'COLORMAP_JET'
    ip.colormap()
    assert ip.image.shape == (32, 32, 3)

    # 3D color colormap
    ip.config['IMAGE_COLORMAP'] = 'COLORMAP_HOT'
    ip.colormap()
    assert ip.image.shape == (32, 32, 3)

    # Unknown colormap
    ip.config['IMAGE_COLORMAP'] = 'COLORMAP_NONEXISTENT'
    ip.colormap()


def test_fish2pano_and_circular_display(ol_processor):
    ip = ol_processor
    data = np.full((64, 64, 3), 100, dtype=np.uint8)
    ip.image = data.copy()

    ip.config['LENS_OFFSET_X'] = 2
    ip.config['LENS_OFFSET_Y'] = -2
    ip.config['FISH2PANO'] = {'DIAMETER': 50, 'ROTATE_ANGLE': 45}

    pano = ip.fish2pano(1)
    assert pano is not None

    # fish2pano_cardinal_dirs_label
    ip.config['CARDINAL_DIRS'] = {'ENABLE': False}
    assert ip.fish2pano_cardinal_dirs_label(pano) is pano

    ip.config['CARDINAL_DIRS'] = {'ENABLE': True}
    ip._cardinal_dirs_label = MagicMock()
    ip._cardinal_dirs_label.panorama_label.return_value = pano
    res = ip.fish2pano_cardinal_dirs_label(pano)
    ip._cardinal_dirs_label.panorama_label.assert_called_once_with(pano)

    # circular_display
    ip.config['CIRCULAR_DISPLAY'] = {'IMAGE_CIRCLE_DIAMETER': 40, 'RESOLUTION': 64}
    circ = ip.circular_display(1)
    assert circ.shape == (64, 64, 3)
