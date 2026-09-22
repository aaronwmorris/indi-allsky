import ctypes
import os
import io
import json
import time
from datetime import datetime, timezone, timedelta
from multiprocessing import Array, Queue
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pytest
from astropy.io import fits

from indi_allsky import constants
from indi_allsky.image import ImageWorker
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbFitsImageTable,
)
from indi_allsky.flask import db


@pytest.fixture
def image_worker(app, base_config, tmp_path):
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        if not cam:
            cam = IndiAllSkyDbCameraTable(
                name='ZWO ASI676MC',
                uuid='cam-extra-coverage',
                latitude=51.5074,  # Northern hemisphere for lat_ref == 'N' (line 536)
                longitude=-0.1278,
                elevation=50,
                nightSunAlt=-6.0,
                lensFocalLength=2.5,
                lensFocalRatio=1.4,
                lensImageCircle=1000,
                lensName='Test Lens',
                width=1920,
                height=1080,
                pixelSize=2.9,
                cfa=constants.CFA_RGGB,
                owner='Admin',
            )
            db.session.add(cam)
            db.session.commit()
        else:
            cam.name = 'ZWO ASI676MC'
            cam.latitude = 51.5074
            cam.longitude = -0.1278
            db.session.commit()

        config = dict(base_config)
        config['VARLIB_FOLDER'] = str(tmp_path / 'varlib')
        config['IMAGE_DIR'] = str(tmp_path / 'images')
        config['IMAGE_FOLDER'] = str(tmp_path / 'images')
        config['IMAGE_SAVE_FITS'] = False
        config['TEMP_DISPLAY'] = 'f'
        config['DAYTIME_CAPTURE_SAVE'] = True
        Path(config['VARLIB_FOLDER']).mkdir(parents=True, exist_ok=True)
        Path(config['IMAGE_DIR']).mkdir(parents=True, exist_ok=True)

        error_q = Queue()
        image_q = Queue()
        upload_q = Queue()

        position_av = Array('d', [51.5074, -0.1278, 50.0, 0.0, 0.0])
        exposure_av = Array(ctypes.c_int32, [1000000, 1000000, 0, 1000, 100, 30000000, 5000000])
        gain_av = Array(ctypes.c_int32, [100000, 100000, 0, 0, 100000, 100000, 400000, 50000, 200000, 100000])
        binning_av = Array('i', [1, 1, 1, 2, 1, 1])
        sensors_temp_av = Array('f', [25.0] * 110)
        sensors_user_av = Array('f', [10.0] * 110)
        night_av = Array('i', [1, 0])
        astro_av = Array('f', [0.0] * 10)

        worker = ImageWorker(
            idx=0,
            config=config,
            error_q=error_q,
            image_q=image_q,
            upload_q=upload_q,
            position_av=position_av,
            exposure_av=exposure_av,
            gain_av=gain_av,
            binning_av=binning_av,
            sensors_temp_av=sensors_temp_av,
            sensors_user_av=sensors_user_av,
            night_av=night_av,
            astro_av=astro_av,
        )

        return worker


def test_process_image_libcamera_black_level_and_mask_base(image_worker, tmp_path, app):
    """Test lines 445 (libcamera black level fallback), 536 (lat_ref == 'N'), 645-646 (mask base generation), and 1033-1034 (skip /snap)."""
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        fits_file = tmp_path / 'test_capture.fits'
        hdu = fits.PrimaryHDU(np.zeros((64, 64), dtype=np.uint16))
        hdu.writeto(str(fits_file))

        image_worker.generate_mask_base = True
        image_worker.exposure_o.target_adu_found = True

        real_add = image_worker.image_processor.add

        def mock_add(*args, **kwargs):
            i_ref = real_add(*args, **kwargs)
            i_ref.libcamera_black_level = 64
            return i_ref

        dummy_img = Path(image_worker.image_dir) / 'out.jpg'
        dummy_latest = Path(image_worker.image_dir) / 'latest.jpg'
        dummy_img.touch()
        dummy_latest.touch()

        mock_snap = MagicMock()
        mock_snap.mountpoint = '/snap'
        mock_root = MagicMock()
        mock_root.mountpoint = '/'

        with patch.object(image_worker.image_processor, 'add', side_effect=mock_add), \
             patch.object(image_worker, 'write_mask_base_img') as mock_mask, \
             patch.object(image_worker, 'write_img', return_value=(dummy_img, dummy_latest)), \
             patch.object(image_worker.image_processor, 'calibrate') as mock_calibrate, \
             patch('psutil.disk_partitions', return_value=[mock_snap, mock_root]), \
             patch('psutil.disk_usage', return_value=MagicMock(percent=35.0)):

            i_dict = {
                'filename': str(fits_file),
                'exposure': 1.0,
                'gain': 100.0,
                'binning': 1,
                'exp_time': time.time(),
                'exp_elapsed': 1.0,
                'camera_id': cam.id,
                # No libcamera_black_level in i_dict so it falls back to i_ref.libcamera_black_level
            }

            image_worker.processImage(i_dict)

            assert mock_calibrate.call_args[1]['libcamera_black_level'] is True
            assert image_worker.generate_mask_base is False
            mock_mask.assert_called_once()


