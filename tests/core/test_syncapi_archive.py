from copy import deepcopy
from datetime import datetime, timedelta
import logging
from queue import Queue
import uuid

import pytest

from indi_allsky.syncapi import automatic_sync_enabled, archive_sync_enabled, destination_fingerprint


def media_puts(env):
    return [call for call in env.calls if call[0] == 'PUT' and not call[1].endswith('/camera')]


@pytest.fixture
def retry_waits(sync_env, monkeypatch):
    waits = []
    monkeypatch.setattr(sync_env.sync.SyncApiSyncWorker, 'wait_for_retry', lambda worker, delay: waits.append(delay))
    return waits


def test_mode_defaults_and_fingerprint():
    assert automatic_sync_enabled({'SYNCAPI': {'ENABLE': True}})
    assert not automatic_sync_enabled({'SYNCAPI': {'ENABLE': True, 'MODE': 'archive'}})
    assert not automatic_sync_enabled({'SYNCAPI': {'ENABLE': False}})
    assert archive_sync_enabled({'SYNCAPI': {'ENABLE': True, 'MODE': 'archive'}})
    assert not archive_sync_enabled({'SYNCAPI': {'ENABLE': False, 'MODE': 'archive'}})
    assert not archive_sync_enabled({'SYNCAPI': {'ENABLE': True}})
    first = {'SYNCAPI': {'BASEURL': 'https://NAS:443/indi-allsky/', 'USERNAME': 'user', 'APIKEY': 'one'}}
    second = {'SYNCAPI': {'BASEURL': 'https://nas/indi-allsky', 'USERNAME': 'user', 'APIKEY': 'two'}}
    assert destination_fingerprint(first) == destination_fingerprint(second)


def test_incremental_archive_and_metadata(sync_env):
    env = sync_env
    old = env.asset(age=65)
    sent = env.asset(sync_id=999)
    recent = env.asset(age=0)
    thumb = env.thumbnail(old)
    result = env.run()
    assert result['state'] == 'complete', result
    assert result['completed'] == 1
    assert result['files'] == 2
    assert old.sync_id and thumb.sync_id
    assert sent.sync_id == 999 and recent.sync_id is None
    with env.nas.app_context():
        stored = env.models.IndiAllSkyDbImageTable.query.one()
        assert stored.thumbnail_uuid == thumb.uuid
        assert stored.data['custom_feature'] == 'preserved'
        assert stored.getFilesystemPath().read_bytes() == old.getFilesystemPath().read_bytes()
    env.calls.clear()
    assert env.run()['completed'] == 0
    assert media_puts(env) == []


@pytest.mark.parametrize('kind', ['image', 'panoramaimage', 'video', 'minivideo', 'keogram', 'startrail', 'startrailvideo', 'panoramavideo', 'rawimage', 'fitsimage'])
def test_all_supported_media_roundtrip(sync_env, kind):
    env = sync_env
    entry = env.asset(kind)
    result = env.run([kind])
    assert result['state'] == 'complete', result
    assert entry.sync_id
    with env.nas.app_context():
        stored = env.sync.MEDIA[kind][0].query.one()
        assert stored.getFilesystemPath().is_file()
        if hasattr(stored, 'success'):
            assert stored.success


@pytest.mark.parametrize('page_size', [1, 2, 100])
def test_media_types_are_interleaved_oldest_first(sync_env, monkeypatch, page_size):
    env = sync_env
    monkeypatch.setattr(env.sync.SyncApiSyncWorker, 'page_size', page_size)
    start = datetime.now().replace(microsecond=0) - timedelta(days=30)
    kinds = list(env.sync.MEDIA)
    entries = [
        (kind, env.asset(kind, createDate=start + timedelta(hours=hour)))
        for kind, hour in zip(kinds + ['image'] * 3, [12, 4, 7, 2, 9, 1, 8, 11, 5, 6, 0, 7, 10])
    ]
    thumb = env.thumbnail(entries[0][1])
    thumb.createDate = datetime.now()  # Thumbnail date must not split its parent unit.
    env.db.session.commit()

    result = env.run(kinds)
    assert result['state'] == 'complete', result
    assert result['completed'] == len(entries)
    expected = []
    for kind, entry in sorted(entries, key=lambda pair: (pair[1].createDate, pair[0], pair[1].id)):
        expected.append((env.sync.MEDIA[kind][1], entry.createDate.timestamp()))
        if entry.thumbnail_uuid:
            expected.append((env.sync.constants.THUMBNAIL, thumb.createDate.timestamp()))
    assert [(call[2]['type'], call[2]['createDate']) for call in media_puts(env)] == expected

    env.calls.clear()
    assert env.run(kinds)['completed'] == 0
    assert media_puts(env) == []


