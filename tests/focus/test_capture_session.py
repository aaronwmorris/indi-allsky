from __future__ import annotations

import json
import os
import queue
import time
from types import SimpleNamespace

import numpy as np
import pytest

from indi_allsky import constants
from indi_allsky.focus.capture_session import FocusGlue
from indi_allsky.focus.gearing import MSG_GEAR_LIMIT_UNSET
from indi_allsky.focus.gearing import MSG_GEAR_UNSET
from indi_allsky.focus.gearing import MSG_LIMIT_UNSET
from indi_allsky.focus.capture_session import MSG_MOTOR_OPEN
from indi_allsky.focus.capture_session import open_link
from indi_allsky.focus.capture_session import state_path_for
from indi_allsky.focus.controller import MSG_MISSING_PROPERTY
from indi_allsky.focus.controller import MSG_NO_MOTOR
from indi_allsky.focus.controller import focus_sleep
from indi_allsky.focus.controller import focus_wait_turn
from indi_allsky.focus.controller import run_session_pass
from indi_allsky.focus.link import LinkClient
from indi_allsky.focus.link import LinkServer
from tests.focus.test_controller import Page
from tests.focus.test_controller import wait_for
from tests.focus.test_indi_stream import FakeClient
from tests.focus.test_lens import FakeClock as LensClock
from tests.focus.test_lens import FakeDriver


CCD_INFO = {
    'CCD_EXPOSURE': {'CCD_EXPOSURE_VALUE': {'min': 0.000032, 'max': 3600.0}},
    'CCD_INFO': {'CCD_BITSPERPIXEL': {'current': 16}},
    'CCD_FRAME': {'WIDTH': {'max': 640}, 'HEIGHT': {'max': 480}},
    'GAIN_INFO': {'current': 7.0, 'min': 0.0, 'max': 510.0, 'step': 1.0},
}


class FakeMiscDb(object):
    def __init__(self):
        self.states = []

    def setState(self, key, value):
        self.states.append((key, value))

    def getState(self, key):
        # miscDb.getState: the stored value as a string; NoResultFound (here KeyError) when there is none
        value = self.last(key)
        if value is None:
            raise KeyError(key)
        return str(value)

    def last(self, key):
        values = [v for k, v in self.states if k == key]
        return values[-1] if values else None


class Camera(FakeClient):
    """A video camera with a 30 s normal exposure under way."""

    def __init__(self):
        super(Camera, self).__init__()
        self.image_q = queue.Queue()
        self.exposing = True
        self.disconnected = False
        self.ccd_removed = False

    def abortCcdExposure(self):
        self.aborts += 1
        self.exposing = False

    def getCcdExposureStatus(self):
        return (not self.exposing), ('BUSY' if self.exposing else 'READY')


@pytest.fixture
def rig(sock_path, closers):
    return _make_rig(sock_path, closers)


def _make_rig(sock_path, closers, **glue_kw):
    link = LinkServer(sock_path)
    link.start()
    closers.append(link)
    camera = Camera()
    reconfigured = []
    notices = []
    glue = FocusGlue(
        camera, link,
        camera_interface='test_rotating_stars', device_name='Rotating Stars Test Camera',
        ccd_info=CCD_INFO, cfa=None, gain=lambda: 7.0,
        state_path=state_path_for(sock_path),
        reconfigure=lambda: reconfigured.append(True),
        exposure_max=5.0,
        notify=lambda key, message: notices.append((key, message)),
        **glue_kw,
    )
    worker = SimpleNamespace(focus=glue.service, _shutdown=False, _miscDb=FakeMiscDb())

    def page():
        before = set(link.clients())
        client = LinkClient(sock_path)
        client.connect(hello={'controls': True})
        closers.append(client)
        assert wait_for(lambda: set(link.clients()) - before)
        return Page(client)

    return SimpleNamespace(link=link, camera=camera, glue=glue, worker=worker, page=page,
                           reconfigured=reconfigured, notices=notices, state_path=state_path_for(sock_path))


