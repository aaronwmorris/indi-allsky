"""Exercise archive replacement through real FITS staging and the worker."""

from datetime import datetime, timedelta, timezone
from contextlib import nullcontext
import hashlib
from unittest import mock

from astropy.io import fits
import numpy
import pytest

from indi_allsky import asi676mc_calibration as web
from indi_allsky import asi676mc_calibration_engine as engine
from tests.core import test_asi676mc_calibration_engine as frame_fixtures


@pytest.fixture
def archive(tmp_path, request):
    normal = frame_fixtures.TestAsi676mcCalibrationEngine._normal_frame()
    bad = frame_fixtures.TestAsi676mcCalibrationEngine._bad_stream(normal)
    records = []
    for group in range(getattr(request, 'param', 16)):
        exposure = 0.001 if group % 2 else 0.002
        for role, offset, data in (
            ('before', 0, normal), ('bad', 20, bad), ('after', 40, normal),
        ):
            timestamp = datetime(2026, 7, 1, tzinfo=timezone.utc) + timedelta(
                seconds=300 * group + offset,
            )
            header = fits.Header({
                'DATE-OBS': timestamp.isoformat(), 'EXPTIME': exposure,
                'GAIN': 0.0, 'XBINNING': 1, 'YBINNING': 1,
                'BAYERPAT': 'RGGB', 'INSTRUME': 'ZWO CCD ASI676MC',
            })
            path = tmp_path / f'{group:02d}_{role}.fit'
            fits.PrimaryHDU(data=data, header=header).writeto(path)
            records.append({
                'id': len(records) + 1, 'path': path, 'size': path.stat().st_size,
                'timestamp': timestamp.timestamp(), 'exposure': exposure,
                'gain': 0.0, 'binmode': 1, 'width': 128, 'height': 128,
                'camera_name': 'ZWO CCD ASI676MC', 'roles': [],
            })
    return records


def start_session(tmp_path, records, target_groups=7):
    root = tmp_path / 'sessions'
    session = web.create_session('tester', storage_root=root)
    web.mark_queued(
        session['session_id'], 'tester', task_id=1, max_pair_seconds=90,
        settings=engine.DEFAULT_SETTINGS, storage_root=root,
        source_details={
            'kind': 'database', 'selection_mode': 'background_full_retention',
            'requested_group_count': target_groups, 'camera_name': 'ZWO CCD ASI676MC',
        },
    )
    return root, session['session_id'], lambda *_args: {
        'fits_records': records, 'bad_frames': [], 'source_details': {},
    }


@pytest.fixture
def small_frames(monkeypatch):
    """Speed up tiny FITS fixtures without relaxing fit-quality checks.

    Sample minima and the blend search grid are reduced only in these tests.
    The larger-image regression below separately exercises production defaults.
    """
    for key, value in {
        'MIN_GAIN_SAMPLES_PER_PARITY': 10, 'MIN_HIGHLIGHT_SAMPLES_TOTAL': 10,
        'MIN_HIGHLIGHT_SAMPLES_PER_PAIR': 1,
        'BLEND_START_VALUES': (0.50, 0.55, 0.60),
        'BLEND_END_VALUES': (0.70, 0.75, 0.80),
    }.items():
        monkeypatch.setitem(engine.CALIBRATION_OPTIONS, key, value)


def scored_validation(monkeypatch, reject):
    """Inject reproducible negative comparisons; keep real repair/validation."""
    validate = engine.validate_calibrated_frames
    attempts = []

    def run(pairs, settings, **kwargs):
        attempts.append([pair.bad.source_name for pair in pairs])
        repaired = normal = 0
        checks, failures = [], []
        for pair in pairs:
            if reject(pair.bad.source_name):
                with mock.patch.object(
                    engine, '_reference_error', side_effect=(0.49, 0.11, 0.085),
                ):
                    result = validate([pair], settings, **kwargs)
            else:
                result = validate([pair], settings, **kwargs)
            repaired += result[0]
            normal += result[1]
            checks.extend(result[2])
            failures.extend(result[3])
        return repaired, normal, checks, failures

    monkeypatch.setattr(engine, 'validate_calibrated_frames', run)
    return attempts


