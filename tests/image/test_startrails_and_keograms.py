import pytest
import numpy as np
import cv2
from datetime import datetime, timezone, timedelta
from pathlib import Path

from indi_allsky.starTrails import StarTrailGenerator
from indi_allsky.keogram import KeogramGenerator
from indi_allsky.detectLines import IndiAllskyDetectLines


# ==============================================================================
# Keogram Generator Tests
# ==============================================================================

def test_keogram_generator_basic(tmp_path):
    config = {
        'KEOGRAM_ANGLE': 0,
        'LENS_OFFSET_X': 0,
        'LENS_OFFSET_Y': 0,
        'IMAGE_BORDER': {'TOP': 0, 'LEFT': 0, 'RIGHT': 0, 'BOTTOM': 0},
    }
    keogram_gen = KeogramGenerator(config=config)
    keogram_gen.label = False

    # Process 3 sequential frames (100x100 BGR)
    for i in range(3):
        frame = np.full((100, 100, 3), 50 + i * 20, dtype=np.uint8)
        time_exp = datetime(2026, 9, 1, 12, i, 0, tzinfo=timezone.utc)
        keogram_gen.processImage(frame, time_exp)

    assert keogram_gen.process_count == 3
    assert keogram_gen.keogram_data is not None


def test_keogram_rotation_angles():
    config = {
        'KEOGRAM_ANGLE': 90,
        'LENS_OFFSET_X': 0,
        'LENS_OFFSET_Y': 0,
        'IMAGE_BORDER': {},
    }
    keogram_gen = KeogramGenerator(config=config)
    keogram_gen.label = False

    frame = np.zeros((80, 80, 3), dtype=np.uint8)
    time_exp = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    keogram_gen.processImage(frame, time_exp)

    assert keogram_gen.process_count == 1


# ==============================================================================
# Star Trails Generator Tests
# ==============================================================================

def test_startrails_generator_process(tmp_path):
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir(exist_ok=True)

    config = {
        'IMAGE_FOLDER': str(tmp_path),
        'IMAGE_FILE_TYPE': 'jpg',
        'IMAGE_FILE_COMPRESSION': {'jpg': 90},
        'STARTRAILS_TIMELAPSE': False,
        'STARTRAILS_PIXEL_THOLD': 1.0,
        'STARTRAILS_MASK_THOLD': 200,
        'STARTRAILS_MAX_ADU': 250,
        'STARTRAILS_SUN_ALT_THOLD': -6.0,
        'STARTRAILS_MIN_STARS': 0,
        'LATITUDE': -34.9,
        'LONGITUDE': 138.6,
    }

    mask = {1: None}
    trail_gen = StarTrailGenerator(config=config, mask=mask)
    trail_gen.max_adu = 250
    trail_gen.sun_alt_threshold = 90.0  # Allow test execution regardless of real-world local time

    # Frame 1: Base background
    f1 = np.full((64, 64, 3), 10, dtype=np.uint8)
    # Frame 2: Bright star pixel at (20, 20)
    f2 = np.full((64, 64, 3), 10, dtype=np.uint8)
    f2[20, 20] = [200, 200, 200]
    # Frame 3: Bright star pixel at (21, 21)
    f3 = np.full((64, 64, 3), 10, dtype=np.uint8)
    f3[21, 21] = [220, 220, 220]

    night_time = datetime(2026, 9, 1, 15, 0, 0, tzinfo=timezone.utc)  # Night time for solar alt
    dummy_path = tmp_path / "test.jpg"
    dummy_path.touch()

    trail_gen.processImage(dummy_path, f1, binning=1, adu=20)
    trail_gen.processImage(dummy_path, f2, binning=1, adu=20)
    trail_gen.processImage(dummy_path, f3, binning=1, adu=20)

    assert trail_gen.trail_count >= 2
    assert trail_gen.trail_image is not None
    assert trail_gen.trail_image.shape == (64, 64, 3)
    # The max pixel composite should contain the bright stars
    assert np.all(trail_gen.trail_image[20, 20] >= 200)
    assert np.all(trail_gen.trail_image[21, 21] >= 220)