def start_session(r):
    page = r.page()
    page.client.send({'kind': 'start'})
    assert wait_for(lambda: run_session_pass(r.worker) and r.worker.focus.active, timeout=3.0)
    return page


def test_state_file_sits_next_to_the_socket():
    assert state_path_for('/var/lib/indi-allsky/focus-session.sock') == \
        '/var/lib/indi-allsky/focus-session.state.json'


def test_start_during_long_exposure_breaks_wait(rig):
    page = rig.page()
    assert run_session_pass(rig.worker) is False  # idle: the normal schedule goes on
    page.client.send({'kind': 'start'})
    time.sleep(0.05)  # the command is on its way
    t0 = time.monotonic()
    left = False
    while time.monotonic() - t0 < 11:  # capture's wait loop, around a 30 s exposure
        if focus_wait_turn(rig.worker):
            left = True
            break
    elapsed = time.monotonic() - t0
    assert left and elapsed < 0.2
    assert rig.camera.aborts == 1  # counted before the session ends
    assert rig.worker.focus.active
    assert os.path.exists(rig.state_path)
    rig.worker.focus.stop('done')


def test_a_start_without_a_plan_is_a_preview(rig):
    # a page from before the two start buttons sends no plan: it must never run on into a pick or a lens move
    start_session(rig)
    assert rig.worker.focus.controller._plan == 'preview'


def test_start_saves_the_camera_state_next_to_the_socket(rig):
    start_session(rig)
    with open(rig.state_path) as f:
        saved = json.load(f)
    assert saved['numbers']['CCD_CONTROLS']['Gain'] == 100.0
    assert saved['switches']['CCD_VIDEO_STREAM'] == ['STREAM_OFF']
    assert rig.camera.blob_sink is not None
    rig.worker.focus.stop('done')


def test_service_feeds_watchdog(rig):
    start_session(rig)
    db = rig.worker._miscDb
    db.states.clear()
    later = time.monotonic() + 60  # past the status throttle
    t0 = time.monotonic()
    assert run_session_pass(rig.worker, clock=lambda: later) is True
    assert time.monotonic() - t0 >= 0.04  # it paces the loop
    assert db.last('STATUS') == constants.STATUS_FOCUSING
    assert db.last('WATCHDOG') is not None
    written = len(db.states)
    assert run_session_pass(rig.worker, clock=lambda: later + 0.1) is True
    assert len(db.states) == written  # not a database write 20 times a second
    rig.worker.focus.stop('done')


def test_stop_ends_session_and_restores(rig):
    page = start_session(rig)
    rig.camera.taken()
    rig.worker._shutdown = True  # SIGTERM, SIGINT or SIGHUP
    assert run_session_pass(rig.worker) is True
    assert not rig.worker.focus.active
    assert page.json('ended')['reason'] == 'stopped'
    calls = rig.camera.taken()
    assert ('switch', 'CCD_VIDEO_STREAM', ('STREAM_OFF',)) in calls
    assert [c[1] for c in calls if c[0] == 'number'][-1] == 'CCD_CONTROLS'
    assert ('switch', 'CCD_VIDEO_STREAM', ('STREAM_ON',)) not in calls
    assert rig.camera.numbers['CCD_CONTROLS']['Gain'][0] == 100.0
    assert rig.camera.blob_sink is None
    assert not os.path.exists(rig.state_path)
    assert rig.reconfigured == [True]
    assert rig.worker._miscDb.last('STATUS') == constants.STATUS_RUNNING
    assert run_session_pass(rig.worker) is False  # the normal schedule resumes


def test_done_from_the_page_ends_and_restores(rig):
    page = start_session(rig)
    page.client.send({'kind': 'done'})
    assert wait_for(lambda: not run_session_pass(rig.worker) and not rig.worker.focus.active, timeout=3.0)
    assert page.json('ended')['reason'] == 'done'
    assert not os.path.exists(rig.state_path)
    assert rig.reconfigured == [True]


def test_disconnected_camera_keeps_the_state_file_for_startup(rig):
    start_session(rig)
    rig.camera.disconnected = True
    rig.worker.focus.stop('stopped')
    assert os.path.exists(rig.state_path)
    assert rig.reconfigured == []


