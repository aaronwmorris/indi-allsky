from datetime import datetime
import json
import os
import tempfile
from unittest.mock import patch

import pytest

if 'INDI_ALLSKY_FLASK_CONFIG' not in os.environ:
    _tmp_flask_cfg = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
    json.dump({
        'SECRET_KEY': 'test-secret-key',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'MIGRATION_FOLDER': 'migrations',
        'INDI_ALLSKY_IMAGE_FOLDER': tempfile.gettempdir(),
        'ADMIN_NETWORKS': ['127.0.0.1/32'],
    }, _tmp_flask_cfg)
    _tmp_flask_cfg.close()
    os.environ['INDI_ALLSKY_FLASK_CONFIG'] = _tmp_flask_cfg.name

from indi_allsky.flask import create_app
from indi_allsky.flask import db
from indi_allsky.flask.forms import IndiAllskyVideoViewer
from indi_allsky.flask.forms import normalize_video_tags
from indi_allsky.flask.models import IndiAllSkyDbCameraTable
from indi_allsky.flask.models import IndiAllSkyDbTaskQueueTable
from indi_allsky.flask.models import IndiAllSkyDbVideoTable


class TestNormalizeVideoTags:
    def test_normalizes_hash_prefix_whitespace_and_duplicates(self):
        assert normalize_video_tags('#aurora, #Storm, lightning bugs, #AURORA,  ') == [
            'aurora',
            'storm',
            'lightning bugs',
        ]
        assert normalize_video_tags(['#Meteor', 'meteor', '  ']) == ['meteor']


class TestVideoMetadataAndTagFilter:
    def test_save_metadata_and_filter_videos(self):
        flask_app = create_app()
        flask_app.config['LOGIN_DISABLED'] = True
        flask_app.config['WTF_CSRF_ENABLED'] = False

        with flask_app.app_context():
            db.create_all()
            cam = IndiAllSkyDbCameraTable(
                uuid='cam-uuid-tags',
                name='TestCam',
                friendlyName='TestCam',
            )
            db.session.add(cam)
            db.session.commit()

            now = datetime(2026, 11, 22, 23, 0, 0)
            v1 = IndiAllSkyDbVideoTable(
                filename='vid1.mp4',
                camera_id=cam.id,
                createDate=now,
                dayDate=now.date(),
                dayDate_year=2026,
                dayDate_month=11,
                dayDate_day=22,
                night=True,
                success=True,
                data={'max_stars': 100},
            )
            v2 = IndiAllSkyDbVideoTable(
                filename='vid2.mp4',
                camera_id=cam.id,
                createDate=now,
                dayDate=datetime(2026, 11, 21).date(),
                dayDate_year=2026,
                dayDate_month=11,
                dayDate_day=21,
                night=True,
                success=True,
                data={'max_stars': 50, 'note': 'Clear sky', 'tags': ['clear']},
            )
            db.session.add_all([v1, v2])
            db.session.commit()

            # Update v1 metadata via AjaxVideoMetadataView with SyncAPI enabled
            from indi_allsky.flask.views import AjaxVideoMetadataView
            with flask_app.test_request_context(
                '/ajax/videometadata',
                method='POST',
                json={
                    'VIDEO_ID': v1.id,
                    'NOTE': 'Strong red aurora substorm around midnight.',
                    'TAGS': '#aurora, #storm, lightning bugs',
                },
                environ_base={'REMOTE_ADDR': '127.0.0.1'},
            ), patch.object(AjaxVideoMetadataView, 'verify_admin_network', return_value=True):
                view = object.__new__(AjaxVideoMetadataView)
                view.indi_allsky_config = {'SYNCAPI': {'ENABLE': True}}
                resp = view.dispatch_request()

            payload = resp.get_json()
            assert payload['note'] == 'Strong red aurora substorm around midnight.'
            assert payload['tags'] == ['aurora', 'storm', 'lightning bugs']
            assert IndiAllSkyDbTaskQueueTable.query.count() == 1

            # Verify getVideos tag filtering
            viewer = IndiAllskyVideoViewer(camera_id=cam.id, local=True)
            all_vids = viewer.getVideos(2026, 11, 'all')
            assert len(all_vids) == 2

            aurora_vids = viewer.getVideos(2026, 11, 'all', tag_filter='#aurora')
            assert len(aurora_vids) == 1
            assert aurora_vids[0]['id'] == v1.id
            assert aurora_vids[0]['note'] == 'Strong red aurora substorm around midnight.'
            assert aurora_vids[0]['tags'] == ['aurora', 'storm', 'lightning bugs']
