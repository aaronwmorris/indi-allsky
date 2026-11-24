"""Completed reports share local-media permissions and never render in HTTP."""
from datetime import date
from pathlib import Path
import re

from flask import Flask
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader
import pytest

from indi_allsky.flask import db, views
from indi_allsky.flask.forms import night_report_urls
from indi_allsky.flask.models import IndiAllSkyDbCameraTable as Camera, IndiAllSkyDbKeogramTable as Keogram
from indi_allsky.flask.models import IndiAllSkyDbTaskQueueTable as Task, TaskQueueState, IndiAllSkyDbUserTable as User
from indi_allsky import night_report_service


@pytest.fixture
def reports(tmp_path, monkeypatch):
    archive = tmp_path / 'images'
    archive.mkdir()
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
                      INDI_ALLSKY_IMAGE_FOLDER=str(archive), SECRET_KEY='test')
    db.init_app(app)
    CSRFProtect(app)
    login = LoginManager(app)
    login.user_loader(lambda user_id: db.session.get(User, int(user_id)))
    login.unauthorized_handler(lambda: ('Sign in', 401))

    def initialize(view, template_name=None):
        view.login_disabled = app.config.get('LOGIN_DISABLED', False)
        view.indi_allsky_config = {}
        view.template_name = template_name

    for cls in (views.NightReportView, views.NightReportPageView, views.LatestNightReportRedirect):
        monkeypatch.setattr(cls, '__init__', initialize)
        monkeypatch.setattr(cls, 'verify_admin_network', lambda self: app.config.get('TRUSTED', False))
    monkeypatch.setattr(views.TemplateView, 'get_context', lambda self: {})
    monkeypatch.setattr(night_report_service, 'read_report_metadata', lambda entry: app.config.get('REPORT_METADATA', {
        'metrics': [{'id': 'lux', 'label': 'Sky Brightness', 'unit': 'lx', 'kind': 'lux'},
                    {'id': 'sky_temperature', 'label': 'Sky Temperature', 'unit': '°C', 'kind': 'temperature'}],
        'selected_metrics': ['lux'],
    }))
    monkeypatch.setattr(night_report_service, 'report_ready', lambda entry: app.config.get('READY', True))
    monkeypatch.setattr(night_report_service, 'report_paths', lambda entry: {
        kind: archive / ('report.' + kind) for kind in ('png', 'csv')
    })
    (archive / 'report.png').write_bytes(b'\x89PNG\r\n\x1a\nreport')
    (archive / 'report.csv').write_text('time,sky_temperature_c\n2026-11-14T20:00:00+01:00,-25\n')
    app.add_url_rule('/night_report', endpoint='indi_allsky.night_report_view',
                     view_func=views.NightReportView.as_view('report'))
    app.add_url_rule('/latestnightreport', view_func=views.LatestNightReportRedirect.as_view('latest_report'))
    app.add_url_rule('/view_keogram', endpoint='indi_allsky.keogram_image_view', view_func=lambda: '')
    templates = Path(__file__).resolve().parents[2] / 'indi_allsky' / 'flask' / 'templates'
    app.jinja_loader = ChoiceLoader([DictLoader({'base.html': '{% block head %}{% endblock %}{% block content %}{% endblock %}'}),
                                    FileSystemLoader(str(templates))])
    with app.app_context():
        db.create_all()
        camera = Camera(id=1, name='test', uuid='test', local=True, hidden=False)
        entry = Keogram(id=1, camera=camera, filename='keogram.jpg',
                        dayDate=date(2026, 11, 14), night=True, success=True)
        db.session.add(entry)
        db.session.commit()
        yield app.test_client(), app, entry, archive
        db.session.remove()
        db.drop_all()


@pytest.mark.parametrize('fmt,download,mime,disposition', [
    ('png', None, 'image/png', 'inline'),
    ('png', '1', 'image/png', 'attachment'),
    ('csv', None, 'text/csv', 'attachment'),
])
def test_download_completed_report(reports, fmt, download, mime, disposition):
    client, _, _, archive = reports
    query = {'keogram_id': 1, 'format': fmt}
    if download:
        query['download'] = download
    response = client.get('/night_report', query_string=query)
    assert response.status_code == 200
    assert response.data == (archive / ('report.' + fmt)).read_bytes()
    assert response.mimetype == mime
    assert response.headers['Content-Disposition'].startswith(disposition)
    assert 'allsky-night-report_ccd1_20261114.' + fmt in response.headers['Content-Disposition']
    assert response.cache_control.private
    assert response.headers['X-Content-Type-Options'] == 'nosniff'


@pytest.mark.parametrize('query,fmt', [({}, 'png'), ({'camera_id': 1, 'format': 'csv'}, 'csv')])
def test_latest_redirect_downloads_report(reports, query, fmt):
    client, _, _, archive = reports
    response = client.get('/latestnightreport', query_string=query, follow_redirects=True)
    redirect, = response.history
    assert redirect.status_code == 302 and redirect.cache_control.no_store
    assert response.status_code == 200 and response.data == (archive / ('report.' + fmt)).read_bytes()


