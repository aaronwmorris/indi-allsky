#!/usr/bin/env python3
"""ASI676MC RAW16 detector, repairer, and calibration tool.

What goes wrong in a bad frame
------------------------------
An ordinary one-shot-color sensor does not deliver ready-made RGB pixels.  It
delivers one brightness number per photosite through a repeating 2x2 pattern:

    R  G1
    G2 B

This is called an RGGB Bayer mosaic.  ``RAW16`` means those numbers are stored
as unsigned 16-bit values, normally from 0 (black) to 65535 (full scale).

The exact low-level camera, firmware, driver, or USB cause of the intermittent
ASI676MC failure is not known.  What is known from paired bad and normal FITS
captures is the repeatable corruption present in the delivered pixel data:

* the Bayer mosaic is displaced by one sensor row;
* R, G1, G2, and B are multiplied by four different, stable factors;
* the weakened green values make red plus blue dominate, so the image looks
  strongly purple or magenta;
* in bright areas, one or both damaged green samples can hit the RAW ceiling.
  Clipping destroys their original value, so those samples need a conservative
  estimate from the surviving red, blue, and neighboring green information.

In other words, this tool does not claim to fix the unknown hardware/driver
cause.  It recognizes and reverses the consistent corruption in the resulting
RAW mosaic.

How the repair works
--------------------
For a detected bad frame the tool:

1. moves the mosaic back by one row;
2. divides each RGGB parity by its measured bad-frame gain;
3. reconstructs clipped green samples from neighboring G2 plus the surviving
   red/blue relationship;
4. measures the repaired frame again;
5. writes a new FITS file only if the purple signature has disappeared.

Normal frames take a detection-only path and are never changed.  Input FITS
files are never overwritten unless a user explicitly chooses an already-used
output name together with ``--overwrite``.

The script has two intentionally separate workflows:

* Give it one FITS file to inspect and, when the purple-frame signature is
  present, write a repaired RAW16 RGGB FITS copy.
* Give it a folder with ``--calibrate`` to classify captures, match each bad
  frame to nearby normal frames with the same capture settings, measure the
  camera-specific repair constants, and write a report for manual entry.

Calibration is conservative.  It requires at least seven independently
detected failures and at least one distinct matched normal frame per failure.
Before/bad/after triplets are preferred because they suppress scene changes.
Mixed cameras, capture settings, weak signature separation, and insufficient
highlight evidence are reported rather than silently producing constants.

Only Python, NumPy, and Astropy are required.  The script does not connect to
indi-allsky, a database, or a web service.  All working constants are visible
in the definition block below.

Reading guide
-------------
The file follows the same order as the work performed:

1. validate settings and classify the four RGGB Bayer parities;
2. repair a single failed RAW16 mosaic and verify the result;
3. read and match a folder of bad/normal FITS captures;
4. estimate gains, clipping, and highlight-transition values;
5. validate the rounded recommendations and write a text report;
6. expose those two workflows through the command line.

The calibration code deliberately favors explainable, conservative estimates
over fitting every last sample.  A recommendation is not emitted unless the
supplied evidence passes all checks near ``validate_evidence()``.
"""

import argparse
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from functools import lru_cache
from pathlib import Path
import re
import statistics
import time

import numpy


# ---------------------------------------------------------------------------
# User-adjustable definitions
# ---------------------------------------------------------------------------
#
# Keep every value that affects detection, repair, or calibration in this
# block.  A user can copy calibrated values from the text report into these
# definitions when testing the repair utility, or type them into fields with
# the same names on indi-allsky's Image settings page.

DEFAULT_SETTINGS = {
    # Detection requires all three ratios to pass.  Requiring three related
    # symptoms makes a naturally red or blue scene much less likely to trigger
    # a false repair.
    'PURPLE_RATIO_THRESHOLD': 1.5,
    'RED_SIDE_RATIO_THRESHOLD': 1.25,
    'BLUE_SIDE_RATIO_THRESHOLD': 1.5,

    # Detection inspects every 32nd pixel in each Bayer parity.  The even step
    # is important: an odd step would jump between R, G1, G2, and B positions.
    'SAMPLE_STEP': 32,

    # Source green values at or above this number are treated as clipped.  The
    # camera's observed RAW16 plateau is 65534; a little headroom catches all
    # values that belong to that plateau.
    'SOURCE_SATURATION_THRESHOLD': 65000,

    # These are the multipliers observed in the broken data stream.  Repair
    # divides each parity by its value.  G1 and G2 are listed separately because
    # the two physical green positions are affected differently.
    'GAIN_R': 0.91004,
    'GAIN_G1': 1.68652,
    'GAIN_G2': 1.09238,
    'GAIN_B': 0.59537,

    # In a clipped highlight, low/high describes how balanced red and blue are.
    # Below START the conservative factor-two estimate is kept.  Between START
    # and END the estimate blends smoothly toward the stronger color channel.
    'HIGHLIGHT_BLEND_START_RATIO': 0.55,
    'HIGHLIGHT_BLEND_END_RATIO': 0.75,

    # Large images are processed in strips so a Raspberry Pi does not need
    # several full-resolution temporary arrays at the same time.
    'CHUNK_ROWS': 128,
}

CALIBRATION_OPTIONS = {
    # Evidence requirements.
    'MIN_BAD_PAIRS': 7,
    'MIN_GOOD_BAD_RATIO': 1.0,
    'RECOMMENDED_GOOD_BAD_RATIO': 2.0,
    'MAX_PAIR_SECONDS': 90.0,
    'MIN_EXPOSURE_LEVELS': 2,

    # Sparse central-image sampling.  This is even to preserve Bayer parity.
    'SAMPLE_STEP': 8,
    'MIN_REFERENCE_VALUE': 512,
    'MAX_REFERENCE_VALUE': 62000,
    'MAX_SOURCE_VALUE_FOR_GAIN': 64000,
    'MAX_REFERENCE_CHANGE_FRACTION': 0.15,
    'REFERENCE_CHANGE_FLOOR': 256,
    'MIN_GAIN_SAMPLES_PER_PARITY': 500,

    # A RAW16 plateau near 65534 is expected.  Values close to the existing
    # 65000 threshold are deliberately snapped to that proven default.
    'SATURATION_HEADROOM': 534,
    'SATURATION_DEFAULT_SNAP': 64,

    # Highlight-boundary search.  The repair uses an 800-step equivalent
    # base/high fixed point, so finer search increments would not create
    # meaningfully finer output.
    'BLEND_START_VALUES': (
        0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70,
    ),
    'BLEND_END_VALUES': (
        0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95,
    ),
    'MIN_BLEND_WIDTH': 0.10,
    'MIN_HIGHLIGHT_SAMPLES_TOTAL': 1000,
    'MIN_HIGHLIGHT_SAMPLES_PER_PAIR': 50,
    'HIGHLIGHT_REFERENCE_MIN': 4096,
    # Do not replace a proven default with a neighboring grid point unless it
    # improves the cross-pair score by more than two percent.  This guards
    # against fitting cloud movement or a small number of transition pixels.
    'PREFER_DEFAULT_SCORE_TOLERANCE': 0.02,

}


# Integer scales used by the clipped-highlight blend.
#
# BASE_SCALE=800 represents the default transition boundaries exactly:
# low/high=0.55 maps to base/high=719/800, while 0.75 maps to 775/800.
# WEIGHT_MAX=255 represents a blend weight from 0 to 1 using integer
# arithmetic: 0 keeps the conservative green estimate, 255 uses the strongest
# red/blue channel, and intermediate values blend smoothly between them.
#
# These are fixed implementation details.  They are not camera-specific
# measurements and should not be calibrated or changed by users.
_HIGHLIGHT_BLEND_BASE_SCALE = 800
_HIGHLIGHT_BLEND_WEIGHT_MAX = 255

# These labels are copied from indi-allsky's Image settings page.  Keeping the
# report in user-interface language means users do not have to guess how the
# internal constant names map to the visible form.
CONFIG_ENTRY_LABELS = (
    ('PURPLE_RATIO_THRESHOLD', 'Purple Ratio Threshold'),
    ('RED_SIDE_RATIO_THRESHOLD', 'Red-side Ratio Threshold'),
    ('BLUE_SIDE_RATIO_THRESHOLD', 'Blue-side Ratio Threshold'),
    ('SOURCE_SATURATION_THRESHOLD', 'Source Saturation Threshold'),
    ('GAIN_R', 'Bad-frame Gain R'),
    ('GAIN_G1', 'Bad-frame Gain G1'),
    ('GAIN_G2', 'Bad-frame Gain G2'),
    ('GAIN_B', 'Bad-frame Gain B'),
    ('HIGHLIGHT_BLEND_START_RATIO', 'Highlight Blend Start Ratio'),
    ('HIGHLIGHT_BLEND_END_RATIO', 'Highlight Blend End Ratio'),
    ('SAMPLE_STEP', 'Signature Sample Step'),
    ('CHUNK_ROWS', 'Repair Chunk Rows'),
)

