"""The focus session in the capture process: commands in, pictures and readings out.

`FocusService` lives as long as capture does and is the only reader of `LinkServer.poll_commands()`. With no session
it answers `ping` and `hello`, and turns a `start` from a page with controls into a `FocusController`.

`FocusController` runs one session. Its worker thread takes each `RawFrame` from the picture source, in order, and
when it falls behind it skips to the newest waiting frame (frame numbers still count the skipped ones):

    hot-pixel fix -> gray -> measure (picked stars) or pick (star count, glare filtered) -> preview copy -> clock -> JPEG
    -> link.broadcast_frame, then link.broadcast_json(reading)

Threading: every change of session state happens on the caller's thread (`handle`, `service`, `begin`, `end`), and so
does every call into the source but one. The worker never calls the source; it posts requests (a pick result, an
exposure-search step, a failure) that `service()` applies. `_lock` covers the rules, the ledger, the star set and the
generation counters; the worker takes it once per frame, only to copy a snapshot.

The one exception is `source.whole_frame()`, which can wait many seconds for a picture. A `focus-preview` thread makes
that call and the JPEG, then posts the reply for `service()` to send, so commands (`ping`, `done`) are answered and the
session rules keep ticking meanwhile. One preview at a time: a second `preview` while one is pending gets an `error`.
`end()` stops the source, which releases a waiting `whole_frame()`, and joins the thread; a reply still pending then is
dropped, so nothing follows `ended`.

Saturated stars: a star whose raw peak reaches SATURATION_FRACTION (0.98) of full scale is clipped, so its measured
size is wrong. The peak is the maximum of the hot-pixel-fixed raw (before gray) in a MEASURE_BOX square around the
star. It is checked twice:
  - at the pick, as the median peak over the grading frames. Such a star stays in the set with the state `saturated`
    in the `stars` message, so the page can show why it is not used. It is not dropped, because a shorter exposure
    can bring it back: the per-frame check below decides each frame.
  - on every frame: a star clipped in that frame never adds to `size`, whatever its state, and its ring says
    `saturated`. A star marked `saturated` at the pick counts again on a frame where it is not clipped. When no star
    is used and a wanted one was clipped, the reading's message is MSG_SATURATED.

A page may command only when the hello it registered with carries `'controls': True`. `ping` and `hello` are open to
every page; every other command is refused to a watcher with an `error`.

Messages from a page (`kind` and fields):
    start                           begin a session (FocusService); during one, answered with `state`
    done                            end the session
    ping        id?                 -> pong
    hello                           -> state
    keep_going                      reset the idle timer
    set_camera  exposure, gain, cmd_id?      exposure in s (0 < e <= 3600), gain >= 0
    set_region  roi: [x, y, w, h] | null, cmd_id?   snapped to the Bayer grid (even x, y, w, h)
    preview                         -> preview, later (one at a time; `error` while one is pending)
    pick_stars                      stack 3 frames begun after the press, pick, grade
    star        id, state: keep | drop | pin        pin is exclusive
    min_snr     value               clamped to 3..60
    move_to     target, cmd_id?     move the lens to `target` steps (clamped to what it can reach); frames begun
                                    Lens.SETTLE_S after the move ends carry cmd_id
    nudge       steps, cmd_id?      move by signed steps (positive outward)
    back        cmd_id?             return to where the lens last rested (after Autofocus: where it started)
    stop                            stop a move, or a running Autofocus; the lens stays where it is
    autofocus   cmd_id?             scan, fit and park; needs picked stars
    clear_graph                     empty the graph's points and fit; answered with `graph`
    set_stretch mode: auto | manual | off, black?, white?, relevel?
                                    the picture's levels, for every page; measuring never sees them. manual needs
                                    black and white as shares of full scale (0..1, white > black); auto with
                                    relevel: true levels again from the next frame
    tune                            run the exposure search again (the video rig's tune ladder);
                                    `error` while a pick runs. set_camera stops a running one; pick_stars is
                                    refused while a tune runs
cmd_id is an int in 0..2**32-1.

Messages to a page:
    state     session ('active' | 'idle'), controls, pages, idle_warning (s or null), rig {page, picture, reason};
              active: motor {configured, ok, reason}; idle: driver_has_video, idle_reason (the last session's end
              reason or null)
    lens      every LensState field, cmd_id (of the move, or null), reachable [lo, hi], fine, coarse (steps)
    graph     measure, points [[x, star_id, size]...] (star_id null for contrast), fit (as `fit`, or null)
    fit       c, a, k, P, band [lo, hi], n, stars, ok, message; or null when cleared
    pong      t (server epoch s), id (echoed)
    mode      picture, reason, exposure, gain, roi ([x, y, w, h] or null)
    reading   frame, cmd_id, capture_time, exposure, gain, width, height (gray px; the JPEG is half size),
              measure ('stars' | 'contrast' | 'none'), stars_visible (count before a pick, else null),
              size (median of the used stars, px, or null), stars_used, contrast (or null),
              rings [{id, x, y, size, snr, state}] (size and snr null when the star was not found; state as in
              `stars`, but `saturated` only when this frame clipped the star), message (or null)
              x (the lens position the frame's points sit at, or null), points ([[x, star_id, size]...] or [])
    measure   measure (sent when the measure switches)
    stars     stars [{id, x, y, snr1, state: kept | weak | saturated | dropped | pinned}], min_snr
              (precedence: pinned, dropped, saturated, then kept or weak by snr1)
    progress  what ('pick' | 'exposure_search' | 'tune' | 'region' | 'autofocus'), message, done; pick also:
              frame, of, candidates; autofocus also: stage, stages, estimate_s, columns. 'tune' and 'exposure_search': the session's search, from the start or a tune command
              'region': the session moved the first region off a clipped light source (`off_glare`), once
    stretch   mode ('auto' | 'manual' | 'off'), black, white (shares of full scale; null until Auto has levelled)
    preview   jpeg (base64), width, height (the whole sensor, px), jpeg_width, jpeg_height
    error     message, command
    ended     reason ('done' | 'cancelled' | 'cancelled_hand' | 'cancel_short' | 'no_page' | 'idle' | 'failed'
              | 'stopped')
"""

from __future__ import annotations

import base64
import dataclasses
import logging
import math
import queue
import statistics
import threading
from collections import deque
import time
import traceback
from dataclasses import dataclass
from typing import Callable
from typing import Optional

import cv2
import numpy as np

from indi_allsky import constants
from indi_allsky.focus.autofocus import STAGES
from indi_allsky.focus.autofocus import Autofocus
from indi_allsky.focus.exposure_search import FOUND_STARS
from indi_allsky.focus.exposure_search import MSG_NO_STARS
from indi_allsky.focus.exposure_search import brightness
from indi_allsky.focus.fit import fit_curve
from indi_allsky.focus.frame import ISO_CLOCK_FORMAT
from indi_allsky.focus.frame import Stretch
from indi_allsky.focus.frame import draw_clock
from indi_allsky.focus.frame import encode_jpeg
from indi_allsky.focus.frame import pack_frame
from indi_allsky.focus.frame import preview
from indi_allsky.focus.lens import Lens
from indi_allsky.focus.measure import DEFAULT_MIN_SNR
from indi_allsky.focus.measure import MEASURE_BOX
from indi_allsky.focus.measure import Candidate
from indi_allsky.focus.measure import Tracker
from indi_allsky.focus.measure import contrast_score
from indi_allsky.focus.measure import find_hot_pixels
from indi_allsky.focus.measure import fix_hot_pixels
from indi_allsky.focus.measure import grade
from indi_allsky.focus.measure import measure_star
from indi_allsky.focus.measure import noise_sigma
from indi_allsky.focus.measure import off_glare
from indi_allsky.focus.measure import pick
from indi_allsky.focus.measure import to_gray
from indi_allsky.focus.rigs import RigDecision
from indi_allsky.focus.session import CommandLedger
from indi_allsky.focus.session import SessionRules
from indi_allsky.focus.sources import normalise_bayer
from indi_allsky.focus.tune import count_stars
from indi_allsky.focus.tune import where


logger = logging.getLogger('indi_allsky')


WORKER_POLL_S = 0.1
JOIN_TIMEOUT_S = 5.0
MAX_FRAME_FAILURES = 5
MEASURE_SWITCH_FRAMES = 5     # a new measure must win this many frames in a row
PICK_FRAMES = 3
GRADE_SECONDS = 4.0           # grade over about 4 s of single frames, and at least 3
GRADE_MIN_FRAMES = 3
MAX_POINTS = 20000            # graph points kept, oldest dropped
FINE_LENS_DEGREES = 0.8       # step sizes in lens-ring degrees; a good fit replaces fine and medium
MEDIUM_LENS_DEGREES = 3.5
COARSE_LENS_DEGREES = 13.0
AF_TAIL_S = 2.0               # after the scan, wait this long (plus two exposures) for its last frames
MIN_SNR_RANGE = (3.0, 60.0)
MAX_EXPOSURE_S = 3600.0
PREVIEW_MAX_PX = 1024
SATURATION_FRACTION = 0.98    # a raw peak at or above this share of full scale is clipped
CMD_ID_MAX = 2 ** 32 - 1
STRETCH_MODES = ('auto', 'manual', 'off')

# a session's plan (the page's start message): run on into autofocus, or stop after the tune
PLAN_AUTOFOCUS = 'autofocus'
PLAN_PREVIEW = 'preview'

