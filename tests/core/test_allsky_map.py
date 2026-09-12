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

    with patch('urllib.request.urlopen', return_value=fake_response) as mock_urlopen:
        ok, msg = send_allsky_map_ping(config, None)
        assert ok is True
        assert "Success" in msg
        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        assert req.get_header('X-api-key') == 'secret-key-123'
        body = json.loads(req.data.decode('utf-8'))
        assert body['lat'] == -34.9285
        assert body['lng'] == 138.6007
        assert 'imageBase64' in body


def test_request_allsky_map_api_key_url_rewriting_and_logger():
    fake_response = MagicMock()
    fake_response.read.return_value = json.dumps({'api_key': 'abc-123'}).encode('utf-8')
    fake_response.__enter__.return_value = fake_response
    fake_response.__exit__.return_value = None

    mock_logger = MagicMock()
    # Test URL ending with /api/ping
    with patch('urllib.request.urlopen', return_value=fake_response) as mock_urlopen:
        ok, key = request_allsky_map_api_key('https://map.allsky.tv/api/ping', logger=mock_logger)
        assert ok is True
        assert key == 'abc-123'
        assert mock_urlopen.call_args[0][0].full_url == 'https://map.allsky.tv/api/register'
        mock_logger.info.assert_called_once()

    # Test URL without /api/register
    with patch('urllib.request.urlopen', return_value=fake_response) as mock_urlopen:
        ok, key = request_allsky_map_api_key('https://map.allsky.tv', logger=None)
        assert ok is True
        assert mock_urlopen.call_args[0][0].full_url == 'https://map.allsky.tv/api/register'


def test_request_allsky_map_api_key_missing_key_in_response():
    fake_response = MagicMock()
    fake_response.read.return_value = json.dumps({'error': 'no key'}).encode('utf-8')
    fake_response.__enter__.return_value = fake_response
    fake_response.__exit__.return_value = None

    with patch('urllib.request.urlopen', return_value=fake_response):
        ok, msg = request_allsky_map_api_key('https://map.allsky.tv')
        assert ok is False
        assert "Unexpected response structure" in msg


def test_request_allsky_map_api_key_errors_with_logger():
    mock_logger = MagicMock()
    
    # HTTPError
    err = urllib.error.HTTPError('http://test', 403, 'Forbidden', {}, MagicMock(read=lambda: b'Denied'))
    with patch('urllib.request.urlopen', side_effect=err):
        ok, msg = request_allsky_map_api_key('https://map.allsky.tv', logger=mock_logger)
        assert ok is False
        assert "HTTP Error 403" in msg
        mock_logger.error.assert_called()

    # URLError
    url_err = urllib.error.URLError("DNS failure")
    with patch('urllib.request.urlopen', side_effect=url_err):
        ok, msg = request_allsky_map_api_key('https://map.allsky.tv', logger=mock_logger)
        assert ok is False
        assert "Network unreachable: DNS failure" in msg
        mock_logger.warning.assert_called()

    # Exception
    with patch('urllib.request.urlopen', side_effect=ValueError("Unexpected")):
        ok, msg = request_allsky_map_api_key('https://map.allsky.tv', logger=mock_logger)
        assert ok is False
        assert "Error: Unexpected" in msg


def test_send_allsky_map_ping_url_and_metadata(tmp_path):
    config = {
        'ALLSKYMAP': {
            'API_URL': 'https://map.allsky.tv',
            'API_KEY': 'my-key',
            'CAMERA_OWNER': 'Jane Doe',
            'WEBSITE_URL': 'https://example.com',
            'UPLOAD_IMAGE': False,
        },
        'CAMERA': {'NAME': 'Fallback Camera'},
    }
    fake_response = MagicMock()
    fake_response.read.return_value = b'{"status": "ok"}'
    fake_response.__enter__.return_value = fake_response
    fake_response.__exit__.return_value = None
    mock_logger = MagicMock()

    with patch('urllib.request.urlopen', return_value=fake_response) as mock_urlopen:
        ok, msg = send_allsky_map_ping(config, mock_logger)
        assert ok is True
        mock_logger.info.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == 'https://map.allsky.tv/api/ping'
        body = json.loads(req.data.decode('utf-8'))
        assert body['name'] == 'Fallback Camera'
        assert body['owner'] == 'Jane Doe'
        assert body['siteUrl'] == 'https://example.com'
        assert body['lat'] == 0.0
        assert body['lng'] == 0.0
        assert body['imageBase64'] == ''


