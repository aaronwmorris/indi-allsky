"""Web-session support for ASI676MC FITS calibration.

The web workflow imports indi-allsky's numerical calibration engine directly
as a Python module; it never starts a shell command or an external FITS program.

This module owns the web-specific concerns around that engine:

* private, per-user upload sessions;
* conservative file-count and storage limits;
* atomic manifest/result files shared by gunicorn and the video worker;
* deletion of uploaded FITS or database staging links as soon as a job finishes;
* a compact result shape suitable for polling from the browser.
* a web-native text report that never exposes private staging paths.

Session data lives below Flask's non-public instance directory by default.
This is important because the capture service uses systemd ``PrivateTmp`` and
therefore cannot reliably read files uploaded into the web process's ``/tmp``.
Deployments may override the location with ``ASI676MC_CALIBRATION_FOLDER``.
"""

from contextlib import redirect_stdout
from datetime import datetime
from datetime import timezone
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import textwrap
import time
import unicodedata
import uuid


SESSION_ID_RE = re.compile(r'^[0-9a-f]{32}$')
FITS_SUFFIXES = ('.fit', '.fits', '.fts')

# An uncompressed full-resolution ASI676MC FITS is roughly tens of megabytes.
# These limits comfortably allow sizeable calibration collections while
# preventing one authenticated browser session from consuming the whole disk.
MAX_FILE_COUNT = 200
MAX_DATABASE_FILE_COUNT = 300
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_SESSION_BYTES = 2 * 1024 * 1024 * 1024
SESSION_RETENTION_SECONDS = 7 * 24 * 60 * 60
DATABASE_BAD_FRAME_MIN = 7
DATABASE_BAD_FRAME_MAX = 100
DATABASE_CAPTURE_TIME_TOLERANCE = 1.0

# Comparison tolerances are deliberately much smaller than the calibration
# engine's useful fitting resolution.  They are only used to tell an operator
# that saving the result is unlikely to change repaired pixels noticeably; the
# derived values themselves are never rounded or altered by this comparison.
CONFIGURATION_EQUIVALENCE_TOLERANCES = {
    'GAIN_R': {'rel_tol': 0.005, 'abs_tol': 0.00001},
    'GAIN_G1': {'rel_tol': 0.005, 'abs_tol': 0.00001},
    'GAIN_G2': {'rel_tol': 0.005, 'abs_tol': 0.00001},
    'GAIN_B': {'rel_tol': 0.005, 'abs_tol': 0.00001},
    # The fitter already snaps a measured plateau within 64 RAW16 levels to
    # the proven default, so a difference inside the same band is negligible.
    'SOURCE_SATURATION_THRESHOLD': {'rel_tol': 0.0, 'abs_tol': 64.0},
    # The settings form exposes blend ratios at 0.01 precision.  Half one
    # displayed step covers harmless serialization/rounding differences only.
    'HIGHLIGHT_BLEND_START_RATIO': {'rel_tol': 0.0, 'abs_tol': 0.005},
    'HIGHLIGHT_BLEND_END_RATIO': {'rel_tol': 0.0, 'abs_tol': 0.005},
}

DERIVED_VALUE_KEYS = (
    'GAIN_R',
    'GAIN_G1',
    'GAIN_G2',
    'GAIN_B',
    'SOURCE_SATURATION_THRESHOLD',
    'HIGHLIGHT_BLEND_START_RATIO',
    'HIGHLIGHT_BLEND_END_RATIO',
)

DERIVED_VALUE_LABELS = {
    'GAIN_R': 'Bad-frame Gain R',
    'GAIN_G1': 'Bad-frame Gain G1',
    'GAIN_G2': 'Bad-frame Gain G2',
    'GAIN_B': 'Bad-frame Gain B',
    'SOURCE_SATURATION_THRESHOLD': 'Source Saturation Threshold',
    'HIGHLIGHT_BLEND_START_RATIO': 'Highlight Blend Start Ratio',
    'HIGHLIGHT_BLEND_END_RATIO': 'Highlight Blend End Ratio',
}


def _counted_item(count, singular, plural=None):
    """Return a readable count without exposing ``frame(s)`` style copy."""
    count = int(count)
    noun = singular if count == 1 else (plural or singular + 's')
    return '{0} {1}'.format(count, noun)


