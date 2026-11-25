from __future__ import annotations

from indi_allsky.focus.session import CommandLedger
from indi_allsky.focus.session import IDLE_TIMEOUT_S
from indi_allsky.focus.session import IDLE_WARNING_S
from indi_allsky.focus.session import MAX_PAGES
from indi_allsky.focus.session import NO_PAGE_TIMEOUT_S
from indi_allsky.focus.session import SessionRules


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def now(self):
        return self.t

    def __call__(self):
        return self.t


def _rules():
    clock = FakeClock()
    rules = SessionRules(clock)
    rules.start()
    return clock, rules


def test_constants():
    assert (NO_PAGE_TIMEOUT_S, IDLE_TIMEOUT_S, IDLE_WARNING_S, MAX_PAGES) == (120, 900, 60, 3)


def test_no_page_for_120s_ends():
    clock, rules = _rules()
    rules.page_connected('a')
    t0 = clock.t
    rules.page_left('a')
    clock.t = t0 + 119
    assert rules.tick() is None
    clock.t = t0 + 120
    assert rules.tick() == 'no_page'
    assert not rules.active
    assert rules.end_reason == 'no_page'


def test_never_connected_times_out_from_start():
    clock, rules = _rules()
    clock.t += 120
    assert rules.tick() == 'no_page'


def test_reconnect_inside_window_continues():
    clock, rules = _rules()
    rules.page_connected('a')
    t0 = clock.t
    rules.page_left('a')
    clock.t = t0 + 100
    rules.page_connected('a')
    clock.t = t0 + 200
    assert rules.tick() is None


def test_unknown_page_left_is_noop():
    clock, rules = _rules()
    rules.page_connected('a')
    rules.page_left('zzz')
    clock.t += 500
    assert rules.tick() is None


def test_idle_15min_with_warning():
    clock, rules = _rules()
    rules.page_connected('a')
    t0 = clock.t
    clock.t = t0 + 839
    assert rules.idle_warning() is None
    clock.t = t0 + 840
    assert rules.idle_warning() == 60.0
    clock.t = t0 + 900
    assert rules.tick() == 'idle'


def test_keep_going_restarts_idle():
    clock, rules = _rules()
    rules.page_connected('a')
    t0 = clock.t
    clock.t = t0 + 870
    rules.touched()
    clock.t = t0 + 880
    assert rules.idle_warning() is None
    clock.t = t0 + 900
    assert rules.tick() is None


def test_end_reason_reported_once():
    clock, rules = _rules()
    clock.t += 120
    assert rules.tick() == 'no_page'
    assert rules.tick() is None
    assert rules.end_reason == 'no_page'


def test_explicit_end():
    clock, rules = _rules()
    rules.end('user')
    assert not rules.active
    assert rules.end_reason == 'user'
    clock.t += 5000
    assert rules.tick() is None
    assert rules.idle_warning() is None


def test_ledger_marks_frames_after_settle():
    clock = FakeClock(10.0)
    ledger = CommandLedger(clock)
    ledger.begin(1)
    clock.t = 11.0
    ledger.done(1, 0.5)
    assert ledger.effective_before(11.4) == 0
    assert ledger.effective_before(11.5) == 1


def test_ledger_in_flight_never_counts_and_highest_wins():
    clock = FakeClock(10.0)
    ledger = CommandLedger(clock)
    ledger.begin(1)
    clock.t = 11.0
    ledger.done(1)
    ledger.begin(2)
    assert ledger.effective_before(100.0) == 1
    clock.t = 12.0
    ledger.done(2, 1.0)
    assert ledger.effective_before(12.9) == 1
    assert ledger.effective_before(13.0) == 2
    assert CommandLedger(clock).effective_before(100.0) == 0
