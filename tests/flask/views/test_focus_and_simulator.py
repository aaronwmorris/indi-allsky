import os
import io
import json
import base64
import numpy as np
import cv2
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock
from indi_allsky.config import IndiAllSkyConfig
from indi_allsky.flask import db
from indi_allsky.flask.base_views import BaseView
from indi_allsky.flask.views import JsonFocusView
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbConfigTable,
    IndiAllSkyDbUserTable,
    IndiAllSkyDbTaskQueueTable,
)
from indi_allsky.flask.forms import IndiAllskyImageViewer


@pytest.fixture
def focus_db(flask_app):
    """Seed database for focus and viewer tests."""
    with flask_app.app_context():
        db.session.query(IndiAllSkyDbTaskQueueTable).delete()
        db.session.query(IndiAllSkyDbCameraTable).delete()
        db.session.query(IndiAllSkyDbConfigTable).delete()
        db.session.query(IndiAllSkyDbUserTable).delete()
        db.session.commit()

        camera = IndiAllSkyDbCameraTable(
            id=1,
            name="main_camera",
            driver="indi_asi_ccd",
            friendlyName="Camera 1",
            uuid="44444444-4444-4444-4444-444444444444",
            latitude=-34.0,
            longitude=138.0,
            elevation=50,
            nightSunAlt=-6.0,
            local=True,
            hidden=False,
            utc_offset=36000.0,
            lensFocalLength=4.0,
            lensFocalRatio=2.0,
            lensImageCircle=180.0,
            cfa=None,
            owner="Admin",
            connectDate=db.func.now(),
            width=1920,
            height=1080,
            pixelSize=2.4,
        )
        db.session.add(camera)

        config_entry = IndiAllSkyDbConfigTable(
            data={
                'WEBSITE': {'TITLE': 'indi-allsky'},
                'IMAGE_FILE_TYPE': 'jpg',
                'IMAGE_FOLDER': '/tmp',
                'INDI_PORT': 7624,
                'FOCUS_MODE': True,
                'FOCUSER': {'CLASSNAME': 'gpio_stepper'},
            },
            level="1.0",
            note='test config',
        )
        db.session.add(config_entry)

        admin = IndiAllSkyDbUserTable(
            username="admin",
            password="hashed_password",
            email="admin@example.org",
            name="Admin",
            active=True,
            admin=True,
        )
        db.session.add(admin)

        system_user = IndiAllSkyDbUserTable(
            username="system",
            password="hashed_password",
            email="system@example.org",
            name="System",
            active=True,
            admin=True,
        )
        db.session.add(system_user)

        db.session.commit()
        yield
        db.session.remove()


