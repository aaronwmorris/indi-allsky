import base64
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
import pytest
import numpy as np

from indi_allsky import asi676mc_calibration as calib
from indi_allsky import asi676mc_calibration_engine as calibration_engine


@pytest.fixture
def calib_tmp(tmp_path):
    root = tmp_path / 'calib_storage'
    root.mkdir()
    return root


def test_text_and_selection_helpers():
    # _counted_item
    assert calib._counted_item(1, 'frame') == '1 frame'
    assert calib._counted_item(2, 'frame') == '2 frames'
    assert calib._counted_item(2, 'entry', 'entries') == '2 entries'

    # _initial_database_search_text
    assert calib._initial_database_search_text({'selection_mode': 'marked_groups'}) == 'Not used; marked evidence was sufficient'
    assert calib._initial_database_search_text({'selection_mode': 'full_retention_detector_groups'}) == 'Complete retained archive'
    assert calib._initial_database_search_text({'selection_mode': 'other'}) == 'Not recorded by this result version'
    assert calib._initial_database_search_text({'selection_mode': 'progressive_search'}) == 'Not recorded by this result version'
    assert calib._initial_database_search_text({'selection_mode': 'progressive_search', 'initial_scan_file_count': 'bad'}) == 'Not recorded by this result version'
    assert calib._initial_database_search_text({'selection_mode': 'progressive_search', 'initial_scan_file_count': 42}) == '42 FITS files'

    # _database_selection_text
    assert calib._database_selection_text('marked_groups') == 'marked groups with adjacent normal FITS'
    assert calib._database_selection_text('full_retention_detector_groups') == 'complete-retention detector search'
    assert calib._database_selection_text('full_retention_population_groups') == 'complete-retention missed-purple population search'
    assert calib._database_selection_text('background_full_retention') == 'queued complete-retention search'
    assert calib._database_selection_text('other') == 'progressive ratio search through retained FITS'

    # _database_search_coverage_line
    assert 'Complete retained archive' in calib._database_search_coverage_line({'selection_mode': 'full_retention_x'})
    assert 'Initial fallback search target:' in calib._database_search_coverage_line({'selection_mode': 'other'})

    # _readable_join
    assert calib._readable_join([]) == ''
    assert calib._readable_join(['one']) == 'one'
    assert calib._readable_join(['one', 'two']) == 'one and two'
    assert calib._readable_join(['one', 'two', 'three']) == 'one, two, and three'


def test_storage_root_and_session_dir(calib_tmp):
    # Custom root
    root = calib.get_storage_root(calib_tmp)
    assert root == calib_tmp.resolve()

    # Flask current_app configured
    mock_app = mock.Mock()
    mock_app.config = {'ASI676MC_CALIBRATION_FOLDER': str(calib_tmp / 'custom')}
    with mock.patch.dict('sys.modules', {'flask': mock.Mock(current_app=mock_app)}):
        assert calib.get_storage_root(None) == (calib_tmp / 'custom').resolve()

    # Flask current_app not configured (instance_path fallback)
    mock_app.config = {}
    mock_app.instance_path = str(calib_tmp / 'instance')
    with mock.patch.dict('sys.modules', {'flask': mock.Mock(current_app=mock_app)}):
        assert calib.get_storage_root(None) == (calib_tmp / 'instance' / 'asi676mc_calibration').resolve()

    # chmod OSError handling
    with mock.patch.object(Path, 'chmod', side_effect=OSError('chmod error')):
        assert calib.get_storage_root(calib_tmp) == calib_tmp.resolve()

    # _session_dir invalid session ID
    with pytest.raises(calib.CalibrationSessionError, match='no longer available'):
        calib._session_dir('invalid-id', calib_tmp)

    # _session_dir valid 32-char hex
    valid_id = '0123456789abcdef0123456789abcdef'
    session_path = calib_tmp / valid_id
    session_path.mkdir()
    assert calib._session_dir(valid_id, calib_tmp) == session_path.resolve()

    with mock.patch.object(Path, 'resolve', return_value=calib_tmp / 'other' / valid_id):
        with pytest.raises(calib.CalibrationSessionError, match='could not be opened'):
            calib._session_dir(valid_id, calib_tmp)


def test_file_lock_and_atomic_write_and_manifest(calib_tmp):
    # _atomic_write_json chmod OSError and exception handling
    target = calib_tmp / 'test.json'
    with mock.patch.object(Path, 'chmod', side_effect=OSError('perm')):
        calib._atomic_write_json(target, {'key': 'val'})
    assert target.exists()

    with mock.patch('os.replace', side_effect=RuntimeError('replace error')):
        with pytest.raises(RuntimeError):
            calib._atomic_write_json(target, {'fail': True})

    # _read_manifest exceptions
    sess_dir = calib_tmp / 'sess'
    sess_dir.mkdir()
    with pytest.raises(calib.CalibrationSessionError, match='no longer available'):
        calib._read_manifest(sess_dir)

    manifest_file = sess_dir / 'manifest.json'
    manifest_file.write_text('bad json', encoding='utf-8')
    with pytest.raises(calib.CalibrationSessionError, match='could not be read'):
        calib._read_manifest(sess_dir)

    with mock.patch.object(Path, 'read_text', side_effect=OSError('read error')):
        with pytest.raises(calib.CalibrationSessionError, match='could not be read'):
            calib._read_manifest(sess_dir)


def test_recover_stale_and_expired_sessions(calib_tmp):
    valid_id = '0123456789abcdef0123456789abcdef'
    sess_dir = calib_tmp / valid_id
    sess_dir.mkdir()

    # Non-recovering status
    manifest = {'status': 'success'}
    assert calib._recover_stale_session_unlocked(sess_dir, manifest) == manifest

    # Running but not stale
    now_iso = datetime.now(timezone.utc).isoformat()
    manifest = {'status': 'running', 'heartbeat_utc': now_iso}
    assert calib._recover_stale_session_unlocked(sess_dir, manifest) == manifest

    # Stale running with invalid timestamp
    manifest = {'status': 'running', 'heartbeat_utc': 'not-a-date'}
    recovered = calib._recover_stale_session_unlocked(sess_dir, manifest)
    assert recovered['status'] == 'failed'
    assert 'worker stopped responding' in recovered['error']

    # Stale cancel_requested
    manifest = {'status': 'cancel_requested', 'heartbeat_utc': 'not-a-date'}
    recovered = calib._recover_stale_session_unlocked(sess_dir, manifest)
    assert recovered['status'] == 'cancelled'
    assert recovered['error'] is None

    # Stale uploading
    manifest = {'status': 'uploading', 'updated_utc': 'not-a-date'}
    recovered = calib._recover_stale_session_unlocked(sess_dir, manifest)
    assert recovered['status'] == 'failed'
    assert 'upload stopped responding' in recovered['error']

    # Stale queued
    manifest = {'status': 'queued', 'updated_utc': 'not-a-date'}
    recovered = calib._recover_stale_session_unlocked(sess_dir, manifest)
    assert recovered['status'] == 'failed'

    # cleanup_expired_sessions stat OSError
    orig_stat = Path.stat
    def failing_candidate_stat(self, *args, **kwargs):
        if self.parent == calib_tmp:
            raise OSError('stat fail')
        return orig_stat(self, *args, **kwargs)

    with mock.patch.object(Path, 'stat', side_effect=failing_candidate_stat, autospec=True):
        assert calib.cleanup_expired_sessions(calib_tmp) == 0

    # create_session owner validation
    with pytest.raises(calib.CalibrationSessionError, match='owner is required'):
        calib.create_session('', calib_tmp)

    # create_session success
    mf = calib.create_session('user1', calib_tmp)
    assert mf['owner'] == 'user1'


def test_unique_upload_name_and_database_compatibility(calib_tmp):
    upload_dir = calib_tmp / 'uploads'
    upload_dir.mkdir()

    # Empty/invalid name
    with pytest.raises(calib.CalibrationUploadError, match='no usable filename'):
        calib._unique_upload_name(upload_dir, '___...___')

    # Non-FITS extension
    with pytest.raises(calib.CalibrationUploadError, match='only uncompressed'):
        calib._unique_upload_name(upload_dir, 'image.jpg')

    # Collisions
    f1 = upload_dir / 'test.fit'
    f1.write_text('dummy')
    f2 = upload_dir / 'test_2.fit'
    f2.write_text('dummy')
    candidate = calib._unique_upload_name(upload_dir, 'test.fit')
    assert candidate.name == 'test_3.fit'

    # is_database_fits_path
    assert calib.is_database_fits_path('test.fit') is True
    assert calib.is_database_fits_path('test.fits.gz') is True
    assert calib.is_database_fits_path('test.jpg') is False

    # _database_record_has_role
    record = {'roles': [{'role': 'bad'}, 'not-a-dict', {'role': 'normal'}]}
    assert calib._database_record_has_role(record, 'bad') is True
    assert calib._database_record_has_role(record, 'other') is False

    # _database_compatibility_key
    assert calib._database_compatibility_key({'exposure': 'bad'}) is None
    assert calib._database_compatibility_key({'exposure': 1.0, 'gain': 100.0, 'binmode': 1, 'width': 100, 'height': 100}) == (100, 100, 1.0, 100.0, 1)


