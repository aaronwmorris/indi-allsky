import queue
from datetime import datetime, date
from types import SimpleNamespace
from pathlib import Path
import pytest

from indi_allsky import constants
from indi_allsky.miscUpload import miscUpload
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbTaskQueueTable,
    TaskQueueState,
    TaskQueueQueue,
)
from indi_allsky.flask import db


@pytest.fixture
def mock_asset():
    cam = SimpleNamespace(id=1, uuid='cam-uuid-123')
    return SimpleNamespace(
        id=42,
        camera=cam,
        filename='/tmp/images/test_file.jpg',
        createDate=datetime(2026, 3, 15, 21, 30, 0),
        dayDate=date(2026, 3, 15),
        night=True,
        s3_key='images/test_file.jpg',
    )


def test_misc_upload_disabled(app):
    with app.app_context():
        upload_q = queue.Queue()
        night_av = [1, 0]
        uploader = miscUpload({'FILETRANSFER': {'UPLOAD_IMAGE': False}}, upload_q, night_av)

        # upload_image should return early if upload is disabled
        uploader.upload_image(None)
        assert uploader._image_count == 0


def test_misc_upload_image_task(app, tmp_path):
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        if not cam:
            cam = IndiAllSkyDbCameraTable(
                name='MiscUpload Cam',
                uuid='cam-misc-1',
                latitude=-34.9285,
                longitude=138.6007,
                elevation=50,
                nightSunAlt=-6.0,
            )
            db.session.add(cam)
            db.session.commit()

        img_file = tmp_path / "test_img.jpg"
        img_file.write_bytes(b"image data")

        image = IndiAllSkyDbImageTable(
            camera_id=cam.id,
            filename=str(img_file),
            createDate=datetime.now(),
            dayDate=date.today(),
            night=True,
            exposure=10.0,
            gain=100.0,
            binmode=1,
            adu=128.0,
            data={},
        )
        db.session.add(image)
        db.session.commit()

        config = {
            'IMAGE_FILE_TYPE': 'jpg',
            'FILETRANSFER': {
                'UPLOAD_IMAGE': 1,
                'REMOTE_IMAGE_FOLDER': '/remote/images',
                'REMOTE_IMAGE_NAME': 'img_{0:s}.jpg',
            },
        }

        upload_q = queue.Queue()
        night_av = [1, 0]
        uploader = miscUpload(config, upload_q, night_av)

        uploader.upload_image(image)
        assert uploader._image_count == 1
        assert upload_q.qsize() == 1
        task_msg = upload_q.get()
        assert 'task_id' in task_msg


def test_upload_image_none_and_skip(app, mock_asset):
    with app.app_context():
        upload_q = queue.Queue()
        config = {
            'IMAGE_FILE_TYPE': 'jpg',
            'EXPOSURE_PERIOD': 10,
            'FILETRANSFER': {
                'UPLOAD_IMAGE': 2,
                'REMOTE_IMAGE_FOLDER': '/remote/{tod}',
                'REMOTE_IMAGE_NAME': 'img_{0:s}_{camera_uuid}.jpg',
                'UPLOAD_LATEST_IMAGE': True,
                'REMOTE_LATEST_FOLDER': '/remote/latest',
            },
        }
        uploader = miscUpload(config, upload_q, [1, 0])

        # None entry returns early
        uploader.upload_image(None)
        assert uploader._image_count == 0

        # First call: image_count=1 % 2 != 0 -> skip
        mock_asset.night = False
        uploader.upload_image(mock_asset)
        assert uploader._image_count == 1
        assert upload_q.qsize() == 0

        # Second call: image_count=2 % 2 == 0 -> uploaded + latest image
        uploader.upload_image(mock_asset)
        assert uploader._image_count == 2
        assert upload_q.qsize() == 2


