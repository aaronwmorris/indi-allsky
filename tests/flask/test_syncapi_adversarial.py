"""Hostile and accidental inputs against disposable SyncAPI receiver databases."""
import hashlib
import hmac
import io
import json
import math
import os
from pathlib import Path
import subprocess
import time

import pytest


def signed(env, route, metadata, *, header=None, bucket_offset=0, method='POST', media=None):
    payload = metadata if isinstance(metadata, bytes) else json.dumps(metadata).encode()
    digest = hmac.new(b'test-api-key', str(math.floor(time.time() / 300) + bucket_offset).encode() + payload,
                      hashlib.sha3_512).hexdigest()
    headers = {'Authorization': header if header is not None else 'Bearer tester:' + digest}
    data = {'metadata': (io.BytesIO(payload), 'metadata.json'), 'syncapi_end': ''}
    if media is not None:
        data['media'] = (io.BytesIO(media), 'upload.jpg')
    env.nas.config['PROPAGATE_EXCEPTIONS'] = False
    return env.nas.test_client().open('/indi-allsky/sync/v1/' + route,
                                    method=method, headers=headers, data=data)


@pytest.mark.parametrize('header', ['', 'Bearer', 'Bearer unknown:123', 'Bearer tester:wrong',
                                   'Bearer tester:a:b', 'Bearer  tester:123', 'Basic tester:123',
                                   'Bearer tester:\u00e9', 'Bearer tester:' + '\u00e9' * 128,
                                   "Bearer ' OR 1=1--:123"])
def test_malformed_authentication_is_a_client_error_without_writes(sync_env, header):
    env = sync_env
    response = signed(env, 'camera/lookup', {'id': 0, 'camera_uuid': env.camera.uuid}, header=header)
    assert 400 <= response.status_code < 500, response.get_data(as_text=True)
    with env.nas.app_context():
        assert env.models.IndiAllSkyDbCameraTable.query.count() == 0


@pytest.mark.parametrize('route', ['camera/lookup', 'image/lookup', 'thumbnail/lookup'])
@pytest.mark.parametrize('payload', [b'{broken', b'\xff', None, [], 'text', 42, {},
                                    {'camera_uuid': []}, {'camera_uuid': {}}])
def test_signed_malformed_lookup_metadata_is_a_client_error(sync_env, route, payload):
    env = sync_env
    response = signed(env, route, payload)
    assert 400 <= response.status_code < 500, response.get_data(as_text=True)
    with env.nas.app_context():
        assert env.models.IndiAllSkyDbImageTable.query.count() == 0


@pytest.mark.parametrize('delta,accepted', [(-5, False), (-4, True), (0, True), (1, True), (2, False)])
def test_signature_clock_window(sync_env, monkeypatch, delta, accepted):
    env = sync_env
    monkeypatch.setattr(time, 'time', lambda: 1800000000)
    response = signed(env, 'camera/lookup', {'id': 0, 'camera_uuid': env.camera.uuid}, bucket_offset=delta)
    assert response.status_code == 400
    assert response.get_json()['error'] == ('camera_missing' if accepted else 'authentication failed')


@pytest.mark.parametrize('field,value', [('expected_size', 0), ('expected_size', -1), ('expected_size', True),
                                       ('expected_size', '16'), ('sha256', None), ('sha256', 'x' * 64),
                                       ('sha256', '0' * 63), ('sha256', '+' + '0' * 63),
                                       ('createDate', None), ('createDate', True), ('createDate', float('nan')),
                                       ('createDate', 10**100), ('utc_offset', 'bad'), ('utc_offset', float('inf'))])
def test_invalid_lookup_fields_cannot_modify_an_existing_asset(sync_env, field, value):
    env = sync_env
    entry = env.asset()
    assert env.run()['state'] == 'complete'
    source_bytes = entry.getFilesystemPath().read_bytes()
    metadata = env.sync.metadata_for(entry, env.sync.constants.IMAGE)
    metadata.update(expected_size=len(source_bytes), sha256=hashlib.sha256(source_bytes).hexdigest())
    metadata[field] = value
    response = signed(env, 'image/lookup', metadata)
    assert response.status_code == 400
    with env.nas.app_context():
        assert env.models.IndiAllSkyDbImageTable.query.one().getFilesystemPath().read_bytes() == source_bytes


