import os
import tempfile
import io
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import numpy as np
import pytest
import requests
from astropy.io import fits
from passlib.hash import argon2

from indi_allsky import constants
from indi_allsky.config import IndiAllSkyConfigBase
from indi_allsky.flask.forms import (
    IndiAllskyFitsImageViewer,
    IndiAllskyFitsImageViewerPreload,
    IndiAllskyImageProcessingForm,
)
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbConfigTable,
    IndiAllSkyDbUserTable,
    IndiAllSkyDbFitsImageTable,
)


def _generate_dummy_fits_bytes(width=100, height=100):
    """Generate in-memory FITS file bytes with standard headers."""
    data = np.full((height, width), 500, dtype=np.uint16)
    hdu = fits.PrimaryHDU(data)
    hdu.header['EXPTIME'] = 1.0
    hdu.header['GAIN'] = 100.0
    hdu.header['XBINNING'] = 1
    hdu.header['CCD-TEMP'] = 20.0
    buf = io.BytesIO()
    hdu.writeto(buf)
    return buf.getvalue()


@pytest.fixture
def populated_fits_env(flask_app, db, tmp_path):
    """Seed test database with camera, config, admin user, and dummy FITS files."""
    with flask_app.app_context():
        cfg = dict(IndiAllSkyConfigBase._base_config)
        cfg['IMAGE_FOLDER'] = str(tmp_path / 'images')
        cfg['VARLIB_FOLDER'] = str(tmp_path / 'varlib')
        cfg['LOCATION_LATITUDE'] = -34.9285
        cfg['LOCATION_LONGITUDE'] = 138.6007
        cfg['LOCATION_ELEVATION'] = 50
        cfg['NIGHT_SUN_ALT_DEG'] = -6.0
        cfg['CAMERA_INTERFACE'] = 'indi_simulator_ccd'

        config_entry = IndiAllSkyDbConfigTable(
            data=cfg,
            level='1.0',
            note='test',
        )
        db.session.add(config_entry)

        camera = IndiAllSkyDbCameraTable(
            name='main_camera',
            uuid='cam-main-uuid-1',
            driver='indi_simulator_ccd',
            friendlyName='Main Camera',
            latitude=-34.9285,
            longitude=138.6007,
            elevation=50,
            nightSunAlt=-6.0,
            lensFocalLength=2.5,
            lensFocalRatio=1.4,
            lensImageCircle=1000,
            width=100,
            height=100,
            pixelSize=2.9,
            cfa=constants.CFA_RGGB,
            owner='Admin',
            local=True,
            minExposure=0.0001,
            maxExposure=60.0,
            minGain=0,
            maxGain=100,
            minBinning=1,
            maxBinning=4,
            s3_prefix='https://mybucket.s3.amazonaws.com/allsky',
            web_nonlocal_images=False,
        )
        db.session.add(camera)

        admin_user = IndiAllSkyDbUserTable(
            username='admin',
            password=argon2.hash('AdminPassword123!'),
            email='admin@example.org',
            name='Admin User',
            active=True,
            admin=True,
            staff=True,
        )
        db.session.add(admin_user)
        db.session.commit()
        yield


@pytest.fixture
def auth_client(flask_app, populated_fits_env):
    """Provide an authenticated test client logged in as admin."""
    client = flask_app.test_client()
    res = client.post(
        '/indi-allsky/login',
        json={'USERNAME': 'admin', 'PASSWORD': 'AdminPassword123!', 'NEXT': ''},
    )
    assert res.status_code == 200
    return client


# ==============================================================================
# Model Tests: IndiAllSkyDbFileBase / IndiAllSkyDbFitsImageTable
# ==============================================================================

def test_get_url_local(flask_app, db):
    """Test getUrl() with local=True returns relative local URL."""
    with flask_app.app_context():
        fits_img = IndiAllSkyDbFitsImageTable(
            camera_id=1,
            filename='/var/www/html/allsky/images/20260908/fits/test.fit',
            exposure=1.0,
            gain=100.0,
            binmode=1,
            dayDate=datetime(2026, 9, 8).date(),
        )
        db.session.add(fits_img)
        db.session.commit()

        local_url = fits_img.getUrl(local=True)
        assert str(local_url) == 'images/20260908/fits/test.fit'


def test_get_url_remote_url(flask_app, db):
    """Test getUrl() with local=False returns remote_url when set."""
    with flask_app.app_context():
        fits_img = IndiAllSkyDbFitsImageTable(
            camera_id=1,
            filename='/var/www/html/allsky/images/20260908/fits/test.fit',
            remote_url='https://cdn.example.org/fits/test.fit',
            exposure=1.0,
            gain=100.0,
            binmode=1,
            dayDate=datetime(2026, 9, 8).date(),
        )
        db.session.add(fits_img)
        db.session.commit()

        url = fits_img.getUrl(local=False)
        assert url == 'https://cdn.example.org/fits/test.fit'


