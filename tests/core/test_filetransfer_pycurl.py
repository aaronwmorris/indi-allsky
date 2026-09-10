import sys
from unittest.mock import MagicMock, patch
from pathlib import Path
import pytest
import pycurl

from indi_allsky.filetransfer.pycurl_syncapi_v1 import pycurl_syncapi_v1
from indi_allsky.filetransfer.pycurl_webdav_https import pycurl_webdav_https
from indi_allsky.filetransfer.pycurl_ftpes import pycurl_ftpes, ftpes
from indi_allsky.filetransfer.pycurl_sftp import pycurl_sftp, sftp
from indi_allsky.filetransfer.pycurl_ftp import pycurl_ftp, ftp
from indi_allsky.filetransfer.pycurl_ftps import pycurl_ftps, ftps
from indi_allsky.filetransfer.exceptions import (
    AuthenticationFailure,
    ConnectionFailure,
    CertificateValidationFailure,
    TransferFailure,
)


def test_pycurl_syncapi_v1_connect_and_put(tmp_path):
    mock_pycurl = MagicMock()
    mock_curl = MagicMock()
    mock_pycurl.Curl.return_value = mock_curl
    mock_pycurl.FORM_BUFFER = 'FORM_BUFFER'
    mock_pycurl.FORM_BUFFERPTR = 'FORM_BUFFERPTR'
    mock_pycurl.FORM_CONTENTTYPE = 'FORM_CONTENTTYPE'
    mock_pycurl.FORM_FILE = 'FORM_FILE'
    mock_pycurl.FORM_FILENAME = 'FORM_FILENAME'
    mock_pycurl.WRITEFUNCTION = 10001

    callbacks = {}
    def fake_setopt(option, value):
        callbacks[option] = value

    def fake_perform():
        if mock_pycurl.WRITEFUNCTION in callbacks:
            callbacks[mock_pycurl.WRITEFUNCTION](b'{"success": true}')

    mock_curl.setopt.side_effect = fake_setopt
    mock_curl.perform.side_effect = fake_perform

    with patch.dict(sys.modules, {'pycurl': mock_pycurl}):
        config = {
            'FILETRANSFER': {
                'FORCE_IPV4': True,
                'LIBCURL_OPTIONS': {
                    'CURLOPT_SSL_VERIFYPEER': 0,
                    '#comment': 'ignore',
                },
            },
        }
        transfer = pycurl_syncapi_v1(config)
        transfer.connect(
            hostname='https://sync.example.com/api/v1',
            username='user',
            apikey='key123',
            cert_bypass=True,
        )

        test_file = tmp_path / "sync.jpg"
        test_file.write_bytes(b"dummy image data")

        mock_curl.getinfo.return_value = 200
        transfer.put(
            local_file=str(test_file),
            metadata={'camera_uuid': 'cam-1', 'time': 'now'},
        )

        assert mock_curl.setopt.call_count >= 1
        assert mock_curl.perform.call_count >= 1
        transfer.close()
        mock_curl.close.assert_called_once()


def test_webdav_lifecycle_and_put(tmp_path):
    mock_curl = MagicMock()
    with patch('pycurl.Curl', return_value=mock_curl):
        config = {
            'FILETRANSFER': {
                'FORCE_IPV4': True,
                'LIBCURL_OPTIONS': {
                    '#ignored': 'comment',
                    'CURLOPT_TIMEOUT': 15,
                },
            }
        }
        transfer = pycurl_webdav_https(config)
        assert transfer._port == 443

        transfer.connect(
            hostname='webdav.example.com',
            username='myuser',
            password='mypassword',
            cert_bypass=True,
        )
        assert transfer.url == 'https://webdav.example.com:443'

        # Test IPv6 and cert_bypass=False
        config_v6 = {
            'FILETRANSFER': {
                'FORCE_IPV6': True,
                'LIBCURL_OPTIONS': {},
            }
        }
        transfer_v6 = pycurl_webdav_https(config_v6)
        transfer_v6.connect(
            hostname='webdav.example.com',
            username='myuser',
            password='mypassword',
            cert_bypass=False,
        )

        local_file = tmp_path / "img.jpg"
        local_file.write_bytes(b"image data here")

        transfer.put(
            local_file=str(local_file),
            remote_file='parent/folder/img.jpg',
        )
        assert mock_curl.perform.call_count >= 2  # MKCOL and upload
        mock_curl.unsetopt.assert_called_with(pycurl.CUSTOMREQUEST)

        transfer.close()
        mock_curl.close.assert_called()


