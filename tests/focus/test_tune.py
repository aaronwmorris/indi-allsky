"""The tune ladder: which points it takes, and which it settles on."""

from __future__ import annotations

import numpy as np

from indi_allsky.focus.exposure_search import MSG_BRIGHT
from indi_allsky.focus.exposure_search import MSG_NO_STARS
from indi_allsky.focus.exposure_search import MSG_SHORTEST_OVER
from indi_allsky.focus.tune import LADDER_S
from indi_allsky.focus.tune import MSG_TUNE_REFUSED
from indi_allsky.focus.tune import Tune
from indi_allsky.focus.tune import count_stars
from indi_allsky.focus.tune import ladder_exposures
from indi_allsky.focus.measure import noise_sigma
from indi_allsky.focus.tune import ladder_gains
from tests.focus import synth


def run(tune, score):
    """Step the tune to the end; score(exposure, gain) -> (count, level). Returns the final step and the points
    taken, in order."""
    taken = []
    step = tune.first()
    while not step.done:
        taken.append((tune.exposure, tune.gain))
        step = tune.step(*score(tune.exposure, tune.gain))
    return step, taken


def test_ladder_exposures_clamp_and_dedupe():
    assert ladder_exposures(1e-6, 15.0) == list(LADDER_S)
    assert ladder_exposures(0.15, 0.5) == [0.15, 0.2, 0.4, 0.5]
    assert ladder_exposures(2.0, 1.0) == [2.0]  # a ceiling under the shortest: the shortest alone


def test_ladder_gains_span_or_keep():
    assert ladder_gains(0, 600, 81) == [150, 300, 450]
    assert ladder_gains(None, None, 81) == [None]
    assert ladder_gains(100, 100, 100) == [None]  # a fixed gain


def test_each_step_says_which_point_of_how_many():
    tune = Tune([0.1, 0.2, 0.4], [None])
    first = tune.first()
    assert (first.step, first.of) == (1, 3)
    second = tune.step(5, 'dark')
    assert (second.step, second.of) == (2, 3)
    tune.step(5, 'dark')
    final = tune.step(5, 'dark')
    assert final.done and final.step is None  # the end carries no point number


def test_a_skipped_point_moves_the_step_on():
    # 0.1 s over-exposed: every longer point is dead, so the tune ends at once
    tune = Tune([0.1, 0.2, 0.4], [None])
    tune.first()
    assert tune.step(0, 'over').done


def test_knee_is_the_shortest_that_gets_most_of_the_stars():
    counts = {0.05: 2, 0.1: 9, 0.2: 18, 0.4: 20, 0.8: 21, 1.6: 22}
    step, taken = run(Tune(list(LADDER_S), [None]), lambda e, g: (counts[e], 'dark'))
    assert len(taken) == 6
    assert step.exposure == 0.2 and step.gain is None  # 18 >= 0.8 * 22
    assert step.message == 'Tuned: 0.2 s · 18 stars.'


def test_ties_at_the_knee_go_to_the_lower_gain():
    def score(e, g):
        return (20 if e >= 0.2 else 1), 'dark'
    step, _ = run(Tune([0.1, 0.2, 0.4], [150, 300, 450]), score)
    assert (step.exposure, step.gain) == (0.2, 150)
    assert step.message == 'Tuned: 0.2 s at gain 150 · 20 stars.'


def test_a_higher_gain_can_win_a_shorter_exposure():
    def score(e, g):
        return (20 if e * g >= 60 else 2), 'dark'
    step, _ = run(Tune([0.1, 0.2, 0.4], [150, 300, 450]), score)
    assert (step.exposure, step.gain) == (0.2, 300)  # 0.2 x 300 gets there; 0.4 x 150 is longer


def test_over_exposure_skips_the_rest_of_that_gain_and_higher():
    def score(e, g):
        return 10, ('over' if e * g >= 120 else 'dark')
    _, taken = run(Tune([0.1, 0.2, 0.4, 0.8], [150, 300, 450]), score)
    # 0.4 x 300 is over: neither 0.4 x 450 nor anything longer at 300 or 450 is taken
    assert (0.4, 450) not in taken and (0.8, 300) not in taken and (0.8, 450) not in taken
    assert (0.8, 150) in taken