def capture_configuration_guidance(config):
    """Describe whether current capture settings retain calibration evidence.

    The current configuration cannot prove how older files were captured, so
    this is deliberately advisory.  Automatic discovery will still inspect
    the FITS that actually exist. This guidance explains why future purple
    frames will produce low-disk pairs, full-sequence groups, or no usable
    untouched evidence at all. The returned guidance intentionally combines
    the active conditions into one concise, severity-ranked explanation.
    """
    config = config if isinstance(config, dict) else {}
    repair = config.get('IMAGE_ASI676MC_REPAIR', {})
    repair = repair if isinstance(repair, dict) else {}

    repair_enabled = bool(repair.get('ENABLE', False))
    exclude_only = bool(repair.get('EXCLUDE_ONLY', True))
    diagnostic_fits = bool(repair.get('SAVE_DIAGNOSTIC_FITS', False))
    periodic_fits = bool(config.get('IMAGE_SAVE_FITS', False))
    compressed_fits = bool(config.get('IMAGE_SAVE_FITS_COMPRESSED', False))
    try:
        fits_period = int(config.get('IMAGE_SAVE_FITS_PERIOD', 7200))
    except (TypeError, ValueError):
        fits_period = None
    try:
        retention_days = int(config.get('IMAGE_FITS_EXPIRE_DAYS', 10))
    except (TypeError, ValueError):
        retention_days = None
    fits_period_valid = fits_period is not None and fits_period >= 0
    # Match the Image Settings validator: zero days is not a valid retention
    # policy even though it can be represented in a hand-edited config file.
    retention_valid = retention_days is not None and retention_days >= 1

    if not periodic_fits:
        periodic_text = 'Off'
    elif fits_period == 0:
        periodic_text = 'Every Image'
    elif not fits_period_valid:
        periodic_text = 'On (invalid interval)'
    else:
        periodic_text = 'Every {0} seconds'.format(fits_period)

    mode_text = (
        'Off'
        if not repair_enabled
        else ('Exclude Only' if exclude_only else 'Repair active')
    )
    if diagnostic_fits and repair_enabled:
        diagnostic_text = 'On'
    elif diagnostic_fits:
        diagnostic_text = 'Inactive (handling off)'
    else:
        diagnostic_text = 'Off'
    if compressed_fits and periodic_fits:
        compression_text = 'On'
    elif compressed_fits:
        compression_text = 'Inactive (ordinary FITS off)'
    else:
        compression_text = 'Off'
    facts = [
        {'label': 'Repair mode', 'value': mode_text},
        {
            'label': 'Bad + following RAW FITS',
            'value': diagnostic_text,
        },
        {'label': 'Ordinary FITS', 'value': periodic_text},
        {
            'label': 'Ordinary FITS compression',
            'value': compression_text,
        },
        {
            'label': 'FITS retention',
            'value': (
                _counted_item(retention_days, 'day')
                if retention_valid
                else 'Invalid value'
            ),
        },
    ]

    # Resolve the full switch combination into one operator-facing outcome.
    # Lead with whether future evidence will be usable, then give the shortest
    # concrete settings change. Implementation details matter only when they
    # explain why an apparently enabled saving mode is insufficient.
    guidance_level = 'warning'
    guidance_title = 'FITS capture settings need attention'
    guidance_sentences = []
    if not repair_enabled:
        guidance_title = 'Purple-frame handling is off'
        if diagnostic_fits:
            guidance_sentences.append(
                'New purple frames will not be marked for automatic saved FITS '
                'search. The configured Bad + following RAW FITS option is '
                'inactive until purple-frame handling is enabled.'
            )
        else:
            guidance_sentences.append(
                'New purple frames will not be marked for automatic saved FITS '
                'search.'
            )
        if periodic_fits and fits_period == 0:
            # Database discovery can open indi-allsky's gzip-compressed FITS,
            # but the browser uploader deliberately accepts only uncompressed
            # files. With no purple-frame flags, decompression is therefore the
            # only way to use this particular saved sequence manually.
            if compressed_fits:
                guidance_sentences.append(
                    'Ordinary FITS saving is set to Every Image with '
                    'compression, so complete sequences are still being saved. '
                    'Manual upload accepts uncompressed FITS only; decompress '
                    'the selected files first. For automatic discovery of '
                    'future purple frames, enable handling in Exclude Only mode.'
                )
            else:
                guidance_sentences.append(
                    'Ordinary FITS saving is set to Every Image, so complete '
                    'sequences are still being saved and can be uploaded for '
                    'calibration. For automatic discovery of future purple '
                    'frames, enable handling in Exclude Only mode.'
                )
        elif periodic_fits and not fits_period_valid:
            if diagnostic_fits:
                guidance_sentences.append(
                    'The ordinary FITS interval is invalid. Correct or disable '
                    'it, then enable purple-frame handling in Exclude Only mode; '
                    'the configured Bad + following RAW FITS option will begin '
                    'low-disk collection.'
                )
            else:
                guidance_sentences.append(
                    'The ordinary FITS interval is invalid. Enable purple-frame '
                    'handling in Exclude Only mode, then turn on Bad + following '
                    'RAW FITS for low disk use or set ordinary FITS to Every '
                    'Image for complete sequences.'
                )
        elif periodic_fits:
            if diagnostic_fits:
                guidance_sentences.append(
                    'Periodic ordinary FITS may miss a randomly occurring purple '
                    'frame. Enable purple-frame handling in Exclude Only mode; '
                    'the configured Bad + following RAW FITS option will then '
                    'provide the more reliable low-disk source.'
                )
            else:
                guidance_sentences.append(
                    'Periodic ordinary FITS may miss a randomly occurring purple '
                    'frame. Enable purple-frame handling in Exclude Only mode, '
                    'then turn on Bad + following RAW FITS for low disk use or '
                    'set ordinary FITS to Every Image for complete sequences.'
                )
        else:
            if diagnostic_fits:
                guidance_sentences.append(
                    'No FITS files are currently being saved. Enable purple-frame '
                    'handling in Exclude Only mode; the configured Bad + '
                    'following RAW FITS option will then begin low-disk '
                    'collection.'
                )
            else:
                guidance_sentences.append(
                    'No FITS saving is enabled. To collect calibration data, '
                    'enable purple-frame handling in Exclude Only mode, then '
                    'turn on Bad + following RAW FITS for low disk use or set '
                    'ordinary FITS to Every Image for complete sequences.'
                )
    elif exclude_only:
        if diagnostic_fits:
            guidance_level = 'success'
            if periodic_fits and fits_period == 0:
                guidance_title = 'Ready to collect complete FITS sequences'
                guidance_sentences.append(
                    'Exclude Only leaves purple frames unchanged. Bad + '
                    'following RAW FITS saves each detected purple frame '
                    'unchanged and also saves the immediately following frame. '
                    'Ordinary FITS saving set to Every Image can add normal '
                    'references on either side for stronger good/bad/good '
                    'groups. Incompatible following frames are ignored. This '
                    'combination uses the most disk space.'
                )
            elif periodic_fits and not fits_period_valid:
                guidance_level = 'warning'
                guidance_title = 'Ordinary FITS setting needs correction'
                guidance_sentences.append(
                    'Exclude Only and Bad + following RAW FITS provide the '
                    'low-disk calibration source. The ordinary FITS interval '
                    'is invalid; correct it or turn ordinary FITS saving off.'
                )
            elif periodic_fits:
                guidance_title = 'Ready for low-disk FITS collection'
                guidance_sentences.append(
                    'Exclude Only leaves purple frames unchanged, and Bad + '
                    'following RAW FITS saves each detected purple frame '
                    'unchanged and also saves the immediately following frame. '
                    'The tool uses only compatible normal references. Periodic '
                    'ordinary FITS may add another compatible reference but is '
                    'not required.'
                )
            else:
                guidance_title = 'Ready for low-disk FITS collection'
                guidance_sentences.append(
                    'Exclude Only leaves purple frames unchanged, and Bad + '
                    'following RAW FITS saves each detected purple frame '
                    'unchanged and also saves the immediately following frame. '
                    'Once all evidence requirements above are met, this '
                    'provides calibration data with minimal disk use; ordinary '
                    'FITS can remain off.'
                )
        elif periodic_fits and fits_period == 0:
            guidance_level = 'success'
            guidance_title = 'Ready to collect complete FITS sequences'
            guidance_sentences.append(
                'Exclude Only leaves purple frames unchanged, and ordinary '
                'FITS saving set to Every Image saves complete sequences for '
                'automatic discovery. These good/bad/good groups provide '
                'strong evidence but use more disk space.'
            )
        elif periodic_fits and not fits_period_valid:
            guidance_title = 'No reliable calibration FITS will be saved'
            guidance_sentences.append(
                'Exclude Only marks purple frames without changing them, but '
                'the ordinary FITS interval is invalid. Turn on Bad + following '
                'RAW FITS for low disk use, or correct the interval and choose '
                'Every Image for complete sequences.'
            )
        elif periodic_fits:
            guidance_title = 'Periodic FITS saving may miss purple frames'
            guidance_sentences.append(
                'Exclude Only marks purple frames without changing them, but a '
                'periodic interval may not save a FITS at the right time. Turn '
                'on Bad + following RAW FITS for low disk use, or set ordinary '
                'FITS to Every Image for complete sequences.'
            )
        else:
            guidance_title = 'No calibration FITS will be saved'
            guidance_sentences.append(
                'Exclude Only marks purple frames without changing them, but '
                'no FITS saving is enabled. Turn on Bad + following RAW FITS '
                'for low disk use, or set ordinary FITS to Every Image for '
                'complete sequences.'
            )
    else:
        if diagnostic_fits:
            guidance_level = 'success'
            if periodic_fits and fits_period == 0:
                guidance_title = 'Ready to collect complete FITS sequences'
                guidance_sentences.append(
                    'Repair is active, but Bad + following RAW FITS preserves '
                    'the original purple frame before repair and also saves '
                    'the immediately following frame. Ordinary FITS saving set '
                    'to Every Image can add normal references on either side. '
                    'Incompatible following frames and repaired purple-frame '
                    'copies are not used. This uses more disk space.'
                )
            elif periodic_fits and not fits_period_valid:
                guidance_level = 'warning'
                guidance_title = 'Ordinary FITS setting needs correction'
                guidance_sentences.append(
                    'Repair is active, and Bad + following RAW FITS provides '
                    'the pre-repair calibration source. The ordinary FITS '
                    'interval is invalid; correct it or turn ordinary FITS '
                    'saving off.'
                )
            elif periodic_fits:
                guidance_title = 'Ready for low-disk FITS collection'
                guidance_sentences.append(
                    'Repair is active, but Bad + following RAW FITS preserves '
                    'the original purple frame before repair and also saves '
                    'the immediately following frame. The tool uses only '
                    'compatible normal references. Periodic ordinary FITS may '
                    'add another compatible reference but is not required.'
                )
            else:
                guidance_title = 'Ready for low-disk FITS collection'
                guidance_sentences.append(
                    'Repair is active, and Bad + following RAW FITS preserves '
                    'the original purple frame before repair and also saves '
                    'the immediately following frame. Once all evidence '
                    'requirements above are met, this provides calibration '
                    'data with minimal disk use; ordinary FITS can remain off.'
                )
        else:
            guidance_title = 'No untouched purple-frame FITS will be saved'
            if periodic_fits and fits_period == 0:
                guidance_sentences.append(
                    'Repair is active, and ordinary FITS saving set to Every '
                    'Image writes files after repair, so it cannot be relied '
                    'on to preserve the original purple frame. Either turn on '
                    'Bad + following RAW FITS, or switch to Exclude Only and '
                    'keep ordinary FITS set to Every Image to collect '
                    'calibration data.'
                )
            elif periodic_fits and not fits_period_valid:
                guidance_sentences.append(
                    'Repair is active, Bad + following RAW FITS is off, and the '
                    'ordinary FITS interval is invalid. Either turn on Bad + '
                    'following RAW FITS, or switch to Exclude Only and set '
                    'ordinary FITS to Every Image to collect calibration '
                    'data.'
                )
            elif periodic_fits:
                guidance_sentences.append(
                    'Repair is active, and periodic ordinary FITS is written '
                    'after repair and may also miss the relevant frames. Either '
                    'turn on Bad + following RAW FITS, or switch to Exclude '
                    'Only and set ordinary FITS to Every Image to collect '
                    'calibration data.'
                )
            else:
                guidance_sentences.append(
                    'Repair is active, but no FITS saving is enabled. Either '
                    'turn on Bad + following RAW FITS, or switch to Exclude '
                    'Only and set ordinary FITS to Every Image to collect '
                    'calibration data.'
                )

    if not retention_valid:
        guidance_level = 'warning'
        if guidance_title.startswith('Ready'):
            guidance_title = (
                'FITS can be saved, but automatic search is unavailable'
            )
        guidance_sentences.append(
            'Set FITS retention to at least 1 day before using Find saved '
            'FITS; manual upload remains available.'
        )

    guidance = {
        'level': guidance_level,
        'title': guidance_title,
        'text': ' '.join(guidance_sentences),
    }

    return {
        'facts': facts,
        'guidance': guidance,
        'repair_enabled': repair_enabled,
        'exclude_only': exclude_only,
        'diagnostic_fits': diagnostic_fits,
        'periodic_fits': periodic_fits,
        'fits_period': fits_period,
    }


