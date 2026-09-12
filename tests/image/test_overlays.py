import numpy as np
import cv2
import pytest

from indi_allsky.overlay.cardinalDirsLabel import IndiAllskyCardinalDirsLabel
from indi_allsky.overlay.moonOverlay import IndiAllSkyMoonOverlay


def test_cardinal_dirs_label_opencv():
    config = {
        'IMAGE_FLIP_V': False,
        'IMAGE_FLIP_H': False,
        'IMAGE_LABEL_SYSTEM': 'opencv',
        'LENS_AZIMUTH': 0,
        'CARDINAL_DIRS': {
            'CHAR_NORTH': 'N',
            'CHAR_EAST': 'E',
            'CHAR_WEST': 'W',
            'CHAR_SOUTH': 'S',
            'OFFSET_TOP': 10,
            'OFFSET_BOTTOM': 10,
            'OFFSET_LEFT': 10,
            'OFFSET_RIGHT': 10,
            'OUTLINE_CIRCLE': True,
            'FONT_COLOR': [255, 255, 255],
        },
        'TEXT_PROPERTIES': {
            'FONT_FACE': 'FONT_HERSHEY_SIMPLEX',
            'FONT_AA': 'LINE_AA',
            'FONT_SCALE': 1.0,
            'FONT_THICKNESS': 1,
            'FONT_OUTLINE': True,
        },
    }

    labeler = IndiAllskyCardinalDirsLabel(config)
    img = np.zeros((300, 300, 3), dtype=np.uint8)

    res = labeler.main(img.copy())
    assert res.shape == (300, 300, 3)
    assert not np.array_equal(res, img)


def test_moon_overlay_apply():
    config = {
        'MOON_OVERLAY': {
            'SCALE': 0.5,
            'X': 50,
            'Y': 50,
            'FLIP_V': False,
            'FLIP_H': False,
            'DARK_SIDE_SCALE': 0.3,
        }
    }

    moon_overlay = IndiAllSkyMoonOverlay(config)
    # Mock moon_orig to a synthetic 100x100 4-channel image
    fake_moon = np.zeros((100, 100, 4), dtype=np.uint8)
    cv2.circle(fake_moon, (50, 50), 40, (255, 255, 255, 255), -1)
    moon_overlay.moon_orig = fake_moon

    target_img = np.zeros((300, 300, 3), dtype=np.uint8)
    # Apply waxing crescent (cycle 15%, illumination phase 20%) - modifies target_img in place
    moon_overlay.apply(target_img, moon_cycle_percent=15.0, moon_phase=20.0)
    assert target_img.shape == (300, 300, 3)
    assert np.any(target_img > 0)

    # Apply full moon (cycle 50%, illumination phase 100%)
    target_img_full = np.zeros((300, 300, 3), dtype=np.uint8)
    moon_overlay.apply(target_img_full, moon_cycle_percent=50.0, moon_phase=100.0)
    assert target_img_full.shape == (300, 300, 3)
    assert np.any(target_img_full > 0)
    assert target_img_full.sum() > target_img.sum()

    # Test moon_cycle_percent <= 75 and moon_cycle_percent > 75
    target_img_waning = np.zeros((300, 300, 3), dtype=np.uint8)
    moon_overlay.apply(target_img_waning, moon_cycle_percent=65.0, moon_phase=70.0)
    assert np.any(target_img_waning > 0)

    target_img_crescent = np.zeros((300, 300, 3), dtype=np.uint8)
    moon_overlay.apply(target_img_crescent, moon_cycle_percent=85.0, moon_phase=30.0)
    assert np.any(target_img_crescent > 0)

    # Test flips and negative coordinates
    config_flipped = {
        'MOON_OVERLAY': {
            'SCALE': 0.5,
            'X': -10,
            'Y': -10,
            'FLIP_V': True,
            'FLIP_H': True,
            'DARK_SIDE_SCALE': 0.3,
        }
    }
    moon_overlay_flipped = IndiAllSkyMoonOverlay(config_flipped)
    moon_overlay_flipped.moon_orig = fake_moon.copy()
    target_img_flipped = np.zeros((300, 300, 3), dtype=np.uint8)
    moon_overlay_flipped.apply(target_img_flipped, moon_cycle_percent=30.0, moon_phase=40.0)
    assert np.any(target_img_flipped > 0)

    # Test boundary check (coordinates exceeding boundary)
    config_boundary = {
        'MOON_OVERLAY': {
            'SCALE': 0.5,
            'X': 500,
            'Y': 500,
            'FLIP_V': False,
            'FLIP_H': False,
            'DARK_SIDE_SCALE': 0.3,
        }
    }
    moon_overlay_boundary = IndiAllSkyMoonOverlay(config_boundary)
    moon_overlay_boundary.moon_orig = fake_moon.copy()
    target_img_boundary = np.zeros((300, 300, 3), dtype=np.uint8)
    moon_overlay_boundary.apply(target_img_boundary, moon_cycle_percent=30.0, moon_phase=40.0)
    assert np.any(target_img_boundary > 0)

    # Test lazy image loading via cv2.imread when moon_orig is None
    moon_overlay_load = IndiAllSkyMoonOverlay(config)
    with patch('cv2.imread', return_value=fake_moon.copy()):
        target_img_lazy = np.zeros((300, 300, 3), dtype=np.uint8)
        moon_overlay_load.apply(target_img_lazy, moon_cycle_percent=20.0, moon_phase=20.0)
        assert moon_overlay_load.moon_orig is not None