def test_candidate_filtering_and_database_staging(calib_tmp):
    mf = calib.create_session('user1', calib_tmp)
    sess_id = mf['session_id']
    sess = calib_tmp / sess_id

    # Verify staging file errors
    with pytest.raises(calib.CalibrationSessionError, match='too many files'):
        calib._stage_database_files_unlocked(sess_id, 'user1', range(calib.DATABASE_MAX_FILES + 1), calib_tmp)

    # Token mismatch
    with pytest.raises(calib.CalibrationSessionError, match='could not continue'):
        calib._stage_database_files_unlocked(sess_id, 'user1', [], calib_tmp, worker_token='wrong')

    # Status mismatch
    with pytest.raises(calib.CalibrationSessionError, match='no longer prepare files'):
        calib._stage_database_files_unlocked(sess_id, 'user1', [], calib_tmp, expected_status='other')

    # Cancel marker exists
    marker = calib._cancel_marker_path(sess)
    marker.write_text('cancel')
    fake_existing_fit = calib_tmp / 'existing.fit'
    fake_existing_fit.write_text('SIMPLE  =                    T' + ' ' * 2854)
    with pytest.raises(calib.CalibrationSessionError, match='was cancelled'):
        calib._stage_database_files_unlocked(
            sess_id,
            'user1',
            [{'id': 1, 'path': str(fake_existing_fit), 'camera_name': 'ZWO ASI676MC'}],
            calib_tmp,
        )
    marker.unlink()

    # Staging various file issues
    not_fits = calib_tmp / 'fake.txt'
    not_fits.write_text('dummy')

    with pytest.raises(calib.CalibrationSessionError, match='unsupported database FITS format'):
        calib._stage_database_files_unlocked(
            sess_id,
            'user1',
            [{'id': 1, 'path': str(not_fits), 'camera_name': 'ZWO ASI676MC'}],
            calib_tmp,
        )

    with pytest.raises(calib.CalibrationSessionError, match='not positively identified'):
        calib._stage_database_files_unlocked(
            sess_id,
            'user1',
            [{'id': 1, 'path': str(fake_existing_fit), 'camera_name': 'Canon EOS'}],
            calib_tmp,
        )

    # Missing file
    missing_file = calib_tmp / 'missing.fit'
    with pytest.raises(calib.CalibrationSessionError, match='all selected database FITS became unavailable during staging'):
        calib._stage_database_files_unlocked(
            sess_id,
            'user1',
            [{'id': 2, 'path': str(missing_file), 'camera_name': 'ZWO ASI676MC'}],
            calib_tmp,
        )

    # Mixed missing and valid
    staged = calib._stage_database_files_unlocked(
        sess_id,
        'user1',
        [
            {'id': 2, 'path': str(missing_file), 'camera_name': 'ZWO ASI676MC'},
            {'id': 3, 'path': str(fake_existing_fit), 'camera_name': 'ZWO ASI676MC'},
        ],
        calib_tmp,
    )
    assert len(staged['files']) == 1


def test_add_file_unlocked_branches(calib_tmp):
    mf = calib.create_session('user1', calib_tmp)
    sess_id = mf['session_id']
    sess = calib_tmp / sess_id

    # status != uploading
    mf['status'] = 'running'
    calib._write_manifest(sess, mf)
    with pytest.raises(calib.CalibrationUploadError, match='no longer uploading'):
        calib.store_upload(sess_id, 'user1', mock.Mock(), calib_tmp)

    mf['status'] = 'uploading'
    calib._write_manifest(sess, mf)

    # Cancel marker exists
    marker = calib._cancel_marker_path(sess)
    marker.write_text('cancel')
    with pytest.raises(calib.CalibrationUploadError, match='was cancelled'):
        calib.store_upload(sess_id, 'user1', mock.Mock(), calib_tmp)
    marker.unlink()

    # MAX_FILE_COUNT exceeded
    mf['files'] = [{'name': f'f{i}'} for i in range(calib.MAX_FILE_COUNT)]
    calib._write_manifest(sess, mf)
    with pytest.raises(calib.CalibrationUploadError, match='at most'):
        calib.store_upload(sess_id, 'user1', mock.Mock(), calib_tmp)
    mf['files'] = []
    calib._write_manifest(sess, mf)

    # file_storage is None or empty filename
    with pytest.raises(calib.CalibrationUploadError, match='no FITS file was supplied'):
        calib.store_upload(sess_id, 'user1', None, calib_tmp)

    mock_storage = mock.Mock()
    mock_storage.filename = ''
    with pytest.raises(calib.CalibrationUploadError, match='no FITS file was supplied'):
        calib.store_upload(sess_id, 'user1', mock_storage, calib_tmp)

    # Cancel marker appears while streaming
    mock_storage.filename = 'test.fit'
    def mock_read(chunk_size):
        if not marker.exists():
            marker.write_text('cancel')
            return b'SIMPLE  =                    T' + b' ' * 2854
        return b''
    mock_storage.stream = mock.Mock()
    mock_storage.stream.read = mock.Mock(side_effect=mock_read)
    with pytest.raises(calib.CalibrationUploadError, match='was cancelled'):
        calib.store_upload(sess_id, 'user1', mock_storage, calib_tmp)
    if marker.exists():
        marker.unlink()

    # Empty file
    mock_storage.stream.read = mock.Mock(side_effect=[b''])
    with pytest.raises(calib.CalibrationUploadError, match='does not appear to be a FITS file'):
        calib.store_upload(sess_id, 'user1', mock_storage, calib_tmp)

    # Not a FITS file
    mock_storage.stream.read = mock.Mock(side_effect=[b'NOT_A_FITS_HEADER' + b' ' * 100, b''])
    with pytest.raises(calib.CalibrationUploadError, match='does not appear to be a FITS file'):
        calib.store_upload(sess_id, 'user1', mock_storage, calib_tmp)


def test_session_lifecycle_and_queuing(calib_tmp):
    mf = calib.create_session('user1', calib_tmp)
    sess_id = mf['session_id']
    sess = calib_tmp / sess_id

    # cancel_upload_session alias
    res = calib.cancel_upload_session(sess_id, 'user1', calib_tmp)
    assert res['status'] == 'cancelled'

    # cancel on finished session
    mf['status'] = 'success'
    calib._write_manifest(sess, mf)
    with pytest.raises(calib.CalibrationSessionError, match='already finished'):
        calib._cancel_session_unlocked(sess_id, 'user1', calib_tmp)

    # discard active session
    mf2 = calib.create_session('user2', calib_tmp)
    sess2_id = mf2['session_id']
    sess2 = calib_tmp / sess2_id
    with pytest.raises(calib.CalibrationSessionError, match='still running'):
        calib.discard_session(sess2_id, 'user2', calib_tmp)

    # discard finished session
    calib.cancel_session(sess2_id, 'user2', calib_tmp)
    calib.discard_session(sess2_id, 'user2', calib_tmp)
    assert not sess2.exists()

    # mark_failed
    mf3 = calib.create_session('user3', calib_tmp)
    res_failed = calib.mark_failed(mf3['session_id'], 'user3', 'Pre-queue failure', calib_tmp)
    assert res_failed['status'] == 'failed'
    assert res_failed['error'] == 'Pre-queue failure'

    # _mark_queued_unlocked
    mf4 = calib.create_session('user4', calib_tmp)
    sess4_id = mf4['session_id']
    sess4 = calib_tmp / sess4_id
    # cancel marker
    marker = calib._cancel_marker_path(sess4)
    marker.write_text('cancel')
    with pytest.raises(calib.CalibrationSessionError, match='was cancelled'):
        calib._mark_queued_unlocked(sess4_id, 'user4', 1, 10, {}, storage_root=calib_tmp)
    marker.unlink()

    # status != uploading
    mf4['status'] = 'running'
    calib._write_manifest(sess4, mf4)
    with pytest.raises(calib.CalibrationSessionError, match='already started'):
        calib._mark_queued_unlocked(sess4_id, 'user4', 1, 10, {}, storage_root=calib_tmp)


def test_population_preview_branches():
    # Empty candidates
    assert calib._population_preview_candidates([]) == []
    evidence = [
        {'population': 'Likely purple', 'purple_ratio': 1.5, 'red_side_ratio': 1.2, 'blue_side_ratio': 1.1, 'timestamp_utc': '2026-01-01T00:00:00Z', 'name': 'f1.fit'},
        {'population': 'Likely normal', 'purple_ratio': 0.8, 'red_side_ratio': 0.9, 'blue_side_ratio': 0.85, 'timestamp_utc': '2026-01-01T00:00:10Z', 'name': 'f2.fit'},
    ]
    candidates = calib._population_preview_candidates(evidence)
    assert len(candidates) == 2

    # _render_population_preview white_point <= black_point
    engine_mock = mock.Mock()
    flat_data = np.ones((100, 100), dtype=np.uint16) * 1000
    engine_mock._read_fits.return_value = (flat_data, {}, 0)

    with pytest.raises(ValueError, match='no usable brightness range'):
        calib._render_population_preview(Path('dummy.fit'), engine_mock)

    # Large image triggering resize_scale < 1.0
    large_data = np.random.randint(500, 30000, size=(1000, 1000), dtype=np.uint16)
    engine_mock._read_fits.return_value = (large_data, {}, 0)
    preview = calib._render_population_preview(Path('dummy.fit'), engine_mock)
    assert 'data_url' in preview
    assert preview['width'] <= calib.POPULATION_PREVIEW_MAX_DIMENSION
    assert preview['height'] <= calib.POPULATION_PREVIEW_MAX_DIMENSION

    # Encoding failure
    with mock.patch('cv2.imencode', return_value=(False, None)):
        with pytest.raises(ValueError, match='encoding failed'):
            calib._render_population_preview(Path('dummy.fit'), engine_mock)

    # Encoded exceeds limit
    with mock.patch('cv2.imencode', return_value=(True, np.zeros((calib.POPULATION_PREVIEW_MAX_BYTES + 10,), dtype=np.uint8))):
        with pytest.raises(ValueError, match='exceeds the size limit'):
            calib._render_population_preview(Path('dummy.fit'), engine_mock)