class DummyCamera:
    def __init__(self, name="TestCam", lens_name="TestLens", owner="TestOwner", lat=-34.9285, lon=138.6007, focal_len=2.5, focal_ratio=1.4):
        self.name = name
        self.lensName = lens_name
        self.owner = owner
        self.latitude = lat
        self.longitude = lon
        self.lensFocalLength = focal_len
        self.lensFocalRatio = focal_ratio


from indi_allsky.exceptions import KeogramMismatchException


def test_keogram_properties_and_methods(tmp_path):
    config = {
        'KEOGRAM_ANGLE': 0,
        'LENS_OFFSET_X': 2,
        'LENS_OFFSET_Y': -2,
        'IMAGE_BORDER': {'TOP': 4, 'LEFT': 4, 'RIGHT': 2, 'BOTTOM': 2},
    }
    keogram_gen = KeogramGenerator(config=config, skip_frames=2)
    assert keogram_gen.skip_frames == 2

    keogram_gen.angle = 45.0
    assert keogram_gen.angle == 45.0

    keogram_gen.v_scale_factor = 90
    assert keogram_gen.v_scale_factor == 90

    keogram_gen.h_scale_factor = 90
    assert keogram_gen.h_scale_factor == 90

    keogram_gen.x_offset = 10
    assert keogram_gen.x_offset == 10

    keogram_gen.y_offset = -10
    assert keogram_gen.y_offset == -10

    keogram_gen.crop_top = 5
    assert keogram_gen.crop_top == 5

    keogram_gen.crop_bottom = 5
    assert keogram_gen.crop_bottom == 5

    keogram_gen.timestamps = [100.0, 200.0]
    assert keogram_gen.timestamps == [100.0, 200.0]

    keogram_gen.label = True
    assert keogram_gen.label is True

    fake_final = np.zeros((30, 40, 3), dtype=np.uint8)
    keogram_gen.keogram_final = fake_final
    assert keogram_gen.shape == (30, 40, 3)

    # decdeg2dms
    deg, m, s = keogram_gen.decdeg2dms(-34.9285)
    assert deg == -34
    deg2, m2, s2 = keogram_gen.decdeg2dms(138.6007)
    assert deg2 == 138

    # Process frames with skip_frames = 2
    f = np.zeros((50, 50, 3), dtype=np.uint8)
    keogram_gen.processImage(f, 1000.0)
    keogram_gen.processImage(f, 1001.0)
    # First 2 were skipped
    assert len(keogram_gen.timestamps) == 2  # initially had 2 items
    keogram_gen.processImage(f, 1002.0)
    assert len(keogram_gen.timestamps) == 3

    # Dimension mismatch
    f_bad = np.zeros((40, 40, 3), dtype=np.uint8)
    with pytest.raises(KeogramMismatchException):
        keogram_gen.processImage(f_bad, 1003.0)

    # Trim edges with angle < switch_angle and angle >= switch_angle
    keogram_gen.config['ORB_PROPERTIES'] = {'RADIUS': 2}
    keogram_gen.original_width = 100
    keogram_gen.original_height = 80
    keogram_gen.rotated_width = 110
    keogram_gen.rotated_height = 90
    keogram_gen.angle = 15.0
    kg_dummy = np.zeros((90, 20, 3), dtype=np.uint8)
    trimmed1 = keogram_gen.trimEdges(kg_dummy)
    assert trimmed1 is not None

    keogram_gen.angle = 75.0
    trimmed2 = keogram_gen.trimEdges(kg_dummy)
    assert trimmed2 is not None

    # Angle % 180 > 90 (covers line 420)
    keogram_gen.angle = 135.0
    trimmed3 = keogram_gen.trimEdges(kg_dummy)
    assert trimmed3 is not None


