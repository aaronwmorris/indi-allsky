import ctypes
from datetime import datetime, timezone
import math
from multiprocessing import Array
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from astropy.io import fits
import cv2
import ephem
import numpy as np

from indi_allsky import constants
from indi_allsky.exceptions import BadImage
from indi_allsky.flask import db
from indi_allsky.flask.models import IndiAllSkyDbTleDataTable
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


def test_dng_processing_rawpy_unavailable(proc_fixture, tmp_path, dummy_camera):
    """Cover lines 701-702: rawpy module not available exception."""
    proc_fixture.post_init()
    dng_file = tmp_path / 'test.dng'
    dng_file.write_bytes(b'dummy dng content')

    with patch('indi_allsky.processing.rawpy', None):
        with pytest.raises(Exception, match='rawpy module not available'):
            proc_fixture.add(
                dng_file,
                1.0,
                100.0,
                1,
                datetime.now(),
                1.0,
                dummy_camera,
            )


def test_dng_processing_libraw_io_error(proc_fixture, tmp_path, dummy_camera):
    """Cover lines 707-708: LibRawIOError raised as BadImage."""
    rawpy = pytest.importorskip('rawpy')
    proc_fixture.post_init()
    dng_file = tmp_path / 'corrupt.dng'
    dng_file.write_bytes(b'corrupt')

    with patch('rawpy.imread', side_effect=rawpy._rawpy.LibRawIOError):
        with pytest.raises(BadImage):
            proc_fixture.add(
                dng_file,
                1.0,
                100.0,
                1,
                datetime.now(),
                1.0,
                dummy_camera,
            )


def test_dng_processing_success_and_cfa_variants(proc_fixture, tmp_path, dummy_camera):
    """Cover lines 519, 704-787: DNG parsing, privacy mode, and bayer pattern detection."""
    pytest.importorskip('rawpy')
    proc_fixture.post_init()
    dng_file = tmp_path / 'valid.dng'
    dng_file.write_bytes(b'fake dng')

    mock_raw = MagicMock()
    mock_raw.raw_image = np.zeros((32, 32), dtype=np.uint16)
    mock_raw.color_desc = b'RGBG'
    mock_raw.raw_pattern = np.array([[0, 1], [3, 2]])  # RGGB

    # Case 1: normal DNG with privacy mode False
    proc_fixture.config['PRIVACY_MODE'] = False
    with patch('rawpy.imread', return_value=mock_raw):
        i_ref = proc_fixture.add(
            dng_file,
            1.0,
            100.0,
            1,
            datetime.now(),
            1.0,
            dummy_camera,
        )
        assert i_ref is not None

    # Case 2: privacy mode True + raw_pattern causes IndexError + camera.cfa fallback
    proc_fixture.config['PRIVACY_MODE'] = True
    mock_raw.raw_pattern = np.array([[0, 99], [99, 99]])  # IndexError on color_desc
    with patch('rawpy.imread', return_value=mock_raw):
        i_ref = proc_fixture.add(
            dng_file,
            1.0,
            100.0,
            1,
            datetime.now(),
            1.0,
            dummy_camera,
        )
        assert i_ref is not None

    # Case 3: raw_pattern is None + config CFA_PATTERN override
    proc_fixture.config['CFA_PATTERN'] = 'GRBG'
    mock_raw.raw_pattern = None
    dummy_camera.owner = None
    with patch('rawpy.imread', return_value=mock_raw):
        i_ref = proc_fixture.add(
            dng_file,
            1.0,
            100.0,
            1,
            datetime.now(),
            1.0,
            dummy_camera,
        )
        assert i_ref is not None


def test_add_unsupported_image_format(proc_fixture, tmp_path, dummy_camera):
    """Cover line 525: Unsupported image format in add()."""
    proc_fixture.post_init()
    bmp_file = tmp_path / 'test.bmp'
    bmp_file.write_bytes(b'dummy')

    with pytest.raises(Exception, match='Unsupported image format'):
        proc_fixture.add(
            bmp_file,
            1.0,
            100.0,
            1,
            datetime.now(),
            1.0,
            dummy_camera,
        )


