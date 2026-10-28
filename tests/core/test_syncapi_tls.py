"""Certificate rejection must not be confused with an interrupted TLS connection."""
import importlib
import logging
import socket
import socketserver
import ssl
import threading

import pytest
import requests
from urllib3.exceptions import MaxRetryError, SSLError
from urllib3.util.ssl_match_hostname import CertificateError


@pytest.mark.parametrize('failure', ['verification', 'hostname', 'eof'])
@pytest.mark.parametrize('wrapper', ['args', 'reason', 'cause', 'text'])
@pytest.mark.parametrize('lookup', [False, True])
def test_tls_failure_classification(sync_env, monkeypatch, failure, wrapper, lookup):
    env = sync_env
    certificate = failure != 'eof'
    error = {'verification': ssl.SSLCertVerificationError(1, 'test certificate rejection'),
             'hostname': CertificateError("hostname 'nas' doesn't match 'receiver'"),
             'eof': ssl.SSLEOFError(8, 'EOF occurred in violation of protocol')}[failure]
    if wrapper == 'args':
        error = requests.exceptions.SSLError(SSLError(error))
    elif wrapper == 'reason':
        error = requests.exceptions.SSLError(MaxRetryError(None, '/sync/v1/camera', SSLError(error)))
    elif wrapper == 'cause':
        outer = requests.exceptions.SSLError('TLS request failed')
        outer.__cause__ = error
        error = outer
    else:
        # Some SSL backends retain only OpenSSL's error text.
        error = requests.exceptions.SSLError('certificate verify failed' if certificate
                                             else '[SSL: UNEXPECTED_EOF_WHILE_READING]')

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(env.transport.requests, 'post' if lookup else 'put', fail)
    client = env.transport.requests_syncapi_v1(env.config, quiet=True)
    client.connect(hostname='https://nas/indi-allsky/sync/v1/camera', username='tester', apikey='test-key')
    expected = env.transport.CertificateValidationFailure if certificate else env.transport.ConnectionFailure
    with pytest.raises(expected) as caught:
        client.put(local_file='camera', empty_file=True, metadata={}, lookup=lookup)
    assert caught.value.__cause__ is error


@pytest.mark.parametrize('probe', [False, True])
def test_certificate_rejection_still_blocks_schedule(sync_env, monkeypatch, probe):
    env = sync_env
    env.asset()
    schedule = importlib.import_module('indi_allsky.syncapi_schedule')
    env.save_schedule(dict(enabled=True, interval=1, delay=0, upload_limit=0, types=['image']))

    def reject(*args, **kwargs):
        raise requests.exceptions.SSLError(ssl.SSLCertVerificationError(1, 'test certificate rejection'))

    monkeypatch.setattr(env.transport.requests, 'post' if probe else 'put', reject)
    if probe:
        assert schedule.probe_receiver(env.config, None, env.camera.uuid)[0] == 'blocked'
    else:
        scheduler = schedule.SyncApiScheduler()
        scheduler.tick(env.config, env.sync.get_state('CONFIG_ID'))
        scheduler.start_run(env.config, schedule.settings())
        env.sync.SyncApiSyncWorker(env.app, env.sync.active_task().id).execute()
        assert env.sync.status()['reason'] == 'certificate'
        scheduler.tick(env.config, env.sync.get_state('CONFIG_ID'))
        assert schedule.status()['state'] == 'paused' and not schedule.settings()['enabled']


@pytest.fixture
def interrupted_tls():
    calls = []

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.settimeout(2)
            calls.append(self.request.recv(16384))
            # Receive the ClientHello, then close without presenting a certificate.
            self.request.shutdown(socket.SHUT_RDWR)

    with socketserver.TCPServer(('127.0.0.1', 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f'https://127.0.0.1:{server.server_address[1]}/indi-allsky', calls
        finally:
            server.shutdown()
            thread.join(timeout=5)
            assert not thread.is_alive()


@pytest.mark.parametrize('cert_bypass', [False, True])
def test_real_tls_interruption_retries_and_keeps_schedule(sync_env, interrupted_tls, monkeypatch, caplog, cert_bypass):
    env = sync_env
    url, calls = interrupted_tls
    entry = env.asset()
    schedule = importlib.import_module('indi_allsky.syncapi_schedule')
    env.config['SYNCAPI'].update(BASEURL=url, CERT_BYPASS=cert_bypass, CONNECT_TIMEOUT=1, TIMEOUT=2)
    env.save_schedule(dict(enabled=True, interval=1, delay=0, upload_limit=0, types=['image']))
    scheduler = schedule.SyncApiScheduler()
    scheduler.tick(env.config, env.sync.get_state('CONFIG_ID'))
    scheduler.start_run(env.config, schedule.settings())
    task = env.sync.active_task()
    monkeypatch.setattr(env.sync.SyncApiSyncWorker, 'wait_for_retry', lambda *args: None)
    with requests.Session() as session:
        session.trust_env = False
        monkeypatch.setattr(env.transport.requests, 'put', session.put)
        monkeypatch.setattr(env.transport.requests, 'post', session.post)
        with caplog.at_level(logging.DEBUG, logger='indi_allsky'):
            env.sync.SyncApiSyncWorker(env.app, task.id).execute()
            result = env.sync.status()
            assert result['state'] == 'failed' and result['reason'] == 'connection', result
            assert '3 attempts' in result['message'] and len(calls) == 3
            assert entry.sync_id is None and result['files'] == 0
            scheduler.tick(env.config, env.sync.get_state('CONFIG_ID'))
            assert schedule.status()['state'] == 'waiting' and schedule.settings()['enabled']
            assert schedule.probe_receiver(env.config, None, env.camera.uuid)[0] == 'offline'
    assert len(calls) == 4
    tls_logs = [r for r in caplog.records if r.getMessage() == 'SyncAPI TLS request failed']
    assert len(tls_logs) == 4
    assert all(isinstance(r.exc_info[1], requests.exceptions.SSLError) for r in tls_logs)
    assert len([r for r in caplog.records if r.name == 'indi_allsky' and r.levelno >= logging.WARNING]) == 1


def test_tls_interruption_after_commit_recovers_without_duplicate(sync_env, monkeypatch, caplog):
    env = sync_env
    entry = env.asset()
    expected_bytes = entry.getFilesystemPath().read_bytes()
    original = env.transport.requests.put
    uploads = []

    def lose_acknowledgement(url, **kwargs):
        response = original(url, **kwargs)
        if url.endswith('/image'):
            uploads.append(url)
            if len(uploads) == 1:
                raise requests.exceptions.SSLError(ssl.SSLEOFError(8, 'TLS connection closed'))
        return response

    monkeypatch.setattr(env.transport.requests, 'put', lose_acknowledgement)
    monkeypatch.setattr(env.sync.SyncApiSyncWorker, 'wait_for_retry', lambda *args: None)
    with caplog.at_level(logging.WARNING, logger='indi_allsky'):
        result = env.run()
    assert result['state'] == 'complete' and result['completed'] == 1 and entry.sync_id is not None
    assert len(uploads) == 1 and result['files'] == 0
    with env.nas.app_context():
        rows = env.models.IndiAllSkyDbImageTable.query.all()
        assert len(rows) == 1
        assert rows[0].getFilesystemPath().read_bytes() == expected_bytes
    assert not [r for r in caplog.records if r.name == 'indi_allsky' and r.levelno >= logging.WARNING]