def test_friendly_rejected_file_reason_all():
    reasons = [
        'contains no image data',
        'decoded fits image exceeds the 512 mib safety limit',
        'requires a two-dimensional raw16 frame',
        'unsigned 16-bit raw data',
        'at least four rows and four columns',
        'even raw frame dimensions',
        'missing explicit bayerpat=rggb',
        'expected rggb bayer data, got GBRG',
        'already repaired by asi676mc frame handling',
        'exposure is invalid',
        'finite value greater than zero',
        'gain is invalid',
        'finite non-negative value',
        'xbinning=1 and ybinning=1',
        'requires unbinned database fits',
        'requires zero bayer offsets',
        'different or conflicting asi camera identity',
        'non-asi676mc camera',
        'bound calibration camera is not positively identified',
        'does not explicitly identify an asi676mc camera',
        'not positively identified as asi676mc',
        'missing usable date-obs/date and filename timestamp',
        'incomplete saved detector signature metadata',
        'sampled frame has no usable green signal',
        'sampled frame produced a non-finite detector ratio',
        'some other unknown reason',
    ]
    for r in reasons:
        guidance = calib._friendly_rejected_file_reason(r)
        assert isinstance(guidance, str)
        assert len(guidance) > 10


def test_friendly_failure_messages_and_task_messages():
    messages = [
        'complete retained database archive with no eligible asi676mc fits',
        'complete retained database archive with no safe purple/normal population',
        'complete retained database archive other failure',
        'selected for this database search has changed',
        'selected database camera is no longer an asi676mc',
        'no compatible raw16 rggb fits files found: rejection summary: {"contains no image data": 2}',
        '2 matched purple frames found',
        'both normal and purple frames are required',
        'matched normal/purple ratio is too low',
        'detected purple frames have no compatible nearby normal',
        'cover only one exposure setting',
        'more than one explicit camera identity found',
        'lack the required asi676mc raw16 rggb',
        'no fits matched the configured purple-frame detector',
        'no fits remained classified as normal',
        'automatic threshold analysis could not make a safe suggestion: at least 14 compatible fits',
        'automatic threshold analysis could not make a safe suggestion: non-finite or non-positive values',
        'automatic threshold analysis could not make a safe suggestion: do not vary in all three detector ratios',
        'automatic threshold analysis could not make a safe suggestion: do not form two stable populations',
        'automatic threshold analysis could not make a safe suggestion: ratio does not have the required clean gap',
        'automatic threshold analysis could not make a safe suggestion: configured thresholds already lie inside every observed gap',
        'automatic threshold analysis could not make a safe suggestion: no compatible nearby normal',
        'automatic threshold analysis could not make a safe suggestion: normal/purple ratio',
        'automatic threshold analysis could not make a safe suggestion: cover only one exposure',
        'configured combined purple/green ratio threshold 1.25 is too low',
        'misclassifies at least one supplied normal frame',
        'no source green plateau found',
        'has usable samples in only 1 pair',
        'estimate is outside the plausible asi676mc range',
        'varies too much between pairs',
        'best clipped-highlight fit score is too high',
        'too few stable samples to compare',
        'validation_group_count_after_exclusion: too few groups remain',
        'validation_refit_signature_separation: insufficient separation',
        'validation_runtime_repair: test.fit: repair failed',
        'validation_normal_rejected: test.fit: rejected',
        'validation_normal_modified: test.fit: modified',
        'repaired frame remains too different',
        'repair does not materially improve agreement',
        'evidence does not confirm the asi676mc one-row phase shift',
        'astropy could not be imported',
        'calibrated repair validation failed',
        'calibration queue service error',
        'calibration session not found',
        'completely unknown engine error message',
    ]
    for msg in messages:
        friendly = calib._friendly_failure_message(msg)
        assert isinstance(friendly, str)
        assert len(friendly) > 0

    # task_failure_message
    msg_astropy = 'astropy could not be imported'
    friendly_astropy = calib._friendly_failure_message(msg_astropy)
    assert calib.task_failure_message(msg_astropy, limit=255) == friendly_astropy

    long_validation = 'validation_runtime_repair: capture_20260701_120000.fit: ' + 'x' * 300
    task_res = calib.task_failure_message(long_validation, limit=50)
    assert len(task_res) <= 50
    assert task_res.endswith('…')

    long_other = 'x' * 500
    fallback = calib.task_failure_message(long_other, limit=60)
    assert len(fallback) <= 60


def test_warnings_and_guidance():
    # _result_warnings with various branch conditions
    quality = {
        'marginal_exclusions': [{'group': 1}],
        'bound_session_camera_count': 1,
        'bound_database_camera_count': 2,
        'requested_group_count': 10,
        'used_group_count': 5,
        'replacement_group_count': 0,
    }
    thresholds = [
        {'marginal': True, 'label': 'Combined', 'normal_max': 0.9, 'current': 1.0, 'purple_min': 1.1, 'suggested': 1.05},
    ]
    source_details = {
        'kind': 'database',
        'requested_group_count': 10,
        'staging_skipped_file_count': 2,
        'selection_limit_reached': True,
        'selection_mode': 'full_retention_detector_groups',
    }
    warnings = calib._result_warnings(
        quality,
        source_details=source_details,
        threshold_assessment=thresholds,
        report_context=True,
    )
    assert len(warnings) >= 4

    # Without report_context and without full_retention
    source_details['selection_mode'] = 'progressive_search'
    warnings2 = calib._result_warnings(
        quality,
        source_details=source_details,
        threshold_assessment=thresholds,
        report_context=False,
    )
    assert len(warnings2) >= 4


def test_report_formatting_and_completed_values(calib_tmp):
    # _format_report_timestamp
    dt_no_tz = '2026-08-01 12:00:00'
    formatted = calib._format_report_timestamp(dt_no_tz)
    assert '2026-08-01' in formatted
    assert calib._format_report_timestamp('invalid-date') == 'invalid-date'

    # _format_report_filename_timestamp
    assert '2026-08-01' in calib._format_report_filename_timestamp(dt_no_tz)

    # _original_report_filename
    manifest_files = [{'name': '001_abc.fit', 'original_name': 'orig_capture.fit'}]
    assert calib._original_report_filename('001_abc.fit', manifest_files) == 'orig_capture.fit'
    assert calib._original_report_filename('002_xyz.fit', manifest_files) == '002_xyz.fit'

    # format_failure_report
    manifest = {
        'completed_utc': '2026-08-01T12:00:00Z',
        'sources_deleted_utc': '2026-08-01T12:00:05Z',
        'files': [{'name': 'f1.fit'}],
        'source': {
            'kind': 'database',
            'camera_name': 'ZWO ASI676MC',
            'requested_group_count': 7,
            'staged_group_count': 7,
            'reserve_group_count': 0,
        },
    }
    report = calib.format_failure_report('no compatible raw16 rggb fits files found', manifest)
    assert 'Status: Failed' in report
    assert 'Method: Saved FITS search' in report

    manifest['source']['kind'] = 'upload'
    report_upload = calib.format_failure_report('no compatible raw16 rggb fits files found', manifest)
    assert 'Method: Manual FITS upload' in report_upload

    manifest['source']['kind'] = 'other'
    report_other = calib.format_failure_report('no compatible raw16 rggb fits files found', manifest)
    assert 'Method: Tools > Fix ASI676MC purple frames' in report_other

    # get_completed_result branches
    mf = calib.create_session('user1', calib_tmp)
    sess_id = mf['session_id']
    sess = calib_tmp / sess_id

    with pytest.raises(calib.CalibrationSessionError, match='not completed successfully'):
        calib.get_completed_result(sess_id, 'user1', calib_tmp)

    mf['status'] = 'success'
    calib._write_manifest(sess, mf)
    with pytest.raises(calib.CalibrationSessionError, match='result is missing'):
        calib.get_completed_result(sess_id, 'user1', calib_tmp)

    # Threshold suggestion incomplete / invalid / no changes
    result_path = sess / 'result.json'
    result_path.write_text(json.dumps({
        'outcome': 'threshold_suggestion',
        'threshold_suggestions': [{'key': 'PURPLE_RATIO_THRESHOLD', 'change_recommended': True, 'suggested': -1.0}],
    }))
    with pytest.raises(calib.CalibrationSessionError, match='result is invalid'):
        calib.get_completed_result(sess_id, 'user1', calib_tmp)

    result_path.write_text(json.dumps({
        'outcome': 'threshold_suggestion',
        'threshold_suggestions': [{'key': 'PURPLE_RATIO_THRESHOLD', 'change_recommended': True, 'suggested': 'not-a-number'}],
    }))
    with pytest.raises(calib.CalibrationSessionError, match='result is incomplete'):
        calib.get_completed_result(sess_id, 'user1', calib_tmp)

    result_path.write_text(json.dumps({
        'outcome': 'threshold_suggestion',
        'threshold_suggestions': [{'key': 'PURPLE_RATIO_THRESHOLD', 'change_recommended': False, 'suggested': 1.5}],
    }))
    with pytest.raises(calib.CalibrationSessionError, match='contains no recommended changes'):
        calib.get_completed_result(sess_id, 'user1', calib_tmp)

    # Standard values incomplete
    result_path.write_text(json.dumps({
        'outcome': 'success',
        'values': [{'key': 'PURPLE_GREEN_RATIO', 'value': 1.2}],
    }))
    with pytest.raises(calib.CalibrationSessionError, match='result is incomplete'):
        calib.get_completed_result(sess_id, 'user1', calib_tmp)

    # _get_report_details
    with pytest.raises(calib.CalibrationSessionError, match='report is missing'):
        calib._get_report_details(sess_id, 'user1', calib_tmp)

    report_path = sess / 'asi676mc_calibration_report.txt'
    report_path.write_text('report content')
    p, m = calib._get_report_details(sess_id, 'user1', calib_tmp)
    assert p == report_path

    # get_report_download with invalid completion timestamp
    mf['completed_utc'] = 'bad-timestamp'
    mf['created_utc'] = 'bad-timestamp'
    calib._write_manifest(sess, mf)
    path_dl, name_dl = calib.get_report_download(sess_id, 'user1', calib_tmp)
    assert path_dl == report_path
    assert name_dl.endswith('_asi676mc_calibration_report.txt')