@pytest.mark.parametrize(
    'prefix, key, expected',
    [
        (
            'https://s3.example.com/bucket',
            'cam_1/fits/image.fits',
            'https://s3.example.com/bucket/cam_1/fits/image.fits',
        ),
        (
            'https://s3.example.com/bucket/',
            'cam_1/fits/image.fits',
            'https://s3.example.com/bucket/cam_1/fits/image.fits',
        ),
        (
            'https://s3.example.com/bucket/',
            '/cam_1/fits/image.fits',
            'https://s3.example.com/bucket/cam_1/fits/image.fits',
        ),
        (
            'https://s3.example.com/bucket',
            '/cam_1/fits/image.fits',
            'https://s3.example.com/bucket/cam_1/fits/image.fits',
        ),
    ],
)
def test_get_url_s3_prefix_and_key(flask_app, db, prefix, key, expected):
    """Test getUrl() formats S3 URL properly and normalizes slashes."""
    with flask_app.app_context():
        fits_img = IndiAllSkyDbFitsImageTable(
            camera_id=1,
            filename='/var/www/html/allsky/images/20260908/fits/test.fit',
            s3_key=key,
            exposure=1.0,
            gain=100.0,
            binmode=1,
            dayDate=datetime(2026, 9, 8).date(),
        )
        db.session.add(fits_img)
        db.session.commit()

        url = fits_img.getUrl(s3_prefix=prefix, local=False)
        assert url == expected


def test_get_url_nonlocal_fallback_to_local(flask_app, db):
    """Test getUrl() falls back to local URL if local=False but no remote URL or S3 key exists."""
    with flask_app.app_context():
        fits_img = IndiAllSkyDbFitsImageTable(
            camera_id=1,
            filename='/var/www/html/allsky/images/20260908/fits/test.fit',
            exposure=1.0,
            gain=100.0,
            binmode=1,
            dayDate=datetime(2026, 9, 8).date(),
        )
        db.session.add(fits_img)
        db.session.commit()

        url = fits_img.getUrl(local=False)
        assert str(url) == 'images/20260908/fits/test.fit'


def test_get_local_or_cached_path_local_hit(flask_app, db, tmp_path):
    """Test getLocalOrCachedPath returns Path to existing local file without remote request."""
    local_file = tmp_path / 'test.fit'
    local_file.write_bytes(b'DUMMY_FITS_DATA')

    with flask_app.app_context():
        fits_img = IndiAllSkyDbFitsImageTable(
            camera_id=1,
            filename=str(local_file),
            exposure=1.0,
            gain=100.0,
            binmode=1,
            dayDate=datetime(2026, 9, 8).date(),
        )
        db.session.add(fits_img)
        db.session.commit()

        with patch('requests.get') as mock_get:
            result = fits_img.getLocalOrCachedPath()
            assert result == local_file
            mock_get.assert_not_called()


def test_get_local_or_cached_path_remote_download_and_cache(flask_app, db):
    """Test getLocalOrCachedPath downloads missing file from remote URL and caches it."""
    dummy_fits_data = _generate_dummy_fits_bytes(50, 50)
    remote_url = 'https://s3.example.com/allsky/cam_1/fits/image.fits'

    with flask_app.app_context():
        fits_img = IndiAllSkyDbFitsImageTable(
            camera_id=1,
            filename='/nonexistent/local/path/image.fits',
            remote_url=remote_url,
            exposure=1.0,
            gain=100.0,
            binmode=1,
            dayDate=datetime(2026, 9, 8).date(),
        )
        db.session.add(fits_img)
        db.session.commit()

        # Mock streaming response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.__enter__.return_value = mock_response
        mock_response.iter_content.return_value = [dummy_fits_data]
        mock_response.raise_for_status = MagicMock()

        with patch('requests.get', return_value=mock_response) as mock_get:
            cached_path = fits_img.getLocalOrCachedPath()

            assert cached_path is not None
            assert cached_path.is_file()
            assert cached_path.name.endswith('.fits')
            assert cached_path.read_bytes() == dummy_fits_data
            mock_get.assert_called_once_with(remote_url, stream=True, timeout=30.0)

            # Subsequent call should hit cache without calling requests.get again
            mock_get.reset_mock()
            second_path = fits_img.getLocalOrCachedPath()
            assert second_path == cached_path
            mock_get.assert_not_called()

        if cached_path and cached_path.is_file():
            cached_path.unlink()


def test_get_local_or_cached_path_s3_key_fallback(flask_app, db):
    """Test getLocalOrCachedPath downloads using s3_prefix + s3_key when remote_url is None."""
    dummy_fits_data = _generate_dummy_fits_bytes(50, 50)
    s3_prefix = 'https://mybucket.s3.amazonaws.com/allsky'
    s3_key = 'cam_1/fits/20260908/image.fits'

    with flask_app.app_context():
        fits_img = IndiAllSkyDbFitsImageTable(
            camera_id=1,
            filename='/nonexistent/local/path/image.fits',
            s3_key=s3_key,
            exposure=1.0,
            gain=100.0,
            binmode=1,
            dayDate=datetime(2026, 9, 8).date(),
        )
        db.session.add(fits_img)
        db.session.commit()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.__enter__.return_value = mock_response
        mock_response.iter_content.return_value = [dummy_fits_data]
        mock_response.raise_for_status = MagicMock()

        with patch('requests.get', return_value=mock_response) as mock_get:
            cached_path = fits_img.getLocalOrCachedPath(s3_prefix=s3_prefix)

            assert cached_path is not None
            assert cached_path.is_file()
            assert cached_path.read_bytes() == dummy_fits_data
            mock_get.assert_called_once_with(
                'https://mybucket.s3.amazonaws.com/allsky/cam_1/fits/20260908/image.fits',
                stream=True,
                timeout=30.0,
            )

        if cached_path and cached_path.is_file():
            cached_path.unlink()