def test_smoke_rating_type_error(proc_fixture, tmp_path, dummy_camera):
    """Cover lines 904-906: TypeError when casting smoke rating."""
    proc_fixture.post_init()
    dummy_camera.data['SMOKE_RATING'] = [1, 2, 3]  # triggers TypeError on int()
    fits_file = tmp_path / 'test_smoke.fits'
    hdu = fits.PrimaryHDU(np.zeros((32, 32), dtype=np.uint8))
    hdu.writeto(str(fits_file))

    i_ref = proc_fixture.add(
        fits_file,
        1.0,
        100.0,
        1,
        datetime.now(),
        1.0,
        dummy_camera,
    )
    assert i_ref is not None


def test_rotate_image_with_offset(proc_fixture):
    """Cover line 1905: _rotate_angle with use_offset=True."""
    proc_fixture.post_init()
    proc_fixture.image = np.zeros((64, 64, 3), dtype=np.uint8)
    proc_fixture._rotate_angle(45, use_offset=True)
    assert proc_fixture.image is not None


def test_denoise_unknown_algorithm(proc_fixture):
    """Cover lines 2108-2110: AttributeError for unknown denoise algorithm."""
    proc_fixture.post_init()
    proc_fixture.image = np.zeros((64, 64, 3), dtype=np.uint8)
    proc_fixture.config['IMAGE_DENOISE'] = 'nonexistent_algorithm'
    proc_fixture.denoise()


def test_add_logo_load_overlay_failure(proc_fixture):
    """Cover lines 2670-2671: logo overlay failed to load."""
    proc_fixture.post_init()
    proc_fixture.image = np.zeros((64, 64, 3), dtype=np.uint8)
    proc_fixture.config['LOGO_OVERLAY'] = 'dummy_logo.png'
    with patch.object(proc_fixture, '_load_logo_overlay', return_value=(False, False)):
        proc_fixture.apply_logo_overlay(binning=1)


def test_calculate_astrometry_next_pass_none(proc_fixture):
    """Cover lines 3015, 3020, 3053, 3058, 3091, 3096."""
    proc_fixture.post_init()
    mock_sat = MagicMock()
    mock_sat.alt = 0.5

    satellite_data = {
        'iss': mock_sat,
        'hst': mock_sat,
        'tiangong': mock_sat,
    }

    with patch.object(proc_fixture, 'populateSatelliteData', return_value=satellite_data), \
         patch('ephem.Observer.next_pass', return_value=(None, None, None, None)):
        proc_fixture.update_astrometric_data(datetime.now())

    assert proc_fixture.astrometric_data['iss_next_h'] == 0.0
    assert proc_fixture.astrometric_data['iss_next_alt'] == 0.0
    assert proc_fixture.astrometric_data['hst_next_h'] == 0.0
    assert proc_fixture.astrometric_data['tiangong_next_h'] == 0.0
    assert proc_fixture.astrometric_data['tiangong_next_alt'] == 0.0


def test_populate_satellite_data_success(proc_fixture):
    """Cover line 3132: successfully populating satellite TLE data."""
    proc_fixture.post_init()
    mock_sat_entry = MagicMock()
    mock_sat_entry.title = 'ISS'
    mock_sat_entry.line1 = 'line1'
    mock_sat_entry.line2 = 'line2'

    mock_sat = MagicMock()
    with patch('indi_allsky.processing.IndiAllSkyDbTleDataTable.query') as mock_query, \
         patch('ephem.readtle', return_value=mock_sat):
        mock_query.filter.return_value.filter.return_value.order_by.return_value.first.return_value = mock_sat_entry
        proc_fixture.satellite_dict = {
            'iss': {'title': 'ISS', 'group': 'stations'},
        }
        sat_data = proc_fixture.populateSatelliteData()
        assert sat_data['iss'] is mock_sat


