from __future__ import annotations

import math
import queue
import statistics
import threading
import time

import numpy as np
import pytest

from indi_allsky.focus import controller as controller_mod
from indi_allsky.focus.controller import CameraInfo
from indi_allsky.focus.controller import FocusController
from indi_allsky.focus.controller import FocusService
from indi_allsky.focus.controller import MSG_OFF_GLARE
from indi_allsky.focus.exposure_search import ExposureSearch
from indi_allsky.focus.exposure_search import MSG_NO_STARS
from indi_allsky.focus.exposure_search import SearchStep
from indi_allsky.focus.tune import Tune
from indi_allsky.focus.frame import Stretch
from indi_allsky.focus.frame import unpack_header
from indi_allsky.focus.link import LinkClient
from indi_allsky.focus.link import LinkServer
from indi_allsky.focus.measure import grade
from indi_allsky.focus.rigs import RigDecision
from indi_allsky.focus.sources import RawFrame
from indi_allsky.focus.lens import Lens
from tests.focus import synth
from tests.focus.test_lens import FakeClock as LensClock
from tests.focus.test_lens import FakeDriver


SHAPE = (256, 256)
RIG = RigDecision('new', 'stills', 'test rig')
GRID = synth.grid_stars(SHAPE, 1.5, 20000)
# 16 stars from faint to bright: the faint ones grade weak at higher brightness limits
GRADED = [synth.Star(s.x, s.y, s.sigma, f) for s, f in zip(GRID, np.geomspace(300, 30000, len(GRID)))]


def wait_for(cond, timeout=5.0):
    deadline = time.monotonic() + timeout
    while True:
        value = cond()
        if value or time.monotonic() >= deadline:
            return value
        time.sleep(0.01)


class FakeClock(object):
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t


class Epoch(object):
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeSource(object):
    def __init__(self):
        self.frames = queue.Queue()
        self.calls = []
        self.whole = synth.frame(SHAPE)

    def start(self, roi, exposure, gain):
        self.calls.append(('start', roi, exposure, gain))

    def set_camera(self, exposure, gain):
        self.calls.append(('set_camera', exposure, gain))

    def whole_frame(self):
        self.calls.append(('whole_frame',))
        return self.whole

    def stop(self):
        self.calls.append(('stop',))

    def kinds(self):
        return [c[0] for c in self.calls]


def raw_frame(stars=(), t_end=1001.0, exposure=1.0, gain=100.0, background=synth.BACKGROUND, seed=synth.SEED):
    return RawFrame(synth.frame(SHAPE, stars=stars, background=background, seed=seed), 65535.0, 'RGGB',
                    t_end, exposure, gain)


class Page(object):
    """A LinkClient plus everything it has received so far."""

    def __init__(self, client):
        self.client = client
        self.got = []

    def next(self, pred, timeout=5.0, pump=None):
        """The oldest unclaimed message matching pred, reading more as needed. `pump` runs between reads."""
        deadline = time.monotonic() + timeout
        seen = 0
        while True:
            for i in range(seen, len(self.got)):
                if pred(self.got[i]):
                    return self.got.pop(i)
            seen = len(self.got)
            if time.monotonic() >= deadline:
                raise AssertionError('timed out; got {0!r}'.format([_short(m) for m in self.got]))
            if pump is not None:
                pump()
            msg = self.client.recv(timeout=0.05)
            if msg is not None:
                self.got.append(msg)

    def json(self, kind, timeout=5.0, pump=None, **match):
        return self.next(lambda m: m[0] == 'json' and m[1].get('kind') == kind
                         and all(m[1].get(k) == v for k, v in match.items()), timeout, pump)[1]

    def frame(self, timeout=5.0):
        return unpack_header(self.next(lambda m: m[0] == 'frame', timeout)[1])

    def drain(self, wait=0.2):
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            msg = self.client.recv(timeout=0.02)
            if msg is not None:
                self.got.append(msg)
        out, self.got = self.got, []
        return out


def _short(m):
    return ('frame', len(m[1])) if m[0] == 'frame' else m[1]


@pytest.fixture
def link(sock_path, closers):
    server = LinkServer(sock_path)
    server.start()
    closers.append(server)
    return server


@pytest.fixture
def connect(link, sock_path, closers):
    def _connect(controls=True):
        before = set(link.clients())
        client = LinkClient(sock_path)
        client.connect(hello={'controls': True} if controls else None)
        closers.append(client)
        assert wait_for(lambda: set(link.clients()) - before)
        (cid,) = set(link.clients()) - before
        return cid, Page(client)
    return _connect


@pytest.fixture
def source():
    return FakeSource()


@pytest.fixture
def epoch():
    return Epoch()


@pytest.fixture
def make(link, source, epoch, closers):
    def _make(**kw):
        ctrl = FocusController(source, link, FakeClock(), RIG, kw.pop('lens', False), epoch=kw.pop('epoch', epoch),
                               exposure=kw.pop('exposure', 1.0), gain=kw.pop('gain', 100.0), **kw)
        closers.append(_Ender(ctrl))
        return ctrl
    return _make


class _Ender(object):
    def __init__(self, ctrl):
        self.ctrl = ctrl

    def close(self):
        if self.ctrl.active:
            self.ctrl.end('stopped')


def reading(page, frame_no=None, ctrl=None):
    match = {} if frame_no is None else {'frame': frame_no}
    return page.json('reading', pump=ctrl.service if ctrl else None, **match)


def run_pick(ctrl, page, source, epoch, stars=GRADED, exposure=2.0):
    """Press Pick stars at epoch 1000 and feed three frames begun after it; return the `stars` message."""
    epoch.t = 1000.0
    ctrl.handle(page.cid, {'kind': 'pick_stars'})
    for i in range(3):  # one at a time: a worker that falls behind skips frames
        source.frames.put(raw_frame(stars, t_end=1000.0 + exposure * (i + 1), exposure=exposure))
        page.json('progress', what='pick', frame=i + 1, pump=ctrl.service)
    return page.json('stars', pump=ctrl.service, timeout=10.0)


@pytest.fixture
def session(connect, make, source, epoch):
    """A begun controller and one page with controls."""
    cid, page = connect()
    page.cid = cid
    ctrl = make(exposure=2.0)
    ctrl.begin(cid)
    page.json('state')
    page.json('mode')
    return ctrl, page


# --- frames and readings ----------------------------------------------------------------------------------------

def test_frame_then_reading_order(session, source):
    ctrl, page = session
    source.frames.put(raw_frame(GRID, t_end=1003.0, exposure=2.0))
    msgs = []
    page.next(lambda m: msgs.append(m) or (m[0] == 'json' and m[1].get('kind') == 'reading'))
    frames = [unpack_header(m[1]) for m in msgs if m[0] == 'frame']
    assert len(frames) == 1
    head = frames[0]
    assert msgs[-1][1]['frame'] == head['frame_no'] == 1
    assert head['capture_time'] == pytest.approx(1002.0)  # mid-exposure: t_end - exposure / 2
    assert head['exposure'] == pytest.approx(2.0)
    assert msgs.index(next(m for m in msgs if m[0] == 'frame')) < len(msgs) - 1


def test_reading_measured_before_clock(connect, make, source, epoch, monkeypatch):
    def run():
        cid, page = connect()
        page.cid = cid
        ctrl = make(exposure=2.0)
        ctrl.begin(cid)
        run_pick(ctrl, page, source, epoch)
        source.frames.put(raw_frame(GRADED, t_end=1010.0, exposure=2.0))
        got = reading(page, 4, ctrl)
        ctrl.end('stopped')
        page.client.close()
        return got

    plain = run()

    def white(img, capture_time, frame_no, fmt=None):
        img[...] = 255

    monkeypatch.setattr(controller_mod, 'draw_clock', white)
    assert run() == plain
    assert plain['measure'] == 'stars' and plain['size'] > 0


# --- picking --------------------------------------------------------------------------------------------------------

def test_pick_uses_frames_begun_after_press(session, source, epoch):
    ctrl, page = session
    epoch.t = 1000.0
    ctrl.handle(page.cid, {'kind': 'pick_stars'})
    # begun at 999.5, before the press: it holds an extra star and must not be stacked
    extra = synth.Star(120.3, 72.2, 1.5, 20000)
    source.frames.put(raw_frame(GRID + [extra], t_end=1001.5, exposure=2.0))
    reading(page, 1, ctrl)
    for i in range(3):
        source.frames.put(raw_frame(GRID, t_end=1002.0 + 2.0 * (i + 1), exposure=2.0))
        progress = page.json('progress', what='pick', pump=ctrl.service, frame=i + 1)
        assert progress['of'] == 3 and progress['done'] is False
    stars = page.json('stars', pump=ctrl.service)
    assert len(stars['stars']) == len(GRID)
    assert not any(abs(s['x'] - extra.x) < 6 and abs(s['y'] - extra.y) < 6 for s in stars['stars'])
    for s in stars['stars']:
        assert s['snr1'] > 0
        assert s['state'] == grade(s['snr1'], stars['min_snr'])
    assert page.json('progress', what='pick', pump=ctrl.service, done=True)['message'] == 'Picked 16 stars.'


