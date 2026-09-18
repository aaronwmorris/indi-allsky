import os
import io
import json
import pytest
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import dbus
from indi_allsky.flask import db
from indi_allsky.flask.views import (
    AjaxSetTimeView,
    AjaxSetTimezoneView,
    FitsImageViewerView,
    AjaxFitsImageViewerView,
    Fits2JpegView,
    GalleryViewerView,
    AjaxGalleryViewerView,
)
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbConfigTable,
    IndiAllSkyDbUserTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbFitsImageTable,
    IndiAllSkyDbTaskQueueTable,
)
from indi_allsky.flask.forms import (
    IndiAllskyFitsImageViewer,
    IndiAllskyGalleryViewer,
)


@pytest.fixture
def gallery_db(flask_app):
    """Seed database for gallery, FITS viewer, and task endpoints."""
    with flask_app.app_context():
        db.session.query(IndiAllSkyDbTaskQueueTable).delete()
        db.session.query(IndiAllSkyDbFitsImageTable).delete()
        db.session.query(IndiAllSkyDbImageTable).delete()
        db.session.query(IndiAllSkyDbCameraTable).delete()
        db.session.query(IndiAllSkyDbConfigTable).delete()
        db.session.query(IndiAllSkyDbUserTable).delete()
        db.session.commit()

        camera = IndiAllSkyDbCameraTable(
            id=1,
            name="main_camera",
            driver="indi_asi_ccd",
            friendlyName="Camera 1",
            uuid="cam1_uuid",
            lensImageCircle=1000,
            latitude=-34.0,
            longitude=138.0,
            elevation=0.0,
            nightSunAlt=-6.0,
        )
        db.session.add(camera)

        system_user = IndiAllSkyDbUserTable(
            username="system",
            email="system@example.com",
            password="pass",
            admin=True,
        )
        db.session.add(system_user)

        admin_user = IndiAllSkyDbUserTable(
            username="admin",
            email="admin@example.com",
            password="pass",
            admin=True,
        )
        db.session.add(admin_user)

        normal_user = IndiAllSkyDbUserTable(
            username="user",
            email="user@example.com",
            password="pass",
            admin=False,
        )
        db.session.add(normal_user)

        config = IndiAllSkyDbConfigTable(
            id=1,
            level=1,
            note="Initial config",
            data={
                "IMAGE_FOLDER": "/tmp",
                "IMAGE_FILE_TYPE": "jpg",
                "IMAGE_FILE_COMPRESSION": {"jpg": 85},
                "ENCRYPT_PASSWORDS": False,
            },
        )
        db.session.add(config)
        db.session.commit()
        yield