def test_lookup_ignores_injected_paths_and_media(sync_env, tmp_path):
    env = sync_env
    entry = env.asset()
    assert env.run()['state'] == 'complete'
    sentinel = tmp_path / 'outside-receiver.jpg'
    sentinel.write_bytes(b'must remain intact')
    source_bytes = entry.getFilesystemPath().read_bytes()
    metadata = env.sync.metadata_for(entry, env.sync.constants.IMAGE)
    metadata.update(expected_size=len(source_bytes), sha256=hashlib.sha256(source_bytes).hexdigest(),
                    filename=str(sentinel), uuid=str(sentinel.with_suffix('')), overwrite=True)
    response = signed(env, 'image/lookup', metadata, media=b'hostile replacement')
    assert response.status_code == 200 and response.get_json()['present'] is True
    assert sentinel.read_bytes() == b'must remain intact'


def test_signed_thumbnail_upload_cannot_escape_receiver_root(sync_env, tmp_path):
    env = sync_env
    entry = env.asset()
    assert env.run()['state'] == 'complete'
    thumb = env.thumbnail(entry)
    parent = env.sync.metadata_for(entry, env.sync.constants.IMAGE)
    metadata = env.sync.metadata_for(thumb, env.sync.constants.THUMBNAIL, parent)
    sentinel = tmp_path / 'outside-receiver.jpg'
    sentinel.write_bytes(b'must remain intact')
    # Only the disposable sentinel is targeted, never a real system file.
    metadata.update(uuid=str(sentinel.with_suffix('')), file_size=7)
    response = signed(env, 'thumbnail', metadata, method='PUT', media=b'changed')
    assert response.status_code == 400
    assert sentinel.read_bytes() == b'must remain intact', f'Escaped archive root; HTTP {response.status_code}'


def test_disabled_account_cannot_use_existing_sync_api_key(sync_env):
    env = sync_env
    with env.nas.app_context():
        user = env.models.IndiAllSkyDbUserTable.query.one()
        user.active = False
        env.db.session.commit()
    response = signed(env, 'camera/lookup', {'id': 0, 'camera_uuid': env.camera.uuid})
    assert response.get_json() == {'error': 'authentication failed'}


def test_large_unsigned_metadata_is_rejected_without_database_writes(sync_env):
    env = sync_env
    metadata = {'id': 0, 'camera_uuid': env.camera.uuid, 'padding': 'X' * (2 * 1024 * 1024)}
    response = signed(env, 'camera/lookup', metadata, header='Bearer tester:invalid')
    assert response.status_code == 400 and response.get_json() == {'error': 'authentication failed'}
    with env.nas.app_context():
        assert env.models.IndiAllSkyDbCameraTable.query.count() == 0


@pytest.mark.parametrize('identifier', ['../outside', '/tmp/outside', r'..\outside', r'C:\outside',
                                      r'\\server\share', '.', '', None, [], {}])
@pytest.mark.parametrize('kind', ['camera', 'thumbnail'])
def test_upload_rejects_unsafe_identifiers_before_inserting_rows(sync_env, kind, identifier):
    env = sync_env
    camera_metadata = env.sync.metadata_for(env.camera, env.sync.constants.CAMERA)
    if kind == 'camera':
        metadata = camera_metadata
    else:
        assert signed(env, 'camera', camera_metadata, method='PUT').status_code == 200
        entry = env.asset()
        metadata = env.sync.metadata_for(env.thumbnail(entry), env.sync.constants.THUMBNAIL,
                                         env.sync.metadata_for(entry, env.sync.constants.IMAGE))
    metadata.update(uuid=identifier, file_size=7)
    response = signed(env, kind, metadata, method='PUT', media=b'changed')
    assert response.status_code == 400
    with env.nas.app_context():
        model = env.models.IndiAllSkyDbCameraTable if kind == 'camera' else env.models.IndiAllSkyDbThumbnailTable
        assert model.query.count() == 0
    assert not list(Path(env.nas.config['INDI_ALLSKY_IMAGE_FOLDER']).rglob('*'))