def test_latest_skips_unfinished_nights_and_other_cameras(reports, monkeypatch):
    client, _, entry, _ = reports
    other = Camera(id=2, name='other', uuid='other', local=True)
    db.session.add_all([
        Keogram(id=2, camera=entry.camera, filename='next.jpg', dayDate=date(2026, 11, 15), night=True, success=True),
        Keogram(id=3, camera=other, filename='other.jpg', dayDate=date(2026, 11, 16), night=True, success=True),
    ])
    db.session.commit()
    ready = {1, 3}
    monkeypatch.setattr(night_report_service, 'report_ready', lambda entry: entry.id in ready)
    def latest(camera_id):
        return client.get('/latestnightreport', query_string={'camera_id': camera_id}, follow_redirects=True)
    assert latest(1).request.args['keogram_id'] == '1'
    assert latest(2).request.args['keogram_id'] == '3'
    ready.add(2)
    assert latest(1).request.args['keogram_id'] == '2'
    ready.clear()
    assert latest(1).status_code == 404


@pytest.mark.parametrize('query', [{'camera_id': 'x'}, {'camera_id': -1}, {'camera_id': 2 ** 63}, {'format': 'html'}])
def test_latest_rejects_invalid_parameters(reports, query):
    client, _, _, _ = reports
    assert client.get('/latestnightreport', query_string=query).status_code == 400


def test_latest_without_a_camera(reports):
    client, _, entry, _ = reports
    assert client.get('/latestnightreport?camera_id=99').status_code == 404
    entry.camera.hidden = True
    db.session.commit()
    assert client.get('/latestnightreport').status_code == 404


@pytest.mark.parametrize('query', [
    {}, {'keogram_id': 'x'}, {'keogram_id': 0}, {'keogram_id': -1},
    {'keogram_id': 2 ** 64}, {'keogram_id': 1, 'format': '../../etc/passwd'},
])
def test_bad_parameters_do_not_reach_files(reports, query):
    client, _, _, _ = reports
    assert client.get('/night_report', query_string=query).status_code == 400


@pytest.mark.parametrize('field,value', [('night', False), ('success', False),
                                        ('camera.hidden', True), ('camera.local', False)])
def test_ineligible_keograms_are_not_exposed(reports, field, value):
    client, _, entry, _ = reports
    target, name = (entry.camera, field.split('.')[1]) if '.' in field else (entry, field)
    setattr(target, name, value)
    db.session.commit()
    assert client.get('/night_report?keogram_id=1').status_code == 404
    assert client.get('/latestnightreport?camera_id=1').status_code == 404


def test_missing_or_unfinished_reports_return_404(reports):
    client, app, _, archive = reports
    assert client.get('/night_report?keogram_id=2').status_code == 404
    app.config['READY'] = False
    assert client.get('/night_report?keogram_id=1&format=png').status_code == 404
    app.config['READY'] = True
    (archive / 'report.png').unlink()
    assert client.get('/night_report?keogram_id=1&format=png').status_code == 404


@pytest.mark.parametrize('allow_admin,trusted,expected', [
    (False, False, 404), (False, True, 404), (True, False, 404), (True, True, 200),
])
def test_remote_only_policy_honours_both_admin_conditions(reports, allow_admin, trusted, expected):
    client, app, entry, _ = reports
    entry.camera.web_nonlocal_images = True
    entry.camera.web_local_images_admin = allow_admin
    # A remote keogram URL cannot grant access to the local report sidecar.
    entry.remote_url = 'https://example.com/keogram.jpg'
    db.session.commit()
    app.config['TRUSTED'] = trusted
    assert client.get('/night_report?keogram_id=1').status_code == expected
    assert client.get('/latestnightreport?camera_id=1', follow_redirects=True).status_code == expected


def test_policy_is_taken_from_the_report_camera(reports):
    client, _, entry, _ = reports
    other = Camera(id=2, name='restricted', uuid='restricted', local=True,
                   web_nonlocal_images=True, web_local_images_admin=False)
    db.session.add(other)
    entry.camera = other
    db.session.commit()
    with client.session_transaction() as session:
        session['camera_id'] = 1
    assert client.get('/night_report?keogram_id=1&camera_id=1').status_code == 404


@pytest.mark.parametrize('setting', ['INDI_ALLSKY_AUTH_ALL_VIEWS', 'INDI_ALLSKY_AUTH_MEDIA_VIEWS'])
def test_report_requires_media_login_when_configured(reports, setting):
    client, app, _, _ = reports
    app.config[setting] = True
    assert client.get('/night_report?keogram_id=1').status_code == 401
    assert client.get('/latestnightreport').status_code == 401