class CalibrationSessionError(RuntimeError):
    """Base class for a malformed, inaccessible, or invalid web session."""


class CalibrationUploadError(CalibrationSessionError):
    """Raised when an uploaded file is unsafe or outside the accepted limits."""


def _utc_now_text():
    return datetime.now(timezone.utc).isoformat()


def get_storage_root(storage_root=None):
    """Return and create the private cross-process calibration directory."""
    if storage_root is None:
        from flask import current_app

        configured = current_app.config.get('ASI676MC_CALIBRATION_FOLDER')
        if configured:
            storage_root = Path(configured)
        else:
            storage_root = Path(current_app.instance_path).joinpath(
                'asi676mc_calibration'
            )

    root = Path(storage_root).resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        # Some mounted/container filesystems do not implement POSIX modes.
        pass
    return root


def _session_dir(session_id, storage_root=None):
    """Resolve a generated session ID without accepting path components."""
    if not SESSION_ID_RE.fullmatch(str(session_id or '')):
        raise CalibrationSessionError('invalid calibration session')

    root = get_storage_root(storage_root)
    session_dir = root.joinpath(session_id).resolve()
    if session_dir.parent != root:
        raise CalibrationSessionError('invalid calibration session path')
    return session_dir


def _manifest_path(session_dir):
    return session_dir.joinpath('manifest.json')


def _cancel_marker_path(session_dir):
    """Return the tombstone checked by concurrent upload requests."""
    return session_dir.joinpath('.upload-cancelled')


