"""Authenticated archive lookups must pass proxies without invoking uploads."""

import importlib

import pytest
from werkzeug.wrappers import Response


def test_archive_and_recovery_work_through_proxy_rejecting_get_bodies(sync_env, monkeypatch):
    env = sync_env
    receiver = env.nas.wsgi_app

    def proxy(environ, start_response):
        if environ['REQUEST_METHOD'] == 'GET' and int(environ.get('CONTENT_LENGTH') or 0):
            return Response('GET bodies rejected', status=405)(environ, start_response)
        return receiver(environ, start_response)

    monkeypatch.setattr(env.nas, 'wsgi_app', proxy)
    assert env.nas.test_client().get('/indi-allsky/sync/v1/camera', data=b'body').status_code == 405
    schedule = importlib.import_module('indi_allsky.syncapi_schedule')
    assert schedule.probe_receiver(env.config, None, env.camera.uuid)[0] == 'ready'
    with env.nas.app_context():
        assert env.models.IndiAllSkyDbCameraTable.query.count() == 0

    entry = env.asset()
    thumbnail = env.thumbnail(entry)
    assert env.run()['state'] == 'complete'
    remote_ids = entry.sync_id, thumbnail.sync_id
    assert schedule.probe_receiver(env.config, env.camera.sync_id, env.camera.uuid)[0] == 'ready'
    # Simulate lost local acknowledgements: POST lookups recover both IDs.
    entry.sync_id = thumbnail.sync_id = None
    env.db.session.commit()
    env.calls.clear()
    result = env.run()
    assert result['state'] == 'complete' and result['files'] == 0
    assert (entry.sync_id, thumbnail.sync_id) == remote_ids
    assert [(method, path) for method, path, _ in env.calls] == [
        ('PUT', '/indi-allsky/sync/v1/camera'),
        ('POST', '/indi-allsky/sync/v1/image/lookup'),
        ('POST', '/indi-allsky/sync/v1/thumbnail/lookup'),
    ]


@pytest.mark.parametrize('kind', ['camera', 'image'])
@pytest.mark.parametrize('apikey', ['test-api-key', 'incorrect-key'])
def test_lookup_requires_authentication_and_never_changes_receiver(sync_env, kind, apikey):
    env = sync_env
    entry = env.asset()
    assert env.run()['state'] == 'complete'

    def snapshot():
        with env.nas.app_context():
            camera = env.models.IndiAllSkyDbCameraTable.query.one()
            image = env.models.IndiAllSkyDbImageTable.query.one()
            return (camera.id, camera.name, camera.utc_offset, image.id, image.filename,
                    image.getFilesystemPath().read_bytes())

    before = snapshot()
    if kind == 'camera':
        metadata = dict(id=env.camera.sync_id, camera_uuid=env.camera.uuid,
                        uuid=env.camera.uuid, name='Must not overwrite camera')
    else:
        metadata = env.sync.metadata_for(entry, env.sync.constants.IMAGE)
        # A mismatch requests a later upload; the lookup itself must not repair
        # media or update the camera timezone, even with valid credentials.
        metadata.update(expected_size=entry.getFilesystemPath().stat().st_size,
                        sha256='0' * 64, utc_offset=before[2] + 3600)
    client = env.transport.requests_syncapi_v1(env.config, quiet=True)
    client.connect(hostname='https://nas/indi-allsky/sync/v1/' + kind, username='tester', apikey=apikey)
    try:
        if apikey == 'incorrect-key':
            with pytest.raises(env.errors.AuthenticationFailure):
                client.put(local_file='camera', metadata=metadata, empty_file=True, lookup=True)
        else:
            result = client.put(local_file='camera', metadata=metadata, empty_file=True, lookup=True)
            assert result == ({'id': env.camera.sync_id} if kind == 'camera' else
                              {'lookup_supported': True, 'present': False})
    finally:
        client.close()
    assert snapshot() == before


def test_lookup_routes_reject_upload_methods_and_unsigned_requests(sync_env):
    env = sync_env
    client = env.nas.test_client()
    for endpoint in env.sync.constants.ENDPOINT_V1.values():
        url = '/indi-allsky/' + endpoint + '/lookup'
        for method in ('GET', 'PUT', 'DELETE'):
            assert client.open(url, method=method).status_code == 405
        assert client.post(url).status_code == 400
    with env.nas.app_context():
        assert env.models.IndiAllSkyDbCameraTable.query.count() == 0
        assert env.models.IndiAllSkyDbImageTable.query.count() == 0


@pytest.mark.parametrize('status', [404, 405])
def test_missing_lookup_endpoint_does_not_fall_back_to_get_or_upload(sync_env, monkeypatch, status):
    env = sync_env
    env.asset()
    receiver = env.nas.wsgi_app

    def old_receiver(environ, start_response):
        if environ['PATH_INFO'].endswith('/lookup'):
            return Response('Lookup unavailable', status=status)(environ, start_response)
        return receiver(environ, start_response)

    monkeypatch.setattr(env.nas, 'wsgi_app', old_receiver)
    result = env.run()
    assert result['state'] == 'failed' and 'Update the receiver' in result['message']
    assert [(method, path) for method, path, _ in env.calls] == [
        ('PUT', '/indi-allsky/sync/v1/camera'),
        ('POST', '/indi-allsky/sync/v1/image/lookup'),
    ]