from indi_allsky.overlay.imageOverlay import IndiAllSkyImageOverlay
from unittest.mock import MagicMock, patch
import pycurl


def test_image_overlay_apply_bounds_and_channels():
    config = {
        'IMAGE_OVERLAY': {
            'LOAD_INTERVAL': 99999,
            'A_WIDTH': 50,
            'A_HEIGHT': 50,
            'A_X': -30,
            'A_Y': -30,
        },
        'FILETRANSFER': {},
    }
    overlay = IndiAllSkyImageOverlay(config)
    img = np.zeros((200, 200, 3), dtype=np.uint8)

    # 1. No data loaded -> returns None safely
    overlay.apply(img)
    assert np.all(img == 0)

    # 2. 4-channel overlay with negative and clamped coords
    overlay_rgba = np.full((50, 50, 4), 200, dtype=np.uint8)
    overlay.images_dict['a']['data'] = overlay_rgba
    overlay.images_dict['a']['x'] = -30
    overlay.images_dict['a']['y'] = -30
    overlay.apply(img)
    assert np.any(img > 0)

    # Coords exceeding boundary
    overlay.images_dict['a']['x'] = 190
    overlay.images_dict['a']['y'] = 190
    overlay.apply(img)

    # 3. 3-channel overlay
    img3 = np.zeros((200, 200, 3), dtype=np.uint8)
    overlay_bgr = np.full((50, 50, 3), 150, dtype=np.uint8)
    overlay.images_dict['a']['data'] = overlay_bgr
    overlay.images_dict['a']['x'] = 20
    overlay.images_dict['a']['y'] = 20
    overlay.apply(img3)
    assert np.any(img3 > 0)


