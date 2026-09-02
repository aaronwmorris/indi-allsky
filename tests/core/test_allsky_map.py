import json
import urllib.error
from unittest.mock import patch, MagicMock
import pytest

from indi_allsky.allsky_map import request_allsky_map_api_key, send_allsky_map_ping


def test_request_allsky_map_api_key_empty():
    ok, msg = request_allsky_map_api_key("")
    assert not ok
    assert "API URL is required" in msg


def test_request_allsky_map_api_key_success():
    fake_response = MagicMock()
    fake_response.read.return_value = json.dumps({'api_key': 'test-allsky-key-123'}).encode('utf-8')
    fake_response.__enter__.return_value = fake_response
    fake_response.__exit__.return_value = None

    with patch('urllib.request.urlopen', return_value=fake_response):
        ok, key = request_allsky_map_api_key('https://map.allsky.tv/api/register')
        assert ok is True
        assert key == 'test-allsky-key-123'


def test_request_allsky_map_api_key_http_error():
    err = urllib.error.HTTPError(
        url='https://map.allsky.tv/api/register',
        code=400,
        msg='Bad Request',
        hdrs={},
        fp=MagicMock(read=lambda: b'Invalid request data'),
    )
    with patch('urllib.request.urlopen', side_effect=err):
        ok, msg = request_allsky_map_api_key('https://map.allsky.tv/api/register')
        assert ok is False
        assert 'HTTP Error 400' in msg


def test_send_allsky_map_ping_missing_config():
    ok, msg = send_allsky_map_ping({}, None)
    assert not ok
    assert "missing" in msg


def test_send_allsky_map_ping_success(tmp_path):
    img_file = tmp_path / "latest.jpg"
    img_file.write_bytes(b"dummy image data")

    config = {
        'ALLSKYMAP': {
            'API_URL': 'https://map.allsky.tv/api/ping',
            'API_KEY': 'secret-key-123',
            'CAMERA_NAME': 'Test Cam',
            'UPLOAD_IMAGE': True,
        },
        'LOCATION_LATITUDE': -34.9285,
        'LOCATION_LONGITUDE': 138.6007,
        'IMAGE_FOLDER': str(tmp_path),
    }

    fake_response = MagicMock()
    fake_response.read.return_value = b'{"status": "ok"}'
    fake_response.__enter__.return_value = fake_response
    fake_response.__exit__.return_value = None

    with patch('urllib.request.urlopen', return_value=fake_response):
        ok, msg = send_allsky_map_ping(config, None)
        assert ok is True
        assert "Success" in msg
