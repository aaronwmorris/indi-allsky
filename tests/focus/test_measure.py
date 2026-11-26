from __future__ import annotations

import math

import numpy as np
import pytest

from indi_allsky.focus.measure import DEFAULT_MIN_SNR
from indi_allsky.focus.measure import Candidate
from indi_allsky.focus.measure import StarReading
from indi_allsky.focus.measure import Tracker
from indi_allsky.focus.measure import contrast_score
from indi_allsky.focus.measure import detect
from indi_allsky.focus.measure import find_hot_pixels
from indi_allsky.focus.measure import fix_hot_pixels
from indi_allsky.focus.measure import glare_mask
from indi_allsky.focus.measure import grade
from indi_allsky.focus.measure import measure_star
from indi_allsky.focus.measure import noise_sigma
from indi_allsky.focus.measure import off_glare
from indi_allsky.focus.measure import pick
from indi_allsky.focus.measure import to_gray
from tests.focus import synth


BAYER_STEP = 2


def _clean_gray(raw, bayer='RGGB', step=BAYER_STEP):
    """The per-frame path: hot pixels found and fixed on the mosaic, then gray."""
    hot = find_hot_pixels(raw, step)
    return to_gray(fix_hot_pixels(raw, hot, step), bayer), hot


def _near(cands, x, y, r):
    return [c for c in cands if (c.x - x) ** 2 + (c.y - y) ** 2 <= r ** 2]


def test_one_pixel_star_survives_hot_pixel_fix_and_pick():
    """A star about 1 px wide must survive the hot-pixel fix, be picked, and measure smaller.

    The Bayer mapping follows the repo's convention (constants.py CFA_RGGB -> OpenCV BG), which centres the sharp
    star close to where it was drawn (true (100.3, 128.2)). The sizes asserted below were recorded from this
    synthetic frame (synth seed 20261124).

    The star sits off the pixel centre by (0.3, 0.2). Exactly centred, a sigma 0.45 px star puts 18% of its centre
    pixel's excess in each neighbour, under the 25% rule, so it is classified as a hot pixel.
    """
    # off-centre on purpose: a pixel-centred sigma 0.45 star is classed as hot (a known limitation)
    small = synth.Star(100.3, 128.2, 0.45, 20000)
    wide = synth.Star(160.3, 128.2, 1.0, 20000)
    raw = synth.frame(stars=[small, wide], hot=[(128, 104, 30000)])

    gray, hot = _clean_gray(raw)
    assert list(zip(hot[0].tolist(), hot[1].tolist())) == [(128, 104)]
    assert gray[128, 104] < gray[128, 100]  # the hot pixel is gone; the star's pixel is not

    cands = pick(gray)
    assert len(_near(cands, small.x, small.y, 1.5)) == 1
    assert not _near(cands, 104, 128, 1.5)

    sigma = noise_sigma(gray)
    r_small = measure_star(gray, small.x, small.y, sigma)
    r_wide = measure_star(gray, wide.x, wide.y, sigma)
    assert r_small is not None and r_wide is not None
    assert r_small.size < r_wide.size
    assert r_small.size == pytest.approx(2.031, abs=0.005)
    assert r_wide.size == pytest.approx(2.840, abs=0.005)


def test_hot_pixel_removed_not_counted_as_star():
    star = synth.Star(80.3, 80.2, 1.2, 20000)
    raw = synth.frame(stars=[star], hot=[(170, 150, 40000)])

    # without the fix, the demosaiced hot pixel is picked as a star
    assert _near(pick(to_gray(raw, 'RGGB')), 150, 170, 2)

    gray, hot = _clean_gray(raw)
    assert list(zip(hot[0].tolist(), hot[1].tolist())) == [(170, 150)]
    cands = pick(gray)
    assert not _near(cands, 150, 170, 3)
    assert len(_near(cands, star.x, star.y, 1.5)) == 1


def test_hot_pixel_fix_uses_same_colour_neighbours():
    raw = np.zeros((10, 10), np.uint16)
    raw[0::2, 0::2] = 100  # red sites
    raw[1::2, 1::2] = 300  # blue sites
    raw[4, 4] = 60000      # a hot red pixel
    hot = (np.array([4]), np.array([4]))
    fixed = fix_hot_pixels(raw, hot, BAYER_STEP)
    assert fixed.dtype == np.float32
    assert fixed[4, 4] == 100
    assert raw[4, 4] == 60000  # a copy, not in place