@pytest.mark.parametrize('err_code, expected_exc', [
    (pycurl.E_LOGIN_DENIED, AuthenticationFailure),
    (pycurl.E_COULDNT_RESOLVE_HOST, ConnectionFailure),
    (pycurl.E_COULDNT_CONNECT, ConnectionFailure),
    (pycurl.E_URL_MALFORMAT, ConnectionFailure),
    (pycurl.E_OPERATION_TIMEDOUT, ConnectionFailure),
    (pycurl.E_PEER_FAILED_VERIFICATION, CertificateValidationFailure),
    (999, pycurl.error),
])
def test_webdav_mkcol_errors(tmp_path, err_code, expected_exc):
    mock_curl = MagicMock()
    mock_curl.perform.side_effect = pycurl.error(err_code, 'mkcol error')
    with patch('pycurl.Curl', return_value=mock_curl):
        transfer = pycurl_webdav_https({'FILETRANSFER': {}})
        transfer.connect(hostname='x', username='u', password='p')
        local_file = tmp_path / "img.jpg"
        local_file.write_bytes(b"data")

        with pytest.raises(expected_exc):
            transfer.put(local_file=str(local_file), remote_file='folder/img.jpg')


@pytest.mark.parametrize('err_code, expected_exc', [
    (pycurl.E_LOGIN_DENIED, AuthenticationFailure),
    (pycurl.E_COULDNT_RESOLVE_HOST, ConnectionFailure),
    (pycurl.E_COULDNT_CONNECT, ConnectionFailure),
    (pycurl.E_OPERATION_TIMEDOUT, ConnectionFailure),
    (pycurl.E_PEER_FAILED_VERIFICATION, CertificateValidationFailure),
    (pycurl.E_REMOTE_ACCESS_DENIED, TransferFailure),
    (pycurl.E_REMOTE_FILE_NOT_FOUND, TransferFailure),
    (999, pycurl.error),
])
def test_webdav_upload_errors(tmp_path, err_code, expected_exc):
    mock_curl = MagicMock()
    # First perform is MKCOL (succeeds), second perform is upload (fails)
    mock_curl.perform.side_effect = [None, pycurl.error(err_code, 'upload error')]
    with patch('pycurl.Curl', return_value=mock_curl):
        transfer = pycurl_webdav_https({'FILETRANSFER': {}})
        transfer.connect(hostname='x', username='u', password='p')
        local_file = tmp_path / "img.jpg"
        local_file.write_bytes(b"data")

        with pytest.raises(expected_exc):
            transfer.put(local_file=str(local_file), remote_file='folder/img.jpg')


def test_ftpes_lifecycle_and_atomic(tmp_path):
    mock_curl = MagicMock()
    with patch('pycurl.Curl', return_value=mock_curl):
        config = {
            'FILETRANSFER': {
                'FORCE_IPV4': True,
                'LIBCURL_OPTIONS': {
                    '#comment': 'skip',
                    'CURLOPT_TIMEOUT': 20,
                },
            }
        }
        transfer = ftpes(config)
        assert transfer._port == 21

        transfer.connect(
            hostname='ftp.example.com',
            username='user',
            password='pwd',
            cert_bypass=True,
        )
        assert transfer.url == 'ftp://ftp.example.com:21'

        config_v6 = {
            'FILETRANSFER': {
                'FORCE_IPV6': True,
                'LIBCURL_OPTIONS': {},
            }
        }
        transfer_v6 = ftpes(config_v6)
        transfer_v6.connect(
            hostname='ftp.example.com',
            username='user',
            password='pwd',
            cert_bypass=False,
        )

        local_file = tmp_path / "img.jpg"
        local_file.write_bytes(b"data")

        # Non-atomic put
        transfer.atomic = False
        transfer.put(local_file=str(local_file), remote_file='remote/img.jpg')
        assert mock_curl.perform.called

        # Atomic put
        transfer.atomic = True
        transfer.put(local_file=str(local_file), remote_file='remote/img.jpg')

        postquote_calls = [
            call[0][1] for call in mock_curl.setopt.call_args_list if call[0][0] == pycurl.POSTQUOTE
        ]
        assert any(any('*DELE' in cmd for cmd in cmds) for cmds in postquote_calls)

        transfer.close()
        mock_curl.close.assert_called()