def test_no_stars_leaves_the_longest_unclipped_at_mid_gain():
    step, _ = run(Tune([0.1, 0.2, 0.4], [150, 300, 450]), lambda e, g: (0, 'dark'))
    assert (step.exposure, step.gain, step.message) == (0.4, 300, MSG_NO_STARS)


def test_never_settles_on_a_point_without_stars():
    counts = {(0.1, 150): 0, (0.1, 300): 6, (0.2, 150): 0, (0.2, 300): 0}
    step, _ = run(Tune([0.1, 0.2], [150, 300]), lambda e, g: (counts[(e, g)], 'dark'))
    assert (step.exposure, step.gain) == (0.1, 300)


def test_all_over_settles_on_the_shortest_lowest():
    step, taken = run(Tune([0.1, 0.2], [150, 300]), lambda e, g: (0, 'over'))
    assert taken == [(0.1, 150)]  # everything else is longer or higher
    assert (step.exposure, step.gain, step.message) == (0.1, 150, MSG_SHORTEST_OVER)


def test_bright_without_stars_focuses_on_contrast():
    step, _ = run(Tune([0.1, 0.2], [None]), lambda e, g: (0, 'bright'))
    assert (step.exposure, step.message) == (0.1, MSG_BRIGHT)


def test_a_refused_point_is_skipped_and_the_tune_goes_on():
    tune = Tune([0.1, 0.2, 0.4], [None])
    tune.first()
    tune.step(3, 'dark')
    step = tune.fail()                      # the camera refused 0.2 s
    assert (step.exposure, step.done) == (0.4, False)
    step = tune.step(20, 'dark')
    assert step.done and step.exposure == 0.4  # the refused point never wins
    assert tune.table().splitlines()[2].split()[:4] == ['0.2', '-', '-', 'failed']


def test_a_refused_last_point_still_settles():
    tune = Tune([0.1, 0.2], [None])
    tune.first()
    tune.step(20, 'dark')
    step = tune.fail()
    assert step.done and step.exposure == 0.1


def test_every_point_refused_keeps_the_settings():
    tune = Tune([0.1, 0.2], [None])
    tune.first()
    tune.fail()
    step = tune.fail()
    assert step.done and step.exposure is None and step.message == MSG_TUNE_REFUSED


def test_all_over_after_a_refusal_settles_on_a_point_that_was_taken():
    tune = Tune([0.1, 0.2], [150, 300])
    tune.first()
    tune.fail()                             # 0.1 s at gain 150 refused
    tune.step(0, 'over')                    # 0.1 s at gain 300
    step = tune.step(0, 'over')             # 0.2 s at gain 150; 0.2 s at 300 is then dead
    assert step.done and (step.exposure, step.gain, step.message) == (0.1, 300, MSG_SHORTEST_OVER)


def test_progress_counts_the_points():
    tune = Tune([0.1, 0.2], [150, 300])
    assert tune.first().message == 'Tuning: 1 of 4 · 0.1 s at gain 150'
    assert tune.step(3, 'dark').message == 'Tuning: 2 of 4 · 0.1 s at gain 300'


def test_table_lists_every_point():
    tune = Tune([0.1, 0.2], [None])
    tune.step(3, 'dark', t=100.0)
    tune.step(7, 'dark', t=101.5)
    lines = tune.table().splitlines()
    assert len(lines) == 3 and lines[2].split()[:4] == ['0.2', '-', '7', 'dark'] and lines[2].endswith('1.5')


def test_count_stars_skips_faint_and_clipped():
    shape = (200, 200)
    bright = [synth.Star(50.3, 50.2, 1.5, 40000.0), synth.Star(150.3, 50.2, 1.5, 40000.0),
              synth.Star(50.3, 150.2, 1.5, 40000.0)]
    faint = synth.Star(150.3, 150.2, 1.5, 150.0)
    gray = synth.frame(shape, stars=bright + [faint]).astype(np.float32)
    clip = 0.98 * 65535.0
    assert count_stars(gray, gray, clip, noise_sigma(gray)) == 3
    clipped = gray.copy()
    clipped[50, 50] = 65535.0  # one clipped core: not a glare blob, but that star is saturated
    assert count_stars(clipped, clipped, clip, noise_sigma(clipped)) == 2