_FITS_SUFFIXES = ('.fit', '.fits', '.fts')
_COMPRESSED_FITS_SUFFIXES = tuple(
    '{0}.gz'.format(suffix)
    for suffix in _FITS_SUFFIXES
)
_CAMERA_NAME_RE = re.compile(
    r'(?<![A-Z0-9])ASI[\s_-]*676MC(?![A-Z0-9])',
    re.IGNORECASE,
)
_OTHER_ASI_CAMERA_RE = re.compile(
    r'(?<![A-Z0-9])ASI[\s_-]*(?!676MC)[0-9]+[A-Z]*',
    re.IGNORECASE,
)
_FILENAME_TIME_RE = re.compile(r'(\d{8})[_-](\d{6})')


# ---------------------------------------------------------------------------
# Shared detection and repair implementation
# ---------------------------------------------------------------------------


def normalize_settings(settings=None):
    """Merge and validate repair settings."""
    config = dict(DEFAULT_SETTINGS)
    if settings:
        config.update(settings)

    normalized = {
        'PURPLE_RATIO_THRESHOLD': float(config['PURPLE_RATIO_THRESHOLD']),
        'RED_SIDE_RATIO_THRESHOLD': float(
            config['RED_SIDE_RATIO_THRESHOLD']
        ),
        'BLUE_SIDE_RATIO_THRESHOLD': float(
            config['BLUE_SIDE_RATIO_THRESHOLD']
        ),
        'SAMPLE_STEP': int(config['SAMPLE_STEP']),
        'SOURCE_SATURATION_THRESHOLD': int(
            config['SOURCE_SATURATION_THRESHOLD']
        ),
        'GAIN_R': float(config['GAIN_R']),
        'GAIN_G1': float(config['GAIN_G1']),
        'GAIN_G2': float(config['GAIN_G2']),
        'GAIN_B': float(config['GAIN_B']),
        'HIGHLIGHT_BLEND_START_RATIO': float(
            config['HIGHLIGHT_BLEND_START_RATIO']
        ),
        'HIGHLIGHT_BLEND_END_RATIO': float(
            config['HIGHLIGHT_BLEND_END_RATIO']
        ),
        'CHUNK_ROWS': int(config['CHUNK_ROWS']),
    }

    for key in (
        'PURPLE_RATIO_THRESHOLD',
        'RED_SIDE_RATIO_THRESHOLD',
        'BLUE_SIDE_RATIO_THRESHOLD',
        'GAIN_R',
        'GAIN_G1',
        'GAIN_G2',
        'GAIN_B',
    ):
        if normalized[key] <= 0:
            raise ValueError(f'{key} must be greater than zero')

    if normalized['SAMPLE_STEP'] < 2 or normalized['SAMPLE_STEP'] % 2:
        raise ValueError('SAMPLE_STEP must be an even number of at least two')
    if normalized['CHUNK_ROWS'] < 2 or normalized['CHUNK_ROWS'] % 2:
        raise ValueError('CHUNK_ROWS must be an even number of at least two')

    saturation = normalized['SOURCE_SATURATION_THRESHOLD']
    if saturation < 1 or saturation > 65535:
        raise ValueError(
            'SOURCE_SATURATION_THRESHOLD must be between 1 and 65535'
        )

    start = normalized['HIGHLIGHT_BLEND_START_RATIO']
    end = normalized['HIGHLIGHT_BLEND_END_RATIO']
    if start <= 0 or start >= 1:
        raise ValueError(
            'HIGHLIGHT_BLEND_START_RATIO must be between zero and one'
        )
    if end <= 0 or end > 1:
        raise ValueError(
            'HIGHLIGHT_BLEND_END_RATIO must be greater than zero and at most one'
        )
    if start >= end:
        raise ValueError(
            'HIGHLIGHT_BLEND_START_RATIO must be less than '
            'HIGHLIGHT_BLEND_END_RATIO'
        )
    _highlight_blend_base_boundaries(start, end)

    return normalized


@lru_cache(maxsize=64)
def _highlight_blend_base_boundaries(start_ratio, end_ratio):
    """Map low/high boundary ratios to factor-two base/high fixed points."""
    def base_ratio(channel_ratio):
        """Convert low/high chroma ratio to the Method-5 base/high ratio."""
        return 1.0 - (((1.0 - channel_ratio) ** 2) / 2.0)

    start = round(base_ratio(start_ratio) * _HIGHLIGHT_BLEND_BASE_SCALE)
    end = round(base_ratio(end_ratio) * _HIGHLIGHT_BLEND_BASE_SCALE)
    if start >= end:
        raise ValueError(
            'highlight blend ratios are too close at fixed-point precision'
        )
    return start, end


def validate_raw_mosaic(data):
    """Reject data that cannot safely use the RAW16 RGGB repair."""
    if not isinstance(data, numpy.ndarray):
        raise ValueError('repair requires a NumPy array')
    if data.ndim != 2:
        raise ValueError('repair requires a two-dimensional RAW16 frame')
    if data.dtype.kind != 'u' or data.dtype.itemsize != 2:
        raise ValueError('repair requires unsigned 16-bit RAW data')
    if not data.flags.writeable:
        raise ValueError('repair requires a writable RAW frame')

    height, width = data.shape
    if height < 4 or width < 4:
        raise ValueError('repair requires at least four rows and columns')
    if height % 2 or width % 2:
        raise ValueError('repair requires even RAW frame dimensions')


def frame_signature(data, settings=None):
    """Measure the four Bayer parities and classify the purple failure."""
    validate_raw_mosaic(data)
    return _frame_signature(data, normalize_settings(settings))


