"""Exercise the real acquisition loop without optional camera/INDI imports."""

import ast
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy
import pytest

from indi_allsky.temperature import master_capture_temperature
from indi_allsky import dark_automation


class BadImage(Exception):
    pass


@pytest.fixture
def acquisition(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[2] / 'indi_allsky' / 'darks.py'
    capture_class = next(node for node in ast.parse(source.read_text(encoding='utf-8')).body
                         if isinstance(node, ast.ClassDef) and node.name == 'IndiAllSkyDarks')
    methods = [node for node in capture_class.body if isinstance(node, ast.FunctionDef)
               and node.name in ('_take_exposures', '_sleep_interruptibly', '_check_shutdown')]
    clock = SimpleNamespace(now=0.0, cancel_at=None, stacking_seconds=0.0, bpm_seconds=0.0)
    events = []
    capture = SimpleNamespace(
        automation_manifest={'automation': True}, count=3, _shutdown=False,
        _pre_shoot_reconfigure=lambda: None, _resolve_automation_geometry=lambda *args: None,
        getCcdTemperature=lambda: 20.0,
        camera_id=1, capture_profile='night', image_dir=tmp_path, darks_dir=tmp_path,
        config={}, exposure_av=None, gain_av=None, binning_av=None, bitmax=16, hotpixel_adu_percent=90,
        _expUtils=SimpleNamespace(GAIN_CURRENT=0, BINNING_CURRENT=1),
    )

    def sleep(seconds):
        clock.now += seconds
        if clock.cancel_at is not None and clock.now >= clock.cancel_at:
            capture._shutdown = True

    def progress(phase, message, current_frame=None):
        events.append((phase, clock.now, current_frame))

    def shoot(exposure, *args, **kwargs):
        events.append(('shoot', clock.now))
        clock.now += exposure

    class Image(list):
        def writeto(self, file):
            file.write(b'fake image')

    capture.shoot = shoot
    capture._publish_progress = progress
    capture._wait_for_image = lambda exposure: Image([
        SimpleNamespace(data=numpy.ones((2, 2)), header={'BITPIX': 16}),
    ])
    capture._automation_frame_data = lambda *args: {'automation': True} if capture.automation_manifest.get('automation') else {}
    capture._miscDb = SimpleNamespace(
        addBadPixelMap=lambda *args, **kwargs: SimpleNamespace(),
        addDarkFrame=lambda *args, **kwargs: SimpleNamespace(),
    )

    def checkpoint(*args):
        events.append(('activate', clock.now))
        return {'activated': 2, 'deactivated': 0}

    monkeypatch.setattr(dark_automation, 'checkpoint_master_pair', checkpoint)

    class Stacker:
        def __init__(self, *args):
            pass

        def stack(self, source, output, *args, **kwargs):
            events.append(('stack', clock.now))
            sleep(clock.stacking_seconds)
            output.write_bytes(b'dark')
            return 1, 0

        def buildBadPixelMap(self, source, output, *args, **kwargs):
            events.append(('bpm', clock.now))
            sleep(clock.bpm_seconds)
            output.write_bytes(b'map')
            return 1, 0

    capture.take = lambda exposure: capture._take_exposures(exposure, 0, 1, 'dark_test_{2:d}.fit', 'bpm_test_{2:d}.fit', Stacker)
    namespace = {
        '__name__': 'indi_allsky.darks', 'datetime': datetime,
        'Path': Path, 'numpy': numpy, 'BadImage': BadImage,
        'constants': SimpleNamespace(DARK_FRAME=1, BPM_FRAME=2),
        'IndiAllSkyDbDarkFrameTable': object, 'IndiAllSkyDbBadPixelMapTable': object,
        'db': SimpleNamespace(session=SimpleNamespace(
            commit=lambda: events.append(('commit', clock.now)),
            rollback=lambda: events.append(('rollback', clock.now)),
        )),
        'master_capture_temperature': master_capture_temperature,
        'logger': logging.getLogger(__name__),
        'time': SimpleNamespace(monotonic=lambda: clock.now, time=lambda: clock.now, sleep=sleep),
        'tempfile': SimpleNamespace(
            TemporaryDirectory=lambda **kwargs: tempfile.TemporaryDirectory(dir=tmp_path, **kwargs),
            NamedTemporaryFile=tempfile.NamedTemporaryFile,
        ),
    }
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(source), 'exec'), namespace)
    for method in methods:
        setattr(capture, method.name, namespace[method.name].__get__(capture))
    return capture, clock, events


@pytest.mark.parametrize('manifest,delay,exposure', [
    ({'automation': True}, 0, 1),
    ({'automation': True, 'exposure_delay': 0}, 0, 1),
    ({'automation': True, 'exposure_delay': 2.5}, 2.5, 1),
    ({'exposure_delay': 2.5}, 0, 1),  # Legacy captures retain their existing timing.
    ({'automation': True, 'exposure_delay': 'exposure'}, 1, 1),
    ({'automation': True, 'exposure_delay': 'exposure'}, 5, 5),
    ({'automation': True, 'exposure_delay': 'exposure'}, 10, 10),
    ({'automation': True, 'exposure_delay': 'exposure'}, 0.25, 0.25),
    ({'exposure_delay': 'exposure'}, 0, 1),
])
def test_every_source_image_gets_cooldown_with_final_wait_overlapping_stacking(acquisition, manifest, delay, exposure):
    capture, clock, events = acquisition
    capture.automation_manifest = manifest
    capture.take(exposure)
    assert [event[1] for event in events if event[0] == 'shoot'] == [0, exposure + delay, 2 * (exposure + delay)]
    assert clock.now == 3 * (exposure + delay)  # The final image cools down before this set finishes.
    assert [event[1] for event in events if event[0] == 'stack'] == [3 * exposure + 2 * delay]


