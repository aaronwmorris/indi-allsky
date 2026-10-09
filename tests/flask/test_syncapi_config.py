"""The configuration save transaction, without unrelated camera form fields."""
import ast
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import importlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace

import flask
from flask.views import View
from flask_login import LoginManager, current_user, login_required
from flask_wtf.csrf import CSRFProtect, generate_csrf
import pytest
from sqlalchemy import select

from indi_allsky.exceptions import ConfigSaveException


@pytest.fixture
def config_endpoint(sync_env):
    env = sync_env
    schedule = importlib.import_module('indi_allsky.syncapi_schedule')
    root = Path(__file__).resolve().parents[2]
    config_source = root / 'indi_allsky/config.py'
    tree = ast.parse(config_source.read_text(encoding='utf-8'))
    config_class = next(node for node in tree.body
                        if isinstance(node, ast.ClassDef) and node.name == 'IndiAllSkyConfig')
    base_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'IndiAllSkyConfigBase')
    defaults = ast.literal_eval(base_class.body[0].value.args[0])
    methods = [node for node in config_class.body if isinstance(node, ast.FunctionDef)
               and node.name in ('_setConfigEntry', '_validateConfig', 'config')]
    config_namespace = dict(__name__='indi_allsky.config', __package__='indi_allsky',
                            db=env.db, datetime=datetime, timezone=timezone, __config_level__='test',
                            OrderedDict=OrderedDict, ConfigSaveException=ConfigSaveException, app=flask.current_app,
                            IndiAllSkyDbConfigTable=env.models.IndiAllSkyDbConfigTable)
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(config_source), 'exec'), config_namespace)
    control = SimpleNamespace(fail_save=False, before_commit=[])
    env.config.update(INDI_SERVER='localhost', CCD_CONFIG={}, INDI_CONFIG_DEFAULTS={})

    class Writer:
        _setConfigEntry = config_namespace['_setConfigEntry']
        _validateConfig = config_namespace['_validateConfig']
        config = config_namespace['config']
        base_config = defaults

        def __init__(self):
            self._config = deepcopy(env.config)

        def save(self, username, note):
            self._validateConfig()
            # A separate reader cannot see either pending change before the
            # actual configuration writer commits its SQLAlchemy session.
            with env.db.engine.connect() as connection:
                previous = connection.execute(select(env.models.IndiAllSkyDbConfigTable.data)
                    .order_by(env.models.IndiAllSkyDbConfigTable.createDate.desc())).scalar()
                control.before_commit.append(previous['SYNCAPI'].get('ARCHIVE_INTERVAL'))
            if control.fail_save:
                env.db.session.flush()
                raise ConfigSaveException('Configuration save failed')
            row = self._setConfigEntry(deepcopy(self.config), SimpleNamespace(id=None), note, False)
            self.config_id = row.id
            env.config.clear()
            env.config.update(deepcopy(self.config))
            return row

    class BaseView(View):
        def __init__(self):
            self._indi_allsky_config_obj = Writer()
            self.indi_allsky_config = self._indi_allsky_config_obj.config
            self._miscDb = SimpleNamespace(setState=lambda key, value: env.sync.set_state(key, value))

    source = root / 'indi_allsky/flask/views.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    view = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'AjaxConfigView')
    method = next(node for node in view.body if isinstance(node, ast.FunctionDef) and node.name == 'dispatch_request')
    start = next(i for i, node in enumerate(method.body) if isinstance(node, ast.ImportFrom) and node.module == 'syncapi')
    # Keep real authentication, form rejection and the entire final save path.
    # Camera-field conversion is outside this feature and needs Pi services.
    method.body = method.body[:4] + ast.parse("config_note = 'test save'\nreload_on_save = False").body + method.body[start:]
    namespace = dict(__name__='indi_allsky.flask.views', __package__='indi_allsky.flask', BaseView=BaseView,
        login_required=login_required, current_user=current_user, app=flask.current_app, request=flask.request,
        jsonify=flask.jsonify, db=env.db, constants=env.sync.constants, ConfigSaveException=ConfigSaveException,
        IndiAllskyConfigForm=lambda data: SimpleNamespace(errors={}, validate=lambda: not data.get('invalid_other_field')),
        IndiAllSkyDbTaskQueueTable=env.models.IndiAllSkyDbTaskQueueTable,
        IndiAllSkyDbConfigTable=env.models.IndiAllSkyDbConfigTable,
        IndiAllskyConfigRestoreForm=lambda data: SimpleNamespace(validate=lambda: True),
        io=io, json=json, OrderedDict=OrderedDict, tempfile=tempfile, Path=Path,
        datetime=datetime, send_file=flask.send_file,
        TaskQueueState=env.models.TaskQueueState, TaskQueueQueue=env.models.TaskQueueQueue)
    views = [view] + [node for node in tree.body if isinstance(node, ast.ClassDef)
                      and node.name in ('ConfigDownloadView', 'AjaxConfigRestoreView')]
    exec(compile(ast.fix_missing_locations(ast.Module(body=views, type_ignores=[])), str(source), 'exec'), namespace)
    env.app.add_url_rule('/ajax/config', view_func=namespace['AjaxConfigView'].as_view('config_save'))
    env.app.add_url_rule('/config/download', view_func=namespace['ConfigDownloadView'].as_view('config_download'))
    env.app.add_url_rule('/ajax/config/restore', view_func=namespace['AjaxConfigRestoreView'].as_view('config_restore'))
    env.app.add_url_rule('/csrf', view_func=lambda: flask.jsonify(token=generate_csrf()))
    login = LoginManager(env.app)
    login.user_loader(lambda user_id: env.db.session.get(env.models.IndiAllSkyDbUserTable, int(user_id)))
    CSRFProtect(env.app)
    user = env.models.IndiAllSkyDbUserTable(username='admin', password='test', email='admin@example.invalid', admin=True)
    env.db.session.add(user)
    env.db.session.commit()
    client = env.app.test_client()
    with client.session_transaction() as session:
        session['_user_id'], session['_fresh'] = str(user.id), True
    headers = {'X-CSRFToken': client.get('/csrf').get_json()['token']}
    return SimpleNamespace(env=env, schedule=schedule, control=control, client=client, headers=headers, user=user,
                           defaults=defaults)


