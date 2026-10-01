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
    TaskQueueState,
    TaskQueueQueue,
)
from indi_allsky.flask import db
from indi_allsky.exceptions import BadImage, TimeOutException


@pytest.fixture
def worker_setup(app, base_config, tmp_path):
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        if not cam:
            cam = IndiAllSkyDbCameraTable(
                name='Test Image Cam',
                uuid='cam-cov-1',
                latitude=-34.9285,
                longitude=138.6007,
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
        Path(config['VARLIB_FOLDER']).mkdir(parents=True, exist_ok=True)
        Path(config['IMAGE_DIR']).mkdir(parents=True, exist_ok=True)

        error_q = Queue()
        image_q = Queue()
        upload_q = Queue()

        position_av = Array('d', [-34.9285, 138.6007, 50.0, 0.0, 0.0])
        exposure_av = Array(ctypes.c_int32, [1000000, 1000000, 0, 1000, 100, 30000000, 5000000])
        gain_av = Array(ctypes.c_int32, [100000, 100000, 0, 0, 100000, 100000, 400000, 50000, 200000, 100000])
        binning_av = Array('i', [1, 1, 1, 2, 1, 1])
        sensors_temp_av = Array('f', [20.0] * 110)
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


def test_image_worker_init_edge_cases(app, base_config, tmp_path):
    config = dict(base_config)
    config['CCD_CONFIG'] = {'EXPOSURE_CLASSNAME': 'nonexistent_class'}
    config.pop('IMAGE_FOLDER', None)
    config['VARLIB_FOLDER'] = str(tmp_path / 'varlib')

    position_av = Array('d', [0.0] * 5)
    exposure_av = Array(ctypes.c_int32, [0] * 7)
    gain_av = Array(ctypes.c_int32, [0] * 10)
    binning_av = Array('i', [1] * 6)
    sensors_temp_av = Array('f', [0.0] * 110)
    sensors_user_av = Array('f', [0.0] * 110)
    night_av = Array('i', [0, 0])
    astro_av = Array('f', [0.0] * 10)

    worker = ImageWorker(
        idx=1,
        config=config,
        error_q=Queue(),
        image_q=Queue(),
        upload_q=Queue(),
        position_av=position_av,
        exposure_av=exposure_av,
        gain_av=gain_av,
        binning_av=binning_av,
        sensors_temp_av=sensors_temp_av,
        sensors_user_av=sensors_user_av,
        night_av=night_av,
        astro_av=astro_av,
    )
    assert worker.name == 'Image-1'
    assert worker.image_dir.name == 'images'


def test_image_worker_sigalarm_and_run(worker_setup):
    worker = worker_setup
    with pytest.raises(TimeOutException):
        worker.sigalarm_handler_worker(14, None)

    # Test run() when saferun() raises an exception
    with patch.object(worker, 'saferun', side_effect=RuntimeError('Worker failure')):
        with pytest.raises(RuntimeError):
            worker.run()
        err_msg, tb = worker.error_q.get(timeout=2.0)
        assert 'Worker failure' in err_msg



def test_image_worker_saferun_flow(worker_setup):
    worker = worker_setup
    # Put a stop command
    worker.image_q.put({'stop': True})
    with patch.object(worker.image_processor, 'realtimeKeogramDataSave') as mock_save:
        worker.saferun()
        mock_save.assert_called_once()
        assert worker._shutdown is True


@pytest.mark.parametrize('fmt', ['jpg', 'png', 'webp', 'tif'])
def test_image_worker_write_img_formats(worker_setup, app, fmt):
    worker = worker_setup
    worker.config['IMAGE_FILE_TYPE'] = fmt
    worker.config['IMAGE_FILE_COMPRESSION'] = {'jpg': 90, 'png': 3}

    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        data = np.full((32, 32, 3), 100, dtype=np.uint8)
        mock_i_ref = MagicMock()
        mock_i_ref.camera_id = cam.id
        mock_i_ref.camera_uuid = cam.uuid
        mock_i_ref.exp_date = datetime.now()
        mock_i_ref.day_date = datetime.now().date()

        latest, exp = worker.write_img(data, mock_i_ref, cam, jpeg_exif=b"")
        assert latest.exists()
        assert exp.exists()

        # Duplicate file path test
        latest2, exp2 = worker.write_img(data, mock_i_ref, cam, jpeg_exif=b"")
        assert latest2.exists()
        assert exp2 is None


def test_image_worker_write_img_unknown_format(worker_setup, app):
    worker = worker_setup
    worker.config['IMAGE_FILE_TYPE'] = 'bmp'
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        data = np.full((32, 32, 3), 100, dtype=np.uint8)
        mock_i_ref = MagicMock()
        mock_i_ref.camera_id = cam.id
        mock_i_ref.camera_uuid = cam.uuid
        mock_i_ref.exp_date = datetime.now()
        mock_i_ref.day_date = datetime.now().date()

        with pytest.raises(Exception, match='Unknown file type'):
            worker.write_img(data, mock_i_ref, cam)


@pytest.mark.parametrize('fmt', ['jpg', 'png', 'webp', 'tif'])
def test_image_worker_write_panorama_img_formats(worker_setup, app, fmt):
    worker = worker_setup
    worker.config['IMAGE_FILE_TYPE'] = fmt
    worker.config['IMAGE_FILE_COMPRESSION'] = {'jpg': 90, 'png': 3}
    worker.image_processor.image = np.full((100, 100, 3), 100, dtype=np.uint8)
    worker.image_processor.update_astrometric_data(datetime.now())

    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        pano_data = np.full((30, 80, 3), 120, dtype=np.uint8)
        mock_i_ref = MagicMock()
        mock_i_ref.binning = 1
        mock_i_ref.camera_id = cam.id
        mock_i_ref.camera_uuid = cam.uuid
        mock_i_ref.exp_date = datetime.now()
        mock_i_ref.day_date = datetime.now().date()
        mock_i_ref.exposure = 1.0
        mock_i_ref.gain = 100.0
        mock_i_ref.sqm_value = 21.0
        mock_i_ref.stars = []
        mock_i_ref.lines = []
        mock_i_ref.kpindex = 1
        mock_i_ref.ovation_max = 0
        mock_i_ref.smoke_rating = constants.SMOKE_RATING_CLEAR
        mock_i_ref.aurora_mag_bt = 0
        mock_i_ref.aurora_mag_gsm_bz = 0
        mock_i_ref.aurora_plasma_density = 0
        mock_i_ref.aurora_plasma_speed = 0
        mock_i_ref.aurora_plasma_temp = 0
        mock_i_ref.aurora_n_hemi_gw = 0
        mock_i_ref.aurora_s_hemi_gw = 0
        mock_i_ref.asi676mc_repair_result = None

        worker.write_panorama_img(pano_data, mock_i_ref, cam, jpeg_exif=b"")
        latest = worker.image_dir.joinpath(f'panorama.{fmt}')
        assert latest.exists()


def test_image_worker_write_panorama_img_unknown_format(worker_setup, app):
    worker = worker_setup
    worker.config['IMAGE_FILE_TYPE'] = 'bmp'
    worker.image_processor.image = np.full((100, 100, 3), 100, dtype=np.uint8)
    worker.image_processor.update_astrometric_data(datetime.now())

    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        pano_data = np.full((30, 80, 3), 120, dtype=np.uint8)
        mock_i_ref = MagicMock()
        mock_i_ref.camera_id = cam.id
        mock_i_ref.camera_uuid = cam.uuid
        mock_i_ref.exp_date = datetime.now()
        mock_i_ref.day_date = datetime.now().date()

        with pytest.raises(Exception, match='Unknown file type'):
            worker.write_panorama_img(pano_data, mock_i_ref, cam)



@pytest.mark.parametrize('fmt', ['jpg', 'png', 'webp', 'tif'])
def test_image_worker_write_circular_display_formats(worker_setup, fmt):
    worker = worker_setup
    worker.config['IMAGE_FILE_TYPE'] = fmt
    worker.config['IMAGE_FILE_COMPRESSION'] = {'jpg': 90, 'png': 3}

    circ_data = np.full((40, 40, 3), 110, dtype=np.uint8)
    worker.write_circular_display_img(circ_data, jpeg_exif=b"")
    latest = worker.image_dir.joinpath(f'circular_display.{fmt}')
    assert latest.exists()


def test_image_worker_write_circular_display_unknown(worker_setup):
    worker = worker_setup
    worker.config['IMAGE_FILE_TYPE'] = 'bmp'
    circ_data = np.full((40, 40, 3), 110, dtype=np.uint8)
    with pytest.raises(Exception, match='Unknown file type'):
        worker.write_circular_display_img(circ_data)


@pytest.mark.parametrize('fmt', ['jpg', 'png', 'webp', 'tif'])
def test_image_worker_write_realtime_keogram_formats(worker_setup, app, fmt):
    worker = worker_setup
    worker.config['IMAGE_FILE_TYPE'] = fmt
    worker.config['IMAGE_FILE_COMPRESSION'] = {'jpg': 90, 'png': 3}
    worker.image_processor.realtimeKeogramApplyLabels = MagicMock(side_effect=lambda x: x)

    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        keo_data = np.full((50, 50, 3), 120, dtype=np.uint8)
        worker.write_realtime_keogram(keo_data, cam)
        keo_file = worker.image_dir.joinpath(f'ccd_{cam.uuid}', f'realtime_keogram.{fmt}')
        assert keo_file.exists()


def test_image_worker_write_realtime_keogram_unknown(worker_setup, app):
    worker = worker_setup
    worker.config['IMAGE_FILE_TYPE'] = 'bmp'
    worker.image_processor.realtimeKeogramApplyLabels = MagicMock(side_effect=lambda x: x)

    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        keo_data = np.full((50, 50, 3), 120, dtype=np.uint8)
        with pytest.raises(Exception, match='Unknown file type'):
            worker.write_realtime_keogram(keo_data, cam)


@pytest.mark.parametrize('fmt,bitpix', [
    ('jpg', 8),
    ('jpg', 16),
    ('png', 16),
    ('jp2', 16),
    ('webp', 16),
    ('tif', 16),
])
def test_image_worker_export_raw_image(worker_setup, app, tmp_path, fmt, bitpix):
    worker = worker_setup
    export_dir = tmp_path / 'export_raw'
    worker.config['IMAGE_EXPORT_RAW'] = fmt
    worker.config['IMAGE_EXPORT_FOLDER'] = str(export_dir)
    worker.config['IMAGE_FILE_COMPRESSION'] = {'jpg': 90, 'png': 3}
    worker.image_processor.update_astrometric_data(datetime.now())

    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        mock_i_ref = MagicMock()
        mock_i_ref.camera_id = cam.id
        mock_i_ref.camera_uuid = cam.uuid
        mock_i_ref.exp_date = datetime.now()
        mock_i_ref.day_date = datetime.now().date()
        mock_i_ref.exposure = 1.0
        mock_i_ref.gain = 100.0
        mock_i_ref.binning = 1
        mock_i_ref.image_bitpix = bitpix
        mock_i_ref.sqm_value = 21.0
        mock_i_ref.stars = []
        mock_i_ref.lines = []
        mock_i_ref.kpindex = 1
        mock_i_ref.ovation_max = 0
        mock_i_ref.smoke_rating = constants.SMOKE_RATING_CLEAR
        mock_i_ref.aurora_mag_bt = 0
        mock_i_ref.aurora_mag_gsm_bz = 0
        mock_i_ref.aurora_plasma_density = 0
        mock_i_ref.aurora_plasma_speed = 0
        mock_i_ref.aurora_plasma_temp = 0
        mock_i_ref.aurora_n_hemi_gw = 0
        mock_i_ref.aurora_s_hemi_gw = 0

        dtype = np.uint8 if bitpix == 8 else np.uint16
        mock_i_ref.opencv_data = np.full((32, 32, 3), 100, dtype=dtype)

        worker.export_raw_image(mock_i_ref, cam)
        assert export_dir.exists()


def test_image_worker_export_raw_image_edge_cases(worker_setup, app, tmp_path):
    worker = worker_setup

    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        mock_i_ref = MagicMock()

        # Disabled in config
        worker.config['IMAGE_EXPORT_RAW'] = None
        worker.export_raw_image(mock_i_ref, cam)

        # Folder not defined
        worker.config['IMAGE_EXPORT_RAW'] = 'jpg'
        worker.config['IMAGE_EXPORT_FOLDER'] = None
        worker.export_raw_image(mock_i_ref, cam)

        # Daytime capture disabled
        worker.config['IMAGE_EXPORT_FOLDER'] = str(tmp_path / 'export')
        worker.night_av[constants.NIGHT_NIGHT] = 0
        worker.config['DAYTIME_CAPTURE_SAVE'] = False
        worker.export_raw_image(mock_i_ref, cam)

        # Unsupported bit depth
        worker.night_av[constants.NIGHT_NIGHT] = 1
        mock_i_ref.image_bitpix = 32
        mock_i_ref.opencv_data = np.zeros((10, 10), dtype=np.float32)
        with pytest.raises(Exception, match='Unsupported bit depth'):
            worker.export_raw_image(mock_i_ref, cam)


@pytest.mark.parametrize('temp_unit', ['f', 'k', 'c'])
def test_image_worker_upload_metadata_temp_and_tod(worker_setup, app, temp_unit):
    worker = worker_setup
    worker.image_processor.update_astrometric_data(datetime.now())
    worker.config['TEMP_DISPLAY'] = temp_unit
    worker.config['FILETRANSFER'] = {
        'UPLOAD_METADATA': True,
        'UPLOAD_IMAGE': 1,
        'REMOTE_METADATA_FOLDER': '/meta/{timeofday}',
        'REMOTE_METADATA_NAME': 'meta.json',
    }

    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        mock_i_ref = MagicMock()
        mock_i_ref.camera_name = cam.name
        mock_i_ref.camera_id = cam.id
        mock_i_ref.camera_uuid = cam.uuid
        mock_i_ref.exp_date = datetime.now()
        mock_i_ref.day_date = datetime.now().date()
        mock_i_ref.gain = 100.0
        mock_i_ref.exposure = 1.0
        mock_i_ref.target_adu = 128.0
        mock_i_ref.sqm_value = 21.0
        mock_i_ref.stars = []
        mock_i_ref.kpindex = 1
        mock_i_ref.ovation_max = 0
        mock_i_ref.smoke_rating = constants.SMOKE_RATING_CLEAR
        mock_i_ref.aurora_mag_bt = 0
        mock_i_ref.aurora_mag_gsm_bz = 0
        mock_i_ref.aurora_plasma_density = 0
        mock_i_ref.aurora_plasma_speed = 0
        mock_i_ref.aurora_plasma_temp = 0
        mock_i_ref.aurora_n_hemi_gw = 0
        mock_i_ref.aurora_s_hemi_gw = 0

        # Day mode
        worker.night_av[constants.NIGHT_NIGHT] = 0
        worker.upload_metadata(mock_i_ref, 128.0, 128.0)
        assert worker.upload_q.qsize() == 1
        task_item = worker.upload_q.get()
        assert task_item['task_id'] is not None


def test_image_worker_hook_timeout_and_errors(worker_setup, tmp_path):
    worker = worker_setup
    worker.config['IMAGE_SAVE_HOOK_TIMEOUT'] = 0.1

    # Simulate pre-hook timeout
    mock_proc = MagicMock()
    poll_calls = [0]
    def mock_poll():
        poll_calls[0] += 1
        return None if poll_calls[0] < 3 else 0
    mock_proc.poll.side_effect = mock_poll
    worker.image_save_hook_process = mock_proc
    worker.image_save_hook_process_start = time.time() - 10
    worker.pre_hook_datajson_name_p = tmp_path / "pre_hook.json"
    worker.pre_hook_datajson_name_p.touch()

    worker.wait_image_save_pre_hook()
    mock_proc.terminate.assert_called()

    # Simulate post-hook timeout
    mock_proc2 = MagicMock()
    poll_calls2 = [0]
    def mock_poll2():
        poll_calls2[0] += 1
        return None if poll_calls2[0] < 3 else 0
    mock_proc2.poll.side_effect = mock_poll2
    worker.image_save_hook_process = mock_proc2
    worker.image_save_hook_process_start = time.time() - 10
    worker.wait_image_save_post_hook()
    mock_proc2.terminate.assert_called()

    # Pre-hook invalid JSON
    mock_proc3 = MagicMock()
    mock_proc3.poll.return_value = 0
    mock_proc3.returncode = 0
    mock_proc3.communicate.return_value = (b"", b"")
    worker.image_save_hook_process = mock_proc3
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("invalid json")
    worker.pre_hook_datajson_name_p = bad_json
    res = worker.wait_image_save_pre_hook()
    assert res['custom_1'] == ''




def test_image_worker_full_process_image(worker_setup, app, tmp_path):
    worker = worker_setup
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()

        # Create dummy FITS file
        fits_file = tmp_path / "capture.fits"
        hdu = fits.PrimaryHDU(np.full((64, 64), 500, dtype=np.uint16))
        hdu.header['EXPTIME'] = 1.0
        hdu.header['GAIN'] = 100.0
        hdu.header['BITPIX'] = 16
        hdu.header['BAYERPAT'] = 'RGGB'
        hdu.writeto(str(fits_file))

        # Enable all features
        worker.config['IMAGE_SAVE_FITS'] = True
        worker.config['IMAGE_SAVE_FITS_PRE_DARK'] = False
        worker.config['DETECT_METEORS'] = True
        worker.config['DETECT_STARS'] = True
        worker.config['DETECT_DRAW'] = True
        worker.config['CONTRAST_ENHANCE_16BIT'] = True
        worker.config['NIGHT_CONTRAST_ENHANCE'] = True
        worker.config['FISH2PANO'] = {'ENABLE': True, 'MODULUS': 1, 'ENABLE_CARDINAL_DIRS': False}
        worker.config['CIRCULAR_DISPLAY'] = {'ENABLE': True}
        worker.config['PRIVACY_MODE'] = True
        worker.config['TEMP_DISPLAY'] = 'f'

        # Mock psutil calls to be safe across environments
        mock_cpu = MagicMock(user=5.0, system=2.0, nice=0.0, iowait=1.0)
        mock_mem = MagicMock(used=2000, total=8000, cached=1000, free=5000)
        mock_disk = MagicMock(percent=50.0)
        mock_part = MagicMock(mountpoint='/')
        mock_temp = MagicMock(current=42.0, label='Core 0')

        with patch('psutil.cpu_times_percent', return_value=mock_cpu), \
             patch('psutil.virtual_memory', return_value=mock_mem), \
             patch('psutil.disk_partitions', return_value=[mock_part]), \
             patch('psutil.disk_usage', return_value=mock_disk), \
             patch('psutil.sensors_temperatures', return_value={'cpu': [mock_temp]}):

            i_dict = {
                'filename': str(fits_file),
                'exposure': 1.0,
                'gain': 100.0,
                'binning': 1,
                'exp_time': datetime.now().timestamp(),
                'exp_elapsed': 1.0,
                'camera_id': cam.id,
            }

            worker.processImage(i_dict)
            assert worker.image_count == 1
            latest = worker.image_dir.joinpath('latest.jpg')
            assert latest.exists()


def test_image_worker_process_image_pre_dark_and_bad_image(worker_setup, app, tmp_path):
    worker = worker_setup
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()

        # BadImage handling
        corrupt_file = tmp_path / "corrupt.fits"
        corrupt_file.write_bytes(b"bad binary content")

        i_dict_bad = {
            'filename': str(corrupt_file),
            'exposure': 1.0,
            'gain': 100.0,
            'binning': 1,
            'exp_time': datetime.now().timestamp(),
            'exp_elapsed': 1.0,
            'camera_id': cam.id,
        }
        with patch.object(worker.image_processor, 'add', side_effect=BadImage("Corrupted file")):
            worker.processImage(i_dict_bad)
            assert not corrupt_file.exists()

        # Pre-dark FITS save
        fits_file2 = tmp_path / "capture_predark.fits"
        hdu = fits.PrimaryHDU(np.full((32, 32), 600, dtype=np.uint16))
        hdu.header['EXPTIME'] = 1.0
        hdu.header['GAIN'] = 100.0
        hdu.header['BITPIX'] = 16
        hdu.header['BAYERPAT'] = 'RGGB'
        hdu.writeto(str(fits_file2))

        worker.config['IMAGE_SAVE_FITS'] = True
        worker.config['IMAGE_SAVE_FITS_PRE_DARK'] = True
        worker.config['IMAGE_EXIF_PRIVACY'] = True

        i_dict_predark = {
            'filename': str(fits_file2),
            'exposure': 1.0,
            'gain': 100.0,
            'binning': 1,
            'exp_time': datetime.now().timestamp(),
            'exp_elapsed': 1.0,
            'camera_id': cam.id,
        }
        worker.processImage(i_dict_predark)


def test_image_worker_saferun_empty_queue(worker_setup):
    worker = worker_setup
    calls = [0]
    orig_get = worker.image_q.get

    def mock_get(timeout=None):
        calls[0] += 1
        if calls[0] == 1:
            raise queue.Empty
        return {'stop': True}

    with patch.object(worker.image_q, 'get', side_effect=mock_get):
        worker.saferun()
        assert worker._shutdown is True






def test_image_worker_process_image_sqm_and_daytime_contrast(worker_setup, app, tmp_path):
    worker = worker_setup
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        fits_file = tmp_path / "sqm_proc.fits"
        hdu = fits.PrimaryHDU(np.full((32, 32), 450, dtype=np.uint16))
        hdu.header['EXPTIME'] = 1.0
        hdu.header['GAIN'] = 100.0
        hdu.header['BITPIX'] = 16
        hdu.header['BAYERPAT'] = 'RGGB'
        hdu.writeto(str(fits_file))

        # sqm_exposure = True
        with patch.object(worker, 'process_sqm_exposure') as mock_sqm:
            i_dict_sqm = {
                'filename': str(fits_file),
                'exposure': 1.0,
                'gain': 100.0,
                'binning': 1,
                'exp_time': datetime.now().timestamp(),
                'exp_elapsed': 1.0,
                'camera_id': cam.id,
                'sqm_exposure': True,
            }
            worker.processImage(i_dict_sqm)
            mock_sqm.assert_called_once()

        # Daytime contrast 8-bit
        fits_file2 = tmp_path / "daytime.fits"
        hdu.writeto(str(fits_file2))
        worker.night_av[constants.NIGHT_NIGHT] = 0
        worker.config['DAYTIME_CAPTURE'] = True
        worker.config['DAYTIME_CAPTURE_SAVE'] = False
        worker.config['CONTRAST_ENHANCE_16BIT'] = False
        worker.config['DAYTIME_CONTRAST_ENHANCE'] = True

        i_dict_day = {
            'filename': str(fits_file2),
            'exposure': 0.1,
            'gain': 10.0,
            'binning': 1,
            'exp_time': datetime.now().timestamp(),
            'exp_elapsed': 0.1,
            'camera_id': cam.id,
        }
        worker.processImage(i_dict_day)


def test_image_worker_asi676mc_diagnostic_workflow(worker_setup, app, tmp_path):
    worker = worker_setup
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        worker.config['IMAGE_ASI676MC_REPAIR'] = {
            'ENABLE': True,
            'SAVE_DIAGNOSTIC_FITS': True,
            'SAVE_PRECEDING_FITS': True,
        }

        # Normal frame 1 -> should be cached as preceding candidate
        f1 = tmp_path / "f1.fits"
        hdu1 = fits.PrimaryHDU(np.full((32, 32), 500, dtype=np.uint16))
        hdu1.writeto(str(f1))

        mock_i1 = MagicMock()
        mock_i1.camera_id = cam.id
        mock_i1.camera_uuid = cam.uuid
        mock_i1.exp_date = datetime.now()
        mock_i1.day_date = datetime.now().date()
        mock_i1.exposure = 1.0
        mock_i1.gain = 100.0
        mock_i1.binning = 1
        mock_i1.hdulist = [hdu1]
        mock_i1.image_bayerpat = 'RGGB'
        mock_i1.detected_camera_name = 'ZWO ASI676MC'
        mock_i1.asi676mc_repair_result = {'status': 'normal'}

        with patch('indi_allsky.asi676mc.camera_name_matches', return_value=True):
            worker.capture_asi676mc_diagnostic_fits(f1, mock_i1, cam)
            assert cam.id in worker.asi676mc_diagnostic_previous

            # Repaired frame 2 -> archives preceding (f1) and current (f2)
            f2 = tmp_path / "f2.fits"
            hdu2 = fits.PrimaryHDU(np.full((32, 32), 600, dtype=np.uint16))
            hdu2.writeto(str(f2))

            mock_i2 = MagicMock()
            mock_i2.camera_id = cam.id
            mock_i2.camera_uuid = cam.uuid
            mock_i2.exp_date = datetime.now() + timedelta(seconds=2)
            mock_i2.day_date = datetime.now().date()
            mock_i2.exposure = 1.0
            mock_i2.gain = 100.0
            mock_i2.binning = 1
            mock_i2.hdulist = [hdu2]
            mock_i2.image_bayerpat = 'RGGB'
            mock_i2.detected_camera_name = 'ZWO ASI676MC'
            mock_i2.asi676mc_repair_result = {
                'status': 'repaired',
                'raw_mean_quadrant_ratios': [1.0, 1.0, 1.0, 1.0],
                'corrected_mean_quadrant_ratios': [1.0, 1.0, 1.0, 1.0],
            }

            worker.capture_asi676mc_diagnostic_fits(f2, mock_i2, cam)
            assert cam.id in worker.asi676mc_diagnostic_pending

            # Normal frame 3 -> archives following, reuses as preceding
            f3 = tmp_path / "f3.fits"
            hdu3 = fits.PrimaryHDU(np.full((32, 32), 520, dtype=np.uint16))
            hdu3.writeto(str(f3))

            mock_i3 = MagicMock()
            mock_i3.camera_id = cam.id
            mock_i3.camera_uuid = cam.uuid
            mock_i3.exp_date = datetime.now() + timedelta(seconds=4)
            mock_i3.day_date = datetime.now().date()
            mock_i3.exposure = 1.0
            mock_i3.gain = 100.0
            mock_i3.binning = 1
            mock_i3.hdulist = [hdu3]
            mock_i3.image_bayerpat = 'RGGB'
            mock_i3.detected_camera_name = 'ZWO ASI676MC'
            mock_i3.asi676mc_repair_result = {'status': 'normal'}

            worker.capture_asi676mc_diagnostic_fits(f3, mock_i3, cam)

            # Repaired frame 4 -> reuses preceding role from saved following frame
            f4 = tmp_path / "f4.fits"
            hdu4 = fits.PrimaryHDU(np.full((32, 32), 650, dtype=np.uint16))
            hdu4.writeto(str(f4))

            mock_i4 = MagicMock()
            mock_i4.camera_id = cam.id
            mock_i4.camera_uuid = cam.uuid
            mock_i4.exp_date = datetime.now() + timedelta(seconds=6)
            mock_i4.day_date = datetime.now().date()
            mock_i4.exposure = 1.0
            mock_i4.gain = 100.0
            mock_i4.binning = 1
            mock_i4.hdulist = [hdu4]
            mock_i4.image_bayerpat = 'RGGB'
            mock_i4.detected_camera_name = 'ZWO ASI676MC'
            mock_i4.asi676mc_repair_result = {
                'status': 'repaired',
                'raw_mean_quadrant_ratios': [1.0, 1.0, 1.0, 1.0],
                'corrected_mean_quadrant_ratios': [1.0, 1.0, 1.0, 1.0],
            }

            worker.capture_asi676mc_diagnostic_fits(f4, mock_i4, cam)

