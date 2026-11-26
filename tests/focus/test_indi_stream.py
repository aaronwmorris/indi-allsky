from __future__ import annotations

import json
import os
import threading
import time

import numpy as np
import pytest

from indi_allsky.focus import indi_stream
from indi_allsky.focus.indi_stream import NUMBERS
from indi_allsky.focus.indi_stream import SWITCHES
from indi_allsky.focus.indi_stream import IndiStreamSource
from indi_allsky.focus.indi_stream import MissingProperty
from indi_allsky.focus.indi_stream import focus_startup_restore
from indi_allsky.focus.indi_stream import has_video
from indi_allsky.focus.indi_stream import restore_state
from indi_allsky.focus.indi_stream import save_state
from indi_allsky.focus.indi_stream import required_properties
from indi_allsky.focus.indi_stream import CONTROL_TIMEOUT_S
from indi_allsky.focus.indi_stream import OPTIONAL_LOOK_S


SENSOR = (640, 480)


class Elem(object):
    def __init__(self, name, value=0.0, low=0.0, high=1e9, on=False):
        self._name, self._value, self._min, self._max, self._on = name, value, low, high, on

    def getName(self):
        return self._name

    def getValue(self):
        return self._value

    def getMin(self):
        return self._min

    def getMax(self):
        return self._max

    def getState(self):
        return 1 if self._on else 0


def default_numbers():
    return {
        'CCD_CONTROLS': {'Gain': (100.0, 0, 600), 'Offset': (10.0, 0, 255)},
        'CCD_FRAME': {'X': (0.0, 0, 640), 'Y': (0.0, 0, 480), 'WIDTH': (640.0, 1, 640), 'HEIGHT': (480.0, 1, 480)},
        'CCD_BINNING': {'HOR_BIN': (1.0, 1, 4), 'VER_BIN': (1.0, 1, 4)},
        'CCD_STREAM_FRAME': {'X': (0.0, 0, 640), 'Y': (0.0, 0, 480), 'WIDTH': (640.0, 1, 640),
                             'HEIGHT': (480.0, 1, 480)},
        'STREAMING_EXPOSURE': {'STREAMING_EXPOSURE_VALUE': (0.1, 0.000032, 3600),
                               'STREAMING_DIVISOR_VALUE': (1.0, 1, 100)},
        'LIMITS': {'LIMITS_BUFFER_MAX': (512.0, 1, 65536), 'LIMITS_PREVIEW_FPS': (10.0, 1, 30)},
        'CCD_EXPOSURE': {'CCD_EXPOSURE_VALUE': (1.0, 0.000032, 3600)},
    }


def default_switches():
    return {
        'STREAM_FULL_DEPTH': {'FULL_DEPTH_8BIT': True, 'FULL_DEPTH_16BIT': False},
        'CCD_STREAM_ENCODER': {'RAW': False, 'MJPEG': True},
        'CCD_VIDEO_FORMAT': {'ASI_IMG_RAW8': False, 'ASI_IMG_RAW16': True},
        'CCD_CAPTURE_FORMAT': {'ASI_IMG_RAW8': False, 'ASI_IMG_RAW16': True},
        'CCD_VIDEO_STREAM': {'STREAM_ON': False, 'STREAM_OFF': True},
        'CCD_ABORT_EXPOSURE': {'ABORT': False},
    }


