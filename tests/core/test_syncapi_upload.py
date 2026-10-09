"""Stream archive uploads through the real encoder/receiver with a fake clock."""

from copy import deepcopy
from datetime import datetime, timedelta
import logging
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('options,level', [({}, logging.INFO), ({'quiet': True}, logging.DEBUG)])
def test_archive_logging_is_opt_in_without_changing_live_upload_logs(sync_env, monkeypatch, caplog, options, level):
    env = sync_env
    client = env.transport.requests_syncapi_v1(env.config, **options)
    client.connect(hostname='https://nas/indi-allsky/sync/v1/camera', username='tester', apikey='test-api-key')
    monkeypatch.setattr(env.transport.requests, 'put', lambda *args, **kwargs: SimpleNamespace(
        status_code=200, text='{"id": 1}'))
    with caplog.at_level(logging.DEBUG, logger='indi_allsky'):
        assert client.put(local_file='camera', metadata={}, empty_file=True) == {'id': 1}
    transfer_logs = [record for record in caplog.records
                     if record.getMessage().startswith(('Uploading ', 'File transferred '))]
    assert len(transfer_logs) == 2
    assert all(record.levelno == level for record in transfer_logs)


def upload_worker(env, monkeypatch, limit=256):
    entry = env.asset()
    media = bytes(range(256)) * 8192 + b'\r\n'
    entry.getFilesystemPath().write_bytes(media)
    task = env.sync.request_sync(env.config, ['image'], upload_limit=limit)
    worker = env.sync.SyncApiSyncWorker(env.app, task.id)
    clock = SimpleNamespace(now=1000, waits=[], stopped=False)

    def wait(seconds):
        clock.waits.append(seconds)
        clock.now += seconds

    monkeypatch.setattr(env.sync, 'time', SimpleNamespace(monotonic=lambda: clock.now))
    worker.stop_event = SimpleNamespace(wait=wait, is_set=lambda: clock.stopped)
    return entry, media, worker, clock


@pytest.mark.parametrize('limit', [0, 256, 1024])
def test_upload_paces_wire_bytes_preserves_media_and_reports_progress(sync_env, monkeypatch, limit):
    env = sync_env
    entry, media, worker, clock = upload_worker(env, monkeypatch, limit)
    snapshots, lengths = [], []
    original_send, original_state = env.transport.requests.put, env.sync.set_state

    def send(url, **kwargs):
        if url.endswith('/image'):
            lengths.append(kwargs['data'].len)
        return original_send(url, **kwargs)

    def save(key, value, **kwargs):
        if key == env.sync.STATUS_KEY:
            snapshots.append(deepcopy(value))
        return original_state(key, value, **kwargs)

    monkeypatch.setattr(env.transport.requests, 'put', send)
    monkeypatch.setattr(env.sync, 'set_state', save)
    worker.execute()
    result = env.sync.status()
    assert result['state'] == 'complete', result
    assert result['bytes'] == len(media) and result['files'] == 1
    assert 'upload' not in result
    assert sum(clock.waits) == pytest.approx(lengths[0] / (limit * 1024) if limit else 0)
    if limit == 256:
        progress = [state for state in snapshots if 'upload' in state]
        assert progress and all(0 < state['upload']['bytes'] < len(media) for state in progress)
        assert all(state['bytes'] == 0 and state['files'] == 0 for state in progress)
        assert all(250000 < state['rates']['bytes'] <= 256 * 1024 for state in progress)
        assert all(state['rates']['items'] == state['rates']['files'] == 0 for state in progress)
    assert 'rates' not in result
    with env.nas.app_context():
        remote = env.models.IndiAllSkyDbImageTable.query.one()
        assert remote.getFilesystemPath().read_bytes() == media
    assert entry.sync_id


@pytest.mark.parametrize('cancel', ['database', 'service'])
def test_cancellation_during_pacing_does_not_acknowledge_partial_file(sync_env, monkeypatch, cancel):
    env = sync_env
    entry, _, worker, clock = upload_worker(env, monkeypatch)
    wait = worker.stop_event.wait

    def cancel_while_waiting(seconds):
        wait(seconds)
        if cancel == 'service':
            clock.stopped = True
        elif clock.now >= 1005:
            env.sync.cancel_sync(worker.task_id)

    worker.stop_event.wait = cancel_while_waiting
    worker.execute()
    result = env.sync.status()
    assert result['state'] == 'cancelled', result
    assert result['files'] == result['bytes'] == 0 and entry.sync_id is None
    assert 'upload' not in result
    assert clock.now < 1005.1 if cancel == 'database' else clock.now < 1001
    with env.nas.app_context():
        assert env.models.IndiAllSkyDbImageTable.query.count() == 0