def _atomic_write_json(path, data):
    """Publish JSON atomically so browser polling never sees half a file."""
    path = Path(path)
    with tempfile.NamedTemporaryFile(
        mode='w',
        encoding='utf-8',
        dir=path.parent,
        prefix='.manifest-',
        suffix='.tmp',
        delete=False,
    ) as temporary_file:
        json.dump(data, temporary_file, indent=2, sort_keys=True)
        temporary_name = temporary_file.name

    os.replace(temporary_name, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _read_manifest(session_dir):
    try:
        return json.loads(_manifest_path(session_dir).read_text(encoding='utf-8'))
    except FileNotFoundError as error:
        raise CalibrationSessionError('calibration session not found') from error
    except (OSError, json.JSONDecodeError) as error:
        raise CalibrationSessionError('calibration session is unreadable') from error


def _write_manifest(session_dir, manifest):
    # A cancel request may be handled by a different gunicorn worker while an
    # upload request is still unwinding.  Never let that older request publish
    # its stale ``uploading`` manifest over the cancellation result.
    if (
        _cancel_marker_path(session_dir).exists()
        and manifest.get('status') != 'cancelled'
    ):
        raise CalibrationSessionError('this calibration upload was cancelled')
    manifest['updated_utc'] = _utc_now_text()
    _atomic_write_json(_manifest_path(session_dir), manifest)


def _remove_upload_dir(session_dir):
    """Delete uploaded source FITS while retaining small session results."""
    upload_dir = session_dir.joinpath('uploads')
    if upload_dir.exists():
        shutil.rmtree(upload_dir)


def cleanup_expired_sessions(storage_root=None, now=None):
    """Remove abandoned sessions; return the number removed.

    The function only examines directories whose names match IDs generated by
    this module, and it never follows a computed path outside the storage root.
    Atomic manifest replacements refresh the session-directory modification
    time after each completed upload, so the age represents the last durable
    activity rather than the time the first FITS started transferring.  This
    same function is called both when a new session starts and from the regular
    video-worker asset expiration task.
    """
    root = get_storage_root(storage_root)
    cutoff = (time.time() if now is None else float(now)) - (
        SESSION_RETENTION_SECONDS
    )
    removed = 0
    for candidate in root.iterdir():
        if (
            candidate.is_symlink()
            or not candidate.is_dir()
            or not SESSION_ID_RE.fullmatch(candidate.name)
        ):
            continue
        try:
            modified = candidate.stat().st_mtime
        except OSError:
            continue
        if modified >= cutoff:
            continue
        shutil.rmtree(candidate)
        removed += 1
    return removed


def create_session(owner, storage_root=None):
    """Create an upload session owned by one authenticated username."""
    owner = str(owner or '').strip()
    if not owner:
        raise CalibrationSessionError('an authenticated owner is required')

    root = get_storage_root(storage_root)
    cleanup_expired_sessions(root)
    session_id = uuid.uuid4().hex
    session_dir = _session_dir(session_id, root)
    upload_dir = session_dir.joinpath('uploads')
    upload_dir.mkdir(mode=0o700, parents=True)

    manifest = {
        'version': 1,
        'session_id': session_id,
        'owner': owner,
        'status': 'uploading',
        'created_utc': _utc_now_text(),
        'updated_utc': _utc_now_text(),
        'files': [],
        'total_bytes': 0,
        'task_id': None,
        'error': None,
    }
    _write_manifest(session_dir, manifest)
    return manifest


def get_session(session_id, owner=None, storage_root=None):
    """Load a session and optionally enforce its authenticated owner."""
    session_dir = _session_dir(session_id, storage_root)
    manifest = _read_manifest(session_dir)
    if owner is not None and manifest.get('owner') != str(owner):
        # Deliberately do not disclose whether another user's session exists.
        raise CalibrationSessionError('calibration session not found')
    return session_dir, manifest


def _unique_upload_name(upload_dir, original_name):
    # Keep this module usable in numerical/unit-test environments that do not
    # install the Flask web stack.  The conservative basename sanitizer has the
    # same security purpose as Werkzeug's secure_filename: remove path pieces,
    # normalize to ASCII, and admit only a small portable character set.
    original_text = str(original_name).replace('\\', '/').split('/')[-1]
    ascii_name = unicodedata.normalize('NFKD', original_text)\
        .encode('ascii', 'ignore')\
        .decode('ascii')
    safe_name = re.sub(r'[^A-Za-z0-9_.-]+', '_', ascii_name).strip('._')
    if not safe_name:
        raise CalibrationUploadError('the uploaded file has no usable filename')

    suffix = Path(safe_name).suffix.lower()
    if suffix not in FITS_SUFFIXES:
        raise CalibrationUploadError(
            'only uncompressed .fit, .fits, and .fts files are accepted'
        )

    candidate = upload_dir.joinpath(safe_name)
    counter = 2
    while candidate.exists():
        candidate = upload_dir.joinpath(
            '{0}_{1}{2}'.format(Path(safe_name).stem, counter, suffix)
        )
        counter += 1
    return candidate


def is_database_fits_path(path):
    """Return whether a database asset is a FITS format Astropy can open."""
    name = Path(path).name.lower()
    return name.endswith((
        '.fit',
        '.fits',
        '.fts',
        '.fit.gz',
        '.fits.gz',
        '.fts.gz',
    ))


def _database_record_has_role(record, role_name):
    """Inspect normalized diagnostic roles without trusting missing metadata."""
    return any(
        role.get('role') == role_name
        for role in record.get('roles', ())
        if isinstance(role, dict)
    )


def _database_compatibility_key(record):
    """Mirror the engine's inexpensive database-visible pairing fields."""
    return (
        record.get('width'),
        record.get('height'),
        round(float(record.get('exposure', -1.0)), 12),
        round(float(record.get('gain', -1.0)), 6),
        int(record.get('binmode', 1)),
    )


def select_database_evidence(
    fits_records,
    bad_frames,
    max_bad_frames,
    max_pair_seconds,
):
    """Select newest-first bad/reference groups from normalized DB records.

    Explicit diagnostic roles are preferred because their bad FITS is known to
    be untouched input. Ordinary FITS are associated with an image row marked
    bad when their capture times agree within one second. At most one normal
    reference on each side is retained; the calibration engine subsequently
    reopens every selected FITS and verifies its true signature and complete
    compatibility before using it.
    """
    max_bad_frames = int(max_bad_frames)
    if (
        max_bad_frames < DATABASE_BAD_FRAME_MIN
        or max_bad_frames > DATABASE_BAD_FRAME_MAX
    ):
        raise CalibrationSessionError(
            'database purple-frame limit must be between {0} and {1}'.format(
                DATABASE_BAD_FRAME_MIN,
                DATABASE_BAD_FRAME_MAX,
            )
        )
    max_pair_seconds = float(max_pair_seconds)
    if (
        not math.isfinite(max_pair_seconds)
        or max_pair_seconds <= 0
        or max_pair_seconds > 3600
    ):
        raise CalibrationSessionError(
            'maximum pair separation must be greater than 0 and no more than '
            '3600 seconds'
        )

    records = sorted(
        (dict(record) for record in fits_records),
        key=lambda record: float(record['timestamp']),
    )
    records_by_id = {record['id']: record for record in records}

    # Diagnostic FITS can carry more than one role when consecutive failures
    # occur. A record with any ``bad`` role is never eligible as a reference.
    diagnostic_candidates = []
    diagnostic_capture_ids = set()
    for record in records:
        for role in record.get('roles', ()):
            if not isinstance(role, dict) or role.get('role') != 'bad':
                continue
            capture_id = str(role.get('capture_id') or '')
            if not capture_id or capture_id in diagnostic_capture_ids:
                continue
            diagnostic_capture_ids.add(capture_id)
            diagnostic_candidates.append(record)

    candidates = list(diagnostic_candidates)
    known_bad_ids = {
        record['id']
        for record in records
        if _database_record_has_role(record, 'bad')
    }
    # Ordinary saving can create a second DB row at the same capture time as an
    # explicit diagnostic bad FITS. Even if the corresponding JPEG/image row
    # has already expired, that duplicate must not become another group's
    # supposedly normal reference.
    for diagnostic_bad in diagnostic_candidates:
        diagnostic_time = float(diagnostic_bad['timestamp'])
        diagnostic_key = _database_compatibility_key(diagnostic_bad)
        known_bad_ids.update(
            record['id']
            for record in records
            if not record.get('roles')
            and _database_compatibility_key(record) == diagnostic_key
            and abs(float(record['timestamp']) - diagnostic_time)
            <= DATABASE_CAPTURE_TIME_TOLERANCE
        )

    # Associate ordinary saved FITS with bad image rows. If an explicit
    # diagnostic bad capture exists at that time, keep it and do not add the
    # post-repair ordinary FITS as a second candidate.
    diagnostic_times = [
        float(record['timestamp'])
        for record in diagnostic_candidates
    ]
    for bad_frame in sorted(
        (dict(frame) for frame in bad_frames),
        key=lambda frame: float(frame['timestamp']),
        reverse=True,
    ):
        bad_time = float(bad_frame['timestamp'])
        ordinary_matches = [
            record for record in records
            if not record.get('roles')
            and abs(float(record['timestamp']) - bad_time)
            <= DATABASE_CAPTURE_TIME_TOLERANCE
            and round(float(record.get('exposure', -1.0)), 12)
            == round(float(bad_frame.get('exposure', -1.0)), 12)
            and round(float(record.get('gain', -1.0)), 6)
            == round(float(bad_frame.get('gain', -1.0)), 6)
        ]
        known_bad_ids.update(record['id'] for record in ordinary_matches)
        # Ordinary FITS written for an actually repaired frame contains the
        # corrected mosaic, not calibration evidence. The caller marks only
        # historical Exclude Only captures as safe ordinary bad candidates;
        # every known-bad timestamp is still excluded from normal references.
        if not bad_frame.get('allow_ordinary', True):
            continue
        if any(
            abs(diagnostic_time - bad_time)
            <= DATABASE_CAPTURE_TIME_TOLERANCE
            for diagnostic_time in diagnostic_times
        ):
            continue
        if ordinary_matches:
            candidates.append(min(
                ordinary_matches,
                key=lambda record: abs(float(record['timestamp']) - bad_time),
            ))

    groups = []
    selected_ids = set()
    reference_ids = set()
    seen_bad_ids = set()
    for bad_record in sorted(
        candidates,
        key=lambda record: float(record['timestamp']),
        reverse=True,
    ):
        if bad_record['id'] in seen_bad_ids:
            continue
        seen_bad_ids.add(bad_record['id'])
        bad_time = float(bad_record['timestamp'])
        compatibility_key = _database_compatibility_key(bad_record)
        normal_candidates = [
            record for record in records
            if record['id'] not in known_bad_ids
            and not _database_record_has_role(record, 'bad')
            and _database_compatibility_key(record) == compatibility_key
            and 0 < abs(float(record['timestamp']) - bad_time)
            <= max_pair_seconds
        ]
        before = [
            record for record in normal_candidates
            if float(record['timestamp']) < bad_time
        ]
        after = [
            record for record in normal_candidates
            if float(record['timestamp']) > bad_time
        ]
        references = []
        if before:
            references.append(max(
                before,
                key=lambda record: float(record['timestamp']),
            ))
        if after:
            references.append(min(
                after,
                key=lambda record: float(record['timestamp']),
            ))
        if not references:
            continue

        groups.append({
            'bad': bad_record,
            'references': references,
        })
        selected_ids.add(bad_record['id'])
        selected_ids.update(record['id'] for record in references)
        reference_ids.update(record['id'] for record in references)
        if len(groups) >= max_bad_frames:
            break

    selected_records = [
        records_by_id[record_id]
        for record_id in selected_ids
    ]
    selected_records.sort(key=lambda record: float(record['timestamp']))
    return selected_records, {
        'requested_bad_count': max_bad_frames,
        'candidate_bad_count': len(seen_bad_ids),
        'selected_bad_count': len(groups),
        'selected_normal_count': len(reference_ids),
        'selected_file_count': len(selected_records),
        'two_sided_count': sum(
            1 for group in groups if len(group['references']) == 2
        ),
    }


def stage_database_files(session_id, owner, records, storage_root=None):
    """Link selected local DB assets into a private calibration session.

    Hard links keep a selected FITS alive if its database row expires while the
    job is queued without duplicating large files. On a separate filesystem a
    symbolic link provides the same zero-copy workspace; only the private link
    is removed when calibration finishes, never the database-owned source.
    """
    session_dir, manifest = get_session(session_id, owner, storage_root)
    if manifest.get('status') != 'uploading':
        raise CalibrationSessionError('this calibration session is not staging')
    records = list(records)
    if len(records) > MAX_DATABASE_FILE_COUNT:
        raise CalibrationSessionError(
            'database calibration may stage at most {0} FITS files'.format(
                MAX_DATABASE_FILE_COUNT
            )
        )

    upload_dir = session_dir.joinpath('uploads')
    for record in records:
        source = Path(record['path']).resolve()
        if not source.is_file():
            raise CalibrationSessionError(
                'a selected database FITS is no longer available: {0}'.format(
                    source.name
                )
            )
        if not is_database_fits_path(source):
            raise CalibrationSessionError(
                'unsupported database FITS format: {0}'.format(source.name)
            )
        destination = upload_dir.joinpath(
            '{0}_{1}'.format(record['id'], source.name)
        )
        try:
            os.link(str(source), str(destination))
            link_type = 'hardlink'
        except OSError:
            destination.symlink_to(source)
            link_type = 'symlink'

        file_size = source.stat().st_size
        manifest['files'].append({
            'name': destination.name,
            'original_name': source.name,
            'size': file_size,
            'database_id': int(record['id']),
            'link_type': link_type,
        })
        manifest['total_bytes'] += file_size

    _write_manifest(session_dir, manifest)
    return manifest


def store_upload(session_id, owner, file_storage, storage_root=None):
    """Stream one browser-selected FITS into its private session.

    The browser calls this once per selected file, automatically.  Sequential
    transfer avoids holding an entire 14-30 file collection in one request and
    allows the page to report reliable file-level progress.
    """
    session_dir, manifest = get_session(session_id, owner, storage_root)
    if manifest.get('status') != 'uploading':
        raise CalibrationUploadError('this calibration session is no longer uploading')
    if _cancel_marker_path(session_dir).exists():
        raise CalibrationUploadError('this calibration upload was cancelled')
    if len(manifest['files']) >= MAX_FILE_COUNT:
        raise CalibrationUploadError(
            f'a calibration session may contain at most {MAX_FILE_COUNT} files'
        )
    if file_storage is None or not getattr(file_storage, 'filename', ''):
        raise CalibrationUploadError('no FITS file was supplied')

    upload_dir = session_dir.joinpath('uploads')
    destination = _unique_upload_name(upload_dir, file_storage.filename)
    partial = destination.with_name(destination.name + '.part')
    written = 0
    first_card = b''

    try:
        with partial.open('wb') as output_file:
            while True:
                if _cancel_marker_path(session_dir).exists():
                    raise CalibrationUploadError(
                        'this calibration upload was cancelled'
                    )
                chunk = file_storage.stream.read(1024 * 1024)
                if not chunk:
                    break
                if not first_card:
                    first_card = chunk[:80]
                written += len(chunk)
                if written > MAX_FILE_BYTES:
                    raise CalibrationUploadError(
                        f'{file_storage.filename} exceeds the per-file size limit'
                    )
                if manifest['total_bytes'] + written > MAX_SESSION_BYTES:
                    raise CalibrationUploadError(
                        'the selected files exceed the calibration-session size limit'
                    )
                output_file.write(chunk)

        # Every standard uncompressed FITS primary HDU begins with a SIMPLE
        # card.  Astropy performs the complete structural validation later.
        if not first_card.startswith(b'SIMPLE  ='):
            raise CalibrationUploadError(
                f'{file_storage.filename} does not appear to be a FITS file'
            )
        if written == 0:
            raise CalibrationUploadError(f'{file_storage.filename} is empty')
        if _cancel_marker_path(session_dir).exists():
            raise CalibrationUploadError('this calibration upload was cancelled')

        os.replace(partial, destination)
        try:
            destination.chmod(0o600)
        except OSError:
            pass
    except Exception:
        try:
            partial.unlink()
        except FileNotFoundError:
            pass
        raise

    entry = {
        'name': destination.name,
        'original_name': str(file_storage.filename),
        'size': written,
    }
    manifest['files'].append(entry)
    manifest['total_bytes'] += written
    _write_manifest(session_dir, manifest)
    return entry, manifest


def cancel_upload_session(session_id, owner, storage_root=None):
    """Cancel an unqueued upload and immediately remove its source FITS.

    The marker is written before deletion so an upload still executing in a
    second web worker cannot restore a stale manifest after cancellation.
    Repeating a completed cancellation is harmless, which lets the browser
    retry safely after losing the first response. Queued or running numerical
    jobs are intentionally not interruptible.
    """
    session_dir, manifest = get_session(session_id, owner, storage_root)
    if manifest.get('status') == 'cancelled':
        return manifest
    if manifest.get('status') != 'uploading':
        raise CalibrationSessionError(
            'only an upload that has not been queued can be cancelled'
        )

    marker_path = _cancel_marker_path(session_dir)
    marker_path.write_text(_utc_now_text(), encoding='ascii')
    try:
        marker_path.chmod(0o600)
    except OSError:
        pass

    manifest['status'] = 'cancelled'
    manifest['completed_utc'] = _utc_now_text()
    manifest['error'] = None
    _remove_upload_dir(session_dir)
    manifest['sources_deleted_utc'] = _utc_now_text()
    _write_manifest(session_dir, manifest)
    return manifest


def discard_session(session_id, owner, storage_root=None):
    """Delete a finished/cancelled owned session and its retained results."""
    session_dir, manifest = get_session(session_id, owner, storage_root)
    if manifest.get('status') in ('uploading', 'queued', 'running'):
        raise CalibrationSessionError(
            'an active calibration session cannot be discarded'
        )
    shutil.rmtree(session_dir)


def mark_queued(
    session_id,
    owner,
    task_id,
    max_pair_seconds,
    settings,
    config_id=None,
    source_details=None,
    storage_root=None,
):
    """Freeze the upload set and record the background job parameters."""
    session_dir, manifest = get_session(session_id, owner, storage_root)
    if manifest.get('status') != 'uploading':
        raise CalibrationSessionError('this calibration session has already started')
    if len(manifest.get('files', [])) < 14:
        raise CalibrationSessionError(
            'select at least 14 FITS files: seven purple frames and at least '
            'seven distinct normal references'
        )

    max_pair_seconds = float(max_pair_seconds)
    if (
        not math.isfinite(max_pair_seconds)
        or max_pair_seconds <= 0
        or max_pair_seconds > 3600
    ):
        raise CalibrationSessionError(
            'maximum pair separation must be greater than 0 and no more than '
            '3600 seconds'
        )

    manifest['status'] = 'queued'
    manifest['task_id'] = int(task_id)
    manifest['max_pair_seconds'] = max_pair_seconds
    manifest['settings'] = dict(settings)
    manifest['config_id'] = int(config_id) if config_id is not None else None
    manifest['source'] = dict(source_details or {
        'kind': 'upload',
        'selected_file_count': len(manifest.get('files', [])),
    })
    manifest['error'] = None
    _write_manifest(session_dir, manifest)
    return manifest


def mark_failed(session_id, owner, message, storage_root=None):
    """Record a pre-worker failure such as a database queueing error."""
    session_dir, manifest = get_session(session_id, owner, storage_root)
    _remove_upload_dir(session_dir)
    manifest['status'] = 'failed'
    manifest['completed_utc'] = _utc_now_text()
    manifest['sources_deleted_utc'] = _utc_now_text()
    manifest['error'] = str(message)
    _write_manifest(session_dir, manifest)
    return manifest


def _result_summary(payload):
    settings = payload['IMAGE_ASI676MC_REPAIR']
    quality = payload['quality']
    values = [
        {
            'key': key,
            'label': DERIVED_VALUE_LABELS[key],
            'value': settings[key],
        }
        for key in DERIVED_VALUE_KEYS
    ]

    quality_summary = {
        'matched_bad_count': quality['pair_count'],
        'unmatched_bad_count': quality.get('unmatched_bad_count', 0),
        'matched_normal_count': quality['unique_good_count'],
        'normal_bad_ratio': quality['good_bad_ratio'],
        'two_sided_count': quality['two_sided_count'],
        'exposure_level_count': len(quality['exposure_levels']),
        'validated_bad_count': quality.get('validated_bad_repairs', 0),
        'validated_normal_count': quality.get('validated_normal_frames', 0),
        'rejected_file_count': quality['rejected_file_count'],
        'highlight_sample_count': quality['highlight_sample_count'],
    }

    return {
        'values': values,
        'quality': quality_summary,
        'warnings': _result_warnings(quality_summary),
    }


def _readable_join(parts):
    """Join short UI phrases with natural punctuation."""
    parts = list(parts)
    if len(parts) < 2:
        return ''.join(parts)
    if len(parts) == 2:
        return '{0} and {1}'.format(parts[0], parts[1])
    return '{0}, and {1}'.format(', '.join(parts[:-1]), parts[-1])


def _result_warnings(quality, source_details=None, report_context=False):
    """Build non-overlapping result notes for the page or downloaded report.

    Both surfaces interpret the evidence identically.  Only the final pointer
    for rejected-file details differs: the page points to the download, while
    the download points to its own detail section.
    """
    warnings = []
    source_details = source_details or {}

    if (
        source_details.get('kind') == 'database'
        and source_details.get('selected_bad_count', 0)
        < source_details.get('requested_bad_count', 0)
    ):
        warnings.append(
            'The saved FITS search looked for up to {1} purple frames and '
            'found {0} usable groups before reaching the oldest retained '
            'data. Calibration continued because the minimum of seven was '
            'met.'.format(
                source_details['selected_bad_count'],
                source_details['requested_bad_count'],
            )
        )

    matched_count = int(quality.get('matched_bad_count', 0))
    two_sided_count = int(quality.get('two_sided_count', 0))
    normal_count = int(quality.get('matched_normal_count', 0))
    if matched_count:
        one_sided_count = matched_count - two_sided_count
        # Each one-sided group uses one reference and each two-sided group uses
        # two. Fewer distinct files than that total means at least one normal
        # reference was reused; comparing only against the purple-frame count
        # would miss reuse in otherwise complete groups.
        reference_use_count = matched_count + two_sided_count
        references_reused = normal_count < reference_use_count
        coverage_parts = []
        if one_sided_count == matched_count:
            coverage_parts.append(
                'all {0} purple frames used one adjacent normal reference'
                .format(matched_count)
            )
        elif one_sided_count:
            remaining_text = (
                'the remaining purple frame'
                if one_sided_count == 1
                else 'the other {0} purple frames'.format(one_sided_count)
            )
            coverage_parts.append(
                '{0} of {1} purple frames had normal references on both '
                'sides; {2} used one adjacent normal reference'
                .format(two_sided_count, matched_count, remaining_text)
            )
        if references_reused:
            coverage_parts.append(
                'some normal references were reused for more than one group'
            )
        if coverage_parts:
            if one_sided_count and references_reused:
                improvement = (
                    'more complete, independent good/bad/good groups would '
                    'improve confidence'
                )
            elif one_sided_count:
                improvement = (
                    'more complete good/bad/good groups would improve confidence'
                )
            else:
                improvement = (
                    'more independent normal references would improve confidence'
                )
            coverage_text = '. '.join(
                part[:1].upper() + part[1:]
                for part in coverage_parts
            )
            warnings.append(
                '{0}. Calibration is valid, but {1}.'.format(
                    coverage_text,
                    improvement,
                )
            )

    skipped_parts = []
    unmatched_count = int(quality.get('unmatched_bad_count', 0))
    if unmatched_count:
        skipped_parts.append(
            '{0} without a compatible nearby normal FITS'.format(
                _counted_item(unmatched_count, 'purple frame')
            )
        )
    rejected_count = int(quality.get('rejected_file_count', 0))
    if rejected_count:
        skipped_parts.append(
            '{0} that could not be read or used'.format(
                _counted_item(rejected_count, 'FITS file')
            )
        )
    missing_count = int(source_details.get('missing_local_count', 0))
    if missing_count:
        skipped_parts.append(
            '{0} whose {1} no longer on disk'.format(
                _counted_item(
                    missing_count,
                    'saved FITS entry',
                    'saved FITS entries',
                ),
                'file was' if missing_count == 1 else 'files were',
            )
        )
    unsupported_count = int(source_details.get('unsupported_count', 0))
    if unsupported_count:
        skipped_parts.append(
            '{0} with {1}'.format(
                _counted_item(unsupported_count, 'saved FITS file'),
                'an unsupported filename'
                if unsupported_count == 1
                else 'unsupported filenames',
            )
        )
    if skipped_parts:
        warning = (
            'The tool skipped {0}. The remaining FITS still met the '
            'calibration requirements.'.format(_readable_join(skipped_parts))
        )
        if rejected_count:
            if report_context:
                warning += (
                    ' Rejected-file details are listed later in this report.'
                )
            else:
                warning += (
                    ' Download the text report for rejected-file details.'
                )
        warnings.append(warning)

    return warnings


def _friendly_failure_message(message):
    """Translate calibration-engine failures into safe, actionable UI copy."""
    message_text = str(message or '')
    lowered = message_text.lower()
    matched_count = re.search(r'(\d+) matched bad frames found', lowered)
    if 'no compatible raw16 rggb fits files found' in lowered:
        return (
            'No compatible unprocessed ASI676MC RAW16 RGGB FITS were found. '
            'Choose a collection containing the original camera FITS.'
        )
    if matched_count:
        return (
            'Only {0} purple frames had a compatible nearby normal FITS; at '
            'least seven are required.'.format(matched_count.group(1))
        )
    if 'both normal and bad frames are required' in lowered:
        return (
            'The collection did not contain both recognisable purple frames '
            'and normal frames. Check the selected FITS and try again.'
        )
    if 'matched normal/bad ratio' in lowered:
        return (
            'There were not enough different normal reference frames. Provide '
            'at least one distinct compatible normal frame for each purple frame.'
        )
    if 'cover only one exposure' in lowered:
        return (
            'The matched purple frames use only one exposure. Include data from '
            'at least two exposure settings.'
        )
    if (
        'more than one explicit camera identity' in lowered
        or 'different explicit asi camera' in lowered
    ):
        return (
            'Files from more than one camera were detected. Use FITS from this '
            'ASI676MC only.'
        )
    if (
        'misclassifies at least one supplied normal frame' in lowered
        or 'misses at least one supplied bad frame' in lowered
        or 'overlapping normal and bad ranges' in lowered
    ):
        return (
            'The normal and purple frames could not be separated reliably. '
            'Check that the collection contains genuine purple frames with '
            'nearby normal frames, then review the detection thresholds in '
            'Image Settings.'
        )
    if (
        'no source green plateau' in lowered
        or 'stable jointly-clipped highlight samples' in lowered
        or 'no valid highlight blend candidates' in lowered
    ):
        return (
            'The collection does not contain enough stable bright daylight '
            'highlights. Add brighter daylight pairs or good/bad/good groups.'
        )
    if 'has usable samples in only' in lowered:
        return (
            'Too few stable pixels could be compared across the matched '
            'frames. Try clearer daylight data with less cloud or scene change.'
        )
    if (
        'calibrated repair validation failed' in lowered
        or 'calibrated detector rejects normal frame' in lowered
        or 'normal-frame validation mutated' in lowered
        or 'repair validation failed' in lowered
    ):
        return (
            'The derived values did not pass the final safety checks, so no '
            'result was produced. Try a larger, cleaner, more varied collection.'
        )
    if 'queue' in lowered and 'calibration' in lowered:
        return (
            'Calibration could not be started because the background worker is '
            'unavailable. Check that indi-allsky is running and try again.'
        )
    if 'session' in lowered and (
        'not found' in lowered
        or 'not queued' in lowered
        or 'no longer' in lowered
    ):
        return (
            'The previous calibration expired or is no longer available. Start '
            'a new calibration.'
        )
    return (
        'An unexpected error occurred while checking the FITS. Try again or '
        'use a different FITS collection; if the problem repeats, check the '
        'indi-allsky log.'
    )


REPORT_LINE_WIDTH = 88


def _append_report_section(lines, title):
    """Start a readable plain-text section with consistent spacing."""
    if lines and lines[-1] != '':
        lines.append('')
    lines.extend((title, '-' * len(title)))


def _append_report_paragraph(lines, text, prefix=''):
    """Wrap prose while keeping list markers readable in a text download."""
    subsequent = ' ' * len(prefix)
    lines.extend(textwrap.wrap(
        str(text),
        width=REPORT_LINE_WIDTH,
        initial_indent=prefix,
        subsequent_indent=subsequent,
    ))


def _format_report_value(value):
    """Format configuration values without adding misleading precision."""
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    if isinstance(value, float):
        return '{0:.10g}'.format(value)
    return str(value)


def _format_report_timestamp(value):
    """Turn an ISO timestamp into an explicitly UTC, human-readable value."""
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).strftime(
            '%Y-%m-%d %H:%M:%S UTC'
        )
    except (TypeError, ValueError):
        return str(value or 'Unknown')