def _frame_signature(data, config):
    """Compute the inexpensive central-frame failure signature.

    Sampling only the central half avoids the dark circular border of a
    fisheye image.  Every step is even, so each sample remains on the same
    RGGB parity.  The failure is declared only when all three independent
    color ratios cross their thresholds.
    """
    height, width = data.shape
    step = config['SAMPLE_STEP']
    y_start = (height // 4) & ~1
    y_stop = (3 * height // 4) & ~1
    x_start = (width // 4) & ~1
    x_stop = (3 * width // 4) & ~1

    # RGGB parity order is R, G1, G2, B.  Medians are robust to stars, hot
    # pixels, and small bright clouds that would distort a mean.
    medians = [
        float(numpy.median(data[
            y_start + row:y_stop:step,
            x_start + column:x_stop:step,
        ]))
        for row in range(2)
        for column in range(2)
    ]

    # A failed frame raises both red-side and blue-side measurements relative
    # to their neighboring greens.  Requiring the combined purple ratio plus
    # both side ratios avoids confusing a naturally red or blue scene with the
    # camera fault.
    green_sum = medians[1] + medians[2]
    purple_ratio = (
        (medians[0] + medians[3]) / green_sum
        if green_sum > 0
        else float('inf')
    )
    red_side_ratio = (
        medians[0] / medians[1] if medians[1] > 0 else float('inf')
    )
    blue_side_ratio = (
        medians[3] / medians[2] if medians[2] > 0 else float('inf')
    )
    is_bad = (
        purple_ratio >= config['PURPLE_RATIO_THRESHOLD']
        and red_side_ratio >= config['RED_SIDE_RATIO_THRESHOLD']
        and blue_side_ratio >= config['BLUE_SIDE_RATIO_THRESHOLD']
    )
    return {
        'parity_medians': medians,
        'purple_ratio': purple_ratio,
        'red_side_ratio': red_side_ratio,
        'blue_side_ratio': blue_side_ratio,
        'is_bad': is_bad,
    }


@lru_cache(maxsize=8)
def _build_lookup_tables(gains):
    """Precompute inverse-gain values for every possible RAW16 code.

    Table lookup is substantially cheaper than dividing twelve million pixels
    for every repaired ASI676MC frame, and the cache is shared across files.
    """
    values = numpy.arange(65536, dtype=numpy.float64)
    return tuple(
        numpy.rint(numpy.clip(values / gain, 0, 65535)).astype(numpy.uint16)
        for gain in gains
    )


def _pack_clipped_green_masks(data, saturation_threshold, chunk_rows):
    """Bit-pack G1-clipped and jointly-green-clipped source masks."""
    green1 = data[0::2, 1::2]
    green2 = data[1::2, 0::2]
    height, width = green1.shape
    rows_per_chunk = max(1, chunk_rows // 2)
    packed_width = (width + 7) // 8
    g1_packed = numpy.empty((height, packed_width), dtype=numpy.uint8)
    both_packed = numpy.empty((height, packed_width), dtype=numpy.uint8)

    # One bit per Bayer cell is enough.  At full ASI676MC resolution this saves
    # several megabytes compared with keeping two full boolean arrays alive
    # throughout repair.
    for row_start in range(0, height, rows_per_chunk):
        row_stop = min(row_start + rows_per_chunk, height)
        g1_clipped = green1[row_start:row_stop] >= saturation_threshold
        g2_clipped = green2[row_start:row_stop] >= saturation_threshold
        g1_packed[row_start:row_stop] = numpy.packbits(
            g1_clipped,
            axis=1,
        )
        numpy.logical_and(g1_clipped, g2_clipped, out=g2_clipped)
        both_packed[row_start:row_stop] = numpy.packbits(
            g2_clipped,
            axis=1,
        )
    return g1_packed, both_packed


def _reconstruct_clipped_green(
    data,
    green1_clipped_packed,
    both_green_clipped_packed,
    chunk_rows,
    highlight_blend_start_ratio,
    highlight_blend_end_ratio,
):
    """Reconstruct only source-clipped green samples in the RGGB mosaic."""
    red = data[0::2, 0::2]
    green1 = data[0::2, 1::2]
    green2 = data[1::2, 0::2]
    blue = data[1::2, 1::2]
    plane_height, plane_width = green1.shape
    plane_chunk_rows = max(1, chunk_rows // 2)
    blend_start, blend_end = _highlight_blend_base_boundaries(
        highlight_blend_start_ratio,
        highlight_blend_end_ratio,
    )

    for row_start in range(0, plane_height, plane_chunk_rows):
        row_stop = min(row_start + plane_chunk_rows, plane_height)
        rows = numpy.arange(row_start, row_stop)

        upper = green2[numpy.maximum(rows - 1, 0)].astype(numpy.uint32)
        lower = green2[rows].astype(numpy.uint32)
        estimate = numpy.empty(
            (row_stop - row_start, plane_width),
            dtype=numpy.uint16,
        )
        estimate[:, :-1] = numpy.rint(
            (
                upper[:, :-1]
                + upper[:, 1:]
                + lower[:, :-1]
                + lower[:, 1:]
            ) / 4.0
        ).astype(numpy.uint16)
        estimate[:, -1] = numpy.rint(
            (upper[:, -1] + lower[:, -1]) / 2.0
        ).astype(numpy.uint16)

        mask = numpy.unpackbits(
            green1_clipped_packed[row_start:row_stop],
            axis=1,
            count=plane_width,
        ).view(numpy.bool_)
        target = green1[row_start:row_stop]
        replace = mask & (estimate > target)
        target[replace] = estimate[replace]

        both_clipped = numpy.unpackbits(
            both_green_clipped_packed[row_start:row_stop],
            axis=1,
            count=plane_width,
        ).view(numpy.bool_)
        if not numpy.any(both_clipped):
            continue

        # Method 5: begin with the factor-two estimate, retain it at strongly
        # coloured boundaries, then blend toward max(red, blue) over the two
        # configured low/high ratios.  The operations reuse existing uint32
        # buffers so this extra refinement does not require another image-sized
        # temporary array.
        upper[:] = red[row_start:row_stop]
        numpy.maximum(upper, blue[row_start:row_stop], out=upper)
        lower[:] = red[row_start:row_stop]
        numpy.minimum(lower, blue[row_start:row_stop], out=lower)

        estimate[:] = upper
        upper -= lower
        lower[:] = upper
        lower *= lower
        upper[:] = estimate
        lower += upper
        upper *= 2
        numpy.floor_divide(lower, upper, out=lower, where=upper != 0)
        upper[:] = estimate
        upper -= lower
        estimate[:] = upper

        lower += upper
        upper *= _HIGHLIGHT_BLEND_BASE_SCALE
        lower *= blend_start
        numpy.greater(upper, lower, out=mask)
        numpy.subtract(upper, lower, out=upper, where=mask)
        numpy.multiply(upper, mask, out=upper)

        upper *= _HIGHLIGHT_BLEND_WEIGHT_MAX
        lower //= blend_start
        lower *= blend_end - blend_start
        lower //= 2
        numpy.add(upper, lower, out=upper, where=mask)
        lower *= 2
        numpy.floor_divide(upper, lower, out=upper, where=mask)
        numpy.minimum(upper, _HIGHLIGHT_BLEND_WEIGHT_MAX, out=upper)

        lower //= blend_end - blend_start
        lower -= estimate
        lower *= upper
        lower += _HIGHLIGHT_BLEND_WEIGHT_MAX // 2
        lower //= _HIGHLIGHT_BLEND_WEIGHT_MAX
        lower += estimate
        estimate[:] = lower

        numpy.maximum(target, estimate, out=target, where=both_clipped)
        green2_target = green2[row_start:row_stop]
        numpy.maximum(
            green2_target,
            estimate,
            out=green2_target,
            where=both_clipped,
        )


def repair_in_place(data, settings=None):
    """Restore row phase, Bayer gains, and clipped green values."""
    validate_raw_mosaic(data)
    config = normalize_settings(settings)
    chunk_rows = config['CHUNK_ROWS']
    height = data.shape[0]
    gains = (
        config['GAIN_R'],
        config['GAIN_G1'],
        config['GAIN_G2'],
        config['GAIN_B'],
    )

    # The bad USB frame is displaced by one sensor row.  Move all usable rows
    # up first; copying in forward chunks is safe because NumPy evaluates the
    # right-hand slice before assigning it.
    for row_start in range(0, height - 1, chunk_rows):
        row_stop = min(row_start + chunk_rows, height - 1)
        data[row_start:row_stop] = data[row_start + 1:row_stop + 1]
    data[-1] = data[-3]

    # Record clipping before gain correction.  Once the inverse gains are
    # applied, a value of 65534 no longer proves that the camera clipped it.
    g1_packed, both_packed = _pack_clipped_green_masks(
        data,
        config['SOURCE_SATURATION_THRESHOLD'],
        chunk_rows,
    )

    # Correct each RGGB parity independently using the measured bad-frame
    # gains.  Work in row chunks to stay usable on low-memory Raspberry Pis.
    lookup_tables = _build_lookup_tables(gains)
    for row_start in range(0, height, chunk_rows):
        row_stop = min(row_start + chunk_rows, height)
        for row_parity in range(2):
            for column_parity in range(2):
                plane = data[
                    row_start + row_parity:row_stop:2,
                    column_parity::2,
                ]
                lookup = lookup_tables[row_parity * 2 + column_parity]
                plane[:] = lookup[plane]

    _reconstruct_clipped_green(
        data,
        g1_packed,
        both_packed,
        chunk_rows,
        config['HIGHLIGHT_BLEND_START_RATIO'],
        config['HIGHLIGHT_BLEND_END_RATIO'],
    )
    return data


def repair_if_needed(data, settings=None):
    """Repair a temporary copy and commit it only after validation."""
    config = normalize_settings(settings)
    validate_raw_mosaic(data)
    started = time.perf_counter()
    signature_before = _frame_signature(data, config)
    detection_s = time.perf_counter() - started
    if not signature_before['is_bad']:
        return {
            'repaired': False,
            'validation_failed': False,
            'signature_before': signature_before,
            'signature_after': None,
            'timing': {
                'detection_s': detection_s,
                'repair_s': 0.0,
                'total_s': time.perf_counter() - started,
            },
        }

    repair_started = time.perf_counter()
    # Never risk the caller's original mosaic until the repaired copy has been
    # measured again and no longer carries the failure signature.
    repaired = data.copy()
    repair_in_place(repaired, config)
    signature_after = _frame_signature(repaired, config)
    repair_s = time.perf_counter() - repair_started
    result = {
        'repaired': not signature_after['is_bad'],
        'validation_failed': signature_after['is_bad'],
        'signature_before': signature_before,
        'signature_after': signature_after,
        'timing': {
            'detection_s': detection_s,
            'repair_s': repair_s,
            'total_s': time.perf_counter() - started,
        },
    }
    if result['repaired']:
        data[:] = repaired
    return result


# ---------------------------------------------------------------------------
# FITS input/output and the single-file workflow
# ---------------------------------------------------------------------------


def _fits_module():
    """Import Astropy lazily so ``--help`` works without that dependency."""
    try:
        from astropy.io import fits
    except ModuleNotFoundError as error:
        raise RuntimeError(
            'missing astropy; install it with: python -m pip install astropy'
        ) from error
    return fits


def _read_fits(path, copy=False):
    """Return image data, a copied header, and the image-HDU index."""
    fits = _fits_module()
    with fits.open(path, memmap=False, uint=True) as hdulist:
        for index, hdu in enumerate(hdulist):
            if hdu.data is None:
                continue
            data = numpy.squeeze(numpy.asarray(hdu.data))
            if copy:
                data = data.copy()
            validate_raw_mosaic(data)
            header = hdu.header.copy()
            bayer = str(header.get('BAYERPAT', '')).strip().upper()
            if bayer and bayer != 'RGGB':
                raise ValueError(f'expected RGGB Bayer data, got {bayer}')
            return data, header, index
    raise ValueError('FITS file contains no image data')


def default_output_path(input_path):
    """Choose a corrected-copy name that never replaces the source by default."""
    suffix = input_path.suffix or '.fit'
    return input_path.with_name(f'{input_path.stem}_corrected{suffix}')


def process_frame(
    input_path,
    output_path=None,
    check_only=False,
    overwrite=False,
    settings=None,
):
    """Inspect one FITS and write a repaired copy only when necessary."""
    fits = _fits_module()
    config = normalize_settings(settings)
    with fits.open(input_path, memmap=False, uint=True) as hdulist:
        image_hdu = next(
            (hdu for hdu in hdulist if hdu.data is not None),
            None,
        )
        if image_hdu is None:
            raise ValueError('FITS file contains no image data')
        data = numpy.squeeze(numpy.asarray(image_hdu.data))
        validate_raw_mosaic(data)
        bayer = str(image_hdu.header.get('BAYERPAT', '')).strip().upper()
        if bayer and bayer != 'RGGB':
            raise ValueError(f'expected RGGB Bayer data, got {bayer}')

        result = repair_if_needed(data, config)
        before = result['signature_before']
        print(f'Frame: {input_path}')
        print(
            'Signature: purple={0:.3f}, red-side={1:.3f}, '
            'blue-side={2:.3f}'.format(
                before['purple_ratio'],
                before['red_side_ratio'],
                before['blue_side_ratio'],
            )
        )
        if not before['is_bad']:
            print('Classification: normal; no correction required')
            return result, None
        print('Classification: ASI676MC purple-frame signature detected')
        if check_only:
            print('Check-only mode: no output written')
            return result, None
        if result['validation_failed']:
            raise RuntimeError(
                'repair validation failed; bad signature remains'
            )

        image_hdu.data = data
        image_hdu.header['ASI676FX'] = (
            True,
            'ASI676MC purple frame repaired',
        )
        image_hdu.header['PURPRAT'] = (
            round(before['purple_ratio'], 6),
            'Purple ratio before repair',
        )
        image_hdu.header['ASIBLEND'] = (
            '{0:.3f},{1:.3f}'.format(
                config['HIGHLIGHT_BLEND_START_RATIO'],
                config['HIGHLIGHT_BLEND_END_RATIO'],
            ),
            'Highlight blend start,end ratios',
        )
        image_hdu.header.add_history(
            'ASI676MC RAW16 row phase, Bayer gains, and clipped greens repaired'
        )

        if output_path is None:
            output_path = default_output_path(input_path)
        hdulist.writeto(output_path, overwrite=overwrite, checksum=True)

    after = result['signature_after']
    print(
        'Post-repair: purple={0:.3f}; repair={1:.1f} ms'.format(
            after['purple_ratio'],
            result['timing']['repair_s'] * 1000.0,
        )
    )
    print(f'Corrected FITS: {output_path}')
    return result, output_path


def _parse_timestamp(header, path):
    """Read capture time from FITS metadata or a legacy filename.

    Pairing uses only elapsed seconds, so treating a timezone-less legacy
    timestamp as UTC does not affect the before/after relationship.
    """
    value = header.get('DATE-OBS') or header.get('DATE')
    if value:
        text = str(value).strip().replace('Z', '+00:00')
        try:
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            pass

    match = _FILENAME_TIME_RE.search(path.name)
    if match:
        parsed = datetime.strptime(
            ''.join(match.groups()),
            '%Y%m%d%H%M%S',
        ).replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    raise ValueError('missing usable DATE-OBS/DATE and filename timestamp')


def _header_float(header, *keys, default=None):
    """Return the first numeric FITS value among common keyword aliases."""
    for key in keys:
        value = header.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _camera_name(header):
    """Return the first useful camera identity from several FITS conventions."""
    for key in (
        'CAMERA',
        'CAMMODEL',
        'CCDNAME',
        'INSTRUME',
        'TELESCOP',
    ):
        value = str(header.get(key, '')).strip()
        if value:
            return value
    return ''


def _specific_camera_name(name):
    """Normalize ASI676MC names while discarding generic legacy labels."""
    if _CAMERA_NAME_RE.search(name):
        return 'asi676mc'
    lowered = name.strip().lower()
    if not lowered or lowered in ('indi-allsky', 'unknown', 'camera'):
        return ''
    return lowered


@dataclass(frozen=True)
class FrameRecord:
    """Immutable index entry for one inspected FITS capture."""
    path: Path
    timestamp: float
    exposure: float
    gain: float
    xbin: int
    ybin: int
    shape: tuple
    bayer: str
    camera_name: str
    signature: dict

    @property
    def is_bad(self):
        """Expose the detector result stored with this capture."""
        return bool(self.signature['is_bad'])

    @property
    def compatibility_key(self):
        """Capture attributes that must agree before frames can be paired."""
        return (
            self.shape,
            self.bayer,
            round(self.exposure, 12),
            round(self.gain, 6),
            self.xbin,
            self.ybin,
            _specific_camera_name(self.camera_name),
        )


@dataclass(frozen=True)
class MatchedPair:
    """A detected failure and its one or two nearby normal references."""
    bad: FrameRecord
    references: tuple

    @property
    def two_sided(self):
        """Report whether references exist both before and after the failure."""
        return (
            any(ref.timestamp < self.bad.timestamp for ref in self.references)
            and any(ref.timestamp > self.bad.timestamp for ref in self.references)
        )


def inspect_fits(path, settings):
    """Build a lightweight calibration record for one FITS file."""
    data, header, _index = _read_fits(path)
    if bool(header.get('ASI676FX', False)):
        raise ValueError('already repaired by ASI676MC frame handling')
    signature = frame_signature(data, settings)
    exposure = _header_float(header, 'EXPTIME', 'EXPOSURE', default=-1.0)
    gain = _header_float(header, 'GAIN', 'CCD-GAIN', default=-1.0)
    return FrameRecord(
        path=path,
        timestamp=_parse_timestamp(header, path),
        exposure=exposure,
        gain=gain,
        xbin=int(_header_float(header, 'XBINNING', default=1)),
        ybin=int(_header_float(header, 'YBINNING', default=1)),
        shape=tuple(data.shape),
        bayer=str(header.get('BAYERPAT', 'RGGB')).strip().upper() or 'RGGB',
        camera_name=_camera_name(header),
        signature=signature,
    )


def scan_folder(folder, settings, recursive=True):
    """Inspect compatible FITS files and return records plus rejected files."""
    iterator = folder.rglob('*') if recursive else folder.glob('*')
    paths = sorted(
        path for path in iterator
        if path.is_file()
        and path.name.lower().endswith(
            _FITS_SUFFIXES + _COMPRESSED_FITS_SUFFIXES
        )
    )
    records = []
    rejected = []
    for path in paths:
        try:
            records.append(inspect_fits(path, settings))
        except (OSError, ValueError) as error:
            rejected.append((path, str(error)))
    return records, rejected


def _compatible(left, right):
    """Compare capture settings while tolerating generic camera headers."""
    left_key = left.compatibility_key[:-1]
    right_key = right.compatibility_key[:-1]
    if left_key != right_key:
        return False
    left_camera = _specific_camera_name(left.camera_name)
    right_camera = _specific_camera_name(right.camera_name)
    return not left_camera or not right_camera or left_camera == right_camera


def match_pairs(records, max_pair_seconds):
    """Match each failure to its nearest compatible normal on either side."""
    normal = [record for record in records if not record.is_bad]
    pairs = []
    unmatched = []
    for bad in (record for record in records if record.is_bad):
        candidates = [
            record for record in normal
            if _compatible(bad, record)
            and abs(record.timestamp - bad.timestamp) <= max_pair_seconds
        ]
        before = [
            record for record in candidates
            if record.timestamp < bad.timestamp
        ]
        after = [
            record for record in candidates
            if record.timestamp > bad.timestamp
        ]
        # A two-sided pair lets us interpolate through slow changes in sky
        # brightness.  With only one side available, the nearest compatible
        # capture is still useful but is reported as weaker evidence.
        references = []
        if before:
            references.append(max(before, key=lambda item: item.timestamp))
        if after:
            references.append(min(after, key=lambda item: item.timestamp))
        if not references and candidates:
            references.append(
                min(
                    candidates,
                    key=lambda item: abs(item.timestamp - bad.timestamp),
                )
            )
        if references:
            pairs.append(MatchedPair(bad=bad, references=tuple(references)))
        else:
            unmatched.append(bad)
    return pairs, unmatched


# ---------------------------------------------------------------------------
# Sparse pair sampling and camera-constant estimation
# ---------------------------------------------------------------------------


def _sample_planes(record, bad_source, step):
    """Copy sparse central Bayer planes; shift bad source rows by one."""
    data, _header, _index = _read_fits(record.path)
    height, width = data.shape
    y_start = (height // 4) & ~1
    y_stop = (3 * height // 4) & ~1
    x_start = (width // 4) & ~1
    x_stop = (3 * width // 4) & ~1
    row_offset = 1 if bad_source else 0
    return tuple(
        data[
            y_start + row + row_offset:y_stop + row_offset:step,
            x_start + column:x_stop:step,
        ].copy()
        for row in range(2)
        for column in range(2)
    )


def _reference_planes(pair, step):
    """Interpolate before/after samples to the bad frame timestamp."""
    sampled = [
        (
            reference,
            _sample_planes(reference, bad_source=False, step=step),
        )
        for reference in pair.references
    ]
    if len(sampled) == 1:
        planes = tuple(
            plane.astype(numpy.float64)
            for plane in sampled[0][1]
        )
        stable = tuple(
            numpy.ones(plane.shape, dtype=numpy.bool_)
            for plane in planes
        )
        return planes, stable

    before = max(
        (item for item in sampled if item[0].timestamp < pair.bad.timestamp),
        key=lambda item: item[0].timestamp,
        default=None,
    )
    after = min(
        (item for item in sampled if item[0].timestamp > pair.bad.timestamp),
        key=lambda item: item[0].timestamp,
        default=None,
    )
    if before is None or after is None:
        nearest = min(
            sampled,
            key=lambda item: abs(item[0].timestamp - pair.bad.timestamp),
        )
        planes = tuple(
            plane.astype(numpy.float64)
            for plane in nearest[1]
        )
        stable = tuple(
            numpy.ones(plane.shape, dtype=numpy.bool_)
            for plane in planes
        )
        return planes, stable

    # Linear time interpolation estimates what the bad frame would have looked
    # like between its normal neighbors.  A separate stability mask removes
    # pixels where fast cloud movement makes that estimate unreliable.
    span = after[0].timestamp - before[0].timestamp
    after_weight = (pair.bad.timestamp - before[0].timestamp) / span
    before_weight = 1.0 - after_weight
    planes = []
    stable = []
    fraction = CALIBRATION_OPTIONS['MAX_REFERENCE_CHANGE_FRACTION']
    floor = CALIBRATION_OPTIONS['REFERENCE_CHANGE_FLOOR']
    for before_plane, after_plane in zip(before[1], after[1]):
        before_float = before_plane.astype(numpy.float64)
        after_float = after_plane.astype(numpy.float64)
        reference = (
            before_float * before_weight
            + after_float * after_weight
        )
        allowed_change = numpy.maximum(floor, reference * fraction)
        planes.append(reference)
        stable.append(
            numpy.abs(after_float - before_float) <= allowed_change
        )
    return tuple(planes), tuple(stable)


@dataclass
class PairSamples:
    """Sparse Bayer samples retained from one bad/reference group."""
    pair: MatchedPair
    bad_planes: tuple
    reference_planes: tuple
    stable_masks: tuple


def collect_pair_samples(pairs):
    """Load only the central sparse samples needed by calibration.

    Holding these small arrays instead of complete 3552x3552 frames keeps the
    command-line workflow practical on machines with limited memory.
    """
    step = CALIBRATION_OPTIONS['SAMPLE_STEP']
    samples = []
    for index, pair in enumerate(pairs, start=1):
        print(
            f'  Sampling pair {index}/{len(pairs)}: {pair.bad.path.name}',
            flush=True,
        )
        reference_planes, stable_masks = _reference_planes(pair, step)
        samples.append(PairSamples(
            pair=pair,
            bad_planes=_sample_planes(
                pair.bad,
                bad_source=True,
                step=step,
            ),
            reference_planes=reference_planes,
            stable_masks=stable_masks,
        ))
    return samples


def _median_absolute_deviation(values):
    """Return a robust spread measurement that is insensitive to outliers."""
    median = statistics.median(values)
    return statistics.median(abs(value - median) for value in values)


def estimate_gains(samples):
    """Estimate each bad-stream RGGB multiplier with equal pair weighting."""
    parity_names = ('GAIN_R', 'GAIN_G1', 'GAIN_G2', 'GAIN_B')
    per_parity = {name: [] for name in parity_names}
    sample_counts = {name: 0 for name in parity_names}
    minimum = CALIBRATION_OPTIONS['MIN_REFERENCE_VALUE']
    maximum = CALIBRATION_OPTIONS['MAX_REFERENCE_VALUE']
    source_max = CALIBRATION_OPTIONS['MAX_SOURCE_VALUE_FOR_GAIN']
    required = CALIBRATION_OPTIONS['MIN_GAIN_SAMPLES_PER_PARITY']

    for pair_sample in samples:
        for name, bad, reference, stable in zip(
            parity_names,
            pair_sample.bad_planes,
            pair_sample.reference_planes,
            pair_sample.stable_masks,
        ):
            mask = (
                stable
                & (reference >= minimum)
                & (reference <= maximum)
                & (bad >= minimum)
                & (bad <= source_max)
            )
            count = int(numpy.count_nonzero(mask))
            if count < required:
                continue
            ratios = bad[mask].astype(numpy.float64) / reference[mask]
            # Reject moving-cloud and transient mismatches without assuming
            # the expected camera gain.
            lower, upper = numpy.quantile(ratios, (0.10, 0.90))
            trimmed = ratios[(ratios >= lower) & (ratios <= upper)]
            per_parity[name].append(float(numpy.median(trimmed)))
            sample_counts[name] += int(trimmed.size)

    # Every capture contributes one median per parity, regardless of how many
    # valid pixels it happens to contain.  This prevents a single clear frame
    # from dominating several cloudy but otherwise valid pairs.
    estimates = {}
    for name in parity_names:
        values = per_parity[name]
        if len(values) < CALIBRATION_OPTIONS['MIN_BAD_PAIRS']:
            raise CalibrationError(
                f'{name} has usable samples in only {len(values)} pairs'
            )
        estimates[name] = {
            'value': float(statistics.median(values)),
            'mad': float(_median_absolute_deviation(values)),
            'pair_values': values,
            'sample_count': sample_counts[name],
        }
    return estimates


def estimate_saturation_threshold(samples):
    """Measure the source green ceiling and recommend its lower guard."""
    maxima = []
    for sample in samples:
        maxima.extend((
            int(numpy.max(sample.bad_planes[1])),
            int(numpy.max(sample.bad_planes[2])),
        ))
    clipped_maxima = [
        value for value in maxima
        if value >= DEFAULT_SETTINGS['SOURCE_SATURATION_THRESHOLD']
    ]
    if not clipped_maxima:
        raise CalibrationError(
            'no source green plateau was found; collect brighter daylight pairs'
        )
    # Use a high percentile rather than the absolute maximum so one hot pixel
    # cannot masquerade as the camera's clipping plateau.
    plateau = int(round(numpy.quantile(clipped_maxima, 0.90)))
    threshold = max(
        1,
        plateau - CALIBRATION_OPTIONS['SATURATION_HEADROOM'],
    )
    default = DEFAULT_SETTINGS['SOURCE_SATURATION_THRESHOLD']
    if abs(threshold - default) <= CALIBRATION_OPTIONS[
        'SATURATION_DEFAULT_SNAP'
    ]:
        threshold = default
    return threshold, plateau


def _highlight_arrays(pair_sample, gains, saturation_threshold):
    """Select stable, informative jointly-clipped highlight samples.

    Red and blue survive the camera fault well enough to guide reconstruction;
    the normal reference provides the target chromaticity for green.  Samples
    that changed between the before/after references are excluded.
    """
    bad = pair_sample.bad_planes
    reference = pair_sample.reference_planes
    stable = numpy.logical_and.reduce(pair_sample.stable_masks)
    jointly_clipped = (
        (bad[1] >= saturation_threshold)
        & (bad[2] >= saturation_threshold)
    )

    red = numpy.clip(
        bad[0].astype(numpy.float64) / gains['GAIN_R'],
        0.0,
        65535.0,
    )
    green1 = bad[1].astype(numpy.float64) / gains['GAIN_G1']
    green2 = bad[2].astype(numpy.float64) / gains['GAIN_G2']
    blue = numpy.clip(
        bad[3].astype(numpy.float64) / gains['GAIN_B'],
        0.0,
        65535.0,
    )
    high = numpy.maximum(red, blue)
    low = numpy.minimum(red, blue)
    reference_red = reference[0]
    reference_green = (reference[1] + reference[2]) / 2.0
    reference_blue = reference[3]
    mask = (
        stable
        & jointly_clipped
        & (high > 0)
        & (
            reference_green
            >= CALIBRATION_OPTIONS['HIGHLIGHT_REFERENCE_MIN']
        )
        # Fully clipped normal references contain no target chroma.  Keeping
        # them would reward pushing every reconstructed green value to white
        # and would bias the fitted boundaries toward 1.0.
        & (reference_red < saturation_threshold)
        & (reference_green < saturation_threshold)
        & (reference_blue < saturation_threshold)
    )
    return tuple(
        array[mask]
        for array in (
            high,
            low,
            green1,
            green2,
            red,
            blue,
            reference_red,
            reference_green,
            reference_blue,
        )
    )


def _highlight_prediction(arrays, start_ratio, end_ratio):
    """Apply the floating-point equivalent of Method 5 to sparse samples."""
    high, low, green1, green2 = arrays[:4]
    difference = high - low
    # The factor-two curve preserves strongly colored highlights better than
    # simply forcing green to max(red, blue).  The bounded weight then moves
    # smoothly toward that maximum only as red and blue become more balanced.
    base = high - (difference * difference / (2.0 * high))
    start_base, end_base = _highlight_blend_base_boundaries(
        start_ratio,
        end_ratio,
    )
    base_ratio = base / high
    weight = numpy.clip(
        (
            base_ratio * _HIGHLIGHT_BLEND_BASE_SCALE
            - start_base
        ) / (end_base - start_base),
        0.0,
        1.0,
    )
    target = base + weight * (high - base)
    return (
        numpy.maximum(green1, target)
        + numpy.maximum(green2, target)
    ) / 2.0


def _highlight_score(datasets, start_ratio, end_ratio):
    """Score one boundary pair using equal weight per capture pair."""
    pair_errors = []
    for arrays in datasets:
        red, blue = arrays[4:6]
        reference_red, reference_green, reference_blue = arrays[6:9]
        predicted_green = _highlight_prediction(
            arrays,
            start_ratio,
            end_ratio,
        )

        # Compare chromaticity rather than absolute brightness.  Consecutive
        # sky frames can differ slightly in exposure or cloud luminance, while
        # the colour relationship that the repair must restore is stable.
        predicted_sum = red + predicted_green + blue
        reference_sum = reference_red + reference_green + reference_blue
        predicted_red = red / predicted_sum
        predicted_green = predicted_green / predicted_sum
        predicted_blue = blue / predicted_sum
        reference_red = reference_red / reference_sum
        reference_green = reference_green / reference_sum
        reference_blue = reference_blue / reference_sum
        chroma_error = numpy.sqrt(
            (predicted_red - reference_red) ** 2
            + (predicted_green - reference_green) ** 2
            + (predicted_blue - reference_blue) ** 2
        )
        pair_errors.append(float(numpy.median(chroma_error)))
    return float(statistics.mean(pair_errors))


def estimate_highlight_ratios(samples, gains, saturation_threshold):
    """Grid-search bounded Method-5 highlight ratios against normal frames."""
    datasets = []
    counts = []
    for pair_sample in samples:
        arrays = _highlight_arrays(
            pair_sample,
            gains,
            saturation_threshold,
        )
        count = int(arrays[0].size)
        if count < CALIBRATION_OPTIONS['MIN_HIGHLIGHT_SAMPLES_PER_PAIR']:
            continue
        datasets.append(arrays)
        counts.append(count)

    total = sum(counts)
    if total < CALIBRATION_OPTIONS['MIN_HIGHLIGHT_SAMPLES_TOTAL']:
        raise CalibrationError(
            'only {0} stable jointly-clipped highlight samples were found; '
            'collect brighter daylight pairs'.format(total)
        )

    # The search space is intentionally small and explicit.  It is easier to
    # audit than a black-box optimizer and matches the runtime's fixed-point
    # precision closely enough that finer candidates would not be meaningful.
    candidates = []
    for start in CALIBRATION_OPTIONS['BLEND_START_VALUES']:
        for end in CALIBRATION_OPTIONS['BLEND_END_VALUES']:
            if end - start < CALIBRATION_OPTIONS['MIN_BLEND_WIDTH']:
                continue
            try:
                score = _highlight_score(datasets, start, end)
            except ValueError:
                continue
            candidates.append((score, start, end))
    candidates.sort()
    if not candidates:
        raise CalibrationError('no valid highlight blend candidates')

    raw_best = candidates[0]
    default_score = _highlight_score(
        datasets,
        DEFAULT_SETTINGS['HIGHLIGHT_BLEND_START_RATIO'],
        DEFAULT_SETTINGS['HIGHLIGHT_BLEND_END_RATIO'],
    )
    tolerance = CALIBRATION_OPTIONS['PREFER_DEFAULT_SCORE_TOLERANCE']
    # Prefer the field-tested defaults when a neighboring point wins by only
    # a tiny amount.  Such a difference is more likely cloud motion or scene
    # noise than a real camera-to-camera change.
    if default_score <= raw_best[0] * (1.0 + tolerance):
        selected = (
            default_score,
            DEFAULT_SETTINGS['HIGHLIGHT_BLEND_START_RATIO'],
            DEFAULT_SETTINGS['HIGHLIGHT_BLEND_END_RATIO'],
        )
        preferred_default = True
    else:
        selected = raw_best
        preferred_default = False
    runner_up = candidates[1] if len(candidates) > 1 else raw_best
    return {
        'start_ratio': selected[1],
        'end_ratio': selected[2],
        'score': selected[0],
        'raw_best_start_ratio': raw_best[1],
        'raw_best_end_ratio': raw_best[2],
        'raw_best_score': raw_best[0],
        'preferred_default': preferred_default,
        'runner_up_score': runner_up[0],
        'default_score': default_score,
        'sample_count': total,
        'pair_count': len(datasets),
        'per_pair_counts': counts,
    }


# ---------------------------------------------------------------------------
# Evidence checks, final validation, and the human-readable report
# ---------------------------------------------------------------------------


def signature_ranges(records):
    """Summarize normal and bad detector metrics for the audit report."""
    metrics = (
        'purple_ratio',
        'red_side_ratio',
        'blue_side_ratio',
    )
    result = {}
    for metric in metrics:
        good = [
            record.signature[metric]
            for record in records
            if not record.is_bad
        ]
        bad = [
            record.signature[metric]
            for record in records
            if record.is_bad
        ]
        if not good or not bad:
            raise CalibrationError(
                'both normal and bad frames are required for signature ranges'
            )
        result[metric] = {
            'good_min': float(min(good)),
            'good_max': float(max(good)),
            'bad_min': float(min(bad)),
            'bad_max': float(max(bad)),
        }
    return result


def validate_signature_separation(ranges, settings):
    """Require every supplied frame to fall on the correct threshold side."""
    threshold_names = {
        'purple_ratio': 'PURPLE_RATIO_THRESHOLD',
        'red_side_ratio': 'RED_SIDE_RATIO_THRESHOLD',
        'blue_side_ratio': 'BLUE_SIDE_RATIO_THRESHOLD',
    }
    for metric, threshold_name in threshold_names.items():
        values = ranges[metric]
        threshold = settings[threshold_name]
        if values['good_max'] >= threshold:
            raise CalibrationError(
                f'{threshold_name} misclassifies at least one supplied normal frame'
            )
        if values['bad_min'] < threshold:
            raise CalibrationError(
                f'{threshold_name} misses at least one supplied bad frame'
            )
        if values['good_max'] >= values['bad_min']:
            raise CalibrationError(
                f'{metric} has overlapping normal and bad ranges'
            )


def _exposure_levels(pairs):
    """Return distinct exposures represented by matched failures."""
    return sorted({round(pair.bad.exposure, 12) for pair in pairs})


class CalibrationError(RuntimeError):
    """Raised when a folder cannot support a defensible calibration."""


def validate_evidence(records, pairs, unmatched, allow_unmatched=False):
    """Refuse calibration when the dataset cannot support safe conclusions.

    Seven matched failures are the minimum statistical base.  Multiple
    exposures reduce the chance that constants describe only one brightness
    regime, and explicit mixed-camera folders are rejected outright.
    """
    bad_records = [record for record in records if record.is_bad]
    normal_records = [record for record in records if not record.is_bad]
    minimum = CALIBRATION_OPTIONS['MIN_BAD_PAIRS']
    if len(pairs) < minimum:
        raise CalibrationError(
            f'{len(pairs)} matched bad frames found; at least {minimum} required'
        )
    if unmatched and not allow_unmatched:
        raise CalibrationError(
            f'{len(unmatched)} detected bad frames have no compatible nearby normal'
        )

    unique_good = {
        reference.path
        for pair in pairs
        for reference in pair.references
    }
    ratio = len(unique_good) / len(pairs)
    if ratio < CALIBRATION_OPTIONS['MIN_GOOD_BAD_RATIO']:
        raise CalibrationError(
            'matched normal/bad ratio is {0:.2f}:1; at least '
            '{1:.2f}:1 is required'.format(
                ratio,
                CALIBRATION_OPTIONS['MIN_GOOD_BAD_RATIO'],
            )
        )
    exposures = _exposure_levels(pairs)
    if len(exposures) < CALIBRATION_OPTIONS['MIN_EXPOSURE_LEVELS']:
        raise CalibrationError(
            'matched failures cover only one exposure; collect more varied data'
        )

    explicit_names = {
        _specific_camera_name(record.camera_name)
        for record in records
        if _specific_camera_name(record.camera_name)
    }
    if len(explicit_names) > 1:
        raise CalibrationError(
            'folder contains more than one explicit camera identity: '
            + ', '.join(sorted(explicit_names))
        )
    other_asi = {
        name for name in explicit_names
        if _OTHER_ASI_CAMERA_RE.search(name)
        and not _CAMERA_NAME_RE.search(name)
    }
    if other_asi:
        raise CalibrationError(
            'folder contains a different explicit ASI camera: '
            + ', '.join(sorted(other_asi))
        )

    return {
        'bad_count': len(bad_records),
        'normal_count': len(normal_records),
        'pair_count': len(pairs),
        'unmatched_bad_count': len(unmatched),
        'unique_good_count': len(unique_good),
        'good_bad_ratio': ratio,
        'two_sided_count': sum(pair.two_sided for pair in pairs),
        'exposure_levels': exposures,
        'explicit_camera_names': sorted(explicit_names),
    }


def validate_calibrated_frames(pairs, settings):
    """Apply final rounded settings to every pair without writing outputs."""
    repaired_count = 0
    normal_count = 0
    unique_normal = {
        reference.path: reference
        for pair in pairs
        for reference in pair.references
    }
    # This is deliberately a full-resolution final pass.  Sparse calibration
    # can estimate constants, but only the real runtime algorithm can prove
    # that every failure clears detection after repair.
    for pair in pairs:
        data, _header, _index = _read_fits(pair.bad.path, copy=True)
        result = repair_if_needed(data, settings)
        if not result['repaired'] or result['validation_failed']:
            raise CalibrationError(
                f'calibrated repair validation failed for {pair.bad.path}'
            )
        repaired_count += 1

    # A normal frame must take the fast no-op path.  The array comparison also
    # guards against future changes accidentally touching normal input.
    for record in unique_normal.values():
        data, _header, _index = _read_fits(record.path, copy=True)
        original = data.copy()
        result = repair_if_needed(data, settings)
        if result['repaired'] or result['signature_before']['is_bad']:
            raise CalibrationError(
                f'calibrated detector rejects normal frame {record.path}'
            )
        if not numpy.array_equal(data, original):
            raise CalibrationError(
                f'normal-frame validation mutated {record.path}'
            )
        normal_count += 1
    return repaired_count, normal_count


def calibration_payload(
    folder,
    settings,
    evidence,
    ranges,
    gains,
    saturation_threshold,
    saturation_plateau,
    highlight,
    rejected,
):
    """Collect calibrated settings and presentation-neutral audit data.

    The numerical payload is shared by every caller.  It deliberately carries
    enough structured detail for the integrated web workflow to build its own
    report instead of parsing or relabelling the folder-oriented text output.
    This dictionary remains internal working data, not a configuration export.
    """
    # Round gains exactly as the web form stores them.  The final validation
    # below uses these rounded values, not higher-precision hidden estimates.
    calibrated = dict(settings)
    for name, result in gains.items():
        calibrated[name] = round(result['value'], 5)
    calibrated['SOURCE_SATURATION_THRESHOLD'] = saturation_threshold
    calibrated['HIGHLIGHT_BLEND_START_RATIO'] = highlight['start_ratio']
    calibrated['HIGHLIGHT_BLEND_END_RATIO'] = highlight['end_ratio']

    return {
        'format': 'indi-allsky-asi676mc-calibration-v1',
        'source_folder': str(folder.resolve()),
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'quality': {
            **evidence,
            'rejected_file_count': len(rejected),
            'highlight_pair_count': highlight['pair_count'],
            'highlight_sample_count': highlight['sample_count'],
            'highlight_score': highlight['score'],
            'highlight_default_score': highlight['default_score'],
            'highlight_raw_best_score': highlight['raw_best_score'],
            'highlight_raw_best_start_ratio': (
                highlight['raw_best_start_ratio']
            ),
            'highlight_raw_best_end_ratio': highlight['raw_best_end_ratio'],
            'highlight_preferred_default': highlight['preferred_default'],
            'highlight_runner_up_score': highlight['runner_up_score'],
            'source_saturation_plateau': saturation_plateau,
        },
        'signature_ranges': ranges,
        'gain_estimates': gains,
        # Store only the staged basename and reason.  The integrated workflow
        # maps that basename back to the user-facing original filename from its
        # private manifest; absolute session paths must never enter a download.
        'rejected_files': [
            {
                'name': Path(path).name,
                'reason': str(reason),
            }
            for path, reason in rejected
        ],
        'IMAGE_ASI676MC_REPAIR': {
            'ENABLE': False,
            'LOG_EVERY_FRAME': False,
            'GALLERY_ENABLE': True,
            'SAVE_DIAGNOSTIC_FITS': False,
            'SAVE_PRECEDING_FITS': False,
            **calibrated,
        },
    }


def format_report(payload, rejected):
    """Render a user-facing result first and technical audit details second."""
    quality = payload['quality']
    settings = payload['IMAGE_ASI676MC_REPAIR']
    lines = [
        'ASI676MC calibration report',
        '=' * 40,
        f"Source: {payload['source_folder']}",
        f"Generated: {payload['generated_utc']}",
        '',
        'RESULT: CALIBRATION PASSED',
        '==========================',
        (
            f"Validated {quality.get('validated_bad_repairs', 0)} repaired "
            'purple frames and confirmed that '
            f"{quality.get('validated_normal_frames', 0)} normal frames "
            'remain unchanged.'
        ),
        '',
        'REVIEW THESE CALIBRATION VALUES',
        '===============================',
        '1. Compare these values with the current configuration.',
        '2. On the web result page, an administrator can apply all seven.',
        '3. They can also be entered under Image > ASI676MC RAW16 Frame Repair.',
        '4. Review the result before relying on actual repair.',
        '',
    ]
    for key, label in CONFIG_ENTRY_LABELS:
        lines.append(f'{label}: {settings[key]}')

    lines.extend((
        '',
        'Do not import this report as a configuration file. The feature',
        'checkboxes are intentionally left for the operator to choose.',
        '',
        'Evidence used',
        '-------------',
        f"Purple frames used: {quality['pair_count']}",
        (
            'Purple frames skipped without a reference: '
            f"{quality['unmatched_bad_count']}"
        ),
        f"Distinct normal references: {quality['unique_good_count']}",
        f"Normal/purple ratio: {quality['good_bad_ratio']:.2f}:1",
        (
            'Good/bad/good groups: '
            f"{quality['two_sided_count']}/{quality['pair_count']}"
        ),
        f"Exposure levels: {len(quality['exposure_levels'])}",
        (
            'Repair checks passed: '
            f"{quality.get('validated_bad_repairs', 0)}"
        ),
        (
            'Normal-frame checks passed: '
            f"{quality.get('validated_normal_frames', 0)}"
        ),
        (
            'Camera names found in FITS headers: '
            + (
                ', '.join(quality['explicit_camera_names'])
                if quality['explicit_camera_names']
                else 'none (generic legacy headers)'
            )
        ),
        f"FITS files rejected: {quality['rejected_file_count']}",
        '',
        'Gain stability',
        '--------------',
    ))
    for key in ('GAIN_R', 'GAIN_G1', 'GAIN_G2', 'GAIN_B'):
        estimate = payload['gain_estimates'][key]
        lines.append(
            '{0}: {1:.5f} (pair MAD {2:.5f}, {3} samples)'.format(
                key,
                estimate['value'],
                estimate['mad'],
                estimate['sample_count'],
            )
        )

    lines.extend((
        '',
        'Highlight fit',
        '-------------',
        (
            'Stable jointly-clipped samples: '
            f"{quality['highlight_sample_count']} across "
            f"{quality['highlight_pair_count']} pairs"
        ),
        f"Selected median chromaticity error: {quality['highlight_score']:.6f}",
        (
            'Original 0.55/0.75 chromaticity error: '
            f"{quality['highlight_default_score']:.6f}"
        ),
        (
            'Unregularized grid best: '
            f"{quality['highlight_raw_best_start_ratio']:.2f}/"
            f"{quality['highlight_raw_best_end_ratio']:.2f} at "
            f"{quality['highlight_raw_best_score']:.6f}"
        ),
        (
            'Kept proven defaults within tolerance: '
            f"{quality['highlight_preferred_default']}"
        ),
        (
            'Runner-up chromaticity error: '
            f"{quality['highlight_runner_up_score']:.6f}"
        ),
        (
            'Measured source green plateau: '
            f"{quality['source_saturation_plateau']}"
        ),
        '',
        'Signature separation',
        '--------------------',
    ))
    for metric, values in payload['signature_ranges'].items():
        lines.append(
            '{0}: normal {1:.3f}-{2:.3f}; purple {3:.3f}-{4:.3f}'.format(
                metric,
                values['good_min'],
                values['good_max'],
                values['bad_min'],
                values['bad_max'],
            )
        )

    if quality['good_bad_ratio'] < CALIBRATION_OPTIONS[
        'RECOMMENDED_GOOD_BAD_RATIO'
    ]:
        lines.extend((
            '',
            'Warning: calibration passed the required 1:1 normal/bad ratio,',
            'but fewer than two distinct normal references per bad frame were',
            'available. Before/bad/after triplets would improve confidence.',
        ))
    if rejected:
        lines.extend(('', 'Rejected files', '--------------'))
        lines.extend(f'{path}: {reason}' for path, reason in rejected)
    return '\n'.join(lines) + '\n'


def calibrate_folder(
    folder,
    settings=None,
    recursive=True,
    max_pair_seconds=None,
    allow_unmatched=False,
):
    """Run the complete folder calibration and return audit data plus report.

    The sequence matters: cheap structural/evidence checks happen before
    expensive sample fitting, and full-resolution validation happens last with
    the rounded values that a user will actually type into indi-allsky.
    """
    config = normalize_settings(settings)
    if max_pair_seconds is None:
        max_pair_seconds = CALIBRATION_OPTIONS['MAX_PAIR_SECONDS']

    print(f'Scanning FITS files under: {folder}')
    records, rejected = scan_folder(folder, config, recursive=recursive)
    if not records:
        raise CalibrationError('no compatible RAW16 RGGB FITS files found')
    bad_count = sum(record.is_bad for record in records)
    print(
        f'Classified {len(records)} files: '
        f'{bad_count} bad, {len(records) - bad_count} normal'
    )

    pairs, unmatched = match_pairs(records, max_pair_seconds)
    evidence = validate_evidence(
        records,
        pairs,
        unmatched,
        allow_unmatched=allow_unmatched,
    )
    ranges = signature_ranges(records)
    validate_signature_separation(ranges, config)
    print(
        'Matched {0} bad frames to {1} distinct normal frames '
        '({2:.2f}:1)'.format(
            evidence['pair_count'],
            evidence['unique_good_count'],
            evidence['good_bad_ratio'],
        )
    )

    samples = collect_pair_samples(pairs)
    gains_detail = estimate_gains(samples)
    gain_values = {
        name: result['value']
        for name, result in gains_detail.items()
    }
    saturation_threshold, plateau = estimate_saturation_threshold(samples)
    print('Fitting clipped-highlight boundaries...')
    highlight = estimate_highlight_ratios(
        samples,
        gain_values,
        saturation_threshold,
    )
    payload = calibration_payload(
        folder,
        config,
        evidence,
        ranges,
        gains_detail,
        saturation_threshold,
        plateau,
        highlight,
        rejected,
    )
    print('Validating calibrated settings against every matched frame...')
    repaired_count, normal_validation_count = validate_calibrated_frames(
        pairs,
        payload['IMAGE_ASI676MC_REPAIR'],
    )
    payload['quality']['validated_bad_repairs'] = repaired_count
    payload['quality']['validated_normal_frames'] = normal_validation_count
    return payload, format_report(payload, rejected)


# ---------------------------------------------------------------------------
# Command-line interface
# ---------------------------------------------------------------------------


def parse_args():
    """Define the mutually compatible single-file and folder options."""
    parser = argparse.ArgumentParser(
        description=(
            'Inspect/repair one ASI676MC RAW16 FITS file, or calibrate the '
            'camera-specific constants from a folder of matched captures.'
        ),
    )
    parser.add_argument(
        'input',
        type=Path,
        help='one FITS file, or a folder when --calibrate is used',
    )
    parser.add_argument(
        '--calibrate',
        action='store_true',
        help='scan INPUT as a folder and calculate repair settings',
    )
    parser.add_argument(
        '--output',
        type=Path,
        help='single-file corrected FITS path',
    )
    parser.add_argument(
        '--check-only',
        action='store_true',
        help='classify one FITS without writing a repaired copy',
    )
    parser.add_argument(
        '--overwrite',
        action='store_true',
        help='allow replacement of an existing output file',
    )
    parser.add_argument(
        '--no-recursive',
        action='store_true',
        help='calibration: inspect only the selected folder',
    )
    parser.add_argument(
        '--max-pair-seconds',
        type=float,
        default=CALIBRATION_OPTIONS['MAX_PAIR_SECONDS'],
        help='calibration: maximum time from bad to matching normal',
    )
    parser.add_argument(
        '--report',
        type=Path,
        help='calibration text report path',
    )
    return parser.parse_args()


def main():
    """Validate command combinations, run the workflow, and report failures."""
    args = parse_args()
    try:
        # Both workflows use the visible definitions at the top of this file.
        # There is deliberately no connection to an indi-allsky installation.
        settings = normalize_settings()
        if args.calibrate:
            if not args.input.is_dir():
                raise ValueError(
                    f'calibration input is not a folder: {args.input}'
                )
            if args.output or args.check_only:
                raise ValueError(
                    '--output and --check-only apply only to single files'
                )
            _payload, report_text = calibrate_folder(
                args.input,
                settings=settings,
                recursive=not args.no_recursive,
                max_pair_seconds=args.max_pair_seconds,
            )
            # Calibration intentionally writes one human-readable artifact.
            # It cannot be mistaken for an importable indi-allsky backup.
            report_path = args.report or (
                args.input / 'asi676mc_calibration_report.txt'
            )
            if not args.overwrite and report_path.exists():
                raise FileExistsError(
                    f'output exists; use --overwrite: {report_path}'
                )
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report_text, encoding='utf-8')
            print(report_text)
            print(f'Report: {report_path}')
            return

        if not args.input.is_file():
            raise ValueError(f'file not found: {args.input}')
        if args.check_only and args.output is not None:
            raise ValueError('--output cannot be used with --check-only')
        process_frame(
            args.input,
            output_path=args.output,
            check_only=args.check_only,
            overwrite=args.overwrite,
            settings=settings,
        )
    except (
        CalibrationError,
        FileExistsError,
        OSError,
        RuntimeError,
        ValueError,
    ) as error:
        raise SystemExit(f'error: {error}') from error


if __name__ == '__main__':
    main()