def test_a_failing_poll_ends_the_session_not_capture(rig):
    start_session(rig)

    def broken():
        raise RuntimeError('bug')

    rig.worker.focus.controller.service = broken
    assert run_session_pass(rig.worker) is True
    assert not rig.worker.focus.active
    assert not os.path.exists(rig.state_path)


def test_failed_start_still_leaves_the_wait_and_cleans_up(rig):
    real = rig.camera.set_number

    def broken(device, name, values, sync=True, timeout=None):
        if name == 'CCD_STREAM_FRAME':  # optional to restore, so the state file goes
            raise RuntimeError('no camera')
        return real(device, name, values, sync, timeout)

    rig.camera.set_number = broken  # the stream cannot start
    page = rig.page()
    page.client.send({'kind': 'start'})
    time.sleep(0.05)
    assert wait_for(lambda: focus_wait_turn(rig.worker), timeout=2.0)  # the exposure was aborted all the same
    assert rig.camera.aborts == 1
    assert not rig.worker.focus.active
    assert not os.path.exists(rig.state_path)
    assert focus_wait_turn(rig.worker) is False


def test_classic_rig_refuses_start_without_touching_the_camera(sock_path, closers):
    link = LinkServer(sock_path)
    link.start()
    closers.append(link)
    camera = Camera()
    glue = FocusGlue(camera, link, camera_interface='indi_passive', device_name='x', ccd_info=CCD_INFO, cfa=None,
                     gain=lambda: 0.0, state_path=state_path_for(sock_path), reconfigure=lambda: None)
    worker = SimpleNamespace(focus=glue.service, _shutdown=False, _miscDb=FakeMiscDb())
    client = LinkClient(sock_path)
    client.connect(hello={'controls': True})
    closers.append(client)
    page = Page(client)
    assert wait_for(lambda: link.clients())
    client.send({'kind': 'start'})
    err = page.json('error', pump=lambda: run_session_pass(worker))
    assert err['command'] == 'start'
    assert camera.aborts == 0 and not glue.service.active
    client.send({'kind': 'start'})
    time.sleep(0.05)
    assert focus_wait_turn(worker) is False  # nothing was aborted: capture keeps waiting for its exposure


def test_stills_rig_uses_the_image_queue(sock_path, closers):
    link = LinkServer(sock_path)
    link.start()
    closers.append(link)
    camera = Camera()
    camera.setCcdExposure = lambda *a, **k: None
    original_q = camera.image_q
    glue = FocusGlue(camera, link, camera_interface='indi_accumulator', device_name='x', ccd_info=CCD_INFO,
                     cfa=None, gain=lambda: 0.0, state_path=state_path_for(sock_path), reconfigure=lambda: None)
    worker = SimpleNamespace(focus=glue.service, _shutdown=False, _miscDb=FakeMiscDb())
    client = LinkClient(sock_path)
    client.connect(hello={'controls': True})
    closers.append(client)
    assert wait_for(lambda: link.clients())
    client.send({'kind': 'start'})
    assert wait_for(lambda: run_session_pass(worker) and glue.service.active, timeout=3.0)
    assert camera.image_q is not original_q
    assert camera.blob_sink is None
    glue.service.stop('done')
    assert camera.image_q is original_q


def test_open_link_in_use_gives_none(sock_path, closers):
    first = open_link(sock_path)
    closers.append(first)
    assert first is not None
    assert open_link(sock_path) is None


def test_open_link_on_a_directory_gives_none(tmp_path):
    assert open_link(str(tmp_path)) is None


def test_open_link_on_a_file_leaves_it_and_says_why(tmp_path, caplog):
    path = str(tmp_path / 'notes.txt')  # a mistyped INDI_ALLSKY_FOCUS_ADDRESS
    with open(path, 'w') as f:
        f.write('keep me')
    with caplog.at_level('WARNING', logger='indi_allsky'):
        assert open_link(path) is None
    with open(path) as f:
        assert f.read() == 'keep me'
    assert 'not a socket' in caplog.text