@pytest.mark.parametrize('err_code, expected_exc', [
    (pycurl.E_LOGIN_DENIED, AuthenticationFailure),
    (pycurl.E_COULDNT_RESOLVE_HOST, ConnectionFailure),
    (pycurl.E_COULDNT_CONNECT, ConnectionFailure),
    (pycurl.E_OPERATION_TIMEDOUT, ConnectionFailure),
    (pycurl.E_URL_MALFORMAT, ConnectionFailure),
    (pycurl.E_USE_SSL_FAILED, ConnectionFailure),
    (pycurl.E_PEER_FAILED_VERIFICATION, CertificateValidationFailure),
    (pycurl.E_REMOTE_ACCESS_DENIED, TransferFailure),
    (pycurl.E_REMOTE_FILE_NOT_FOUND, TransferFailure),
    (pycurl.E_QUOTE_ERROR, None),
    (999, pycurl.error),
])
def test_ftpes_errors(tmp_path, err_code, expected_exc):
    mock_curl = MagicMock()
    mock_curl.perform.side_effect = pycurl.error(err_code, 'ftpes error')
    with patch('pycurl.Curl', return_value=mock_curl):
        transfer = pycurl_ftpes({'FILETRANSFER': {}})
        transfer.connect(hostname='x', username='u', password='p')
        local_file = tmp_path / "img.jpg"
        local_file.write_bytes(b"data")

        if expected_exc:
            with pytest.raises(expected_exc):
                transfer.put(local_file=str(local_file), remote_file='img.jpg')
        else:
            # E_QUOTE_ERROR is safely ignored
            transfer.put(local_file=str(local_file), remote_file='img.jpg')


def test_sftp_lifecycle_and_keys(tmp_path):
    mock_curl = MagicMock()
    with patch('pycurl.Curl', return_value=mock_curl):
        config = {
            'FILETRANSFER': {
                'FORCE_IPV4': True,
                'LIBCURL_OPTIONS': {
                    '#skip': 'val',
                    'CURLOPT_TIMEOUT': 10,
                },
            }
        }
        transfer = sftp(config)
        assert transfer._port == 22

        # Key-based authentication
        transfer.connect(
            hostname='sftp.example.com',
            username='user',
            password='keypassword',
            private_key='/tmp/id_rsa',
            public_key='/tmp/id_rsa.pub',
        )
        assert transfer.url == 'sftp://sftp.example.com:22'

        # Password authentication + IPv6
        config_v6 = {
            'FILETRANSFER': {
                'FORCE_IPV6': True,
                'LIBCURL_OPTIONS': {},
            }
        }
        transfer_v6 = sftp(config_v6)
        transfer_v6.connect(
            hostname='sftp.example.com',
            username='user',
            password='pwd',
        )

        local_file = tmp_path / "img.jpg"
        local_file.write_bytes(b"data")

        # Non-atomic put
        transfer.atomic = False
        transfer.put(local_file=str(local_file), remote_file='dest/img.jpg')

        # Atomic put
        transfer.atomic = True
        transfer.put(local_file=str(local_file), remote_file='dest/img.jpg')

        postquote_calls = [
            call[0][1] for call in mock_curl.setopt.call_args_list if call[0][0] == pycurl.POSTQUOTE
        ]
        assert any(any('*rm' in cmd for cmd in cmds) for cmds in postquote_calls)

        transfer.close()
        mock_curl.close.assert_called()


