"""Live video from an INDI camera for a focus session, and the camera state saved around it.

`IndiStreamSource` drives the driver's stream (CCD_VIDEO_STREAM) and turns each blob into a `RawFrame`. It works on
any client with `set_number`, `set_switch`, `get_control`, `ccd_device` and a `blob_sink` attribute: the INDI client
calls `blob_sink(data, fmt, t)` for every blob while it is set, instead of making a FITS for the image queue. A client
with `start_video(exposure, roi)` and `stop_video()` (the test cameras) streams by itself, and no property is set.

`save_state` / `restore_state` keep exactly the properties the stream changes (focus_spike.py:27-28). The state is
written next to the link's socket, so a capture process that dies in a session puts the camera back when it starts
again (`focus_startup_restore`).

This module never imports PyIndi: switch states are compared by value (ISS_ON is 1).
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from typing import Optional

import numpy as np

from indi_allsky.focus.frame import decode_stream
from indi_allsky.focus.sources import RawFrame
from indi_allsky.focus.sources import normalise_bayer
from indi_allsky.focus.sources import snap_roi


logger = logging.getLogger('indi_allsky')


NUMBERS = ('CCD_CONTROLS', 'CCD_GAIN', 'CCD_FRAME', 'CCD_BINNING', 'CCD_STREAM_FRAME', 'STREAMING_EXPOSURE', 'LIMITS')
SWITCHES = ('STREAM_FULL_DEPTH', 'CCD_STREAM_ENCODER', 'CCD_VIDEO_FORMAT', 'CCD_CAPTURE_FORMAT', 'CCD_VIDEO_STREAM')

# restore order (focus_spike.py restore): the stream off first, then formats, then numbers; the stream stays off
RESTORE_SWITCHES = ('STREAM_FULL_DEPTH', 'CCD_STREAM_ENCODER', 'CCD_VIDEO_FORMAT', 'CCD_CAPTURE_FORMAT')
RESTORE_NUMBERS = ('CCD_BINNING', 'CCD_FRAME', 'CCD_STREAM_FRAME', 'STREAMING_EXPOSURE', 'LIMITS', 'CCD_CONTROLS',
                   'CCD_GAIN')

# a session does not start without these: it could not put the camera back (or stream at all) without them
REQUIRED = ('CCD_FRAME',)
REQUIRED_VIDEO = ('CCD_VIDEO_STREAM', 'CCD_STREAM_ENCODER', 'STREAMING_EXPOSURE')

RESTORE_NOTICE_KEY = 'focus_restore'
MSG_RESTORE_FAILED = ('The focus session could not put back the camera setting {0}. indi-allsky tries again when '
                      'capture restarts; until then pictures may come out wrong.')

CONTROL_TIMEOUT_S = 1.0      # finding a property; get_control waits forever on 0
OPTIONAL_LOOK_S = 0.05       # finding one the driver may not have: it defined its properties when it connected
SET_TIMEOUT_S = 5.0           # a property change to settle
WHOLE_FRAME_TIMEOUT_S = 30.0
MAX_QUEUED = 4                # frames waiting for the controller; older ones are dropped
# STREAM_FULL_DEPTH and CCD_CONTROLS are ZWO's and LIMITS is INDI's stream manager: each is set only when the driver
# has it (`_has`). IndiClient.set_switch/set_number look a property up with the client's full timeout, so a missing
# one is skipped after a short look instead.
ISS_ON = 1

# Where a driver keeps its gain, in the order IndiClient.setCcdGain (camera/indi.py) prefers them: CCD_CONTROLS/Gain
# (ZWO, ToupTek and kin, Player One, svbony since INDI 2.0.4), else CCD_GAIN/GAIN (QHY, the simulator, rpicam,
# libcamera, DSI, older svbony). setCcdGain itself is not called: it picks by driver name, raises for a driver it
# does not know and updates capture's shared gain value. A driver with neither cannot have its gain set here.
GAIN_PROPERTIES = (('CCD_CONTROLS', 'Gain'), ('CCD_GAIN', 'GAIN'))
_UNPROBED = object()


def _on(state) -> bool:
    return state == ISS_ON or str(state).upper() in ('ON', 'ISS_ON')


def _element_max(e) -> Optional[float]:
    getter = getattr(e, 'getMax', None)
    value = getter() if callable(getter) else getattr(e, 'max', None)
    return None if value is None else float(value)


def _element_min(e) -> Optional[float]:
    getter = getattr(e, 'getMin', None)
    value = getter() if callable(getter) else getattr(e, 'min', None)
    return None if value is None else float(value)


def _device(client):
    return getattr(client, 'ccd_device', None)


def _numbers(client, name, timeout=CONTROL_TIMEOUT_S) -> dict:
    ctl = client.get_control(_device(client), name, 'number', timeout=timeout)
    return {e.getName(): float(e.getValue()) for e in ctl}


def _switch_on(client, name, timeout=CONTROL_TIMEOUT_S) -> list:
    ctl = client.get_control(_device(client), name, 'switch', timeout=timeout)
    return [e.getName() for e in ctl if _on(e.getState())]


def has_video(client) -> bool:
    """True when the camera's driver has a CCD_VIDEO_STREAM property."""
    own = getattr(client, 'has_video', None)
    if callable(own):
        try:
            return bool(own())
        except Exception:
            logger.exception('Focus: could not tell whether the camera has video')
            return False
    try:
        return bool(client.get_control(_device(client), 'CCD_VIDEO_STREAM', 'switch', timeout=CONTROL_TIMEOUT_S))
    except Exception:
        return False


