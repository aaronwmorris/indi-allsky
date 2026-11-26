"""Tune: try a ladder of exposures and gains, keep the shortest that shows most of the stars.

One frame per point. A point's score is the stars a pick would keep: glint-filtered candidates (`pick` with the
clip) whose peak S/N is at least `DEFAULT_MIN_SNR` and whose peak is not clipped. The choice is the shortest exposure
whose count is at least `KNEE_FRACTION` of the best count; at that exposure, the lowest gain that gets there.

`Tune` has the same step protocol as `ExposureSearch`: `exposure` and `gain` are the point to take next, and
`step(count, level)` returns a `SearchStep` (exposure, done, message, gain).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from indi_allsky.focus.exposure_search import FOUND_STARS
from indi_allsky.focus.exposure_search import MSG_BRIGHT
from indi_allsky.focus.exposure_search import MSG_NO_STARS
from indi_allsky.focus.exposure_search import MSG_SHORTEST_OVER
from indi_allsky.focus.exposure_search import SearchStep
from indi_allsky.focus.measure import DEFAULT_MIN_SNR
from indi_allsky.focus.measure import MEASURE_BOX
from indi_allsky.focus.measure import measure_star
from indi_allsky.focus.measure import pick


LADDER_S = (0.05, 0.1, 0.2, 0.4, 0.8, 1.6)
GAIN_FRACTIONS = (0.25, 0.5, 0.75)  # of the camera's gain span: low, mid, high
KNEE_FRACTION = 0.80

MSG_TUNING = 'Tuning: {0:d} of {1:d} · {2}'
MSG_TUNED = 'Tuned: {0} · {1:d} stars.'
MSG_TUNE_REFUSED = 'The camera took none of the tune settings. Your settings are kept.'


def ladder_exposures(shortest: float, ceiling: float) -> list[float]:
    """LADDER_S inside [shortest, ceiling], ascending, without repeats."""
    lo = float(shortest) if float(shortest) > 0 else LADDER_S[0]
    hi = max(float(ceiling), lo)
    out = sorted({min(max(e, lo), hi) for e in LADDER_S})
    return out


def ladder_gains(gain_min: Optional[float], gain_max: Optional[float], current: float) -> list[Optional[float]]:
    """Low, mid and high gain across the camera's span. [None] (keep the gain) when the span is unknown or fixed."""
    if gain_min is None or gain_max is None or not gain_max > gain_min:
        return [None]
    span = float(gain_max) - float(gain_min)
    return sorted({round(float(gain_min) + f * span) for f in GAIN_FRACTIONS})


def count_stars(gray: np.ndarray, fixed: np.ndarray, clip: float, sigma: float,
                min_snr: float = DEFAULT_MIN_SNR) -> int:
    """The stars a pick of this one frame would keep: outside the glare, S/N >= min_snr, not clipped."""
    n = 0
    half = MEASURE_BOX // 2
    for c in pick(gray, clip=clip):
        m = measure_star(gray, c.x, c.y, sigma)
        if m is None or not math.isfinite(m.snr) or m.snr < min_snr:
            continue
        xi, yi = int(round(c.x)), int(round(c.y))
        box = fixed[max(0, yi - half):yi + half + 1, max(0, xi - half):xi + half + 1]
        if box.size and float(box.max()) >= clip:
            continue
        n += 1
    return n


@dataclass
class TunePoint:
    exposure: float
    gain: Optional[float]
    count: Optional[int] = None   # None: skipped (a shorter exposure or lower gain was already over-exposed)
    level: Optional[str] = None
    t: Optional[float] = None     # when its frame ended (epoch s), for the log