def test_paused_sleep_ends_on_start_and_answers_pages(rig):
    page = rig.page()
    page.client.send({'kind': 'ping', 'id': 3})
    t0 = time.monotonic()
    assert focus_sleep(rig.worker, 0.3) is False  # nothing to start: the whole sleep
    assert time.monotonic() - t0 >= 0.3
    assert page.json('pong')['id'] == 3  # answered during the sleep
    page.client.send({'kind': 'start'})
    t0 = time.monotonic()
    assert focus_sleep(rig.worker, 31) is True
    assert time.monotonic() - t0 < 1.0
    rig.worker.focus.stop('done')


def test_sleep_without_a_link_just_sleeps():
    slept = []
    assert focus_sleep(SimpleNamespace(focus=None), 31, sleep=slept.append) is False
    assert slept == [31]


def test_blob_sink_bypasses_image_queue(fake_pyindi):
    indi = fake_pyindi('indi')

    class Q(object):
        def put(self, *a, **k):
            raise AssertionError('image_q touched')

    class Blob(object):
        def __init__(self, data, fmt):
            self._data, self._fmt = data, fmt

        def getblobdata(self):
            return self._data

        def getFormat(self):
            return self._fmt

    client = indi.IndiClient.__new__(indi.IndiClient)
    client.image_q = Q()
    client.exposureStartTime = 0
    got = []
    client.blob_sink = lambda data, fmt, t: got.append((data, fmt, t))
    client.processBlob(Blob(b'\x00\x01' * 8, '.stream'))
    assert got and got[0][:2] == (b'\x00\x01' * 8, '.stream') and isinstance(got[0][2], float)

    def raising(data, fmt, t):
        raise RuntimeError('sink bug')

    client.blob_sink = raising
    client.processBlob(Blob(b'xx', '.stream'))  # never kills the INDI thread

    client.blob_sink = None
    client.processBlob(Blob(b'xx', '.stream'))  # a late stream frame with no session: dropped
    client.processBlob(Blob(b'xx', '.stream.z'))
    assert indi.IndiClient.blob_sink is None  # off unless a session sets it


def test_indi_client_has_video_checks_the_property(fake_pyindi):
    indi = fake_pyindi('indi')

    class Prop(object):
        def __init__(self, valid):
            self.valid = valid

        def isValid(self):
            return self.valid

        def __bool__(self):
            return True

    class Device(object):
        def __init__(self, prop):
            self.prop = prop

        def getSwitch(self, name):
            return self.prop if name == 'CCD_VIDEO_STREAM' else None

    client = indi.IndiClient.__new__(indi.IndiClient)
    client._ccd_device = Device(Prop(True))
    assert client.has_video() is True
    client._ccd_device = Device(Prop(False))
    assert client.has_video() is False
    client._ccd_device = Device(None)
    assert client.has_video() is False
    client._ccd_device = object()  # FakeIndiCcd and friends have no switches
    assert client.has_video() is False


def test_test_camera_streams_frames(fake_pyindi):
    tc = fake_pyindi('test_cameras')

    class Tiny(tc.IndiClientTestCameraBase):
        def updateImage(self, binning):
            img = np.zeros((48, 64, 3), dtype=np.uint16)
            img[20:23, 30:33] = 30000
            self._image = img

    cam = Tiny.__new__(Tiny)
    got = []
    cam.blob_sink = lambda data, fmt, t: got.append((data, fmt, t))
    cam.sim_position = 0
    assert cam.has_video() is True
    cam.start_video(0.02, (16, 8, 32, 32))
    assert wait_for(lambda: len(got) >= 3, timeout=3.0)
    cam.stop_video()
    n = len(got)
    time.sleep(0.1)
    assert len(got) <= n + 1
    data, fmt, t = got[0]
    assert fmt == '.stream' and len(data) == 32 * 32 * 2
    raw = np.frombuffer(data, dtype='<u2').reshape(32, 32)
    assert raw[12:15, 14:17].min() == 30000  # the crop starts at (16, 8)

    cam.sim_position = 40  # out of focus: the star spreads
    got.clear()
    cam.start_video(0.02, (16, 8, 32, 32))
    assert wait_for(lambda: len(got) >= 1, timeout=3.0)
    cam.stop_video()
    blurred = np.frombuffer(got[0][0], dtype='<u2').reshape(32, 32)
    assert blurred.max() < raw.max()
    assert (blurred > 1000).sum() > (raw > 1000).sum()