@pytest.fixture
def progress_updates(monkeypatch):
    updates = []
    write_manifest = web._write_manifest

    def record_progress(session_dir, manifest):
        updates.append(dict(manifest.get('progress') or {}))
        return write_manifest(session_dir, manifest)

    monkeypatch.setattr(web, '_write_manifest', record_progress)
    return updates


def test_replaces_more_than_three_negative_groups_and_refits(
    tmp_path, archive, small_frames, monkeypatch, progress_updates,
):
    hashes = {r['path']: hashlib.sha256(r['path'].read_bytes()).digest() for r in archive}
    # Five recent groups fail over several rounds, including one that was
    # outside the initial seven-plus-three set.
    rejected = {'15_bad.fit', '14_bad.fit', '13_bad.fit', '12_bad.fit', '05_bad.fit'}
    attempts = scored_validation(monkeypatch, lambda name: name in rejected)
    # Ten three-file groups fit, but the entire 16-group archive does not.
    monkeypatch.setattr(web, 'DATABASE_MAX_FILES', 30)
    monkeypatch.setattr(web, 'DATABASE_MAX_BYTES', sum(r['size'] for r in archive[:30]))
    root, session_id, loader = start_session(tmp_path, archive)
    result = web.run_calibration_session(session_id, storage_root=root, database_loader=loader)

    assert result['quality']['validated_bad_count'] == 7
    search = result['source']['validation_search']
    assert search['rejected_group_count'] == 5
    assert search['replacement_group_count'] == 5
    assert len(attempts) >= 3
    assert '05_bad.fit' in {name for attempt in attempts for name in attempt}
    assert not rejected.intersection(attempts[-1])
    assert search['candidate_group_count'] == 16
    assert search['remaining_candidate_group_count'] == 4
    assert not (root / session_id / 'uploads').exists()
    assert hashes == {path: hashlib.sha256(path.read_bytes()).digest() for path in hashes}
    report = (root / session_id / 'asi676mc_calibration_report.txt').read_text()
    assert 'Replacement groups selected: 5' in report
    exclusions = report.split('Frame groups set aside', 1)[1].split('Result notes', 1)[0]
    assert sum(line.startswith('- ') for line in exclusions.splitlines()) == 5
    assert ' '.join(exclusions.split()).count('increased the comparison error by 29.4%') == 5
    assert all(exclusions.count(name) == 1 for name in rejected)
    assert {'phase': 'replacing_groups', 'reason': 'evidence'} in progress_updates


def test_exhaustion_is_reported_with_counts_and_no_settings(
    tmp_path, archive, small_frames, monkeypatch,
):
    attempts = scored_validation(monkeypatch, lambda _name: True)
    root, session_id, loader = start_session(tmp_path, archive)
    with pytest.raises(engine.CalibrationError, match='no further suitable replacements'):
        web.run_calibration_session(session_id, storage_root=root, database_loader=loader)
    manifest = web._read_manifest(root / session_id)
    assert manifest['status'] == 'failed'
    assert manifest['source']['validation_search']['rejected_group_count'] == 14
    assert len(attempts) == 2
    assert not (root / session_id / 'result.json').exists()
    assert not (root / session_id / 'uploads').exists()
    report = (root / session_id / 'asi676mc_calibration_report.txt').read_text()
    assert 'no further suitable replacements' in report
    assert 'Groups rejected: 14' in report
    assert all(r['path'].is_file() for r in archive)


def test_replaces_lost_exposure_seed_with_oldest_suitable_group(
    tmp_path, archive, small_frames, monkeypatch,
):
    for record in archive:
        group = int(record['path'].name[:2])
        record['exposure'] = .002 if group in (0, 15) else .001
        with fits.open(record['path'], mode='update') as hdus:
            hdus[0].header['EXPTIME'] = record['exposure']
    attempts = scored_validation(monkeypatch, lambda name: name == '15_bad.fit')
    root, session_id, loader = start_session(tmp_path, archive)
    result = web.run_calibration_session(session_id, storage_root=root, database_loader=loader)
    assert '00_bad.fit' not in attempts[0]
    assert '00_bad.fit' in attempts[-1]
    assert result['quality']['exposure_level_count'] == 2


