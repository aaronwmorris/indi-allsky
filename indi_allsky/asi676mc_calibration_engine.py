"""Numerical engine for the integrated ASI676MC calibration workflow.

This module owns only the evidence-processing pipeline: inspect staged FITS,
match purple frames to compatible normal references, estimate the seven
camera-specific values, and validate the rounded result against every matched
frame. Session ownership, uploads, database discovery, cleanup, reporting, and
configuration updates remain in :mod:`indi_allsky.asi676mc_calibration`.

Live detection and repair are intentionally imported from
:mod:`indi_allsky.asi676mc`. Keeping one implementation prevents calibration
from approving values against an algorithm that differs from the image worker.
"""

from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from datetime import timezone
from pathlib import Path
import re
import statistics

import numpy

from . import asi676mc


# The runtime defaults are also the starting point for fitting. This is an
# alias, not a copy: tests and future changes see one authoritative definition.
DEFAULT_SETTINGS = asi676mc.DEFAULT_SETTINGS

# Calibration-only policy and sampling parameters. These values decide whether
# evidence is sufficient; they never alter live repair unless calibration
# succeeds and an administrator explicitly applies the derived settings.
CALIBRATION_OPTIONS = {
    # Evidence requirements.
    'MIN_BAD_PAIRS': 7,
    'MIN_GOOD_BAD_RATIO': 1.0,
    'RECOMMENDED_GOOD_BAD_RATIO': 2.0,
    'MAX_PAIR_SECONDS': 90.0,
    'MIN_EXPOSURE_LEVELS': 2,

    # Threshold discovery is deliberately stricter than merely finding two
    # k-means clusters. Each population must independently contain enough
    # frames for the normal calibration minimum, and every detector metric
    # needs a clean gap of at least ten percent. This keeps cloud movement or
    # ordinary scene changes from being presented as a camera-failure mode.
    'MIN_THRESHOLD_CLUSTER_SIZE': 7,
    'MIN_THRESHOLD_GAP_FRACTION': 0.10,
    'MIN_THRESHOLD_MARGIN_FRACTION': 0.15,

    # Sparse central-image sampling.  This is even to preserve Bayer parity.
    'SAMPLE_STEP': 8,
    'MIN_REFERENCE_VALUE': 512,
    'MAX_REFERENCE_VALUE': 62000,
    'MAX_SOURCE_VALUE_FOR_GAIN': 64000,
    'MAX_REFERENCE_CHANGE_FRACTION': 0.15,
    'REFERENCE_CHANGE_FLOOR': 256,
    'MIN_GAIN_SAMPLES_PER_PARITY': 500,
    'MIN_CALIBRATED_GAIN': 0.25,
    'MAX_CALIBRATED_GAIN': 4.0,
    'MAX_GAIN_RELATIVE_MAD': 0.15,

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
    'MAX_HIGHLIGHT_SCORE': 0.08,

    # A real phase-shift repair must make the bad capture materially closer to
    # its adjacent normal reference, not merely clear the detector ratios.
    'MAX_REPAIRED_REFERENCE_ERROR': 0.35,
    'MIN_REFERENCE_ERROR_IMPROVEMENT': 0.10,

}

MAX_DECODED_FITS_BYTES = 256 * 1024 * 1024


_FITS_SUFFIXES = ('.fit', '.fits', '.fts')
_COMPRESSED_FITS_SUFFIXES = tuple(
    '{0}.gz'.format(suffix)
    for suffix in _FITS_SUFFIXES
)
_OTHER_ASI_CAMERA_RE = re.compile(
    r'(?<![A-Z0-9])ASI[\s_-]*(?!676MC)[0-9]+[A-Z]*',
    re.IGNORECASE,
)
_FILENAME_TIME_RE = re.compile(r'(\d{8})[_-](\d{6})')

DETECTION_THRESHOLD_DETAILS = {
    'purple_ratio': (
        'PURPLE_RATIO_THRESHOLD',
        'Combined purple/green ratio threshold',
    ),
    'red_side_ratio': (
        'RED_SIDE_RATIO_THRESHOLD',
        'Red-side ratio threshold',
    ),
    'blue_side_ratio': (
        'BLUE_SIDE_RATIO_THRESHOLD',
        'Blue-side ratio threshold',
    ),
}


# ---------------------------------------------------------------------------
# FITS inspection and evidence indexing
# ---------------------------------------------------------------------------

def _fits_module():
    """Import indi-allsky's FITS dependency only when a job starts."""
    try:
        from astropy.io import fits
    except ModuleNotFoundError as error:
        raise RuntimeError(
            'indi-allsky FITS support is unavailable (Astropy could not be '
            'imported)'
        ) from error
    return fits


def _read_fits(path, copy=False):
    """Return image data, merged metadata, and the image-HDU index."""
    fits = _fits_module()
    with fits.open(path, memmap=False, uint=True) as hdulist:
        for index, hdu in enumerate(hdulist):
            if hdu.data is None:
                continue
            data = numpy.squeeze(numpy.asarray(hdu.data))
            if data.nbytes > MAX_DECODED_FITS_BYTES:
                raise ValueError(
                    'decoded FITS image exceeds the {0:d} MiB safety limit'.format(
                        MAX_DECODED_FITS_BYTES // (1024 * 1024),
                    )
                )
            if copy:
                data = data.copy()
            asi676mc.validate_raw_mosaic(data)
            # Camera metadata is commonly stored in the primary header while
            # pixels live in an extension. Image-HDU values override matching
            # primary values because they describe the selected array.
            header = hdulist[0].header.copy()
            if index:
                header.extend(hdu.header, update=True, unique=True)
            bayer = str(header.get('BAYERPAT', '')).strip().upper()
            if not bayer:
                raise ValueError('missing explicit BAYERPAT=RGGB metadata')
            if bayer != 'RGGB':
                raise ValueError(f'expected RGGB Bayer data, got {bayer}')
            return data, header, index
    raise ValueError('FITS file contains no image data')



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


