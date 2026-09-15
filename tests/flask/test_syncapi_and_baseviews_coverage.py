"""Tests for syncapi_views.py and base_views.py coverage."""
import io
import json
import math
import time
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import dbus
import dbus.exceptions
import ephem
import psutil
from sqlalchemy.exc import NoResultFound
from cryptography.fernet import Fernet
from passlib.hash import argon2

from indi_allsky import constants
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbThumbnailTable,
    IndiAllSkyDbVideoTable,
    IndiAllSkyDbMiniVideoTable,
    IndiAllSkyDbKeogramTable,
    IndiAllSkyDbStarTrailsTable,
    IndiAllSkyDbFitsImageTable,
    IndiAllSkyDbRawImageTable,
    IndiAllSkyDbPanoramaImageTable,
    IndiAllSkyDbPanoramaVideoTable,
    IndiAllSkyDbUserTable,
    IndiAllSkyDbConfigTable,
    NotificationCategory,
)
from indi_allsky.flask.base_views import BaseView, TemplateView, FakeCamera, JsonView
from indi_allsky.flask.syncapi_views import (
    SyncApiBaseView,
    SyncApiCameraView,
    SyncApiImageView,
    SyncApiThumbnailView,
    AuthenticationFailure,
)
from indi_allsky.flask.miscDb import miscDb
from indi_allsky.flask import db as _db


def make_auth_header(username, raw_api_key, metadata_bytes):
    time_floor = math.floor(time.time() / 300)
    hmac_message = str(time_floor).encode() + metadata_bytes
    sig = hmac.new(raw_api_key.encode(), msg=hmac_message, digestmod=hashlib.sha3_512).hexdigest()
    return {'Authorization': f'Bearer {username}:{sig}'}


@pytest.fixture(autouse=True)
def _base_sync_db(flask_app, tmp_path, db):
    flask_app.config['INDI_ALLSKY_IMAGE_FOLDER'] = str(tmp_path)
    flask_app.config['ADMIN_NETWORKS'] = ['127.0.0.1/32']

    with flask_app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        if not cam:
            cam = IndiAllSkyDbCameraTable(
                name="sync_cam",
                uuid="sync-cam-uuid-1",
                friendlyName="Sync Camera",
                latitude=-34.9, longitude=138.6, elevation=50,
                nightSunAlt=-6.0, local=True,
                utc_offset=0,
            )
            db.session.add(cam)
        else:
            cam.uuid = "sync-cam-uuid-1"
            cam.utc_offset = 0
            db.session.add(cam)

        cfg = IndiAllSkyDbConfigTable.query.first()
        if not cfg:
            cfg = IndiAllSkyDbConfigTable(
                data={
                    'WEBSITE': {'TITLE': 'indi-allsky'},
                    'PRIVACY_MODE': False,
                    'IMAGE_FOLDER': str(tmp_path),
                },
                level='1.0', note='test',
            )
            db.session.add(cfg)
        else:
            cfg.data = {**cfg.data, 'IMAGE_FOLDER': str(tmp_path), 'PRIVACY_MODE': False}
            db.session.add(cfg)

        password_key = flask_app.config['PASSWORD_KEY']
        f = Fernet(password_key.encode())
        raw_key = "sync_api_key_secret_123"
        enc_key = f.encrypt(raw_key.encode()).decode()

        u = IndiAllSkyDbUserTable.query.filter_by(username='syncapiuser').first()
        if not u:
            u = IndiAllSkyDbUserTable(
                username='syncapiuser',
                password=argon2.hash('ValidPassword123!'),
                email='sync@example.com',
                active=True, admin=True,
                apikey=enc_key,
            )
            db.session.add(u)
        else:
            u.apikey = enc_key
            db.session.add(u)

        db.session.commit()


@pytest.fixture
def sync_env():
    return 'syncapiuser', "sync_api_key_secret_123", "sync-cam-uuid-1"


# ===========================================================================
# syncapi_views.py coverage tests
# ===========================================================================