class FakeClient(object):
    """Just enough of IndiClient: set_number, set_switch, get_control, blob_sink, ccd_device."""

    def __init__(self, numbers=None, switches=None):
        self.numbers = default_numbers() if numbers is None else numbers
        self.switches = default_switches() if switches is None else switches
        self.ccd_device = object()
        self.blob_sink = None
        self.calls = []
        self.lock = threading.Lock()
        self.aborts = 0

    def get_control(self, device, name, ctl_type, timeout=None):
        assert device is self.ccd_device
        assert timeout is not None and timeout > 0  # 0 waits forever in IndiClient.get_control
        if ctl_type == 'number' and name in self.numbers:
            return [Elem(k, v[0], v[1], v[2]) for k, v in self.numbers[name].items()]
        if ctl_type == 'switch' and name in self.switches:
            return [Elem(k, on=v) for k, v in self.switches[name].items()]
        raise TimeoutError('Timeout finding control {0}'.format(name))

    def set_number(self, device, name, values, sync=True, timeout=None):
        assert device is self.ccd_device
        if name not in self.numbers:
            raise TimeoutError(name)
        with self.lock:
            self.calls.append(('number', name, dict(values)))
        for k, v in values.items():
            low, high = self.numbers[name][k][1:]
            self.numbers[name][k] = (float(v), low, high)

    def set_switch(self, device, name, on_switches=[], off_switches=[], sync=True, timeout=None):
        assert device is self.ccd_device
        if name not in self.switches:
            raise TimeoutError(name)
        with self.lock:
            self.calls.append(('switch', name, tuple(on_switches)))
        for k in self.switches[name]:
            self.switches[name][k] = k in on_switches

    def abortCcdExposure(self):
        self.aborts += 1

    def taken(self):
        with self.lock:
            calls, self.calls = self.calls, []
        return calls


def stream(on):
    return ('switch', 'CCD_VIDEO_STREAM', ('STREAM_ON' if on else 'STREAM_OFF',))


def test_indi_stream_start_order():
    client = FakeClient()
    src = IndiStreamSource(client, sensor=SENSOR)
    src.start((100, 50, 256, 128), 0.2, 150)
    assert client.taken() == [
        stream(False),
        ('number', 'CCD_BINNING', {'HOR_BIN': 1, 'VER_BIN': 1}),
        ('number', 'CCD_FRAME', {'X': 100, 'Y': 50, 'WIDTH': 256, 'HEIGHT': 128}),
        ('number', 'CCD_STREAM_FRAME', {'X': 0, 'Y': 0, 'WIDTH': 256, 'HEIGHT': 128}),
        ('switch', 'CCD_STREAM_ENCODER', ('RAW',)),
        ('switch', 'STREAM_FULL_DEPTH', ('FULL_DEPTH_16BIT',)),
        ('number', 'LIMITS', {'LIMITS_PREVIEW_FPS': 5.0}),
        ('number', 'CCD_CONTROLS', {'Gain': 150.0}),
        ('number', 'STREAMING_EXPOSURE', {'STREAMING_EXPOSURE_VALUE': 0.2, 'STREAMING_DIVISOR_VALUE': 1}),
        stream(True),
    ]
    assert client.blob_sink is not None
    src.stop()


def test_driver_specific_properties_are_skipped_when_absent():
    # STREAM_FULL_DEPTH and CCD_CONTROLS.Gain are ZWO's; LIMITS comes with INDI's stream manager. A driver without
    # one still streams, and IndiClient.set_switch/set_number would otherwise wait out their full default timeout.
    client = FakeClient()
    for name in ('STREAM_FULL_DEPTH',):
        del client.switches[name]
    for name in ('LIMITS', 'CCD_CONTROLS'):
        del client.numbers[name]
    src = IndiStreamSource(client, sensor=SENSOR)
    src.start((0, 0, 64, 64), 0.2, 150)
    src.set_camera(0.5, 10)
    names = [c[1] for c in client.taken()]
    assert not {'STREAM_FULL_DEPTH', 'LIMITS', 'CCD_CONTROLS'} & set(names)
    assert names.count('STREAMING_EXPOSURE') == 2
    src.stop()


def test_indi_stream_whole_sensor_when_no_region():
    client = FakeClient()
    src = IndiStreamSource(client, sensor=SENSOR)
    src.start(None, 0.1, 0)
    frame = [c for c in client.taken() if c[1] == 'CCD_FRAME'][0]
    assert frame[2] == {'X': 0, 'Y': 0, 'WIDTH': 640, 'HEIGHT': 480}
    src.stop()


def fps_set(calls):
    return [c[2]['LIMITS_PREVIEW_FPS'] for c in calls if c[1] == 'LIMITS']