def test_retry_resets_partial_progress_and_only_counts_acknowledged_bytes(sync_env, monkeypatch):
    env = sync_env
    entry, media, worker, clock = upload_worker(env, monkeypatch)
    original = env.transport.requests.put
    uploads = []

    def interrupted(url, **kwargs):
        if url.endswith('/image'):
            uploads.append(deepcopy(worker.progress['upload']))
            if len(uploads) == 1:
                for _ in range(180):
                    kwargs['data'].read(8192)
                assert env.sync.status()['upload']['bytes'] > 0
                assert env.sync.status()['rates']['bytes'] > 0
                raise env.transport.requests.exceptions.ConnectionError('interrupted upload')
        return original(url, **kwargs)

    def retry_wait(delay):
        assert 'upload' not in env.sync.status()
        assert env.sync.status()['bytes'] == 0
        clock.now += delay

    monkeypatch.setattr(env.transport.requests, 'put', interrupted)
    monkeypatch.setattr(worker, 'wait_for_retry', retry_wait)
    worker.execute()
    result = env.sync.status()
    assert result['state'] == 'complete', result
    assert len(uploads) == 2 and all(upload['bytes'] == 0 for upload in uploads)
    assert result['files'] == 1 and result['bytes'] == len(media) and entry.sync_id
    assert worker.transferred_bytes > len(media)  # Retransmission is traffic, not another completed file.


def test_recent_rates_use_elapsed_intervals_and_handle_forced_updates(sync_env, monkeypatch):
    env = sync_env
    _, _, worker, clock = upload_worker(env, monkeypatch)
    worker.progress = dict(task_id=worker.task_id, state='running', completed=0, files=0, bytes=0,
                           upload=dict(bytes=0, total=2000000))
    worker.publish(force=True)
    assert 'rates' not in env.sync.status()
    clock.now += 2
    worker.upload_progress(1000000, 2000000)
    worker.progress.update(completed=3, files=5)
    clock.now += 3
    worker.publish()
    expected = dict(bytes=200000, items=0.6, files=1)
    assert env.sync.status()['rates'] == expected

    clock.now += 0.2
    worker.upload_progress(1100000, 2000000)
    worker.publish(force=True)
    assert env.sync.status()['rates'] == expected  # No spike from an immediate status update.
    clock.now += 4.8
    worker.publish(force=True)
    assert env.sync.status()['rates'] == dict(bytes=20000, items=0, files=0)
    # Lookup recovery can complete items without uploading another file.
    worker.progress['completed'] += 2
    clock.now += 5
    worker.publish()
    assert env.sync.status()['rates'] == dict(bytes=0, items=0.4, files=0)
    clock.now += 5
    worker.publish()
    assert env.sync.status()['rates'] == dict(bytes=0, items=0, files=0)
    worker.progress['state'] = 'cancelled'
    worker.publish(force=True)
    assert 'rates' not in env.sync.status()


def test_status_hides_stale_rates_without_changing_saved_progress(sync_env):
    env = sync_env
    task = env.sync.request_sync(env.config, ['image'])
    saved = dict(task_id=task.id, state='running', updated=(datetime.now() - timedelta(seconds=16)).isoformat(),
                 rates=dict(bytes=250000, items=0.5, files=1), completed=3)
    env.sync.set_state(env.sync.STATUS_KEY, saved)
    assert 'rates' not in env.sync.status()
    assert env.sync.status()['completed'] == 3
    assert env.sync.get_state(env.sync.STATUS_KEY) == saved


def test_limit_exceeding_authentication_window_fails_before_sending(sync_env, monkeypatch):
    env = sync_env
    entry, _, worker, clock = upload_worker(env, monkeypatch)
    # Simulate an oversized streaming body without allocating a huge test file.
    original = env.transport.MultipartEncoder
    streams = []

    def oversized(fields):
        encoder = original(fields=fields)
        if fields['media'][0] == entry.getFilesystemPath().name:
            encoder._len = 256 * 1024 * 1200 + 1
            streams.append(fields['media'][1])
        return encoder

    monkeypatch.setattr(env.transport, 'MultipartEncoder', oversized)
    worker.execute()
    result = env.sync.status()
    assert result['state'] == 'failed' and result['reason'] == 'configuration_or_receiver'
    assert 'Increase the speed limit' in result['message']
    assert '20 minutes' in result['message'] and entry.getFilesystemPath().name in result['message']
    assert not clock.waits and entry.sync_id is None
    assert streams and all(stream.closed for stream in streams)
    assert not [call for call in env.calls if call[0] == 'PUT' and call[1].endswith('/image')]
