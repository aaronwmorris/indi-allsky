"""Web-session support for ASI676MC FITS calibration.

The numerical calibration remains in ``misc/asi676mc_frame_repair.py``.  That
file is intentionally self-contained so it can still be copied to an older
indi-allsky installation.  The web application imports it as a Python module;
it never starts a shell command or an external FITS program.

This module owns the web-specific concerns around that engine:

* private, per-user upload sessions;
* conservative file-count and storage limits;
* atomic manifest/result files shared by gunicorn and the video worker;
* deletion of large uploaded FITS files as soon as a job finishes; and
* a compact result shape suitable for polling from the browser.

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
import time
import unicodedata
import uuid


SESSION_ID_RE = re.compile(r'^[0-9a-f]{32}$')
FITS_SUFFIXES = ('.fit', '.fits', '.fts')

# An uncompressed full-resolution ASI676MC FITS is roughly tens of megabytes.
# These limits comfortably allow sizeable calibration collections while
# preventing one authenticated browser session from consuming the whole disk.
MAX_FILE_COUNT = 200
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_SESSION_BYTES = 2 * 1024 * 1024 * 1024
SESSION_RETENTION_SECONDS = 7 * 24 * 60 * 60

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


def capture_configuration_guidance(config):
    """Describe whether current capture settings retain calibration evidence.

    The current configuration cannot prove how older files were captured, so
    this is deliberately advisory.  Automatic discovery will still inspect
    the FITS that actually exist.  These messages help explain why future bad
    frames will produce low-disk pairs, full-sequence triplets, or no usable
    untouched evidence at all.
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

    if not periodic_fits:
        periodic_text = 'Off'
    elif fits_period == 0:
        periodic_text = 'Every image'
    elif fits_period is None:
        periodic_text = 'On (invalid interval)'
    else:
        periodic_text = 'Every {0} seconds'.format(fits_period)

    mode_text = (
        'Off'
        if not repair_enabled
        else ('Exclude only' if exclude_only else 'Actual repair')
    )
    facts = [
        {'label': 'Repair mode', 'value': mode_text},
        {
            'label': 'Bad + following RAW FITS',
            'value': 'On' if diagnostic_fits else 'Off',
        },
        {'label': 'Ordinary FITS', 'value': periodic_text},
        {
            'label': 'Ordinary FITS compression',
            'value': 'On' if compressed_fits else 'Off',
        },
        {
            'label': 'FITS retention',
            'value': (
                '{0} days'.format(retention_days)
                if retention_days is not None
                else 'Invalid value'
            ),
        },
    ]

    messages = []
    if repair_enabled and exclude_only:
        messages.append({
            'level': 'success',
            'text': (
                'Safe detection-only mode is active: bad frames are flagged '
                'and excluded from timelapses without changing their pixels.'
            ),
        })
    elif repair_enabled:
        messages.append({
            'level': 'info',
            'text': (
                'Actual repair is active. Ordinary FITS are written after '
                'ASI676MC repair, so they may not retain the original bad mosaic.'
            ),
        })
    else:
        messages.append({
            'level': 'warning',
            'text': (
                'ASI676MC handling is disabled. Frames are not flagged by the '
                'live pipeline, although every-image ordinary FITS can still '
                'be classified later from their contents.'
            ),
        })
        if diagnostic_fits:
            messages.append({
                'level': 'warning',
                'text': (
                    'Bad and Following RAW FITS is selected but inactive until '
                    'ASI676MC handling is enabled.'
                ),
            })

    if repair_enabled and diagnostic_fits:
        messages.append({
            'level': 'success',
            'text': (
                'Low-disk evidence collection is active: each detected bad '
                'frame and its immediately following untouched RAW FITS are kept.'
            ),
        })
    elif repair_enabled and not exclude_only:
        messages.append({
            'level': 'warning',
            'text': (
                'Enable Bad and Following RAW FITS before collecting calibration '
                'data; otherwise actual repair may remove the original failure '
                'before ordinary FITS are saved.'
            ),
        })

    if periodic_fits and fits_period == 0:
        messages.append({
            'level': 'info',
            'text': (
                'Every-image FITS saving can provide stronger good/bad/good '
                'triplets, at substantially higher disk usage.'
            ),
        })
    elif periodic_fits:
        messages.append({
            'level': 'warning',
            'text': (
                'Periodic FITS saving does not guarantee a FITS for a randomly '
                'occurring bad frame. Use Every Image or enable Bad and '
                'Following RAW FITS while collecting evidence.'
            ),
        })
    elif repair_enabled and not diagnostic_fits:
        messages.append({
            'level': 'warning',
            'text': (
                'No FITS evidence collection is enabled. Future flagged bad '
                'frames may have no FITS available to the calibration tool.'
            ),
        })

    return {
        'facts': facts,
        'messages': messages,
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
    Queued or running numerical jobs are intentionally not interruptible.
    """
    session_dir, manifest = get_session(session_id, owner, storage_root)
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
    storage_root=None,
):
    """Freeze the upload set and record the background job parameters."""
    session_dir, manifest = get_session(session_id, owner, storage_root)
    if manifest.get('status') != 'uploading':
        raise CalibrationSessionError('this calibration session has already started')
    if len(manifest.get('files', [])) < 14:
        raise CalibrationSessionError(
            'select at least 14 FITS files: seven bad frames and at least '
            'seven distinct normal references'
        )

    max_pair_seconds = float(max_pair_seconds)
    if max_pair_seconds <= 0 or max_pair_seconds > 3600:
        raise CalibrationSessionError(
            'maximum pair separation must be between 0 and 3600 seconds'
        )

    manifest['status'] = 'queued'
    manifest['task_id'] = int(task_id)
    manifest['max_pair_seconds'] = max_pair_seconds
    manifest['settings'] = dict(settings)
    manifest['config_id'] = int(config_id) if config_id is not None else None
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

    warnings = []
    if quality.get('unmatched_bad_count'):
        warnings.append(
            '{0} detected bad frame(s) had no compatible adjacent normal FITS '
            'and were ignored.'.format(quality['unmatched_bad_count'])
        )
    if quality.get('rejected_file_count'):
        warnings.append(
            '{0} uploaded file(s) were rejected; see the text report for '
            'details.'.format(quality['rejected_file_count'])
        )
    if quality.get('good_bad_ratio', 0) < 2.0:
        warnings.append(
            'Calibration passed, but fewer than two distinct normal references '
            'per bad frame were available. Triplets would improve confidence.'
        )

    return {
        'values': values,
        'quality': {
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
        },
        'warnings': warnings,
    }


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
            'message': 'Current configuration could not be compared: {0}'.format(
                error
            ),
            'differing_keys': [],
        }

    if exact:
        return {
            'status': 'exact',
            'message': (
                'Already matches the current configuration exactly; applying '
                'again is unnecessary.'
            ),
            'differing_keys': [],
        }
    if equivalent:
        return {
            'status': 'equivalent',
            'message': (
                'Effectively matches the current configuration; applying '
                'these tiny differences is unlikely to have a noticeable effect.'
            ),
            'differing_keys': [],
        }
    return {
        'status': 'different',
        'message': '',
        'differing_keys': differing_keys,
    }


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
            payload, report_text = calibration_engine.calibrate_folder(
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
        _atomic_write_json(session_dir.joinpath('result.json'), result)
        session_dir.joinpath('asi676mc_calibration_report.txt').write_text(
            report_text,
            encoding='utf-8',
        )
        session_dir.joinpath('calibration.log').write_text(
            captured_output.getvalue(),
            encoding='utf-8',
        )

        # Remove the large inputs before publishing ``success``. Therefore a
        # browser that can see the result is guaranteed not to have uploaded
        # source FITS still retained by the calibration session.
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
                '{0}; uploaded FITS cleanup also failed: {1}'
            ).format(error, cleanup_error)
        _write_manifest(session_dir, manifest)
        raise


def get_status(session_id, owner, storage_root=None):
    """Return the browser-safe status/result for an owned session."""
    session_dir, manifest = get_session(session_id, owner, storage_root)
    response = {
        'session_id': session_id,
        'status': manifest['status'],
        'file_count': len(manifest.get('files', [])),
        'total_bytes': manifest.get('total_bytes', 0),
        'task_id': manifest.get('task_id'),
        'error': manifest.get('error'),
        'sources_deleted_utc': manifest.get('sources_deleted_utc'),
        'report_available': session_dir.joinpath(
            'asi676mc_calibration_report.txt'
        ).is_file(),
    }
    result_path = session_dir.joinpath('result.json')
    if manifest['status'] == 'success' and result_path.is_file():
        response['result'] = json.loads(result_path.read_text(encoding='utf-8'))
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