def test_upload_video_variants(app, mock_asset):
    with app.app_context():
        upload_q = queue.Queue()
        # Disabled
        uploader = miscUpload({'FILETRANSFER': {'UPLOAD_VIDEO': False}}, upload_q, [1, 0])
        uploader.upload_video(mock_asset)
        assert upload_q.qsize() == 0

        # Enabled (night=True, with latest)
        config = {
            'FILETRANSFER': {
                'UPLOAD_VIDEO': True,
                'REMOTE_VIDEO_FOLDER': '/video/{timeofday}',
                'REMOTE_VIDEO_NAME': 'vid_{camera_uuid}.mp4',
                'UPLOAD_LATEST_VIDEO': True,
                'REMOTE_LATEST_FOLDER': '/video/latest',
            },
        }
        uploader = miscUpload(config, upload_q, [1, 0])
        uploader.upload_video(mock_asset)
        assert upload_q.qsize() == 2

        # Enabled (night=False, without latest)
        mock_asset.night = False
        config['FILETRANSFER']['UPLOAD_LATEST_VIDEO'] = False
        uploader.upload_video(mock_asset)
        assert upload_q.qsize() == 3


def test_upload_mini_video(app, mock_asset):
    with app.app_context():
        upload_q = queue.Queue()
        # Disabled
        uploader = miscUpload({'FILETRANSFER': {'UPLOAD_MINI_VIDEO': False}}, upload_q, [1, 0])
        uploader.upload_mini_video(mock_asset)
        assert upload_q.qsize() == 0

        # Enabled (night=True)
        config = {
            'FILETRANSFER': {
                'UPLOAD_MINI_VIDEO': True,
                'REMOTE_MINI_VIDEO_FOLDER': '/mini/{tod}',
                'REMOTE_MINI_VIDEO_NAME': 'mini_{camera_id}.mp4',
            },
        }
        uploader = miscUpload(config, upload_q, [1, 0])
        uploader.upload_mini_video(mock_asset)
        assert upload_q.qsize() == 1

        # Enabled (night=False)
        mock_asset.night = False
        uploader.upload_mini_video(mock_asset)
        assert upload_q.qsize() == 2


def test_upload_panorama_video(app, mock_asset):
    with app.app_context():
        upload_q = queue.Queue()
        # Disabled
        uploader = miscUpload({'FILETRANSFER': {'UPLOAD_PANORAMA_VIDEO': False}}, upload_q, [1, 0])
        uploader.upload_panorama_video(mock_asset)
        assert upload_q.qsize() == 0

        # Enabled with latest (night=True)
        config = {
            'FILETRANSFER': {
                'UPLOAD_PANORAMA_VIDEO': True,
                'REMOTE_PANORAMA_VIDEO_FOLDER': '/pano/{tod}',
                'REMOTE_PANORAMA_VIDEO_NAME': 'pano_vid.mp4',
                'UPLOAD_LATEST_VIDEO': True,
                'REMOTE_LATEST_FOLDER': '/pano/latest',
            },
        }
        uploader = miscUpload(config, upload_q, [1, 0])
        uploader.upload_panorama_video(mock_asset)
        assert upload_q.qsize() == 2

        # Enabled (night=False, without latest)
        mock_asset.night = False
        config['FILETRANSFER']['UPLOAD_LATEST_VIDEO'] = False
        uploader.upload_panorama_video(mock_asset)
        assert upload_q.qsize() == 3


def test_upload_keogram(app, mock_asset):
    with app.app_context():
        upload_q = queue.Queue()
        # Disabled
        uploader = miscUpload({'FILETRANSFER': {'UPLOAD_KEOGRAM': False}}, upload_q, [1, 0])
        uploader.upload_keogram(mock_asset)
        assert upload_q.qsize() == 0

        # Enabled with latest (night=True)
        config = {
            'FILETRANSFER': {
                'UPLOAD_KEOGRAM': True,
                'REMOTE_KEOGRAM_FOLDER': '/keogram/{tod}',
                'REMOTE_KEOGRAM_NAME': 'keogram.jpg',
                'UPLOAD_LATEST_VIDEO': True,
                'REMOTE_LATEST_FOLDER': '/keogram/latest',
            },
        }
        uploader = miscUpload(config, upload_q, [1, 0])
        uploader.upload_keogram(mock_asset)
        assert upload_q.qsize() == 2

        # Enabled (night=False, without latest)
        mock_asset.night = False
        config['FILETRANSFER']['UPLOAD_LATEST_VIDEO'] = False
        uploader.upload_keogram(mock_asset)
        assert upload_q.qsize() == 3