def test_min_snr_regrades_without_repick(session, source, epoch):
    ctrl, page = session
    first = run_pick(ctrl, page, source, epoch)
    page.json('progress', what='pick', done=True, pump=ctrl.service)
    page.drain()
    calls = list(source.calls)
    ctrl.handle(page.cid, {'kind': 'min_snr', 'value': 30})
    again = page.json('stars')
    assert again['min_snr'] == 30
    assert [(s['id'], s['x'], s['y'], s['snr1']) for s in again['stars']] == \
        [(s['id'], s['x'], s['y'], s['snr1']) for s in first['stars']]
    states = [s['state'] for s in again['stars']]
    assert states == [grade(s['snr1'], 30) for s in again['stars']]
    assert 'weak' in states and 'kept' in states
    assert source.calls == calls
    assert not [m for m in page.drain() if m[0] == 'json' and m[1].get('kind') == 'progress']

    ctrl.handle(page.cid, {'kind': 'min_snr', 'value': 500})
    assert page.json('stars')['min_snr'] == 60  # the slider's range is 3 to 60


def test_drop_and_pin(session, source, epoch):
    ctrl, page = session
    stars = run_pick(ctrl, page, source, epoch, stars=GRID)
    kept = [s['id'] for s in stars['stars'] if s['state'] == 'kept']
    assert len(kept) > 3
    target = kept[0]

    ctrl.handle(page.cid, {'kind': 'star', 'id': target, 'state': 'pin'})
    assert {s['id']: s['state'] for s in page.json('stars')['stars']}[target] == 'pinned'
    source.frames.put(raw_frame(GRID, t_end=1010.0, exposure=2.0))
    r = reading(page, 4, ctrl)
    rings = {ring['id']: ring for ring in r['rings']}
    assert r['stars_used'] == 1
    assert r['size'] == pytest.approx(rings[target]['size'])

    ctrl.handle(page.cid, {'kind': 'star', 'id': target, 'state': 'drop'})
    assert {s['id']: s['state'] for s in page.json('stars')['stars']}[target] == 'dropped'
    source.frames.put(raw_frame(GRID, t_end=1012.0, exposure=2.0))
    r = reading(page, 5, ctrl)
    assert r['stars_used'] == len(kept) - 1
    assert {ring['id']: ring['state'] for ring in r['rings']}[target] == 'dropped'


def test_set_camera_restarts_and_resets_stretch(session, source, monkeypatch):
    ctrl, page = session
    used = []
    real = controller_mod.preview

    def spy(gray, stretch):
        used.append(stretch)
        return real(gray, stretch)

    monkeypatch.setattr(controller_mod, 'preview', spy)
    linear = Stretch(0.0, 65535.0, 1.0)

    for n in (1, 2, 3):
        source.frames.put(raw_frame(GRID, t_end=1000.0 + 2 * n, exposure=2.0))
        reading(page, n, ctrl)
    assert used[0] == linear
    assert used[1] != linear and used[1].gamma == pytest.approx(0.8)
    assert used[2] is used[1]

    ctrl.handle(page.cid, {'kind': 'set_camera', 'exposure': 4.0, 'gain': 50, 'cmd_id': 3})
    assert ('set_camera', 4.0, 50.0) in source.calls
    mode = page.json('mode')
    assert (mode['exposure'], mode['gain']) == (4.0, 50.0)
    for n in (4, 5):
        source.frames.put(raw_frame(GRID, t_end=1100.0 + 4 * n, exposure=4.0, gain=50.0))
        reading(page, n, ctrl)
    assert used[3] == linear
    assert used[4] != linear


@pytest.fixture
def stretches(monkeypatch):
    """Every Stretch the worker drew a picture with, in order."""
    used = []
    real = controller_mod.preview

    def spy(gray, stretch):
        used.append(stretch)
        return real(gray, stretch)

    monkeypatch.setattr(controller_mod, 'preview', spy)
    return used


def _measured(r):
    return {k: v for k, v in r.items() if k not in ('frame', 'capture_time')}


def test_stretch_starts_auto_and_reports_its_levels(session, source, stretches):
    ctrl, page = session
    first = page.json('stretch')
    assert first == {'kind': 'stretch', 'mode': 'auto', 'black': None, 'white': None}
    for n in (1, 2):
        source.frames.put(raw_frame(GRID, t_end=1000.0 + 2 * n, exposure=2.0))
        reading(page, n, ctrl)
    levels = page.json('stretch', pump=ctrl.service)
    assert levels['mode'] == 'auto'
    assert levels['black'] == pytest.approx(stretches[1].black / 65535.0)
    assert levels['white'] == pytest.approx(stretches[1].white / 65535.0)
    assert 0.0 <= levels['black'] < levels['white'] <= 0.98


def test_stretch_modes_change_only_the_picture(session, source, stretches):
    ctrl, page = session
    readings = []
    n = 0

    def one():
        nonlocal n
        n += 1
        source.frames.put(raw_frame(GRID, t_end=1000.0 + 2 * n, exposure=2.0))
        readings.append(_measured(reading(page, n, ctrl)))

    one()
    one()                                                           # Auto: linear, then levelled
    ctrl.handle(page.cid, {'kind': 'set_stretch', 'mode': 'manual', 'black': 0.01, 'white': 0.2})
    assert page.json('stretch', mode='manual') == {'kind': 'stretch', 'mode': 'manual', 'black': 0.01, 'white': 0.2}
    one()
    assert stretches[-1] == Stretch(0.01 * 65535.0, 0.2 * 65535.0)
    ctrl.handle(page.cid, {'kind': 'set_stretch', 'mode': 'off'})
    assert page.json('stretch', mode='off')['mode'] == 'off'
    one()
    assert stretches[-1] == Stretch(0.0, 65535.0, 1.0)

    assert all(r == readings[0] for r in readings)


def test_relevel_levels_from_the_next_frame(session, source, stretches):
    ctrl, page = session
    for n in (1, 2):
        source.frames.put(raw_frame(GRID, t_end=1000.0 + 2 * n, exposure=2.0))
        reading(page, n, ctrl)
    before = stretches[-1]
    ctrl.handle(page.cid, {'kind': 'set_stretch', 'mode': 'auto', 'relevel': True})
    page.json('stretch', mode='auto')
    # a brighter sky: the new levels must come from this frame, with no linear frame first
    source.frames.put(raw_frame(GRID, t_end=1006.0, exposure=2.0, background=8000.0))
    reading(page, 3, ctrl)
    assert stretches[-1] != before
    assert stretches[-1].gamma == pytest.approx(0.8)
    assert stretches[-1].black > before.black


def test_manual_levels_survive_a_camera_change(session, source, stretches):
    ctrl, page = session
    ctrl.handle(page.cid, {'kind': 'set_stretch', 'mode': 'manual', 'black': 0.05, 'white': 0.5})
    ctrl.handle(page.cid, {'kind': 'set_camera', 'exposure': 4.0, 'gain': 50, 'cmd_id': 3})
    source.frames.put(raw_frame(GRID, t_end=1010.0, exposure=4.0, gain=50.0))
    reading(page, 1, ctrl)
    assert stretches[-1] == Stretch(0.05 * 65535.0, 0.5 * 65535.0)


def test_a_joining_page_gets_the_stretch(session, connect):
    ctrl, page = session
    ctrl.handle(page.cid, {'kind': 'set_stretch', 'mode': 'manual', 'black': 0.1, 'white': 0.3})
    _, late = connect(controls=False)
    got = late.json('stretch', pump=ctrl.service)
    assert (got['mode'], got['black'], got['white']) == ('manual', 0.1, 0.3)


def test_bad_stretch_values_get_an_error(session):
    ctrl, page = session
    page.json('stretch')
    for msg in ({'kind': 'set_stretch', 'mode': 'loud'},
                {'kind': 'set_stretch', 'mode': 'manual', 'black': 0.5, 'white': 0.5},
                {'kind': 'set_stretch', 'mode': 'manual', 'black': 0.2, 'white': 1.5},
                {'kind': 'set_stretch', 'mode': 'manual', 'black': -0.1, 'white': 0.5},
                {'kind': 'set_stretch', 'mode': 'manual', 'black': True, 'white': 0.5},
                {'kind': 'set_stretch', 'mode': 'manual'}):
        ctrl.handle(page.cid, msg)
        assert page.json('error')['command'] == 'set_stretch'
    assert not [m for m in page.drain() if m[0] == 'json' and m[1].get('kind') == 'stretch']