def test_indi_stream_fps_always_capped():
    client = FakeClient()  # the driver's LIMITS_PREVIEW_FPS max is 30
    src = IndiStreamSource(client, sensor=SENSOR)
    src.start(None, 0.001, 0)  # 1000 fps asked
    assert fps_set(client.taken()) == [30.0]
    src.set_camera(0.0001, 0)
    assert fps_set(client.taken()) == [30.0]
    src.set_camera(2.0, 0)  # 0.5 fps is under the driver's minimum (1): ZWO refuses it and the session ended
    assert fps_set(client.taken()) == [1.0]
    src.set_camera(0.05, 0)
    assert fps_set(client.taken()) == [20.0]
    src.stop()


def test_set_camera_restarts_stream():
    client = FakeClient()
    src = IndiStreamSource(client, sensor=SENSOR)
    src.start((0, 0, 64, 64), 0.1, 0)
    client.taken()
    src.set_camera(0.25, 300)
    assert client.taken() == [
        stream(False),
        ('number', 'LIMITS', {'LIMITS_PREVIEW_FPS': 4.0}),
        ('number', 'CCD_CONTROLS', {'Gain': 300.0}),
        ('number', 'STREAMING_EXPOSURE', {'STREAMING_EXPOSURE_VALUE': 0.25, 'STREAMING_DIVISOR_VALUE': 1}),
        stream(True),
    ]
    src.stop()


def test_saved_state_is_exact_property_list():
    assert NUMBERS == ('CCD_CONTROLS', 'CCD_GAIN', 'CCD_FRAME', 'CCD_BINNING', 'CCD_STREAM_FRAME', 'STREAMING_EXPOSURE',
                       'LIMITS')
    assert SWITCHES == ('STREAM_FULL_DEPTH', 'CCD_STREAM_ENCODER', 'CCD_VIDEO_FORMAT', 'CCD_CAPTURE_FORMAT',
                        'CCD_VIDEO_STREAM')
    client = FakeClient()
    state = save_state(client)
    assert set(state) == {'numbers', 'switches'}
    assert set(state['numbers']) == set(NUMBERS) - {'CCD_GAIN'}  # a ZWO has no CCD_GAIN; CCD_EXPOSURE is not saved
    assert set(state['switches']) == set(SWITCHES)  # CCD_ABORT_EXPOSURE neither
    assert state['numbers']['CCD_CONTROLS'] == {'Gain': 100.0, 'Offset': 10.0}
    assert state['switches']['CCD_STREAM_ENCODER'] == ['MJPEG']
    json.dumps(state)  # it goes to a file
    assert client.taken() == []  # saving only reads


def test_saved_state_skips_a_missing_property():
    client = FakeClient()
    del client.numbers['LIMITS']
    state = save_state(client)
    assert 'LIMITS' not in state['numbers']
    assert set(state['numbers']) == set(NUMBERS) - {'LIMITS', 'CCD_GAIN'}


def test_saving_looks_briefly_for_a_property_the_driver_may_not_have():
    # the driver defined its properties when it connected: waiting a second for CCD_GAIN, which a ZWO never has,
    # only delays the start
    client = FakeClient()
    looks = {}
    real = client.get_control

    def get_control(device, name, ctl_type, timeout=None):
        looks[name] = timeout
        return real(device, name, ctl_type, timeout=timeout)

    client.get_control = get_control
    save_state(client)
    for name in required_properties(True):
        assert looks[name] == CONTROL_TIMEOUT_S
    assert looks['CCD_GAIN'] == OPTIONAL_LOOK_S
    assert looks['LIMITS'] == OPTIONAL_LOOK_S
    assert 0 < OPTIONAL_LOOK_S < CONTROL_TIMEOUT_S


