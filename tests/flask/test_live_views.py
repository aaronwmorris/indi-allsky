"""Polling and live-file regression tests for the image and canvas views."""

import ast
from datetime import datetime, timedelta, timezone
import math
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import json

from indi_allsky.archive_health import BLOCKED
from indi_allsky import constants
from indi_allsky.live_status import CAPTURE_STATES, camera_timezone, capture_time, health_reason, latest_live_row, station_status

from flask import Flask, jsonify, request
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
    method_names = ('get_objects', 'setLiveFile', 'get_live_status', 'set_last_permitted_image', 'set_archive_frame')
    methods = [n for n in view_class.body if isinstance(n, ast.FunctionDef) and n.name in method_names]
    panel_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'AjaxStatusUpdateView')
    methods.append(next(n for n in panel_class.body if isinstance(n, ast.FunctionDef) and n.name == 'dispatch_request'))
    now = datetime(2026, 11, 7, 20)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now
    camera_zone = now.astimezone().tzinfo
    user = SimpleNamespace(is_authenticated=False, is_admin=False)
    # The real archive access rule is shared with login_optional_media.
    misc = ast.parse((path.parent/'misc.py').read_text())
    rule = next(n for n in misc.body if isinstance(n, ast.FunctionDef) and n.name == 'media_access_allowed')
    methods.append(rule)
    base_path = path.parent / 'base_views.py'
    base = next(n for n in ast.parse(base_path.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'BaseView')
    station_methods = ('get_indi_allsky_status', 'render_status_panel', 'get_status_text')
    methods.extend(n for n in base.body if isinstance(n, ast.FunctionDef) and n.name in station_methods)

    scope = dict(Path=Path, constants=constants, CAPTURE_STATES=CAPTURE_STATES, station_status=station_status,
                 time=SimpleNamespace(time=lambda: now.timestamp()),
                 psutil=SimpleNamespace(boot_time=lambda: now.timestamp() - 10),
                 archive_state=lambda cfg: {}, ups_problem=lambda path: False, timedelta=timedelta,
                 request=request, jsonify=jsonify, datetime=Clock, timezone=timezone, BLOCKED=BLOCKED,
                 camera_timezone=lambda camera: camera_zone, capture_time=capture_time, health_reason=health_reason, current_user=user)
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), 'exec'), scope)
    view = SimpleNamespace(history_seconds=900, indi_allsky_config={'IMAGE_FOLDER': str(tmp_path), 'IMAGE_FILE_TYPE': 'jpg'},
                           camera_now=now, camera_is_night=True, capture_pause=False, daytime_capture=True,
                           daytime_capture_save=False, local_indi_allsky=True, web_nonlocal_images=False,
                           live_file_allowed=True, latest_image_t='images/latest.{0}', sun_set_date=None)
    view.cameraSetup = lambda **kwargs: None
    view.camera = SimpleNamespace(id=3, local=True)
    view.live_archive_state = {}
    view.login_disabled = False
    view.web_local_images_admin = False
    view.user = user
    view.verify_admin_network = lambda: True
    view.live_states = {
        'DB_CAMERA_ID': SimpleNamespace(value='3', createDate=now-timedelta(days=1)),
        'CAPTURE_HEALTH': SimpleNamespace(value=json.dumps({'updated':int(now.timestamp()), 'stage':'idle'}), createDate=now)
    }
    view.live_states['WATCHDOG'] = SimpleNamespace(value=str(int(now.timestamp())))
    view.live_states['STATUS'] = SimpleNamespace(value=str(constants.STATUS_RUNNING))
    view.get_camera_info = lambda: {'camera_name':'Fixture'}
    view.get_astrometric_info = view.get_smoke_info = view.get_aurora_info = view.get_image_data = lambda: {}
    view.getUptime = lambda: 'fixture uptime'
    view.get_web_extra_text = lambda: '<div>Extra text</div>'
    calls = []

    def get_image(camera_id, history_seconds, not_after=None, live_now=None):
        calls.append((camera_id, history_seconds, not_after))
        return {'url': 'images/archive.jpg', 'width': 640, 'height': 480,
                'create_date': now - timedelta(hours=2), 'id': 17, 'utc_offset': None}

    view.getLatestImage = get_image
    for name in (*method_names[1:], *station_methods):
        setattr(view, name, scope[name].__get__(view))
    file = tmp_path / 'latest.jpg'
    file.write_bytes(b'test')
    ns = int(now.timestamp() * 1e9) - 1000000000
    os.utime(file, ns=(ns, ns))

    app = Flask(__name__)
    scope.update(app=app)
    app.add_url_rule('/latest', 'latest', view_func=lambda: scope['get_objects'](view))
    app.add_url_rule('/panel', 'panel', view_func=lambda: scope['dispatch_request'](view))
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