def test_multiple_mini_timelapses_survive(sync_env):
    env = sync_env
    first = env.asset('minivideo')
    second = env.asset('minivideo', createDate=first.createDate + timedelta(seconds=30))
    assert env.run(['minivideo'])['state'] == 'complete'
    with env.nas.app_context():
        entries = env.models.IndiAllSkyDbMiniVideoTable.query.all()
        assert len(entries) == 2
        assert all(entry.getFilesystemPath().exists() for entry in entries)


def test_offline_bounded_retries_one_warning(sync_env, monkeypatch, caplog, retry_waits):
    env = sync_env
    for _ in range(20):
        env.asset()
    calls = []
    def offline(*args, **kwargs):
        calls.append(1)
        raise env.transport.requests.exceptions.ConnectionError('offline')
    monkeypatch.setattr(env.transport.requests, 'put', offline)
    with caplog.at_level(logging.WARNING, logger='indi_allsky'):
        result = env.run()
    assert result['state'] == 'failed'
    assert len(calls) == 3
    assert retry_waits == [5, 15]
    assert 'Camera metadata upload failed for "Local camera"' in result['message']
    assert 'ConnectionError: offline' in result['message']
    assert len([record for record in caplog.records if record.name == 'indi_allsky']) == 1
    for _ in range(10):
        env.sync.status()
    assert len(calls) == 3


@pytest.mark.parametrize('first_kind', ['image', 'video'])
def test_failure_then_resume_does_not_resend_success(sync_env, monkeypatch, first_kind, retry_waits):
    env = sync_env
    first = env.asset(first_kind, age=3)
    second = env.asset(age=2)
    original = env.transport.requests.put
    def fail_second(url, **kwargs):
        stream = kwargs['data']
        metadata = getattr(stream, 'encoder', stream).fields['metadata'][1].getvalue()
        if url.endswith('/image') and str(second.createDate.timestamp()) in metadata:
            raise env.transport.requests.exceptions.ConnectionError('offline')
        return original(url, **kwargs)
    monkeypatch.setattr(env.transport.requests, 'put', fail_second)
    assert env.run(['image', 'video'])['state'] == 'failed'
    assert retry_waits == [5, 15]
    assert first.sync_id and second.sync_id is None
    monkeypatch.setattr(env.transport.requests, 'put', original)
    env.calls.clear()
    assert env.run(['image', 'video'])['state'] == 'complete'
    assert len(media_puts(env)) == 1


@pytest.mark.parametrize('fail_after', ['image', 'thumbnail'])
def test_lost_acknowledgement_retry_recovers_without_copy(sync_env, monkeypatch, fail_after, retry_waits):
    env = sync_env
    image = env.asset()
    thumb = env.thumbnail(image)
    original = env.transport.requests.put
    failed = False
    def lose_response(url, **kwargs):
        nonlocal failed
        response = original(url, **kwargs)
        if url.endswith('/' + fail_after) and not failed:
            failed = True
            raise env.transport.requests.exceptions.ConnectionError('response lost after commit')
        return response
    monkeypatch.setattr(env.transport.requests, 'put', lose_response)
    assert env.run()['state'] == 'complete'
    assert retry_waits == [5]
    assert image.sync_id and thumb.sync_id
    puts = media_puts(env)
    assert [call[1].split('/')[-1] for call in puts] == ['image', 'thumbnail']
    with env.nas.app_context():
        remote = env.models.IndiAllSkyDbImageTable.query.one()
        assert remote.thumbnail_uuid == thumb.uuid
        assert env.models.IndiAllSkyDbThumbnailTable.query.one().getFilesystemPath().exists()
    env.calls.clear()
    assert env.run()['completed'] == 0
    assert media_puts(env) == []