def test_watcher_cannot_set_the_stretch(session, connect):
    ctrl, page = session
    wid, watcher = connect(controls=False)
    ctrl.handle(wid, {'kind': 'set_stretch', 'mode': 'off'})
    assert watcher.json('error')['command'] == 'set_stretch'
    assert ctrl._stretch_msg()['mode'] == 'auto'


# --- what the number shows ------------------------------------------------------------------------------------------

def test_contrast_when_no_stars_and_bright(session, source):
    ctrl, page = session
    source.frames.put(raw_frame((), background=20000.0, exposure=2.0))
    r = reading(page, 1, ctrl)
    assert r['measure'] == 'contrast'
    assert r['contrast'] > 0
    assert r['size'] is None


def test_no_stars_dark_message(session, source):
    ctrl, page = session
    source.frames.put(raw_frame((), exposure=2.0))
    r = reading(page, 1, ctrl)
    assert r['measure'] == 'none'
    assert r['message'] == MSG_NO_STARS


def test_stars_visible_before_a_pick(session, source):
    ctrl, page = session
    source.frames.put(raw_frame(GRID, exposure=2.0))
    r = reading(page, 1, ctrl)
    assert r['measure'] == 'stars'
    assert r['stars_visible'] == len(GRID)
    assert r['size'] is None
    assert r['message'] == 'About 16 stars visible · press Tune to measure'  # no motor: Tune runs on into a pick


def test_measure_switch_needs_several_frames(session, source):
    ctrl, page = session
    source.frames.put(raw_frame((), exposure=2.0))
    assert reading(page, 1, ctrl)['measure'] == 'none'
    for n in range(2, 6):
        source.frames.put(raw_frame((), background=20000.0, exposure=2.0))
        assert reading(page, n, ctrl)['measure'] == 'none'
    source.frames.put(raw_frame((), background=20000.0, exposure=2.0))
    assert reading(page, 6, ctrl)['measure'] == 'contrast'


def test_measure_message_on_switch(session, source):
    ctrl, page = session
    source.frames.put(raw_frame((), exposure=2.0))
    assert page.json('measure')['measure'] == 'none'
    for n in range(2, 7):
        source.frames.put(raw_frame((), background=20000.0, exposure=2.0))
        reading(page, n, ctrl)
    assert page.json('measure')['measure'] == 'contrast'


# --- commands -------------------------------------------------------------------------------------------------------

def test_watcher_cannot_command(session, connect, source):
    ctrl, page = session
    wid, watcher = connect(controls=False)
    calls = list(source.calls)
    ctrl.handle(wid, {'kind': 'set_camera', 'exposure': 8.0, 'gain': 1})
    err = watcher.json('error')
    assert err['command'] == 'set_camera'
    assert err['message']
    assert source.calls == calls
    assert ctrl.exposure == 2.0

    ctrl.handle(wid, {'kind': 'ping', 'id': 9})
    pong = watcher.json('pong')
    assert pong['id'] == 9 and abs(pong['t'] - time.time()) < 5


def test_bad_values_get_an_error(session, source):
    ctrl, page = session
    calls = list(source.calls)
    for msg in ({'kind': 'set_camera', 'exposure': -1, 'gain': 1},
                {'kind': 'set_camera', 'exposure': 'x', 'gain': 1},
                {'kind': 'move_to', 'target': 1, 'cmd_id': -4},
                {'kind': 'star', 'id': 99, 'state': 'pin'},
                {'kind': 'set_region', 'roi': [1, 2]},
                {'kind': 'no_such_thing'}):
        ctrl.handle(page.cid, msg)
        assert page.json('error')['command'] == msg['kind']
    assert source.calls == calls


def test_set_camera_refused_during_pick(session, source, epoch):
    ctrl, page = session
    ctrl.handle(page.cid, {'kind': 'pick_stars'})
    ctrl.handle(page.cid, {'kind': 'set_camera', 'exposure': 4.0, 'gain': 50})
    assert page.json('error')['message'] == 'Wait for the star pick to finish.'
    assert 'set_camera' not in source.kinds()


def test_set_region_restarts_source_and_clears_stars(session, source, epoch):
    ctrl, page = session
    run_pick(ctrl, page, source, epoch)
    ctrl.handle(page.cid, {'kind': 'set_region', 'roi': [11, 21, 101, 81], 'cmd_id': 4})
    assert page.json('stars')['stars'] == []
    assert page.json('mode')['roi'] == [10, 20, 100, 80]
    assert source.calls[-2:] == [('stop',), ('start', (10, 20, 100, 80), 2.0, 100.0)]


def _moon_raw(t_end=1001.0):
    raw = synth.frame(SHAPE, stars=GRID, glints=[synth.Glint(60.0, 60.0, 8.0, 80000)])
    return RawFrame(raw, 65535.0, 'RGGB', t_end, 1.0, 100.0)


def test_first_region_moves_off_a_clipped_light(connect, make, source):
    cid, page = connect()
    ctrl = make(roi=(512, 512, 256, 256), sensor=(1024, 1024))
    ctrl.begin(cid)
    source.frames.put(_moon_raw())
    msg = page.json('progress', what='region', pump=ctrl.service)
    assert msg['message'] == MSG_OFF_GLARE and msg['done'] is True
    roi = tuple(page.json('mode', pump=ctrl.service, roi=list(ctrl.roi))['roi'])
    assert roi != (512, 512, 256, 256) and roi[2:] == (256, 256)
    assert source.calls[-2:] == [('stop',), ('start', roi, 1.0, 100.0)]
    # the moon (sensor 572, 572; disc radius about 48 px) is clear of the new region
    x, y, w, h = roi
    assert math.hypot(max(x - 572, 0, 572 - x - w), max(y - 572, 0, 572 - y - h)) >= 48


def test_first_region_stays_without_a_clipped_light(connect, make, source):
    cid, page = connect()
    ctrl = make(roi=(512, 512, 256, 256), sensor=(1024, 1024))
    ctrl.begin(cid)
    source.frames.put(raw_frame(GRID))
    reading(page, ctrl=ctrl)
    ctrl.service()
    assert source.kinds() == ['start']
    assert not [m for m in page.drain() if m[0] == 'json' and m[1].get('what') == 'region']


def test_preview_sends_whole_frame(session, source):
    ctrl, page = session
    ctrl.handle(page.cid, {'kind': 'preview'})
    msg = page.json('preview', pump=ctrl.service)
    assert (msg['width'], msg['height']) == SHAPE[::-1]
    assert msg['jpeg']


def _lens_session(connect, source, link, closers, limit=400, backlash=20, speed=100.0, exposure=2.0):
    """A begun controller with a real Lens on a fake driver; the lens clock is the controller's epoch."""
    cid, page = connect()
    page.cid = cid
    clock = LensClock()
    driver = FakeDriver(clock, speed=speed)
    holder = []
    lens = Lens(driver, limit=limit, backlash=backlash, clock=clock,
                on_change=lambda st: holder[0].on_lens_change(st) if holder else None, sleep=clock.sleep)
    ctrl = FocusController(source, link, FakeClock(), RIG, lens, epoch=clock, exposure=exposure, gain=100.0)
    holder.append(ctrl)
    closers.append(_LensCloser(lens))
    closers.append(_Ender(ctrl))
    ctrl.begin(cid)
    page.json('state')
    page.json('mode')
    return ctrl, page, lens, clock


class _LensCloser(object):
    def __init__(self, lens):
        self.lens = lens

    def close(self):
        self.lens.close()


def test_move_to_marks_later_frames(connect, source, link, closers):
    ctrl, page, lens, clock = _lens_session(connect, source, link, closers)
    ctrl.handle(page.cid, {'kind': 'move_to', 'target': 30, 'cmd_id': 7})
    ctrl.service()
    assert lens.wait(5)
    rest = page.json('lens', pump=ctrl.service, cmd_id=7, moving=False)
    assert rest['position'] == 30
    done = clock.t   # the lens came to rest here; frames begun SETTLE_S later carry the command
    source.frames.put(raw_frame(GRID, t_end=done + Lens.SETTLE_S - 0.1 + 2.0, exposure=2.0))
    assert page.frame()['cmd_id'] == 0
    source.frames.put(raw_frame(GRID, t_end=done + Lens.SETTLE_S + 2.0, exposure=2.0))
    assert page.frame()['cmd_id'] == 7