# -- fix round 1 ------------------------------------------------------------------------------------------------------

def test_ceiling_is_the_configured_exposure_max_not_the_drivers(rig):
    start_session(rig)  # the driver allows 3600 s; the config says 5 s
    ctrl = rig.worker.focus.controller
    assert ctrl.limits['exposure_max'] == 5.0
    assert ctrl._search.kind == 'tune'  # a video rig tunes; its ladder (up to 1.6 s) is inside the ceiling
    assert max(p.exposure for p in ctrl._search.points) == 1.6
    rig.worker.focus.stop('done')


def test_controller_gets_the_camera_limits_capture_already_knows(rig):
    start_session(rig)  # exposure: the driver's shortest to the configured ceiling; gain: the driver's GAIN_INFO
    assert rig.worker.focus.controller.limits == {
        'exposure_min': 0.000032, 'exposure_max': 5.0, 'gain_min': 0.0, 'gain_max': 510.0}
    rig.worker.focus.stop('done')


def test_unknown_limits_are_none(rig):
    rig.glue.ccd_info = {k: v for k, v in CCD_INFO.items() if k not in ('GAIN_INFO', 'CCD_EXPOSURE')}
    start_session(rig)
    limits = rig.worker.focus.controller.limits
    assert (limits['exposure_min'], limits['gain_min'], limits['gain_max']) == (None, None, None)
    assert limits['exposure_max'] == 5.0  # the config's ceiling is always known
    rig.worker.focus.stop('done')


@pytest.mark.parametrize('gain_min, gain_max', [
    (-1.0, -1.0),   # indi.py fake_gain_info: the camera has no gain control
    (10.0, 5.0),    # an upside-down range
])
def test_a_sentinel_gain_range_is_unknown(rig, gain_min, gain_max):
    rig.glue.ccd_info = dict(CCD_INFO, GAIN_INFO={'current': 0.0, 'min': gain_min, 'max': gain_max, 'step': 1.0})
    start_session(rig)
    limits = rig.worker.focus.controller.limits
    assert (limits['gain_min'], limits['gain_max']) == (None, None)
    rig.worker.focus.stop('done')


def test_a_driver_without_a_gain_property_sends_no_gain_limits(rig):
    del rig.camera.numbers['CCD_CONTROLS']  # GAIN_INFO still says 0 .. 510: the stream cannot set it all the same
    start_session(rig)
    limits = rig.worker.focus.controller.limits
    assert (limits['gain_min'], limits['gain_max']) == (None, None)
    rig.worker.focus.stop('done')


@pytest.mark.parametrize('before', [constants.STATUS_PAUSED, constants.STATUS_SLEEPING, constants.STATUS_RUNNING])
def test_the_status_before_the_session_comes_back_after_it(rig, before):
    rig.worker._miscDb.setState('STATUS', before)  # capture paused, asleep for the day, or running
    start_session(rig)
    assert rig.worker._miscDb.last('STATUS') == constants.STATUS_FOCUSING
    rig.worker.focus.stop('done')
    assert run_session_pass(rig.worker) is True
    assert rig.worker._miscDb.last('STATUS') == before


def test_status_is_running_after_a_session_when_none_was_known(rig):
    start_session(rig)
    rig.worker.focus.stop('done')
    run_session_pass(rig.worker)
    assert rig.worker._miscDb.last('STATUS') == constants.STATUS_RUNNING


def test_a_fixed_gain_keeps_its_limits(rig):
    rig.glue.ccd_info = dict(CCD_INFO, GAIN_INFO={'current': 1.0, 'min': 1.0, 'max': 1.0, 'step': 1.0})
    start_session(rig)
    limits = rig.worker.focus.controller.limits
    assert (limits['gain_min'], limits['gain_max']) == (1.0, 1.0)
    rig.worker.focus.stop('done')


