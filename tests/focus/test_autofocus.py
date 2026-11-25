"""The autofocus scan state machine."""

from __future__ import annotations

import math

import numpy as np
import pytest

from indi_allsky.focus.autofocus import FRAME_SPAN_STEPS
from indi_allsky.focus.autofocus import MSG_FLAT
from indi_allsky.focus.autofocus import MSG_LIMIT
from indi_allsky.focus.autofocus import MSG_NO_STARS
from indi_allsky.focus.autofocus import STAGES
from indi_allsky.focus.autofocus import STAGE_WORDS
from indi_allsky.focus.autofocus import Autofocus
from indi_allsky.focus.fit import Fit


def af(here=0, reachable=(-469, 512), limit=512, exposure=0.25, speed=25.0):
    return Autofocus(here=here, reachable=reachable, limit=limit, exposure=exposure, speed=speed)


def a_fit(c=10.4, ok=True, message=None):
    return Fit(c=c, a=1.5, k=0.03, P=9.0, band=(c - 20, c + 20), noise=0.05, n=400, stars=4, scatter=0.1,
               rise=5.0, ok=ok, message=message)


def test_constants():
    assert STAGES == ('start', 'scan', 'fit', 'park')
    assert set(STAGE_WORDS) == set(STAGES)
    assert FRAME_SPAN_STEPS == 8
    assert MSG_NO_STARS == 'No stars to measure. Try a longer exposure.'
    assert MSG_LIMIT == 'Best focus may be beyond the travel limit.'
    assert MSG_FLAT == 'Could not find a clear best focus.'


def test_window_is_half_the_travel_limit_each_side():
    a = af(here=0, limit=512)
    assert (a.here, a.start, a.end) == (0, -256, 256)
    a = af(here=0, limit=301, reachable=(-500, 500))
    assert (a.start, a.end) == (-round(301 / 2), round(301 / 2))


def test_window_is_clamped_to_reachable():
    a = af(here=-400, reachable=(-469, 512), limit=512)
    assert (a.start, a.end) == (-469, -144)
    a = af(here=400, reachable=(-469, 512), limit=512)
    assert (a.start, a.end) == (144, 512)


def test_max_rate_paces_one_frame_to_eight_steps():
    assert af(exposure=0.25, speed=200).max_rate == pytest.approx(32.0)
    assert af(exposure=0.25, speed=25).max_rate == pytest.approx(25.0)     # the motor is the slower one
    assert af(exposure=2.0, speed=25).max_rate == pytest.approx(4.0)


def test_estimate_s():
    a = af(here=0, exposure=1.0, speed=25.0)      # start -256, end 256, max_rate 8
    expected = (256 + 43) / 25.0 + 512 / 8.0 + 3 + 256 / 25.0
    assert a.estimate_s(0, 43) == math.ceil(expected)
    assert a.estimate_s(-256, 0) == math.ceil(512 / 8.0 + 3 + 256 / 25.0)


def test_add_frame_samples_and_columns():
    a = af()
    a.begin_scan()
    assert a.columns() == 0 and a.samples().shape == (0, 3)
    a.add_frame(-100.5, [(0, 3.2), (2, 4.0)])
    a.add_frame(-92.0, [])                        # no stars: not a column
    a.add_frame(-84.0, [(0, 3.0)])
    assert a.columns() == 2
    np.testing.assert_array_equal(a.samples(), [[-100.5, 0, 3.2], [-100.5, 2, 4.0], [-84.0, 0, 3.0]])


def test_frames_only_during_the_scan():
    a = af()
    with pytest.raises(RuntimeError):
        a.add_frame(0.0, [(0, 1.0)])


def test_a_run_that_parks():
    a = af()
    assert a.stage == 'start' and a.words == STAGE_WORDS['start'] and not a.done
    a.begin_scan()
    assert a.stage == 'scan'
    a.add_frame(0.0, [(0, 2.0)])
    assert a.begin_fit() is None and a.stage == 'fit'
    assert a.begin_park(a_fit(c=10.4)) is None and a.stage == 'park'
    assert a.park_target() == 10
    a.finish()
    assert a.done and a.stage == 'done' and a.message is None and a.words == ''


def test_park_target_stays_inside_the_window():
    a = af()
    a.begin_scan()
    a.add_frame(0.0, [(0, 2.0)])
    a.begin_fit()
    a.begin_park(a_fit(c=256.6))
    assert a.park_target() == 256


def test_no_stars_finishes_at_begin_fit():
    a = af()
    a.begin_scan()
    assert a.begin_fit() == MSG_NO_STARS
    assert a.done and a.message == MSG_NO_STARS and a.words == MSG_NO_STARS


def test_no_fit_or_a_bad_fit_finishes():
    for fit, msg in ((None, MSG_FLAT), (a_fit(ok=False, message=MSG_LIMIT), MSG_LIMIT)):
        a = af()
        a.begin_scan()
        a.add_frame(0.0, [(0, 2.0)])
        a.begin_fit()
        assert a.begin_park(fit) == msg
        assert a.done and a.message == msg and a.fit is fit


def test_stop_finishes_from_any_stage_and_keeps_the_first_message():
    a = af()
    a.begin_scan()
    a.finish('Stopped.')
    a.finish('later')
    assert a.done and a.message == 'Stopped.'
    with pytest.raises(RuntimeError):
        a.begin_fit()


def test_stages_only_move_forward():
    a = af()
    with pytest.raises(RuntimeError):
        a.begin_fit()
    a.begin_scan()
    with pytest.raises(RuntimeError):
        a.begin_scan()
    with pytest.raises(RuntimeError):
        a.park_target()
