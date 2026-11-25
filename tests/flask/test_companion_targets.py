"""Exercise target lookup, exact image permissions and frame-bound sky projection."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from flask import Flask
import pytest

from indi_allsky import companion_targets
from indi_allsky.companion_targets import OnlineCatalogUnavailable, UnknownTargetName, resolve_coordinates, resolve_name
from indi_allsky.flask import db, views
from indi_allsky.flask.companion import companion_status, latest_companion_image, skyline_directions
from indi_allsky.flask.models import IndiAllSkyDbCameraTable as Camera, IndiAllSkyDbImageTable as Frame


def test_draw_separate_branch_tips_without_bridging_open_sky_or_the_north_seam():
    heights = [10., 11., 31., None, 30., 29.]
    contour = skyline_directions({'altitudes': heights, 'step_deg': 60.})
    assert contour == [(10., 0.), (11., 60.), None, (31., 120.), None,
                       (30., 240.), (29., 300.), None, (10., 0.)]
    assert heights == [10., 11., 31., None, 30., 29.]


def test_estimated_contour_closes_at_north_and_spans_the_original_gaps():
    profile = {'altitudes': [None, 9., None, 30.], 'step_deg': 90., 'envelope': [19., 9., 20., 30.]}
    assert skyline_directions(profile) == [(19., 0.), (9., 90.), (20., 180.), (30., 270.), (19., 0.)]


@pytest.mark.parametrize('name,ra,dec', [
    ('Messier 0031', 10.685, 41.269), ('Andromeda Galaxy', 10.685, 41.269),
    ('nGc 07000', 314.821, 44.529), ('North America Nebula', 314.821, 44.529),
    ('IC 01805', 38.172, 61.457), ('Polarstern', 37.955, 89.264),
    ('Vega', 279.235, 38.784), ('Plejaden', 56.75, 24.117),
])
def test_catalogue_lookup(name, ra, dec):
    target = resolve_name(name)
    assert target['ra_deg'] == pytest.approx(ra, abs=.01)
    assert target['dec_deg'] == pytest.approx(dec, abs=.01)
    assert target['label']


@pytest.mark.parametrize('name', [
    "Thor’s Lightning", 'thors lightning nebula', 'SNR G150.3+4.5', 'G150.3+4.5',
])
def test_thors_lightning_aliases(name):
    assert resolve_name(name) == {'label': "Thor's Lightning", 'ra_deg': 66.75, 'dec_deg': 55.466667}


@pytest.mark.parametrize('name', ['Giant Squid Nebula', 'Squid Nebula', 'Tintenfischnebel', 'Ou4', 'Outters 4'])
def test_squid_nebula_aliases(name):
    assert resolve_name(name) == {'label': 'Squid Nebula', 'ra_deg': 317.95075, 'dec_deg': 59.985833}


def test_online_access_is_only_used_for_an_explicit_local_miss(monkeypatch):
    monkeypatch.setattr(companion_targets, '_sesame_reply', lambda name: pytest.fail('Unexpected network lookup'))
    assert resolve_name('Tintenfischnebel', online=True) == resolve_name('Ou4')
    with pytest.raises(UnknownTargetName):
        resolve_name('LDN 1235')
    with pytest.raises(ValueError, match='Several objects'):
        resolve_name('Antennae Galaxies', online=True)
    for invalid in ('', '  ', '---', 'Sirius\nVega', 'X' * 129):
        with pytest.raises(ValueError, match='Enter an object name'):
            resolve_name(invalid, online=True)


def test_online_reads_one_signed_j2000_position(monkeypatch):
    reply = ('<Sesame><Target><name>HD 209458</name><Resolver><jradeg>330.79</jradeg>'
             '<jdedeg>-0.62</jdedeg></Resolver></Target></Sesame>')
    monkeypatch.setattr(companion_targets, '_sesame_reply', lambda name: reply)
    assert resolve_name('HD 209458', online=True) == {'label': 'HD 209458', 'ra_deg': 330.79, 'dec_deg': -.62}


def test_online_distinguishes_a_catalogue_miss_from_service_errors(monkeypatch):
    reply = '<Sesame><Target><INFO> *** NNNothing found *** </INFO></Target></Sesame>'
    monkeypatch.setattr(companion_targets, '_sesame_reply', lambda name: reply)
    with pytest.raises(UnknownTargetName, match='CDS Sesame could not find'):
        resolve_name('Example unknown object', online=True)


@pytest.mark.parametrize('content', [
    '', '<html>Maintenance</html>', '<Sesame><Target/></Sesame>',
    '<!DOCTYPE Sesame [<!ENTITY name "value">]><Sesame/>',
    '<Sesame><Target><Resolver/><Resolver/></Target></Sesame>',
    '<Sesame><Target><Resolver><jdedeg>-2</jdedeg></Resolver></Target></Sesame>',
    '<Sesame><Target><Resolver><jradeg>nan</jradeg><jdedeg>1</jdedeg></Resolver></Target></Sesame>',
    '<Sesame><Target><Resolver><jradeg>-1</jradeg><jdedeg>1</jdedeg></Resolver></Target></Sesame>',
    '<Sesame><Target><Resolver><jradeg>180</jradeg><jdedeg>91</jdedeg></Resolver></Target></Sesame>',
])
def test_bad_online_responses_do_not_create_markers(monkeypatch, content):
    monkeypatch.setattr(companion_targets, '_sesame_reply', lambda name: content)
    with pytest.raises(OnlineCatalogUnavailable):
        resolve_name('Online test', online=True)


def test_online_transport_uses_a_fixed_host_and_quotes_the_whole_name(monkeypatch):
    connection = MagicMock()
    make_connection = MagicMock(return_value=connection)
    monkeypatch.setattr(companion_targets, 'HTTPSConnection', make_connection)
    response = connection.getresponse.return_value.__enter__.return_value
    response.status = 200
    response.isclosed.return_value = False
    response.read1.side_effect = [b'<Sesame/>', b'']
    assert companion_targets._sesame_reply('A+B /?&') == '<Sesame/>'
    make_connection.assert_called_once_with('vizier.idia.ac.za', timeout=3)
    connection.request.assert_called_once_with('GET', '/viz-bin/nph-sesame/-ox/SNV?A%2BB%20%2F%3F%26',
                                               headers={'Accept': 'application/xml'})
    connection.close.assert_called_once()


@pytest.mark.parametrize('problem', ['redirect', 'oversized', 'timeout'])
def test_online_transport_limits_replies_and_never_follows_redirects(monkeypatch, problem):
    connection = MagicMock()
    monkeypatch.setattr(companion_targets, 'HTTPSConnection', lambda *args, **kwargs: connection)
    response = connection.getresponse.return_value.__enter__.return_value
    response.status = 302 if problem == 'redirect' else 200
    response.isclosed.return_value = False
    if problem == 'oversized':
        response.read1.side_effect = lambda size: b'X' * size
    else:
        response.read1.side_effect = TimeoutError()
    with pytest.raises(OnlineCatalogUnavailable):
        resolve_name('Online test', online=True)
    if problem == 'redirect':
        response.read1.assert_not_called()
    connection.request.assert_called_once()
    connection.close.assert_called_once()


@pytest.mark.parametrize('ra,dec,expected', [
    ('12:30:00', '-00:30:00', (187.5, -.5)),
    ('12h30m00s', '−00°30′00″', (187.5, -.5)),
    ('12.5h', '+90', (187.5, 90)), ('12.5', '-90deg', (12.5, -90)),
    ('+12 30 00', '0 30', (187.5, .5)), ('0', '0', (0, 0)),
])
def test_coordinate_formats(ra, dec, expected):
    target = resolve_coordinates(ra, dec)
    assert (target['ra_deg'], target['dec_deg']) == expected


def solution(roll=0, width=1000, tilt=90):
    return dict(id='a' * 32, image_size=[width, 1000], location=[51.5, 0.0], values=dict(
        AZIMUTH_ANGLE=roll, POINTING_AZIMUTH=180, LENS_ALTITUDE=tilt, RADIAL_DISTORTION=0.,
        LATITUDE_OFFSET=0., LONGITUDE_OFFSET=0., IMAGE_CIRCLE_DIAMETER=1000,
        OFFSET_X=0, OFFSET_Y=0, PRECESSION=True))


@pytest.fixture
def station(tmp_path):
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', INDI_ALLSKY_IMAGE_FOLDER=str(tmp_path))
    db.init_app(app)
    with app.app_context():
        db.create_all()
        for cid in (1, 2):
            db.session.add(Camera(id=cid, name=f'camera {cid}', uuid=f'camera-{cid}', local=False))
        db.session.flush()
        wall = datetime(2026, 11, 14, 19, 30)
        for fid, cid, model, url in [
            (1, 1, solution(), 'https://example.com/one.jpg'),
            (2, 1, solution(roll=180), None),
            (3, 2, solution(), 'https://example.com/three.jpg'),
            (4, 1, solution(width=800), None),
            (5, 1, None, None),
            (6, 1, solution(tilt=0), None),
        ]:
            db.session.add(Frame(id=fid, camera_id=cid, filename=f'{fid}.jpg', remote_url=url,
                                 createDate=wall, dayDate=wall.date(), exposure=1, gain=1, adu=1,
                                 night=True, width=1000, height=1000,
                                 data={'utc_offset': 3600, 'star_alignment': model}))
        db.session.commit()
        view = SimpleNamespace(model=Frame, local_images_allowed=True, s3_prefix='',
                               getCameraPrivacyLatLong=lambda site: (site.latitude, site.longitude))
        view.cameraSetup = lambda camera_id, **_: setattr(view, 'camera', db.session.get(Camera, camera_id))
        app.add_url_rule('/companion', view_func=lambda: companion_status(view))
        yield app.test_client(), view


def call(client, frame, pairs):
    return client.get('/companion', query_string=[('camera_id', '1'), ('frame', frame)]
                      + [('target', pair) for pair in pairs])


@pytest.mark.parametrize('query', [
    {'ra':'nan', 'dec':'5'}, {'ra':'24:00:00', 'dec':'0'}, {'ra':'5', 'dec':'90:00:01'},
    {'ra':'5', 'dec':'0h'}, {'ra':'1:60', 'dec':'5'}, {'ra':'-1', 'dec':'5'}, {'ra':'1'},
    {'resolve':'unknown imaginary object'}, {'frame':'999999999999999999999', 'target':'1,0'},
    {'resolve':'G150.3-4.5'}, {'frame':1, 'target':'1,nan'}, {'frame':1, 'target':'360,0'}, {'frame':'1'},
])
def test_invalid_input_returns_actionable_json(station, query):
    client, _ = station
    response = client.get('/companion', query_string=dict(camera_id=1, **query))
    assert response.status_code == 400 and response.json['error']


def test_bulk_limit_only_applies_per_request(station):
    client, _ = station
    assert call(client, 1, ['0,90'] * 65).status_code == 400
    response = call(client, 5, ['0,90'] * 64)
    assert len(response.json['points']) == 64


def test_planning_without_a_frame_and_invalid_input(station):
    client, view = station
    params = dict(camera_id=1, target='17,59', target_settings='{}')
    view.getCameraPrivacyLatLong = lambda _: (51, 10)
    payload = client.get('/companion', query_string=params).json
    assert payload['frame'] is None and payload['qualities'][0]['state'] == 'unknown'
    assert payload['windows'][0]['state'] in ('open', 'upcoming', 'none')
    assert datetime.fromisoformat(payload['window_at']).tzinfo is not None
    for invalid in (dict(frame='x'), dict(target_settings='{bad')):
        assert client.get('/companion', query_string=dict(params, **invalid)).status_code == 400


def test_horizontal_track_and_capture_marker_share_the_fitted_lens():
    import numpy as np
    from indi_allsky.lens_solver.projection import precessCatalog, predictAltAz

    model = solution(roll=46, tilt=85)
    model['observed_at'] = 1794685508
    model['values'].update(LATITUDE_OFFSET=3., LONGITUDE_OFFSET=-5.)
    coordinates = [(66.75, 55.466667), (317.95075, 59.985833)]
    actual = companion_targets.project_targets(coordinates, model)
    catalog = precessCatalog(np.asarray(coordinates), model['observed_at'])
    alt, az = predictAltAz(catalog, *model['location'], model['observed_at'])
    track = companion_targets.project_horizon_line(model, list(zip(np.degrees(alt), np.degrees(az))) + [None])
    for point, sample in zip(actual, track):
        assert sample == pytest.approx(point, abs=1e-5)
    assert track[-1] is None


@pytest.mark.parametrize('extra', [
    [('path_end_at', 'bad')], [('path_end_at', 'NaN')], [('path_end_at', '2026-13-13T13:00Z')],
    [('path_end_at', '2026-11-14T19:15:00')], [('path_end_at', '2026-11-14T19:15:00+01:00')],
    [('path_end_at', ''), ('path_end_at', '')], [('edit_path', '-1')], [('edit_path', '1')],
    [('edit_path', '0'), ('edit_path', '0')], [('path_end_setup', 'a' * 65)],
])
def test_manual_path_rejects_ambiguous_or_invalid_requests(station, extra):
    client, _ = station
    query = [('camera_id', 1), ('frame', 1), ('target', '0,90'), ('target_settings', '{}')]
    response = client.get('/companion', query_string=query + extra)
    assert response.status_code == 400 and response.json['error']


def test_manual_path_uses_current_setup_exact_endpoint_and_only_selected_editor(station, monkeypatch):
    from indi_allsky.flask import companion
    client, view = station
    view.getCameraPrivacyLatLong = lambda _: (51.5, 0.0)

    class CaptureClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 14, 18, 30, 10, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(companion, 'datetime', CaptureClock)
    targets = [('target', '10,41'), ('target', '0,90')]
    base = [('camera_id', 1), ('edit_path', 0), ('target_settings', '{}')] + targets
    def request_frame(fid, *extra):
        return client.get('/companion', query_string=[('frame', fid)] + base + list(extra)).json

    automatic = request_frame(1)
    token = automatic['setup_id']
    assert token and len(token) == 32 and request_frame(1)['setup_id'] == token
    editor, untouched = automatic['windows']
    assert 'edit_path' not in untouched
    assert editor['edit_path'][0]['at'] == automatic['window_at']
    anchor = editor['edit_path'][18]
    assert set(anchor) == {'at', 'x', 'y'}
    end_at = anchor['at'].replace('+00:00', 'Z')
    marker = [('path_end_setup', token), ('path_end_at', end_at), ('path_end_at', '')]
    edited, other = request_frame(1, *marker)['windows']
    assert edited['manual_end_status'] == 'applied' and edited['track_end_reason'] == 'user_marked'
    assert edited['track_ends_at'] == anchor['at'] and edited['intersection'] == edited['track'][-1]
    assert edited['intersection'] == pytest.approx(dict(x=anchor['x'], y=anchor['y']), abs=.00005)
    assert other == untouched
    turned = request_frame(2, *marker)
    assert turned['setup_id'] != token and turned['windows'][0]['manual_end_status'] == 'setup_changed'
    assert turned['windows'][0]['track_end_reason'] != 'user_marked'
    unavailable = request_frame(5, *marker)
    assert unavailable['setup_id'] is None and unavailable['windows'][0]['manual_end_status'] == 'unavailable'
    assert unavailable['windows'][0]['edit_path'] == []
    late = request_frame(1, ('path_end_setup', token), ('path_end_at', '2026-11-15T18:30:05Z'), ('path_end_at', ''))
    assert late['windows'][0]['manual_end_status'] == 'out_of_range'  # 24h from the image, not the request.
    # Reversing the target list must not allow a northern pole on a south-facing lens.
    south = request_frame(6)
    inactive, off_sensor = request_frame(6, ('path_end_setup', south['setup_id']), ('path_end_at', ''),
                                         ('path_end_at', end_at))['windows']
    assert inactive['manual_end_status'] is None and off_sensor['manual_end_status'] == 'outside_image'
    # The pole never sets here. Even with an identical lens solution its
    # private time limit from yesterday must not follow it to another night.
    assert other['circumpolar'] is True
    image = db.session.get(Frame, 1)
    image.dayDate += timedelta(days=1)
    db.session.commit()
    later = request_frame(1, ('path_end_setup', token), ('path_end_at', ''), ('path_end_at', end_at))
    assert later['setup_id'] != token
    assert later['windows'][1]['manual_end_status'] == 'setup_changed'
    assert later['windows'][1]['track_end_reason'] == 'forecast_limit'


@pytest.fixture
def horizon_station(station, tmp_path, monkeypatch):
    from indi_allsky import companion_visible_horizon as vision
    from indi_allsky.flask import companion_horizon as cache
    from indi_allsky.flask.companion import companion_observed_horizon

    _, view = station
    entry = db.session.get(Frame, 1)
    anchor = entry.createDate
    minutes = [0, 1, 2, 10, 16, 17, 19, 21, 23, 38, 40, 42, 58]
    for index, minute in enumerate(minutes, 10):
        pose_id = 'b' if index in (11, 22) else 'a'
        pose = dict(solution(), id=pose_id * 32)
        db.session.add(Frame(id=index, camera_id=entry.camera_id, filename=f'{index}.jpg',
                             createDate=anchor + timedelta(minutes=minute), dayDate=anchor.date(),
                             exposure=30, gain=1, adu=1, night=True, width=1000, height=1000,
                             data={'utc_offset': 3600, 'star_alignment': pose}))
        (tmp_path / f'{index}.jpg').touch()
    db.session.commit()
    probes, full = [], []
    # No signal on 10 and 16, isolated departure at 15, repeatable change at 19/20.
    shapes = {10: None, 15: 2, 16: None, 19: 3, 20: 3, 21: 3, 22: 4}
    def signature(path, model):
        index = int(path.stem)
        probes.append(index)
        return shapes.get(index, 1)
    def measure(frames):
        full.append([int(path.stem) for path, _ in frames])
        return {'envelope': [float(len(frames))] * 4, 'frames': len(frames)}
    def request_frame(index):
        frame = db.session.get(Frame, index)
        return companion_observed_horizon(view, frame, views.virtualsky_frame_alignment(view, frame))
    monkeypatch.setattr(vision, 'horizon_signature', signature)
    monkeypatch.setattr(vision, 'significant_horizon_change', lambda a, b: a != b)
    monkeypatch.setattr(vision, 'measure_horizon', measure)
    monkeypatch.setattr(cache.tempfile, 'gettempdir', lambda: str(tmp_path / 'cache'))
    return request_frame, probes, full


def test_horizon_saved_from_first_good_frame_and_only_rebuilt_after_confirmation(horizon_station, tmp_path):
    from flask import current_app
    from indi_allsky.flask.companion_horizon import _read_version
    request_frame, probes, full = horizon_station
    first = request_frame(13)
    assert first['source_frame_id'] == 12 and full == [[12]] and probes == [10, 12]
    cache_path, = (tmp_path / 'cache').rglob('*.json')
    modified = cache_path.stat().st_mtime_ns
    _read_version.cache_clear()
    current_app.extensions.pop('companion_horizon_fallback')  # another worker starts empty
    assert request_frame(14) == first and cache_path.stat().st_mtime_ns == modified
    for index in (15, 15, 16, 17, 18, 19):
        assert request_frame(index) == first
    assert full == [[12]] and probes == [10, 12, 15, 16, 17, 19]
    updated = request_frame(20)
    assert updated['source_frame_id'] == 20 and full == [[12], [19, 20]]
    assert request_frame(21) == updated
    assert request_frame(13) == first and request_frame(10) is None  # no future references on replay
    assert request_frame(22)['source_frame_id'] == 11  # different pose has its own first good image
    assert full == [[12], [19, 20], [11]]


def test_horizon_concurrent_request_returns_available_reference_without_duplicate_work(horizon_station, tmp_path):
    import fcntl
    request_frame, probes, full = horizon_station
    first = request_frame(13)
    lock_path, = (tmp_path / 'cache').rglob('*.lock')
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert request_frame(15) == first
        assert probes == [10, 12] and full == [[12]]
    assert request_frame(15) == first and probes[-1] == 15


def test_horizon_keeps_acquisition_bounded_and_handles_unwritable_cache(horizon_station, tmp_path, monkeypatch):
    from indi_allsky.flask import companion_horizon as cache
    request_frame, probes, full = horizon_station
    (tmp_path / 'cache').touch()  # cannot create the shared cache directory
    wall = cache.time.time()
    monkeypatch.setattr(cache, 'time', SimpleNamespace(time=lambda: wall))
    assert request_frame(10) is None and request_frame(10) is None
    assert request_frame(13) is None and probes == [10] and full == []
    wall -= 3600  # an NTP correction or reboot cannot strand the retry cursor
    first = request_frame(13)
    assert first['source_frame_id'] == 12 and request_frame(13) == first and full == [[12]]


def test_historical_replay_never_replaces_live_reference(horizon_station, tmp_path, monkeypatch):
    from indi_allsky.flask import companion_horizon as cache
    request_frame, _, _ = horizon_station
    frame = db.session.get(Frame, 13)
    live = frame.createDate.replace(tzinfo=timezone(timedelta(hours=1))).timestamp()
    monkeypatch.setattr(cache, 'time', SimpleNamespace(time=lambda: live))
    first = request_frame(13)
    path, = (tmp_path / 'cache').rglob('*.json')
    previous = path.read_bytes()
    live += 86400
    assert request_frame(13) == first
    assert request_frame(15) == first
    assert len(list((tmp_path / 'cache').rglob('*.json'))) == 2 and path.read_bytes() == previous


def test_remote_only_targets_never_read_a_local_image(station, monkeypatch):
    from indi_allsky import companion_target_quality
    client, view = station
    view.local_images_allowed = False
    monkeypatch.setattr(companion_target_quality, 'assess_targets', lambda *a, **k: pytest.fail('Local image read'))
    params = dict(camera_id=1, target='17,59', target_settings='{}')
    assert client.get('/companion', query_string=dict(params, frame=1)).json['qualities'][0]['state'] == 'unknown'
    assert client.get('/companion', query_string=dict(params, frame=2)).json['state'] == 'unavailable'


def test_resolution_endpoint(station):
    client, _ = station
    assert client.get('/companion?camera_id=1&resolve=M31').json['target']['label'] == 'M31'
    assert client.get('/companion?camera_id=1&ra=12h&dec=-3').json['target']['ra_deg'] == 180


def test_other_camera_and_unpublished_remote_frame_are_inaccessible(station):
    client, view = station
    assert call(client, 3, ['0,90']).json == {'state':'unavailable', 'points':[None], 'frame':3}
    view.local_images_allowed = False
    assert call(client, 2, ['0,90']).json == {'state':'unavailable', 'points':[None], 'frame':2}


def test_missing_companion_alignment_support(station, monkeypatch):
    client, _ = station
    monkeypatch.delattr(views, 'virtualsky_frame_alignment', raising=False)
    assert call(client, 1, ['0,90']).json == {'frame':1, 'state':'unavailable', 'points':[None]}


@pytest.mark.skipif(not hasattr(views, 'virtualsky_frame_alignment'), reason='requires automatic stellar alignment')
@pytest.mark.parametrize('private_location', [(None, None), (None, 10), (50, None)])
def test_markers_require_both_visible_observer_coordinates(station, private_location):
    client, view = station
    view.getCameraPrivacyLatLong = lambda site: private_location
    assert call(client, 1, ['0,90']).json == {'frame':1, 'state':'orientation_pending', 'points':[None]}


@pytest.mark.skipif(not hasattr(views, 'virtualsky_frame_alignment'), reason='requires automatic stellar alignment')
def test_markers_use_the_requested_frame_and_its_capture_geometry(station):
    client, _ = station
    # Northern pole is above the northern horizon here, southern pole is below it.
    coords = ['0,90', '0,-90', '279.2347,38.7837']
    original = call(client, 1, coords).json
    turned = call(client, 2, coords).json
    assert original['state'] == turned['state'] == 'ready'
    p, invisible, vega = original['points']
    assert invisible is None and vega is not None
    assert abs(p['x'] - .5) < .01 and .23 < p['y'] < .30
    assert turned['points'][0]['y'] == pytest.approx(1 - p['y'])
    assert call(client, 4, coords).json['state'] == 'orientation_pending'  # mismatched dimensions
    assert call(client, 5, coords).json['state'] == 'orientation_pending'  # unsolved frame
    assert call(client, 6, coords).json['points'][0] is None  # lens facing due south


def test_live_file_never_inherits_saved_image_id(tmp_path):
    now = datetime.now(timezone.utc)
    record = {'url': 'images/exposure.jpg', 'id': 7, 'create_date': (now - timedelta(minutes=2)).replace(tzinfo=None)}
    view = SimpleNamespace(indi_allsky_config={'FOCUS_MODE': True, 'IMAGE_FOLDER': str(tmp_path)}, live_file_allowed=True)
    assert latest_companion_image(view, now, record)['id'] == 7
    (Path(tmp_path) / 'latest.jpg').touch()
    current = latest_companion_image(view, now + timedelta(seconds=1), record)
    assert current['time_source'] == 'file' and 'id' not in current