def _original_report_filename(staged_name, manifest_files):
    """Map a private staged basename back to its user-facing source name."""
    for file_entry in manifest_files or ():
        if file_entry.get('name') == staged_name:
            return str(file_entry.get('original_name') or staged_name)
    return str(staged_name or 'Unknown FITS file')


def compare_result_to_configuration(result, repair_config):
    """Classify whether a result would materially change current settings.

    ``exact`` means all seven stored values compare equal. ``equivalent`` uses
    the narrow per-field tolerances above. ``different`` means applying at
    least one result can have a meaningful effect. Invalid or incomplete data
    is reported as ``unavailable`` rather than hiding the Apply action.
    """
    try:
        from . import asi676mc

        configured = asi676mc.normalize_settings(repair_config or {})
        derived = {
            item['key']: item['value']
            for item in result.get('values', [])
            if item.get('key') in DERIVED_VALUE_KEYS
        }
        if set(derived) != set(DERIVED_VALUE_KEYS):
            raise ValueError('the calibration result is incomplete')

        exact = True
        equivalent = True
        differing_keys = []
        for key in DERIVED_VALUE_KEYS:
            configured_value = float(configured[key])
            derived_value = float(derived[key])
            if configured_value != derived_value:
                exact = False

            tolerance = CONFIGURATION_EQUIVALENCE_TOLERANCES[key]
            if not math.isclose(
                configured_value,
                derived_value,
                rel_tol=tolerance['rel_tol'],
                abs_tol=tolerance['abs_tol'],
            ):
                equivalent = False
                differing_keys.append(key)
    except (KeyError, TypeError, ValueError) as error:
        return {
            'status': 'unavailable',
            'message': (
                'The current repair values could not be loaded for comparison. '
                'Open Image Settings to review them before applying this result.'
            ),
            'configured_values': {},
            'differing_keys': [],
        }

    configured_values = {
        key: configured[key]
        for key in DERIVED_VALUE_KEYS
    }

    if exact:
        return {
            'status': 'exact',
            'message': (
                'The derived values already match the current configuration '
                'exactly. No update is needed.'
            ),
            'configured_values': configured_values,
            'differing_keys': [],
        }
    if equivalent:
        return {
            'status': 'equivalent',
            'message': (
                'Result effectively matches the current configuration. '
                'Applying it is unlikely to produce a visible change.'
            ),
            'configured_values': configured_values,
            'differing_keys': [],
        }
    return {
        'status': 'different',
        'message': '',
        'configured_values': configured_values,
        'differing_keys': differing_keys,
    }