@pytest.mark.parametrize('delay', [2.5, 'exposure'])
def test_bad_image_retry_also_waits_for_cooldown(acquisition, delay):
    capture, clock, events = acquisition
    capture.automation_manifest['exposure_delay'] = delay
    receive_image = capture._wait_for_image

    def reject_first(exposure):
        capture._wait_for_image = receive_image
        raise BadImage('Invalid frame')

    capture._wait_for_image = reject_first
    capture.take(1)
    interval = 2 if delay == 'exposure' else 3.5
    assert [event[1] for event in events if event[0] == 'shoot'] == [0, interval, 2 * interval, 3 * interval]


@pytest.mark.parametrize('delay,cancel_at', [(2.5, 1.5), (2.5, 3.5), ('exposure', 1.5), ('exposure', 2)])
def test_cancellation_during_or_at_end_of_delay_prevents_next_exposure(acquisition, delay, cancel_at):
    capture, clock, events = acquisition
    capture.automation_manifest['exposure_delay'] = delay
    clock.cancel_at = cancel_at
    with pytest.raises(KeyboardInterrupt):
        capture.take(1)
    assert len([event for event in events if event[0] == 'shoot']) == 1
    assert clock.now == cancel_at
    assert not any(event[0] == 'stacking' for event in events)


@pytest.mark.parametrize('delay,exposures,starts', [
    ('exposure', [10, 5, 1], [0, 20, 40, 60, 70, 80, 90, 92, 94]),
    ('exposure', [1, 5, 10], [0, 2, 4, 6, 16, 26, 36, 56, 76]),
    (2.5, [10, 5, 1], [0, 12.5, 25, 37.5, 45, 52.5, 60, 63.5, 67]),
    (2.5, [1, 5, 10], [0, 3.5, 7, 10.5, 18, 25.5, 33, 45.5, 58]),
])
def test_delay_spans_master_set_boundaries(acquisition, delay, exposures, starts):
    capture, clock, events = acquisition
    capture.automation_manifest['exposure_delay'] = delay
    for exposure in exposures:
        capture.take(exposure)
    assert [event[1] for event in events if event[0] == 'shoot'] == starts


@pytest.mark.parametrize('delay,cancel_at', [(2.5, 8.5), (2.5, 10.5), ('exposure', 5.5), ('exposure', 6)])
def test_cancellation_in_final_cooldown_discards_pair_and_prevents_next_set(acquisition, delay, cancel_at):
    capture, clock, events = acquisition
    capture.automation_manifest['exposure_delay'] = delay
    clock.cancel_at = cancel_at
    with pytest.raises(KeyboardInterrupt):
        capture.take(1)
        capture.take(5)
    assert len([event for event in events if event[0] == 'shoot']) == 3
    assert clock.now == cancel_at
    assert any(event[0] == 'stacking' for event in events)
    assert not any(event[0] == 'activate' for event in events)
    assert ('rollback', cancel_at) in events
    assert list(capture.image_dir.iterdir()) == []


@pytest.mark.parametrize('delay', [0, 2.5, 'exposure'])
@pytest.mark.parametrize('stacking_seconds,bpm_seconds', [(0.5, 0.5), (1, 1.5), (4, 6), (0, 12)])
def test_next_set_waits_for_longer_of_cooldown_and_master_creation(acquisition, delay, stacking_seconds, bpm_seconds):
    capture, clock, events = acquisition
    capture.automation_manifest['exposure_delay'] = delay
    clock.stacking_seconds = stacking_seconds
    clock.bpm_seconds = bpm_seconds
    capture.take(10)
    final_image_time = 30 + 2 * (10 if delay == 'exposure' else delay)
    next_set_time = final_image_time + max(10 if delay == 'exposure' else delay, stacking_seconds + bpm_seconds)
    assert [event[1] for event in events if event[0] == 'stack'] == [final_image_time]
    assert clock.now == next_set_time
    assert ('commit', next_set_time) in events
    capture.take(5)
    assert [event[1] for event in events if event[0] == 'shoot'][3] == next_set_time


def test_cancellation_while_building_during_cooldown_discards_pair(acquisition):
    capture, clock, events = acquisition
    capture.automation_manifest['exposure_delay'] = 'exposure'
    clock.stacking_seconds = 1
    clock.bpm_seconds = 1
    clock.cancel_at = 5.5
    with pytest.raises(KeyboardInterrupt):
        capture.take(1)
    assert not any(event[0] == 'activate' for event in events)
    assert list(capture.image_dir.iterdir()) == []