def test_upload_startrail(app, mock_asset):
    with app.app_context():
        upload_q = queue.Queue()
        # Disabled
        uploader = miscUpload({'FILETRANSFER': {'UPLOAD_STARTRAIL': False}}, upload_q, [1, 0])
        uploader.upload_startrail(mock_asset)
        assert upload_q.qsize() == 0

        # Enabled with latest (night=True)
        config = {
            'FILETRANSFER': {
                'UPLOAD_STARTRAIL': True,
                'REMOTE_STARTRAIL_FOLDER': '/startrail/{tod}',
                'REMOTE_STARTRAIL_NAME': 'startrail.jpg',
                'UPLOAD_LATEST_VIDEO': True,
                'REMOTE_LATEST_FOLDER': '/startrail/latest',
            },
        }
        uploader = miscUpload(config, upload_q, [1, 0])
        uploader.upload_startrail(mock_asset)
        assert upload_q.qsize() == 2

        # Enabled (night=False, without latest)
        mock_asset.night = False
        config['FILETRANSFER']['UPLOAD_LATEST_VIDEO'] = False
        uploader.upload_startrail(mock_asset)
        assert upload_q.qsize() == 3


def test_upload_startrail_video(app, mock_asset):
    with app.app_context():
        upload_q = queue.Queue()
        # Disabled
        uploader = miscUpload({'FILETRANSFER': {'UPLOAD_STARTRAIL_VIDEO': False}}, upload_q, [1, 0])
        uploader.upload_startrail_video(mock_asset)
        assert upload_q.qsize() == 0

        # Enabled with latest (night=True)
        config = {
            'FILETRANSFER': {
                'UPLOAD_STARTRAIL_VIDEO': True,
                'REMOTE_STARTRAIL_VIDEO_FOLDER': '/startrail_vid/{tod}',
                'REMOTE_STARTRAIL_VIDEO_NAME': 'startrail_vid.mp4',
                'UPLOAD_LATEST_VIDEO': True,
                'REMOTE_LATEST_FOLDER': '/startrail_vid/latest',
            },
        }
        uploader = miscUpload(config, upload_q, [1, 0])
        uploader.upload_startrail_video(mock_asset)
        assert upload_q.qsize() == 2

        # Enabled (night=False, without latest)
        mock_asset.night = False
        config['FILETRANSFER']['UPLOAD_LATEST_VIDEO'] = False
        uploader.upload_startrail_video(mock_asset)
        assert upload_q.qsize() == 3


def test_upload_panorama(app, mock_asset):
    with app.app_context():
        upload_q = queue.Queue()
        # Disabled
        uploader = miscUpload({'FILETRANSFER': {'UPLOAD_PANORAMA': False}}, upload_q, [1, 0])
        uploader.upload_panorama(mock_asset)
        assert upload_q.qsize() == 0

        # Enabled with skipping and latest
        config = {
            'IMAGE_FILE_TYPE': 'jpg',
            'EXPOSURE_PERIOD': 10,
            'FILETRANSFER': {
                'UPLOAD_PANORAMA': 2,
                'REMOTE_PANORAMA_FOLDER': '/pano/{tod}',
                'REMOTE_PANORAMA_NAME': 'pano_{0:s}.jpg',
                'UPLOAD_LATEST_PANORAMA': True,
                'REMOTE_LATEST_FOLDER': '/pano/latest',
            },
        }
        uploader = miscUpload(config, upload_q, [1, 0])
        # First call skipped (count=1 % 2 != 0)
        uploader.upload_panorama(mock_asset)
        assert upload_q.qsize() == 0

        # Second call uploaded (count=2 % 2 == 0) (night=True)
        uploader.upload_panorama(mock_asset)
        assert upload_q.qsize() == 2

        # Third call (count=3 % 2 != 0)
        mock_asset.night = False
        uploader.upload_panorama(mock_asset)
        assert upload_q.qsize() == 2

        # Fourth call (count=4 % 2 == 0) (night=False)
        uploader.upload_panorama(mock_asset)
        assert upload_q.qsize() == 4


