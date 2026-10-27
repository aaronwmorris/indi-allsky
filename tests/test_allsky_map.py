import base64
import io
import json
import logging
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from indi_allsky.allsky_map import send_allsky_map_ping


@pytest.fixture
def base_config(tmp_path):
    return {
        'LOCATION_LATITUDE': -34.92,
        'LOCATION_LONGITUDE': 138.60,
        'CAMERA': {'NAME': 'Test SkyCam'},
        'IMAGE_FOLDER': str(tmp_path),
        'IMAGE_FILE_TYPE': 'jpg',
        'ALLSKYMAP': {
            'API_URL': 'https://allsky-map.com',
            'API_KEY': 'test_key',
            'UPLOAD_IMAGE': True,
        },
    }


def test_missing_api_key_or_url():
    config = {'ALLSKYMAP': {}}
    logger = logging.getLogger('test_map')
    success, msg = send_allsky_map_ping(config, logger)
    assert not success
    assert 'missing' in msg.lower()


def test_ping_with_jpg(tmp_path, base_config):
    img_path = tmp_path / 'latest.jpg'
    img = Image.new('RGB', (10, 10), color='blue')
    img.save(str(img_path), format='JPEG')

    logger = logging.getLogger('test_map')

    with patch('urllib.request.urlopen') as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"status": "ok"}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        success, _ = send_allsky_map_ping(base_config, logger)

        assert success
        assert mock_urlopen.called
        req = mock_urlopen.call_args[0][0]
        data = json.loads(req.data.decode('utf-8'))
        assert data['imageBase64']
        decoded = base64.b64decode(data['imageBase64'])
        assert decoded.startswith(b'\xff\xd8\xff')


def test_ping_with_png_ignores_stale_jpg(tmp_path, base_config):
    # Simulate the exact issue in Discussion #3307:
    # A stale latest.jpg remains, but IMAGE_FILE_TYPE is now 'png'.
    stale_jpg = tmp_path / 'latest.jpg'
    stale_img = Image.new('RGB', (10, 10), color='red')
    stale_img.save(str(stale_jpg), format='JPEG')

    new_png = tmp_path / 'latest.png'
    png_img = Image.new('RGB', (10, 10), color='green')
    png_img.save(str(new_png), format='PNG')

    base_config['IMAGE_FILE_TYPE'] = 'png'
    logger = logging.getLogger('test_map')

    with patch('urllib.request.urlopen') as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"status": "ok"}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        success, _ = send_allsky_map_ping(base_config, logger)

        assert success
        req = mock_urlopen.call_args[0][0]
        data = json.loads(req.data.decode('utf-8'))
        assert data['imageBase64']
        decoded = base64.b64decode(data['imageBase64'])
        # Valid PNG magic bytes
        assert decoded.startswith(b'\x89PNG\r\n\x1a\n')


def test_ping_with_tif_transcoded_to_jpeg(tmp_path, base_config):
    # TIFF files must be transcoded to JPEG for map compatibility
    tif_path = tmp_path / 'latest.tif'
    tif_img = Image.new('RGB', (20, 20), color='cyan')
    tif_img.save(str(tif_path), format='TIFF')

    base_config['IMAGE_FILE_TYPE'] = 'tif'
    logger = logging.getLogger('test_map')

    with patch('urllib.request.urlopen') as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"status": "ok"}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        success, _ = send_allsky_map_ping(base_config, logger)

        assert success
        req = mock_urlopen.call_args[0][0]
        data = json.loads(req.data.decode('utf-8'))
        assert data['imageBase64']
        decoded = base64.b64decode(data['imageBase64'])
        # Transcoded output must be JPEG
        assert decoded.startswith(b'\xff\xd8\xff')


def test_ping_oversized_png_transcoded_under_10mb(tmp_path, base_config):
    png_path = tmp_path / 'latest.png'
    png_img = Image.new('RGB', (50, 50), color='magenta')
    png_img.save(str(png_path), format='PNG')

    base_config['IMAGE_FILE_TYPE'] = 'png'
    logger = logging.getLogger('test_map')

    # Simulate raw PNG read returning 12MB
    fake_png_data = b'x' * (12 * 1024 * 1024)

    mock_im = MagicMock()
    mock_im.__enter__.return_value = mock_im
    mock_im.__exit__.return_value = None
    def fake_save(buf, format, quality):
        buf.write(b'\xff\xd8\xff' + b'y' * 1000)

    mock_im.convert.return_value.save.side_effect = fake_save

    with patch('builtins.open', patch('builtins.open').__enter__()):
        pass

    original_open = open

    def custom_open(path, mode='r', *args, **kwargs):
        if str(path) == str(png_path) and 'rb' in mode:
            return io.BytesIO(fake_png_data)
        return original_open(path, mode, *args, **kwargs)

    with (
        patch('builtins.open', side_effect=custom_open),
        patch('PIL.Image.open', return_value=mock_im),
        patch('urllib.request.urlopen') as mock_urlopen,
    ):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"status": "ok"}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        success, _ = send_allsky_map_ping(base_config, logger)

        assert success
        req = mock_urlopen.call_args[0][0]
        data = json.loads(req.data.decode('utf-8'))
        assert data['imageBase64']
        decoded = base64.b64decode(data['imageBase64'])
        assert decoded.startswith(b'\xff\xd8\xff')
        assert len(decoded) <= 10 * 1024 * 1024


def test_ping_truly_oversized_image_skipped(tmp_path, base_config):
    # Image exceeds 10MB and cannot be compressed under 10MB
    jpg_path = tmp_path / 'latest.jpg'
    jpg_path.write_bytes(b'x' * (11 * 1024 * 1024))

    base_config['IMAGE_FILE_TYPE'] = 'jpg'
    logger = logging.getLogger('test_map')

    with patch('urllib.request.urlopen') as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"status": "ok"}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        success, _ = send_allsky_map_ping(base_config, logger)

        assert success
        req = mock_urlopen.call_args[0][0]
        data = json.loads(req.data.decode('utf-8'))
        # Exceeds 10MB limit and is not valid image to transcode, so empty string
        assert data['imageBase64'] == ''