@pytest.mark.parametrize('stage', ['camera', 'lookup', 'upload'])
def test_temporary_failure_recovers_quietly(sync_env, monkeypatch, caplog, retry_waits, stage):
    env = sync_env
    entry = env.asset()
    method = 'post' if stage == 'lookup' else 'put'
    original = getattr(env.transport.requests, method)
    failures = []

    def temporary_failure(url, **kwargs):
        target = '/camera' if stage == 'camera' else '/image/lookup' if stage == 'lookup' else '/image'
        if url.endswith(target) and len(failures) < 2:
            failures.append(1)
            raise env.transport.requests.exceptions.ConnectTimeout('connection timed out')
        return original(url, **kwargs)

    monkeypatch.setattr(env.transport.requests, method, temporary_failure)
    with caplog.at_level(logging.WARNING, logger='indi_allsky'):
        result = env.run()
    assert result['state'] == 'complete', result
    assert result['files'] == 1 and entry.sync_id
    assert retry_waits == [5, 15]
    assert len(media_puts(env)) == 1
    assert not [record for record in caplog.records if record.name == 'indi_allsky']


@pytest.mark.parametrize('stage, failure', [('lookup', 'ReadTimeout'), ('upload', 'ConnectionError')])
def test_exhausted_retries_report_file_stage_and_cause(sync_env, monkeypatch, caplog, retry_waits, stage, failure):
    env = sync_env
    entry = env.asset('video')
    method = 'post' if stage == 'lookup' else 'put'
    original = getattr(env.transport.requests, method)
    failures = []

    def fail(url, **kwargs):
        if url.endswith('/video/lookup' if stage == 'lookup' else '/video'):
            failures.append(1)
            raise getattr(env.transport.requests.exceptions, failure)('test network failure')
        return original(url, **kwargs)

    monkeypatch.setattr(env.transport.requests, method, fail)
    with caplog.at_level(logging.WARNING, logger='indi_allsky'):
        result = env.run(['video'])
    assert result['state'] == 'failed' and entry.sync_id is None
    assert 'after 3 attempts' in result['message']
    assert '{0} failed for "{1}"'.format(stage.capitalize(), entry.getFilesystemPath().name) in result['message']
    assert failure + ': test network failure' in result['message']
    assert len(failures) == 3 and retry_waits == [5, 15]
    warnings = [record for record in caplog.records if record.name == 'indi_allsky']
    assert len(warnings) == 1
    assert result['message'] in warnings[0].getMessage()


def test_lost_acknowledgement_then_offline_resumes_without_copy(sync_env, monkeypatch, retry_waits):
    env = sync_env
    entry = env.asset()
    thumb = env.thumbnail(entry)
    original_put, original_post = env.transport.requests.put, env.transport.requests.post
    offline = False

    def lose_response(url, **kwargs):
        nonlocal offline
        response = original_put(url, **kwargs)
        if url.endswith('/image'):
            offline = True
            raise env.transport.requests.exceptions.ConnectionError('response lost after commit')
        return response

    def unavailable_lookup(url, **kwargs):
        if offline:
            raise env.transport.requests.exceptions.ConnectionError('still offline')
        return original_post(url, **kwargs)

    monkeypatch.setattr(env.transport.requests, 'put', lose_response)
    monkeypatch.setattr(env.transport.requests, 'post', unavailable_lookup)
    assert env.run()['state'] == 'failed'
    assert entry.sync_id is None and thumb.sync_id is None
    assert retry_waits == [5, 15]
    monkeypatch.setattr(env.transport.requests, 'put', original_put)
    monkeypatch.setattr(env.transport.requests, 'post', original_post)
    env.calls.clear()
    assert env.run()['state'] == 'complete'
    assert [call[1].split('/')[-1] for call in media_puts(env)] == ['thumbnail']