def test_keogram_finalize_and_labels(tmp_path):
    font_file = "hack/Hack-Regular.ttf"
    config = {
        'KEOGRAM_ANGLE': 0,
        'LENS_OFFSET_X': 0,
        'LENS_OFFSET_Y': 0,
        'IMAGE_BORDER': {},
        'IMAGE_FILE_TYPE': 'jpg',
        'IMAGE_FILE_COMPRESSION': {'jpg': 90, 'png': 6},
        'IMAGE_LABEL_SYSTEM': 'pillow',
        'TEXT_PROPERTIES': {
            'FONT_FACE': 'FONT_HERSHEY_SIMPLEX',
            'FONT_AA': 'LINE_AA',
            'FONT_SCALE': 0.8,
            'FONT_THICKNESS': 1,
            'FONT_COLOR': [255, 255, 255],
            'FONT_OUTLINE': True,
            'PIL_FONT_FILE': font_file,
            'PIL_FONT_SIZE': 14,
        },
        'ORB_PROPERTIES': {'RADIUS': 2},
        'IMAGE_EXIF_PRIVACY': False,
    }

    gen = KeogramGenerator(config)
    gen.label = True
    gen.crop_top = 2
    gen.crop_bottom = 2
    gen.h_scale_factor = 100
    gen.v_scale_factor = 100

    # Build keogram with timestamps that transition across hours (e.g. 12:00, 13:00, 14:00)
    base_dt = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(5):
        frame = np.full((60, 60, 3), 30 + i * 10, dtype=np.uint8)
        ts = (base_dt + timedelta(hours=i)).timestamp()
        gen.processImage(frame, ts)

    cam = DummyCamera(lat=-34.9, lon=-138.6, owner="SkyOwner")

    # 1. Finalize with pillow label and jpg output
    out_jpg = tmp_path / "keogram.jpg"
    gen.finalize(str(out_jpg), cam)
    assert out_jpg.exists()

    # 2. Finalize with opencv label and png output, outline=True, crop_top=0, crop_bottom=0
    gen.config['IMAGE_LABEL_SYSTEM'] = 'opencv'
    gen.config['IMAGE_FILE_TYPE'] = 'png'
    gen.config['TEXT_PROPERTIES']['FONT_OUTLINE'] = True
    gen.crop_top = 0
    gen.crop_bottom = 0
    cam_pos = DummyCamera(lat=34.9, lon=138.6, owner=None)
    out_png = tmp_path / "keogram.png"
    gen.finalize(str(out_png), cam_pos)
    assert out_png.exists()

    # 3. Pillow custom font, privacy=True, webp output
    gen.config['IMAGE_LABEL_SYSTEM'] = 'pillow'
    gen.config['IMAGE_FILE_TYPE'] = 'webp'
    gen.config['IMAGE_EXIF_PRIVACY'] = True
    gen.config['TEXT_PROPERTIES']['PIL_FONT_FILE'] = 'custom'
    gen.config['TEXT_PROPERTIES']['PIL_FONT_CUSTOM'] = str(gen.font_path.joinpath(font_file))
    gen.config['TEXT_PROPERTIES']['FONT_OUTLINE'] = False
    out_webp = tmp_path / "keogram.webp"
    gen.finalize(str(out_webp), cam)
    assert out_webp.exists()

    # 4. Tif output with label=False
    gen.config['IMAGE_FILE_TYPE'] = 'tif'
    gen.label = False
    out_tif = tmp_path / "keogram.tif"
    gen.finalize(str(out_tif), cam)
    assert out_tif.exists()

    # 5. Unsupported type
    gen.config['IMAGE_FILE_TYPE'] = 'bmp'
    with pytest.raises(Exception, match='Unknown file type'):
        gen.finalize(str(tmp_path / "keogram.bmp"), cam)