def test_image_overlay_load_image_jpeg_and_png():
    config = {
        'IMAGE_OVERLAY': {
            'LOAD_INTERVAL': 100,
            'A_URL': 'http://camera.local/overlay.jpg',
            'A_IMAGE_FILE_TYPE': 'jpg',
            'A_USERNAME': 'admin',
            'A_PASSWORD': 'secretpassword',
            'A_WIDTH': 40,
            'A_HEIGHT': 40,
            'A_X': 10,
            'A_Y': 10,
        },
        'FILETRANSFER': {
            'FORCE_IPV4': True,
            'LIBCURL_OPTIONS': {
                '#comment': 'ignore',
                'CURLOPT_TIMEOUT': 5,
            },
        },
    }

    # Generate real test JPEG bytes
    raw_img = np.zeros((50, 50, 3), dtype=np.uint8)
    raw_img[10:30, 10:30] = 255
    _, jpg_bytes = cv2.imencode('.jpg', raw_img)

    mock_curl = MagicMock()
    written_data = []

    def fake_setopt(opt, val):
        if opt == pycurl.WRITEDATA:
            written_data.append(val)

    def fake_perform():
        if written_data:
            written_data[-1].write(jpg_bytes.tobytes())

    mock_curl.setopt.side_effect = fake_setopt
    mock_curl.perform.side_effect = fake_perform
    mock_curl.getinfo.return_value = 200

    with patch('pycurl.Curl', return_value=mock_curl):
        overlay = IndiAllSkyImageOverlay(config)
        overlay.load_image()
        assert overlay.images_dict['a']['data'] is not None
        assert overlay.images_dict['a']['data'].shape == (40, 40, 3)

        # Corrupt JPEG
        def fake_corrupt_perform():
            if written_data:
                written_data[-1].write(b'bad jpeg data')
        mock_curl.perform.side_effect = fake_corrupt_perform
        overlay.load_image()

        # PNG loading
        _, png_bytes = cv2.imencode('.png', raw_img)
        def fake_png_perform():
            if written_data:
                written_data[-1].write(png_bytes.tobytes())
        mock_curl.perform.side_effect = fake_png_perform
        overlay.images_dict['a']['image_file_type'] = 'png'
        overlay.load_image()
        assert overlay.images_dict['a']['data'] is not None
        assert overlay.images_dict['a']['data'].shape == (40, 40, 3)

        # Corrupt PNG
        mock_curl.perform.side_effect = fake_corrupt_perform
        overlay.load_image()

        # HTTP error >= 400
        mock_curl.getinfo.return_value = 404
        overlay.load_image()


@pytest.mark.parametrize('err_code', [
    pycurl.E_LOGIN_DENIED,
    pycurl.E_COULDNT_RESOLVE_HOST,
    pycurl.E_COULDNT_CONNECT,
    pycurl.E_OPERATION_TIMEDOUT,
    pycurl.E_URL_MALFORMAT,
    pycurl.E_UNSUPPORTED_PROTOCOL,
    999,
])
def test_image_overlay_load_image_errors(err_code):
    config = {
        'IMAGE_OVERLAY': {
            'A_URL': 'http://invalid.url',
            'A_IMAGE_FILE_TYPE': 'jpg',
        },
        'FILETRANSFER': {
            'FORCE_IPV6': True,
        },
    }
    mock_curl = MagicMock()
    mock_curl.perform.side_effect = pycurl.error(err_code, 'curl error')

    with patch('pycurl.Curl', return_value=mock_curl):
        overlay = IndiAllSkyImageOverlay(config)
        # Should catch gracefully and return
        overlay.load_image()


from indi_allsky import constants
from indi_allsky.overlay.lightgraphOverlay import IndiAllSkyLightgraphOverlay