def test_driver_without_a_required_property_refuses_and_leaves_the_camera_alone(rig):
    del rig.camera.numbers['STREAMING_EXPOSURE']
    page = rig.page()
    page.client.send({'kind': 'start'})
    err = page.json('error', pump=lambda: run_session_pass(rig.worker))
    assert err['command'] == 'start'
    assert err['message'] == MSG_MISSING_PROPERTY.format('STREAMING_EXPOSURE')
    assert rig.camera.aborts == 0 and rig.camera.exposing
    assert rig.camera.taken() == []
    assert rig.camera.blob_sink is None
    assert not os.path.exists(rig.state_path)
    assert not rig.worker.focus.active
    assert focus_wait_turn(rig.worker) is False  # capture keeps waiting for its exposure


def test_a_required_property_not_restored_keeps_the_file_and_notifies(rig):
    start_session(rig)
    real = rig.camera.set_number

    def failing(device, name, values, sync=True, timeout=None):
        if name == 'STREAMING_EXPOSURE':
            raise TimeoutError(name)
        return real(device, name, values, sync, timeout)

    rig.camera.set_number = failing
    rig.worker.focus.stop('done')
    assert os.path.exists(rig.state_path)  # the next capture start tries again
    assert [k for k, _ in rig.notices] == ['focus_restore']
    assert 'STREAMING_EXPOSURE' in rig.notices[0][1]
    assert rig.camera.blob_sink is None
    assert rig.reconfigured == [True]


def test_an_optional_property_not_restored_deletes_the_file_quietly(rig):
    start_session(rig)
    real = rig.camera.set_number

    def failing(device, name, values, sync=True, timeout=None):
        if name == 'LIMITS':
            raise TimeoutError(name)
        return real(device, name, values, sync, timeout)

    rig.camera.set_number = failing
    rig.worker.focus.stop('done')
    assert not os.path.exists(rig.state_path)
    assert rig.notices == []


def test_end_always_clears_the_blob_sink(rig):
    start_session(rig)
    rig.camera.blob_sink = lambda *a: None  # not the source's own: its stop leaves it
    rig.camera.disconnected = True  # on_end returns early
    rig.worker.focus.stop('stopped')
    assert rig.camera.blob_sink is None


def test_a_failing_end_still_puts_the_camera_back(rig):
    start_session(rig)
    controller = rig.worker.focus.controller

    def broken(reason):
        raise RuntimeError('bug')

    controller.end = broken
    rig.worker.focus.stop('stopped')
    assert not rig.worker.focus.active and rig.worker.focus.controller is None
    assert rig.worker.focus.idle_reason == 'stopped'
    assert rig.reconfigured == [True]
    controller._stop.set()  # end() never ran: stop its worker here
    controller.source.stop()


def test_failure_logs_name_the_error_type_not_its_message(rig, caplog):
    start_session(rig)

    def broken():
        raise RuntimeError('words a page sent')

    rig.worker.focus.controller.service = broken
    with caplog.at_level('DEBUG', logger='indi_allsky'):
        assert run_session_pass(rig.worker) is True
    assert 'Focus: the session failed (RuntimeError)' in caplog.text
    assert 'words a page sent' not in caplog.text
    assert not any(r.exc_info for r in caplog.records)


def test_a_failing_setup_logs_the_error_type_only(rig, caplog):
    def broken(*args, **kwargs):
        raise ValueError('words a page sent')

    rig.glue.service._make = broken
    page = rig.page()
    page.client.send({'kind': 'start'})
    with caplog.at_level('DEBUG', logger='indi_allsky'):
        err = page.json('error', pump=lambda: run_session_pass(rig.worker))
    assert err['command'] == 'start'
    assert 'Focus: the session could not be set up (ValueError)' in caplog.text
    assert 'words a page sent' not in caplog.text