def test_lens_commands_without_motor(session):
    ctrl, page = session
    for msg in ({'kind': 'move_to', 'target': 5, 'cmd_id': 1}, {'kind': 'nudge', 'steps': 5, 'cmd_id': 2},
                {'kind': 'back', 'cmd_id': 3}, {'kind': 'autofocus', 'cmd_id': 4}):
        ctrl.handle(page.cid, msg)
        err = page.json('error', pump=ctrl.service)
        assert err['command'] == msg['kind'] and err['message'] == controller_mod.MSG_NO_MOTOR


def test_lens_commands_wait_for_the_tune(connect, source, link, closers):
    # a lens moved mid-tune would spoil the exposures it compares
    ctrl, page, lens, clock = _lens_session(connect, source, link, closers)
    with ctrl._lock:
        ctrl._search_on = True
    for msg in ({'kind': 'move_to', 'target': 5, 'cmd_id': 1}, {'kind': 'nudge', 'steps': 5, 'cmd_id': 2},
                {'kind': 'back', 'cmd_id': 3}, {'kind': 'autofocus', 'cmd_id': 4}):
        ctrl.handle(page.cid, msg)
        err = page.json('error', pump=ctrl.service)
        assert err['command'] == msg['kind'] and err['message'] == controller_mod.MSG_SEARCH_BUSY
    assert lens.state.position == 0 and not lens.state.moving


def test_back_without_previous(connect, source, link, closers):
    ctrl, page, lens, clock = _lens_session(connect, source, link, closers)
    ctrl.handle(page.cid, {'kind': 'back', 'cmd_id': 3})
    err = page.json('error', pump=ctrl.service)
    assert err['message'] == controller_mod.MSG_NO_BACK


def test_join_gets_lens_and_graph(connect, source, link, closers):
    ctrl, page, lens, clock = _lens_session(connect, source, link, closers)
    cid2, page2 = connect(controls=False)
    lens_msg = page2.json('lens', pump=ctrl.service)
    assert list(lens_msg['reachable']) == [-380, 400]
    assert 1 <= lens_msg['fine'] <= lens_msg['medium'] <= lens_msg['coarse']
    graph = page2.json('graph', pump=ctrl.service)
    assert graph['points'] == [] and graph['fit'] is None


BEST = 30   # the simulated lens position of best focus


def _blurred(lens, t_end, exposure):
    """A frame whose stars blur with the lens's distance from BEST at mid-exposure."""
    x = lens.position_at(t_end - exposure / 2)
    sigma = 1.2 + 0.025 * abs(x - BEST)
    stars = [synth.Star(s.x, s.y, sigma, 20000 * (1.5 / sigma) ** 2) for s in GRID]
    return raw_frame(stars, t_end=t_end, exposure=exposure)


def _feed(ctrl, page, source, frame):
    """Feed one frame and wait for its reading."""
    page.n = getattr(page, 'n', 0) + 1
    source.frames.put(frame)
    page.json('reading', pump=ctrl.service, frame=page.n)


def _pick_with_lens(ctrl, page, source, lens, clock, exposure):
    """Press Pick stars and feed frames at rest (best focus blur at 0) until the pick is graded."""
    ctrl.handle(page.cid, {'kind': 'pick_stars'})
    ctrl.service()
    t = clock.t
    for _ in range(int(Lens.SETTLE_S + controller_mod.GRADE_SECONDS / exposure) + 6):
        t += exposure
        clock.t = t   # the picture clock moves on with the frames (autofocus may start mid-feed)
        _feed(ctrl, page, source, _blurred(lens, t, exposure))
        if any(m[0] == 'json' and m[1].get('kind') == 'stars' for m in page.got):
            break
    stars = page.json('stars', pump=ctrl.service)
    assert stars['stars']


def _run_scan(ctrl, page, source, lens, clock, exposure):
    """Pump until the scan move has ended, then feed the frames that ran during it, one at a time."""
    assert wait_for(lambda: (ctrl.service() or True) and ctrl._af is not None and ctrl._af.stage == 'scan'
                    and ctrl._af_feed is not None and lens.wait(0) and not lens.state.moving)
    t = ctrl._af_feed[1]
    ended = clock.t
    while t <= ended + exposure:
        t += exposure
        _feed(ctrl, page, source, _blurred(lens, t, exposure))


def test_a_pick_starts_autofocus_and_it_parks_at_best_focus(connect, source, link, closers):
    exposure = 0.5
    ctrl, page, lens, clock = _lens_session(connect, source, link, closers, limit=160, exposure=exposure)
    _pick_with_lens(ctrl, page, source, lens, clock, exposure)
    # no Autofocus press: the finished pick starts it
    _run_scan(ctrl, page, source, lens, clock, exposure)
    fit = page.json('fit', pump=ctrl.service, timeout=15.0)
    assert abs(fit['c'] - BEST) <= 4
    done = page.json('progress', what='autofocus', done=True, pump=ctrl.service, timeout=10.0)
    assert done['stage'] == 'done'
    assert lens.wait(5)
    assert abs(lens.state.position - BEST) <= 4
    assert lens.state.previous == 0      # Back returns to where autofocus began
    # the graph holds the sweep's samples only: frames at rest after the run add none
    swept = list(ctrl._points)
    assert swept and all(-80 <= x <= 80 for x, _, _ in swept)
    t = clock.t
    for _ in range(3):
        t += exposure
        _feed(ctrl, page, source, _blurred(lens, t, exposure))
    assert list(ctrl._points) == swept


def test_frames_at_rest_draw_no_graph_points(connect, source, link, closers):
    exposure = 0.5
    ctrl, page, lens, clock = _lens_session(connect, source, link, closers, limit=160, exposure=exposure)
    ctrl._af_auto = None
    t = clock.t
    for _ in range(4):
        t += exposure
        _feed(ctrl, page, source, _blurred(lens, t, exposure))
    assert list(ctrl._points) == []


def test_lens_command_cancels_the_queued_autofocus(connect, source, link, closers):
    exposure = 0.5
    ctrl, page, lens, clock = _lens_session(connect, source, link, closers, limit=160, exposure=exposure)
    with ctrl._lock:
        ctrl._af_auto = ctrl._stars_gen
    ctrl.handle(page.cid, {'kind': 'nudge', 'steps': 5, 'cmd_id': 21})
    assert ctrl._af_auto is None


def test_autofocus_stop_ends_run(connect, source, link, closers):
    exposure = 0.5
    ctrl, page, lens, clock = _lens_session(connect, source, link, closers, limit=160, exposure=exposure)
    _pick_with_lens(ctrl, page, source, lens, clock, exposure)
    assert wait_for(lambda: (ctrl.service() or True) and ctrl._af is not None and ctrl._af.stage == 'scan')
    ctrl.handle(page.cid, {'kind': 'stop', 'cmd_id': 13})
    msg = page.json('progress', what='autofocus', done=True, pump=ctrl.service)
    assert msg['message'] == controller_mod.MSG_AF_STOPPED
    assert lens.wait(5)
    ctrl.handle(page.cid, {'kind': 'set_camera', 'exposure': 1.0, 'gain': 100, 'cmd_id': 14})
    ctrl.service()
    assert not [m for m in page.drain(0.2) if m[0] == 'json' and m[1].get('kind') == 'error']


def test_autofocus_without_stars_picks_them_first(connect, source, link, closers):
    ctrl, page, lens, clock = _lens_session(connect, source, link, closers)
    with ctrl._lock:
        ctrl._plan = controller_mod.PLAN_PREVIEW
    ctrl.handle(page.cid, {'kind': 'autofocus'})
    assert page.json('progress', what='pick', pump=ctrl.service)['done'] is False
    assert ctrl._plan == controller_mod.PLAN_AUTOFOCUS   # the pick runs on into autofocus
    assert page.json('state', pump=ctrl.service)['plan'] == 'autofocus'
    assert lens.state.position == 0 and not lens.state.moving


def test_stars_visible_with_a_motor_points_at_autofocus(connect, source, link, closers):
    ctrl, page, lens, clock = _lens_session(connect, source, link, closers)
    source.frames.put(raw_frame(GRID, t_end=clock() + 2.5, exposure=2.0))
    assert reading(page, None, ctrl)['message'] == 'About 16 stars visible · press Autofocus to measure'


def test_a_preview_pick_does_not_start_autofocus(connect, source, link, closers):
    exposure = 0.5
    ctrl, page, lens, clock = _lens_session(connect, source, link, closers, limit=160, exposure=exposure)
    with ctrl._lock:
        ctrl._plan = controller_mod.PLAN_PREVIEW
    _pick_with_lens(ctrl, page, source, lens, clock, exposure)
    assert ctrl._stars and ctrl._af_auto is None
    for _ in range(3):
        ctrl.service()
    assert ctrl._af is None and not lens.state.moving