def test_focus_view_rendering(flask_app, focus_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        res = client.get('/indi-allsky/focus?camera_id=1')
        assert res.status_code == 200


def test_json_focus_view_missing_image(flask_app, focus_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        # Ensure latest.jpg does not exist in /tmp
        latest_img = Path('/tmp/latest.jpg')
        if latest_img.exists():
            latest_img.unlink()

        res = client.get('/indi-allsky/js/focus?camera_id=1&zoom=2&x_offset=0&y_offset=0')
        assert res.status_code == 400


def test_json_focus_view_with_image_formats(flask_app, focus_db, tmp_path):
    client = flask_app.test_client()

    img = np.zeros((400, 400, 3), dtype=np.uint8)
    cv2.circle(img, (200, 200), 20, (255, 255, 255), -1)

    # 1. JPEG decode error branch
    bad_jpg = Path('/tmp/latest.jpg')
    bad_jpg.write_bytes(b'not a jpeg')
    try:
        with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
            res = client.get('/indi-allsky/js/focus?camera_id=1')
            assert res.status_code == 400
    finally:
        if bad_jpg.exists():
            bad_jpg.unlink()

    # 2. PNG format branch
    png_img = Path('/tmp/latest.png')
    cv2.imwrite(str(png_img), img)
    cfg_png = {'IMAGE_FOLDER': '/tmp', 'IMAGE_FILE_TYPE': 'png', 'FOCUS_MODE': False, 'ENCRYPT_PASSWORDS': False}
    try:
        with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
            with patch.object(IndiAllSkyConfig, 'config', new_callable=PropertyMock, return_value=cfg_png):
                with patch('indi_allsky.stars.IndiAllSkyStars.detectObjects', return_value=[]):
                    res = client.get('/indi-allsky/js/focus?camera_id=1')
                    assert res.status_code == 200
    finally:
        if png_img.exists():
            png_img.unlink()

    # 3. FITS format branch
    fits_img = Path('/tmp/latest.fits')
    mock_hdu = MagicMock()
    mock_hdu.data = np.zeros((3, 400, 400), dtype=np.uint8)
    cfg_fits = {'IMAGE_FOLDER': '/tmp', 'IMAGE_FILE_TYPE': 'fits', 'FOCUS_MODE': False, 'ENCRYPT_PASSWORDS': False}
    try:
        with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
            with patch.object(IndiAllSkyConfig, 'config', new_callable=PropertyMock, return_value=cfg_fits):
                with patch('astropy.io.fits.open', return_value=[mock_hdu]):
                    with patch('indi_allsky.stars.IndiAllSkyStars.detectObjects', return_value=[]):
                        fits_img.touch()
                        res = client.get('/indi-allsky/js/focus?camera_id=1')
                        assert res.status_code == 200
    finally:
        if fits_img.exists():
            fits_img.unlink()

    # 4. FITS open error branch
    try:
        with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
            with patch.object(IndiAllSkyConfig, 'config', new_callable=PropertyMock, return_value=cfg_fits):
                with patch('astropy.io.fits.open', side_effect=OSError('FITS error')):
                    fits_img.touch()
                    res = client.get('/indi-allsky/js/focus?camera_id=1')
                    assert res.status_code == 400
    finally:
        if fits_img.exists():
            fits_img.unlink()

    # 5. PIL image format (e.g. .tif) branch
    tif_img = Path('/tmp/latest.tif')
    tif_img.touch()
    cfg_tif = {'IMAGE_FOLDER': '/tmp', 'IMAGE_FILE_TYPE': 'tif', 'FOCUS_MODE': False, 'ENCRYPT_PASSWORDS': False}
    try:
        with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
            with patch.object(IndiAllSkyConfig, 'config', new_callable=PropertyMock, return_value=cfg_tif):
                with patch('PIL.Image.open') as mock_pil:
                    mock_pil.return_value.__enter__.return_value = img
                    with patch('indi_allsky.stars.IndiAllSkyStars.detectObjects', return_value=[]):
                        res = client.get('/indi-allsky/js/focus?camera_id=1')
                        assert res.status_code == 200
    finally:
        if tif_img.exists():
            tif_img.unlink()


def test_ajax_focus_controller_exceptions(flask_app, focus_db):
    from indi_allsky.devices.exceptions import DeviceControlException
    client = flask_app.test_client()

    payload = {
        'DIRECTION': 'IN',
        'STEP_DEGREES': 12,
    }

    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        with patch('indi_allsky.flask.views.current_user') as mock_user:
            mock_user.is_admin = True
            with patch('indi_allsky.flask.views.AjaxFocusControllerView.verify_admin_network', return_value=True):
                # SystemError during init
                with patch('indi_allsky.focuser.IndiAllSkyFocuserInterface', side_effect=SystemError('Init error')):
                    res = client.post('/indi-allsky/ajax/focuscontroller?camera_id=1', json=payload)
                    assert res.status_code == 400
                    assert 'focuser_error' in res.get_json()

                # DeviceControlException during move
                mock_focuser = MagicMock()
                mock_focuser.move.side_effect = DeviceControlException('Move error')
                with patch('indi_allsky.focuser.IndiAllSkyFocuserInterface', return_value=mock_focuser):
                    res_m = client.post('/indi-allsky/ajax/focuscontroller?camera_id=1', json=payload)
                    assert res_m.status_code == 400
                    assert 'focuser_error' in res_m.get_json()


def test_image_viewer_view(flask_app, focus_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        res = client.get('/indi-allsky/imageviewer?camera_id=1')
        assert res.status_code == 200


def test_ajax_image_viewer_view_queries(flask_app, focus_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        # Query with year, month, day, hour
        payload_hour = {
            'CAMERA_ID': 1,
            'YEAR_SELECT': 2026,
            'MONTH_SELECT': 9,
            'DAY_SELECT': 18,
            'HOUR_SELECT': 12,
            'FILTER_DETECTIONS': False,
        }
        with patch.object(IndiAllskyImageViewer, 'getImages', lambda self, *a, **k: []):
            res_h = client.post('/indi-allsky/ajax/imageviewer?camera_id=1', json=payload_hour)
            assert res_h.status_code == 200
            assert 'IMAGE_DATA' in res_h.get_json()

        # Query with year, month, day
        payload_day = {
            'CAMERA_ID': 1,
            'YEAR_SELECT': 2026,
            'MONTH_SELECT': 9,
            'DAY_SELECT': 18,
            'HOUR_SELECT': -1,
            'FILTER_DETECTIONS': True,
        }
        with patch.object(IndiAllskyImageViewer, 'getHours', lambda self, *a, **k: [(12, '12:00')]):
            with patch.object(IndiAllskyImageViewer, 'getImages', lambda self, *a, **k: []):
                res_d = client.post('/indi-allsky/ajax/imageviewer?camera_id=1', json=payload_day)
                assert res_d.status_code == 200
                assert 'HOUR_SELECT' in res_d.get_json()

        # Query with year, month
        payload_month = {
            'CAMERA_ID': 1,
            'YEAR_SELECT': 2026,
            'MONTH_SELECT': 9,
            'DAY_SELECT': 0,
            'HOUR_SELECT': -1,
            'FILTER_DETECTIONS': False,
        }
        with patch.object(IndiAllskyImageViewer, 'getDays', lambda self, *a, **k: [(18, '18')]):
            with patch.object(IndiAllskyImageViewer, 'getHours', lambda self, *a, **k: [(12, '12:00')]):
                with patch.object(IndiAllskyImageViewer, 'getImages', lambda self, *a, **k: []):
                    res_m = client.post('/indi-allsky/ajax/imageviewer?camera_id=1', json=payload_month)
                    assert res_m.status_code == 200
                    assert 'DAY_SELECT' in res_m.get_json()

        # Query with year only
        payload_year = {
            'CAMERA_ID': 1,
            'YEAR_SELECT': 2026,
            'MONTH_SELECT': 0,
            'DAY_SELECT': 0,
            'HOUR_SELECT': -1,
            'FILTER_DETECTIONS': False,
        }
        with patch.object(IndiAllskyImageViewer, 'getMonths', lambda self, *a, **k: [(9, 'September')]):
            with patch.object(IndiAllskyImageViewer, 'getDays', lambda self, *a, **k: [(18, '18')]):
                with patch.object(IndiAllskyImageViewer, 'getHours', lambda self, *a, **k: [(12, '12:00')]):
                    with patch.object(IndiAllskyImageViewer, 'getImages', lambda self, *a, **k: []):
                        res_y = client.post('/indi-allsky/ajax/imageviewer?camera_id=1', json=payload_year)
                        assert res_y.status_code == 200
                        assert 'MONTH_SELECT' in res_y.get_json()

        # Query fallback (no year selected)
        payload_fallback = {
            'CAMERA_ID': 1,
            'YEAR_SELECT': 0,
            'MONTH_SELECT': 0,
            'DAY_SELECT': 0,
            'HOUR_SELECT': -1,
            'FILTER_DETECTIONS': False,
        }
        with patch.object(IndiAllskyImageViewer, 'getYears', lambda self, *a, **k: []):
            res_fb = client.post('/indi-allsky/ajax/imageviewer?camera_id=1', json=payload_fallback)
            assert res_fb.status_code == 200
            assert 'YEAR_SELECT' in res_fb.get_json()
