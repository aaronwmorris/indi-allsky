"""Autofocus: one continuous outward scan across a window around the lens, one fit, park.

A pure state machine: no threads, no I/O. It holds the stage, the window and the scan's samples; the controller
drives the lens and the fit and advances the stage:

    'start'  lens.move_to(start)                                       -> begin_scan()
    'scan'   lens.move_to(end, scan=True, max_rate=max_rate); add_frame() per frame inside the move -> begin_fit()
    'fit'    fit_curve(samples(), span=(start, end), limit=reachable) off the request path -> begin_park(fit)
    'park'   lens.move_to(round(fit.c))                                -> finish()

Any failure or a Stop goes straight to finish(message). Stages only move forward; a call out of order raises
RuntimeError, which is a controller bug.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from indi_allsky.focus.exposure_search import MSG_NO_STARS
from indi_allsky.focus.fit import MSG_FLAT
from indi_allsky.focus.fit import MSG_LIMIT
from indi_allsky.focus.fit import Fit


__all__ = ('STAGES', 'STAGE_WORDS', 'FRAME_SPAN_STEPS', 'MSG_NO_STARS', 'MSG_LIMIT', 'MSG_FLAT', 'Autofocus')

STAGES = ('start', 'scan', 'fit', 'park')
STAGE_WORDS = {'start': 'Moving to the start', 'scan': 'Scanning outward',
               'fit': 'Finding best focus', 'park': 'Moving to best focus'}
DONE = 'done'
FRAME_SPAN_STEPS = 8
FIT_ALLOWANCE_S = 3.0   # the estimate's allowance for the fit itself (about 2.5 s on a Pi 4)


class Autofocus:
    """One autofocus run. `here` is where the lens rests when it starts; `reachable` the (lo, hi) a target may be;
    `limit` the travel limit in steps; `exposure` the session's exposure in seconds; `speed` the driver's steps/s."""

    def __init__(self, *, here: int, reachable: tuple[int, int], limit: int, exposure: float, speed: float):
        if speed <= 0:
            raise ValueError('speed must be positive')
        lo, hi = int(min(reachable)), int(max(reachable))
        window = round(limit / 2)
        self.here = int(here)
        self.reachable = (lo, hi)
        self.window = window
        self.start = int(min(max(self.here - window, lo), hi))
        self.end = int(max(min(self.here + window, hi), self.start))
        self.speed = float(speed)
        self.exposure = float(exposure)
        self.max_rate = min(self.speed, FRAME_SPAN_STEPS / self.exposure) if self.exposure > 0 else self.speed
        self.stage = STAGES[0]
        self.fit: Optional[Fit] = None
        self.message: Optional[str] = None
        self._columns: list[np.ndarray] = []

    # --- reading ---------------------------------------------------------------------------------------------

    @property
    def done(self) -> bool:
        return self.stage == DONE

    @property
    def words(self) -> str:
        """The page's words for the stage; the outcome message once done."""
        return (self.message or '') if self.done else STAGE_WORDS[self.stage]

    def estimate_s(self, position: int, backlash: int) -> float:
        """Seconds for the whole run from `position`, rounded up: to the start (with the backlash leg), the paced
        scan, the fit, and back from the end to a best focus guessed at `here`."""
        t = ((abs(position - self.start) + backlash) / self.speed
             + (self.end - self.start) / self.max_rate
             + FIT_ALLOWANCE_S
             + abs(self.end - self.here) / self.speed)
        return float(math.ceil(t))

    def samples(self) -> np.ndarray:
        """(N, 3) float array of (x, star_id, size), every column in the order added."""
        if not self._columns:
            return np.empty((0, 3), dtype=float)
        return np.vstack(self._columns)

    def columns(self) -> int:
        """Frames that gave at least one star."""
        return len(self._columns)

    # --- feeding ---------------------------------------------------------------------------------------------

    def add_frame(self, x: float, rows: list[tuple[int, float]]) -> None:
        """One frame's column: every used star's (star_id, size), all at lens position x. Only during 'scan'.
        A frame with no stars adds nothing and is not a column."""
        self._require('scan')
        if not rows:
            return
        col = np.empty((len(rows), 3), dtype=float)
        col[:, 0] = x
        col[:, 1:] = np.asarray(rows, dtype=float).reshape(-1, 2)
        self._columns.append(col)

    # --- stages ----------------------------------------------------------------------------------------------

    def begin_scan(self) -> None:
        """The lens is at the start: scan outward to the end."""
        self._require('start')
        self.stage = 'scan'

    def begin_fit(self) -> Optional[str]:
        """The scan is over. Returns None to go on and fit, or the failure message (MSG_NO_STARS when no frame gave
        a star), in which case the run is finished and the controller sends the lens back to `here`."""
        self._require('scan')
        if not self._columns:
            self.finish(MSG_NO_STARS)
            return MSG_NO_STARS
        self.stage = 'fit'
        return None

    def begin_park(self, fit: Optional[Fit]) -> Optional[str]:
        """The fit is back. Returns None to park at round(fit.c), or the failure message (no curve, or the fit is
        not ok), in which case the run is finished and the controller sends the lens back to `here`. The fit is kept
        either way, so a not-ok curve can still be shown."""
        self._require('fit')
        self.fit = fit
        if fit is None:
            self.finish(MSG_FLAT)
            return MSG_FLAT
        if not fit.ok:
            self.finish(fit.message or MSG_FLAT)
            return self.message
        self.stage = 'park'
        return None

    def park_target(self) -> int:
        """Where to park: round(fit.c), inside the scanned window."""
        self._require('park')
        return int(min(max(round(self.fit.c), self.start), self.end))

    def finish(self, message: Optional[str] = None) -> None:
        """End the run from any stage: parked (no message), failed, or stopped. Idempotent; the first message
        stays."""
        if self.done:
            return
        self.stage = DONE
        self.message = message

    def _require(self, stage: str) -> None:
        if self.stage != stage:
            raise RuntimeError('autofocus is at %r, not %r' % (self.stage, stage))
