import os
import io
import sys
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

# Global mocks for google oauth libraries if not installed
if 'google_auth_oauthlib' not in sys.modules:
    mock_gao = MagicMock()
    mock_flow = MagicMock()
    mock_gao.flow = mock_flow
    sys.modules['google_auth_oauthlib'] = mock_gao
    sys.modules['google_auth_oauthlib.flow'] = mock_flow

if 'google.oauth2.credentials' not in sys.modules:
    mock_google = sys.modules.get('google', MagicMock())
    mock_oauth2 = MagicMock()
    mock_creds_mod = MagicMock()
    mock_oauth2.credentials = mock_creds_mod
    mock_google.oauth2 = mock_oauth2
    sys.modules['google'] = mock_google
    sys.modules['google.oauth2'] = mock_oauth2
    sys.modules['google.oauth2.credentials'] = mock_creds_mod

if 'oauthlib' not in sys.modules:
    mock_oauthlib = MagicMock()
    mock_oauth2 = MagicMock()
    mock_rfc = MagicMock()
    mock_errors = MagicMock()
    class InvalidGrantError(Exception):
        pass
    mock_errors.InvalidGrantError = InvalidGrantError
    mock_rfc.errors = mock_errors
    mock_oauth2.rfc6749 = mock_rfc
    mock_oauthlib.oauth2 = mock_oauth2
    sys.modules['oauthlib'] = mock_oauthlib
    sys.modules['oauthlib.oauth2'] = mock_oauth2
    sys.modules['oauthlib.oauth2.rfc6749'] = mock_rfc
    sys.modules['oauthlib.oauth2.rfc6749.errors'] = mock_errors

if 'google.auth.transport.requests' not in sys.modules:
    mock_google_auth = sys.modules.get('google.auth', MagicMock())
    mock_transport = MagicMock()
    mock_requests_mod = MagicMock()
    mock_transport.requests = mock_requests_mod
    mock_google_auth.transport = mock_transport
    sys.modules['google.auth'] = mock_google_auth
    sys.modules['google.auth.transport'] = mock_transport
    sys.modules['google.auth.transport.requests'] = mock_requests_mod

import pytest
from passlib.hash import argon2

from indi_allsky import constants
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbThumbnailTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbBadPixelMapTable,
    IndiAllSkyDbDarkFrameTable,
    IndiAllSkyDbVideoTable,
    IndiAllSkyDbMiniVideoTable,
    IndiAllSkyDbKeogramTable,
    IndiAllSkyDbStarTrailsTable,
    IndiAllSkyDbStarTrailsVideoTable,
    IndiAllSkyDbFitsImageTable,
    IndiAllSkyDbRawImageTable,
    IndiAllSkyDbPanoramaImageTable,
    IndiAllSkyDbPanoramaVideoTable,
    IndiAllSkyDbLongTermKeogramTable,
    IndiAllSkyDbTaskQueueTable,
    IndiAllSkyDbNotificationTable,
    IndiAllSkyDbStateTable,
    IndiAllSkyDbUserTable,
    IndiAllSkyDbConfigTable,
    TaskQueueState,
    TaskQueueQueue,
    NotificationCategory,
)
from indi_allsky.flask.miscDb import miscDb
from indi_allsky.flask import db as _db


@pytest.fixture(autouse=True)
def _base_env(flask_app, db):
    flask_app.config['ADMIN_NETWORKS'] = ['127.0.0.1/32']
    with flask_app.app_context():
        if not IndiAllSkyDbCameraTable.query.first():
            db.session.add(IndiAllSkyDbCameraTable(
                name="models_test_camera",
                uuid="models-cam-uuid-1",
                friendlyName="Models Camera",
                latitude=-34.9, longitude=138.6, elevation=50,
                nightSunAlt=-6.0, local=True,
            ))
        if not IndiAllSkyDbConfigTable.query.first():
            db.session.add(IndiAllSkyDbConfigTable(
                data={'WEBSITE': {'TITLE': 'indi-allsky'}},
                level='1.0', note='test',
            ))
        db.session.commit()


# ===========================================================================
# models.py coverage tests
# ===========================================================================