def test_upload_realtime_keogram(app, tmp_path):
    with app.app_context():
        upload_q = queue.Queue()
        # Disabled
        uploader = miscUpload({'FILETRANSFER': {'UPLOAD_REALTIME_KEOGRAM': False}}, upload_q, [1, 0])
        uploader.upload_realtime_keogram('/tmp/keogram.jpg', SimpleNamespace(id=1, uuid='uuid1'))
        assert upload_q.qsize() == 0

        keo_file = tmp_path / "keogram.jpg"
        keo_file.write_bytes(b"data")

        # Enabled with count skipping
        config = {
            'EXPOSURE_PERIOD': 10,
            'FILETRANSFER': {
                'UPLOAD_REALTIME_KEOGRAM': 2,
                'REMOTE_REALTIME_KEOGRAM_FOLDER': '/realtime/{tod}',
                'REMOTE_REALTIME_KEOGRAM_NAME': 'rt_{camera_uuid}.jpg',
            },
        }
        uploader = miscUpload(config, upload_q, [1, 0])  # night_av[constants.NIGHT_NIGHT] = 1
        cam = SimpleNamespace(id=1, uuid='uuid1')

        # First call skipped
        uploader.upload_realtime_keogram(str(keo_file), cam)
        assert upload_q.qsize() == 0

        # Second call uploaded (night)
        uploader.upload_realtime_keogram(str(keo_file), cam)
        assert upload_q.qsize() == 1

        # Third call skipped
        uploader.upload_realtime_keogram(str(keo_file), cam)
        assert upload_q.qsize() == 1

        # Fourth call uploaded (day)
        uploader.night_av = [0, 1]
        uploader.upload_realtime_keogram(str(keo_file), cam)
        assert upload_q.qsize() == 2


def test_upload_raw_image(app, mock_asset):
    with app.app_context():
        upload_q = queue.Queue()
        # Disabled
        uploader = miscUpload({'FILETRANSFER': {'UPLOAD_RAW': False}}, upload_q, [1, 0])
        uploader.upload_raw_image(mock_asset)
        assert upload_q.qsize() == 0

        # Enabled with latest (night=True)
        config = {
            'FILETRANSFER': {
                'UPLOAD_RAW': True,
                'REMOTE_RAW_FOLDER': '/raw/{tod}',
                'REMOTE_RAW_NAME': 'raw_{camera_uuid}.raw',
                'UPLOAD_LATEST_RAW': True,
                'REMOTE_LATEST_FOLDER': '/raw/latest',
            },
        }
        uploader = miscUpload(config, upload_q, [1, 0])
        uploader.upload_raw_image(mock_asset)
        assert upload_q.qsize() == 2

        # Enabled (night=False, without latest)
        mock_asset.night = False
        config['FILETRANSFER']['UPLOAD_LATEST_RAW'] = False
        uploader.upload_raw_image(mock_asset)
        assert upload_q.qsize() == 3


def test_upload_fits_image(app, mock_asset):
    with app.app_context():
        upload_q = queue.Queue()
        # Disabled
        uploader = miscUpload({'FILETRANSFER': {'UPLOAD_FITS': False}}, upload_q, [1, 0])
        uploader.upload_fits_image(mock_asset)
        assert upload_q.qsize() == 0

        # Enabled (night=True)
        config = {
            'FILETRANSFER': {
                'UPLOAD_FITS': True,
                'REMOTE_FITS_FOLDER': '/fits/{tod}',
                'REMOTE_FITS_NAME': 'fits_{camera_uuid}.fits',
            },
        }
        uploader = miscUpload(config, upload_q, [1, 0])
        uploader.upload_fits_image(mock_asset)
        assert upload_q.qsize() == 1

        # Enabled (night=False)
        mock_asset.night = False
        uploader.upload_fits_image(mock_asset)
        assert upload_q.qsize() == 2


