#!/usr/bin/env python3
"""Diagnostic test to verify that denoising methods respect protection masks."""

import sys
import os

# Add workspace to path
ws_path = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ws_path)

import numpy as np
import time
from PIL import Image
from indi_allsky.denoise import IndiAllskyDenoise
from indi_allsky.protection_masks import star_mask

# Load test image
img_path = os.path.join(os.path.dirname(__file__), 'Test Output', 'real_01_input.png')
img_pil = Image.open(img_path)
img = np.array(img_pil, dtype=np.float32)

# Normalize if needed
if img.max() > 1.0:
    img /= 255.0

# Compute luminance for mask generation
from cv2 import cvtColor, COLOR_RGB2GRAY
if img.ndim == 3:
    lum = cvtColor((img * 255).astype(np.uint8), COLOR_RGB2GRAY).astype(np.float32) / 255.0
else:
    lum = img

# Generate protection masks
print("Generating star mask...")
sm = star_mask(lum, threshold_sigma=3.0, fwhm=4.5)
print(f"  Star mask: min={sm.min():.4f}, max={sm.max():.4f}, mean={sm.mean():.4f}")
print(f"  Protected pixels (star_mask ~= 0): {np.count_nonzero(sm < 0.1)}")

# Combined mask (star mask only)
combined = sm
print(f"\nCombined mask: min={combined.min():.4f}, max={combined.max():.4f}")
print(f"  Protected pixels (combined ~= 0): {np.count_nonzero(combined < 0.1)}")
print(f"  Unprotected pixels (combined ~= 1): {np.count_nonzero(combined > 0.9)}")

# Create denoise engine
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

# Get the protection mask that the denoise engine builds
print("\n" + "="*70)
print("Protection mask built by denoise engine:")
protection = d._build_protection_mask(img)
print(f"  Type: {type(protection)}, dtype: {protection.dtype}")
print(f"  Shape: {protection.shape}")
print(f"  Min={protection.min():.4f}, max={protection.max():.4f}, mean={protection.mean():.4f}")
print(f"  Protected pixels (~= 0): {np.count_nonzero(protection < 0.1)}")
print(f"  Unprotected pixels (~= 1): {np.count_nonzero(protection > 0.9)}")

# Test denoising and check if protected regions stay unchanged
print("\n" + "="*70)
print("Testing if protected regions are preserved during denoise:")

# Convert to uint8 for denoise (it expects that)
img_uint8 = (img * 255).astype(np.uint8) if img.max() <= 1.0 else img.astype(np.uint8)

methods = ['gaussian_blur', 'bilateral', 'wavelet', 'median_blur']
for method_name in methods:
    print(f"\n--- {method_name} ---")
    method = getattr(d, method_name)
    
    # Denoise
    t0 = time.perf_counter()
    denoised = method(img_uint8.copy())
    elapsed = time.perf_counter() - t0
    
    # Convert back to float for comparison
    denoised_f = denoised.astype(np.float32) / 255.0 if denoised.max() > 1 else denoised.astype(np.float32)
    img_f = img_uint8.astype(np.float32) / 255.0 if img_uint8.max() > 1 else img_uint8.astype(np.float32)
    
    # Check differences in protected vs unprotected regions
    if img_f.ndim == 3:
        prot_mask_2d = protection
        # For color images, check each channel
        for c in range(img_f.shape[2]):
            ch_orig = img_f[:, :, c]
            ch_den = denoised_f[:, :, c]
            
            # Pixels where protection should apply (mask < 0.1)
            protected_area = prot_mask_2d < 0.1
            unprotected_area = prot_mask_2d > 0.9
            
            diff_protected = np.abs(ch_orig[protected_area] - ch_den[protected_area])
            diff_unprotected = np.abs(ch_orig[unprotected_area] - ch_den[unprotected_area])
            
            print(f"  Channel {c}:")
            print(f"    Protected area - mean diff: {diff_protected.mean():.6f}, max diff: {diff_protected.max():.6f}")
            print(f"    Unprotected area - mean diff: {diff_unprotected.mean():.6f}, max diff: {diff_unprotected.max():.6f}")
            
            # Check if protected pixels are actually unchanged
            unchanged_in_protected = np.count_nonzero(diff_protected < 1e-6)
            total_protected = np.count_nonzero(protected_area)
            pct_unchanged = 100.0 * unchanged_in_protected / max(total_protected, 1)
            print(f"    Protected pixels unchanged: {unchanged_in_protected}/{total_protected} ({pct_unchanged:.1f}%)")
    
    print(f"  Time: {elapsed:.3f}s")

print("\n" + "="*70)
print("Diagnosis complete.")
