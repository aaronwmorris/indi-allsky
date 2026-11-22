import io
import time
from pathlib import Path
from multiprocessing import Array, Queue
from unittest.mock import MagicMock, patch
import pytest
import pycurl

from indi_allsky.camera.pycurl_camera import PycurlCameraWorker, IndiClientPycurl


def test_pycurl_camera_worker_success(tmp_path):
    dl_file = tmp_path / "download.jpg"
    config = {
        'FILETRANSFER': {
            'FORCE_IPV4': True,
            'LIBCURL_OPTIONS': {
                '#comment': 'ignore',
                'CURLOPT_TIMEOUT': 10,
            },
        },
        'PYCURL_CAMERA': {
            'USERNAME': 'user',
            'PASSWORD': 'password',
            'URL': 'http://camera.local/stream.mjpg',
        },
    }

    mock_curl = MagicMock()
    mock_curl.getinfo.return_value = 200

    def fake_perform():
        # dl_file should be open for writing
        pass

    mock_curl.perform.side_effect = fake_perform

    with patch('pycurl.Curl', return_value=mock_curl):
        worker = PycurlCameraWorker(1, config, dl_file)
        worker.run()

        assert dl_file.exists()
        mock_curl.close.assert_called_once()


def test_pycurl_camera_worker_http_error(tmp_path):
    dl_file = tmp_path / "download_err.jpg"
    config = {
        'FILETRANSFER': {
            'FORCE_IPV6': True,
            'LIBCURL_OPTIONS': {},
        },
        'PYCURL_CAMERA': {
            'URL': 'http://camera.local/stream.mjpg',
        },
    }

    mock_curl = MagicMock()
    mock_curl.getinfo.return_value = 500

    with patch('pycurl.Curl', return_value=mock_curl):
        worker = PycurlCameraWorker(2, config, dl_file)
        worker.run()

        # File should be unlinked on HTTP >= 400
        assert not dl_file.exists()
        mock_curl.close.assert_called_once()


@pytest.mark.parametrize('err_code', [
    pycurl.E_LOGIN_DENIED,
    pycurl.E_COULDNT_RESOLVE_HOST,
    pycurl.E_COULDNT_CONNECT,
    pycurl.E_OPERATION_TIMEDOUT,
    pycurl.E_URL_MALFORMAT,
    pycurl.E_UNSUPPORTED_PROTOCOL,
    999,
])
def test_pycurl_camera_worker_curl_errors(tmp_path, err_code):
    dl_file = tmp_path / f"download_err_{err_code}.jpg"
    config = {
        'FILETRANSFER': {},
        'PYCURL_CAMERA': {
            'URL': 'http://camera.local/stream.mjpg',
        },
    }

    mock_curl = MagicMock()
    mock_curl.perform.side_effect = pycurl.error(err_code, 'curl error')

    with patch('pycurl.Curl', return_value=mock_curl):
        worker = PycurlCameraWorker(3, config, dl_file)
        worker.run()

        # File should be unlinked on error
        assert not dl_file.exists()
        mock_curl.close.assert_called_once()


@pytest.fixture
def pycurl_camera_client(flask_app):
    config = {
        'PYCURL_CAMERA': {
            'IMAGE_FILE_TYPE': 'jpg',
            'URL': 'http://camera.local/stream.mjpg',
        },
        'FILETRANSFER': {},
    }
    image_q = Queue()
    position_av = Array('d', [0.0] * 5)
    exposure_av = Array('f', [-1.0] * 7)
    gain_av = Array('f', [-1.0] * 10)
    binning_av = Array('i', [1] * 6)
    night_av = Array('i', [1, 0])

    client = IndiClientPycurl(
        config,
        image_q,
        position_av,
        exposure_av,
        gain_av,
        binning_av,
        night_av,
    )
    client.findCcd()
    return client


def test_pycurl_camera_client_methods(pycurl_camera_client, tmp_path):
    client = pycurl_camera_client

    # Gain and binning
    client.setCcdGain(5.0)
    assert client.getCcdGain() == 5.0
    assert client.gain == 5.0

    client.setCcdBinning(None)  # None early returns
    client.setCcdBinning(2)
    assert client.binning == 2

    # Info inspection
    info = client.getCcdInfo()
    assert 'CCD_EXPOSURE' in info
    assert 'CCD_INFO' in info
    assert 'CCD_FRAME' in info
    assert 'GAIN_INFO' in info
    assert 'BINNING_INFO' in info

    # Cooler / Temperature stubs
    client.enableCcdCooler()
    client.disableCcdCooler()
    assert client.getCcdTemperature() == client.ccd_temp
    client.setCcdTemperature(0.0)
    client.setCcdScopeInfo()

    # Exposure status when no worker
    ready, status = client.getCcdExposureStatus()
    assert ready is True
    assert status == 'READY'

    # setCcdExposure with OSError
    with patch('tempfile.NamedTemporaryFile', side_effect=OSError('disk full')):
        client.setCcdExposure(1.0, 5.0, 1)

    # Mock PycurlCameraWorker so we don't start real background threads/curl
    with patch('indi_allsky.camera.pycurl_camera.PycurlCameraWorker') as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker.is_alive.return_value = True
        mock_worker_cls.return_value = mock_worker

        # Start exposure non-sync
        client.setCcdExposure(exposure=2.0, gain=10.0, binning=1, sync=False)
        assert client.active_exposure is True

        # Second exposure while active is ignored
        client.setCcdExposure(exposure=5.0, gain=10.0, binning=1)

        # Status while alive
        ready, status = client.getCcdExposureStatus()
        assert ready is False
        assert status == 'BUSY'

        # Abort exposure
        test_file = tmp_path / "exp.jpg"
        test_file.write_bytes(b'data')
        client.current_exposure_file_p = test_file
        client.abortCcdExposure()
        assert client.active_exposure is False
        assert not test_file.exists()

        # Call abort again when file does not exist to hit FileNotFoundError
        client.abortCcdExposure()

        # Re-trigger with sync=True
        mock_worker.is_alive.return_value = False
        client.setCcdExposure(exposure=0.5, gain=5.0, binning=1, sync=True, sqm_exposure=True)
        assert client.image_q.qsize() == 1
        item = client.image_q.get()
        assert item['exposure'] == 0.5
        assert item['sqm_exposure'] is True

        # Status when worker finished and active_exposure was True
        client.active_exposure = True
        ready, status = client.getCcdExposureStatus()
        assert ready is True
        assert status == 'READY'
        assert client.active_exposure is False
        assert client.image_q.qsize() == 1
