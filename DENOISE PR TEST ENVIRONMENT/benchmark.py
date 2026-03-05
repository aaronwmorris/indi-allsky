#!/usr/bin/env python3
"""Denoise pipeline performance benchmark.

Measures wall-clock time for each stage of the protection-mask and
denoise pipeline against the real MW test image.  Results are printed
as a table and appended to ``benchmark_history.csv`` so regressions
or improvements can be tracked over time.

Run:
    python "DENOISE PR TEST ENVIRONMENT/benchmark.py"

Baseline (2026-03-01, pre-optimisation):
    Star mask .............. ~13 s   (8389 stars @ threshold_sigma=1.5)
    MW mask ................ ~20 s
    Full pipeline (build) .. ~14 s   (star + MW concurrent)
    Wavelet denoise ........ ~16 s
    Bilateral denoise ...... ~14 s
    Gaussian denoise ....... ~11 s
    Median denoise ......... ~21 s

After sensitivity reduction + separable Gaussian (DAOStarFinder):
    Star mask .............. ~7 s    (2340 stars @ threshold_sigma=3.0)
    Full pipeline (build) .. ~12 s

After CV2 matched-filter star detector (DAOStarFinder removed):
    Star mask .............. ~1 s    (1540 stars @ threshold_sigma=3.0)
    Full pipeline (build) .. ~1.1 s  (star completes before MW)

Target:
    Star mask .............. < 2 s
    Full pipeline (build) .. < 3 s
"""

from __future__ import annotations

import csv
import os
import sys
import time
from datetime import datetime

import cv2
import numpy as np

# ---------------------------------------------------------------------------
_this_dir = os.path.abspath(os.path.dirname(__file__))
_project_root = os.path.abspath(os.path.join(_this_dir, '..'))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from indi_allsky.protection_masks import (
    star_mask,
    milkyway_mask,
    _cached_star,
)
from indi_allsky.denoise import IndiAllskyDenoise

# ---------------------------------------------------------------------------
HISTORY_CSV = os.path.join(_this_dir, 'benchmark_history.csv')
IMAGE_PATH = os.path.join(_this_dir, 'milkyway_noisy_test.jpg')

# Baseline times (seconds) — updated 2026-03-01 after CV2 matched-filter.
# Any stage exceeding 1.5× its baseline triggers a warning.
BASELINES = {
    'star_mask':      1.5,
    'milkyway_mask':  20.0,
    'build_pipeline': 32.0,
    'wavelet':        28.0,
    'bilateral':      23.0,
    'gaussian_blur':  22.0,
    'median_blur':    20.0,
}

WARN_FACTOR = 1.5   # warn if time > baseline × this


def _timeit(label, fn, *args, **kwargs):
    """Run *fn*, return (result, elapsed_seconds)."""
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    elapsed = time.perf_counter() - t0
    return result, elapsed


def run():
    if not os.path.isfile(IMAGE_PATH):
        print(f'ERROR: Test image not found: {IMAGE_PATH}')
        return 1

    img = cv2.imread(IMAGE_PATH, cv2.IMREAD_COLOR)
    if img is None:
        print('ERROR: cv2.imread returned None')
        return 1

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    h, w = gray.shape

    print()
    print('=' * 70)
    print('  Denoise Pipeline Benchmark')
    print(f'  Image: {w}×{h}  ({os.path.basename(IMAGE_PATH)})')
    print(f'  Date:  {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 70)

    timings: dict[str, float] = {}
    extras: dict[str, str] = {}

    # ----- Star mask -----
    _cached_star.cache_clear()
    s_mask, t = _timeit('star_mask', star_mask, gray, percentile=99.0)
    n_stars = 0
    if s_mask.min() < 0.5:
        binary = (s_mask < 0.5).astype(np.uint8)
        n_stars, _ = cv2.connectedComponents(binary)
        n_stars -= 1
    timings['star_mask'] = t
    extras['star_mask'] = f'{n_stars} stars'

    # ----- Milky Way mask -----
    mw_mask, t = _timeit('milkyway_mask', milkyway_mask, gray, star_m=s_mask, percentile=60.0)
    coverage = np.count_nonzero(mw_mask < 0.99) / mw_mask.size * 100
    timings['milkyway_mask'] = t
    extras['milkyway_mask'] = f'{coverage:.1f}% coverage'

    # ----- Full pipeline (_build_protection_mask) -----
    cfg = {
        'DENOISE_PROTECT_STARS': True,
        'DENOISE_PROTECT_MILKYWAY': True,
        'DENOISE_MILKYWAY_PERCENTILE': 60.0,
        'DENOISE_MILKYWAY_BOX_SIZE': 128,
        'DENOISE_MILKYWAY_FILTER_SIZE': 5,
        'DENOISE_STAR_PERCENTILE': 99.0,
        'DENOISE_STAR_SIGMA': 3.0,
        'DENOISE_STAR_FWHM': 4.5,
        'IMAGE_DENOISE_STRENGTH': 5,
        'USE_NIGHT_COLOR': True,
        'ADAPTIVE_BLEND': True,
        'LOCAL_STATS_KSIZE': 3,
    }
    night_av = [False] * 20
    night_av[0] = True

    _cached_star.cache_clear()
    d = IndiAllskyDenoise(cfg, night_av)
    _, t = _timeit('build_pipeline', d._build_protection_mask, img)
    timings['build_pipeline'] = t

    # ----- Denoise methods -----
    for name, fn in [('wavelet', d.wavelet),
                     ('bilateral', d.bilateral),
                     ('gaussian_blur', d.gaussian_blur),
                     ('median_blur', d.median_blur)]:
        _cached_star.cache_clear()
        _, t = _timeit(name, fn, img.copy())
        timings[name] = t

    # ----- Print results -----
    print()
    print(f'  {"Stage":<20s}  {"Time (s)":>9s}  {"Baseline":>9s}  {"Δ":>7s}  {"Status":<8s}  Notes')
    print(f'  {"-" * 20}  {"-" * 9}  {"-" * 9}  {"-" * 7}  {"-" * 8}  -----')

    warnings = 0
    for stage, elapsed in timings.items():
        baseline = BASELINES.get(stage, None)
        if baseline:
            delta = elapsed - baseline
            delta_str = f'{delta:+.2f}s'
            if elapsed > baseline * WARN_FACTOR:
                status = 'SLOW'
                warnings += 1
            elif elapsed < baseline * 0.7:
                status = 'FAST'
            else:
                status = 'OK'
        else:
            delta_str = ''
            status = ''
        note = extras.get(stage, '')
        print(f'  {stage:<20s}  {elapsed:>9.2f}s  {baseline or 0:>8.1f}s  {delta_str:>7s}  {status:<8s}  {note}')

    print()
    total = sum(timings.values())
    print(f'  Total wall-clock: {total:.1f}s')
    if warnings:
        print(f'  ⚠ {warnings} stage(s) exceeded {WARN_FACTOR:.1f}× baseline')

    # ----- Append to CSV history -----
    write_header = not os.path.isfile(HISTORY_CSV)
    with open(HISTORY_CSV, 'a', newline='') as f:
        fieldnames = ['timestamp'] + list(BASELINES.keys()) + ['total', 'stars']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        row = {'timestamp': datetime.now().isoformat()}
        row.update(timings)
        row['total'] = total
        row['stars'] = extras.get('star_mask', '')
        writer.writerow(row)
    print(f'  History saved to: {os.path.relpath(HISTORY_CSV, _project_root)}')

    print()
    print('=' * 70)
    return 0


if __name__ == '__main__':
    sys.exit(run())