def test_find_hot_pixels_skips_the_edge():
    raw = synth.frame(shape=(64, 64))
    raw[1, 30] = 60000  # within step of the edge
    raw[30, 30] = 60000
    ys, xs = find_hot_pixels(raw, BAYER_STEP)
    assert list(zip(ys.tolist(), xs.tolist())) == [(30, 30)]


def test_to_gray_mono_passes_through_and_bayer_is_full_resolution():
    raw = synth.frame(shape=(32, 48))
    mono = to_gray(raw, None)
    assert mono.dtype == np.float32 and mono.shape == (32, 48)
    assert np.array_equal(mono, raw.astype(np.float32))
    for pattern in ('RGGB', 'GRBG', 'GBRG', 'BGGR'):
        g = to_gray(raw, pattern)
        assert g.dtype == np.float32 and g.shape == (32, 48)
    with pytest.raises(ValueError):
        to_gray(raw, 'XYZW')


def test_to_gray_follows_repo_bayer_convention():
    """constants.py CFA_* mapping: a pure-red field must weigh as red (0.299), not blue (0.114)."""
    level = 10000
    for pattern, red_site in (('RGGB', (0, 0)), ('GRBG', (0, 1)), ('GBRG', (1, 0)), ('BGGR', (1, 1))):
        raw = np.zeros((32, 32), np.uint16)
        raw[red_site[0]::2, red_site[1]::2] = level
        g = float(np.median(to_gray(raw, pattern)[4:-4, 4:-4]))
        assert g == pytest.approx(0.299 * level, rel=0.02), pattern


def test_noise_sigma_matches_gaussian():
    rng = np.random.default_rng(1)
    g = rng.normal(500.0, 20.0, (512, 512)).astype(np.float32)
    assert noise_sigma(g) == pytest.approx(20.0, rel=0.03)


def test_size_grows_with_blur():
    shape = (256, 256)
    sizes = []
    for s in (1.0, 2.0, 3.0):
        stars = synth.grid_stars(shape, s, 60000)
        gray, _ = _clean_gray(synth.frame(shape=shape, stars=stars))
        sigma = noise_sigma(gray)
        readings = [measure_star(gray, st.x, st.y, sigma) for st in stars]
        assert all(r is not None for r in readings)
        sizes.append(float(np.median([r.size for r in readings])))
    assert sizes[0] < sizes[1] < sizes[2]


def test_pick_rejects_glint_edge_and_split():
    """The split pair is small and faint on purpose: with the 1.2 px smoothing, any brighter pair 5 px apart merges
    into one component in `detect` and never reaches the same-star rule."""
    shape = (256, 256)
    glint = synth.Glint(190.0, 190.0, math.sqrt(1200 / math.pi), 20000)
    edge = synth.Star(10.3, 128.2, 1.0, 20000)       # 10 px from the left edge
    bright = synth.Star(80.3, 80.2, 0.5, 1600)
    faint = synth.Star(85.3, 80.2, 0.5, 1000)         # 5 px from the bright star
    control = synth.Star(128.3, 60.2, 1.0, 20000)
    raw = synth.frame(shape=shape, stars=[edge, bright, faint, control], glints=[glint])
    gray, _ = _clean_gray(raw)

    # each rejection fails for its own reason
    found = detect(gray)
    assert [c for c in _near(found, glint.x, glint.y, 3) if c.area > 900]
    assert _near(found, edge.x, edge.y, 1.5)
    assert len(_near(found, bright.x, bright.y, 1.5)) == 1
    assert len(_near(found, faint.x, faint.y, 1.5)) == 1

    cands = pick(gray)
    assert all(isinstance(c, Candidate) for c in cands)
    assert not _near(cands, glint.x, glint.y, glint.radius + 2)
    assert not _near(cands, edge.x, edge.y, 3)
    assert len(_near(cands, bright.x, bright.y, 1.5)) == 1
    assert not _near(cands, faint.x, faint.y, 1.5)
    assert len(_near(cands, control.x, control.y, 1.5)) == 1
    fluxes = [c.flux for c in cands]
    assert fluxes == sorted(fluxes, reverse=True)