def test_write_img_basic(image_worker, app):
    """Test write_img execution with mock image reference and camera."""
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        mock_i_ref = MagicMock()
        mock_i_ref.camera_id = cam.id
        mock_i_ref.exp_date = datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
        mock_i_ref.day_date = datetime(2026, 6, 21).date()
        mock_i_ref.exposure = 2.5
        mock_i_ref.gain = 150.0
        mock_i_ref.binning = 1
        mock_i_ref.image_bayerpat = 'RGGB'
        mock_i_ref.target_adu = 20000
        mock_i_ref.adu = 20500
        mock_i_ref.focus_metric = 100.0
        mock_i_ref.stars = 42

        # 3-channel uint8 test image
        img_data = np.zeros((100, 100, 3), dtype=np.uint8)

        latest_path, img_path = image_worker.write_img(img_data, mock_i_ref, cam)
        assert latest_path is not None
        assert img_path is not None


def test_asi676mc_diagnostics_coverage_paths(image_worker, tmp_path, app):
    """Test lines 1379-1380, 1391, 1452-1453, 1462-1469, 1488-1489, 1538-1539, 1657."""
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()

        # Enable repair and diagnostic fits
        image_worker.config['IMAGE_ASI676MC_REPAIR'] = {
            'ENABLE': True,
            'SAVE_DIAGNOSTIC_FITS': True,
            'SAVE_PRECEDING_FITS': False,  # Triggers line 1379-1380
        }

        # 1. save_preceding is False (lines 1379-1380) and discarded pending state (line 1391)
        image_worker.asi676mc_diagnostic_previous[cam.id] = {'old': 1}
        # Incompatible pending state
        image_worker.asi676mc_diagnostic_pending[cam.id] = {
            'capture_id': 'pending-123',
            'context': {'image_shape': (999, 999)},
        }

        mock_i = MagicMock()
        mock_i.camera_id = cam.id
        mock_i.camera_uuid = cam.uuid
        mock_i.detected_camera_name = 'ZWO ASI676MC'
        mock_i.exp_date = datetime(2026, 1, 1, 1, 0, 0, tzinfo=timezone.utc)
        mock_i.day_date = datetime(2026, 1, 1).date()
        mock_i.exposure = 1.0
        mock_i.gain = 100.0
        mock_i.binning = 1
        mock_i.image_bayerpat = 'RGGB'
        mock_i.hdulist = [fits.PrimaryHDU(np.zeros((32, 32), dtype=np.uint8))]
        mock_i.asi676mc_repair_result = None

        fits_file = tmp_path / 'sample.fits'
        fits_file.touch()

        image_worker.capture_asi676mc_diagnostic_fits(fits_file, mock_i, cam)
        assert cam.id not in image_worker.asi676mc_diagnostic_previous

        # 2. Lines 1452-1453: _attach_asi676mc_diagnostic_to_image raises Exception
        image_worker.config['IMAGE_ASI676MC_REPAIR']['SAVE_PRECEDING_FITS'] = True
        prev_ctx = image_worker._asi676mc_diagnostic_frame_context(mock_i)
        prev_ctx.update({
            'source_name': 'prev.fits',
            'fits_ext': 'fits',
            'diagnostic_fits_id': None,
            'fits_bytes': b'FAKEFITS',
            'image_id': 12345,
        })
        image_worker.asi676mc_diagnostic_previous[cam.id] = prev_ctx

        # Purple frame trigger
        mock_i.asi676mc_repair_result = {'status': 'validation_failed'}
        mock_preceding_entry = MagicMock()
        mock_preceding_entry.filename = 'preceding.fits'

        with patch.object(image_worker, '_archive_asi676mc_diagnostic_fits', return_value=mock_preceding_entry), \
             patch.object(image_worker, '_attach_asi676mc_diagnostic_to_image', side_effect=RuntimeError('Attach error')):
            # Should handle exception at lines 1452-1453 without crashing
            image_worker.capture_asi676mc_diagnostic_fits(fits_file, mock_i, cam)

        # 3. Lines 1462-1463: exception saving cached preceding FITS
        image_worker.asi676mc_diagnostic_previous[cam.id] = dict(prev_ctx)
        with patch.object(image_worker, '_archive_asi676mc_diagnostic_fits', side_effect=RuntimeError('Archive error')):
            image_worker.capture_asi676mc_diagnostic_fits(fits_file, mock_i, cam)

        # 4. Line 1469: Incompatible preceding context discard
        image_worker.asi676mc_diagnostic_previous[cam.id] = dict(prev_ctx)
        with patch('indi_allsky.asi676mc.diagnostic_reference_compatible', return_value=False):
            image_worker.capture_asi676mc_diagnostic_fits(fits_file, mock_i, cam)

        # 5. Lines 1488-1489: exception saving current diagnostic FITS
        mock_i.asi676mc_repair_result = {'status': 'validation_failed'}
        with patch.object(image_worker, '_archive_asi676mc_diagnostic_fits', side_effect=OSError('Disk full')):
            image_worker.capture_asi676mc_diagnostic_fits(fits_file, mock_i, cam)

        # 6. Lines 1538-1539: exception caching preceding-frame candidate
        mock_i.asi676mc_repair_result = {'status': 'normal'}
        with patch.object(image_worker, '_cache_asi676mc_diagnostic_frame', side_effect=OSError('Read error')):
            image_worker.capture_asi676mc_diagnostic_fits(fits_file, mock_i, cam)

        # 7. Line 1657: _attach_asi676mc_diagnostic_to_image with non-existent image_id
        non_existent_ctx = {'image_id': 9999999}
        image_worker._attach_asi676mc_diagnostic_to_image(non_existent_ctx, MagicMock(), {'role': 'preceding'})