def test_get_image_label_extra_adsb_and_sat_lines(proc_fixture):
    """Cover lines 3390-3393, 3401-3402, 3410-3411: extra text, aircraft, satellite lines."""
    proc_fixture.post_init()
    proc_fixture.config['IMAGE_EXTRA_TEXT'] = 'extra.txt'
    proc_fixture.config['IMAGE_LABEL_TEMPLATE'] = '{exposure}'
    proc_fixture.update_astrometric_data(datetime.now())
    proc_fixture.astrometric_data['hst_next_alt'] = 0.0
    i_ref = MagicMock()
    i_ref.exposure = 1.0
    i_ref.gain = 100
    i_ref.gain_f = 100.0
    i_ref.temp = 20.0
    i_ref.stars = [1, 2, 3]
    i_ref.lines = []
    i_ref.sqm_value = 21.0
    i_ref.smoke_rating = constants.SMOKE_RATING_CLEAR
    i_ref.owner = 'Admin'
    i_ref.location = 'Observatory'
    i_ref.kpindex = 2.0
    i_ref.ovation_max = 50
    i_ref.aurora_mag_bt = 5.0
    i_ref.aurora_mag_gsm_bz = -2.0
    i_ref.aurora_plasma_density = 4.0
    i_ref.aurora_plasma_speed = 400.0
    i_ref.aurora_plasma_temp = 100000
    i_ref.aurora_n_hemi_gw = 20
    i_ref.aurora_s_hemi_gw = 22
    i_ref.day_date = '20260913'
    i_ref.exp_date = datetime.now()
    i_ref.exp_date_utc = datetime.now(timezone.utc)

    with patch.object(proc_fixture, 'get_extra_text', return_value=['Extra Line 1', 'Extra Line 2']), \
         patch.object(proc_fixture, 'get_adsb_aircraft_text', return_value=['Aircraft A1', 'Aircraft A2']), \
         patch.object(proc_fixture, 'get_satellite_tracking_text', return_value=['Satellite S1']):
        label = proc_fixture.get_image_label(i_ref, adsb_aircraft_list=['dummy'], custom_hook_data={})
        assert 'Extra Line 1' in label
        assert 'Aircraft A1' in label
        assert 'Satellite S1' in label


def test_draw_orbs_off(proc_fixture):
    """Cover line 3509: orb_mode == 'off'."""
    proc_fixture.post_init()
    proc_fixture.image = np.zeros((64, 64, 3), dtype=np.uint8)
    proc_fixture.config['ORB_PROPERTIES'] = {'MODE': 'off'}
    i_ref = MagicMock()
    proc_fixture._image_orb_opencv(i_ref)


def test_get_satellite_tracking_eclipsed_and_dir_error(proc_fixture):
    """Cover lines 3832, 3838, and 3861-3863: eclipsed, low altitude, and direction IndexError."""
    proc_fixture.post_init()
    proc_fixture.config['SATELLITE_TRACK'] = {
        'ENABLE': True,
        'LABEL_ENABLE': True,
        'DAYTIME_TRACK': True,
        'ALT_DEG_MIN': 20.0,
        'LABEL_LIMIT': 10,
        'SAT_LABEL_TEMPLATE': '{title} {dir}',
    }

    # Case 1: sat is eclipsed (line 3832)
    entry_eclipsed = MagicMock(title='SAT_ECL', line1='l1', line2='l2')
    sat_eclipsed = MagicMock()
    sat_eclipsed.eclipsed = True

    # Case 2: sat alt < alt_deg_min (line 3838)
    entry_low = MagicMock(title='SAT_LOW', line1='l1', line2='l2')
    sat_low = MagicMock()
    sat_low.eclipsed = False
    sat_low.alt = math.radians(5.0)

    # Case 3: sat valid, but cardinal_directions raises IndexError (lines 3861-3863)
    entry_valid = MagicMock(title='SAT_VALID', line1='l1', line2='l2')
    sat_valid = MagicMock()
    sat_valid.eclipsed = False
    sat_valid.alt = math.radians(45.0)
    sat_valid.az = math.radians(359.9)
    sat_valid.elevation = 500000
    sat_valid.mag = 2.0
    sat_valid.sublat = 0.1
    sat_valid.sublong = 0.1
    sat_valid.range = 600000
    sat_valid.range_velocity = 7000

    def mock_readtle(title, l1, l2):
        if title == 'SAT_ECL':
            return sat_eclipsed
        elif title == 'SAT_LOW':
            return sat_low
        else:
            return sat_valid

    proc_fixture.cardinal_directions = ['N'] * 15  # Rounding 359.9/22.5 is 16 -> IndexError!

    with patch('indi_allsky.processing.IndiAllSkyDbTleDataTable.query') as mock_query, \
         patch('ephem.readtle', side_effect=mock_readtle):
        mock_query.filter.return_value.order_by.return_value.limit.return_value = [entry_eclipsed, entry_low, entry_valid]
        lines = proc_fixture.get_satellite_tracking_text()

    assert any('SAT_VALID Error' in l for l in lines)