def test_falls_behind_keeps_newest(connect, make, source):
    cid, page = connect()
    ctrl = make(exposure=2.0)
    for i in range(4):
        source.frames.put(raw_frame(GRID, t_end=1002.0 + i, exposure=2.0))
    ctrl.begin(cid)
    head = page.frame()
    assert head['frame_no'] == 4
    assert head['capture_time'] == pytest.approx(1004.0)
    assert reading(page, 4, ctrl)['frame'] == 4
    later = page.drain(0.3)
    assert not [m for m in later if m[0] == 'frame']
    assert not [m for m in later if m[0] == 'json' and m[1].get('kind') == 'reading']


def test_exposure_search_lengthens_until_stars(connect, make, source):
    cid, page = connect()
    ctrl = make(exposure=1.0, search=lambda e, g, lim: ExposureSearch(0.001, 15.0, e))
    ctrl.begin(cid)
    source.frames.put(raw_frame((), exposure=1.0))
    step = page.json('progress', what='exposure_search', pump=ctrl.service)
    assert step['message'] == 'No stars yet. Trying 2 s.' and step['done'] is False
    assert ('set_camera', 2.0, 100.0) in source.calls
    source.frames.put(raw_frame(GRID, exposure=2.0, t_end=1003.0))
    step = page.json('progress', what='exposure_search', pump=ctrl.service)
    assert step['done'] is True and step['message'] == 'Found 16 stars at 2 s.'


def _tuned(make, gains=(None,), exposures=(0.1, 0.2), **kw):
    return make(exposure=1.0, search=lambda e, g, lim: Tune(list(exposures), list(gains)), **kw)


def _progress(page):
    return [m[1] for m in page.drain(0.1) if m[0] == 'json' and m[1].get('kind') == 'progress']


def test_tune_runs_at_start_and_settles(connect, make, source):
    cid, page = connect()
    ctrl = _tuned(make)
    ctrl.begin(cid)
    assert source.calls[0] == ('start', None, 0.1, 100.0)  # the first point: no restart for it
    first = page.json('progress', what='tune')
    assert first['message'] == 'Tuning: 1 of 2 · 0.1 s'
    assert (first['step'], first['of']) == (1, 2)  # for the page's step bar
    source.frames.put(raw_frame((), exposure=0.1))
    step = page.json('progress', what='tune', pump=ctrl.service)
    assert step['message'] == 'Tuning: 2 of 2 · 0.2 s' and step['done'] is False
    assert (step['step'], step['of']) == (2, 2)
    assert ('set_camera', 0.2, 100.0) in source.calls
    source.frames.put(raw_frame(GRID, exposure=0.2))
    step = page.json('progress', what='tune', pump=ctrl.service)
    assert step == {'kind': 'progress', 'what': 'tune', 'message': 'Tuned: 0.2 s · 16 stars.', 'done': True}
    assert ctrl.exposure == 0.2
    # stars found: the pick starts on its own
    assert page.json('progress', what='pick', pump=ctrl.service)['done'] is False


def _preview_tune(page, ctrl, source, cid):
    ctrl.begin(cid, 'preview')
    assert page.json('state')['plan'] == 'preview'
    page.json('progress', what='tune')
    source.frames.put(raw_frame((), exposure=0.1))
    page.json('progress', what='tune', pump=ctrl.service)
    source.frames.put(raw_frame(GRID, exposure=0.2))
    assert page.json('progress', what='tune', pump=ctrl.service)['done'] is True


def test_a_motor_preview_stops_after_the_tune(connect, make, source, closers):
    # with a motor, Autofocus picks the stars when it is pressed
    cid, page = connect()
    clock = LensClock()
    lens = Lens(FakeDriver(clock), limit=400, backlash=20, clock=clock, sleep=clock.sleep)
    closers.append(_LensCloser(lens))
    ctrl = _tuned(make, lens=lens, epoch=clock)
    _preview_tune(page, ctrl, source, cid)
    ctrl.service()
    assert not [m for m in _progress(page) if m['what'] == 'pick']
    assert ctrl._pick_press is None


def test_a_hand_preview_picks_stars_after_the_tune(connect, make, source):
    # no motor, no Autofocus: the pick follows the tune, so the star size shows with no button
    cid, page = connect()
    ctrl = _tuned(make)
    _preview_tune(page, ctrl, source, cid)
    assert page.json('progress', what='pick', pump=ctrl.service)['done'] is False
    assert ctrl._plan == controller_mod.PLAN_PREVIEW


def test_a_tune_without_stars_does_not_start_a_pick(connect, make, source):
    cid, page = connect()
    ctrl = _tuned(make)
    ctrl.begin(cid)
    page.json('progress', what='tune')
    for exposure in (0.1, 0.2):
        source.frames.put(raw_frame((), exposure=exposure))
        page.json('progress', what='tune', pump=ctrl.service)
    assert not [m for m in _progress(page) if m['what'] == 'pick']
    assert ctrl._pick_press is None


def test_tune_skips_frames_of_the_wrong_point(connect, make, source):
    cid, page = connect()
    ctrl = _tuned(make)
    ctrl.begin(cid)
    page.json('progress', what='tune')
    source.frames.put(raw_frame((), exposure=1.0))                 # the old exposure
    reading(page, 1, ctrl)
    source.frames.put(raw_frame((), exposure=0.1, t_end=1000.05))  # begun before the tune moved the camera
    reading(page, 2, ctrl)
    assert not _progress(page)


def test_set_camera_stops_a_tune(connect, make, source):
    cid, page = connect()
    ctrl = _tuned(make)
    ctrl.begin(cid)
    page.json('progress', what='tune')
    ctrl.handle(cid, {'kind': 'set_camera', 'exposure': 0.5, 'gain': 100.0})
    stop = page.json('progress', what='tune')
    assert stop['done'] is True and stop['message'] == 'Tune stopped: your settings are kept.'
    source.frames.put(raw_frame((), exposure=0.1))
    reading(page, 1, ctrl)
    assert not _progress(page)
    assert ctrl.exposure == 0.5


def test_pick_waits_for_the_tune(connect, make, source):
    cid, page = connect()
    ctrl = _tuned(make)
    ctrl.begin(cid)
    ctrl.handle(cid, {'kind': 'pick_stars'})
    assert page.json('error')['message'] == 'Wait for the tune to finish.'


def test_tune_command_runs_it_again_and_drops_the_old_one(connect, make, source):
    cid, page = connect()
    ctrl = _tuned(make, gains=(150, 300))
    ctrl.begin(cid)
    page.json('progress', what='tune')
    old_gen = ctrl._search_gen
    ctrl.handle(cid, {'kind': 'set_camera', 'exposure': 0.5, 'gain': 100.0})
    ctrl.handle(cid, {'kind': 'tune'})
    assert ctrl._search_gen == old_gen + 1
    assert source.calls[-1] == ('set_camera', 0.1, 150.0)
    ctrl._post(('search', old_gen, SearchStep(9.0, False, 'stale', 300.0)))
    ctrl.service()
    assert (ctrl.exposure, ctrl.gain) == (0.1, 150.0)  # the old generation's step was dropped


def test_tune_after_a_pick_runs_to_the_end(connect, make, source, epoch):
    cid, page = connect()
    page.cid = cid
    ctrl = _tuned(make)
    ctrl.begin(cid)
    page.json('progress', what='tune')  # the start-up tune
    ctrl.handle(cid, {'kind': 'set_camera', 'exposure': 2.0, 'gain': 100.0})
    assert page.json('progress', what='tune')['done'] is True  # stopped
    assert run_pick(ctrl, page, source, epoch)['stars']
    epoch.t = 2000.0
    ctrl.handle(cid, {'kind': 'tune'})
    assert page.json('progress', what='tune')['message'] == 'Tuning: 1 of 2 · 0.1 s'
    source.frames.put(raw_frame(GRID, exposure=0.1, t_end=2000.5))
    assert page.json('progress', what='tune', pump=ctrl.service)['message'] == 'Tuning: 2 of 2 · 0.2 s'
    source.frames.put(raw_frame(GRID, exposure=0.2, t_end=2001.0))
    assert page.json('progress', what='tune', pump=ctrl.service)['done'] is True
    assert ctrl.exposure == 0.1  # 16 stars at both: the shorter wins


def test_moving_the_region_starts_the_tune_again(connect, make, source):
    cid, page = connect()
    ctrl = _tuned(make)
    ctrl.begin(cid)
    page.json('progress', what='tune')
    source.frames.put(raw_frame((), exposure=0.1))
    page.json('progress', what='tune', pump=ctrl.service)  # on to point 2
    gen = ctrl._search_gen
    ctrl.handle(cid, {'kind': 'set_region', 'roi': [0, 0, 64, 64]})
    assert ctrl._search_gen == gen + 1
    assert page.json('progress', what='tune')['message'] == 'Tuning: 1 of 2 · 0.1 s'
    assert ctrl.exposure == 0.1