class TestModelsCoverage:

    def test_camera_model_virtual_properties_and_methods(self, flask_app, db):
        """Covers lines 123, 127, 131, 136 in models.py."""
        with flask_app.app_context():
            cam = IndiAllSkyDbCameraTable.query.first()
            assert cam.filename == 'camera'
            assert cam.validateFile() is True
            cam.deleteFile()  # no-op
            assert cam.getFilesystemPath() == 'camera'

    def test_file_base_relative_path_and_url(self, flask_app, tmp_path, db):
        """Covers lines 151-153, 158-161, 174, 182-187, 191-196, 202-217 in models.py."""
        with flask_app.app_context():
            flask_app.config['INDI_ALLSKY_IMAGE_FOLDER'] = str(tmp_path)
            cam = IndiAllSkyDbCameraTable.query.first()

            # Relative filename
            img_rel = IndiAllSkyDbImageTable(
                camera_id=cam.id,
                filename='test_folder/image1.jpg',
                createDate=datetime.now(),
                dayDate=datetime.now().date(),
                exposure=1.0, gain=100.0, adu=100.0,
            )
            assert img_rel.getRelativePath() == Path('test_folder/image1.jpg')
            assert img_rel.getFilesystemPath() == tmp_path / 'test_folder/image1.jpg'
            assert img_rel.validateFile() is False  # file doesn't exist yet

            # Create file
            full_p = img_rel.getFilesystemPath()
            full_p.parent.mkdir(parents=True, exist_ok=True)
            full_p.write_bytes(b'dummy')
            assert img_rel.validateFile() is True

            # getUrl tests
            assert img_rel.getUrl(local=True) == Path('images/test_folder/image1.jpg')
            img_rel.remote_url = 'https://cdn.example.com/img1.jpg'
            assert img_rel.getUrl(local=False) == 'https://cdn.example.com/img1.jpg'
            img_rel.remote_url = None
            img_rel.s3_key = 's3key/img1.jpg'
            assert img_rel.getUrl(s3_prefix='https://s3.aws.com/bucket', local=False) == 'https://s3.aws.com/bucket/s3key/img1.jpg'

            # Absolute filename
            abs_file = tmp_path / 'sub' / 'abs.jpg'
            img_abs = IndiAllSkyDbImageTable(
                camera_id=cam.id,
                filename=str(abs_file),
                createDate=datetime.now(),
                dayDate=datetime.now().date(),
                exposure=1.0, gain=100.0, adu=100.0,
            )
            assert img_abs.getRelativePath() == Path('sub/abs.jpg')
            assert img_abs.getFilesystemPath() == abs_file

            # deleteFile with non-existent file (FileNotFoundError caught)
            img_abs.deleteFile()

            # deleteAsset with thumbnail
            thumb = IndiAllSkyDbThumbnailTable(
                uuid='thumb-uuid-1',
                filename=str(tmp_path / 'thumb.jpg'),
                createDate=datetime.now(),
                camera_id=cam.id,
            )
            db.session.add(thumb)
            db.session.commit()

            img_rel.thumbnail_uuid = 'thumb-uuid-1'
            db.session.add(img_rel)
            db.session.commit()

            img_rel.deleteAsset()

            # Orphan thumbnail uuid (NoResultFound branch)
            img_orphan = IndiAllSkyDbImageTable(
                filename=str(tmp_path / 'orphan.jpg'),
                createDate=datetime.now(),
                dayDate=datetime.now().date(),
                exposure=1.0, gain=0.0, adu=0.0,
                camera_id=cam.id,
                thumbnail_uuid='nonexistent-thumb-uuid-999',
            )
            img_orphan.deleteAsset()

            # Thumbnail table virtual properties
            assert thumb.thumbnail_uuid is None
            thumb.deleteAsset()

    def test_model_reprs(self, flask_app, db):
        """Covers __repr__ across all file tables in models.py."""
        with flask_app.app_context():
            cam = IndiAllSkyDbCameraTable.query.first()
            now = datetime.now()
            today = now.date()

            thumb = IndiAllSkyDbThumbnailTable(filename='t.jpg', createDate=now, camera_id=cam.id)
            img = IndiAllSkyDbImageTable(filename='i.jpg', createDate=now, dayDate=today, exposure=1.0, gain=0.0, adu=0.0, camera_id=cam.id)
            dark = IndiAllSkyDbDarkFrameTable(filename='d.jpg', createDate=now, bitdepth=8, exposure=1, gain=0.0, camera_id=cam.id)
            bpm = IndiAllSkyDbBadPixelMapTable(filename='b.jpg', createDate=now, bitdepth=8, exposure=1, gain=0.0, camera_id=cam.id)
            vid = IndiAllSkyDbVideoTable(filename='v.mp4', createDate=now, dayDate=today, camera_id=cam.id)
            mvid = IndiAllSkyDbMiniVideoTable(filename='mv.mp4', createDate=now, dayDate=today, targetDate=now, startDate=now, endDate=now, note='n', camera_id=cam.id)
            keo = IndiAllSkyDbKeogramTable(filename='k.jpg', createDate=now, dayDate=today, camera_id=cam.id)
            st = IndiAllSkyDbStarTrailsTable(filename='s.jpg', createDate=now, dayDate=today, camera_id=cam.id)
            stv = IndiAllSkyDbStarTrailsVideoTable(filename='sv.mp4', createDate=now, dayDate=today, camera_id=cam.id)
            fits = IndiAllSkyDbFitsImageTable(filename='f.fits', createDate=now, dayDate=today, exposure=1.0, gain=0.0, camera_id=cam.id)
            raw = IndiAllSkyDbRawImageTable(filename='r.raw', createDate=now, dayDate=today, exposure=1.0, gain=0.0, camera_id=cam.id)
            pano = IndiAllSkyDbPanoramaImageTable(filename='p.jpg', createDate=now, dayDate=today, exposure=1.0, gain=0.0, camera_id=cam.id)
            panov = IndiAllSkyDbPanoramaVideoTable(filename='pv.mp4', createDate=now, dayDate=today, camera_id=cam.id)

            assert 'Thumbnail' in repr(thumb)
            assert 'Image' in repr(img)
            assert 'DarkFrame' in repr(dark)
            assert dark.remote_url is None
            assert dark.s3_key is None
            assert 'BadPixelMap' in repr(bpm)
            assert bpm.remote_url is None
            assert bpm.s3_key is None
            assert 'Video' in repr(vid)
            assert 'Mini Video' in repr(mvid)
            assert 'Keogram' in repr(keo)
            assert 'StarTrails' in repr(st)
            assert 'StarTrailVideo' in repr(stv)
            assert 'FitsImage' in repr(fits)
            assert 'RawImage' in repr(raw)
            assert 'PanoramaImage' in repr(pano)
            assert 'PanoramaVideo' in repr(panov)

    def test_task_queue_table_state_methods(self, flask_app, db):
        """Covers lines 860-879 in models.py."""
        with flask_app.app_context():
            task = IndiAllSkyDbTaskQueueTable(
                queue=TaskQueueQueue.MAIN,
                state=TaskQueueState.MANUAL,
            )
            db.session.add(task)
            db.session.commit()

            task.setQueued()
            assert task.state == TaskQueueState.QUEUED
            task.setRunning()
            assert task.state == TaskQueueState.RUNNING
            task.setSuccess('done')
            assert task.state == TaskQueueState.SUCCESS
            assert task.result == 'done'
            task.setFailed('err')
            assert task.state == TaskQueueState.FAILED
            assert task.result == 'err'
            task.setExpired()
            assert task.state == TaskQueueState.EXPIRED

    def test_notification_table_methods(self, flask_app, db):
        """Covers lines 907-914 in models.py."""
        with flask_app.app_context():
            notif = IndiAllSkyDbNotificationTable(
                category=NotificationCategory.GENERAL,
                item='test_item',
                notification='test msg',
                expireDate=datetime.now() + timedelta(hours=1),
            )
            db.session.add(notif)
            db.session.commit()

            notif.setAck()
            assert notif.ack is True
            notif.setExpired()
            assert notif.expireDate <= datetime.now()

    def test_user_table_properties_and_apikey(self, flask_app, db):
        """Covers lines 972, 977, 995-997 in models.py."""
        password_key = flask_app.config['PASSWORD_KEY']
        with flask_app.app_context():
            u = IndiAllSkyDbUserTable(
                username='modeltestuser',
                password=argon2.hash('ValidPassword123!'),
                email='model@example.com',
                active=True, staff=True, admin=True,
            )
            db.session.add(u)
            db.session.commit()

            assert u.is_active is True
            assert u.is_authenticated is True
            assert u.is_anonymous is False
            assert u.is_staff is True
            assert u.is_admin is True
            assert u.get_id() == u.id

            u.setApiKey('raw_api_secret_key_123', password_key)
            assert u.getApiKey(password_key) == 'raw_api_secret_key_123'