def test_run_calibration_cancellation_and_error_handling(calib_tmp):
    mf = calib.create_session('user1', calib_tmp)
    sess_id = mf['session_id']
    sess = calib_tmp / sess_id

    # Must be queued
    mf['status'] = 'queued'
    mf['max_pair_seconds'] = 60.0
    calib._write_manifest(sess, mf)

    # CalibrationCancelled handling
    with mock.patch('indi_allsky.asi676mc_calibration_engine.calibrate_folder', side_effect=calib.CalibrationCancelled):
        res = calib.run_calibration_session(sess_id, storage_root=calib_tmp)
        assert res is None
        _d, mf_after = calib.get_session(sess_id, 'user1', calib_tmp)
        assert mf_after['status'] == 'cancelled'

    # Exception with cleanup error
    mf2 = calib.create_session('user2', calib_tmp)
    sess2_id = mf2['session_id']
    sess2 = calib_tmp / sess2_id
    mf2['status'] = 'queued'
    mf2['max_pair_seconds'] = 60.0
    calib._write_manifest(sess2, mf2)

    with mock.patch('indi_allsky.asi676mc_calibration_engine.calibrate_folder', side_effect=ValueError('calib fail')), \
         mock.patch('indi_allsky.asi676mc_calibration._remove_upload_dir', side_effect=OSError('cleanup fail')):
        with pytest.raises(ValueError, match='calib fail'):
            calib.run_calibration_session(sess2_id, storage_root=calib_tmp)
        _d, mf2_after = calib.get_session(sess2_id, 'user2', calib_tmp)
        assert mf2_after['status'] == 'failed'
        assert 'cleanup also failed' in mf2_after['error']


def test_more_upload_and_calibration_branches(calib_tmp):
    # 1. store_upload size limits
    mf = calib.create_session('user1', calib_tmp)
    sess_id = mf['session_id']
    sess = calib_tmp / sess_id

    mock_storage = mock.Mock()
    mock_storage.filename = 'test.fit'
    mock_storage.stream.read.return_value = b'SIMPLE  =                    T'

    with mock.patch('indi_allsky.asi676mc_calibration.MAX_FILE_BYTES', 10):
        with pytest.raises(calib.CalibrationUploadError, match='exceeds the per-file size limit'):
            calib.store_upload(sess_id, 'user1', mock_storage, calib_tmp)

    with mock.patch('indi_allsky.asi676mc_calibration.MAX_SESSION_BYTES', 10):
        with pytest.raises(calib.CalibrationUploadError, match='exceed the calibration-session size limit'):
            calib.store_upload(sess_id, 'user1', mock_storage, calib_tmp)

    # 2. destination.chmod OSError during store_upload
    mock_storage.stream.read.side_effect = [b'SIMPLE  =                    T' + b' ' * 2854, b'']
    with mock.patch.object(Path, 'chmod', side_effect=OSError('chmod fail')):
        entry, mf_res = calib.store_upload(sess_id, 'user1', mock_storage, calib_tmp)
        assert len(mf_res['files']) == 1

    # 3. get_completed_result standard derived values success
    mf['status'] = 'success'
    calib._write_manifest(sess, mf)
    res_path = sess / 'result.json'
    res_data = {
        'outcome': 'standard',
        'values': [
            {'key': k, 'value': 1.0} for k in calib.DERIVED_VALUE_KEYS
        ],
    }
    res_path.write_text(json.dumps(res_data))
    mf_loaded, res_loaded, vals = calib.get_completed_result(sess_id, 'user1', calib_tmp)
    assert len(vals) == len(calib.DERIVED_VALUE_KEYS)

    # 4. _get_report_details and get_report_path
    mf['status'] = 'running'
    calib._write_manifest(sess, mf)
    with pytest.raises(calib.CalibrationSessionError, match='report is not ready'):
        calib.get_report_path(sess_id, 'user1', calib_tmp)

    # 5. run_calibration_session: cancel marker exists before it starts
    mf['status'] = 'queued'
    mf['max_pair_seconds'] = 60.0
    calib._write_manifest(sess, mf)
    marker = calib._cancel_marker_path(sess)
    marker.write_text('cancel')
    with pytest.raises(calib.CalibrationCancelled):
        calib.run_calibration_session(sess_id, storage_root=calib_tmp)
    marker.unlink()

    # 6. run_calibration_session: cancel_requested during active_manifest
    mf['status'] = 'queued'
    calib._write_manifest(sess, mf)

    def trigger_cancel(*args, **kwargs):
        with calib._file_lock(calib._session_lock_path(sess)):
            m = calib._read_manifest(sess)
            m['status'] = 'cancel_requested'
            calib._write_manifest(sess, m)
        raise calib.CalibrationCancelled()

    with mock.patch('indi_allsky.asi676mc_calibration_engine.calibrate_folder', side_effect=trigger_cancel):
        res = calib.run_calibration_session(sess_id, storage_root=calib_tmp)
        assert res is None

    # 7. run_calibration_session: worker token claim lost
    mf['status'] = 'queued'
    calib._write_manifest(sess, mf)

    def trigger_claim_lost(*args, **kwargs):
        with calib._file_lock(calib._session_lock_path(sess)):
            m = calib._read_manifest(sess)
            m['worker_token'] = 'other_worker'
            calib._write_manifest(sess, m)
        raise RuntimeError('dummy trigger')

    with mock.patch('indi_allsky.asi676mc_calibration_engine.calibrate_folder', side_effect=trigger_claim_lost):
        with pytest.raises(RuntimeError):
            calib.run_calibration_session(sess_id, storage_root=calib_tmp)

    # 8. run_calibration_session: background_full_retention without loader
    mf['status'] = 'queued'
    mf['source'] = {'kind': 'database', 'selection_mode': 'background_full_retention'}
    mf['files'] = []
    calib._write_manifest(sess, mf)
    with pytest.raises(calib.CalibrationSessionError, match='requires a retained-FITS loader'):
        calib.run_calibration_session(sess_id, storage_root=calib_tmp, database_loader=None)


def test_asi676mc_manifest_and_session_edge_cases(calib_tmp):
    # 1. _atomic_write_json temp unlink FileNotFoundError
    with mock.patch('tempfile.NamedTemporaryFile') as mock_tmp:
        mock_file = mock.MagicMock()
        mock_file.name = str(calib_tmp / 'temp.tmp')
        mock_tmp.return_value.__enter__.return_value = mock_file
        with mock.patch('os.replace', side_effect=RuntimeError('replace fail')):
            with mock.patch.object(Path, 'unlink', side_effect=FileNotFoundError):
                with pytest.raises(RuntimeError):
                    calib._atomic_write_json(calib_tmp / 'atomic.json', {'a': 1})

    # 2. _write_manifest cancelled conflict
    sess_id = 'a1' * 16
    sess_dir = calib_tmp / sess_id
    sess_dir.mkdir()
    marker = calib._cancel_marker_path(sess_dir)
    marker.write_text('cancel')
    with pytest.raises(calib.CalibrationSessionError, match='cancelled'):
        calib._write_manifest(sess_dir, {'status': 'uploading'})
    marker.unlink()

    # 3. cleanup_expired_sessions with symlink or file matching session regex
    file_sess = calib_tmp / ('b1' * 16)
    file_sess.write_text('file')
    assert calib.cleanup_expired_sessions(calib_tmp) >= 0

    # 4. create_session with invalid updated_utc or damaged manifest
    old_sess = calib_tmp / ('c1' * 16)
    old_sess.mkdir()
    (old_sess / 'manifest.json').write_text('{"status": "uploading", "updated_utc": "invalid_date"}')
    bad_sess = calib_tmp / ('d1' * 16)
    bad_sess.mkdir()
    (bad_sess / 'manifest.json').write_text('invalid json')
    new_mf = calib.create_session('user1', storage_root=calib_tmp)
    assert new_mf['session_id'] is not None

    # 5. database_search_checkpoint not uploading
    s_id = new_mf['session_id']
    s_dir = calib_tmp / s_id
    new_mf['status'] = 'running'
    calib._write_manifest(s_dir, new_mf)
    with pytest.raises(calib.CalibrationSessionError, match='already finished or stopped'):
        calib.database_search_checkpoint(s_id, 'user1', calib_tmp)


