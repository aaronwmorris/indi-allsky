import os
import tempfile
import io
from pathlib import Path
from datetime import datetime, timezone
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