def test_send_allsky_map_ping_image_size_limit_and_read_error(tmp_path):
    mock_logger = MagicMock()
    large_img = tmp_path / "latest.jpg"
    # Write a small file first
    large_img.write_bytes(b"small")

    config = {
        'ALLSKYMAP': {
            'API_URL': 'https://map.allsky.tv/api/ping',
            'API_KEY': 'my-key',
            'UPLOAD_IMAGE': True,
        },
        'IMAGE_FOLDER': str(tmp_path),
    }

    fake_response = MagicMock()
    fake_response.read.return_value = b'ok'
    fake_response.__enter__.return_value = fake_response
    fake_response.__exit__.return_value = None

    # Test image larger than 5MB
    with patch('builtins.open', patch('builtins.open', mock_open_data=b'a' * (5 * 1024 * 1024 + 1))):
        with patch('urllib.request.urlopen', return_value=fake_response):
            with patch('os.path.exists', return_value=True):
                mock_file = MagicMock()
                mock_file.read.return_value = b'a' * (5 * 1024 * 1024 + 1)
                mock_file.__enter__.return_value = mock_file
                with patch('builtins.open', return_value=mock_file):
                    send_allsky_map_ping(config, mock_logger)
                    mock_logger.warning.assert_called_with('Allsky Map Ping: latest.jpg is larger than 5MB limit')

    # Test file read exception
    with patch('os.path.exists', return_value=True):
        with patch('builtins.open', side_effect=IOError("Permission denied")):
            with patch('urllib.request.urlopen', return_value=fake_response):
                send_allsky_map_ping(config, mock_logger)
                mock_logger.error.assert_called()


def test_send_allsky_map_ping_errors_and_notifications():
    mock_logger = MagicMock()
    config = {
        'ALLSKYMAP': {
            'API_URL': 'https://map.allsky.tv/api/ping',
            'API_KEY': 'my-key',
        }
    }

    # HTTP 401 with db_notification_helper
    mock_notify = MagicMock()
    err401 = urllib.error.HTTPError('http://test', 401, 'Unauthorized', {}, MagicMock(read=lambda: b'Invalid key'))
    with patch('urllib.request.urlopen', side_effect=err401):
        ok, msg = send_allsky_map_ping(config, mock_logger, db_notification_helper=mock_notify)
        assert ok is False
        assert "HTTP Error 401" in msg
        mock_notify.assert_called_once()
        mock_logger.error.assert_called()

    # HTTP 403 with failing db_notification_helper
    mock_failing_notify = MagicMock(side_effect=Exception("DB error"))
    err403 = urllib.error.HTTPError('http://test', 403, 'Forbidden', {}, MagicMock(read=lambda: b'Forbidden'))
    with patch('urllib.request.urlopen', side_effect=err403):
        ok, msg = send_allsky_map_ping(config, mock_logger, db_notification_helper=mock_failing_notify)
        assert ok is False
        assert "HTTP Error 403" in msg

    # URLError
    url_err = urllib.error.URLError("Connection refused")
    with patch('urllib.request.urlopen', side_effect=url_err):
        ok, msg = send_allsky_map_ping(config, mock_logger)
        assert ok is False
        assert "Network unreachable: Connection refused" in msg
        mock_logger.warning.assert_called()

    # Generic Exception
    with patch('urllib.request.urlopen', side_effect=RuntimeError("Boom")):
        ok, msg = send_allsky_map_ping(config, mock_logger)
        assert ok is False
        assert "Unexpected error: Boom" in msg
        mock_logger.error.assert_called()