def test_a_watcher_cannot_tune(connect, make, source):
    cid, page = connect()
    ctrl = _tuned(make)
    ctrl.begin(cid)
    wid, watcher = connect(controls=False)
    ctrl.handle(wid, {'kind': 'tune'})
    assert watcher.json('error')['message'] == 'Only a page with controls can do that.'


def test_tune_without_a_search_is_unknown(session):
    ctrl, page = session
    ctrl.handle(page.cid, {'kind': 'tune'})
    assert page.json('error')['message'] == 'Unknown command.'


def test_done_ends_and_stops_source(session, source):
    ctrl, page = session
    ctrl.handle(page.cid, {'kind': 'done'})
    assert page.json('ended')['reason'] == 'done'
    assert not ctrl.active
    assert source.kinds()[-1] == 'stop'


def test_cancel_without_a_motor_ends_at_once(session, source):
    ctrl, page = session
    ctrl.handle(page.cid, {'kind': 'cancel'})
    assert page.json('ended')['reason'] == 'cancelled_hand'
    assert not ctrl.active


def test_cancel_returns_the_lens_to_where_it_was_at_start(connect, source, link, closers):
    ctrl, page, lens, clock = _lens_session(connect, source, link, closers)
    ctrl.handle(page.cid, {'kind': 'move_to', 'target': 60, 'cmd_id': 7})
    ctrl.service()
    assert lens.wait(5) and lens.state.position == 60
    ctrl.handle(page.cid, {'kind': 'cancel'})
    ctrl.handle(page.cid, {'kind': 'nudge', 'steps': 5, 'cmd_id': 8})
    assert page.json('error', pump=ctrl.service)['message'] == controller_mod.MSG_CANCELLING
    ended = page.json('ended', pump=ctrl.service, timeout=10.0)
    assert ended['reason'] == 'cancelled'
    assert lens.state.position == 0
    assert not ctrl.active


def test_cancel_stops_a_running_autofocus_and_returns(connect, source, link, closers):
    exposure = 0.5
    ctrl, page, lens, clock = _lens_session(connect, source, link, closers, limit=160, exposure=exposure)
    _pick_with_lens(ctrl, page, source, lens, clock, exposure)
    assert wait_for(lambda: (ctrl.service() or True) and ctrl._af is not None and ctrl._af.stage == 'scan')
    ctrl.handle(page.cid, {'kind': 'cancel'})
    msg = page.json('progress', what='autofocus', done=True, pump=ctrl.service)
    assert msg['message'] == controller_mod.MSG_AF_STOPPED
    assert page.json('ended', pump=ctrl.service, timeout=10.0)['reason'] == 'cancelled'
    assert lens.state.position == 0


def test_cancel_at_step_zero_ends_without_a_move(connect, source, link, closers):
    ctrl, page, lens, clock = _lens_session(connect, source, link, closers)
    ctrl.handle(page.cid, {'kind': 'cancel'})
    assert page.json('ended', pump=ctrl.service)['reason'] == 'cancelled'
    assert lens.state.position == 0


def test_no_page_ends_session(connect, make, source, link):
    cid, page = connect()
    clock = FakeClock()
    ctrl = FocusController(source, link, clock, RIG, False, epoch=Epoch(), exposure=1.0, gain=1.0)
    ctrl.begin(cid)
    page.client.close()
    assert wait_for(lambda: not link.clients())
    ctrl.service()
    assert ctrl.active
    clock.t = 121.0
    ctrl.service()
    assert not ctrl.active
    assert ctrl.end_reason == 'no_page'


# --- the service ----------------------------------------------------------------------------------------------------

INFO = CameraInfo(interface='indi', device_name='CCD Simulator', driver_has_video=True, rig=RIG)


def test_service_idle_answers_ping_and_state(link, connect):
    service = FocusService(link, INFO, lambda cid: pytest.fail('no session expected'))
    cid, page = connect(controls=False)
    page.client.send({'kind': 'hello'})
    page.client.send({'kind': 'ping', 'id': 1})
    state = page.json('state', pump=service.poll)
    assert state['session'] == 'idle'
    assert state['rig'] == {'page': 'new', 'picture': 'stills', 'reason': 'test rig'}
    assert state['driver_has_video'] is True
    assert state['controls'] is False
    assert page.json('pong', pump=service.poll)['id'] == 1

    page.client.send({'kind': 'set_camera', 'exposure': 1, 'gain': 1})
    assert page.json('error', pump=service.poll)['command'] == 'set_camera'


def test_service_start_from_watcher_refused(link, connect):
    made = []
    service = FocusService(link, INFO, lambda cid: made.append(cid))
    cid, page = connect(controls=False)
    page.client.send({'kind': 'start'})
    assert page.json('error', pump=service.poll)['command'] == 'start'
    assert made == []


def test_service_start_returns_true_once(link, connect, source, closers):
    made = []

    def make_controller(cid):
        ctrl = FocusController(source, link, FakeClock(), RIG, False, epoch=Epoch(), exposure=1.0, gain=1.0)
        closers.append(_Ender(ctrl))
        made.append(ctrl)
        return ctrl

    service = FocusService(link, INFO, make_controller)
    cid, page = connect()
    page.client.send({'kind': 'start'})
    page.client.send({'kind': 'start'})
    results = []
    page.json('mode', pump=lambda: results.append(service.poll()))
    wait_for(lambda: results.append(service.poll()) or len(results) > 20)
    assert results.count(True) == 1
    assert len(made) == 1 and made[0].active
    assert ('start', None, 1.0, 1.0) in source.calls

    page.client.send({'kind': 'done'})
    ended = page.json('ended', pump=service.poll)
    assert ended['reason'] == 'done'
    idle = page.json('state', pump=service.poll, session='idle', idle_reason='done')
    assert idle['controls'] is True and not service.active


def test_source_that_fails_to_start_ends_the_session(connect, make, source):
    cid, page = connect()

    def broken(roi, exposure, gain):
        raise RuntimeError('no camera')

    source.start = broken
    ctrl = make()
    ctrl.begin(cid)
    assert not ctrl.active
    assert ctrl.end_reason == 'failed'
    assert page.json('ended')['reason'] == 'failed'


def test_frame_from_before_a_region_change_is_skipped(session, source, epoch):
    # a stills load in flight when the region moves can queue one old-region frame after the drain
    ctrl, page = session
    epoch.t = 1000.0
    source.frames.put(raw_frame(GRID, t_end=1002.0, exposure=2.0))  # queued before: drained
    ctrl.handle(page.cid, {'kind': 'set_region', 'roi': [0, 0, 256, 256]})
    assert source.frames.empty()
    page.json('mode')
    source.frames.put(raw_frame(GRID, t_end=1001.0, exposure=2.0))  # began 999: the old region
    source.frames.put(raw_frame(GRID, t_end=1003.0, exposure=2.0))  # began 1001
    r = reading(page, ctrl=ctrl)
    assert r['capture_time'] == pytest.approx(1002.0)
    assert not [m for m in page.drain() if m[0] == 'json' and m[1].get('kind') == 'reading']


def test_source_error_with_no_way_back_ends_the_session(session, source):
    ctrl, page = session

    def broken(exposure, gain):
        raise RuntimeError('camera gone')

    source.set_camera = broken
    ctrl.handle(page.cid, {'kind': 'set_camera', 'exposure': 4.0, 'gain': 1})
    assert not ctrl.active
    assert page.json('ended')['reason'] == 'failed'


def _refuse(source, *exposures):
    """The camera refuses these exposures (and takes everything else, including the way back)."""
    def set_camera(exposure, gain):
        source.calls.append(('set_camera', exposure, gain))
        if any(math.isclose(exposure, e) for e in exposures):
            raise RuntimeError('LIMITS_PREVIEW_FPS went to Alert')
    source.set_camera = set_camera


def test_a_refused_set_camera_goes_back_and_the_session_goes_on(session, source):
    ctrl, page = session
    _refuse(source, 4.0)
    ctrl.handle(page.cid, {'kind': 'set_camera', 'exposure': 4.0, 'gain': 100.0, 'cmd_id': 7})
    err = page.json('error')
    assert err['command'] == 'set_camera' and err['cmd_id'] == 7
    assert err['message'] == 'The camera did not take 4 s at gain 100. It is back on 2 s at gain 100.'
    assert source.calls[-2:] == [('set_camera', 4.0, 100.0), ('set_camera', 2.0, 100.0)]
    assert ctrl.active and (ctrl.exposure, ctrl.gain) == (2.0, 100.0)
    assert page.json('mode')['exposure'] == 2.0  # the sliders snap back


