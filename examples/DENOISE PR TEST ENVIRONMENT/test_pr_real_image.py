#!/usr/bin/env python3
"""PR validation — real photograph.

Loads the real image from this directory and generates overlay / mask
images suitable for embedding in a pull request.  All outputs go to
``DENOISE PR TEST ENVIRONMENT/Test Output/``.

Run:
    python "DENOISE PR TEST ENVIRONMENT/test_pr_real_image.py"

Outputs (in DENOISE PR TEST ENVIRONMENT/Test Output/):
    real_01_input.png               – original image (resized if needed)
    real_02_star_mask.png           – star application mask (black holes at stars)
    real_06_overlay.png             – input + green contour (stars)
    real_08_denoised_comparison.png – side-by-side before / after
"""

from __future__ import annotations

import os
import sys
import time
import textwrap

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Path setup — imports come from the regular project tree (indi_allsky/)
# ---------------------------------------------------------------------------
_this_dir = os.path.abspath(os.path.dirname(__file__))
_project_root = os.path.abspath(os.path.join(_this_dir, '..'))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from indi_allsky import protection_masks as pm
from indi_allsky.protection_masks import (
    star_mask,
    _cached_star,
)
from scipy.ndimage import median_filter as _mfilt

# ---------------------------------------------------------------------------
# Output goes to "DENOISE PR TEST ENVIRONMENT/Test Output/"
# ---------------------------------------------------------------------------
OUT_DIR = os.path.join(_this_dir, 'Test Output')
os.makedirs(OUT_DIR, exist_ok=True)

# Allow overriding the input image via command-line argument
def _choose_image():
    import argparse
    p = argparse.ArgumentParser(description='real image PR validator')
    p.add_argument('image', nargs='?',
                   help='path to a test image (defaults to bundled test photo)')
    p.add_argument('--expand-radius', type=int, default=None,
                   help='optional: override star-mask expand_radius (pixels)')
    args = p.parse_args()
    # store CLI-provided expand radius for callers regardless of image
    _choose_image._expand_radius = args.expand_radius
    if args.image:
        if not os.path.isfile(args.image):
            print(f"ERROR: specified image not found: {args.image}")
            sys.exit(1)
        return args.image

    # Fallback: look for packaged test images
    candidates = [
        os.path.join(_this_dir, 'ccd1_20260301_224251.png'),
        os.path.join(_this_dir, 'test_image.jpg'),
    ]
    for pth in candidates:
        if os.path.isfile(pth):
            return pth
    print('ERROR: No input image found.  Looked for:')
    for pth in candidates:
        print(f'  {pth}')
    sys.exit(1)

IMAGE_PATH = _choose_image()

# Determine expand_radius: CLI argument overrides module default
from indi_allsky import protection_masks as _pm
_cli_expand = getattr(_choose_image, '_expand_radius', None)
if _cli_expand is not None:
    expand_radius = int(_cli_expand)
else:
    expand_radius = _pm.DEFAULT_EXPAND_RADIUS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save(name: str, img: np.ndarray):
    path = os.path.join(OUT_DIR, name)
    if img.dtype in (np.float32, np.float64):
        img = np.clip(img * 255, 0, 255).astype(np.uint8)
    cv2.imwrite(path, img)
    return path


def _mask_to_colour(mask: np.ndarray, cmap=cv2.COLORMAP_VIRIDIS) -> np.ndarray:
    u8 = np.clip(mask * 255, 0, 255).astype(np.uint8)
    return cv2.applyColorMap(u8, cmap)


def _overlay_contour(base_bgr: np.ndarray, mask: np.ndarray,
                     colour=(0, 255, 0), thickness=2) -> np.ndarray:
    vis = base_bgr.copy()
    binary = (mask > 0.05).astype(np.uint8) * 255
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(vis, contours, -1, colour, thickness)
    return vis