@pytest.mark.parametrize('kind', ['image', 'video', 'thumbnail'])
def test_upload_rejects_symlink_escape(sync_env, tmp_path, kind):
    env = sync_env
    entry = env.asset('image' if kind == 'thumbnail' else kind)
    metadata = env.sync.metadata_for(entry, env.sync.MEDIA['image' if kind == 'thumbnail' else kind][1])
    if kind == 'thumbnail':
        metadata = env.sync.metadata_for(env.thumbnail(entry), env.sync.constants.THUMBNAIL, metadata)
    camera_uuid = env.camera.uuid
    assert signed(env, 'camera', env.sync.metadata_for(env.camera, env.sync.constants.CAMERA), method='PUT').status_code == 200
    outside = tmp_path / 'outside'
    outside.mkdir()
    link = Path(env.nas.config['INDI_ALLSKY_IMAGE_FOLDER']) / ('ccd_' + camera_uuid)
    if os.name == 'nt':
        # Directory junctions exercise real path resolution without requiring
        # Windows' elevated privilege for creating symbolic links.
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                       check=True, capture_output=True, timeout=10)
    else:
        link.symlink_to(outside, target_is_directory=True)
    try:
        metadata['file_size'] = 7
        response = signed(env, kind, metadata, method='PUT', media=b'changed')
        assert response.status_code == 400
        assert not list(outside.rglob('*'))
        with env.nas.app_context():
            model = env.models.IndiAllSkyDbThumbnailTable if kind == 'thumbnail' else env.sync.MEDIA[kind][0]
            assert model.query.count() == 0
    finally:
        if os.name == 'nt':
            link.rmdir()
        else:
            link.unlink()


@pytest.mark.parametrize('kind,method', [('image', 'PUT'), ('video', 'PUT'), ('image', 'DELETE')])
def test_existing_unsafe_record_cannot_delete_outside_media_root(sync_env, tmp_path, kind, method):
    env = sync_env
    entry = env.asset(kind)
    assert env.run([kind])['state'] == 'complete'
    metadata = env.sync.metadata_for(entry, env.sync.MEDIA[kind][1])
    media = entry.getFilesystemPath().read_bytes()
    metadata.update(id=entry.sync_id, file_size=len(media))
    sentinel = tmp_path / 'existing-outside.jpg'
    sentinel.write_bytes(b'must remain intact')
    with env.nas.app_context():
        remote = env.sync.MEDIA[kind][0].query.one()
        remote.filename = str(sentinel)
        env.db.session.commit()
    response = signed(env, kind, metadata, method=method, media=media)
    assert response.status_code == 400
    assert sentinel.read_bytes() == b'must remain intact'
    with env.nas.app_context():
        assert env.sync.MEDIA[kind][0].query.one().filename == str(sentinel)


def test_thumbnail_post_rejects_existing_file_without_replacing_it(sync_env):
    env = sync_env
    entry = env.asset()
    thumb = env.thumbnail(entry)
    assert env.run()['state'] == 'complete'
    metadata = env.sync.metadata_for(thumb, env.sync.constants.THUMBNAIL,
                                     env.sync.metadata_for(entry, env.sync.constants.IMAGE))
    metadata['file_size'] = 7
    expected = thumb.getFilesystemPath().read_bytes()
    response = signed(env, 'thumbnail', metadata, media=b'changed')
    assert response.status_code == 400 and response.get_json() == {'error': 'file_exists'}
    with env.nas.app_context():
        assert env.models.IndiAllSkyDbThumbnailTable.query.one().getFilesystemPath().read_bytes() == expected


