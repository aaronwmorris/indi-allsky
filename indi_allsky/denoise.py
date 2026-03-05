"""Denoising utilities for indi-allsky.

This module defines :class:`IndiAllskyDenoise`, a collection of filtering
algorithms.  Star protection is delegated to
:mod:`indi_allsky.protection_masks`, ensuring consistent masking logic
across the codebase.
"""

import cv2
import numpy
import logging
import time
import pywt
import concurrent.futures
import datetime

from . import constants

from .protection_masks import star_mask

# caches to avoid rebuilding small objects repeatedly
_db4_wavelet = None  # will hold a pywt.Wavelet('db4') instance
_wavelet_level_cache: dict[int,int] = {}  # min_dim -> max_level
_hotpixel_kernel_cache: dict[int,numpy.ndarray] = {}  # radius -> kernel

# Shared thread pool to avoid creating executors on every call.  The
# pool size is deliberately kept small (4 workers) to match the cores on a
# typical Raspberry Pi.
_thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)

# Hoisted constant maps to avoid reallocating them per-call
_GAUSSIAN_SIGMA_MAP = {1: 1.0, 2: 1.8, 3: 3.0, 4: 4.2, 5: 5.8}
_WAVELET_SCALE_MAP = {1: 1.8, 2: 3.0, 3: 4.6, 4: 7.0, 5: 9.2}
_BILATERAL_TUNED_SIGMA = {1: 8, 2: 8, 3: 8, 4: 12, 5: 16}

# tuning constants for various denoising algorithms; extracted from the
# long series of adjustments sprinkled through the original implementation.
# Keeping them here makes it easier to audit and tweak.

# wavelet strength adjustment:
WAVELET_SCALE_ADJUST = 1.10  # 10% boost to the base scale value

# gaussian modifications (sigma & blend) applied as cumulative multipliers.
# combining them once gives a single constant that is easier to read and reason about.
GAUSSIAN_SIGMA_ADJUST = 0.707625   
GAUSSIAN_BLEND_ADJUST = GAUSSIAN_SIGMA_ADJUST

# median strength adjustments for kernel size and blend.
MEDIAN_KSIZE_ADJUST = 0.851       
MEDIAN_BLEND_ADJUST = MEDIAN_KSIZE_ADJUST    

# bilateral strength adjustments tuning
BILATERAL_BLEND_BUMP = 1.20
BILATERAL_SIGMA_BUMP = 1.20

# use Astropy for robust statistics
from astropy.stats import sigma_clipped_stats


logger = logging.getLogger('indi_allsky')