class TestSyncApiViewsCoverage:

    def test_syncapi_init_empty_image_folder(self, flask_app, db):
        """Covers syncapi_views.py line 69."""
        with flask_app.test_request_context():
            with patch('indi_allsky.config.IndiAllSkyConfig') as mock_cfg:
                mock_cfg.return_value.config = {'IMAGE_FOLDER': ''}
                v = SyncApiBaseView()
                assert v.image_dir is not None
                assert str(v.image_dir).endswith('images')

    def test_syncapi_dispatch_invalid_method(self, flask_app, sync_env):
        """Covers syncapi_views.py lines 91-92."""
        username, raw_key, cam_uuid = sync_env
        meta = json.dumps({'camera_uuid': cam_uuid, 'file_size': 0, 'utc_offset': 0}).encode()
        headers = make_auth_header(username, raw_key, meta)
        with flask_app.test_request_context('/', method='OPTIONS',
                                            data={'metadata': (io.BytesIO(meta), 'meta.json')},
                                            headers=headers):
            v = SyncApiBaseView()
            with patch.object(v, 'authorize', return_value=True):
                resp, code = v.dispatch_request()
                assert code == 400

    def test_syncapi_get_delete_put_methods(self, flask_app, sync_env, tmp_path):
        """Covers get, delete, put endpoints and camera not found paths."""
        username, raw_key, cam_uuid = sync_env
        client = flask_app.test_client()

        # 1. GET with missing camera
        meta_bad_cam = json.dumps({'camera_uuid': 'unknown-uuid', 'id': 1, 'utc_offset': 0}).encode()
        headers = make_auth_header(username, raw_key, meta_bad_cam)
        resp = client.get('/indi-allsky/sync/v1/image', data={'metadata': (io.BytesIO(meta_bad_cam), 'meta.json')}, headers=headers)
        assert resp.status_code == 400
        assert resp.get_json().get('error') == 'camera not found'

        # 2. GET with valid camera but entry not found -> returns file_missing
        meta_missing_entry = json.dumps({'camera_uuid': cam_uuid, 'id': 99999, 'utc_offset': 0}).encode()
        headers = make_auth_header(username, raw_key, meta_missing_entry)
        resp = client.get('/indi-allsky/sync/v1/image', data={'metadata': (io.BytesIO(meta_missing_entry), 'meta.json')}, headers=headers)
        assert resp.status_code == 400
        assert resp.get_json().get('error') == 'file_missing'

        # 3. GET with valid entry
        with flask_app.app_context():
            cam = IndiAllSkyDbCameraTable.query.filter_by(uuid=cam_uuid).first()
            img = IndiAllSkyDbImageTable(
                camera_id=cam.id,
                filename='sync_test.jpg',
                createDate=datetime.now(),
                dayDate=datetime.now().date(),
                exposure=1.0, gain=100.0, adu=100.0,
            )
            _db.session.add(img)
            _db.session.commit()
            img_id = img.id

        meta_valid = json.dumps({'camera_uuid': cam_uuid, 'id': img_id, 'utc_offset': 0}).encode()
        headers = make_auth_header(username, raw_key, meta_valid)
        resp = client.get('/indi-allsky/sync/v1/image', data={'metadata': (io.BytesIO(meta_valid), 'meta.json')}, headers=headers)
        assert resp.status_code == 200
        assert resp.get_json().get('id') == img_id

        # 4. DELETE entry
        resp_del = client.delete('/indi-allsky/sync/v1/image', data={'metadata': (io.BytesIO(meta_valid), 'meta.json')}, headers=headers)
        assert resp_del.status_code == 200

        # 5. PUT delegates to post(overwrite=True)
        media_data = b'media content'
        meta_post = json.dumps({
            'camera_uuid': cam_uuid,
            'file_size': len(media_data),
            'filename': 'new_img.jpg',
            'createDate': datetime.now().timestamp(),
            'dayDate': datetime.now().strftime('%Y%m%d'),
            'night': 1,
            'exposure': 1.0,
            'gain': 100.0,
            'binmode': 1,
            'adu': 100.0,
            'adu_roi': 0,
            'detections': 0,
            'utc_offset': 0,
            'moonmode': 0,
            'moonphase': 0.0,
            'sqm': 0.0,
            'stars': 0,
            'calibrated': False,
            'stable': True,
            'temp': 0.0,
            'height': 100,
            'width': 200,
            'exp_elapsed': 1.0,
            'process_elapsed': 0.1,
        }).encode()
        headers_put = make_auth_header(username, raw_key, meta_post)
        resp_put = client.put(
            '/indi-allsky/sync/v1/image',
            data={'metadata': (io.BytesIO(meta_post), 'meta.json'), 'media': (io.BytesIO(media_data), 'img.jpg')},
            headers=headers_put,
        )
        assert resp_put.status_code in (200, 201)

    def test_syncapi_camera_view_crud(self, flask_app, sync_env):
        """Covers SyncApiCameraView get, post, put, delete."""
        username, raw_key, cam_uuid = sync_env
        client = flask_app.test_client()

        # GET
        with flask_app.app_context():
            cam = IndiAllSkyDbCameraTable.query.filter_by(uuid=cam_uuid).first()
            cam_id = cam.id

        meta_get = json.dumps({'id': cam_id, 'camera_uuid': cam_uuid, 'utc_offset': 0}).encode()
        headers = make_auth_header(username, raw_key, meta_get)
        resp = client.get('/indi-allsky/sync/v1/camera', data={'metadata': (io.BytesIO(meta_get), 'meta.json')}, headers=headers)
        assert resp.status_code == 200

        # POST / PUT
        meta_cam = json.dumps({
            'uuid': 'new-synced-cam-1',
            'name': 'Synced Camera 1',
            'friendlyName': 'Synced Cam',
            'utc_offset': 0,
        }).encode()
        headers_cam = make_auth_header(username, raw_key, meta_cam)
        resp_post = client.post('/indi-allsky/sync/v1/camera', data={'metadata': (io.BytesIO(meta_cam), 'meta.json')}, headers=headers_cam)
        assert resp_post.status_code in (200, 201)

        resp_put = client.put('/indi-allsky/sync/v1/camera', data={'metadata': (io.BytesIO(meta_cam), 'meta.json')}, headers=headers_cam)
        assert resp_put.status_code in (200, 201)

        # DELETE -> not implemented (400)
        resp_del = client.delete('/indi-allsky/sync/v1/camera', data={'metadata': (io.BytesIO(meta_cam), 'meta.json')}, headers=headers_cam)
        assert resp_del.status_code == 400
        assert resp_del.get_json().get('error') == 'not_implemented'

    def test_syncapi_thumbnail_view(self, flask_app, sync_env, tmp_path):
        """Covers SyncApiThumbnailView post with various origins."""
        username, raw_key, cam_uuid = sync_env
        client = flask_app.test_client()

        media_data = b'thumb bytes'
        now = datetime.now()

        # Origin IMAGE
        meta_thumb = json.dumps({
            'camera_uuid': cam_uuid,
            'file_size': len(media_data),
            'uuid': 'thumb-sync-uuid-1',
            'origin': constants.IMAGE,
            'dayDate': now.strftime('%Y%m%d'),
            'createDate': now.timestamp(),
            'night': True,
            'width': 150,
            'height': 100,
            'utc_offset': 0,
        }).encode()
        headers = make_auth_header(username, raw_key, meta_thumb)
        resp = client.post(
            '/indi-allsky/sync/v1/thumbnail',
            data={'metadata': (io.BytesIO(meta_thumb), 'meta.json'), 'media': (io.BytesIO(media_data), 'thumb.jpg')},
            headers=headers,
        )
        assert resp.status_code in (200, 201)

        # Origin PANORAMA_IMAGE
        meta_pano_thumb = json.dumps({
            'camera_uuid': cam_uuid,
            'file_size': len(media_data),
            'uuid': 'thumb-sync-pano-1',
            'origin': constants.PANORAMA_IMAGE,
            'dayDate': now.strftime('%Y%m%d'),
            'createDate': now.timestamp(),
            'night': False,
            'width': 150,
            'height': 100,
            'utc_offset': 0,
        }).encode()
        headers_pano = make_auth_header(username, raw_key, meta_pano_thumb)
        resp_pano = client.post(
            '/indi-allsky/sync/v1/thumbnail',
            data={'metadata': (io.BytesIO(meta_pano_thumb), 'meta.json'), 'media': (io.BytesIO(media_data), 'thumb.jpg')},
            headers=headers_pano,
        )
        assert resp_pano.status_code in (200, 201)

    def test_syncapi_auth_failures(self, flask_app, sync_env):
        """Covers syncapi_views.py lines 94-96, 338-340, 343-344, 349-350, 359, 391-392."""
        username, raw_key, cam_uuid = sync_env
        client = flask_app.test_client()
        meta = json.dumps({'camera_uuid': cam_uuid, 'utc_offset': 0}).encode()

        # 1. Missing Authorization header
        resp = client.get('/indi-allsky/sync/v1/camera', data={'metadata': (io.BytesIO(meta), 'meta.json')})
        assert resp.status_code == 400
        assert resp.get_json().get('error') == 'authentication failed'

        # 2. Malformed header (no space)
        resp = client.get('/indi-allsky/sync/v1/camera', data={'metadata': (io.BytesIO(meta), 'meta.json')},
                          headers={'Authorization': 'InvalidNoSpace'})
        assert resp.status_code == 400
        assert resp.get_json().get('error') == 'authentication failed'

        # 3. Malformed header (no colon in user_hmac_hash)
        resp = client.get('/indi-allsky/sync/v1/camera', data={'metadata': (io.BytesIO(meta), 'meta.json')},
                          headers={'Authorization': 'Bearer NoColonInToken'})
        assert resp.status_code == 400
        assert resp.get_json().get('error') == 'authentication failed'

        # 4. Unknown user
        resp = client.get('/indi-allsky/sync/v1/camera', data={'metadata': (io.BytesIO(meta), 'meta.json')},
                          headers={'Authorization': 'Bearer nonexistentuser:1234abcd'})
        assert resp.status_code == 400
        assert resp.get_json().get('error') == 'authentication failed'

        # 5. Invalid HMAC signature
        resp = client.get('/indi-allsky/sync/v1/camera', data={'metadata': (io.BytesIO(meta), 'meta.json')},
                          headers={'Authorization': f'Bearer {username}:badbadbadbadbad'})
        assert resp.status_code == 400
        assert resp.get_json().get('error') == 'authentication failed'

    def test_syncapi_post_media_size_mismatch(self, flask_app, sync_env):
        """Covers syncapi_views.py lines 107-108 (media file size does not match)."""
        username, raw_key, cam_uuid = sync_env
        client = flask_app.test_client()
        media_data = b'actual size is 21 bytes'
        meta = json.dumps({
            'camera_uuid': cam_uuid,
            'file_size': 99999,  # mismatch
            'utc_offset': 0,
        }).encode()
        headers = make_auth_header(username, raw_key, meta)
        resp = client.post(
            '/indi-allsky/sync/v1/image',
            data={'metadata': (io.BytesIO(meta), 'meta.json'), 'media': (io.BytesIO(media_data), 'img.jpg')},
            headers=headers,
        )
        assert resp.status_code == 400
        assert resp.get_json().get('error') == 'authentication failed'

    def test_syncapi_delete_errors_and_getcamera_offset(self, flask_app, sync_env):
        """Covers syncapi_views.py lines 141-143, 148-150, 287-288, 404-405."""
        username, raw_key, cam_uuid = sync_env
        client = flask_app.test_client()

        # Camera not found in delete
        meta_bad_cam = json.dumps({'camera_uuid': 'missing-cam-uuid', 'id': 1, 'utc_offset': 0}).encode()
        headers_bad_cam = make_auth_header(username, raw_key, meta_bad_cam)
        resp = client.delete('/indi-allsky/sync/v1/video', data={'metadata': (io.BytesIO(meta_bad_cam), 'meta.json')}, headers=headers_bad_cam)
        assert resp.status_code == 400
        assert resp.get_json().get('error') == 'camera not found'

        # Entry missing in delete (lines 148-150, 287-288)
        meta_missing = json.dumps({'camera_uuid': cam_uuid, 'id': 99999, 'utc_offset': 3600}).encode()
        headers_missing = make_auth_header(username, raw_key, meta_missing)
        resp = client.delete('/indi-allsky/sync/v1/video', data={'metadata': (io.BytesIO(meta_missing), 'meta.json')}, headers=headers_missing)
        assert resp.status_code == 400
        assert resp.get_json().get('error') == 'file_missing'

        # Verify camera utc_offset was updated to 3600 (lines 404-405)
        with flask_app.app_context():
            cam = IndiAllSkyDbCameraTable.query.filter_by(uuid=cam_uuid).first()
            assert cam.utc_offset == 3600
            cam.utc_offset = 0
            _db.session.commit()

    def test_syncapi_camera_view_missing_entry(self, flask_app, sync_env):
        """Covers syncapi_views.py lines 424-426, 455-456."""
        username, raw_key, cam_uuid = sync_env
        client = flask_app.test_client()

        meta_missing_cam = json.dumps({'id': 99999, 'camera_uuid': 'nonexistent-uuid', 'utc_offset': 0}).encode()
        headers = make_auth_header(username, raw_key, meta_missing_cam)
        resp = client.get('/indi-allsky/sync/v1/camera', data={'metadata': (io.BytesIO(meta_missing_cam), 'meta.json')}, headers=headers)
        assert resp.status_code == 400
        assert resp.get_json().get('error') == 'camera_missing'

    def test_syncapi_base_view_process_post_all_timelapse_subclasses(self, flask_app, sync_env, tmp_path):
        """Covers syncapi_views.py lines 120-122, 180-269 across Video, MiniVideo, Keogram, Startrail, StartrailVideo, PanoramaVideo."""
        username, raw_key, cam_uuid = sync_env
        client = flask_app.test_client()

        endpoints = [
            '/indi-allsky/sync/v1/video',
            '/indi-allsky/sync/v1/minivideo',
            '/indi-allsky/sync/v1/keogram',
            '/indi-allsky/sync/v1/startrail',
            '/indi-allsky/sync/v1/startrailvideo',
            '/indi-allsky/sync/v1/panoramavideo',
        ]

        now = datetime.now()
        media_data = b'video or timelapse data bytes'

        for endpoint in endpoints:
            # Pre-create orphaned file on disk to cover lines 236-237 (filename_p.exists() -> unlink)
            day_dir = tmp_path / f'ccd_{cam_uuid}' / now.strftime('%Y%m%d')
            day_dir.mkdir(parents=True, exist_ok=True)
            # Create a file matching the expected name
            for orphan_file in day_dir.glob('*'):
                orphan_file.unlink()

            # 1. Post daytime (night=False)
            meta_day = json.dumps({
                'camera_uuid': cam_uuid,
                'file_size': len(media_data),
                'dayDate': now.strftime('%Y%m%d'),
                'createDate': now.timestamp(),
                'night': False,
                'targetDate': now.timestamp(),
                'startDate': now.timestamp(),
                'endDate': now.timestamp(),
                'utc_offset': 0,
                'note': 'test note',
            }).encode()
            headers = make_auth_header(username, raw_key, meta_day)
            resp = client.post(
                endpoint,
                data={'metadata': (io.BytesIO(meta_day), 'meta.json'), 'media': (io.BytesIO(media_data), 'file.mp4')},
                headers=headers,
            )
            assert resp.status_code in (200, 201)

            # 2. Post nighttime (night=True)
            meta_night = json.dumps({
                'camera_uuid': cam_uuid,
                'file_size': len(media_data),
                'dayDate': now.strftime('%Y%m%d'),
                'createDate': now.timestamp(),
                'night': True,
                'targetDate': now.timestamp(),
                'startDate': now.timestamp(),
                'endDate': now.timestamp(),
                'utc_offset': 0,
                'note': 'test note',
            }).encode()
            headers_night = make_auth_header(username, raw_key, meta_night)
            resp_night = client.post(
                endpoint,
                data={'metadata': (io.BytesIO(meta_night), 'meta.json'), 'media': (io.BytesIO(media_data), 'file.mp4')},
                headers=headers_night,
            )
            assert resp_night.status_code in (200, 201)

            # 3. Post again with overwrite=False -> file_exists (lines 120-122, 211)
            resp_exists = client.post(
                endpoint,
                data={'metadata': (io.BytesIO(meta_night), 'meta.json'), 'media': (io.BytesIO(media_data), 'file.mp4')},
                headers=headers_night,
            )
            assert resp_exists.status_code == 400
            assert resp_exists.get_json().get('error') == 'file_exists'

            # 4. Put with overwrite=True -> replaces existing entry and unlinks file (lines 214-217, 235-237)
            resp_put = client.put(
                endpoint,
                data={'metadata': (io.BytesIO(meta_night), 'meta.json'), 'media': (io.BytesIO(media_data), 'file.mp4')},
                headers=headers_night,
            )
            assert resp_put.status_code in (200, 201)

            # 5. Post empty media file (file_size == 0)
            meta_empty = json.dumps({
                'camera_uuid': cam_uuid,
                'file_size': 0,
                'dayDate': (now + timedelta(days=1)).strftime('%Y%m%d'),
                'createDate': (now + timedelta(days=1)).timestamp(),
                'night': True,
                'targetDate': (now + timedelta(days=1)).timestamp(),
                'startDate': (now + timedelta(days=1)).timestamp(),
                'endDate': (now + timedelta(days=1)).timestamp(),
                'utc_offset': 0,
                'note': 'empty test',
            }).encode()
            headers_empty = make_auth_header(username, raw_key, meta_empty)
            resp_empty = client.post(
                endpoint,
                data={'metadata': (io.BytesIO(meta_empty), 'meta.json'), 'media': (io.BytesIO(b''), 'empty.mp4')},
                headers=headers_empty,
            )
            assert resp_empty.status_code in (200, 201)

    def test_syncapi_process_post_multiple_results_found(self, flask_app, sync_env, tmp_path):
        """Covers syncapi_views.py lines 218-220 (MultipleResultsFound in SyncApiBaseView.processPost)."""
        from indi_allsky.flask.syncapi_views import SyncApiVideoView, EntryError
        v = SyncApiVideoView()
        with flask_app.app_context():
            cam = IndiAllSkyDbCameraTable.query.filter_by(uuid=sync_env[2]).first()
            d_date = datetime.now().date()
            v1 = IndiAllSkyDbVideoTable(filename=str(tmp_path / 'v1.mp4'), createDate=datetime.now(), dayDate=d_date, night=True, camera_id=cam.id)
            v2 = IndiAllSkyDbVideoTable(filename=str(tmp_path / 'v2.mp4'), createDate=datetime.now(), dayDate=d_date, night=True, camera_id=cam.id)
            _db.session.add_all([v1, v2])
            _db.session.commit()

            tmp_file = tmp_path / 'tmp_test.mp4'
            tmp_file.write_bytes(b'test')
            meta = {
                'createDate': datetime.now().timestamp(),
                'dayDate': d_date.strftime('%Y%m%d'),
                'night': True,
                'utc_offset': 0,
            }
            with pytest.raises(EntryError):
                v.processPost(cam, meta, tmp_file, overwrite=True)

    def test_syncapi_image_views_and_keogram_pixels(self, flask_app, sync_env, tmp_path):
        """Covers syncapi_views.py lines 514-522, 529, 562-563, 598 across Image, RawImage, FitsImage, PanoramaImage."""
        username, raw_key, cam_uuid = sync_env
        client = flask_app.test_client()

        endpoints = [
            '/indi-allsky/sync/v1/image',
            '/indi-allsky/sync/v1/rawimage',
            '/indi-allsky/sync/v1/fitsimage',
            '/indi-allsky/sync/v1/panoramaimage',
        ]

        now = datetime.now()
        media_data = b'image data bytes'

        for endpoint in endpoints:
            # 1. Post daytime (night=False, covers getImageFolder line 562-563)
            meta_day = {
                'camera_uuid': cam_uuid,
                'file_size': len(media_data),
                'filename': 'test_day_img.jpg',
                'createDate': now.timestamp(),
                'dayDate': now.strftime('%Y%m%d'),
                'night': False,
                'exposure': 1.0,
                'gain': 100.0,
                'binmode': 1,
                'adu': 100.0,
                'adu_roi': 0,
                'detections': 0,
                'utc_offset': 0,
                'moonmode': 0,
                'moonphase': 0.0,
                'sqm': 0.0,
                'stars': 0,
                'calibrated': False,
                'stable': True,
                'temp': 0.0,
                'height': 100,
                'width': 200,
                'exp_elapsed': 1.0,
                'process_elapsed': 0.1,
                'bitdepth': 8,
            }
            if endpoint == '/indi-allsky/sync/v1/image':
                meta_day['keogram_pixels'] = [[128, 128, 128]] * 5  # covers line 598

            meta_day_bytes = json.dumps(meta_day).encode()
            headers = make_auth_header(username, raw_key, meta_day_bytes)
            resp = client.post(
                endpoint,
                data={'metadata': (io.BytesIO(meta_day_bytes), 'meta.json'), 'media': (io.BytesIO(media_data), 'img.jpg')},
                headers=headers,
            )
            assert resp.status_code in (200, 201)

            # 2. Post again with overwrite=False -> file_exists (lines 514-516)
            resp_exists = client.post(
                endpoint,
                data={'metadata': (io.BytesIO(meta_day_bytes), 'meta.json'), 'media': (io.BytesIO(media_data), 'img.jpg')},
                headers=headers,
            )
            assert resp_exists.status_code == 400
            assert resp_exists.get_json().get('error') == 'file_exists'

            # 3. Put with overwrite=True -> replaces existing entry and unlinks file (lines 518-522, 529)
            resp_put = client.put(
                endpoint,
                data={'metadata': (io.BytesIO(meta_day_bytes), 'meta.json'), 'media': (io.BytesIO(media_data), 'img.jpg')},
                headers=headers,
            )
            assert resp_put.status_code in (200, 201)

    def test_syncapi_process_post_orphaned_file_on_disk(self, flask_app, sync_env, tmp_path):
        """Covers syncapi_views.py lines 236-237 and 529 (orphaned file on disk removed)."""
        from indi_allsky.flask.syncapi_views import SyncApiVideoView, SyncApiImageView
        with flask_app.app_context():
            cam = IndiAllSkyDbCameraTable.query.filter_by(uuid=sync_env[2]).first()
            now = datetime.now()
            ts = int(now.timestamp())
            d_str = now.strftime('%Y%m%d')
            local_offset = datetime.now().astimezone().utcoffset().total_seconds()
            adjusted_ts = int(ts - local_offset)

            # 1. BaseView (Video lines 236-237)
            date_folder = tmp_path / f'ccd_{cam.uuid}' / d_str
            date_folder.mkdir(parents=True, exist_ok=True)
            orphaned_video = date_folder / f'allsky-timelapse_ccd{cam.id}_{d_str}_day_{adjusted_ts}.mp4'
            orphaned_video.write_bytes(b'orphan')

            v = SyncApiVideoView()
            tmp_f = tmp_path / 'temp.mp4'
            tmp_f.write_bytes(b'new video')
            meta = {
                'createDate': float(ts),
                'dayDate': d_str,
                'night': False,
                'utc_offset': 0,
            }
            v.processPost(cam, meta, tmp_f, overwrite=False)
            assert orphaned_video.read_bytes() == b'new video'

            # 2. BaseImageView (Image line 529)
            target_create_date = datetime.fromtimestamp(float(adjusted_ts))
            img_folder = tmp_path / f'ccd_{cam.uuid}' / 'exposures' / target_create_date.strftime('%Y%m%d') / 'day' / target_create_date.strftime('%d_%H')
            img_folder.mkdir(parents=True, exist_ok=True)
            orphaned_img = img_folder / f'ccd{cam.id}_{target_create_date.strftime("%Y%m%d_%H%M%S")}.jpg'
            orphaned_img.write_bytes(b'orphan img')

            v_img = SyncApiImageView()
            tmp_img = tmp_path / 'temp.jpg'
            tmp_img.write_bytes(b'new img')
            meta_img = {
                'createDate': float(ts),
                'dayDate': d_str,
                'night': False,
                'exposure': 1.0,
                'gain': 100.0,
                'binmode': 1,
                'adu': 100.0,
                'adu_roi': 0,
                'detections': 0,
                'utc_offset': 0,
                'moonmode': 0,
                'moonphase': 0.0,
                'sqm': 0.0,
                'stars': 0,
                'calibrated': False,
                'stable': True,
                'temp': 0.0,
                'height': 100,
                'width': 200,
                'exp_elapsed': 1.0,
                'process_elapsed': 0.1,
                'bitdepth': 8,
            }
            v_img.processPost(cam, meta_img, tmp_img, overwrite=False)
            assert orphaned_img.read_bytes() == b'new img'

    def test_syncapi_thumbnail_branches(self, flask_app, sync_env, tmp_path):
        """Covers syncapi_views.py lines 728, 746-748, 754-769 in SyncApiThumbnailView."""
        username, raw_key, cam_uuid = sync_env
        client = flask_app.test_client()

        now = datetime.now()
        media_data = b'thumbnail bytes 123'

        # 1. Origin KEOGRAM (covers line 728)
        meta_keo = json.dumps({
            'camera_uuid': cam_uuid,
            'file_size': len(media_data),
            'uuid': 'thumb-keo-uuid-1',
            'origin': constants.KEOGRAM,
            'dayDate': now.strftime('%Y%m%d'),
            'createDate': now.timestamp(),
            'night': True,
            'width': 150,
            'height': 100,
            'utc_offset': 0,
        }).encode()
        headers_keo = make_auth_header(username, raw_key, meta_keo)
        resp_keo = client.post(
            '/indi-allsky/sync/v1/thumbnail',
            data={'metadata': (io.BytesIO(meta_keo), 'meta.json'), 'media': (io.BytesIO(media_data), 'thumb.jpg')},
            headers=headers_keo,
        )
        assert resp_keo.status_code in (200, 201)

        # 2. Origin STARTRAIL with file already existing on disk, overwrite=False -> EntryExists (lines 754-756)
        meta_st = json.dumps({
            'camera_uuid': cam_uuid,
            'file_size': len(media_data),
            'uuid': 'thumb-st-uuid-1',
            'origin': constants.STARTRAIL,
            'dayDate': now.strftime('%Y%m%d'),
            'createDate': now.timestamp(),
            'night': True,
            'width': 150,
            'height': 100,
            'utc_offset': 0,
        }).encode()
        headers_st = make_auth_header(username, raw_key, meta_st)
        resp_st1 = client.post(
            '/indi-allsky/sync/v1/thumbnail',
            data={'metadata': (io.BytesIO(meta_st), 'meta.json'), 'media': (io.BytesIO(media_data), 'thumb.jpg')},
            headers=headers_st,
        )
        assert resp_st1.status_code in (200, 201)

        # Attempt to post again (file exists, overwrite=False)
        resp_st_exists = client.post(
            '/indi-allsky/sync/v1/thumbnail',
            data={'metadata': (io.BytesIO(meta_st), 'meta.json'), 'media': (io.BytesIO(media_data), 'thumb.jpg')},
            headers=headers_st,
        )
        assert resp_st_exists.status_code == 400
        assert resp_st_exists.get_json().get('error') == 'file_exists'

        # Put (overwrite=True, replaces image and old DB entry, lines 758-768)
        resp_st_put = client.put(
            '/indi-allsky/sync/v1/thumbnail',
            data={'metadata': (io.BytesIO(meta_st), 'meta.json'), 'media': (io.BytesIO(media_data), 'thumb.jpg')},
            headers=headers_st,
        )
        assert resp_st_put.status_code in (200, 201)

        # Orphaned thumbnail entry in DB when file does NOT exist on disk (lines 746-748)
        from indi_allsky.flask.syncapi_views import SyncApiThumbnailView
        with flask_app.app_context():
            cam = IndiAllSkyDbCameraTable.query.filter_by(uuid=cam_uuid).first()
            non_existent_file = tmp_path / f'ccd_{cam_uuid}' / 'timelapse' / now.strftime('%Y%m%d') / 'thumbnails' / 'orphan_thumb.jpg'
            orphan_entry = IndiAllSkyDbThumbnailTable(
                uuid='orphan_thumb',
                filename=str(non_existent_file),
                createDate=now,
                camera_id=cam.id,
            )
            _db.session.add(orphan_entry)
            _db.session.commit()

            v_thumb = SyncApiThumbnailView()
            tmp_media = tmp_path / 'temp_thumb.jpg'
            tmp_media.write_bytes(media_data)
            meta_orphan = {
                'camera_uuid': cam_uuid,
                'uuid': 'orphan_thumb',
                'origin': constants.KEOGRAM,
                'dayDate': now.strftime('%Y%m%d'),
                'createDate': now.timestamp(),
                'night': True,
                'width': 150,
                'height': 100,
                'utc_offset': 0,
            }
            v_thumb.processPost(cam, meta_orphan, tmp_media, overwrite=False)

        # Thumbnail file exists on disk, but NO row in DB, with overwrite=True (lines 768-769)
        with flask_app.app_context():
            cam = IndiAllSkyDbCameraTable.query.filter_by(uuid=cam_uuid).first()
            existing_disk_dir = tmp_path / f'ccd_{cam_uuid}' / 'timelapse' / now.strftime('%Y%m%d') / 'thumbnails'
            existing_disk_dir.mkdir(parents=True, exist_ok=True)
            existing_disk_file = existing_disk_dir / 'nodb_thumb.jpg'
            existing_disk_file.write_bytes(media_data)

            v_thumb = SyncApiThumbnailView()
            tmp_media2 = tmp_path / 'temp_thumb2.jpg'
            tmp_media2.write_bytes(media_data)
            meta_nodb = {
                'camera_uuid': cam_uuid,
                'uuid': 'nodb_thumb',
                'origin': constants.KEOGRAM,
                'dayDate': now.strftime('%Y%m%d'),
                'createDate': now.timestamp(),
                'night': True,
                'width': 150,
                'height': 100,
                'utc_offset': 0,
            }
            v_thumb.processPost(cam, meta_nodb, tmp_media2, overwrite=True)