class Tune(object):

    kind = 'tune'

    def __init__(self, exposures: list[float], gains: list[Optional[float]]) -> None:
        if not exposures or not gains:
            raise ValueError('a tune needs at least one exposure and one gain')
        # exposure-major: the short (fast) end of every gain first
        self.points = [TunePoint(float(e), g) for e in exposures for g in gains]
        self.ceiling = max(exposures)
        self._i = 0
        self._final: Optional[SearchStep] = None
        self._mid_gain = gains[len(gains) // 2]

    @property
    def exposure(self) -> float:
        return self._point().exposure

    @property
    def gain(self) -> Optional[float]:
        return self._point().gain

    @property
    def done(self) -> bool:
        return self._final is not None

    def _point(self) -> TunePoint:
        if self._final is not None:
            return TunePoint(self._final.exposure, self._final.gain)
        return self.points[self._i]

    def first(self) -> SearchStep:
        p = self.points[0]
        return SearchStep(p.exposure, False, self._progress(0), p.gain, step=1, of=len(self.points))

    def _progress(self, i: int) -> str:
        p = self.points[i]
        return MSG_TUNING.format(i + 1, len(self.points), where(p.exposure, p.gain))

    def step(self, star_count: int, level: str, t: Optional[float] = None) -> SearchStep:
        if self._final is not None:
            return self._final
        p = self.points[self._i]
        p.count, p.level, p.t = int(star_count), level, t
        return self._advance()

    def fail(self) -> SearchStep:
        """The camera refused the current point: mark it 'failed' (it never wins) and go on to the next."""
        if self._final is not None:
            return self._final
        self.points[self._i].level = 'failed'
        return self._advance()

    def _advance(self) -> SearchStep:
        self._i += 1
        while self._i < len(self.points) and self._dead(self.points[self._i]):
            self._i += 1
        if self._i >= len(self.points):
            return self._finish()
        nxt = self.points[self._i]
        return SearchStep(nxt.exposure, False, self._progress(self._i), nxt.gain, step=self._i + 1,
                          of=len(self.points))

    def _dead(self, q: TunePoint) -> bool:
        """Over-exposed for sure: a point no longer and no higher in gain was already over (or bright)."""
        for p in self.points:
            if p.level in ('over', 'bright') and p.exposure <= q.exposure and _le(p.gain, q.gain):
                return True
        return False

    def _finish(self) -> SearchStep:
        taken = [p for p in self.points if p.count is not None]
        usable = [p for p in taken if p.level == 'dark']
        best = max((p.count for p in usable), default=0)
        if best >= FOUND_STARS:
            good = [p for p in usable if p.count >= KNEE_FRACTION * best]
            p = min(good, key=lambda q: (q.exposure, _gain_key(q.gain)))
            final = SearchStep(p.exposure, True, MSG_TUNED.format(where(p.exposure, p.gain), p.count), p.gain,
                               found=True)
        elif any(p.level == 'bright' for p in taken):
            p = min((q for q in taken if q.level == 'bright'), key=lambda q: (q.exposure, _gain_key(q.gain)))
            final = SearchStep(p.exposure, True, MSG_BRIGHT, p.gain)
        elif usable:
            # no stars anywhere: the longest exposure that was not over, at mid gain if it got there
            longest = max(p.exposure for p in usable)
            at = [p for p in usable if p.exposure == longest]
            mid = [p for p in at if p.gain == self._mid_gain]
            p = mid[0] if mid else min(at, key=lambda q: _gain_key(q.gain))
            final = SearchStep(p.exposure, True, MSG_NO_STARS, p.gain)
        elif taken:
            # every point taken was over-exposed: the shortest, lowest gain
            p = min(taken, key=lambda q: (q.exposure, _gain_key(q.gain)))
            final = SearchStep(p.exposure, True, MSG_SHORTEST_OVER, p.gain)
        else:
            final = SearchStep(None, True, MSG_TUNE_REFUSED)  # the camera refused them all: stay where it is
        self._final = final
        return final

    def table(self) -> str:
        """The ladder as a log table: exposure, gain, stars, level, seconds since the previous point's frame."""
        rows = ['exposure_s  gain  stars  level   dt_s']
        prev = None
        for p in self.points:
            dt = '' if p.t is None or prev is None else '{0:.1f}'.format(p.t - prev)
            if p.t is not None:
                prev = p.t
            rows.append('{0:>10g}  {1:>4}  {2:>5}  {3:<6}  {4}'.format(
                p.exposure, '-' if p.gain is None else '{0:g}'.format(p.gain),
                '-' if p.count is None else p.count, p.level or 'skip', dt))
        return '\n'.join(rows)


def _le(a: Optional[float], b: Optional[float]) -> bool:
    return a is None or b is None or a <= b


def _gain_key(g: Optional[float]) -> float:
    return -math.inf if g is None else g


def where(exposure: float, gain: Optional[float]) -> str:
    """'0.4 s at gain 150', or '0.4 s' when the gain is the camera's own."""
    if gain is None:
        return '{0:g} s'.format(exposure)
    return '{0:g} s at gain {1:g}'.format(exposure, gain)