def test_get_local_or_cached_path_remote_404_returns_none(flask_app, db):
    """Test getLocalOrCachedPath returns None when remote download fails with 404."""
    with flask_app.app_context():
        fits_img = IndiAllSkyDbFitsImageTable(
            camera_id=1,
            filename='/nonexistent/local/path/image.fits',
            remote_url='https://s3.example.com/allsky/missing.fits',
            exposure=1.0,
            gain=100.0,
            binmode=1,
            dayDate=datetime(2026, 9, 8).date(),
        )
        db.session.add(fits_img)
        db.session.commit()

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.__enter__.return_value = mock_response
        mock_response.raise_for_status.side_effect = requests.HTTPError('404 Not Found')

        with patch('requests.get', return_value=mock_response):
            result = fits_img.getLocalOrCachedPath()
            assert result is None


def test_get_local_or_cached_path_connection_error_returns_none(flask_app, db):
    """Test getLocalOrCachedPath returns None when connection fails."""
    with flask_app.app_context():
        fits_img = IndiAllSkyDbFitsImageTable(
            camera_id=1,
            filename='/nonexistent/local/path/image.fits',
            remote_url='https://s3.example.com/allsky/error.fits',
            exposure=1.0,
            gain=100.0,
            binmode=1,
            dayDate=datetime(2026, 9, 8).date(),
        )
        db.session.add(fits_img)
        db.session.commit()

        with patch('requests.get', side_effect=requests.ConnectionError('Network unreachable')):
            result = fits_img.getLocalOrCachedPath()
            assert result is None


def test_get_local_or_cached_path_no_sources_returns_none(flask_app, db):
    """Test getLocalOrCachedPath returns None when local file is missing and no remote URL/key."""
    with flask_app.app_context():
        fits_img = IndiAllSkyDbFitsImageTable(
            camera_id=1,
            filename='/nonexistent/local/path/image.fits',
            exposure=1.0,
            gain=100.0,
            binmode=1,
            dayDate=datetime(2026, 9, 8).date(),
        )
        db.session.add(fits_img)
        db.session.commit()

        result = fits_img.getLocalOrCachedPath()
        assert result is None


# ==============================================================================
# Form Tests: IndiAllskyFitsImageViewer & IndiAllskyFitsImageViewerPreload
# ==============================================================================

def test_fits_form_filters_local_vs_nonlocal(flask_app, db):
    """Test IndiAllskyFitsImageViewer filters out local-only images when local=False."""
    now = datetime(2026, 9, 8, 22, 15, 0, tzinfo=timezone.utc)

    with flask_app.app_context():
        # Image 1: local-only
        img_local = IndiAllSkyDbFitsImageTable(
            camera_id=1,
            filename='/var/www/html/allsky/images/20260908/fits/local_only.fit',
            createDate=now,
            createDate_year=now.year,
            createDate_month=now.month,
            createDate_day=now.day,
            createDate_hour=now.hour,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
            binmode=1,
        )
        # Image 2: S3 remote
        img_remote = IndiAllSkyDbFitsImageTable(
            camera_id=1,
            filename='/var/www/html/allsky/images/20260908/fits/remote_s3.fit',
            s3_key='cam_1/fits/20260908/remote_s3.fit',
            createDate=now,
            createDate_year=now.year,
            createDate_month=now.month,
            createDate_day=now.day,
            createDate_hour=now.hour,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
            binmode=1,
        )
        db.session.add(img_local)
        db.session.add(img_remote)
        db.session.commit()

    with flask_app.test_request_context():
        # When local=True: both images returned, download links use local URLs
        form_local = IndiAllskyFitsImageViewer(
            camera_id=1,
            local=True,
            s3_prefix='https://mybucket.s3.amazonaws.com/allsky',
        )
        images_local = form_local.getImages(now.year, now.month, now.day, now.hour)
        assert len(images_local) == 2
        for item in images_local:
            assert item['fits'].startswith('images/')

        # When local=False: only S3 remote image returned, download link points to S3 URL
        form_nonlocal = IndiAllskyFitsImageViewer(
            camera_id=1,
            local=False,
            s3_prefix='https://mybucket.s3.amazonaws.com/allsky',
        )
        images_nonlocal = form_nonlocal.getImages(now.year, now.month, now.day, now.hour)
        assert len(images_nonlocal) == 1
        assert images_nonlocal[0]['fits'] == 'https://mybucket.s3.amazonaws.com/allsky/cam_1/fits/20260908/remote_s3.fit'


