"""Web-session support for ASI676MC FITS calibration.

The web workflow imports indi-allsky's numerical calibration engine directly
as a Python module; it never starts a shell command or an external FITS program.

This module owns the web-specific concerns around that engine:

* private, per-user staging sessions;
* conservative file-count and storage limits;
* atomic manifest/result files shared by gunicorn and the video worker;
* deletion of uploaded FITS or private database staging files when a job ends;
* a compact result shape suitable for polling from the browser; and
* a web-native text report that never exposes private staging paths.

Session data lives below Flask's non-public instance directory by default.
This is important because the capture service uses systemd ``PrivateTmp`` and
therefore cannot reliably read files uploaded into the web process's ``/tmp``.
Deployments may override the location with ``ASI676MC_CALIBRATION_FOLDER``.
"""

from contextlib import contextmanager
from contextlib import redirect_stdout
from collections import Counter
from datetime import datetime
from datetime import timezone
import io
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import textwrap
import threading
import time
import unicodedata
import uuid


logger = logging.getLogger('indi_allsky')

SESSION_ID_RE = re.compile(r'^[0-9a-f]{32}$')
FITS_SUFFIXES = ('.fit', '.fits', '.fts')

# An uncompressed full-resolution ASI676MC FITS is roughly tens of megabytes.
# These limits comfortably allow sizeable calibration collections while
# preventing one authenticated browser session from consuming the whole disk.
MAX_FILE_COUNT = 80
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_SESSION_BYTES = 2 * 1024 * 1024 * 1024
TRANSFER_CHUNK_BYTES = 1024 * 1024
MAX_ACTIVE_SESSIONS_PER_OWNER = 2
MAX_ACTIVE_SESSIONS_GLOBAL = 4
SESSION_RETENTION_SECONDS = 7 * 24 * 60 * 60
UPLOADING_STALE_SECONDS = 30 * 60
QUEUED_STALE_SECONDS = 30 * 60
RUNNING_STALE_SECONDS = 2 * 60 * 60
DATABASE_GROUP_MIN = 7
DATABASE_GROUP_MAX = 30
DATABASE_CAPTURE_TIME_TOLERANCE = 1.0
DATABASE_MAX_FILES = 200
DATABASE_MAX_BYTES = MAX_SESSION_BYTES
PROGRESS_MANIFEST_INTERVAL_FILES = 50
# A collection does not need every purple frame to have two normal references.
# Once nine out of ten matched frames form complete good/purple/good triplets,
# the remaining one-sided evidence is too small a share to justify asking the
# user for another capture solely to improve triplet completeness.
TRIPLET_COVERAGE_COMPLETE_PERCENT = 90.0
ACTIVE_SESSION_STATUSES = (
    'uploading',
    'queued',
    'running',
    'cancel_requested',
)

# POSIX/Windows advisory locks coordinate different processes, but Windows may
# report EDEADLK when two threads in one gunicorn process lock the same byte.
# Serialize those threads first. The reference count lets completed session
# paths leave this registry without splitting existing waiters across two
# different process-local locks.
_PROCESS_FILE_LOCKS = {}
_PROCESS_FILE_LOCKS_GUARD = threading.Lock()

# Comparison tolerances are deliberately much smaller than the calibration
# engine's useful fitting resolution.  They are only used to tell a user
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

DETECTION_THRESHOLD_KEYS = (
    'PURPLE_RATIO_THRESHOLD',
    'RED_SIDE_RATIO_THRESHOLD',
    'BLUE_SIDE_RATIO_THRESHOLD',
)

DERIVED_VALUE_LABELS = {
    'GAIN_R': 'Purple-frame Gain R',
    'GAIN_G1': 'Purple-frame Gain G1',
    'GAIN_G2': 'Purple-frame Gain G2',
    'GAIN_B': 'Purple-frame Gain B',
    'SOURCE_SATURATION_THRESHOLD': 'Source Saturation Threshold',
    'HIGHLIGHT_BLEND_START_RATIO': 'Highlight Blend Start Ratio',
    'HIGHLIGHT_BLEND_END_RATIO': 'Highlight Blend End Ratio',
}


def _counted_item(count, singular, plural=None):
    """Return a readable count without exposing ``frame(s)`` style copy."""
    count = int(count)
    noun = singular if count == 1 else (plural or singular + 's')
    return '{0} {1}'.format(count, noun)


def _initial_database_search_text(source_details):
    """Describe the fallback target without mislabelling older results."""
    selection_mode = source_details.get('selection_mode')
    if selection_mode == 'marked_groups':
        return 'Not used; marked evidence was sufficient'
    if str(selection_mode or '').startswith('full_retention_'):
        return 'Complete retained archive'
    if selection_mode != 'progressive_search':
        return 'Not recorded by this result version'
    try:
        count = int(source_details['initial_scan_file_count'])
    except (KeyError, TypeError, ValueError):
        return 'Not recorded by this result version'
    return _counted_item(count, 'FITS file')


def _database_selection_text(selection_mode):
    """Return report wording for retained and current database workflows."""
    if selection_mode == 'marked_groups':
        return 'marked groups with adjacent normal FITS'
    if selection_mode == 'full_retention_detector_groups':
        return 'complete-retention detector search'
    if selection_mode == 'full_retention_population_groups':
        return 'complete-retention missed-purple population search'
    if selection_mode == 'background_full_retention':
        return 'queued complete-retention search'
    return 'progressive ratio search through retained FITS'


def _database_search_coverage_line(source_details):
    """Describe either exhaustive coverage or the legacy initial scan budget."""
    if str(source_details.get('selection_mode') or '').startswith(
        'full_retention_'
    ):
        return 'Database search coverage: Complete retained archive'
    return 'Initial fallback search target: {0}'.format(
        _initial_database_search_text(source_details)
    )


def capture_configuration_guidance(config):
    """Describe whether current capture settings retain calibration evidence.

    The current configuration cannot prove how older files were captured, so
    this is deliberately advisory.  Automatic discovery will still inspect
    the FITS that actually exist. This guidance explains why future purple
    frames will produce low-disk pairs, cached triplets, full-sequence groups,
    or no usable untouched evidence at all. The returned guidance intentionally
    combines the active conditions into one concise, severity-ranked
    explanation.
    """
    config = config if isinstance(config, dict) else {}
    repair = config.get('IMAGE_ASI676MC_REPAIR', {})
    repair = repair if isinstance(repair, dict) else {}

    repair_enabled = bool(repair.get('ENABLE', False))
    exclude_only = bool(repair.get('EXCLUDE_ONLY', True))
    diagnostic_fits = bool(repair.get('SAVE_DIAGNOSTIC_FITS', False))
    preceding_fits_configured = bool(
        repair.get('SAVE_PRECEDING_FITS', False)
    )
    preceding_fits = bool(
        repair_enabled
        and diagnostic_fits
        and preceding_fits_configured
    )
    standard_fits = bool(config.get('IMAGE_SAVE_FITS', False))
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

    if not standard_fits:
        standard_fits_text = 'Off'
    elif fits_period == 0:
        standard_fits_text = 'Every Image'
    elif not fits_period_valid:
        standard_fits_text = 'On (invalid interval)'
    else:
        standard_fits_text = 'Every {0} seconds'.format(fits_period)

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
    if preceding_fits:
        preceding_text = 'On (one-frame memory cache)'
    elif preceding_fits_configured and not repair_enabled:
        preceding_text = 'Inactive (handling off)'
    elif preceding_fits_configured and not diagnostic_fits:
        preceding_text = 'Inactive (Save Bad and Following RAW FITS off)'
    else:
        preceding_text = 'Off'
    if compressed_fits and standard_fits:
        compression_text = 'On'
    elif compressed_fits:
        compression_text = 'Inactive (standard FITS off)'
    else:
        compression_text = 'Off'
    facts = [
        {'label': 'Repair mode', 'value': mode_text},
        {
            'label': 'Save Bad and Following RAW FITS',
            'value': diagnostic_text,
        },
        {
            'label': 'Also Save Preceding RAW FITS',
            'value': preceding_text,
        },
        {'label': 'Standard FITS', 'value': standard_fits_text},
        {
            'label': 'Standard FITS compression',
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

    # Resolve the full switch combination into one user-facing outcome.
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
                'Automatic saved-FITS search cannot mark new purple frames '
                'while handling is off. Turn on purple-frame handling and '
                'keep Exclude Only on; the configured diagnostic saving will '
                'then start.'
            )
        else:
            guidance_sentences.append(
                'Automatic saved-FITS search cannot mark new purple frames '
                'while handling is off.'
            )
        if standard_fits and fits_period == 0:
            # Database discovery can open indi-allsky's gzip-compressed FITS,
            # but the browser uploader deliberately accepts only uncompressed
            # files. With no purple-frame flags, decompression is therefore the
            # only way to use this particular saved sequence manually.
            if compressed_fits:
                guidance_sentences.append(
                    'Complete compressed FITS sequences are being saved. '
                    'Decompress selected files before manual upload, or turn '
                    'on handling in Exclude Only mode for future automatic searches.'
                )
            else:
                guidance_sentences.append(
                    'Complete FITS sequences are being saved and can be '
                    'uploaded manually. Turn on handling in Exclude Only mode '
                    'for future automatic searches.'
                )
        elif standard_fits and not fits_period_valid:
            if diagnostic_fits:
                guidance_sentences.append(
                    'Correct or disable the invalid standard FITS interval. '
                    'Then turn on handling in Exclude Only mode; the configured '
                    'diagnostic saving will begin collecting calibration FITS.'
                )
            else:
                guidance_sentences.append(
                    'Correct the invalid standard FITS interval. For future '
                    'calibration data, turn on handling in Exclude Only mode '
                    'and save diagnostic FITS, or save standard FITS for Every Image.'
                )
        elif standard_fits:
            if diagnostic_fits:
                guidance_sentences.append(
                    'Periodic standard FITS may miss random purple frames. '
                    'Turn on handling in Exclude Only mode; the configured '
                    'diagnostic saving will then collect them more reliably.'
                )
            else:
                guidance_sentences.append(
                    'Periodic standard FITS may miss random purple frames. '
                    'Turn on handling in Exclude Only mode and save diagnostic '
                    'FITS, or save standard FITS for Every Image.'
                )
        else:
            if diagnostic_fits:
                guidance_sentences.append(
                    'No FITS are being saved. Turn on handling in Exclude Only '
                    'mode; the configured diagnostic saving will then begin.'
                )
            else:
                guidance_sentences.append(
                    'No FITS are being saved. Turn on handling in Exclude Only '
                    'mode and save diagnostic FITS, or save standard FITS for '
                    'Every Image.'
                )
    elif exclude_only:
        if diagnostic_fits:
            guidance_level = 'success'
            if standard_fits and fits_period == 0:
                guidance_title = 'Ready to collect complete FITS sequences'
                guidance_sentences.append(
                    'Exclude Only keeps purple frames unchanged. Diagnostic '
                    'saving keeps each purple frame and the next matching '
                    'frame. Every Image also saves the complete sequence and '
                    'uses additional disk space.'
                )
            elif standard_fits and not fits_period_valid:
                guidance_level = 'warning'
                guidance_title = 'Standard FITS setting needs correction'
                guidance_sentences.append(
                    'Diagnostic calibration FITS will be saved. Correct the '
                    'invalid standard FITS interval or turn standard FITS off.'
                )
            elif standard_fits:
                guidance_title = 'Ready for low-disk FITS collection'
                guidance_sentences.append(
                    'Exclude Only keeps purple frames unchanged. Diagnostic '
                    'saving keeps each purple frame and the next matching '
                    'normal frame. Periodic standard FITS are not required for calibration.'
                )
            else:
                guidance_title = 'Ready for low-disk FITS collection'
                guidance_sentences.append(
                    'Exclude Only keeps purple frames unchanged. Diagnostic '
                    'saving keeps each purple frame and the next matching '
                    'normal frame without saving every image.'
                )
        elif standard_fits and fits_period == 0:
            guidance_level = 'success'
            guidance_title = 'Ready to collect complete FITS sequences'
            guidance_sentences.append(
                'Exclude Only keeps purple frames unchanged, and Every Image '
                'saves complete sequences for automatic search. This provides '
                'strong evidence but uses more disk space.'
            )
        elif standard_fits and not fits_period_valid:
            guidance_title = 'No reliable calibration FITS will be saved'
            guidance_sentences.append(
                'Purple frames will remain unchanged, but the standard FITS '
                'interval is invalid. Save diagnostic FITS, or correct the '
                'interval and choose Every Image.'
            )
        elif standard_fits:
            guidance_title = 'Periodic FITS saving may miss purple frames'
            guidance_sentences.append(
                'Purple frames will remain unchanged, but periodic FITS may '
                'miss them. Save diagnostic FITS, or set standard FITS to Every Image.'
            )
        else:
            guidance_title = 'No calibration FITS will be saved'
            guidance_sentences.append(
                'Purple frames will remain unchanged, but no FITS are being '
                'saved. Save diagnostic FITS, or set standard FITS to Every Image.'
            )
    else:
        if diagnostic_fits:
            guidance_level = 'success'
            if standard_fits and fits_period == 0:
                guidance_title = 'Ready to collect complete FITS sequences'
                guidance_sentences.append(
                    'Repair is active. Diagnostic saving keeps the original '
                    'purple frame before repair and the next matching frame. '
                    'Every Image also saves the normal processed output and '
                    'uses additional disk space.'
                )
            elif standard_fits and not fits_period_valid:
                guidance_level = 'warning'
                guidance_title = 'Standard FITS setting needs correction'
                guidance_sentences.append(
                    'Diagnostic calibration FITS will be saved before repair. '
                    'Correct the invalid standard FITS interval or turn '
                    'standard FITS off.'
                )
            elif standard_fits:
                guidance_title = 'Ready for low-disk FITS collection'
                guidance_sentences.append(
                    'Repair is active. Diagnostic saving keeps the original '
                    'purple frame before repair and the next matching normal '
                    'frame. Periodic standard FITS are not required for calibration.'
                )
            else:
                guidance_title = 'Ready for low-disk FITS collection'
                guidance_sentences.append(
                    'Repair is active. Diagnostic saving keeps the original '
                    'purple frame before repair and the next matching normal '
                    'frame without saving every image.'
                )
        else:
            guidance_title = 'No untouched purple-frame FITS will be saved'
            if standard_fits and fits_period == 0:
                guidance_sentences.append(
                    'Every Image saves files after repair, so the original '
                    'purple frame is lost. Turn on diagnostic FITS saving, or '
                    'switch to Exclude Only while collecting calibration data.'
                )
            elif standard_fits and not fits_period_valid:
                guidance_sentences.append(
                    'Repair is active, diagnostic FITS saving is off, and the '
                    'standard FITS interval is invalid. Turn on diagnostic '
                    'saving, or switch to Exclude Only and set standard FITS '
                    'to Every Image while collecting calibration data.'
                )
            elif standard_fits:
                guidance_sentences.append(
                    'Periodic standard FITS may miss purple frames and are '
                    'saved after repair. Turn on diagnostic saving, or switch '
                    'to Exclude Only and set standard FITS to Every Image '
                    'while collecting calibration data.'
                )
            else:
                guidance_sentences.append(
                    'Repair is active, but no FITS are being saved. Turn on '
                    'diagnostic saving, or switch to Exclude Only and set '
                    'standard FITS to Every Image while collecting calibration data.'
                )

    if repair_enabled and diagnostic_fits:
        if standard_fits and fits_period == 0:
            guidance_sentences.append(
                'Diagnostic FITS are preferred. Keep Every Image on only if '
                'you also need standard FITS, or temporarily if diagnostic '
                'saving misses purple frames. Using both takes the most disk space.'
            )
        elif standard_fits and fits_period_valid:
            guidance_sentences.append(
                'Diagnostic FITS are preferred. Keep periodic standard FITS '
                'on only if you need them for another purpose. If diagnostic '
                'saving misses purple frames, temporarily set standard FITS '
                'saving to Every Image.'
            )
        elif not standard_fits:
            guidance_sentences.append(
                'Diagnostic FITS are preferred, so standard FITS can remain '
                'off unless you need them. If diagnostic saving misses purple '
                'frames, temporarily set standard FITS saving to Every Image.'
            )

    if preceding_fits:
        guidance_sentences.append(
            'Preceding RAW FITS saving is on. It keeps one normal frame in '
            'memory and saves it only when the next matching frame is purple. '
            'This provides a before/purple/after group while using about one '
            'extra FITS frame of memory and disk space.'
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
        'preceding_fits': preceding_fits,
        'standard_fits': standard_fits,
        'fits_period': fits_period,
    }


class CalibrationSessionError(RuntimeError):
    """Base class for a malformed, inaccessible, or invalid web session."""


class CalibrationUploadError(CalibrationSessionError):
    """Raised when an uploaded file is unsafe or outside the accepted limits."""


class CalibrationCancelled(CalibrationSessionError):
    """Raised inside the worker when an owner requests cancellation."""


def _utc_now_text():
    """Return an unambiguous timezone-aware timestamp for session files."""
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
        raise CalibrationSessionError(
            'This calibration run is no longer available. Reload the page '
            'and start a new calibration.'
        )

    root = get_storage_root(storage_root)
    session_dir = root.joinpath(session_id).resolve()
    if session_dir.parent != root:
        raise CalibrationSessionError(
            'This calibration run could not be opened. Reload the page and '
            'start a new calibration.'
        )
    return session_dir


def _manifest_path(session_dir):
    """Return the durable state file for one private calibration session."""
    return session_dir.joinpath('manifest.json')


def _cancel_marker_path(session_dir):
    """Return the tombstone checked by uploads and the background worker."""
    return session_dir.joinpath('.cancel-requested')


@contextmanager
def _file_lock(lock_path):
    """Hold one process-local and cross-process advisory path lock."""
    lock_path = Path(lock_path).resolve()
    lock_key = str(lock_path)
    with _PROCESS_FILE_LOCKS_GUARD:
        process_entry = _PROCESS_FILE_LOCKS.get(lock_key)
        if process_entry is None:
            process_entry = [threading.RLock(), 0]
            _PROCESS_FILE_LOCKS[lock_key] = process_entry
        process_entry[1] += 1
    process_lock = process_entry[0]
    process_lock.acquire()
    try:
        lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with lock_path.open('a+b') as lock_file:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b'0')
                lock_file.flush()
            lock_file.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                lock_file.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        process_lock.release()
        with _PROCESS_FILE_LOCKS_GUARD:
            process_entry[1] -= 1
            if process_entry[1] == 0:
                _PROCESS_FILE_LOCKS.pop(lock_key, None)