def test_can_finish_with_seven_when_archive_cannot_fill_requested_target(
    tmp_path, archive, small_frames, monkeypatch,
):
    attempts = scored_validation(monkeypatch, lambda name: int(name[:2]) >= 7)
    root, session_id, loader = start_session(tmp_path, archive, target_groups=9)
    result = web.run_calibration_session(session_id, storage_root=root, database_loader=loader)
    assert len(attempts[-1]) == 7
    assert result['quality']['used_group_count'] == 7
    assert result['source']['validation_search']['remaining_candidate_group_count'] == 0


@pytest.mark.parametrize('complete_groups,second_exposure_only_in_pair,expected_triplets', [
    (8, False, 7),  # Older triplets outrank the eight newest one-sided groups.
    (4, False, 4),  # Pairs fill the target when too few triplets exist.
    (8, True, 6),   # Required exposure diversity takes priority over completeness.
    (0, False, 0),  # Triplets are preferred, never required for success.
])
def test_prefers_triplets_without_losing_usable_pairs(
    tmp_path, archive, small_frames, complete_groups,
    second_exposure_only_in_pair, expected_triplets,
):
    archive[:] = [
        record for record in archive
        if not (
            record['path'].name.endswith('_after.fit')
            and int(record['path'].name[:2]) >= complete_groups
        )
    ]
    if second_exposure_only_in_pair:
        for record in archive:
            record['exposure'] = .002 if record['path'].name.startswith('15_') else .001
            with fits.open(record['path'], mode='update') as hdus:
                hdus[0].header['EXPTIME'] = record['exposure']
    root, session_id, loader = start_session(tmp_path, archive)
    result = web.run_calibration_session(session_id, storage_root=root, database_loader=loader)
    assert result['quality']['validated_bad_count'] == 7
    assert result['quality']['two_sided_count'] == expected_triplets
    assert result['quality']['exposure_level_count'] == 2
    assert result['source']['validation_search']['rejected_group_count'] == 0


def test_unusable_triplets_are_replaced_by_valid_one_sided_groups(
    tmp_path, archive, small_frames,
):
    archive[:] = [
        record for record in archive
        if not (
            record['path'].name.endswith('_after.fit')
            and int(record['path'].name[:2]) >= 8
        )
    ]
    for record in archive:
        if record['path'].name.endswith('_before.fit') and int(record['path'].name[:2]) < 8:
            with fits.open(record['path'], mode='update') as hdus:
                hdus[0].data = numpy.rint(
                    hdus[0].data.astype(float) * .45,
                ).astype(numpy.uint16)
    root, session_id, loader = start_session(tmp_path, archive)
    result = web.run_calibration_session(session_id, storage_root=root, database_loader=loader)
    assert result['quality']['validated_bad_count'] == 7
    assert result['quality']['two_sided_count'] == 0
    assert result['source']['validation_search']['rejected_group_count'] == 8


def test_missing_staged_source_is_replaced_from_catalog(
    tmp_path, archive, small_frames, monkeypatch,
):
    stage = web.stage_database_files_for_worker
    removed = False

    def expire_source(*args, **kwargs):
        nonlocal removed
        if not removed:
            next(r['path'] for r in archive if r['path'].name == '15_bad.fit').unlink()
            removed = True
        return stage(*args, **kwargs)

    monkeypatch.setattr(web, 'stage_database_files_for_worker', expire_source)
    root, session_id, loader = start_session(tmp_path, archive)
    result = web.run_calibration_session(session_id, storage_root=root, database_loader=loader)
    assert result['quality']['validated_bad_count'] == 7
    search = result['source']['validation_search']
    assert search['rejected_group_count'] == 1
    assert search['excluded_groups'][0]['name'] == '15_bad.fit'


def test_archive_without_stable_reference_samples_cannot_produce_settings(
    tmp_path, archive, small_frames,
):
    for record in archive:
        if record['path'].name.endswith('_before.fit'):
            with fits.open(record['path'], mode='update') as hdus:
                hdus[0].data = numpy.rint(
                    hdus[0].data.astype(float) * .45,
                ).astype(numpy.uint16)
    root, session_id, loader = start_session(tmp_path, archive)
    with pytest.raises(engine.CalibrationError, match='no further suitable replacements'):
        web.run_calibration_session(session_id, storage_root=root, database_loader=loader)
    manifest = web._read_manifest(root / session_id)
    assert manifest['source']['validation_search']['rejected_group_count'] == 14
    assert not (root / session_id / 'result.json').exists()
    assert not (root / session_id / 'uploads').exists()


