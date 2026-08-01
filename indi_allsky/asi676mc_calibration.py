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
    manifest['updated_utc'] = _utc_now_text()
    _atomic_write_json(_manifest_path(session_dir), manifest)


def cleanup_expired_sessions(storage_root=None, now=None):
    """Remove abandoned sessions; return the number removed.

    The function only examines directories whose names match IDs generated by
    this module, and it never follows a computed path outside the storage root.
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
    manifest['status'] = 'failed'
    manifest['completed_utc'] = _utc_now_text()
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


def run_calibration_session(session_id, storage_root=None):
    """Run the standalone calibration engine for one queued web session."""
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
                report_title='ASI676MC web calibration report',
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

        manifest['status'] = 'success'
        manifest['completed_utc'] = result['completed_utc']
        manifest['error'] = None
        _write_manifest(session_dir, manifest)
        return result
    except Exception as error:
        session_dir.joinpath('calibration.log').write_text(
            captured_output.getvalue(),
            encoding='utf-8',
        )
        manifest['status'] = 'failed'
        manifest['completed_utc'] = _utc_now_text()
        manifest['error'] = str(error)
        _write_manifest(session_dir, manifest)
        raise
    finally:
        # Results and the small audit log remain downloadable for seven days;
        # the much larger source FITS are no longer needed after validation.
        if upload_dir.exists():
            shutil.rmtree(upload_dir)


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
