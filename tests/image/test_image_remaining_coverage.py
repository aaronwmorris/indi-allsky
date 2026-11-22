import ctypes
import os
import io
import json
import time
from datetime import datetime, timezone, timedelta
from multiprocessing import Array, Queue
from pathlib import Path
from unittest.mock import MagicMock, patch
import cv2
import numpy as np
import pytest
from astropy.io import fits
import queue

from indi_allsky import constants
from indi_allsky.image import ImageWorker
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbFitsImageTable,
    IndiAllSkyDbPanoramaImageTable,
    IndiAllSkyDbRawImageTable,
)
from indi_allsky.flask import db
from indi_allsky.exceptions import BadImage


@pytest.fixture
def worker(app, base_config, tmp_path):
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        if not cam:
            cam = IndiAllSkyDbCameraTable(
                name='Coverage Cam',
                uuid='cov-cam-uuid',
                latitude=-34.9285,
                longitude=-138.6007,
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

        config = dict(base_config)
        config['VARLIB_FOLDER'] = str(tmp_path / 'varlib')
        config['IMAGE_DIR'] = str(tmp_path / 'images')
        config['IMAGE_FOLDER'] = str(tmp_path / 'images')
        config['IMAGE_EXPORT_FOLDER'] = str(tmp_path / 'export')
        config['TEMP_DISPLAY'] = 'k'
        Path(config['VARLIB_FOLDER']).mkdir(parents=True, exist_ok=True)
        Path(config['IMAGE_DIR']).mkdir(parents=True, exist_ok=True)
        Path(config['IMAGE_EXPORT_FOLDER']).mkdir(parents=True, exist_ok=True)

        w = ImageWorker(
            idx=0,
            config=config,
            error_q=Queue(),
            image_q=Queue(),
            upload_q=Queue(),
            position_av=Array('d', [-34.9285, -138.6007, 50.0, 0.0, 0.0]),
            exposure_av=Array(ctypes.c_int32, [1000000, 1000000, 0, 1000, 100, 30000000, 5000000]),
            gain_av=Array(ctypes.c_int32, [100000, 100000, 0, 0, 100000, 100000, 400000, 50000, 200000, 100000]),
            binning_av=Array('i', [1, 1, 1, 2, 1, 1]),
            sensors_temp_av=Array('f', [20.0] * 110),
            sensors_user_av=Array('f', [10.0] * 110),
            night_av=Array('i', [1, 0]),
            astro_av=Array('f', [0.0] * 10),
        )
        return w


def test_worker_run_and_libcamera_raw_interface(worker, tmp_path, app):
    with app.app_context():
        # Test worker.run loop processing item and stop (lines 267-268)
        img_dict = {
            'filename': str(tmp_path / 'nonexistent.fits'),
            'exposure': 1.0,
            'gain': 100.0,
            'binning': 1,
            'exp_time': time.time(),
            'exp_elapsed': 1.0,
            'camera_id': 1,
        }
        worker.image_q.put(img_dict)
        worker.image_q.put({'stop': True})
        worker.run()

        # Test CAMERA_INTERFACE libcamera_ with .dng and non-.dng (lines 320-325, 329)
        worker.config['CAMERA_INTERFACE'] = 'libcamera_pi'
        i_dict_dng = dict(img_dict)
        i_dict_dng['filename'] = str(tmp_path / 'frame.dng')
        i_dict_dng['filename_t'] = 'custom_title'
        worker.processImage(i_dict_dng)
        assert worker.libcamera_raw is True
        assert worker.filename_t == 'custom_title'

        i_dict_fits = dict(img_dict)
        i_dict_fits['filename'] = str(tmp_path / 'frame.fits')
        worker.processImage(i_dict_fits)
        assert worker.libcamera_raw is False


def test_process_image_adsb_diagnostic_and_transforms(worker, tmp_path, app):
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        test_fits = tmp_path / 'capture.fits'
        # 3-channel FITS (3, 32, 32)
        hdu = fits.PrimaryHDU(np.full((3, 32, 32), 200, dtype=np.uint8))
        hdu.header['EXPTIME'] = 1.0
        hdu.header['GAIN'] = 100.0
        hdu.writeto(str(test_fits))

        worker.config['ADSB'] = {'ENABLE': True}
        worker.config['IMAGE_EXPORT_RAW'] = 'jpg'
        worker.config['CONTRAST_ENHANCE_16BIT'] = True
        worker.config['DAYTIME_CONTRAST_ENHANCE'] = True
        worker.config['FISH2PANO'] = {'ENABLE': True, 'MODULUS': 1, 'ENABLE_CARDINAL_DIRS': True}
        worker.night_av[constants.NIGHT_NIGHT] = 0  # day

        # libcamera raw settings (lines 564-573)
        worker.libcamera_raw = True

        # Diagnostic fits failure (lines 417-418)
        with patch.object(worker, 'capture_asi676mc_diagnostic_fits', side_effect=Exception('Diagnostic error')), \
             patch('indi_allsky.image.AdsbAircraftHttpWorker') as mock_adsb_worker_cls:
            mock_adsb_instance = MagicMock()
            mock_adsb_worker_cls.return_value = mock_adsb_instance

            # Also mock fish2pano methods
            with patch.object(worker.image_processor, 'fish2pano', return_value=np.zeros((30, 60, 3), dtype=np.uint8)), \
                 patch.object(worker.image_processor, 'fish2pano_cardinal_dirs_label', return_value=np.zeros((30, 60, 3), dtype=np.uint8)), \
                 patch.object(worker, 'write_panorama_img'):

                # Mock disk_partitions, disk_usage, sensors_temperatures for MQTT block (lines 1030-1069)
                mock_part_snap = MagicMock(mountpoint='/snap/core')
                mock_part_root = MagicMock(mountpoint='/')
                mock_part_data = MagicMock(mountpoint='/data')
                temp_list = [MagicMock(current=40.0 + i, label=f'T{i}') for i in range(55)]

                with patch('psutil.disk_partitions', return_value=[mock_part_snap, mock_part_root, mock_part_data]), \
                     patch('psutil.disk_usage', side_effect=[PermissionError('Denied'), MagicMock(percent=50.0)]), \
                     patch('psutil.sensors_temperatures', return_value={'cpu': temp_list}):

                    i_dict = {
                        'filename': str(test_fits),
                        'exposure': 1.0,
                        'gain': 100.0,
                        'binning': 1,
                        'exp_time': time.time(),
                        'exp_elapsed': 1.0,
                        'camera_id': cam.id,
                        'libcamera_black_level': 32,
                        'libcamera_awb_gains': [1.5, 2.0],
                        'libcamera_ccm': [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                    }
                    worker.processImage(i_dict)


def test_process_image_exposure_exclusion_and_metadata(worker, tmp_path, app):
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        test_fits = tmp_path / 'capture2.fits'
        hdu = fits.PrimaryHDU(np.full((32, 32), 200, dtype=np.uint8))
        hdu.header['EXPTIME'] = 1.0
        hdu.header['GAIN'] = 100.0
        hdu.writeto(str(test_fits))

        worker.generate_mask_base = True
        worker.exposure_o.target_adu_found = True

        worker.config['CONTRAST_ENHANCE_16BIT'] = False
        worker.config['NIGHT_CONTRAST_ENHANCE'] = True
        worker.night_av[constants.NIGHT_NIGHT] = 1

        def mock_correct_frame(i_ref):
            i_ref.asi676mc_repair_result = {
                'status': 'validation_failed',
                'diagnostic_fits': {'fits_id': 123},
            }

        worker.image_processor.update_astrometric_data(datetime.now())

        latest_file = Path(worker.image_dir) / 'latest.jpg'
        latest_file.touch()
        img_file = Path(worker.image_dir) / 'img.jpg'
        img_file.touch()

        with patch.object(worker.image_processor, 'correct_asi676mc_frame', side_effect=mock_correct_frame), \
             patch.object(worker, 'write_mask_base_img'), \
             patch.object(worker, 'write_img', return_value=(img_file, latest_file)):

            worker.exposure_o.hist_adu = [100.0, 120.0]
            worker.adsb_aircraft_list = [{'hex': 'abc123'}]

            i_dict = {
                'filename': str(test_fits),
                'exposure': 1.0,
                'gain': 100.0,
                'binning': 1,
                'exp_time': time.time(),
                'exp_elapsed': 1.0,
                'camera_id': cam.id,
                'libcamera_black_level': 16,
            }
            worker.processImage(i_dict)


def test_asi676mc_diagnostic_caching_and_database_roles(worker, tmp_path, app):
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()

        # 1. save_preceding False pops previous context (lines 1379-1380)
        worker.config['ASI676MC_PURPLE_FRAME_SAVE_PRECEDING'] = False
        worker.asi676mc_diagnostic_previous[cam.id] = {'mock': 1}
        mock_i = MagicMock()
        mock_i.camera_id = cam.id
        mock_i.camera_uuid = cam.uuid
        mock_i.day_date = datetime.now().date()
        mock_i.exposure = 1.0
        mock_i.gain = 100.0
        mock_i.binning = 1
        mock_i.image_bayerpat = 'RGGB'
        mock_i.hdulist = [fits.PrimaryHDU(np.zeros((32, 32), dtype=np.uint8))]
        mock_i.asi676mc_repair_result = None
        worker.capture_asi676mc_diagnostic_fits(tmp_path / 'dummy.fits', mock_i, cam)
        assert cam.id not in worker.asi676mc_diagnostic_previous

        # 2. _set_asi676mc_cached_image_id matching context (line 1615)
        now_dt = datetime.now()
        mock_i.exp_date = now_dt
        worker.asi676mc_diagnostic_previous[cam.id] = {'exp_date': now_dt}
        worker._set_asi676mc_cached_image_id(mock_i, 999)
        assert worker.asi676mc_diagnostic_previous[cam.id]['image_id'] == 999

        # 3. _add_asi676mc_diagnostic_role exception rollback (lines 1637-1639)
        fits_metadata = {
            'createDate': datetime.now(),
            'dayDate': '20260101',
            'exposure': 1.0,
            'gain': 100.0,
            'binmode': 1,
            'night': True,
            'height': 32,
            'width': 32,
            'fileSize': 1000,
        }
        fits_entry = worker._miscDb.addFitsImage('test_role.fits', cam.id, fits_metadata)

        with patch.object(db.session, 'commit', side_effect=Exception('Commit fail')):
            with pytest.raises(Exception, match='Commit fail'):
                worker._add_asi676mc_diagnostic_role(fits_entry.id, {'role': 'preceding', 'capture_id': 'cid'})

        # 4. _attach_asi676mc_diagnostic_to_image (lines 1653-1672)
        img_entry = IndiAllSkyDbImageTable(
            camera_id=cam.id,
            filename='rendered_test.jpg',
            createDate=datetime.now(),
            dayDate=datetime.now().date(),
            exposure=1.0,
            gain=100.0,
            binmode=1,
            night=True,
            adu=100.0,
            data={},
        )
        db.session.add(img_entry)
        db.session.commit()

        cached_ctx = {'image_id': img_entry.id}
        worker._attach_asi676mc_diagnostic_to_image(cached_ctx, fits_entry, {'role': 'preceding', 'capture_id': 'cid'})

        # Test rollback on exception in _attach_asi676mc_diagnostic_to_image
        with patch.object(db.session, 'commit', side_effect=Exception('Attach commit fail')):
            with pytest.raises(Exception, match='Attach commit fail'):
                worker._attach_asi676mc_diagnostic_to_image(cached_ctx, fits_entry, {'role': 'preceding', 'capture_id': 'cid'})

        # 5. _archive_asi676mc_diagnostic_fits FileExistsError (line 1714)
        src_fits = tmp_path / 'source.fits'
        src_fits.touch()
        with patch.object(Path, 'joinpath') as mock_joinpath:
            mock_target = MagicMock()
            mock_target.exists.return_value = True
            mock_joinpath.return_value = mock_target
            with pytest.raises(FileExistsError):
                worker._archive_asi676mc_diagnostic_fits(src_fits, mock_i, cam, [{'role': 'bad', 'capture_id': 'cid'}])

        # 6. _archive_asi676mc_diagnostic_fits upload failure rollback (lines 1781-1783)
        with patch.object(worker._miscUpload, 's3_upload_fits', side_effect=Exception('S3 fail')):
            ctx = worker._asi676mc_diagnostic_frame_context(mock_i)
            ctx['fits_bytes'] = b'mock fits bytes'
            ctx['fits_ext'] = 'fits'
            ctx['asi676mc_signature'] = {'sig': '123'}  # line 1757
            entry = worker._archive_asi676mc_diagnostic_fits(None, None, cam, [{'role': 'bad', 'capture_id': 'cid_12345'}], cached_context=ctx)
            assert entry is not None


def test_write_fit_and_export_raw_image(worker, tmp_path, app):
    with app.app_context():
        worker.image_processor.update_astrometric_data(datetime.now())
        cam = IndiAllSkyDbCameraTable.query.first()
        mock_i = MagicMock()
        mock_i.camera_id = cam.id
        mock_i.camera_uuid = cam.uuid
        mock_i.exp_date = datetime.now()
        mock_i.day_date = datetime.now().date()
        mock_i.exposure = 1.0
        mock_i.gain = 100.0
        mock_i.binning = 1
        mock_i.night = True
        mock_i.width = 32
        mock_i.height = 32
        mock_i.stars = []
        mock_i.lines = []
        mock_i.sqm_value = 20.0
        mock_i.smoke_rating = 0
        mock_i.kpindex = 1.0
        mock_i.ovation_max = 5
        mock_i.aurora_mag_bt = 1.0
        mock_i.aurora_mag_gsm_bz = -1.0
        mock_i.aurora_plasma_density = 1.0
        mock_i.aurora_plasma_speed = 400.0
        mock_i.aurora_plasma_temp = 1000
        mock_i.aurora_n_hemi_gw = 10
        mock_i.aurora_s_hemi_gw = 12
        # 1. write_fit with signature metadata, repair status, file_dir creation, and existing file (lines 1882, 1887, 1900, 1906-1908)
        mock_i.asi676mc_repair_result = {'status': 'repaired', 'raw_mean_quadrant_ratios': [1.0] * 4}
        worker.write_fit(mock_i, cam)
        # Calling write_fit again when file exists (lines 1906-1908)
        worker.write_fit(mock_i, cam)

        # 2. export_raw_image grayscale (line 1988), daytime (line 2018), and existing file (lines 2098-2100)
        worker.night_av[constants.NIGHT_NIGHT] = 0  # day
        mock_i.image_bitpix = 8
        mock_i.opencv_data = np.zeros((32, 32), dtype=np.uint8)  # 2D grayscale
        worker.config['IMAGE_EXPORT_RAW'] = 'jpg'
        worker.export_raw_image(mock_i, cam)
        # Call again so file exists (lines 2098-2100)
        with patch.object(worker._miscDb, 'addRawImage'):
            worker.export_raw_image(mock_i, cam)

        # Unknown file type in export_raw_image (line 2005)
        worker.config['IMAGE_EXPORT_RAW'] = 'unsupported_fmt'
        with pytest.raises(Exception, match='Unknown file type'):
            worker.export_raw_image(mock_i, cam)

        # 3. _getImageFolder daytime (line 2392)
        day_folder = worker._getImageFolder(mock_i.exp_date, mock_i.day_date, cam, 'images')
        assert 'day' in str(day_folder)

        # 4. write_panorama_img file exists (lines 2549-2551)
        worker.image_processor.image = np.zeros((32, 32, 3), dtype=np.uint8)
        pano_data = np.zeros((20, 40, 3), dtype=np.uint8)
        worker.write_panorama_img(pano_data, mock_i, cam)
        with patch.object(worker._miscDb, 'addPanoramaImage'):
            worker.write_panorama_img(pano_data, mock_i, cam)

        # 5. write_img with large data >= 1MB (line 2250)
        worker.config['IMAGE_FILE_TYPE'] = 'jpg'
        worker.config['IMAGE_FILE_COMPRESSION'] = {'jpg': 95}
        large_img = np.random.randint(0, 255, (1200, 1200, 3), dtype=np.uint8)
        worker.write_img(large_img, mock_i, cam)


def test_hooks_coverage_and_timeouts(worker, tmp_path):
    worker.image_processor.update_astrometric_data(datetime.now())

    # 1. pre-save hook not executable (lines 2759-2760)
    hook_file = tmp_path / 'hook.sh'
    hook_file.write_text('#!/bin/bash\necho ok')
    os.chmod(str(hook_file), 0o444)
    worker.config['IMAGE_SAVE_HOOK_PRE'] = str(hook_file)
    worker.start_image_save_pre_hook(1.0, 100.0, 1)

    # 2. pre-save hook Popen OSError (lines 2827-2829)
    os.chmod(str(hook_file), 0o755)
    with patch('subprocess.Popen', side_effect=OSError('Spawn failed')):
        worker.start_image_save_pre_hook(1.0, 100.0, 1)

    # 3. post-save hook with focus_mode, not a file, empty file, not executable, and OSError (lines 2834, 2844-2845, 2848-2849, 2852-2853, 2913-2915)
    worker.image_processor.focus_mode = True
    worker.config['IMAGE_SAVE_HOOK_POST'] = str(hook_file)
    assert worker.start_image_save_post_hook(tmp_path / 'img.jpg', 1.0, 100.0, 1) is None
    worker.image_processor.focus_mode = False

    # Not a file (directory)
    worker.config['IMAGE_SAVE_HOOK_POST'] = str(tmp_path)
    worker.start_image_save_post_hook(tmp_path / 'img.jpg', 1.0, 100.0, 1)

    # Empty file
    empty_hook = tmp_path / 'empty_hook.sh'
    empty_hook.touch()
    worker.config['IMAGE_SAVE_HOOK_POST'] = str(empty_hook)
    worker.start_image_save_post_hook(tmp_path / 'img.jpg', 1.0, 100.0, 1)

    # Not executable
    os.chmod(str(hook_file), 0o444)
    worker.config['IMAGE_SAVE_HOOK_POST'] = str(hook_file)
    worker.start_image_save_post_hook(tmp_path / 'img.jpg', 1.0, 100.0, 1)

    # Popen OSError
    os.chmod(str(hook_file), 0o755)
    with patch('subprocess.Popen', side_effect=OSError('Spawn failed')):
        worker.start_image_save_post_hook(tmp_path / 'img.jpg', 1.0, 100.0, 1)

    # 4. wait_image_save_pre_hook timeout, kill, and JSON errors (lines 2944-2946, 2951-2954, 2973-2979)
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None  # running
    worker.image_save_hook_process = mock_proc
    worker.image_save_hook_process_start = time.time() - 10  # expired
    worker.config['IMAGE_SAVE_HOOK_TIMEOUT'] = 1
    worker.pre_hook_datajson_name_p = tmp_path / 'hook_data.json'
    worker.pre_hook_datajson_name_p.touch()

    # Timeout kill
    worker.wait_image_save_pre_hook()
    assert mock_proc.kill.called

    # Non-zero returncode in post-save hook (lines 3055-3058)
    mock_post_proc = MagicMock()
    mock_post_proc.poll.side_effect = [None, 1]  # active then finished
    mock_post_proc.communicate.return_value = (b'Error line 1\nError line 2', b'')
    mock_post_proc.returncode = 1
    worker.image_save_hook_process = mock_post_proc
    worker.image_save_hook_process_start = time.time()
    worker.wait_image_save_post_hook()

    # 5. process_sqm_exposure BadImage (lines 3102-3106)
    bad_file = tmp_path / 'bad_sqm.fits'
    bad_file.write_bytes(b'bad data')
    with patch.object(worker.image_processor, '_add', side_effect=BadImage('Corrupt')):
        worker.process_sqm_exposure(
            bad_file, 1.0, 100.0, 1, datetime.now(), 1.0, MagicMock(), 0
        )