def test_discover_evidence_edge_cases(tmp_path):
    # 1. Invalid max_pair_seconds
    with pytest.raises(calib.CalibrationSessionError, match='maximum pair separation'):
        calib.discover_full_retention_database_evidence([], [], 10, -5, {})
    with pytest.raises(calib.CalibrationSessionError, match='maximum pair separation'):
        calib.discover_full_retention_database_evidence([], [], 10, 5000, {})

    # 2. Corrupt / invalid records in fits_records
    sample_fits = tmp_path / 'sample.fits'
    sample_fits.write_bytes(b'SIMPLE  =                    T' + b' ' * 2850)
    records = [
        {'path': str(tmp_path / 'nonexistent.fits'), 'timestamp': 100.0, 'id': 1},  # OSError
        {'path': str(sample_fits), 'timestamp': 100.0, 'id': 2, 'camera_name': 'wrong_cam'},  # wrong camera
        {'path': str(sample_fits), 'timestamp': float('nan'), 'id': 3, 'camera_name': 'ZWO ASI676MC'},  # non-finite timestamp
    ]
    with pytest.raises(calibration_engine.CalibrationError, match='no eligible ASI676MC FITS'):
        calib.discover_full_retention_database_evidence(records, [], 10, 60, {})

    # 3. bad_frames with allow_standard=False and compatibility_key None
    valid_record = {
        'path': str(sample_fits),
        'timestamp': 100.0,
        'id': 10,
        'camera_name': 'ZWO ASI676MC',
        'exposure': 5.0,
        'gain': 100.0,
        'binmode': 1,
        'width': 1000,
        'height': 1000,
        'size': len(sample_fits.read_bytes()),
        'roles': ['bad'],
    }
    bad_frames = [
        {'timestamp': 'bad'},  # invalid
        {'timestamp': 100.0, 'exposure': 5.0, 'gain': 100.0, 'allow_standard': False},  # matches valid_record
    ]
    with mock.patch('indi_allsky.asi676mc_calibration._database_compatibility_key', return_value=None):
        with pytest.raises(calibration_engine.CalibrationError, match='exhausted: only 0 compatible FITS'):
            calib.discover_full_retention_database_evidence([valid_record], bad_frames, 10, 60, {})


def test_discover_inspection_errors_and_populations(tmp_path):
    sample_fits = tmp_path / 'sample_good.fits'
    sample_fits.write_bytes(b'SIMPLE  =                    T' + b' ' * 2850)
    record = {
        'path': str(sample_fits),
        'timestamp': 100.0,
        'id': 11,
        'camera_name': 'ZWO ASI676MC',
        'exposure': 5.0,
        'gain': 100.0,
        'binmode': 1,
        'width': 1000,
        'height': 1000,
        'size': len(sample_fits.read_bytes()),
        '_signature_metadata_usable': True,
        'signature': {'ratio1': 1.0},
    }

    # RepairedFitsError raise (caught as recoverable error in loop)
    with mock.patch('indi_allsky.asi676mc_calibration_engine.inspect_fits_metadata', side_effect=calibration_engine.RepairedFitsError('repaired')):
        with pytest.raises(calibration_engine.CalibrationError, match='exhausted: only 0 compatible FITS'):
            calib.discover_full_retention_database_evidence([record], [], 10, 60, {})

    # Unrecoverable error raise vs Recoverable error rejected count
    with mock.patch('indi_allsky.asi676mc_calibration_engine.inspect_fits_metadata', side_effect=RuntimeError('fatal')):
        with pytest.raises(RuntimeError):
            calib.discover_full_retention_database_evidence([record], [], 10, 60, {})

    # Less than minimum * 2 inspected
    mock_frame = mock.MagicMock(is_bad=False, timestamp=100.0, exposure=5.0, path=sample_fits)
    with mock.patch('indi_allsky.asi676mc_calibration_engine.inspect_fits_metadata', return_value=mock_frame):
        with pytest.raises(calibration_engine.CalibrationError, match='exhausted: only 1 compatible FITS'):
            calib.discover_full_retention_database_evidence([record], [], 10, 60, {})


def test_staging_and_copy_edge_cases(calib_tmp, tmp_path):
    # 1. _copy_database_file cancel_marker after loop and partial.unlink FileNotFoundError
    src = tmp_path / 'src.fits'
    src.write_bytes(b'DATA')
    dst = calib_tmp / 'dst.fits'
    marker_mock = mock.MagicMock()
    marker_mock.exists.side_effect = [False, True]
    orig_unlink = Path.unlink
    def selective_unlink(self, *args, **kwargs):
        if str(self).endswith('.part'):
            raise FileNotFoundError()
        return orig_unlink(self, *args, **kwargs)

    with mock.patch.object(Path, 'unlink', side_effect=selective_unlink, autospec=True):
        with pytest.raises(calib.CalibrationSessionError, match='cancelled'):
            calib._copy_database_file(src, dst, marker_mock)

    # 2. _stage_database_files_unlocked rejections
    sess = calib.create_session('user1', storage_root=calib_tmp)
    sid = sess['session_id']
    sdir = calib_tmp / sid

    f_small = tmp_path / 'f_small.fits'
    f_small.write_bytes(b'SMALL')
    rec_os_err = {'path': str(f_small), 'id': 1, 'camera_name': 'ZWO ASI676MC'}
    orig_stat = Path.stat

    def failing_stat(self, *args, **kwargs):
        if self.name == 'f_small.fits':
            raise OSError('perm')
        return orig_stat(self, *args, **kwargs)

    def huge_stat(self, *args, **kwargs):
        if self.name == 'f_huge.fits':
            return os.stat_result((stat.S_IFREG | 0o644, 1, 1, 1, 1000, 1000, calib.MAX_FILE_BYTES + 100, 0, 0, 0))
        return orig_stat(self, *args, **kwargs)

    def db_max_stat(self, *args, **kwargs):
        if self.name == 'f_huge.fits':
            return os.stat_result((stat.S_IFREG | 0o644, 1, 1, 1, 1000, 1000, calib.DATABASE_MAX_BYTES + 100, 0, 0, 0))
        return orig_stat(self, *args, **kwargs)

    with mock.patch.object(Path, 'stat', side_effect=failing_stat, autospec=True):
        with pytest.raises(calib.CalibrationSessionError, match='became unavailable'):
            calib._stage_database_files_unlocked(sid, 'user1', [rec_os_err], storage_root=calib_tmp)

    f_huge = tmp_path / 'f_huge.fits'
    f_huge.write_bytes(b'H')
    rec_huge = {'path': str(f_huge), 'id': 2, 'camera_name': 'ZWO ASI676MC'}
    with mock.patch.object(Path, 'stat', side_effect=huge_stat, autospec=True):
        with pytest.raises(calib.CalibrationSessionError, match='became unavailable'):
            calib._stage_database_files_unlocked(sid, 'user1', [rec_huge], storage_root=calib_tmp)

    with mock.patch.object(Path, 'stat', side_effect=db_max_stat, autospec=True):
        with pytest.raises(calib.CalibrationSessionError, match='became unavailable'):
            calib._stage_database_files_unlocked(sid, 'user1', [rec_huge], storage_root=calib_tmp)

    # os.link and copy fail with OSError
    rec_valid = {'path': str(f_small), 'id': 3, 'camera_name': 'ZWO ASI676MC'}
    with mock.patch('os.link', side_effect=OSError('link error')):
        with mock.patch('indi_allsky.asi676mc_calibration._copy_database_file', side_effect=OSError('copy error')):
            with pytest.raises(calib.CalibrationSessionError, match='became unavailable'):
                calib._stage_database_files_unlocked(sid, 'user1', [rec_valid], storage_root=calib_tmp)


def test_upload_and_queue_edge_cases(calib_tmp):
    # 1. _store_upload_unlocked cancelled & unlink FileNotFoundError
    sess = calib.create_session('user1', storage_root=calib_tmp)
    sid = sess['session_id']
    sdir = calib_tmp / sid

    # Cancelled upload & unlink FileNotFoundError
    marker = calib._cancel_marker_path(sdir)
    marker.write_text('cancel')
    mock_valid = mock.Mock(
        filename='valid.fits',
        stream=io.BytesIO(b'SIMPLE  =' + b' ' * 72 + b'EXTRA_DATA'),
    )
    orig_unlink = Path.unlink
    def selective_unlink(self, *args, **kwargs):
        if str(self).endswith('.part'):
            raise FileNotFoundError()
        return orig_unlink(self, *args, **kwargs)

    with mock.patch.object(Path, 'unlink', side_effect=selective_unlink, autospec=True):
        with pytest.raises(calib.CalibrationUploadError, match='cancelled'):
            calib._store_upload_unlocked(sid, 'user1', mock_valid, storage_root=calib_tmp)
    marker.unlink()

    # 2. _cancel_session_unlocked running status and chmod OSError
    sess['status'] = 'running'
    calib._write_manifest(sdir, sess)
    orig_chmod = Path.chmod
    def failing_chmod(self, *args, **kwargs):
        if '.cancel' in str(self):
            raise OSError('perm')
        return orig_chmod(self, *args, **kwargs)

    with mock.patch.object(Path, 'chmod', side_effect=failing_chmod, autospec=True):
        res_cancel = calib._cancel_session_unlocked(sid, 'user1', storage_root=calib_tmp)
        assert res_cancel['status'] == 'cancel_requested'

    with mock.patch.object(Path, 'chmod', side_effect=failing_chmod, autospec=True):
        calib.cancel_session(sid, 'user1', storage_root=calib_tmp)

    # 3. _mark_queued_unlocked invalid max_pair_seconds and settings error
    sess2 = calib.create_session('user1', storage_root=calib_tmp)
    sid2 = sess2['session_id']
    sdir2 = calib_tmp / sid2
    sess2['status'] = 'uploading'
    sess2['files'] = [{'name': f'f{i}.fits'} for i in range(15)]
    calib._write_manifest(sdir2, sess2)
    with pytest.raises(calib.CalibrationSessionError, match='maximum gap'):
        calib._mark_queued_unlocked(sid2, 'user1', 1, 0, {}, storage_root=calib_tmp)

    with mock.patch('indi_allsky.asi676mc.normalize_settings', side_effect=ValueError('bad settings')):
        with pytest.raises(calib.CalibrationSessionError, match='settings are invalid'):
            calib._mark_queued_unlocked(sid2, 'user1', 1, 60, {}, storage_root=calib_tmp)


