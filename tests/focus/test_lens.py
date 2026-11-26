"""Lens mover: outward-finishing moves, travel limit, Back, Stop, and the step log."""

from __future__ import annotations

import threading

import pytest

from indi_allsky.focus.lens import Lens
from indi_allsky.focus.lens import LensState


T0 = 1000.0


class FakeClock:
    def __init__(self, t: float = T0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        self.t += dt


class FakeDriver:
    """The driver API the lens mover expects. Each step advances the fake clock by 1 / STEPS_PER_SECOND."""

    STEPS_PER_TURN = 512

    def __init__(self, clock: FakeClock, *, speed: float = 100.0, can_stop: bool = True, fail_at=None,
                 hook=None, gate: threading.Event = None):
        self.clock = clock
        self.STEPS_PER_SECOND = speed
        self.CAN_STOP = can_stop
        self.fail_at = fail_at      # raise before this step (1-based, counted over the driver's life)
        self.hook = hook            # hook(total_steps) after every step
        self.gate = gate            # the first step waits for it
        self.shaft = 0
        self.path = [0]             # shaft position after every step
        self.calls = []             # steps asked per call
        self.total = 0

    def move_steps(self, steps, should_stop=None):
        self.calls.append(steps)
        d = 1 if steps > 0 else -1
        n = 0
        for _ in range(abs(steps)):
            if self.gate is not None:
                assert self.gate.wait(5)
                self.gate = None
            if self.fail_at is not None and self.total + 1 == self.fail_at:
                raise OSError('coil driver not responding')
            self.clock.t += 1.0 / self.STEPS_PER_SECOND
            self.shaft += d
            self.path.append(self.shaft)
            self.total += 1
            n += 1
            if self.hook is not None:
                self.hook(self.total)
            if self.CAN_STOP and should_stop is not None and should_stop():
                break
        return d * n


def make(limit=200, backlash=20, **kw):
    clock = FakeClock()
    driver = FakeDriver(clock, **kw)
    changes = []
    lens = Lens(driver, limit=limit, backlash=backlash, clock=clock, on_change=changes.append, sleep=clock.sleep)
    return lens, driver, clock, changes


def go(lens, target, **kw):
    assert lens.move_to(target, **kw)
    assert lens.wait(5)
    return lens.state


def phases(changes):
    out = []
    for s in changes:
        if not out or out[-1] != s.phase:
            out.append(s.phase)
    return out


@pytest.fixture
def rig():
    lens, driver, clock, changes = make()
    yield lens, driver, clock, changes
    lens.close()


# --- outward finish ----------------------------------------------------------------------------

def test_inward_target_passes_by_the_backlash_then_comes_back_outward(rig):
    lens, driver, clock, changes = rig
    s = go(lens, -100)
    assert s.position == -100 and driver.shaft == -100
    assert min(driver.path) == -120
    assert driver.path[-1] > driver.path[-2]          # last step outward
    assert driver.calls == [-120, 20]
    assert phases(changes) == ['backlash', 'move', 'rest']
    assert s.moving is False and s.target is None and s.phase == 'rest'


def test_outward_target_after_outward_travel_goes_straight(rig):
    lens, driver, clock, changes = rig
    go(lens, 10)
    driver.calls.clear()
    changes.clear()
    s = go(lens, 15)
    assert s.position == 15
    assert driver.calls == [5]
    assert phases(changes) == ['move', 'rest']


def test_outward_target_after_inward_travel_takes_up_backlash_first(rig):
    lens, driver, clock, changes = rig
    # Stop during the backlash leg: the last travel was inward.
    driver.hook = lambda n: lens.stop() if n == 10 else None
    s = go(lens, -50)
    assert s.position == -10
    driver.hook = None
    driver.calls.clear()
    s = go(lens, -5)                                  # outward by less than the backlash
    assert driver.calls == [-15, 20]
    assert s.position == -5 and min(driver.path) == -25


def test_outward_target_further_than_the_backlash_after_inward_travel_is_one_leg(rig):
    lens, driver, clock, changes = rig
    driver.hook = lambda n: lens.stop() if n == 10 else None
    go(lens, -50)
    driver.hook = None
    driver.calls.clear()
    changes.clear()
    s = go(lens, 30)                                  # 40 outward >= backlash: the run itself takes it up
    assert driver.calls == [40]
    assert s.position == 30
    assert 'backlash' not in phases(changes)


def test_same_position_after_outward_travel_does_nothing(rig):
    lens, driver, clock, changes = rig
    go(lens, 40)
    driver.calls.clear()
    changes.clear()
    assert lens.move_to(40) is True
    assert lens.wait(1)
    assert driver.calls == []
    assert changes and changes[-1].phase == 'rest' and changes[-1].moving is False
    assert lens.state.previous == 0                   # a move that does nothing leaves Back alone


def test_same_position_after_inward_travel_reapproaches(rig):
    lens, driver, clock, changes = rig
    driver.hook = lambda n: lens.stop() if n == 10 else None
    go(lens, -50)
    driver.hook = None
    driver.calls.clear()
    s = go(lens, -10)
    assert driver.calls == [-20, 20]
    assert s.position == -10


def test_scan_phase_names_the_outward_leg(rig):
    lens, driver, clock, changes = rig
    go(lens, -30, scan=True)
    assert phases(changes) == ['backlash', 'scan', 'rest']


# --- limits, Back --------------------------------------------------------------------------------

def test_targets_are_clamped_to_reachable(rig):
    lens, driver, clock, changes = rig
    assert lens.reachable() == (-180, 200)
    s = go(lens, -1000)
    assert s.position == -180
    assert min(driver.path) == -200                   # the take-up never crosses the limit
    s = go(lens, 1000)
    assert s.position == 200 and max(driver.path) == 200


def test_state_carries_the_settings(rig):
    lens, driver, clock, changes = rig
    s = lens.state
    assert isinstance(s, LensState)
    assert (s.position, s.target, s.moving, s.phase, s.previous) == (0, None, False, 'rest', None)
    assert (s.limit, s.backlash, s.steps_per_turn, s.speed, s.error) == (200, 20, 512, 100.0, None)


def test_back_returns_to_the_last_resting_position(rig):
    lens, driver, clock, changes = rig
    assert lens.back() is False                       # nothing to go back to yet
    go(lens, 50)
    assert lens.state.previous == 0
    go(lens, 80)
    assert lens.state.previous == 50
    assert lens.back()
    assert lens.wait(5)
    s = lens.state
    assert s.position == 50 and s.previous == 80
    assert driver.path[-1] > driver.path[-2]          # Back finishes outward too


def test_set_previous_overrides_back(rig):
    lens, driver, clock, changes = rig
    go(lens, 50)
    lens.set_previous(-30)
    assert lens.state.previous == -30
    assert changes[-1].previous == -30
    assert lens.back()
    assert lens.wait(5)
    assert lens.state.position == -30


def test_nudge_is_relative(rig):
    lens, driver, clock, changes = rig
    go(lens, 50)
    assert lens.nudge(-7)
    assert lens.wait(5)
    assert lens.state.position == 43
    assert min(driver.path[-30:]) == 23               # outward finish applies


# --- Stop, refusals, failures ---------------------------------------------------------------------

def test_stop_mid_move_keeps_the_steps_actually_moved(rig):
    lens, driver, clock, changes = rig
    driver.hook = lambda n: lens.stop() if n == 30 else None
    s = go(lens, 100)
    assert s.position == 30 and driver.shaft == 30
    assert s.moving is False and s.phase == 'rest' and s.target is None
    assert s.previous == 0


def test_stop_during_the_backlash_leg_skips_the_outward_leg(rig):
    lens, driver, clock, changes = rig
    driver.hook = lambda n: lens.stop() if n == 5 else None
    s = go(lens, -50)
    assert s.position == -5
    assert driver.calls == [-70]


def test_a_second_move_is_refused_while_one_runs():
    gate = threading.Event()
    lens, driver, clock, changes = make(gate=gate)
    try:
        assert lens.move_to(50)
        assert lens.move_to(80) is False
        assert lens.nudge(5) is False
        assert lens.wait(0.05) is False
        gate.set()
        assert lens.wait(5)
        assert lens.state.position == 50
        assert driver.calls == [50]
    finally:
        gate.set()
        lens.close()


def test_a_driver_failure_ends_the_move_in_plain_words_and_the_next_move_works():
    lens, driver, clock, changes = make(fail_at=11)
    try:
        s = go(lens, 50)
        assert s.position == 10 and s.moving is False and s.phase == 'rest'
        assert s.error == 'The focus motor failed: coil driver not responding'
        assert changes[-1].error == s.error and changes[-1].moving is False
        driver.fail_at = None
        s = go(lens, 60)
        assert s.position == 60 and s.error is None
    finally:
        lens.close()


def test_on_change_failure_does_not_kill_the_mover():
    clock = FakeClock()
    driver = FakeDriver(clock)

    def boom(state):
        raise RuntimeError('callback broke')

    lens = Lens(driver, limit=200, backlash=20, clock=clock, on_change=boom, sleep=clock.sleep)
    try:
        assert go(lens, 10).position == 10
        assert go(lens, 20).position == 20
    finally:
        lens.close()


def test_close_stops_and_refuses_further_moves():
    gate = threading.Event()
    lens, driver, clock, changes = make(gate=gate)
    assert lens.move_to(100)
    gate.set()
    lens.close()
    assert lens.state.moving is False
    assert lens.move_to(10) is False


# --- drivers that cannot stop part-way -------------------------------------------------------------

def test_cannot_stop_driver_gets_one_second_pieces_and_a_sample_each():
    lens, driver, clock, changes = make(speed=14.0, can_stop=False)
    try:
        s = go(lens, 50)
        assert s.position == 50
        assert driver.calls == [14, 14, 14, 8]
        assert lens.position_at(T0 + 1.0) == pytest.approx(14)
        assert lens.position_at(T0 + 0.5) == pytest.approx(7)
    finally:
        lens.close()


def test_cannot_stop_driver_stops_between_pieces():
    lens, driver, clock, changes = make(speed=14.0, can_stop=False)
    try:
        driver.hook = lambda n: lens.stop() if n == 3 else None
        s = go(lens, 50)
        assert driver.calls == [14]
        assert s.position == 14
    finally:
        lens.close()


def test_cannot_stop_driver_pieces_shrink_to_the_max_rate():
    lens, driver, clock, changes = make(speed=14.0, can_stop=False)
    try:
        go(lens, 20, max_rate=5.0)
        assert driver.calls == [5, 5, 5, 5]
        assert clock.t - T0 == pytest.approx(4.0)     # paced to 5 steps/s
    finally:
        lens.close()


def test_a_frame_inside_one_piece_is_not_still():
    lens, driver, clock, changes = make(speed=14.0, can_stop=False)
    try:
        go(lens, 28)
        # No step sample falls inside (T0 + 0.2, T0 + 0.8), but the lens was moving.
        assert lens.still_between(T0 + 0.2, T0 + 0.8) is False
    finally:
        lens.close()


# --- the step log ---------------------------------------------------------------------------------

def test_position_at_is_none_before_the_session_and_exact_at_rest(rig):
    lens, driver, clock, changes = rig
    assert lens.position_at(T0 - 1) is None
    assert lens.position_at(T0) == 0
    clock.t += 100                                    # a long rest
    go(lens, 50)                                      # 100 steps/s: T0+100 .. T0+100.5
    assert lens.position_at(T0 + 50) == 0             # still at rest then, not halfway
    assert lens.position_at(T0 + 100) == 0
    assert lens.position_at(T0 + 100.25) == pytest.approx(25)
    assert lens.position_at(T0 + 100.255) == pytest.approx(25.5)
    assert lens.position_at(T0 + 500) == 50


def test_still_between_needs_the_settle_time(rig):
    lens, driver, clock, changes = rig
    clock.t += 10
    go(lens, 50)                                      # moving T0+10 .. T0+10.5
    assert lens.still_between(T0 + 1, T0 + 9) is True
    assert lens.still_between(T0 + 9, T0 + 10.2) is False
    assert lens.still_between(T0 + 10.6, T0 + 11) is False   # inside the 0.5 s settle
    assert lens.still_between(T0 + 11.0, T0 + 12) is True
    assert lens.still_between(T0 + 10.99, T0 + 12) is False


def test_still_between_is_false_while_a_move_runs():
    gate = threading.Event()
    lens, driver, clock, changes = make(gate=gate)
    try:
        assert lens.move_to(50)
        assert lens.still_between(T0 + 100, T0 + 200) is False
        gate.set()
        assert lens.wait(5)
    finally:
        gate.set()
        lens.close()


def test_inside_move_true_only_inside_one_outward_leg(rig):
    lens, driver, clock, changes = rig
    clock.t += 10
    go(lens, -40, scan=True)                          # backlash: T0+10 .. T0+10.6 (60 in), scan: .. T0+10.8
    assert lens.inside_move(T0 + 10.65, T0 + 10.75) is True
    assert lens.inside_move(T0 + 10.615, T0 + 10.795) is True  # first step .. last step
    assert lens.inside_move(T0 + 10.6, T0 + 10.7) is False    # before the scan leg's first step
    assert lens.inside_move(T0 + 10.2, T0 + 10.4) is False    # inside the backlash (inward) leg
    assert lens.inside_move(T0 + 10.7, T0 + 10.9) is False    # runs past the last step
    clock.t += 1
    go(lens, 0)                                       # T0+11.8 .. T0+12.2
    assert lens.inside_move(T0 + 10.7, T0 + 11.9) is False    # spans two moves
    assert lens.inside_move(T0 + 11.85, T0 + 12.1) is True
    assert lens.inside_move(T0 + 1, T0 + 2) is False


def test_inside_move_answers_while_the_leg_is_still_running(rig):
    lens, driver, clock, changes = rig
    seen = {}

    def ask(n):
        if n == 50:
            # Paced at 10 steps/s, the frame ending now is past the latest step sample.
            seen['mid'] = lens.inside_move(clock.t - 0.2, clock.t)
            seen['early'] = lens.inside_move(clock.t - 60, clock.t)

    go(lens, 30)
    driver.hook = ask
    go(lens, 130, scan=True, max_rate=10.0)
    assert seen == {'mid': True, 'early': False}


def test_paced_cannot_stop_driver_holds_position_through_the_pause():
    lens, driver, clock, changes = make(speed=14.0, can_stop=False)
    try:
        go(lens, 20, max_rate=5.0)                    # pieces of 5 steps, each 0.36 s, then a pause to 1 s
        assert lens.position_at(T0 + 0.7) == pytest.approx(5)
        assert lens.position_at(T0 + 1.0) == pytest.approx(5)
    finally:
        lens.close()


def test_max_rate_paces_the_motor(rig):
    lens, driver, clock, changes = rig
    go(lens, 20)
    assert clock.t - T0 == pytest.approx(0.2)
    start = clock.t
    go(lens, 40, max_rate=10.0)
    assert clock.t - start == pytest.approx(2.0)
    # Step n starts on the schedule start + (n - 1) / 10 and takes 0.01 s: step 10 at +0.91, step 11 at +1.01.
    assert lens.position_at(start + 1.0) == pytest.approx(30.9)


def test_on_change_at_start_while_moving_and_at_the_end(rig):
    lens, driver, clock, changes = rig
    go(lens, 150)                                     # 1.5 s at 100 steps/s
    assert changes[0].moving is True and changes[0].phase == 'move' and changes[0].target == 150
    moving = [s for s in changes if s.moving]
    assert len(moving) >= 6                           # start + about every 0.25 s
    assert changes[-1].moving is False and changes[-1].position == 150
    positions = [s.position for s in moving]
    assert positions == sorted(positions)


def test_the_step_log_is_bounded(monkeypatch):
    from indi_allsky.focus import lens as lens_mod
    monkeypatch.setattr(lens_mod, 'LOG_CAP', 100)
    monkeypatch.setattr(lens_mod, 'LOG_TRIM', 10)
    lens, driver, clock, changes = make(limit=1000, backlash=20)
    try:
        go(lens, 500)
        assert len(lens._log_t) <= 110
        assert lens.position_at(T0) is None           # trimmed away
        assert lens.position_at(clock.t) == 500
    finally:
        lens.close()


def test_first_small_outward_move_takes_up_the_backlash():
    # at the session start nobody knows which way the gears last turned
    lens, driver, clock, changes = make()
    s = go(lens, 5)
    assert s.position == 5
    assert min(driver.path) == 5 - 20
    assert phases(changes)[:2] == ['backlash', 'move']
