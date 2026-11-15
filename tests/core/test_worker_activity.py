from multiprocessing import get_context

import pytest

from indi_allsky.worker_activity import WorkerActivity, media_phase, read_worker_activity


def _producer(config, pipe):
    capture = WorkerActivity(config, 'capture')
    image = WorkerActivity(config, 'image')
    media = WorkerActivity(config, 'media')
    capture.set(1, 'Capturing an image')
    image.set(1, 'Analyzing image')
    with media.during(1, 'Generating keogram and star trails', '20261114'):
        pipe.send(True)
        pipe.recv()
        with media.during(1, 'Encoding star-trail timelapse', '20261114'):
            capture.set(1, 'Waiting for next exposure')
            image.clear()
            pipe.send(True)
            pipe.recv()
        pipe.send(True)
        pipe.recv()
    image.set(2, 'Saving image')
    capture.clear()
    media.set(0, 'Backing up database', 'unexpected user text')
    pipe.send(True)
    pipe.recv()


def test_worker_locks_report_parallel_phases_and_clear_on_process_death(tmp_path):
    ctx = get_context('spawn')
    config = {'VARLIB_FOLDER': str(tmp_path)}
    left, right = ctx.Pipe()
    proc = ctx.Process(target=_producer, args=(config, right))
    proc.start()
    right.close()
    try:
        assert left.poll(8) and left.recv()
        assert read_worker_activity(config, 1) == [
            'Capturing an image', 'Analyzing image', 'Generating keogram and star trails · 2026-11-14']
        assert read_worker_activity(config, 1, include_capture=False) == [
            'Analyzing image', 'Generating keogram and star trails · 2026-11-14']
        assert not read_worker_activity(config, 2)
        left.send(True)
        assert left.poll(5) and left.recv()
        assert read_worker_activity(config, 1) == [
            'Waiting for next exposure', 'Encoding star-trail timelapse · 2026-11-14']
        left.send(True)
        assert left.poll(5) and left.recv()
        assert read_worker_activity(config, 1)[-1] == 'Generating keogram and star trails · 2026-11-14'
        left.send(True)
        assert left.poll(5) and left.recv()
        assert read_worker_activity(config, 1) == ['Backing up database']
        assert read_worker_activity(config, 2) == ['Saving image', 'Backing up database']
    finally:
        proc.kill()
        proc.join(timeout=5)
        left.close()
    assert not read_worker_activity(config, 1)
    assert not read_worker_activity(config, 2)


@pytest.mark.parametrize(('action', 'kwargs', 'label'), [
    ('generateKeogramStarTrails', {'night': False}, 'Generating keogram'),
    ('generateKeogramStarTrails', {'night': True}, 'Generating keogram and star trails'),
    ('generateVideo', {'night': True}, 'Generating nighttime timelapse'),
    ('generatePanoramaVideo', {'night': False}, 'Generating daytime panorama timelapse'),
    ('generateMiniVideo', {'panorama_image_id': 4}, 'Generating panorama mini timelapse'),
    ('generateMiniVideo', {}, 'Generating mini timelapse'),
    ('unknown', {}, None),
])
def test_media_phase_uses_actual_requested_product(action, kwargs, label):
    assert media_phase(action, kwargs) == label


def test_status_unavailable_does_not_break_work(tmp_path):
    (tmp_path / 'worker-activity').write_text('unavailable')
    config = {'VARLIB_FOLDER': str(tmp_path)}
    with WorkerActivity(config, 'image').during(42, 'Saving image'):
        assert read_worker_activity(config, 42) == []


def _progress_producer(config, pipe):
    import time
    from unittest.mock import patch

    media = WorkerActivity(config, 'media')
    media.set(7, 'Generating daytime panorama timelapse', '20261115')
    epoch = time.monotonic() - 80
    while True:
        command = pipe.recv()
        if command == 'end':
            media.finish_progress()
        elif command == 'retry':
            media.clear()
            media.set(7, 'Generating daytime panorama timelapse', '20261115')
        else:
            stage, done, total, offset = command
            with patch('indi_allsky.worker_activity.time.monotonic', return_value=epoch + offset):
                media.progress(stage, done, total)
        pipe.send(str(media.progress_path) if media.progress_path else '')


def test_progress_tracks_real_counts_eta_and_stage_lifetime(tmp_path):
    from pathlib import Path

    ctx = get_context('spawn')
    config = {'VARLIB_FOLDER': str(tmp_path)}
    left, right = ctx.Pipe()
    proc = ctx.Process(target=_progress_producer, args=(config, right))
    proc.start()
    right.close()
    def send(command):
        left.send(command)
        assert left.poll(8)
        return left.recv()
    def read():
        return read_worker_activity(config, 7, detailed=True)[0]
    sidecar = None
    try:
        stage = 'Preparing frames'
        sidecar = Path(send((stage, 0, 60, 0)))
        assert sidecar.is_file()
        marker = tmp_path / 'worker-activity/7-media'
        initial_mtime = marker.stat().st_mtime_ns
        assert read()['completed'] == 0 and read()['eta_seconds'] is None
        send((stage, 2, 60, 0.5))
        assert read()['completed'] == 0  # throttle in the RAM writer
        send((stage, 10, 60, 5))
        assert read()['completed'] == 10 and read()['eta_seconds'] is None  # long-stalled pass
        send(('Encoding frames', 0, 50, 65))
        send(('Encoding frames', 20, 50, 75))
        assert read() == {'role': 'media', 'label': 'Generating daytime panorama timelapse',
                          'day': '2026-11-15', 'stage': 'Encoding frames', 'completed': 20,
                          'total': 50, 'eta_seconds': 15}
        date_only = read_worker_activity(config, 7)
        assert date_only == ['Generating daytime panorama timelapse · 2026-11-15']
        assert marker.stat().st_mtime_ns == initial_mtime
        assert not read_worker_activity(config, 8, detailed=True)
        send('end')
        assert 'completed' not in read() and not sidecar.exists()
        send(('Encoding frames', 0, 12, 76))
        send(('Encoding frames', 12, 12, 76.1))
        assert read()['completed'] == 12
        send('retry')
        assert 'stage' not in read()
        send(('Stacking frames', 1, 9, 78))
    finally:
        proc.kill()
        proc.join(timeout=5)
        left.close()
        if sidecar:
            sidecar.unlink(missing_ok=True)
    assert not read_worker_activity(config, 7, detailed=True)


def test_tracking_counts_after_the_consumer_finishes_each_item(tmp_path, monkeypatch):
    from unittest.mock import Mock

    worker = WorkerActivity({'VARLIB_FOLDER': str(tmp_path)}, 'media')
    progress = Mock()
    finish = Mock()
    monkeypatch.setattr(worker, 'progress', progress)
    monkeypatch.setattr(worker, 'finish_progress', finish)
    items = worker.track('Stacking frames', [10, 20, 30], 3)
    assert next(items) == 10
    progress.assert_called_once_with('Stacking frames', 0, 3)
    assert next(items) == 20
    progress.assert_called_with('Stacking frames', 1, 3)
    items.close()
    finish.assert_called_once()


def test_missing_shared_progress_storage_does_not_interrupt_frames(tmp_path, monkeypatch):
    from indi_allsky import worker_activity

    monkeypatch.setattr(worker_activity, '_progress_file', lambda *args: tmp_path / 'missing' / 'progress')
    worker = WorkerActivity({'VARLIB_FOLDER': str(tmp_path)}, 'media')
    with worker.during(1, 'Generating keogram'):
        assert list(worker.track('Stacking frames', [1, 2, 3], 3)) == [1, 2, 3]
        assert worker.progress_fd is None
