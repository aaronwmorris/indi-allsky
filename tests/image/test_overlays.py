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