def test_upload_db_backup(app, tmp_path):
    with app.app_context():
        upload_q = queue.Queue()
        # Disabled
        uploader = miscUpload({'FILETRANSFER': {'UPLOAD_DB_BACKUP': False}}, upload_q, [1, 0])
        uploader.upload_db_backup('/tmp/backup.sql')
        assert upload_q.qsize() == 0

        backup_file = tmp_path / "backup.sql"
        backup_file.write_bytes(b"data")

        # Enabled (night)
        config = {
            'FILETRANSFER': {
                'UPLOAD_DB_BACKUP': True,
                'REMOTE_DB_BACKUP_FOLDER': '/backup/{tod}',
            },
        }
        uploader = miscUpload(config, upload_q, [1, 0])
        uploader.upload_db_backup(str(backup_file))
        assert upload_q.qsize() == 1

        # Enabled (day)
        uploader.night_av = [0, 1]
        uploader.upload_db_backup(str(backup_file))
        assert upload_q.qsize() == 2


def test_mqtt_publish_image(app):
    with app.app_context():
        upload_q = queue.Queue()
        # Disabled
        uploader = miscUpload({'MQTTPUBLISH': {'ENABLE': False}}, upload_q, [1, 0])
        uploader.mqtt_publish_image('/tmp/img.jpg', 'allsky/image', {'meta': 'data'})
        assert upload_q.qsize() == 0

        # Enabled
        uploader = miscUpload({'MQTTPUBLISH': {'ENABLE': True}}, upload_q, [1, 0])
        uploader.mqtt_publish_image('/tmp/img.jpg', 'allsky/image', {'meta': 'data'})
        assert upload_q.qsize() == 1


def test_s3_upload_methods(app, mock_asset):
    with app.app_context():
        upload_q = queue.Queue()
        # S3 Disabled
        uploader = miscUpload({'S3UPLOAD': {'ENABLE': False}}, upload_q, [1, 0])
        uploader.s3_upload_asset(mock_asset, {})
        assert upload_q.qsize() == 0

        # S3 Enabled with None asset
        config = {
            'S3UPLOAD': {
                'ENABLE': True,
                'UPLOAD_FITS': True,
                'UPLOAD_RAW': True,
            },
        }
        uploader = miscUpload(config, upload_q, [1, 0])
        uploader.s3_upload_asset(None, {})
        assert upload_q.qsize() == 0

        # S3 Enabled with asset
        uploader.s3_upload_asset(mock_asset, {'meta': 1})
        assert upload_q.qsize() == 1

        # S3 image
        uploader.s3_upload_image(mock_asset, {})
        assert upload_q.qsize() == 2

        # S3 FITS disabled vs enabled
        config_no_fits = {'S3UPLOAD': {'ENABLE': True, 'UPLOAD_FITS': False}}
        uploader_no_fits = miscUpload(config_no_fits, upload_q, [1, 0])
        uploader_no_fits.s3_upload_fits(mock_asset, {})
        assert upload_q.qsize() == 2
        uploader.s3_upload_fits(mock_asset, {})
        assert upload_q.qsize() == 3

        # S3 RAW disabled vs enabled
        config_no_raw = {'S3UPLOAD': {'ENABLE': True, 'UPLOAD_RAW': False}}
        uploader_no_raw = miscUpload(config_no_raw, upload_q, [1, 0])
        uploader_no_raw.s3_upload_raw(mock_asset, {})
        assert upload_q.qsize() == 3
        uploader.s3_upload_raw(mock_asset, {})
        assert upload_q.qsize() == 4

        # Other S3 wrappers
        uploader.s3_upload_panorama(mock_asset, {})
        assert upload_q.qsize() == 5
        uploader.s3_upload_panorama_video(mock_asset, {})
        assert upload_q.qsize() == 6
        uploader.s3_upload_video(mock_asset, {})
        assert upload_q.qsize() == 7
        uploader.s3_upload_mini_video(mock_asset, {})
        assert upload_q.qsize() == 8
        uploader.s3_upload_keogram(mock_asset, {})
        assert upload_q.qsize() == 9
        uploader.s3_upload_startrail(mock_asset, {})
        assert upload_q.qsize() == 10
        uploader.s3_upload_startrail_video(mock_asset, {})
        assert upload_q.qsize() == 11
        uploader.s3_upload_thumbnail(mock_asset, {})
        assert upload_q.qsize() == 12