def test_a_second_session_keeps_the_settings_the_first_could_not_put_back(rig):
    rig.camera.numbers['STREAMING_EXPOSURE']['STREAMING_EXPOSURE_VALUE'] = (2.0, 0.000032, 3600)
    start_session(rig)
    real = rig.camera.set_number

    def failing(device, name, values, sync=True, timeout=None):
        if name == 'STREAMING_EXPOSURE':
            raise TimeoutError(name)
        return real(device, name, values, sync, timeout)

    rig.camera.set_number = failing
    rig.worker.focus.stop('done')
    assert os.path.exists(rig.state_path)
    rig.camera.set_number = real  # the driver answers again
    assert rig.camera.numbers['STREAMING_EXPOSURE']['STREAMING_EXPOSURE_VALUE'][0] != 2.0

    start_session(rig)  # the camera still holds the first session's exposure
    rig.worker.focus.stop('done')
    assert rig.camera.numbers['STREAMING_EXPOSURE']['STREAMING_EXPOSURE_VALUE'][0] == 2.0  # the original value
    assert not os.path.exists(rig.state_path)


GEARS = dict(gear_motor_teeth=12, gear_lens_teeth=82, travel_limit_lens_degrees=30.0, backlash_degrees=30.0)


class _Driver(FakeDriver):
    def __init__(self):
        super().__init__(LensClock())
        self.deinits = 0

    def deinit(self):
        self.deinits += 1


def test_a_focus_motor_opens_with_the_session_and_closes_with_it(sock_path, closers):
    drivers = []

    def opener():
        drivers.append(_Driver())
        return drivers[-1]

    r = _make_rig(sock_path, closers, open_focuser=opener, **GEARS)
    page = start_session(r)
    state = page.json('state', session='active', pump=lambda: run_session_pass(r.worker))
    assert state['motor'] == {'configured': True, 'ok': True, 'reason': None}
    lens = page.json('lens', pump=lambda: run_session_pass(r.worker))
    # the limit is lens degrees through the 82:12 gears; the backlash is motor degrees
    per_lens_turn = 512 * 82 / 12.0
    assert lens['steps_per_lens_turn'] == per_lens_turn
    assert lens['limit'] == round(30 * per_lens_turn / 360) and lens['backlash'] == round(30 * 512 / 360)
    r.worker.focus.stop('done')
    assert len(drivers) == 1 and drivers[0].deinits == 1


def test_a_focus_motor_that_will_not_open_leaves_focus_by_hand(sock_path, closers):
    def opener():
        raise OSError('no I2C device')

    r = _make_rig(sock_path, closers, open_focuser=opener, **GEARS)
    page = start_session(r)
    state = page.json('state', session='active', pump=lambda: run_session_pass(r.worker))
    assert state['motor'] == {'configured': True, 'ok': False, 'reason': MSG_MOTOR_OPEN}
    page.client.send({'kind': 'nudge', 'steps': 5, 'cmd_id': 1})
    err = page.json('error', pump=lambda: run_session_pass(r.worker))
    assert err['message'] == MSG_NO_MOTOR
    r.worker.focus.stop('done')


def test_no_focus_motor_configured(rig):
    page = start_session(rig)
    assert page.json('state', session='active', pump=lambda: run_session_pass(rig.worker))['motor'] == {'configured': False, 'ok': False, 'reason': None}
    rig.worker.focus.stop('done')


@pytest.mark.parametrize('settings, reason', [
    (dict(GEARS, gear_motor_teeth=0), MSG_GEAR_UNSET),
    (dict(GEARS, travel_limit_lens_degrees=0), MSG_LIMIT_UNSET),
    (dict(GEARS, gear_lens_teeth=0, travel_limit_lens_degrees=0), MSG_GEAR_LIMIT_UNSET),
])
def test_a_focus_motor_without_its_gears_or_limit_stays_closed(sock_path, closers, settings, reason):
    opened = []

    def opener():
        opened.append(1)
        return _Driver()

    r = _make_rig(sock_path, closers, open_focuser=opener, **settings)
    page = start_session(r)
    state = page.json('state', session='active', pump=lambda: run_session_pass(r.worker))
    assert state['motor'] == {'configured': True, 'ok': False, 'reason': reason}
    assert opened == []
    r.worker.focus.stop('done')