def test_startrails_properties_and_mask():
    config = {
        'IMAGE_FOLDER': '/tmp',
        'IMAGE_FILE_TYPE': 'jpg',
        'IMAGE_FILE_COMPRESSION': {'jpg': 90},
        'STARTRAILS_TIMELAPSE': False,
        'STARTRAILS_PIXEL_THOLD': 1.0,
        'STARTRAILS_MASK_THOLD': 200,
        'STARTRAILS_MAX_ADU': 250,
        'STARTRAILS_SUN_ALT_THOLD': -6.0,
        'STARTRAILS_MIN_STARS': 0,
        'LATITUDE': -34.9,
        'LONGITUDE': 138.6,
        'SQM_ROI': [10, 10, 50, 50],
        'FISH2PANO': {},
    }
    mask = {1: None}
    stg = StarTrailGenerator(config, mask=mask)

    stg.max_adu = 220
    assert stg.max_adu == 220

    stg.mask_threshold = 190
    assert stg.mask_threshold == 190

    stg.pixel_cutoff_threshold = 2.0
    assert stg.pixel_cutoff_threshold == 2.0

    stg.min_stars = 10
    assert stg.min_stars == 10

    stg.latitude = 40.0
    assert stg.latitude == 40.0

    stg.longitude = -74.0
    assert stg.longitude == -74.0

    stg.sun_alt_threshold = -12.0
    assert stg.sun_alt_threshold == -12.0

    stg.moon_alt_threshold = 5.0
    assert stg.moon_alt_threshold == 5.0

    stg.moon_phase_threshold = 40.0
    assert stg.moon_phase_threshold == 40.0

    stg.moonmode_alt = 8.0
    assert stg.moonmode_alt == 8.0

    stg.moonmode_phase = 50.0
    assert stg.moonmode_phase == 50.0

    # Read-only properties
    stg.trail_count = 99
    assert stg.trail_count == 0
    stg.timelapse_frame_count = 99
    assert stg.timelapse_frame_count == 0
    stg.timelapse_frame_list = ['bad']
    assert stg.timelapse_frame_list == []
    stg.shape = (10, 10)

    # _generateStarMask with SQM_ROI and fallback
    test_img = np.zeros((80, 80), dtype=np.uint8)
    stg._generateStarMask(test_img, binning=1)
    assert stg._star_mask_dict[1] is not None
    assert stg._star_mask_dict[1][20, 20] == 255

    stg.config['SQM_ROI'] = []
    stg.config['SQM_FOV_DIV'] = 4
    stg._generateStarMask(test_img, binning=1)
    assert stg._star_mask_dict[1] is not None

    # decdeg2dms
    deg, m, s = stg.decdeg2dms(-34.9285)
    assert deg == -34
    deg2, m2, s2 = stg.decdeg2dms(138.6007)
    assert deg2 == 138


