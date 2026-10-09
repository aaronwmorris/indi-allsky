"""Exercise the actual main-service task methods with isolated infrastructure."""
import ast
from datetime import datetime, timedelta
import logging
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import or_


def main_service(env):
    source = Path(__file__).resolve().parents[2] / 'indi_allsky/allsky.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'IndiAllSky')
    methods = {'_queueManualTasks', '_flushOldTasks', '_startSyncWorker', '_stopSyncWorker', '_expireOrphanedTasks', '_scheduleSync'}
    cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in methods]
    namespace = dict(__name__='indi_allsky.allsky', __package__='indi_allsky', db=env.db, app=env.app,
                     datetime=datetime, timedelta=timedelta, or_=or_, logger=logging.getLogger('indi_allsky'),
                     TaskQueueState=env.models.TaskQueueState, TaskQueueQueue=env.models.TaskQueueQueue,
                     IndiAllSkyDbTaskQueueTable=env.models.IndiAllSkyDbTaskQueueTable)
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(source), 'exec'), namespace)
    main = namespace['IndiAllSky']()
    main.sync_worker = main.sync_task_id = None
    main.sync_scheduler = None
    main.config = env.config
    main._config_obj = SimpleNamespace(config_id=1)
    return main


def test_only_one_racing_request_is_admitted(sync_env):
    env = sync_env
    main = main_service(env)
    first = env.sync.request_sync(env.config, ['image'])
    second = env.models.IndiAllSkyDbTaskQueueTable(queue=first.queue, state=first.state, data=dict(first.data))
    env.db.session.add(second)
    env.db.session.commit()
    main._queueManualTasks()
    assert main.sync_task_id in (first.id, second.id)
    states = {env.db.session.get(env.models.IndiAllSkyDbTaskQueueTable, task_id).state for task_id in (first.id, second.id)}
    assert states == {env.models.TaskQueueState.QUEUED, env.models.TaskQueueState.EXPIRED}


def test_active_run_survives_cleanup_but_reboot_expires_it(sync_env):
    env = sync_env
    main = main_service(env)
    task = env.sync.request_sync(env.config, ['image'])
    task.createDate = datetime.now() - timedelta(days=5)
    task.setRunning()
    main.sync_worker = SimpleNamespace(task_id=task.id, is_alive=lambda: True)
    main._flushOldTasks()
    assert env.db.session.get(env.models.IndiAllSkyDbTaskQueueTable, task.id) is not None
    main._expireOrphanedTasks()
    assert task.state == env.models.TaskQueueState.EXPIRED


def test_dead_worker_reports_failure_without_restart(sync_env):
    env = sync_env
    main = main_service(env)
    task = env.sync.request_sync(env.config, ['image'])
    task.setRunning()
    main.sync_worker = SimpleNamespace(task_id=task.id, is_alive=lambda: False)
    env.sync.set_state(env.sync.STATUS_KEY, {'reason': 'connection'})
    main._startSyncWorker()
    env.db.session.refresh(task)
    assert task.state == env.models.TaskQueueState.FAILED
    assert env.sync.status()['state'] == 'failed'
    assert env.sync.status()['reason'] == 'unexpected'
    assert main.sync_worker is None
    assert env.calls == []


def test_main_service_admits_scheduled_task_through_existing_queue(sync_env, monkeypatch):
    import importlib
    env = sync_env
    schedule = importlib.import_module('indi_allsky.syncapi_schedule')
    main = main_service(env)
    env.asset()
    main._config_obj.config_id = env.save_schedule(dict(enabled=True, interval=1, delay=0, upload_limit=0, types=['image']))
    clock = SimpleNamespace(now=0)
    monkeypatch.setattr(schedule, 'time', SimpleNamespace(monotonic=lambda: clock.now))
    monkeypatch.setattr(schedule, 'ReceiverProbe', lambda *args: SimpleNamespace(
        start=lambda: None, is_alive=lambda: False, result=('ready', 'Ready')))
    main._scheduleSync()
    clock.now = 60
    main._scheduleSync()
    main._scheduleSync()
    task = env.sync.active_task()
    main._queueManualTasks()
    assert main.sync_task_id == task.id and task.state == env.models.TaskQueueState.QUEUED
    starts = []
    monkeypatch.setattr(env.sync, 'SyncApiSyncWorker', lambda app, task_id: SimpleNamespace(
        start=lambda: starts.append(task_id), is_alive=lambda: True))
    main._startSyncWorker()
    main._scheduleSync()
    main._startSyncWorker()
    assert starts == [task.id] and env.calls == []