@pytest.mark.parametrize('scheme,accepted', [('Bearer', True), ('bearer', True), ('Basic', False)])
def test_signed_request_requires_bearer_scheme(sync_env, monkeypatch, scheme, accepted):
    env = sync_env
    # Use a fixed bucket so a wall-clock boundary cannot invalidate the test.
    monkeypatch.setattr(time, 'time', lambda: 1800000000)
    metadata = {'id': 0, 'camera_uuid': env.camera.uuid}
    payload = json.dumps(metadata).encode()
    digest = hmac.new(b'test-api-key', b'6000000' + payload, hashlib.sha3_512).hexdigest()
    response = signed(env, 'camera/lookup', payload, header=f'{scheme} tester:{digest}')
    assert response.status_code == 400
    assert response.get_json()['error'] == ('camera_missing' if accepted else 'authentication failed')


def test_account_without_api_key_is_rejected(sync_env):
    env = sync_env
    with env.nas.app_context():
        env.models.IndiAllSkyDbUserTable.query.one().apikey = None
        env.db.session.commit()
    response = signed(env, 'camera/lookup', {'id': 0, 'camera_uuid': env.camera.uuid})
    assert response.status_code == 400 and response.get_json() == {'error': 'authentication failed'}


@pytest.mark.parametrize('camera_id', [None, [], {}, '1', True, -1, 2**63])
def test_camera_lookup_rejects_invalid_id_without_query_errors(sync_env, camera_id):
    env = sync_env
    response = signed(env, 'camera/lookup', {'id': camera_id, 'camera_uuid': env.camera.uuid})
    assert response.status_code == 400 and response.get_json() == {'error': 'invalid metadata'}


@pytest.mark.parametrize('thumbnail_uuid', [None, [], {}, '../outside'])
def test_thumbnail_lookup_validates_uuid_before_querying(sync_env, thumbnail_uuid):
    env = sync_env
    assert env.run()['state'] == 'complete'  # Register a real receiver camera.
    response = signed(env, 'thumbnail/lookup', {'camera_uuid': env.camera.uuid, 'uuid': thumbnail_uuid,
                                               'expected_size': 7, 'sha256': '0' * 64})
    assert response.status_code == 400 and response.get_json() == {'error': 'invalid metadata'}


def test_rejected_upload_cleans_temporary_media(sync_env, monkeypatch):
    env = sync_env
    entry = env.asset()
    assert env.run()['state'] == 'complete'
    metadata = env.sync.metadata_for(env.thumbnail(entry), env.sync.constants.THUMBNAIL,
                                     env.sync.metadata_for(entry, env.sync.constants.IMAGE))
    metadata.update(uuid='../outside', file_size=7)
    paths = []
    original = env.receiver.SyncApiBaseView.saveMedia

    def record(view, media):
        path = original(view, media)
        paths.append(path)
        return path

    monkeypatch.setattr(env.receiver.SyncApiBaseView, 'saveMedia', record)
    assert signed(env, 'thumbnail', metadata, method='PUT', media=b'changed').status_code == 400
    assert len(paths) == 1 and not paths[0].exists()


def test_replacement_checks_thumbnail_path_before_deleting_parent(sync_env, tmp_path):
    env = sync_env
    entry = env.asset()
    env.thumbnail(entry)
    assert env.run()['state'] == 'complete'
    metadata = env.sync.metadata_for(entry, env.sync.constants.IMAGE)
    media = entry.getFilesystemPath().read_bytes()
    metadata['file_size'] = len(media)
    sentinel = tmp_path / 'old-thumbnail.jpg'
    sentinel.write_bytes(b'must remain intact')
    with env.nas.app_context():
        parent = env.models.IndiAllSkyDbImageTable.query.one()
        parent_id, parent_path = parent.id, parent.getFilesystemPath()
        env.models.IndiAllSkyDbThumbnailTable.query.one().filename = str(sentinel)
        env.db.session.commit()
    response = signed(env, 'image', metadata, method='PUT', media=media)
    assert response.status_code == 400
    assert sentinel.read_bytes() == b'must remain intact'
    assert parent_path.read_bytes() == media
    with env.nas.app_context():
        assert env.models.IndiAllSkyDbImageTable.query.one().id == parent_id
        assert env.models.IndiAllSkyDbThumbnailTable.query.one().filename == str(sentinel)
