"""Lens mover: moves that always finish outward, a travel limit, Back, Stop, and a step log.

Steps are driver steps, counted from the session start (position 0, positive outward = `cw`). Nothing is
written to disk: a new session starts a new count.

Every move finishes travelling outward. A target below the current position, or any target after the last
travel was inward, is approached from target - backlash (phase 'backlash'), so the backlash is always taken up
in the outward direction before the lens stops.

The mover runs moves on its own thread so pictures keep flowing and Stop can be heard. The step log records
one (t, position) sample per completed step (per ~1 s piece for drivers that cannot stop part-way), plus one at
construction and one at the start of every leg. A *leg* is one direction of travel inside one `move_to`: the
'backlash' leg is inward, the 'move' or 'scan' leg is outward. `position_at`, `still_between` and `inside_move`
answer from that log, so a frame's timing can be matched to where the lens was.
"""

from __future__ import annotations

import bisect
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable
from typing import Optional


logger = logging.getLogger('indi_allsky')


LOG_CAP = 50000          # step-log samples kept
LOG_TRIM = 5000          # dropped at once when the log grows past LOG_CAP + LOG_TRIM
LEG_CAP = 2000           # legs kept
CHANGE_EVERY_S = 0.25    # on_change cadence while moving
PIECE_S = 1.0            # move length per call for a driver that cannot stop part-way

MSG_DRIVER = 'The focus motor failed: {0}'


@dataclass(frozen=True)
class LensState:
    position: int            # steps from the session start; positive outward
    target: Optional[int]    # the move's final target, or None at rest
    moving: bool
    phase: str               # 'rest' | 'move' | 'backlash' (the extra inward leg) | 'scan'
    previous: Optional[int]  # where Back goes (the last resting position before the last move), or None
    limit: int               # travel limit, steps each side
    backlash: int            # take-up, steps
    steps_per_turn: int      # motor steps per motor turn
    steps_per_lens_turn: float  # motor steps per turn of the lens ring, through the external gears
    speed: float             # steps/s, the driver's stated speed
    error: Optional[str]     # the last move's failure in plain words, or None


class _Leg:
    """One direction of travel inside one move."""

    __slots__ = ('move_id', 'direction', 'phase', 'start', 'first', 'last', 'open')

    def __init__(self, move_id: int, direction: int, phase: str, start: float):
        self.move_id = move_id
        self.direction = direction
        self.phase = phase
        self.start = start                  # leg start (before the first step)
        self.first: Optional[float] = None  # time of the first completed step
        self.last: Optional[float] = None   # time of the latest completed step
        self.open = True