def test_sidecar_symlink_cannot_escape_archive(reports):
    client, _, _, archive = reports
    private = archive.parent / 'private.csv'
    private.write_text('not a report')
    (archive / 'report.csv').unlink()
    (archive / 'report.csv').symlink_to(private)
    response = client.get('/night_report?keogram_id=1&format=csv')
    assert response.status_code == 404
    assert b'not a report' not in response.data
    assert client.get('/latestnightreport?format=csv').status_code == 404


def test_absolute_keogram_outside_archive_cannot_expose_sidecars(reports):
    client, _, entry, archive = reports
    entry.filename = str(archive.parent / 'private.jpg')
    db.session.commit()
    assert client.get('/night_report?keogram_id=1').status_code == 404
    assert client.get('/latestnightreport').status_code == 404


def test_archive_links_follow_readiness_and_media_visibility(reports):
    _, app, entry, _ = reports
    with app.test_request_context():
        links = night_report_urls(entry, local=True)
        assert set(links) == {'view', 'image', 'png', 'csv'}
        assert 'format=' not in links['view']
        assert 'download=1' in links['png'] and 'format=csv' in links['csv']
        assert night_report_urls(entry, local=False) == {}
        entry.camera.hidden = True
        assert night_report_urls(entry, local=True) == {}
        entry.camera.hidden = False
        app.config['READY'] = False
        assert set(night_report_urls(entry, local=True)) == {'view'}


def csrf(client):
    response = client.get('/night_report?keogram_id=1')
    assert response.status_code == 200
    return re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)


def test_report_page_shows_available_curves_and_all_measurements_csv_hint(reports):
    client, _, _, _ = reports
    response = client.get('/night_report?keogram_id=1')
    assert response.status_code == 200 and response.mimetype == 'text/html'
    assert 'Sky Temperature' in response.text and 'Sky Brightness' in response.text
    assert 'CSV includes all recorded measurements' in response.text
    assert 'Save and regenerate' not in response.text


def test_admin_can_save_selection_and_double_submit_queues_once(reports):
    client, app, _, _ = reports
    app.config.update(TRUSTED=True, INDI_ALLSKY_AUTH_MEDIA_VIEWS=True)
    admin = User(username='admin', email='admin@example.test', password='unused', admin=True)
    db.session.add(admin)
    db.session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(admin.id)
    token = csrf(client)
    for _ in range(2):
        response = client.post('/night_report?keogram_id=1', data={'csrf_token': token, 'metrics': ['sky_temperature']})
        assert response.status_code == 303
    assert night_report_service.report_options(1) == ['sky_temperature']
    tasks = Task.query.all()
    assert len(tasks) == 1 and tasks[0].state == TaskQueueState.MANUAL
    assert tasks[0].data == {'action': 'generateNightReport', 'kwargs': {'camera_id': 1, 'keogram_id': 1}}
    page = client.get(response.location).text
    assert 'Report queued for generation' in page
    assert 'previous report remains available' in page


def test_empty_selection_requests_keogram_only(reports):
    client, app, _, _ = reports
    app.config.update(LOGIN_DISABLED=True, TRUSTED=True)
    response = client.post('/night_report?keogram_id=1', data={'csrf_token': csrf(client)})
    assert response.status_code == 303
    assert night_report_service.report_options(1) == []


def test_save_during_running_render_queues_one_followup(reports):
    client, app, _, _ = reports
    app.config.update(LOGIN_DISABLED=True, TRUSTED=True)
    token = csrf(client)
    client.post('/night_report?keogram_id=1', data={'csrf_token': token, 'metrics': 'lux'})
    task = Task.query.one()
    task.state = TaskQueueState.RUNNING
    db.session.commit()
    for _ in range(2):
        response = client.post('/night_report?keogram_id=1', data={'csrf_token': token, 'metrics': 'sky_temperature'})
        assert response.status_code == 303
    assert Task.query.filter_by(state=TaskQueueState.MANUAL).count() == 1
    assert Task.query.count() == 2


def test_save_rejects_unavailable_measurement_without_changing_preferences(reports):
    client, app, _, _ = reports
    app.config.update(LOGIN_DISABLED=True, TRUSTED=True)
    response = client.post('/night_report?keogram_id=1', data={'csrf_token': csrf(client), 'metrics': 'arbitrary/path'})
    assert response.status_code == 400
    assert Task.query.count() == 0 and night_report_service.report_options(1) is None


def test_save_requires_csrf_and_admin_network(reports):
    client, app, _, _ = reports
    app.config.update(LOGIN_DISABLED=True, TRUSTED=True)
    assert client.post('/night_report?keogram_id=1', data={'metrics': 'lux'}).status_code == 400
    token = csrf(client)
    app.config['TRUSTED'] = False
    assert client.post('/night_report?keogram_id=1', data={'csrf_token': token, 'metrics': 'lux'}).status_code == 403
    app.config.update(TRUSTED=True, LOGIN_DISABLED=False)
    assert client.post('/night_report?keogram_id=1', data={'csrf_token': token, 'metrics': 'lux'}).status_code == 403
    assert Task.query.count() == 0
