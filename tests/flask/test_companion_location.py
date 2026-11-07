import ast
import ipaddress
import math
import socket
from functools import cached_property
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import ephem
from flask import Flask, abort, current_app, request
import pytest

from indi_allsky.companion_astronomy import camera_timezone, night_ephemeris


@pytest.fixture(scope='module')
def functions():
    # Exercise the actual route and camera setup without importing hardware services.
    directory = Path(__file__).resolve().parents[2] / 'indi_allsky/flask'
    names = {'cameraSetup', 'getCameraPrivacyLatLong', 'getSunSetDate',
             'companion_status', 'latest_companion_image', 'verify_admin_network', 'local_images_allowed'}
    scope = dict(datetime=datetime, timedelta=timedelta, timezone=timezone, math=math,
                 ephem=ephem, request=request, abort=abort, camera_timezone=camera_timezone,
                 app=current_app, ipaddress=ipaddress, socket=socket, cached_property=cached_property,
                 psutil=SimpleNamespace(net_if_addrs=lambda: {}),
                 night_ephemeris=night_ephemeris,
                 companion_charts=lambda *args, **kwargs: ([], [], [{'id': 'test-series'}]))
    for filename in ('base_views.py', 'views.py', 'companion.py'):
        path = directory / filename
        tree = ast.parse(path.read_text(encoding='utf-8'))
        nodes = [node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef) and node.name in names]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), scope)
    return SimpleNamespace(**{name: scope[name] for name in names})


def view_for(functions, latitude, longitude, private):
    camera = SimpleNamespace(id=3, tz='UTC', utc_offset=0, local=False, data={},
                             latitude=latitude, longitude=longitude, nightSunAlt=None, elevation=None,
                             capture_pause=False, daytime_capture=True, daytime_capture_save=True,
                             s3_prefix='', web_nonlocal_images=False, web_local_images_admin=False)
    view = SimpleNamespace(camera=None, indi_allsky_config={'PRIVACY_MODE': private},
                           getCameraById=lambda camera_id: camera,
                           getSunSetDate=lambda: pytest.fail('unneeded legacy sunset calculation'),
                           local_images_allowed=True)
    view.cameraSetup = lambda **kwargs: functions.cameraSetup(view, **kwargs)
    view.getCameraPrivacyLatLong = lambda cam: functions.getCameraPrivacyLatLong(view, cam)
    view.getLatestImage = lambda *args, **kwargs: {
        'url': 'images/example.jpg', 'create_date': datetime(2026, 11, 7, 12),
    }
    return view


@pytest.mark.parametrize('private', [False, True])
@pytest.mark.parametrize('latitude,longitude', [(None, None), (None, 8.7), (48.2, None), (0.0, 0.0)])
def test_status_keeps_media_and_moon_phase_when_location_is_incomplete(functions, latitude, longitude, private):
    app = Flask(__name__)
    view = view_for(functions, latitude, longitude, private)
    app.add_url_rule('/status', view_func=lambda: functions.companion_status(view))
    response = app.test_client().get('/status?camera_id=3')
    assert response.status_code == 200
    data = response.get_json()
    assert data['image']['url'] == 'images/example.jpg' and data['series'][0]['id'] == 'test-series'
    assert data['astronomy']['moon_phase'] and 0 <= data['astronomy']['moon_illumination'] <= 100
    for key in ('evening_start', 'evening_end', 'morning_start', 'morning_end', 'moon_rise', 'moon_set'):
        assert (data['astronomy'][key] is None) == (latitude is None or longitude is None)


def test_image_only_does_not_depend_on_location(functions):
    app = Flask(__name__)
    view = view_for(functions, None, None, True)
    view.getCameraPrivacyLatLong = lambda cam: pytest.fail('unneeded location lookup')
    app.add_url_rule('/status', view_func=lambda: functions.companion_status(view))
    response = app.test_client().get('/status?camera_id=3&image_only=1')
    assert response.status_code == 200
    assert response.json['image']['url'] == 'images/example.jpg'
    assert 'astronomy' not in response.json and 'series' not in response.json


@pytest.mark.parametrize('latitude,longitude,horizon', [(None, 0, -6), (12, None, -6), (12, 0, None)])
def test_legacy_sunset_is_unavailable_without_observer_information(functions, latitude, longitude, horizon):
    view = SimpleNamespace(camera=SimpleNamespace(latitude=latitude, longitude=longitude,
                                                 elevation=None, nightSunAlt=horizon), sun_set_date='previous')
    functions.getSunSetDate(view)
    assert view.sun_set_date is None


def test_privacy_preserves_unknowns_and_rounds_each_available_coordinate(functions):
    view = SimpleNamespace(indi_allsky_config={'PRIVACY_MODE': True})
    cam = SimpleNamespace(latitude=None, longitude=8.7)
    assert functions.getCameraPrivacyLatLong(view, cam) == (None, 9.0)
    cam.latitude, cam.longitude = -24.3, 0.0
    assert functions.getCameraPrivacyLatLong(view, cam) == (-24.0, 0.0)


@pytest.mark.parametrize('remote_only,exception,client_ip,expected', [
    (True, True, '192.0.2.42', True),
    (True, True, '198.51.100.42', False),
    (True, False, '192.0.2.42', False),
    (False, False, '198.51.100.42', True),
])
def test_image_and_history_share_request_visibility(functions, monkeypatch, remote_only, exception, client_ip, expected):
    app = Flask(__name__)
    app.config['ADMIN_NETWORKS'] = ['192.0.2.0/24']

    class View(SimpleNamespace):
        local_images_allowed = functions.local_images_allowed
        verify_admin_network = functions.verify_admin_network

    def charts(*args, local_images_allowed):
        return [], [], ['local' if local_images_allowed else 'remote']

    monkeypatch.setitem(functions.companion_status.__globals__, 'companion_charts', charts)

    @app.get('/status')
    def status():
        source = view_for(functions, 45, 10, False)
        camera = source.getCameraById(3)
        camera.web_nonlocal_images = remote_only
        camera.web_local_images_admin = exception
        view = View(camera=None, indi_allsky_config=source.indi_allsky_config, getCameraById=source.getCameraById)
        view.cameraSetup = lambda **kwargs: functions.cameraSetup(view, **kwargs)
        view.getCameraPrivacyLatLong = lambda cam: functions.getCameraPrivacyLatLong(view, cam)
        view.getLatestImage = lambda *args, **kwargs: {
            'url': 'local' if view.local_images_allowed else 'remote',
            'create_date': datetime(2025, 1, 1),
        }
        return functions.companion_status(view)

    data = app.test_client().get('/status?camera_id=3', environ_base={'REMOTE_ADDR': client_ip}).get_json()
    source = 'local' if expected else 'remote'
    assert data['image']['url'] == source
    assert data['series'] == [source]