# ===========================================================================
# miscDb.py coverage tests
# ===========================================================================

class TestMiscDbCoverage:

    def test_add_camera_name_match_and_updates(self, flask_app, db):
        """Covers addCamera name matching and data update branches."""
        with flask_app.app_context():
            mdb = miscDb({})
            metadata = {
                'name': 'Camera Match Test',
                'serialNumber': '',  # no serial
                'connected': True,
                'data': {'custom_prop': 42},
            }
            cam = mdb.addCamera(metadata)
            assert cam.name == 'Camera Match Test'
            assert cam.data.get('custom_prop') == 42

            # Match again by name
            metadata2 = {
                'name': 'Camera Match Test',
                'serialNumber': 'SN-NEW-99',
                'connected': True,
                'data': {'custom_prop': 43},
            }
            cam2 = mdb.addCamera(metadata2)
            assert cam2.id == cam.id
            assert cam2.serialNumber == 'SN-NEW-99'
            assert cam2.data.get('custom_prop') == 43

    def test_add_camera_remote(self, flask_app, db):
        """Covers addCamera_remote lines 170-248."""
        with flask_app.app_context():
            mdb = miscDb({})
            metadata = {
                'uuid': 'remote-cam-uuid-1',
                'name': 'Remote Cam',
                'friendlyName': 'Remote Friendly',
                'serialNumber': 'SN-REMOTE-1',
                'data': {'remote_flag': True},
            }
            cam = mdb.addCamera_remote(metadata)
            assert cam.uuid == 'remote-cam-uuid-1'
            assert cam.local is False

            # Update existing remote camera
            cam2 = mdb.addCamera_remote(metadata)
            assert cam2.id == cam.id

    def test_all_media_add_methods(self, flask_app, tmp_path, db):
        """Covers addImage, addDarkFrame, addBadPixelMap, addVideo, addMiniVideo,
        addPanoramaVideo, addKeogram, addStarTrail, addStarTrailVideo,
        addFitsImage, addRawImage, addPanoramaImage, addThumbnail_remote."""
        with flask_app.app_context():
            cam = IndiAllSkyDbCameraTable.query.first()
            mdb = miscDb({'IMAGE_FOLDER': str(tmp_path)})

            now = datetime.now()
            today_str = now.strftime('%Y%m%d')

            # None filename returns None
            assert mdb.addImage(None, cam.id, {}) is None
            assert mdb.addDarkFrame(None, cam.id, {}) is None
            assert mdb.addBadPixelMap(None, cam.id, {}) is None
            assert mdb.addVideo(None, cam.id, {}) is None
            assert mdb.addMiniVideo(None, cam.id, {}) is None
            assert mdb.addPanoramaVideo(None, cam.id, {}) is None
            assert mdb.addKeogram(None, cam.id, {}) is None
            assert mdb.addStarTrail(None, cam.id, {}) is None
            assert mdb.addStarTrailVideo(None, cam.id, {}) is None
            assert mdb.addFitsImage(None, cam.id, {}) is None
            assert mdb.addRawImage(None, cam.id, {}) is None
            assert mdb.addPanoramaImage(None, cam.id, {}) is None
            assert mdb.addThumbnail_remote(None, cam.id, {}) is None

            # addImage
            img_meta = {
                'createDate': now.timestamp(),
                'dayDate': today_str,
                'exposure': 5.0,
                'exp_elapsed': 5.1,
                'gain': 100.0,
                'binmode': 1,
                'temp': 20.0,
                'calibrated': True,
                'night': 1,
                'adu': 1500.0,
                'adu_roi': 0,
                'stable': True,
                'moonmode': 0,
                'moonphase': 50.0,
                'sqm': 21.0,
                'stars': 100,
                'detections': 2,
                'process_elapsed': 0.5,
                'height': 1080,
                'width': 1920,
            }
            img = mdb.addImage('test_img.jpg', cam.id, img_meta)
            assert img is not None

            # addDarkFrame (with and without temp)
            dark_meta = {
                'createDate': now,
                'bitdepth': 16,
                'exposure': 5,
                'gain': 100.0,
                'binmode': 1,
                'temp': 15.0,
                'adu': 100.0,
                'height': 1080,
                'width': 1920,
            }
            dark = mdb.addDarkFrame('dark.jpg', cam.id, dark_meta)
            assert dark.temp == 15.0
            dark_meta['temp'] = 0.0
            dark_no_temp = mdb.addDarkFrame('dark2.jpg', cam.id, dark_meta)
            assert dark_no_temp.temp is None

            # addBadPixelMap (with and without temp)
            bpm_meta = {
                'createDate': now.timestamp(),
                'bitdepth': 16,
                'exposure': 5,
                'gain': 100.0,
                'binmode': 1,
                'temp': 10.0,
                'height': 1080,
                'width': 1920,
            }
            bpm = mdb.addBadPixelMap('bpm.jpg', cam.id, bpm_meta)
            assert bpm.temp == 10.0
            bpm_meta['temp'] = None
            bpm_no_temp = mdb.addBadPixelMap('bpm2.jpg', cam.id, bpm_meta)
            assert bpm_no_temp.temp is None

            # addVideo
            vid_meta = {
                'createDate': now.timestamp(),
                'dayDate': today_str,
                'night': True,
                'framerate': 25.0,
                'frames': 100,
            }
            vid = mdb.addVideo('vid.mp4', cam.id, vid_meta)
            assert vid is not None

            # addMiniVideo
            mvid_meta = {
                'createDate': now,
                'dayDate': now.date(),
                'targetDate': now.timestamp(),
                'startDate': now.timestamp(),
                'endDate': now.timestamp(),
                'night': False,
                'framerate': 30.0,
                'frames': 50,
                'note': 'mini vid note',
            }
            mvid = mdb.addMiniVideo('mvid.mp4', cam.id, mvid_meta)
            assert mvid is not None

            # addPanoramaVideo
            pvid_meta = {
                'createDate': now.timestamp(),
                'dayDate': today_str,
                'night': True,
                'framerate': 25.0,
                'frames': 60,
            }
            pvid = mdb.addPanoramaVideo('pvid.mp4', cam.id, pvid_meta)
            assert pvid is not None

            # addKeogram
            keo_meta = {
                'createDate': now.timestamp(),
                'dayDate': today_str,
                'night': True,
                'frames': 120,
            }
            keo = mdb.addKeogram('keo.jpg', cam.id, keo_meta)
            assert keo is not None

            # addStarTrail
            st_meta = {
                'createDate': now.timestamp(),
                'dayDate': today_str,
                'night': True,
                'frames': 150,
            }
            st = mdb.addStarTrail('st.jpg', cam.id, st_meta)
            assert st is not None

            # addStarTrailVideo
            stv_meta = {
                'createDate': now.timestamp(),
                'dayDate': today_str,
                'night': True,
                'framerate': 24.0,
                'frames': 150,
            }
            stv = mdb.addStarTrailVideo('stv.mp4', cam.id, stv_meta)
            assert stv is not None

            # addFitsImage
            fits_meta = {
                'createDate': now.timestamp(),
                'dayDate': today_str,
                'exposure': 10.0,
                'gain': 200.0,
                'binmode': 1,
                'night': True,
                'height': 1080,
                'width': 1920,
            }
            fits = mdb.addFitsImage('fits.fits', cam.id, fits_meta)
            assert fits is not None

            # addRawImage
            raw_meta = {
                'createDate': now.timestamp(),
                'dayDate': today_str,
                'exposure': 5.0,
                'gain': 100.0,
                'binmode': 1,
                'night': False,
                'height': 1080,
                'width': 1920,
            }
            raw = mdb.addRawImage('raw.raw', cam.id, raw_meta)
            assert raw is not None

            # addPanoramaImage
            pano_meta = {
                'createDate': now.timestamp(),
                'dayDate': today_str,
                'exposure': 8.0,
                'gain': 120.0,
                'binmode': 1,
                'night': True,
                'height': 1080,
                'width': 1920,
            }
            pano = mdb.addPanoramaImage('pano.jpg', cam.id, pano_meta)
            assert pano is not None

            # addThumbnail_remote
            thumb_meta = {
                'createDate': now.timestamp(),
                'uuid': 'thumb-remote-uuid-1',
                'width': 150,
                'height': 100,
            }
            thumb = mdb.addThumbnail_remote('thumb_remote.jpg', cam.id, thumb_meta)
            assert thumb is not None

    def test_get_current_camera_id(self, flask_app, db):
        """Covers lines 1097-1111 in miscDb.py."""
        with flask_app.app_context():
            mdb = miscDb({})
            cam = IndiAllSkyDbCameraTable.query.first()

            # Via DB_CAMERA_ID state
            mdb.setState('DB_CAMERA_ID', str(cam.id))
            assert mdb.getCurrentCameraId() == cam.id

            # Fallback to most recent connected camera
            mdb.removeState('DB_CAMERA_ID')
            assert mdb.getCurrentCameraId() == cam.id

    def test_miscdb_additional_branches(self, flask_app, tmp_path, db):
        """Covers all datetime/date variations, friendlyName, and thumbnail_uuid exceptions in miscDb."""
        import numpy as np
        import cv2
        from PIL import Image
        from sqlalchemy.orm.exc import NoResultFound

        with flask_app.app_context():
            cam = IndiAllSkyDbCameraTable.query.first()
            mdb = miscDb({'IMAGE_FOLDER': str(tmp_path)})

            now = datetime.now()
            today_date = now.date()
            today_str = now.strftime('%Y%m%d')

            # 1. addCamera with serialNumber match & name match without uuid (lines 77, 102)
            cam.uuid = None
            cam.serialNumber = 'SN123'
            db.session.commit()
            cam_sn = mdb.addCamera({'name': 'Existing Cam', 'serialNumber': 'SN123', 'friendlyName': 'Friendly SN'})
            assert cam_sn.uuid is not None

            cam.uuid = None
            db.session.commit()
            cam_name = mdb.addCamera({'name': cam.name, 'serialNumber': None, 'friendlyName': 'Friendly Name'})
            assert cam_name.uuid is not None

            # New camera
            cam_new = mdb.addCamera({'name': 'New Cam Unique', 'serialNumber': None, 'friendlyName': 'Friendly Cam Unique'})
            assert cam_new.id is not None

            # 2. addCamera_remote with non-excluded attribute (line 223)
            cam_rem = mdb.addCamera_remote({'uuid': 'rem-uuid-unique', 'name': 'Rem Cam Unique', 'nightSunAlt': -12.0})
            assert cam_rem.nightSunAlt == -12.0

            # 3. Media methods with datetime createDate and date dayDate (lines 291, 297, 365-366, etc.)
            img = mdb.addImage('img_dt.jpg', cam.id, {
                'createDate': now,
                'dayDate': today_date,
                'exposure': 1.0,
                'exp_elapsed': 1.1,
                'gain': 100.0,
                'binmode': 1,
                'temp': 20.0,
                'adu': 100.0,
                'adu_roi': 0,
                'calibrated': True,
                'night': False,
                'stable': True,
                'moonmode': 0,
                'moonphase': 0.0,
                'sqm': 0.0,
                'stars': 0,
                'detections': 0,
                'process_elapsed': 0.1,
                'height': 100,
                'width': 200,
                'thumbnail_uuid': 'nonexistent-thumb-uuid-1',  # lines 365-366
            })
            assert img is not None

            dark = mdb.addDarkFrame('dark_ts.jpg', cam.id, {
                'createDate': now.timestamp(),  # line 398
                'bitdepth': 8, 'exposure': 1, 'gain': 0.0, 'temp': 0.0,
                'binmode': 1, 'height': 100, 'width': 200,
            })
            assert dark is not None

            bpm = mdb.addBadPixelMap('bpm_dt.jpg', cam.id, {
                'createDate': now,  # line 466
                'bitdepth': 8, 'exposure': 1, 'gain': 0.0, 'temp': 0.0,
                'binmode': 1, 'height': 100, 'width': 200,
            })
            assert bpm is not None

            vid = mdb.addVideo('vid_dt.mp4', cam.id, {
                'createDate': now,  # line 527
                'dayDate': today_date,  # line 533
                'night': False,
            })
            assert vid is not None

            mvid = mdb.addMiniVideo('mvid_dt.mp4', cam.id, {
                'createDate': now.timestamp(),  # line 589
                'targetDate': now,  # line 597
                'startDate': now,  # line 603
                'endDate': now,  # line 609
                'dayDate': today_str,  # line 613
                'night': True,
                'note': 'test',
            })
            assert mvid is not None

            pvid = mdb.addPanoramaVideo('pvid_dt.mp4', cam.id, {
                'createDate': now,  # line 672
                'dayDate': today_date,  # line 678
                'night': False,
            })
            assert pvid is not None

            keo = mdb.addKeogram('keo_dt.jpg', cam.id, {
                'createDate': now,  # line 729
                'dayDate': today_date,  # line 735
                'night': False,
                'thumbnail_uuid': 'nonexistent-thumb-uuid-2',  # lines 769-770
            })
            assert keo is not None

            st = mdb.addStarTrail('st_dt.jpg', cam.id, {
                'createDate': now,  # line 800
                'dayDate': today_date,  # line 806
                'night': False,
                'thumbnail_uuid': 'nonexistent-thumb-uuid-3',  # lines 840-841
            })
            assert st is not None

            stv = mdb.addStarTrailVideo('stv_dt.mp4', cam.id, {
                'createDate': now,  # line 870
                'dayDate': today_date,  # line 876
                'night': False,
            })
            assert stv is not None

            fits = mdb.addFitsImage('fits_dt.fits', cam.id, {
                'createDate': now,  # line 927
                'dayDate': today_date,  # line 933
                'exposure': 1.0, 'gain': 0.0, 'binmode': 1, 'night': False,
                'height': 100, 'width': 200,
            })
            assert fits is not None

            raw = mdb.addRawImage('raw_dt.raw', cam.id, {
                'createDate': now,  # line 991
                'dayDate': today_date,  # line 997
                'exposure': 1.0, 'gain': 0.0, 'binmode': 1, 'night': False,
                'height': 100, 'width': 200,
            })
            assert raw is not None

            pano = mdb.addPanoramaImage('pano_dt.jpg', cam.id, {
                'createDate': now,  # line 1055
                'dayDate': today_date,  # line 1061
                'exposure': 1.0, 'gain': 0.0, 'binmode': 1, 'night': False,
                'height': 100, 'width': 200,
                'thumbnail_uuid': 'nonexistent-thumb-uuid-4',  # lines 1109-1111 in addPanoramaImage
            })
            assert pano is not None

            # 4. addNotification with duplicate and clearNotification with no notices (lines 1125-1126, 1154)
            mdb.addNotification(NotificationCategory.GENERAL, 'test_item_dup', 'test note', expire=timedelta(hours=1))
            mdb.addNotification(NotificationCategory.GENERAL, 'test_item_dup', 'test note', expire=timedelta(hours=1))
            mdb.clearNotification(NotificationCategory.GENERAL, 'nonexistent_item_for_clear')

            # 5. add_long_term_keogram_data with float timestamp (line 1515)
            mdb.add_long_term_keogram_data(now.timestamp(), cam.id, [[100, 100, 100]] * 5)

            # 6. addThumbnail_remote with datetime createDate (line 1485)
            mdb.addThumbnail_remote('thumb_remote_dt.jpg', cam.id, {
                'createDate': now,
                'uuid': 'thumb-remote-dt-1',
                'width': 150,
                'height': 100,
            })

            # 7. Event broadcast exception paths (lines 365-366, 769-770, 840-841)
            with patch('indi_allsky.events.event_manager.broadcast', side_effect=RuntimeError('ev err')):
                img_ev = mdb.addImage('img_ev.jpg', cam.id, {
                    'createDate': now, 'dayDate': today_date, 'exposure': 1.0, 'exp_elapsed': 1.0,
                    'gain': 0.0, 'binmode': 1, 'temp': 0.0, 'adu': 0.0, 'adu_roi': 0, 'calibrated': False,
                    'night': False, 'stable': True, 'moonmode': 0, 'moonphase': 0.0, 'sqm': 0.0,
                    'stars': 0, 'detections': 0, 'process_elapsed': 0.0, 'height': 10, 'width': 10,
                })
                assert img_ev is not None

                keo_ev = mdb.addKeogram('keo_ev.jpg', cam.id, {
                    'createDate': now, 'dayDate': today_date, 'night': False, 'frames': 1,
                })
                assert keo_ev is not None

                st_ev = mdb.addStarTrail('st_ev.jpg', cam.id, {
                    'createDate': now, 'dayDate': today_date, 'night': False, 'frames': 1,
                })
                assert st_ev is not None

            # 8. getCurrentCameraId with no cameras in DB (lines 1109-1111)
            with patch('indi_allsky.flask.miscDb.IndiAllSkyDbStateTable.query') as mock_state:
                mock_state.filter.return_value.one.side_effect = NoResultFound
                with patch('indi_allsky.flask.miscDb.IndiAllSkyDbCameraTable.query') as mock_cam:
                    mock_cam.order_by.return_value.limit.return_value.one.side_effect = NoResultFound
                    with pytest.raises(NoResultFound):
                        mdb.getCurrentCameraId()

    def test_add_thumbnail_comprehensive(self, flask_app, tmp_path, db):
        """Covers lines 1242-1453 (addThumbnail) in miscDb.py."""
        import numpy as np
        import cv2
        from PIL import Image

        with flask_app.app_context():
            cam = IndiAllSkyDbCameraTable.query.first()
            if not cam:
                cam = IndiAllSkyDbCameraTable(
                    name="thumb_cam", uuid="thumb-cam-uuid",
                    latitude=0, longitude=0, elevation=0, nightSunAlt=-6, local=True,
                )
                db.session.add(cam)
                db.session.commit()

            mdb = miscDb({'IMAGE_FOLDER': str(tmp_path), 'IMAGE_FILE_COMPRESSION': {'jpg': 90}})
            now = datetime.now()

            # Create an entry model
            img_entry = IndiAllSkyDbImageTable(
                camera_id=cam.id,
                filename=str(tmp_path / 'test_orig.jpg'),
                createDate=now,
                dayDate=now.date(),
                exposure=1.0, gain=0.0, adu=0.0,
            )
            db.session.add(img_entry)
            db.session.commit()

            # 1. Early return when thumbnail_uuid is already set (lines 1242-1243)
            img_entry.thumbnail_uuid = 'already-has-thumb'
            assert mdb.addThumbnail(img_entry, {}, cam.id, {}) is None
            img_entry.thumbnail_uuid = None

            # 2. numpy_data provided (wide: img_width >= img_height) with origin=IMAGE and odd height (101)
            np_data = np.zeros((101, 150, 3), dtype=np.uint8)  # odd height makes thumb_height 101 to test lines 1409-1412
            entry_meta = {}
            thumb_meta = {
                'createDate': now.timestamp(),
                'dayDate': now.strftime('%Y%m%d'),
                'night': True,
                'origin': constants.IMAGE,
                'camera_uuid': cam.uuid,
            }
            res1 = mdb.addThumbnail(img_entry, entry_meta, cam.id, thumb_meta, numpy_data=np_data)
            assert res1 is not None
            assert img_entry.thumbnail_uuid is not None
            img_entry.thumbnail_uuid = None

            # 3. numpy_data tall (img_height > img_width) with origin=PANORAMA_IMAGE & night=False
            np_data_tall = np.zeros((201, 101, 3), dtype=np.uint8)
            thumb_meta_tall = {
                'createDate': now,
                'dayDate': now.date(),
                'night': False,
                'origin': constants.PANORAMA_IMAGE,
                'camera_uuid': cam.uuid,
            }
            res2 = mdb.addThumbnail(img_entry, {}, cam.id, thumb_meta_tall, numpy_data=np_data_tall)
            assert res2 is not None
            img_entry.thumbnail_uuid = None

            # 4. numpy_data with origin=KEOGRAM (timelapse directory)
            thumb_meta_keo = {
                'createDate': now,
                'dayDate': now.date(),
                'night': True,
                'origin': constants.KEOGRAM,
                'camera_uuid': cam.uuid,
            }
            res3 = mdb.addThumbnail(img_entry, {}, cam.id, thumb_meta_keo, numpy_data=np_data)
            assert res3 is not None
            img_entry.thumbnail_uuid = None

            # 5. image_entry provided:
            # 5a. image_entry file not found
            missing_entry = IndiAllSkyDbImageTable(camera_id=cam.id, filename=str(tmp_path / 'nonexistent.jpg'), createDate=now, dayDate=now.date(), exposure=1.0, gain=0.0, adu=0.0)
            assert mdb.addThumbnail(img_entry, {}, cam.id, thumb_meta, image_entry=missing_entry) is None

            # 5b. image_entry JPG (valid & bad)
            jpg_file = tmp_path / 'sample.jpg'
            cv2.imwrite(str(jpg_file), np_data)
            jpg_entry = IndiAllSkyDbImageTable(camera_id=cam.id, filename=str(jpg_file), createDate=now, dayDate=now.date(), exposure=1.0, gain=0.0, adu=0.0)
            assert mdb.addThumbnail(img_entry, {}, cam.id, thumb_meta, image_entry=jpg_entry) is not None
            img_entry.thumbnail_uuid = None

            bad_jpg = tmp_path / 'bad.jpg'
            bad_jpg.write_bytes(b'corrupt_jpeg_data')
            bad_jpg_entry = IndiAllSkyDbImageTable(camera_id=cam.id, filename=str(bad_jpg), createDate=now, dayDate=now.date(), exposure=1.0, gain=0.0, adu=0.0)
            assert mdb.addThumbnail(img_entry, {}, cam.id, thumb_meta, image_entry=bad_jpg_entry) is None

            # 5c. image_entry PNG (valid & bad)
            png_file = tmp_path / 'sample.png'
            cv2.imwrite(str(png_file), np_data)
            png_entry = IndiAllSkyDbImageTable(camera_id=cam.id, filename=str(png_file), createDate=now, dayDate=now.date(), exposure=1.0, gain=0.0, adu=0.0)
            assert mdb.addThumbnail(img_entry, {}, cam.id, thumb_meta, image_entry=png_entry) is not None
            img_entry.thumbnail_uuid = None

            bad_png = tmp_path / 'bad.png'
            bad_png.write_bytes(b'')
            bad_png_entry = IndiAllSkyDbImageTable(camera_id=cam.id, filename=str(bad_png), createDate=now, dayDate=now.date(), exposure=1.0, gain=0.0, adu=0.0)
            assert mdb.addThumbnail(img_entry, {}, cam.id, thumb_meta, image_entry=bad_png_entry) is None

            # 5d. image_entry other format (BMP via PIL) (valid & bad)
            bmp_file = tmp_path / 'sample.bmp'
            Image.fromarray(np_data).save(str(bmp_file))
            bmp_entry = IndiAllSkyDbImageTable(camera_id=cam.id, filename=str(bmp_file), createDate=now, dayDate=now.date(), exposure=1.0, gain=0.0, adu=0.0)
            assert mdb.addThumbnail(img_entry, {}, cam.id, thumb_meta, image_entry=bmp_entry) is not None
            img_entry.thumbnail_uuid = None

            bad_bmp = tmp_path / 'bad.bmp'
            bad_bmp.write_bytes(b'not_a_bmp')
            bad_bmp_entry = IndiAllSkyDbImageTable(camera_id=cam.id, filename=str(bad_bmp), createDate=now, dayDate=now.date(), exposure=1.0, gain=0.0, adu=0.0)
            assert mdb.addThumbnail(img_entry, {}, cam.id, thumb_meta, image_entry=bad_bmp_entry) is None

            # 6. entry filesystem path fallback (when image_entry=None and numpy_data=None):
            # 6a. entry file not found
            missing_entry_direct = IndiAllSkyDbImageTable(camera_id=cam.id, filename=str(tmp_path / 'nofile.jpg'), createDate=now, dayDate=now.date(), exposure=1.0, gain=0.0, adu=0.0)
            assert mdb.addThumbnail(missing_entry_direct, {}, cam.id, thumb_meta) is None

            # 6b. entry JPG (valid & bad)
            assert mdb.addThumbnail(jpg_entry, {}, cam.id, thumb_meta) is not None
            jpg_entry.thumbnail_uuid = None
            assert mdb.addThumbnail(bad_jpg_entry, {}, cam.id, thumb_meta) is None

            # 6c. entry PNG (valid & bad)
            assert mdb.addThumbnail(png_entry, {}, cam.id, thumb_meta) is not None
            png_entry.thumbnail_uuid = None
            assert mdb.addThumbnail(bad_png_entry, {}, cam.id, thumb_meta) is None

            # 6d. entry other format (BMP) (valid & bad)
            assert mdb.addThumbnail(bmp_entry, {}, cam.id, thumb_meta) is not None
            bmp_entry.thumbnail_uuid = None
            assert mdb.addThumbnail(bad_bmp_entry, {}, cam.id, thumb_meta) is None

            # 7. FileNotFoundError when stat() is called (lines 1431-1432)
            orig_stat = Path.stat
            def selective_stat(self, *args, **kwargs):
                if str(self).endswith('.jpg') and 'thumbnails' in str(self):
                    raise FileNotFoundError
                return orig_stat(self, *args, **kwargs)

            with patch.object(Path, 'stat', autospec=True, side_effect=selective_stat):
                res_stat = mdb.addThumbnail(img_entry, {}, cam.id, thumb_meta, numpy_data=np_data)
                assert res_stat is not None
                assert res_stat.fileSize is None
                img_entry.thumbnail_uuid = None