def _side_by_side(left: np.ndarray, right: np.ndarray,
                  label_left='Before', label_right='After') -> np.ndarray:
    h, w = left.shape[:2]
    bar_h = max(30, h // 30)
    font_scale = max(0.5, h / 1200)
    thickness = max(1, int(h / 600))

    bar1 = np.zeros((bar_h, w, 3), np.uint8)
    cv2.putText(bar1, label_left, (10, bar_h - 8), cv2.FONT_HERSHEY_SIMPLEX,
                font_scale, (255, 255, 255), thickness, cv2.LINE_AA)
    bar2 = np.zeros((bar_h, w, 3), np.uint8)
    cv2.putText(bar2, label_right, (10, bar_h - 8), cv2.FONT_HERSHEY_SIMPLEX,
                font_scale, (255, 255, 255), thickness, cv2.LINE_AA)
    return np.hstack([np.vstack([bar1, left]),
                      np.vstack([bar2, right])])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

class Results:
    def __init__(self):
        self.entries: list[tuple[str, bool, str]] = []

    def check(self, name: str, condition: bool, detail: str = ''):
        self.entries.append((name, condition, detail))
        status = 'PASS' if condition else '** FAIL **'
        print(f'  [{status}] {name}' + (f'  — {detail}' if detail else ''))

    @property
    def passed(self):
        return sum(1 for _, ok, _ in self.entries if ok)

    @property
    def failed(self):
        return sum(1 for _, ok, _ in self.entries if not ok)


def run():
    results = Results()

    print('\n' + '=' * 70)
    print('  Protection Masks — Real Image Validation')
    print('=' * 70)

    # ===== Load image =====
    print(f'\n--- Loading: {os.path.basename(IMAGE_PATH)} ---')
    img = cv2.imread(IMAGE_PATH, cv2.IMREAD_COLOR)
    if img is None:
        print('ERROR: cv2.imread returned None')
        return 1
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    h, w = gray.shape
    print(f'  Shape: {img.shape}  ({w}x{h})')
    _save('real_01_input.png', img)

    # ===== 1. Star mask =====
    print('\n--- 1. Star mask ---')
    _cached_star.cache_clear()
    t0 = time.perf_counter()
    # apply PSF checks: compactness, sharpness and elongation limits
    s_mask = star_mask(
        gray,
        percentile=99.0,
        # Use sharpness/elongation only (min_peak_ratio disabled because
        # many real images have low central-peak fractions after smoothing)
        min_sharpness=0.05,
        max_sharpness=10.0,
        max_elongation=4.0,
        expand_radius=expand_radius,
    )
    t_star = time.perf_counter() - t0

    n_stars = 0
    if s_mask.min() < 0.5:
        binary = (s_mask < 0.5).astype(np.uint8)
        n_stars, _ = cv2.connectedComponents(binary)
        n_stars -= 1

    results.check('star_mask shape', s_mask.shape == gray.shape)
    results.check('star_mask [0, 1]',
                  float(s_mask.min()) >= 0 and float(s_mask.max()) <= 1,
                  f'min={s_mask.min():.4f}  max={s_mask.max():.4f}')
    results.check('stars detected', n_stars > 5,
                  f'{n_stars} stars')
    results.check('soft Gaussian stamps', len(np.unique(s_mask)) > 2,
                  f'{len(np.unique(s_mask))} unique values')
    # expect elongated artifacts removed (heuristic: <10% of pixels protected)
    pct = np.count_nonzero(s_mask < 0.5) / s_mask.size * 100
    results.check('star mask sparsity <10%', pct < 10.0, f'{pct:.1f}%')

    _save('real_02_star_mask.png', s_mask)
    print(f'  Time: {t_star * 1000:.0f} ms  ({n_stars} stars detected)')

    # Nebula masking removed from pipeline (no diffuse-mask generated)

    # ===== 3. Star overlay (combined mask removed) =====
    print('\n--- 2. Star overlay (combined removed) ---')
    # Use the star mask directly for contour/heatmap overlays
    t0_overlay = time.perf_counter()
    overlay = _overlay_contour(img, 1.0 - s_mask, colour=(0, 255, 0), thickness=2)
    _save('real_06_overlay.png', overlay)
    t_overlay = time.perf_counter() - t0_overlay
    print(f'  Time: {t_overlay * 1000:.0f} ms')

    # heatmap overlays removed per request

    # ===== 3. All denoise methods (strength 5) with protection =====
    from indi_allsky.denoise import IndiAllskyDenoise

    denoise_cfg = {
        'IMAGE_DENOISE_STRENGTH': 5,
        'USE_NIGHT_COLOR': True,
        'DENOISE_PROTECT_STARS': True,
        'DENOISE_STAR_PERCENTILE': 99.0,
        'DENOISE_STAR_SIGMA': 3.0,
        'DENOISE_STAR_FWHM': 4.5,
        'ADAPTIVE_BLEND': True,
        'LOCAL_STATS_KSIZE': 3,
    }
    night_av = [False] * 20
    night_av[0] = True
    d = IndiAllskyDenoise(denoise_cfg, night_av)

    methods = [
        ('wavelet',       d.wavelet),
        ('bilateral',     d.bilateral),
        ('gaussian_blur', d.gaussian_blur),
        ('median_blur',   d.median_blur),
    ]
    timings = {}
    for idx, (name, fn) in enumerate(methods):
        print(f'\n--- 3{chr(97+idx)}. {name} (strength 5) with protection ---')
        t0 = time.perf_counter()
        denoised = fn(img.copy())
        elapsed = time.perf_counter() - t0
        timings[name] = elapsed

        results.check(f'{name} output shape', denoised.shape == img.shape)
        results.check(f'{name} output dtype', denoised.dtype == img.dtype)
        n_diff = np.count_nonzero(denoised != img)
        results.check(f'{name} image modified', not np.array_equal(denoised, img),
                      f'{n_diff:,} pixels differ')

        # ensure mean luminance is preserved (within a tolerance) so denoising
        # doesn't globally brighten/darken the frame
        def mean_lum(image):
            if image.ndim == 3 and image.shape[2] >= 3:
                # use the same Rec.601 weights as denoise._compute_luminance
                return (0.299 * image[:, :, 2].mean() +
                        0.587 * image[:, :, 1].mean() +
                        0.114 * image[:, :, 0].mean())
            return float(image.mean())
        orig_mean = mean_lum(img)
        den_mean = mean_lum(denoised)
        diff = abs(orig_mean - den_mean)
        results.check(f'{name} luminance match', diff < (orig_mean * 0.02 + 1e-6),
                      f'orig={orig_mean:.3f} den={den_mean:.3f} diff={diff:.3f}')

        # Save the denoised output itself (user requested methods returned)
        suffix = f'real_08{chr(97+idx)}_{name}.png'
        _save(suffix, denoised)
        # report timing immediately after the section
        print(f'  Time: {elapsed * 1000:.0f} ms  ({n_diff:,} px changed)')


    # Ridge-trace visualization removed (was part of Milky-Way/nebula mask)
    # No ridge computation or drawing is performed in the PR harness.

    # ===== 5. interval warning logging =====
    print('\n--- 5. interval warning logging ---')
    import io
    import logging
    from indi_allsky import constants as _const

    # temporarily shorten the night interval and capture log output
    original_period = d.config.get('EXPOSURE_PERIOD')
    d.config['EXPOSURE_PERIOD'] = 3.0

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.WARNING)
    logger = logging.getLogger('indi_allsky')
    logger.addHandler(handler)

    # run one denoise call (gaussian is representative)
    _ = d.gaussian_blur(img.copy())

    logger.removeHandler(handler)
    warn_log = buf.getvalue()
    results.check('interval warning logged', 'denoise not recommended' in warn_log.lower())

    # restore configuration
    if original_period is not None:
        d.config['EXPOSURE_PERIOD'] = original_period

    # ===== 4. Daytime gating for star mask =====
    # The denoiser should skip the relatively expensive star-mask step
    # between 05:00 and 16:59.  We verify that by monkey‑patching both the
    # clock and the mask generator and ensuring the latter is only
    # invoked at night.
    print('\n--- 4. star mask daytime gate ---')
    img_small = np.zeros((8, 8, 3), dtype=np.uint8)
    den_small = img_small.copy()
    dtype_max = 255.0

    orig_star = d._star_mask
    try:
        called = False
        def fake_mask(img):
            nonlocal called
            called = True
            return orig_star(img)
        d._star_mask = fake_mask

        # daytime → helper returns False
        d._is_star_mask_time = lambda: False
        _ = d._apply_star_protection(img_small, den_small, dtype_max)
        results.check('daytime star-mask skipped', not called)

        # night → helper returns True
        called = False
        d._is_star_mask_time = lambda: True
        _ = d._apply_star_protection(img_small, den_small, dtype_max)
        results.check('night star-mask executed', called)
    finally:
        d._star_mask = orig_star
        # restore original helper (not strictly needed but tidy)
        delattr(d, '_is_star_mask_time')

    # ===== 7. IndiAllskyDenoise integration =====
    print('\n--- 7. IndiAllskyDenoise star_mask integration ---')
    from indi_allsky.denoise import IndiAllskyDenoise

    # verify that an empty configuration delegates entirely to the
    # protection_masks.star_mask defaults (i.e. no hard-coded values).
    # Use the same luminance conversion the wrapper applies so the
    # comparison is apples-to-apples.
    from indi_allsky.protection_masks import star_mask as _pm_star

    cfg_empty = {
        'DENOISE_PROTECT_STARS': True,
    }
    d_empty = IndiAllskyDenoise(cfg_empty, [False])
    lum = d_empty._compute_luminance(img)   # wrapper's grayscale formula
    baseline = _pm_star(lum)                # call library default directly
    prot_empty = d_empty._star_mask(img)
    results.check('wrapper uses library defaults',
                  np.array_equal(prot_empty, baseline),
                  'star-mask mismatch with default parameters')

    cfg = {
        'DENOISE_PROTECT_STARS': True,
        'DENOISE_STAR_PERCENTILE': 99.0,
        'DENOISE_STAR_SIGMA': 3.0,
        'DENOISE_STAR_FWHM': 4.5,
    }
    d = IndiAllskyDenoise(cfg, [False])
    t0 = time.perf_counter()
    prot = d._star_mask(img)
    t_pipe = time.perf_counter() - t0

    results.check('pipeline mask shape', prot.shape == gray.shape)
    results.check('pipeline mask [0, 1]',
                  float(prot.min()) >= 0 and float(prot.max()) <= 1)
    results.check('pipeline non-trivial',
                  np.count_nonzero(prot) > 0,
                  f'{np.count_nonzero(prot):,} nonzero')
    print(f'  Time: {t_pipe * 1000:.0f} ms')

    # ===== Summary =====
    out_abs = os.path.abspath(OUT_DIR)
    print('\n' + '=' * 70)
    total = results.passed + results.failed
    print(f'  Results: {results.passed}/{total} passed  ({results.failed} failed)')
    print(f'  Output:  {out_abs}')
    print('=' * 70)

    print(textwrap.dedent(f"""\

PR images ({os.path.relpath(OUT_DIR, _project_root)}):
  real_01_input.png               Original input photograph
  real_02_star_mask.png           Star mask (black holes at stars, white sky)
    real_06_overlay.png             Input + green protection contour (stars)
  real_08a_wavelet.png            Denoised output: wavelet
  real_08b_bilateral.png          Denoised output: bilateral
  real_08c_gaussian_blur.png      Denoised output: gaussian_blur
  real_08d_median_blur.png        Denoised output: median_blur


"""))

    if results.failed:
        print('** THERE WERE FAILURES — see above **')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(run())