# -- camera state ---------------------------------------------------------------------------------------------------

class MissingProperty(Exception):
    """The driver lacks (or did not answer for) a property a session needs. `name` is the property."""

    def __init__(self, name: str):
        super(MissingProperty, self).__init__(name)
        self.name = name


def required_properties(video: bool) -> tuple:
    return REQUIRED + (REQUIRED_VIDEO if video else ())


def save_state(client, *, video: bool = True) -> dict:
    """{'numbers': {property: {element: value}}, 'switches': {property: [elements on]}} for the properties the
    stream changes. An optional property the driver does not have is left out; a required one (`REQUIRED`, and
    `REQUIRED_VIDEO` for video) raises MissingProperty. Saving only reads, so a refusal leaves the camera as it was."""
    required = required_properties(video)
    state = {'numbers': {}, 'switches': {}}
    for kind, names, read in (('numbers', NUMBERS, _numbers), ('switches', SWITCHES, _switch_on)):
        for name in names:
            try:
                state[kind][name] = read(client, name, CONTROL_TIMEOUT_S if name in required else OPTIONAL_LOOK_S)
            except Exception:
                if name in required:
                    logger.error('Focus: the camera has no %s; a focus session cannot start', name)
                    raise MissingProperty(name)
                logger.info('Focus: the camera has no %s to save', name)
    return state


def restore_state(client, state: dict) -> list:
    """Put the saved values back, the stream off whatever was saved. Returns the properties that failed; each
    failure is logged and the rest are still restored."""
    device = _device(client)
    failures = []
    numbers = state.get('numbers') or {}
    switches = state.get('switches') or {}

    def attempt(what, fn, *args, **kwargs):
        try:
            fn(*args, **kwargs)
        except Exception as e:
            failures.append(what)
            logger.error('Focus: could not restore %s (%s)', what, type(e).__name__)

    if 'CCD_VIDEO_STREAM' in switches:
        attempt('CCD_VIDEO_STREAM', client.set_switch, device, 'CCD_VIDEO_STREAM', on_switches=['STREAM_OFF'])
    for name in RESTORE_SWITCHES:
        on = switches.get(name)
        if on:
            attempt(name, client.set_switch, device, name, on_switches=list(on))
    for name in RESTORE_NUMBERS:
        values = numbers.get(name)
        if values:
            attempt(name, client.set_number, device, name, dict(values), timeout=SET_TIMEOUT_S)
    return failures


def write_state(path: str, state: dict) -> None:
    """Atomically: a crash mid-write leaves the old file or none, never half a file."""
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_state(path: str) -> Optional[dict]:
    """The state a session left in the file, or None when there is none or it cannot be read."""
    try:
        with open(path) as f:
            state = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        logger.error('Focus: the saved camera state could not be read (%s)', type(e).__name__)
        return None
    return state if isinstance(state, dict) else None