def test_reports_and_helpers_coverage(calib_tmp):
    # 1. _build_population_previews error handling
    with mock.patch('indi_allsky.asi676mc_calibration._population_preview_candidates', side_effect=KeyError('bad key')):
        assert calib._build_population_previews({'population_evidence': [{'name': 'a'}]}, calib_tmp, mock.Mock()) == []

    # staged_name with path traversal
    candidates = [{'name': '../outside.fits'}]
    with mock.patch('indi_allsky.asi676mc_calibration._population_preview_candidates', return_value=candidates):
        assert calib._build_population_previews({}, calib_tmp, mock.Mock()) == []

    # 2. _result_warnings branches
    w1 = calib._result_warnings({
        'marginal_exclusions': [{'name': 'f1', 'improvement_vs_gain_only': 0.1, 'required_improvement': 0.2}],
        'replacement_group_count': 0,
        'requested_group_count': None,
        'used_group_count': 5,
        'search_stopped_early': True,
        'scanned_file_count': 10,
        'available_file_count': 20,
        'matched_bad_count': 7,
        'two_sided_count': 0,  # one_sided_count == matched_count
        'matched_normal_count': 7,
    }, source_details={'kind': 'database', 'selection_mode': 'full_retention_population_groups'})
    assert any('The remaining evidence was sufficient' in w for w in w1)
    assert any('found another likely group' in w for w in w1)
    assert any('All 7 purple frames had one nearby normal reference' in w for w in w1)

    w2 = calib._result_warnings({
        'matched_bad_count': 10,
        'two_sided_count': 2,
        'matched_normal_count': 14,
    })
    assert any('more complete normal/purple/normal groups would improve confidence' in w for w in w2)

    # 3. _rejection_summary and _friendly_threshold_analysis_failure
    assert calib._rejection_summary('prefix Rejection summary: invalid json') == {}
    assert calib._rejection_summary('prefix Rejection summary: [1, 2]') == {}
    assert calib._rejection_summary('prefix Rejection summary: {"r1": "bad"}') == {}

    f1 = calib._friendly_threshold_analysis_failure('matched purple frames found in data')
    assert f1 is not None
    f2 = calib._friendly_threshold_analysis_failure('evidence cover only one exposure setting')
    assert 'only one exposure' in f2
    f3 = calib._friendly_threshold_analysis_failure('unrecognized reason')
    assert 'safe threshold suggestion' in f3

    # 4. task_failure_message & _format_report_value
    assert calib.task_failure_message('validation_failed: img.fits: measurement 0.5', limit=60) == 'Could not verify img.fits: measurement 0.5.'
    assert calib.task_failure_message('validation_failed: img.fits: measurement 0.5', limit=20) == 'Could not verify im…'
    assert calib.task_failure_message('some very long failure without pattern that exceeds limit', limit=15) == 'Calibration cou'
    assert calib._format_report_value(True) == 'Yes'
    assert calib._format_report_value(False) == 'No'

    # 5. format_threshold_suggestion_report with detected_bad_count >= 7, population_evidence, full_retention_, rejected_files
    thresh_payload = {
        'outcome': 'threshold_suggestion',
        'generated_utc': '2026-01-01T00:00:00Z',
        'quality': {'detected_bad_count': 8, 'likely_purple_count': 8, 'likely_normal_count': 8, 'pair_count': 8, 'unique_good_count': 8, 'two_sided_count': 8, 'exposure_levels': [1.0]},
        'threshold_suggestions': [{'metric': 'purple_ratio', 'label': 'Purple Ratio', 'normal_max': 1.0, 'purple_min': 2.0, 'change_recommended': True, 'current': 1.5, 'suggested': 1.8}],
        'signature_ranges': {'purple_ratio': {'good_min': 0.5, 'good_max': 1.0, 'bad_min': 2.0, 'bad_max': 2.5}},
        'population_evidence': [{'population': 'likely_purple', 'timestamp_utc': '2026-01-01T00:00:00Z', 'name': 'img1.fits', 'purple_ratio': 2.1, 'red_side_ratio': 1.1, 'blue_side_ratio': 1.1}],
        'rejected_files': [{'name': 'bad1.fits', 'reason': 'unreadable'}],
    }
    thresh_manifest = {
        'max_pair_seconds': 60.0,
        'source': {'kind': 'database', 'selection_mode': 'full_retention_detector_groups'},
        'files': [{'name': 'img1.fits', 'original_name': 'orig_img1.fits'}],
    }
    report_t = calib.format_threshold_suggestion_report(thresh_payload, thresh_manifest)
    assert 'The combined detector identified enough purple frames' in report_t
    assert 'Population examples to verify' in report_t
    assert 'The background search inspected the complete retained archive' in report_t
    assert 'Rejected FITS details' in report_t

    # 6. format_failure_report when not cleanup_complete
    fail_manifest = {
        'source': {'kind': 'database'},
        'sources_deleted_utc': None,  # not cleanup_complete
        'files': [],
    }
    fail_rep = calib.format_failure_report('failed', fail_manifest)
    assert 'could not be removed immediately' in fail_rep

    # 7. format_integrated_report with missing configured_values key, non-db/upload source, no notes, gain_estimates skip, assessment text
    int_payload = {
        'outcome': 'calibrated',
        'generated_utc': '2026-01-01T00:00:00Z',
        'derived_settings': {k: 1.0 for k in calib.DERIVED_VALUE_KEYS},
        'comparison': {'configured_values': {}, 'differing_keys': []},  # key not in configured_values
        'quality': {
            'matched_bad_count': 7,
            'pair_count': 7,
            'two_sided_count': 7,
            'unique_good_count': 7,
            'good_bad_ratio': 1.0,
            'exposure_levels': [1.0],
            'rejected_file_count': 0,
            'highlight_sample_count': 0,
        },
        'gain_estimates': {'GAIN_R': None},  # empty estimate skipped
        'signature_ranges': {'purple_ratio': {'good_min': 0.5, 'good_max': 1.0, 'bad_min': 2.0, 'bad_max': 2.5}},
        'threshold_assessment': [{'metric': 'purple_ratio', 'label': 'Purple Ratio', 'normal_max': 1.0, 'current': 1.2, 'purple_min': 2.0, 'suggested': 1.5, 'marginal': True}],
    }
    int_manifest = {
        'source': {'kind': 'other'},  # not db or upload
        'files': [],
        'settings': {},
    }
    with mock.patch('indi_allsky.asi676mc_calibration.compare_result_to_configuration', return_value={'status': 'unavailable', 'configured_values': {}, 'differing_keys': []}):
        int_rep = calib.format_integrated_report(int_payload, int_manifest)
        assert 'Unavailable' in int_rep
        assert 'Method: Tools > Fix ASI676MC purple frames' in int_rep
        assert 'gap midpoint 1.500' in int_rep

    # 8. run_calibration_session signature saver exception and failure report write failure
    sess = calib.create_session('user1', storage_root=calib_tmp)
    sid = sess['session_id']
    sdir = calib_tmp / sid
    sess['status'] = 'queued'
    sess['max_pair_seconds'] = 60.0
    sess['source'] = {'kind': 'database', 'selection_mode': 'background_full_retention'}
    calib._write_manifest(sdir, sess)

    def progress_loader(source_details, progress_cb):
        progress_cb({'phase': 'loading', 'processed_files': 1, 'total_files': 100})
        progress_cb({'phase': 'loading', 'processed_files': 2, 'total_files': 100})
        progress_cb({'phase': 'loading', 'processed_files': 100, 'total_files': 100})
        progress_cb({'phase': 'loading', 'processed_files': 25, 'total_files': 100})
        return {'fits_records': [], 'bad_frames': []}

    bad_saver = mock.Mock(side_effect=RuntimeError('db err'))

    def fake_discover(*args, **kwargs):
        if kwargs.get('signature_callback'):
            kwargs['signature_callback'](101, {'purple_ratio': 2.0})
        return [], {'legacy_signature_cached_count': 0}

    orig_write_text = Path.write_text

    def selective_write_text(self, data, *args, **kwargs):
        if self.name == 'asi676mc_calibration_report.txt':
            raise OSError('disk full on report')
        return orig_write_text(self, data, *args, **kwargs)

    with mock.patch('indi_allsky.asi676mc_calibration.discover_full_retention_database_evidence', side_effect=fake_discover):
        with mock.patch('indi_allsky.asi676mc_calibration.stage_database_files_for_worker'):
            with mock.patch('indi_allsky.asi676mc_calibration_engine.calibrate_folder', side_effect=RuntimeError('engine fail')):
                with mock.patch.object(Path, 'write_text', side_effect=selective_write_text, autospec=True):
                    with mock.patch('indi_allsky.asi676mc_calibration._remove_upload_dir', side_effect=OSError('cleanup fail')):
                        with pytest.raises(RuntimeError):
                            calib.run_calibration_session(sid, storage_root=calib_tmp, database_loader=progress_loader, database_signature_saver=bad_saver)

    # Missing database_loader on background_full_retention
    sess_nl = calib.create_session('user1', storage_root=calib_tmp)
    sid_nl = sess_nl['session_id']
    sdir_nl = calib_tmp / sid_nl
    sess_nl['status'] = 'queued'
    sess_nl['max_pair_seconds'] = 60.0
    sess_nl['source'] = {'kind': 'database', 'selection_mode': 'background_full_retention'}
    calib._write_manifest(sdir_nl, sess_nl)
    with pytest.raises(calib.CalibrationSessionError, match='requires a retained-FITS loader'):
        calib.run_calibration_session(sid_nl, storage_root=calib_tmp)

    # 9. run_calibration_session signature saver success, active_manifest cancel_requested and lost claim, population_evidence rename
    sess2 = calib.create_session('user1', storage_root=calib_tmp)
    sid2 = sess2['session_id']
    sdir2 = calib_tmp / sid2
    sess2['status'] = 'queued'
    sess2['max_pair_seconds'] = 60.0
    sess2['source'] = {'kind': 'database', 'selection_mode': 'background_full_retention'}
    calib._write_manifest(sdir2, sess2)

    good_saver = mock.Mock()
    mock_payload = {
        'outcome': 'calibrated',
        'generated_utc': '2026-01-01T00:00:00Z',
        'derived_settings': {k: 1.0 for k in calib.DERIVED_VALUE_KEYS},
        'comparison': {'configured_values': {k: 1.0 for k in calib.DERIVED_VALUE_KEYS}, 'differing_keys': []},
        'quality': {
            'matched_bad_count': 7,
            'pair_count': 7,
            'two_sided_count': 7,
            'unique_good_count': 7,
            'good_bad_ratio': 1.0,
            'exposure_levels': [1.0],
            'rejected_file_count': 0,
            'highlight_sample_count': 0,
        },
        'population_evidence': [{'name': 'orig_name.fits', 'population': 'likely_purple'}],
    }

    with mock.patch('indi_allsky.asi676mc_calibration.discover_full_retention_database_evidence', side_effect=fake_discover):
        with mock.patch('indi_allsky.asi676mc_calibration.stage_database_files_for_worker'):
            with mock.patch('indi_allsky.asi676mc_calibration_engine.calibrate_folder', return_value=mock_payload):
                res = calib.run_calibration_session(sid2, storage_root=calib_tmp, database_loader=progress_loader, database_signature_saver=good_saver)
                assert res is not None

    # Upload kind session calibration
    sess_up = calib.create_session('user1', storage_root=calib_tmp)
    sid_up = sess_up['session_id']
    sdir_up = calib_tmp / sid_up
    sess_up['status'] = 'queued'
    sess_up['max_pair_seconds'] = 60.0
    sess_up['source'] = {'kind': 'upload'}
    sess_up['camera'] = {'name': 'ZWO ASI676MC'}
    sess_up['files'] = [{'name': '000001_up.fits', 'original_name': 'orig_up.fits', 'size': 1000}]
    calib._write_manifest(sdir_up, sess_up)
    with mock.patch('indi_allsky.asi676mc_calibration_engine.calibrate_folder', return_value=mock_payload):
        res_up = calib.run_calibration_session(sid_up, storage_root=calib_tmp)
        assert res_up is not None

    # Reports with upload and non-full retention modes
    thresh_upload = {
        'outcome': 'threshold_suggestion',
        'generated_utc': '2026-01-01T00:00:00Z',
        'quality': {'detected_bad_count': 1, 'likely_purple_count': 8, 'likely_normal_count': 8, 'pair_count': 8, 'unique_good_count': 8, 'two_sided_count': 8, 'exposure_levels': [1.0]},
        'threshold_suggestions': [{'metric': 'purple_ratio', 'label': 'Purple Ratio', 'normal_max': 1.0, 'purple_min': 2.0, 'change_recommended': False, 'current': 1.5, 'suggested': 1.5}],
        'signature_ranges': {'purple_ratio': {'good_min': 0.5, 'good_max': 1.0, 'bad_min': 2.0, 'bad_max': 2.5}},
    }
    rep_u = calib.format_threshold_suggestion_report(thresh_upload, {'source': {'kind': 'upload'}, 'files': [{'name': 'f.fits'}]})
    assert 'Manual FITS upload' in rep_u

    rep_f1 = calib.format_failure_report('failed', {'source': {'kind': 'upload'}, 'sources_deleted_utc': '2026-01-01T00:00:00Z', 'files': []})
    assert 'Manual FITS upload' in rep_f1
    assert 'The private uploaded copies were removed.' in rep_f1

    rep_f2 = calib.format_failure_report('failed', {'source': {'kind': 'upload'}, 'sources_deleted_utc': None, 'files': []})
    assert 'could not be removed immediately' in rep_f2

    int_u_payload = dict(mock_payload)
    int_u_payload['quality'] = dict(mock_payload['quality'])
    int_u_payload['quality']['bound_session_camera_count'] = 3
    int_u_payload['quality']['highlight_score'] = 0.01
    int_u_payload['quality']['highlight_default_score'] = 0.02
    int_u_payload['quality']['highlight_raw_best_start_ratio'] = 0.5
    int_u_payload['quality']['highlight_raw_best_end_ratio'] = 0.8
    int_u_payload['quality']['highlight_raw_best_score'] = 0.01
    int_u_payload['quality']['highlight_preferred_default'] = True
    int_u_payload['quality']['highlight_runner_up_score'] = 0.03
    int_u_payload['quality']['source_saturation_plateau'] = 65000
    int_u_payload['signature_ranges'] = {'purple_ratio': {'good_min': 0.5, 'good_max': 1.0, 'bad_min': 2.0, 'bad_max': 2.5}}
    rep_int_u = calib.format_integrated_report(int_u_payload, {'source': {'kind': 'upload'}, 'files': [{'name': 'f.fits'}]})
    assert 'selected camera binding for 3 uploaded files' in rep_int_u
    assert 'Highlight blend fit details' in rep_int_u

    rep_int_db_prog = calib.format_integrated_report(int_u_payload, {
        'source': {'kind': 'database', 'selection_mode': 'progressive_search', 'staged_group_count': 5},
        'files': [{'name': 'f.fits'}],
    })
    assert 'compact evidence set' in rep_int_db_prog
    assert 'Purple-frame groups staged: 5' in rep_int_db_prog

    # active_manifest cancel_requested and worker claim lost
    sess3 = calib.create_session('user1', storage_root=calib_tmp)
    sid3 = sess3['session_id']
    sdir3 = calib_tmp / sid3
    sess3['status'] = 'queued'
    sess3['max_pair_seconds'] = 60.0
    calib._write_manifest(sdir3, sess3)

    def cancel_on_calibrate(*args, **kwargs):
        m = calib._read_manifest(sdir3)
        m['status'] = 'cancel_requested'
        calib._write_manifest(sdir3, m)
        kwargs['checkpoint_callback']()

    with mock.patch('indi_allsky.asi676mc_calibration_engine.calibrate_folder', side_effect=cancel_on_calibrate):
        res_c = calib.run_calibration_session(sid3, storage_root=calib_tmp)
        assert res_c is None

    sess4 = calib.create_session('user1', storage_root=calib_tmp)
    sid4 = sess4['session_id']
    sdir4 = calib_tmp / sid4
    sess4['status'] = 'queued'
    sess4['max_pair_seconds'] = 60.0
    calib._write_manifest(sdir4, sess4)

    def steal_worker_claim(*args, **kwargs):
        m = calib._read_manifest(sdir4)
        m['worker_token'] = 'stolen_token'
        calib._write_manifest(sdir4, m)
        kwargs['checkpoint_callback']()

    with mock.patch('indi_allsky.asi676mc_calibration_engine.calibrate_folder', side_effect=steal_worker_claim):
        with pytest.raises(calib.CalibrationSessionError, match='claim was lost'):
            calib.run_calibration_session(sid4, storage_root=calib_tmp)