def format_integrated_report(payload, manifest):
    """Build the report downloaded from the authenticated calibration page.

    The numerical engine also supports folder-based callers, but their source
    path and next steps are not meaningful in the web UI.  Building this report
    from structured payload and session data keeps the integrated workflow
    accurate: it can name the real evidence source, compare the saved result
    with the configuration snapshot, explain cleanup, and avoid exposing the
    private staging directory.
    """
    quality = payload['quality']
    derived_settings = payload['IMAGE_ASI676MC_REPAIR']
    result_summary = _result_summary(payload)
    source_details = manifest.get('source') or {}
    configured_at_start = manifest.get('settings') or {}
    comparison = compare_result_to_configuration(
        result_summary,
        configured_at_start,
    )

    lines = [
        'indi-allsky ASI676MC purple-frame calibration report',
        '=' * 54,
        'Status: Successful',
        'Generated: {0}'.format(_format_report_timestamp(
            payload.get('generated_utc') or manifest.get('completed_utc')
        )),
    ]

    _append_report_section(lines, 'Calibration result')
    _append_report_paragraph(
        lines,
        'The derived values passed the final safety checks. They repaired all '
        '{0} purple frames used for validation, while all {1} distinct normal '
        'reference frames remained unchanged.'.format(
            quality.get('validated_bad_repairs', 0),
            quality.get('validated_normal_frames', 0),
        ),
    )
    _append_report_paragraph(
        lines,
        'Running the calibration did not change the indi-allsky configuration. '
        'Only an administrator can apply the result from the calibration page.',
    )

    _append_report_section(lines, 'Recommended calibration values')
    _append_report_paragraph(
        lines,
        'Review these values under Tools > ASI676MC Calibration. An '
        'administrator can use Apply and reload, or the values can be entered '
        'manually under Configuration > Image > ASI676MC RAW16 Frame Repair.',
    )

    configured_values = comparison.get('configured_values', {})
    differing_keys = set(comparison.get('differing_keys', ()))
    table_rows = []
    for key in DERIVED_VALUE_KEYS:
        derived_value = derived_settings[key]
        if key not in configured_values:
            configured_text = 'Unavailable'
            assessment = 'Review manually'
        else:
            configured_value = configured_values[key]
            configured_text = _format_report_value(configured_value)
            if float(derived_value) == float(configured_value):
                assessment = 'Same'
            elif key in differing_keys:
                assessment = 'Meaningful change'
            else:
                assessment = 'Negligible difference'
        table_rows.append((
            DERIVED_VALUE_LABELS[key],
            _format_report_value(derived_value),
            configured_text,
            assessment,
        ))

    label_width = max(len('Setting'), *(len(row[0]) for row in table_rows))
    derived_width = max(len('Derived'), *(len(row[1]) for row in table_rows))
    configured_width = max(
        len('Configured when started'),
        *(len(row[2]) for row in table_rows)
    )
    table_format = '{{0:<{0}}}  {{1:>{1}}}  {{2:>{2}}}  {{3}}'.format(
        label_width,
        derived_width,
        configured_width,
    )
    lines.extend((
        '',
        table_format.format(
            'Setting',
            'Derived',
            'Configured when started',
            'Assessment',
        ),
        table_format.format(
            '-' * label_width,
            '-' * derived_width,
            '-' * configured_width,
            '-' * len('Assessment'),
        ),
    ))
    lines.extend(table_format.format(*row) for row in table_rows)

    comparison_text = {
        'exact': (
            'All seven values matched the configuration when calibration '
            'started. No update was needed at that time.'
        ),
        'equivalent': (
            'The result effectively matched the configuration when '
            'calibration started. Applying it was unlikely to produce a '
            'visible change.'
        ),
        'different': (
            'One or more values differed enough to make a meaningful change '
            'to repaired images.'
        ),
        'unavailable': (
            'The configuration snapshot could not be compared. Review the '
            'current values in Image Settings before applying this result.'
        ),
    }[comparison.get('status', 'unavailable')]
    lines.append('')
    _append_report_paragraph(lines, comparison_text)
    _append_report_paragraph(
        lines,
        'The result page compares against the live configuration, which may '
        'have changed since this calibration started.',
    )

    _append_report_section(lines, 'Evidence source')
    source_kind = source_details.get('kind')
    selected_file_count = source_details.get(
        'selected_file_count',
        len(manifest.get('files', ())),
    )
    if source_kind == 'database':
        lines.extend((
            'Method: Saved FITS search on the ASI676MC Calibration page',
            'Camera: {0}'.format(source_details.get('camera_name', 'Unknown')),
            'Search order: Newest retained FITS first',
            'Requested maximum: {0}'.format(_counted_item(
                source_details.get('requested_bad_count', 0),
                'purple-frame group',
            )),
            'Usable groups selected: {0}'.format(
                source_details.get('selected_bad_count', 0)
            ),
            'Distinct normal references selected: {0}'.format(
                source_details.get('selected_normal_count', 0)
            ),
            'Distinct FITS selected: {0}'.format(selected_file_count),
            'Saved FITS entries in retention window: {0}'.format(
                source_details.get('database_fits_count', 0)
            ),
            'FITS retention cutoff: {0} ({1})'.format(
                source_details.get('retention_cutoff', 'Unknown'),
                _counted_item(source_details.get('retention_days', 0), 'day')
                if isinstance(source_details.get('retention_days'), int)
                else 'Unknown retention',
            ),
            'Entries whose files were missing: {0}'.format(
                source_details.get('missing_local_count', 0)
            ),
            'Files with unsupported names: {0}'.format(
                source_details.get('unsupported_count', 0)
            ),
        ))
        _append_report_paragraph(
            lines,
            'Only the session\'s temporary staging links were removed after '
            'calibration. The original saved FITS were left unchanged and '
            'remain subject to the normal FITS retention setting.',
        )
    elif source_kind == 'upload':
        lines.extend((
            'Method: Manual FITS upload on the ASI676MC Calibration page',
            'FITS selected: {0}'.format(selected_file_count),
        ))
        _append_report_paragraph(
            lines,
            'The private uploaded copies were removed after calibration. The '
            'original files on the user\'s computer were never modified.',
        )
    else:
        lines.extend((
            'Method: ASI676MC Calibration page',
            'FITS selected: {0}'.format(selected_file_count),
        ))
        _append_report_paragraph(
            lines,
            'The private session inputs were removed after calibration.',
        )

    _append_report_section(lines, 'Evidence used')
    evidence_lines = (
        ('Purple frames with a normal reference', quality['pair_count']),
        ('Purple frames skipped without a reference',
         quality.get('unmatched_bad_count', 0)),
        ('Distinct normal references', quality['unique_good_count']),
        ('Normal-to-purple ratio',
         '{0:.2f}:1'.format(quality['good_bad_ratio'])),
        ('Good/purple/good groups', '{0} of {1}'.format(
            quality['two_sided_count'], quality['pair_count']
        )),
        ('Exposure settings represented', len(quality['exposure_levels'])),
        ('Purple-frame repair checks passed',
         quality.get('validated_bad_repairs', 0)),
        ('Normal-frame unchanged checks passed',
         quality.get('validated_normal_frames', 0)),
        ('FITS files unreadable or unusable',
         quality.get('rejected_file_count', 0)),
    )
    evidence_width = max(len(label) for label, _value in evidence_lines)
    lines.extend(
        '{0:<{1}}  {2}'.format(label + ':', evidence_width + 1, value)
        for label, value in evidence_lines
    )
    camera_names = quality.get('explicit_camera_names', ())
    lines.append('Camera identity in FITS headers: {0}'.format(
        ', '.join(camera_names)
        if camera_names
        else 'No explicit name (compatible legacy headers)'
    ))
    lines.append('Maximum matching separation: {0:g} seconds'.format(
        float(manifest.get('max_pair_seconds', 0))
    ))

    _append_report_section(lines, 'Result notes')
    report_notes = _result_warnings(
        result_summary['quality'],
        source_details,
        report_context=True,
    )
    if report_notes:
        for note in report_notes:
            _append_report_paragraph(lines, note, prefix='- ')
    else:
        lines.append('No additional warnings.')

    rejected_files = payload.get('rejected_files') or ()
    if rejected_files:
        _append_report_section(lines, 'Rejected FITS details')
        _append_report_paragraph(
            lines,
            'These files were not used. Their rejection did not prevent the '
            'remaining evidence from passing calibration.',
        )
        for rejected in rejected_files:
            original_name = _original_report_filename(
                rejected.get('name'),
                manifest.get('files'),
            )
            _append_report_paragraph(
                lines,
                '{0}: {1}'.format(
                    original_name,
                    rejected.get('reason') or 'Unreadable or unusable FITS',
                ),
                prefix='- ',
            )

    gain_estimates = payload.get('gain_estimates') or {}
    if gain_estimates:
        _append_report_section(lines, 'Gain fit details')
        _append_report_paragraph(
            lines,
            'MAD is the median absolute deviation between matched-frame '
            'estimates; smaller values indicate more consistent evidence.',
        )
        for key in ('GAIN_R', 'GAIN_G1', 'GAIN_G2', 'GAIN_B'):
            estimate = gain_estimates.get(key)
            if not estimate:
                continue
            lines.append(
                '{0}: {1:.5f}; pair MAD {2:.5f}; {3} samples'.format(
                    DERIVED_VALUE_LABELS[key],
                    estimate['value'],
                    estimate['mad'],
                    estimate['sample_count'],
                )
            )

    if 'highlight_score' in quality:
        _append_report_section(lines, 'Highlight blend fit details')
        lines.extend((
            'Selected start/end ratios: {0}/{1}'.format(
                _format_report_value(
                    derived_settings['HIGHLIGHT_BLEND_START_RATIO']
                ),
                _format_report_value(
                    derived_settings['HIGHLIGHT_BLEND_END_RATIO']
                ),
            ),
            'Stable clipped-highlight samples: {0} across {1} groups'.format(
                quality.get('highlight_sample_count', 0),
                quality.get('highlight_pair_count', 0),
            ),
            'Selected median chromaticity error: {0:.6f}'.format(
                quality['highlight_score']
            ),
            'Proven 0.55/0.75 error: {0:.6f}'.format(
                quality['highlight_default_score']
            ),
            'Unregularized grid best: {0:.2f}/{1:.2f} at {2:.6f}'.format(
                quality['highlight_raw_best_start_ratio'],
                quality['highlight_raw_best_end_ratio'],
                quality['highlight_raw_best_score'],
            ),
            'Proven defaults retained within tolerance: {0}'.format(
                'Yes' if quality['highlight_preferred_default'] else 'No'
            ),
            'Runner-up chromaticity error: {0:.6f}'.format(
                quality['highlight_runner_up_score']
            ),
            'Measured source-green plateau: {0}'.format(
                quality['source_saturation_plateau']
            ),
        ))

    signature_ranges = payload.get('signature_ranges') or {}
    if signature_ranges:
        _append_report_section(lines, 'Purple-frame signature separation')
        _append_report_paragraph(
            lines,
            'The normal and purple ranges below did not overlap and remained '
            'on the correct side of the configured detection thresholds.',
        )
        signature_labels = {
            'purple_ratio': 'Combined purple/green ratio',
            'red_side_ratio': 'Red-side ratio',
            'blue_side_ratio': 'Blue-side ratio',
        }
        for metric, values in signature_ranges.items():
            lines.append(
                '{0}: normal {1:.3f}-{2:.3f}; purple {3:.3f}-{4:.3f}'.format(
                    signature_labels.get(metric, metric),
                    values['good_min'],
                    values['good_max'],
                    values['bad_min'],
                    values['bad_max'],
                )
            )

    _append_report_section(lines, 'About this report')
    _append_report_paragraph(
        lines,
        'This is a human-readable record from Tools > ASI676MC Calibration, '
        'not a configuration file. It cannot be imported into indi-allsky.',
    )
    _append_report_paragraph(
        lines,
        'Only the seven calibration values above were derived. Repair mode, '
        'FITS saving, logging, gallery, and other feature switches remain '
        'operator choices and are never changed by calibration itself.',
    )
    return '\n'.join(lines).rstrip() + '\n'


