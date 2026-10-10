import ctypes
from datetime import datetime
from multiprocessing import Array
from pathlib import Path
from unittest.mock import MagicMock

from astropy.io import fits
import cv2
import numpy as np
import pytest

from indi_allsky import constants
from indi_allsky.processing import ImageProcessor


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
def image_processor_fixture(base_config, tmp_path):
    config = dict(base_config)
    config['VARLIB_FOLDER'] = str(tmp_path)
    config['LOCATION_LATITUDE'] = -34.9285
    config['LOCATION_LONGITUDE'] = 138.6007
    config['LOCATION_ELEVATION'] = 50.0
    config['NIGHT_SUN_ALT_DEG'] = -6.0
    config['ORB_PROPERTIES'] = {
        'AZ_OFFSET': 0.0,
        'RETROGRADE': False,
        'SUN_COLOR': [255, 200, 0],
        'MOON_COLOR': [200, 200, 200],
    }

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


def test_image_processor_init_and_properties(image_processor_fixture):
    ip = image_processor_fixture

    # Test basic properties
    ip.libcamera_raw = True
    assert ip.libcamera_raw is True

    ip.max_bit_depth = 12
    assert ip.max_bit_depth == 12

    ip.text_color_rgb = [255, 128, 0]
    assert ip.text_color_rgb == [255, 128, 0]
    assert ip.text_color_bgr == [0, 128, 255]

    ip.text_color_bgr = [10, 20, 30]
    assert ip.text_color_bgr == [10, 20, 30]
    assert ip.text_color_rgb == [30, 20, 10]

    ip.image = np.full((100, 100, 3), 128, dtype=np.uint8)
    ip.text_xy = [10, 20]
    assert ip.text_xy == [10, 20]

    ip.text_anchor_pillow = 'mm'
    assert ip.text_anchor_pillow == 'mm'

    ip.text_size_pillow = 24
    assert ip.text_size_pillow == 24

    ip.text_font_height = 32
    assert ip.text_font_height == 32

    # Realtime keogram properties
    ip.realtime_keogram_data = np.zeros((10, 10, 3), dtype=np.uint8)
    assert ip.realtime_keogram_data is not None
    ip.realtime_keogram_timestamps = [1.0, 2.0]
    assert ip.realtime_keogram_timestamps == [1.0, 2.0]
    assert ip.astrometric_data == {}
    assert ip.camera_sqm_raw_mag is not None



def test_image_processor_add_jpeg(image_processor_fixture, dummy_camera, tmp_path):
    ip = image_processor_fixture
    img_file = tmp_path / "test_frame.jpg"
    img_arr = np.full((64, 64, 3), 120, dtype=np.uint8)
    cv2.imwrite(str(img_file), img_arr)

    i_ref = ip.add(
        filename=str(img_file),
        exposure=1.0,
        gain=100.0,
        binning=1,
        exp_date=datetime.now(),
        exp_elapsed=1.0,
        camera=dummy_camera,
    )

    assert i_ref is not None
    assert i_ref.kpindex == 3.5
    assert i_ref.ovation_max == 50
    assert i_ref.smoke_rating == constants.SMOKE_RATING_CLEAR

    ip.debayer()
    ip.stack()
    assert ip.image is not None
    assert ip.shape == (64, 64, 3)
    assert ip.getLatestImage() == i_ref


def test_image_processor_add_png(image_processor_fixture, dummy_camera, tmp_path):
    ip = image_processor_fixture
    img_file = tmp_path / "test_frame.png"
    img_arr = np.full((64, 64, 3), 150, dtype=np.uint8)
    cv2.imwrite(str(img_file), img_arr)

    i_ref = ip.add(
        filename=str(img_file),
        exposure=1.0,
        gain=100.0,
        binning=1,
        exp_date=datetime.now(),
        exp_elapsed=1.0,
        camera=dummy_camera,
    )

    assert i_ref is not None
    ip.debayer()
    ip.stack()
    assert ip.image is not None


def test_image_processor_add_fits(image_processor_fixture, dummy_camera, tmp_path):
    ip = image_processor_fixture
    fits_file = tmp_path / "test_frame.fits"
    data = np.full((64, 64), 1000, dtype=np.uint16)
    hdu = fits.PrimaryHDU(data)
    hdu.header['EXPTIME'] = 1.5
    hdu.header['GAIN'] = 100.0
    hdu.header['BITPIX'] = 16
    hdu.header['BAYERPAT'] = 'RGGB'
    hdu.writeto(str(fits_file))

    i_ref = ip.add(
        filename=str(fits_file),
        exposure=1.5,
        gain=100.0,
        binning=1,
        exp_date=datetime.now(),
        exp_elapsed=1.5,
        camera=dummy_camera,
    )

    assert i_ref is not None
    ip.debayer()
    ip.stack()
    assert ip.image is not None


