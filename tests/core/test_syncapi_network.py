"""Disposable real HTTP receiver: fault injection must never contact a live installation."""
import errno
from copy import deepcopy
from datetime import datetime, timedelta
import importlib
import logging
import random
import threading
import time
from types import SimpleNamespace

import pytest
import requests
from werkzeug.serving import WSGIRequestHandler, make_server
from werkzeug.wrappers import Response


@pytest.fixture
def wire(sync_env, monkeypatch, request):
    env = sync_env
    state = SimpleNamespace(calls=[], fault=None, fired=False, after_commit=False)
    application = env.nas.wsgi_app
    env.nas.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)

    def proxy(environ, start_response):
        path, method = environ['PATH_INFO'], environ['REQUEST_METHOD']
        state.calls.append((method, path))
        if state.fault == 'lookup_redirect' and path.endswith('/lookup'):
            return Response('', status=302, headers={'Location': '/login'})(environ, start_response)
        target = path.endswith('/image') and method == 'PUT'
        inject = target and not state.fired and state.fault
        if inject:
            state.fired = True
        if inject and isinstance(state.fault, int):
            return Response('<html>Proxy unavailable</html>', status=state.fault)(environ, start_response)
        if inject and state.fault == 'html':
            return Response('<html>Login required</html>', content_type='text/html')(environ, start_response)
        if not inject:
            return application(environ, start_response)
        captured = {}

        def capture(status, headers, exc_info=None):
            captured.update(status=status, headers=headers)

        output = application(environ, capture)
        try:
            body = b''.join(output)
        finally:
            if hasattr(output, 'close'):
                output.close()
        state.after_commit = captured['status'].startswith('200')
        if state.fault == 'timeout':
            time.sleep(0.25)
        if state.fault == 'truncated_ack':
            # The receiver committed, but the connection ends halfway through
            # its acknowledgement while Content-Length still promises all bytes.
            body = body[:max(1, len(body) // 2)]
        start_response(captured['status'], captured['headers'])
        return [body]

    class QuietHandler(WSGIRequestHandler):
        def log(self, *args, **kwargs):
            pass

    tls = getattr(request, 'param', False)
    server = make_server('127.0.0.1', 0, proxy, threaded=True, request_handler=QuietHandler,
                         ssl_context='adhoc' if tls else None)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    session = requests.Session()
    session.trust_env = False
    monkeypatch.setattr(env.transport.requests, 'put', session.put)
    monkeypatch.setattr(env.transport.requests, 'post', session.post)
    monkeypatch.setattr(env.transport.requests, 'get', session.get)
    scheme = 'https' if tls else 'http'
    env.config['SYNCAPI'].update(BASEURL=f'{scheme}://127.0.0.1:{server.server_port}/indi-allsky',
                                CONNECT_TIMEOUT=1, TIMEOUT=2)
    row = env.models.IndiAllSkyDbConfigTable.query.first()
    row.data = deepcopy(env.config)
    env.db.session.commit()
    monkeypatch.setattr(env.sync.SyncApiSyncWorker, 'wait_for_retry', lambda _, delay: time.sleep(0.02))
    try:
        yield SimpleNamespace(env=env, state=state, server=server, session=session)
    finally:
        session.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def assert_remote_bytes(env, entry):
    expected_bytes, remote_id = entry.getFilesystemPath().read_bytes(), entry.sync_id
    with env.nas.app_context():
        rows = env.models.IndiAllSkyDbImageTable.query.all()
        assert len(rows) == 1
        assert rows[0].getFilesystemPath().read_bytes() == expected_bytes
        assert rows[0].id == remote_id


@pytest.mark.parametrize('fault', [429, 500, 502, 503, 504, 'timeout', 'truncated_ack'])
def test_real_http_transient_failure_recovers_without_duplicate(wire, monkeypatch, caplog, fault):
    env, state = wire.env, wire.state
    entry = env.asset()
    entry.getFilesystemPath().write_bytes(b'archive-data\r\n' * 10000)
    state.fault = fault
    if fault == 'timeout':
        env.config['SYNCAPI']['TIMEOUT'] = 0.1
        row = env.models.IndiAllSkyDbConfigTable.query.first()
        row.data = deepcopy(env.config)
        env.db.session.commit()
        monkeypatch.setattr(env.sync.SyncApiSyncWorker, 'wait_for_retry', lambda _, delay: time.sleep(0.3))
    with caplog.at_level(logging.WARNING, logger='indi_allsky'):
        result = env.run()
    assert result['state'] == 'complete', result
    assert result['completed'] == 1
    assert_remote_bytes(env, entry)
    uploads = state.calls.count(('PUT', '/indi-allsky/sync/v1/image'))
    assert uploads == (1 if fault in ('timeout', 'truncated_ack') else 2)
    if fault in ('timeout', 'truncated_ack'):
        assert state.after_commit and result['files'] == 0
    assert not [r for r in caplog.records if r.name == 'indi_allsky' and r.levelno >= logging.WARNING]


def test_real_http_html_acknowledgement_fails_safely_and_manual_retry_recovers(wire):
    env = wire.env
    entry = env.asset()
    wire.state.fault = 'html'
    result = env.run()
    assert result['state'] == 'failed' and entry.sync_id is None
    assert 'acknowledgement' in result['message']
    result = env.run()
    assert result['state'] == 'complete'
    assert_remote_bytes(env, entry)


@pytest.mark.parametrize('status', [413, 507])
def test_proxy_size_limit_or_storage_rejection_stops_without_acknowledgement(wire, status):
    env = wire.env
    entry = env.asset()
    wire.state.fault = status
    result = env.run()
    assert result['state'] == 'failed' and result['reason'] == 'configuration_or_receiver'
    assert entry.sync_id is None and result['files'] == 0
    assert wire.state.calls.count(('PUT', '/indi-allsky/sync/v1/image')) == 1


@pytest.mark.parametrize('permanent', [False, True])
def test_real_receiver_disk_full_never_acknowledges_unsaved_media(wire, monkeypatch, permanent):
    env = wire.env
    entry = env.asset()
    copy = env.receiver.shutil.copy2
    failures = []

    def disk_full(source, destination, *args, **kwargs):
        if not failures or permanent:
            failures.append(destination)
            raise OSError(errno.ENOSPC, 'Simulated receiver disk full')
        return copy(source, destination, *args, **kwargs)

    monkeypatch.setattr(env.receiver.shutil, 'copy2', disk_full)
    result = env.run()
    if permanent:
        assert result['state'] == 'failed' and result['reason'] == 'connection', result
        assert entry.sync_id is None and result['files'] == 0
        assert len(failures) == 3
    else:
        assert result['state'] == 'complete', result
        assert_remote_bytes(env, entry)


def test_real_streamed_upload_cancels_during_pacing_without_acknowledgement(wire):
    env = wire.env
    entry = env.asset()
    entry.getFilesystemPath().write_bytes(b'X' * (512 * 1024))
    task = env.sync.request_sync(env.config, ['image'], upload_limit=128)
    worker = env.sync.SyncApiSyncWorker(env.app, task.id)
    timer = threading.Timer(0.25, worker.stop_event.set)
    timer.start()
    started = time.monotonic()
    try:
        worker.execute()
    finally:
        timer.cancel()
        timer.join(timeout=2)
    result = env.sync.status()
    assert result['state'] == 'cancelled', result
    assert result['files'] == 0 and entry.sync_id is None
    assert time.monotonic() - started < 2
    assert env.run()['state'] == 'complete'
    assert_remote_bytes(env, entry)


@pytest.mark.parametrize('wire', [True], indirect=True)
def test_real_tls_invalid_certificate_stops_until_explicitly_allowed(wire):
    env = wire.env
    entry = env.asset()
    result = env.run()
    assert result['state'] == 'failed' and result['reason'] == 'certificate', result
    assert entry.sync_id is None and not wire.state.calls
    env.config['SYNCAPI']['CERT_BYPASS'] = True
    env.models.IndiAllSkyDbConfigTable.query.first().data = deepcopy(env.config)
    env.db.session.commit()
    assert env.run()['state'] == 'complete'
    assert_remote_bytes(env, entry)


def test_real_proxy_redirect_does_not_forward_signed_lookup_or_upload(wire):
    env = wire.env
    entry = env.asset()
    wire.state.fault = 'lookup_redirect'
    result = env.run()
    assert result['state'] == 'failed' and entry.sync_id is None
    assert wire.state.calls == [('PUT', '/indi-allsky/sync/v1/camera'),
                               ('POST', '/indi-allsky/sync/v1/image/lookup')]


def test_real_refused_connection_has_bounded_retries_and_one_sender_warning(wire, caplog):
    env = wire.env
    entry = env.asset()
    wire.server.shutdown()
    wire.server.server_close()
    with caplog.at_level(logging.WARNING, logger='indi_allsky'):
        result = env.run()
    assert result['state'] == 'failed' and result['reason'] == 'connection'
    assert '3 attempts' in result['message'] and entry.sync_id is None
    assert len([r for r in caplog.records if r.name == 'indi_allsky' and r.levelno >= logging.WARNING]) == 1


def test_truncated_reply_recovers_and_schedule_continues(wire, caplog):
    env = wire.env
    entry = env.asset()
    schedule = importlib.import_module('indi_allsky.syncapi_schedule')
    env.save_schedule(dict(enabled=True, interval=1, delay=0, upload_limit=0, types=['image']))
    scheduler = schedule.SyncApiScheduler()
    scheduler.tick(env.config, env.sync.get_state('CONFIG_ID'))
    scheduler.start_run(env.config, schedule.settings())
    task = env.sync.active_task()
    wire.state.fault = 'truncated_ack'
    with caplog.at_level(logging.WARNING, logger='indi_allsky'):
        env.sync.SyncApiSyncWorker(env.app, task.id).execute()
        result = env.sync.status()
    assert result['state'] == 'complete' and result['files'] == 0
    assert wire.state.after_commit and entry.sync_id is not None
    scheduler.tick(env.config, env.sync.get_state('CONFIG_ID'))
    assert schedule.status()['state'] == 'waiting'
    assert schedule.settings()['enabled'] is True
    assert not [r for r in caplog.records if r.name == 'indi_allsky' and r.levelno >= logging.WARNING]
    assert wire.state.calls.count(('PUT', '/indi-allsky/sync/v1/image')) == 1
    assert_remote_bytes(env, entry)


def test_same_size_receiver_corruption_is_repaired_over_http(wire):
    env = wire.env
    entry = env.asset()
    expected = entry.getFilesystemPath().read_bytes()
    assert env.run()['state'] == 'complete'
    entry.sync_id = None
    env.db.session.commit()
    with env.nas.app_context():
        path = env.models.IndiAllSkyDbImageTable.query.one().getFilesystemPath()
        path.write_bytes(bytes(value ^ 255 for value in expected))
    result = env.run()
    assert result['state'] == 'complete' and result['files'] == 1
    assert_remote_bytes(env, entry)


def test_mixed_archive_stays_oldest_first_during_capture_and_expiration(wire, monkeypatch):
    env = wire.env
    randomizer = random.Random(20261009)
    start = datetime.now().replace(microsecond=0) - timedelta(days=40)
    specifications = [(kind, start + timedelta(days=day, minutes=index))
                      for day in range(3) for index, kind in enumerate(env.sync.MEDIA)]
    randomizer.shuffle(specifications)
    entries = []
    for kind, created in specifications:
        entry = env.asset(kind, createDate=created, dayDate=created.date())
        entries.append((created, kind, entry.id))
    expected_order = sorted(entries)
    expired = env.db.session.get(env.sync.MEDIA[expected_order[-1][1]][0], expected_order[-1][2])
    expired_path = expired.getFilesystemPath()
    real_transfer = env.sync.SyncApiSyncWorker.transfer_unit
    observed, inserted = [], []

    def transfer(worker, entry, media_type):
        kind = next(name for name, (model, code, _) in env.sync.MEDIA.items() if code == media_type)
        observed.append((entry.createDate, kind, entry.id))
        if not inserted:
            # Model an expiration run and an import/capture appearing after the
            # worker's upper ID bounds, without mutating any live installation.
            expired_path.unlink()
            inserted.append(env.asset('image', createDate=start - timedelta(days=1)))
        return real_transfer(worker, entry, media_type)

    monkeypatch.setattr(env.sync.SyncApiSyncWorker, 'transfer_unit', transfer)
    monkeypatch.setattr(env.sync.SyncApiSyncWorker, 'page_size', 2)
    result = env.run(list(env.sync.MEDIA))
    assert result['state'] == 'complete', result
    assert observed == expected_order
    assert result['completed'] == 29 and result['skipped'] == 1 and result['total'] == 30
    assert inserted[0].sync_id is None
    monkeypatch.setattr(env.sync.SyncApiSyncWorker, 'transfer_unit', real_transfer)
    result = env.run(list(env.sync.MEDIA))
    assert result['state'] == 'complete' and result['completed'] == 1 and result['skipped'] == 1
    assert result['files'] == 1 and inserted[0].sync_id is not None