def test_replacement_cannot_hide_loss_of_the_only_second_exposure(
    tmp_path, archive, small_frames, monkeypatch,
):
    for record in archive:
        record['exposure'] = .002 if record['path'].name.startswith('15_') else .001
        with fits.open(record['path'], mode='update') as hdus:
            hdus[0].header['EXPTIME'] = record['exposure']
    scored_validation(monkeypatch, lambda name: name == '15_bad.fit')
    root, session_id, loader = start_session(tmp_path, archive)
    with pytest.raises(engine.CalibrationError, match='only one exposure'):
        web.run_calibration_session(session_id, storage_root=root, database_loader=loader)
    manifest = web._read_manifest(root / session_id)
    assert manifest['source']['validation_search']['rejected_group_count'] == 1
    assert not (root / session_id / 'result.json').exists()


@pytest.mark.parametrize('archive', [10], indirect=True)
def test_replacement_with_unmodified_production_sample_and_quality_limits(
    tmp_path, archive,
):
    # Enough actual pixels to meet every production sample minimum. The small
    # fixtures elsewhere lower only sample counts, never quality thresholds.
    normal = numpy.tile(frame_fixtures.TestAsi676mcCalibrationEngine._normal_frame(), (8, 8))
    bad = frame_fixtures.TestAsi676mcCalibrationEngine._bad_stream(normal)
    for record in archive:
        data = bad if record['path'].name.endswith('_bad.fit') else normal
        if record['path'].name == '09_before.fit':
            data = numpy.rint(data.astype(float) * .45).astype(numpy.uint16)
        with fits.open(record['path'], mode='update') as hdus:
            hdus[0].data = data
        record.update(width=1024, height=1024, size=record['path'].stat().st_size)
    hashes = {r['path']: hashlib.sha256(r['path'].read_bytes()).digest() for r in archive}
    root, session_id, loader = start_session(tmp_path, archive)
    result = web.run_calibration_session(session_id, storage_root=root, database_loader=loader)
    assert result['quality']['validated_bad_count'] == 7
    assert result['quality']['highlight_sample_count'] >= 1000
    assert result['source']['validation_search']['rejected_group_count'] == 1
    assert hashes == {path: hashlib.sha256(path.read_bytes()).digest() for path in hashes}


@pytest.mark.parametrize('has_bright_group', [True, False])
def test_missing_recent_highlights_searches_older_groups_without_relaxing_fit(
    tmp_path, archive, small_frames, has_bright_group, progress_updates,
):
    # The only bright group has one reference. Triplet preference must not
    # prevent recovery from finding the highlight evidence it needs.
    if has_bright_group:
        archive[:] = [r for r in archive if r['path'].name != '00_before.fit']
    normal = numpy.rint(
        frame_fixtures.TestAsi676mcCalibrationEngine._normal_frame().astype(float) * .25,
    ).astype(numpy.uint16)
    bad = frame_fixtures.TestAsi676mcCalibrationEngine._bad_stream(normal)
    for record in archive:
        if has_bright_group and record['path'].name.startswith('00_'):
            continue
        with fits.open(record['path'], mode='update') as hdus:
            hdus[0].data = bad if record['path'].name.endswith('_bad.fit') else normal
    root, session_id, loader = start_session(tmp_path, archive)
    if has_bright_group:
        result = web.run_calibration_session(session_id, storage_root=root, database_loader=loader)
        assert result['quality']['validated_bad_count'] == 7
        assert result['quality']['highlight_sample_count'] >= 10
        assert result['quality']['exposure_level_count'] == 2
    else:
        with pytest.raises(engine.CalibrationError, match='archive.*highlight'):
            web.run_calibration_session(session_id, storage_root=root, database_loader=loader)
        assert not (root / session_id / 'result.json').exists()
    manifest = web._read_manifest(root / session_id)
    assert manifest['source']['validation_search']['examined_group_count'] == 16
    assert manifest['source']['validation_search']['highlight_search_group_count'] == (
        14 if has_bright_group else 16
    )
    assert manifest['source']['validation_search']['rejected_group_count'] == 0
    assert {'phase': 'replacing_groups', 'reason': 'highlights'} in progress_updates