def test_image_processor_convert_16bit_to_8bit(image_processor_fixture, dummy_camera, tmp_path):
    ip = image_processor_fixture
    fits_file = tmp_path / "test_16.fits"
    data = np.full((64, 64), 32000, dtype=np.uint16)
    hdu = fits.PrimaryHDU(data)
    hdu.header['EXPTIME'] = 1.0
    hdu.header['GAIN'] = 100.0
    hdu.header['BITPIX'] = 16
    hdu.writeto(str(fits_file))

    ip.add(
        filename=str(fits_file),
        exposure=1.0,
        gain=100.0,
        binning=1,
        exp_date=datetime.now(),
        exp_elapsed=1.0,
        camera=dummy_camera,
    )

    ip.debayer()
    ip.stack()
    ip.max_bit_depth = 16
    ip.convert_16bit_to_8bit()
    assert ip.image.dtype == np.uint8


def test_image_processor_color_correction_matrix(image_processor_fixture):
    ip = image_processor_fixture
    ip.image = np.full((32, 32, 3), 120, dtype=np.uint8)

    # 3x3 identity CCM matrix
    ccm = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    ip.apply_color_correction_matrix(ccm)
    assert ip.image.shape == (32, 32, 3)


def test_image_processor_geometric_transforms(image_processor_fixture, dummy_camera, tmp_path):
    ip = image_processor_fixture
    img_file = tmp_path / "geom.jpg"
    cv2.imwrite(str(img_file), np.full((64, 48, 3), 128, dtype=np.uint8))

    ip.add(
        filename=str(img_file),
        exposure=1.0,
        gain=100.0,
        binning=1,
        exp_date=datetime.now(),
        exp_elapsed=1.0,
        camera=dummy_camera,
    )
    ip.debayer()
    ip.stack()

    # Flip V and H
    ip.flip_v()
    assert ip.image.shape == (64, 48, 3)
    ip.flip_h()
    assert ip.image.shape == (64, 48, 3)

    # Rotate 90
    ip.config['IMAGE_ROTATE'] = 'ROTATE_90_CLOCKWISE'
    ip.rotate_90()
    assert ip.image.shape == (48, 64, 3)

    # Rotate angle
    ip.config['IMAGE_ROTATE_ANGLE'] = 45
    ip.config['IMAGE_ROTATE_KEEP_SIZE'] = False
    ip.rotate_angle()
    assert ip.image is not None

    # Crop ROI
    ip.config['IMAGE_CROP_ROI'] = [5, 5, 25, 25]
    ip.crop_image()
    assert ip.image.shape[0] == 20
    assert ip.image.shape[1] == 20


def test_image_processor_color_adjustments(image_processor_fixture, dummy_camera, tmp_path):
    ip = image_processor_fixture
    img_file = tmp_path / "adj.jpg"
    cv2.imwrite(str(img_file), np.full((64, 64, 3), 128, dtype=np.uint8))

    ip.add(
        filename=str(img_file),
        exposure=1.0,
        gain=100.0,
        binning=1,
        exp_date=datetime.now(),
        exp_elapsed=1.0,
        camera=dummy_camera,
    )
    ip.debayer()
    ip.stack()

    # Manual white balance
    ip.config['WBB_FACTOR'] = 1.2
    ip.config['WBG_FACTOR'] = 1.0
    ip.config['WBR_FACTOR'] = 0.8
    ip.white_balance_manual_bgr()
    assert ip.image is not None

    # Saturation adjust
    ip.config['SATURATION_FACTOR'] = 1.5
    ip.saturation_adjust()
    assert ip.image is not None

    # Gamma correction
    ip.config['GAMMA_CORRECTION'] = 1.8
    ip.apply_gamma_correction()
    assert ip.image is not None

    # Sharpen
    ip.config['SHARPEN_AMOUNT'] = 0.5
    ip.sharpen()
    assert ip.image is not None

    # Contrast CLAHE
    ip.config['CLAHE_CLIPLIMIT'] = 2.0
    ip.config['CLAHE_GRIDSIZE'] = 8
    ip.contrast_clahe()
    assert ip.image is not None

    # Colorize
    ip.colorize()
    assert len(ip.image.shape) == 3


def test_image_processor_adu_calculations(image_processor_fixture, dummy_camera, tmp_path):
    ip = image_processor_fixture
    img_file = tmp_path / "adu_frame.jpg"
    cv2.imwrite(str(img_file), np.full((64, 64, 3), 150, dtype=np.uint8))

    ip.add(
        filename=str(img_file),
        exposure=1.0,
        gain=100.0,
        binning=1,
        exp_date=datetime.now(),
        exp_elapsed=1.0,
        camera=dummy_camera,
    )
    ip.debayer()
    ip.stack()

    adu = ip.calculate_8bit_adu()
    assert 0 <= adu <= 255



def test_image_processor_sqm_calculations(image_processor_fixture, dummy_camera, tmp_path):
    ip = image_processor_fixture
    img_file = tmp_path / "sqm_frame.jpg"
    cv2.imwrite(str(img_file), np.full((64, 64, 3), 50, dtype=np.uint8))

    i_ref = ip.add(
        filename=str(img_file),
        exposure=5.0,
        gain=100.0,
        binning=1,
        exp_date=datetime.now(),
        exp_elapsed=5.0,
        camera=dummy_camera,
    )
    ip.debayer()
    ip.stack()

    ip.calculateJankySqm()
    assert i_ref.sqm_value is not None


