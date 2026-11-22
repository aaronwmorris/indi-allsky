import io
import time
from multiprocessing import Queue, Array
from unittest.mock import MagicMock, patch
import numpy as np
import pytest
from astropy.io import fits
import PyIndi

from indi_allsky.camera.indi_accumulator import IndiClientIndiAccumulator
from indi_allsky.exceptions import TimeOutException


def create_test_fits_blob(shape=(20, 20), data_val=100, header_extra=None, dtype=np.int32):
    data = np.full(shape, data_val, dtype=dtype)
    hdu = fits.PrimaryHDU(data)
    hdu.header['TESTKEY'] = 'TESTVAL'
    hdu.header['EXPTIME'] = 1.0
    if header_extra:
        for k, v in header_extra.items():
            hdu.header[k] = v
    buf = io.BytesIO()
    hdu.writeto(buf)
    blob_bytes = buf.getvalue()

    mock_blob = MagicMock()
    mock_blob.getblobdata.return_value = blob_bytes
    return mock_blob


@pytest.fixture
def accum_client(flask_app):
    config = {
        'ACCUM_CAMERA': {
            'SUB_EXPOSURE_MAX': 2.0,
            'EVEN_EXPOSURES': True,
            'CLAMP_16BIT': False,
        }
    }
    image_q = Queue()
    position_av = Array('d', [0.0] * 5)
    exposure_av = Array('i', [1000000] * 7)
    gain_av = Array('i', [100000] * 10)
    binning_av = Array('i', [1] * 6)
    night_av = Array('i', [1, 0])

    client = IndiClientIndiAccumulator(
        config,
        image_q,
        position_av,
        exposure_av,
        gain_av,
        binning_av,
        night_av,
    )
    client.ccd_device = MagicMock()
    client.ccd_device.getDeviceName.return_value = 'TestCCD'
    client.ccd_min_exp = 0.1
    return client


def test_accum_properties(accum_client):
    assert accum_client.sub_exposure_max == 2.0
    assert accum_client.even_exposures is True
    assert accum_client.clamp_16bit is False
    assert accum_client.total_sub_exposures == 0
    assert accum_client.sub_exposure_base == 0.0

    accum_client.ccd_min_exp = 0.05
    assert accum_client.ccd_min_exp == 0.05


def test_accum_set_ccd_exposure_busy(accum_client):
    accum_client.camera_ready = False
    with pytest.raises(Exception, match='Camera is busy'):
        accum_client.setCcdExposure(5.0, 10.0, 1)


def test_accum_set_ccd_exposure_even(accum_client):
    with patch.object(accum_client, 'set_number') as mock_set_num, \
         patch.object(accum_client, 'setCcdGain') as mock_set_gain, \
         patch.object(accum_client, 'setCcdBinning') as mock_set_bin:
        accum_client.gain = 5.0
        accum_client.binning = 1

        accum_client.setCcdExposure(exposure=5.0, gain=10.0, binning=2, sync=False)

        assert accum_client.total_sub_exposures == 3  # ceil(5.0 / 2.0) = 3
        assert pytest.approx(accum_client.sub_exposure_base) == 5.0 / 3
        mock_set_gain.assert_called_once_with(10.0)
        mock_set_bin.assert_called_once_with(2)
        mock_set_num.assert_called_once()
        assert accum_client.camera_ready is False
        assert accum_client.exposure_state == 'BUSY'


def test_accum_set_ccd_exposure_not_even(accum_client):
    accum_client._even_exposures = False
    with patch.object(accum_client, 'set_number') as mock_set_num:
        accum_client.gain = 10.0
        accum_client.binning = 1
        accum_client.setCcdExposure(exposure=5.0, gain=10.0, binning=1, sync=False)

        assert accum_client.total_sub_exposures == 3
        assert accum_client.sub_exposure_base == 2.0
        mock_set_num.assert_called_once()