def test_recovery_notes_remain_concise_and_explain_reduced_group_count():
    quality = {
        'requested_group_count': 9, 'used_group_count': 7,
        'replacement_group_count': 100,
        'marginal_exclusions': [
            {'name': f'unreadable_{index}.fit', 'reason': 'A FITS could not be read.'}
            for index in range(100)
        ],
    }
    warning = web._result_warnings(quality)[0]
    assert '100 frame groups' in warning
    assert '100 additional groups' in warning
    assert 'used 7 of the requested 9 groups' in warning
    assert 'Download details' in warning
    assert 'unreadable_0.fit' not in warning
    assert len(warning) < 600
    assert 'Frame groups set aside in this report' in web._result_warnings(
        quality, report_context=True,
    )[0]


@pytest.mark.parametrize('archive', [24], indirect=True)
def test_highlight_search_combines_useful_groups_from_different_batches(
    tmp_path, archive, small_frames, monkeypatch,
):
    bright_groups = {0, 2, 4, 7, 10, 13, 18}
    normal = numpy.rint(
        frame_fixtures.TestAsi676mcCalibrationEngine._normal_frame().astype(float) * .25,
    ).astype(numpy.uint16)
    bad = frame_fixtures.TestAsi676mcCalibrationEngine._bad_stream(normal)
    for record in archive:
        if int(record['path'].name[:2]) not in bright_groups:
            with fits.open(record['path'], mode='update') as hdus:
                hdus[0].data = bad if record['path'].name.endswith('_bad.fit') else normal
    monkeypatch.setitem(engine.CALIBRATION_OPTIONS, 'MIN_HIGHLIGHT_SAMPLES_TOTAL', 100)
    root, session_id, loader = start_session(tmp_path, archive)
    result = web.run_calibration_session(session_id, storage_root=root, database_loader=loader)
    assert result['quality']['validated_bad_count'] == 7
    assert result['quality']['highlight_sample_count'] >= 100
    search = result['source']['validation_search']
    assert search['highlight_search_group_count'] == 24
    assert search['rejected_group_count'] == 0
    assert result['quality']['examined_group_count'] == search['examined_group_count'] == 24
    assert result['quality']['replacement_group_count'] == search['replacement_group_count'] == 17


@pytest.mark.parametrize('archive,burst_start', [(16, 9), (7, 3)], indirect=['archive'])
def test_recent_burst_sharing_references_does_not_hide_older_diverse_groups(
    tmp_path, archive, small_frames, burst_start,
):
    base = datetime(2026, 7, 2, tzinfo=timezone.utc)
    for record in archive:
        group = int(record['path'].name[:2])
        if group < burst_start:
            continue
        # The burst's failures have the same nearest before/after references.
        role = record['path'].stem.split('_')[1]
        offset = {'before': 0, 'bad': 20 + group, 'after': 60}[role]
        timestamp = base + timedelta(seconds=offset)
        record.update(timestamp=timestamp.timestamp(), exposure=.001)
        with fits.open(record['path'], mode='update') as hdus:
            hdus[0].header['DATE-OBS'] = timestamp.isoformat()
            hdus[0].header['EXPTIME'] = .001
    root, session_id, loader = start_session(tmp_path, archive)
    result = web.run_calibration_session(session_id, storage_root=root, database_loader=loader)
    assert result['quality']['validated_bad_count'] == 7
    assert result['quality']['matched_normal_count'] >= 7
    assert result['quality']['normal_bad_ratio'] >= 1
    assert result['quality']['exposure_level_count'] == 2


