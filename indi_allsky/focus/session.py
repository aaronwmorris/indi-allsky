"""Focus session timeouts and the command ledger.

Single-threaded contract: nothing here takes a lock.  The controller calls
every method under its own lock.

Two clock domains, on purpose:

* ``SessionRules`` takes an object with ``now() -> float`` (monotonic seconds,
  see ``SessionClock``).  Timeouts must not jump with wall-clock changes.
* ``CommandLedger`` takes a zero-argument callable returning epoch seconds
  (default ``time.time``).  It is compared against frame end times from the
  camera, which are epoch seconds.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger('indi_allsky')

NO_PAGE_TIMEOUT_S = 120
IDLE_TIMEOUT_S = 900
IDLE_WARNING_S = 60
MAX_PAGES = 3


class SessionClock:
    """Monotonic clock; tests pass a fake with the same ``now()``."""

    def now(self) -> float:
        return time.monotonic()


class SessionRules:
    def __init__(self, clock=None):
        self._clock = clock if clock is not None else SessionClock()
        self.active = False
        self.end_reason: str | None = None
        self._pages: set = set()
        self._no_page_since = 0.0
        self._last_touch = 0.0

    def start(self) -> None:
        now = self._clock.now()
        self.active = True
        self.end_reason = None
        self._pages = set()
        self._no_page_since = now
        self._last_touch = now

    def end(self, reason: str) -> None:
        self.active = False
        self.end_reason = reason

    def page_connected(self, page_id) -> None:
        self._pages.add(page_id)

    def page_left(self, page_id) -> None:
        if page_id not in self._pages:
            return
        self._pages.discard(page_id)
        if not self._pages:
            self._no_page_since = self._clock.now()

    def touched(self) -> None:
        """Any admin command or keep_going."""
        self._last_touch = self._clock.now()

    def tick(self) -> str | None:
        """Return the end reason at most once; the rules are inactive afterwards."""
        if not self.active:
            return None
        now = self._clock.now()
        if not self._pages and now - self._no_page_since >= NO_PAGE_TIMEOUT_S:
            self.end('no_page')
        elif now - self._last_touch >= IDLE_TIMEOUT_S:
            self.end('idle')
        return self.end_reason if not self.active else None

    def idle_warning(self) -> float | None:
        """Seconds left before idle end, when inside the last IDLE_WARNING_S; else None."""
        if not self.active:
            return None
        remaining = IDLE_TIMEOUT_S - (self._clock.now() - self._last_touch)
        if 0 < remaining <= IDLE_WARNING_S:
            return float(remaining)
        return None


class CommandLedger:
    """Which lens-move commands had settled by a given exposure start (epoch seconds)."""

    def __init__(self, clock=None):
        self._clock = clock if clock is not None else time.time
        self._begun: set = set()
        self._effective_at: dict = {}  # cmd_id -> done + settle

    def begin(self, cmd_id: int) -> None:
        self._begun.add(cmd_id)

    def done(self, cmd_id: int, settle_s: float = 0.0) -> None:
        self._effective_at[cmd_id] = self._clock() + settle_s

    def effective_before(self, exposure_start: float) -> int:
        """Highest cmd_id with done + settle <= exposure_start; 0 if none."""
        ids = [c for c, t in self._effective_at.items() if t <= exposure_start]
        return max(ids) if ids else 0