@pytest.mark.parametrize('err_code, expected_exc', [
    (pycurl.E_LOGIN_DENIED, AuthenticationFailure),
    (pycurl.E_COULDNT_RESOLVE_HOST, ConnectionFailure),
    (pycurl.E_COULDNT_CONNECT, ConnectionFailure),
    (pycurl.E_OPERATION_TIMEDOUT, ConnectionFailure),
    (pycurl.E_URL_MALFORMAT, ConnectionFailure),
    (pycurl.E_PEER_FAILED_VERIFICATION, CertificateValidationFailure),
    (pycurl.E_REMOTE_ACCESS_DENIED, TransferFailure),
    (pycurl.E_REMOTE_FILE_NOT_FOUND, TransferFailure),
    (pycurl.E_QUOTE_ERROR, None),
    (999, pycurl.error),
])
def test_sftp_errors(tmp_path, err_code, expected_exc):
    mock_curl = MagicMock()
    mock_curl.perform.side_effect = pycurl.error(err_code, 'sftp error')
    with patch('pycurl.Curl', return_value=mock_curl):
        transfer = pycurl_sftp({'FILETRANSFER': {}})
        transfer.connect(hostname='x', username='u', password='p')
        local_file = tmp_path / "img.jpg"
        local_file.write_bytes(b"data")

        if expected_exc:
            with pytest.raises(expected_exc):
                transfer.put(local_file=str(local_file), remote_file='img.jpg')
        else:
            transfer.put(local_file=str(local_file), remote_file='img.jpg')


def test_ftp_lifecycle_and_put(tmp_path):
    mock_curl = MagicMock()
    with patch('pycurl.Curl', return_value=mock_curl):
        config = {
            'FILETRANSFER': {
                'FORCE_IPV4': True,
                'LIBCURL_OPTIONS': {
                    '#ignored': 'comment',
                    'CURLOPT_TIMEOUT': 15,
                },
            }
        }
        transfer = pycurl_ftp(config)
        assert transfer._port == 21

        transfer.connect(
            hostname='ftp.example.com',
            username='myuser',
            password='mypassword',
        )
        assert transfer.url == 'ftp://ftp.example.com:21'

        # Test IPv6
        config_v6 = {
            'FILETRANSFER': {
                'FORCE_IPV6': True,
            }
        }
        transfer_v6 = ftp(config_v6)
        transfer_v6.connect(hostname='ftp.example.com', username='u', password='p')

        local_file = tmp_path / "img.jpg"
        local_file.write_bytes(b"data")

        # Non-atomic put
        transfer.atomic = False
        transfer.put(local_file=str(local_file), remote_file='dest/img.jpg')

        # Atomic put
        transfer.atomic = True
        transfer.put(local_file=str(local_file), remote_file='dest/img.jpg')

        postquote_calls = [
            call[0][1] for call in mock_curl.setopt.call_args_list if call[0][0] == pycurl.POSTQUOTE
        ]
        assert any(any('RNTO' in cmd for cmd in cmds) for cmds in postquote_calls)

        transfer.close()
        mock_curl.close.assert_called()


