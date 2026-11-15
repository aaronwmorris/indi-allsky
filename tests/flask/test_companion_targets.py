"""Exercise target lookup, exact image permissions and frame-bound sky projection."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from flask import Flask
import pytest

from indi_allsky import companion_targets
from indi_allsky.companion_targets import OnlineCatalogUnavailable, UnknownTargetName, resolve_coordinates, resolve_name
from indi_allsky.flask import db, views
from indi_allsky.flask.companion import companion_status, latest_companion_image
from indi_allsky.flask.models import IndiAllSkyDbCameraTable as Camera, IndiAllSkyDbImageTable as Frame


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
    from unittest.mock import MagicMock
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
    from unittest.mock import MagicMock
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
    return dict(id='a' * 32, image_size=[width, 1000], location=[52.7, 12.4], values=dict(
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