MOON = synth.Glint(150.0, 150.0, 15.0, 80000)                 # clips: area about 700 px
HALO = synth.Star(150.0, 150.0, 40.0, 1.0e7)                    # about 1000 e peak: the halo mask ends near 55 px
SPIKE_KNOTS = [synth.Star(150.3 + d, 150.2, 1.0, 6000) for d in (35, 50, 65, 80)]
FAR_STARS = [synth.Star(420.3, 400.2, 1.0, 6000), synth.Star(420.3, 120.2, 1.0, 6000),
             synth.Star(120.3, 420.2, 1.0, 6000)]


def _moon_frame():
    raw = synth.frame(shape=(512, 512), stars=[HALO, *SPIKE_KNOTS, *FAR_STARS], glints=[MOON])
    return _clean_gray(raw)[0]


def test_pick_with_clip_drops_moon_spikes_and_keeps_far_stars():
    """The 2026-11-24 full-moon night: knots along the moon's spikes were picked as stars."""
    gray = _moon_frame()
    cands = pick(gray, clip=0.98 * 65535)
    for s in SPIKE_KNOTS:
        assert not _near(cands, s.x, s.y, 3), s
    for s in FAR_STARS:
        assert len(_near(cands, s.x, s.y, 1.5)) == 1, s


def test_glare_mask_covers_the_moon_but_not_a_clipped_star_core():
    gray = _moon_frame()
    gray[99:102, 399:402] = 65535.0                             # a bright star's clipped core: 9 px
    mask = glare_mask(gray, 0.98 * 65535)
    assert mask[150, 150] and mask[150, 230]                    # inside 6 x the moon's radius
    assert not mask[100, 400]
    assert not mask[400, 400]


def test_peak_snr_uses_central_7x7():
    """Pure noise: the typical box reads under 4, and the central 7x7 reads lower than the whole 25x25 box would.

    Not every noise box reads under 4. On Bayer gray, noise_sigma's every-4th-pixel sample lands on one Bayer site,
    the red one (std 13.8 there vs 17.0 over all pixels on this synth), so the S/N of a pure-noise box reaches 4
    in about one box in nine (11.7% of 1369 on a 512x512 frame; median 3.0). On a mono frame the median is 2.2.
    The noise is sampled on every 4th pixel, so which Bayer site it lands on is fixed.
    """
    gray = to_gray(synth.frame(shape=(256, 256)), 'RGGB')
    sigma = noise_sigma(gray)
    central, whole = [], []
    for y in range(20, 240, 20):
        for x in range(20, 240, 20):
            r = measure_star(gray, x, y, sigma)
            central.append(r.snr if r else 0.0)
            b = gray[y - 12:y + 13, x - 12:x + 13]
            bg = float(np.median(np.concatenate([b[0], b[-1], b[:, 0], b[:, -1]])))
            whole.append((float(b.max()) - bg) / sigma)
    assert float(np.median(central)) < 4
    assert float(np.median(central)) < float(np.median(whole)) - 1

    mono = synth.frame(shape=(256, 256)).astype(np.float32)
    msig = noise_sigma(mono)
    snrs = [measure_star(mono, x, y, msig) for y in range(20, 240, 20) for x in range(20, 240, 20)]
    assert float(np.median([r.snr if r else 0.0 for r in snrs])) < 3

    # a bright star 8 px from the box centre is in the box but outside the central 7x7
    star = synth.Star(136.3, 128.2, 1.0, 40000)
    gray = to_gray(synth.frame(shape=(256, 256), stars=[star]), 'RGGB')
    off = measure_star(gray, 128, 128, noise_sigma(gray))
    on = measure_star(gray, star.x, star.y, noise_sigma(gray))
    assert isinstance(on, StarReading) and on.snr > 100
    assert off is None or off.snr < 0.1 * on.snr


def test_measure_star_outside_frame_is_none():
    gray = to_gray(synth.frame(shape=(64, 64)), 'RGGB')
    assert measure_star(gray, 5, 30, noise_sigma(gray)) is None
    assert measure_star(gray, 30, 60, noise_sigma(gray)) is None


def _field(shape, stars, dx, dy, seed):
    moved = [s._replace(x=s.x + dx, y=s.y + dy) for s in stars]
    return to_gray(synth.frame(shape=shape, stars=moved, seed=seed), 'RGGB')


