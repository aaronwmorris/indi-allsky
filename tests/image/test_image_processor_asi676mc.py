import ctypes
from datetime import datetime, timedelta
from multiprocessing import Array
from unittest.mock import MagicMock, patch
from astropy.io import fits
import numpy as np
import pytest

from indi_allsky import constants
from indi_allsky.processing import ImageProcessor, ImageData
from indi_allsky.flask.models import NotificationCategory


class DummyCamera:
    def __init__(self):
        self.id = 1
        self.name = "ZWO CCD ASI676MC"
        self.uuid = "12345678-1234-5678-1234-567812345678"
        self.location = "Observatory"
        self.lensFocalLength = 2.5
        self.lensFocalRatio = 1.4
        self.lensImageCircle = 1000
        self.width = 64
        self.height = 64
        self.pixelSize = 2.9
        self.cfa = constants.CFA_RGGB
        self.owner = "Admin"
        self.data = {}


@pytest.fixture
def ip_fixture(base_config, tmp_path):
    config = dict(base_config)
    config['VARLIB_FOLDER'] = str(tmp_path)
    config['LOCATION_LATITUDE'] = -34.9285
    config['LOCATION_LONGITUDE'] = 138.6007
    config['LOCATION_ELEVATION'] = 50.0
    config['NIGHT_SUN_ALT_DEG'] = -6.0
    config['ORB_PROPERTIES'] = {
        'AZ_OFFSET': 0.0,
        'RETROGRADE': False,
        'SUN_COLOR': [255, 200, 0],
        'MOON_COLOR': [200, 200, 200],
    }

    position_av = Array('d', [0.0] * 5)
    exposure_av = Array(ctypes.c_int32, [1000000, 1000000, 0, 1000, 100, 30000000, 5000000])
    gain_av = Array(ctypes.c_int32, [100000, 100000, 0, 0, 100000, 100000, 400000, 50000, 200000, 100000])
    binning_av = Array('i', [1, 1, 1, 2, 1, 1])
    sensors_temp_av = Array('f', [0.0] * 110)
    sensors_user_av = Array('f', [0.0] * 110)
    night_av = Array('i', [1, 0])
    astro_av = Array('f', [0.0] * 10)

    return ImageProcessor(
        config=config,
        position_av=position_av,
        exposure_av=exposure_av,
        gain_av=gain_av,
        binning_av=binning_av,
        sensors_temp_av=sensors_temp_av,
        sensors_user_av=sensors_user_av,
        night_av=night_av,
        astro_av=astro_av,
    )


def make_dummy_image_data(ip, binning=1, bayerpat='RGGB', detected_cam="ZWO CCD ASI676MC", x_off=0, y_off=0):
    data = np.full((64, 64), 500, dtype=np.uint16)
    hdu = fits.PrimaryHDU(data)
    hdu.header['XBAYROFF'] = x_off
    hdu.header['YBAYROFF'] = y_off
    hdulist = fits.HDUList([hdu])

    i_ref = ImageData(
        config=ip.config,
        hdulist=hdulist,
        exposure=1.0,
        gain=100.0,
        binning=binning,
        exp_date=datetime.now(),
        exp_elapsed=1.0,
        day_date=datetime.now().date(),
        camera_id=1,
        camera_name="ZWO CCD ASI676MC",
        camera_uuid="cam-uuid",
        owner="Admin",
        location="Observatory",
        image_bitpix=16,
        image_bayerpat=bayerpat,
        target_adu=10000,
        detected_camera_name=detected_cam,
    )
    return i_ref