def options():
    return dict(enabled=True, interval=5, delay=0, upload_limit=256, types=['image', 'rawimage'])


def test_config_save_commits_schedule_and_requests_reload(config_endpoint):
    ctx = config_endpoint
    response = ctx.client.post('/ajax/config', json={'SYNCAPI_SCHEDULE': options()}, headers=ctx.headers)
    assert response.status_code == 200
    assert 'Reloading' in response.get_json()['success-message']
    assert ctx.control.before_commit == [None]
    assert all(ctx.schedule.settings()[key] == value for key, value in options().items())
    assert ctx.env.models.IndiAllSkyDbConfigTable.query.count() == 2
    assert ctx.env.models.IndiAllSkyDbTaskQueueTable.query.one().data['action'] == 'reload'
    assert ctx.env.calls == []


def test_failed_config_save_rolls_back_staged_schedule(config_endpoint):
    ctx = config_endpoint
    ctx.env.save_schedule(options())
    ctx.schedule.pause('Paused before saving.')
    saved = ctx.schedule.settings()
    ctx.control.fail_save = True
    response = ctx.client.post('/ajax/config', json={'SYNCAPI_SCHEDULE': options()}, headers=ctx.headers)
    assert response.status_code == 400
    assert ctx.schedule.settings() == saved
    assert ctx.env.models.IndiAllSkyDbConfigTable.query.count() == 2
    assert ctx.env.models.IndiAllSkyDbTaskQueueTable.query.count() == 0


@pytest.mark.parametrize('payload', [None, [], dict(options(), enabled='true'), dict(options(), interval=0),
    dict(options(), delay=None), dict(options(), delay=1.5), dict(options(), types=[]),
    dict(options(), upload_limit=-1), dict(options(), upload_limit=True), dict(options(), upload_limit=123),
    dict(options(), upload_limit='256'), dict(options(), upload_limit=None)])
def test_invalid_schedule_rejects_whole_configuration(config_endpoint, payload):
    ctx = config_endpoint
    response = ctx.client.post('/ajax/config', json={'SYNCAPI_SCHEDULE': payload}, headers=ctx.headers)
    assert response.status_code == 400
    assert 'syncapi-run-schedule-controls' in response.get_json()
    assert ctx.control.before_commit == []
    assert ctx.env.models.IndiAllSkyDbConfigTable.query.count() == 1
    assert not ctx.schedule.settings()['enabled']


def test_unrelated_config_saves_preserve_active_schedule(config_endpoint):
    ctx = config_endpoint
    ctx.env.save_schedule(options())
    saved = ctx.schedule.settings()
    task = ctx.env.sync.request_sync(ctx.env.config, ['image'], schedule_revision=saved['revision'])
    for payload in ({}, {'SYNCAPI_SCHEDULE': options()}):
        response = ctx.client.post('/ajax/config', json=payload, headers=ctx.headers)
        assert response.status_code == 200
        assert 'Reloading' not in response.get_json()['success-message']
        assert ctx.schedule.settings() == saved
        assert ctx.env.sync.active_task().id == task.id
    response = ctx.client.post('/ajax/config', json={'SYNCAPI_SCHEDULE': dict(options(), interval=7)}, headers=ctx.headers)
    assert response.status_code == 400
    assert ctx.schedule.settings() == saved


def test_config_auth_csrf_and_other_validation_precede_schedule_changes(config_endpoint):
    ctx = config_endpoint
    payload = {'SYNCAPI_SCHEDULE': options()}
    assert ctx.client.post('/ajax/config', json=payload).status_code == 400
    assert ctx.client.post('/ajax/config', json=dict(payload, invalid_other_field=True), headers=ctx.headers).status_code == 400
    ctx.user.admin = False
    ctx.env.db.session.commit()
    assert ctx.client.post('/ajax/config', json=payload, headers=ctx.headers).status_code == 400
    assert not ctx.schedule.settings()['enabled']
    assert ctx.env.models.IndiAllSkyDbConfigTable.query.count() == 1