def test_tracker_follows_46px_drift_in_steps():
    """The brief: the field shifts 5 px a frame for 10 frames (50 px; the name says 46). max_shift is 6."""
    shape = (256, 256)
    stars = synth.grid_stars(shape, 1.5, 40000, spacing=40, margin=40)
    stars = [s for s in stars if s.x < 170]  # room to drift right
    gray = _field(shape, stars, 0, 0, 0)
    tracker = Tracker(pick(gray))
    assert len(tracker.positions) == len(stars)

    for k in range(1, 11):
        dx = 5.0 * k
        got = tracker.update(_field(shape, stars, dx, 0.0, k), noise_sigma(gray))
        assert sorted(got) == list(range(len(stars)))
        assert all(isinstance(r, StarReading) for r in got.values())
    for (x, y), s in zip(sorted(tracker.positions, key=lambda p: (round(p[1]), p[0])),
                         sorted(stars, key=lambda s: (round(s.y), s.x))):
        assert x == pytest.approx(s.x + 50.0, abs=0.5)
        assert y == pytest.approx(s.y, abs=0.5)


def test_tracker_moves_lost_star_with_the_rest():
    shape = (256, 256)
    stars = [synth.Star(80.3, 80.2, 1.5, 40000), synth.Star(150.3, 90.2, 1.5, 40000),
             synth.Star(110.3, 160.2, 1.5, 40000)]
    tracker = Tracker([Candidate(s.x, s.y, 1.0, 9) for s in stars])

    # star 2 vanishes (a cloud) while the field moves 4 px, then returns 8 px from where it was last seen
    hidden = [stars[0], stars[1], stars[2]._replace(flux=0.0)]
    gray = _field(shape, hidden, 4.0, 0.0, 1)
    got = tracker.update(gray, noise_sigma(gray))
    assert sorted(got) == [0, 1]
    assert tracker.positions[2][0] == pytest.approx(stars[2].x + 4.0, abs=0.5)

    gray = _field(shape, stars, 8.0, 0.0, 2)
    got = tracker.update(gray, noise_sigma(gray))
    assert sorted(got) == [0, 1, 2]


def test_tracker_rejects_weak_and_jumped():
    shape = (128, 128)
    star = synth.Star(64.3, 64.2, 1.5, 40000)
    gray = _field(shape, [star], 0.0, 0.0, 1)
    sigma = noise_sigma(gray)
    assert Tracker([Candidate(star.x, star.y, 1.0, 9)], track_snr=1e9).update(gray, sigma) == {}
    assert Tracker([Candidate(star.x - 5, star.y, 1.0, 9)], max_shift=3.0).update(gray, sigma) == {}
    assert sorted(Tracker([Candidate(star.x - 5, star.y, 1.0, 9)]).update(gray, sigma)) == [0]


def test_contrast_score_higher_when_sharper():
    shape = (256, 256)
    sharp = to_gray(synth.frame(shape=shape, stars=synth.grid_stars(shape, 1.0, 40000)), 'RGGB')
    soft = to_gray(synth.frame(shape=shape, stars=synth.grid_stars(shape, 3.0, 40000)), 'RGGB')
    assert contrast_score(sharp) > contrast_score(soft)
    assert isinstance(contrast_score(sharp), float)


def test_grade():
    assert DEFAULT_MIN_SNR == 8.0
    assert grade(7.9, DEFAULT_MIN_SNR) == 'weak'
    assert grade(8.0, DEFAULT_MIN_SNR) == 'kept'
    assert grade(3.0, 3.0) == 'kept'


def test_off_glare_moves_the_region_clear_of_the_moon():
    gray = _moon_frame()                                        # moon at (150, 150), radius 15: disc about 90 px
    roi = (1000, 1200, 512, 512)
    new = off_glare(gray, 0.98 * 65535, roi, (3000, 3000))
    x, y, w, h = new
    assert (w, h) == (512, 512) and x % 2 == 0 and y % 2 == 0
    assert 0 <= x <= 3000 - w and 0 <= y <= 3000 - h
    mx, my = 1150.0, 1350.0
    assert math.hypot(max(x - mx, 0, mx - x - w), max(y - my, 0, my - y - h)) >= 90
    # nearest the sensor's centre: no clear region on the grid is closer
    assert math.hypot(x + 256 - 1500, y + 256 - 1500) < 300


def test_off_glare_none_without_a_light_or_without_room():
    clean = _clean_gray(synth.frame(shape=(512, 512), stars=FAR_STARS))[0]
    assert off_glare(clean, 0.98 * 65535, (0, 0, 512, 512), (3000, 3000)) is None
    assert off_glare(_moon_frame(), 0.98 * 65535, (0, 0, 512, 512), (512, 512)) is None
