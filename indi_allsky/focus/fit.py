"""The focus curve: one curve through every picked star's samples.

    size = min(P, sqrt(a^2 + (k (x - c))^2))

`c` is best focus in driver steps, `a` the star size there, `k` the slope of the V's sides and `P` the plateau (far
from focus a star outgrows the measuring box and stops growing, so plateau samples are fitted, not thrown away).

The solver is scipy `least_squares` with a soft-L1 loss so faint or lost stars measuring junk cannot drag the
centre, multi-started over c and the V's width because the cost has local minima on a flat plateau. It fits one
curve for all stars, with no per-star size offset: the star id only counts the stars.

The sharp zone is noise-based, not where the V meets the plateau: the band is where the curve lies within one
frame's measurement noise of its lowest point.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


MSG_LIMIT = 'Best focus may be beyond the travel limit.'
MSG_FLAT = 'Could not find a clear best focus.'

MIN_SAMPLES = 30
MIN_SPAN_STEPS = 5.0
NOISE_FLOOR_PX = 0.02
MIN_RISE = 0.1

# solver (k bound in px per driver step)
F_SCALE = 1.5
MAX_NFEV = 60
START_CS = 13
START_HALF_WIDTHS = (0.08, 0.2, 0.4)   # of the span: where the V meets the plateau, for the k start value
A_BOUNDS = (0.5, 30.0)
K_BOUNDS = (1e-5, 4.0)                 # px/step
P_BOUNDS = (2.0, 40.0)
START_ROWS = 2500                      # the multi-start runs on at most this many samples


@dataclass(frozen=True)
class Fit:
    c: float                    # best focus, steps
    a: float                    # size at best, px
    k: float                    # slope, px/step
    P: float                    # plateau, px
    band: tuple[float, float]   # sharp zone (lo, hi) in steps
    noise: float                # px, what the band is measured by
    n: int                      # samples used
    stars: int                  # stars that contributed
    scatter: float              # robust residual sigma / a
    rise: float                 # (curve's highest point inside the span - a) / a; (P - a) / a once it plateaus
    ok: bool                    # passes the curve check
    message: Optional[str]      # failure wording when not ok, else None


def model(x, c, a, k, P) -> np.ndarray:
    """min(P, sqrt(a^2 + (k (x - c))^2))."""
    x = np.asarray(x, dtype=float)
    return np.minimum(P, np.sqrt(a * a + (k * (x - c)) ** 2))


def _robust_sigma(r: np.ndarray) -> float:
    return 1.4826 * float(np.median(np.abs(r)))


def _stars_per_frame(x: np.ndarray, j: np.ndarray) -> float:
    """Median count of distinct stars per column. A frame yields one sample per star, all at one x; counting
    distinct star ids (not samples) keeps two frames taken at the same resting x from counting as one big frame."""
    order = np.lexsort((j, x))
    xs, js = x[order], j[order]
    new_col = np.r_[True, xs[1:] != xs[:-1]]
    new_pair = new_col | np.r_[True, js[1:] != js[:-1]]
    col_id = np.cumsum(new_col) - 1
    counts = np.bincount(col_id[new_pair])
    return float(np.median(counts))


def _residuals(x: np.ndarray, s: np.ndarray):
    def res(p):
        c, a, k, P = p
        return s - np.minimum(P, np.sqrt(a * a + (k * (x - c)) ** 2))

    def jac(p):
        c, a, k, P = p
        d = x - c
        q = np.sqrt(a * a + (k * d) ** 2)
        v = q < P
        J = np.zeros((x.size, 4))
        J[v, 0] = k * k * d[v] / q[v]
        J[v, 1] = -a / q[v]
        J[v, 2] = -k * d[v] * d[v] / q[v]
        J[~v, 3] = -1.0
        return J

    return res, jac


def _solve(x: np.ndarray, s: np.ndarray, lo: float, hi: float):
    """Multi-start soft-L1 least squares. The starts run on an even, x-sorted subsample of at most START_ROWS
    rows; the best one is then polished on every sample. Returns the scipy result, or None."""
    from scipy.optimize import least_squares

    P0 = float(np.clip(np.percentile(s, 75), *P_BOUNDS))
    a0 = float(np.clip(max(1.0, np.percentile(s, 3)), *A_BOUNDS))
    width = hi - lo
    lower = [lo, A_BOUNDS[0], K_BOUNDS[0], P_BOUNDS[0]]
    upper = [hi, A_BOUNDS[1], K_BOUNDS[1], P_BOUNDS[1]]

    def run(xx, ss, p0):
        res, jac = _residuals(xx, ss)
        try:
            return least_squares(res, p0, jac=jac, loss='soft_l1', f_scale=F_SCALE, max_nfev=MAX_NFEV,
                                 bounds=(lower, upper))
        except (ValueError, np.linalg.LinAlgError):
            return None

    if x.size > START_ROWS:
        order = np.argsort(x, kind='stable')
        pick = order[np.linspace(0, x.size - 1, START_ROWS).astype(int)]
        xs, ss = x[pick], s[pick]
    else:
        xs, ss = x, s

    best = None
    for c0 in np.linspace(lo, hi, START_CS):
        for half in START_HALF_WIDTHS:
            k0 = float(np.clip(np.sqrt(max(P0 * P0 - a0 * a0, 1.0)) / (half * width), *K_BOUNDS))
            r = run(xs, ss, [c0, a0, k0, P0])
            if r is not None and (best is None or r.cost < best.cost):
                best = r
    if best is not None and xs is not x:
        best = run(x, s, best.x) or best
    return best


def fit_curve(samples: np.ndarray, *, span: tuple[float, float],
              limit: Optional[tuple[float, float]] = None) -> Optional[Fit]:
    """Fit one curve to (x, star_id, size) samples. None when there are fewer than 30 usable samples, when x spans
    less than 5 steps, or when the solver finds nothing. `span` is the scanned range and bounds c; `limit` is the
    reachable range, for the travel-limit check."""
    arr = np.asarray(samples, dtype=float).reshape(-1, 3)
    arr = arr[np.all(np.isfinite(arr), axis=1)]
    if len(arr) < MIN_SAMPLES:
        return None
    x, j, s = arr[:, 0], arr[:, 1], arr[:, 2]
    if float(x.max() - x.min()) < MIN_SPAN_STEPS:
        return None
    lo, hi = float(min(span)), float(max(span))
    if hi - lo < MIN_SPAN_STEPS:
        return None

    best = _solve(x, s, lo, hi)
    if best is None:
        return None
    c, a, k, P = (float(v) for v in best.x)

    sigma = _robust_sigma(s - model(x, c, a, k, P))
    n = int(len(x))
    stars = int(len(np.unique(j)))
    scatter = sigma / a
    # how far the fitted curve actually rises inside the scan. Equal to (P - a) / a whenever the scan reaches the
    # plateau; on flat data the plateau is never reached, P gets no gradient and stays wherever it started, so
    # (P - a) / a would be a number the data never set.
    rise = (float(np.max(model([lo, hi], c, a, k, P))) - a) / a

    noise = max(NOISE_FLOOR_PX, sigma / np.sqrt(_stars_per_frame(x, j)))
    half = float(np.sqrt((a + noise) ** 2 - a * a) / k)
    band = (max(lo, c - half), min(hi, c + half))

    ok, message = True, None
    if rise < max(MIN_RISE, 3.0 * scatter / np.sqrt(n / stars)):
        ok, message = False, MSG_FLAT
    elif limit is not None and (c - min(limit) <= half or max(limit) - c <= half):
        ok, message = False, MSG_LIMIT
    elif c - lo <= half or hi - c <= half:
        # c is bounded by the scan: at its edge the lowest point was never bracketed, best focus lies past it
        ok, message = False, MSG_FLAT

    return Fit(c=c, a=a, k=k, P=P, band=band, noise=float(noise), n=n, stars=stars, scatter=float(scatter),
               rise=float(rise), ok=ok, message=message)