def test_a_refused_tune_point_is_skipped_and_the_tune_goes_on(connect, make, source):
    cid, page = connect()
    _refuse(source, 0.2)
    ctrl = _tuned(make, exposures=(0.1, 0.2, 0.4))
    ctrl.begin(cid)
    page.json('progress', what='tune')
    source.frames.put(raw_frame((), exposure=0.1))
    step = page.json('progress', what='tune', pump=ctrl.service)
    assert step['message'] == 'Tuning: 3 of 3 · 0.4 s' and step['done'] is False
    assert source.calls[-3:] == [('set_camera', 0.2, 100.0), ('set_camera', 0.1, 100.0), ('set_camera', 0.4, 100.0)]
    assert ctrl.active
    source.frames.put(raw_frame(GRID, exposure=0.4, t_end=1003.0))
    assert page.json('progress', what='tune', pump=ctrl.service)['message'] == 'Tuned: 0.4 s · 16 stars.'


def test_a_refused_search_step_stops_the_search(connect, make, source):
    cid, page = connect()
    _refuse(source, 2.0)
    ctrl = make(exposure=1.0, search=lambda e, g, lim: ExposureSearch(0.001, 15.0, e))
    ctrl.begin(cid)
    source.frames.put(raw_frame((), exposure=1.0))
    step = page.json('progress', what='exposure_search', pump=ctrl.service)
    assert step['done'] is True
    assert step['message'] == 'The camera did not take 2 s at gain 100. It is back on 1 s at gain 100.'
    assert ctrl.active and ctrl.exposure == 1.0


def test_service_start_that_fails_returns_false(link, connect, source):
    def broken(roi, exposure, gain):
        raise RuntimeError('no camera')

    source.start = broken
    made = []

    def make_controller(cid):
        made.append(FocusController(source, link, FakeClock(), RIG, False, epoch=Epoch(), exposure=1.0, gain=1.0))
        return made[-1]

    service = FocusService(link, INFO, make_controller)
    cid, page = connect()
    page.client.send({'kind': 'start'})
    results = []
    idle = page.json('state', pump=lambda: results.append(service.poll()), idle_reason='failed')
    assert idle['session'] == 'idle'
    assert True not in results
    assert len(made) == 1 and service.controller is None


def test_saturated_star_never_counts(session, source, epoch):
    ctrl, page = session
    stars = list(GRID)
    bright = stars[5]
    stars[5] = synth.Star(bright.x, bright.y, bright.sigma, 3e6)  # clips at 65535 in the raw
    picked = run_pick(ctrl, page, source, epoch, stars=stars)
    states = {s['id']: s['state'] for s in picked['stars']}
    sat = [i for i, state in states.items() if state == 'saturated']
    assert len(sat) == 1
    (sat_id,) = sat
    star = next(s for s in picked['stars'] if s['id'] == sat_id)
    assert (star['x'], star['y']) == (pytest.approx(bright.x, abs=1.0), pytest.approx(bright.y, abs=1.0))

    source.frames.put(raw_frame(stars, t_end=1010.0, exposure=2.0))
    r = reading(page, 4, ctrl)
    rings = {ring['id']: ring for ring in r['rings']}
    assert rings[sat_id]['state'] == 'saturated'
    others = [ring['size'] for i, ring in rings.items() if i != sat_id and ring['state'] == 'kept']
    assert r['stars_used'] == len(others) > 0
    assert r['size'] == pytest.approx(statistics.median(others))

    # pinned, it is still left out, and the page says why
    ctrl.handle(page.cid, {'kind': 'star', 'id': sat_id, 'state': 'pin'})
    page.json('stars')
    source.frames.put(raw_frame(stars, t_end=1012.0, exposure=2.0))
    r = reading(page, 5, ctrl)
    assert r['stars_used'] == 0
    assert r['size'] is None
    assert r['message'] == controller_mod.MSG_SATURATED
    assert {ring['id']: ring['state'] for ring in r['rings']}[sat_id] == 'saturated'


class SlowWholeSource(FakeSource):
    """whole_frame waits until released or stopped, like a stills source with no picture yet."""

    def __init__(self):
        super().__init__()
        self.release = threading.Event()
        self.waiting = threading.Event()
        self.stopped = False

    def whole_frame(self):
        self.calls.append(('whole_frame',))
        self.waiting.set()
        self.release.wait(10.0)
        if self.stopped:
            raise RuntimeError('stopped')
        return self.whole

    def stop(self):
        super().stop()
        self.stopped = True
        self.release.set()


def test_slow_preview_never_blocks_commands(link, connect, closers):
    source = SlowWholeSource()

    def make_controller(cid):
        ctrl = FocusController(source, link, FakeClock(), RIG, False, epoch=Epoch(), exposure=1.0, gain=1.0)
        closers.append(_Ender(ctrl))
        return ctrl

    service = FocusService(link, INFO, make_controller)
    cid, page = connect()
    page.client.send({'kind': 'start'})
    page.json('mode', pump=service.poll)

    t0 = time.monotonic()
    page.client.send({'kind': 'preview'})
    assert wait_for(lambda: service.poll() or source.waiting.is_set(), timeout=2.0)
    page.client.send({'kind': 'ping', 'id': 9})
    assert page.json('pong', pump=service.poll, timeout=2.0)['id'] == 9
    page.client.send({'kind': 'preview'})
    busy = page.json('error', pump=service.poll, timeout=2.0)
    assert (busy['command'], busy['message']) == ('preview', controller_mod.MSG_PREVIEW_BUSY)
    page.client.send({'kind': 'done'})
    assert page.json('ended', pump=service.poll, timeout=2.0)['reason'] == 'done'
    assert time.monotonic() - t0 < 2.0

    for _ in range(10):
        service.poll()
    late = [m[1] for m in page.drain() if m[0] == 'json']
    assert not [m for m in late if m.get('kind') == 'preview' or m.get('command') == 'preview']
    assert not [t for t in threading.enumerate() if t.name == 'focus-preview']


# --- fix round 1 ---------------------------------------------------------------------------------------------------

def test_huge_int_is_invalid_not_a_crash(session, source):
    ctrl, page = session
    huge = int('9' * 400)  # valid JSON; float() of it overflows
    ctrl.handle(page.cid, {'kind': 'set_camera', 'exposure': huge, 'gain': 1})
    assert page.json('error', command='set_camera')['message'] == 'Not a valid exposure.'
    ctrl.handle(page.cid, {'kind': 'min_snr', 'value': -huge})
    assert page.json('error', command='min_snr')['message'] == 'Not a valid brightness.'
    assert ctrl.active
    assert 'set_camera' not in source.kinds()


def test_handler_bug_gets_an_error_and_the_session_goes_on(session, source, monkeypatch, caplog):
    ctrl, page = session

    def broken(cid, msg):
        raise KeyError('secret-page-input')

    monkeypatch.setattr(ctrl, '_cmd_keep_going', broken)
    ctrl.handle(page.cid, {'kind': 'keep_going', 'note': 'secret-page-input'})
    err = page.json('error', command='keep_going')
    assert err['message'] == controller_mod.MSG_COMMAND_FAILED
    assert ctrl.active
    ctrl.handle(page.cid, {'kind': 'ping', 'id': 2})
    assert page.json('pong')['id'] == 2
    assert 'note' not in caplog.text


def test_failed_start_does_not_take_the_rest_of_the_batch(link, connect, source, closers):
    def broken(roi, exposure, gain):
        source.calls.append(('start', roi, exposure, gain))
        raise RuntimeError('no camera')

    source.start = broken
    service = FocusService(link, INFO, lambda cid: FocusController(source, link, FakeClock(), RIG, False,
                                                                   epoch=Epoch(), exposure=1.0, gain=1.0))
    cid, page = connect()
    page.client.send({'kind': 'start'})
    page.client.send({'kind': 'set_region', 'roi': [0, 0, 64, 64]})
    page.client.send({'kind': 'set_camera', 'exposure': 2.0, 'gain': 1})
    time.sleep(0.3)  # all three in one poll batch
    assert service.poll() is False
    assert page.json('ended')['reason'] == 'failed'
    for _ in range(5):
        service.poll()
    after = [m[1] for m in page.drain() if m[0] == 'json']
    assert {m['kind'] for m in after} <= {'state', 'error'}
    assert [m['command'] for m in after if m['kind'] == 'error'] == ['set_region', 'set_camera']
    assert all(m['session'] == 'idle' for m in after if m['kind'] == 'state')
    assert source.kinds() == ['start', 'stop']  # never restarted


