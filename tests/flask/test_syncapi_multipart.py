"""Exercise real streamed multipart encoding and Werkzeug parsing, without a server."""

from functools import partial
import hashlib
import io
import json
from types import SimpleNamespace

import pytest
from requests_toolbelt import MultipartEncoder
from werkzeug.formparser import MultiPartParser


BOUNDARY = 'b' * 32


def client_for(env, quiet=True):
    client = env.transport.requests_syncapi_v1(env.config, quiet=quiet)
    client.connect(hostname='https://nas/indi-allsky/sync/v1/image', username='tester', apikey='test-api-key')
    return client


@pytest.mark.parametrize('chunk_size', [256, 1024, 65536])
@pytest.mark.parametrize('tail', [b'X', b'\r', b'\n', b'\r\n'])
def test_streamed_media_survives_delimiter_splits(sync_env, monkeypatch, tmp_path, chunk_size, tail):
    env = sync_env
    path = tmp_path / 'test.jpg'
    client = client_for(env)
    monkeypatch.setattr(env.transport, 'MultipartEncoder', partial(MultipartEncoder, boundary=BOUNDARY))

    def receive(url, **kwargs):
        encoder = kwargs['data']
        # Construction must not consume the file or buffer the entire upload.
        assert encoder.fields['media'][1].tell() == 0
        body = b''.join(iter(lambda: encoder.read(8192), b''))
        _, files = MultiPartParser(buffer_size=chunk_size).parse(io.BytesIO(body), BOUNDARY.encode(), len(body))
        try:
            assert files['media'].read() == media
            assert files['metadata'].read() == json.dumps(metadata).encode()
        finally:
            for part in files.values():
                part.close()
        return SimpleNamespace(status_code=200, text='{"id": 1}')

    monkeypatch.setattr(env.transport.requests, 'put', receive)
    # Sweep both the media delimiter and the final closing delimiter across
    # read boundaries, including binary files with legitimate CR/LF endings.
    for size in range(2 * chunk_size - 512, 2 * chunk_size):
        media = (bytes(range(256)) * (size // 256 + 1))[:size] + tail
        path.write_bytes(media)
        metadata = {'type': 1}
        assert client.put(local_file=path, metadata=metadata, empty_file=False)['id'] == 1


@pytest.mark.parametrize('kind', ['panoramaimage', 'video'])
def test_archive_upload_at_original_fault_alignment(sync_env, monkeypatch, kind):
    env = sync_env
    entry = env.asset(kind)
    path = entry.getFilesystemPath()
    metadata = env.sync.metadata_for(entry, env.sync.MEDIA[kind][1])
    size = 1178511
    for _ in range(3):
        metadata['file_size'] = size
        old_encoder = MultipartEncoder(fields={
            'metadata': ('metadata.json', json.dumps(metadata), 'application/json'),
            'media': (path.name, b'X' * size, 'application/octet-stream'),
        }, boundary=BOUNDARY)
        if old_encoder.len % 65536 == 3:
            break
        size += 3 - old_encoder.len % 65536
    assert old_encoder.len % 65536 == 3
    # At this alignment the old closing delimiter ends a chunk after its
    # first trailing dash. Werkzeug 3.1.6 and 3.1.8 append its CR to the media.
    original = b'X' * (size - 2) + b'\r\n'
    path.write_bytes(original)
    monkeypatch.setattr(env.transport, 'MultipartEncoder', partial(MultipartEncoder, boundary=BOUNDARY))
    result = env.run([kind])
    assert result['state'] == 'complete', result
    assert result['files'] == 1 and entry.sync_id
    with env.nas.app_context():
        stored = env.sync.MEDIA[kind][0].query.one().getFilesystemPath().read_bytes()
        assert len(stored) == len(original)
        assert hashlib.sha256(stored).digest() == hashlib.sha256(original).digest()


@pytest.mark.parametrize('change', ['extra_cr', 'truncated'])
def test_damaged_media_is_rejected_without_authentication_error(sync_env, monkeypatch, change):
    env = sync_env
    entry = env.asset()
    assert env.run()['state'] == 'complete'
    entry.sync_id = None
    env.db.session.commit()
    with env.nas.app_context():
        remote = env.models.IndiAllSkyDbImageTable.query.one()
        remote_id, remote_path = remote.id, remote.getFilesystemPath()
        # Force a repair upload, whose failure must leave this file untouched.
        remote_path.write_bytes(b'existing receiver file')
    original_save = env.receiver.SyncApiBaseView.saveMedia
    temporary_paths = []

    def damaged_save(view, media_file):
        path = original_save(view, media_file)
        data = path.read_bytes()
        path.write_bytes(data + b'\r' if change == 'extra_cr' else data[:-1])
        temporary_paths.append(path)
        return path

    monkeypatch.setattr(env.receiver.SyncApiBaseView, 'saveMedia', damaged_save)
    result = env.run()
    assert result['state'] == 'failed'
    assert result['reason'] == 'configuration_or_receiver'
    assert 'media size does not match' in result['message']
    assert entry.getFilesystemPath().name in result['message']
    assert 'authentication' not in result['message']
    assert result['files'] == 0 and entry.sync_id is None
    assert len(temporary_paths) == 1 and not temporary_paths[0].exists()
    with env.nas.app_context():
        assert env.models.IndiAllSkyDbImageTable.query.one().id == remote_id
        assert remote_path.read_bytes() == b'existing receiver file'


@pytest.mark.parametrize('quiet', [False, True])
def test_size_mismatch_response_in_both_transfer_modes(sync_env, monkeypatch, quiet):
    env = sync_env
    entry = env.asset()
    monkeypatch.setattr(env.transport.requests, 'put', lambda *a, **k: SimpleNamespace(
        status_code=400, json=lambda: {'error': 'media_size_mismatch'}))
    with pytest.raises(env.errors.TransferFailure, match='media size does not match'):
        client_for(env, quiet=quiet).put(local_file=entry.getFilesystemPath(), metadata={}, empty_file=False)


def test_invalid_signature_still_fails_authentication(sync_env):
    env = sync_env
    entry = env.asset()
    client = client_for(env)
    client.apikey = 'incorrect-key'
    with pytest.raises(env.errors.AuthenticationFailure, match='authentication failed'):
        client.put(local_file=entry.getFilesystemPath(), metadata={}, empty_file=False)
    with env.nas.app_context():
        assert env.models.IndiAllSkyDbImageTable.query.count() == 0