MSG_CONTROLS = 'Only a page with controls can do that.'
MSG_NO_SESSION = 'No focus session is running.'
MSG_UNKNOWN = 'Unknown command.'
MSG_COMMAND_FAILED = 'That did not work. The focus session goes on.'
MSG_CAMERA_REFUSED = 'The camera did not take {0}. It is back on {1}.'
MSG_INVALID = 'Not a valid {0}.'
MSG_PICK_BUSY = 'Wait for the star pick to finish.'
MSG_SEARCH_BUSY = 'Wait for the tune to finish.'
MSG_SEARCH_STOPPED = 'Tune stopped: your settings are kept.'
MSG_PICK_WAIT = 'Picking stars: waiting for a new picture'
MSG_PICKING = 'Picking stars: frame {0:d} of {1:d} · {2:d} found so far'
MSG_PICK_NONE = 'No stars found to pick. Try a longer exposure.'
MSG_PICKED = 'Picked {0:d} stars.'
MSG_PICK_CANCELLED = 'Star pick cancelled: the region moved.'
MSG_OFF_GLARE = 'The region moved away from a bright light (the moon?). Use Move region to choose another.'
MSG_VISIBLE = 'About {0:d} stars visible · press Autofocus to measure'
MSG_VISIBLE_HAND = 'About {0:d} stars visible · press Tune to measure'  # a hand rig's tune runs on into a pick
MSG_OVER = 'The picture is over-exposed. Try a shorter exposure.'
MSG_LOST = 'None of the picked stars is in this picture.'
MSG_PREVIEW_FAILED = 'Could not take a whole-sensor picture.'
MSG_PREVIEW_BUSY = 'A whole-sensor picture is already on its way.'
MSG_SATURATED = 'The picked stars are saturated. Try a shorter exposure.'
MSG_EXPOSURE_RANGE = 'That exposure is outside what this camera can take. The camera was not changed.'
MSG_GAIN_RANGE = 'That gain is outside what this camera can take. The camera was not changed.'
MSG_START_FAILED = 'The focus session could not start.'
MSG_NO_MOTOR = 'No focus motor is set up.'
MSG_LENS_BUSY = 'Wait for the lens to stop.'
MSG_CANCELLING = 'Cancel is putting the lens back.'
MSG_AF_NEEDS_STARS = 'Autofocus needs stars.'
MSG_AF_BUSY = 'Autofocus is running. Press Stop first.'
MSG_AF_STOPPED = 'Autofocus stopped. Back returns the lens to where it was.'
MSG_AF_SHORT = 'The lens stopped short. Autofocus stopped.'
MSG_NO_BACK = 'There is no earlier position to go back to.'
MSG_MISSING_PROPERTY = ('The camera driver has no {0}, which a focus session needs. '
                        'The session did not start and the camera was not changed.')

SESSION_TURN_S = 0.05         # capture's loop sleep while a session runs, and per wait-loop turn
STATUS_EVERY_S = 1.0          # WATCHDOG and STATUS writes during a session, at most this often

OPEN_COMMANDS = ('ping', 'hello')


def step_sizes(steps_per_lens_turn: float, fit: Optional[dict]) -> dict:
    """The Fine, Medium and Coarse step sizes in motor steps. Fixed lens-degree sizes until a good fit; then Fine
    is a quarter of the fit's band and Medium the whole band. Coarse stays fixed."""
    def steps(lens_deg):
        return max(1, int(round(lens_deg * steps_per_lens_turn / 360.0)))
    sizes = {'fine': steps(FINE_LENS_DEGREES), 'medium': steps(MEDIUM_LENS_DEGREES),
             'coarse': steps(COARSE_LENS_DEGREES)}
    if fit is not None and fit.get('ok'):
        band = fit['band'][1] - fit['band'][0]
        sizes['fine'] = max(1, int(round(band / 4.0)))
        sizes['medium'] = max(1, int(round(band)))
    return sizes


@dataclass(frozen=True)
class CameraInfo:
    interface: str
    device_name: str
    driver_has_video: bool
    rig: RigDecision


class _Invalid(Exception):
    """A command value out of range; the argument names it for MSG_INVALID."""


class StartRefused(Exception):
    """Raised by a controller factory before it touches the camera. Its message is page copy: the page shows it,
    and capture's exposure goes on."""


def _rig_dict(rig) -> dict:
    return dataclasses.asdict(rig) if rig is not None else None


def _num(v, name, low=None, high=None, low_open=False) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise _Invalid(name)
    try:
        v = float(v)  # an int too large for a float (valid JSON) raises OverflowError
    except (OverflowError, TypeError, ValueError):
        raise _Invalid(name) from None
    if not math.isfinite(v):
        raise _Invalid(name)
    if low is not None and (v < low or (low_open and v == low)):
        raise _Invalid(name)
    if high is not None and v > high:
        raise _Invalid(name)
    return v


def _int(v, name, low, high) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not low <= v <= high:
        raise _Invalid(name)
    return v


def _cmd_id(msg) -> Optional[int]:
    if msg.get('cmd_id') is None:
        return None
    return _int(msg['cmd_id'], 'command id', 0, CMD_ID_MAX)


def _echo_id(msg) -> Optional[int]:
    """A command's id to send back with an error about it; None when it has no valid one."""
    try:
        return _cmd_id(msg) if isinstance(msg, dict) else None
    except _Invalid:
        return None


def _roi(v):
    if v is None:
        return None
    if not isinstance(v, (list, tuple)) or len(v) != 4:
        raise _Invalid('region')
    x, y, w, h = (_int(n, 'region', 0, 1 << 20) for n in v)
    x, y, w, h = x - x % 2, y - y % 2, w - w % 2, h - h % 2
    if w < 2 or h < 2:
        raise _Invalid('region')
    return (x, y, w, h)


def _f(v) -> Optional[float]:
    """A JSON-safe float: NaN and infinities become None."""
    if v is None:
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def _peak(raw, x, y) -> float:
    """The brightest raw value in the measure box around (x, y)."""
    half = MEASURE_BOX // 2
    xi, yi = int(round(x)), int(round(y))
    box = raw[max(0, yi - half):yi + half + 1, max(0, xi - half):xi + half + 1]
    return float(box.max()) if box.size else 0.0


class _Pick(object):
    """The worker's star pick in progress: stack frames begun after `press`, then grade the picked stars."""

    def __init__(self, gen, press):
        self.gen = gen
        self.press = press
        self.frames = []          # (gray, hot-pixel-fixed raw, saturation level) of each stacked frame
        self.stack = None
        self.cands = None
        self.snrs = None
        self.peaks = None         # per candidate: its raw peak over the saturation level, per grading frame
        self.need = GRADE_MIN_FRAMES


