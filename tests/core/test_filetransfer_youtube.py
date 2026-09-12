import sys
import json
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky.filetransfer.youtube_oauth2 import (
    youtube_oauth2,
    RETRIABLE_STATUS_CODES,
    MAX_RETRIES,
)
from indi_allsky.filetransfer.exceptions import (
    ConnectionFailure,
    AuthenticationFailure,
)


class MockHttpError(Exception):
    def __init__(self, resp, content=b""):
        super().__init__(f"HTTP {resp.status}")
        self.resp = resp
        self.content = content


class MockHttpLib2Error(Exception):
    pass


class MockRefreshError(Exception):
    pass


@pytest.fixture
def mock_google_modules():
    mock_google = MagicMock()
    mock_google_oauth2 = MagicMock()
    mock_google_oauth2_credentials = MagicMock()
    mock_google_auth = MagicMock()
    mock_google_auth_exceptions = MagicMock()
    mock_googleapiclient = MagicMock()
    mock_googleapiclient_discovery = MagicMock()
    mock_googleapiclient_http = MagicMock()
    mock_googleapiclient_errors = MagicMock()
    mock_httplib2 = MagicMock()

    mock_google.oauth2 = mock_google_oauth2
    mock_google.oauth2.credentials = mock_google_oauth2_credentials
    mock_google.auth = mock_google_auth
    mock_google.auth.exceptions = mock_google_auth_exceptions
    mock_google_auth_exceptions.RefreshError = MockRefreshError

    mock_googleapiclient.discovery = mock_googleapiclient_discovery
    mock_googleapiclient.http = mock_googleapiclient_http
    mock_googleapiclient.errors = mock_googleapiclient_errors
    mock_googleapiclient_errors.HttpError = MockHttpError

    mock_httplib2.HttpLib2Error = MockHttpLib2Error

    modules = {
        'google': mock_google,
        'google.oauth2': mock_google_oauth2,
        'google.oauth2.credentials': mock_google_oauth2_credentials,
        'google.auth': mock_google_auth,
        'google.auth.exceptions': mock_google_auth_exceptions,
        'googleapiclient': mock_googleapiclient,
        'googleapiclient.discovery': mock_googleapiclient_discovery,
        'googleapiclient.http': mock_googleapiclient_http,
        'googleapiclient.errors': mock_googleapiclient_errors,
        'httplib2': mock_httplib2,
    }

    with patch.dict(sys.modules, modules):
        yield {
            'google': mock_google,
            'credentials': mock_google_oauth2_credentials.Credentials,
            'discovery': mock_googleapiclient_discovery,
            'http': mock_googleapiclient_http,
            'errors': mock_googleapiclient_errors,
            'httplib2': mock_httplib2,
        }


def test_youtube_connect_disabled():
    transfer = youtube_oauth2({})
    with pytest.raises(ConnectionFailure, match='Youtube uploads are not enabled'):
        transfer.connect()

    transfer_disabled = youtube_oauth2({'YOUTUBE': {'ENABLE': False}})
    with pytest.raises(ConnectionFailure, match='Youtube uploads are not enabled'):
        transfer_disabled.connect()


def test_youtube_connect_success_and_close(mock_google_modules):
    config = {'YOUTUBE': {'ENABLE': True}}
    transfer = youtube_oauth2(config)
    assert transfer.client is None

    mock_cred_instance = MagicMock(expired=False)
    mock_google_modules['credentials'].return_value = mock_cred_instance
    mock_service = MagicMock()
    mock_google_modules['discovery'].build.return_value = mock_service

    cred_dict = {
        'token': 'mock_token',
        'refresh_token': 'mock_refresh',
        'client_id': 'cid',
        'client_secret': 'csec',
    }
    transfer.connect(credentials_json=json.dumps(cred_dict))

    mock_google_modules['credentials'].assert_called_once_with(**cred_dict)
    mock_google_modules['discovery'].build.assert_called_once_with(
        'youtube', 'v3', credentials=mock_cred_instance
    )
    assert transfer.client is mock_service

    transfer.close()