def _camera_names(header):
    """Return all explicit camera identities from common FITS conventions."""
    values = []
    for key in (
        'CAMERA',
        'CAMMODEL',
        'CCDNAME',
        'INSTRUME',
        'TELESCOP',
    ):
        value = str(header.get(key, '')).strip()
        if value and value not in values:
            values.append(value)
    return values


def _camera_name(header):
    """Prefer a positive ASI676MC identity over generic legacy labels."""
    values = _camera_names(header)
    return next(
        (value for value in values if asi676mc.camera_name_matches(value)),
        values[0] if values else '',
    )


def _specific_camera_name(name):
    """Normalize ASI676MC names while discarding generic legacy labels."""
    # Reuse the live camera gate so calibration cannot silently recognize a
    # different set of ASI676MC name variants than runtime repair.
    if asi676mc.camera_name_matches(name):
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
    x_bayer_offset: int = 0
    y_bayer_offset: int = 0

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
            self.x_bayer_offset,
            self.y_bayer_offset,
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
    signature = asi676mc.frame_signature(data, settings)
    exposure = _header_float(header, 'EXPTIME', 'EXPOSURE', default=-1.0)
    gain = _header_float(header, 'GAIN', 'CCD-GAIN', default=-1.0)
    if not numpy.isfinite(exposure) or exposure <= 0.0:
        raise ValueError('exposure must be a finite value greater than zero')
    if not numpy.isfinite(gain) or gain < 0.0:
        raise ValueError('gain must be a finite non-negative value')
    xbin = int(_header_float(header, 'XBINNING', default=-1))
    ybin = int(_header_float(header, 'YBINNING', default=-1))
    if xbin != 1 or ybin != 1:
        raise ValueError('calibration requires XBINNING=1 and YBINNING=1')
    x_bayer_offset = int(_header_float(header, 'XBAYROFF', default=0))
    y_bayer_offset = int(_header_float(header, 'YBAYROFF', default=0))
    if x_bayer_offset or y_bayer_offset:
        raise ValueError('calibration requires zero Bayer offsets')
    camera_names = _camera_names(header)
    conflicting_asi = [
        name for name in camera_names
        if _OTHER_ASI_CAMERA_RE.search(name)
        and not asi676mc.camera_name_matches(name)
    ]
    if conflicting_asi:
        raise ValueError(
            'FITS contains a different or conflicting ASI camera identity: {0}'.format(
                ', '.join(conflicting_asi),
            )
        )
    camera_name = _camera_name(header)
    if not asi676mc.camera_name_matches(camera_name):
        raise ValueError('FITS does not explicitly identify an ASI676MC camera')
    return FrameRecord(
        path=path,
        timestamp=_parse_timestamp(header, path),
        exposure=exposure,
        gain=gain,
        xbin=xbin,
        ybin=ybin,
        x_bayer_offset=x_bayer_offset,
        y_bayer_offset=y_bayer_offset,
        shape=tuple(data.shape),
        bayer=str(header['BAYERPAT']).strip().upper(),
        camera_name=camera_name,
        signature=signature,
    )


def inspect_fits_metadata(path, metadata, settings):
    """Build a record from ratios captured when a database FITS was saved.

    The ratios are independent of detector thresholds, so the current settings
    can reclassify an older capture without decoding its full image. Missing or
    malformed legacy metadata falls back to normal FITS inspection in
    :func:`scan_folder`.
    """
    signature_data = metadata.get('signature') or {}
    signature = {
        name: float(signature_data[name])
        for name in DETECTION_THRESHOLD_DETAILS
    }
    if (
        not all(numpy.isfinite(value) and value > 0.0 for value in signature.values())
        or not metadata.get('width')
        or not metadata.get('height')
        or float(metadata.get('timestamp', 0.0)) <= 0.0
    ):
        raise ValueError('incomplete saved detector signature metadata')
    signature['is_bad'] = (
        signature['purple_ratio'] >= settings['PURPLE_RATIO_THRESHOLD']
        and signature['red_side_ratio'] >= settings['RED_SIDE_RATIO_THRESHOLD']
        and signature['blue_side_ratio'] >= settings['BLUE_SIDE_RATIO_THRESHOLD']
    )
    binmode = int(metadata.get('binmode', -1))
    exposure = float(metadata.get('exposure', -1.0))
    gain = float(metadata.get('gain', -1.0))
    camera_name = str(metadata.get('camera_name') or '')
    if binmode != 1:
        raise ValueError('calibration requires unbinned database FITS')
    if not numpy.isfinite(exposure) or exposure <= 0.0:
        raise ValueError('database FITS exposure is invalid')
    if not numpy.isfinite(gain) or gain < 0.0:
        raise ValueError('database FITS gain is invalid')
    if not asi676mc.camera_name_matches(camera_name):
        raise ValueError('database FITS is not positively identified as ASI676MC')
    return FrameRecord(
        path=path,
        timestamp=float(metadata['timestamp']),
        exposure=exposure,
        gain=gain,
        xbin=binmode,
        ybin=binmode,
        x_bayer_offset=0,
        y_bayer_offset=0,
        shape=(int(metadata['height']), int(metadata['width'])),
        bayer='RGGB',
        camera_name=camera_name,
        signature=signature,
    )