@pytest.mark.parametrize('control', ['cancel', 'shutdown', 'config'])
def test_retry_wait_honors_control_before_next_request(sync_env, monkeypatch, control):
    env = sync_env
    env.asset()
    task = env.sync.request_sync(env.config, ['image'])
    worker = env.sync.SyncApiSyncWorker(env.app, task.id)
    calls, waits = [], []

    def offline(*args, **kwargs):
        calls.append(1)
        raise env.transport.requests.exceptions.ConnectionError('offline')

    def interrupt_wait(delay):
        waits.append(delay)
        assert 'Retrying in 5 seconds (attempt 2 of 3)' in env.sync.status()['message']
        if control == 'cancel':
            env.sync.cancel_sync(task.id)
        elif control == 'shutdown':
            worker.stop()
        else:
            config = deepcopy(env.config)
            config['SYNCAPI']['MODE'] = 'automatic'
            row = env.models.IndiAllSkyDbConfigTable.query.one()
            row.data = config
            env.db.session.commit()

    monkeypatch.setattr(env.transport.requests, 'put', offline)
    monkeypatch.setattr(worker.stop_event, 'wait', interrupt_wait)
    worker.execute()
    assert env.sync.status()['state'] == 'cancelled'
    assert calls == [1] and waits == [1]


def test_corrupt_unacknowledged_file_is_replaced(sync_env):
    env = sync_env
    image = env.asset()
    thumb = env.thumbnail(image)
    assert env.run()['state'] == 'complete'
    image.sync_id = None
    env.db.session.commit()
    with env.nas.app_context():
        env.models.IndiAllSkyDbImageTable.query.one().getFilesystemPath().write_bytes(b'corrupt')
    env.calls.clear()
    assert env.run()['state'] == 'complete'
    assert len(media_puts(env)) == 2
    with env.nas.app_context():
        assert env.models.IndiAllSkyDbThumbnailTable.query.one().uuid == thumb.uuid


def test_filter_missing_remote_hidden_unfinished(sync_env):
    env = sync_env
    missing = env.asset()
    missing.getFilesystemPath().unlink()
    incomplete = env.asset('video', success=False)
    for local, hidden in ((False, False), (True, True)):
        camera = env.models.IndiAllSkyDbCameraTable(uuid=str(uuid.uuid4()), name=str(uuid.uuid4()), local=local, hidden=hidden)
        env.db.session.add(camera)
        env.db.session.commit()
        env.asset(camera_id=camera.id)
    result = env.run(['image', 'video'])
    assert result['total'] == 1 and result['skipped'] == 1
    assert incomplete.sync_id is None and missing.sync_id is None
    assert media_puts(env) == []


def test_duplicate_start_cancel_and_destination_guard(sync_env):
    env = sync_env
    task = env.sync.request_sync(env.config, ['image'])
    assert env.sync.request_sync(env.config, ['video']).id == task.id
    env.sync.cancel_sync(task.id)
    worker = env.sync.SyncApiSyncWorker(env.app, task.id)
    worker.execute()
    assert env.sync.status()['state'] == 'cancelled'
    assert env.calls == []
    different = deepcopy(env.config)
    different['SYNCAPI']['BASEURL'] = 'https://another/indi-allsky'
    with pytest.raises(ValueError, match='destination changed'):
        env.sync.request_sync(different, ['image'])


def test_automatic_enqueue_gates_and_legacy_jobs(sync_env, caplog):
    env = sync_env
    upload = env.load('indi_allsky.miscUpload', 'indi_allsky/miscUpload.py')
    uploader = env.load('indi_allsky.uploader', 'indi_allsky/uploader.py')
    queue = Queue()
    helper = upload.miscUpload(env.config, queue, [1, 0])
    asset = env.asset()
    with caplog.at_level(logging.INFO, logger='indi_allsky'):
        for _ in range(20):
            helper.syncapi_image(asset, {})
            helper.syncapi_panorama(asset, {})
            helper.syncapi_thumbnail(asset, {})
        worker = uploader.FileUploader(1, env.config, Queue(), queue)
        worker._syncapi(asset, {})
        worker.config = deepcopy(env.config)
        worker.config['SYNCAPI']['MODE'] = 'automatic'  # stale worker during reload
        task = env.models.IndiAllSkyDbTaskQueueTable(queue=env.models.TaskQueueQueue.UPLOAD,
            state=env.models.TaskQueueState.QUEUED, data={'action': 504})
        env.db.session.add(task)
        env.db.session.commit()
        worker.processUpload({'task_id': task.id})
    assert task.state == env.models.TaskQueueState.EXPIRED
    assert queue.empty() and env.calls == []
    assert not [record for record in caplog.records if record.name == 'indi_allsky']