class Lens:
    SETTLE_S = 0.5           # a fixed allowance, not measured

    def __init__(self, driver, *, limit: int, backlash: int, steps_per_lens_turn: Optional[float] = None,
                 clock=time.time, on_change: Callable[[LensState], None] = lambda s: None,
                 sleep: Optional[Callable[[float], None]] = None):
        """`sleep` paces `max_rate` moves; None waits on the stop signal (so Stop cuts a pause short).
        `steps_per_lens_turn` only rides along in the state so the page can show lens degrees; None means
        the motor turns the lens directly. Tests pass a fake `clock` and `sleep` together."""
        if limit < 1 or backlash < 0 or backlash >= 2 * limit:
            raise ValueError('bad travel limit {0!r} or backlash {1!r}'.format(limit, backlash))

        self._driver = driver
        self._clock = clock
        self._on_change = on_change
        self._sleep = sleep

        self._limit = int(limit)
        self._backlash = int(backlash)
        self._steps_per_turn = int(driver.STEPS_PER_TURN)
        self._steps_per_lens_turn = float(steps_per_lens_turn or self._steps_per_turn)
        self._speed = float(driver.STEPS_PER_SECOND)
        self._can_stop = bool(driver.CAN_STOP)

        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._wake = threading.Event()
        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._closed = False

        self._position = 0
        self._target: Optional[int] = None
        self._moving = False
        self._phase = 'rest'
        self._previous: Optional[int] = None
        self._error: Optional[str] = None
        self._last_dir = 0          # +1 outward, -1 inward, 0 unknown (session start)

        self._plan: list[tuple[int, str]] = []   # (leg target, phase), set by move_to for the worker
        self._max_rate: Optional[float] = None
        self._move_id = 0
        self._move_t0 = 0.0

        self._log_t: list[float] = []
        self._log_x: list[int] = []
        self._legs: deque[_Leg] = deque(maxlen=LEG_CAP)

        self._log(self._clock(), 0)

    # --- reading --------------------------------------------------------------------------------

    @property
    def state(self) -> LensState:
        with self._lock:
            return self._snapshot()

    def _snapshot(self) -> LensState:
        return LensState(position=self._position, target=self._target, moving=self._moving, phase=self._phase,
                         previous=self._previous, limit=self._limit, backlash=self._backlash,
                         steps_per_turn=self._steps_per_turn, steps_per_lens_turn=self._steps_per_lens_turn,
                         speed=self._speed, error=self._error)

    def reachable(self) -> tuple[int, int]:
        """What a target may be: the inward limit less the take-up, out to the outward limit."""
        return (-self._limit + self._backlash, self._limit)

    def position_at(self, t: float) -> Optional[float]:
        """Lens position at time t, interpolated between logged samples; None before the first sample."""
        with self._lock:
            ts, xs = self._log_t, self._log_x
            if not ts or t < ts[0]:
                return None
            i = bisect.bisect_right(ts, t)
            if i >= len(ts):
                return float(xs[-1])
            t0, t1 = ts[i - 1], ts[i]
            x0, x1 = xs[i - 1], xs[i]
            if t1 <= t0:
                return float(x1)
            return x0 + (x1 - x0) * (t - t0) / (t1 - t0)

    def still_between(self, t0: float, t1: float) -> bool:
        """True when the lens was at rest, and settled, through [t0, t1]: no leg's travel (from its start to its
        last step; to now if still running) overlaps [t0 - SETTLE_S, t1]. A running move counts from its start."""
        lo = t0 - self.SETTLE_S
        with self._lock:
            if self._moving and t1 >= self._move_t0:
                return False         # a move has started, even if its first leg has not been logged yet
            for leg in self._legs:
                end = float('inf') if leg.open else (leg.last if leg.last is not None else leg.start)
                if leg.start <= t1 and end >= lo:
                    return False
            return True

    def inside_move(self, t0: float, t1: float) -> bool:
        """True when [t0, t1] lies wholly inside one outward leg of one move: at or after its first logged
        step, at or before its last (up to now while the leg is still running)."""
        with self._lock:
            now = self._clock()
            for leg in self._legs:
                if leg.direction <= 0 or leg.first is None:
                    continue
                end = max(now, leg.last) if leg.open else leg.last
                if leg.first <= t0 and t1 <= end:
                    return True
            return False

    def wait(self, timeout: Optional[float] = None) -> bool:
        """True when no move is running (waits up to `timeout` real seconds)."""
        with self._idle:
            return self._idle.wait_for(lambda: not self._moving, timeout)

    # --- moving ---------------------------------------------------------------------------------

    def move_to(self, target: int, *, scan: bool = False, max_rate: Optional[float] = None) -> bool:
        """Start a move on the mover's thread; False (nothing moves) if one is running or the mover is closed."""
        lo, hi = self.reachable()
        target = max(lo, min(hi, int(round(target))))
        with self._lock:
            if self._moving or self._closed:
                return False

            pos = self._position
            outward_phase = 'scan' if scan else 'move'
            plan: list[tuple[int, str]] = []
            # unknown (session start) counts as inward: the backlash may sit either way, so take it up
            if target < pos or (self._last_dir <= 0 and target - pos < self._backlash):
                plan.append((target - self._backlash, 'backlash'))
            if target != pos or plan:
                plan.append((target, outward_phase))

            if plan:
                self._plan = plan
                self._max_rate = max_rate if max_rate and max_rate > 0 else None
                self._previous = pos
                self._target = target
                self._moving = True
                self._phase = plan[0][1]
                self._error = None
                self._move_id += 1
                self._move_t0 = self._clock()
                self._stop_evt.clear()
                if self._thread is None:
                    self._thread = threading.Thread(target=self._run, name='focus-lens', daemon=True)
                    self._thread.start()
                self._wake.set()
                return True

            # Already there with the backlash taken up outward: nothing to do.
            snap = self._snapshot()
        self._emit(snap)
        return True

    def nudge(self, steps: int) -> bool:
        with self._lock:
            pos = self._position
        return self.move_to(pos + int(steps))

    def back(self) -> bool:
        with self._lock:
            prev = self._previous
        if prev is None:
            return False
        return self.move_to(prev)

    def set_previous(self, x: int) -> None:
        with self._lock:
            self._previous = int(x)
            snap = self._snapshot()
        self._emit(snap)

    def stop(self) -> None:
        """Ask the running move to stop. Returns at once; `wait()` for it to end."""
        self._stop_evt.set()

    def close(self) -> None:
        """Stop any move and end the mover's thread. Never deinits the driver (the session owns it)."""
        with self._lock:
            self._closed = True
            thread = self._thread
        self._stop_evt.set()
        self._wake.set()
        if thread is not None:
            thread.join()

    # --- the mover's thread ---------------------------------------------------------------------

    def _run(self) -> None:
        while True:
            self._wake.wait()
            with self._lock:
                self._wake.clear()
                if not self._moving:
                    if self._closed:
                        return
                    continue
                plan = list(self._plan)
                max_rate = self._max_rate
                move_id = self._move_id

            self._emit(self.state)   # move start
            try:
                self._do_move(move_id, plan, max_rate)
            except Exception as e:  # a driver failure ends the move; the thread lives on
                logger.exception('Focus motor move failed')
                with self._lock:
                    self._error = MSG_DRIVER.format(e)
            finally:
                with self._lock:
                    for leg in self._legs:
                        leg.open = False
                    self._moving = False
                    self._target = None
                    self._phase = 'rest'
                    snap = self._snapshot()
                    self._idle.notify_all()
            self._emit(snap)         # move end

            with self._lock:
                if self._closed:
                    return

    def _do_move(self, move_id: int, plan: list[tuple[int, str]], max_rate: Optional[float]) -> None:
        for i, (leg_target, phase) in enumerate(plan):
            if self._stop_evt.is_set():
                return
            with self._lock:
                start_pos = self._position
                changed = self._phase != phase
                self._phase = phase
                snap = self._snapshot()
            if i > 0 and changed:
                self._emit(snap)     # phase change
            delta = leg_target - start_pos
            if delta == 0:
                continue
            moved = self._do_leg(move_id, phase, start_pos, delta, max_rate)
            if moved != delta:
                return               # stopped (or the driver came up short): the move ends here

    def _do_leg(self, move_id: int, phase: str, start_pos: int, delta: int, max_rate: Optional[float]) -> int:
        direction = 1 if delta > 0 else -1
        now = self._clock()
        leg = _Leg(move_id, direction, phase, now)
        with self._lock:
            self._legs.append(leg)
            self._log(now, start_pos)   # the leg's start: keeps position_at exact through the rest before it

        counted = [0]                  # steps completed in this leg, from the should_stop calls
        last_emit = [now]

        def pace() -> None:
            if max_rate is None:
                return
            due = leg.start + abs(counted[0]) / max_rate
            dt = due - self._clock()
            if dt > 0:
                if self._sleep is not None:
                    self._sleep(dt)
                else:
                    self._stop_evt.wait(dt)

        def note(n: int) -> Optional[LensState]:
            """n more steps completed: update position, log a sample; a snapshot when on_change is due."""
            t = self._clock()
            with self._lock:
                counted[0] += direction * n
                self._position = start_pos + counted[0]
                self._log(t, self._position)
                if leg.first is None:
                    leg.first = self._log_t[-1]
                leg.last = self._log_t[-1]
                if n:
                    self._last_dir = direction
                if t - last_emit[0] >= CHANGE_EVERY_S:
                    last_emit[0] = t
                    return self._snapshot()
            return None

        def should_stop() -> bool:
            snap = note(1)
            if snap is not None:
                self._emit(snap)
            pace()
            return self._stop_evt.is_set()

        try:
            if self._can_stop:
                moved = int(self._driver.move_steps(delta, should_stop))
            else:
                rate = self._speed if max_rate is None else min(self._speed, max_rate)
                piece = max(1, int(round(rate * PIECE_S)))
                moved = 0
                while moved != delta and not self._stop_evt.is_set():
                    k = direction * min(piece, abs(delta - moved))
                    if moved:
                        with self._lock:   # the piece's start, so position_at holds through a pacing pause
                            self._log(self._clock(), start_pos + moved)
                    got = int(self._driver.move_steps(k, None))
                    moved += got
                    if got:
                        snap = note(abs(got))
                        self._emit(snap if snap is not None else self.state)
                    if got != k:
                        break
                    pace()
        finally:
            with self._lock:
                leg.open = False

        with self._lock:
            if moved != counted[0]:
                # The driver's own count wins; log the correction so position_at agrees.
                self._position = start_pos + moved
                self._log(self._clock(), self._position)
                if moved:
                    self._last_dir = 1 if moved > 0 else -1
        return moved

    # --- helpers --------------------------------------------------------------------------------

    def _log(self, t: float, x: int) -> None:
        """Append a sample (lock held). Times never go backwards, so bisect stays valid."""
        if self._log_t and t < self._log_t[-1]:
            t = self._log_t[-1]
        self._log_t.append(t)
        self._log_x.append(int(x))
        if len(self._log_t) > LOG_CAP + LOG_TRIM:
            cut = len(self._log_t) - LOG_CAP
            del self._log_t[:cut]
            del self._log_x[:cut]
            first = self._log_t[0]
            while self._legs and self._legs[0].start < first and not self._legs[0].open:
                self._legs.popleft()

    def _emit(self, snap: LensState) -> None:
        try:
            self._on_change(snap)
        except Exception:
            logger.exception('Lens on_change failed')