def test_opted_in_page_can_open_old_frame_and_keep_it_while_paused(latest):
    client, view, _, calls = latest
    url = '/latest?camera_id=3&live_status=1&night=auto'
    data = client.get(url).get_json()
    image = data['latest_image']
    assert image['frame_key'] == '3:17' and image['time_source'] == 'capture'
    assert image['url'] == 'images/archive.jpg' and calls[-1] == (3, None, None)
    assert datetime.fromisoformat(data['live_status']['now']).timestamp() - datetime.fromisoformat(image['captured_at']).timestamp() == 7200
    assert data['live_status']['reason'] == 'no_recent_image'
    view.capture_pause = True
    view.daytime_capture_save = True
    paused = client.get(url).get_json()
    assert paused['latest_image']['frame_key'] == image['frame_key'] and paused['live_status']['reason'] == 'paused'
    assert client.get('/latest?camera_id=3').get_json()['latest_image']['url'] is None


def test_live_file_revision_time_restrictions_and_archive_guard(latest, monkeypatch):
    client, view, file, _ = latest
    view.camera_is_night = False
    url = '/latest?camera_id=3&live_status=1&night=auto'
    original = client.get(url).get_json()
    entry = original['latest_image']
    assert entry['time_source'] == 'file' and entry['frame_key'] == 'file:{}'.format(file.stat().st_mtime_ns)
    assert datetime.fromisoformat(entry['captured_at']).timestamp() == file.stat().st_mtime
    assert original['live_status']['reason'] is None
    view.live_archive_state = {'level':BLOCKED, 'reason':'full'}
    stat = Path.stat
    def checked_stat(path, *args, **kwargs):
        assert path != file, 'a web request must not probe a blocked archive'
        return stat(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', checked_stat)
    data = client.get(url).get_json()
    assert data['latest_image']['url'] is None and data['live_status']['reason'] == 'archive_full'
    view.live_states['DB_CAMERA_ID'].value = '4'
    data = client.get(url).get_json()
    assert data['latest_image']['url'] is None and data['live_status']['reason'] == 'no_recent_image'


@pytest.mark.parametrize(('trusted','login_disabled','admin','remote','expected','manage','sign_in'), [
    (True, False, False, False, 'capture_recovering', False, True),
    (False, False, False, False, 'no_recent_image', False, False),
    (False, False, True, False, 'capture_recovering', True, False),
    (True, True, False, False, 'capture_recovering', True, False),
    (True, False, True, True, 'no_recent_image', False, False),
])
def test_diagnostic_scope_and_recovery_labels(latest, trusted, login_disabled, admin, remote, expected, manage, sign_in):
    client, view, _, _ = latest
    view.login_disabled = login_disabled
    view.verify_admin_network = lambda: trusted
    view.user.is_authenticated = view.user.is_admin = admin
    view.local_indi_allsky = not remote
    state = view.live_states['CAPTURE_HEALTH']
    state.value = json.dumps({'updated': view.camera_now.timestamp(), 'recovery':'capture'})
    url = '/latest?camera_id=3&live_status=1&night=auto'
    status = client.get(url).get_json()['live_status']
    assert (status['reason'], status['can_manage'], status['can_sign_in_to_manage']) == (expected, manage, sign_in)
    if trusted and not admin and not remote:
        view.web_nonlocal_images = True
        assert client.get(url).get_json()['live_status']['reason'] == 'no_recent_image'


def test_stale_worker_does_not_report_recovery_or_old_archive_state(latest):
    client, view, _, _ = latest
    view.live_archive_state = {'level':BLOCKED, 'reason':'full'}
    view.live_states['CAPTURE_HEALTH'].value = json.dumps({'updated':view.camera_now.timestamp()-91, 'recovery':'image'})
    assert client.get('/latest?camera_id=3&live_status=1').get_json()['live_status']['reason'] == 'capture_status_stale'
    view.indi_allsky_config.update(EXPOSURE_PERIOD_DAY=150, EXPOSURE_PERIOD=30, CCD_EXPOSURE_MAX=10)
    assert client.get('/latest?camera_id=3&live_status=1&night=0').get_json()['live_status']['stale_after_s'] == 315
    assert client.get('/latest?camera_id=3&live_status=1&night=1').get_json()['live_status']['stale_after_s'] == 90


def test_live_view_orders_the_repeated_hour_by_real_time(tmp_path):
    import sqlalchemy as sa
    from sqlalchemy.orm import Session, declarative_base
    zone = ZoneInfo('Europe/Berlin')
    base = declarative_base()
    class Frame(base):
        __tablename__ = 'test_frames'
        id = sa.Column(sa.Integer, primary_key=True)
        createDate = sa.Column(sa.DateTime)
        data = sa.Column(sa.JSON)
    engine = sa.create_engine('sqlite:///:memory:')
    base.metadata.create_all(engine)
    with Session(engine) as db:
        wall = datetime(2026, 10, 25, 2, 50)
        first = Frame(createDate=wall, data={'utc_offset':7200})
        second = Frame(createDate=wall.replace(minute=2), data={'utc_offset':3600})
        future = Frame(createDate=wall.replace(minute=25), data={'utc_offset':3600})
        db.add_all([first, second, future]); db.commit()
        now = wall.replace(minute=15, tzinfo=zone, fold=1)
        assert latest_live_row(db.query(Frame), Frame, now).id == second.id
        assert latest_live_row(db.query(Frame), Frame, now.replace(hour=3)).id == future.id
        db.delete(second); db.commit()
        assert latest_live_row(db.query(Frame), Frame, now).id == first.id
        assert capture_time(wall, 7200, now).timestamp() < now.timestamp()
        assert capture_time(wall, None, now.replace(hour=3)) is None
        assert capture_time(wall.replace(month=3, day=29), None, now) is None


def test_anonymous_live_view_respects_archive_auth_while_authenticated_can_open_old_frame(latest):
    client, view, _, _ = latest
    view.daytime_capture_save = True
    client.application.config['INDI_ALLSKY_AUTH_MEDIA_VIEWS'] = True
    url = '/latest?camera_id=3&live_status=1'
    assert client.get(url).get_json()['latest_image']['url'] is None
    view.capture_pause = True
    assert client.get(url).get_json()['latest_image']['url'] is None
    view.user.is_authenticated = True
    assert client.get(url).get_json()['latest_image']['url'] == 'images/archive.jpg'
    view.capture_pause = False
    view.user.is_authenticated = False
    # The same public live page still serves a recent authorized live frame.
    get = view.getLatestImage
    view.getLatestImage = lambda *a, **kw: {**get(*a, **kw), 'create_date':view.camera_now-timedelta(seconds=20)}
    assert client.get(url).get_json()['latest_image']['frame_key'] == '3:17'

@pytest.mark.parametrize(('published','code','label'), [
    (constants.STATUS_RUNNING, 'running', 'RUNNING'),
    (constants.STATUS_NOINDISERVER, 'no_indiserver', 'NO INDISERVER'),
    (constants.STATUS_STOPPED, 'stopped', 'STOPPED'),
    (constants.STATUS_CAMERAERROR, 'camera_error', 'CAMERA ERROR'),
])
def test_panel_and_image_share_the_station_status_even_with_a_fresh_frame(latest, published, code, label):
    client, view, _, _ = latest
    view.indi_allsky_config['WEB_STATUS_TEMPLATE'] = '{camera_name}: {status}'
    view.live_states['STATUS'].value = str(published)
    endpoint = '/latest?camera_id=3&live_status=1&night=0'
    fast = client.get(endpoint).get_json()
    assert fast['latest_image']['url'] and fast['live_status']['reason'] is None
    assert fast['live_status']['station']['code'] == code
    assert 'status_text' not in fast
    full = client.get(endpoint + '&status_details=1').get_json()
    assert client.get('/panel?camera_id=3').get_json()['status_text'] == full['status_text']
    station = full['live_status']['station']
    assert station == fast['live_status']['station']
    assert full['status_text'] == (
        '<div>Fixture: <span data-station-state class="{}">{}</span></div><div>Extra text</div>'
        .format(station['class_name'], label)
    )


def test_panel_details_are_opt_in_and_use_a_single_station_snapshot(latest):
    from unittest.mock import Mock
    client, view, _, _ = latest
    view.get_indi_allsky_status = Mock(wraps=view.get_indi_allsky_status)
    view.get_astrometric_info = Mock(return_value={})
    endpoint = '/latest?camera_id=3&night=0'
    assert 'live_status' not in client.get(endpoint + '&status_details=1').get_json()
    view.get_indi_allsky_status.assert_not_called()
    client.get(endpoint + '&live_status=1')
    view.get_indi_allsky_status.assert_called_once_with(notify=False)
    view.get_astrometric_info.assert_not_called()
    view.get_indi_allsky_status.reset_mock()
    view.indi_allsky_config['WEB_STATUS_TEMPLATE'] = 'Camera {camera_name}'
    full = client.get(endpoint + '&live_status=1&status_details=1').get_json()
    assert full['status_text'] == '<div>Camera Fixture</div><div>Extra text</div>'
    view.get_indi_allsky_status.assert_called_once_with(notify=True)
    view.get_astrometric_info.assert_called_once()


def test_stopping_and_restarting_indi_updates_state_without_waiting_for_a_new_frame(latest):
    client, view, _, _ = latest
    view.indi_allsky_config['WEB_STATUS_TEMPLATE'] = '{status}'
    endpoint = '/latest?camera_id=3&night=0&live_status=1'
    responses = []
    for value in (constants.STATUS_RUNNING, constants.STATUS_NOINDISERVER, constants.STATUS_RUNNING):
        view.live_states['STATUS'].value = str(value)
        responses.append(client.get(endpoint).get_json())

    assert [response['live_status']['station']['code'] for response in responses] == [
        'running', 'no_indiserver', 'running',
    ]
    frame = responses[0]['latest_image']
    assert frame['frame_key'] and frame['captured_at']
    assert all(response['latest_image'] == frame for response in responses)


def test_camera_timezone_uses_host_dst_and_remote_camera_offset(monkeypatch):
    monkeypatch.setenv('TZ', 'Europe/Berlin')
    camera = SimpleNamespace(local=True, tz='CST', utc_offset=-21600)
    zone = camera_timezone(camera)
    assert datetime(2026, 7, 1, tzinfo=zone).utcoffset() == timedelta(hours=2)
    assert datetime(2026, 12, 1, tzinfo=zone).utcoffset() == timedelta(hours=1)
    camera.local = False
    assert camera_timezone(camera).utcoffset(None) == timedelta(hours=-6)