class FocusController(object):

    def __init__(self, source, link, clock, rig: RigDecision, lens: Optional[Lens], *,
                 motor_reason: Optional[str] = None,
                 epoch: Callable[[], float] = time.time, exposure: float = 1.0, gain: float = 0.0, roi=None,
                 search: Optional[Callable[[float, float, dict], object]] = None,
                 saved_camera: Optional[dict] = None,
                 exposure_min: Optional[float] = None, exposure_max: Optional[float] = None,
                 gain_min: Optional[float] = None, gain_max: Optional[float] = None,
                 sensor: Optional[tuple[int, int]] = None, clock_format: str = ISO_CLOCK_FORMAT):
        """clock_format: the strftime format of the time stamped on each picture (frame.clock_format).

        exposure_min .. gain_max: what the camera takes (None: not known). The page's controls stay inside them
        and set_camera refuses anything outside. A source whose `can_set_gain()` is False keeps its gain: the gain
        limits are then None and set_camera leaves the gain as it is.

        sensor: (width, height) in px. With it and a `roi`, the first frame is checked for a clipped light source
        (the moon) and the region moves off it (`off_glare`).

        search: makes the session's exposure search, called as search(exposure, gain, limits) at the start, on a
        `tune` command, and when the region moves while one runs. It returns an `ExposureSearch` or a `Tune`.

        lens: the session's `Lens` (its clock must be `epoch`, the clock frames are stamped with), or None when there
        is no focus motor. motor_reason: why a configured motor could not be used (None when it works or none is
        configured). The lens's on_change must call `on_lens_change`."""
        self.source = source
        self._clock_format = clock_format
        can_set_gain = getattr(source, 'can_set_gain', None)
        self._gain_settable = bool(can_set_gain()) if callable(can_set_gain) else True
        if not self._gain_settable:
            gain_min = gain_max = None
        self.limits = {'exposure_min': exposure_min, 'exposure_max': exposure_max,
                       'gain_min': gain_min, 'gain_max': gain_max}
        self.link = link
        self.rig = rig
        self.lens = lens if lens else None
        self.motor = {'configured': self.lens is not None or motor_reason is not None, 'ok': self.lens is not None,
                      'reason': motor_reason}
        self.exposure = float(exposure)
        self.gain = float(gain)
        self.roi = tuple(roi) if roi is not None else None
        self.saved_camera = dict(saved_camera) if saved_camera is not None else {
            'exposure': self.exposure, 'gain': self.gain, 'roi': self.roi}
        self.end_reason = None

        self._epoch = epoch
        self._lock = threading.Lock()
        self.rules = SessionRules(clock)
        self.ledger = CommandLedger(clock=epoch)
        self._stars = []          # [{'id', 'x', 'y', 'snr1', 'saturated', 'choice': keep | drop | pin}]
        self._stars_gen = 0
        self._min_snr = DEFAULT_MIN_SNR
        self._region_gen = 0
        self._region_since = None  # epoch of the last region change
        self._pick_gen = 0
        self._pick_press = None   # epoch of the pick's start while a pick runs
        self._search_factory = search
        self._search = None          # the running (or last) search; the worker steps it, this thread replaces it
        self._search_on = False
        self._search_gen = 0
        self._search_since = None    # epoch of its last camera change: a frame begun before it is not its point
        self._stretch_mode = 'auto'
        self._stretch_levels = None  # (black, white) as shares of full scale: Auto's latest or the Manual choice
        self._stretch_gen = 0        # a new generation makes Auto level again from the next frame
        self._points = deque(maxlen=MAX_POINTS)  # graph points [x, star_id, size] (star_id None for contrast)
        self._fit = None             # the graph's fit message body, or None
        self._lens_cmd = None        # cmd_id of the page's running lens move
        self._af_feed = None         # (gen, scan start epoch) while the autofocus scan takes frames

        self._active = False
        self._ended = False
        self._pages = set()
        self._warned = None
        self._requests = queue.Queue()
        self._stop = threading.Event()
        self._thread = None
        self._preview_thread = None
        self._restarts = 0        # source restarts by set_region (under _lock)
        self._lens_events = queue.Queue()

        # autofocus: owning thread only (the worker sees _af_feed, the fit thread posts its result)
        self._af = None
        self._af_gen = 0
        self._af_cmd = None
        self._af_auto = None         # stars_gen of a pick that starts autofocus once stars are measured
        # the session's plan: 'autofocus' runs on by itself (a tune that finds stars starts the pick, a pick starts
        # autofocus); 'preview' stops after the tune and leaves the lens to the reader until they press Autofocus
        self._plan = PLAN_AUTOFOCUS
        self._af_seen = None      # t_end of the newest scan frame applied
        self._af_scan_end = None  # (epoch the scan move ended, deadline for its last frames)
        self._cancel = None  # None | 'stopping' | 'returning': Cancel is putting the lens back to step 0

        # worker-only state
        self._frame_no = 0
        self._seen_stars_gen = -1
        self._seen_pick_gen = 0
        self._tracker = None
        self._pick = None
        self._frame_key = None
        self._hot = None
        self._stretch = None
        self._stretch_phase = 'linear'
        self._seen_stretch_gen = 0
        self._measure = None
        self._pending_measure = (None, 0)
        self._seen_search_gen = 0
        self._searcher = None
        self._search_done = False
        self._last_format = (None, 65535.0)
        self._sensor = tuple(sensor) if sensor is not None else None
        self._glare_check = self._sensor is not None and self.roi is not None

    @property
    def active(self) -> bool:
        return self._active

    # -- life ------------------------------------------------------------------------------------------------------

    def begin(self, by_client: int, plan: str = PLAN_AUTOFOCUS) -> None:
        """plan: PLAN_AUTOFOCUS or PLAN_PREVIEW (any other value is PLAN_AUTOFOCUS)."""
        with self._lock:
            self._plan = PLAN_PREVIEW if plan == PLAN_PREVIEW else PLAN_AUTOFOCUS
            self.rules.start()
            self._pages = set(self.link.clients())
            for cid in self._pages:
                self.rules.page_connected(cid)
            self._active = True
        logger.info('Focus session started by page %d', by_client)
        first = self._new_search()
        if first is not None:  # the source starts at the search's first point: no restart for it
            self.exposure = float(first.exposure)
            if first.gain is not None:
                self.gain = float(first.gain)
        if not self._source_call('start', self.source.start, self.roi, self.exposure, self.gain):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name='focus-worker', daemon=True)
        self._thread.start()
        self._send_state()
        self.link.broadcast_json(self._mode_msg())
        self.link.broadcast_json(self._stretch_msg())
        if self.lens is not None:
            self.link.broadcast_json(self._lens_msg(self.lens.state))
        self.link.broadcast_json(self._graph_msg())
        if first is not None:
            self._search_progress(first)

    def _new_search(self):
        """Make a new search and make it the running one. Returns its first step: None when it starts where the
        camera already is (or there is no search)."""
        if self._search_factory is None:
            return None
        search = self._search_factory(self.exposure, self.gain, dict(self.limits))
        with self._lock:
            self._search = search
            self._search_gen += 1
            self._search_on = True
            self._search_since = self._epoch()
        return search.first()

    def _search_progress(self, step):
        msg = {'kind': 'progress', 'what': self._search.kind, 'message': step.message, 'done': step.done}
        if step.step is not None and step.of:
            msg['step'], msg['of'] = step.step, step.of  # the page's step bar
        self.link.broadcast_json(msg)

    def _step_gain(self, step) -> float:
        return self.gain if step.gain is None or not self._gain_settable else float(step.gain)

    def _move_to(self, step) -> Optional[bool]:
        """Put the camera on a search step's exposure and gain. Same answers as _set_camera."""
        gain = self._step_gain(step)
        if step.exposure is None or (math.isclose(step.exposure, self.exposure) and math.isclose(gain, self.gain)):
            return True
        moved = self._set_camera(step.exposure, gain)
        if not moved:
            return moved
        self.exposure, self.gain = float(step.exposure), gain
        with self._lock:
            self._search_since = self._epoch()
        self.link.broadcast_json(self._mode_msg())
        return True

    def _go(self, step):
        """Move the camera to a search step and report it. A point the camera refuses is skipped (a tune) or stops
        the search (the stills search); a refusal with no way back has ended the session. Returns the step the
        camera is on, or None."""
        while True:
            moved = self._move_to(step)
            if moved:
                self._search_progress(step)
                return step
            if moved is None:
                return None
            fail = getattr(self._search, 'fail', None)
            if fail is None or step.done:
                with self._lock:
                    self._search_on = False
                self.link.broadcast_json({'kind': 'progress', 'what': self._search.kind, 'done': True,
                                          'message': self._refused(step.exposure, self._step_gain(step))})
                return None
            step = fail()  # a tune has a finite ladder, and its last step is done
            if step.done:
                self._settled(step)

    def _settled(self, step) -> None:
        with self._lock:
            self._search_on = False
        if hasattr(self._search, 'table'):
            logger.info('Focus: tune ladder (%s)\n%s', step.message, self._search.table())

    def _set_camera(self, exposure, gain) -> Optional[bool]:
        """Put the camera on exposure and gain. True: done. False: refused, and back on the settings it had (the
        session goes on). None: refused with no way back (the session ended as failed)."""
        try:
            self.source.set_camera(exposure, gain)
            return True
        except Exception:
            logger.exception('Focus: the camera refused %s', where(exposure, gain))
        try:
            self.source.set_camera(self.exposure, self.gain)
            return False
        except Exception:
            logger.exception('Focus: the camera could not go back to %s', where(self.exposure, self.gain))
            self.end('failed')
            return None

    def _refused(self, exposure, gain) -> str:
        return MSG_CAMERA_REFUSED.format(where(exposure, gain), where(self.exposure, self.gain))

    def end(self, reason: str) -> None:
        with self._lock:
            if self._ended:
                return
            self._ended = True
            self._active = False
            if self.rules.active:
                self.rules.end(reason)
            self.end_reason = reason
        logger.info('Focus session ended: %s', reason)
        self._stop.set()
        if self.lens is not None:
            self.lens.stop()  # the session's on_end closes it
        if self._af is not None:
            self._af.finish(MSG_AF_STOPPED)
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(JOIN_TIMEOUT_S)
            if self._thread.is_alive():
                logger.error('Focus: the worker did not stop within %.0f s', JOIN_TIMEOUT_S)
        try:
            self.source.stop()  # also releases a waiting whole_frame()
        except Exception:
            logger.exception('Focus: the picture source failed to stop')
        pending = self._preview_thread
        if pending is not None and pending is not threading.current_thread():
            pending.join(JOIN_TIMEOUT_S)
            if pending.is_alive():
                logger.error('Focus: the whole-sensor picture did not stop')
        self.link.broadcast_json({'kind': 'ended', 'reason': reason})

    def abandon(self, reason: str) -> None:
        """After `end` itself failed: count the session as over, so the service still puts the camera back."""
        with self._lock:
            self._ended = True
            self._active = False
            if self.end_reason is None:
                self.end_reason = reason

    def service(self) -> None:
        """Page arrivals, the session rules, and the worker's requests. Call it often from the owning thread."""
        if not self._active:
            return
        now_pages = set(self.link.clients())
        with self._lock:
            joined = now_pages - self._pages
            for cid in joined:
                self.rules.page_connected(cid)
            for cid in self._pages - now_pages:
                self.rules.page_left(cid)
            self._pages = now_pages
            reason = self.rules.tick()
            warning = self.rules.idle_warning()
        for cid in sorted(joined):
            self._send_state(cid)
            self.link.send_json(cid, self._mode_msg())
            self.link.send_json(cid, self._stretch_msg())
            self.link.send_json(cid, self._stars_msg())
            if self._measure is not None:
                self.link.send_json(cid, {'kind': 'measure', 'measure': self._measure})
            if self.lens is not None:
                self.link.send_json(cid, self._lens_msg(self.lens.state))
            self.link.send_json(cid, self._graph_msg())
            if self._af is not None and not self._af.done:
                self.link.send_json(cid, self._af_progress())

        while True:
            try:
                request = self._requests.get_nowait()
            except queue.Empty:
                break
            if not self._active:
                return
            self._apply(request)
        if not self._active:
            return
        self._service_lens()
        if not self._active:
            return
        self._auto_autofocus()

        if reason is not None:
            self.end(reason)
            return
        warned = None if warning is None else int(math.ceil(warning))
        if warned != self._warned:
            self._warned = warned
            self._send_state()

    # -- commands --------------------------------------------------------------------------------------------------

    def handle(self, client_id: int, msg: dict) -> None:
        """One command from a page. Never raises: a bad command gets an `error` and the session goes on."""
        kind = msg.get('kind') if isinstance(msg, dict) else None
        echo = _echo_id(msg)
        if not self._active and kind not in OPEN_COMMANDS:
            self._error(client_id, kind, MSG_NO_SESSION, echo)  # ended (a failed start, say) but not yet reaped
            return
        if kind not in OPEN_COMMANDS and not self._controls(client_id):
            self._error(client_id, kind, MSG_CONTROLS, echo)
            return
        if kind not in OPEN_COMMANDS:
            with self._lock:
                self.rules.touched()
        handler = getattr(self, '_cmd_' + kind, None) if isinstance(kind, str) else None
        if handler is None:
            self._error(client_id, kind, MSG_UNKNOWN)
            return
        try:
            handler(client_id, msg)
        except _Invalid as e:
            self._error(client_id, kind, MSG_INVALID.format(e.args[0]), echo)
        except Exception as e:
            # a bug, not a camera fault (source errors end the session in _source_call): keep the session for
            # every page and tell this one. Only the kind and the exception type are logged: the message, and so
            # a traceback's last line, can carry page input. The frames go to debug, without it.
            logger.warning('Focus: the %s command failed (%s)', kind, type(e).__name__)
            logger.debug('Focus: where the %s command failed:\n%s', kind,
                         ''.join(traceback.format_tb(e.__traceback__)))
            self._error(client_id, kind, MSG_COMMAND_FAILED, echo)

    def _cmd_ping(self, cid, msg):
        self.link.send_json(cid, {'kind': 'pong', 't': time.time(), 'id': msg.get('id')})

    def _cmd_hello(self, cid, msg):
        self._send_state(cid)

    def _cmd_start(self, cid, msg):
        self._send_state(cid)

    def _cmd_keep_going(self, cid, msg):
        self._warned = None
        self._send_state()

    def _cmd_done(self, cid, msg):
        self.end('done')  # keep the lens where it is: the page's Save

    def _cmd_cancel(self, cid, msg):
        """Put the lens back where it was at Start (step 0), then end the session. With no motor, end at once."""
        with self._lock:
            self._af_auto = None
        if self.lens is None:
            self.end('cancelled_hand')
            return
        if self._cancel is not None:
            return
        self._cancel = 'stopping'
        self.lens.stop()
        if self._af_running():
            self._af_end(MSG_AF_STOPPED, back=False)
        self._step_cancel()

    def _step_cancel(self) -> None:
        """On the owning thread: once the lens is at rest, send it to step 0; once it is there, end."""
        if self._cancel is None or self.lens.state.moving:
            return
        st = self.lens.state
        if self._cancel == 'stopping' and st.error is None and st.position != 0 and self.lens.move_to(0):
            self._cancel = 'returning'
            return
        position = self.lens.state.position
        if position != 0:
            logger.warning('Focus: Cancel left the lens at step %d, not where it was at Start', position)
        self.end('cancelled' if position == 0 else 'cancel_short')

    def _cmd_set_camera(self, cid, msg):
        if self._af_busy(cid, 'set_camera', msg):
            return
        exposure = _num(msg.get('exposure'), 'exposure', 0.0, MAX_EXPOSURE_S, low_open=True)
        gain = _num(msg.get('gain'), 'gain', 0.0)
        if not self._gain_settable:
            gain = self.gain  # the camera's gain cannot be changed: never claim it was
        cmd_id = _cmd_id(msg)
        lim = self.limits
        if ((lim['exposure_min'] is not None and exposure < lim['exposure_min'])
                or (lim['exposure_max'] is not None and exposure > lim['exposure_max'])):
            self._error(cid, 'set_camera', MSG_EXPOSURE_RANGE, cmd_id)
            return
        if ((lim['gain_min'] is not None and gain < lim['gain_min'])
                or (lim['gain_max'] is not None and gain > lim['gain_max'])):
            self._error(cid, 'set_camera', MSG_GAIN_RANGE, cmd_id)
            return
        with self._lock:
            if self._pick_press is not None:
                busy = True
            else:
                busy = False
                stopped = self._search_on  # the sliders override a running search
                self._search_on = False
                if cmd_id is not None:
                    self.ledger.begin(cmd_id)
        if busy:
            self._error(cid, 'set_camera', MSG_PICK_BUSY, cmd_id)
            return
        if stopped:
            self.link.broadcast_json({'kind': 'progress', 'what': self._search.kind, 'message': MSG_SEARCH_STOPPED,
                                      'done': True})
        moved = self._set_camera(exposure, gain)
        if moved is None:
            return
        if moved:
            self.exposure, self.gain = exposure, gain
        if cmd_id is not None:
            with self._lock:
                self.ledger.done(cmd_id, 0.0)
        if not moved:
            self._error(cid, 'set_camera', self._refused(exposure, gain), cmd_id)
        self.link.broadcast_json(self._mode_msg())  # on a refusal, the sliders go back

    def _cmd_set_region(self, cid, msg):
        if cid is not None and self._af_busy(cid, 'set_region', msg):
            return
        roi = _roi(msg.get('roi'))
        cmd_id = _cmd_id(msg)
        with self._lock:
            if cmd_id is not None:
                self.ledger.begin(cmd_id)
            cancelled = self._pick_press is not None
            self._clear_stars_locked()
            self._restarts += 1  # before the stop: a preview it releases knows it was superseded
        if not self._source_call('stop', self.source.stop):
            return
        _drain(self.source.frames)
        with self._lock:
            # a frame begun before now is from the old region; the worker skips it (a stills load in flight can
            # still queue one after the drain)
            self._region_gen += 1
            self._region_since = self._epoch()
        self.roi = roi
        if not self._source_call('start', self.source.start, roi, self.exposure, self.gain):
            return
        if cmd_id is not None:
            with self._lock:
                self.ledger.done(cmd_id, 0.0)
        if cancelled:
            self.link.broadcast_json({'kind': 'progress', 'what': 'pick', 'message': MSG_PICK_CANCELLED,
                                      'done': True, 'frame': 0, 'of': PICK_FRAMES, 'candidates': 0})
        self.link.broadcast_json(self._stars_msg())
        self.link.broadcast_json(self._mode_msg())
        with self._lock:
            searching = self._search_on
        if searching:  # its points so far were of the old region: start it again
            self._restart_search()

    def _cmd_tune(self, cid, msg):
        if self._af_busy(cid, 'tune', msg):
            return
        if self._search_factory is None:
            self._error(cid, 'tune', MSG_UNKNOWN)
            return
        with self._lock:
            busy = self._pick_press is not None
        if busy:
            self._error(cid, 'tune', MSG_PICK_BUSY)
            return
        self._restart_search()

    def _restart_search(self):
        first = self._new_search()
        if first is not None:
            self._go(first)

    def _cmd_preview(self, cid, msg):
        if self._preview_thread is not None and self._preview_thread.is_alive():
            self._error(cid, 'preview', MSG_PREVIEW_BUSY)
            return
        with self._lock:
            restarts = self._restarts
        self._preview_thread = threading.Thread(target=self._take_preview, args=(cid, restarts),
                                                name='focus-preview', daemon=True)
        self._preview_thread.start()

    def _take_preview(self, cid, restarts):
        """On the focus-preview thread: wait for the whole sensor, make the reply, post it for service()."""
        try:
            raw = self.source.whole_frame()
            reply = self._preview_msg(raw, self._preview_bayer())
        except Exception:
            with self._lock:
                superseded = self._restarts != restarts
            if self._stop.is_set() or superseded:
                # the session ended, or a region change restarted the source: expected, and nothing to say
                logger.info('Focus: whole-sensor picture abandoned (%s)', 'ended' if self._stop.is_set() else
                            'the region moved')
                return
            logger.exception('Focus: whole-sensor picture failed')
            reply = None
        self._post(('preview', cid, reply))

    def _preview_bayer(self):
        """The Bayer pattern for the whole sensor: the source's, else the stream's (the region crop keeps the
        Bayer phase). None before any picture or for mono."""
        known = normalise_bayer(getattr(self.source, 'bayer', None))
        return known if known is not None else self._last_format[0]

    @staticmethod
    def _preview_msg(raw, bayer):
        gray = to_gray(raw, bayer)
        full = float(np.iinfo(raw.dtype).max) if raw.dtype.kind in 'ui' else 65535.0
        img = preview(gray, Stretch.from_frame(gray, SATURATION_FRACTION * full))  # the moon must not set white
        longest = max(img.shape[:2])
        if longest > PREVIEW_MAX_PX:
            f = PREVIEW_MAX_PX / float(longest)
            img = cv2.resize(img, (max(1, int(img.shape[1] * f)), max(1, int(img.shape[0] * f))),
                             interpolation=cv2.INTER_AREA)
        # width and height are the sensor's: the page maps the region it draws on the JPEG back to sensor px
        return {
            'kind': 'preview',
            'jpeg': base64.b64encode(encode_jpeg(img)).decode('ascii'),
            'width': int(raw.shape[1]),
            'height': int(raw.shape[0]),
            'jpeg_width': int(img.shape[1]),
            'jpeg_height': int(img.shape[0]),
        }

    def _cmd_pick_stars(self, cid, msg):
        if self._af_busy(cid, 'pick_stars', msg):
            return
        if not self._begin_pick():
            self._error(cid, 'pick_stars', MSG_SEARCH_BUSY)

    def _begin_pick(self) -> bool:
        """Start a pick. False: a tune is running."""
        with self._lock:
            # stopping a tune would leave the camera on whichever ladder point it had reached; the stills search
            # only ever lengthens toward stars, so a pick just ends it there
            if self._search_on and self._search.kind == 'tune':
                return False
            self._pick_gen += 1
            self._pick_press = self._epoch()
            self._search_on = False
            self._af_auto = None
        self.link.broadcast_json({'kind': 'progress', 'what': 'pick', 'message': MSG_PICK_WAIT,
                                  'done': False, 'frame': 0, 'of': PICK_FRAMES, 'candidates': 0})
        return True

    def _cmd_star(self, cid, msg):
        state = msg.get('state')
        if state not in ('keep', 'drop', 'pin'):
            raise _Invalid('star state')
        with self._lock:
            ids = [s['id'] for s in self._stars]
            star_id = msg.get('id')
            if isinstance(star_id, bool) or star_id not in ids:
                raise _Invalid('star')
            for s in self._stars:
                if s['id'] == star_id:
                    s['choice'] = state
                elif state == 'pin' and s['choice'] == 'pin':
                    s['choice'] = 'keep'
        self.link.broadcast_json(self._stars_msg())

    def _cmd_min_snr(self, cid, msg):
        value = _num(msg.get('value'), 'brightness')
        with self._lock:
            self._min_snr = min(max(value, MIN_SNR_RANGE[0]), MIN_SNR_RANGE[1])
        self.link.broadcast_json(self._stars_msg())

    def _cmd_set_stretch(self, cid, msg):
        mode = msg.get('mode')
        if mode not in STRETCH_MODES:
            raise _Invalid('stretch')
        levels = None
        if mode == 'manual':
            black = _num(msg.get('black'), 'black level', 0.0, 1.0)
            white = _num(msg.get('white'), 'white level', 0.0, 1.0)
            if white <= black:
                raise _Invalid('white level')
            levels = (black, white)
        with self._lock:
            if mode == 'manual':
                self._stretch_levels = levels
            elif mode == 'auto' and (self._stretch_mode != 'auto' or msg.get('relevel') is True):
                self._stretch_gen += 1  # level again from the next frame; the levels shown stay until then
            self._stretch_mode = mode
        self.link.broadcast_json(self._stretch_msg())

    # -- the lens and autofocus -----------------------------------------------------------------------------------

    def on_lens_change(self, state) -> None:
        """The lens's on_change: any thread. service() sends it on."""
        self._lens_events.put(state)

    def _af_running(self) -> bool:
        return self._af is not None and not self._af.done

    def _af_busy(self, cid, command, msg) -> bool:
        """Refuse a command that would spoil a running autofocus."""
        if not self._af_running():
            return False
        self._error(cid, command, MSG_AF_BUSY, _echo_id(msg))
        return True

    def _lens_ready(self, cid, command, cmd_id) -> bool:
        if self.lens is None:
            self._error(cid, command, MSG_NO_MOTOR, cmd_id)
            return False
        if self._af_running():
            self._error(cid, command, MSG_AF_BUSY, cmd_id)
            return False
        if self._cancel is not None:
            self._error(cid, command, MSG_CANCELLING, cmd_id)
            return False
        with self._lock:
            searching = self._search_on
        if searching:  # a move mid-tune would spoil the exposures it compares
            self._error(cid, command, MSG_SEARCH_BUSY, cmd_id)
            return False
        if self.lens.state.moving:
            self._error(cid, command, MSG_LENS_BUSY, cmd_id)
            return False
        return True

    def _page_move(self, cid, command, cmd_id, go) -> None:
        """Run one page-driven lens move. Frames begun Lens.SETTLE_S after it ends carry cmd_id."""
        if not self._lens_ready(cid, command, cmd_id):
            return
        with self._lock:
            self._af_auto = None  # the page took the lens: it decides what comes next
            if cmd_id is not None:
                self.ledger.begin(cmd_id)
            self._lens_cmd = cmd_id
        if not go():
            with self._lock:
                self._lens_cmd = None
                if cmd_id is not None:
                    self.ledger.done(cmd_id, 0.0)
            self._error(cid, command, MSG_NO_BACK if command == 'back' else MSG_LENS_BUSY, cmd_id)

    def _cmd_move_to(self, cid, msg):
        target = int(round(_num(msg.get('target'), 'target')))
        self._page_move(cid, 'move_to', _cmd_id(msg), lambda: self.lens.move_to(target))

    def _cmd_nudge(self, cid, msg):
        steps = _num(msg.get('steps'), 'steps')
        if steps != int(steps):
            raise _Invalid('steps')
        self._page_move(cid, 'nudge', _cmd_id(msg), lambda: self.lens.nudge(int(steps)))

    def _cmd_back(self, cid, msg):
        self._page_move(cid, 'back', _cmd_id(msg), lambda: self.lens.back())

    def _cmd_stop(self, cid, msg):
        with self._lock:
            self._af_auto = None
        if self.lens is None:
            self._error(cid, 'stop', MSG_NO_MOTOR)
            return
        self.lens.stop()
        if self._af_running():
            self._af_end(MSG_AF_STOPPED, back=False)

    def _cmd_clear_graph(self, cid, msg):
        with self._lock:
            self._points.clear()
            self._fit = None
        self.link.broadcast_json(self._graph_msg())

    def _cmd_autofocus(self, cid, msg):
        cmd_id = _cmd_id(msg)
        if not self._lens_ready(cid, 'autofocus', cmd_id):
            return
        with self._lock:
            unpicked = not self._stars
            was_preview = self._plan == PLAN_PREVIEW
            if unpicked:
                self._plan = PLAN_AUTOFOCUS  # a tune or pick under way runs on into autofocus
            picking = self._pick_press is not None
            searching = self._search_on
        if unpicked:
            # from a preview: pick the stars first, and autofocus follows the pick
            if was_preview:
                self._send_state()
            if not picking and not searching:
                self._begin_pick()
            return  # the page sends this press without a cmd_id: the pick's progress answers it
        refused = self._start_autofocus(cmd_id)
        if refused is not None:
            self._error(cid, 'autofocus', refused, cmd_id)

    def _auto_autofocus(self) -> None:
        """On the owning thread: start the autofocus a finished pick queued, once its stars are measured."""
        with self._lock:
            queued = self._af_auto
            if queued is None:
                return
            if queued != self._stars_gen or not self._stars:
                self._af_auto = None  # those stars are gone
                return
        if self.lens is None or self._af_running() or self.lens.state.moving or self._measure != 'stars':
            return  # not yet: the next pass looks again
        with self._lock:
            self._af_auto = None
        refused = self._start_autofocus(None)
        if refused is not None:
            logger.info('Focus: autofocus after the pick did not start: %s', refused)

    def _start_autofocus(self, cmd_id) -> Optional[str]:
        """Start an autofocus run; the lens is ready. Returns why not, or None."""
        with self._lock:
            picking = self._pick_press is not None
            searching = self._search_on
            picked = bool(self._stars)
            self._af_auto = None
        if picking:
            return MSG_PICK_BUSY
        if searching:
            return MSG_SEARCH_BUSY
        if not picked or self._measure != 'stars':
            return MSG_AF_NEEDS_STARS
        st = self.lens.state
        af = Autofocus(here=st.position, reachable=self.lens.reachable(), limit=st.limit, exposure=self.exposure,
                       speed=st.speed)
        if not self.lens.move_to(af.start):
            return MSG_LENS_BUSY
        with self._lock:
            self._points.clear()  # the graph shows this run's sweep only
            self._fit = None
        self.link.broadcast_json(self._graph_msg())
        self.lens.set_previous(af.here)
        self._af = af
        self._af_gen += 1
        self._af_cmd = cmd_id
        self._af_seen = None
        self._af_scan_end = None
        with self._lock:
            if cmd_id is not None:
                self.ledger.begin(cmd_id)
        logger.info('Focus: autofocus from %d, scan %d..%d at %.1f steps/s', af.here, af.start, af.end, af.max_rate)
        self.link.broadcast_json(self._af_progress())
        return None

    def _service_lens(self) -> None:
        """On the owning thread: send the lens's news, settle a page move, and step a running autofocus."""
        if self.lens is None:
            return
        latest = None
        for latest in _drain_items(self._lens_events):
            pass
        if latest is not None:
            self.link.broadcast_json(self._lens_msg(latest))
            with self._lock:
                cmd_id = self._lens_cmd
                settled = cmd_id is not None and not latest.moving and not self.lens.state.moving
                if settled:
                    self._lens_cmd = None
                    self.ledger.done(cmd_id, Lens.SETTLE_S)
        if self._cancel is not None:
            self._step_cancel()
            return
        self._step_af()

    def _step_af(self) -> None:
        af = self._af
        if af is None or af.done or af.stage == 'fit':
            return
        st = self.lens.state
        if st.moving:
            return
        if st.error:
            self._af_end(st.error, back=False)  # a failed motor is not asked to move again
            return
        if af.stage == 'start':
            if st.position != af.start:
                self._af_end(MSG_AF_SHORT, back=True)
                return
            af.begin_scan()
            with self._lock:
                self._af_feed = (self._af_gen, self._epoch())
            if not self._af_move(af.end, scan=True, max_rate=af.max_rate):
                return
        elif af.stage == 'scan':
            if self._af_scan_end is None:
                if st.position != af.end:
                    self._af_end(MSG_AF_SHORT, back=True)
                    return
                now = self._epoch()
                self._af_scan_end = (now, now + 2.0 * self.exposure + AF_TAIL_S)
            ended, deadline = self._af_scan_end
            if (self._af_seen is None or self._af_seen <= ended) and self._epoch() < deadline:
                return  # the scan's last frames are still on their way
            with self._lock:
                self._af_feed = None
            message = af.begin_fit()
            if message is not None:
                self._af_end(message, back=True)
                return
            gen = self._af_gen
            threading.Thread(target=self._fit_job, args=(gen, af.samples(), (af.start, af.end),
                                                         self.lens.reachable()),
                             name='focus-fit', daemon=True).start()
        elif af.stage == 'park':
            if st.position != af.park_target():
                self._af_end(MSG_AF_SHORT, back=False)
                return
            self._af_end(None, back=False)
            return
        self.link.broadcast_json(self._af_progress())

    def _af_move(self, target, **kw) -> bool:
        if self.lens.move_to(target, **kw):
            self.lens.set_previous(self._af.here)  # Back returns to where autofocus began
            return True
        self._af_end(MSG_LENS_BUSY, back=False)
        return False

    def _fit_job(self, gen, samples, span, limit):
        """On the focus-fit thread: the fit takes seconds on a Pi, so it stays off the owning thread."""
        try:
            fit = fit_curve(samples, span=span, limit=limit)
        except Exception:
            logger.exception('Focus: the autofocus fit failed')
            fit = None
        self._post(('af_fit', gen, fit))

    def _af_end(self, message, back: bool) -> None:
        """Finish the autofocus: parked (message None), failed, or stopped. back: return the lens to its start."""
        af = self._af
        af.finish(message)
        with self._lock:
            self._af_feed = None
            if self._af_cmd is not None:
                self.ledger.done(self._af_cmd, Lens.SETTLE_S)
        if back and self.lens.move_to(af.here):
            self.lens.set_previous(af.here)
        if message is None:
            logger.info('Focus: autofocus parked at %d (best focus %.1f)', self.lens.state.position, af.fit.c)
        else:
            logger.info('Focus: autofocus ended: %s', message)
        self.link.broadcast_json(self._af_progress())

    # -- messages --------------------------------------------------------------------------------------------------

    def _controls(self, cid) -> bool:
        hello = self.link.client_hello(cid)
        return bool(hello) and hello.get('controls') is True

    def _error(self, cid, command, message, cmd_id=None):
        """cmd_id: the refused command's id, so the page stops waiting for that one command to show."""
        self.link.send_json(cid, {'kind': 'error', 'message': message,
                                  'command': command if isinstance(command, str) else None,
                                  'cmd_id': cmd_id})

    def _send_state(self, cid=None):
        with self._lock:
            pages = len(self._pages)
            warning = self.rules.idle_warning()
        targets = [cid] if cid is not None else self.link.clients()
        for target in targets:
            self.link.send_json(target, {
                'kind': 'state',
                'session': 'active' if self._active else 'idle',
                'controls': self._controls(target),
                'pages': pages,
                'idle_warning': None if warning is None else int(math.ceil(warning)),
                'rig': _rig_dict(self.rig),
                'motor': dict(self.motor),
                'plan': self._plan,
            })

    def _lens_msg(self, st) -> dict:
        msg = dataclasses.asdict(st)
        with self._lock:
            fit = self._fit
            cmd_id = self._lens_cmd
        msg.update(kind='lens', cmd_id=cmd_id, reachable=list(self.lens.reachable()),
                   **step_sizes(st.steps_per_lens_turn, fit))
        return msg

    def _graph_msg(self) -> dict:
        with self._lock:
            return {'kind': 'graph', 'measure': self._measure, 'points': [list(p) for p in self._points],
                    'fit': dict(self._fit) if self._fit is not None else None}

    def _af_progress(self) -> dict:
        af = self._af
        st = self.lens.state
        return {'kind': 'progress', 'what': 'autofocus', 'stage': af.stage, 'stages': list(STAGES),
                'message': af.words, 'done': af.done, 'estimate_s': af.estimate_s(st.position, st.backlash),
                'columns': af.columns()}

    def _mode_msg(self):
        return {
            'kind': 'mode',
            'picture': self.rig.picture if self.rig is not None else None,
            'reason': self.rig.reason if self.rig is not None else None,
            'exposure': self.exposure,
            'gain': self.gain,
            'roi': list(self.roi) if self.roi is not None else None,
            **self.limits,
        }

    def _stretch_msg(self):
        with self._lock:
            levels = self._stretch_levels
            return {'kind': 'stretch', 'mode': self._stretch_mode,
                    'black': levels[0] if levels else None, 'white': levels[1] if levels else None}

    def _star_state(self, s, saturation=True) -> str:
        if s['choice'] == 'pin':
            return 'pinned'
        if s['choice'] == 'drop':
            return 'dropped'
        if saturation and s['saturated']:
            return 'saturated'
        return grade(s['snr1'], self._min_snr)

    def _stars_msg(self):
        with self._lock:
            stars = [{'id': s['id'], 'x': s['x'], 'y': s['y'], 'snr1': s['snr1'], 'state': self._star_state(s)}
                     for s in self._stars]
            return {'kind': 'stars', 'stars': stars, 'min_snr': self._min_snr}

    def _clear_stars_locked(self):
        self._stars = []
        self._stars_gen += 1
        self._pick_gen += 1
        self._pick_press = None

    # -- worker requests (applied on the owning thread) ------------------------------------------------------------

    def _source_call(self, what, fn, *args) -> bool:
        """Call the picture source; on an error, log it and end the session as failed."""
        try:
            fn(*args)
            return True
        except Exception:
            logger.exception('Focus: the picture source failed to %s', what)
            self.end('failed')
            return False

    def _post(self, request):
        self._requests.put(request)

    def _apply(self, request):
        what = request[0]
        if what == 'end':
            self.end(request[1])
        elif what == 'stars':
            _, gen, found = request
            with self._lock:
                if gen != self._pick_gen:
                    return
                self._stars = [{'id': i, 'x': x, 'y': y, 'snr1': snr1, 'saturated': sat, 'choice': 'keep'}
                               for i, (x, y, snr1, sat) in enumerate(found)]
                self._stars_gen += 1
                self._pick_press = None
            self.link.broadcast_json(self._stars_msg())
            self.link.broadcast_json({'kind': 'progress', 'what': 'pick', 'message': MSG_PICKED.format(len(found)),
                                      'done': True, 'frame': PICK_FRAMES, 'of': PICK_FRAMES,
                                      'candidates': len(found)})
            with self._lock:
                if found and self.lens is not None and self._plan == PLAN_AUTOFOCUS:
                    self._af_auto = self._stars_gen  # starts once the worker measures these stars
        elif what == 'preview':
            _, cid, reply = request
            if reply is None:
                self._error(cid, 'preview', MSG_PREVIEW_FAILED)
            else:
                self.link.send_json(cid, reply)
        elif what == 'pick_failed':
            _, gen, message = request
            with self._lock:
                if gen != self._pick_gen:
                    return
                self._pick_press = None
            self.link.broadcast_json({'kind': 'progress', 'what': 'pick', 'message': message, 'done': True,
                                      'frame': PICK_FRAMES, 'of': PICK_FRAMES, 'candidates': 0})
        elif what == 'off_glare':
            _, old, new = request
            if self.roi != tuple(old):
                return  # a page moved the region meanwhile: its choice wins
            logger.info('Focus: a clipped light source in region %s; moving to %s', list(old), list(new))
            self._cmd_set_region(None, {'roi': list(new)})
            if self.roi == tuple(new):
                self.link.broadcast_json({'kind': 'progress', 'what': 'region', 'message': MSG_OFF_GLARE,
                                          'done': True})
        elif what == 'stretch_levels':
            _, gen, levels = request
            with self._lock:
                if gen != self._stretch_gen or self._stretch_mode != 'auto':
                    return  # Manual or Off since, or a newer Re-level is on its way
                self._stretch_levels = levels
            self.link.broadcast_json(self._stretch_msg())
        elif what == 'af_frame':
            _, gen, t_end, x, rows = request
            af = self._af
            if gen != self._af_gen or af is None or af.stage != 'scan':
                return
            self._af_seen = t_end if self._af_seen is None else max(self._af_seen, t_end)
            if x is not None and rows:
                af.add_frame(x, rows)
        elif what == 'af_fit':
            _, gen, fit = request
            af = self._af
            if gen != self._af_gen or af is None or af.stage != 'fit':
                return  # stopped meanwhile
            body = _fit_dict(fit)
            with self._lock:
                self._fit = body
            if body is not None:
                self.link.broadcast_json(dict(body, kind='fit'))
            else:
                self.link.broadcast_json(self._graph_msg())  # no curve: the graph says fit null
            if self.lens is not None:
                self.link.broadcast_json(self._lens_msg(self.lens.state))  # the nudge sizes follow the band
            message = af.begin_park(fit)
            if message is not None:
                self._af_end(message, back=True)
                return
            if self._af_move(af.park_target()):
                self.link.broadcast_json(self._af_progress())
        elif what == 'graph':
            self.link.broadcast_json(self._graph_msg())
        elif what == 'search':
            _, gen, step = request
            with self._lock:
                if gen != self._search_gen or not self._search_on:
                    return  # stopped by the sliders, or a newer search is on its way
            if step.done:
                self._settled(step)
            landed = self._go(step)
            if landed is not None and landed.done and landed.found and self._active and not self._af_running() \
                    and (self._plan == PLAN_AUTOFOCUS or self.lens is None):
                # the next step follows on its own: stars to measure. A preview with a motor stops here, as Autofocus
                # picks them when pressed; a hand rig has no Autofocus, so its preview picks them now
                self._begin_pick()

    # -- the worker ------------------------------------------------------------------------------------------------

    def _run(self):
        failures = 0
        frames = self.source.frames
        while not self._stop.is_set():
            try:
                frame = frames.get(timeout=WORKER_POLL_S)
            except queue.Empty:
                continue
            count = 1
            while True:  # behind: measure only the newest waiting frame
                try:
                    frame = frames.get_nowait()
                except queue.Empty:
                    break
                count += 1
            self._frame_no += count
            if self._stop.is_set():
                return
            try:
                self._process(frame, self._frame_no)
                failures = 0
            except Exception:
                logger.exception('Focus: frame %d failed', self._frame_no)
                failures += 1
                if failures >= MAX_FRAME_FAILURES:
                    self._post(('end', 'failed'))
                    return

    def _snapshot(self, exposure_start):
        with self._lock:
            return {
                # the state without the pick's saturation mark: each frame checks clipping for itself
                'stars': [(s['id'], s['x'], s['y'], self._star_state(s, saturation=False)) for s in self._stars],
                'stars_gen': self._stars_gen,
                'region_gen': self._region_gen,
                'region_since': self._region_since,
                'pick_gen': self._pick_gen,
                'pick_press': self._pick_press,
                'search_on': self._search_on,
                'search_gen': self._search_gen,
                'search': self._search,
                'search_since': self._search_since,
                'stretch_mode': self._stretch_mode,
                'stretch_levels': self._stretch_levels,
                'stretch_gen': self._stretch_gen,
                'cmd_id': self.ledger.effective_before(exposure_start),
                'af_feed': self._af_feed,
            }

    def _process(self, frame, n):
        exposure_start = frame.t_end - frame.exposure
        capture_time = frame.t_end - frame.exposure / 2.0
        snap = self._snapshot(exposure_start)
        if snap['region_since'] is not None and exposure_start < snap['region_since']:
            return  # taken before the region moved
        bayer = normalise_bayer(frame.bayer)
        full_scale = float(frame.full_scale)
        raw = frame.raw
        self._last_format = (bayer, full_scale)

        # a new region, shape or camera setting: find hot pixels again and show the next frame linear
        key = (raw.shape, snap['region_gen'], frame.exposure, frame.gain)
        if key != self._frame_key:
            self._frame_key = key
            self._hot = None
            self._stretch = None
            # while a search runs every point is a new key: level at once, or the picture stays dark throughout
            self._stretch_phase = 'pending' if snap['search_on'] else 'linear'

        step = 2 if bayer else 1
        if self._hot is None:
            self._hot = find_hot_pixels(raw, step)
        fixed = fix_hot_pixels(raw, self._hot, step)
        gray = to_gray(fixed, bayer)
        clip = SATURATION_FRACTION * full_scale
        sigma = noise_sigma(gray)
        level = brightness(gray, full_scale)
        height, width = gray.shape[:2]

        # -- measure -------------------------------------------------------------------------------------------------
        if snap['stars_gen'] != self._seen_stars_gen:
            self._seen_stars_gen = snap['stars_gen']
            self._tracker = Tracker([Candidate(x, y, 0.0, 0) for _, x, y, _ in snap['stars']]) \
                if snap['stars'] else None

        picked = bool(snap['stars'])
        count = None
        rings = []
        size = None
        used = 0
        star_sizes = []
        if picked:
            got = self._tracker.update(gray, sigma)
            positions = self._tracker.positions
            pinned = [sid for sid, _, _, state in snap['stars'] if state == 'pinned']
            use = set(pinned) if pinned else {sid for sid, _, _, state in snap['stars'] if state == 'kept'}
            sizes = []
            star_sizes = []
            clipped = False
            for i, (sid, _, _, state) in enumerate(snap['stars']):
                m = got.get(i)
                x, y = (m.x, m.y) if m is not None else positions[i]
                saturated = state != 'dropped' and _peak(fixed, x, y) >= clip
                rings.append({'id': sid, 'x': _f(x), 'y': _f(y), 'size': _f(m.size) if m else None,
                              'snr': _f(m.snr) if m else None, 'state': 'saturated' if saturated else state})
                if sid in use and saturated:
                    clipped = True
                elif m is not None and sid in use and math.isfinite(m.size):
                    sizes.append(m.size)
                    star_sizes.append((sid, float(m.size)))
            used = len(sizes)
            size = _f(statistics.median(sizes)) if sizes else None
            candidate = 'stars'
        else:
            count = len(pick(gray, clip=clip))
            candidate = 'stars' if count >= FOUND_STARS else ('contrast' if level == 'bright' else 'none')
        measure = self._switch_measure(candidate, immediate=picked)

        contrast = _f(contrast_score(gray)) if measure == 'contrast' else None
        if measure == 'stars':
            if not picked:
                message = (MSG_VISIBLE if self.lens is not None else MSG_VISIBLE_HAND).format(count)
            elif used == 0:
                message = MSG_SATURATED if clipped else MSG_LOST
            else:
                message = None
        elif measure == 'none':
            message = MSG_OVER if level == 'over' else MSG_NO_STARS
        else:
            message = None

        # -- where the lens was, and the graph's points ---------------------------------------------
        x, points = None, []
        if self.lens is not None:
            still = self.lens.still_between(exposure_start, frame.t_end)
            if still or self.lens.inside_move(exposure_start, frame.t_end):
                x = self.lens.position_at(capture_time)
            if x is not None:
                x = float(x)
            feed = snap['af_feed']
            if feed is not None and exposure_start >= feed[1]:
                # the graph holds the autofocus sweep's samples only, never live frames between sweeps
                if x is not None and measure == 'stars':
                    points = [[x, sid, sz] for sid, sz in star_sizes]
                if points:
                    with self._lock:
                        self._points.extend(points)
                self._post(('af_frame', feed[0], frame.t_end, x if measure == 'stars' else None,
                            [(sid, sz) for _, sid, sz in points]))

        # -- picking and the exposure search ---------------------------------------------------------------------------
        moving = False
        if self._glare_check:
            self._glare_check = False
            roi = self.roi
            new = off_glare(gray, clip, roi, self._sensor) if roi is not None else None
            if new is not None:
                self._post(('off_glare', roi, new))
                moving = True  # the search waits for the new region's frames
        self._step_pick(snap, frame, gray, fixed, clip, sigma, exposure_start)
        if not moving:
            self._step_search(snap, frame, gray, fixed, clip, sigma, count, level, exposure_start)

        # -- preview -------------------------------------------------------------------------------------------------
        img = preview(gray, self._display_stretch(snap, gray, clip, full_scale))  # a new uint8 image: the clock never touches what was measured
        draw_clock(img, capture_time, n, self._clock_format)
        self.link.broadcast_frame(pack_frame(encode_jpeg(img), n, capture_time, frame.exposure, frame.gain,
                                             snap['cmd_id']))
        self.link.broadcast_json({
            'kind': 'reading',
            'frame': n,
            'cmd_id': snap['cmd_id'],
            'capture_time': capture_time,
            'exposure': float(frame.exposure),
            'gain': float(frame.gain),
            'width': int(width),
            'height': int(height),
            'measure': measure,
            'stars_visible': count,
            'size': size,
            'stars_used': used,
            'contrast': contrast,
            'rings': rings,
            'message': message,
            'x': x,
            'points': points,
        })

    def _display_stretch(self, snap, gray, clip, full_scale) -> Stretch:
        """The levels for this frame's picture. Only the picture: what was measured never sees them.

        Off: linear. Manual: the page's levels. Auto: the first frame after a new region or camera setting is
        linear, the next one sets the levels (outside the glare) and they stay; Re-level sets them from the next
        frame."""
        mode = snap['stretch_mode']
        if mode == 'off':
            return Stretch(0.0, full_scale, 1.0)
        if mode == 'manual':
            black, white = snap['stretch_levels']
            return Stretch(black * full_scale, white * full_scale)
        if snap['stretch_gen'] != self._seen_stretch_gen:
            self._seen_stretch_gen = snap['stretch_gen']
            self._stretch_phase = 'pending'
        if self._stretch_phase == 'linear':
            self._stretch_phase = 'pending'
            return Stretch(0.0, full_scale, 1.0)
        if self._stretch_phase == 'pending':
            self._stretch = Stretch.from_frame(gray, clip)
            self._stretch_phase = 'fixed'
            self._post(('stretch_levels', snap['stretch_gen'],
                        (self._stretch.black / full_scale, self._stretch.white / full_scale)))
        return self._stretch

    def _switch_measure(self, candidate, immediate):
        if self._measure is None or immediate:
            changed = candidate != self._measure
            self._measure = candidate
            self._pending_measure = (None, 0)
        elif candidate == self._measure:
            self._pending_measure = (None, 0)
            changed = False
        else:
            want, run = self._pending_measure
            run = run + 1 if want == candidate else 1
            self._pending_measure = (candidate, run)
            changed = run >= MEASURE_SWITCH_FRAMES
            if changed:
                self._measure = candidate
                self._pending_measure = (None, 0)
        if changed:
            with self._lock:
                self._points.clear()
                self._fit = None
            self.link.broadcast_json({'kind': 'measure', 'measure': self._measure})
            self._post(('graph',))
        return self._measure

    def _step_pick(self, snap, frame, gray, fixed, clip, sigma, exposure_start):
        if snap['pick_gen'] != self._seen_pick_gen:
            self._seen_pick_gen = snap['pick_gen']
            self._pick = _Pick(snap['pick_gen'], snap['pick_press']) if snap['pick_press'] is not None else None
        p = self._pick
        if p is None:
            return

        if p.cands is None:
            if exposure_start < p.press:
                return
            g = gray.astype(np.float64)
            p.stack = g if p.stack is None else p.stack + g
            p.frames.append((gray, fixed, clip))
            k = len(p.frames)
            found = pick(p.stack / k, clip=clip)
            self.link.broadcast_json({'kind': 'progress', 'what': 'pick',
                                      'message': MSG_PICKING.format(k, PICK_FRAMES, len(found)),
                                      'done': False, 'frame': k, 'of': PICK_FRAMES, 'candidates': len(found)})
            if k < PICK_FRAMES:
                return
            p.cands = found  # every star, brightest first
            p.stack = None
            if not p.cands:
                self._post(('pick_failed', p.gen, MSG_PICK_NONE))
                self._pick = None
                return
            p.need = max(int(math.ceil(GRADE_SECONDS / max(frame.exposure, 1e-3) - 1e-9)), GRADE_MIN_FRAMES)
            p.snrs = [[] for _ in p.cands]
            p.peaks = [[] for _ in p.cands]
            stacked, p.frames = p.frames, []
            for g, f, c in stacked:
                self._grade_frame(p, g, f, c, noise_sigma(g))
        else:
            self._grade_frame(p, gray, fixed, clip, sigma)

        if len(p.snrs[0]) >= p.need:
            found = [(float(c.x), float(c.y), float(statistics.median(s)), bool(statistics.median(k) >= 1.0))
                     for c, s, k in zip(p.cands, p.snrs, p.peaks)]
            self._post(('stars', p.gen, found))
            self._pick = None

    def _step_search(self, snap, frame, gray, fixed, clip, sigma, count, level, exposure_start):
        """One search point per frame: a frame taken at the point's exposure and gain, begun after the camera
        moved there. The tune counts the stars a pick would keep; the stills search, the pick's candidates."""
        if snap['search_gen'] != self._seen_search_gen:
            self._seen_search_gen = snap['search_gen']
            self._searcher = snap['search']
            self._search_done = False
        s = self._searcher
        # picked stars do not stop it: a tune pressed after a pick works like moving the sliders, and the stars are
        # followed by position whatever the exposure
        if s is None or not snap['search_on'] or self._search_done or self._pick is not None:
            return
        since = snap['search_since']
        if since is not None and exposure_start < since:
            return
        if not math.isclose(frame.exposure, s.exposure):
            return
        if s.gain is not None and self._gain_settable and not math.isclose(frame.gain, s.gain):
            return
        if s.kind == 'tune':
            count = count_stars(gray, fixed, clip, sigma)
        elif count is None:  # stars are picked, so the reading did not count candidates
            count = len(pick(gray, clip=clip))
        step = s.step(count, level, frame.t_end)
        self._search_done = step.done
        self._post(('search', snap['search_gen'], step))

    @staticmethod
    def _grade_frame(p, gray, fixed, clip, sigma):
        for c, snrs, peaks in zip(p.cands, p.snrs, p.peaks):
            m = measure_star(gray, c.x, c.y, sigma)
            snrs.append(max(float(m.snr), 0.0) if m is not None and math.isfinite(m.snr) else 0.0)
            peaks.append(_peak(fixed, c.x, c.y) / clip)  # >= 1 when clipped