@pytest.mark.parametrize('fault', ['runtime_repair', 'original_improvement', 'comparison_samples'])
def test_individual_validation_failures_use_archive_replacements(
    tmp_path, archive, small_frames, monkeypatch, fault,
):
    validate = engine.validate_calibrated_frames

    def validate_with_fault(pairs, settings, **kwargs):
        repaired = normal = 0
        checks, failures = [], []
        for pair in pairs:
            patch = None
            if pair.bad.source_name == '15_bad.fit':
                if fault == 'runtime_repair':
                    repair = engine.asi676mc.repair_if_needed

                    def fail_bad(data, config):
                        result = repair(data, config)
                        if result['repaired']:
                            result['validation_failed'] = True
                        return result

                    patch = mock.patch.object(engine.asi676mc, 'repair_if_needed', fail_bad)
                else:
                    patch = mock.patch.object(
                        engine, '_reference_error', side_effect=(
                            (.10, .11, .30) if fault == 'original_improvement'
                            else engine.CalibrationError('too few stable samples')
                        ),
                    )
            with patch if patch else nullcontext():
                result = validate([pair], settings, **kwargs)
            repaired += result[0]
            normal += result[1]
            checks.extend(result[2])
            failures.extend(result[3])
        return repaired, normal, checks, failures

    monkeypatch.setattr(engine, 'validate_calibrated_frames', validate_with_fault)
    root, session_id, loader = start_session(tmp_path, archive)
    result = web.run_calibration_session(session_id, storage_root=root, database_loader=loader)
    assert result['quality']['validated_bad_count'] == 7
    assert result['source']['validation_search']['rejected_group_count'] == 1
    assert result['source']['validation_search']['excluded_groups'][0]['name'] == '15_bad.fit'


def test_fits_becoming_unreadable_during_sampling_is_replaced(
    tmp_path, archive, small_frames, monkeypatch,
):
    sample = engine._sample_planes

    def unreadable(record, *args, **kwargs):
        if record.source_name == '15_bad.fit':
            raise OSError('FITS read failed')
        return sample(record, *args, **kwargs)

    monkeypatch.setattr(engine, '_sample_planes', unreadable)
    root, session_id, loader = start_session(tmp_path, archive)
    result = web.run_calibration_session(session_id, storage_root=root, database_loader=loader)
    assert result['quality']['validated_bad_count'] == 7
    assert result['source']['validation_search']['rejected_group_count'] == 1


@pytest.mark.parametrize('source', ['15_bad.fit', '15_before.fit'])
@pytest.mark.parametrize('read_error', [OSError, ValueError])
def test_fits_becoming_unreadable_during_validation_is_replaced(
    tmp_path, archive, small_frames, monkeypatch, source, read_error,
):
    read = engine._read_fits
    validate = engine.validate_calibrated_frames
    validating = False

    def unreadable(path, *args, **kwargs):
        if validating and path.name.endswith(source):
            raise read_error('FITS read failed')
        return read(path, *args, **kwargs)

    def start_validation(*args, **kwargs):
        nonlocal validating
        validating = True
        return validate(*args, **kwargs)

    monkeypatch.setattr(engine, '_read_fits', unreadable)
    monkeypatch.setattr(engine, 'validate_calibrated_frames', start_validation)
    root, session_id, loader = start_session(tmp_path, archive)
    result = web.run_calibration_session(session_id, storage_root=root, database_loader=loader)
    assert result['quality']['validated_bad_count'] == 7
    assert result['source']['validation_search']['rejected_group_count'] == 1


@pytest.mark.parametrize('fault', [
    'normal_detection', 'normal_pixels', 'unstable_gains', 'unsafe_highlights', 'bug',
])
def test_global_safety_failures_are_not_hidden_by_replacement(
    tmp_path, archive, small_frames, monkeypatch, fault,
):
    if fault.startswith('normal_'):
        repair = engine.asi676mc.repair_if_needed

        def unsafe_normal(data, settings):
            result = repair(data, settings)
            if not result['signature_before']['is_bad']:
                if fault == 'normal_detection':
                    result['signature_before']['is_bad'] = True
                else:
                    data[0, 0] += 1
            return result

        monkeypatch.setattr(engine.asi676mc, 'repair_if_needed', unsafe_normal)
        error_type, message = engine.CalibrationError, 'validation_normal_'
    else:
        error_type = RuntimeError if fault == 'bug' else engine.CalibrationError
        message = {
            'unstable_gains': 'gains vary too much',
            'unsafe_highlights': 'unsafe highlight fit',
            'bug': 'programming fault',
        }[fault]
        function = 'estimate_highlight_ratios' if fault == 'unsafe_highlights' else 'estimate_gains'
        monkeypatch.setattr(engine, function, mock.Mock(side_effect=error_type(message)))
    root, session_id, loader = start_session(tmp_path, archive)
    with pytest.raises(error_type, match=message):
        web.run_calibration_session(session_id, storage_root=root, database_loader=loader)
    manifest = web._read_manifest(root / session_id)
    assert manifest['status'] == 'failed'
    assert manifest['source']['validation_search']['rejected_group_count'] == 0
    assert not (root / session_id / 'result.json').exists()
    assert not (root / session_id / 'uploads').exists()