def test_ended_controller_refuses_commands(connect, make, source):
    cid, page = connect()

    def broken(roi, exposure, gain):
        raise RuntimeError('no camera')

    source.start = broken
    ctrl = make()
    ctrl.begin(cid)
    page.json('ended')
    ctrl.handle(cid, {'kind': 'set_region', 'roi': [0, 0, 64, 64]})
    assert page.json('error', command='set_region')['message'] == controller_mod.MSG_NO_SESSION
    assert source.kinds() == ['stop']


def test_pick_keeps_every_star(session, source, epoch):
    ctrl, page = session
    many = synth.grid_stars(SHAPE, 1.5, 20000, spacing=30, margin=30)
    assert len(many) > 20
    stars = run_pick(ctrl, page, source, epoch, stars=many)
    assert len(stars['stars']) == len(many)


def test_grading_covers_about_4_s_with_no_cap(session, source, epoch):
    ctrl, page = session
    exposure = 0.25  # 4 s is 16 frames: more than the old cap of 10
    epoch.t = 1000.0
    ctrl.handle(page.cid, {'kind': 'pick_stars'})
    for n in range(1, 17):
        source.frames.put(raw_frame(GRID, t_end=1000.0 + exposure * n, exposure=exposure))
        reading(page, n, ctrl)
        ctrl.service()
        got = [m for m in page.drain(0.05) if m[0] == 'json' and m[1].get('kind') == 'stars']
        if n < 16:
            assert not got, 'graded after {0:d} frames'.format(n)
    assert len(got) == 1 and len(got[0][1]['stars']) == len(GRID)


def test_preview_released_by_a_region_change_is_quiet(session, source, monkeypatch, caplog):
    ctrl, page = session
    slow = SlowWholeSource()
    ctrl.source = slow
    ctrl.handle(page.cid, {'kind': 'preview'})
    assert slow.waiting.wait(2.0)
    ctrl.handle(page.cid, {'kind': 'set_region', 'roi': [0, 0, 64, 64]})
    page.json('mode')
    assert wait_for(lambda: not ctrl._preview_thread.is_alive())
    for _ in range(5):
        ctrl.service()
    msgs = [m[1] for m in page.drain() if m[0] == 'json']
    assert not [m for m in msgs if m.get('kind') == 'preview' or m.get('command') == 'preview']
    assert not [r for r in caplog.records if r.levelname == 'ERROR']


def test_preview_before_any_frame_uses_the_source_bayer(session, source, monkeypatch):
    ctrl, page = session
    source.bayer = 'rggb'
    seen = []
    real = controller_mod.to_gray

    def spy(raw, bayer):
        seen.append(bayer)
        return real(raw, bayer)

    monkeypatch.setattr(controller_mod, 'to_gray', spy)
    ctrl.handle(page.cid, {'kind': 'preview'})
    page.json('preview', pump=ctrl.service)
    assert seen == ['RGGB']


# --- camera limits (Task 12 fix round 1) ---------------------------------------------------------------------------

LIMITS = {'exposure_min': 0.001, 'exposure_max': 5.0, 'gain_min': 0.0, 'gain_max': 400.0}


def test_mode_carries_the_camera_limits(connect, make):
    cid, page = connect()
    ctrl = make(exposure=2.0, **LIMITS)
    ctrl.begin(cid)
    mode = page.json('mode')
    assert {k: mode[k] for k in LIMITS} == LIMITS


def test_mode_limits_are_null_when_unknown(connect, make):
    cid, page = connect()
    ctrl = make(exposure=2.0)
    ctrl.begin(cid)
    mode = page.json('mode')
    assert [mode[k] for k in LIMITS] == [None, None, None, None]


@pytest.mark.parametrize('exposure, gain, message', [
    (6.0, 100, 'exposure'),
    (0.0005, 100, 'exposure'),
    (1.0, 401, 'gain'),
])
def test_set_camera_outside_the_limits_is_refused_and_never_reaches_the_camera(
        connect, make, source, exposure, gain, message):
    cid, page = connect()
    ctrl = make(exposure=2.0, **LIMITS)
    ctrl.begin(cid)
    page.json('mode')
    ctrl.handle(cid, {'kind': 'set_camera', 'exposure': exposure, 'gain': gain, 'cmd_id': 9})
    err = page.json('error', command='set_camera')
    expected = controller_mod.MSG_EXPOSURE_RANGE if message == 'exposure' else controller_mod.MSG_GAIN_RANGE
    assert err['message'] == expected
    assert err['cmd_id'] == 9
    assert 'set_camera' not in source.kinds()
    assert ctrl.active
    assert ctrl.ledger.effective_before(1e12) == 0


def test_set_camera_at_the_limits_is_taken(connect, make, source):
    cid, page = connect()
    ctrl = make(exposure=2.0, **LIMITS)
    ctrl.begin(cid)
    ctrl.handle(cid, {'kind': 'set_camera', 'exposure': 5.0, 'gain': 400})
    assert ('set_camera', 5.0, 400.0) in source.calls


def test_set_camera_with_no_gain_limits_takes_gain_zero(connect, make, source):
    cid, page = connect()
    ctrl = make(exposure=2.0, exposure_min=0.001, exposure_max=5.0, gain_min=None, gain_max=None)
    ctrl.begin(cid)
    ctrl.handle(cid, {'kind': 'set_camera', 'exposure': 1.0, 'gain': 0})
    assert ('set_camera', 1.0, 0.0) in source.calls


def test_errors_carry_the_command_id(session):
    ctrl, page = session
    ctrl.handle(page.cid, {'kind': 'set_region', 'roi': 'x', 'cmd_id': 12})
    assert page.json('error', command='set_region')['cmd_id'] == 12
    ctrl.handle(page.cid, {'kind': 'set_region', 'roi': 'x', 'cmd_id': 'bad'})
    assert page.json('error', command='set_region')['cmd_id'] is None


# -- final review ------------------------------------------------------------------------------------------------------

SECRET_BODY = 'S3CRET-BODY-c0ffee'


class GainlessSource(FakeSource):
    """A camera whose driver has no gain property the stream can set."""

    def can_set_gain(self):
        return False


def test_a_source_that_cannot_set_gain_sends_no_gain_limits_and_keeps_its_gain(link, connect, epoch, closers):
    source = GainlessSource()
    ctrl = FocusController(source, link, FakeClock(), RIG, False, epoch=epoch, exposure=1.0, gain=100.0,
                           gain_min=0.0, gain_max=510.0)
    closers.append(_Ender(ctrl))
    cid, page = connect()
    ctrl.begin(cid)
    assert (ctrl.limits['gain_min'], ctrl.limits['gain_max']) == (None, None)
    ctrl.handle(cid, {'kind': 'set_camera', 'exposure': 4.0, 'gain': 300, 'cmd_id': 3})
    assert ('set_camera', 4.0, 100.0) in source.calls
    mode = page.json('mode', exposure=4.0)
    assert (mode['gain'], mode['gain_min'], mode['gain_max']) == (100.0, None, None)


def test_a_command_bug_logs_the_kind_and_type_only(session, monkeypatch, caplog):
    ctrl, page = session

    def broken(cid, msg):
        raise ValueError('page said ' + SECRET_BODY)

    monkeypatch.setattr(ctrl, '_cmd_keep_going', broken)
    with caplog.at_level('DEBUG', logger='indi_allsky'):
        ctrl.handle(page.cid, {'kind': 'keep_going', 'note': SECRET_BODY})
    assert page.json('error', command='keep_going')
    warnings = [r for r in caplog.records if r.levelname == 'WARNING' and 'keep_going' in r.getMessage()]
    assert len(warnings) == 1 and 'ValueError' in warnings[0].getMessage()
    assert not [r for r in caplog.records if r.levelname in ('ERROR', 'CRITICAL')]
    assert SECRET_BODY not in caplog.text
    assert all(r.exc_info is None for r in caplog.records)


def test_step_sizes_are_lens_degrees_until_a_good_fit():
    from indi_allsky.focus.controller import step_sizes
    per_lens_turn = 512 * 82 / 12.0          # 28BYJ-48 through 82:12 gears
    assert step_sizes(per_lens_turn, None) == {'fine': 8, 'medium': 34, 'coarse': 126}
    assert step_sizes(per_lens_turn, {'ok': False, 'band': [100, 140]}) == {'fine': 8, 'medium': 34, 'coarse': 126}
    # a good fit: Fine is a quarter of the band, Medium the band; Coarse stays fixed
    assert step_sizes(per_lens_turn, {'ok': True, 'band': [100, 140]}) == {'fine': 10, 'medium': 40, 'coarse': 126}
    assert step_sizes(512, {'ok': True, 'band': [0, 1]}) == {'fine': 1, 'medium': 1, 'coarse': 18}