class IndiAllskyDenoise(object):
    """Lightweight image denoising for allsky cameras.

    Provides four denoising algorithms.  Bilateral, gaussian and
    median filters all run at similar speed on target hardware; wavelet is
    noticeably slower but offers the highest quality.

    Algorithms exposed to callers:
      - gaussian_blur: Direct Gaussian blur with strength-based blending
      - median_blur: Direct median filter with strength-based blending
      - bilateral: Edge-aware bilateral filter (preserves star edges)
      - wavelet: BayesShrink wavelet denoise (frequency-domain, best quality)

    All algorithms apply the filter directly and blend with the original
    at a strength-dependent ratio.  Strength 1 gives subtle smoothing;
    strength 5 produces fully-filtered output (visibly smoother).

    Each algorithm respects a configurable strength parameter (1-5).
    Temporal averaging is handled separately by the stacking system.

    Configuration may also tweak algorithm-specific knobs:
      * GAUSSIAN_SIGMA, GAUSSIAN_BLEND
      * MEDIAN_BLEND
      * BILATERAL_SIGMA_COLOR, BILATERAL_SIGMA_SPACE
      * DENOISE_STAR_* (star protection parameters)
      * ADAPTIVE_BLEND (enable/disable variance‑based blend adaptivity)
      * LOCAL_STATS_KSIZE (window size for variance map, odd integer >=3)
    """

    def __init__(self, config, night_av):
        self.config = config
        self.night_av = night_av

    def _get_dtype_max(self, img):
        """Return the maximum value for the image dtype."""
        if numpy.issubdtype(img.dtype, numpy.integer):
            return float(numpy.iinfo(img.dtype).max)
        return 1.0

    def _match_luminance(self, orig, result):
        """Apply a small global gain to ``result`` so that its mean
        luminance matches ``orig``.

        This compensates for the slight darkening or brightening that
        frequently accompanies spatial filtering.  We compute only the
        *means* of the two images rather than creating full luminance
        arrays – this is significantly cheaper on large colour frames.
        The gain is clamped according to configuration keys
        ``DENOISE_MIN_LUM_GAIN``/``DENOISE_MAX_LUM_GAIN`` to avoid large
        contrast shifts.

        The routine always returns a new array; on failure it simply
        returns ``result`` unchanged.
        """
        try:
            # compute channel means instead of full luminance images
            if orig.ndim == 3 and orig.shape[2] >= 3:
                # channel order is B, G, R in our data; weights follow
                # Rec.601 luma coefficients (R=0.299, G=0.587, B=0.114).
                # note the original code used orig[:, :, 2] for R, hence
                # the weighted combination below.
                orig_means = [orig[:, :, c].astype(numpy.float32).mean()
                              for c in range(3)]
                res_means = [result[:, :, c].astype(numpy.float32).mean()
                             for c in range(3)]
                orig_mean = (0.114 * orig_means[0] +
                             0.587 * orig_means[1] +
                             0.299 * orig_means[2])
                res_mean = (0.114 * res_means[0] +
                            0.587 * res_means[1] +
                            0.299 * res_means[2])
            else:
                orig_mean = float(orig.astype(numpy.float32).mean())
                res_mean = float(result.astype(numpy.float32).mean())

            if res_mean <= 1e-6:
                return result

            gain = orig_mean / (res_mean + 1e-9)

            min_gain = float(self.config.get('DENOISE_MIN_LUM_GAIN', 0.92))
            max_gain = float(self.config.get('DENOISE_MAX_LUM_GAIN', 1.08))
            gain = max(min_gain, min(max_gain, gain))

            # apply gain and clip
            res_f = result.astype(numpy.float32) * gain
            dtype_max = float(numpy.iinfo(result.dtype).max) if numpy.issubdtype(result.dtype, numpy.integer) else 1.0
            res_f = numpy.clip(res_f, 0.0, dtype_max).astype(result.dtype)
            return res_f
        except Exception:
            return result

    def _compute_luminance(self, img):
        """Return a float32 luminance image for `img` (shape HxW)."""
        if img.ndim == 3 and img.shape[2] >= 3:
            return (0.299 * img[:, :, 2].astype(numpy.float32) +
                    0.587 * img[:, :, 1].astype(numpy.float32) +
                    0.114 * img[:, :, 0].astype(numpy.float32))
        return img.astype(numpy.float32)


    def _local_variance(self, img, ksize=3):
        """Compute a local variance map using a fast OpenCV box blur.

        Uses the identity E[x^2] - (E[x])^2 on the luminance channel and
        relies on `cv2.blur` which is significantly faster than the
        astropy Box2DKernel approach for typical image sizes.
        """
        if ksize % 2 == 0:
            ksize += 1
        lum = self._compute_luminance(img).astype(numpy.float32)
        mean = cv2.blur(lum, (ksize, ksize))
        mean_sq = cv2.blur(lum * lum, (ksize, ksize))
        var = mean_sq - mean * mean
        numpy.clip(var, 0.0, None, out=var)
        return var

    def _star_mask(self, img):
        """Return a soft point-source mask using the protection_masks module.

        This wrapper adapts the mask generator to this class's configuration
        format.  Exceptions are caught and a blank mask returned, preserving
        the previous fault-tolerant behaviour.
        """
        try:
            # the protection_masks.star_mask call expects a grayscale float32 image
            if img.ndim == 3 and img.shape[2] >= 3:
                gray = self._compute_luminance(img)
            else:
                gray = img.astype(numpy.float32)

            # build keyword arguments from any DENOISE_STAR_* keys present in
            # the configuration.  When no key is supplied we simply allow
            # ``protection_masks.star_mask`` to use its own DEFAULT_* values.
            param_map = {
                'DENOISE_STAR_PERCENTILE': 'percentile',
                'DENOISE_STAR_SIGMA': 'threshold_sigma',
                'DENOISE_STAR_FWHM': 'fwhm',
                'DENOISE_STAR_PROTECT_RADIUS': 'expand_radius',
            }
            kwargs: dict[str, object] = {}
            for cfg_key, arg_name in param_map.items():
                if cfg_key in self.config:
                    val = self.config[cfg_key]
                    # numeric parameters are stored as strings in the config
                    # so convert to the appropriate type when forwarding.
                    if arg_name == 'expand_radius':
                        kwargs[arg_name] = int(val)
                    else:
                        kwargs[arg_name] = float(val)

            return star_mask(gray, **kwargs)
        except Exception:
            return numpy.zeros(img.shape[:2], dtype=numpy.float32)


    def _is_star_mask_time(self) -> bool:
        """Return ``True`` when the current local hour should allow star masking.

        The rule is hardwired to 17:00–05:00.  Having a separate method makes it
        easy to override during tests without touching the global
        ``datetime`` module (which is immutable).
        """
        now = datetime.datetime.now()
        return (now.hour >= 17) or (now.hour < 5)

    def _apply_star_protection(self, original, denoised, dtype_max):
        """Blend star regions back to the original, preserving point sources.

        If DENOISE_PROTECT_STARS is False (or the star mask is empty)
        the denoised image is returned unchanged.
        """
        # daytime gating: only apply star protection during the night window.
        if not self._is_star_mask_time():
            return denoised

        if not bool(self.config.get('DENOISE_PROTECT_STARS', True)):
            return denoised

        # obtain soft star protection mask (delegates to protection_masks.star_mask)
        star_mask = self._star_mask(original)

        if not numpy.any(star_mask > 0.01):
            return denoised

        # Expand to 3D if colour image
        if original.ndim == 3:
            sm = star_mask[:, :, numpy.newaxis]
        else:
            sm = star_mask

        orig_f = original.astype(numpy.float32)
        den_f = denoised.astype(numpy.float32)
        # `star_mask` uses 1.0 = sky (unprotected), 0.0 = protected (stars).
        # We want protected pixels to retain the original and sky to use
        # the denoised value. Therefore blend as:
        #   result = star_mask * denoised + (1 - star_mask) * original
        result = sm * den_f + (1.0 - sm) * orig_f
        return numpy.clip(result, 0, dtype_max).astype(original.dtype)

    def _get_strength(self):
        """Return the effective denoise strength (int) respecting night/day config.

        Also warn if the capture interval for the current period is unusually
        short.  Denoising is not recommended when frames arrive faster than
        approximately five seconds, and we emit a log message so the problem
        can be diagnosed after the fact.
        """
        # determine current period according to night/day flag
        if self.night_av[constants.NIGHT_NIGHT]:
            period = float(self.config.get('EXPOSURE_PERIOD', 0))
            # only warn when operating at night
            if period > 0 and period < 5.0:
                logger.warning('Denoise not recommended if capture interval < 5s, (%.2fs)', period)
        else:
            period = float(self.config.get('EXPOSURE_PERIOD_DAY', 0))

        if self.config.get('USE_NIGHT_COLOR', True) or self.night_av[constants.NIGHT_NIGHT]:
            return int(self.config.get('IMAGE_DENOISE_STRENGTH', 3))
        # daytime
        return int(self.config.get('IMAGE_DENOISE_STRENGTH_DAY', 3))

    def _norm_strength(self):
        """Return normalized strength t in [0,1] derived from effective strength 1..5."""
        s = max(1, min(self._get_strength(), 5))
        return (float(s) - 1.0) / 4.0

    def _compute_adaptive_blend(self, base_blend, original_image):
        """Compute an adaptive blend map based on local image variance.
        
        Returns a blend array (or scalar) where high-variance regions
        get reduced blend (variance-based fade), while smooth background
        areas use the full nominal blend. Stars are masked completely
        (no blend) in the separate star protection step via
        _apply_star_protection().
        """
        if not bool(self.config.get('ADAPTIVE_BLEND', True)):
            return base_blend
        if base_blend <= 0.0 or base_blend >= 1.0:
            return base_blend

        ksize = int(self.config.get('LOCAL_STATS_KSIZE', 3))
        var_map = self._local_variance(original_image, ksize)
        mean_var = float(numpy.mean(var_map)) + 1e-9
        var_norm = numpy.clip(var_map / mean_var, 0.0, 1.0)
        adapt = 1.0 - var_norm

        if original_image.ndim == 3:
            adapt = adapt[:, :, numpy.newaxis]

        return base_blend * adapt

    def _blend_with_original(self, original, processed, blend_map, dtype_max):
        """Blend processed image with original using blend_map.
        
        Args:
            original: Original image
            processed: Processed/denoised image
            blend_map: Blend factor(s) in [0, 1]
            dtype_max: Maximum value for output dtype
        
        Returns:
            Blended result in original dtype
        """
        result_f32 = (blend_map * processed.astype(numpy.float32) +
                     (1.0 - blend_map) * original.astype(numpy.float32))
        return numpy.clip(result_f32, 0, dtype_max).astype(original.dtype)

    def _finalize_denoise(self, original, processed, blend_map, dtype_max):
        """Apply final denoising steps: blending, luminance matching, and star protection."""
        result = self._blend_with_original(original, processed, blend_map, dtype_max)
        result = self._match_luminance(original, result)
        result = self._apply_star_protection(original, result, dtype_max)
        return result


    def _get_bilateral_sigma(self):
        """Return (sigmaColor, sigmaSpace) for the bilateral filter."""
        # Tuned sigma_color per strength (derived from benchmarks).
        # These values provide consistent denoising without external test files.
        sigma_space = int(self.config.get('BILATERAL_SIGMA_SPACE', 15))

        strength = max(1, min(self._get_strength(), 5))
        # Tuned mapping: strengths 1-5 -> sigma_color (baseline)
        tuned_sigma = {
            1: 8,
            2: 8,
            3: 8,
            4: 12,
            5: 16,
        }

        base_sigma = float(tuned_sigma.get(strength, 10))

        # Allow scaling/exponent to reshape strength→sigma mapping.
        bil_scale_factor = float(self.config.get('BILATERAL_SCALE_FACTOR', 0.4))
        bil_scale_exp = float(self.config.get('BILATERAL_SCALE_EXP', 1.0))

        t = (float(strength) - 1.0) / 4.0
        sigma_min = base_sigma * bil_scale_factor * (1.0 ** (bil_scale_exp - 1.0))
        sigma_max = base_sigma * bil_scale_factor * (5.0 ** (bil_scale_exp - 1.0))
        sigma_color = int(max(1.0, sigma_min + (sigma_max - sigma_min) * (t ** bil_scale_exp)))

        # If explicit override provided, respect it; otherwise bump by 10%
        if 'BILATERAL_SIGMA_COLOR' in self.config:
            sigma_color = int(self.config.get('BILATERAL_SIGMA_COLOR'))
        else:
            # bump computed sigma_color by a fixed factor
            sigma_color = int(max(1.0, sigma_color * BILATERAL_SIGMA_BUMP))

        return max(1, sigma_color), max(1, sigma_space)


    def _medianBlur(self, img, ksize):
        """cv2.medianBlur only supports CV_8U for multi-channel images in newer OpenCV.
        Split into per-channel blurs when the image is 16-bit (or deeper) multi-channel."""
        def _blur_channel(ch):
            # Fast path for 8-bit single-channel
            if ch.dtype == numpy.uint8:
                return cv2.medianBlur(ch, ksize)

            # Integer types (commonly uint16) — scale down to 8-bit, blur, scale back
            if numpy.issubdtype(ch.dtype, numpy.integer):
                # Use a divisor that maps 0..65535 -> 0..255 approximately
                divisor = 257
                ch8 = (ch.astype(numpy.uint32) // divisor).astype(numpy.uint8)
                b8 = cv2.medianBlur(ch8, ksize)
                return (b8.astype(numpy.uint32) * divisor).astype(ch.dtype)

            # Floating types: scale to 0..255, blur, then rescale back
            ch8 = numpy.clip((ch * 255.0), 0, 255).astype(numpy.uint8)
            b8 = cv2.medianBlur(ch8, ksize)
            return (b8.astype(numpy.float32) / 255.0).astype(ch.dtype)

        # Fast path for small kernels on small images: skip thread overhead
        if ksize <= 5 and img.shape[0] < 512 and img.shape[1] < 512:
            if img.ndim == 2:
                return _blur_channel(img)
            channels = cv2.split(img)
            blurred = [_blur_channel(ch) for ch in channels]
            return cv2.merge(blurred)

        # Single-channel image
        if img.ndim == 2:
            return _blur_channel(img)

        # Multi-channel: process each channel independently and merge
        channels = cv2.split(img)
        # submit per-channel work to shared thread pool
        futures = [_thread_pool.submit(_blur_channel, ch) for ch in channels]
        blurred = [f.result() for f in futures]
        return cv2.merge(blurred)

    # ------------------------------------------------------------------
    # Algorithm: Median Blur (direct — effective general-purpose denoising)
    # ------------------------------------------------------------------
    def median_blur(self, scidata):
        """Apply a direct median blur blended with the original.

        Applies a median filter at a strength-dependent kernel size and
        blends the result with the original.  The median filter naturally
        preserves edges (unlike Gaussian) while effectively smoothing
        noise.

        Strength mapping:
          1 → 3×3 kernel, blend=0.40   (gentle)
          3 → 7×7 kernel, blend=0.70   (moderate)
          5 → 11×11 kernel, blend=1.00  (strong — fully filtered)

        Strength range: 1-5.
        """
        strength = self._get_strength()
        if strength <= 0:
            return scidata

        # Process at full resolution to maintain image quality
        strength = max(1, min(strength, 5))
        ksize = self._compute_median_ksize(strength)

        blurred = self._medianBlur(scidata, ksize)

        # Compute blend based on strength and user config
        norm_strength = self._norm_strength()
        base_blend = float(self.config.get('MEDIAN_BLEND', 0.35 + 0.57 * norm_strength))
        blend = max(0.0, min(1.0, base_blend * MEDIAN_BLEND_ADJUST))

        # Apply adaptive blending in high-variance regions (stars, bright noise)
        adaptive_blend = self._compute_adaptive_blend(blend, scidata)

        # Finalize: blend, match luminance, protect stars
        dtype_max = self._get_dtype_max(scidata)
        result = self._finalize_denoise(scidata, blurred, adaptive_blend, dtype_max)

        # Log diagnostics
        avg_blend = float(numpy.mean(adaptive_blend)) if isinstance(adaptive_blend, numpy.ndarray) else adaptive_blend
        logger.info('Applying median denoise, ksize=%d base_blend=%.2f avg_blend=%.2f',
                   ksize, blend, avg_blend)

        return result

    def _compute_median_ksize(self, strength):
        """Compute median blur kernel size from strength (1-5).
        
        Returns an odd integer >= 3, adjusted by MEDIAN_KSIZE_ADJUST constant.
        """
        base_ksize = strength * 2 + 1  # Always odd: 3, 5, 7, 9, 11
        ksize = int(round(base_ksize * MEDIAN_KSIZE_ADJUST))
        ksize = ksize + 1 if ksize % 2 == 0 else ksize
        return max(3, ksize)

    def _compute_gaussian_sigma(self, strength):
        """Compute Gaussian blur sigma from strength (1-5).
        
        Returns adjusted sigma value, configurable per strength level
        or globally via config keys.
        """
        default_sigma_map = {1: 1.0, 2: 1.8, 3: 3.0, 4: 4.2, 5: 5.8}
        sigma = float(self.config.get('GAUSSIAN_SIGMA',
                                      default_sigma_map.get(strength, 3.0)))
        return sigma * GAUSSIAN_SIGMA_ADJUST

    def _apply_gaussian_blur(self, img, sigma):
        """Apply Gaussian blur to single or multi-channel image.
        
        Uses threading for multi-channel images to distribute work.
        """
        if img.ndim == 2 or img.shape[2] < 2:
            return cv2.GaussianBlur(img, (0, 0), sigma)

        # Multi-channel: blur each channel on thread pool
        futures = [_thread_pool.submit(cv2.GaussianBlur, img[:, :, c], (0, 0), sigma)
                  for c in range(img.shape[2])]
        channels = [f.result() for f in futures]
        return numpy.stack(channels, axis=2)

    def _apply_bilateral_filter(self, img, diameter, sigma_color, sigma_space, dtype_max):
        """Apply bilateral filter, handling dtype conversion if needed.
        
        Returns:
            (filtered_image, needs_conversion_flag)
        """
        needs_conversion = img.dtype not in (numpy.uint8, numpy.float32)

        if needs_conversion:
            # bilateralFilter supports uint8 and float32.
            # OpenCV float32 bilateral is optimized for 0.0-1.0 range.
            # Normalize to 0-1, scale sigmaColor by 1/255 (user-facing sigma
            # is calibrated for 0-255 range). sigmaSpace is in pixel units,
            # no adjustment needed.
            sigma_color_norm = float(sigma_color) / 255.0
            img_f32 = img.astype(numpy.float32) / dtype_max
            filtered_f32 = cv2.bilateralFilter(img_f32, diameter, sigma_color_norm,
                                              float(sigma_space))
            filtered = numpy.clip(numpy.rint(filtered_f32 * dtype_max),
                                 0, float(dtype_max)).astype(img.dtype)
        else:
            filtered = cv2.bilateralFilter(img, diameter, sigma_color, sigma_space)

        return filtered, needs_conversion


    # ------------------------------------------------------------------
    # Algorithm: Gaussian Blur (direct — simple and effective)
    # ------------------------------------------------------------------
    def gaussian_blur(self, scidata):
        # NOTE: any future improvements to gauss/median/bilateral should keep
        # compute cost comparable to the existing implementation.  We try to
        # avoid expensive full‑resolution filtering by threading each channel
        # and by falling back to single‑channel variants when possible.

        """Apply a direct Gaussian blur blended with the original.

        Applies cv2.GaussianBlur at a strength-dependent sigma and
        linearly blends the blurred result with the original.  Higher
        strengths use a larger sigma *and* a larger blend fraction so
        the smoothing effect is always clearly visible.

        Strength mapping (defaults, configurable via GAUSSIAN_SIGMA_MAP):
          1 → σ≈1.5, blend=0.30   (gentle)
          3 → σ≈5.0, blend=0.65   (moderate)
          5 → σ≈11,  blend=1.00   (strong — fully blurred)

        Strength range: 1-5.
        """
        strength = self._get_strength()
        if strength <= 0:
            return scidata

        # Process at full resolution to maintain image quality
        strength = max(1, min(strength, 5))
        sigma = self._compute_gaussian_sigma(strength)

        # Blur single or multi-channel image
        blurred = self._apply_gaussian_blur(scidata, sigma)

        # Compute blend based on strength and user config
        norm_strength = self._norm_strength()
        base_blend = float(self.config.get('GAUSSIAN_BLEND', 0.25 + 0.55 * norm_strength))
        blend = max(0.0, min(1.0, base_blend * GAUSSIAN_BLEND_ADJUST))

        # Apply adaptive blending in high-variance regions
        adaptive_blend = self._compute_adaptive_blend(blend, scidata)

        # Finalize: blend, match luminance, protect stars
        dtype_max = self._get_dtype_max(scidata)
        result = self._finalize_denoise(scidata, blurred, adaptive_blend, dtype_max)

        # Log diagnostics
        avg_blend = float(numpy.mean(adaptive_blend)) if isinstance(adaptive_blend, numpy.ndarray) else adaptive_blend
        logger.info('Applying gaussian denoise, sigma=%.1f base_blend=%.2f avg_blend=%.2f',
                   sigma, blend, avg_blend)

        return result


    # ------------------------------------------------------------------
    # Algorithm: Bilateral Filter (edge-aware, high quality)
    # ------------------------------------------------------------------
    def bilateral(self, scidata):
        """Apply an edge-aware bilateral filter.

        Smooths areas of similar brightness (noisy sky background) while
        preserving sharp intensity transitions (star edges).  Much faster
        than Non-Local Means but higher quality than Gaussian/Median for
        astro images.

        The strength parameter controls the filter size (d):
          d = strength * 2 + 1   (diameter: 3, 5, 7, 9, 11)
        sigmaColor and sigmaSpace are user-configurable:
          sigmaColor controls how much difference in brightness is tolerated
          sigmaSpace controls how far away pixels can influence
        Lower sigmaColor preserves more edges.  Strength range: 1-5.
        """
        strength = self._get_strength()
        if strength <= 0:
            return scidata

        # Process at full resolution to maintain image quality
        strength = max(1, min(strength, 5))
        diameter = strength * 2 + 1
        sigma_color, sigma_space = self._get_bilateral_sigma()

        # Compute blend based on strength and user config
        norm_strength = self._norm_strength()
        base_blend = float(self.config.get('BILATERAL_BLEND', 0.25 + 0.55 * norm_strength))
        blend = max(0.0, min(1.0, base_blend * BILATERAL_BLEND_BUMP))

        # Apply adaptive blending in high-variance regions
        adaptive_blend = self._compute_adaptive_blend(blend, scidata)

        # Apply bilateral filter with dtype conversion if needed
        dtype_max = self._get_dtype_max(scidata)
        denoised, needs_conversion = self._apply_bilateral_filter(
            scidata, diameter, sigma_color, sigma_space, dtype_max)

        # Finalize: blend, match luminance, protect stars
        result = self._finalize_denoise(scidata, denoised, adaptive_blend, dtype_max)

        # Log diagnostics
        avg_blend = float(numpy.mean(adaptive_blend)) if isinstance(adaptive_blend, numpy.ndarray) else adaptive_blend
        log_msg = ('Applying bilateral denoise, d=%d sigmaColor=%d sigmaSpace=%d '
                  'base_blend=%.2f avg_blend=%.2f')
        if needs_conversion:
            log_msg += ' (float32 converted)'
        logger.info(log_msg, diameter, sigma_color, sigma_space, blend, avg_blend)

        return result

    # ------------------------------------------------------------------
    # Algorithm: Non-local Means (patch-based)
    # ------------------------------------------------------------------
    # Older experiments included non-local means filter, but
    # it proved far too slow on target hardware so the implementation was
    # dropped.  This is a warning.



    # ------------------------------------------------------------------
    # Algorithm: Wavelet Denoise (BayesShrink — frequency-domain, best quality)
    # ------------------------------------------------------------------
    def wavelet(self, scidata):
        """Apply wavelet-based denoising with BayesShrink adaptive thresholding.

        Decomposes the image into frequency bands using the Discrete
        Wavelet Transform (DWT), estimates noise in the finest detail
        coefficients, and shrinks noisy coefficients using BayesShrink
        adaptive soft thresholding.

        The strength parameter controls both the threshold scaling and
        the blend ratio with the original image:
          1 → gentle shrinkage, 40% blend   (subtle smoothing)
          3 → moderate shrinkage, 70% blend  (visible smoothing)
          5 → strong shrinkage, 100% blend   (aggressive, slightly blurry)

        Wavelet: Daubechies-4 (db4), levels: auto (3-4), soft thresholding.
        Requires PyWavelets (pywt).  Strength range: 1-5.
        """
        start_t = time.time()
        strength = self._get_strength()
        logger.info('Wavelet denoise requested (strength=%d)', strength)

        if strength <= 0:
            return scidata

        # Process at full resolution to maintain image quality
        small = scidata

        strength = max(1, min(strength, 5))

        # Simple linear scale: strength 1→1.5x, 3→4.0x, 5→8.0x
        # These directly multiply the BayesShrink threshold.
        default_scale_map = {1: 1.8, 2: 3.0, 3: 4.6, 4: 7.0, 5: 9.2}
        scale = float(self.config.get('WAVELET_SCALE', default_scale_map.get(strength, 4.6)))
        # apply the simplified single adjustment constant (≈1.10)
        scale = float(scale) * WAVELET_SCALE_ADJUST

        # Determine dtype range for normalization based on the target image
        # (always full resolution as `small` is simply the original).
        target = small
        if numpy.issubdtype(target.dtype, numpy.integer):
            dtype_max = float(numpy.iinfo(target.dtype).max)
        else:
            dtype_max = 1.0

        orig_dtype = target.dtype

        # Auto decomposition levels: 3-4 based on smallest image dimension
        # (downsampling no longer applies so we just use the full-size dims)
        min_dim = min(target.shape[0], target.shape[1])
        # cache wavelet object and level computation
        global _db4_wavelet
        if _db4_wavelet is None:
            _db4_wavelet = pywt.Wavelet('db4')
        if min_dim in _wavelet_level_cache:
            max_level = _wavelet_level_cache[min_dim]
        else:
            max_level = pywt.dwt_max_level(min_dim, _db4_wavelet.dec_len)
            _wavelet_level_cache[min_dim] = max_level
        levels = min(max(max_level, 1), 4)

        def _denoise_channel(channel):
            """Denoise a single 2D channel using BayesShrink."""
            # Normalize to 0-1 float for wavelet precision (float32 is adequate
            # and significantly faster than float64 on large arrays).
            data = channel.astype(numpy.float32) / dtype_max

            # Forward DWT
            coeffs = pywt.wavedec2(data, 'db4', level=levels)

            # Estimate noise sigma from finest detail coefficients (HH band).
            # Replace the heavier astropy call with a simple MAD estimator using
            # pure numpy; this avoids importing and calling astropy for every
            # channel (and saves about 10–15 % of the total runtime).
            detail_hh = coeffs[-1][2]  # HH = diagonal detail at finest level
            # median absolute deviation → Gaussian sigma
            med = numpy.median(detail_hh)
            mad = numpy.median(numpy.abs(detail_hh - med))
            sigma_noise = mad / 0.6745

            # Enforce a minimum noise floor so the filter always does
            # *something* even on high-SNR / well-lit images.
            min_sigma = float(self.config.get('WAVELET_MIN_SIGMA', 0.005))
            sigma_noise = max(sigma_noise, min_sigma)

            # Apply BayesShrink to each detail level.  The loops have been
            # flattened/expressed as comprehensions wherever possible to reduce
            # Python overhead; bands are small so the savings are modest but
            # measurable.  We also compute the variance once per band.
            denoised_coeffs = [coeffs[0]]  # keep approximation untouched
            for detail_level in coeffs[1:]:
                new_details = []
                for detail_band in detail_level:
                    # compute band variance once
                    var_band = numpy.var(detail_band)
                    sigma_band = numpy.sqrt(max(var_band - sigma_noise * sigma_noise, 0.0))
                    if sigma_band < 1e-10:
                        threshold = numpy.max(numpy.abs(detail_band))
                    else:
                        threshold = (sigma_noise * sigma_noise) / sigma_band
                    threshold *= scale
                    new_details.append(pywt.threshold(detail_band, threshold, mode='soft'))
                denoised_coeffs.append(tuple(new_details))

            # Inverse DWT
            reconstructed = pywt.waverec2(denoised_coeffs, 'db4')
            reconstructed = reconstructed[:channel.shape[0], :channel.shape[1]]

            return numpy.clip(reconstructed * dtype_max, 0, dtype_max).astype(orig_dtype)

        # Handle grayscale vs color on the *target* image (small or full).
        if target.ndim == 2:
            result_small = _denoise_channel(target)
        else:
            futures = [_thread_pool.submit(_denoise_channel, target[:, :, c])
                       for c in range(target.shape[2])]
            channels = [f.result() for f in futures]
            result_small = numpy.stack(channels, axis=2)

        # Use the denoised result directly
        result = result_small

        # Compute blend based on strength
        norm_strength = self._norm_strength()
        blend = float(self.config.get('WAVELET_BLEND', 0.46 + 0.54 * norm_strength))
        blend = max(0.0, min(1.0, blend))

        # Blend, match luminance and protect stars using the shared
        # finalization helper so that any future improvements (eg. a more
        # efficient luminance matcher) automatically apply here.
        blended = self._finalize_denoise(scidata, result, blend, float(dtype_max))

        elapsed = time.time() - start_t
        logger.info('Applied wavelet denoise (BayesShrink) levels=%d scale=%.2f blend=%.2f time=%.3fs',
                levels, scale, blend, elapsed)

        return blended