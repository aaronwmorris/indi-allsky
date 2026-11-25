"""Synthetic RGGB frames for the measuring tests: Gaussian stars, Poisson and read noise, planted hot pixels and glints.

Every channel has the same response, so the gray conversion sees the star as drawn. Stars are integrated over each
pixel (not sampled at its centre), so a sigma 0.45 px star puts about half its light in one pixel, as a real one does.
"""

from __future__ import annotations

from typing import NamedTuple
from typing import Sequence

import numpy as np
from scipy.special import erf


SEED = 20261124

BACKGROUND = 1000.0
READ_NOISE = 8.0


class Star(NamedTuple):
    x: float          # pixel centres are at integer coordinates
    y: float
    sigma: float      # Gaussian sigma, px
    flux: float       # total electrons


class Glint(NamedTuple):
    x: float
    y: float
    radius: float
    level: float      # electrons per pixel added inside the disc


def _axis_weights(n: int, c: float, sigma: float) -> np.ndarray:
    """Fraction of a 1-D Gaussian at c that falls in each pixel [i - 0.5, i + 0.5)."""
    edges = (np.arange(n + 1, dtype=np.float64) - 0.5 - c) / (sigma * np.sqrt(2.0))
    return 0.5 * np.diff(erf(edges))


def light(shape: tuple[int, int], stars: Sequence[Star] = (), glints: Sequence[Glint] = ()) -> np.ndarray:
    """Noise-free signal (electrons) above the background."""
    h, w = shape
    img = np.zeros(shape, np.float64)
    for s in stars:
        img += s.flux * np.outer(_axis_weights(h, s.y, s.sigma), _axis_weights(w, s.x, s.sigma))
    if glints:
        yy, xx = np.mgrid[0:h, 0:w]
        for g in glints:
            img[(xx - g.x) ** 2 + (yy - g.y) ** 2 <= g.radius ** 2] += g.level
    return img


def frame(
    shape: tuple[int, int] = (256, 256),
    stars: Sequence[Star] = (),
    hot: Sequence[tuple[int, int, int]] = (),
    glints: Sequence[Glint] = (),
    background: float = BACKGROUND,
    read_noise: float = READ_NOISE,
    seed: int = SEED,
) -> np.ndarray:
    """An RGGB uint16 mosaic. `hot` is (y, x, value): that pixel is set to `value` after the noise."""
    rng = np.random.default_rng(seed)
    signal = background + light(shape, stars, glints)
    img = rng.poisson(signal).astype(np.float64) + rng.normal(0.0, read_noise, shape)
    for y, x, v in hot:
        img[y, x] = v
    return np.clip(np.round(img), 0, 65535).astype(np.uint16)


def grid_stars(
    shape: tuple[int, int],
    sigma: float,
    flux: float,
    spacing: int = 48,
    margin: int = 48,
    offset: tuple[float, float] = (0.3, 0.2),
) -> list[Star]:
    """Stars on a regular grid, each off the pixel centre by `offset`."""
    h, w = shape
    return [
        Star(x + offset[0], y + offset[1], sigma, flux)
        for y in range(margin, h - margin + 1, spacing)
        for x in range(margin, w - margin + 1, spacing)
    ]