def test_restore_puts_values_back_and_never_starts_the_stream():
    client = FakeClient()
    state = save_state(client)
    state['switches']['CCD_VIDEO_STREAM'] = ['STREAM_ON']  # saved while some other client streamed
    src = IndiStreamSource(client, sensor=SENSOR)
    src.start((0, 0, 64, 64), 0.5, 400)
    src.stop()
    client.taken()
    assert restore_state(client, state) == []
    calls = client.taken()
    assert calls[0] == stream(False)
    assert stream(True) not in calls
    assert [c[1] for c in calls[1:5]] == ['STREAM_FULL_DEPTH', 'CCD_STREAM_ENCODER', 'CCD_VIDEO_FORMAT',
                                          'CCD_CAPTURE_FORMAT']
    assert [c[1] for c in calls[5:]] == ['CCD_BINNING', 'CCD_FRAME', 'CCD_STREAM_FRAME', 'STREAMING_EXPOSURE',
                                         'LIMITS', 'CCD_CONTROLS']
    assert client.numbers['CCD_CONTROLS']['Gain'][0] == 100.0
    assert client.numbers['CCD_FRAME']['WIDTH'][0] == 640.0
    assert client.switches['CCD_STREAM_ENCODER'] == {'RAW': False, 'MJPEG': True}


def test_restore_goes_on_past_a_failing_property():
    client = FakeClient()
    state = save_state(client)
    state['numbers']['NOT_THERE'] = {'A': 1.0}
    del client.numbers['CCD_BINNING']
    assert restore_state(client, state) == ['CCD_BINNING']  # NOT_THERE is not on the list
    names = [c[1] for c in client.taken()]
    assert 'CCD_CONTROLS' in names and 'NOT_THERE' not in names


def test_startup_restores_after_crash(tmp_path):
    client = FakeClient()
    state = save_state(client)
    path = str(tmp_path / 'focus-session.state.json')
    with open(path, 'w') as f:
        json.dump(state, f)
    client.numbers['CCD_CONTROLS']['Gain'] = (400.0, 0, 600)  # the session's gain, left by a crash
    assert focus_startup_restore(client, path) is True
    assert client.numbers['CCD_CONTROLS']['Gain'][0] == 100.0
    assert not os.path.exists(path)


@pytest.mark.parametrize('broken', ['CCD_FRAME', 'CCD_STREAM_ENCODER', 'STREAMING_EXPOSURE'])
def test_startup_restore_keeps_the_file_and_raises_a_notice_when_a_required_property_fails(tmp_path, broken):
    client = FakeClient()
    state = save_state(client)
    path = str(tmp_path / 'focus-session.state.json')
    with open(path, 'w') as f:
        json.dump(state, f)
    client.numbers.pop(broken, None)  # the driver does not take it back this time
    client.switches.pop(broken, None)
    notices = []
    assert focus_startup_restore(client, path, notify=lambda key, msg: notices.append((key, msg))) is True
    assert os.path.exists(path)  # the next start tries again
    assert notices == [(indi_stream.RESTORE_NOTICE_KEY, indi_stream.MSG_RESTORE_FAILED.format(broken))]
    # the next start: the property is back, the restore works, the file goes
    client.numbers.update({k: v for k, v in default_numbers().items() if k == broken})
    client.switches.update({k: v for k, v in default_switches().items() if k == broken})
    notices.clear()
    assert focus_startup_restore(client, path, notify=lambda key, msg: notices.append((key, msg))) is True
    assert not os.path.exists(path) and notices == []


def test_startup_restore_drops_the_file_when_only_an_optional_property_fails(tmp_path):
    client = FakeClient()
    state = save_state(client)
    path = str(tmp_path / 'focus-session.state.json')
    with open(path, 'w') as f:
        json.dump(state, f)
    del client.numbers['LIMITS']
    notices = []
    assert focus_startup_restore(client, path, notify=lambda key, msg: notices.append((key, msg))) is True
    assert not os.path.exists(path) and notices == []


def test_startup_restore_survives_a_failing_notify(tmp_path):
    client = FakeClient()
    state = save_state(client)
    path = str(tmp_path / 'focus-session.state.json')
    with open(path, 'w') as f:
        json.dump(state, f)
    del client.numbers['CCD_FRAME']

    def broken(key, msg):
        raise RuntimeError('no database')

    assert focus_startup_restore(client, path, notify=broken) is True  # never raises
    assert os.path.exists(path)


