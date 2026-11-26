from __future__ import annotations

import numpy as np

from indi_allsky.focus.exposure_search import BRIGHT_FRACTION
from indi_allsky.focus.exposure_search import FOUND_STARS
from indi_allsky.focus.exposure_search import OVER_FRACTION
from indi_allsky.focus.exposure_search import ExposureSearch
from indi_allsky.focus.exposure_search import brightness
from indi_allsky.focus.exposure_search import default_ceiling


def _flat(fraction, full_scale=255.0):
    return np.full((8, 8), fraction * full_scale)


def test_brightness_levels():
    assert brightness(_flat(0.95), 255.0) == 'over'
    assert brightness(_flat(OVER_FRACTION), 255.0) == 'over'
    assert brightness(_flat(0.5), 255.0) == 'bright'
    assert brightness(_flat(BRIGHT_FRACTION), 255.0) == 'bright'
    assert brightness(_flat(0.05), 255.0) == 'dark'
    assert brightness(_flat(0.0), 255.0) == 'dark'


def test_brightness_uses_median_and_full_scale():
    gray = np.zeros((10, 10))
    gray[0, :5] = 65535.0  # a few hot pixels do not make it over-exposed
    assert brightness(gray, 65535.0) == 'dark'
    assert brightness(_flat(0.9, 65535.0), 65535.0) == 'over'


def test_default_ceiling():
    assert default_ceiling(None) == 15.0
    assert default_ceiling(60.0) == 15.0
    assert default_ceiling(8.0) == 8.0


def test_doubles_until_stars():
    s = ExposureSearch(shortest=0.001, ceiling=15.0, start=0.001)
    a = s.step(0, 'dark')
    b = s.step(0, 'dark')
    c = s.step(7, 'dark')
    assert (a.exposure, a.done) == (0.002, False)
    assert (b.exposure, b.done) == (0.004, False)
    assert (c.exposure, c.done) == (0.004, True)
    assert FOUND_STARS == 5


def test_stops_at_ceiling_with_message():
    s = ExposureSearch(shortest=1.0, ceiling=4.0, start=1.0)
    assert s.step(0, 'dark').exposure == 2.0
    assert s.step(0, 'dark').exposure == 4.0
    last = s.step(0, 'dark')
    assert last.done is True
    assert last.exposure == 4.0
    assert last.message == 'No stars to measure. Try a longer exposure.'


def test_doubling_is_clamped_to_ceiling():
    s = ExposureSearch(shortest=1.0, ceiling=3.0, start=1.0)
    assert s.step(0, 'dark').exposure == 2.0
    step = s.step(0, 'dark')
    assert step.exposure == 3.0
    assert step.done is False
    assert s.step(0, 'dark').done is True


def test_stops_on_bright_without_stars():
    s = ExposureSearch(shortest=0.001, ceiling=15.0, start=0.01)
    step = s.step(0, 'bright')
    assert step.done is True
    assert step.exposure == 0.01
    assert 'contrast' in step.message


def test_halves_when_over_exposed():
    s = ExposureSearch(shortest=0.001, ceiling=15.0, start=0.1)
    a = s.step(0, 'over')
    b = s.step(0, 'over')
    c = s.step(0, 'bright')
    assert (a.exposure, a.done) == (0.05, False)
    assert (b.exposure, b.done) == (0.025, False)
    assert (c.exposure, c.done) == (0.025, True)


def test_over_wins_even_with_stars():
    s = ExposureSearch(shortest=0.001, ceiling=15.0, start=0.1)
    step = s.step(9, 'over')
    assert step.exposure == 0.05
    assert step.done is False


def test_halving_clamps_to_shortest():
    s = ExposureSearch(shortest=0.03, ceiling=15.0, start=0.05)
    step = s.step(0, 'over')
    assert step.exposure == 0.03
    assert step.done is False
    assert s.step(0, 'over').done is True


def test_shortest_still_over_says_so():
    s = ExposureSearch(shortest=0.001, ceiling=15.0, start=0.001)
    step = s.step(0, 'over')
    assert step.done is True
    assert step.exposure == 0.001
    assert 'shortest exposure' in step.message
    assert 'over-exposed' in step.message


def test_message_per_step_is_shown():
    s = ExposureSearch(shortest=0.001, ceiling=0.004, start=0.001)
    steps = [
        s.step(0, 'dark'),
        s.step(0, 'dark'),
        s.step(0, 'dark'),
        s.step(0, 'dark'),
    ]
    steps.append(ExposureSearch(0.001, 15.0, 0.1).step(0, 'over'))
    steps.append(ExposureSearch(0.001, 15.0, 0.1).step(8, 'bright'))
    steps.append(ExposureSearch(0.001, 15.0, 0.1).step(0, 'bright'))
    for step in steps:
        assert step.message


def test_step_after_done_returns_same_result():
    s = ExposureSearch(shortest=0.001, ceiling=15.0, start=0.001)
    final = s.step(7, 'dark')
    assert final.done is True
    assert s.step(0, 'dark') == final
    assert s.step(0, 'over') == final


def test_a_zero_or_negative_start_still_reaches_the_ceiling():
    # 0 * 2 == 0: unclamped, the search would ask for 0 s forever and never finish
    for shortest, start in ((0.0, 0.0), (-1.0, 0.0), (0.0, -0.5), (float('nan'), float('nan'))):
        s = ExposureSearch(shortest=shortest, ceiling=15.0, start=start)
        assert s.shortest > 0 and s.exposure > 0
        for _ in range(64):
            step = s.step(0, 'dark')
            if step.done:
                break
        assert step.done and step.exposure == 15.0
