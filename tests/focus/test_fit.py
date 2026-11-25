"""The focus-curve fit: one soft-L1 curve through every star's samples."""

from __future__ import annotations

import numpy as np
import pytest

from indi_allsky.focus.fit import MSG_FLAT
from indi_allsky.focus.fit import MSG_LIMIT
from indi_allsky.focus.fit import fit_curve
from indi_allsky.focus.fit import model


SPAN = (-256.0, 256.0)


def scan(*, c=37.0, k=0.03, P=9.0, sizes=(1.2, 1.4, 1.6, 1.9), noise=0.1, outliers=0.0, frames=200, span=SPAN,
         seed=1):
    """One outward scan: `frames` columns evenly across `span`, every star measured in every frame."""
    rng = np.random.default_rng(seed)
    xs = np.linspace(span[0], span[1], frames)
    rows = []
    for sid, a in enumerate(sizes):
        s = model(xs, c, a, k, P) + rng.normal(0.0, noise, xs.size)
        bad = rng.random(xs.size) < outliers
        s[bad] = rng.uniform(5.0, 30.0, int(bad.sum()))
        rows.append(np.c_[xs, np.full(xs.size, sid), s])
    return np.vstack(rows)


def test_model_is_a_v_with_a_plateau():
    m = model(np.array([-1000.0, 0.0, 10.0, 1000.0]), 0.0, 1.5, 0.1, 9.0)
    assert m[1] == pytest.approx(1.5)
    assert m[2] == pytest.approx(np.hypot(1.5, 1.0))
    assert m[0] == m[3] == 9.0


@pytest.mark.parametrize('c', [-120.0, 0.0, 37.0, 150.0])
def test_recovers_best_focus_within_two_steps(c):
    f = fit_curve(scan(c=c), span=SPAN)
    assert f is not None and f.ok and f.message is None
    assert abs(f.c - c) <= 2.0
    assert f.stars == 4 and f.n == 800
    assert f.band[0] < c < f.band[1]
    assert f.k <= 4.0


def test_band_contains_c_and_widens_with_noise():
    quiet = fit_curve(scan(noise=0.05), span=SPAN)
    loud = fit_curve(scan(noise=0.3), span=SPAN)
    for f in (quiet, loud):
        assert f.band[0] <= f.c <= f.band[1]
    assert loud.noise > quiet.noise
    assert (loud.band[1] - loud.band[0]) > (quiet.band[1] - quiet.band[0])


def test_band_is_where_the_curve_is_within_noise_of_its_bottom():
    f = fit_curve(scan(), span=SPAN)
    half = np.sqrt((f.a + f.noise) ** 2 - f.a ** 2) / f.k
    assert f.band == pytest.approx((f.c - half, f.c + half))
    assert model(f.band[1], f.c, f.a, f.k, f.P) == pytest.approx(f.a + f.noise)


def test_band_is_clipped_to_the_span():
    f = fit_curve(scan(noise=0.3, k=0.004), span=SPAN)
    assert SPAN[0] <= f.band[0] and f.band[1] <= SPAN[1]


def test_noise_has_a_floor():
    f = fit_curve(scan(noise=0.0, sizes=(1.5,) * 4), span=SPAN)
    assert f.noise == pytest.approx(0.02)


def test_flat_data_is_not_a_curve():
    f = fit_curve(scan(k=1e-4), span=SPAN)
    assert f is not None and not f.ok
    assert f.message == MSG_FLAT == 'Could not find a clear best focus.'


def test_flat_small_stars_are_not_a_curve():
    # the plateau is never reached, so P is never set by the data: the check must not lean on it
    f = fit_curve(scan(k=0.0, sizes=(1.2,) * 4, noise=0.05), span=SPAN)
    assert not f.ok and f.message == MSG_FLAT


def test_best_focus_near_the_travel_limit_says_so():
    span = (-469.0, 0.0)
    f = fit_curve(scan(c=-460.0, span=span), span=span, limit=(-469, 512))
    assert not f.ok
    assert f.message == MSG_LIMIT == 'Best focus may be beyond the travel limit.'


def test_best_focus_well_inside_the_limit_is_ok():
    f = fit_curve(scan(), span=SPAN, limit=(-469, 512))
    assert f.ok and f.message is None


def test_c_is_bounded_to_the_span():
    span = (-100.0, 100.0)
    f = fit_curve(scan(c=180.0, span=span), span=span)
    assert -100.0 <= f.c <= 100.0


@pytest.mark.parametrize('c', [130.0, -130.0])
def test_best_focus_past_the_scan_is_not_ok(c):
    # the travel limit is far away, so the scan's own edge is what stopped c
    span = (-100.0, 100.0)
    f = fit_curve(scan(c=c, span=span), span=span, limit=(-2000, 2000))
    assert f is None or (not f.ok and f.message == MSG_FLAT)


def test_too_few_samples_is_none():
    data = scan(frames=7)                 # 28 samples
    assert fit_curve(data, span=SPAN) is None
    assert fit_curve(np.empty((0, 3)), span=SPAN) is None


def test_too_narrow_a_span_is_none():
    data = scan(frames=50, span=(10.0, 14.0))
    assert fit_curve(data, span=(10.0, 14.0)) is None
    assert fit_curve(data, span=SPAN) is None    # the samples' own x span counts too


def test_non_finite_samples_are_ignored():
    data = scan()
    data[::10, 2] = np.nan
    f = fit_curve(data, span=SPAN)
    assert f is not None and abs(f.c - 37.0) <= 2.0
    assert f.n == len(data) - len(data[::10])


def test_outliers_do_not_drag_the_centre():
    f = fit_curve(scan(outliers=0.1), span=SPAN)
    assert f.ok and abs(f.c - 37.0) <= 2.0


def test_noise_is_per_frame_not_per_sample():
    # the same per-sample scatter with more stars per frame: one frame's average reading is less noisy
    few = fit_curve(scan(sizes=(1.5,) * 2, noise=0.2), span=SPAN)
    many = fit_curve(scan(sizes=(1.5,) * 8, noise=0.2), span=SPAN)
    assert many.noise < few.noise


def test_twenty_thousand_samples():
    data = scan(sizes=tuple(1.2 + 0.1 * i for i in range(8)), frames=2500, outliers=0.05)
    assert len(data) == 20000
    f = fit_curve(data, span=SPAN)
    assert f.ok and abs(f.c - 37.0) <= 2.0