def test_more_discovery_and_copy_edge_cases(tmp_path, calib_tmp):
    # 1. allow_standard=True and duplicate standard ids with compatibility_key
    sample_fits = tmp_path / 'sample.fits'
    sample_fits.write_bytes(b'SIMPLE  =                    T' + b' ' * 2850)
    rec1 = {
        'path': str(sample_fits),
        'timestamp': 100.0,
        'id': 10,
        'camera_name': 'ZWO ASI676MC',
        'exposure': 5.0,
        'gain': 100.0,
        'binmode': 1,
        'width': 1000,
        'height': 1000,
        'size': len(sample_fits.read_bytes()),
        'roles': [{'role': 'bad'}],
    }
    rec2 = {
        'path': str(sample_fits),
        'timestamp': 100.0,
        'id': 11,
        'camera_name': 'ZWO ASI676MC',
        'exposure': 5.0,
        'gain': 100.0,
        'binmode': 1,
        'width': 1000,
        'height': 1000,
        'size': len(sample_fits.read_bytes()),
    }
    rec3 = {
        'path': str(sample_fits),
        'timestamp': 100.0,
        'id': 12,
        'camera_name': 'ZWO ASI676MC',
        'exposure': 5.0,
        'gain': 100.0,
        'binmode': 1,
        'width': 1000,
        'height': 1000,
        'size': len(sample_fits.read_bytes()),
        'roles': [{'role': 'bad'}],
    }
    bad_frames = [
        {'timestamp': 100.0, 'exposure': 5.0, 'gain': 100.0, 'allow_standard': True},
    ]
    key_values = [None, 'key1', 'key1']
    with mock.patch('indi_allsky.asi676mc_calibration._database_compatibility_key', side_effect=lambda r: key_values.pop(0) if key_values else 'key1'):
        with pytest.raises(calibration_engine.CalibrationError, match='exhausted: only 0 compatible FITS'):
            calib.discover_full_retention_database_evidence([rec1, rec2, rec3], bad_frames, 10, 60, {})

    # 2. infer_detection_populations raises CalibrationError in discover_full_retention_database_evidence
    mock_frame = mock.MagicMock(is_bad=False, timestamp=100.0, exposure=5.0, path=sample_fits)
    with mock.patch('indi_allsky.asi676mc_calibration_engine.inspect_fits', return_value=mock_frame):
        with mock.patch('indi_allsky.asi676mc_calibration_engine.match_pairs', return_value=([], [])):
            with mock.patch('indi_allsky.asi676mc_calibration_engine.infer_detection_populations', side_effect=calibration_engine.CalibrationError('pop error')):
                with pytest.raises(calibration_engine.CalibrationError, match='neither the configured detector nor population analysis'):
                    records = [{
                        'path': str(sample_fits),
                        'timestamp': 100.0 + i,
                        'id': 20 + i,
                        'camera_name': 'ZWO ASI676MC',
                        'exposure': 5.0,
                        'gain': 100.0,
                        'binmode': 1,
                        'width': 1000,
                        'height': 1000,
                        'size': len(sample_fits.read_bytes()),
                    } for i in range(15)]
                    calib.discover_full_retention_database_evidence(records, [], 10, 60, {})

    # 3. validate_evidence raises CalibrationError and seeded exposures continue and duplicate group records
    exposures = [5.0, 5.0, 10.0, 5.0, 10.0, 15.0, 20.0]
    pairs_list = [
        mock.MagicMock(
            bad=mock.MagicMock(timestamp=200.0 - i, exposure=exposures[i], path=sample_fits),
            references=[mock.MagicMock(path=sample_fits)],
        )
        for i in range(7)
    ]
    with mock.patch('indi_allsky.asi676mc_calibration_engine.inspect_fits', return_value=mock_frame):
        with mock.patch('indi_allsky.asi676mc_calibration_engine.infer_detection_populations', return_value=[mock_frame] * 15):
            with mock.patch('indi_allsky.asi676mc_calibration_engine.match_pairs', return_value=(pairs_list, [])):
                with mock.patch('indi_allsky.asi676mc_calibration_engine.validate_evidence', side_effect=calibration_engine.CalibrationError('invalid evidence')):
                    with pytest.raises(calibration_engine.CalibrationError, match='could not satisfy calibration requirements'):
                        calib.discover_full_retention_database_evidence(records, [], 10, 60, {})

    # 4. _copy_database_file cancel_marker check after read loop
    src = tmp_path / 'source_f.fits'
    src.write_bytes(b'FITS_DATA')
    dst = calib_tmp / 'dest_f.fits'
    marker_mock = mock.MagicMock()
    marker_mock.exists.side_effect = [False, False, True]
    with pytest.raises(calib.CalibrationSessionError, match='cancelled'):
        calib._copy_database_file(src, dst, marker_mock)

    # 5. _store_upload_unlocked cancel marker check after read loop
    sess_u = calib.create_session('user_u1', storage_root=calib_tmp)
    sid_u = sess_u['session_id']
    mock_upload = mock.Mock(
        filename='up.fits',
        stream=io.BytesIO(b'SIMPLE  =' + b' ' * 72),
    )
    with mock.patch('indi_allsky.asi676mc_calibration._cancel_marker_path') as mock_cmp:
        mock_cmp.return_value.exists.side_effect = [False, False, False, True]
        with pytest.raises(calib.CalibrationUploadError, match='this calibration upload was cancelled'):
            calib._store_upload_unlocked(sid_u, 'user_u1', mock_upload, storage_root=calib_tmp)
    calib.cancel_session(sid_u, 'user_u1', storage_root=calib_tmp)

    # 5b. _store_upload_unlocked partial.unlink FileNotFoundError
    sess_u_fnf = calib.create_session('user_u2', storage_root=calib_tmp)
    sid_u_fnf = sess_u_fnf['session_id']
    mock_upload_fnf = mock.Mock(
        filename='bad_file.fits',
        stream=io.BytesIO(b'NOT_A_FITS_HEADER'),
    )
    orig_unlink = Path.unlink
    def selective_unlink_fnf(self, *args, **kwargs):
        if str(self).endswith('.part'):
            raise FileNotFoundError()
        return orig_unlink(self, *args, **kwargs)
    with mock.patch.object(Path, 'unlink', side_effect=selective_unlink_fnf, autospec=True):
        with pytest.raises(calib.CalibrationUploadError, match='does not appear to be a FITS'):
            calib._store_upload_unlocked(sid_u_fnf, 'user_u2', mock_upload_fnf, storage_root=calib_tmp)
    calib.cancel_session(sid_u_fnf, 'user_u2', storage_root=calib_tmp)

    # 6. progressive search warnings
    pw = calib._result_warnings({
        'scanned_file_count': 10,
        'available_file_count': 20,
        'search_stopped_early': True,
    }, source_details={'kind': 'database', 'selection_mode': 'progressive_search'})
    assert any('found enough files after checking 10 of 20' in w for w in pw)

    # 7. _stage_database_files_unlocked total_bytes limit
    sess_s = calib.create_session('user_stage', storage_root=calib_tmp)
    sid_s = sess_s['session_id']
    f_h1 = tmp_path / 'f_h1.fits'
    f_h1.write_bytes(b'H1' * 50)
    f_h2 = tmp_path / 'f_h2.fits'
    f_h2.write_bytes(b'H2' * 50)
    rec_h1 = {'path': str(f_h1), 'id': 101, 'camera_name': 'ZWO ASI676MC'}
    rec_h2 = {'path': str(f_h2), 'id': 102, 'camera_name': 'ZWO ASI676MC'}
    orig_stat = Path.stat
    def staged_stat(self, *args, **kwargs):
        if self.name in ('f_h1.fits', 'f_h2.fits'):
            return os.stat_result((stat.S_IFREG | 0o644, 1, 1, 1, 1000, 1000, 100, 0, 0, 0))
        return orig_stat(self, *args, **kwargs)
    with mock.patch('indi_allsky.asi676mc_calibration.DATABASE_MAX_BYTES', 150):
        with mock.patch.object(Path, 'stat', side_effect=staged_stat, autospec=True):
            staged_m = calib._stage_database_files_unlocked(sid_s, 'user_stage', [rec_h1, rec_h2], storage_root=calib_tmp)
            assert len(staged_m['files']) == 1
            assert staged_m['source']['staging_skipped_file_count'] == 1
            assert staged_m['source']['staging_rejection_counts']['selected FITS no longer fits staging limit'] == 1
    calib.cancel_session(sid_s, 'user_stage', storage_root=calib_tmp)

    # 8. cancel_session and _cancel_session_unlocked chmod OSError
    sess_chmod = calib.create_session('user_chmod1', storage_root=calib_tmp)
    sid_chmod = sess_chmod['session_id']
    sess_chmod2 = calib.create_session('user_chmod2', storage_root=calib_tmp)
    sid_chmod2 = sess_chmod2['session_id']
    def failing_chmod(*args, **kwargs):
        raise OSError('chmod failed')
    with mock.patch.object(Path, 'chmod', side_effect=failing_chmod):
        calib.cancel_session(sid_chmod, 'user_chmod1', storage_root=calib_tmp)
        calib._cancel_session_unlocked(sid_chmod2, 'user_chmod2', storage_root=calib_tmp)

    # 9. format_integrated_report with no warnings (line 3963)
    clean_payload = {
        'outcome': 'calibrated',
        'generated_utc': '2026-01-01T00:00:00Z',
        'derived_settings': {k: 1.0 for k in calib.DERIVED_VALUE_KEYS},
        'comparison': {'configured_values': {k: 1.0 for k in calib.DERIVED_VALUE_KEYS}, 'differing_keys': []},
        'quality': {
            'matched_bad_count': 7,
            'pair_count': 7,
            'two_sided_count': 7,
            'unique_good_count': 14,
            'matched_normal_count': 14,
            'good_bad_ratio': 2.0,
            'exposure_levels': [1.0],
            'rejected_file_count': 0,
            'highlight_sample_count': 0,
        },
    }
    clean_rep = calib.format_integrated_report(clean_payload, {'source': {'kind': 'upload'}, 'files': []})
    assert 'No additional warnings.' in clean_rep




