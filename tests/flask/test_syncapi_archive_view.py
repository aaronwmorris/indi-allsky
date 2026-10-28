import ast
from pathlib import Path

import flask
from flask.views import View
from flask_login import LoginManager, login_required, current_user
from flask_wtf.csrf import CSRFProtect, generate_csrf
from sqlalchemy.orm.exc import NoResultFound
import pytest


@pytest.fixture
def sync_endpoint(sync_env):
    env = sync_env
    class BaseView(View):
        def __init__(self):
            self.indi_allsky_config = env.config
            self.indi_allsky_config_id = env.models.IndiAllSkyDbConfigTable.query.order_by(env.models.IndiAllSkyDbConfigTable.createDate.desc()).first().id
            self._miscDb = type('State', (), {'getState': lambda _, key: str(env.sync.get_state(key))})()

    source = Path(__file__).resolve().parents[2] / 'indi_allsky/flask/views.py'
    node = next(item for item in ast.parse(source.read_text(encoding='utf-8')).body
                if isinstance(item, ast.ClassDef) and item.name == 'AjaxSyncApiRunView')
    namespace = dict(__name__='indi_allsky.flask.views', __package__='indi_allsky.flask', BaseView=BaseView,
                     login_required=login_required, current_user=current_user, app=flask.current_app,
                     request=flask.request, jsonify=flask.jsonify, NoResultFound=NoResultFound)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)
    env.app.add_url_rule('/ajax/syncapi/run', view_func=namespace['AjaxSyncApiRunView'].as_view('sync_run'))
    env.app.add_url_rule('/token', view_func=lambda: flask.jsonify(token=generate_csrf()))
    login = LoginManager(env.app)
    login.user_loader(lambda user_id: env.db.session.get(env.models.IndiAllSkyDbUserTable, int(user_id)))
    CSRFProtect(env.app)
    user = env.models.IndiAllSkyDbUserTable(username='admin', password='test', email='admin@example.invalid', admin=True)
    env.db.session.add(user)
    env.db.session.commit()
    client = env.app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True
    token = client.get('/token').get_json()['token']
    return env, client, user, {'X-CSRFToken': token}


def test_start_returns_job_without_network(sync_endpoint):
    env, client, _, headers = sync_endpoint
    response = client.post('/ajax/syncapi/run', json={'action': 'start', 'types': ['image']}, headers=headers)
    assert response.status_code == 200
    assert response.get_json()['state'] == 'queued'
    assert env.calls == []
    again = client.post('/ajax/syncapi/run', json={'action': 'start', 'types': ['video']}, headers=headers)
    assert again.get_json()['task_id'] == response.get_json()['task_id']
    result = client.post('/ajax/syncapi/run', json={'action': 'cancel', 'task_id': response.get_json()['task_id']}, headers=headers)
    assert result.get_json()['cancel_requested']


def test_requires_csrf_and_admin(sync_endpoint):
    env, client, user, headers = sync_endpoint
    assert client.post('/ajax/syncapi/run', json={'action': 'start'}).status_code == 400
    user.admin = False
    env.db.session.commit()
    assert client.get('/ajax/syncapi/run').status_code == 403
    assert client.post('/ajax/syncapi/run', json={'action': 'start'}, headers=headers).status_code == 403
    assert env.sync.active_task() is None


def test_start_uses_unsaved_speed_without_changing_saved_settings(sync_endpoint):
    from indi_allsky.syncapi_schedule import settings
    env, client, _, headers = sync_endpoint
    response = client.post('/ajax/syncapi/run', json={'action': 'start', 'types': ['image'], 'upload_limit': 256}, headers=headers)
    assert response.status_code == 200
    assert env.sync.active_task().data['upload_limit'] == 256
    assert settings()['upload_limit'] == 0 and env.calls == []


@pytest.mark.parametrize('payload', [[], None, {'action': 'start', 'types': []}, {'action': 'start', 'types': ['invalid']}, {'action': 'cancel', 'task_id': True},
    {'action': 'start', 'upload_limit': -1}, {'action': 'start', 'upload_limit': True}, {'action': 'schedule'}])
def test_rejects_invalid_requests(sync_endpoint, payload):
    env, client, _, headers = sync_endpoint
    response = client.post('/ajax/syncapi/run', data=flask.json.dumps(payload), content_type='application/json', headers=headers)
    assert response.status_code == 400
    assert env.sync.active_task() is None and env.calls == []


def test_waits_for_configuration_reload(sync_endpoint):
    env, client, _, headers = sync_endpoint
    env.sync.set_state('CONFIG_ID', 0)
    response = client.post('/ajax/syncapi/run', json={'action': 'start'}, headers=headers)
    assert response.status_code == 400
    assert 'reload' in response.get_json()['error']
    assert env.calls == []


@pytest.mark.parametrize('scheduled', [False, True])
def test_cancellation_only_pauses_runs_started_by_the_schedule(sync_endpoint, scheduled):
    env, client, _, headers = sync_endpoint
    env.save_schedule(dict(enabled=True, interval=5, delay=2, upload_limit=0, types=['image', 'rawimage']))
    response = client.get('/ajax/syncapi/run')
    saved = response.get_json()['schedule']['settings']
    assert saved['enabled'] and saved['interval'] == 5 and saved['delay'] == 2
    assert saved['types'] == ['image', 'rawimage']
    assert env.calls == [] and env.sync.active_task() is None
    assert client.get('/ajax/syncapi/run').get_json()['schedule']['settings'] == saved
    if scheduled:
        task_id = env.sync.request_sync(env.config, ['image'], schedule_revision=saved['revision']).id
    else:
        response = client.post('/ajax/syncapi/run', json={'action': 'start', 'types': ['image']}, headers=headers)
        task_id = response.get_json()['task_id']
    assert client.get('/ajax/syncapi/run').get_json()['scheduled'] is scheduled
    # An outdated Cancel must not pause the schedule or cancel a newer run.
    response = client.post('/ajax/syncapi/run', json={'action': 'cancel', 'task_id': task_id - 1}, headers=headers)
    assert response.get_json()['schedule']['settings']['enabled']
    response = client.post('/ajax/syncapi/run', json={'action': 'cancel', 'task_id': task_id, 'scheduled': not scheduled}, headers=headers)
    result = response.get_json()
    assert result['cancel_requested']
    assert result['schedule']['settings']['enabled'] is not scheduled
    if scheduled:
        assert result['schedule']['state'] == 'paused'
    else:
        assert result['schedule']['settings'] == saved
    assert env.calls == []
