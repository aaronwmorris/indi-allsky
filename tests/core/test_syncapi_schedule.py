"""Availability scheduling against real source/receiver databases, with a fake clock."""

from copy import deepcopy
from datetime import timedelta
import importlib
import logging
from types import SimpleNamespace

import pytest


@pytest.fixture
def schedule_env(sync_env, monkeypatch):
    env = sync_env
    module = importlib.import_module('indi_allsky.syncapi_schedule')
    clock = SimpleNamespace(now=0)
    monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: clock.now))
    probes = []

    class Probe:
        def __init__(self, *args):
            self.result = None
            self.alive = True
            probes.append(self)

        def start(self):
            pass

        def is_alive(self):
            return self.alive

        def finish(self, outcome='ready'):
            self.result = outcome, 'Test receiver ' + outcome
            self.alive = False

    monkeypatch.setattr(module, 'ReceiverProbe', Probe)
    scheduler = module.SyncApiScheduler()

    def tick(seconds=0, config_id=None, busy=False):
        clock.now += seconds
        if config_id is None:
            config_id = env.sync.get_state('CONFIG_ID')
        scheduler.tick(env.config, config_id, busy=busy)
        return module.status()

    def enable(delay=3, types=None):
        env.save_schedule(dict(enabled=True, interval=10, delay=delay, upload_limit=0, types=types or ['image']))
        tick()

    def queue_run():
        tick(600)
        probes[-1].finish()
        tick()
        delay = module.settings()['delay']
        if delay:
            tick(delay * 60)
            probes[-1].finish()
            tick()
        return env.sync.active_task()

    return SimpleNamespace(env=env, module=module, scheduler=scheduler, clock=clock,
                           probes=probes, tick=tick, enable=enable, queue_run=queue_run)


def test_disabled_and_empty_schedules_do_not_probe_or_create_tasks(schedule_env):
    ctx = schedule_env
    ctx.tick(10000)
    assert ctx.probes == []
    ctx.enable()
    for _ in range(5):
        ctx.tick(600)
    assert ctx.probes == [] and ctx.env.sync.active_task() is None
    assert 'No eligible files' in ctx.module.status()['message']


def test_offline_checks_are_quiet_and_restart_the_interval(schedule_env, caplog):
    ctx = schedule_env
    ctx.env.asset()
    ctx.enable()
    with caplog.at_level(logging.WARNING, logger='indi_allsky'):
        for n in range(1, 5):
            ctx.tick(599)
            assert len(ctx.probes) == n - 1
            ctx.tick(1)
            ctx.probes[-1].finish('offline')
            assert ctx.tick()['state'] == 'waiting'
    assert ctx.env.sync.active_task() is None and ctx.env.calls == []
    assert not caplog.records


def test_wait_recheck_run_and_repeat_with_incremental_checkpoints(schedule_env):
    ctx = schedule_env
    image = ctx.env.asset()
    ctx.env.save_schedule(dict(enabled=True, interval=10, delay=3, upload_limit=256, types=['image']))
    ctx.tick()
    ctx.tick(600)
    ctx.probes[-1].finish()
    assert ctx.tick()['state'] == 'settling'
    ctx.tick(179)
    assert len(ctx.probes) == 1 and ctx.env.sync.active_task() is None
    ctx.tick(1)
    ctx.probes[-1].finish()
    ctx.tick()
    task = ctx.env.sync.active_task()
    assert task.data['types'] == ['image']
    assert task.data['upload_limit'] == 256
    assert task.data['schedule_revision'] == ctx.module.settings()['revision']
    ctx.env.sync.SyncApiSyncWorker(ctx.env.app, task.id).execute()
    assert image.sync_id
    assert ctx.tick()['state'] == 'waiting'
    ctx.tick(600)
    assert len(ctx.probes) == 2  # Already caught up: no empty run or camera update.
    next_image = ctx.env.asset()
    task = ctx.queue_run()
    ctx.env.sync.SyncApiSyncWorker(ctx.env.app, task.id).execute()
    assert ctx.env.sync.status()['completed'] == 1 and next_image.sync_id