def test_accum_start_next_exposure_branches(accum_client):
    with patch.object(accum_client, 'set_number') as mock_set_num:
        # 1. exposure_remain < ccd_min_exp
        accum_client.ccd_min_exp = 0.5
        accum_client.exposure_remain = 0.2
        accum_client._total_sub_exposures = 2
        accum_client.current_sub_exposure_count = 1
        accum_client._startNextExposure()
        assert accum_client.exposure_remain == 0.0
        mock_set_num.assert_called_with(
            accum_client.ccd_device, 'CCD_EXPOSURE', {'CCD_EXPOSURE_VALUE': 0.5}, sync=False, timeout=accum_client.timeout
        )

        # 2. exp_count == 1, even_exposures=True
        accum_client._even_exposures = True
        accum_client._sub_exposure_base = 1.5
        accum_client.exposure_remain = 1.5
        accum_client._total_sub_exposures = 2
        accum_client.current_sub_exposure_count = 1
        accum_client._startNextExposure()
        assert accum_client.exposure_remain == 0.0
        mock_set_num.assert_called_with(
            accum_client.ccd_device, 'CCD_EXPOSURE', {'CCD_EXPOSURE_VALUE': 1.5}, sync=False, timeout=accum_client.timeout
        )

        # 3. exp_count == 1, even_exposures=False
        accum_client._even_exposures = False
        accum_client.exposure_remain = 0.8
        accum_client._total_sub_exposures = 2
        accum_client.current_sub_exposure_count = 1
        accum_client._startNextExposure()
        assert accum_client.exposure_remain == 0.0
        mock_set_num.assert_called_with(
            accum_client.ccd_device, 'CCD_EXPOSURE', {'CCD_EXPOSURE_VALUE': 0.8}, sync=False, timeout=accum_client.timeout
        )

        # 4. exp_count > 1
        accum_client._even_exposures = True
        accum_client._sub_exposure_base = 2.0
        accum_client.exposure_remain = 6.0
        accum_client._total_sub_exposures = 3
        accum_client.current_sub_exposure_count = 0
        accum_client._startNextExposure()
        assert pytest.approx(accum_client.exposure_remain) == 4.0
        mock_set_num.assert_called_with(
            accum_client.ccd_device, 'CCD_EXPOSURE', {'CCD_EXPOSURE_VALUE': 2.0}, sync=False, timeout=accum_client.timeout
        )


def test_accum_sync_exposure(accum_client):
    states = [(False, 'BUSY'), (True, 'READY')]

    def mock_get_status():
        return states.pop(0)

    with patch.object(accum_client, 'set_number'), \
         patch.object(accum_client, 'getCcdExposureStatus', side_effect=mock_get_status):
        accum_client.gain = 10.0
        accum_client.binning = 1
        accum_client.setCcdExposure(exposure=2.0, gain=10.0, binning=1, sync=True)


def test_accum_get_ccd_exposure_status(accum_client):
    accum_client.camera_ready = True
    accum_client.exposure_state = 'READY'
    assert accum_client.getCcdExposureStatus() == (True, 'READY')


def test_accum_abort_ccd_exposure_normal(accum_client):
    mock_switch = MagicMock()
    mock_switch.getPermission.return_value = PyIndi.IP_RW
    mock_elem = MagicMock()
    mock_switch.__getitem__.return_value = mock_elem

    accum_client.sendNewSwitch = MagicMock()
    with patch.object(accum_client, 'get_control', return_value=mock_switch) as mock_get_control:
        accum_client.abortCcdExposure()
        assert accum_client.exposure_remain == 0.0
        assert accum_client.camera_ready is True
        assert accum_client.exposure_state == 'READY'
        mock_get_control.assert_called_once_with(accum_client.ccd_device, 'CCD_ABORT_EXPOSURE', 'switch', timeout=2.0)
        mock_elem.setState.assert_called_once_with(PyIndi.ISS_ON)
        accum_client.sendNewSwitch.assert_called_once_with(mock_switch)