def test_notify_asi676mc_issue(ip_fixture):
    ip = ip_fixture
    ip._miscDb = MagicMock()

    # validation_failed
    ip._notify_asi676mc_issue('validation_failed', reason='bad ratio')
    ip._miscDb.addNotification.assert_called_once()
    assert ip._miscDb.addNotification.call_args[0][0] == NotificationCategory.CAMERA
    assert ip._miscDb.addNotification.call_args[0][1] == 'Asi676mcRepairFailed'

    # skipped
    ip._miscDb.reset_mock()
    ip._notify_asi676mc_issue('skipped', reason='unsupported binning')
    ip._miscDb.addNotification.assert_called_once()
    assert ip._miscDb.addNotification.call_args[0][1] == 'Asi676mcRepairSkipped'

    # skipped without reason
    ip._miscDb.reset_mock()
    ip._notify_asi676mc_issue('skipped', reason=None)
    ip._miscDb.addNotification.assert_called_once()

    # other status does nothing
    ip._miscDb.reset_mock()
    ip._notify_asi676mc_issue('normal')
    ip._miscDb.addNotification.assert_not_called()

    # exception handling
    ip._miscDb.addNotification.side_effect = RuntimeError('db failed')
    ip._notify_asi676mc_issue('skipped', reason='err')  # should not raise


def test_set_asi676mc_repair_result(ip_fixture):
    ip = ip_fixture
    ip._miscDb = MagicMock()
    i_ref = make_dummy_image_data(ip)

    res = ip._set_asi676mc_repair_result(i_ref, 'repaired')
    assert res is True
    assert i_ref.asi676mc_repair_result['status'] == 'repaired'

    res_skip = ip._set_asi676mc_repair_result(i_ref, 'skipped', reason='test')
    assert res_skip is False
    assert i_ref.asi676mc_repair_result['status'] == 'skipped'