def test_config_defaults_ignore_old_state_preferences(schedule_env):
    ctx = schedule_env
    ctx.env.sync.set_state('SYNCAPI_SCHEDULE_SETTINGS', dict(enabled=True, interval=1, delay=0,
                           upload_limit=512, types=['rawimage'], revision='old'))
    defaults = ctx.module.settings()
    assert not defaults['enabled'] and defaults['interval'] == 10 and defaults['delay'] == 0
    assert defaults['upload_limit'] == 0 and defaults['types'] == ctx.env.sync.DEFAULT_TYPES
    ctx.env.save_schedule(dict(enabled=False, interval=5, delay=3, upload_limit=512, types=['image']))
    assert ctx.module.settings()['upload_limit'] == 512
    task = ctx.env.sync.request_sync(ctx.env.config, ['image'])
    assert task.data['upload_limit'] == 512


def test_default_delay_starts_run_after_first_successful_check(schedule_env):
    ctx = schedule_env
    ctx.env.asset()
    # Omit timing overrides: exercise the defaults used by a newly enabled schedule.
    options = ctx.module.configured_settings({'SYNCAPI': {'ARCHIVE_SCHEDULE': True}})
    ctx.env.save_schedule(options)
    assert options['delay'] == 0
    ctx.tick()
    ctx.tick(600)
    ctx.probes[-1].finish()
    ctx.tick()
    task = ctx.env.sync.active_task()
    assert task is not None and task.data['action'] == 'archive_sync'
    assert len(ctx.probes) == 1
    assert task.data['schedule_revision'] == ctx.module.settings()['revision']


def test_receiver_disappearing_during_startup_delay_restarts_cycle(schedule_env):
    ctx = schedule_env
    ctx.env.asset()
    ctx.enable()
    ctx.tick(600)
    ctx.probes[-1].finish()
    ctx.tick()
    ctx.tick(180)
    ctx.probes[-1].finish('offline')
    assert ctx.tick()['state'] == 'waiting'
    assert ctx.env.sync.active_task() is None
    ctx.tick(599)
    assert len(ctx.probes) == 2
    ctx.tick(1)
    assert len(ctx.probes) == 3


@pytest.mark.parametrize('failure', ['connection', 'http'])
def test_connection_failure_rearms_but_authentication_failure_pauses(schedule_env, monkeypatch, failure):
    ctx = schedule_env
    ctx.env.asset()
    ctx.enable(delay=0)
    task = ctx.queue_run()
    monkeypatch.setattr(ctx.env.sync.SyncApiSyncWorker, 'retry_delays', ())
    def unavailable(*args, **kwargs):
        if failure == 'http':
            return SimpleNamespace(status_code=503)
        raise ctx.env.transport.requests.exceptions.ConnectionError('offline')
    monkeypatch.setattr(ctx.env.transport.requests, 'put', unavailable)
    ctx.env.sync.SyncApiSyncWorker(ctx.env.app, task.id).execute()
    assert ctx.env.sync.status()['reason'] == 'connection'
    assert ctx.tick()['settings']['enabled']
    task = ctx.queue_run()
    monkeypatch.setattr(ctx.env.transport.requests, 'put', lambda *a, **k: SimpleNamespace(
        status_code=400, json=lambda: {'error': 'authentication failed'}))
    ctx.env.sync.SyncApiSyncWorker(ctx.env.app, task.id).execute()
    result = ctx.tick()
    assert result['state'] == 'paused' and not result['settings']['enabled']
    restarted = ctx.module.SyncApiScheduler()
    restarted.tick(ctx.env.config, ctx.env.sync.get_state('CONFIG_ID'))
    assert ctx.module.status()['state'] == 'paused'


def test_manual_run_preempts_probe_and_prevents_overlap(schedule_env):
    ctx = schedule_env
    ctx.env.asset()
    ctx.enable(delay=0)
    ctx.tick(600)
    task = ctx.env.sync.request_sync(ctx.env.config, ['image'])
    ctx.tick()
    ctx.probes[-1].finish()
    ctx.tick(600)
    assert len(ctx.probes) == 1 and ctx.env.sync.active_task().id == task.id
    ctx.env.sync.SyncApiSyncWorker(ctx.env.app, task.id).execute()
    ctx.tick()
    assert ctx.env.sync.active_task() is None
    ctx.tick(600)
    assert len(ctx.probes) == 1


def test_changed_settings_discard_inflight_probe_and_cancel_stale_job(schedule_env):
    ctx = schedule_env
    ctx.env.asset()
    ctx.enable(delay=0)
    ctx.tick(600)
    old_revision = ctx.module.settings()['revision']
    ctx.env.save_schedule(dict(enabled=True, interval=5, delay=1, upload_limit=0, types=['video']))
    ctx.tick()
    ctx.probes[-1].finish()
    ctx.tick()
    assert ctx.env.sync.active_task() is None
    # Exercise the other side of the race: a job admitted just after Save/Cancel.
    task = ctx.env.sync.request_sync(ctx.env.config, ['image'], schedule_revision=old_revision)
    ctx.env.sync.SyncApiSyncWorker(ctx.env.app, task.id).execute()
    assert ctx.env.sync.status()['state'] == 'cancelled' and ctx.env.calls == []