# ===========================================================================
# base_views.py coverage tests
# ===========================================================================

class TestBaseViewsCoverage:

    def test_base_view_camera_setup_and_helpers(self, flask_app, db):
        """Covers BaseView methods in base_views.py."""
        with flask_app.test_request_context('/?camera_id=1'):
            bv = BaseView()
            bv.cameraSetup()
            assert bv.camera is not None

            # getCameraById with missing id returns FakeCamera
            fc1 = bv.getCameraById(99999)
            assert isinstance(fc1, FakeCamera)

            # getCameraById(-1) returns FakeCamera if no camera or returns current camera
            fc_or_cam = bv.getCameraById(-1)
            assert fc_or_cam is not None

            # getCameraById(-1) when no camera in DB (lines 123-124)
            with patch('indi_allsky.flask.base_views.IndiAllSkyDbCameraTable') as mock_cam_cls:
                mock_cam_cls.query.order_by.return_value.first.return_value = None
                fc_none = bv.getCameraById(-1)
                assert isinstance(fc_none, FakeCamera)

            # getCameraPrivacyLatLong (lines 141-144)
            cam = bv.camera
            orig_elev = cam.elevation
            orig_data = cam.data
            orig_alt = cam.alt
            orig_az = cam.az
            try:
                lat, lon = bv.getCameraPrivacyLatLong(cam)
                assert lat == cam.latitude
                assert lon == cam.longitude

                # PRIVACY_MODE on
                bv.indi_allsky_config['PRIVACY_MODE'] = True
                lat_p, lon_p = bv.getCameraPrivacyLatLong(cam)
                assert lat_p == float(round(cam.latitude))
                assert lon_p == float(round(cam.longitude))
                bv.indi_allsky_config['PRIVACY_MODE'] = False

                # camera_data populated (line 93)
                cam.data = {'TEST_KEY': '123'}
                bv.camera = cam
                bv.cameraSetup()
                assert bv.camera_data == {'TEST_KEY': '123'}

                # camera.elevation is None (line 212)
                cam.elevation = None
                cam.alt = 45.0
                cam.az = 180.0
                bv.camera = cam
                bv.getSunSetDate()
                assert bv.sun_set_date is not None

                # camera.alt and az floats (lines 337, 342)
                cinfo = bv.get_camera_info()
                assert cinfo['alt'] == 45.0
                assert cinfo['az'] == 180.0

                # AlwaysUpError and NeverUpError in getSunSetDate (lines 234-239)
                with patch('indi_allsky.flask.base_views.ephem.Observer') as mock_obs_cls:
                    mock_obs = mock_obs_cls.return_value
                    mock_obs.next_setting.side_effect = ephem.AlwaysUpError()
                    bv.getSunSetDate()
                    assert bv.sun_set_date is None

                    mock_obs.next_setting.side_effect = ephem.NeverUpError()
                    bv.getSunSetDate()
                    assert bv.sun_set_date is None
            finally:
                cam.elevation = orig_elev
                cam.data = orig_data
                cam.alt = orig_alt
                cam.az = orig_az

    def test_base_view_admin_network_verification(self, flask_app):
        """Covers BaseView.verify_admin_network."""
        flask_app.config['ADMIN_NETWORKS'] = ['127.0.0.1/32', 'invalid_network_cidr']
        with flask_app.test_request_context('/', environ_base={'REMOTE_ADDR': '127.0.0.1'}):
            bv = BaseView()
            assert bv.verify_admin_network() is True

        with flask_app.test_request_context('/', environ_base={'REMOTE_ADDR': '198.51.100.1'}):
            bv = BaseView()
            assert bv.verify_admin_network() is False

        # With X-Forwarded-For and invalid client IP
        with flask_app.test_request_context('/', headers={'X-Forwarded-For': 'invalid_client_ip'}):
            bv = BaseView()
            assert bv.verify_admin_network() is False

        with flask_app.test_request_context('/', headers={'X-Forwarded-For': '127.0.0.1'}):
            bv = BaseView()
            assert bv.verify_admin_network() is True

    def test_base_view_systemd_methods(self, flask_app):
        """Covers systemd unit operations with dbus mocked."""
        bv = BaseView()
        mock_bus = MagicMock()
        mock_mgr = MagicMock()
        mock_bus.get_object.return_value = mock_mgr

        with patch('dbus.SessionBus', return_value=mock_bus), \
             patch('dbus.Interface', return_value=mock_mgr):
            bv.startSystemdUnit('test.service')
            bv.stopSystemdUnit('test.service')
            bv.restartSystemdUnit('test.service')
            bv.hupSystemdUnit('test.service')
            bv.enableSystemdUnit('test.service')
            bv.disableSystemdUnit('test.service')

    def test_base_view_status_branches(self, flask_app, db):
        """Covers all branches of get_indi_allsky_status."""
        with flask_app.test_request_context('/?camera_id=1'):
            bv = BaseView()
            bv.cameraSetup()

            # Remote indi-allsky
            bv.local_indi_allsky = False
            assert 'REMOTE' in bv.get_indi_allsky_status()['status']
            bv.local_indi_allsky = True

            # Watchdog ValueError
            with patch.object(bv._miscDb, 'getState', side_effect=ValueError('bad')):
                assert 'UNKNOWN' in bv.get_indi_allsky_status()['status']

            # Watchdog expired (> 600s)
            with patch.object(bv._miscDb, 'getState', return_value=str(int(time.time() - 1000))):
                assert 'DOWN' in bv.get_indi_allsky_status()['status']

            # FOCUS_MODE on
            bv.indi_allsky_config['FOCUS_MODE'] = True
            with patch.object(bv._miscDb, 'getState', return_value=str(int(time.time()))):
                assert 'FOCUS MODE' in bv.get_indi_allsky_status()['status']
            bv.indi_allsky_config['FOCUS_MODE'] = False

            # STATUS NoResultFound and ValueError
            def mock_get_state(k):
                if k == 'WATCHDOG':
                    return str(int(time.time()))
                if k == 'STATUS':
                    raise NoResultFound()
                return '0'

            with patch.object(bv._miscDb, 'getState', side_effect=mock_get_state):
                assert 'RUNNING' in bv.get_indi_allsky_status()['status']

            def mock_get_state_ve(k):
                if k == 'WATCHDOG':
                    return str(int(time.time()))
                if k == 'STATUS':
                    raise ValueError()
                return '0'

            with patch.object(bv._miscDb, 'getState', side_effect=mock_get_state_ve):
                assert 'UNKNOWN' in bv.get_indi_allsky_status()['status']

            # All status constants
            status_map = {
                constants.STATUS_RUNNING: 'RUNNING',
                constants.STATUS_SLEEPING: 'SLEEPING',
                constants.STATUS_RELOADING: 'RELOADING',
                constants.STATUS_STARTING: 'STARTING',
                constants.STATUS_STOPPING: 'STOPPING',
                constants.STATUS_STOPPED: 'STOPPED',
                constants.STATUS_PAUSED: 'PAUSED',
                constants.STATUS_NOCAMERA: 'NO CAMERA',
                constants.STATUS_CAMERAERROR: 'CAMERA ERROR',
                constants.STATUS_NOINDISERVER: 'NO INDISERVER',
                999: 'UNKNOWN',
            }
            for code, label in status_map.items():
                def make_st(c=code):
                    return lambda k: str(int(time.time())) if k == 'WATCHDOG' else str(c)
                with patch.object(bv._miscDb, 'getState', side_effect=make_st()):
                    res = bv.get_indi_allsky_status()
                    assert label in res['status']

    def test_base_view_astrometric_and_sun_branches(self, flask_app):
        """Covers all branches in get_astrometric_info."""
        with flask_app.test_request_context('/?camera_id=1'):
            bv = BaseView()
            bv.cameraSetup()

            # Empty config returns {}
            orig_cfg = bv.indi_allsky_config
            bv.indi_allsky_config = {}
            assert bv.get_astrometric_info() == {}
            bv.indi_allsky_config = orig_cfg

            orig_elev = bv.camera.elevation
            orig_alt = bv.camera.nightSunAlt
            orig_lat = bv.camera.latitude
            try:
                # Elevation is None and PRIVACY_MODE is True
                bv.camera.elevation = None
                bv.indi_allsky_config['PRIVACY_MODE'] = True
                astro = bv.get_astrometric_info()
                assert astro['elevation'] == 0
                assert astro['latitude'] == 0.0
                bv.indi_allsky_config['PRIVACY_MODE'] = False

                # Day mode (sun_alt > nightSunAlt)
                bv.camera.nightSunAlt = -90.0
                astro_day = bv.get_astrometric_info()
                assert astro_day['mode'] == 'Day'
                assert bv.night is False

                # Northern hemisphere (latitude > 0)
                bv.camera.latitude = 51.5
                astro_north = bv.get_astrometric_info()
                assert 'moon_glyph' in astro_north

                # Waning moon branch and moon_dir rising branch (lines 422, 450, 474)
                mock_sun_ecl = MagicMock()
                mock_sun_ecl.lon = 0.0
                mock_moon_ecl = MagicMock()
                mock_moon_ecl.lon = 3.5  # Waning (moon_quarter >= 2, moon_cycle_percent > 50)
                with patch('ephem.Ecliptic', side_effect=[mock_sun_ecl, mock_moon_ecl]):
                    with patch('ephem.Observer.next_transit') as mock_transit:
                        mock_transit.return_value.datetime.return_value = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=2)
                        astro_waning = bv.get_astrometric_info()
                        assert astro_waning['moon_phase_str'] == 'Waning'
                        assert astro_waning['moon_dir'] == '&nearr;'

                # Ephem NeverUpError and AlwaysUpError on rising/setting calls
                for err in (ephem.NeverUpError(), ephem.AlwaysUpError()):
                    with patch('ephem.Observer.next_rising', side_effect=err), \
                         patch('ephem.Observer.next_setting', side_effect=err):
                        res = bv.get_astrometric_info()
                        assert res['mode_next_change'] == '--:--'
                        assert res['sun_next_rise'] == '--:--'
                        assert res['sun_next_set'] == '--:--'
                        assert res['moon_next_rise'] == '--:--'
                        assert res['moon_next_set'] == '--:--'
                        assert res['sun_next_astro_twilight_rise'] == '--:--'
                        assert res['sun_next_astro_twilight_set'] == '--:--'
            finally:
                bv.camera.elevation = orig_elev
                bv.camera.nightSunAlt = orig_alt
                bv.camera.latitude = orig_lat

    def test_base_view_aurora_and_smoke_info(self, flask_app):
        """Covers get_aurora_info and get_smoke_info branches."""
        with flask_app.test_request_context():
            bv = BaseView()

            # Empty camera_data
            bv.camera_data = {}
            aurora_none = bv.get_aurora_info()
            assert aurora_none['aurora_data_status'] == 'No data'
            smoke_none = bv.get_smoke_info()
            assert smoke_none['smoke_rating'] == 'No data'

            # Populated camera_data with old timestamp (> 6 hours)
            old_ts = int((datetime.now() - timedelta(hours=10)).timestamp())
            bv.camera_data = {
                'KPINDEX_CURRENT': 5.5,
                'KPINDEX_COEF': 2.5,
                'AURORA_DATA_TS': old_ts,
                'SMOKE_RATING': constants.SMOKE_RATING_MEDIUM,
                'SMOKE_DATA_TS': int((datetime.now() - timedelta(hours=30)).timestamp()),
            }
            aurora_old = bv.get_aurora_info()
            assert aurora_old['aurora_data_status'] == '[old]'
            smoke_old = bv.get_smoke_info()
            assert smoke_old['smoke_rating_status'] == '[old]'

            # Fresh data with various kpindex ratings and coefficients
            fresh_ts = int(datetime.now().timestamp())
            for kp, rating in [
                (0.0, ''), (3.0, 'LOW'), (5.5, 'MEDIUM'), (7.0, 'HIGH'), (9.0, 'VERY HIGH'), (-1.0, 'ERROR')
            ]:
                for coef, trend in [(0.0, ''), (2.5, '&nearr;'), (0.3, '&searr;'), (1.0, '&rarr;')]:
                    bv.camera_data = {
                        'KPINDEX_CURRENT': kp,
                        'KPINDEX_COEF': coef,
                        'AURORA_DATA_TS': fresh_ts,
                    }
                    info = bv.get_aurora_info()
                    assert info['kpindex_trend'] == trend
                    if rating:
                        assert rating in info['kpindex_rating']

    def test_base_view_longitude_validation_and_image_data(self, flask_app, db):
        """Covers validate_longitude_timezone and get_image_data."""
        with flask_app.test_request_context('/?camera_id=1'):
            bv = BaseView()
            bv.cameraSetup()

            # validate_longitude_timezone
            bv.indi_allsky_config['LOCATION_LONGITUDE'] = 138.6
            bv.indi_allsky_config['LOCATION_LATITUDE'] = -34.9
            res_val = bv.validate_longitude_timezone()
            assert isinstance(res_val, bool)

            # get_image_data with populated sensors
            img = IndiAllSkyDbImageTable(
                camera_id=bv.camera.id,
                exposure=5.0,
                exp_elapsed=5.1,
                gain=100.0,
                binmode=1,
                temp=15.0,
                adu=20000.0,
                sqm=19.5,
                stars=100,
                detections=1,
                process_elapsed=0.5,
                data={
                    'sensor_user_1': 1.0,  # dew heater on
                    'sensor_user_4': 1.0,  # fan on
                    'sensor_user_6': 999999.0,  # invalid wind dir index
                    'sensor_user_100': 999999,  # invalid rain status
                },
                createDate=datetime.now(),
            )
            bv.latest_image_entry = img
            img_data = bv.get_image_data()
            assert img_data['dew_heater_status'] == 'On'
            assert img_data['fan_status'] == 'On'
            assert img_data['wind_dir'] == 'Error'
            assert img_data['rain_status'] == 'Error'

    def test_base_view_status_text_and_web_extra_text(self, flask_app, tmp_path):
        """Covers get_status_text error branches and get_web_extra_text."""
        bv = BaseView()

        # get_status_text KeyError (lines 875-876)
        bv.indi_allsky_config['WEB_STATUS_TEMPLATE'] = '{nonexistent_key_12345}'
        assert bv.get_status_text({'status': 'Running'}) == 'TEMPLATE ERROR'

        # get_status_text ValueError
        bv.indi_allsky_config['WEB_STATUS_TEMPLATE'] = '{status:d}'  # non-int value causes ValueError
        assert bv.get_status_text({'status': 'Running'}) == 'TEMPLATE ERROR'

        # get_web_extra_text: no config
        bv.indi_allsky_config['WEB_EXTRA_TEXT'] = ''
        assert bv.get_web_extra_text() == ''

        # non-existent file
        bv.indi_allsky_config['WEB_EXTRA_TEXT'] = str(tmp_path / 'missing.txt')
        assert bv.get_web_extra_text() == ''

        # directory
        bv.indi_allsky_config['WEB_EXTRA_TEXT'] = str(tmp_path)
        assert bv.get_web_extra_text() == ''

        # file too large (> 10000 bytes)
        large_f = tmp_path / 'large.txt'
        large_f.write_bytes(b'A' * 10001)
        bv.indi_allsky_config['WEB_EXTRA_TEXT'] = str(large_f)
        assert bv.get_web_extra_text() == ''

        # PermissionError on stat
        with patch.object(Path, 'stat', side_effect=PermissionError('denied')):
            assert bv.get_web_extra_text() == ''

        # valid file
        valid_f = tmp_path / 'extra.txt'
        valid_f.write_text('Line 1\nLine 2', encoding='utf-8')
        bv.indi_allsky_config['WEB_EXTRA_TEXT'] = str(valid_f)
        assert '<div>Line 1</div><div>Line 2</div>' in bv.get_web_extra_text()

        # PermissionError on open
        with patch('io.open', side_effect=PermissionError('open denied')):
            assert bv.get_web_extra_text() == ''

    def test_base_view_load_detection_mask(self, flask_app, tmp_path):
        """Covers _load_detection_mask branches."""
        bv = BaseView()

        # empty DETECT_MASK
        bv.indi_allsky_config['DETECT_MASK'] = ''
        assert bv._load_detection_mask(1) is None

        # non-existent
        bv.indi_allsky_config['DETECT_MASK'] = str(tmp_path / 'missing.png')
        assert bv._load_detection_mask(1) is None

        # directory
        bv.indi_allsky_config['DETECT_MASK'] = str(tmp_path)
        assert bv._load_detection_mask(1) is None

        # PermissionError
        with patch.object(Path, 'is_file', side_effect=PermissionError('denied')):
            assert bv._load_detection_mask(1) is None

        # invalid image (cv2.imread returns None)
        mask_f = tmp_path / 'mask.png'
        mask_f.write_bytes(b'not an image')
        bv.indi_allsky_config['DETECT_MASK'] = str(mask_f)
        with patch('cv2.imread', return_value=None):
            assert bv._load_detection_mask(1) is None

        # valid image
        import numpy as np
        fake_mask = np.zeros((100, 100), dtype=np.uint8)
        fake_mask[10:20, 10:20] = 128
        with patch('cv2.imread', return_value=fake_mask):
            res_mask = bv._load_detection_mask(1)
            assert res_mask is not None

    def test_base_view_dbus_status_and_timer_trigger(self, flask_app):
        """Covers getSystemdUnitStatus and getSystemdTimerTrigger."""
        bv = BaseView()

        def throwing_bus():
            raise dbus.exceptions.DBusException('bus err')

        # getSystemdUnitStatus: DBusException on bus
        s1, s2 = bv.getSystemdUnitStatus('test.service', bus_type=throwing_bus)
        assert s1 == 'D-Bus Unavailable'

        # DBusException on LoadUnit
        mock_bus = MagicMock()
        mock_mgr = MagicMock()
        mock_bus.get_object.return_value = mock_mgr
        mock_mgr.LoadUnit.side_effect = dbus.exceptions.DBusException('load err')
        with patch('dbus.Interface', return_value=mock_mgr):
            s1, s2 = bv.getSystemdUnitStatus('test.service', bus_type=lambda: mock_bus)
            assert s1 == 'UNKNOWN'

        # getSystemdTimerTrigger: DBusException on bus
        assert bv.getSystemdTimerTrigger('test.timer', bus_type=throwing_bus) == -1

        # DBusException on LoadUnit
        with patch('dbus.Interface', return_value=mock_mgr):
            assert bv.getSystemdTimerTrigger('test.timer', bus_type=lambda: mock_bus) == -1

        # next_usec == 18446744073709551615 (already triggered)
        mock_mgr.LoadUnit.side_effect = None
        mock_iface = MagicMock()
        mock_iface.Get.return_value = 18446744073709551615
        with patch('dbus.Interface', return_value=mock_iface):
            assert bv.getSystemdTimerTrigger('test.timer', bus_type=lambda: mock_bus) == -1

        # valid next_usec calculation
        mock_iface.Get.return_value = int((time.time() - psutil.boot_time() + 60) * 1000000)
        with patch('dbus.Interface', return_value=mock_iface):
            assert bv.getSystemdTimerTrigger('test.timer', bus_type=lambda: mock_bus) > 0

    def test_template_view_check_config_and_session(self, flask_app, db):
        """Covers TemplateView check_config, setupSession, get_user_info, and context."""
        with flask_app.test_request_context('/?camera_id=1'):
            tv = TemplateView('index.html')
            tv.local_indi_allsky = True

            # check_config: matching config_id
            cfg_obj = MagicMock()
            cfg_obj.config_id = 1
            with patch.object(tv._miscDb, 'getState', return_value='1'):
                tv.check_config(cfg_obj)

            # check_config: created within 10 min
            cfg_obj.config_id = 2
            cfg_obj.createDate = datetime.now(tz=timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
            with patch.object(tv._miscDb, 'getState', return_value='1'):
                tv.check_config(cfg_obj)

            # check_config: created > 10 min ago (notification added, line 1251)
            cfg_obj.config_id = 2
            cfg_obj.createDate = datetime.now(tz=timezone.utc).replace(tzinfo=None) - timedelta(minutes=15)
            with patch.object(tv._miscDb, 'getState', return_value='1'), \
                 patch.object(tv._miscDb, 'addNotification') as mock_notif:
                tv.check_config(cfg_obj)
                assert mock_notif.called

            # check_config: NoResultFound and ValueError (lines 1260-1262)
            with patch.object(tv._miscDb, 'getState', side_effect=NoResultFound()):
                tv.check_config(cfg_obj)
            with patch.object(tv._miscDb, 'getState', side_effect=ValueError()):
                tv.check_config(cfg_obj)

            # setupSession: NoResultFound when session is empty (lines 1272-1273)
            from flask import session as flask_session
            flask_session.clear()
            with patch.object(tv, 'getLatestCamera', side_effect=NoResultFound()):
                tv.setupSession()
                assert isinstance(tv.camera, FakeCamera)
                assert flask_session['camera_id'] == -1

            # get_user_info authenticated vs anonymous
            u_anon = tv.get_user_info()
            assert 'Login' in u_anon

            # getUptime
            upt = tv.getUptime()
            assert 'days' in upt

    def test_fake_camera_and_json_view(self, flask_app):
        """Covers FakeCamera and JsonView."""
        fc = FakeCamera()
        assert fc.id == -1
        assert fc.name == ''
        assert fc.local is True

        jv = JsonView()
        with pytest.raises(NotImplementedError):
            jv.get_objects()

    def test_base_view_dbus_fallbacks_and_errors(self, flask_app):
        """Covers D-Bus fallback buses, property exceptions, and timer zero."""
        bv = BaseView()

        # _get_systemd_bus with bus_type=None: SystemBus fails, SessionBus succeeds
        mock_session_bus = MagicMock()
        with patch('dbus.SystemBus', side_effect=Exception('no sys bus')), \
             patch('dbus.SessionBus', return_value=mock_session_bus):
            assert bv._get_systemd_bus(None) == mock_session_bus

        # _get_systemd_bus with bus_type=None: both fail -> raises DBusException
        with patch('dbus.SystemBus', side_effect=Exception('no sys bus')), \
             patch('dbus.SessionBus', side_effect=Exception('no session bus')):
            with pytest.raises(dbus.exceptions.DBusException):
                bv._get_systemd_bus(None)

        # getSystemdUnitStatus: interface.Get raises DBusException on ActiveState and UnitFileState
        mock_bus = MagicMock()
        mock_mgr = MagicMock()
        mock_service = MagicMock()
        mock_bus.get_object.return_value = mock_service
        mock_mgr.LoadUnit.return_value = 'unit_path'

        mock_iface = MagicMock()
        mock_iface.Get.side_effect = dbus.exceptions.DBusException('prop err')
        mock_mgr.GetUnitFileState.side_effect = dbus.exceptions.DBusException('mgr err')

        with patch('dbus.Interface', side_effect=[mock_mgr, mock_iface]):
            s1, s2 = bv.getSystemdUnitStatus('test.service', bus_type=lambda: mock_bus)
            assert s1 == 'UNKNOWN'
            assert s2 == 'UNKNOWN'

        # getSystemdUnitStatus: manager.GetUnitFileState raises DBusException when unit_active_state is inactive
        def get_side_effect(iface_name, prop_name):
            if prop_name == 'ActiveState':
                return 'inactive'
            raise dbus.exceptions.DBusException('no unit file state')

        mock_iface.Get.side_effect = get_side_effect
        mock_mgr.GetUnitFileState.side_effect = dbus.exceptions.DBusException('mgr err')
        with patch('dbus.Interface', side_effect=[mock_mgr, mock_iface]):
            s1, s2 = bv.getSystemdUnitStatus('test.service', bus_type=lambda: mock_bus)
            assert s1 == 'inactive'
            assert s2 == 'disabled'

        # getSystemdTimerTrigger: interface.Get raises DBusException
        mock_iface.Get.side_effect = dbus.exceptions.DBusException('timer prop err')
        with patch('dbus.Interface', side_effect=[mock_mgr, mock_iface]):
            assert bv.getSystemdTimerTrigger('test.timer', bus_type=lambda: mock_bus) == -1

        # getSystemdTimerTrigger: next_usec == 0
        mock_iface.Get.side_effect = None
        mock_iface.Get.return_value = 0
        with patch('dbus.Interface', side_effect=[mock_mgr, mock_iface]):
            assert bv.getSystemdTimerTrigger('test.timer', bus_type=lambda: mock_bus) == -1

    def test_base_view_astrometric_and_sensor_missing_coverage(self, flask_app):
        """Covers moon_dir setting branch and get_sensor_info without latest_image_entry."""
        bv = BaseView()
        bv.camera = MagicMock()
        bv.camera.longitude = 0.0
        bv.camera.latitude = 0.0
        bv.camera.elevation = 0
        bv.camera.utc_offset = 0
        bv.camera.nightSunAlt = -6.0
        bv.indi_allsky_config = {
            'PRIVACY_MODE': False,
            'NIGHT_SUN_ALT_DEG': -6.0,
        }

        fake_transit = datetime.now(tz=timezone.utc).replace(tzinfo=None) + timedelta(hours=15)
        with patch('ephem.Observer.next_transit', return_value=MagicMock(datetime=lambda: fake_transit)):
            data = bv.get_astrometric_info()
            assert data.get('moon_dir') == '&searr;'

        bv.latest_image_entry = None
        bv.cardinal_directions = ['N', 'E', 'S', 'W', 'N']
        sensor_data = bv.get_image_data()
        assert sensor_data['exposure'] == 0.0
        assert sensor_data['dew_heater_status'] == 'No data'
        assert sensor_data['fan_status'] == 'No data'
        assert sensor_data['wind_dir'] == 'No data'
        assert sensor_data['rain_status'] == 'No data'