@pytest.mark.parametrize('archive', [24], indirect=True)
def test_entire_initial_staging_batch_expiring_uses_older_archive(
    tmp_path, archive, small_frames, monkeypatch,
):
    stage = web.stage_database_files_for_worker
    expired = False

    def expire_initial(*args, **kwargs):
        nonlocal expired
        if not expired:
            for record in args[2]:
                record['path'].unlink()
            expired = True
        return stage(*args, **kwargs)

    monkeypatch.setattr(web, 'stage_database_files_for_worker', expire_initial)
    root, session_id, loader = start_session(tmp_path, archive)
    result = web.run_calibration_session(session_id, storage_root=root, database_loader=loader)
    assert result['quality']['validated_bad_count'] == 7
    assert result['source']['validation_search']['rejected_group_count'] == 10
    assert result['quality']['excluded_marginal_group_count'] == 10
    assert result['quality']['replacement_group_count'] == 7


def test_cancellation_during_replacement_cleans_only_private_files(
    tmp_path, archive, small_frames, monkeypatch,
):
    root, session_id, loader = start_session(tmp_path, archive)
    scored_validation(monkeypatch, lambda name: name == '15_bad.fit')
    validate = engine.validate_calibrated_frames

    def cancel_after_validation(*args, **kwargs):
        result = validate(*args, **kwargs)
        web.cancel_session(session_id, 'tester', storage_root=root)
        return result

    monkeypatch.setattr(engine, 'validate_calibrated_frames', cancel_after_validation)
    result = web.run_calibration_session(session_id, storage_root=root, database_loader=loader)
    assert result is None
    assert web._read_manifest(root / session_id)['status'] == 'cancelled'
    assert not (root / session_id / 'uploads').exists()
    assert all(r['path'].is_file() for r in archive)


def test_ordinary_colour_populations_cannot_be_accepted_by_skipping(
    tmp_path, archive, small_frames,
):
    # These contain no row shift. Use the actual pixel comparisons, not the
    # scored-validation fixture, to check the original rejection safeguard.
    normal = frame_fixtures.TestAsi676mcCalibrationEngine._normal_frame()
    colour_only = normal.copy()
    for (row, col), gain in zip(((0, 0), (0, 1), (1, 0), (1, 1)), (2, .7, .7, 2)):
        colour_only[row::2, col::2] = numpy.rint(numpy.clip(
            normal[row::2, col::2].astype(float) * gain, 0, 65534,
        )).astype(numpy.uint16)
    for record in archive:
        if record['path'].name.endswith('_bad.fit'):
            with fits.open(record['path'], mode='update') as hdus:
                hdus[0].data = colour_only
    root, session_id, loader = start_session(tmp_path, archive)
    with pytest.raises(engine.CalibrationError, match='no further suitable replacements'):
        web.run_calibration_session(session_id, storage_root=root, database_loader=loader)
    assert not (root / session_id / 'result.json').exists()


@pytest.mark.parametrize('reference_fault', ['changing_sky', 'wrong_brightness'])
def test_unsuitable_reference_group_is_replaced_before_accepting_result(
    tmp_path, archive, small_frames, reference_fault,
):
    # Change actual FITS pixels: either rapidly changing reference frames or
    # two stable references that do not describe the scene in the purple frame.
    for record in archive:
        name = record['path'].name
        if name == '15_before.fit' or (
            reference_fault == 'wrong_brightness' and name == '15_after.fit'
        ):
            with fits.open(record['path'], mode='update') as hdus:
                hdus[0].data = numpy.rint(
                    hdus[0].data.astype(float) * .45,
                ).astype(numpy.uint16)
    root, session_id, loader = start_session(tmp_path, archive)
    result = web.run_calibration_session(session_id, storage_root=root, database_loader=loader)
    assert result['quality']['validated_bad_count'] == 7
    search = result['source']['validation_search']
    assert search['rejected_group_count'] == 1
    assert search['excluded_groups'][0]['name'] == '15_bad.fit'