def test_correct_asi676mc_frame_branches(ip_fixture):
    ip = ip_fixture
    ip._miscDb = MagicMock()

    # 1. Config disabled
    ip.config['IMAGE_ASI676MC_REPAIR'] = {'ENABLE': False}
    i_ref = make_dummy_image_data(ip)
    assert ip.correct_asi676mc_frame(i_ref) is False

    # 2. Camera name mismatch
    ip.config['IMAGE_ASI676MC_REPAIR'] = {'ENABLE': True}
    i_ref_other_cam = make_dummy_image_data(ip, detected_cam="Canon EOS")
    assert ip.correct_asi676mc_frame(i_ref_other_cam) is False

    # 3. Binning != 1
    i_ref_bin2 = make_dummy_image_data(ip, binning=2)
    assert ip.correct_asi676mc_frame(i_ref_bin2) is False
    assert i_ref_bin2.asi676mc_repair_result['status'] == 'skipped'

    # 4. Bayer pattern != RGGB
    i_ref_bggr = make_dummy_image_data(ip, bayerpat='BGGR')
    assert ip.correct_asi676mc_frame(i_ref_bggr) is False
    assert i_ref_bggr.asi676mc_repair_result['status'] == 'skipped'

    # 5. Invalid Bayer offsets metadata (inf, non-integer, ValueError)
    i_ref_inv_offset = make_dummy_image_data(ip)
    with patch.object(i_ref_inv_offset.hdulist[0].header, 'get', return_value=float('inf')):
        assert ip.correct_asi676mc_frame(i_ref_inv_offset) is False
        assert i_ref_inv_offset.asi676mc_repair_result['status'] == 'skipped'

    i_ref_inv_offset2 = make_dummy_image_data(ip)
    with patch.object(i_ref_inv_offset2.hdulist[0].header, 'get', return_value=1.5):
        assert ip.correct_asi676mc_frame(i_ref_inv_offset2) is False
        assert i_ref_inv_offset2.asi676mc_repair_result['status'] == 'skipped'

    i_ref_inv_offset3 = make_dummy_image_data(ip)
    i_ref_inv_offset3.hdulist[0].header['XBAYROFF'] = 'invalid'
    assert ip.correct_asi676mc_frame(i_ref_inv_offset3) is False




    # 5b. Non-zero Bayer offsets
    i_ref_nonzero_offset = make_dummy_image_data(ip, x_off=1, y_off=0)
    assert ip.correct_asi676mc_frame(i_ref_nonzero_offset) is False
    assert i_ref_nonzero_offset.asi676mc_repair_result['status'] == 'skipped'

    # 6. EXCLUDE_ONLY mode = True
    ip.config['IMAGE_ASI676MC_REPAIR'] = {'ENABLE': True, 'EXCLUDE_ONLY': True}

    # 6a. detect_frame raises TypeError / ValueError
    with patch('indi_allsky.asi676mc.detect_frame', side_effect=ValueError('corrupt frame')):
        i_ref = make_dummy_image_data(ip)
        assert ip.correct_asi676mc_frame(i_ref) is False
        assert i_ref.asi676mc_repair_result['status'] == 'skipped'

    # 6b. detect_frame is_bad = True
    fake_sig = {'purple_ratio': 1.8, 'red_side_ratio': 1.5, 'blue_side_ratio': 1.6}
    fake_timing = {'detection_s': 0.005, 'total_s': 0.006}
    with patch('indi_allsky.asi676mc.detect_frame', return_value={'is_bad': True, 'signature': fake_sig, 'timing': fake_timing}):
        i_ref = make_dummy_image_data(ip)
        assert ip.correct_asi676mc_frame(i_ref) is False
        assert i_ref.asi676mc_repair_result['status'] == 'excluded'

    # 6c. detect_frame is_bad = False (with LOG_EVERY_FRAME True and False)
    ip.config['IMAGE_ASI676MC_REPAIR']['LOG_EVERY_FRAME'] = True
    with patch('indi_allsky.asi676mc.detect_frame', return_value={'is_bad': False, 'signature': fake_sig, 'timing': fake_timing}):
        i_ref = make_dummy_image_data(ip)
        assert ip.correct_asi676mc_frame(i_ref) is False
        assert i_ref.asi676mc_repair_result['status'] == 'normal'

    # 7. Repair mode: EXCLUDE_ONLY = False
    ip.config['IMAGE_ASI676MC_REPAIR'] = {'ENABLE': True, 'EXCLUDE_ONLY': False}

    # 7a. repair_if_needed raises ValueError
    with patch('indi_allsky.asi676mc.repair_if_needed', side_effect=ValueError('repair failed')):
        i_ref = make_dummy_image_data(ip)
        assert ip.correct_asi676mc_frame(i_ref) is False
        assert i_ref.asi676mc_repair_result['status'] == 'skipped'

    # 7b. repair_if_needed with validation_failed = True
    fake_repair_val_failed = {
        'repaired': False,
        'validation_failed': True,
        'validation_reason': 'still purple',
        'signature_before': fake_sig,
        'signature_after': fake_sig,
        'timing': {'detection_s': 0.005, 'repair_s': 0.01, 'total_s': 0.015},
    }
    with patch('indi_allsky.asi676mc.repair_if_needed', return_value=fake_repair_val_failed):
        i_ref = make_dummy_image_data(ip)
        assert ip.correct_asi676mc_frame(i_ref) is False
        assert i_ref.asi676mc_repair_result['status'] == 'validation_failed'

    # 7c. repair_if_needed with repaired = False (normal)
    fake_repair_not_needed = {
        'repaired': False,
        'validation_failed': False,
        'signature_before': fake_sig,
        'timing': {'detection_s': 0.005, 'total_s': 0.006},
    }
    with patch('indi_allsky.asi676mc.repair_if_needed', return_value=fake_repair_not_needed):
        i_ref = make_dummy_image_data(ip)
        assert ip.correct_asi676mc_frame(i_ref) is False
        assert i_ref.asi676mc_repair_result['status'] == 'normal'

    # 7d. repair_if_needed with repaired = True
    fake_repaired = {
        'repaired': True,
        'validation_failed': False,
        'signature_before': fake_sig,
        'signature_after': fake_sig,
        'timing': {'detection_s': 0.005, 'repair_s': 0.01, 'total_s': 0.015},
    }
    with patch('indi_allsky.asi676mc.repair_if_needed', return_value=fake_repaired):
        i_ref = make_dummy_image_data(ip)
        assert ip.correct_asi676mc_frame(i_ref) is True
        assert i_ref.asi676mc_repair_result['status'] == 'repaired'
        assert i_ref.hdulist[0].header.get('ASI676FX') is not None