def test_schedule_survives_restart_but_waits_for_applied_config(schedule_env):
    ctx = schedule_env
    ctx.env.asset()
    ctx.enable()
    new = ctx.env.models.IndiAllSkyDbConfigTable(level='test', note='new', data=deepcopy(ctx.env.config))
    ctx.env.db.session.add(new)
    ctx.env.db.session.commit()
    result = ctx.tick(600)
    assert result['state'] == 'applying'
    assert 'Waiting for indi-allsky to apply the configuration' in result['message']
    assert 'next_action' not in result
    assert not ctx.probes
    result = ctx.tick(config_id=new.id)
    assert result['state'] == 'waiting' and 'next_action' in result
    ctx.tick(599, config_id=new.id)
    assert not ctx.probes
    ctx.tick(1, config_id=new.id)
    assert len(ctx.probes) == 1
    restarted = ctx.module.SyncApiScheduler()
    restarted.tick(ctx.env.config, new.id)
    assert ctx.module.settings()['enabled'] and ctx.module.status()['state'] == 'waiting'


def test_reenabled_schedule_reports_applying_before_and_after_service_tick(schedule_env):
    ctx = schedule_env
    ctx.enable()
    ctx.module.pause('Paused by Cancel.')
    ctx.tick()
    config_id = ctx.env.save_schedule(dict(enabled=True, interval=5, delay=3, upload_limit=0, types=['image']), apply=False)
    result = ctx.module.status()
    assert result['state'] == 'applying'
    assert 'Waiting for indi-allsky to apply the configuration' in result['message']
    assert 'next_action' not in result
    assert ctx.tick()['message'] == result['message']
    assert ctx.tick(config_id=config_id)['state'] == 'waiting'
    assert ctx.probes == [] and ctx.env.sync.active_task() is None


def test_applied_automatic_mode_still_explains_why_schedule_cannot_run(schedule_env):
    ctx = schedule_env
    ctx.env.config['SYNCAPI']['MODE'] = 'automatic'
    ctx.enable()
    result = ctx.module.status()
    assert result['state'] == 'disabled'
    assert result['message'] == 'Save and apply Archive sync mode to use the schedule.'
    assert ctx.probes == []


def test_stuck_probe_does_not_accumulate_threads(schedule_env):
    ctx = schedule_env
    ctx.env.asset()
    ctx.enable()
    for _ in range(20):
        ctx.tick(600)
    assert len(ctx.probes) == 1 and ctx.env.sync.active_task() is None


def test_configuration_selection_matches_service_after_clock_adjustment(schedule_env):
    ctx = schedule_env
    ctx.env.asset()
    ctx.enable()
    current = ctx.env.db.session.get(ctx.env.models.IndiAllSkyDbConfigTable, ctx.env.sync.get_state('CONFIG_ID'))
    # The service chooses by timestamp, which need not match insertion order
    # after a clock correction. Its applied configuration must remain usable.
    ctx.env.db.session.add(ctx.env.models.IndiAllSkyDbConfigTable(
        level='test', note='older timestamp', data=deepcopy(ctx.env.config),
        createDate=current.createDate - timedelta(days=1)))
    ctx.env.db.session.commit()
    ctx.tick(600, config_id=current.id)
    assert len(ctx.probes) == 1


def test_probe_error_is_reported_once_and_pauses(schedule_env, caplog):
    ctx = schedule_env
    ctx.env.asset()
    ctx.enable()
    ctx.tick(600)
    ctx.probes[-1].finish('blocked')
    with caplog.at_level(logging.WARNING, logger='indi_allsky'):
        ctx.tick()
        for _ in range(5):
            ctx.tick(600)
    assert len(caplog.records) == 1 and len(ctx.probes) == 1
    assert ctx.module.status()['state'] == 'paused'


