import ctypes
from datetime import datetime, timezone, timedelta
from multiprocessing import Array, Queue
from pathlib import Path
from unittest.mock import MagicMock, patch
import cv2
import numpy as np
import pytest

from indi_allsky import constants
from indi_allsky.image import ImageWorker
from indi_allsky.flask.models import IndiAllSkyDbCameraTable, IndiAllSkyDbImageTable
from indi_allsky.flask import db


@pytest.fixture
def image_worker_setup(app, base_config, tmp_path):
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        if not cam:
            cam = IndiAllSkyDbCameraTable(
                name='ImageWorker Camera',
                uuid='cam-img-test-1',
                latitude=-34.9285,
                longitude=138.6007,
                elevation=50,
                nightSunAlt=-6.0,
                lensFocalLength=2.5,
                lensFocalRatio=1.4,
                lensImageCircle=1000,
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
        Path(config['VARLIB_FOLDER']).mkdir(parents=True, exist_ok=True)
        Path(config['IMAGE_DIR']).mkdir(parents=True, exist_ok=True)

        error_q = Queue()
        image_q = Queue()
        upload_q = Queue()

        position_av = Array('d', [0.0] * 5)
        exposure_av = Array(ctypes.c_int32, [1000000, 1000000, 0, 1000, 100, 30000000, 5000000])
        gain_av = Array(ctypes.c_int32, [100000, 100000, 0, 0, 100000, 100000, 400000, 50000, 200000, 100000])
        binning_av = Array('i', [1, 1, 1, 2, 1, 1])
        sensors_temp_av = Array('f', [0.0] * 110)
        sensors_user_av = Array('f', [0.0] * 110)
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


def test_image_worker_init(image_worker_setup):
    worker = image_worker_setup
    assert worker.name == 'Image-0'
    assert worker._shutdown is False
    assert worker.sqm_history_minutes == 30


def test_image_worker_signals(image_worker_setup):
    worker = image_worker_setup

    worker.sighup_handler_worker(1, None)
    assert worker._shutdown is True


    worker._shutdown = False
    worker.sigterm_handler_worker(15, None)
    assert worker._shutdown is True

    worker._shutdown = False
    worker.sigint_handler_worker(2, None)
    assert worker._shutdown is True


def test_image_worker_properties(image_worker_setup):
    worker = image_worker_setup

    worker.libcamera_raw = True
    assert worker.libcamera_raw is True


def test_image_worker_decdeg2dms(image_worker_setup):
    worker = image_worker_setup

    # Positive degree
    deg, minutes, seconds = worker.decdeg2dms(34.5678)
    assert deg == 34
    assert minutes == 34
    assert round(seconds, 1) == 4.1

    # Negative degree
    deg_neg, min_neg, sec_neg = worker.decdeg2dms(-12.3456)
    assert deg_neg == -12


def test_image_worker_mask_and_focus_writes(image_worker_setup):
    worker = image_worker_setup
    data = np.full((32, 32, 3), 128, dtype=np.uint8)

    # Base mask
    worker.write_mask_base_img(data)
    assert worker.image_dir.joinpath('mask_base.png').exists()

    # Focus PNG
    worker.write_focus_png(data)
    assert worker.image_dir.joinpath('focus.png').exists()

    # Focus FIT
    worker.write_focus_fit(data)
    assert worker.image_dir.joinpath('focus.fit').exists()


def test_image_worker_get_image_folder(image_worker_setup, app):
    worker = image_worker_setup
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        now = datetime.now()
        folder = worker._getImageFolder(now, now.date(), cam, 'raw')
        assert folder.exists()
        assert str(folder).startswith(str(worker.image_dir))


def test_image_worker_sqm_and_stars_data(image_worker_setup, app):
    worker = image_worker_setup
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        now = datetime.now()

        # Add dummy image record
        img = IndiAllSkyDbImageTable(
            camera_id=cam.id,
            filename='dummy.jpg',
            dayDate=now.date(),
            createDate=now,
            exposure=1.0,
            gain=100.0,
            adu=128.0,
            sqm=21.4,
            stars=55,
        )
        db.session.add(img)
        db.session.commit()

        sqm_data = worker.getSqmData(cam.id)
        assert sqm_data['max'] is not None

        stars_data = worker.getStarsData(cam.id)
        assert stars_data['max'] is not None


def test_image_worker_write_status_json(image_worker_setup, app):
    worker = image_worker_setup
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()

        mock_i_ref = MagicMock()
        mock_i_ref.camera_name = cam.name
        mock_i_ref.gain = 100.0
        mock_i_ref.exposure = 1.0
        mock_i_ref.target_adu = 128.0
        mock_i_ref.sqm_value = 21.0
        mock_i_ref.stars = [1, 2, 3]
        mock_i_ref.lines = []
        mock_i_ref.exp_date = datetime.now()
        mock_i_ref.kpindex = 2.0
        mock_i_ref.ovation_max = 30
        mock_i_ref.aurora_mag_bt = 4.0
        mock_i_ref.aurora_mag_gsm_bz = -1.0
        mock_i_ref.aurora_plasma_density = 3.0
        mock_i_ref.aurora_plasma_speed = 400.0
        mock_i_ref.aurora_plasma_temp = 50000
        mock_i_ref.aurora_n_hemi_gw = 10
        mock_i_ref.aurora_s_hemi_gw = 12
        mock_i_ref.smoke_rating = constants.SMOKE_RATING_CLEAR
        mock_i_ref.uptime = 12345

        worker.write_status_json(mock_i_ref, adu=128.0, adu_average=127.5)
        status_file = worker.varlib_folder_p.joinpath('indi_allsky_status.json')
        assert status_file.exists()


def test_image_worker_process_running(image_worker_setup):
    worker = image_worker_setup
    assert worker._processRunning(None) is False

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    assert worker._processRunning(mock_proc) is True

    mock_proc.poll.return_value = 0
    assert worker._processRunning(mock_proc) is False


def test_image_worker_save_hooks(image_worker_setup, tmp_path):
    worker = image_worker_setup
    worker.image_processor.update_astrometric_data(datetime.now())

    # Pre-hook disabled
    worker.config['IMAGE_SAVE_HOOK_PRE'] = None
    worker.start_image_save_pre_hook(1.0, 100.0, 1)
    assert worker.image_save_hook_process is None
    assert worker.wait_image_save_pre_hook() == {}

    # Pre-hook with focus mode
    worker.image_processor.focus_mode = True
    worker.config['IMAGE_SAVE_HOOK_PRE'] = '/tmp/fake.sh'
    worker.start_image_save_pre_hook(1.0, 100.0, 1)
    assert worker.image_save_hook_process is None
    worker.image_processor.focus_mode = False

    # Pre-hook not a file
    worker.config['IMAGE_SAVE_HOOK_PRE'] = str(tmp_path / 'nonexistent.sh')
    worker.start_image_save_pre_hook(1.0, 100.0, 1)
    assert worker.image_save_hook_process is None

    # Pre-hook empty file
    empty_script = tmp_path / 'empty.sh'
    empty_script.touch()
    worker.config['IMAGE_SAVE_HOOK_PRE'] = str(empty_script)
    worker.start_image_save_pre_hook(1.0, 100.0, 1)
    assert worker.image_save_hook_process is None

    # Pre-hook valid executable script
    pre_script = tmp_path / 'pre_hook.sh'
    pre_script.write_text('#!/bin/sh\necho "{\\"custom_1\\": \\"success\\"}" > "$DATA_JSON"\nexit 0\n')
    pre_script.chmod(0o755)
    worker.config['IMAGE_SAVE_HOOK_PRE'] = str(pre_script)
    worker.start_image_save_pre_hook(1.0, 100.0, 1)
    hook_result = worker.wait_image_save_pre_hook()
    assert hook_result.get('custom_1') == 'success'

    # Pre-hook non-zero exit code
    fail_script = tmp_path / 'fail_hook.sh'
    fail_script.write_text('#!/bin/sh\nexit 1\n')
    fail_script.chmod(0o755)
    worker.config['IMAGE_SAVE_HOOK_PRE'] = str(fail_script)
    worker.start_image_save_pre_hook(1.0, 100.0, 1)
    fail_result = worker.wait_image_save_pre_hook()
    assert fail_result.get('custom_1') == ''

    # Post-hook disabled / focus mode
    worker.config['IMAGE_SAVE_HOOK_POST'] = None
    worker.start_image_save_post_hook('/tmp/img.jpg', 1.0, 100.0, 1)
    assert worker.image_save_hook_process is None
    worker.wait_image_save_post_hook()  # returns early safely

    # Post-hook valid executable script
    post_script = tmp_path / 'post_hook.sh'
    post_script.write_text('#!/bin/sh\nexit 0\n')
    post_script.chmod(0o755)
    worker.config['IMAGE_SAVE_HOOK_POST'] = str(post_script)
    worker.start_image_save_post_hook('/tmp/img.jpg', 1.0, 100.0, 1)
    worker.wait_image_save_post_hook()
    assert worker.image_save_hook_process is None


def test_image_worker_save_longterm_keogram_data(image_worker_setup, app):
    worker = image_worker_setup
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        worker.image_processor.image = np.full((100, 100, 3), 75, dtype=np.uint8)

        # Focus mode disabled
        worker.image_processor.focus_mode = True
        assert worker.save_longterm_keogram_data(datetime.now(), cam.id) is None
        worker.image_processor.focus_mode = False

        # Config disabled
        worker.config['LONGTERM_KEOGRAM'] = {'ENABLE': False}
        assert worker.save_longterm_keogram_data(datetime.now(), cam.id) is None

        # Enabled
        worker.config['LONGTERM_KEOGRAM'] = {'ENABLE': True, 'OFFSET_X': 0, 'OFFSET_Y': 0}
        pixels = worker.save_longterm_keogram_data(datetime.now(), cam.id)
        assert len(pixels) == 5
        assert pixels[0] == [75, 75, 75]


def test_image_worker_write_realtime_keogram(image_worker_setup, app):
    worker = image_worker_setup
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()

        # None data
        worker.write_realtime_keogram(None, cam)

        # Valid data
        data = np.full((60, 120, 3), 90, dtype=np.uint8)
        worker.write_realtime_keogram(data, cam)
        keo_file = worker.image_dir.joinpath(f'ccd_{cam.uuid}', 'realtime_keogram.jpg')
        assert keo_file.exists()


def test_image_worker_write_circular_display_img(image_worker_setup):
    worker = image_worker_setup
    data = np.full((64, 64, 3), 110, dtype=np.uint8)
    worker.write_circular_display_img(data, jpeg_exif=b"")
    circ_file = worker.image_dir.joinpath('circular_display.jpg')
    assert circ_file.exists()


def test_image_worker_write_img_variants(image_worker_setup, app):
    worker = image_worker_setup
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        data = np.full((32, 32, 3), 120, dtype=np.uint8)

        mock_i_ref = MagicMock()
        mock_i_ref.camera_id = cam.id
        mock_i_ref.camera_uuid = cam.uuid
        mock_i_ref.exp_date = datetime.now()
        mock_i_ref.day_date = datetime.now().date()

        # Focus mode returns (None, None)
        worker.config['FOCUS_MODE'] = True
        latest, exp = worker.write_img(data, mock_i_ref, cam, jpeg_exif=b"")
        assert latest is None and exp is None
        worker.config['FOCUS_MODE'] = False

        # Daytime capture disabled returns (latest, None)
        worker.night_av[constants.NIGHT_NIGHT] = 0
        worker.config['DAYTIME_CAPTURE'] = True
        worker.config['DAYTIME_CAPTURE_SAVE'] = False
        latest, exp = worker.write_img(data, mock_i_ref, cam, jpeg_exif=b"")
        assert latest is not None
        assert exp is None

        # Normal night save
        worker.night_av[constants.NIGHT_NIGHT] = 1
        latest, exp = worker.write_img(data, mock_i_ref, cam, jpeg_exif=b"")
        assert latest.exists()
        assert exp.exists()


def test_image_worker_write_panorama_img(image_worker_setup, app):
    worker = image_worker_setup
    worker.image_processor.update_astrometric_data(datetime.now())
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        worker.image_processor.image = np.full((100, 100, 3), 80, dtype=np.uint8)
        pano_data = np.full((40, 120, 3), 100, dtype=np.uint8)

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

        # Focus mode returns early
        worker.config['FOCUS_MODE'] = True
        worker.write_panorama_img(pano_data, mock_i_ref, cam, jpeg_exif=b"")
        worker.config['FOCUS_MODE'] = False

        # Daytime save disabled
        worker.night_av[constants.NIGHT_NIGHT] = 0
        worker.config['DAYTIME_CAPTURE'] = True
        worker.config['DAYTIME_CAPTURE_SAVE'] = False
        worker.write_panorama_img(pano_data, mock_i_ref, cam, jpeg_exif=b"")

        # Normal night save
        worker.night_av[constants.NIGHT_NIGHT] = 1
        worker.write_panorama_img(pano_data, mock_i_ref, cam, jpeg_exif=b"")
        latest_pano = worker.image_dir.joinpath('panorama.jpg')
        assert latest_pano.exists()


def test_image_worker_write_fit(image_worker_setup, app):
    from astropy.io import fits

    worker = image_worker_setup
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

        hdu = fits.PrimaryHDU(np.zeros((16, 16), dtype=np.uint16))
        mock_i_ref.hdulist = fits.HDUList([hdu])

        # Next save fits in the future -> skip
        worker.next_save_fits_time = 9999999999
        worker.write_fit(mock_i_ref, cam)

        # Ready to save: daytime capture disabled -> skip
        worker.next_save_fits_time = 0
        worker.night_av[constants.NIGHT_NIGHT] = 0
        worker.config['DAYTIME_CAPTURE_SAVE'] = False
        worker.write_fit(mock_i_ref, cam)

        # Ready to save: uncompressed FITS
        worker.next_save_fits_time = 0
        worker.night_av[constants.NIGHT_NIGHT] = 1
        worker.config['IMAGE_SAVE_FITS_COMPRESSED'] = False
        worker.write_fit(mock_i_ref, cam)

        # Ready to save: compressed FITS
        worker.next_save_fits_time = 0
        worker.config['IMAGE_SAVE_FITS_COMPRESSED'] = True
        worker.write_fit(mock_i_ref, cam)


def test_image_worker_upload_metadata(image_worker_setup, app):
    worker = image_worker_setup
    worker.image_processor.update_astrometric_data(datetime.now())
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

        # Disabled in config
        worker.config['FILETRANSFER'] = {'UPLOAD_METADATA': False}
        worker.upload_metadata(mock_i_ref, 128.0, 127.0)

        # UPLOAD_IMAGE disabled
        worker.config['FILETRANSFER'] = {'UPLOAD_METADATA': True, 'UPLOAD_IMAGE': False}
        worker.upload_metadata(mock_i_ref, 128.0, 127.0)

        # Enabled with count skip and success
        worker.config['FILETRANSFER'] = {
            'UPLOAD_METADATA': True,
            'UPLOAD_IMAGE': 2,
            'REMOTE_METADATA_FOLDER': '/metadata/{tod}',
            'REMOTE_METADATA_NAME': 'meta.json',
        }
        # First call skipped (count=1 % 2 != 0)
        worker.upload_metadata(mock_i_ref, 128.0, 127.0)
        assert worker.upload_q.qsize() == 0

        # Second call uploaded (count=2 % 2 == 0)
        worker.upload_metadata(mock_i_ref, 128.0, 127.0)
        assert worker.upload_q.qsize() == 1


def test_image_worker_asi676mc_extensions(image_worker_setup):
    worker = image_worker_setup
    assert worker._asi676mc_diagnostic_extension(Path('test.fits.gz')) == 'fits.gz'
    assert worker._asi676mc_diagnostic_extension(Path('test.fit.gz')) == 'fit.gz'
    assert worker._asi676mc_diagnostic_extension(Path('test.fits')) == 'fits'
    assert worker._asi676mc_diagnostic_extension(Path('test.fit')) == 'fit'

    with pytest.raises(ValueError, match='is not a FITS file'):
        worker._asi676mc_diagnostic_extension(Path('test.png'))


def test_image_worker_process_sqm_exposure(image_worker_setup, app, tmp_path):
    worker = image_worker_setup
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        fits_file = tmp_path / "sqm_test.fits"
        fits_file.write_bytes(b"FITS dummy")

        mock_i_ref = MagicMock()
        mock_i_ref.libcamera_black_level = 64
        worker.image_processor._add = MagicMock(return_value=mock_i_ref)
        worker.image_processor.correct_asi676mc_frame = MagicMock()
        worker.image_processor._calibrate = MagicMock()
        worker.image_processor._calculateMagnitudeSqm = MagicMock(return_value=(21.5, 20.0, 128.0))

        worker.process_sqm_exposure(
            fits_file,
            1.0,
            100.0,
            1,
            datetime.now(),
            1.0,
            cam,
            0,
        )
        assert not fits_file.exists()
        assert worker.sensors_user_av[constants.SENSOR_USER_CAMERA_SQM_MAG] == pytest.approx(21.5, rel=1e-2)


def test_image_worker_process_image_safeguards(image_worker_setup, app, tmp_path):
    worker = image_worker_setup
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()

        # Nonexistent frame
        missing_file = tmp_path / "missing.jpg"
        worker.processImage({
            'filename': str(missing_file),
            'exposure': 1.0,
            'gain': 100.0,
            'binning': 1,
            'exp_time': datetime.now().timestamp(),
            'exp_elapsed': 1.0,
            'camera_id': cam.id,
        })

        # Empty frame
        empty_file = tmp_path / "empty.jpg"
        empty_file.touch()
        worker.processImage({
            'filename': str(empty_file),
            'exposure': 1.0,
            'gain': 100.0,
            'binning': 1,
            'exp_time': datetime.now().timestamp(),
            'exp_elapsed': 1.0,
            'camera_id': cam.id,
        })
        assert not empty_file.exists()