def test_startup_restore_without_a_file_does_nothing(tmp_path):
    client = FakeClient()
    assert focus_startup_restore(client, str(tmp_path / 'focus-session.state.json')) is False
    assert client.taken() == []


def test_startup_restore_deletes_a_corrupt_file(tmp_path):
    client = FakeClient()
    path = str(tmp_path / 'focus-session.state.json')
    with open(path, 'w') as f:
        f.write('{not json')
    assert focus_startup_restore(client, path) is False
    assert not os.path.exists(path)
    assert client.taken() == []


def test_has_video():
    assert has_video(FakeClient()) is True
    client = FakeClient()
    del client.switches['CCD_VIDEO_STREAM']
    assert has_video(client) is False

    class Says(object):
        def has_video(self):
            return True

    assert has_video(Says()) is True


def u16(img):
    return np.ascontiguousarray(img, dtype='<u2').tobytes()


def test_blobs_become_frames_of_the_region():
    client = FakeClient()
    src = IndiStreamSource(client, sensor=SENSOR, bayer='rggb')
    src.start((10, 20, 64, 32), 0.1, 50)
    img = np.arange(64 * 32, dtype=np.uint16).reshape(32, 64) * 16
    client.blob_sink(u16(img), '.stream', 1234.5)
    frame = src.frames.get(timeout=1)
    assert frame.raw.shape == (32, 64)
    assert np.array_equal(frame.raw, img)
    assert frame.bayer == 'RGGB' and src.bayer == 'RGGB'
    assert (frame.t_end, frame.exposure, frame.gain) == (1234.5, 0.1, 50.0)
    assert frame.full_scale == 65535.0
    client.blob_sink(b'not a frame', '.stream', 1235.0)  # dropped
    assert src.frames.empty()
    src.stop()


def test_unscaled_12_bit_stream_has_12_bit_full_scale():
    client = FakeClient()
    src = IndiStreamSource(client, sensor=SENSOR, bits=12)
    src.start((0, 0, 32, 32), 0.1, 0)
    img = np.full((32, 32), 300, dtype=np.uint16)
    img[5, 5] = 4095
    img[6, 6] = 301  # not a multiple of 16: the data is not shifted up to 16 bits
    client.blob_sink(u16(img), '.stream', 1.0)
    assert src.frames.get(timeout=1).full_scale == 4095.0
    img[6, 6] = 70  # the scale is kept for the whole stream
    client.blob_sink(u16(img * 16), '.stream', 2.0)
    assert src.frames.get(timeout=1).full_scale == 4095.0
    src.stop()


def test_shifted_12_bit_stream_has_16_bit_full_scale():
    client = FakeClient()
    src = IndiStreamSource(client, sensor=SENSOR, bits=12)
    src.start((0, 0, 32, 32), 0.1, 0)
    img = (np.arange(32 * 32, dtype=np.uint16).reshape(32, 32) % 4096) * 16
    client.blob_sink(u16(img), '.stream', 1.0)
    assert src.frames.get(timeout=1).full_scale == 65535.0
    src.stop()


def test_frames_queue_keeps_only_the_newest():
    client = FakeClient()
    src = IndiStreamSource(client, sensor=SENSOR)
    src.start((0, 0, 8, 8), 0.1, 0)
    for i in range(20):
        client.blob_sink(u16(np.full((8, 8), i)), '.stream', float(i))
    got = []
    while not src.frames.empty():
        got.append(src.frames.get_nowait().t_end)
    assert len(got) <= indi_stream.MAX_QUEUED and got[-1] == 19.0
    src.stop()