def test_ajax_set_time_and_timezone_views(flask_app, gallery_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        # 1. Invalid time payload
        res = client.post('/indi-allsky/ajax/settime', json={})
        assert res.status_code == 400

        # 2. DBus exception handling on settime
        with patch.object(AjaxSetTimeView, 'setTimeSystemd', side_effect=dbus.exceptions.DBusException('DBus mock err')):
            res = client.post('/indi-allsky/ajax/settime', json={'NEW_DATETIME': '2026-09-19T01:00:00'})
            assert res.status_code == 400
            assert 'DBus Error' in res.get_json()['form_settime_global'][0]

        # 3. Successful settime call (with mocked setTimeSystemd)
        with patch.object(AjaxSetTimeView, 'setTimeSystemd', return_value=True):
            res = client.post('/indi-allsky/ajax/settime', json={'NEW_DATETIME': '2026-09-19T01:00:00'})
            assert res.status_code == 200
            assert res.get_json()['success-message'] == 'System time updated.'

        # 4. Invalid timezone payload
        res = client.post('/indi-allsky/ajax/settimezone', json={})
        assert res.status_code == 400

        # 5. DBus exception handling on settimezone
        with patch.object(AjaxSetTimezoneView, 'setTimezoneSystemd', side_effect=dbus.exceptions.DBusException('DBus tz mock err')):
            res = client.post('/indi-allsky/ajax/settimezone', json={'NEW_TIMEZONE': 'UTC'})
            assert res.status_code == 400
            assert 'DBus Error' in res.get_json()['form_timezone_global'][0]

        # 6. Successful settimezone call (with mocked setTimezoneSystemd)
        with patch.object(AjaxSetTimezoneView, 'setTimezoneSystemd', return_value=True):
            res = client.post('/indi-allsky/ajax/settimezone', json={'NEW_TIMEZONE': 'UTC'})
            assert res.status_code == 200
            assert res.get_json()['success-message'] == 'System timezone updated.'


def test_fits_image_viewer_and_ajax_views(flask_app, gallery_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        # GET page
        res = client.get('/indi-allsky/fitsimageviewer?camera_id=1')
        assert res.status_code == 200

        # POST ajax query with hour >= 0
        with patch.object(IndiAllskyFitsImageViewer, 'getImages', lambda self, *a, **k: ['fits1.fits']):
            res = client.post('/indi-allsky/ajax/fitsimageviewer', json={
                'CAMERA_ID': 1,
                'YEAR_SELECT': 2026,
                'MONTH_SELECT': 9,
                'DAY_SELECT': 19,
                'HOUR_SELECT': 1,
            })
            assert res.status_code == 200
            assert res.get_json()['IMAGE_DATA'] == ['fits1.fits']


def test_fits2jpeg_view(flask_app, gallery_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        # 1. 404 for missing FITS entry
        res = client.get('/indi-allsky/fits2jpeg?id=999')
        assert res.status_code == 404

        # 2. Convert existing FITS entry
        now_dt = datetime.now()
        fits_file = Path('/tmp/test_fits2jpeg.fits')
        fits_file.touch()

        with flask_app.app_context():
            fits_entry = IndiAllSkyDbFitsImageTable(
                id=10,
                camera_id=1,
                createDate=now_dt,
                dayDate=now_dt.date(),
                exposure=1.0,
                gain=100.0,
                filename=str(fits_file),
            )
            db.session.add(fits_entry)
            db.session.commit()

        try:
            mock_hdu = MagicMock()
            mock_hdu.header = {'EXPTIME': 1.0, 'GAIN': 100.0, 'XBINNING': 1, 'CCD-TEMP': 10.0}
            mock_hdulist = MagicMock()
            mock_hdulist.__getitem__.return_value = mock_hdu
            with patch('astropy.io.fits.open', return_value=mock_hdulist):
                with patch('indi_allsky.flask.views.ImageProcessor') as mock_proc_cls:
                    mock_proc = MagicMock()
                    mock_proc.image = np.zeros((100, 100, 3), dtype=np.uint8)
                    mock_proc_cls.return_value = mock_proc
                    res = client.get('/indi-allsky/fits2jpeg?id=10')
                    assert res.status_code == 200
                    assert res.mimetype == 'image/jpeg'
        finally:
            if fits_file.exists():
                fits_file.unlink()


def test_gallery_viewer_views(flask_app, gallery_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        # GET page
        res = client.get('/indi-allsky/gallery?camera_id=1')
        assert res.status_code == 200

        # POST ajax gallery query
        with patch.object(IndiAllskyGalleryViewer, 'getImages', lambda self, *a, **k: ['img1.jpg']):
            res = client.post('/indi-allsky/ajax/gallery', json={
                'CAMERA_ID': 1,
                'YEAR_SELECT': 2026,
                'MONTH_SELECT': 9,
                'DAY_SELECT': 19,
                'HOUR_SELECT': 1,
                'FILTER_DETECTIONS': False,
            })
            assert res.status_code == 200
            assert res.get_json()['IMAGE_DATA'] == ['img1.jpg']


def test_video_and_mini_video_viewer_views(flask_app, gallery_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        # 1. Timelapse Video Viewer GET & POST
        res = client.get('/indi-allsky/videoviewer?camera_id=1')
        assert res.status_code == 200

        res = client.post('/indi-allsky/ajax/videoviewer', json={
            'CAMERA_ID': 1,
            'YEAR_SELECT': 2026,
            'MONTH_SELECT': 9,
            'TIMEOFDAY_SELECT': 'night',
        })
        assert res.status_code == 200

        # 2. Mini Video Viewer GET & POST
        res = client.get('/indi-allsky/minivideoviewer?camera_id=1')
        assert res.status_code == 200

        res = client.post('/indi-allsky/ajax/minivideoviewer', json={
            'CAMERA_ID': 1,
            'YEAR_SELECT': 2026,
            'MONTH_SELECT': 9,
        })
        assert res.status_code == 200


def test_ajax_mini_video_delete_view(flask_app, gallery_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        # 1. Invalid payload (400)
        res = client.post('/indi-allsky/ajax/minivideoviewer/delete', json={})
        assert res.status_code == 400

        # 2. Mini video not found (404)
        res = client.post('/indi-allsky/ajax/minivideoviewer/delete', json={'CAMERA_ID': 1, 'VIDEO_ID': 999})
        assert res.status_code == 404
