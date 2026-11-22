import ctypes
from datetime import datetime, timezone
import math
from multiprocessing import Array
from pathlib import Path
from unittest.mock import MagicMock, patch

from astropy.io import fits
import cv2
import ephem
import numpy as np
import pytest

from indi_allsky import constants
from indi_allsky.exceptions import BadImage
from indi_allsky.processing import ImageProcessor, ImageData


class DummyCamera:
    def __init__(self):
        self.id = 1
        self.name = "Test_Camera"
        self.uuid = "12345678-1234-5678-1234-567812345678"
        self.location = "Observatory"
        self.lensFocalLength = 2.5
        self.lensFocalRatio = 1.4
        self.lensImageCircle = 1000
        self.width = 64
        self.height = 64
        self.pixelSize = 2.9
        self.cfa = constants.CFA_RGGB
        self.owner = "Admin"
        self.data = {
            'KPINDEX_CURRENT': 3.5,
            'OVATION_MAX': 50,
            'AURORA_MAG_BT': 5.0,
            'AURORA_MAG_GSM_BZ': -2.0,
            'AURORA_PLASMA_DENSITY': 4.0,
            'AURORA_PLASMA_SPEED': 450.0,
            'AURORA_PLASMA_TEMP': 100000,
            'AURORA_N_HEMI_GW': 20,
            'AURORA_S_HEMI_GW': 22,
            'SMOKE_RATING': constants.SMOKE_RATING_CLEAR,
        }


@pytest.fixture
def dummy_camera():
    return DummyCamera()