def remove_state(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.error('Focus: could not delete the saved camera state: %s', e)


def required_failures(failures) -> list:
    """The restore failures that leave the camera unfit for capture: these keep the state file for a retry."""
    return [name for name in failures if name in REQUIRED + REQUIRED_VIDEO]


def raise_restore_notice(notify, required) -> None:
    """notify(RESTORE_NOTICE_KEY, message) for required properties that were not put back; never raises."""
    if notify is None:
        return
    try:
        notify(RESTORE_NOTICE_KEY, MSG_RESTORE_FAILED.format(', '.join(required)))
    except Exception as e:
        logger.error('Focus: the notification could not be raised (%s)', type(e).__name__)


def focus_startup_restore(camera, path: str, notify=None) -> bool:
    """At capture start: if a session left its saved state (the process died in it, or a required property could
    not be put back), restore the camera. True when a state was restored. Never raises.

    The file is deleted unless a required property fails again: then it stays, so the next start (and the next
    session, which returns to it) tries again, and notify(key, message) raises the same notice a session's end
    does. Capture is never held up by it. A file that cannot be read is deleted, so a bad one cannot block every
    start."""
    if not os.path.exists(path):
        return False
    keep = False
    try:
        try:
            with open(path) as f:
                state = json.load(f)
            if not isinstance(state, dict):
                raise ValueError('not a camera state')
        except (OSError, ValueError) as e:
            logger.error('Focus: the saved camera state could not be read, deleting it: %s', e)
            return False
        logger.warning('Focus: a focus session did not end cleanly; restoring the camera')
        failures = restore_state(camera, state)
        if failures:
            logger.error('Focus: %d camera properties could not be restored', len(failures))
        required = required_failures(failures)
        if required:
            keep = True
            logger.error('Focus: a required camera property was not restored: %s; trying again at the next start',
                         ', '.join(required))
            raise_restore_notice(notify, required)
        return True
    except Exception:
        logger.exception('Focus: restoring the camera at startup failed')
        return False
    finally:
        if not keep:
            remove_state(path)


# -- the stream -----------------------------------------------------------------------------------------------------

class IndiStreamSource(object):
    """`PictureSource` over the driver's video stream (new settings restart the stream).

    sensor: (width, height) in pixels; read from CCD_FRAME when not given. bits: the camera's bit depth, to tell
    12-bit data stored as is from data shifted up to 16 bits (full_scale is decided on the first frame of a stream
    and kept). bayer: the sensor's pattern, or None for mono.
    """

    def __init__(self, client, *, sensor=None, bits=None, bayer=None):
        self.client = client
        self.bayer = normalise_bayer(bayer)
        self.frames = queue.Queue()
        self._bits = int(bits) if bits else None
        self._sensor = tuple(int(v) for v in sensor) if sensor else None
        self._simulated = callable(getattr(client, 'start_video', None))
        self._ctl = threading.RLock()     # one camera reconfiguration at a time
        self._cond = threading.Condition()
        self._running = False
        self._generation = 0              # counts start()s: a whole_frame begun before a restart ends with it
        self._region = None               # the region the controller asked for
        self._streaming = None            # the region the camera is streaming now
        self._exposure = 0.0
        self._gain = 0.0
        self._full_scale = None
        self._whole_waiting = False
        self._whole = None
        self._fps_max = None
        self._fps_min = None
        self._present = {}                # optional property -> whether the driver has it
        self._gain_prop = _UNPROBED       # (property, element) the gain goes to, or None: see GAIN_PROPERTIES
        self._size_warned = False         # a blob of the wrong size is reported once per session

    # -- PictureSource -----------------------------------------------------------------------------------------------

    def can_set_gain(self) -> bool:
        """False when the driver has no gain property the stream can set: a new gain is then ignored, and every
        frame keeps the gain the camera has."""
        return self._simulated or self._gain_property() is not None

    def start(self, roi, exposure, gain):
        w, h = self._sensor_size()
        region = snap_roi(roi, (h, w)) if roi is not None else (0, 0, w - w % 2, h - h % 2)
        with self._cond:
            self._region = region
            self._exposure = float(exposure)
            self._gain = float(gain)
            self._running = True
            self._generation += 1
            # a whole_frame still waiting belongs to the stream before this start: release it, and stop it holding
            # back this stream's frames
            self._whole_waiting = False
            self._cond.notify_all()
            self._size_warned = False
        self.client.blob_sink = self._on_blob
        self._configure(region)

    def set_camera(self, exposure, gain):
        """Restart the stream with new settings. While it restarts no frame is taken: one still on its way was
        exposed with the old settings and would carry the new label."""
        settable = self.can_set_gain()
        with self._ctl:
            with self._cond:
                self._exposure = float(exposure)
                if settable:
                    self._gain = float(gain)
                if not self._running:
                    return
                streaming, self._streaming = self._streaming, None
            try:
                if self._simulated:
                    self._restart_simulated(streaming)
                else:
                    self._stream(False)
                    self._set_rate()
                    self._stream(True)
            finally:
                with self._cond:
                    if self._streaming is None:
                        self._streaming = streaming

    def whole_frame(self, timeout=WHOLE_FRAME_TIMEOUT_S):
        """One full-sensor frame: stream the whole sensor until one arrives, then the region again."""
        w, h = self._sensor_size()
        full = (0, 0, w - w % 2, h - h % 2)
        with self._cond:
            if not self._running:
                raise RuntimeError('the picture source stopped')
            generation = self._generation
            self._whole = None
            self._whole_waiting = True
        try:
            self._configure(full, generation)
            deadline = time.monotonic() + timeout
            with self._cond:
                while self._whole is None:
                    # stopped, or stopped and started again (a region change) before this thread woke up
                    if not self._running or self._generation != generation:
                        raise RuntimeError('the picture source stopped')
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('no whole-sensor picture')
                    self._cond.wait(remaining)
                return self._whole
        finally:
            with self._cond:
                same = self._generation == generation
                if same:
                    self._whole_waiting = False
                    self._whole = None
                running, region = self._running, self._region
            if running and same:  # a restart has already put its own region on the camera
                self._configure(region, generation)

    def stop(self):
        with self._cond:
            was = self._running
            self._running = False
            self._cond.notify_all()
        if not was:
            return
        with self._ctl:
            try:
                if self._simulated:
                    self.client.stop_video()
                else:
                    self._stream(False)
            finally:
                if getattr(self.client, 'blob_sink', None) == self._on_blob:
                    self.client.blob_sink = None  # a blob still on its way is dropped by the client

    # -- camera ------------------------------------------------------------------------------------------------------

    def _configure(self, region, generation=None):
        """The start order (focus_spike.py prep_stream): stream off, region, format, rate, gain, exposure, on.
        generation: whole_frame's; when a restart came since, its region is on the camera and this does nothing."""
        with self._ctl:
            with self._cond:
                if not self._running or (generation is not None and generation != self._generation):
                    return
            if self._simulated:
                self._set_streaming(region)
                self._restart_simulated(tuple(region))
                return
            client, device = self.client, _device(self.client)
            self._stream(False)
            if self._has('CCD_BINNING', 'number'):
                # the stream's blobs are binned too: at 2x2 every one would be a quarter of the region's size
                client.set_number(device, 'CCD_BINNING', {'HOR_BIN': 1, 'VER_BIN': 1}, timeout=SET_TIMEOUT_S)
            self._set_streaming(region)
            x, y, w, h = region
            client.set_number(device, 'CCD_FRAME', {'X': x, 'Y': y, 'WIDTH': w, 'HEIGHT': h}, timeout=SET_TIMEOUT_S)
            client.set_number(device, 'CCD_STREAM_FRAME', {'X': 0, 'Y': 0, 'WIDTH': w, 'HEIGHT': h},
                              timeout=SET_TIMEOUT_S)
            client.set_switch(device, 'CCD_STREAM_ENCODER', on_switches=['RAW'])
            if self._has('STREAM_FULL_DEPTH', 'switch'):
                client.set_switch(device, 'STREAM_FULL_DEPTH', on_switches=['FULL_DEPTH_16BIT'])
            self._set_rate()
            self._stream(True)

    def _set_rate(self):
        client, device = self.client, _device(self.client)
        with self._cond:
            exposure, gain = self._exposure, self._gain
        if self._has('LIMITS', 'number'):
            client.set_number(device, 'LIMITS', {'LIMITS_PREVIEW_FPS': self._fps(exposure)}, timeout=SET_TIMEOUT_S)
        prop = self._gain_property()
        if prop is not None:
            client.set_number(device, prop[0], {prop[1]: gain}, timeout=SET_TIMEOUT_S)
        client.set_number(device, 'STREAMING_EXPOSURE',
                          {'STREAMING_EXPOSURE_VALUE': exposure, 'STREAMING_DIVISOR_VALUE': 1},
                          timeout=SET_TIMEOUT_S)

    def _has(self, name, ctl_type) -> bool:
        if name not in self._present:
            try:
                self.client.get_control(_device(self.client), name, ctl_type, timeout=CONTROL_TIMEOUT_S)
                self._present[name] = True
            except Exception:
                logger.warning('Focus: the camera driver has no %s; it is left as it is', name)
                self._present[name] = False
        return self._present[name]

    def _gain_property(self):
        if self._gain_prop is _UNPROBED:
            found = None
            for name, element in GAIN_PROPERTIES:
                try:
                    ctl = self.client.get_control(_device(self.client), name, 'number', timeout=CONTROL_TIMEOUT_S)
                except Exception:
                    continue
                if any(e.getName() == element for e in ctl):
                    found = (name, element)
                    break
            if found is None:
                logger.warning('Focus: the camera driver has no gain property; the gain is left as it is')
            self._gain_prop = found
        return self._gain_prop

    def _stream(self, on):
        # sync=False: the driver keeps CCD_VIDEO_STREAM at BUSY for as long as it streams, so a wait for OK would
        # time out on every start (focus_spike.py set_switch sends and never waits)
        self.client.set_switch(_device(self.client), 'CCD_VIDEO_STREAM',
                               on_switches=['STREAM_ON' if on else 'STREAM_OFF'], sync=False)

    def _restart_simulated(self, region):
        with self._cond:
            exposure = self._exposure
        self.client.stop_video()
        self.client.start_video(exposure, region)

    def _set_streaming(self, region):
        with self._cond:
            self._streaming = tuple(region)
            self._full_scale = None  # decided again on the first frame of this stream

    def _fps(self, exposure) -> float:
        """One picture per exposure, inside the range the driver accepts. The value is a ceiling on preview frames,
        so a floor above 1/exposure is harmless: the exposure still sets the real rate. ZWO's floor is 1 fps, and it
        refuses less (an exposure over 1 s ended the session)."""
        fps = 1.0 / exposure
        if self._fps_max is None:
            try:
                ctl = self.client.get_control(_device(self.client), 'LIMITS', 'number', timeout=CONTROL_TIMEOUT_S)
                for e in ctl:
                    if e.getName() == 'LIMITS_PREVIEW_FPS':
                        self._fps_max = _element_max(e)
                        self._fps_min = _element_min(e)
            except Exception:
                logger.warning('Focus: the driver gave no preview frame rate limit')
        if self._fps_max is not None and self._fps_max > 0:
            fps = min(fps, self._fps_max)
        if self._fps_min is not None and self._fps_min > 0:
            fps = max(fps, self._fps_min)
        return fps

    def _sensor_size(self):
        if self._sensor is None:
            ctl = self.client.get_control(_device(self.client), 'CCD_FRAME', 'number', timeout=CONTROL_TIMEOUT_S)
            sizes = {e.getName(): _element_max(e) for e in ctl}
            self._sensor = (int(sizes['WIDTH']), int(sizes['HEIGHT']))
        return self._sensor

    # -- blobs (on the INDI client's thread) -------------------------------------------------------------------------

    def _on_blob(self, data, fmt, t):
        with self._cond:
            if not self._running or self._streaming is None:
                return
            region, exposure, gain = self._streaming, self._exposure, self._gain
            wanted = self._region
            whole = self._whole_waiting and region[2:] == self._sensor_size_even()
        raw, full_scale = decode_stream(data, region[2], region[3], fmt)
        if raw is None:
            with self._cond:
                warn, self._size_warned = not self._size_warned, True
            if warn:
                logger.warning('Focus: the camera sends pictures of %d bytes, which is not a %dx%d frame; they are '
                               'dropped (is the camera binned?)', len(data), region[2], region[3])
            return
        mosaic = raw.dtype == np.uint16 or len(data) == region[2] * region[3]  # not a debayered or JPEG frame
        if raw.dtype == np.uint16:
            full_scale = self._latch_full_scale(raw)
        raw = np.array(raw, copy=True)
        with self._cond:
            if whole:
                self._whole = raw
                self._cond.notify_all()
                return
            if region != wanted or self._whole_waiting:
                return  # streaming some other region for a moment
        frame = RawFrame(raw=raw, full_scale=full_scale, bayer=self.bayer if mosaic else None, t_end=float(t),
                         exposure=exposure, gain=gain)
        while self.frames.qsize() >= MAX_QUEUED:
            try:
                self.frames.get_nowait()
            except queue.Empty:
                break
        self.frames.put(frame)

    def _sensor_size_even(self):
        w, h = self._sensor
        return (w - w % 2, h - h % 2)

    def _latch_full_scale(self, raw) -> float:
        """65535 unless the camera's bits are fewer and the data is plainly not shifted up to 16 bits: its peak fits
        in those bits and some value is not a multiple of the shift. Decided once per stream."""
        with self._cond:
            if self._full_scale is not None:
                return self._full_scale
        full = 65535.0
        if self._bits is not None and self._bits < 16:
            top = (1 << self._bits) - 1
            step = 1 << (16 - self._bits)
            if int(raw.max()) <= top and bool(np.any(raw % step)):
                full = float(top)
        with self._cond:
            if self._full_scale is None:
                self._full_scale = full
            return self._full_scale