def test_lightgraph_overlay_generate_and_apply():
    font_file = "hack/Hack-Regular.ttf"
    config = {
        'LIGHTGRAPH_OVERLAY': {
            'GRAPH_HEIGHT': 20,
            'GRAPH_BORDER': 2,
            'NOW_MARKER_SIZE': 6,
            'Y': 10,
            'OFFSET_X': 0,
            'SCALE': 0.2,
            'OPACITY': 80,
            'LABEL': True,
            'HOUR_LINES': True,
            'OPENCV_FONT_SCALE': 0.5,
            'PIL_FONT_SIZE': 12,
            'NOW_COLOR': [100, 100, 200],
            'DAY_COLOR': [140, 140, 140],
            'DUSK_COLOR': [180, 90, 50],
            'NIGHT_COLOR': [20, 20, 20],
            'MOONMODE_COLOR': [40, 40, 40],
            'HOUR_COLOR': [10, 10, 80],
            'BORDER_COLOR': [5, 5, 5],
            'FONT_COLOR': [180, 180, 180],
        },
        'TEXT_PROPERTIES': {
            'FONT_FACE': 'FONT_HERSHEY_SIMPLEX',
            'FONT_AA': 'LINE_AA',
            'FONT_SCALE': 0.8,
            'FONT_THICKNESS': 1,
            'FONT_OUTLINE': True,
            'PIL_FONT_FILE': font_file,
        },
        'IMAGE_LABEL_SYSTEM': 'pillow',
    }

    position_av = {
        constants.POSITION_LATITUDE: -34.9285,
        constants.POSITION_LONGITUDE: 138.6007,
    }

    overlay = IndiAllSkyLightgraphOverlay(config, position_av)
    
    # 1. Test generate directly
    lg = overlay.generate()
    assert lg is not None
    assert len(lg.shape) == 3
    overlay.lightgraph = lg

    # Test hour_lines = False
    overlay.hour_lines = False
    lg_no_hour = overlay.generate()
    assert lg_no_hour is not None
    overlay.hour_lines = True

    # Test mapColor directly to cover all color math
    assert overlay.mapColor(0.5, (100, 50, 20), (50, 20, 10)) == (75, 35, 15)

    # 2. Test apply with pillow label
    target_img = np.zeros((400, 600, 3), dtype=np.uint8)
    overlay.apply(target_img)
    assert np.any(target_img > 0)

    # 3. Test apply with opencv label and negative y
    config['IMAGE_LABEL_SYSTEM'] = 'opencv'
    overlay.y = -50
    overlay.offset_x = 10
    overlay.next_generate = 0  # Trigger generate() inside apply()
    overlay.apply(target_img)

    # 4. Test apply with rescale when new_lightgraph_width > image_width
    overlay.scale = 2.0  # Lightgraph is 1440+ border px, > 600 px image width
    overlay.y = 500  # Outside boundary, should clamp y
    overlay.offset_x = -500  # Outside boundary, should clamp x < 0
    overlay.apply(target_img)
    assert overlay.scale <= 600 / 1440

    # 5. Test apply with x + new_lightgraph_width > image_width
    overlay.offset_x = 500
    overlay.apply(target_img)

    # 6. Test pillow label with custom font and outline=False, label=False
    overlay.label = False
    overlay.apply(target_img)

    overlay.label = True
    config['IMAGE_LABEL_SYSTEM'] = 'pillow'
    config['TEXT_PROPERTIES']['PIL_FONT_FILE'] = 'custom'
    # Use real font path for custom font
    base_font_p = overlay.font_path.joinpath(font_file)
    config['TEXT_PROPERTIES']['PIL_FONT_CUSTOM'] = str(base_font_p)
    config['TEXT_PROPERTIES']['FONT_OUTLINE'] = False
    overlay.apply(target_img)