def test_authenticated_probe_is_read_only(sync_env):
    env = sync_env
    module = importlib.import_module('indi_allsky.syncapi_schedule')
    env.asset()
    env.run()
    env.calls.clear()
    assert module.probe_receiver(env.config, env.camera.sync_id, env.camera.uuid)[0] == 'ready'
    assert len(env.calls) == 1 and env.calls[0][0] == 'POST'
    assert env.calls[0][2]['id'] == env.camera.sync_id
    bad_key = deepcopy(env.config)
    bad_key['SYNCAPI']['APIKEY'] = 'wrong-key'
    assert module.probe_receiver(bad_key, env.camera.sync_id, env.camera.uuid)[0] == 'blocked'
    # A brand-new sender can register its camera during its first real run.
    assert module.probe_receiver(env.config, None, env.camera.uuid)[0] == 'ready'
    assert all(call[0] == 'POST' for call in env.calls)


@pytest.mark.parametrize('code,body,outcome', [
    (200, {'id': 7}, 'ready'), (400, {'error': 'camera_missing'}, 'ready'),
    (400, {'error': 'authentication failed'}, 'blocked'), (401, {}, 'blocked'),
    (403, {}, 'blocked'), (404, {}, 'blocked'), (302, {}, 'blocked'),
    (200, {'id': True}, 'blocked'), (200, {'html': 'login'}, 'blocked'),
    (429, {}, 'offline'), (500, {}, 'offline'), (502, {}, 'offline'),
    (503, {}, 'offline'), (504, {}, 'offline'),
])
def test_probe_response_classification(sync_env, monkeypatch, code, body, outcome):
    env = sync_env
    module = importlib.import_module('indi_allsky.syncapi_schedule')
    monkeypatch.setattr(env.transport.requests, 'post', lambda *a, **k: SimpleNamespace(status_code=code, json=lambda: body))
    assert module.probe_receiver(env.config, 1, env.camera.uuid)[0] == outcome


def test_probe_uses_existing_certificate_setting_and_short_timeouts(sync_env, monkeypatch):
    env = sync_env
    module = importlib.import_module('indi_allsky.syncapi_schedule')
    captured = []
    def post(url, **kwargs):
        captured.append((url, kwargs))
        return SimpleNamespace(status_code=200, json=lambda: {'id': 1})
    monkeypatch.setattr(env.transport.requests, 'post', post)
    env.config['SYNCAPI']['CERT_BYPASS'] = True
    assert module.probe_receiver(env.config, 1, env.camera.uuid)[0] == 'ready'
    url, kwargs = captured[0]
    assert url == 'https://nas/indi-allsky/sync/v1/camera/lookup'
    assert kwargs['verify'] is False and kwargs['allow_redirects'] is False
    assert kwargs['timeout'] == (5, 10)
    assert kwargs['headers']['Authorization'].startswith('Bearer tester:')


def test_slow_probe_is_independent_of_flask_and_does_not_mutate_saved_config(sync_env, monkeypatch):
    from threading import Event
    from flask import has_app_context
    module = importlib.import_module('indi_allsky.syncapi_schedule')
    started, release = Event(), Event()
    observed = []
    def probe(config, camera_id, camera_uuid):
        observed.append((has_app_context(), config['SYNCAPI']['APIKEY']))
        started.set()
        release.wait(5)
        return 'ready', 'Ready'
    monkeypatch.setattr(module, 'probe_receiver', probe)
    thread = module.ReceiverProbe(sync_env.config, 1, sync_env.camera.uuid)
    original_key = sync_env.config['SYNCAPI']['APIKEY']
    sync_env.config['SYNCAPI']['APIKEY'] = 'rotated'
    try:
        thread.start()
        assert started.wait(2)
        assert thread.is_alive() and thread.daemon
        assert not sync_env.sync.status()['active']
        assert observed == [(False, original_key)]
    finally:
        release.set()
        thread.join(2)
    assert thread.result == ('ready', 'Ready') and not thread.is_alive()


@pytest.mark.parametrize('field,value', [('enabled', 'true'), ('interval', True), ('interval', 0),
    ('interval', 1441), ('interval', 1.5), ('delay', -1), ('delay', 1441), ('delay', None),
    ('types', []), ('types', ['unknown']), ('types', [1])])
def test_invalid_settings_are_rejected_without_side_effects(sync_env, field, value):
    module = importlib.import_module('indi_allsky.syncapi_schedule')
    payload = dict(enabled=True, interval=10, delay=3, upload_limit=0, types=['image'])
    payload[field] = value
    with pytest.raises(ValueError):
        module.save_settings(sync_env.config, payload)
    assert not module.settings()['enabled'] and sync_env.calls == []