def test_schedule_preference_can_be_saved_with_syncapi_disabled(config_endpoint):
    ctx = config_endpoint
    ctx.env.config['SYNCAPI']['ENABLE'] = False
    response = ctx.client.post('/ajax/config', json={'SYNCAPI_SCHEDULE': options()}, headers=ctx.headers)
    assert response.status_code == 200
    assert ctx.schedule.settings()['enabled']
    assert ctx.env.calls == [] and ctx.env.sync.active_task() is None


def test_schedule_defaults_match_normal_config_template(config_endpoint):
    ctx = config_endpoint
    assert ctx.schedule.configured_settings({}) == ctx.schedule.configured_settings(ctx.defaults)
    assert ctx.defaults['SYNCAPI']['ARCHIVE_DELAY'] == 0


def test_saved_preferences_are_versioned_exported_and_restored(config_endpoint):
    ctx = config_endpoint
    assert ctx.client.post('/ajax/config', json={'SYNCAPI_SCHEDULE': options()}, headers=ctx.headers).status_code == 200
    version = ctx.env.models.IndiAllSkyDbConfigTable.query.order_by(ctx.env.models.IndiAllSkyDbConfigTable.id.desc()).first()
    assert ctx.schedule.configured_settings(version.data) == options()
    # Config exports include preferences, not a run's progress or local pause.
    ctx.schedule.pause('Paused for the test.')
    ctx.env.sync.set_state(ctx.env.sync.STATUS_KEY, dict(completed=42))
    response = ctx.client.get('/config/download', query_string={'id': version.id})
    assert response.status_code == 200
    exported = json.loads(response.data)
    assert ctx.schedule.configured_settings(exported) == options()
    assert 'paused_reason' not in response.get_data(as_text=True)
    assert 'completed' not in exported
    assert ctx.env.db.session.get(ctx.env.models.IndiAllSkyDbStateTable, 'SYNCAPI_SCHEDULE_SETTINGS') is None

    changed = dict(options(), enabled=False, interval=30, delay=8, upload_limit=1024, types=['fitsimage'])
    assert ctx.client.post('/ajax/config', json={'SYNCAPI_SCHEDULE': changed}, headers=ctx.headers).status_code == 200
    assert ctx.schedule.configured_settings(version.data) == options()  # History stays immutable.
    assert ctx.schedule.configured_settings(ctx.env.config) == changed
    response = ctx.client.post('/ajax/config/restore', data={
        'CONFIG_UPLOAD': (io.BytesIO(json.dumps(exported).encode()), 'config.json'),
    }, headers=ctx.headers)
    assert response.status_code == 200
    assert ctx.schedule.configured_settings(ctx.env.config) == options()
    assert all(ctx.schedule.settings()[key] == value for key, value in options().items())


@pytest.mark.parametrize('key,value', [('ARCHIVE_SCHEDULE', 'yes'), ('ARCHIVE_INTERVAL', 0),
    ('ARCHIVE_DELAY', -1), ('ARCHIVE_UPLOAD_LIMIT', 123), ('ARCHIVE_TYPES', ['unknown']),
    (None, None), (None, []), (None, True)])
def test_config_restore_validates_schedule_before_writing(config_endpoint, key, value):
    ctx = config_endpoint
    restored = deepcopy(ctx.env.config)
    if key is None:
        restored['SYNCAPI'] = value
    else:
        restored['SYNCAPI'][key] = value
    response = ctx.client.post('/ajax/config/restore', data={
        'CONFIG_UPLOAD': (io.BytesIO(json.dumps(restored).encode()), 'invalid.json'),
    }, headers=ctx.headers)
    assert response.status_code == 400
    assert 'CONFIG_UPLOAD' in response.get_json()
    assert ctx.env.models.IndiAllSkyDbConfigTable.query.count() == 1


def test_config_save_resumes_identical_paused_preferences(config_endpoint):
    ctx = config_endpoint
    ctx.env.save_schedule(options())
    original = ctx.schedule.settings()
    ctx.schedule.pause('Scheduled run cancelled.')
    assert not ctx.schedule.settings()['enabled']
    # The switch displays effective paused state, while the saved preference
    # remains a config value. Enabling and saving it explicitly clears pause.
    assert ctx.env.config['SYNCAPI']['ARCHIVE_SCHEDULE'] is True
    response = ctx.client.post('/ajax/config', json={'SYNCAPI_SCHEDULE': options()}, headers=ctx.headers)
    assert response.status_code == 200
    resumed = ctx.schedule.settings()
    assert resumed['enabled'] and resumed['revision'] != original['revision']
    assert 'paused_reason' not in resumed