def scan_folder(
    folder,
    settings,
    recursive=True,
    metadata_by_name=None,
    progress_callback=None,
    progressive_check=None,
    initial_scan_count=14,
):
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
    detected_bad_count = 0
    metadata_by_name = metadata_by_name or {}
    total = len(paths)
    initial_target = min(total, max(14, int(initial_scan_count)))
    threshold_search_started = False
    for index, path in enumerate(paths, start=1):
        try:
            metadata = metadata_by_name.get(path.name)
            if metadata:
                metadata_camera_name = str(
                    metadata.get('camera_name') or ''
                )
                if (
                    metadata_camera_name
                    and not asi676mc.camera_name_matches(metadata_camera_name)
                ):
                    raise ValueError(
                        'database metadata identifies a non-ASI676MC camera'
                    )
                try:
                    record = inspect_fits_metadata(path, metadata, settings)
                except (KeyError, TypeError, ValueError):
                    record = inspect_fits(path, settings)
            else:
                record = inspect_fits(path, settings)
            records.append(record)
            if record.is_bad:
                detected_bad_count += 1
        except (OSError, OverflowError, TypeError, ValueError) as error:
            rejected.append((path, str(error)))
        if (
            index >= 14
            and detected_bad_count < CALIBRATION_OPTIONS['MIN_BAD_PAIRS']
        ):
            # Uploads are always scanned in full, while database searches may
            # stop early. Both surfaces should still tell the user when
            # the current detector has failed to find the minimum and the
            # analysis has moved on to population discovery.
            threshold_search_started = True
        phase = (
            'threshold_search'
            if threshold_search_started
            else 'detector_scan'
        )
        if progress_callback:
            progress_callback({
                'phase': phase,
                'processed_files': index,
                'total_files': total,
                'initial_target_files': initial_target,
                'detected_bad_count': detected_bad_count,
            })
        should_check = (
            progressive_check
            and len(records) >= 14
            and (
                index == 14
                or index % 10 == 0
                or index == total
                or detected_bad_count >= CALIBRATION_OPTIONS['MIN_BAD_PAIRS']
            )
        )
        if should_check and progressive_check(records):
            if progress_callback:
                progress_callback({
                    'phase': 'evidence_ready',
                    'processed_files': index,
                    'total_files': total,
                    'initial_target_files': initial_target,
                    'detected_bad_count': detected_bad_count,
                })
            break
    return records, rejected


def _compatible(left, right):
    """Compare all capture settings, including positive camera identity."""
    return left.compatibility_key == right.compatibility_key