def test_restart_status_never_resumes(sync_env):
    env = sync_env
    env.sync.set_state(env.sync.STATUS_KEY, {'state': 'running', 'completed': 4})
    env.sync.interrupt_previous_run()
    assert env.sync.status()['state'] == 'interrupted'
    assert env.sync.status()['completed'] == 4
    assert env.calls == []


def test_cancellation_between_image_and_thumbnail(sync_env, monkeypatch):
    env = sync_env
    image = env.asset()
    env.thumbnail(image)
    original = env.transport.requests.put
    def cancel_after_image(url, **kwargs):
        response = original(url, **kwargs)
        if url.endswith('/image'):
            env.sync.cancel_sync(env.sync.active_task().id)
        return response
    monkeypatch.setattr(env.transport.requests, 'put', cancel_after_image)
    assert env.run()['state'] == 'cancelled'
    assert image.sync_id is None
    assert len(media_puts(env)) == 1
    monkeypatch.setattr(env.transport.requests, 'put', original)
    env.calls.clear()
    assert env.run()['state'] == 'complete'
    assert [call[1].split('/')[-1] for call in media_puts(env)] == ['thumbnail']


def test_capture_during_sync_waits_for_next_run(sync_env, monkeypatch):
    env = sync_env
    first = env.asset(age=5)
    added = []
    original = env.transport.requests.put
    def capture(url, **kwargs):
        response = original(url, **kwargs)
        if url.endswith('/camera') and not added:
            added.append(env.asset(age=10))
        return response
    monkeypatch.setattr(env.transport.requests, 'put', capture)
    monkeypatch.setattr(env.sync.SyncApiSyncWorker, 'page_size', 1)
    assert env.run()['completed'] == 1
    assert first.sync_id and added[0].sync_id is None
    assert env.run()['completed'] == 1
    assert added[0].sync_id


@pytest.mark.parametrize('failure, message', [('certificate', 'certificate'), ('authentication', 'authentication'), ('server', 'HTTP 507'), ('invalid', 'acknowledgement')])
def test_failure_classification_stops_run(sync_env, monkeypatch, failure, message):
    from types import SimpleNamespace
    env = sync_env
    env.asset()
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        if failure == 'certificate':
            raise env.transport.requests.exceptions.SSLError('test certificate')
        if failure == 'authentication':
            return SimpleNamespace(status_code=400, json=lambda: {'error': 'authentication failed'})
        if failure == 'server':
            return SimpleNamespace(status_code=507, json=lambda: {})
        return SimpleNamespace(status_code=200, text='not JSON')
    monkeypatch.setattr(env.transport.requests, 'put', fail)
    result = env.run()
    assert result['state'] == 'failed'
    assert message in result['message']
    assert len(calls) == 1


def test_old_receiver_stops_with_upgrade_message(sync_env, monkeypatch):
    from types import SimpleNamespace
    env = sync_env
    env.asset()
    monkeypatch.setattr(env.transport.requests, 'post', lambda *args, **kwargs: SimpleNamespace(status_code=400))
    result = env.run()
    assert result['state'] == 'failed'
    assert 'Update the receiver' in result['message']
    assert media_puts(env) == []


@pytest.mark.parametrize('http_status, error', [(401, None), (403, None), (400, 'authentication failed')])
def test_lookup_authentication_failure_is_not_an_upgrade_error(sync_env, monkeypatch, http_status, error):
    from types import SimpleNamespace
    env = sync_env
    env.asset(age=3)
    env.asset(age=2)
    requests = []

    def rejected_lookup(*args, **kwargs):
        requests.append(1)
        return SimpleNamespace(status_code=http_status, json=lambda: {'error': error})

    monkeypatch.setattr(env.transport.requests, 'post', rejected_lookup)
    result = env.run()
    assert result['state'] == 'failed'
    assert 'authentication failed' in result['message']
    assert len(requests) == 1 and media_puts(env) == []


def test_lookup_does_not_open_local_media(sync_env, monkeypatch, tmp_path):
    from types import SimpleNamespace
    env = sync_env
    requests = []

    def lookup(url, **kwargs):
        assert url == 'https://nas/indi-allsky/sync/v1/image/lookup'
        assert kwargs['allow_redirects'] is False
        requests.append(kwargs['data'].fields['media'][1].read())
        return SimpleNamespace(status_code=200, text='{"lookup_supported": true, "present": false}')

    monkeypatch.setattr(env.transport.requests, 'post', lookup)
    client = env.transport.requests_syncapi_v1(env.config, quiet=True)
    client.connect(hostname='https://nas/indi-allsky/sync/v1/image', username='tester', apikey='test-api-key')
    try:
        result = client.put(local_file=tmp_path / 'not-present.jpg', metadata={}, empty_file=False, lookup=True)
    finally:
        client.close()
    assert result == {'lookup_supported': True, 'present': False}
    assert requests == [b'']