def test_startrails_exclusions_and_branches(tmp_path):
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir(exist_ok=True)

    config = {
        'IMAGE_FOLDER': str(tmp_path),
        'IMAGE_FILE_TYPE': 'jpg',
        'IMAGE_FILE_COMPRESSION': {'jpg': 90},
        'STARTRAILS_TIMELAPSE': False,
        'STARTRAILS_PIXEL_THOLD': 0.1,  # Low threshold to trigger pixel cutoff
        'STARTRAILS_MASK_THOLD': 50,
        'STARTRAILS_MAX_ADU': 100,
        'STARTRAILS_SUN_ALT_THOLD': -10.0,
        'STARTRAILS_MIN_STARS': 2,
        'LATITUDE': -34.9,
        'LONGITUDE': 138.6,
        'STARTRAILS': {
            'IMAGE_CIRCLE_MASK_ENABLE': True,
            'IMAGE_CIRCLE_MASK_OPACITY': 100,
            'IMAGE_CIRCLE_MASK_DIAMETER': 80,
            'IMAGE_CIRCLE_MASK_BLUR': 5,
        },
        'LENS_OFFSET_X': 0,
        'LENS_OFFSET_Y': 0,
    }

    dummy_file = tmp_path / "frame.jpg"
    dummy_file.touch()

    # Set mtime on dummy_file to daytime (sun alt > sun_alt_threshold)
    # Noon UTC at longitude 0 is solar noon
    noon_ts = datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc).timestamp()
    import os
    os.utime(dummy_file, (noon_ts, noon_ts))

    stg = StarTrailGenerator(config, mask={1: None}, skip_frames=1)
    stg.latitude = 0.0
    stg.longitude = 0.0
    stg.sun_alt_threshold = -10.0  # Sun is high at noon

    img = np.full((100, 100, 3), 40, dtype=np.uint8)

    # 1. First image skipped due to skip_frames=1
    stg.processImage(dummy_file, img, binning=1)
    assert stg.process_count == 1
    assert stg.trail_image is None

    # 2. Second image excluded due to sun alt > threshold
    stg.processImage(dummy_file, img, binning=1)
    assert stg.excluded_images['sun_alt'] == 1

    # Now change mtime to midnight (sun alt < threshold)
    midnight_ts = datetime(2026, 6, 21, 0, 0, 0, tzinfo=timezone.utc).timestamp()
    os.utime(dummy_file, (midnight_ts, midnight_ts))
    stg.sun_alt_threshold = 90.0  # Disable sun cutoff

    # 3. Test moonmode exclusion (moon_alt > moonmode_alt and moon_phase > moonmode_phase)
    stg.moonmode_alt = -90.0
    stg.moonmode_phase = -1.0
    stg.processImage(dummy_file, img, binning=1)
    assert stg.excluded_images['moon_mode'] == 1

    # 4. Test moon alt exclusion
    stg.moonmode_alt = 90.0
    stg.moon_alt_threshold = -90.0
    stg.moon_phase_threshold = -1.0
    stg.processImage(dummy_file, img, binning=1)
    assert stg.excluded_images['moon_alt'] == 1

    # Disable moon exclusions
    stg.moon_alt_threshold = 90.0
    stg.moonmode_alt = 90.0

    # 5. Excluded due to max_adu
    stg.max_adu = 20
    stg.processImage(dummy_file, img, binning=1, adu=50)
    assert stg.excluded_images['adu'] == 1
    stg.max_adu = 250

    # 6. Excluded due to pixel cutoff threshold
    stg.mask_threshold = 50
    stg.pixel_cutoff_threshold = 0.1
    stg.pixels_cutoff = 10
    bright_img = np.full((100, 100, 3), 255, dtype=np.uint8)
    stg.processImage(dummy_file, bright_img, binning=1, adu=30)
    assert stg.excluded_images['pixels'] == 1

    # 7. Excluded due to min_stars
    stg.min_stars = 50
    stg.processImage(dummy_file, img, binning=1, adu=30, star_count=10)
    assert stg.excluded_images['stars'] == 1
    stg.min_stars = 0

    # 8. Dimension mismatch
    bad_dim_img = np.full((60, 60, 3), 30, dtype=np.uint8)
    stg.processImage(dummy_file, bad_dim_img, binning=1, adu=30)

    # 9. Grayscale 2D image processing (with circle mask disabled)
    gray_img = np.full((100, 100), 30, dtype=np.uint8)
    config_gray = config.copy()
    config_gray['STARTRAILS'] = {'IMAGE_CIRCLE_MASK_ENABLE': False}
    stg_gray = StarTrailGenerator(config_gray, mask={1: None})
    stg_gray.sun_alt_threshold = 90.0
    stg_gray.min_stars = 0
    stg_gray.max_adu = 250
    stg_gray.processImage(dummy_file, gray_img, binning=1, adu=30)
    assert stg_gray.trail_image is not None
    assert len(stg_gray.trail_image.shape) == 2

    # 10. Blur = 0 for circle mask
    config['STARTRAILS']['IMAGE_CIRCLE_MASK_BLUR'] = 0
    stg_noblur = StarTrailGenerator(config, mask={1: None})
    mask_noblur = stg_noblur._generate_image_circle_mask(img)
    assert mask_noblur is not None

    # 11. Empty IMAGE_FOLDER fallback (covers line 91)
    config_empty_img = config.copy()
    config_empty_img['IMAGE_FOLDER'] = ''
    stg_empty = StarTrailGenerator(config_empty_img, mask={1: None})
    assert stg_empty.image_dir.exists()

    # 12. min_stars with star_count=None (covers line 331)
    stg.min_stars = 100
    stg.processImage(dummy_file, img, binning=1, adu=30, star_count=None)
    assert stg.excluded_images['stars'] >= 1

    # 13. Circle mask enabled on 3D image (covers lines 344-348, 590, and shape property 222)
    config_mask_3d = config.copy()
    config_mask_3d['STARTRAILS'] = {'IMAGE_CIRCLE_MASK_ENABLE': True, 'IMAGE_CIRCLE_MASK_BLUR': 5}
    stg_mask_3d = StarTrailGenerator(config_mask_3d, mask={1: None})
    stg_mask_3d.sun_alt_threshold = 90.0
    stg_mask_3d.processImage(dummy_file, img, binning=1, adu=30)
    assert stg_mask_3d.trail_image is not None
    assert stg_mask_3d.shape == img.shape

    # 14. Scratch base dir creation (covers line 97)
    scratch_sub = tmp_path / "new_scratch_test"
    config_no_scratch = config.copy()
    config_no_scratch['IMAGE_FOLDER'] = str(scratch_sub)
    stg_scratch = StarTrailGenerator(config_no_scratch, mask={1: None})
    assert scratch_sub.joinpath('scratch').exists()