def match_pairs(records, max_pair_seconds):
    """Match each failure to its nearest compatible normal on either side."""
    normal = [record for record in records if not record.is_bad]
    pairs = []
    unmatched = []
    for bad in (record for record in records if record.is_bad):
        candidates = [
            record for record in normal
            if _compatible(bad, record)
            and record.path != bad.path
            and record.timestamp != bad.timestamp
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


def _sample_array_planes(data, bad_source, step):
    """Copy sparse central Bayer planes from one decoded mosaic."""
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


def _sample_planes(record, bad_source, step):
    """Copy sparse central Bayer planes; shift bad source rows by one."""
    data, _header, _index = _read_fits(record.path)
    return _sample_array_planes(data, bad_source=bad_source, step=step)


def _reference_planes(pair, step):
    """Interpolate before/after samples to the purple-frame timestamp."""
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

    # Linear time interpolation estimates what the purple frame would have looked
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
    background job practical on Raspberry Pi systems with limited memory.
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
        value = estimates[name]['value']
        relative_mad = estimates[name]['mad'] / max(abs(value), 1.0e-12)
        estimates[name]['relative_mad'] = float(relative_mad)
        if (
            value < CALIBRATION_OPTIONS['MIN_CALIBRATED_GAIN']
            or value > CALIBRATION_OPTIONS['MAX_CALIBRATED_GAIN']
        ):
            raise CalibrationError(
                '{0} estimate {1:.5f} is outside the plausible ASI676MC '
                'range {2:g}-{3:g}'.format(
                    name,
                    value,
                    CALIBRATION_OPTIONS['MIN_CALIBRATED_GAIN'],
                    CALIBRATION_OPTIONS['MAX_CALIBRATED_GAIN'],
                )
            )
        if relative_mad > CALIBRATION_OPTIONS['MAX_GAIN_RELATIVE_MAD']:
            raise CalibrationError(
                '{0} varies too much between pairs (relative MAD {1:.3f}); '
                'the higher-ratio frames do not describe one stable camera '
                'failure'.format(name, relative_mad)
            )
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
    start_base, end_base = asi676mc.highlight_blend_base_boundaries(
        start_ratio,
        end_ratio,
    )
    base_ratio = base / high
    weight = numpy.clip(
        (
            base_ratio * asi676mc.HIGHLIGHT_BLEND_BASE_SCALE
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
    if selected[0] > CALIBRATION_OPTIONS['MAX_HIGHLIGHT_SCORE']:
        raise CalibrationError(
            'best clipped-highlight fit score {0:.4f} exceeds the safe '
            'maximum {1:.4f}'.format(
                selected[0],
                CALIBRATION_OPTIONS['MAX_HIGHLIGHT_SCORE'],
            )
        )
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
    """Summarize normal and purple detector metrics for the audit report."""
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
                'both normal and purple frames are required for signature ranges'
            )
        result[metric] = {
            'good_min': float(min(good)),
            'good_max': float(max(good)),
            'bad_min': float(min(bad)),
            'bad_max': float(max(bad)),
        }
    return result


def build_detection_threshold_suggestions(ranges, settings):
    """Build advisory thresholds only when every observed gap is strong."""
    minimum_gap = CALIBRATION_OPTIONS['MIN_THRESHOLD_GAP_FRACTION']
    suggestions = []
    for metric, (threshold_name, threshold_label) in (
        DETECTION_THRESHOLD_DETAILS.items()
    ):
        values = ranges[metric]
        normal_max = values['good_max']
        purple_min = values['bad_min']
        gap_fraction = (
            (purple_min - normal_max) / max(abs(normal_max), 1.0e-12)
        )
        if normal_max >= purple_min or gap_fraction < minimum_gap:
            raise CalibrationError(
                '{0} does not have the required clean gap between the two '
                'possible populations'.format(threshold_label)
            )

        current = float(settings[threshold_name])
        current_is_safe = normal_max < current <= purple_min
        suggested = (
            current
            if current_is_safe
            else round((normal_max + purple_min) / 2.0, 3)
        )
        suggestions.append({
            'metric': metric,
            'key': threshold_name,
            'label': threshold_label,
            'current': current,
            'suggested': suggested,
            'normal_max': normal_max,
            'purple_min': purple_min,
            'change_recommended': not current_is_safe,
        })

    if not any(item['change_recommended'] for item in suggestions):
        raise CalibrationError(
            'the configured thresholds already lie inside every observed gap; '
            'the detector result cannot be explained safely by threshold changes'
        )
    return suggestions


def assess_detection_threshold_margins(ranges, settings):
    """Describe how comfortably each configured threshold sits in its gap."""
    minimum_margin = CALIBRATION_OPTIONS['MIN_THRESHOLD_MARGIN_FRACTION']
    assessments = []
    for metric, (threshold_name, threshold_label) in (
        DETECTION_THRESHOLD_DETAILS.items()
    ):
        values = ranges[metric]
        normal_max = values['good_max']
        purple_min = values['bad_min']
        threshold = float(settings[threshold_name])
        gap = purple_min - normal_max
        if gap <= 0.0:
            continue
        position = (threshold - normal_max) / gap
        margin_fraction = min(position, 1.0 - position)
        assessments.append({
            'metric': metric,
            'key': threshold_name,
            'label': threshold_label,
            'current': threshold,
            'suggested': round((normal_max + purple_min) / 2.0, 3),
            'normal_max': normal_max,
            'purple_min': purple_min,
            'gap_position': position,
            'margin_fraction': margin_fraction,
            'marginal': margin_fraction < minimum_margin,
        })
    return assessments


def threshold_suggestion_payload(
    records,
    evidence,
    ranges,
    suggestions,
    detected_bad_count,
):
    """Collect the shared preliminary result for inferred or known labels."""
    population_evidence = [
        {
            'name': record.path.name,
            'timestamp_utc': datetime.fromtimestamp(
                record.timestamp,
                tz=timezone.utc,
            ).isoformat(),
            'population': 'higher ratio' if record.is_bad else 'lower ratio',
            'purple_ratio': record.signature['purple_ratio'],
            'red_side_ratio': record.signature['red_side_ratio'],
            'blue_side_ratio': record.signature['blue_side_ratio'],
        }
        for record in sorted(records, key=lambda item: item.timestamp)
    ]
    return {
        'outcome': 'threshold_suggestion',
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'quality': {
            **evidence,
            'detected_bad_count': int(detected_bad_count),
            'likely_purple_count': sum(record.is_bad for record in records),
            'likely_normal_count': sum(not record.is_bad for record in records),
        },
        'signature_ranges': ranges,
        'threshold_suggestions': suggestions,
        'population_evidence': population_evidence,
    }


def suggest_detection_thresholds(records, settings, max_pair_seconds):
    """Return a preliminary threshold result for two clean populations.

    This path is used only when the configured detector cannot identify the
    seven purple frames required for normal calibration. It clusters the three
    detector ratios without using database flags or filenames, then applies
    the same adjacency, compatibility, exposure, and camera-identity checks as
    calibration. A result is advisory: repair constants are not fitted and the
    web layer never applies these thresholds automatically.
    """
    minimum = CALIBRATION_OPTIONS['MIN_THRESHOLD_CLUSTER_SIZE']
    if len(records) < minimum * 2:
        raise CalibrationError(
            'at least {0} compatible FITS are required for automatic '
            'threshold analysis'.format(minimum * 2)
        )

    metric_names = tuple(DETECTION_THRESHOLD_DETAILS)
    metric_values = numpy.asarray([
        [record.signature[name] for name in metric_names]
        for record in records
    ], dtype=numpy.float64)
    if (
        not numpy.all(numpy.isfinite(metric_values))
        or numpy.any(metric_values <= 0.0)
    ):
        raise CalibrationError(
            'detector ratios contain non-finite or non-positive values'
        )

    # Ratios are multiplicative, so logarithms make proportional differences
    # comparable. Standardising each metric gives the combined ratio and both
    # side ratios equal influence instead of letting the widest range dominate.
    log_values = numpy.log(metric_values)
    scale = numpy.std(log_values, axis=0)
    if numpy.any(scale <= numpy.finfo(numpy.float64).eps):
        raise CalibrationError(
            'the FITS do not vary in all three detector ratios'
        )
    standardized = (
        log_values - numpy.mean(log_values, axis=0)
    ) / scale

    population_score = numpy.sum(standardized, axis=1)
    centroids = numpy.vstack((
        standardized[numpy.argmin(population_score)],
        standardized[numpy.argmax(population_score)],
    ))
    labels = numpy.zeros(len(records), dtype=numpy.int8)
    for _iteration in range(50):
        distances = numpy.sum(
            (standardized[:, numpy.newaxis, :] - centroids) ** 2,
            axis=2,
        )
        next_labels = numpy.argmin(distances, axis=1).astype(numpy.int8)
        counts = numpy.bincount(next_labels, minlength=2)
        if numpy.any(counts == 0):
            raise CalibrationError(
                'the detector ratios do not form two stable populations'
            )
        next_centroids = numpy.vstack([
            numpy.mean(standardized[next_labels == index], axis=0)
            for index in range(2)
        ])
        if numpy.array_equal(next_labels, labels):
            labels = next_labels
            centroids = next_centroids
            break
        labels = next_labels
        centroids = next_centroids

    counts = numpy.bincount(labels, minlength=2)
    if numpy.any(counts < minimum):
        raise CalibrationError(
            'the two possible populations contain {0} and {1} FITS; at least '
            '{2} are required in each'.format(counts[0], counts[1], minimum)
        )

    raw_centroids = numpy.vstack([
        numpy.mean(metric_values[labels == index], axis=0)
        for index in range(2)
    ])
    if numpy.all(raw_centroids[0] < raw_centroids[1]):
        purple_label = 1
    elif numpy.all(raw_centroids[1] < raw_centroids[0]):
        purple_label = 0
    else:
        raise CalibrationError(
            'the possible higher-ratio population is not higher in all three '
            'purple-frame detector ratios'
        )
    normal_label = 1 - purple_label

    # A frame already recognised by the live detector must never land in the
    # inferred normal group. Such disagreement means the collection cannot
    # safely explain the detector miss with one set of thresholds.
    conflicting_detected = sum(
        record.is_bad and labels[index] == normal_label
        for index, record in enumerate(records)
    )
    if conflicting_detected:
        raise CalibrationError(
            '{0} currently detected purple frame(s) fall in the lower-ratio '
            'population'.format(conflicting_detected)
        )

    inferred_records = [
        replace(
            record,
            signature={
                **record.signature,
                'is_bad': bool(labels[index] == purple_label),
            },
        )
        for index, record in enumerate(records)
    ]
    ranges = signature_ranges(inferred_records)
    pairs, unmatched = match_pairs(inferred_records, max_pair_seconds)
    evidence = validate_evidence(
        inferred_records,
        pairs,
        unmatched,
        allow_unmatched=True,
    )

    suggestions = build_detection_threshold_suggestions(ranges, settings)
    return threshold_suggestion_payload(
        inferred_records,
        evidence,
        ranges,
        suggestions,
        detected_bad_count=sum(record.is_bad for record in records),
    )


def validate_signature_separation(ranges, settings):
    """Require clean per-ratio evidence around every configured threshold.

    Live detection requires all three ratios at once, but calibration is more
    conservative: each measured ratio must independently separate the supplied
    normal and purple populations. A successful fit should not conceal a weak
    detector margin or silently change a user's detection settings.
    """
    for metric, (threshold_name, threshold_label) in (
        DETECTION_THRESHOLD_DETAILS.items()
    ):
        values = ranges[metric]
        threshold = settings[threshold_name]
        normal_max = values['good_max']
        purple_min = values['bad_min']
        if normal_max >= purple_min:
            raise CalibrationError(
                'Configured {0} cannot be checked because the supplied ranges '
                'overlap (normal maximum {1:.3f}, purple minimum {2:.3f}). No '
                'single threshold cleanly separates this evidence. Calibration '
                'stopped without changing settings; check the selected files.'
                .format(threshold_label, normal_max, purple_min)
            )

        suggested = (normal_max + purple_min) / 2.0
        if values['good_max'] >= threshold:
            raise CalibrationError(
                'Configured {0} is {1:.3f}, but a frame currently classified '
                'as normal reaches {2:.3f}. This may be a normal outlier or an '
                'unrecognised purple frame. The observed gap permits a value '
                'above {2:.3f} and no more than {3:.3f} (midpoint {4:.3f}). '
                'Calibration stopped without changing settings; review the '
                'evidence and threshold, then run it again.'.format(
                    threshold_label,
                    threshold,
                    normal_max,
                    purple_min,
                    suggested,
                )
            )
        if values['bad_min'] < threshold:
            raise CalibrationError(
                'Configured {0} is {1:.3f}, but the supplied purple range '
                'falls to {2:.3f}. The observed gap permits a value above '
                '{3:.3f} and no more than {2:.3f} (midpoint {4:.3f}). '
                'Calibration stopped without changing settings; review the '
                'evidence and threshold, then run it again.'.format(
                    threshold_label,
                    threshold,
                    purple_min,
                    normal_max,
                    suggested,
                )
            )


def _exposure_levels(pairs):
    """Return distinct exposures represented by matched failures."""
    return sorted({round(pair.bad.exposure, 12) for pair in pairs})


class CalibrationError(RuntimeError):
    """Raised when an evidence collection cannot support safe calibration."""


def validate_evidence(records, pairs, unmatched, allow_unmatched=False):
    """Refuse calibration when the dataset cannot support safe conclusions.

    Seven matched failures are the minimum statistical base.  Multiple
    exposures reduce the chance that constants describe only one brightness
    regime, and explicit mixed-camera collections are rejected outright.
    """
    bad_records = [record for record in records if record.is_bad]
    normal_records = [record for record in records if not record.is_bad]
    invalid_records = [
        record for record in records
        if (
            not asi676mc.camera_name_matches(record.camera_name)
            or record.bayer != 'RGGB'
            or record.xbin != 1
            or record.ybin != 1
            or record.x_bayer_offset != 0
            or record.y_bayer_offset != 0
            or not numpy.isfinite(record.exposure)
            or record.exposure <= 0.0
            or not numpy.isfinite(record.gain)
            or record.gain < 0.0
        )
    ]
    if invalid_records:
        raise CalibrationError(
            '{0} evidence file(s) lack the required ASI676MC RAW16 RGGB, '
            'unbinned, zero-offset capture identity or valid exposure/gain '
            'metadata'.format(len(invalid_records))
        )
    minimum = CALIBRATION_OPTIONS['MIN_BAD_PAIRS']
    if len(pairs) < minimum:
        raise CalibrationError(
            f'{len(pairs)} matched purple frames found; at least {minimum} required'
        )
    if unmatched and not allow_unmatched:
        raise CalibrationError(
            f'{len(unmatched)} detected purple frames have no compatible nearby normal'
        )

    unique_good = {
        reference.path
        for pair in pairs
        for reference in pair.references
    }
    ratio = len(unique_good) / len(pairs)
    if ratio < CALIBRATION_OPTIONS['MIN_GOOD_BAD_RATIO']:
        raise CalibrationError(
            'matched normal/purple ratio is {0:.2f}:1; at least '
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
    if explicit_names != {'asi676mc'}:
        raise CalibrationError(
            'all evidence must explicitly identify ASI676MC; found: '
            + ', '.join(sorted(explicit_names))
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


def _reference_error(observed_planes, reference_planes, stable_masks):
    """Return a robust sparse error against a time-matched normal reference."""
    parity_errors = []
    minimum = CALIBRATION_OPTIONS['MIN_REFERENCE_VALUE']
    maximum = CALIBRATION_OPTIONS['MAX_REFERENCE_VALUE']
    for observed, reference, stable in zip(
        observed_planes,
        reference_planes,
        stable_masks,
    ):
        observed = observed.astype(numpy.float64)
        mask = (
            stable
            & (reference >= minimum)
            & (reference <= maximum)
            & numpy.isfinite(observed)
        )
        required_samples = min(100, max(16, observed.size // 4))
        if numpy.count_nonzero(mask) < required_samples:
            continue
        relative_error = (
            numpy.abs(observed[mask] - reference[mask])
            / numpy.maximum(reference[mask], minimum)
        )
        parity_errors.append(float(numpy.median(relative_error)))
    if len(parity_errors) != 4:
        raise CalibrationError(
            'too few stable samples to compare a repaired frame with its reference'
        )
    return float(statistics.mean(parity_errors))


def _best_gain_only_planes(observed_planes, reference_planes, stable_masks):
    """Fit the best counterfactual with no row-phase correction."""
    corrected = []
    minimum = CALIBRATION_OPTIONS['MIN_REFERENCE_VALUE']
    maximum = CALIBRATION_OPTIONS['MAX_REFERENCE_VALUE']
    for observed, reference, stable in zip(
        observed_planes,
        reference_planes,
        stable_masks,
    ):
        observed_float = observed.astype(numpy.float64)
        mask = (
            stable
            & (reference >= minimum)
            & (reference <= maximum)
            & (observed_float >= minimum)
        )
        if not numpy.any(mask):
            raise CalibrationError(
                'too few samples for the gain-only phase countercheck'
            )
        ratio = float(numpy.median(observed_float[mask] / reference[mask]))
        if not numpy.isfinite(ratio) or ratio <= 0.0:
            raise CalibrationError('invalid gain-only phase countercheck')
        corrected.append(observed_float / ratio)
    return tuple(corrected)


def validate_calibrated_frames(pairs, settings):
    """Apply final rounded settings to every pair without writing outputs."""
    repaired_count = 0
    normal_count = 0
    similarity_checks = []
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
        original = data.copy()
        reference_planes, stable_masks = _reference_planes(
            pair,
            CALIBRATION_OPTIONS['SAMPLE_STEP'],
        )
        original_planes = _sample_array_planes(
            original,
            bad_source=False,
            step=CALIBRATION_OPTIONS['SAMPLE_STEP'],
        )
        original_error = _reference_error(
            original_planes,
            reference_planes,
            stable_masks,
        )
        result = asi676mc.repair_if_needed(data, settings)
        if not result['repaired'] or result['validation_failed']:
            raise CalibrationError(
                f'calibrated repair validation failed for {pair.bad.path}'
            )
        repaired_planes = _sample_array_planes(
            data,
            bad_source=False,
            step=CALIBRATION_OPTIONS['SAMPLE_STEP'],
        )
        repaired_error = _reference_error(
            repaired_planes,
            reference_planes,
            stable_masks,
        )

        # Compare with a counterfactual that applies the fitted gains without
        # the ASI676MC one-row phase correction. A genuine phase-shift failure
        # should match its neighbors better after the row correction; two
        # ordinary colour/brightness populations generally will not.
        unshifted_corrected = _best_gain_only_planes(
            original_planes,
            reference_planes,
            stable_masks,
        )
        unshifted_error = _reference_error(
            unshifted_corrected,
            reference_planes,
            stable_masks,
        )
        improvement = CALIBRATION_OPTIONS['MIN_REFERENCE_ERROR_IMPROVEMENT']
        if repaired_error > CALIBRATION_OPTIONS['MAX_REPAIRED_REFERENCE_ERROR']:
            raise CalibrationError(
                'repaired frame remains too different from its normal '
                'reference: {0}'.format(pair.bad.path)
            )
        if repaired_error > original_error * (1.0 - improvement):
            raise CalibrationError(
                'repair does not materially improve agreement with the normal '
                'reference: {0}'.format(pair.bad.path)
            )
        if repaired_error > unshifted_error * (1.0 - improvement):
            raise CalibrationError(
                'evidence does not confirm the ASI676MC one-row phase shift: '
                '{0}'.format(pair.bad.path)
            )
        similarity_checks.append({
            'name': pair.bad.path.name,
            'original_error': original_error,
            'gain_only_error': unshifted_error,
            'repaired_error': repaired_error,
        })
        repaired_count += 1

    # A normal frame must take the fast no-op path.  The array comparison also
    # guards against future changes accidentally touching normal input.
    for record in unique_normal.values():
        data, _header, _index = _read_fits(record.path, copy=True)
        original = data.copy()
        result = asi676mc.repair_if_needed(data, settings)
        if result['repaired'] or result['signature_before']['is_bad']:
            raise CalibrationError(
                f'calibrated detector rejects normal frame {record.path}'
            )
        if not numpy.array_equal(data, original):
            raise CalibrationError(
                f'normal-frame validation mutated {record.path}'
            )
        normal_count += 1
    return repaired_count, normal_count, similarity_checks


def calibration_payload(
    settings,
    evidence,
    ranges,
    gains,
    saturation_threshold,
    saturation_plateau,
    highlight,
    rejected,
):
    """Collect the seven derived settings and their supporting audit data."""
    # Round gains exactly as the web form stores them.  The final validation
    # below uses these rounded values, not higher-precision hidden estimates.
    calibrated = dict(settings)
    for name, result in gains.items():
        calibrated[name] = round(result['value'], 5)
    calibrated['SOURCE_SATURATION_THRESHOLD'] = saturation_threshold
    calibrated['HIGHLIGHT_BLEND_START_RATIO'] = highlight['start_ratio']
    calibrated['HIGHLIGHT_BLEND_END_RATIO'] = highlight['end_ratio']

    derived_settings = {
        key: calibrated[key]
        for key in (
            'GAIN_R',
            'GAIN_G1',
            'GAIN_G2',
            'GAIN_B',
            'SOURCE_SATURATION_THRESHOLD',
            'HIGHLIGHT_BLEND_START_RATIO',
            'HIGHLIGHT_BLEND_END_RATIO',
        )
    }

    return {
        'outcome': 'calibration',
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
        'derived_settings': derived_settings,
    }


def dataset_has_actionable_result(records, settings, max_pair_seconds):
    """Return whether progressive discovery can safely stop reading FITS.

    This performs only lightweight evidence checks. Expensive pixel fitting is
    still run once, after the scan stops. Failures are intentionally swallowed:
    another older batch may add the missing outlier, exposure, or reference.
    """
    minimum = CALIBRATION_OPTIONS['MIN_BAD_PAIRS']
    bad_count = sum(record.is_bad for record in records)
    normal_count = len(records) - bad_count
    if bad_count >= minimum and normal_count >= minimum:
        try:
            pairs, unmatched = match_pairs(records, max_pair_seconds)
            validate_evidence(
                records,
                pairs,
                unmatched,
                allow_unmatched=True,
            )
            ranges = signature_ranges(records)
            try:
                validate_signature_separation(ranges, settings)
            except CalibrationError:
                build_detection_threshold_suggestions(ranges, settings)
            return True
        except CalibrationError:
            return False

    try:
        suggest_detection_thresholds(records, settings, max_pair_seconds)
        return True
    except CalibrationError:
        return False



def calibrate_folder(
    folder,
    settings=None,
    recursive=True,
    max_pair_seconds=None,
    allow_unmatched=False,
    metadata_by_name=None,
    progress_callback=None,
    progressive=False,
    initial_scan_count=14,
):
    """Run complete calibration for one staged evidence directory.

    The sequence matters: cheap structural/evidence checks happen before
    expensive sample fitting, and full-resolution validation happens last with
    the rounded values that a user will actually type into indi-allsky.
    """
    config = asi676mc.normalize_settings(settings)
    if max_pair_seconds is None:
        max_pair_seconds = CALIBRATION_OPTIONS['MAX_PAIR_SECONDS']

    print(f'Scanning FITS files under: {folder}')
    progressive_check = None
    if progressive:
        progressive_check = lambda records: dataset_has_actionable_result(
            records,
            config,
            max_pair_seconds,
        )
    records, rejected = scan_folder(
        folder,
        config,
        recursive=recursive,
        metadata_by_name=metadata_by_name,
        progress_callback=progress_callback,
        progressive_check=progressive_check,
        initial_scan_count=max(14, int(initial_scan_count)),
    )
    scanned_file_count = len(records) + len(rejected)
    available_file_count = (
        len(metadata_by_name)
        if metadata_by_name
        else scanned_file_count
    )

    def finish_scan_payload(payload):
        """Attach progressive-scan coverage fields to either result shape."""
        payload['quality']['scanned_file_count'] = scanned_file_count
        payload['quality']['available_file_count'] = available_file_count
        payload['quality']['search_stopped_early'] = (
            scanned_file_count < available_file_count
        )
        return payload

    if not records:
        raise CalibrationError('no compatible RAW16 RGGB FITS files found')
    bad_count = sum(record.is_bad for record in records)
    normal_count = len(records) - bad_count
    minimum = CALIBRATION_OPTIONS['MIN_BAD_PAIRS']
    if bad_count < minimum or normal_count < minimum:
        print(
            'Configured detector found {0} purple and {1} normal FITS; '
            'checking for two clean ratio populations...'.format(
                bad_count,
                normal_count,
            )
        )
        try:
            payload = suggest_detection_thresholds(
                records,
                config,
                max_pair_seconds,
            )
        except CalibrationError as error:
            raise CalibrationError(
                'configured detection produced {0} purple and {1} normal '
                'FITS. Automatic threshold analysis could not make a safe '
                'suggestion: {2}'.format(bad_count, normal_count, error)
            ) from error
        payload['quality']['rejected_file_count'] = len(rejected)
        payload['rejected_files'] = [
            {
                'name': Path(path).name,
                'reason': str(reason),
            }
            for path, reason in rejected
        ]
        print(
            'Found two clean populations with {0} likely purple and {1} '
            'likely normal FITS; returning threshold suggestions only.'.format(
                payload['quality']['likely_purple_count'],
                payload['quality']['likely_normal_count'],
            )
        )
        return finish_scan_payload(payload)
    print(
        f'Classified {len(records)} files: '
        f'{bad_count} purple, {normal_count} normal'
    )

    pairs, unmatched = match_pairs(records, max_pair_seconds)
    evidence = validate_evidence(
        records,
        pairs,
        unmatched,
        allow_unmatched=allow_unmatched,
    )
    ranges = signature_ranges(records)
    try:
        validate_signature_separation(ranges, config)
    except CalibrationError as separation_error:
        # The detector can find enough frames through its three-way AND rule
        # even when one individual threshold lies outside that metric's safe
        # gap. Present the same review-and-rerun result used for an outright
        # detector miss instead of fitting repair constants against a weak
        # detector configuration.
        try:
            suggestions = build_detection_threshold_suggestions(
                ranges,
                config,
            )
        except CalibrationError:
            raise separation_error
        payload = threshold_suggestion_payload(
            records,
            evidence,
            ranges,
            suggestions,
            detected_bad_count=bad_count,
        )
        payload['quality']['rejected_file_count'] = len(rejected)
        payload['rejected_files'] = [
            {
                'name': Path(path).name,
                'reason': str(reason),
            }
            for path, reason in rejected
        ]
        print(
            'Detector populations are clear, but one or more configured '
            'thresholds lie outside their safe gaps; returning threshold '
            'suggestions only.'
        )
        return finish_scan_payload(payload)
    threshold_assessment = assess_detection_threshold_margins(ranges, config)
    print(
        'Matched {0} purple frames to {1} distinct normal frames '
        '({2:.2f}:1)'.format(
            evidence['pair_count'],
            evidence['unique_good_count'],
            evidence['good_bad_ratio'],
        )
    )

    if progress_callback:
        progress_callback({
            'phase': 'fitting',
            'processed_files': scanned_file_count,
            'total_files': available_file_count,
            'detected_bad_count': bad_count,
        })
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
        config,
        evidence,
        ranges,
        gains_detail,
        saturation_threshold,
        plateau,
        highlight,
        rejected,
    )
    payload['threshold_assessment'] = threshold_assessment
    print('Validating calibrated settings against every matched frame...')
    if progress_callback:
        progress_callback({
            'phase': 'validating',
            'processed_files': scanned_file_count,
            'total_files': available_file_count,
            'detected_bad_count': bad_count,
        })
    validation_settings = dict(config)
    validation_settings.update(payload['derived_settings'])
    (
        repaired_count,
        normal_validation_count,
        similarity_checks,
    ) = validate_calibrated_frames(
        pairs,
        validation_settings,
    )
    payload['quality']['validated_bad_repairs'] = repaired_count
    payload['quality']['validated_normal_frames'] = normal_validation_count
    payload['quality']['reference_similarity_checks'] = similarity_checks
    payload['quality']['worst_repaired_reference_error'] = max(
        check['repaired_error'] for check in similarity_checks
    )
    return finish_scan_payload(payload)
