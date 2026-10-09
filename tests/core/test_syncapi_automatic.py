"""Protect the original upload queue and API alongside Archive sync.

Use real multipart parsing, receiver views, files and separate databases. Only
network delivery and unrelated storage providers are replaced: these checks
must never contact a user's configured receiver, bucket or MQTT broker.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import hmac
import io
import json
import math
from queue import Queue
import time
from types import SimpleNamespace

import pytest


KINDS = ['image', 'panoramaimage', 'video', 'minivideo', 'keogram', 'startrail',
         'startrailvideo', 'panoramavideo', 'rawimage', 'fitsimage', 'thumbnail']


@pytest.fixture
def automatic(sync_env, request):
    env = sync_env
    # Missing MODE is an existing installation's configuration, not Archive mode.
    env.config['SYNCAPI'].pop('MODE')
    if getattr(request, 'param', None):
        env.config['SYNCAPI']['MODE'] = request.param
    env.config['SYNCAPI'].update(UPLOAD_IMAGE=1, UPLOAD_PANORAMA=1,
                                ARCHIVE_SCHEDULE=True, ARCHIVE_UPLOAD_LIMIT=128,
                                ARCHIVE_TYPES=['video'])
    env.config['EXPOSURE_PERIOD'] = 15
    row = env.models.IndiAllSkyDbConfigTable.query.one()
    row.data = deepcopy(env.config)
    env.db.session.commit()
    module = env.load('indi_allsky.uploader', 'indi_allsky/uploader.py')
    helper_module = env.load('indi_allsky.miscUpload', 'indi_allsky/miscUpload.py')
    queue = Queue()
    worker = module.FileUploader(1, env.config, Queue(), queue)
    helper = helper_module.miscUpload(env.config, queue, [1, 0])

    def enqueue(entry, metadata, action=None, **extra):
        task = env.models.IndiAllSkyDbTaskQueueTable(
            queue=env.models.TaskQueueQueue.UPLOAD, state=env.models.TaskQueueState.QUEUED,
            data=dict(action=action or env.sync.constants.TRANSFER_SYNC_V1,
                      model=type(entry).__name__, id=entry.id, metadata=metadata, **extra))
        env.db.session.add(task)
        env.db.session.commit()
        queue.put({'task_id': task.id})
        return task

    def drain():
        while not queue.empty():
            item = queue.get_nowait()
            worker.processUpload(item)
            task = env.db.session.get(env.models.IndiAllSkyDbTaskQueueTable, item['task_id'])
            assert task.state == env.models.TaskQueueState.SUCCESS, task.result

    enqueue(env.camera, env.sync.metadata_for(env.camera, env.sync.constants.CAMERA))
    drain()
    assert env.camera.sync_id
    return SimpleNamespace(env=env, module=module, worker=worker, helper=helper,
                           queue=queue, enqueue=enqueue, drain=drain)


def make_media(env, kind, **overrides):
    if kind == 'thumbnail':
        parent = env.asset()
        entry = env.thumbnail(parent)
        metadata = env.sync.metadata_for(entry, env.sync.constants.THUMBNAIL,
                                         env.sync.metadata_for(parent, env.sync.constants.IMAGE))
    else:
        entry = env.asset(kind, **overrides)
        metadata = env.sync.metadata_for(entry, env.sync.MEDIA[kind][1])
    return entry, metadata


@pytest.mark.parametrize('automatic', [None, 'automatic'], indirect=True)
@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('empty', [False, True], ids=['media', 'metadata-only'])
def test_original_queue_transfers_media_and_metadata(automatic, kind, empty):
    env = automatic.env
    env.config['SYNCAPI']['EMPTY_FILE'] = empty
    entry, metadata = make_media(env, kind)
    source = entry.getFilesystemPath().read_bytes()
    metadata['s3_key'] = 'existing/object.jpg' if empty else None
    automatic.enqueue(entry, metadata)
    automatic.drain()
    assert entry.sync_id
    # Automatic uploads must not acquire Archive lookups, pacing or selection.
    assert all(method == 'PUT' and not route.endswith('/lookup') for method, route, _ in env.calls)
    with env.nas.app_context():
        remote = env.db.session.get(type(entry), entry.sync_id)
        assert remote is not None
        if empty:
            assert not remote.getFilesystemPath().exists()
            assert remote.s3_key == 'existing/object.jpg'
        else:
            assert remote.getFilesystemPath().read_bytes() == source
    assert entry.getFilesystemPath().read_bytes() == source


@pytest.mark.parametrize('automatic', [None, 'automatic'], indirect=True)
@pytest.mark.parametrize('kind,method,setting', [
    ('image', 'syncapi_image', 'UPLOAD_IMAGE'),
    ('panoramaimage', 'syncapi_panorama', 'UPLOAD_PANORAMA')])
def test_original_sampling_and_post_s3_deferral(automatic, kind, method, setting):
    env = automatic.env
    env.config['SYNCAPI'].update({setting: 3, 'POST_S3': True})
    start = datetime.now() - timedelta(days=1)
    entries = [make_media(env, kind, createDate=(start + timedelta(minutes=i)).replace(microsecond=0))
               for i in range(7)]
    send = getattr(automatic.helper, method)
    for entry, metadata in entries:
        send(entry, metadata)
    assert automatic.queue.empty()  # Waiting for S3 must not advance sampling.
    for entry, metadata in entries:
        entry.s3_key = 'already/in/s3'
        send(entry, metadata)
    automatic.drain()
    assert [i for i, (entry, _) in enumerate(entries, 1) if entry.sync_id] == [3, 6]
    with env.nas.app_context():
        assert env.sync.MEDIA[kind][0].query.count() == 2
    env.config['SYNCAPI'][setting] = 0
    send(*make_media(env, kind))
    assert automatic.queue.empty()


@pytest.mark.parametrize('kind,method', [
    ('video', 'syncapi_video'), ('minivideo', 'syncapi_mini_video'),
    ('keogram', 'syncapi_keogram'), ('startrail', 'syncapi_startrail'),
    ('startrailvideo', 'syncapi_startrail_video'),
    ('panoramavideo', 'syncapi_panorama_video'), ('thumbnail', 'syncapi_thumbnail')])
def test_original_generated_media_helpers(automatic, kind, method):
    entry, metadata = make_media(automatic.env, kind)
    getattr(automatic.helper, method)(entry, metadata)
    assert automatic.queue.qsize() == 1
    automatic.drain()
    assert entry.sync_id


@pytest.mark.parametrize('mode', ['automatic', 'archive', 'disabled'])
@pytest.mark.parametrize('provider', ['file', 's3', 'mqtt'])
def test_other_upload_providers_still_run_in_every_sync_mode(automatic, monkeypatch, mode, provider):
    env = automatic.env
    env.config['SYNCAPI'].update(MODE=mode, ENABLE=mode != 'disabled', POST_S3=True)
    row = env.models.IndiAllSkyDbConfigTable.query.one()
    row.data = deepcopy(env.config)
    env.db.session.commit()
    calls = []

    class Storage:
        def __init__(self, *args, **kwargs):
            pass

        def connect(self, **kwargs):
            calls.append(('connect', kwargs))

        def put(self, **kwargs):
            calls.append(('put', kwargs))
            return {}

        def close(self):
            pass

    monkeypatch.setattr(automatic.module.filetransfer, 'test_storage', Storage, raising=False)
    monkeypatch.setattr(automatic.module.filetransfer, 'paho_mqtt', Storage, raising=False)
    env.config.update(
        FILETRANSFER=dict(CLASSNAME='test_storage', HOST='storage.invalid', USERNAME='test', PASSWORD='test', PORT=0),
        S3UPLOAD=dict(CLASSNAME='test_storage', ACCESS_KEY='test', SECRET_KEY='test', REGION='test',
                      HOST='storage.invalid', BUCKET='test', URL_TEMPLATE='{host}/{bucket}/{key}',
                      TLS=True, CERT_BYPASS=False, STORAGE_CLASS='STANDARD', ACL='private', PORT=0),
        MQTTPUBLISH=dict(HOST='mqtt.invalid', USERNAME='test', PASSWORD='test', TRANSPORT='tcp',
                         TLS=False, PORT=0, BASE_TOPIC='test', QOS=0))
    entry, metadata = make_media(env, 'image')
    action = {'file': env.sync.constants.TRANSFER_UPLOAD, 's3': env.sync.constants.TRANSFER_S3,
              'mqtt': env.sync.constants.TRANSFER_MQTT}[provider]
    automatic.enqueue(entry, metadata, action, remote_file='latest.jpg', image_topic='image')
    automatic.drain()
    assert [name for name, _ in calls] == ['connect', 'put']
    assert entry.getFilesystemPath().is_file()
    if provider == 's3':
        assert entry.s3_key
        assert bool(entry.sync_id) == (mode == 'automatic')
    elif provider == 'file':
        assert entry.uploaded


def signed(env, kind, metadata, method, media=b''):
    payload = json.dumps(dict(metadata, file_size=len(media))).encode()
    bucket = str(math.floor(time.time() / 300)).encode()
    signature = hmac.new(b'test-api-key', bucket + payload, hashlib.sha3_512).hexdigest()
    # Original clients send two multipart parts, without Archive's trailing field.
    return env.nas.test_client().open('/indi-allsky/sync/v1/' + kind, method=method,
        headers={'Authorization': 'Bearer tester:' + signature},
        data={'metadata': (io.BytesIO(payload), 'metadata.json'),
              'media': (io.BytesIO(media), 'media.jpg')})


@pytest.mark.parametrize('kind', KINDS)
def test_original_post_get_put_delete_contract(automatic, kind):
    env = automatic.env
    entry, metadata = make_media(env, kind)
    created = signed(env, kind, metadata, 'POST', b'original')
    assert created.status_code == 200, created.get_json()
    remote_id = created.get_json()['id']
    found = signed(env, kind, dict(metadata, id=remote_id), 'GET')
    assert found.status_code == 200 and found.get_json()['id'] == remote_id
    duplicate = signed(env, kind, metadata, 'POST', b'changed')
    assert duplicate.status_code == 400 and duplicate.get_json()['error'] == 'file_exists'
    with env.nas.app_context():
        assert env.db.session.get(type(entry), remote_id).getFilesystemPath().read_bytes() == b'original'
    replaced = signed(env, kind, metadata, 'PUT', b'replacement')
    assert replaced.status_code == 200, replaced.get_json()
    remote_id = replaced.get_json()['id']
    with env.nas.app_context():
        path = env.db.session.get(type(entry), remote_id).getFilesystemPath()
        assert path.read_bytes() == b'replacement'
    deleted = signed(env, kind, dict(metadata, id=remote_id), 'DELETE')
    assert deleted.status_code == 200 and not path.exists()
    with env.nas.app_context():
        assert env.db.session.get(type(entry), remote_id) is None