def test_syncapi_image(app, mock_asset):
    with app.app_context():
        upload_q = queue.Queue()
        # Disabled
        uploader = miscUpload({'SYNCAPI': {'ENABLE': False}}, upload_q, [1, 0])
        uploader.syncapi_image(mock_asset, {})
        assert upload_q.qsize() == 0

        # None entry
        config = {'SYNCAPI': {'ENABLE': True, 'POST_S3': True, 'UPLOAD_IMAGE': 2}, 'EXPOSURE_PERIOD': 10}
        uploader = miscUpload(config, upload_q, [1, 0])
        uploader.syncapi_image(None, {})
        assert upload_q.qsize() == 0

        # Delaying syncapi until after S3 (s3_key is None and POST_S3 is True)
        mock_asset.s3_key = None
        uploader.syncapi_image(mock_asset, {})
        assert upload_q.qsize() == 0

        # Stateful bool object to hit redundant check at line 1050
        class MutatingBool:
            def __init__(self):
                self.called = 0
                self.s3_key = 'key'
            def __bool__(self):
                self.called += 1
                return self.called == 1

        mutating_asset = MutatingBool()
        uploader.syncapi_image(mutating_asset, {})
        assert upload_q.qsize() == 0

        # POST_S3 False, but UPLOAD_IMAGE is False
        mock_asset.s3_key = 'test_key'
        config['SYNCAPI']['UPLOAD_IMAGE'] = False
        uploader.syncapi_image(mock_asset, {})
        assert upload_q.qsize() == 0

        # Enabled with count skipping
        config['SYNCAPI']['UPLOAD_IMAGE'] = 2
        # First call skipped
        uploader.syncapi_image(mock_asset, {})
        assert upload_q.qsize() == 0

        # Second call uploaded
        uploader.syncapi_image(mock_asset, {})
        assert upload_q.qsize() == 1


def test_syncapi_video_and_wrappers(app, mock_asset):
    with app.app_context():
        upload_q = queue.Queue()
        # Disabled
        uploader = miscUpload({'SYNCAPI': {'ENABLE': False}}, upload_q, [1, 0])
        uploader.syncapi_video(mock_asset, {})
        assert upload_q.qsize() == 0

        # POST_S3 delay
        config = {'SYNCAPI': {'ENABLE': True, 'POST_S3': True}}
        uploader = miscUpload(config, upload_q, [1, 0])
        mock_asset.s3_key = None
        uploader.syncapi_video(mock_asset, {})
        assert upload_q.qsize() == 0

        # POST_S3 False, s3_key None (proceeds through delay check)
        config_no_posts3 = {'SYNCAPI': {'ENABLE': True, 'POST_S3': False}}
        uploader_no_posts3 = miscUpload(config_no_posts3, upload_q, [1, 0])
        mock_asset.s3_key = None
        uploader_no_posts3.syncapi_video(mock_asset, {})
        assert upload_q.qsize() == 1

        # Falsy asset to hit line 1101
        class FalsyAsset:
            s3_key = 'test_key'
            def __bool__(self):
                return False

        uploader.syncapi_video(FalsyAsset(), {})
        assert upload_q.qsize() == 1

        # S3 key set, normal upload
        mock_asset.s3_key = 's3_key'
        uploader.syncapi_video(mock_asset, {})
        assert upload_q.qsize() == 2

        # Wrappers
        uploader.syncapi_mini_video(mock_asset, {})
        assert upload_q.qsize() == 3
        uploader.syncapi_keogram(mock_asset, {})
        assert upload_q.qsize() == 4
        uploader.syncapi_startrail(mock_asset, {})
        assert upload_q.qsize() == 5
        uploader.syncapi_startrail_video(mock_asset, {})
        assert upload_q.qsize() == 6
        uploader.syncapi_panorama_video(mock_asset, {})
        assert upload_q.qsize() == 7
        uploader.syncapi_thumbnail(mock_asset, {})
        assert upload_q.qsize() == 8