def test_fits_preload_form_filtering(flask_app, db):
    """Test IndiAllskyFitsImageViewerPreload filters out local-only records when local=False."""
    now = datetime(2026, 9, 8, 22, 15, 0, tzinfo=timezone.utc)

    with flask_app.app_context():
        # Local-only image
        img_local = IndiAllSkyDbFitsImageTable(
            camera_id=1,
            filename='/var/www/html/allsky/images/20260908/fits/local_only.fit',
            createDate=now,
            createDate_year=now.year,
            createDate_month=now.month,
            createDate_day=now.day,
            createDate_hour=now.hour,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
            binmode=1,
        )
        db.session.add(img_local)
        db.session.commit()

    with flask_app.test_request_context():
        # In non-local mode with only a local-only image, preload form has no choices
        form_preload = IndiAllskyFitsImageViewerPreload(
            camera_id=1,
            local=False,
            s3_prefix='https://mybucket.s3.amazonaws.com/allsky',
        )
        assert form_preload.YEAR_SELECT.choices == (('', 'None'),)

        # In local mode, year choice is available
        form_preload_local = IndiAllskyFitsImageViewerPreload(
            camera_id=1,
            local=True,
            s3_prefix='https://mybucket.s3.amazonaws.com/allsky',
        )
        assert form_preload_local.YEAR_SELECT.choices == [(2026, '2026')]


# ==============================================================================
# View Tests: FitsImageViewerView, AjaxFitsImageViewerView, Fits2JpegView, JsonImageProcessingView
# ==============================================================================

def test_fits_viewer_page_renders(auth_client):
    """Test GET /indi-allsky/fitsimageviewer renders 200 OK."""
    response = auth_client.get('/indi-allsky/fitsimageviewer?camera_id=1')
    assert response.status_code == 200
    assert b'FITS' in response.data or b'fits' in response.data


def test_ajax_fits_image_viewer_nonlocal_s3_url(auth_client, flask_app, db):
    """Test Ajax endpoint returns S3 URLs in IMAGE_DATA when camera is configured for nonlocal images."""
    now = datetime(2026, 9, 8, 22, 15, 0, tzinfo=timezone.utc)

    with flask_app.app_context():
        camera = db.session.get(IndiAllSkyDbCameraTable, 1)
        camera.web_nonlocal_images = True
        camera.s3_prefix = 'https://mybucket.s3.amazonaws.com/allsky'

        fits_row = IndiAllSkyDbFitsImageTable(
            camera_id=camera.id,
            filename='/var/www/html/allsky/images/20260908/fits/test.fit',
            s3_key='cam_1/fits/20260908/test.fit',
            createDate=now,
            createDate_year=now.year,
            createDate_month=now.month,
            createDate_day=now.day,
            createDate_hour=now.hour,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
            binmode=1,
        )
        db.session.add(fits_row)
        db.session.commit()

    ajax_payload = {
        'CAMERA_ID': 1,
        'YEAR_SELECT': 2026,
        'MONTH_SELECT': 9,
        'DAY_SELECT': 8,
        'HOUR_SELECT': 22,
    }
    response = auth_client.post('/indi-allsky/ajax/fitsimageviewer', json=ajax_payload)
    assert response.status_code == 200
    data = response.get_json()

    assert 'IMAGE_DATA' in data
    assert len(data['IMAGE_DATA']) == 1
    # Verify S3 URL is present in the fits key for download
    assert data['IMAGE_DATA'][0]['fits'] == 'https://mybucket.s3.amazonaws.com/allsky/cam_1/fits/20260908/test.fit'
    # Verify preview URL points to fits2jpeg endpoint
    assert data['IMAGE_DATA'][0]['url'].startswith('/indi-allsky/fits2jpeg?id=')


def test_ajax_fits_image_viewer_local_url(auth_client, flask_app, db):
    """Test Ajax endpoint returns local URLs in IMAGE_DATA when camera has local images."""
    now = datetime(2026, 9, 8, 22, 15, 0, tzinfo=timezone.utc)

    with flask_app.app_context():
        camera = db.session.get(IndiAllSkyDbCameraTable, 1)
        camera.web_nonlocal_images = False

        fits_row = IndiAllSkyDbFitsImageTable(
            camera_id=camera.id,
            filename='/var/www/html/allsky/images/20260908/fits/test_local.fit',
            s3_key='cam_1/fits/20260908/test_local.fit',
            createDate=now,
            createDate_year=now.year,
            createDate_month=now.month,
            createDate_day=now.day,
            createDate_hour=now.hour,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
            binmode=1,
        )
        db.session.add(fits_row)
        db.session.commit()

    with patch.dict(flask_app.config, {'INDI_ALLSKY_IMAGE_FOLDER': '/var/www/html/allsky/images'}):
        ajax_payload = {
            'CAMERA_ID': 1,
            'YEAR_SELECT': 2026,
            'MONTH_SELECT': 9,
            'DAY_SELECT': 8,
            'HOUR_SELECT': 22,
        }
        response = auth_client.post('/indi-allsky/ajax/fitsimageviewer', json=ajax_payload)
        assert response.status_code == 200
        data = response.get_json()

        assert 'IMAGE_DATA' in data
        assert len(data['IMAGE_DATA']) == 1
        assert data['IMAGE_DATA'][0]['fits'].startswith('images/')