def test_image_processor_astro_darkness(image_processor_fixture):
    ip = image_processor_fixture

    # Test night
    ip.night_av[0] = 1
    ip.astro_av[constants.ASTRO_SUN_ALT] = -20.0
    ip._check_astro_darkness()
    assert ip.astro_darkness is not None

    # Test day
    ip.night_av[0] = 0
    ip.astro_av[constants.ASTRO_SUN_ALT] = 15.0
    ip._check_astro_darkness()
    assert ip.astro_darkness is not None


def test_image_processor_text_drawing(image_processor_fixture):
    ip = image_processor_fixture
    data = np.zeros((100, 100, 3), dtype=np.uint8)

    # OpenCV text drawing
    ip.drawText_opencv(data, "Test Text", (10, 50), [255, 255, 255])
    assert data is not None
    assert data.shape == (100, 100, 3)


def test_image_processor_detections(image_processor_fixture, dummy_camera, tmp_path):
    ip = image_processor_fixture
    img_file = tmp_path / "detect.jpg"
    cv2.imwrite(str(img_file), np.full((64, 64, 3), 128, dtype=np.uint8))

    ip.add(
        filename=str(img_file),
        exposure=1.0,
        gain=100.0,
        binning=1,
        exp_date=datetime.now(),
        exp_elapsed=1.0,
        camera=dummy_camera,
    )
    ip.debayer()
    ip.stack()

    ip.detectStars()
    ip.detectLines()
    ip.drawDetections()
    assert ip.image is not None


def test_image_processor_astrometrics(image_processor_fixture):
    ip = image_processor_fixture
    ip.position_av[constants.POSITION_LATITUDE] = -34.9285
    ip.position_av[constants.POSITION_LONGITUDE] = 138.6007
    ip.position_av[constants.POSITION_ELEVATION] = 50.0

    ip.update_astrometric_data(datetime.now())
    assert 'sun_alt' in ip.astrometric_data
    assert 'moon_alt' in ip.astrometric_data
    assert 'moon_phase' in ip.astrometric_data
    assert 'venus_alt' in ip.astrometric_data


def test_image_processor_scaling_and_splitscreen(image_processor_fixture, dummy_camera, tmp_path):
    ip = image_processor_fixture
    img_file = tmp_path / "scale.jpg"
    cv2.imwrite(str(img_file), np.full((64, 64, 3), 128, dtype=np.uint8))

    ip.add(
        filename=str(img_file),
        exposure=1.0,
        gain=100.0,
        binning=1,
        exp_date=datetime.now(),
        exp_elapsed=1.0,
        camera=dummy_camera,
    )
    ip.debayer()
    ip.stack()

    # Scaling
    ip.config['IMAGE_SCALE'] = 50
    ip.scale_image()
    assert ip.image.shape == (32, 32, 3)

    # Splitscreen
    d1 = np.full((32, 32, 3), 100, dtype=np.uint8)
    d2 = np.full((32, 32, 3), 200, dtype=np.uint8)
    res = ip.splitscreen(d1, d2)
    assert res.shape == (32, 32, 3)


def test_image_processor_more_color_transforms(image_processor_fixture, dummy_camera, tmp_path):
    ip = image_processor_fixture
    img_file = tmp_path / "color_xf.jpg"
    cv2.imwrite(str(img_file), np.full((64, 64, 3), 128, dtype=np.uint8))

    ip.add(
        filename=str(img_file),
        exposure=1.0,
        gain=100.0,
        binning=1,
        exp_date=datetime.now(),
        exp_elapsed=1.0,
        camera=dummy_camera,
    )
    ip.debayer()
    ip.stack()

    # Auto WB
    ip.config['AUTO_WB'] = True
    ip.white_balance_auto_bgr()
    assert ip.image is not None

    # MTF WB
    ip.config['WBB_MTF_MIDTONES'] = 0.6
    ip.white_balance_mtf()
    assert ip.image is not None

    # CLAHE 16-bit
    ip.contrast_clahe_16bit()
    assert ip.image is not None


def test_image_processor_circle_holes(image_processor_fixture, dummy_camera, tmp_path):
    ip = image_processor_fixture
    img_file = tmp_path / "holes.jpg"
    cv2.imwrite(str(img_file), np.full((64, 64, 3), 128, dtype=np.uint8))

    i_ref = ip.add(
        filename=str(img_file),
        exposure=1.0,
        gain=100.0,
        binning=1,
        exp_date=datetime.now(),
        exp_elapsed=1.0,
        camera=dummy_camera,
    )
    ip.debayer()
    ip.stack()

    i_ref.hole_mask = np.zeros((64, 64), dtype=bool)
    i_ref.hole_mask[10, 10] = True
    ip.circleHoles(i_ref)
    assert ip.image is not None