def test_youtube_put_night_and_day(tmp_path, mock_google_modules):
    config = {
        'YOUTUBE': {
            'ENABLE': True,
            'TITLE_TEMPLATE': '{day_date:%Y-%m-%d} - {timeofday} - {asset_label}',
            'DESCRIPTION_TEMPLATE': 'Description for {day_date:%Y-%m-%d}',
            'PRIVACY_STATUS': 'unlisted',
            'TAGS': ['sky', 'astronomy'],
            'CATEGORY': 28,
        }
    }
    transfer = youtube_oauth2(config)
    mock_service = MagicMock()
    transfer.client = mock_service

    mock_insert = MagicMock()
    mock_service.videos().insert.return_value = mock_insert
    mock_insert.next_chunk.return_value = (None, {'id': 'vid_night_123'})

    video_file = tmp_path / "timelapse.mp4"
    video_file.write_bytes(b"video content")

    # Test night=True
    meta_night = {
        'night': True,
        'dayDate': '20260912',
        'asset_label': 'keogram',
    }
    resp_night = transfer.put(local_file=str(video_file), metadata=meta_night)
    assert resp_night == {'id': 'vid_night_123'}

    call_kwargs = mock_service.videos().insert.call_args[1]
    assert call_kwargs['part'] == 'snippet,status'
    assert call_kwargs['body']['snippet']['title'] == '2026-09-12 - Night - keogram'
    assert call_kwargs['body']['snippet']['description'] == 'Description for 2026-09-12'
    assert call_kwargs['body']['snippet']['tags'] == ['sky', 'astronomy']
    assert call_kwargs['body']['snippet']['categoryId'] == 28
    assert call_kwargs['body']['status']['privacyStatus'] == 'unlisted'

    # Test night=False with default config templates
    transfer_default = youtube_oauth2({'YOUTUBE': {'ENABLE': True}})
    transfer_default.client = mock_service
    mock_insert.next_chunk.return_value = (None, {'id': 'vid_day_456'})

    meta_day = {
        'night': False,
        'dayDate': '20260912',
        'asset_label': 'timelapse',
    }
    resp_day = transfer_default.put(local_file=str(video_file), metadata=meta_day)
    assert resp_day == {'id': 'vid_day_456'}

    call_kwargs_day = mock_service.videos().insert.call_args[1]
    assert call_kwargs_day['body']['snippet']['title'] == 'Allsky Timelapse - 2026-09-12 - Day'
    assert call_kwargs_day['body']['snippet']['description'] == ''
    assert call_kwargs_day['body']['snippet']['tags'] == []
    assert call_kwargs_day['body']['snippet']['categoryId'] == 22
    assert call_kwargs_day['body']['status']['privacyStatus'] == 'private'


def test_youtube_resumable_upload_chunks(mock_google_modules):
    transfer = youtube_oauth2({'YOUTUBE': {'ENABLE': True}})
    mock_insert = MagicMock()
    # First chunk: not complete (response is None), second chunk: complete with id
    mock_insert.next_chunk.side_effect = [
        (MagicMock(), None),
        (None, {'id': 'vid_chunks'}),
    ]

    resp = transfer.resumable_upload(mock_insert)
    assert resp == {'id': 'vid_chunks'}
    assert mock_insert.next_chunk.call_count == 2


def test_youtube_resumable_upload_unexpected_response(mock_google_modules):
    transfer = youtube_oauth2({'YOUTUBE': {'ENABLE': True}})
    mock_insert = MagicMock()
    mock_insert.next_chunk.return_value = (None, {'status': 'incomplete'})

    with pytest.raises(Exception, match='The upload failed with an unexpected response:'):
        transfer.resumable_upload(mock_insert)


def test_youtube_resumable_upload_refresh_error(mock_google_modules):
    transfer = youtube_oauth2({'YOUTUBE': {'ENABLE': True}})
    mock_insert = MagicMock()
    mock_insert.next_chunk.side_effect = MockRefreshError('OAuth refresh token invalid')

    with pytest.raises(AuthenticationFailure):
        transfer.resumable_upload(mock_insert)


@pytest.mark.parametrize('status_code', RETRIABLE_STATUS_CODES)
def test_youtube_resumable_upload_retriable_http_error(mock_google_modules, status_code):
    transfer = youtube_oauth2({'YOUTUBE': {'ENABLE': True}})
    mock_insert = MagicMock()

    resp_mock = MagicMock(status=status_code)
    err = MockHttpError(resp_mock, b'Server error')

    mock_insert.next_chunk.side_effect = [
        err,
        (None, {'id': f'vid_retry_{status_code}'}),
    ]

    with patch('time.sleep') as mock_sleep:
        resp = transfer.resumable_upload(mock_insert)
        assert resp == {'id': f'vid_retry_{status_code}'}
        mock_sleep.assert_called_once_with(2.0)


def test_youtube_resumable_upload_non_retriable_http_error(mock_google_modules):
    transfer = youtube_oauth2({'YOUTUBE': {'ENABLE': True}})
    mock_insert = MagicMock()

    resp_mock = MagicMock(status=403)
    err = MockHttpError(resp_mock, b'Forbidden')
    mock_insert.next_chunk.side_effect = err

    with pytest.raises(MockHttpError):
        transfer.resumable_upload(mock_insert)


def test_youtube_resumable_upload_httplib2_error(mock_google_modules):
    transfer = youtube_oauth2({'YOUTUBE': {'ENABLE': True}})
    mock_insert = MagicMock()

    err = MockHttpLib2Error('Connection reset by peer')
    mock_insert.next_chunk.side_effect = [
        err,
        (None, {'id': 'vid_httplib2_retry'}),
    ]

    with patch('time.sleep') as mock_sleep:
        resp = transfer.resumable_upload(mock_insert)
        assert resp == {'id': 'vid_httplib2_retry'}
        mock_sleep.assert_called_once_with(2.0)


def test_youtube_resumable_upload_exceeds_max_retries(mock_google_modules):
    transfer = youtube_oauth2({'YOUTUBE': {'ENABLE': True}})
    mock_insert = MagicMock()

    resp_mock = MagicMock(status=500)
    err = MockHttpError(resp_mock, b'Persistent 500')
    # MAX_RETRIES is 3, so 4 errors will exceed max retries
    mock_insert.next_chunk.side_effect = [err] * (MAX_RETRIES + 1)

    with patch('time.sleep') as mock_sleep:
        with pytest.raises(Exception, match='No longer attempting to retry.'):
            transfer.resumable_upload(mock_insert)
        assert mock_sleep.call_count == MAX_RETRIES