def test_cardinal_dirs_label_extended(tmp_path):
    font_file = "hack/Hack-Regular.ttf"
    config = {
        'IMAGE_FLIP_V': True,
        'IMAGE_FLIP_H': True,
        'IMAGE_LABEL_SYSTEM': 'pillow',
        'LENS_AZIMUTH': 45,
        'CARDINAL_DIRS': {
            'CHAR_NORTH': 'N',
            'CHAR_EAST': 'E',
            'CHAR_WEST': 'W',
            'CHAR_SOUTH': 'S',
            'OFFSET_TOP': 50,
            'OFFSET_BOTTOM': 50,
            'OFFSET_LEFT': 50,
            'OFFSET_RIGHT': 50,
            'OUTLINE_CIRCLE': True,
            'FONT_COLOR': [255, 255, 255],
            'SWAP_NS': True,
            'SWAP_EW': True,
            'DIAMETER': 200,
            'PIL_FONT_SIZE': 20,
        },
        'TEXT_PROPERTIES': {
            'FONT_FACE': 'FONT_HERSHEY_SIMPLEX',
            'FONT_AA': 'LINE_AA',
            'FONT_SCALE': 1.0,
            'FONT_THICKNESS': 1,
            'FONT_OUTLINE': True,
            'PIL_FONT_FILE': font_file,
        },
        'FISH2PANO': {
            'DIRS_OFFSET_BOTTOM': 30,
            'ROTATE_ANGLE': 15,
            'FLIP_H': True,
            'OPENCV_FONT_SCALE': 0.8,
            'PIL_FONT_SIZE': 18,
        },
        'IMAGE_BORDER': {'TOP': 10, 'LEFT': 10, 'RIGHT': 0, 'BOTTOM': 0},
        'LENS_OFFSET_X': 5,
        'LENS_OFFSET_Y': -5,
    }

    labeler = IndiAllskyCardinalDirsLabel(config)
    assert labeler.az == 225.0
    labeler.az = 180
    assert labeler.az == 180.0
    assert labeler.diameter == 200
    labeler.diameter = 250
    assert labeler.diameter == 250

    img = np.zeros((300, 300, 3), dtype=np.uint8)

    # Test main with pillow and outline=True
    res = labeler.main(img.copy())
    assert not np.array_equal(res, img)

    # Small image to trigger boundary clamps in pillow main (x < left_offset, x > width - right_offset, etc.)
    small_img = np.zeros((60, 60, 3), dtype=np.uint8)
    labeler.main(small_img)

    # Test pillow with custom font and outline=False
    config['TEXT_PROPERTIES']['PIL_FONT_FILE'] = 'custom'
    base_font_p = labeler.font_path.joinpath(font_file)
    config['TEXT_PROPERTIES']['PIL_FONT_CUSTOM'] = str(base_font_p)
    config['TEXT_PROPERTIES']['FONT_OUTLINE'] = False
    labeler_custom = IndiAllskyCardinalDirsLabel(config)
    res_custom = labeler_custom.main(img.copy())
    assert not np.array_equal(res_custom, img)

    # Test all angle branches in findDirectionCoordinate and getCircleOppAdj
    # switch angles are around 45 degrees
    test_angles = [10, 40, 50, 80, 100, 130, 140, 170, 190, 220, 230, 260, 280, 310, 320, 350]
    for ang in test_angles:
        x, y = labeler.findDirectionCoordinate(img, ang)
        assert isinstance(x, int)
        assert isinstance(y, int)

    # Test getCircleOppAdj when adj > radius (large angle)
    opp, adj = labeler.getCircleOppAdj(89.9, 45, 150, 150)
    assert opp > 0
    opp2, adj2 = labeler.getCircleOppAdj(0.1, 45, 150, 150)
    assert opp2 >= 0

    # Test panorama_label with pillow (standard font, outline=True and clamps)
    config['TEXT_PROPERTIES']['PIL_FONT_FILE'] = font_file
    config['TEXT_PROPERTIES']['FONT_OUTLINE'] = True
    pano_img = np.zeros((100, 400, 3), dtype=np.uint8)
    labeler_pano_pillow = IndiAllskyCardinalDirsLabel(config)
    res_pano = labeler_pano_pillow.panorama_label(pano_img.copy())
    assert not np.array_equal(res_pano, pano_img)

    # Small pano image to trigger clamps in pillow and opencv
    small_pano = np.zeros((40, 50, 3), dtype=np.uint8)
    labeler_pano_pillow.panorama_label(small_pano)

    # Test panorama_label with opencv (FLIP_H = False, outline = True)
    config['IMAGE_LABEL_SYSTEM'] = 'opencv'
    config['TEXT_PROPERTIES']['FONT_OUTLINE'] = True
    config['FISH2PANO']['FLIP_H'] = False
    labeler_pano_cv = IndiAllskyCardinalDirsLabel(config)
    res_pano_cv = labeler_pano_cv.panorama_label(pano_img.copy())
    assert not np.array_equal(res_pano_cv, pano_img)
    labeler_pano_cv.panorama_label(small_pano)

    # Test panorama_label with pillow custom font and outline=False (covers lines 506, 523)
    config['IMAGE_LABEL_SYSTEM'] = 'pillow'
    config['TEXT_PROPERTIES']['PIL_FONT_FILE'] = 'custom'
    config['TEXT_PROPERTIES']['FONT_OUTLINE'] = False
    labeler_pano_custom = IndiAllskyCardinalDirsLabel(config)
    labeler_pano_custom.panorama_label(pano_img.copy())

    # Trigger x > width - right_offset in panorama_label_opencv (covers line 472)
    config['IMAGE_LABEL_SYSTEM'] = 'opencv'
    config['CARDINAL_DIRS']['OFFSET_RIGHT'] = 200
    labeler_pano_cv2 = IndiAllskyCardinalDirsLabel(config)
    labeler_pano_cv2.panorama_label(pano_img.copy())