def _fit_dict(fit) -> Optional[dict]:
    if fit is None:
        return None
    return {'c': fit.c, 'a': fit.a, 'k': fit.k, 'P': fit.P, 'band': [fit.band[0], fit.band[1]], 'n': fit.n,
            'stars': fit.stars, 'ok': fit.ok, 'message': fit.message}


def _drain_items(q):
    while True:
        try:
            yield q.get_nowait()
        except queue.Empty:
            return


def _drain(q):
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            return


class FocusService(object):
    """Commands while capture runs; owns at most one `FocusController` at a time."""

    def __init__(self, link, camera_info: CameraInfo, make_controller: Callable[[int], FocusController], *,
                 on_end: Optional[Callable[[FocusController], None]] = None):
        self.link = link
        self.camera_info = camera_info
        self._make = make_controller
        self._on_end = on_end
        self.controller = None
        self.idle_reason = None
        self.status_at = None     # when run_session_pass last wrote WATCHDOG and STATUS
        self.ended_unreported = False  # a session ended and capture has not written its status back yet
        self.status_before = None      # capture's STATUS when the running session began (None: not known)
        self._known = set()
        self._start_attempted = False

    @property
    def active(self) -> bool:
        return self.controller is not None and self.controller.active

    def poll(self) -> bool:
        """Drain the commands. True when this call started a session."""
        started = False
        self._reap()
        for cid, msg in self.link.poll_commands():
            if self.controller is not None:
                self.controller.handle(cid, msg)
                self._reap()
                continue
            kind = msg.get('kind') if isinstance(msg, dict) else None
            if kind == 'ping':
                self.link.send_json(cid, {'kind': 'pong', 't': time.time(), 'id': msg.get('id')})
            elif kind == 'hello':
                self._send_idle_state(cid)
            elif kind == 'start':
                hello = self.link.client_hello(cid)
                if not hello or hello.get('controls') is not True:
                    self._error(cid, kind, MSG_CONTROLS)
                    continue
                rig = self.camera_info.rig
                if rig is None or rig.picture is None:
                    # refused before the camera is touched: capture's exposure goes on
                    self._error(cid, kind, (rig.reason if rig is not None else '') or MSG_START_FAILED)
                    continue
                attempted, self._start_attempted = self._start_attempted, True  # making it aborts the exposure
                try:
                    controller = self._make(cid)
                except StartRefused as e:
                    self._start_attempted = attempted  # refused before the camera was touched
                    self._error(cid, kind, str(e) or MSG_START_FAILED)
                    continue
                except Exception as e:
                    # the type only; a message could carry what a client sent
                    logger.error('Focus: the session could not be set up (%s)', type(e).__name__)
                    self._error(cid, kind, MSG_START_FAILED)
                    continue
                self.controller = controller
                # no plan: a page older than the two start buttons; a preview never moves the lens unasked
                controller.begin(cid, msg.get('plan', PLAN_PREVIEW))
                started = controller.active  # False when the source failed to start
                self._reap()  # a failed start must not take the rest of this batch
            else:
                self._error(cid, kind, MSG_NO_SESSION)

        if self.controller is not None:
            self.controller.service()
            self._reap()
        else:
            now = set(self.link.clients())
            for cid in sorted(now - self._known):
                self._send_idle_state(cid)
            self._known = now
        return started

    def take_start_attempt(self) -> bool:
        """True once after a page with controls asked to start, whether or not the session started: capture
        leaves its wait either way, because making the controller may already have aborted the exposure."""
        attempted, self._start_attempted = self._start_attempted, False
        return attempted

    def stop(self, reason: str) -> None:
        """End the session, if one runs, and put the camera back (capture shutdown, reload, a failure)."""
        controller = self.controller
        if controller is not None:
            try:
                controller.end(reason)
            except Exception as e:
                logger.error('Focus: ending the session failed (%s)', type(e).__name__)
                controller.abandon(reason)
        self._reap()

    def _reap(self):
        controller = self.controller
        if controller is None or controller.active:
            return
        self.controller = None
        self.idle_reason = controller.end_reason
        self.ended_unreported = True
        if self._on_end is not None:
            try:
                self._on_end(controller)
            except Exception:
                logger.exception('Focus: restoring the camera after the session failed')
        self._known = set(self.link.clients())
        for cid in sorted(self._known):
            self._send_idle_state(cid)

    def _send_idle_state(self, cid):
        hello = self.link.client_hello(cid)
        self.link.send_json(cid, {
            'kind': 'state',
            'session': 'idle',
            'controls': bool(hello) and hello.get('controls') is True,
            'pages': len(self.link.clients()),
            'idle_warning': None,
            'rig': _rig_dict(self.camera_info.rig),
            'driver_has_video': bool(self.camera_info.driver_has_video),
            'idle_reason': self.idle_reason,
        })

    def _error(self, cid, command, message):
        self.link.send_json(cid, {'kind': 'error', 'message': message,
                                  'command': command if isinstance(command, str) else None})