def test_fits2jpeg_local_file_success(auth_client, flask_app, db, tmp_path):
    """Test GET /indi-allsky/fits2jpeg with existing local FITS file returns 200 image/jpeg."""
    fits_file = tmp_path / 'test_local.fits'
    fits_file.write_bytes(_generate_dummy_fits_bytes(100, 100))

    now = datetime(2026, 9, 8, 22, 15, 0, tzinfo=timezone.utc)

    with flask_app.app_context():
        fits_row = IndiAllSkyDbFitsImageTable(
            camera_id=1,
            filename=str(fits_file),
            createDate=now,
            createDate_year=now.year,
            createDate_month=now.month,
            createDate_day=now.day,
            createDate_hour=now.hour,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
            binmode=1,
        )
        db.session.add(fits_row)
        db.session.commit()
        fits_id = fits_row.id

    response = auth_client.get(f'/indi-allsky/fits2jpeg?id={fits_id}')
    assert response.status_code == 200
    assert response.content_type == 'image/jpeg'
    assert len(response.data) > 0


def test_fits2jpeg_remote_download_cached_success(auth_client, flask_app, db):
    """Test GET /indi-allsky/fits2jpeg downloads remote S3 file, caches it, and returns 200 image/jpeg."""
    dummy_fits_data = _generate_dummy_fits_bytes(100, 100)
    now = datetime(2026, 9, 8, 22, 15, 0, tzinfo=timezone.utc)

    with flask_app.app_context():
        camera = db.session.get(IndiAllSkyDbCameraTable, 1)
        camera.s3_prefix = 'https://mybucket.s3.amazonaws.com/allsky'

        fits_row = IndiAllSkyDbFitsImageTable(
            camera_id=1,
            filename='/nonexistent/on/web_only/instance/remote.fits',
            s3_key='cam_1/fits/20260908/remote.fits',
            createDate=now,
            createDate_year=now.year,
            createDate_month=now.month,
            createDate_day=now.day,
            createDate_hour=now.hour,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
            binmode=1,
        )
        db.session.add(fits_row)
        db.session.commit()
        fits_id = fits_row.id

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.__enter__.return_value = mock_response
    mock_response.iter_content.return_value = [dummy_fits_data]
    mock_response.raise_for_status = MagicMock()

    with patch('requests.get', return_value=mock_response):
        response = auth_client.get(f'/indi-allsky/fits2jpeg?id={fits_id}')
        assert response.status_code == 200
        assert response.content_type == 'image/jpeg'


def test_fits2jpeg_file_not_found_returns_404(auth_client, flask_app, db):
    """Test GET /indi-allsky/fits2jpeg returns 404 (not 500) when FITS cannot be found or downloaded."""
    now = datetime(2026, 9, 8, 22, 15, 0, tzinfo=timezone.utc)

    with flask_app.app_context():
        fits_row = IndiAllSkyDbFitsImageTable(
            camera_id=1,
            filename='/nonexistent/missing.fits',
            remote_url='https://s3.example.com/missing.fits',
            createDate=now,
            createDate_year=now.year,
            createDate_month=now.month,
            createDate_day=now.day,
            createDate_hour=now.hour,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
            binmode=1,
        )
        db.session.add(fits_row)
        db.session.commit()
        fits_id = fits_row.id

    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.__enter__.return_value = mock_response
    mock_response.raise_for_status.side_effect = requests.HTTPError('404 Not Found')

    with patch('requests.get', return_value=mock_response):
        response = auth_client.get(f'/indi-allsky/fits2jpeg?id={fits_id}')
        assert response.status_code == 404


def test_fits2jpeg_corrupt_file_returns_500(auth_client, flask_app, db, tmp_path):
    """Test GET /indi-allsky/fits2jpeg returns 500 when FITS file is corrupted."""
    corrupt_file = tmp_path / 'corrupt.fits'
    corrupt_file.write_bytes(b'NOT_A_VALID_FITS_FILE_HEADER')

    now = datetime(2026, 9, 8, 22, 15, 0, tzinfo=timezone.utc)

    with flask_app.app_context():
        fits_row = IndiAllSkyDbFitsImageTable(
            camera_id=1,
            filename=str(corrupt_file),
            createDate=now,
            createDate_year=now.year,
            createDate_month=now.month,
            createDate_day=now.day,
            createDate_hour=now.hour,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
            binmode=1,
        )
        db.session.add(fits_row)
        db.session.commit()
        fits_id = fits_row.id

    response = auth_client.get(f'/indi-allsky/fits2jpeg?id={fits_id}')
    assert response.status_code == 500
    assert b'Bad FITS file' in response.data


