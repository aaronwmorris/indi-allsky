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
