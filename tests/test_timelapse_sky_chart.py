from datetime import datetime
from datetime import timedelta
import json
import os
import tempfile

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
from indi_allsky.flask.models import IndiAllSkyDbCameraTable
from indi_allsky.flask.models import IndiAllSkyDbVideoTable
from indi_allsky.video import build_video_chart_summary


class TestBuildVideoChartSummary:
    def test_returns_none_for_empty_or_all_null(self):
        assert build_video_chart_summary([]) is None
        assert build_video_chart_summary([(datetime(2026, 11, 22, 21, 0), None, None)]) is None

    def test_preserves_points_below_max_points(self):
        t0 = datetime(2026, 11, 22, 21, 0)
        samples = [
            (t0, 100, 19.5),
            (t0 + timedelta(minutes=5), 120, 20.0),
        ]
        summary = build_video_chart_summary(samples, max_points=96)
        assert summary == {
            'labels': ['21:00', '21:05'],
            'stars': [100.0, 120.0],
            'sqm': [19.5, 20.0],
        }

    def test_downsamples_large_series_to_max_points(self):
        t0 = datetime(2026, 11, 22, 20, 0)
        samples = [
            (t0 + timedelta(minutes=i), i, 18.0 + (i * 0.01))
            for i in range(300)
        ]
        summary = build_video_chart_summary(samples, max_points=50)
        assert summary is not None
        assert len(summary['labels']) <= 50
        assert len(summary['stars']) == len(summary['labels'])
        assert len(summary['sqm']) == len(summary['labels'])


class TestVideoViewerChartSummary:
    def test_get_videos_exposes_chart_summary(self):
        flask_app = create_app()
        flask_app.config['WTF_CSRF_ENABLED'] = False
        with flask_app.app_context(), flask_app.test_request_context():
            db.create_all()
            cam = IndiAllSkyDbCameraTable(
                uuid='cam-uuid-chart',
                name='TestCam',
                friendlyName='TestCam',
            )
            db.session.add(cam)
            db.session.commit()

            now = datetime(2026, 11, 22, 23, 0, 0)
            chart_summary = {'labels': ['21:00', '22:00'], 'stars': [80, 110], 'sqm': [19.1, 19.8]}
            vid = IndiAllSkyDbVideoTable(
                filename='vid_chart.mp4',
                camera_id=cam.id,
                createDate=now,
                dayDate=now.date(),
                dayDate_year=2026,
                dayDate_month=11,
                dayDate_day=22,
                night=True,
                success=True,
                data={'chart_summary': chart_summary},
            )
            db.session.add(vid)
            db.session.commit()

            viewer = IndiAllskyVideoViewer(camera_id=cam.id, local=True)
            videos = viewer.getVideos(2026, 11, 'night')
            assert len(videos) == 1
            assert videos[0]['chart_summary'] == chart_summary

    def test_get_videos_hides_chart_summary_for_day(self):
        flask_app = create_app()
        flask_app.config['WTF_CSRF_ENABLED'] = False
        with flask_app.app_context(), flask_app.test_request_context():
            db.create_all()
            cam = IndiAllSkyDbCameraTable(
                uuid='cam-uuid-day-chart',
                name='TestCamDay',
                friendlyName='TestCamDay',
            )
            db.session.add(cam)
            db.session.commit()

            now = datetime(2026, 11, 22, 12, 0, 0)
            chart_summary = {'labels': ['12:00', '13:00'], 'stars': [0, 0], 'sqm': [10.0, 10.2]}
            vid = IndiAllSkyDbVideoTable(
                filename='vid_day_chart.mp4',
                camera_id=cam.id,
                createDate=now,
                dayDate=now.date(),
                dayDate_year=2026,
                dayDate_month=11,
                dayDate_day=22,
                night=False,
                success=True,
                data={'chart_summary': chart_summary},
            )
            db.session.add(vid)
            db.session.commit()

            viewer = IndiAllskyVideoViewer(camera_id=cam.id, local=True)
            videos = viewer.getVideos(2026, 11, 'day')
            assert len(videos) == 1
            assert videos[0]['chart_summary'] is None