def _session_lock_path(session_dir):
    """Return the per-session mutation lock shared by web and video workers."""
    return Path(session_dir).joinpath('.session.lock')


def _atomic_write_json(path, data):
    """Publish JSON atomically so browser polling never sees half a file."""
    path = Path(path)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=path.parent,
            prefix='.manifest-',
            suffix='.tmp',
            delete=False,
        ) as temporary_file:
            temporary_name = temporary_file.name
            json.dump(
                data,
                temporary_file,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
        os.replace(temporary_name, path)
    except Exception:
        if temporary_name:
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass
        raise
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _read_manifest(session_dir):
    """Load a session manifest and translate storage damage to a safe error."""
    try:
        return json.loads(_manifest_path(session_dir).read_text(encoding='utf-8'))
    except FileNotFoundError as error:
        raise CalibrationSessionError(
            'This calibration run is no longer available. Reload the page '
            'and start a new calibration.'
        ) from error
    except (OSError, json.JSONDecodeError) as error:
        raise CalibrationSessionError(
            'This calibration run could not be read. Reload the page and '
            'start a new calibration. If this repeats, include this message '
            'when reporting the issue.'
        ) from error


def _write_manifest(session_dir, manifest):
    """Atomically publish session state without undoing a concurrent cancel."""
    # A cancel request may be handled by a different gunicorn worker while an
    # upload request is still unwinding.  Never let that older request publish
    # its stale ``uploading`` manifest over the cancellation result.
    if (
        _cancel_marker_path(session_dir).exists()
        and manifest.get('status') not in (
            'cancel_requested',
            'cancelled',
            'failed',
            'success',
        )
    ):
        raise CalibrationSessionError('this calibration upload was cancelled')
    manifest['updated_utc'] = _utc_now_text()
    _atomic_write_json(_manifest_path(session_dir), manifest)


def _remove_upload_dir(session_dir):
    """Remove private uploads or staged database files, retaining results."""
    upload_dir = session_dir.joinpath('uploads')
    if upload_dir.exists():
        shutil.rmtree(upload_dir)


def _recover_stale_session_unlocked(session_dir, manifest):
    """Fail or cancel an abandoned worker session while its lock is held."""
    status = manifest.get('status')
    if status not in ('uploading', 'queued', 'running', 'cancel_requested'):
        return manifest

    running = status in ('running', 'cancel_requested')
    timestamp_key = 'heartbeat_utc' if running else 'updated_utc'
    if running:
        stale_limit = RUNNING_STALE_SECONDS
    elif status == 'uploading':
        stale_limit = UPLOADING_STALE_SECONDS
    else:
        stale_limit = QUEUED_STALE_SECONDS
    try:
        last_update = datetime.fromisoformat(
            str(manifest.get(timestamp_key) or '')
        )
        age_seconds = (
            datetime.now(timezone.utc) - last_update
        ).total_seconds()
    except (TypeError, ValueError):
        age_seconds = stale_limit + 1

    if age_seconds <= stale_limit:
        return manifest

    _remove_upload_dir(session_dir)
    manifest['status'] = (
        'cancelled' if status == 'cancel_requested' else 'failed'
    )
    manifest['completed_utc'] = _utc_now_text()
    manifest['sources_deleted_utc'] = _utc_now_text()
    manifest['error'] = (
        None
        if status == 'cancel_requested'
        else (
            'calibration upload stopped responding; start a new run'
            if status == 'uploading'
            else 'calibration worker stopped responding; start a new run'
        )
    )
    manifest.pop('worker_token', None)
    _write_manifest(session_dir, manifest)
    return manifest


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


def create_session(owner, storage_root=None, camera_identity=None):
    """Create a private, quota-bounded calibration staging session."""
    owner = str(owner or '').strip()
    if not owner:
        raise CalibrationSessionError('a calibration session owner is required')

    root = get_storage_root(storage_root)
    with _file_lock(root.joinpath('.sessions.lock')):
        cleanup_expired_sessions(root)
        active_manifests = []
        for candidate in root.iterdir():
            if not candidate.is_dir() or not SESSION_ID_RE.fullmatch(candidate.name):
                continue
            try:
                candidate_manifest = _read_manifest(candidate)
                candidate_status = candidate_manifest.get('status')
                recover_candidate = candidate_status in (
                    'queued',
                    'running',
                    'cancel_requested',
                )
                if candidate_status == 'uploading':
                    try:
                        upload_age = (
                            datetime.now(timezone.utc)
                            - datetime.fromisoformat(
                                str(candidate_manifest.get('updated_utc') or '')
                            )
                        ).total_seconds()
                    except (TypeError, ValueError):
                        upload_age = UPLOADING_STALE_SECONDS + 1
                    recover_candidate = upload_age > UPLOADING_STALE_SECONDS
                if recover_candidate:
                    with _file_lock(_session_lock_path(candidate)):
                        candidate_manifest = _recover_stale_session_unlocked(
                            candidate,
                            _read_manifest(candidate),
                        )
            except CalibrationSessionError:
                continue
            if candidate_manifest.get('status') in ACTIVE_SESSION_STATUSES:
                active_manifests.append(candidate_manifest)
        owner_active = sum(
            manifest.get('owner') == owner
            for manifest in active_manifests
        )
        if owner_active >= MAX_ACTIVE_SESSIONS_PER_OWNER:
            raise CalibrationSessionError(
                'Another calibration is already active. Finish or cancel it '
                'before starting a new one.'
            )
        if len(active_manifests) >= MAX_ACTIVE_SESSIONS_GLOBAL:
            raise CalibrationSessionError(
                'The calibration service is currently busy. Wait a few '
                'minutes and try again.'
            )

        session_id = uuid.uuid4().hex
        session_dir = _session_dir(session_id, root)
        upload_dir = session_dir.joinpath('uploads')
        upload_dir.mkdir(mode=0o700, parents=True)

        manifest = {
            'version': 2,
            'session_id': session_id,
            'owner': owner,
            'status': 'uploading',
            'created_utc': _utc_now_text(),
            'updated_utc': _utc_now_text(),
            'files': [],
            'total_bytes': 0,
            'task_id': None,
            'camera': dict(camera_identity or {}),
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
        raise CalibrationSessionError(
            'This calibration run is no longer available. Reload the page '
            'and start a new calibration.'
        )
    return session_dir, manifest


def database_search_checkpoint(session_id, owner, storage_root=None):
    """Stop database discovery promptly after its owned session is cancelled."""
    session_dir, manifest = get_session(session_id, owner, storage_root)
    if (
        manifest.get('status') == 'cancelled'
        or _cancel_marker_path(session_dir).exists()
    ):
        raise CalibrationSessionError(
            'This saved-FITS search was cancelled. Start a new search if you '
            'want to try again.'
        )
    if manifest.get('status') != 'uploading':
        raise CalibrationSessionError(
            'This saved-FITS search has already finished or stopped. Reload '
            'the page to view its result or start again.'
        )
    return manifest


def _unique_upload_name(upload_dir, original_name):
    """Return a sanitized collision-free FITS name inside an upload folder."""
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
    try:
        exposure = round(float(record.get('exposure', -1.0)), 12)
        gain = round(float(record.get('gain', -1.0)), 6)
        binmode = int(record.get('binmode', -1))
    except (OverflowError, TypeError, ValueError):
        return None
    return (
        record.get('width'),
        record.get('height'),
        exposure,
        gain,
        binmode,
    )


def discover_full_retention_database_evidence(
    fits_records,
    bad_frames,
    target_groups,
    max_pair_seconds,
    settings,
    progress_callback=None,
    cancel_callback=None,
    signature_callback=None,
):
    """Inspect the complete retained database catalog and stage only evidence.

    Unlike browser uploads, database discovery owns the search horizon.  Every
    eligible retained row is therefore considered.  Saved detector signatures
    avoid reopening modern FITS; legacy rows are inspected directly.  Only the
    final matched purple/reference groups are returned for bounded private
    staging.
    """
    from . import asi676mc
    from . import asi676mc_calibration_engine as engine

    target_groups = int(target_groups)
    if target_groups < DATABASE_GROUP_MIN or target_groups > DATABASE_GROUP_MAX:
        raise CalibrationSessionError(
            'database purple-frame target must be between {0} and {1}'.format(
                DATABASE_GROUP_MIN,
                DATABASE_GROUP_MAX,
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

    normalized_settings = asi676mc.normalize_settings(settings)
    candidates = []
    for source_record in fits_records:
        try:
            record = dict(source_record)
            path = Path(record['path'])
            file_size = int(record.get('size') or path.stat().st_size)
            record.update({
                'path': path,
                'size': file_size,
                'timestamp': float(record['timestamp']),
                'id': int(record['id']),
            })
        except (KeyError, OSError, OverflowError, TypeError, ValueError):
            continue
        has_signature = bool(record.get('signature'))
        try:
            record.update({
                'exposure': float(record.get('exposure', -1.0)),
                'gain': float(record.get('gain', -1.0)),
                'binmode': int(record.get('binmode', -1)),
                'width': int(record.get('width', -1)),
                'height': int(record.get('height', -1)),
            })
        except (OverflowError, TypeError, ValueError):
            # Legacy FITS are inspected from their authoritative headers, so
            # incomplete database-side capture metadata must not hide them.
            record.update({
                'exposure': -1.0,
                'gain': -1.0,
                'binmode': -1,
                'width': -1,
                'height': -1,
            })
        if (
            not asi676mc.camera_name_matches(record.get('camera_name'))
            or file_size <= 0
            or file_size > MAX_FILE_BYTES
            or not math.isfinite(record['timestamp'])
        ):
            continue
        signature_metadata_usable = has_signature and not (
            not math.isfinite(record['exposure'])
            or record['exposure'] <= 0.0
            or not math.isfinite(record['gain'])
            or record['gain'] < 0.0
            or record['binmode'] != 1
            or record['width'] <= 0
            or record['height'] <= 0
            or record['width'] % 2
            or record['height'] % 2
        )
        record['_signature_metadata_usable'] = signature_metadata_usable
        candidates.append(record)

    candidates.sort(key=lambda item: item['timestamp'], reverse=True)
    if not candidates:
        raise engine.CalibrationError(
            'the complete retained database archive contains no eligible '
            'ASI676MC FITS files'
        )

    # Successfully repaired standard FITS contain corrected pixels and must
    # not re-enter calibration as untouched evidence.  Exclude their matching
    # database rows before any legacy full-image read.
    repaired_standard_ids = set()
    for source_bad_frame in bad_frames:
        try:
            bad_time = float(source_bad_frame['timestamp'])
            bad_exposure = float(source_bad_frame.get('exposure', -1.0))
            bad_gain = float(source_bad_frame.get('gain', -1.0))
        except (KeyError, OverflowError, TypeError, ValueError):
            continue
        if source_bad_frame.get('allow_standard', True):
            continue
        repaired_standard_ids.update(
            record['id']
            for record in candidates
            if not record.get('roles')
            and abs(record['timestamp'] - bad_time)
            <= DATABASE_CAPTURE_TIME_TOLERANCE
            and round(record['exposure'], 12) == round(bad_exposure, 12)
            and round(record['gain'], 6) == round(bad_gain, 6)
        )

    diagnostic_bad_records = [
        record
        for record in candidates
        if _database_record_has_role(record, 'bad')
    ]
    duplicate_standard_ids = set()
    for bad_record in diagnostic_bad_records:
        compatibility_key = _database_compatibility_key(bad_record)
        if compatibility_key is None:
            continue
        duplicate_standard_ids.update(
            record['id']
            for record in candidates
            if not record.get('roles')
            and _database_compatibility_key(record) == compatibility_key
            and abs(record['timestamp'] - bad_record['timestamp'])
            <= DATABASE_CAPTURE_TIME_TOLERANCE
        )

    excluded_ids = repaired_standard_ids | duplicate_standard_ids
    searchable = [
        record for record in candidates
        if record['id'] not in excluded_ids
    ]
    inspected = []
    raw_by_path = {}
    rejected = Counter()
    metadata_signature_count = 0
    legacy_inspected_count = 0
    detected_during_scan = 0
    threshold_search_started = False
    total = len(searchable)
    for index, record in enumerate(searchable, start=1):
        if cancel_callback and (index == 1 or index % 5 == 0):
            cancel_callback()
        path = record['path']
        inspected_legacy = False
        try:
            if record.get('_signature_metadata_usable'):
                try:
                    frame = engine.inspect_fits_metadata(
                        path,
                        record,
                        normalized_settings,
                        verify_header=True,
                    )
                    metadata_signature_count += 1
                except engine.RepairedFitsError:
                    raise
                except (KeyError, TypeError, ValueError):
                    # A malformed or incomplete saved signature must not make
                    # an otherwise valid retained FITS invisible. Treat it as
                    # legacy evidence and inspect the source image directly.
                    frame = engine.inspect_fits(
                        path,
                        normalized_settings,
                        trusted_camera_name=record.get('camera_name'),
                    )
                    legacy_inspected_count += 1
                    inspected_legacy = True
            else:
                frame = engine.inspect_fits(
                    path,
                    normalized_settings,
                    trusted_camera_name=record.get('camera_name'),
                )
                legacy_inspected_count += 1
                inspected_legacy = True
        except Exception as error:
            if not engine.is_recoverable_fits_error(error):
                raise
            rejected[str(error)] += 1
        else:
            inspected.append(frame)
            if frame.is_bad:
                detected_during_scan += 1
            raw_by_path[str(path)] = record
            if inspected_legacy:
                saved_signature = {
                    name: float(frame.signature[name])
                    for name in engine.DETECTION_THRESHOLD_DETAILS
                }
                record['signature'] = saved_signature
                if signature_callback:
                    signature_callback(record['id'], saved_signature)
        if index >= 14 and detected_during_scan < 7:
            threshold_search_started = True
        if progress_callback:
            progress_callback({
                'phase': (
                    'threshold_search'
                    if threshold_search_started
                    else 'detector_scan'
                ),
                'processed_files': index,
                'total_files': total,
                'initial_target_files': total,
                'detected_bad_count': detected_during_scan,
            })

    minimum = engine.CALIBRATION_OPTIONS['MIN_BAD_PAIRS']
    if len(inspected) < minimum * 2:
        raise engine.CalibrationError(
            'the complete retained database archive was exhausted: only {0} '
            'compatible FITS could be inspected; at least {1} are required'
            .format(len(inspected), minimum * 2)
        )

    detected_bad_count = sum(record.is_bad for record in inspected)
    detector_pairs = []
    detector_usable = False
    if detected_bad_count >= minimum:
        detector_pairs, detector_unmatched = engine.match_pairs(
            inspected,
            max_pair_seconds,
            checkpoint_callback=cancel_callback,
        )
        try:
            engine.validate_evidence(
                inspected,
                detector_pairs,
                detector_unmatched,
                allow_unmatched=True,
            )
            detector_usable = True
        except engine.CalibrationError:
            detector_usable = False
    if detector_usable:
        classified = inspected
        selection_mode = 'full_retention_detector_groups'
        pairs = detector_pairs
        unmatched = detector_unmatched
    else:
        try:
            classified = engine.infer_detection_populations(
                inspected,
                checkpoint_callback=cancel_callback,
                allow_detected_conflicts=True,
            )
        except engine.CalibrationError as error:
            raise engine.CalibrationError(
                'the complete retained database archive was exhausted after '
                'inspecting {0} compatible FITS, but neither the configured '
                'detector nor population analysis identified usable '
                'purple/normal evidence: {1}'.format(
                    len(inspected),
                    error,
                )
            ) from error
        selection_mode = 'full_retention_population_groups'
        pairs, unmatched = engine.match_pairs(
            classified,
            max_pair_seconds,
            checkpoint_callback=cancel_callback,
        )
    pairs.sort(key=lambda pair: pair.bad.timestamp, reverse=True)
    exposure_seeds = []
    seeded_exposures = []
    for pair in pairs:
        exposure = float(pair.bad.exposure)
        if any(
            math.isclose(
                exposure,
                seeded,
                rel_tol=engine.EXPOSURE_LEVEL_REL_TOLERANCE,
                abs_tol=engine.EXPOSURE_LEVEL_ABS_TOLERANCE,
            )
            for seeded in seeded_exposures
        ):
            continue
        exposure_seeds.append(pair)
        seeded_exposures.append(exposure)
        if len(exposure_seeds) >= engine.CALIBRATION_OPTIONS[
            'MIN_EXPOSURE_LEVELS'
        ]:
            break
    seeded_ids = {id(pair) for pair in exposure_seeds}
    ordered_pairs = exposure_seeds + [
        pair for pair in pairs
        if id(pair) not in seeded_ids
    ]
    selected_records = []
    selected_ids = set()
    selected_pairs = []
    selected_bytes = 0
    selected_group_count = 0
    two_sided_group_count = 0
    selection_limit_blocked = False

    def add_group(pair, references):
        nonlocal selected_bytes, selection_limit_blocked
        group_frames = (pair.bad,) + tuple(references)
        group_records = []
        for frame in group_frames:
            raw_record = raw_by_path.get(str(frame.path))
            if raw_record is None or raw_record['id'] in selected_ids:
                continue
            group_records.append(raw_record)
        group_bytes = sum(record['size'] for record in group_records)
        if (
            len(selected_records) + len(group_records) > DATABASE_MAX_FILES
            or selected_bytes + group_bytes > DATABASE_MAX_BYTES
        ):
            selection_limit_blocked = True
            return False
        for raw_record in group_records:
            selected_records.append(raw_record)
            selected_ids.add(raw_record['id'])
            selected_bytes += raw_record['size']
        return True

    for pair in ordered_pairs:
        if cancel_callback:
            cancel_callback()
        references = tuple(pair.references)
        added = add_group(pair, references)
        used_two_sided = pair.two_sided
        if not added and len(references) > 1:
            nearest = min(
                references,
                key=lambda item: abs(item.timestamp - pair.bad.timestamp),
            )
            added = add_group(pair, (nearest,))
            used_two_sided = False
        if not added:
            continue
        selected_group_count += 1
        selected_pairs.append(engine.MatchedPair(
            bad=pair.bad,
            references=(
                references
                if used_two_sided
                else (
                    min(
                        references,
                        key=lambda item: abs(
                            item.timestamp - pair.bad.timestamp
                        ),
                    ),
                )
            ),
        ))
        if used_two_sided:
            two_sided_group_count += 1
        if selected_group_count >= target_groups:
            break

    if selected_group_count < minimum:
        limit_detail = ''
        if pairs and selection_limit_blocked:
            limit_detail = ' within the 200-file/2-GiB evidence staging limit'
        raise engine.CalibrationError(
            'the complete retained database archive was exhausted: {0} '
            'purple frames had compatible adjacent normal evidence{1}; at '
            'least {2} are required'.format(
                selected_group_count,
                limit_detail,
                minimum,
            )
        )

    selected_frames = [
        frame for frame in classified
        if raw_by_path[str(frame.path)]['id'] in selected_ids
    ]
    try:
        engine.validate_evidence(
            selected_frames,
            selected_pairs,
            unmatched=[],
            allow_unmatched=True,
        )
    except engine.CalibrationError as error:
        raise engine.CalibrationError(
            'the complete retained database archive was exhausted, but the '
            'selected purple/reference groups could not satisfy calibration '
            'requirements: {0}'.format(error)
        ) from error

    if progress_callback:
        progress_callback({
            'phase': 'evidence_ready',
            'processed_files': total,
            'total_files': total,
            'initial_target_files': total,
            'detected_bad_count': detected_bad_count,
        })

    return selected_records, {
        'requested_group_count': target_groups,
        'selection_mode': selection_mode,
        'selected_file_count': len(selected_records),
        'initial_scan_file_count': len(selected_records),
        'available_file_count': len(inspected),
        'retained_candidate_count': len(candidates),
        'archive_scanned_file_count': len(searchable),
        'compatible_scanned_file_count': len(inspected),
        'metadata_signature_count': metadata_signature_count,
        'legacy_fits_inspected_count': legacy_inspected_count,
        'detected_bad_count': detected_bad_count,
        'selected_group_count': selected_group_count,
        'selected_marked_group_count': sum(
            _database_record_has_role(record, 'bad')
            for record in selected_records
        ),
        'two_sided_group_count': two_sided_group_count,
        'selection_limit_reached': (
            selection_limit_blocked
            or selected_group_count < min(target_groups, len(pairs))
        ),
        'selection_limit_file_count': DATABASE_MAX_FILES,
        'selection_limit_bytes': DATABASE_MAX_BYTES,
        'selected_logical_bytes': selected_bytes,
        'excluded_repaired_standard_count': len(repaired_standard_ids),
        'excluded_duplicate_standard_count': len(duplicate_standard_ids),
        'rejected_file_count': sum(rejected.values()),
        'rejection_counts': dict(sorted(rejected.items())),
        'unmatched_purple_count': len(unmatched),
        'full_retention_exhaustive': True,
    }


def _copy_database_file(source, destination, cancel_marker):
    """Copy one cross-filesystem database FITS with cancellation checkpoints."""
    partial = destination.with_name(destination.name + '.part')
    try:
        with source.open('rb') as source_file, partial.open('xb') as output_file:
            while True:
                if cancel_marker.exists():
                    raise CalibrationSessionError(
                        'this calibration database search was cancelled'
                    )
                chunk = source_file.read(TRANSFER_CHUNK_BYTES)
                if not chunk:
                    break
                output_file.write(chunk)
        if cancel_marker.exists():
            raise CalibrationSessionError(
                'this calibration database search was cancelled'
            )
        shutil.copystat(source, partial)
        os.replace(partial, destination)
    except Exception:
        try:
            partial.unlink()
        except FileNotFoundError:
            pass
        raise


def _stage_database_files_unlocked(
    session_id,
    owner,
    records,
    storage_root=None,
    expected_status='uploading',
    worker_token=None,
):
    """Link selected local DB assets into a private calibration session.

    Hard links keep a selected FITS alive if its database row expires while the
    job is queued without duplicating large files. On a separate filesystem a
    private copy is used; a symbolic link would let a replaced database path
    change the evidence after selection.
    """
    session_dir, manifest = get_session(session_id, owner, storage_root)
    if manifest.get('status') != expected_status:
        raise CalibrationSessionError(
            'This saved-FITS search can no longer prepare files. Reload the '
            'page and start a new search.'
        )
    if (
        worker_token is not None
        and manifest.get('worker_token') != str(worker_token)
    ):
        raise CalibrationSessionError(
            'The calibration service could not continue this run. Reload the '
            'page and start again. If this repeats, include this message when '
            'reporting the issue.'
        )
    if manifest.get('files') or manifest.get('total_bytes'):
        raise CalibrationSessionError(
            'This saved-FITS search already contains temporary files. Reload '
            'the page and start a new search.'
        )
    records = list(records)
    if len(records) > DATABASE_MAX_FILES:
        raise CalibrationSessionError(
            'The saved-FITS search selected too many files. Start a new search '
            'with a lower purple-frame group target.'
        )

    upload_dir = session_dir.joinpath('uploads')
    cancel_marker = _cancel_marker_path(session_dir)
    staging_rejections = Counter()
    from . import asi676mc
    try:
        for sequence, record in enumerate(records):
            if cancel_marker.exists():
                raise CalibrationSessionError(
                    'this calibration database search was cancelled'
                )
            source = Path(record['path']).resolve()
            if not source.is_file():
                staging_rejections['selected FITS no longer available'] += 1
                continue
            if not is_database_fits_path(source):
                raise CalibrationSessionError(
                    'unsupported database FITS format: {0}'.format(source.name)
                )
            if not asi676mc.camera_name_matches(record.get('camera_name')):
                raise CalibrationSessionError(
                    'database evidence is not positively identified as ASI676MC'
                )
            try:
                file_size = source.stat().st_size
            except OSError:
                staging_rejections['selected FITS became unavailable'] += 1
                continue
            if file_size <= 0 or file_size > MAX_FILE_BYTES:
                staging_rejections['selected FITS size changed'] += 1
                continue
            if manifest['total_bytes'] + file_size > MAX_SESSION_BYTES:
                staging_rejections['selected FITS no longer fits staging limit'] += 1
                continue
            destination = upload_dir.joinpath(
                '{0:06d}_{1}_{2}'.format(sequence, record['id'], source.name)
            )
            try:
                os.link(str(source), str(destination))
                link_type = 'hardlink'
            except OSError:
                try:
                    _copy_database_file(source, destination, cancel_marker)
                    link_type = 'copy'
                except OSError:
                    staging_rejections['selected FITS became unreadable'] += 1
                    continue

            manifest['files'].append({
                'name': destination.name,
                'original_name': source.name,
                'size': file_size,
                'database_id': int(record['id']),
                'link_type': link_type,
                # New FITS rows carry threshold-independent detector ratios.
                'signature': (
                    dict(record['signature'])
                    if record.get('signature')
                    else None
                ),
                'timestamp': float(record.get('timestamp', 0.0)),
                'exposure': float(record.get('exposure', -1.0)),
                'gain': float(record.get('gain', -1.0)),
                'binmode': int(record.get('binmode', 1)),
                'width': record.get('width'),
                'height': record.get('height'),
                'camera_name': record.get('camera_name'),
                'repair_status': record.get('repair_status'),
            })
            manifest['total_bytes'] += file_size
        if not manifest['files']:
            raise CalibrationSessionError(
                'all selected database FITS became unavailable during staging'
            )
        if staging_rejections:
            source_details = dict(manifest.get('source') or {})
            source_details['staging_skipped_file_count'] = sum(
                staging_rejections.values()
            )
            source_details['staging_rejection_counts'] = dict(
                sorted(staging_rejections.items())
            )
            manifest['source'] = source_details
    except Exception:
        _remove_upload_dir(session_dir)
        upload_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        raise

    _write_manifest(session_dir, manifest)
    return manifest


def stage_database_files(session_id, owner, records, storage_root=None):
    """Serialize database staging so parallel requests cannot corrupt it."""
    session_dir = _session_dir(session_id, storage_root)
    with _file_lock(_session_lock_path(session_dir)):
        return _stage_database_files_unlocked(
            session_id,
            owner,
            records,
            storage_root=storage_root,
        )


def stage_database_files_for_worker(
    session_id,
    worker_token,
    records,
    storage_root=None,
):
    """Stage selected database evidence for the worker that owns the session."""
    session_dir = _session_dir(session_id, storage_root)
    with _file_lock(_session_lock_path(session_dir)):
        manifest = _read_manifest(session_dir)
        return _stage_database_files_unlocked(
            session_id,
            manifest.get('owner'),
            records,
            storage_root=storage_root,
            expected_status='running',
            worker_token=worker_token,
        )


def _store_upload_unlocked(
    session_id,
    owner,
    file_storage,
    storage_root=None,
):
    """Stream one browser-selected FITS into its private session.

    The browser calls this once per selected file, automatically.  Sequential
    transfer avoids holding an entire 14-80 file collection in one request and
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


def store_upload(session_id, owner, file_storage, storage_root=None):
    """Serialize upload mutation across browser tabs and web workers."""
    session_dir = _session_dir(session_id, storage_root)
    with _file_lock(_session_lock_path(session_dir)):
        return _store_upload_unlocked(
            session_id,
            owner,
            file_storage,
            storage_root=storage_root,
        )


def _cancel_session_unlocked(session_id, owner, storage_root=None):
    """Cancel input discovery/queueing or request worker cancellation."""
    session_dir, manifest = get_session(session_id, owner, storage_root)
    status = manifest.get('status')
    if status in ('cancelled', 'cancel_requested'):
        return manifest
    if status not in ('uploading', 'queued', 'running'):
        raise CalibrationSessionError(
            'This calibration has already finished and cannot be cancelled. '
            'Reload the page to view or clear its result.'
        )

    marker_path = _cancel_marker_path(session_dir)
    marker_path.write_text(_utc_now_text(), encoding='ascii')
    try:
        marker_path.chmod(0o600)
    except OSError:
        pass

    if status == 'running':
        manifest['status'] = 'cancel_requested'
        manifest['error'] = None
        _write_manifest(session_dir, manifest)
        return manifest

    manifest['status'] = 'cancelled'
    manifest['completed_utc'] = _utc_now_text()
    manifest['error'] = None
    _remove_upload_dir(session_dir)
    manifest['sources_deleted_utc'] = _utc_now_text()
    _write_manifest(session_dir, manifest)
    return manifest


def cancel_session(session_id, owner, storage_root=None):
    """Serialize cancellation with staging, queue, and worker transitions."""
    session_dir = _session_dir(session_id, storage_root)
    # Authenticate first, then publish the marker before waiting for a large
    # upload or cross-filesystem database copy to release the session lock.
    # Those staging loops check the marker between chunks/files and unwind.
    _loaded_dir, manifest = get_session(session_id, owner, storage_root)
    if manifest.get('status') in ('uploading', 'queued', 'running'):
        marker_path = _cancel_marker_path(session_dir)
        marker_path.write_text(_utc_now_text(), encoding='ascii')
        try:
            marker_path.chmod(0o600)
        except OSError:
            pass
    with _file_lock(_session_lock_path(session_dir)):
        return _cancel_session_unlocked(
            session_id,
            owner,
            storage_root=storage_root,
        )


def cancel_upload_session(session_id, owner, storage_root=None):
    """Retain compatibility with the original upload-only helper name."""
    return cancel_session(session_id, owner, storage_root)


def discard_session(session_id, owner, storage_root=None):
    """Delete a finished/cancelled owned session and its retained results."""
    session_dir = _session_dir(session_id, storage_root)
    with _file_lock(_session_lock_path(session_dir)):
        _loaded_dir, manifest = get_session(session_id, owner, storage_root)
        if manifest.get('status') in ACTIVE_SESSION_STATUSES:
            raise CalibrationSessionError(
                'This calibration is still running. Cancel it before clearing '
                'the run.'
            )
    shutil.rmtree(session_dir)


def _mark_queued_unlocked(
    session_id,
    owner,
    task_id,
    max_pair_seconds,
    settings,
    config_id=None,
    source_details=None,
    storage_root=None,
):
    """Freeze the staged evidence set and record background-job parameters."""
    session_dir, manifest = get_session(session_id, owner, storage_root)
    if _cancel_marker_path(session_dir).exists():
        raise CalibrationSessionError(
            'This calibration was cancelled. Reset the tool to start again.'
        )
    if manifest.get('status') != 'uploading':
        raise CalibrationSessionError(
            'This calibration has already started. Reload the page to view '
            'its progress or result.'
        )
    source_details = dict(source_details or {})
    database_search = (
        source_details.get('kind') == 'database'
        and source_details.get('selection_mode') == 'background_full_retention'
    )
    if not database_search and len(manifest.get('files', [])) < 14:
        raise CalibrationSessionError(
            'Select at least 14 FITS at once: seven purple frames and at least '
            'seven different nearby normal frames.'
        )

    max_pair_seconds = float(max_pair_seconds)
    if (
        not math.isfinite(max_pair_seconds)
        or max_pair_seconds <= 0
        or max_pair_seconds > 3600
    ):
        raise CalibrationSessionError(
            'Enter a maximum time between 1 and 3600 seconds. Use 90 seconds '
            'unless the matching frames are farther apart.'
        )

    from . import asi676mc

    try:
        normalized_settings = asi676mc.normalize_settings(settings)
    except (OverflowError, TypeError, ValueError) as error:
        raise CalibrationSessionError(
            'The current ASI676MC settings are invalid. Restore the defaults '
            'or correct the highlighted fields in Image Settings, then start '
            'calibration again.'
        ) from error

    manifest['status'] = 'queued'
    manifest['task_id'] = int(task_id)
    manifest['max_pair_seconds'] = max_pair_seconds
    manifest['settings'] = normalized_settings
    manifest['config_id'] = int(config_id) if config_id is not None else None
    manifest['source'] = dict(source_details or {
        'kind': 'upload',
        'selected_file_count': len(manifest.get('files', [])),
    })
    manifest['progress'] = {
        'phase': 'database_search_queued' if database_search else 'queued',
        'processed_files': 0,
        'total_files': len(manifest.get('files', [])),
        'detected_bad_count': 0,
    }
    manifest['error'] = None
    _write_manifest(session_dir, manifest)
    return manifest


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
    """Atomically freeze one session and reject duplicate queue requests."""
    session_dir = _session_dir(session_id, storage_root)
    with _file_lock(_session_lock_path(session_dir)):
        return _mark_queued_unlocked(
            session_id,
            owner,
            task_id,
            max_pair_seconds,
            settings,
            config_id=config_id,
            source_details=source_details,
            storage_root=storage_root,
        )


def mark_failed(session_id, owner, message, storage_root=None):
    """Record a pre-worker failure such as a database queueing error."""
    session_dir = _session_dir(session_id, storage_root)
    with _file_lock(_session_lock_path(session_dir)):
        _loaded_dir, manifest = get_session(session_id, owner, storage_root)
        _remove_upload_dir(session_dir)
        manifest['status'] = 'failed'
        manifest['completed_utc'] = _utc_now_text()
        manifest['sources_deleted_utc'] = _utc_now_text()
        manifest['error'] = str(message)
        _write_manifest(session_dir, manifest)
        return manifest


def _result_summary(payload):
    """Reduce a successful engine payload to the browser-safe result schema."""
    settings = payload['derived_settings']
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
        'worst_repaired_reference_error': quality.get(
            'worst_repaired_reference_error'
        ),
        'rejected_file_count': quality['rejected_file_count'],
        'highlight_sample_count': quality['highlight_sample_count'],
        'scanned_file_count': quality.get('scanned_file_count', 0),
        'available_file_count': quality.get('available_file_count', 0),
        'search_stopped_early': quality.get('search_stopped_early', False),
        'bound_session_camera_count': quality.get(
            'bound_session_camera_count',
            0,
        ),
        'bound_database_camera_count': quality.get(
            'bound_database_camera_count',
            0,
        ),
        'database_metadata_camera_count': quality.get(
            'database_metadata_camera_count',
            0,
        ),
    }

    return {
        'outcome': 'calibration',
        'values': values,
        'threshold_assessment': payload.get('threshold_assessment', []),
        'quality': quality_summary,
        'warnings': _result_warnings(quality_summary),
    }


def _threshold_suggestion_summary(payload):
    """Return the browser-safe preliminary threshold-analysis result."""
    quality = payload['quality']
    quality_summary = {
        'preliminary': True,
        'detected_bad_count': quality.get('detected_bad_count', 0),
        'likely_purple_count': quality['likely_purple_count'],
        'likely_normal_count': quality['likely_normal_count'],
        'matched_bad_count': quality['pair_count'],
        'unmatched_bad_count': quality.get('unmatched_bad_count', 0),
        'matched_normal_count': quality['unique_good_count'],
        'two_sided_count': quality['two_sided_count'],
        'exposure_level_count': len(quality['exposure_levels']),
        'rejected_file_count': quality.get('rejected_file_count', 0),
        'scanned_file_count': quality.get('scanned_file_count', 0),
        'available_file_count': quality.get('available_file_count', 0),
        'search_stopped_early': quality.get('search_stopped_early', False),
        'bound_session_camera_count': quality.get(
            'bound_session_camera_count',
            0,
        ),
        'bound_database_camera_count': quality.get(
            'bound_database_camera_count',
            0,
        ),
        'database_metadata_camera_count': quality.get(
            'database_metadata_camera_count',
            0,
        ),
    }
    return {
        'outcome': 'threshold_suggestion',
        'threshold_suggestions': payload['threshold_suggestions'],
        'signature_ranges': payload['signature_ranges'],
        'population_evidence': payload.get('population_evidence', []),
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


def _result_warnings(
    quality,
    source_details=None,
    report_context=False,
    threshold_assessment=None,
):
    """Build non-overlapping result notes for the page or downloaded report.

    Both surfaces interpret the evidence identically.  Only the final pointer
    for rejected-file details differs: the page points to the download, while
    the download points to its own detail section.
    """
    warnings = []
    bound_identity_count = int(
        quality.get('bound_session_camera_count', 0)
    )
    if bound_identity_count:
        warnings.append(
            'No action is needed: {0} did not name the camera model. The tool '
            'could use {1} because this upload was tied to the selected '
            'ASI676MC. Files that named a different camera were rejected.'
            .format(
                _counted_item(bound_identity_count, 'uploaded FITS file'),
                'it' if bound_identity_count == 1 else 'they',
            )
        )
    bound_database_count = int(
        quality.get('bound_database_camera_count', 0)
    )
    if bound_database_count:
        warnings.append(
            'No action is needed: {0} did not name the camera model. The tool '
            'could use {1} because the saved database {2} belonged to the '
            'selected ASI676MC. Files that named a different camera were rejected.'
            .format(
                _counted_item(bound_database_count, 'saved FITS file'),
                'it' if bound_database_count == 1 else 'they',
                'entry' if bound_database_count == 1 else 'entries',
            )
        )
    source_details = source_details or {}
    preliminary = bool(quality.get('preliminary'))

    marginal_thresholds = [
        item for item in (threshold_assessment or ())
        if item.get('marginal')
    ]
    if marginal_thresholds:
        details = []
        for item in marginal_thresholds:
            details.append(
                '{0}: normal maximum {1:.3f}, current {2:.3f}, purple '
                'minimum {3:.3f}, midpoint {4:.3f}'.format(
                    item['label'],
                    item['normal_max'],
                    item['current'],
                    item['purple_min'],
                    item['suggested'],
                )
            )
        warnings.append((
            'Calibration is valid, but {0}: {1}. Collect more varied FITS and '
            'calibrate again before changing {2}.'
        ).format(
            'this threshold has a narrow margin'
            if len(details) == 1
            else 'these thresholds have narrow margins',
            '; '.join(details),
            'this detection value'
            if len(details) == 1
            else 'these detection values',
        ))

    if source_details.get('kind') == 'database':
        selection_mode = source_details.get('selection_mode')
        target_groups = int(source_details.get('requested_group_count', 0))
        marked_groups = int(
            source_details.get('selected_marked_group_count', 0)
        )
        staging_skipped = int(
            source_details.get('staging_skipped_file_count', 0)
        )
        if staging_skipped:
            warnings.append(
                'No action is needed: {0} selected FITS changed or disappeared '
                'before analysis. The remaining files were still sufficient.'
                .format(staging_skipped)
            )
        if source_details.get('selection_limit_reached'):
            if str(selection_mode or '').startswith('full_retention_'):
                warnings.append(
                    'No action is needed: the complete saved-FITS archive was '
                    'searched. The temporary {0}-file or 2-GiB limit was '
                    'reached, so the newest suitable groups that fit were used.'
                    .format(
                        source_details.get(
                            'selection_limit_file_count',
                            DATABASE_MAX_FILES,
                        )
                    )
                )
            else:
                warnings.append(
                    'The saved-FITS search reached its temporary {0}-file or '
                    '2-GiB limit. The newest marked purple-frame groups were '
                    'used first. If the result asks for more evidence, upload '
                    'the older FITS manually.'
                    .format(
                        source_details.get(
                            'selection_limit_file_count',
                            DATABASE_MAX_FILES,
                        )
                    )
                )
        if selection_mode == 'marked_groups' and marked_groups < target_groups:
            warnings.append(
                'No action is needed: the saved-FITS search found {0} usable '
                'purple-frame groups instead of the requested {1}. At least '
                'seven groups had nearby normal frames, so calibration could '
                'continue.'
                .format(marked_groups, target_groups)
            )
        elif selection_mode == 'progressive_search':
            scanned = int(quality.get('scanned_file_count', 0))
            available = int(
                quality.get('available_file_count', 0)
                or source_details.get('available_file_count', 0)
            )
            if quality.get('search_stopped_early'):
                warnings.append(
                    'No action is needed: fewer than seven ready-to-use groups '
                    'were available, so the tool checked additional saved '
                    'FITS. It found enough evidence after {0} of {1} files.'
                    .format(
                        scanned,
                        available,
                    )
                )
            else:
                warnings.append(
                    'No action is needed: fewer than seven ready-to-use groups '
                    'were available, so the tool checked all {0} suitable '
                    'saved FITS before producing this result.'.format(
                        scanned or available
                    )
                )
        elif selection_mode == 'full_retention_population_groups':
            warnings.append(
                'The current detection settings did not identify enough '
                'purple frames. The tool checked all retained FITS and found '
                'another possible purple-frame group with nearby normal frames.'
            )
        elif selection_mode == 'full_retention_detector_groups':
            warnings.append(
                'No action is needed: the tool checked all retained FITS and '
                'prepared only the recognised purple frames and their nearby '
                'normal references.'
            )

    matched_count = int(quality.get('matched_bad_count', 0))
    two_sided_count = int(quality.get('two_sided_count', 0))
    normal_count = int(quality.get('matched_normal_count', 0))
    if matched_count:
        one_sided_count = matched_count - two_sided_count
        two_sided_percent = 100.0 * two_sided_count / matched_count
        triplet_coverage_complete = (
            two_sided_percent >= TRIPLET_COVERAGE_COMPLETE_PERCENT
        )
        # Each one-sided group uses one reference and each two-sided group uses
        # two. Fewer distinct files than that total means at least one normal
        # reference was reused; comparing only against the purple-frame count
        # would miss reuse in otherwise complete groups.
        reference_use_count = matched_count + two_sided_count
        references_reused = normal_count < reference_use_count
        coverage_parts = []
        if one_sided_count == matched_count:
            coverage_parts.append(
                'all {0} purple frames had one nearby normal reference'
                .format(matched_count)
            )
        elif one_sided_count:
            remaining_text = (
                'the remaining purple frame'
                if one_sided_count == 1
                else 'the other {0} purple frames'.format(one_sided_count)
            )
            coverage_parts.append(
                '{0} of {1} purple frames had normal references before and '
                'after them; {2} had one nearby normal reference'
                .format(two_sided_count, matched_count, remaining_text)
            )
        if references_reused:
            coverage_parts.append(
                'some normal frames were used as a reference more than once'
            )
        if coverage_parts:
            coverage_text = '. '.join(
                part[:1].upper() + part[1:]
                for part in coverage_parts
            )
            result_status = (
                'Threshold evidence is usable'
                if preliminary
                else 'Calibration is valid'
            )
            if not (
                one_sided_count
                and triplet_coverage_complete
                and not references_reused
            ):
                if (
                    one_sided_count
                    and references_reused
                    and not triplet_coverage_complete
                ):
                    improvement = (
                        'more complete before/purple/after groups with '
                        'different normal frames would improve confidence'
                    )
                elif one_sided_count and not triplet_coverage_complete:
                    improvement = (
                        'more complete before/purple/after groups would '
                        'improve confidence'
                    )
                else:
                    improvement = (
                        'more different normal reference frames would improve '
                        'confidence'
                    )
                warnings.append(
                    '{0}. {1}, but {2}.'.format(
                        coverage_text,
                        result_status,
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
            'No action is needed: the tool skipped {0}. The remaining FITS '
            'still met the {1} requirements.'.format(
                _readable_join(skipped_parts),
                'threshold-analysis' if preliminary else 'calibration',
            )
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


def _friendly_rejected_file_reason(reason):
    """Translate one rejected-FITS reason into safe, actionable report text."""
    reason_text = str(reason or '')
    lowered = reason_text.lower()
    if 'contains no image data' in lowered:
        return (
            'The FITS contains no image array. Use the original camera FITS, '
            'not a metadata-only or damaged file.'
        )
    if 'decoded fits image exceeds' in lowered:
        limit = re.search(r'exceeds the (\d+) mib', lowered)
        limit_text = limit.group(1) if limit else '256'
        return (
            'The decoded image exceeds the {0} MiB safety limit. Use the '
            'original single-frame camera FITS.'.format(limit_text)
        )
    if 'two-dimensional raw16 frame' in lowered:
        return (
            'The image is not a two-dimensional RAW16 mosaic. Use an original '
            'unprocessed camera FITS rather than an RGB or stacked image.'
        )
    if 'unsigned 16-bit raw data' in lowered:
        return (
            'The image is not unsigned 16-bit RAW data. Capture or export the '
            'original ASI676MC frame as RAW16.'
        )
    if (
        'at least four rows and four columns' in lowered
        or 'even raw frame dimensions' in lowered
    ):
        return (
            'The RAW mosaic dimensions are not compatible. Use the complete '
            'original camera frame with even width and height.'
        )
    if 'missing explicit bayerpat=rggb' in lowered:
        return (
            'The FITS header does not state BAYERPAT=RGGB. Use an original '
            'ASI676MC FITS that retains its Bayer-pattern metadata.'
        )
    if 'expected rggb bayer data' in lowered:
        match = re.search(r'got\s+([^;]+)', reason_text, re.IGNORECASE)
        observed = match.group(1).strip() if match else 'another pattern'
        return (
            'The FITS is marked as {0}, not RGGB. Use unmodified ASI676MC '
            'RGGB data.'.format(observed)
        )
    if 'already repaired by asi676mc frame handling' in lowered:
        return (
            'The FITS is already marked as repaired. Use the untouched '
            'diagnostic FITS captured before repair.'
        )
    if 'exposure' in lowered and (
        'finite value greater than zero' in lowered
        or 'exposure is invalid' in lowered
    ):
        return (
            'The exposure value is missing or invalid. Use an original FITS '
            'whose header contains a positive EXPTIME or EXPOSURE value.'
        )
    if 'gain' in lowered and (
        'finite non-negative value' in lowered
        or 'gain is invalid' in lowered
    ):
        return (
            'The camera gain is missing or invalid. Use an original FITS '
            'whose header contains a non-negative GAIN value.'
        )
    if (
        'xbinning=1 and ybinning=1' in lowered
        or 'requires unbinned database fits' in lowered
    ):
        return (
            'The FITS is binned or lacks valid binning metadata. Calibration '
            'requires an original 1x1-binned frame.'
        )
    if 'requires zero bayer offsets' in lowered:
        return (
            'The FITS has a non-zero Bayer offset. Calibration requires an '
            'uncropped RGGB frame with zero Bayer offsets.'
        )
    if (
        'different or conflicting asi camera identity' in lowered
        or 'non-asi676mc camera' in lowered
    ):
        return (
            'The metadata identifies a different camera. Use FITS from the '
            'selected ASI676MC only.'
        )
    if 'bound calibration camera is not positively identified' in lowered:
        return (
            'The selected camera is not identified as an ASI676MC. Select an '
            'available ASI676MC and start a new manual upload.'
        )
    if (
        'does not explicitly identify an asi676mc camera' in lowered
        or 'not positively identified as asi676mc' in lowered
    ):
        return (
            'The FITS metadata does not identify an ASI676MC. Use the '
            'camera-bound manual upload or saved-FITS search while that '
            'ASI676MC is available and selected.'
        )
    if 'missing usable date-obs/date and filename timestamp' in lowered:
        return (
            'No usable capture time was found in the FITS header or filename. '
            'Use the original timestamped FITS so nearby frames can be paired.'
        )
    if 'incomplete saved detector signature metadata' in lowered:
        return (
            'The saved database entry lacks complete detector metadata. Try '
            'manual upload of the original FITS instead.'
        )
    if 'sampled frame has no usable green signal' in lowered:
        return (
            'The sampled image has no usable green signal. Use a normally '
            'exposed daylight frame rather than an empty or fully dark frame.'
        )
    if 'sampled frame produced a non-finite detector ratio' in lowered:
        return (
            'The image could not produce valid detector ratios. Use a '
            'normally exposed, unmodified camera FITS.'
        )
    return (
        'The FITS could not be read or did not meet the calibration evidence '
        'requirements. Try the original unprocessed camera FITS.'
    )


def _rejection_summary(message_text):
    """Return validated grouped rejection counts carried by the engine."""
    marker = 'rejection summary:'
    marker_index = message_text.lower().find(marker)
    if marker_index < 0:
        return {}
    encoded = message_text[marker_index + len(marker):].strip()
    try:
        # Cleanup failures may append a second internal clause after the JSON.
        # Decode only the leading object; the browser reports cleanup state
        # separately and should not lose the evidence-rejection explanation.
        raw_counts, _end_index = json.JSONDecoder().raw_decode(encoded)
    except (TypeError, ValueError):
        return {}
    if not isinstance(raw_counts, dict):
        return {}
    counts = {}
    for reason, count in raw_counts.items():
        try:
            count = int(count)
        except (TypeError, ValueError):
            continue
        if count > 0:
            counts[str(reason)] = count
    return counts


def _friendly_all_rejected_message(message_text):
    """Explain an all-rejected collection, retaining every known cause."""
    raw_counts = _rejection_summary(message_text)
    if not raw_counts:
        return (
            'No compatible unprocessed ASI676MC RAW16 RGGB FITS were found. '
            'Check that the files are original, unbinned RAW16 RGGB camera '
            'FITS with valid exposure, gain, timestamp, and camera metadata.'
        )
    grouped = {}
    for reason, count in raw_counts.items():
        friendly = _friendly_rejected_file_reason(reason)
        grouped[friendly] = grouped.get(friendly, 0) + count
    total = sum(grouped.values())
    opening = (
        'The selected FITS could not be used.'
        if total == 1
        else 'None of the {0} selected FITS could be used.'.format(total)
    )
    if len(grouped) == 1:
        detail = next(iter(grouped))
        label = 'Reason' if total == 1 else 'Reason for all {0}'.format(total)
        return '{0} {1}: {2}'.format(opening, label, detail)
    details = []
    for friendly, count in sorted(grouped.items(), key=lambda item: -item[1]):
        details.append('{0}: {1}'.format(
            _counted_item(count, 'file'),
            friendly,
        ))
    return '{0} Reasons: {1}'.format(opening, ' '.join(details))


def _friendly_threshold_analysis_failure(message_text):
    """Explain why detector-ratio population discovery was unsafe."""
    lowered = message_text.lower()
    minimum = re.search(r'at least (\d+) compatible fits', lowered)
    if minimum:
        return (
            'Fewer than {0} compatible files remained. Include at least seven '
            'normal and seven purple frames.'.format(minimum.group(1))
        )
    if 'non-finite or non-positive values' in lowered:
        return (
            'Some files did not produce valid detector ratios. Use normally '
            'exposed, unmodified FITS.'
        )
    if 'do not vary in all three detector ratios' in lowered:
        return (
            'The files do not show two distinguishable groups across all '
            'three detector measurements. Include genuine purple and normal '
            'frames from the same camera.'
        )
    if (
        'do not form two stable populations' in lowered
        or 'possible populations contain' in lowered
        or 'higher-ratio population is not higher' in lowered
        or 'fall in the lower-ratio population' in lowered
    ):
        return (
            'The measured ratios do not form two clean normal and purple '
            'groups. Check the selected files and add clearer examples of both.'
        )
    if 'does not have the required clean gap' in lowered:
        label = message_text.split(' does not ', 1)[0].strip()
        return (
            'The {0} measurements do not cleanly separate the two possible '
            'groups. Add clearer normal and purple examples.'.format(
                label or 'detector',
            )
        )
    if 'configured thresholds already lie inside every observed gap' in lowered:
        return (
            'The current thresholds already separate the two measured groups, '
            'so threshold changes do not explain the detector result. Confirm '
            'that the higher-ratio files show the actual purple-frame fault.'
        )
    if 'matched purple frames found' in lowered:
        return _friendly_failure_message(message_text)
    if 'no compatible nearby normal' in lowered:
        return (
            'Some likely purple frames have no compatible normal frame nearby. '
            'Include complete good/purple/good sequences.'
        )
    if 'normal/purple ratio' in lowered:
        return (
            'There are too few distinct normal reference frames. Include at '
            'least one different nearby normal frame per purple frame.'
        )
    if 'cover only one exposure' in lowered:
        return (
            'The evidence covers only one exposure. Include frames from at '
            'least two exposure settings.'
        )
    return (
        'The measured ratios did not support a safe threshold suggestion. '
        'Include clearer normal and purple examples with adjacent references.'
    )


def _friendly_failure_message(message):
    """Translate calibration-engine failures into safe, actionable UI copy."""
    message_text = str(message or '')
    lowered = message_text.lower()
    # Accept the current wording and older persisted task failures so an
    # interrupted session still receives the same useful explanation after an
    # upgrade.
    matched_count = re.search(
        r'(\d+) matched (?:purple|bad) frames found',
        lowered,
    )
    if 'complete retained database archive' in lowered:
        if 'no eligible asi676mc fits' in lowered:
            return (
                'Saved-FITS discovery checked the complete retention period '
                'but found no eligible local ASI676MC FITS. Check FITS saving '
                'and retention, then try again.'
            )
        if 'no safe purple/normal population' in lowered:
            return (
                'Saved-FITS discovery checked the complete retention period '
                'but the detector ratios did not form a safe purple/normal '
                'population. No settings were changed.'
            )
        return (
            'Saved-FITS discovery checked the complete retention period but '
            'did not find seven purple frames with compatible nearby normal '
            'evidence. No settings were changed.'
        )
    if (
        'selected for this database search has changed' in lowered
        or 'selected database camera is no longer an asi676mc' in lowered
    ):
        return (
            'The camera selected for saved-FITS discovery changed before the '
            'background search started. Select the ASI676MC again and start a '
            'new search.'
        )
    if 'no compatible raw16 rggb fits files found' in lowered:
        return _friendly_all_rejected_message(message_text)
    if matched_count:
        return (
            'Only {0} purple frames had a compatible nearby normal FITS; at '
            'least seven are required.'.format(matched_count.group(1))
        )
    if (
        'both normal and purple frames are required' in lowered
        or 'both normal and bad frames are required' in lowered
    ):
        return (
            'The collection did not contain both recognisable purple frames '
            'and normal frames. Check the selected FITS and try again.'
        )
    if (
        'matched normal/purple ratio' in lowered
        or 'matched normal/bad ratio' in lowered
    ):
        return (
            'There were not enough different normal reference frames. Provide '
            'at least one distinct compatible normal frame for each purple frame.'
        )
    if 'detected purple frames have no compatible nearby normal' in lowered:
        return (
            'Some detected purple frames have no compatible normal FITS '
            'nearby. Include complete good/purple/good sequences or increase '
            'the maximum separation only if those frames belong together.'
        )
    if 'cover only one exposure' in lowered:
        return (
            'The matched purple frames use only one exposure. Include data from '
            'at least two exposure settings.'
        )
    if (
        'more than one explicit camera identity' in lowered
        or 'different explicit asi camera' in lowered
        or 'all evidence must explicitly identify asi676mc' in lowered
    ):
        return (
            'Files from more than one camera were detected. Use FITS from this '
            'ASI676MC only.'
        )
    if 'lack the required asi676mc raw16 rggb' in lowered:
        return (
            'Some evidence failed the final compatibility check. Use original '
            'ASI676MC RAW16 RGGB FITS with 1x1 binning, zero Bayer offsets, and '
            'valid exposure and gain metadata.'
        )
    if 'no fits matched the configured purple-frame detector' in lowered:
        return (
            'No FITS matched the configured purple-frame detector. Confirm '
            'that the collection contains untouched purple frames. If it '
            'does, this camera may need different detection thresholds in '
            'Image Settings before calibration can identify the failures.'
        )
    if 'no fits remained classified as normal' in lowered:
        return (
            'Every compatible FITS matched the configured purple-frame '
            'detector, so no normal references were available. Check the '
            'collection and review the detection thresholds in Image Settings.'
        )
    if 'automatic threshold analysis could not make a safe suggestion' in lowered:
        detail = message_text.split(':', 1)[-1].strip()
        return (
            'The configured detector did not find enough usable purple and '
            'normal frames. {0} No settings were changed.'.format(
                _friendly_threshold_analysis_failure(detail)
            )
        )
    # These engine messages contain only measured ratios and setting names, so
    # they are safe and more useful to show verbatim than a generic summary.
    if (
        lowered.startswith('configured combined purple/green ratio threshold')
        or lowered.startswith('configured red-side ratio threshold')
        or lowered.startswith('configured blue-side ratio threshold')
    ):
        return message_text
    if (
        'misclassifies at least one supplied normal frame' in lowered
        or 'misses at least one supplied purple frame' in lowered
        or 'misses at least one supplied bad frame' in lowered
        or 'overlapping normal and purple ranges' in lowered
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
            'highlights. Add brighter daylight pairs or good/purple/good groups.'
        )
    if 'has usable samples in only' in lowered:
        return (
            'Too few stable pixels could be compared across the matched '
            'frames. Try clearer daylight data with less cloud or scene change.'
        )
    if 'estimate' in lowered and 'outside the plausible asi676mc range' in lowered:
        return (
            'The fitted colour gain is outside the safe ASI676MC range. Check '
            'that the files show the purple row-shift fault and use cleaner '
            'good/purple/good daylight sequences.'
        )
    if 'varies too much between pairs' in lowered:
        return (
            'The fitted colour gain changes too much between frame groups. '
            'Use one ASI676MC and collect cleaner sequences with less cloud, '
            'motion, or exposure change inside each group.'
        )
    if 'best clipped-highlight fit score' in lowered:
        return (
            'The bright-highlight fit was not consistent enough to use safely. '
            'Collect more stable daylight good/purple/good sequences with '
            'visible highlights.'
        )
    if (
        'too few stable samples to compare' in lowered
        or 'too few samples for the gain-only phase countercheck' in lowered
        or 'invalid gain-only phase countercheck' in lowered
    ):
        return (
            'Too few stable scene pixels remained for the final comparison. '
            'Use clearer daylight sequences with less cloud or movement.'
        )
    if (
        'repaired frame remains too different' in lowered
        or 'repair does not materially improve agreement' in lowered
        or 'evidence does not confirm the asi676mc one-row phase shift' in lowered
    ):
        return (
            'The selected high-ratio frames do not behave like the ASI676MC '
            'one-row purple-frame fault after repair. Check the evidence and '
            'use untouched purple frames with close normal references.'
        )
    if 'astropy could not be imported' in lowered:
        return (
            'FITS support is unavailable on this installation. Install the '
            'indi-allsky FITS dependencies, restart the services, and try again.'
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
            'Calibration could not start because the calibration service is '
            'unavailable. Wait a minute and try again. If this repeats, '
            'restart indi-allsky or include this message when reporting the issue.'
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
        'An unexpected error occurred while checking the FITS. Try again with '
        'the original unprocessed FITS. If the problem repeats, include this '
        'message and the selected input method when reporting the issue.'
    )


def task_failure_message(message, limit=255):
    """Return useful calibration failure text for the short task-status field."""
    friendly = _friendly_failure_message(message)
    if len(friendly) <= limit:
        return friendly
    fallback = (
        'Calibration could not use the selected evidence. Open Tools > '
        'ASI676MC Calibration for the complete grouped reasons and next steps.'
    )
    return fallback[:limit]


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


def _local_timezone():
    """Return the system timezone used by the rest of the indi-allsky UI."""
    return datetime.now().astimezone().tzinfo


def _format_report_timestamp(value):
    """Turn an internal UTC timestamp into unambiguous local report time."""
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        local_time = parsed.astimezone(_local_timezone())
        timezone_name = local_time.tzname() or 'local time'
        utc_offset = local_time.strftime('%z')
        if len(utc_offset) == 5:
            utc_offset = '{0}:{1}'.format(utc_offset[:3], utc_offset[3:])
        if utc_offset:
            timezone_name = '{0} (UTC{1})'.format(
                timezone_name,
                utc_offset,
            )
        return '{0} {1}'.format(
            local_time.strftime('%Y-%m-%d %H:%M:%S'),
            timezone_name,
        )
    except (TypeError, ValueError):
        return str(value or 'Unknown')


def _format_report_filename_timestamp(value):
    """Format an internal timestamp for a sortable local report filename."""
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(_local_timezone()).strftime('%Y-%m-%d_%H-%M-%S')


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


def format_threshold_suggestion_report(payload, manifest):
    """Build the report for a safe, preliminary detector-threshold result."""
    quality = payload['quality']
    source_details = manifest.get('source') or {}
    lines = [
        'indi-allsky ASI676MC purple-frame threshold analysis report',
        '=' * 59,
        'Status: Preliminary threshold suggestion',
        'Generated: {0}'.format(_format_report_timestamp(
            payload.get('generated_utc') or manifest.get('completed_utc')
        )),
    ]

    _append_report_section(lines, 'Analysis result')
    if quality.get('detected_bad_count', 0) >= 7:
        detector_summary = (
            'The combined detector identified enough purple frames, but at '
            'least one individual detection threshold lay outside its clean '
            'normal/purple gap.'
        )
    else:
        detector_summary = (
            'The configured detector did not identify enough purple and '
            'normal frames for calibration.'
        )
    _append_report_paragraph(
        lines,
        detector_summary + ' Even so, each of the three measured ratios '
        'separated into two clean, consistently ordered populations. The '
        'higher-ratio '
        'population also had compatible adjacent normal references.',
    )
    _append_report_paragraph(
        lines,
        'No repair constants were derived and no settings were changed during '
        'analysis. If the evidence matches the expected purple-frame failure, '
        'a user who can save settings on the Config page may select Apply '
        'thresholds and reload on the result page. Alternatively, enter only '
        'the fields marked Change recommended in Image Settings. Then reset '
        'the tool and run calibration again.',
    )

    _append_report_section(lines, 'Detection threshold suggestions')
    rows = []
    for item in payload['threshold_suggestions']:
        safe_interval = '>{0:.3f} and <={1:.3f}'.format(
            item['normal_max'],
            item['purple_min'],
        )
        assessment = (
            'Change recommended'
            if item['change_recommended']
            else 'Current value is already safe'
        )
        rows.append((
            item['label'],
            _format_report_value(item['current']),
            _format_report_value(item['suggested']),
            safe_interval,
            assessment,
        ))
    widths = [
        max(len(header), *(len(row[index]) for row in rows))
        for index, header in enumerate((
            'Setting', 'Current', 'Suggested', 'Observed safe interval',
        ))
    ]
    table_format = '{{0:<{0}}}  {{1:>{1}}}  {{2:>{2}}}  {{3:<{3}}}  {{4}}'.format(
        *widths
    )
    lines.extend((
        '',
        table_format.format(
            'Setting', 'Current', 'Suggested', 'Observed safe interval',
            'Assessment',
        ),
        table_format.format(
            '-' * widths[0], '-' * widths[1], '-' * widths[2],
            '-' * widths[3], '-' * len('Assessment'),
        ),
    ))
    lines.extend(table_format.format(*row) for row in rows)

    _append_report_section(lines, 'Evidence used')
    evidence_lines = (
        ('FITS identified by the configured detector',
         quality.get('detected_bad_count', 0)),
        ('FITS in likely purple population', quality['likely_purple_count']),
        ('FITS in likely normal population', quality['likely_normal_count']),
        ('Likely purple frames with a normal reference', quality['pair_count']),
        ('Likely purple frames skipped without a reference',
         quality.get('unmatched_bad_count', 0)),
        ('Distinct normal references', quality['unique_good_count']),
        ('Good/purple/good groups', '{0} of {1}'.format(
            quality['two_sided_count'], quality['pair_count']
        )),
        ('Exposure settings represented', len(quality['exposure_levels'])),
        ('FITS files unreadable or unusable',
         quality.get('rejected_file_count', 0)),
    )
    evidence_width = max(len(label) for label, _value in evidence_lines)
    lines.extend(
        '{0:<{1}}  {2}'.format(label + ':', evidence_width + 1, value)
        for label, value in evidence_lines
    )
    lines.append('Maximum matching separation: {0:g} seconds'.format(
        float(manifest.get('max_pair_seconds', 0))
    ))

    _append_report_section(lines, 'Observed ratio ranges')
    _append_report_paragraph(
        lines,
        'A safe threshold is greater than the likely-normal maximum and no '
        'greater than the likely-purple minimum. Each reported range has a '
        'clean gap. The tool does not suggest a threshold when the populations '
        'overlap.',
    )
    for item in payload['threshold_suggestions']:
        values = payload['signature_ranges'][item['metric']]
        lines.append(
            '{0}: likely normal {1:.3f}-{2:.3f}; likely purple '
            '{3:.3f}-{4:.3f}'.format(
                item['label'],
                values['good_min'],
                values['good_max'],
                values['bad_min'],
                values['bad_max'],
            )
        )

    population_evidence = payload.get('population_evidence') or ()
    if population_evidence:
        _append_report_section(lines, 'Population examples to verify')
        _append_report_paragraph(
            lines,
            'Review these filenames and capture times before saving threshold '
            'changes. The higher-ratio group must be the actual ASI676MC '
            'purple-frame failure, not a second ordinary lighting regime.',
        )
        for item in population_evidence:
            lines.append(
                '{0} | {1} | {2} | ratios {3:.3f}/{4:.3f}/{5:.3f}'.format(
                    item.get('population', 'Unknown population'),
                    _format_report_timestamp(item.get('timestamp_utc')),
                    _original_report_filename(
                        item.get('name'),
                        manifest.get('files'),
                    ),
                    float(item.get('purple_ratio', 0.0)),
                    float(item.get('red_side_ratio', 0.0)),
                    float(item.get('blue_side_ratio', 0.0)),
                )
            )

    _append_report_section(lines, 'Evidence source')
    source_kind = source_details.get('kind')
    selected_count = source_details.get(
        'selected_file_count',
        len(manifest.get('files', ())),
    )
    if source_kind == 'database':
        lines.extend((
            'Method: Saved FITS search on the ASI676MC Calibration page',
            'Camera: {0}'.format(source_details.get('camera_name', 'Unknown')),
            'Selection preference: Newest compatible FITS with required '
            'exposure diversity',
            'Target purple-frame groups: {0}'.format(
                source_details.get('requested_group_count', 0)
            ),
            'Selection path: {0}'.format(
                _database_selection_text(
                    source_details.get('selection_mode')
                )
            ),
            'Usable marked groups found: {0}'.format(
                source_details.get('selected_marked_group_count', 0)
            ),
            _database_search_coverage_line(source_details),
            'FITS inspected: {0} of {1}'.format(
                payload.get('quality', {}).get(
                    'scanned_file_count',
                    selected_count,
                ),
                selected_count,
            ),
            'Eligible retained FITS available: {0}'.format(
                source_details.get('available_file_count', selected_count)
            ),
            'Retained FITS searched: {0}'.format(
                source_details.get(
                    'archive_scanned_file_count',
                    source_details.get('available_file_count', selected_count),
                )
            ),
            'Legacy FITS directly inspected: {0}'.format(
                source_details.get('legacy_fits_inspected_count', 0)
            ),
            'Legacy FITS ratio caches written: {0}'.format(
                source_details.get('legacy_signature_cached_count', 0)
            ),
            'Saved ratio metadata available: {0}'.format(
                source_details.get('metadata_signature_count', 0)
            ),
            'Selected FITS skipped during staging: {0}'.format(
                source_details.get('staging_skipped_file_count', 0)
            ),
            'Post-repair standard FITS excluded: {0}'.format(
                source_details.get('excluded_repaired_standard_count', 0)
            ),
            'Duplicate standard FITS excluded: {0}'.format(
                source_details.get('excluded_duplicate_standard_count', 0)
            ),
            'FITS retention cutoff: {0} ({1})'.format(
                source_details.get('retention_cutoff', 'Unknown'),
                _counted_item(source_details.get('retention_days', 0), 'day')
                if isinstance(source_details.get('retention_days'), int)
                else 'Unknown retention',
            ),
        ))
        if str(source_details.get('selection_mode') or '').startswith(
            'full_retention_'
        ):
            source_explanation = (
                'The background search inspected the complete retained '
                'archive. Saved ratio metadata avoided unnecessary image '
                'decoding; legacy FITS were inspected directly. Only the '
                'final purple/reference groups were staged, and newly '
                'measured legacy ratios were cached on their database rows. '
                'This analysis '
                'removed only temporary staging links; the original saved '
                'FITS remain unchanged.'
            )
        else:
            source_explanation = (
                'When at least seven complete database-marked groups are '
                'available, the tool uses them as a compact evidence set. '
                'Otherwise, population analysis uses measured FITS ratios and '
                'may continue beyond the initial search target. This analysis '
                'removed only temporary staging links; the original saved '
                'FITS remain unchanged.'
            )
        _append_report_paragraph(lines, source_explanation)
    elif source_kind == 'upload':
        lines.extend((
            'Method: Manual FITS upload on the ASI676MC Calibration page',
            'FITS inspected: {0}'.format(selected_count),
        ))
        _append_report_paragraph(
            lines,
            'The private uploaded copies were removed after analysis. The '
            'original files on the user\'s computer were never modified.',
        )

    result_summary = _threshold_suggestion_summary(payload)
    report_notes = _result_warnings(
        result_summary['quality'],
        source_details,
        report_context=True,
        threshold_assessment=payload.get('threshold_assessment'),
    )
    if report_notes:
        _append_report_section(lines, 'Analysis notes')
        for note in report_notes:
            _append_report_paragraph(lines, note, prefix='- ')

    rejected_files = payload.get('rejected_files') or ()
    if rejected_files:
        _append_report_section(lines, 'Rejected FITS details')
        for rejected in rejected_files:
            _append_report_paragraph(
                lines,
                '{0}: {1}'.format(
                    _original_report_filename(
                        rejected.get('name'),
                        manifest.get('files'),
                    ),
                    _friendly_rejected_file_reason(rejected.get('reason')),
                ),
                prefix='- ',
            )

    _append_report_section(lines, 'About this report')
    _append_report_paragraph(
        lines,
        'This is a human-readable record from Tools > ASI676MC Calibration. '
        'It is not a configuration file and cannot be imported. Threshold '
        'suggestions are intentionally separate from the seven repair values; '
        'saving them never activates repair or replaces repair constants.',
    )
    return '\n'.join(lines).rstrip() + '\n'


def format_integrated_report(payload, manifest):
    """Build the report downloaded from the authenticated calibration page.

    Building this report from structured engine output and private session data
    lets it name the real evidence source, compare the result with the starting
    configuration, explain cleanup, and avoid exposing the staging directory.
    """
    if payload.get('outcome') == 'threshold_suggestion':
        return format_threshold_suggestion_report(payload, manifest)

    quality = payload['quality']
    derived_settings = payload['derived_settings']
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
        'The derived values passed the final safety checks. Final validation '
        'repaired all {0} purple frames and left all {1} distinct normal '
        'reference frames unchanged.'.format(
            quality.get('validated_bad_repairs', 0),
            quality.get('validated_normal_frames', 0),
        ),
    )
    _append_report_paragraph(
        lines,
        'The calibration did not change the indi-allsky configuration. A user '
        'who can save settings on the Config page can apply the result from '
        'the calibration page.',
    )

    _append_report_section(lines, 'Recommended calibration values')
    _append_report_paragraph(
        lines,
        'Review these values under Tools > ASI676MC Calibration. A user who '
        'can save settings on the Config page can select Apply values and '
        'reload. Alternatively, enter the values manually under Config > '
        'Image > ASI676MC RAW16 Purple-frame Handling.',
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
            'At the start of calibration, the derived values matched all seven '
            'configured values, so no update was necessary.'
        ),
        'equivalent': (
            'At the start of calibration, the differences between the derived '
            'and configured values were too small to produce a visible change.'
        ),
        'different': (
            'At the start of calibration, one or more derived values differed '
            'enough from the configured values to meaningfully change repaired '
            'images.'
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
            'Selection preference: Newest compatible FITS with required '
            'exposure diversity',
            'Target purple-frame groups: {0}'.format(
                source_details.get('requested_group_count', 0)
            ),
            'Selection path: {0}'.format(
                _database_selection_text(
                    source_details.get('selection_mode')
                )
            ),
            'Usable marked groups found: {0}'.format(
                source_details.get('selected_marked_group_count', 0)
            ),
            _database_search_coverage_line(source_details),
            'FITS inspected: {0} of {1}'.format(
                quality.get('scanned_file_count', selected_file_count),
                selected_file_count,
            ),
            'Eligible retained FITS available: {0}'.format(
                source_details.get(
                    'available_file_count',
                    selected_file_count,
                )
            ),
            'Retained FITS searched: {0}'.format(
                source_details.get(
                    'archive_scanned_file_count',
                    source_details.get(
                        'available_file_count',
                        selected_file_count,
                    ),
                )
            ),
            'Legacy FITS directly inspected: {0}'.format(
                source_details.get('legacy_fits_inspected_count', 0)
            ),
            'Legacy FITS ratio caches written: {0}'.format(
                source_details.get('legacy_signature_cached_count', 0)
            ),
            'Saved ratio metadata available: {0}'.format(
                source_details.get('metadata_signature_count', 0)
            ),
            'Selected FITS skipped during staging: {0}'.format(
                source_details.get('staging_skipped_file_count', 0)
            ),
            'Post-repair standard FITS excluded: {0}'.format(
                source_details.get('excluded_repaired_standard_count', 0)
            ),
            'Duplicate standard FITS excluded: {0}'.format(
                source_details.get('excluded_duplicate_standard_count', 0)
            ),
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
        if str(source_details.get('selection_mode') or '').startswith(
            'full_retention_'
        ):
            source_explanation = (
                'The background search inspected the complete retained '
                'archive. Saved ratio metadata avoided unnecessary image '
                'decoding; legacy FITS were inspected directly. Only the '
                'final purple/reference groups were staged, and newly '
                'measured legacy ratios were cached on their database rows. '
                'This calibration '
                'removed only temporary staging links. The original saved '
                'FITS remain unchanged and continue to follow normal FITS '
                'retention.'
            )
        else:
            source_explanation = (
                'When at least seven complete database-marked groups are '
                'available, the tool uses them as a compact evidence set. '
                'Otherwise, it classifies retained FITS by their measured '
                'ratios and may continue beyond the initial search target. '
                'This calibration removed only temporary staging links. The '
                'original saved FITS remain unchanged and continue to follow '
                'normal FITS retention.'
            )
        _append_report_paragraph(lines, source_explanation)
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
    camera_identity_parts = []
    if camera_names:
        camera_identity_parts.append(
            'explicit FITS headers ({0})'.format(', '.join(camera_names))
        )
    bound_upload_count = int(
        quality.get('bound_session_camera_count', 0)
    )
    if bound_upload_count:
        camera_identity_parts.append(
            'selected camera binding for {0}'.format(
                _counted_item(bound_upload_count, 'uploaded file')
            )
        )
    database_identity_count = int(
        quality.get('bound_database_camera_count', 0)
    ) + int(quality.get('database_metadata_camera_count', 0))
    if database_identity_count:
        camera_identity_parts.append(
            'camera-bound database records for {0}'.format(
                _counted_item(database_identity_count, 'saved file')
            )
        )
    lines.append('Camera identity evidence: {0}'.format(
        _readable_join(camera_identity_parts)
        if camera_identity_parts
        else 'Not recorded'
    ))
    lines.append('Maximum matching separation: {0:g} seconds'.format(
        float(manifest.get('max_pair_seconds', 0))
    ))

    _append_report_section(lines, 'Result notes')
    report_notes = _result_warnings(
        result_summary['quality'],
        source_details,
        report_context=True,
        threshold_assessment=payload.get('threshold_assessment'),
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
                    _friendly_rejected_file_reason(rejected.get('reason')),
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
            'The ranges shown below do not overlap. Each detection threshold '
            'recorded for this run lies within the clean gap between its '
            'normal and purple ranges.',
        )
        signature_labels = {
            'purple_ratio': 'Combined purple/green ratio',
            'red_side_ratio': 'Red-side ratio',
            'blue_side_ratio': 'Blue-side ratio',
        }
        signature_threshold_names = {
            'purple_ratio': 'PURPLE_RATIO_THRESHOLD',
            'red_side_ratio': 'RED_SIDE_RATIO_THRESHOLD',
            'blue_side_ratio': 'BLUE_SIDE_RATIO_THRESHOLD',
        }
        threshold_assessment = {
            item.get('metric'): item
            for item in payload.get('threshold_assessment', ())
        }
        for metric, values in signature_ranges.items():
            assessment = threshold_assessment.get(metric)
            assessment_text = ''
            if assessment:
                assessment_text = '; gap midpoint {0:.3f}; margin {1}'.format(
                    assessment['suggested'],
                    'narrow - collect more data before changing'
                    if assessment.get('marginal')
                    else 'comfortable',
                )
            range_text = (
                '{0}: normal {1:.3f}-{2:.3f}; configured threshold {3:.3f}; '
                'purple {4:.3f}-{5:.3f}{6}'
            ).format(
                signature_labels.get(metric, metric),
                values['good_min'],
                values['good_max'],
                float(configured_at_start.get(
                    signature_threshold_names[metric],
                    0.0,
                )),
                values['bad_min'],
                values['bad_max'],
                assessment_text,
            )
            lines.append(range_text)

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
        'user-controlled and are never changed by calibration itself.',
    )
    return '\n'.join(lines).rstrip() + '\n'


def run_calibration_session(
    session_id,
    storage_root=None,
    database_loader=None,
    database_signature_saver=None,
):
    """Run the calibration engine for one queued web session."""
    session_dir = _session_dir(session_id, storage_root)
    worker_token = uuid.uuid4().hex
    with _file_lock(_session_lock_path(session_dir)):
        _loaded_dir, manifest = get_session(
            session_id,
            storage_root=storage_root,
        )
        # Only the first worker may claim a queued session. Accepting running
        # here allowed duplicate jobs to fit and overwrite the same result.
        if manifest.get('status') != 'queued':
            raise CalibrationSessionError('calibration session is not queued')
        if _cancel_marker_path(session_dir).exists():
            raise CalibrationCancelled('calibration was cancelled before it started')
        manifest['status'] = 'running'
        manifest['started_utc'] = _utc_now_text()
        manifest['heartbeat_utc'] = manifest['started_utc']
        manifest['worker_token'] = worker_token
        _write_manifest(session_dir, manifest)

    def active_manifest():
        """Re-read and validate this worker's claim under the session lock."""
        current = _read_manifest(session_dir)
        if (
            _cancel_marker_path(session_dir).exists()
            or current.get('status') == 'cancel_requested'
        ):
            raise CalibrationCancelled('calibration was cancelled')
        if (
            current.get('status') != 'running'
            or current.get('worker_token') != worker_token
        ):
            raise CalibrationSessionError('calibration worker claim was lost')
        return current

    upload_dir = session_dir.joinpath('uploads')
    captured_output = io.StringIO()
    try:
        # Import the numerical layer only in the background worker. Web views
        # can manage uploads and status without loading NumPy or FITS support.
        from . import asi676mc_calibration_engine

        source_details = manifest.get('source') or {}
        trusted_camera_name = None
        if source_details.get('kind') == 'upload':
            trusted_camera_name = str(
                (manifest.get('camera') or {}).get('name') or ''
            ).strip() or None
        last_progress = dict(manifest.get('progress') or {})

        def record_progress(progress):
            """Publish coarse worker progress without rewriting per frame."""
            nonlocal last_progress
            progress = dict(progress)
            processed = int(progress.get('processed_files', 0))
            phase_changed = progress.get('phase') != last_progress.get('phase')
            if (
                not phase_changed
                and processed % PROGRESS_MANIFEST_INTERVAL_FILES
                and (
                    processed != int(progress.get('total_files', 0))
                )
            ):
                return
            with _file_lock(_session_lock_path(session_dir)):
                current = active_manifest()
                current['progress'] = progress
                current['heartbeat_utc'] = _utc_now_text()
                _write_manifest(session_dir, current)
            last_progress = progress

        def cancellation_checkpoint():
            """Check cancellation during non-file-loop analysis phases."""
            with _file_lock(_session_lock_path(session_dir)):
                active_manifest()

        if (
            source_details.get('kind') == 'database'
            and source_details.get('selection_mode')
            == 'background_full_retention'
            and not manifest.get('files')
        ):
            if database_loader is None:
                raise CalibrationSessionError(
                    'database calibration requires a retained-FITS loader'
                )
            catalog = database_loader(source_details, record_progress)
            legacy_signature_updates = {}
            selected_records, discovery = (
                discover_full_retention_database_evidence(
                    catalog.get('fits_records', ()),
                    catalog.get('bad_frames', ()),
                    source_details.get('requested_group_count', 20),
                    manifest['max_pair_seconds'],
                    manifest.get('settings'),
                    progress_callback=record_progress,
                    cancel_callback=cancellation_checkpoint,
                    signature_callback=(
                        lambda record_id, signature:
                        legacy_signature_updates.__setitem__(
                            int(record_id),
                            dict(signature),
                        )
                    ),
                )
            )
            if database_signature_saver and legacy_signature_updates:
                try:
                    database_signature_saver(
                        source_details,
                        legacy_signature_updates,
                    )
                    discovery['legacy_signature_cached_count'] = len(
                        legacy_signature_updates
                    )
                except Exception:
                    # Caching makes later searches faster but must never turn
                    # otherwise valid evidence into a failed calibration.
                    logger.exception(
                        'Unable to cache ASI676MC legacy FITS signatures'
                    )
                    discovery['legacy_signature_cache_failed'] = True
            stage_database_files_for_worker(
                session_id,
                worker_token,
                selected_records,
                storage_root=storage_root,
            )
            with _file_lock(_session_lock_path(session_dir)):
                manifest = active_manifest()
                updated_source = dict(manifest.get('source') or source_details)
                updated_source.update(catalog.get('source_details') or {})
                updated_source.update(discovery)
                manifest['source'] = updated_source
                manifest['heartbeat_utc'] = _utc_now_text()
                _write_manifest(session_dir, manifest)
            source_details = manifest.get('source') or {}

        metadata_by_name = {
            entry['name']: entry
            for entry in manifest.get('files', ())
            if entry.get('database_id') is not None
        }

        with redirect_stdout(captured_output):
            payload = asi676mc_calibration_engine.calibrate_folder(
                upload_dir,
                settings=manifest.get('settings'),
                recursive=False,
                max_pair_seconds=manifest['max_pair_seconds'],
                allow_unmatched=True,
                metadata_by_name=metadata_by_name,
                progress_callback=record_progress,
                checkpoint_callback=cancellation_checkpoint,
                progressive=(
                    source_details.get('selection_mode')
                    == 'progressive_search'
                ),
                initial_scan_count=source_details.get(
                    'initial_scan_file_count',
                    14,
                ),
                trusted_camera_name=trusted_camera_name,
            )

        with _file_lock(_session_lock_path(session_dir)):
            manifest = active_manifest()
            manifest['heartbeat_utc'] = _utc_now_text()
            _write_manifest(session_dir, manifest)

        # The current engine always supplies scan audit fields. Defaults keep
        # retained results and test/dry-run engines readable without making
        # the web session depend on a single engine payload revision.
        payload_quality = payload.setdefault('quality', {})
        payload_quality.setdefault(
            'scanned_file_count',
            len(manifest.get('files', ())),
        )
        payload_quality.setdefault(
            'available_file_count',
            len(manifest.get('files', ())),
        )
        payload_quality.setdefault('search_stopped_early', False)

        original_names = {
            entry.get('name'): entry.get('original_name') or entry.get('name')
            for entry in manifest.get('files', ())
        }
        for evidence_item in payload.get('population_evidence', ()):
            evidence_item['name'] = original_names.get(
                evidence_item.get('name'),
                evidence_item.get('name'),
            )

        if payload.get('outcome') == 'threshold_suggestion':
            summary = _threshold_suggestion_summary(payload)
        else:
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
        if manifest.get('camera'):
            result['camera'] = dict(manifest['camera'])
        result['warnings'] = _result_warnings(
            result['quality'],
            source_details,
            threshold_assessment=result.get('threshold_assessment'),
        )
        # The downloadable report is built here so it can describe session
        # provenance, configuration comparison, cleanup, and UI actions without
        # exposing the private staging path used by the numerical engine.
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
        # removes only the session's hard links/private copies and leaves the
        # database-owned FITS untouched.
        with _file_lock(_session_lock_path(session_dir)):
            manifest = active_manifest()
            _remove_upload_dir(session_dir)
            manifest['status'] = 'success'
            manifest['completed_utc'] = result['completed_utc']
            manifest['sources_deleted_utc'] = _utc_now_text()
            manifest['error'] = None
            manifest['progress'] = {
                'phase': 'complete',
                'processed_files': result['quality'].get(
                    'scanned_file_count',
                    len(manifest.get('files', [])),
                ),
                'total_files': result['quality'].get(
                    'available_file_count',
                    len(manifest.get('files', [])),
                ),
                'detected_bad_count': result['quality'].get(
                    'matched_bad_count',
                    result['quality'].get('detected_bad_count', 0),
                ),
            }
            manifest.pop('worker_token', None)
            _write_manifest(session_dir, manifest)
        return result
    except CalibrationCancelled:
        for result_name in (
            'result.json',
            'asi676mc_calibration_report.txt',
        ):
            try:
                session_dir.joinpath(result_name).unlink()
            except FileNotFoundError:
                pass
        _remove_upload_dir(session_dir)
        with _file_lock(_session_lock_path(session_dir)):
            manifest = _read_manifest(session_dir)
            manifest['status'] = 'cancelled'
            manifest['completed_utc'] = _utc_now_text()
            manifest['sources_deleted_utc'] = _utc_now_text()
            manifest['error'] = None
            manifest.pop('worker_token', None)
            _write_manifest(session_dir, manifest)
        return None
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
        with _file_lock(_session_lock_path(session_dir)):
            manifest = _read_manifest(session_dir)
            cancelled = (
                _cancel_marker_path(session_dir).exists()
                or manifest.get('status') == 'cancel_requested'
            )
            manifest['status'] = 'cancelled' if cancelled else 'failed'
            manifest['completed_utc'] = _utc_now_text()
            if cleanup_error is None:
                manifest['sources_deleted_utc'] = _utc_now_text()
                manifest['error'] = None if cancelled else str(error)
            else:
                manifest['error'] = (
                    '{0}; private calibration input cleanup also failed: {1}'
                ).format(error, cleanup_error)
            manifest.pop('worker_token', None)
            _write_manifest(session_dir, manifest)
        raise


def get_status(session_id, owner, storage_root=None):
    """Return the browser-safe status/result for an owned session."""
    session_dir = _session_dir(session_id, storage_root)
    with _file_lock(_session_lock_path(session_dir)):
        _loaded_dir, manifest = get_session(session_id, owner, storage_root)
        manifest = _recover_stale_session_unlocked(session_dir, manifest)
    source = manifest.get('source') or {}
    response = {
        'session_id': session_id,
        'status': manifest['status'],
        'file_count': len(manifest.get('files', [])),
        'total_bytes': manifest.get('total_bytes', 0),
        'task_id': manifest.get('task_id'),
        'progress': manifest.get('progress'),
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
            threshold_assessment=result.get('threshold_assessment'),
        )
        response['result'] = result
    return response


def get_completed_result(session_id, owner, storage_root=None):
    """Return the safe subset an authorized user may save to configuration.

    A complete calibration supplies all seven repair constants. Preliminary
    threshold discovery supplies only detector fields explicitly marked for a
    change; it can never smuggle repair constants or operational switches into
    the configuration save path.
    """
    session_dir, manifest = get_session(session_id, owner, storage_root)
    if manifest.get('status') != 'success':
        raise CalibrationSessionError('calibration has not completed successfully')
    result_path = session_dir.joinpath('result.json')
    try:
        result = json.loads(result_path.read_text(encoding='utf-8'))
    except (FileNotFoundError, OSError, json.JSONDecodeError) as error:
        raise CalibrationSessionError('the calibration result is missing') from error

    if result.get('outcome') == 'threshold_suggestion':
        try:
            values = {
                item['key']: float(item['suggested'])
                for item in result.get('threshold_suggestions', ())
                if (
                    item.get('change_recommended')
                    and item.get('key') in DETECTION_THRESHOLD_KEYS
                )
            }
        except (KeyError, TypeError, ValueError) as error:
            raise CalibrationSessionError(
                'the threshold result is incomplete'
            ) from error
        if not all(math.isfinite(value) and value > 0.0 for value in values.values()):
            raise CalibrationSessionError('the threshold result is invalid')
        if not values:
            raise CalibrationSessionError(
                'the threshold result contains no recommended changes'
            )
        return manifest, result, values

    values = {
        item['key']: item['value']
        for item in result.get('values', [])
        if item.get('key') in DERIVED_VALUE_KEYS
    }
    if set(values) != set(DERIVED_VALUE_KEYS):
        raise CalibrationSessionError('the calibration result is incomplete')
    return manifest, result, values


def _get_report_details(session_id, owner, storage_root=None):
    """Resolve an owned completed report and its retained session metadata."""
    session_dir, manifest = get_session(session_id, owner, storage_root)
    if manifest.get('status') != 'success':
        raise CalibrationSessionError('the calibration report is not ready')
    report_path = session_dir.joinpath('asi676mc_calibration_report.txt')
    if not report_path.is_file():
        raise CalibrationSessionError('the calibration report is missing')
    return report_path, manifest


def get_report_path(session_id, owner, storage_root=None):
    """Resolve an owned completed report for the authenticated download view."""
    report_path, _manifest = _get_report_details(
        session_id,
        owner,
        storage_root,
    )
    return report_path


def get_report_download(session_id, owner, storage_root=None):
    """Return an owned report and its stable, sortable download filename."""
    report_path, manifest = _get_report_details(
        session_id,
        owner,
        storage_root,
    )
    timestamp = manifest.get('completed_utc') or manifest.get('created_utc')
    try:
        timestamp_text = _format_report_filename_timestamp(timestamp)
    except (TypeError, ValueError):
        # A retained legacy manifest may lack a usable completion time. The
        # report mtime is stable across downloads and still sorts sensibly.
        modified = datetime.fromtimestamp(
            report_path.stat().st_mtime,
            tz=timezone.utc,
        )
        timestamp_text = modified.astimezone(_local_timezone()).strftime(
            '%Y-%m-%d_%H-%M-%S'
        )
    return (
        report_path,
        '{0}_asi676mc_calibration_report.txt'.format(timestamp_text),
    )