def test_startrails_timelapse_and_finalize(tmp_path):
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir(exist_ok=True)

    config = {
        'IMAGE_FOLDER': str(tmp_path),
        'IMAGE_FILE_TYPE': 'jpg',
        'IMAGE_FILE_COMPRESSION': {'jpg': 90, 'png': 6},
        'STARTRAILS_TIMELAPSE': True,
        'STARTRAILS_PIXEL_THOLD': 100.0,
        'STARTRAILS_MASK_THOLD': 250,
        'STARTRAILS_MAX_ADU': 250,
        'STARTRAILS_SUN_ALT_THOLD': 90.0,
        'STARTRAILS_MIN_STARS': 0,
        'LATITUDE': -34.9,
        'LONGITUDE': 138.6,
        'IMAGE_EXIF_PRIVACY': False,
    }

    dummy_file = tmp_path / "frame.jpg"
    dummy_file.touch()

    stg = StarTrailGenerator(config, mask={1: None})
    stg.sun_alt_threshold = 90.0

    cam = DummyCamera(lat=-34.9, lon=-138.6, owner="OwnerName", focal_len=2.8, focal_ratio=1.4)

    # 1. Finalize with trail_count == 0 -> uses placeholder_image
    stg_zero = StarTrailGenerator(config, mask={1: None})
    f_placeholder = np.full((60, 60, 3), 15, dtype=np.uint8)
    stg_zero.placeholder_image = f_placeholder
    out_zero = tmp_path / "trail_zero.jpg"
    stg_zero.finalize(str(out_zero), cam)
    assert out_zero.exists()

    # 2. Timelapse frames for jpg, png, webp, tif
    frame = np.full((60, 60, 3), 50, dtype=np.uint8)

    # JPG timelapse frame
    stg.processImage(dummy_file, frame, binning=1, adu=30)
    assert stg.timelapse_frame_count == 1

    # PNG timelapse frame & finalize
    stg.config['IMAGE_FILE_TYPE'] = 'png'
    stg.processImage(dummy_file, frame, binning=1, adu=30)
    out_png = tmp_path / "trail.png"
    stg.finalize(str(out_png), cam)
    assert out_png.exists()

    # Webp timelapse frame & finalize with positive coords (lat > 0, lon > 0, privacy=False)
    stg.config['IMAGE_FILE_TYPE'] = 'webp'
    stg.config['IMAGE_EXIF_PRIVACY'] = False
    cam_pos = DummyCamera(lat=34.9, lon=138.6, owner="PosOwner")
    stg.processImage(dummy_file, frame, binning=1, adu=30)
    out_webp = tmp_path / "trail.webp"
    stg.finalize(str(out_webp), cam_pos)
    assert out_webp.exists()

    # Tif timelapse frame & finalize with privacy=True
    stg.config['IMAGE_FILE_TYPE'] = 'tif'
    stg.config['IMAGE_EXIF_PRIVACY'] = True
    stg.processImage(dummy_file, frame, binning=1, adu=30)
    out_tif = tmp_path / "trail.tif"
    stg.finalize(str(out_tif), cam)
    assert out_tif.exists()

    # Unsupported format in timelapse frame
    stg.config['IMAGE_FILE_TYPE'] = 'bmp'
    with pytest.raises(Exception, match='Unknown file type'):
        stg.processImage(dummy_file, frame, binning=1, adu=30)

    # Unsupported format in finalize
    with pytest.raises(Exception, match='Unknown file type'):
        stg.finalize(str(tmp_path / "trail.bmp"), cam)

