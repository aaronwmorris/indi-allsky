"""Exposure search: double until stars show, halve while over-exposed."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


FOUND_STARS = 5

# Starting thresholds, as fractions of full scale. Tune on real scenes.
OVER_FRACTION = 0.80
BRIGHT_FRACTION = 0.15

MAX_CEILING_S = 15.0
SHORTEST_FLOOR_S = 1e-6  # the shortest exposure when the one given is 0 or less

MSG_NO_STARS = 'No stars to measure. Try a longer exposure.'
MSG_SHORTEST_OVER = 'The camera\'s shortest exposure is still over-exposed.'
MSG_BRIGHT = 'The picture is bright enough to focus on picture contrast.'


@dataclass(frozen=True)
class SearchStep:
    exposure: float | None  # the exposure to use next; on done, the one the search settled on
    done: bool
    message: str
    gain: float | None = None  # the gain to use with it; None: keep the gain (this search never changes it)
    found: bool = False  # on done: the search settled where there are stars to pick
    step: int | None = None  # the tune's point being taken (1-based), for the page's step bar; None: no count
    of: int | None = None  # how many points the tune has


def brightness(gray: np.ndarray, full_scale: float) -> str:
    """Return 'over', 'bright' or 'dark' from the median level of the picture."""
    level = float(np.median(gray)) / float(full_scale)

    if level >= OVER_FRACTION:
        return 'over'

    if level >= BRIGHT_FRACTION:
        return 'bright'

    return 'dark'


def default_ceiling(ccd_exposure_max: float | None) -> float:
    """CCD_EXPOSURE_MAX from config, or 15 s, whichever is lower."""
    if ccd_exposure_max is None:
        return MAX_CEILING_S

    return min(float(ccd_exposure_max), MAX_CEILING_S)


class ExposureSearch(object):

    kind = 'exposure_search'
    gain = None  # never changes the gain

    def __init__(self, shortest: float, ceiling: float, start: float) -> None:
        # doubling 0 stays 0, so a search from 0 (or below, or NaN) would never finish: floor them
        self.shortest = float(shortest) if float(shortest) > 0 else SHORTEST_FLOOR_S
        self.ceiling = max(float(ceiling), self.shortest)
        self.exposure = float(start) if float(start) > 0 else self.shortest
        self._final: SearchStep | None = None

    def _finish(self, message: str, found: bool = False) -> SearchStep:
        self._final = SearchStep(self.exposure, True, message, found=found)
        return self._final

    def first(self) -> None:
        """The step that starts the search: none, it starts at the exposure the session already has."""
        return None

    def step(self, star_count: int, level: str, t: float | None = None) -> SearchStep:
        if self._final is not None:
            return self._final

        if level == 'over':
            if self.exposure <= self.shortest:
                self.exposure = self.shortest
                return self._finish(MSG_SHORTEST_OVER)

            self.exposure = max(self.exposure / 2, self.shortest)
            return SearchStep(
                self.exposure,
                False,
                'Over-exposed. Trying {0:g} s.'.format(self.exposure),
            )

        if star_count >= FOUND_STARS:
            return self._finish('Found {0:d} stars at {1:g} s.'.format(star_count, self.exposure), found=True)

        if level == 'bright':
            return self._finish(MSG_BRIGHT)

        if self.exposure >= self.ceiling:
            self.exposure = self.ceiling
            return self._finish(MSG_NO_STARS)

        self.exposure = min(self.exposure * 2, self.ceiling)
        return SearchStep(
            self.exposure,
            False,
            'No stars yet. Trying {0:g} s.'.format(self.exposure),
        )