def test_whole_frame_streams_the_sensor_then_the_region_again():
    client = FakeClient()
    src = IndiStreamSource(client, sensor=(64, 48))
    src.start((8, 8, 16, 16), 0.1, 0)
    client.taken()
    result = {}

    def take():
        result['raw'] = src.whole_frame(timeout=5.0)

    t = threading.Thread(target=take)
    t.start()
    deadline = time.monotonic() + 5
    while not [c for c in client.calls if c[1] == 'CCD_FRAME'] and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.05)
    client.blob_sink(u16(np.full((48, 64), 7)), '.stream', 1.0)
    t.join(5)
    assert result['raw'].shape == (48, 64)
    frames = [c[2] for c in client.taken() if c[1] == 'CCD_FRAME']
    assert frames == [{'X': 0, 'Y': 0, 'WIDTH': 64, 'HEIGHT': 48}, {'X': 8, 'Y': 8, 'WIDTH': 16, 'HEIGHT': 16}]
    assert src.frames.empty()  # the whole-sensor picture is not a region frame
    src.stop()


def test_stop_releases_whole_frame_and_the_sink():
    client = FakeClient()
    src = IndiStreamSource(client, sensor=(64, 48))
    src.start(None, 0.1, 0)
    errors = []

    def take():
        try:
            src.whole_frame(timeout=10.0)
        except Exception as e:
            errors.append(e)

    t = threading.Thread(target=take)
    t.start()
    time.sleep(0.1)
    src.stop()
    t.join(2)
    assert not t.is_alive() and errors
    assert client.blob_sink is None
    assert client.taken()[-1] == stream(False)
    with pytest.raises(RuntimeError):
        src.whole_frame(timeout=1.0)


class VideoCamera(FakeClient):
    """A client that streams by itself, like the test cameras."""

    def __init__(self):
        super(VideoCamera, self).__init__()
        self.video = []

    def start_video(self, exposure, roi):
        self.video.append(('start', exposure, tuple(roi)))

    def stop_video(self):
        self.video.append(('stop',))


def test_simulated_camera_streams_through_start_video():
    cam = VideoCamera()
    src = IndiStreamSource(cam, sensor=SENSOR)
    src.start((0, 0, 32, 32), 0.1, 0)
    src.set_camera(0.2, 0)
    src.stop()
    assert cam.video == [('stop',), ('start', 0.1, (0, 0, 32, 32)), ('stop',), ('start', 0.2, (0, 0, 32, 32)),
                         ('stop',)]
    assert cam.taken() == []  # no INDI properties


# -- fix round 1 ------------------------------------------------------------------------------------------------------

class BusyStreamClient(FakeClient):
    """A driver that holds CCD_VIDEO_STREAM at BUSY while it streams: a set_switch that waits for OK never gets it."""

    def __init__(self):
        super(BusyStreamClient, self).__init__()
        self.stream_syncs = []

    def set_switch(self, device, name, on_switches=[], off_switches=[], sync=True, timeout=None):
        super(BusyStreamClient, self).set_switch(device, name, on_switches, off_switches, sync, timeout)
        if name == 'CCD_VIDEO_STREAM':
            self.stream_syncs.append(sync)
            if sync and 'STREAM_ON' in on_switches:
                time.sleep(2.0)  # the property is BUSY, not OK
                raise TimeoutError('Timeout error')


def test_stream_on_does_not_wait_for_a_busy_property():
    client = BusyStreamClient()
    src = IndiStreamSource(client, sensor=SENSOR)
    t0 = time.monotonic()
    src.start((0, 0, 64, 64), 0.1, 0)
    src.set_camera(0.2, 0)
    assert time.monotonic() - t0 < 0.5
    assert client.stream_syncs and not any(client.stream_syncs)
    src.stop()


def test_binned_camera_streams_at_1x1_and_gets_its_binning_back():
    client = FakeClient()
    client.numbers['CCD_BINNING'] = {'HOR_BIN': (2.0, 1, 4), 'VER_BIN': (2.0, 1, 4)}
    state = save_state(client)
    src = IndiStreamSource(client, sensor=SENSOR)
    src.start((0, 0, 64, 64), 0.1, 0)
    calls = client.taken()
    assert calls[:2] == [stream(False), ('number', 'CCD_BINNING', {'HOR_BIN': 1, 'VER_BIN': 1})]
    src.stop()
    assert restore_state(client, state) == []
    assert client.numbers['CCD_BINNING']['HOR_BIN'][0] == 2.0
    assert client.numbers['CCD_BINNING']['VER_BIN'][0] == 2.0