def run_calibration_session(session_id, storage_root=None):
    """Run the calibration engine for one queued web session."""
    session_dir, manifest = get_session(session_id, storage_root=storage_root)
    if manifest.get('status') not in ('queued', 'running'):
        raise CalibrationSessionError('calibration session is not queued')

    manifest['status'] = 'running'
    manifest['started_utc'] = _utc_now_text()
    _write_manifest(session_dir, manifest)

    upload_dir = session_dir.joinpath('uploads')
    captured_output = io.StringIO()
    try:
        from misc import asi676mc_frame_repair as calibration_engine

        with redirect_stdout(captured_output):
            payload, _engine_report = calibration_engine.calibrate_folder(
                upload_dir,
                settings=manifest.get('settings'),
                recursive=False,
                max_pair_seconds=manifest['max_pair_seconds'],
                allow_unmatched=True,
            )

        summary = _result_summary(payload)
        result = {
            'format': 'indi-allsky-asi676mc-web-calibration-v1',
            'session_id': session_id,
            'completed_utc': _utc_now_text(),
            **summary,
        }
        source_details = manifest.get('source')
        if source_details:
            result['source'] = source_details
        result['warnings'] = _result_warnings(
            result['quality'],
            source_details,
        )
        # The engine's folder-oriented report contains implementation details
        # such as its input path.  The web download is built independently from
        # structured data so upload/search provenance, configuration comparison,
        # cleanup, and UI actions are all described accurately.
        report_text = format_integrated_report(payload, manifest)
        _atomic_write_json(session_dir.joinpath('result.json'), result)
        session_dir.joinpath('asi676mc_calibration_report.txt').write_text(
            report_text,
            encoding='utf-8',
        )
        session_dir.joinpath('calibration.log').write_text(
            captured_output.getvalue(),
            encoding='utf-8',
        )

        # Remove private inputs before publishing ``success``. For browser
        # uploads this deletes the large sources; for database discovery it
        # unlinks only the session's hard/symbolic links and leaves the
        # database-owned FITS untouched.
        _remove_upload_dir(session_dir)
        manifest['status'] = 'success'
        manifest['completed_utc'] = result['completed_utc']
        manifest['sources_deleted_utc'] = _utc_now_text()
        manifest['error'] = None
        _write_manifest(session_dir, manifest)
        return result
    except Exception as error:
        session_dir.joinpath('calibration.log').write_text(
            captured_output.getvalue(),
            encoding='utf-8',
        )
        cleanup_error = None
        try:
            _remove_upload_dir(session_dir)
        except OSError as cleanup_exception:
            cleanup_error = cleanup_exception
        manifest['status'] = 'failed'
        manifest['completed_utc'] = _utc_now_text()
        if cleanup_error is None:
            manifest['sources_deleted_utc'] = _utc_now_text()
            manifest['error'] = str(error)
        else:
            manifest['error'] = (
                '{0}; private calibration input cleanup also failed: {1}'
            ).format(error, cleanup_error)
        _write_manifest(session_dir, manifest)
        raise