def test_archive_asi676mc_diagnostic_fits_exceptions(image_worker, tmp_path, app):
    """Test lines 1728-1733 and 1767-1776: exception paths in _archive_asi676mc_diagnostic_fits."""
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        frame_ctx = {
            'camera_id': cam.id,
            'camera_uuid': cam.uuid,
            'exp_date': datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            'day_date': datetime(2026, 1, 1).date(),
            'exposure': 1.0,
            'gain': 100.0,
            'binning': 1,
            'night': True,
            'image_shape': (32, 32),
            'fits_ext': 'fits',
            'fits_bytes': b'SAMPLEFITSBYTES',
            'asi676mc_signature': {'sig': 1},
        }

        source_p = tmp_path / 'source.fits'
        source_p.touch()

        # 1. Lines 1728-1733: copy raises exception, file unlinked, re-raises
        with patch('shutil.copy2', side_effect=IOError('Copy failed')):
            with pytest.raises(IOError):
                image_worker._archive_asi676mc_diagnostic_fits(
                    source_p,
                    MagicMock(camera_id=cam.id, camera_uuid=cam.uuid, exp_date=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc), day_date=datetime(2026, 1, 1).date(), exposure=1.0, gain=100.0, binning=1, hdulist=[fits.PrimaryHDU(np.zeros((32, 32), dtype=np.uint8))], asi676mc_repair_result=None),
                    cam,
                    [{'role': 'bad', 'capture_id': '1234567890'}],
                    cached_context=None,
                )

        # 2. Lines 1767-1776: addFitsImage raises exception, rollback and unlink
        with patch.object(image_worker._miscDb, 'addFitsImage', side_effect=RuntimeError('DB Error')), \
             patch.object(Path, 'unlink', side_effect=OSError('Cannot delete')):
            with pytest.raises(RuntimeError):
                image_worker._archive_asi676mc_diagnostic_fits(
                    None,
                    None,
                    cam,
                    [{'role': 'bad', 'capture_id': '1234567890'}],
                    cached_context=frame_ctx,
                )