def test_syncapi_panorama(app, mock_asset):
    with app.app_context():
        upload_q = queue.Queue()
        # Disabled
        uploader = miscUpload({'SYNCAPI': {'ENABLE': False}}, upload_q, [1, 0])
        uploader.syncapi_panorama(mock_asset, {})
        assert upload_q.qsize() == 0

        # POST_S3 delay
        config = {'SYNCAPI': {'ENABLE': True, 'POST_S3': True, 'UPLOAD_PANORAMA': 2}, 'EXPOSURE_PERIOD': 10}
        uploader = miscUpload(config, upload_q, [1, 0])
        mock_asset.s3_key = None
        uploader.syncapi_panorama(mock_asset, {})
        assert upload_q.qsize() == 0

        # POST_S3 False, s3_key None (proceeds through delay check)
        config_no_posts3 = {'SYNCAPI': {'ENABLE': True, 'POST_S3': False, 'UPLOAD_PANORAMA': 1}, 'EXPOSURE_PERIOD': 10}
        uploader_no_posts3 = miscUpload(config_no_posts3, upload_q, [1, 0])
        mock_asset.s3_key = None
        uploader_no_posts3.syncapi_panorama(mock_asset, {})
        assert upload_q.qsize() == 1

        # Falsy asset to hit line 1162
        class FalsyAsset:
            s3_key = 'test_key'
            def __bool__(self):
                return False

        uploader.syncapi_panorama(FalsyAsset(), {})
        assert upload_q.qsize() == 1

        # UPLOAD_PANORAMA False
        mock_asset.s3_key = 's3_key'
        config['SYNCAPI']['UPLOAD_PANORAMA'] = False
        uploader.syncapi_panorama(mock_asset, {})
        assert upload_q.qsize() == 1

        # Interval skipping
        config['SYNCAPI']['UPLOAD_PANORAMA'] = 2
        # First call skipped
        uploader.syncapi_panorama(mock_asset, {})
        assert upload_q.qsize() == 1

        # Second call uploaded
        uploader.syncapi_panorama(mock_asset, {})
        assert upload_q.qsize() == 2


def test_youtube_upload_methods(app, mock_asset):
    with app.app_context():
        upload_q = queue.Queue()
        # Disabled YOUTUBE ENABLE directly in _youtube_upload
        uploader_no_yt = miscUpload({'YOUTUBE': {'ENABLE': False}}, upload_q, [1, 0])
        uploader_no_yt._youtube_upload(mock_asset, {})
        assert upload_q.qsize() == 0

        # Individual disabled flags
        config = {
            'YOUTUBE': {
                'ENABLE': True,
                'UPLOAD_VIDEO': False,
                'UPLOAD_MINI_VIDEO': False,
                'UPLOAD_STARTRAIL_VIDEO': False,
                'UPLOAD_PANORAMA_VIDEO': False,
            },
        }
        uploader = miscUpload(config, upload_q, [1, 0])
        uploader.youtube_upload_video(mock_asset, {})
        uploader.youtube_upload_mini_video(mock_asset, {})
        uploader.youtube_upload_startrail_video(mock_asset, {})
        uploader.youtube_upload_panorama_video(mock_asset, {})
        assert upload_q.qsize() == 0

        # All enabled
        config['YOUTUBE']['UPLOAD_VIDEO'] = True
        config['YOUTUBE']['UPLOAD_MINI_VIDEO'] = True
        config['YOUTUBE']['UPLOAD_STARTRAIL_VIDEO'] = True
        config['YOUTUBE']['UPLOAD_PANORAMA_VIDEO'] = True

        meta_v = {}
        uploader.youtube_upload_video(mock_asset, meta_v)
        assert meta_v['asset_label'] == 'Timelapse'
        assert upload_q.qsize() == 1

        meta_mv = {}
        uploader.youtube_upload_mini_video(mock_asset, meta_mv)
        assert meta_mv['asset_label'] == 'Mini Timelapse'
        assert upload_q.qsize() == 2

        meta_sv = {}
        uploader.youtube_upload_startrail_video(mock_asset, meta_sv)
        assert meta_sv['asset_label'] == 'Star Trails Timelapse'
        assert upload_q.qsize() == 3

        meta_pv = {}
        uploader.youtube_upload_panorama_video(mock_asset, meta_pv)
        assert meta_pv['asset_label'] == 'Panorama Timelapse'
        assert upload_q.qsize() == 4