@pytest.mark.parametrize('err_code, expected_exc', [
    (pycurl.E_LOGIN_DENIED, AuthenticationFailure),
    (pycurl.E_COULDNT_RESOLVE_HOST, ConnectionFailure),
    (pycurl.E_COULDNT_CONNECT, ConnectionFailure),
    (pycurl.E_OPERATION_TIMEDOUT, ConnectionFailure),
    (pycurl.E_URL_MALFORMAT, ConnectionFailure),
    (pycurl.E_REMOTE_ACCESS_DENIED, TransferFailure),
    (pycurl.E_REMOTE_FILE_NOT_FOUND, TransferFailure),
    (pycurl.E_QUOTE_ERROR, None),
    (999, pycurl.error),
])
def test_ftp_errors(tmp_path, err_code, expected_exc):
    mock_curl = MagicMock()
    mock_curl.perform.side_effect = pycurl.error(err_code, 'ftp error')
    with patch('pycurl.Curl', return_value=mock_curl):
        transfer = pycurl_ftp({'FILETRANSFER': {}})
        transfer.connect(hostname='x', username='u', password='p')
        local_file = tmp_path / "img.jpg"
        local_file.write_bytes(b"data")

        if expected_exc:
            with pytest.raises(expected_exc):
                transfer.put(local_file=str(local_file), remote_file='img.jpg')
        else:
            transfer.put(local_file=str(local_file), remote_file='img.jpg')


def test_ftps_lifecycle_and_put(tmp_path):
    mock_curl = MagicMock()
    with patch('pycurl.Curl', return_value=mock_curl):
        config = {
            'FILETRANSFER': {
                'FORCE_IPV4': True,
                'LIBCURL_OPTIONS': {
                    '#ignored': 'comment',
                    'CURLOPT_TIMEOUT': 15,
                },
            }
        }
        transfer = pycurl_ftps(config)
        assert transfer._port == 990

        transfer.connect(
            hostname='ftps.example.com',
            username='myuser',
            password='mypassword',
            cert_bypass=True,
        )
        assert transfer.url == 'ftps://ftps.example.com:990'

        # Test IPv6 and cert_bypass=False
        config_v6 = {
            'FILETRANSFER': {
                'FORCE_IPV6': True,
            }
        }
        transfer_v6 = ftps(config_v6)
        transfer_v6.connect(hostname='ftps.example.com', username='u', password='p', cert_bypass=False)

        local_file = tmp_path / "img.jpg"
        local_file.write_bytes(b"data")

        # Non-atomic put
        transfer.atomic = False
        transfer.put(local_file=str(local_file), remote_file='dest/img.jpg')

        # Atomic put
        transfer.atomic = True
        transfer.put(local_file=str(local_file), remote_file='dest/img.jpg')

        postquote_calls = [
            call[0][1] for call in mock_curl.setopt.call_args_list if call[0][0] == pycurl.POSTQUOTE
        ]
        assert any(any('RNTO' in cmd for cmd in cmds) for cmds in postquote_calls)

        transfer.close()
        mock_curl.close.assert_called()


@pytest.mark.parametrize('err_code, expected_exc', [
    (pycurl.E_LOGIN_DENIED, AuthenticationFailure),
    (pycurl.E_COULDNT_RESOLVE_HOST, ConnectionFailure),
    (pycurl.E_COULDNT_CONNECT, ConnectionFailure),
    (pycurl.E_OPERATION_TIMEDOUT, ConnectionFailure),
    (pycurl.E_URL_MALFORMAT, ConnectionFailure),
    (pycurl.E_USE_SSL_FAILED, ConnectionFailure),
    (pycurl.E_PEER_FAILED_VERIFICATION, CertificateValidationFailure),
    (pycurl.E_REMOTE_ACCESS_DENIED, TransferFailure),
    (pycurl.E_REMOTE_FILE_NOT_FOUND, TransferFailure),
    (pycurl.E_QUOTE_ERROR, None),
    (999, pycurl.error),
])
def test_ftps_errors(tmp_path, err_code, expected_exc):
    mock_curl = MagicMock()
    mock_curl.perform.side_effect = pycurl.error(err_code, 'ftps error')
    with patch('pycurl.Curl', return_value=mock_curl):
        transfer = pycurl_ftps({'FILETRANSFER': {}})
        transfer.connect(hostname='x', username='u', password='p')
        local_file = tmp_path / "img.jpg"
        local_file.write_bytes(b"data")

        if expected_exc:
            with pytest.raises(expected_exc):
                transfer.put(local_file=str(local_file), remote_file='img.jpg')
        else:
            transfer.put(local_file=str(local_file), remote_file='img.jpg')


