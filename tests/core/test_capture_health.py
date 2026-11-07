import ast
from contextlib import nullcontext
import json
import logging
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from indi_allsky.capture_health import CameraImageQueue, CaptureHealth, ExposureDeadline, RestartDelay


def test_deadline_requires_a_real_frame_and_a_ready_driver():
    d = ExposureDeadline(60)
    assert d.poll(999_999, True, 0) == 'ready'  # idle schedules create no deadline
    d.start(100, 180, 4)
    assert d.poll(275, True, 4) == 'wait'  # READY can arrive before the BLOB
    assert d.poll(278, False, 5) == 'wait'
    assert d.poll(280, True, 5) == 'ready'
    assert d.poll(1_000_000, True, 5) == 'ready'


def test_abort_retry_then_reconnect_without_faking_ready():
    d = ExposureDeadline(60)
    d.start(100, 10, 4)
    assert d.poll(161, False, 4) == 'abort'
    assert d.poll(168, False, 4) == 'wait'
    assert d.poll(170, True, 4) == 'retry'
    d.start(180, 10, 4)
    assert d.poll(181, True, 4, failed=True) == 'abort'
    assert d.poll(182, False, 4) == 'wait'
    assert d.poll(197, False, 4) == 'reconnect'


def test_queue_records_only_nonempty_capture_files(tmp_path):
    q, health = Queue(), CaptureHealth()
    proxy = CameraImageQueue(q, health)
    path = tmp_path / 'raw.jpg'
    proxy.put({'filename': str(path)})
    path.touch()
    proxy.put({'filename': str(path)})
    path.write_bytes(b'frame')
    proxy.put({'filename': str(path)})
    assert q.qsize() == 3 and health.frames.value == 1
    assert health.status(None)['raw_received'] is not None


def test_health_detects_frozen_worker_and_continued_rejections():
    health = CaptureHealth()
    health.pulse.value = health.image_pulse.value = 200
    health.capture_stage('idle')
    health.pulse.value = 100
    assert health.stalled(580, 330) == 'capture'
    health.pulse.value = 580
    assert health.stalled(590, 330) is None
    assert health.stalled(591, 330) == 'image'
    health.image_pulse.value = 590
    for now in (200, 350, 440, 590):
        health.publication_result(False, now, 390)
    assert health.stalled(590, 330) == 'image'
    health.capture_stage('paused')
    assert health.stalled(590, 330) is None
    health.capture_stage('idle')
    health.publication_result(True, 590, 390)
    assert health.stalled(590, 330) is None
    for now in (591, 602, 1200):
        health.publication_result(False, now, 390)
    assert health.misses.value == 1  # a genuine scheduling gap


def test_exited_pid_is_throttled_once_and_good_progress_resets_backoff():
    policy = RestartDelay()
    assert policy.ready(None, 0, 0)
    first = SimpleNamespace(pid=7)
    assert not policy.ready(first, 100, 0)
    assert not policy.ready(first, 110, 0)
    assert policy.ready(first, 115, 0)
    second = SimpleNamespace(pid=8)
    assert not policy.ready(second, 120, 0)
    assert policy.ready(second, 150, 0)
    third = SimpleNamespace(pid=9)
    assert not policy.ready(third, 180, 5)
    assert policy.ready(third, 195, 5)
    assert policy.ready(None, 196, 5)


def test_supervisor_scopes_recovery_to_same_pid_and_ignores_planned_stop():
    path = Path(__file__).resolve().parents[2] / 'indi_allsky/allsky.py'
    cls = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'IndiAllSky')
    method = next(n for n in cls.body if getattr(n, 'name', None) == '_check_capture_health')
    tick = 1000
    scope = dict(time=SimpleNamespace(monotonic=lambda: tick, time=lambda: tick), json=json,
                 app=SimpleNamespace(app_context=nullcontext), logger=logging.getLogger('indi_allsky'))
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), scope)
    poll = scope[method.name]
    worker = Mock(pid=11, name='image')
    service = SimpleNamespace(config={}, capture_health=CaptureHealth(), _shutdown=False, _reload=True,
                              pending_recovery=None, health_write_time=0, image_worker=worker,
                              recovery_history={'image': []}, _miscDb=Mock(),
                              _exit_service=Mock(side_effect=SystemExit(75)))
    service.capture_health.image_pulse.value = 100
    poll(service)
    worker.terminate.assert_not_called()
    service._reload = False
    poll(service)
    worker.terminate.assert_called_once()
    assert service.pending_recovery == ('image', 11, 1000)

    # A fresh worker arriving inside the grace period is never killed on
    # account of its predecessor's signal.
    service.image_worker = Mock(pid=12)
    service.capture_health.image_pulse.value = tick
    tick += 31
    poll(service)
    assert service.pending_recovery is None
    service._exit_service.assert_not_called()

    service.capture_health.image_pulse.value = 1
    poll(service)
    service.image_worker.terminate.assert_called_once()
    tick += 30
    with pytest.raises(SystemExit):
        poll(service)
    service._exit_service.assert_called_once_with(75)

    # Suppress a third recovery within an hour instead of cycling workers.
    service.image_worker = Mock(pid=13)
    poll(service)
    service.image_worker.terminate.assert_not_called()