def test_wrong_size_blobs_are_reported_once(caplog):
    client = FakeClient()
    src = IndiStreamSource(client, sensor=SENSOR)
    src.start((0, 0, 64, 64), 0.1, 0)
    with caplog.at_level('WARNING', logger='indi_allsky'):
        for _ in range(3):
            client.blob_sink(u16(np.zeros((32, 32))), '.stream', 1.0)  # a 2x2-binned frame of the region
    warnings = [r for r in caplog.records if 'not a 64x64 frame' in r.getMessage()]
    assert len(warnings) == 1 and warnings[0].levelname == 'WARNING'
    assert src.frames.empty()
    src.stop()


@pytest.mark.parametrize('missing, video', [
    ('CCD_FRAME', False), ('CCD_FRAME', True), ('STREAMING_EXPOSURE', True),
    ('CCD_VIDEO_STREAM', True), ('CCD_STREAM_ENCODER', True),
])
def test_save_state_refuses_without_a_required_property(missing, video):
    client = FakeClient()
    client.numbers.pop(missing, None)
    client.switches.pop(missing, None)
    with pytest.raises(MissingProperty) as e:
        save_state(client, video=video)
    assert e.value.name == missing
    assert client.taken() == []


def test_save_state_for_stills_needs_no_stream_property():
    client = FakeClient()
    for name in ('CCD_VIDEO_STREAM', 'CCD_STREAM_ENCODER'):
        del client.switches[name]
    del client.numbers['STREAMING_EXPOSURE']
    assert 'CCD_FRAME' in save_state(client, video=False)['numbers']


def test_frames_in_flight_during_a_restart_are_dropped_not_relabelled():
    class Racing(FakeClient):
        """An old-settings frame arrives while the stream restarts."""
        src = None

        def set_number(self, device, name, values, sync=True, timeout=None):
            super(Racing, self).set_number(device, name, values, sync, timeout)
            if name == 'STREAMING_EXPOSURE' and self.src is not None:
                self.blob_sink(u16(np.full((64, 64), 5)), '.stream', 9.0)

    client = Racing()
    src = IndiStreamSource(client, sensor=SENSOR)
    src.start((0, 0, 64, 64), 0.1, 10)
    client.src = src
    src.set_camera(0.5, 20)
    assert src.frames.empty()  # exposed at 0.1 s: it must not come out labelled 0.5 s
    client.blob_sink(u16(np.full((64, 64), 5)), '.stream', 10.0)
    frame = src.frames.get(timeout=1)
    assert (frame.exposure, frame.gain) == (0.5, 20.0)
    src.stop()


# -- final review ------------------------------------------------------------------------------------------------------

def test_a_restart_during_whole_frame_releases_it_and_region_frames_flow_at_once():
    # set_region is stop() then start(). If start() sets _running before the whole_frame thread wakes, that thread
    # must still learn the source was restarted: otherwise it waits on, and every region frame is dropped meanwhile.
    client = FakeClient()
    src = IndiStreamSource(client, sensor=(64, 48))
    src.start((8, 8, 16, 16), 0.1, 0)
    errors = []

    def take():
        try:
            src.whole_frame(timeout=3.0)
        except Exception as e:
            errors.append(e)

    t = threading.Thread(target=take)
    t.start()
    deadline = time.monotonic() + 5
    while not [c for c in client.calls if c[1] == 'CCD_FRAME' and c[2]['WIDTH'] == 64] and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.05)  # parked in the wait
    with src._cond:  # an RLock: the waiter cannot wake until both are done
        src.stop()
        src.start((16, 16, 16, 16), 0.1, 0)
    t.join(1.0)
    assert not t.is_alive(), 'whole_frame still waits after the restart'
    assert errors and isinstance(errors[0], RuntimeError)
    client.blob_sink(u16(np.full((16, 16), 3)), '.stream', 5.0)
    assert src.frames.get(timeout=0.5).t_end == 5.0  # the new region's frames are not held back
    frames = [c[2] for c in client.taken() if c[1] == 'CCD_FRAME']
    assert frames[-1] == {'X': 16, 'Y': 16, 'WIDTH': 16, 'HEIGHT': 16}  # whole_frame did not move it again
    src.stop()