def test_json_image_processing_missing_file_returns_404(auth_client, flask_app, db):
    """Test POST /indi-allsky/js/processing returns 404 when FITS file cannot be found."""
    now = datetime(2026, 9, 8, 22, 15, 0, tzinfo=timezone.utc)

    with flask_app.app_context():
        fits_row = IndiAllSkyDbFitsImageTable(
            camera_id=1,
            filename='/nonexistent/missing_for_processing.fits',
            createDate=now,
            createDate_year=now.year,
            createDate_month=now.month,
            createDate_day=now.day,
            createDate_hour=now.hour,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
            binmode=1,
        )
        db.session.add(fits_row)
        db.session.commit()
        fits_id = fits_row.id

        payload = {
            'CAMERA_ID': 1,
            'FRAME_TYPE': 'fits',
            'FITS_ID': fits_id,
            'OUTPUT_IMAGE_TYPE': 'jpg',
            'DISABLE_PROCESSING': False,
        }

        import wtforms
        with patch.object(wtforms.Form, 'validate', lambda self, extra_validators=None: True):
            response = auth_client.post('/indi-allsky/js/processing', json=payload)
            assert response.status_code == 404
            data = response.get_json()
            assert data['message'] == 'FITS file not found'


def test_json_image_processing_success(auth_client, flask_app, db, tmp_path):
    """Test POST /indi-allsky/js/processing with valid dummy FITS file returns 200 and image_b64."""
    now = datetime(2026, 9, 8, 22, 15, 0, tzinfo=timezone.utc)
    fits_file = tmp_path / "valid_image.fits"
    fits_file.write_bytes(_generate_dummy_fits_bytes(width=50, height=50))

    pre_fits_file = tmp_path / "pre_image.fits"
    pre_fits_file.write_bytes(_generate_dummy_fits_bytes(width=50, height=50))

    with flask_app.app_context():
        fits_row = IndiAllSkyDbFitsImageTable(
            camera_id=1,
            filename=str(fits_file),
            createDate=now,
            createDate_year=now.year,
            createDate_month=now.month,
            createDate_day=now.day,
            createDate_hour=now.hour,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
            binmode=1,
        )
        pre_fits_row = IndiAllSkyDbFitsImageTable(
            camera_id=1,
            filename=str(pre_fits_file),
            createDate=now - timedelta(minutes=1),
            createDate_year=now.year,
            createDate_month=now.month,
            createDate_day=now.day,
            createDate_hour=now.hour,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
            binmode=1,
        )
        db.session.add_all([fits_row, pre_fits_row])
        db.session.commit()
        fits_id = fits_row.id

        payload = {
            'CAMERA_ID': 1,
            'FRAME_TYPE': 'fits',
            'FITS_ID': fits_id,
            'OUTPUT_IMAGE_TYPE': 'jpg',
            'DISABLE_PROCESSING': False,
            'LENS_IMAGE_CIRCLE': 1000,
            'LENS_OFFSET_X': 0,
            'LENS_OFFSET_Y': 0,
            'LENS_AZIMUTH': 0.0,
            'CCD_BIT_DEPTH': 16,
            'IMAGE_CALIBRATE_DARK': False,
            'IMAGE_CALIBRATE_BPM': False,
            'IMAGE_CALIBRATE_FIX_HOLES': False,
            'IMAGE_CALIBRATE_HOLE_THOLD': 1000,
            'IMAGE_CALIBRATE_MANUAL_OFFSET': 0,
            'NIGHT_CONTRAST_ENHANCE': False,
            'IMAGE_COLORMAP': 'none',
            'CONTRAST_ENHANCE_16BIT': False,
            'CLAHE_CLIPLIMIT': 2.0,
            'CLAHE_GRIDSIZE': 8,
            'IMAGE_STRETCH__CLASSNAME': '',
            'IMAGE_STRETCH__MODE1_GAMMA': 1.0,
            'IMAGE_STRETCH__MODE1_STDDEVS': 3.0,
            'IMAGE_STRETCH__MODE2_SHADOWS': 0.0,
            'IMAGE_STRETCH__MODE2_MIDTONES': 0.5,
            'IMAGE_STRETCH__MODE2_HIGHLIGHTS': 1.0,
            'IMAGE_STRETCH__MODE3_BLACK_CLIP': 0.0,
            'IMAGE_STRETCH__MODE3_SHADOWS': 0.0,
            'IMAGE_STRETCH__MODE3_MIDTONES': 0.5,
            'IMAGE_STRETCH__MODE3_HIGHLIGHTS': 1.0,
            'CFA_PATTERN': 'RGGB',
            'SCNR_ALGORITHM': 'none',
            'SCNR_MTF_MIDTONES': 0.5,
            'IMAGE_DENOISE': 'none',
            'IMAGE_DENOISE_STRENGTH': 0,
            'BILATERAL_SIGMA_COLOR': 75,
            'BILATERAL_SIGMA_SPACE': 75,
            'WBR_FACTOR': 1.0,
            'WBG_FACTOR': 1.0,
            'WBB_FACTOR': 1.0,
            'WBR_MTF_MIDTONES': 0.5,
            'WBG_MTF_MIDTONES': 0.5,
            'WBB_MTF_MIDTONES': 0.5,
            'AUTO_WB': False,
            'SATURATION_FACTOR': 1.0,
            'GAMMA_CORRECTION': 1.0,
            'SHARPEN_AMOUNT': 0.0,
            'IMAGE_ROTATE': 'none',
            'IMAGE_ROTATE_ANGLE': 0,
            'IMAGE_ROTATE_KEEP_SIZE': False,
            'IMAGE_FLIP_V': False,
            'IMAGE_FLIP_H': False,
            'DETECT_MASK': '',
            'SQM_FOV_DIV': 1,
            'IMAGE_STACK_METHOD': 'median',
            'IMAGE_STACK_COUNT': 1,
            'IMAGE_STACK_ALIGN': False,
            'IMAGE_ALIGN_DETECTSIGMA': 5,
            'IMAGE_ALIGN_POINTS': 100,
            'IMAGE_ALIGN_SOURCEMINAREA': 5,
            'FISH2PANO__ENABLE': False,
            'FISH2PANO__DIAMETER': 1000,
            'FISH2PANO__ROTATE_ANGLE': 0,
            'FISH2PANO__SCALE': 1.0,
            'FISH2PANO__FLIP_H': False,
            'FISH2PANO__ENABLE_CARDINAL_DIRS': False,
            'FISH2PANO__DIRS_OFFSET_BOTTOM': 0,
            'FISH2PANO__OPENCV_FONT_SCALE': 1.0,
            'FISH2PANO__PIL_FONT_SIZE': 12,
            'PROCESSING_SPLIT_SCREEN': False,
            'IMAGE_LABEL_TEMPLATE': '',
            'IMAGE_EXTRA_TEXT': '',
            'IMAGE_LABEL_SYSTEM': '',
            'TEXT_PROPERTIES__FONT_FACE': 'FONT_HERSHEY_SIMPLEX',
            'TEXT_PROPERTIES__FONT_SCALE': 1.0,
            'TEXT_PROPERTIES__FONT_THICKNESS': 1,
            'TEXT_PROPERTIES__FONT_OUTLINE': False,
            'TEXT_PROPERTIES__FONT_HEIGHT': 20,
            'TEXT_PROPERTIES__FONT_X': 10,
            'TEXT_PROPERTIES__FONT_Y': 10,
            'TEXT_PROPERTIES__PIL_FONT_FILE': '',
            'TEXT_PROPERTIES__PIL_FONT_CUSTOM': '',
            'TEXT_PROPERTIES__PIL_FONT_SIZE': 12,
            'TEXT_PROPERTIES__FONT_COLOR': '255,255,255',
            'CARDINAL_DIRS__ENABLE': False,
            'CARDINAL_DIRS__SWAP_NS': False,
            'CARDINAL_DIRS__SWAP_EW': False,
            'CARDINAL_DIRS__CHAR_NORTH': 'N',
            'CARDINAL_DIRS__CHAR_EAST': 'E',
            'CARDINAL_DIRS__CHAR_WEST': 'W',
            'CARDINAL_DIRS__CHAR_SOUTH': 'S',
            'CARDINAL_DIRS__DIAMETER': 1000,
            'CARDINAL_DIRS__OFFSET_X': 0,
            'CARDINAL_DIRS__OFFSET_Y': 0,
            'CARDINAL_DIRS__OFFSET_TOP': 0,
            'CARDINAL_DIRS__OFFSET_LEFT': 0,
            'CARDINAL_DIRS__OFFSET_RIGHT': 0,
            'CARDINAL_DIRS__OFFSET_BOTTOM': 0,
            'CARDINAL_DIRS__OPENCV_FONT_SCALE': 1.0,
            'CARDINAL_DIRS__PIL_FONT_SIZE': 12,
            'CARDINAL_DIRS__OUTLINE_CIRCLE': False,
            'CARDINAL_DIRS__FONT_COLOR': '255,255,255',
            'IMAGE_CIRCLE_MASK__ENABLE': False,
            'IMAGE_CIRCLE_MASK__DIAMETER': 1000,
            'IMAGE_CIRCLE_MASK__OFFSET_X': 0,
            'IMAGE_CIRCLE_MASK__OFFSET_Y': 0,
            'IMAGE_CIRCLE_MASK__BLUR': 0,
            'IMAGE_CIRCLE_MASK__OPACITY': 100,
            'IMAGE_CIRCLE_MASK__OUTLINE': False,
            'IMAGE_CROP_IMAGE_CIRCLE': False,
            'IMAGE_BORDER__TOP': 0,
            'IMAGE_BORDER__LEFT': 0,
            'IMAGE_BORDER__RIGHT': 0,
            'IMAGE_BORDER__BOTTOM': 0,
            'IMAGE_BORDER__COLOR': '0,0,0',
            'MOON_OVERLAY__ENABLE': False,
            'MOON_OVERLAY__X': 0,
            'MOON_OVERLAY__Y': 0,
            'MOON_OVERLAY__SCALE': 1.0,
            'MOON_OVERLAY__DARK_SIDE_SCALE': 1.0,
            'MOON_OVERLAY__FLIP_V': False,
            'MOON_OVERLAY__FLIP_H': False,
            'LIGHTGRAPH_OVERLAY__ENABLE': False,
            'LIGHTGRAPH_OVERLAY__GRAPH_HEIGHT': 50,
            'LIGHTGRAPH_OVERLAY__GRAPH_BORDER': 2,
            'LIGHTGRAPH_OVERLAY__Y': 0,
            'LIGHTGRAPH_OVERLAY__OFFSET_X': 0,
            'LIGHTGRAPH_OVERLAY__SCALE': 1.0,
            'LIGHTGRAPH_OVERLAY__NOW_MARKER_SIZE': 5,
            'LIGHTGRAPH_OVERLAY__OPACITY': 100,
            'LIGHTGRAPH_OVERLAY__PIL_FONT_SIZE': 12,
            'LIGHTGRAPH_OVERLAY__OPENCV_FONT_SCALE': 1.0,
            'LIGHTGRAPH_OVERLAY__LABEL': False,
            'LIGHTGRAPH_OVERLAY__HOUR_LINES': False,
            'LIGHTGRAPH_OVERLAY__DAY_COLOR': '255,255,255',
            'LIGHTGRAPH_OVERLAY__DUSK_COLOR': '255,255,255',
            'LIGHTGRAPH_OVERLAY__NIGHT_COLOR': '0,0,0',
            'LIGHTGRAPH_OVERLAY__MOONMODE_COLOR': '100,100,100',
            'LIGHTGRAPH_OVERLAY__HOUR_COLOR': '150,150,150',
            'LIGHTGRAPH_OVERLAY__BORDER_COLOR': '200,200,200',
            'LIGHTGRAPH_OVERLAY__NOW_COLOR': '255,0,0',
            'LIGHTGRAPH_OVERLAY__FONT_COLOR': '150,150,150',
            'SQM_ROI_X1': 0,
            'SQM_ROI_Y1': 0,
            'SQM_ROI_X2': 0,
            'SQM_ROI_Y2': 0,
            'RUN_DETECTION': True,
            'DETECT_STARS_METHOD': 'template',
            'DETECT_STARS_THOLD': 5.0,
            'DETECT_STARS_SEP_THOLD': 1.5,
            'DETECT_STARS_SEP_MAX_RADIUS': 10,
            'DETECT_METEORS_THOLD': 10,
        }

        import wtforms
        with patch.object(wtforms.Form, 'validate', lambda self, extra_validators=None: True):
            response = auth_client.post('/indi-allsky/js/processing', json=payload)
            assert response.status_code == 200
            data = response.get_json()
            assert 'image_b64' in data

            # Test DISABLE_PROCESSING=True branch (lines 9768-9804)
            payload_disable = dict(payload, DISABLE_PROCESSING=True)
            res_disable = auth_client.post('/indi-allsky/js/processing', json=payload_disable)
            assert res_disable.status_code == 200

            # Test IMAGE_STACK_COUNT > 1 stacking branch with previous FITS row (lines 9808-9850)
            payload_stack = dict(payload, IMAGE_STACK_COUNT=2)
            res_stack = auth_client.post('/indi-allsky/js/processing', json=payload_stack)
            assert res_stack.status_code == 200

            # Test PNG output format (lines 9989-9993)
            payload_png = dict(payload, OUTPUT_IMAGE_TYPE='png')
            res_png = auth_client.post('/indi-allsky/js/processing', json=payload_png)
            assert res_png.status_code == 200

            # Test 16-bit CLAHE (lines 9885-9888)
            payload_clahe_16 = dict(payload, NIGHT_CONTRAST_ENHANCE=True, CONTRAST_ENHANCE_16BIT=True)
            res_c16 = auth_client.post('/indi-allsky/js/processing', json=payload_clahe_16)
            assert res_c16.status_code == 200

            # Test 8-bit CLAHE (lines 9939-9942)
            payload_clahe_8 = dict(payload, NIGHT_CONTRAST_ENHANCE=True, CONTRAST_ENHANCE_16BIT=False)
            res_c8 = auth_client.post('/indi-allsky/js/processing', json=payload_clahe_8)
            assert res_c8.status_code == 200

            # Test Rotation and Flips (lines 9902, 9907, 9911)
            payload_rot = dict(payload, IMAGE_ROTATE='90_clockwise', IMAGE_ROTATE_ANGLE=45, IMAGE_FLIP_V=True, IMAGE_FLIP_H=True)
            res_rot = auth_client.post('/indi-allsky/js/processing', json=payload_rot)
            assert res_rot.status_code == 200

            # Test Fish2Pano conversion (lines 9964-9979)
            payload_pano = dict(
                payload,
                FISH2PANO__ENABLE=True,
                FISH2PANO__FLIP_H=True,
                FISH2PANO__ENABLE_CARDINAL_DIRS=True,
                FISH2PANO__DIAMETER=1000,
            )
            res_pano = auth_client.post('/indi-allsky/js/processing', json=payload_pano)
            assert res_pano.status_code == 200

