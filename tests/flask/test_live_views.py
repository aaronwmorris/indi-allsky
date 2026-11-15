"""Polling and live-file regression tests for the image and canvas views."""

import ast
from datetime import datetime, timedelta, timezone
import math
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

from flask import Flask, request
import ephem
import pytest


def test_live_view_javascript():
    node = shutil.which('node')
    assert node, 'Node.js is required for the live-view regression tests'
    result = subprocess.run([node, '--test', str(Path(__file__).with_name('live_views.test.cjs'))],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture
def latest(tmp_path):
    # Import the actual request and file methods without the optional camera drivers.
    path = Path(__file__).resolve().parents[2] / 'indi_allsky/flask/views.py'
    tree = ast.parse(path.read_text())
    view_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'JsonLatestImageView')
    methods = [n for n in view_class.body if isinstance(n, ast.FunctionDef) and n.name in ('get_objects', 'setLiveFile')]
    scope = {'Path': Path, 'timedelta': timedelta, 'request': request}
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), 'exec'), scope)
    now = datetime(2026, 11, 7, 20)
    view = SimpleNamespace(history_seconds=900, indi_allsky_config={'IMAGE_FOLDER': str(tmp_path), 'IMAGE_FILE_TYPE': 'jpg'},
                           camera_now=now, camera_is_night=True, capture_pause=False, daytime_capture=True,
                           daytime_capture_save=False, local_indi_allsky=True, web_nonlocal_images=False,
                           live_file_allowed=True, latest_image_t='images/latest.{0}', sun_set_date=None)
    view.cameraSetup = lambda **kwargs: None
    calls = []

    def get_image(camera_id, history_seconds, not_after):
        calls.append((camera_id, history_seconds, not_after))
        return {'url': 'images/archive.jpg', 'width': 640, 'height': 480}

    view.getLatestImage = get_image
    view.setLiveFile = lambda *args, **kwargs: scope['setLiveFile'](view, *args, **kwargs)
    file = tmp_path / 'latest.jpg'
    file.write_bytes(b'test')
    ns = int(now.timestamp() * 1e9) - 1000000000
    os.utime(file, ns=(ns, ns))

    app = Flask(__name__)
    app.add_url_rule('/latest', view_func=lambda: scope['get_objects'](view))
    return app.test_client(), view, file, calls


def test_auto_switches_from_archive_to_stable_live_file_and_back(latest):
    client, view, file, calls = latest
    endpoint = '/latest?camera_id=3&night=auto'
    assert client.get(endpoint).get_json()['latest_image']['url'] == 'images/archive.jpg'
    assert calls == [(3, 900, view.camera_now)]
    view.camera_is_night = False
    expected = 'images/latest.jpg?v=' + str(file.stat().st_mtime_ns)
    assert client.get(endpoint).get_json()['latest_image']['url'] == expected
    assert client.get(endpoint).get_json()['latest_image']['url'] == expected
    assert client.get('/latest?camera_id=3&night=1').get_json()['latest_image']['url'] == 'images/archive.jpg'
    assert client.get('/latest?camera_id=3').get_json()['latest_image']['url'] == 'images/archive.jpg'
    view.camera_is_night = True
    assert client.get(endpoint).get_json()['latest_image']['url'] == 'images/archive.jpg'


@pytest.mark.parametrize('mode', ['daytime', 'focus'])
def test_live_file_not_served_when_access_is_disallowed(latest, mode):
    client, view, _, calls = latest
    view.camera_is_night = False
    view.live_file_allowed = False
    view.indi_allsky_config['FOCUS_MODE'] = mode == 'focus'
    image = client.get('/latest?camera_id=3&night=auto').get_json()['latest_image']
    assert image['url'] is None
    assert not calls


def test_missing_file_during_publish_is_retried_without_a_500(latest):
    client, view, file, _ = latest
    view.camera_is_night = False
    stamp = file.stat().st_mtime_ns
    file.unlink()
    endpoint = '/latest?camera_id=3&night=auto'
    assert client.get(endpoint).get_json()['latest_image']['url'] is None
    file.write_bytes(b'next')
    os.utime(file, ns=(stamp, stamp))
    assert client.get(endpoint).get_json()['latest_image']['url'].endswith(str(stamp))


def test_deliberately_disabled_daytime_does_not_show_the_last_night_as_current(latest):
    client, view, _, calls = latest
    view.camera_is_night = False
    view.daytime_capture = False
    image = client.get('/latest?camera_id=3&night=auto').get_json()['latest_image']
    assert image['url'] is None and 'Daytime capture disabled' in image['message']
    assert not calls


@pytest.mark.parametrize(('hour', 'night'), [(0, True), (12, False)])
def test_sun_altitude_is_evaluated_for_each_live_request(hour, night):
    path = Path(__file__).resolve().parents[2] / 'indi_allsky/flask/base_views.py'
    base = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'BaseView')
    method = next(n for n in base.body if isinstance(n, ast.FunctionDef) and n.name == 'getSunSetDate')

    class Clock(datetime):
        @classmethod
        def now(cls, tz):
            return datetime(2026, 9, 22, hour, tzinfo=tz)

    scope = dict(datetime=Clock, timezone=timezone, ephem=ephem, math=math)
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), scope)
    view = SimpleNamespace(camera=SimpleNamespace(latitude=45, longitude=0, elevation=0, nightSunAlt=-6))
    scope['getSunSetDate'](view)
    assert view.camera_is_night is night