def test_write_fit_metadata_and_file_exists(image_worker, tmp_path, app):
    """Test lines 1882, 1887, 1900, and 1906-1908 in write_fit."""
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()

        mock_i = MagicMock()
        mock_i.camera_id = cam.id
        mock_i.camera_uuid = cam.uuid
        mock_i.exp_date = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        mock_i.day_date = datetime(2026, 1, 1).date()
        mock_i.exposure = 1.0
        mock_i.gain = 100.0
        mock_i.binning = 1
        mock_i.image_bayerpat = 'RGGB'
        mock_i.detected_camera_name = 'ZWO ASI676MC'
        mock_i.stars = []
        mock_i.lines = []
        mock_i.sqm_value = 21.0
        mock_i.kpindex = 1.0
        mock_i.ovation_max = 0
        mock_i.smoke_rating = 0
        mock_i.aurora_mag_bt = 0.0
        mock_i.aurora_mag_gsm_bz = 0.0
        mock_i.aurora_plasma_density = 0.0
        mock_i.aurora_plasma_speed = 0.0
        mock_i.aurora_plasma_temp = 0.0
        mock_i.aurora_n_hemi_gw = 0.0
        mock_i.aurora_s_hemi_gw = 0.0
        mock_i.asi676mc_repair_result = {
            'status': 'repaired',
            'signature_before': {
                'purple_ratio': 1.05,
                'red_side_ratio': 1.10,
                'blue_side_ratio': 1.01,
            },
        }
        mock_i.hdulist = fits.HDUList([fits.PrimaryHDU(np.zeros((16, 16), dtype=np.uint16))])

        image_worker.image_processor.update_astrometric_data(datetime.now())
        image_worker.night_av[constants.NIGHT_NIGHT] = 1
        image_worker.config['DAYTIME_CAPTURE_SAVE'] = True
        image_worker.next_save_fits_time = 0

        # Target directory
        fits_folder = image_worker._getImageFolder(mock_i.exp_date, mock_i.day_date, cam, 'fits')
        fits_folder.mkdir(parents=True, exist_ok=True)
        dest_filename = fits_folder.joinpath(image_worker.filename_t.format(
            mock_i.camera_id,
            mock_i.exp_date.strftime('%Y%m%d_%H%M%S'),
            'fit',
        ))

        # Pre-create dest file to trigger lines 1906-1908
        dest_filename.touch()

        with patch.object(image_worker._miscDb, 'addFitsImage') as mock_add_fits:
            # When file already exists, it should log error and return early
            image_worker.write_fit(mock_i, cam)
            mock_add_fits.assert_called_once()
            fits_meta = mock_add_fits.call_args[0][2]
            assert 'asi676mc_signature' in fits_meta['data']
            assert fits_meta['data']['asi676mc_fits_repair_status'] == 'repaired'

        # Remove pre-created file, patch _getImageFolder to return uncreated folder to trigger line 1900
        dest_filename.unlink()
        uncreated_folder = Path(image_worker.image_dir) / 'fits_uncreated' / 'subfolder'
        assert not uncreated_folder.exists()

        image_worker.next_save_fits_time = 0
        with patch.object(image_worker, '_getImageFolder', return_value=uncreated_folder), \
             patch.object(image_worker._miscDb, 'addFitsImage'), \
             patch('shutil.copy2'), patch('pathlib.Path.chmod'):
            image_worker.write_fit(mock_i, cam)
            assert uncreated_folder.exists()