def test_a_restart_before_whole_frame_configures_keeps_the_new_region():
    client = FakeClient()
    src = IndiStreamSource(client, sensor=(64, 48))
    src.start((8, 8, 16, 16), 0.1, 0)
    client.taken()
    errors = []

    def take():
        try:
            src.whole_frame(timeout=3.0)
        except Exception as e:
            errors.append(e)

    with src._ctl:  # whole_frame waits here to put the whole sensor on the camera
        t = threading.Thread(target=take)
        t.start()
        deadline = time.monotonic() + 5
        while not src._whole_waiting and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.05)
        src.stop()
        src.start((16, 16, 16, 16), 0.1, 0)
    t.join(1.0)
    assert not t.is_alive() and errors
    frames = [c[2] for c in client.taken() if c[1] == 'CCD_FRAME']
    assert frames == [{'X': 16, 'Y': 16, 'WIDTH': 16, 'HEIGHT': 16}]  # never the whole sensor after the restart
    src.stop()


def ccd_gain_client():
    """A driver with gain in CCD_GAIN/GAIN (indi_qhy_ccd, indi_simulator_ccd, indi_rpicam, indi_libcamera_ccd,
    indi_dsi_ccd, svbony before INDI 2.0.4), not in CCD_CONTROLS/Gain."""
    client = FakeClient()
    del client.numbers['CCD_CONTROLS']
    client.numbers['CCD_GAIN'] = {'GAIN': (30.0, 0, 100)}
    return client


def gains_set(calls):
    return [(c[1], c[2]) for c in calls if c[1] in ('CCD_CONTROLS', 'CCD_GAIN')]


def test_gain_goes_to_ccd_gain_when_the_driver_has_no_ccd_controls_gain():
    client = ccd_gain_client()
    src = IndiStreamSource(client, sensor=SENSOR)
    assert src.can_set_gain()
    src.start((0, 0, 64, 64), 0.1, 40)
    assert gains_set(client.taken()) == [('CCD_GAIN', {'GAIN': 40.0})]
    src.set_camera(0.2, 60)
    assert gains_set(client.taken()) == [('CCD_GAIN', {'GAIN': 60.0})]
    client.blob_sink(u16(np.zeros((64, 64))), '.stream', 1.0)
    assert src.frames.get(timeout=1).gain == 60.0
    src.stop()


def test_ccd_controls_without_a_gain_element_falls_back_to_ccd_gain():
    client = ccd_gain_client()
    client.numbers['CCD_CONTROLS'] = {'Offset': (10.0, 0, 255)}
    src = IndiStreamSource(client, sensor=SENSOR)
    src.start((0, 0, 64, 64), 0.1, 40)
    assert gains_set(client.taken()) == [('CCD_GAIN', {'GAIN': 40.0})]
    src.stop()


def test_a_driver_without_gain_never_claims_a_changed_gain():
    client = FakeClient()
    del client.numbers['CCD_CONTROLS']
    src = IndiStreamSource(client, sensor=SENSOR)
    assert not src.can_set_gain()
    src.start((0, 0, 64, 64), 0.1, 40)
    src.set_camera(0.2, 300)
    assert gains_set(client.taken()) == []
    client.blob_sink(u16(np.zeros((64, 64))), '.stream', 1.0)
    frame = src.frames.get(timeout=1)
    assert (frame.exposure, frame.gain) == (0.2, 40.0)  # the gain the camera has, not the one asked for
    src.stop()


def test_ccd_gain_is_saved_and_put_back():
    client = ccd_gain_client()
    state = save_state(client)
    assert state['numbers']['CCD_GAIN'] == {'GAIN': 30.0}
    src = IndiStreamSource(client, sensor=SENSOR)
    src.start((0, 0, 64, 64), 0.1, 90)
    src.stop()
    assert restore_state(client, state) == []
    assert client.numbers['CCD_GAIN']['GAIN'][0] == 30.0