# ===========================================================================
# youtube_views.py coverage tests
# ===========================================================================

class TestYoutubeViewsCoverage:

    @pytest.fixture
    def auth_client(self, flask_app, db):
        with flask_app.app_context():
            u = IndiAllSkyDbUserTable.query.filter_by(username='ytuser').first()
            if not u:
                u = IndiAllSkyDbUserTable(
                    username='ytuser',
                    password=argon2.hash('ValidPassword123!'),
                    email='yt@example.com',
                    active=True, admin=True,
                )
                db.session.add(u)
                db.session.commit()

        client = flask_app.test_client()
        client.post('/indi-allsky/login', json={
            'USERNAME': 'ytuser',
            'PASSWORD': 'ValidPassword123!',
            'NEXT': '',
        })
        return client

    def test_youtube_authorize_no_secrets_file_aborts_400(self, auth_client, flask_app, db):
        """YoutubeAuthorizeView aborts 400 when SECRETS_FILE is not configured."""
        with flask_app.app_context():
            cfg = IndiAllSkyDbConfigTable.query.first()
            cfg.data = {**cfg.data, 'YOUTUBE': {'SECRETS_FILE': ''}}
            db.session.commit()

        resp = auth_client.get('/indi-allsky/youtube/authorize')
        assert resp.status_code == 400

    def test_youtube_authorize_success(self, auth_client, flask_app, tmp_path, db):
        """YoutubeAuthorizeView generates authorization URL and redirects."""
        secrets_file = tmp_path / 'client_secrets.json'
        secrets_file.write_text('{"installed": {}}')

        with flask_app.app_context():
            cfg = IndiAllSkyDbConfigTable.query.first()
            cfg.data = {**cfg.data, 'YOUTUBE': {'SECRETS_FILE': str(secrets_file)}}
            db.session.commit()

        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ('https://accounts.google.com/o/oauth2/auth', 'state123')
        mock_flow.code_verifier = 'verifier123'

        with patch('google_auth_oauthlib.flow.Flow.from_client_secrets_file', return_value=mock_flow):
            resp = auth_client.get('/indi-allsky/youtube/authorize', follow_redirects=False)
            assert resp.status_code == 302
            assert resp.headers['Location'] == 'https://accounts.google.com/o/oauth2/auth'

    def test_youtube_callback_success(self, auth_client, flask_app, tmp_path, db):
        """YoutubeCallbackView exchanges token and saves encrypted credentials."""
        secrets_file = tmp_path / 'client_secrets.json'
        secrets_file.write_text('{"installed": {}}')

        with flask_app.app_context():
            cfg = IndiAllSkyDbConfigTable.query.first()
            cfg.data = {**cfg.data, 'YOUTUBE': {'SECRETS_FILE': str(secrets_file)}}
            db.session.commit()

        with auth_client.session_transaction() as sess:
            sess['youtube_state'] = 'state123'
            sess['youtube_code_verifier'] = 'verifier123'

        mock_creds = MagicMock()
        mock_creds.token = 'tok_abc'
        mock_creds.refresh_token = 'ref_abc'
        mock_creds.token_uri = 'https://oauth2.googleapis.com/token'
        mock_creds.client_id = 'cid_123'
        mock_creds.client_secret = 'csec_123'
        mock_creds.scopes = ['https://www.googleapis.com/auth/youtube.upload']

        mock_flow = MagicMock()
        mock_flow.credentials = mock_creds

        with patch('google_auth_oauthlib.flow.Flow.from_client_secrets_file', return_value=mock_flow):
            resp = auth_client.get('/indi-allsky/youtube/oauth2callback?code=code123&state=state123', follow_redirects=False)
            assert resp.status_code == 302
            assert '/indi-allsky/config' in resp.headers['Location']

            with flask_app.app_context():
                mdb = miscDb({})
                saved_json = mdb.getState('YOUTUBE_CREDENTIALS')
                assert 'tok_abc' in saved_json

    def test_youtube_callback_invalid_grant_aborts_400(self, auth_client, flask_app, tmp_path, db):
        """YoutubeCallbackView aborts 400 on InvalidGrantError."""
        from oauthlib.oauth2.rfc6749.errors import InvalidGrantError

        secrets_file = tmp_path / 'client_secrets.json'
        secrets_file.write_text('{"installed": {}}')

        with flask_app.app_context():
            cfg = IndiAllSkyDbConfigTable.query.first()
            cfg.data = {**cfg.data, 'YOUTUBE': {'SECRETS_FILE': str(secrets_file)}}
            db.session.commit()

        with auth_client.session_transaction() as sess:
            sess['youtube_state'] = 'state123'
            sess['youtube_code_verifier'] = 'verifier123'

        mock_flow = MagicMock()
        mock_flow.fetch_token.side_effect = InvalidGrantError('Grant invalid')

        with patch('google_auth_oauthlib.flow.Flow.from_client_secrets_file', return_value=mock_flow):
            resp = auth_client.get('/indi-allsky/youtube/oauth2callback?code=badcode&state=state123')
            assert resp.status_code == 400

    def test_youtube_refresh_auth_not_configured(self, auth_client, flask_app, db):
        """YoutubeRefreshAuthView aborts 400 when credentials not in DB."""
        with flask_app.app_context():
            mdb = miscDb({})
            try:
                mdb.removeState('YOUTUBE_CREDENTIALS')
            except Exception:
                pass

        resp = auth_client.get('/indi-allsky/youtube/oauth2refresh')
        assert resp.status_code == 400

    def test_youtube_refresh_auth_not_expired(self, auth_client, flask_app, db):
        """YoutubeRefreshAuthView aborts 400 when credentials are not expired."""
        creds = {
            'token': 'tok', 'refresh_token': 'ref', 'token_uri': 'https://token',
            'client_id': 'cid', 'client_secret': 'csec', 'scopes': [],
        }
        with flask_app.app_context():
            mdb = miscDb({})
            mdb.setEncryptedState('YOUTUBE_CREDENTIALS', json.dumps(creds))

        mock_creds = MagicMock()
        mock_creds.expired = False

        with patch('google.oauth2.credentials.Credentials', return_value=mock_creds):
            resp = auth_client.get('/indi-allsky/youtube/oauth2refresh')
            assert resp.status_code == 400

    def test_youtube_refresh_auth_success(self, auth_client, flask_app, db):
        """YoutubeRefreshAuthView refreshes expired credentials successfully."""
        creds = {
            'token': 'tok_old', 'refresh_token': 'ref', 'token_uri': 'https://token',
            'client_id': 'cid', 'client_secret': 'csec', 'scopes': [],
        }
        with flask_app.app_context():
            mdb = miscDb({})
            mdb.setEncryptedState('YOUTUBE_CREDENTIALS', json.dumps(creds))

        mock_creds = MagicMock()
        mock_creds.expired = True
        mock_creds.refresh_token = 'ref'
        mock_creds.token = 'tok_refreshed'
        mock_creds.token_uri = 'https://token'
        mock_creds.client_id = 'cid'
        mock_creds.client_secret = 'csec'
        mock_creds.scopes = []

        with patch('google.oauth2.credentials.Credentials', return_value=mock_creds), \
             patch('google.auth.transport.requests.Request'):
            resp = auth_client.get('/indi-allsky/youtube/oauth2refresh', follow_redirects=False)
            assert resp.status_code == 302
            assert '/indi-allsky/config' in resp.headers['Location']

            with flask_app.app_context():
                mdb = miscDb({})
                saved_json = mdb.getState('YOUTUBE_CREDENTIALS')
                assert 'tok_refreshed' in saved_json

    def test_youtube_revoke_auth_not_configured(self, auth_client, flask_app, db):
        """YoutubeRevokeAuthView aborts 400 when no credentials."""
        with flask_app.app_context():
            mdb = miscDb({})
            try:
                mdb.removeState('YOUTUBE_CREDENTIALS')
            except Exception:
                pass

        resp = auth_client.get('/indi-allsky/youtube/oauth2revoke')
        assert resp.status_code == 400

    def test_youtube_revoke_auth_failed_remote(self, auth_client, flask_app, db):
        """YoutubeRevokeAuthView aborts 400 when Google revoke endpoint returns non-200."""
        creds = {'token': 'tok', 'refresh_token': 'ref', 'token_uri': 'u', 'client_id': 'c', 'client_secret': 's', 'scopes': []}
        with flask_app.app_context():
            mdb = miscDb({})
            mdb.setEncryptedState('YOUTUBE_CREDENTIALS', json.dumps(creds))

        mock_resp = MagicMock()
        mock_resp.status_code = 400

        with patch('requests.post', return_value=mock_resp):
            resp = auth_client.get('/indi-allsky/youtube/oauth2revoke')
            assert resp.status_code == 400

    def test_youtube_revoke_auth_success(self, auth_client, flask_app, db):
        """YoutubeRevokeAuthView revokes token and removes credentials from DB."""
        creds = {'token': 'tok', 'refresh_token': 'ref', 'token_uri': 'u', 'client_id': 'c', 'client_secret': 's', 'scopes': []}
        with flask_app.app_context():
            mdb = miscDb({})
            mdb.setEncryptedState('YOUTUBE_CREDENTIALS', json.dumps(creds))

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch('requests.post', return_value=mock_resp):
            resp = auth_client.get('/indi-allsky/youtube/oauth2revoke', follow_redirects=False)
            assert resp.status_code == 302
            assert '/indi-allsky/config' in resp.headers['Location']

            with flask_app.app_context():
                mdb = miscDb({})
                with pytest.raises(Exception):
                    mdb.getState('YOUTUBE_CREDENTIALS')