def test_image_save_hooks_temp_display_and_wait_errors(image_worker, tmp_path):
    """Test lines 2792, 2877, 2951-2954, 2973-2979, 2993-2994, 3044-3046."""
    script_p = tmp_path / 'hook.sh'
    script_p.write_text('#!/bin/sh\nexit 0\n')
    script_p.chmod(0o755)

    image_worker.config['IMAGE_SAVE_HOOK_PRE'] = str(script_p)
    image_worker.config['IMAGE_SAVE_HOOK_POST'] = str(script_p)
    image_worker.config['TEMP_DISPLAY'] = 'f'
    image_worker.sensors_temp_av[0] = 20.0
    image_worker.image_processor.update_astrometric_data(datetime.now())

    # 1. Line 2792: Fahrenheit in pre-hook env
    with patch('subprocess.Popen') as mock_popen:
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc
        image_worker.start_image_save_pre_hook(1.0, 100.0, 1)
        mock_popen.assert_called_once()
        env_passed = mock_popen.call_args[1]['env']
        # 20 C = 68 F
        assert 'SENSOR_TEMP_0' in env_passed
        assert abs(float(env_passed['SENSOR_TEMP_0']) - 68.0) < 0.1

    # 2. Line 2877: Fahrenheit in post-hook env
    with patch('subprocess.Popen') as mock_popen:
        image_worker.start_image_save_post_hook(Path('dummy.jpg'), 1.0, 100.0, 1)
        mock_popen.assert_called_once()
        env_passed = mock_popen.call_args[1]['env']
        assert abs(float(env_passed['SENSOR_TEMP_0']) - 68.0) < 0.1

    # 3. Lines 2951-2954: wait_image_save_pre_hook timeout unlink FileNotFoundError & PermissionError
    mock_proc = MagicMock()
    image_worker.image_save_hook_process = mock_proc
    image_worker.image_save_hook_process_start = time.time() - 100  # expired
    image_worker.config['IMAGE_SAVE_HOOK_TIMEOUT'] = 1
    image_worker.pre_hook_datajson_name_p = tmp_path / 'nonexistent_data.json'

    with patch.object(image_worker, '_processRunning', return_value=True):
        # FileNotFoundError on unlink (lines 2951-2952)
        res = image_worker.wait_image_save_pre_hook()
        assert res == {}

    mock_proc = MagicMock()
    image_worker.image_save_hook_process = mock_proc
    image_worker.image_save_hook_process_start = time.time() - 100
    with patch.object(image_worker, '_processRunning', return_value=True), \
         patch.object(Path, 'unlink', side_effect=PermissionError('Denied')):
        # PermissionError on unlink (lines 2953-2954)
        res = image_worker.wait_image_save_pre_hook()
        assert res == {}

    # 4. Lines 2973-2979: hook_rc == 0, reading json raises PermissionError and FileNotFoundError
    mock_proc = MagicMock()
    image_worker.image_save_hook_process = mock_proc
    image_worker.image_save_hook_process_start = time.time()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b'', b'')

    with patch.object(image_worker, '_processRunning', return_value=False), \
         patch('io.open', side_effect=PermissionError('No read')):
        res = image_worker.wait_image_save_pre_hook()
        assert res['custom_1'] == ''

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b'', b'')
    image_worker.image_save_hook_process = mock_proc
    with patch.object(image_worker, '_processRunning', return_value=False), \
         patch('io.open', side_effect=FileNotFoundError('No file')):
        res = image_worker.wait_image_save_pre_hook()
        assert res['custom_1'] == ''

    # 5. Lines 2993-2994: hook_rc != 0, unlink raises PermissionError
    mock_proc = MagicMock()
    image_worker.image_save_hook_process = mock_proc
    mock_proc.returncode = 1
    mock_proc.communicate.return_value = (b'Error message\n', b'')
    with patch.object(image_worker, '_processRunning', return_value=False), \
         patch.object(Path, 'unlink', side_effect=PermissionError('Cannot delete')):
        res = image_worker.wait_image_save_pre_hook()
        assert res['custom_1'] == ''

    # 6. Lines 3044-3046: wait_image_save_post_hook process keeps running -> kill and poll
    mock_proc_kill = MagicMock()
    image_worker.image_save_hook_process = mock_proc_kill
    image_worker.image_save_hook_process_start = time.time() - 100
    image_worker.config['IMAGE_SAVE_HOOK_TIMEOUT'] = 1

    # _processRunning returns True indefinitely
    with patch.object(image_worker, '_processRunning', return_value=True):
        image_worker.wait_image_save_post_hook()
        mock_proc_kill.kill.assert_called_once()
        mock_proc_kill.poll.assert_called_once()
