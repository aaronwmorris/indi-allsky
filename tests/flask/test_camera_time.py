import ast
from datetime import datetime, timedelta, timezone
import hashlib
import math
from pathlib import Path
from types import SimpleNamespace

import flask
import pytest
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import and_


def load_method(filename, class_name, method_name, namespace):
    # Run the production methods without importing the camera/D-Bus services.
    path = Path(__file__).resolve().parents[2] / 'indi_allsky/flask' / filename
    tree = ast.parse(path.read_text(encoding='utf-8'))
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(node for node in cls.body
                  if isinstance(node, ast.FunctionDef) and node.name == method_name)
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[method_name]


@pytest.mark.parametrize('age_seconds', [30, 901], ids=['fresh', 'expired'])
@pytest.mark.parametrize('local,saved_offset,host_offset,wall_time', [
    (True, 7200, 3600, datetime(2026, 10, 25, 12)),
    (True, 3600, 7200, datetime(2026, 3, 29, 12)),
    (True, 3600, 3600, datetime(2026, 10, 25, 12)),
    (True, 0, 0, datetime(2026, 10, 25, 12)),
    (False, 7200, 0, datetime(2026, 10, 25, 12)),
    (False, -18000, 7200, datetime(2026, 10, 25, 12)),
    (False, 19800, -18000, datetime(2026, 10, 25, 12)),
], ids=['local-autumn', 'local-spring', 'local-normal', 'local-utc',
        'remote-ahead', 'remote-behind', 'remote-fractional'])
def test_latest_image_camera_time(local, saved_offset, host_offset, wall_time, age_seconds):
    class Clock(datetime):
        @classmethod
        def now(cls):
            return cls.combine(wall_time.date(), wall_time.time())

        def astimezone(self, tz=None):
            return self.replace(tzinfo=timezone(timedelta(seconds=host_offset)))

    app = flask.Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    db = SQLAlchemy(app)

    class Camera(db.Model):
        id = db.Column(db.Integer, primary_key=True)

    class Image(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        camera_id = db.Column(db.Integer, db.ForeignKey(Camera.id))
        camera = db.relationship(Camera)
        createDate = db.Column(db.DateTime, nullable=False)
        width = db.Column(db.Integer, default=1920)
        height = db.Column(db.Integer, default=1080)

        def getUrl(self, **kwargs):
            return 'images/{0}.jpg'.format(self.id)

    namespace = dict(datetime=Clock, timedelta=timedelta, and_=and_,
                     IndiAllSkyDbCameraTable=Camera)
    setup = load_method('base_views.py', 'BaseView', 'cameraSetup', namespace)
    latest = load_method('views.py', 'JsonLatestImageView', 'getLatestImage', namespace)
    expected_offset = 0 if local else saved_offset - host_offset
    camera_now = wall_time + timedelta(seconds=expected_offset)

    with app.app_context():
        db.create_all()
        camera = Camera(id=7)
        camera.local = local
        camera.utc_offset = saved_offset
        camera.daytime_capture = camera.daytime_capture_save = True
        camera.capture_pause = False
        camera.s3_prefix = ''
        camera.web_nonlocal_images = camera.web_local_images_admin = False
        camera.data = {}
        db.session.add_all([camera, Camera(id=8)])
        db.session.add_all([
            Image(id=1, camera_id=7, createDate=camera_now - timedelta(seconds=age_seconds)),
            Image(id=2, camera_id=8, createDate=camera_now),
        ])
        db.session.commit()
        view = SimpleNamespace(camera=None, getCameraById=lambda camera_id: camera,
                               getSunSetDate=lambda: None, model=Image)
        setup(view, camera_id=7)
        result = latest(view, camera_id=7, history_seconds=900)
        expected = ({'url': 'images/1.jpg', 'width': 1920, 'height': 1080}
                    if age_seconds < 900 else {'url': None})
        assert result == expected
        assert view.camera_time_offset == expected_offset
        assert view.camera_now == camera_now


@pytest.mark.parametrize('local,saved_offset,host_offset,wall_time', [
    (True, 7200, 3600, datetime(2026, 10, 25, 12)),
    (True, 3600, 7200, datetime(2026, 3, 29, 12)),
    (False, 7200, 0, datetime(2026, 10, 25, 12)),
    (False, -18000, 7200, datetime(2026, 10, 25, 12)),
    (False, 19800, -18000, datetime(2026, 10, 25, 12)),
], ids=['local-autumn', 'local-spring', 'remote-ahead', 'remote-behind', 'remote-fractional'])
def test_virtualsky_overlay_uses_solver_camera_time(local, saved_offset, host_offset, wall_time):
    class Clock(datetime):
        @classmethod
        def now(cls):
            return cls.combine(wall_time.date(), wall_time.time())

        def astimezone(self, tz=None):
            return self.replace(tzinfo=timezone(timedelta(seconds=host_offset)))

    class TemplateView:
        def get_context(self):
            return {}

    root = Path(__file__).resolve().parents[2]
    app = flask.Flask(__name__, static_folder=str(root / 'indi_allsky/flask/static'))
    namespace = dict(datetime=Clock, timedelta=timedelta, hashlib=hashlib, math=math,
                     Path=Path, app=flask.current_app, request=flask.request,
                     IndiAllskyVirtualSkyHelperForm=lambda **kwargs: None)
    setup = load_method('base_views.py', 'BaseView', 'cameraSetup', namespace)

    class VirtualSkyView(TemplateView):
        get_context = load_method('views.py', 'VirtualSkyView', 'get_context', namespace)

    namespace['VirtualSkyView'] = VirtualSkyView
    view = VirtualSkyView()
    view.camera = SimpleNamespace(local=local, utc_offset=saved_offset, az=0, alt=90, data={},
                                  daytime_capture=True, daytime_capture_save=True,
                                  capture_pause=False, s3_prefix='', web_nonlocal_images=False,
                                  web_local_images_admin=False)
    view.image_loop_view = 'indi_allsky.js_image_loop_view'
    view.indi_allsky_config = {}
    view.getSunSetDate = lambda: None
    view.getCameraPrivacyLatLong = lambda camera: (52, 13)
    setup(view)

    with app.test_request_context():
        context = view.get_context()

    # The solver's observation time and calibration context use camera_time_offset.
    assert context['time_offset'] == view.camera_time_offset == (0 if local else saved_offset - host_offset)