def get_status(session_id, owner, storage_root=None):
    """Return the browser-safe status/result for an owned session."""
    session_dir, manifest = get_session(session_id, owner, storage_root)
    source = manifest.get('source') or {}
    response = {
        'session_id': session_id,
        'status': manifest['status'],
        'file_count': len(manifest.get('files', [])),
        'total_bytes': manifest.get('total_bytes', 0),
        'task_id': manifest.get('task_id'),
        'error': (
            _friendly_failure_message(manifest.get('error'))
            if manifest.get('status') == 'failed'
            else manifest.get('error')
        ),
        'source_kind': source.get('kind'),
        'sources_deleted_utc': manifest.get('sources_deleted_utc'),
        'report_available': session_dir.joinpath(
            'asi676mc_calibration_report.txt'
        ).is_file(),
    }
    result_path = session_dir.joinpath('result.json')
    if manifest['status'] == 'success' and result_path.is_file():
        result = json.loads(result_path.read_text(encoding='utf-8'))
        # Rebuild human-facing notes when an older retained result is opened.
        # This applies current consolidated wording immediately without
        # modifying the auditable result stored on disk.
        result['warnings'] = _result_warnings(
            result.get('quality', {}),
            result.get('source') or source,
        )
        response['result'] = result
    return response


def get_completed_result(session_id, owner, storage_root=None):
    """Return an owned successful manifest/result for configuration transfer."""
    session_dir, manifest = get_session(session_id, owner, storage_root)
    if manifest.get('status') != 'success':
        raise CalibrationSessionError('calibration has not completed successfully')
    result_path = session_dir.joinpath('result.json')
    try:
        result = json.loads(result_path.read_text(encoding='utf-8'))
    except (FileNotFoundError, OSError, json.JSONDecodeError) as error:
        raise CalibrationSessionError('the calibration result is missing') from error

    values = {
        item['key']: item['value']
        for item in result.get('values', [])
        if item.get('key') in DERIVED_VALUE_KEYS
    }
    if set(values) != set(DERIVED_VALUE_KEYS):
        raise CalibrationSessionError('the calibration result is incomplete')
    return manifest, result, values


def get_report_path(session_id, owner, storage_root=None):
    """Resolve an owned completed report for the authenticated download view."""
    session_dir, manifest = get_session(session_id, owner, storage_root)
    if manifest.get('status') != 'success':
        raise CalibrationSessionError('the calibration report is not ready')
    report_path = session_dir.joinpath('asi676mc_calibration_report.txt')
    if not report_path.is_file():
        raise CalibrationSessionError('the calibration report is missing')
    return report_path