@pytest.fixture
def proc_fixture(base_config, tmp_path):
    config = dict(base_config)
    config['VARLIB_FOLDER'] = str(tmp_path)
    config['IMAGE_FOLDER'] = str(tmp_path / 'images')
    config['LOCATION_LATITUDE'] = -34.9285
    config['LOCATION_LONGITUDE'] = 138.6007
    config['LOCATION_ELEVATION'] = 50.0
    config['NIGHT_SUN_ALT_DEG'] = -6.0

    position_av = Array('d', [0.0] * 5)
    exposure_av = Array(ctypes.c_int32, [1000000, 1000000, 0, 1000, 100, 30000000, 5000000])
    gain_av = Array(ctypes.c_int32, [100000, 100000, 0, 0, 100000, 100000, 400000, 50000, 200000, 100000])
    binning_av = Array('i', [1, 1, 1, 2, 1, 1])
    sensors_temp_av = Array('f', [0.0] * 110)
    sensors_user_av = Array('f', [0.0] * 110)
    night_av = Array('i', [1, 0])
    astro_av = Array('f', [0.0] * 10)

    processor = ImageProcessor(
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
    return processor


def test_processing_stars_method_and_stretch_config(proc_fixture):
    # Test DETECT_STARS_METHOD sep (lines 391-392)
    proc_fixture.config['DETECT_STARS_METHOD'] = 'sep'
    # Test IMAGE_STRETCH CLASSNAME (lines 405-406)
    proc_fixture.config['IMAGE_STRETCH'] = {'CLASSNAME': 'mode3_adaptive_mtf'}
    proc_fixture.post_init()
    assert proc_fixture._stretch_o is not None


def test_add_stacking_branches(proc_fixture, tmp_path, dummy_camera):
    proc_fixture.post_init()
    test_fits = tmp_path / 'test_stack.fits'
    hdu = fits.PrimaryHDU(np.zeros((32, 32), dtype=np.uint8))
    hdu.writeto(str(test_fits))

    # 1. moonmode without IMAGE_STACK_MOONMODE -> clears image_list (line 456)
    proc_fixture.night_av[constants.NIGHT_MOONMODE] = 1
    proc_fixture.config['IMAGE_STACK_MOONMODE'] = False
    proc_fixture.image_list.append(MagicMock())
    proc_fixture.add(test_fits, 1.0, 100, 1, datetime.now(), 1.0, dummy_camera)
    assert len(proc_fixture.image_list) == 1

    # 2. daytime stacking enabled warning (line 462)
    proc_fixture.night_av[constants.NIGHT_MOONMODE] = 0
    proc_fixture.night_av[constants.NIGHT_NIGHT] = 0
    proc_fixture.config['IMAGE_STACK_DAY'] = True
    proc_fixture.stack_count = 3
    proc_fixture.add(test_fits, 1.0, 100, 1, datetime.now(), 1.0, dummy_camera)


def test_add_unsupported_format(proc_fixture, tmp_path, dummy_camera):
    proc_fixture.post_init()
    bad_file = tmp_path / 'test.unsupported'
    bad_file.write_text('bad')
    with pytest.raises(Exception, match='Unsupported image format'):
        proc_fixture.add(bad_file, 1.0, 100, 1, datetime.now(), 1.0, dummy_camera)


def test_add_fits_errors_and_headers(proc_fixture, tmp_path, dummy_camera):
    proc_fixture.post_init()

    # Corrupt FITS file -> OSError -> BadImage (lines 532-533)
    corrupt_fits = tmp_path / 'corrupt.fits'
    corrupt_fits.write_bytes(b'not a valid fits file content')
    with pytest.raises(BadImage):
        proc_fixture.add(corrupt_fits, 1.0, 100, 1, datetime.now(), 1.0, dummy_camera)

    # FITS with missing EXPTIME and GAIN in header (lines 550-556)
    fits_no_exp = tmp_path / 'no_exp.fits'
    hdu = fits.PrimaryHDU(np.full((32, 32), 50, dtype=np.uint8))
    hdu.writeto(str(fits_no_exp))

    i_ref = proc_fixture.add(fits_no_exp, 2.5, 150.0, 1, datetime.now(), 2.5, dummy_camera)
    assert i_ref.exposure == 2.5
    assert i_ref.gain == 150.0


def test_add_jpeg_and_png_branches(proc_fixture, tmp_path, dummy_camera):
    proc_fixture.post_init()

    # 1. Corrupt JPEG -> BadImage (lines 584-585)
    bad_jpg = tmp_path / 'corrupt.jpg'
    bad_jpg.write_bytes(b'\xff\xd8\xff\xe0corrupt')
    with pytest.raises(BadImage):
        proc_fixture.add(bad_jpg, 1.0, 100, 1, datetime.now(), 1.0, dummy_camera)

    # 2. Valid JPEG with PRIVACY_MODE (lines 618-621)
    proc_fixture.config['PRIVACY_MODE'] = True
    good_jpg = tmp_path / 'good.jpg'
    img_bgr = np.full((32, 32, 3), 100, dtype=np.uint8)
    cv2.imwrite(str(good_jpg), img_bgr)
    i_ref_jpg = proc_fixture.add(good_jpg, 1.0, 100, 1, datetime.now(), 1.0, dummy_camera)
    assert i_ref_jpg is not None

    # 3. Bad PNG (cv2.imread returns None) (line 642)
    bad_png = tmp_path / 'bad.png'
    bad_png.write_bytes(b'not a png')
    with pytest.raises(BadImage):
        proc_fixture.add(bad_png, 1.0, 100, 1, datetime.now(), 1.0, dummy_camera)

    # 4. PNG with 4 channels (RGBA) and PRIVACY_MODE (lines 648, 681-684)
    rgba_png = tmp_path / 'rgba.png'
    img_rgba = np.full((32, 32, 4), 200, dtype=np.uint8)
    cv2.imwrite(str(rgba_png), img_rgba)
    i_ref_png = proc_fixture.add(rgba_png, 1.0, 100, 1, datetime.now(), 1.0, dummy_camera)
    assert i_ref_png is not None


def test_custom_fits_headers_and_bit_depth_overrides(proc_fixture, tmp_path, dummy_camera):
    proc_fixture.post_init()

    # FITSHEADERS edge cases (lines 803-805, 809) and preserve INSTRUME
    proc_fixture.config['FITSHEADERS'] = [
        (),                  # triggers IndexError at line 804
        ('', 'some_value'),  # triggers line 809 not k
        ('VALIDKEY', 'VALIDVAL'),
        ('INSTRUME', 'indi_pylibcamera'),
    ]

    # CCD_BIT_DEPTH override (lines 866-870)
    proc_fixture.config['CCD_BIT_DEPTH'] = 14

    fits_file = tmp_path / 'header_test.fits'
    hdu = fits.PrimaryHDU(np.full((32, 32), 200, dtype=np.uint8))
    hdu.header['EXPTIME'] = 1.0
    hdu.header['GAIN'] = 100.0
    hdu.header['INSTRUME'] = 'indi_pylibcamera'
    hdu.header['OFFSET_0'] = 64
    hdu.writeto(str(fits_file))

    # Camera data with invalid SMOKE_RATING string (lines 901-906)
    dummy_camera.data['SMOKE_RATING'] = 'invalid_smoke_string'

    i_ref = proc_fixture.add(fits_file, 1.0, 100, 1, datetime.now(), 1.0, dummy_camera)
    assert i_ref.libcamera_black_level is True  # line 883 & line 4746
    assert proc_fixture.max_bit_depth == 14  # line 870


def test_image_processor_manipulations_and_focus_mode(proc_fixture):
    proc_fixture.post_init()
    proc_fixture.image = np.full((64, 64, 3), 100, dtype=np.uint8)

    # 1. Unknown stack method (lines 1773-1776)
    proc_fixture.stack_method = 'unknown_stack_method'
    mock_iref = MagicMock()
    mock_iref.opencv_data = np.zeros((64, 64, 3), dtype=np.uint8)
    mock_iref.image_bitpix = 8
    mock_iref.asi676mc_repair_result = None
    mock_iref.binning = 1
    proc_fixture.image_list = [mock_iref, mock_iref]
    proc_fixture.stack()

    # 2. _convert_16bit_to_8bit when image_bitpix == 8 (line 1850)
    mock_iref.image_bitpix = 8
    res = proc_fixture._convert_16bit_to_8bit(mock_iref)
    assert np.array_equal(res, proc_fixture.image)

    # 3. Unknown rotation option (lines 1867-1869)
    proc_fixture.config['IMAGE_ROTATE'] = 'NONEXISTENT_ROTATION'
    proc_fixture.rotate_90()

    # 4. rotate_angle with keep_size: True (lines 1915-1916)
    proc_fixture.config['IMAGE_ROTATE_ANGLE'] = 45.0
    proc_fixture.config['IMAGE_ROTATE_KEEP_SIZE'] = True
    proc_fixture.rotate_angle()

    # 5. flip_v and flip_h when config is False (lines 1957, 1965)
    proc_fixture.config['IMAGE_FLIP_V'] = False
    proc_fixture.config['IMAGE_FLIP_H'] = False
    assert proc_fixture.flip_v() is None
    assert proc_fixture.flip_h() is None

    # 6. Focus mode early returns (lines 1974, 1989, 2004, 2157)
    proc_fixture.focus_mode = True
    assert proc_fixture.detectLines() is None
    assert proc_fixture.detectStars() is None
    assert proc_fixture.drawDetections() is None
    assert proc_fixture.white_balance_manual_bgr() is None

    # 7. white_balance_manual_bgr on mono image (line 2162)
    proc_fixture.focus_mode = False
    proc_fixture.image = np.full((32, 32), 100, dtype=np.uint8)
    proc_fixture.white_balance_manual_bgr()

    # 8. Unknown denoise and SCNR algorithms (lines 2108-2110, 2150-2151)
    proc_fixture.config['DENOISE_ALGORITHM'] = 'unknown_denoise'
    proc_fixture.denoise()
    proc_fixture._scnr('unknown_scnr')

    # 9. white_balance_auto_bgr ZeroDivisionError branches (lines 2299-2300, 2304-2305)
    zero_gr_img = np.zeros((10, 10, 3), dtype=np.uint8)
    zero_gr_img[:, :, 0] = 50  # Blue only
    proc_fixture.image = zero_gr_img
    proc_fixture._white_balance_auto_bgr()

    # 10. circleHoles on mono image (line 2608)
    mono_img = np.zeros((32, 32), dtype=np.uint8)
    proc_fixture.image = mono_img
    mock_iref_holes = MagicMock()
    mock_iref_holes.hole_mask = np.zeros((32, 32), dtype=bool)
    mock_iref_holes.hole_mask[10, 10] = True
    proc_fixture.circleHoles(mock_iref_holes)

    # 11. apply_logo_overlay already failed (lines 2663-2664, 2670-2671)
    proc_fixture.config['LOGO_OVERLAY'] = '/nonexistent/logo.png'
    proc_fixture._overlay_dict[1] = False
    proc_fixture.apply_logo_overlay(1)


def test_astrometric_and_satellite_edge_cases(proc_fixture):
    # ephem AlwaysUpError and NeverUpError (lines 2847-2849, 2860-2861, 2878-2880, 2891-2892, 2909-2911, 2922-2923)
    proc_fixture.post_init()
    with patch('ephem.Observer.next_rising', side_effect=ephem.AlwaysUpError), \
         patch('ephem.Observer.next_setting', side_effect=ephem.NeverUpError):
        proc_fixture.update_astrometric_data(datetime.now())
        assert proc_fixture.astrometric_data['sun_next_rise'] == '--:--'
        assert proc_fixture.astrometric_data['sun_next_set'] == '--:--'
        assert proc_fixture.astrometric_data['moon_next_rise'] == '--:--'
        assert proc_fixture.astrometric_data['moon_next_set'] == '--:--'

    # Satellite passes alt < 0 and next_pass returns None or alt (lines 3005, 3012-3020, 3041, 3050-3058, 3081, 3088-3096)
    mock_iss = MagicMock()
    mock_iss.alt = -0.1
    mock_hst = MagicMock()
    mock_hst.alt = 0.5
    mock_tiangong = MagicMock()
    mock_tiangong.alt = -0.2

    mock_pass_tuple = (MagicMock(datetime=lambda: datetime.now()), None, None, math.radians(45.0), None)

    sat_dict = {
        'iss': mock_iss,
        'hst': mock_hst,
        'tiangong': mock_tiangong,
    }
    with patch.object(proc_fixture, 'populateSatelliteData', return_value=sat_dict), \
         patch('ephem.Observer.next_pass', return_value=mock_pass_tuple):
        proc_fixture.update_astrometric_data(datetime.now())
        assert proc_fixture.astrometric_data['iss_up'] == 'No'
        assert proc_fixture.astrometric_data['tiangong_up'] == 'No'
        assert proc_fixture.astrometric_data['hst_alt'] > 0

    # Test populateSatelliteData ephem.readtle ValueError (lines 3126-3132)
    proc_fixture.satellite_dict = {'test_sat': {'group': 'stations', 'title': 'TEST'}}
    mock_sat_entry = MagicMock()
    mock_sat_entry.title = 'TEST'
    mock_sat_entry.line1 = 'BAD_LINE1'
    mock_sat_entry.line2 = 'BAD_LINE2'
    with patch('indi_allsky.processing.IndiAllSkyDbTleDataTable.query') as mock_query, \
         patch('ephem.readtle', side_effect=ValueError('bad tle')):
        mock_query.filter.return_value.filter.return_value.order_by.return_value.first.return_value = mock_sat_entry
        sats = proc_fixture.populateSatelliteData()
        assert 'test_sat' not in sats


def test_labels_extra_text_and_satellite_tracking(proc_fixture, tmp_path):
    proc_fixture.post_init()

    # 1. PermissionError in get_extra_text (lines 3702-3704, 3710-3712)
    extra_txt = tmp_path / 'extra.txt'
    extra_txt.write_text('Custom line 1\nCustom line 2')
    proc_fixture.config['IMAGE_EXTRA_TEXT'] = str(extra_txt)
    with patch('pathlib.Path.stat', side_effect=PermissionError('Access denied')):
        assert proc_fixture.get_extra_text() == []

    with patch('io.open', side_effect=PermissionError('Access denied')):
        assert proc_fixture.get_extra_text() == []

    # 2. ADSB disabled in labels (line 3725)
    proc_fixture.config['ADSB'] = {'ENABLE': True, 'LABEL_ENABLE': False}
    assert proc_fixture.get_adsb_aircraft_text([]) == []

    # 3. get_satellite_tracking_text loop & formatting (lines 3828-3866, 3885-3888)
    proc_fixture.config['SATELLITE_TRACK'] = {
        'ENABLE': True,
        'LABEL_ENABLE': True,
        'ALT_DEG_MIN': 10.0,
        'LABEL_LIMIT': 2,
        'SAT_LABEL_TEMPLATE': '{title}: alt {alt:0.1f}',
    }
    mock_sat = MagicMock()
    mock_sat.eclipsed = False
    mock_sat.alt = math.radians(45.0)
    mock_sat.az = math.radians(90.0)
    mock_sat.elevation = 400000.0
    mock_sat.mag = 1.0
    mock_sat.sublat = math.radians(20.0)
    mock_sat.sublong = math.radians(130.0)
    mock_sat.range = 500000.0
    mock_sat.range_velocity = 7000.0

    mock_db_sat = MagicMock()
    mock_db_sat.title = 'ISS'
    mock_db_sat.line1 = '1 25544U'
    mock_db_sat.line2 = '2 25544U'

    with patch('indi_allsky.processing.IndiAllSkyDbTleDataTable.query') as mock_query, \
         patch('ephem.readtle', return_value=mock_sat):
        mock_query.filter.return_value.order_by.return_value.limit.return_value = [mock_db_sat]
        sat_text = proc_fixture.get_satellite_tracking_text()
        assert len(sat_text) > 0
        assert 'ISS' in sat_text[0]

    # 4. orb_image when orb_mode == 'off' (line 3509)
    proc_fixture.config['ORB_PROPERTIES'] = {'MODE': 'off'}
    proc_fixture.orb_image()


def test_realtime_keogram_and_masks_coverage(proc_fixture, tmp_path):
    proc_fixture.post_init()
    proc_fixture.image = np.full((32, 32, 3), 100, dtype=np.uint8)
    proc_fixture._keogram_store_p = tmp_path / 'keogram.npy'
    proc_fixture._keogram_store_metadata_p = tmp_path / 'keogram.json'

    # 1. realtimeKeogramUpdate EOFError and FileNotFoundError (lines 4271-4277, 4282, 4285)
    with patch.object(proc_fixture, 'realtimeKeogramDataLoad', side_effect=EOFError):
        proc_fixture.realtimeKeogramUpdate()
    with patch.object(proc_fixture, 'realtimeKeogramDataLoad', side_effect=FileNotFoundError):
        proc_fixture.realtimeKeogramUpdate()

    # 2. _load_detection_mask PermissionError (lines 4381-4383)
    mask_file = tmp_path / 'det_mask.png'
    mask_file.write_bytes(b'fake')
    proc_fixture.config['DETECT_MASK'] = str(mask_file)
    with patch('pathlib.Path.is_file', side_effect=PermissionError('Denied')):
        masks = proc_fixture._load_detection_mask()
        assert masks == {1: None, 2: None}

    # 3. _load_logo_overlay with empty config, PermissionError, and non-RGBA image (lines 4418-4419, 4434-4436, 4473-4475)
    proc_fixture.config['LOGO_OVERLAY'] = ''
    assert proc_fixture._load_logo_overlay(proc_fixture.image, 1) == (None, None)

    logo_file = tmp_path / 'logo.png'
    logo_file.write_bytes(b'fake')
    proc_fixture.config['LOGO_OVERLAY'] = str(logo_file)
    with patch('pathlib.Path.exists', side_effect=PermissionError('Denied')):
        assert proc_fixture._load_logo_overlay(proc_fixture.image, 1) == (None, None)

    # Non-RGBA logo (grayscale, 2D) -> raises IndexError on shape[2] -> returns False, None
    cv2.imwrite(str(logo_file), np.full((32, 32), 255, dtype=np.uint8))
    res_bgr, res_alpha = proc_fixture._load_logo_overlay(proc_fixture.image, 1)
    assert res_bgr is False
    assert res_alpha is None

    # 4. _generateAduMask with ADU_ROI (lines 4500-4502)
    proc_fixture.config['ADU_ROI'] = [5, 5, 25, 25]
    proc_fixture._generateAduMask(proc_fixture.image, 1)
    assert proc_fixture._adu_mask_dict[1].shape == (32, 32)
    assert proc_fixture._adu_mask_dict[1][10, 10] == 255
    assert proc_fixture._adu_mask_dict[1][0, 0] == 0

    # 5. ImageData properties: exp_elapsed (line 4674), libcamera_black_level setter (line 4746)
    img_data = ImageData(
        proc_fixture.config,
        fits.HDUList([fits.PrimaryHDU(np.zeros((10, 10), dtype=np.uint8))]),
        1.0, 100, 1, datetime.now(), 1.234, datetime.now().date(),
        1, "Cam", "uuid", "Owner", "Loc", 8, None, 100
    )
    assert img_data.exp_elapsed == 1.234
    img_data.libcamera_black_level = 16
    assert img_data.libcamera_black_level is True