def test_stretch_no_split(proc_fixture):
    """Cover line 3963: self.image = stretched_image when split is False."""
    proc_fixture.post_init()
    proc_fixture.config['IMAGE_STRETCH'] = {'SPLIT': False}
    proc_fixture._stretch_o = MagicMock()
    proc_fixture.night_av[constants.NIGHT_NIGHT] = 1
    proc_fixture.night_av[constants.NIGHT_MOONMODE] = 0
    proc_fixture.image = np.zeros((32, 32, 3), dtype=np.uint8)
    i_ref = MagicMock()

    with patch.object(proc_fixture, 'getLatestImage', return_value=i_ref), \
         patch.object(proc_fixture, '_stretch', return_value=np.ones((32, 32, 3), dtype=np.uint8)):
        proc_fixture.stretch()
        assert np.array_equal(proc_fixture.image, np.ones((32, 32, 3), dtype=np.uint8))


def test_moon_overlay_disabled(proc_fixture):
    """Cover line 4147: moon_overlay returns early when disabled."""
    proc_fixture.post_init()
    proc_fixture.config['MOON_OVERLAY'] = {'ENABLE': False}
    proc_fixture.moon_overlay()


def test_keogram_strip_exceptions_unlink_eof(proc_fixture, tmp_path):
    """Cover lines 4274, 4277: unlinking files on EOFError."""
    proc_fixture.post_init()
    store_p = tmp_path / 'keogram.npy'
    meta_p = tmp_path / 'keogram_meta.json'
    store_p.write_bytes(b'corrupt')
    meta_p.write_bytes(b'corrupt')

    proc_fixture._keogram_store_p = store_p
    proc_fixture._keogram_store_metadata_p = meta_p
    proc_fixture.realtime_keogram_data = None
    proc_fixture.image = np.zeros((32, 32, 3), dtype=np.uint8)

    with patch.object(proc_fixture, 'realtimeKeogramDataLoad', side_effect=EOFError):
        proc_fixture.realtimeKeogramUpdate()
    assert not store_p.exists()
    assert not meta_p.exists()


def test_keogram_strip_exceptions_unlink_filenotfound(proc_fixture, tmp_path):
    """Cover lines 4282, 4285: unlinking files on FileNotFoundError."""
    proc_fixture.post_init()
    store_p = tmp_path / 'keogram2.npy'
    meta_p = tmp_path / 'keogram2_meta.json'
    store_p.write_bytes(b'corrupt')
    meta_p.write_bytes(b'corrupt')

    proc_fixture._keogram_store_p = store_p
    proc_fixture._keogram_store_metadata_p = meta_p
    proc_fixture.realtime_keogram_data = None
    proc_fixture.image = np.zeros((32, 32, 3), dtype=np.uint8)

    with patch.object(proc_fixture, 'realtimeKeogramDataLoad', side_effect=FileNotFoundError):
        proc_fixture.realtimeKeogramUpdate()
    assert not store_p.exists()
    assert not meta_p.exists()


def test_detect_bit_depth_14_and_12():
    """Cover lines 4887 and 4889: detecting 14-bit and 12-bit depths."""
    data_obj = ImageData.__new__(ImageData)

    # Max 5000 -> 14-bit (line 4887)
    mock_hdu14 = fits.HDUList([fits.PrimaryHDU(np.array([[5000]], dtype=np.uint16))])
    data_obj._hdulist = mock_hdu14
    data_obj.detectBitDepth()
    assert data_obj.detected_bit_depth == 14

    # Max 2000 -> 12-bit (line 4889)
    mock_hdu12 = fits.HDUList([fits.PrimaryHDU(np.array([[2000]], dtype=np.uint16))])
    data_obj._hdulist = mock_hdu12
    data_obj.detectBitDepth()
    assert data_obj.detected_bit_depth == 12
