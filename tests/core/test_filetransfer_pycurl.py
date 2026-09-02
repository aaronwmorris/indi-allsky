import sys
from unittest.mock import MagicMock, patch
from pathlib import Path
import pytest

from indi_allsky.filetransfer.pycurl_syncapi_v1 import pycurl_syncapi_v1


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

        transfer.close()
        mock_curl.close.assert_called_once()