def test_accum_abort_ccd_exposure_timeout_and_ro(accum_client):
    # TimeOutException
    with patch.object(accum_client, 'get_control', side_effect=TimeOutException):
        accum_client.abortCcdExposure()
        assert accum_client.camera_ready is True

    # IP_RO
    mock_switch = MagicMock()
    mock_switch.getPermission.return_value = PyIndi.IP_RO
    accum_client.sendNewSwitch = MagicMock()
    with patch.object(accum_client, 'get_control', return_value=mock_switch):
        accum_client.abortCcdExposure()
        accum_client.sendNewSwitch.assert_not_called()


def test_accum_process_blob_multi_exposure_and_complete(accum_client):
    blob1 = create_test_fits_blob(shape=(10, 10), data_val=10)
    blob2 = create_test_fits_blob(shape=(10, 10), data_val=20)

    accum_client.exposure = 4.0
    accum_client.gain = 10.0
    accum_client.binning = 1
    accum_client.sqm_exposure = False
    accum_client.exposureStartTime = time.time()
    accum_client.camera_id = 0
    accum_client._total_sub_exposures = 2
    accum_client.exposure_remain = 2.0

    with patch.object(accum_client, '_startNextExposure') as mock_start_next:
        # First sub-exposure
        accum_client.processBlob(blob1)
        assert accum_client.data is not None
        assert np.all(accum_client.data == 10)
        mock_start_next.assert_called_once()

    # Second sub-exposure (final)
    accum_client.exposure_remain = 0.0
    accum_client.processBlob(blob2)
    assert accum_client.camera_ready is True
    assert accum_client.exposure_state == 'READY'
    assert accum_client.data is None
    assert accum_client.header is None
    job = accum_client.image_q.get(timeout=1.0)
    assert job['exposure'] == 4.0
    assert job['camera_name'] == 'TestCCD'


def test_accum_process_blob_clamp_16bit(accum_client):
    accum_client._clamp_16bit = True
    blob = create_test_fits_blob(shape=(10, 10), data_val=70000)

    accum_client.exposure = 2.0
    accum_client.gain = 10.0
    accum_client.binning = 1
    accum_client.exposureStartTime = time.time()
    accum_client.camera_id = 0
    accum_client._total_sub_exposures = 1
    accum_client.exposure_remain = 0.0

    accum_client.processBlob(blob)
    assert accum_client.camera_ready is True
    job = accum_client.image_q.get(timeout=1.0)
    assert job['exposure'] == 2.0


def test_accum_process_blob_oserror(accum_client):
    blob = create_test_fits_blob(shape=(10, 10), data_val=10)
    accum_client.exposure = 2.0
    accum_client.gain = 10.0
    accum_client.binning = 1
    accum_client.exposureStartTime = time.time()
    accum_client.camera_id = 0
    accum_client._total_sub_exposures = 1
    accum_client.exposure_remain = 0.0

    with patch('astropy.io.fits.HDUList.writeto', side_effect=OSError('Disk full')):
        accum_client.processBlob(blob)
        assert accum_client.data is None
        assert accum_client.header is None


def test_accum_get_ccd_info(accum_client):
    parent_ccd_info = {
        'CCD_EXPOSURE': {
            'CCD_EXPOSURE_VALUE': {
                'max': 300.0,
                'min': 0.00123456,
            }
        }
    }
    with patch('indi_allsky.camera.indi.IndiClient.getCcdInfo', return_value=parent_ccd_info):
        info = accum_client.getCcdInfo()
        # Overridden to 600.0 since 300 < 600
        assert info['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['max'] == 600.0
        assert accum_client.ccd_min_exp == 0.001235

    # When max is already >= 600
    parent_ccd_info_high = {
        'CCD_EXPOSURE': {
            'CCD_EXPOSURE_VALUE': {
                'max': 1000.0,
                'min': 0.01,
            }
        }
    }
    with patch('indi_allsky.camera.indi.IndiClient.getCcdInfo', return_value=parent_ccd_info_high):
        info = accum_client.getCcdInfo()
        assert info['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['max'] == 1000.0