def test_mysql_timestamp_precision(sync_env, monkeypatch):
    env = sync_env
    view = env.receiver.SyncApiImageView()
    value = datetime(2026, 8, 1, 1, 2, 3, 123456).timestamp()
    assert view.receiverDate(value).microsecond == 123456
    with monkeypatch.context() as patch:
        patch.setattr(env.db.engine.dialect, 'name', 'mysql')
        assert view.receiverDate(value).microsecond == 0


@pytest.mark.parametrize('status_code', [429, 500, 502, 503, 504])
@pytest.mark.parametrize('stage', ['camera', 'lookup', 'upload'])
def test_temporary_http_failure_recovers_without_duplicate_uploads(sync_env, monkeypatch, caplog, retry_waits, status_code, stage):
    from types import SimpleNamespace
    env = sync_env
    entry = env.asset()
    method = 'post' if stage == 'lookup' else 'put'
    original = getattr(env.transport.requests, method)
    attempts = []

    def unavailable(url, **kwargs):
        if url.endswith('/camera' if stage == 'camera' else '/image/lookup' if stage == 'lookup' else '/image') and not attempts:
            attempts.append(1)
            # A proxy may lose the upload response after the receiver committed.
            # The retry must recover its ID through a lookup, without resending.
            if stage == 'upload':
                original(url, **kwargs)
            return SimpleNamespace(status_code=status_code, json=lambda: None)
        return original(url, **kwargs)

    monkeypatch.setattr(env.transport.requests, method, unavailable)
    with caplog.at_level(logging.WARNING, logger='indi_allsky'):
        result = env.run()
    assert result['state'] == 'complete', result
    assert result['completed'] == 1 and entry.sync_id
    assert len(media_puts(env)) == 1 and retry_waits == [5]
    assert not [record for record in caplog.records if record.name == 'indi_allsky']


def test_cancel_during_source_hash_stops_before_reading_the_whole_file(sync_env, monkeypatch):
    from contextlib import contextmanager
    from pathlib import Path
    from types import SimpleNamespace
    env = sync_env
    entry = env.asset()
    path = entry.getFilesystemPath()
    path.write_bytes(b'x' * (3 * 1024 * 1024))
    task = env.sync.request_sync(env.config, ['image'])
    worker = env.sync.SyncApiSyncWorker(env.app, task.id)
    clock = SimpleNamespace(now=100)
    monkeypatch.setattr(env.sync, 'time', SimpleNamespace(monotonic=lambda: clock.now))
    original = Path.open
    reads = []

    @contextmanager
    def slow_source(source, *args, **kwargs):
        with original(source, *args, **kwargs) as stream:
            def read(size):
                reads.append(size)
                clock.now += 6
                env.sync.cancel_sync(task.id)
                return stream.read(size)
            yield SimpleNamespace(read=read) if source == path else stream

    monkeypatch.setattr(Path, 'open', slow_source)
    worker.execute()
    assert env.sync.status()['state'] == 'cancelled'
    assert reads == [1024 * 1024]
    assert entry.sync_id is None and media_puts(env) == []


@pytest.mark.parametrize('quiet', [False, True])
def test_temporary_http_classification_preserves_automatic_upload_behavior(sync_env, monkeypatch, quiet):
    from types import SimpleNamespace
    env = sync_env
    client = env.transport.requests_syncapi_v1(env.config, quiet=quiet)
    client.connect(hostname='https://nas/indi-allsky/sync/v1/camera', username='tester', apikey='test-api-key')
    monkeypatch.setattr(env.transport.requests, 'put', lambda *args, **kwargs: SimpleNamespace(status_code=503))
    expected = env.errors.ConnectionFailure if quiet else env.errors.TransferFailure
    with pytest.raises(expected, match='503'):
        client.put(local_file='camera', metadata={}, empty_file=True)