# -- the capture loop --------------------------------------------------------------------------------------------------
# capture.py cannot be imported without PyIndi, so the session's part of its loop lives here.

def _safe_poll(service) -> None:
    """A focus failure ends the session; it never reaches the capture loop."""
    try:
        service.poll()
    except Exception as e:
        # the type only; a message could carry what a client sent
        logger.error('Focus: the session failed (%s)', type(e).__name__)
        try:
            service.stop('failed')
        except Exception as e2:
            logger.error('Focus: ending the failed session failed (%s)', type(e2).__name__)


def _read_status(worker) -> Optional[int]:
    """Capture's STATUS now, or None when there is none, it cannot be read, or it is a focus session's own."""
    try:
        status = int(worker._miscDb.getState('STATUS'))
    except Exception as e:  # NoResultFound before capture wrote one, or a database error
        logger.info('Focus: capture status not known (%s)', type(e).__name__)
        return None
    return None if status == constants.STATUS_FOCUSING else status


def run_session_pass(worker, *, sleep: Callable[[float], None] = time.sleep,
                     epoch: Callable[[], float] = time.time,
                     clock: Callable[[], float] = time.monotonic) -> bool:
    """One pass of capture's main loop for the focus session. True when capture must skip its normal schedule this
    pass: a session runs, or one just started or ended (the camera was aborted or reconfigured).

    worker: `focus` (a FocusService or None), `_shutdown`, `_miscDb`. While a session runs it writes WATCHDOG and
    STATUS_FOCUSING (at most every STATUS_EVERY_S, not 20 times a second) and sleeps SESSION_TURN_S. A shutdown, reload
    or interrupt ends the session as 'stopped'. When a session ends it writes back the STATUS that held before it
    (STATUS_PAUSED while capture is paused, say), or STATUS_RUNNING when that is not known.
    """
    service = getattr(worker, 'focus', None)
    if service is None:
        return False
    was_active = service.active
    _safe_poll(service)
    if service.active and worker._shutdown:
        service.stop('stopped')
    attempted = service.take_start_attempt()

    if service.active:
        now = clock()
        if service.status_at is None or now - service.status_at >= STATUS_EVERY_S:
            if service.status_at is None:  # the session's first pass: STATUS is still capture's own
                service.status_before = _read_status(worker)
            service.status_at = now
            worker._miscDb.setState('WATCHDOG', int(epoch()))
            worker._miscDb.setState('STATUS', constants.STATUS_FOCUSING)
        sleep(SESSION_TURN_S)
        return True

    service.status_at = None
    if service.ended_unreported:
        service.ended_unreported = False
        before, service.status_before = service.status_before, None
        if before is None:
            before = _read_status(worker)  # a session that ended before its first pass never wrote FOCUSING
        worker._miscDb.setState('STATUS', before if before is not None else constants.STATUS_RUNNING)
        return True
    return was_active or attempted


def focus_wait_turn(worker, *, sleep: Callable[[float], None] = time.sleep) -> bool:
    """One turn of capture's wait for an exposure: sleep SESSION_TURN_S, then read the link. True when a page asked
    to start a session, so capture leaves the wait at once instead of after the exposure."""
    sleep(SESSION_TURN_S)
    service = getattr(worker, 'focus', None)
    if service is None:
        return False
    _safe_poll(service)
    return service.take_start_attempt() or service.active


def focus_sleep(worker, seconds: float, *, sleep: Callable[[float], None] = time.sleep,
                clock: Callable[[], float] = time.monotonic) -> bool:
    """Capture's long sleeps (paused, daytime) in SESSION_TURN_S turns, so pages are answered meanwhile. Returns
    True, early, when a page asked to start a session."""
    if getattr(worker, 'focus', None) is None:
        sleep(seconds)
        return False
    end = clock() + seconds
    while clock() < end:
        if focus_wait_turn(worker, sleep=sleep):
            return True
    return False
