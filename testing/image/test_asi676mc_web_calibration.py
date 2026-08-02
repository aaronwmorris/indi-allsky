import io
import ast
from itertools import product
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from indi_allsky import asi676mc_calibration
from indi_allsky import asi676mc_calibration_engine as calibration_engine


class TestAsi676mcWebCalibration(unittest.TestCase):
    """Exercise the cross-process session contract without a live Flask app."""

    @staticmethod
    def _fits_upload(name, payload_size=2880):
        # A complete structural FITS check belongs to Astropy in the calibration
        # engine.  Upload admission only checks the mandatory first SIMPLE card.
        prefix = b'SIMPLE  =                    T'
        payload = prefix + (b' ' * max(0, payload_size - len(prefix)))
        upload = mock.Mock()
        upload.stream = io.BytesIO(payload)
        upload.filename = name
        return upload

    @staticmethod
    def _successful_payload():
        settings = dict(calibration_engine.DEFAULT_SETTINGS)
        return {
            'generated_utc': '2026-08-02T12:34:56+00:00',
            'derived_settings': {
                key: settings[key]
                for key in asi676mc_calibration.DERIVED_VALUE_KEYS
            },
            'quality': {
                'pair_count': 7,
                'unmatched_bad_count': 1,
                'unique_good_count': 14,
                'good_bad_ratio': 2.0,
                'two_sided_count': 7,
                'exposure_levels': [0.001, 0.002],
                'validated_bad_repairs': 7,
                'validated_normal_frames': 14,
                'rejected_file_count': 1,
                'highlight_sample_count': 1200,
                'highlight_pair_count': 7,
                'highlight_score': 0.012345,
                'highlight_default_score': 0.012500,
                'highlight_raw_best_score': 0.012300,
                'highlight_raw_best_start_ratio': 0.54,
                'highlight_raw_best_end_ratio': 0.76,
                'highlight_preferred_default': True,
                'highlight_runner_up_score': 0.012400,
                'source_saturation_plateau': 65534,
                'explicit_camera_names': ['ZWO CCD ASI676MC'],
            },
            'gain_estimates': {
                key: {
                    'value': settings[key],
                    'mad': 0.001,
                    'sample_count': 500,
                }
                for key in ('GAIN_R', 'GAIN_G1', 'GAIN_G2', 'GAIN_B')
            },
            'signature_ranges': {
                'purple_ratio': {
                    'good_min': 0.8,
                    'good_max': 1.0,
                    'bad_min': 1.8,
                    'bad_max': 2.1,
                },
                'red_side_ratio': {
                    'good_min': 0.9,
                    'good_max': 1.1,
                    'bad_min': 1.7,
                    'bad_max': 2.0,
                },
                'blue_side_ratio': {
                    'good_min': 0.9,
                    'good_max': 1.1,
                    'bad_min': 1.7,
                    'bad_max': 2.0,
                },
            },
            'rejected_files': [{
                'name': 'rejected.fit',
                'reason': 'already repaired by ASI676MC frame handling',
            }],
        }

    def test_upload_session_is_owned_and_accepts_batch_members(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = asi676mc_calibration.create_session('alice', root)
            session_id = manifest['session_id']

            first, manifest = asi676mc_calibration.store_upload(
                session_id,
                'alice',
                self._fits_upload('bad_20260801_120000.fit'),
                root,
            )
            second, manifest = asi676mc_calibration.store_upload(
                session_id,
                'alice',
                self._fits_upload('good_20260801_120020.fits'),
                root,
            )

            self.assertEqual(first['name'], 'bad_20260801_120000.fit')
            self.assertEqual(second['name'], 'good_20260801_120020.fits')
            self.assertEqual(len(manifest['files']), 2)
            self.assertGreater(manifest['total_bytes'], 0)

            with self.assertRaises(
                asi676mc_calibration.CalibrationSessionError
            ):
                asi676mc_calibration.get_session(session_id, 'bob', root)

    def test_upload_rejects_non_fits_content_and_extension(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_id = asi676mc_calibration.create_session(
                'alice', root
            )['session_id']

            with self.assertRaises(
                asi676mc_calibration.CalibrationUploadError
            ):
                asi676mc_calibration.store_upload(
                    session_id,
                    'alice',
                    mock.Mock(
                        stream=io.BytesIO(b'not fits'),
                        filename='pretend.fit',
                    ),
                    root,
                )
            with self.assertRaises(
                asi676mc_calibration.CalibrationUploadError
            ):
                asi676mc_calibration.store_upload(
                    session_id,
                    'alice',
                    self._fits_upload('archive.zip'),
                    root,
                )

    def test_cancel_removes_uploads_and_tombstones_the_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_id = asi676mc_calibration.create_session(
                'alice', root
            )['session_id']
            asi676mc_calibration.store_upload(
                session_id,
                'alice',
                self._fits_upload('partial_collection.fit'),
                root,
            )

            manifest = asi676mc_calibration.cancel_upload_session(
                session_id,
                'alice',
                root,
            )
            self.assertEqual(manifest['status'], 'cancelled')
            self.assertFalse(root.joinpath(session_id, 'uploads').exists())
            self.assertTrue(manifest['sources_deleted_utc'])
            repeated = asi676mc_calibration.cancel_upload_session(
                session_id,
                'alice',
                root,
            )
            self.assertEqual(repeated['status'], 'cancelled')
            with self.assertRaises(
                asi676mc_calibration.CalibrationUploadError
            ):
                asi676mc_calibration.store_upload(
                    session_id,
                    'alice',
                    self._fits_upload('too_late.fit'),
                    root,
                )

            asi676mc_calibration.discard_session(session_id, 'alice', root)
            self.assertFalse(root.joinpath(session_id).exists())

    @staticmethod
    def _database_record(record_id, timestamp, roles=()):
        return {
            'id': record_id,
            'path': Path('unused_{0}.fit'.format(record_id)),
            'timestamp': float(timestamp),
            'exposure': 0.001,
            'gain': 100.0,
            'binmode': 1,
            'width': 3552,
            'height': 3552,
            'roles': list(roles),
        }

    def test_database_selection_is_newest_first_and_accepts_fewer_than_limit(self):
        records = []
        for index in range(10):
            capture_id = 'capture-{0}'.format(index)
            bad_time = 1000 + (index * 100)
            records.append(self._database_record(
                100 + index,
                bad_time,
                roles=({'capture_id': capture_id, 'role': 'bad'},),
            ))
            records.append(self._database_record(
                200 + index,
                bad_time + 10,
                roles=({'capture_id': capture_id, 'role': 'following'},),
            ))

        selected, summary = asi676mc_calibration.select_database_evidence(
            records,
            bad_frames=[],
            max_bad_frames=8,
            max_pair_seconds=30,
        )
        selected_ids = {record['id'] for record in selected}
        self.assertEqual(summary['selected_bad_count'], 8)
        self.assertEqual(summary['selected_normal_count'], 8)
        self.assertNotIn(100, selected_ids)
        self.assertNotIn(101, selected_ids)
        self.assertIn(109, selected_ids)

        selected, summary = asi676mc_calibration.select_database_evidence(
            records,
            bad_frames=[],
            max_bad_frames=12,
            max_pair_seconds=30,
        )
        self.assertEqual(summary['requested_bad_count'], 12)
        self.assertEqual(summary['selected_bad_count'], 10)
        self.assertEqual(len(selected), 20)

    def test_database_selection_uses_saved_preceding_and_following_triplet(self):
        records = [
            self._database_record(
                1,
                990,
                roles=({'capture_id': 'capture-1', 'role': 'preceding'},),
            ),
            self._database_record(
                2,
                1000,
                roles=({'capture_id': 'capture-1', 'role': 'bad'},),
            ),
            self._database_record(
                3,
                1010,
                roles=({'capture_id': 'capture-1', 'role': 'following'},),
            ),
        ]

        selected, summary = asi676mc_calibration.select_database_evidence(
            records,
            bad_frames=[],
            max_bad_frames=7,
            max_pair_seconds=30,
        )

        self.assertEqual({record['id'] for record in selected}, {1, 2, 3})
        self.assertEqual(summary['selected_bad_count'], 1)
        self.assertEqual(summary['selected_normal_count'], 2)
        self.assertEqual(summary['two_sided_count'], 1)

    def test_database_selection_rejects_invalid_or_nonfinite_separation(self):
        records = [
            self._database_record(
                1,
                1000,
                roles=({'capture_id': 'capture-1', 'role': 'bad'},),
            ),
            self._database_record(
                2,
                1010,
                roles=({'capture_id': 'capture-1', 'role': 'following'},),
            ),
        ]
        for separation in (0, -1, 3601, float('nan'), float('inf')):
            with self.subTest(separation=separation):
                with self.assertRaises(
                    asi676mc_calibration.CalibrationSessionError
                ):
                    asi676mc_calibration.select_database_evidence(
                        records,
                        bad_frames=[],
                        max_bad_frames=7,
                        max_pair_seconds=separation,
                    )

    def test_database_selection_uses_flagged_standard_fits_and_ignores_unmatched(self):
        records = []
        bad_frames = []
        for index in range(8):
            bad_time = 1000 + (index * 100)
            records.extend((
                self._database_record(100 + index, bad_time),
                self._database_record(200 + index, bad_time + 10),
            ))
            bad_frames.append({
                'timestamp': bad_time,
                'exposure': 0.001,
                'gain': 100.0,
            })
        # A newest flagged bad frame with no adjacent normal FITS is skipped;
        # it must not consume the requested usable-group limit.
        records.append(self._database_record(999, 10000))
        bad_frames.append({
            'timestamp': 10000,
            'exposure': 0.001,
            'gain': 100.0,
        })

        _selected, summary = asi676mc_calibration.select_database_evidence(
            records,
            bad_frames=bad_frames,
            max_bad_frames=8,
            max_pair_seconds=30,
        )
        self.assertEqual(summary['selected_bad_count'], 8)
        self.assertEqual(summary['selected_normal_count'], 8)

        _selected, repaired_summary = (
            asi676mc_calibration.select_database_evidence(
                records[:2],
                bad_frames=[{
                    'timestamp': 1000,
                    'exposure': 0.001,
                    'gain': 100.0,
                    'allow_standard': False,
                }],
                max_bad_frames=7,
                max_pair_seconds=30,
            )
        )
        self.assertEqual(repaired_summary['selected_bad_count'], 0)

    def test_database_staging_links_sources_without_deleting_them(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root.joinpath('sources')
            session_root = root.joinpath('sessions')
            source_dir.mkdir()
            records = []
            for index in range(14):
                suffix = '.fit.gz' if index == 0 else '.fit'
                source = source_dir.joinpath('source_{0}{1}'.format(index, suffix))
                source.write_bytes(b'database fits placeholder')
                records.append({
                    'id': index + 1,
                    'path': source,
                })

            session_id = asi676mc_calibration.create_session(
                'alice', session_root
            )['session_id']
            manifest = asi676mc_calibration.stage_database_files(
                session_id,
                'alice',
                records,
                session_root,
            )
            self.assertEqual(len(manifest['files']), 14)
            self.assertTrue(
                session_root.joinpath(session_id, 'uploads').is_dir()
            )
            asi676mc_calibration.cancel_upload_session(
                session_id,
                'alice',
                session_root,
            )
            self.assertTrue(all(record['path'].is_file() for record in records))

    def test_integrated_database_report_is_actionable_and_auditable(self):
        payload = self._successful_payload()
        settings = dict(calibration_engine.DEFAULT_SETTINGS)
        settings['GAIN_R'] = settings['GAIN_R'] + 0.1
        report = asi676mc_calibration.format_integrated_report(payload, {
            'settings': settings,
            'max_pair_seconds': 90.0,
            'files': [{
                'name': 'rejected.fit',
                'original_name': 'already_fixed.fit',
            }],
            'source': {
                'kind': 'database',
                'camera_name': 'ASI676MC',
                'retention_cutoff': '2026-07-23',
                'retention_days': 10,
                'requested_bad_count': 25,
                'selected_bad_count': 9,
                'selected_normal_count': 10,
                'selected_file_count': 19,
                'database_fits_count': 40,
                'missing_local_count': 2,
                'unsupported_count': 1,
            },
        })

        self.assertTrue(report.startswith(
            'indi-allsky ASI676MC purple-frame calibration report\n'
        ))
        self.assertIn('Status: Successful', report)
        self.assertIn('Recommended calibration values', report)
        self.assertIn('Configured when started', report)
        self.assertIn('Meaningful change', report)
        self.assertIn('Tools > ASI676MC Calibration', report)
        self.assertIn('Method: Saved FITS search', report)
        self.assertIn('Requested maximum: 25 purple-frame groups', report)
        self.assertIn('Usable groups selected: 9', report)
        self.assertIn('FITS retention cutoff: 2026-07-23 (10 days)', report)
        self.assertIn('Entries whose files were missing: 2', report)
        self.assertIn('already_fixed.fit:', report)
        self.assertIn('Rejected-file details are listed later', report)
        self.assertNotIn('DATABASE FITS SELECTION', report)
        self.assertNotIn('REVIEW THESE CALIBRATION VALUES', report)
        self.assertNotIn('Source:', report)
        self.assertNotIn('/private/calibration/session/uploads', report)

    def test_integrated_upload_report_explains_cleanup_and_one_day_grammar(self):
        payload = self._successful_payload()
        payload['quality']['rejected_file_count'] = 0
        payload['quality']['unmatched_bad_count'] = 0
        payload['rejected_files'] = []
        report = asi676mc_calibration.format_integrated_report(payload, {
            'settings': calibration_engine.DEFAULT_SETTINGS,
            'max_pair_seconds': 120.0,
            'files': [],
            'source': {
                'kind': 'upload',
                'selected_file_count': 21,
            },
        })
        self.assertIn('Method: Manual FITS upload', report)
        self.assertIn('FITS selected: 21', report)
        self.assertIn('private uploaded copies were removed', report)
        self.assertIn('No additional warnings.', report)

        database_report = asi676mc_calibration.format_integrated_report(
            payload,
            {
                'settings': calibration_engine.DEFAULT_SETTINGS,
                'max_pair_seconds': 120.0,
                'files': [],
                'source': {
                    'kind': 'database',
                    'retention_cutoff': '2026-08-01',
                    'retention_days': 1,
                },
            },
        )
        self.assertIn(
            'FITS retention cutoff: 2026-08-01 (1 day)',
            database_report,
        )
        self.assertNotIn('1 days', database_report)

    def test_background_run_allows_unmatched_and_removes_uploaded_fits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_id = asi676mc_calibration.create_session(
                'alice', root
            )['session_id']
            for index in range(14):
                asi676mc_calibration.store_upload(
                    session_id,
                    'alice',
                    self._fits_upload(f'collection_{index:02d}.fit'),
                    root,
                )
            asi676mc_calibration.mark_queued(
                session_id,
                'alice',
                task_id=42,
                max_pair_seconds=90.0,
                settings=calibration_engine.DEFAULT_SETTINGS,
                source_details={
                    'kind': 'database',
                    'camera_name': 'ASI676MC',
                    'retention_cutoff': '2026-07-23',
                    'retention_days': 10,
                    'requested_bad_count': 8,
                    'selected_bad_count': 7,
                    'selected_normal_count': 14,
                    'selected_file_count': 14,
                    'database_fits_count': 16,
                    'missing_local_count': 1,
                    'unsupported_count': 1,
                },
                storage_root=root,
            )

            payload = self._successful_payload()
            with mock.patch.object(
                calibration_engine,
                'calibrate_folder',
                return_value=payload,
            ) as calibrate_folder:
                original_write_manifest = asi676mc_calibration._write_manifest
                success_saw_deleted_sources = []

                def observe_manifest(session_dir, manifest):
                    if manifest.get('status') == 'success':
                        success_saw_deleted_sources.append(
                            not session_dir.joinpath('uploads').exists()
                        )
                    return original_write_manifest(session_dir, manifest)

                with mock.patch.object(
                    asi676mc_calibration,
                    '_write_manifest',
                    side_effect=observe_manifest,
                ):
                    result = asi676mc_calibration.run_calibration_session(
                        session_id,
                        root,
                    )

            call_kwargs = calibrate_folder.call_args.kwargs
            self.assertTrue(call_kwargs['allow_unmatched'])
            self.assertFalse(call_kwargs['recursive'])
            self.assertNotIn('report_title', call_kwargs)
            self.assertEqual(result['quality']['matched_bad_count'], 7)
            self.assertEqual(len(result['values']), 7)
            self.assertFalse(root.joinpath(session_id, 'uploads').exists())
            self.assertEqual(success_saw_deleted_sources, [True])

            status = asi676mc_calibration.get_status(
                session_id,
                'alice',
                root,
            )
            self.assertEqual(status['status'], 'success')
            self.assertTrue(status['report_available'])
            self.assertEqual(status['result']['quality']['unmatched_bad_count'], 1)
            self.assertEqual(status['result']['source']['kind'], 'database')
            warnings = ' '.join(status['result']['warnings'])
            self.assertIn('looked for up to 8 purple frames', warnings)
            self.assertIn('found 7 usable groups', warnings)
            self.assertIn('whose file was no longer on disk', warnings)
            self.assertIn('with an unsupported filename', warnings)
            self.assertEqual(len(status['result']['warnings']), 2)
            report = asi676mc_calibration.get_report_path(
                session_id,
                'alice',
                root,
            ).read_text(encoding='utf-8')
            self.assertTrue(report.startswith(
                'indi-allsky ASI676MC purple-frame calibration report\n'
            ))
            self.assertIn(
                'Method: Saved FITS search',
                report,
            )
            self.assertNotIn(str(root), report)

    def test_result_comparison_distinguishes_exact_negligible_and_different(self):
        payload = self._successful_payload()
        result = asi676mc_calibration._result_summary(payload)
        current = dict(calibration_engine.DEFAULT_SETTINGS)

        exact = asi676mc_calibration.compare_result_to_configuration(
            result,
            current,
        )
        self.assertEqual(exact['status'], 'exact')
        self.assertIn('No update is needed', exact['message'])
        self.assertEqual(
            exact['configured_values']['GAIN_R'],
            current['GAIN_R'],
        )

        current['GAIN_R'] *= 1.004
        current['SOURCE_SATURATION_THRESHOLD'] += 64
        current['HIGHLIGHT_BLEND_START_RATIO'] += 0.004
        equivalent = asi676mc_calibration.compare_result_to_configuration(
            result,
            current,
        )
        self.assertEqual(equivalent['status'], 'equivalent')
        self.assertTrue(
            equivalent['message'].startswith(
                'Result effectively matches the current configuration'
            )
        )
        self.assertIn('unlikely to produce a visible change', equivalent['message'])

        current['GAIN_B'] *= 1.02
        different = asi676mc_calibration.compare_result_to_configuration(
            result,
            current,
        )
        self.assertEqual(different['status'], 'different')
        self.assertIn('GAIN_B', different['differing_keys'])

        unavailable = asi676mc_calibration.compare_result_to_configuration(
            {'values': result['values'][:-1]},
            current,
        )
        self.assertEqual(unavailable['status'], 'unavailable')
        self.assertIn('could not be loaded for comparison', unavailable['message'])
        self.assertIn('before applying', unavailable['message'])

    def test_result_notes_combine_related_counts_in_plain_language(self):
        warnings = asi676mc_calibration._result_warnings(
            {
                'matched_bad_count': 7,
                'two_sided_count': 3,
                'matched_normal_count': 7,
                'unmatched_bad_count': 1,
                'rejected_file_count': 2,
            },
            {
                'kind': 'database',
                'requested_bad_count': 10,
                'selected_bad_count': 7,
                'missing_local_count': 1,
                'unsupported_count': 1,
            },
        )
        self.assertEqual(len(warnings), 3)
        self.assertIn('looked for up to 10 purple frames', warnings[0])
        self.assertIn('minimum of seven was met', warnings[0])
        self.assertIn('3 of 7 purple frames had normal references', warnings[1])
        self.assertIn('the other 4 purple frames used one adjacent', warnings[1])
        self.assertIn('normal references were reused', warnings[1])
        self.assertIn('1 purple frame without a compatible', warnings[2])
        self.assertIn('2 FITS files that could not be read or used', warnings[2])
        self.assertNotIn('(s)', ' '.join(warnings))

        reuse_only = asi676mc_calibration._result_warnings({
            'matched_bad_count': 7,
            'two_sided_count': 7,
            'matched_normal_count': 13,
            'unmatched_bad_count': 0,
            'rejected_file_count': 0,
        })
        self.assertEqual(len(reuse_only), 1)
        self.assertIn('normal references were reused', reuse_only[0])
        self.assertIn('more independent normal references', reuse_only[0])

        fully_independent = asi676mc_calibration._result_warnings({
            'matched_bad_count': 7,
            'two_sided_count': 7,
            'matched_normal_count': 14,
            'unmatched_bad_count': 0,
            'rejected_file_count': 0,
        })
        self.assertEqual(fully_independent, [])

    def test_engine_failures_are_translated_to_actionable_browser_text(self):
        too_few = asi676mc_calibration._friendly_failure_message(
            '4 matched purple frames found; need at least 7'
        )
        self.assertIn('Only 4 purple frames', too_few)
        self.assertIn('at least seven are required', too_few)

        no_highlights = asi676mc_calibration._friendly_failure_message(
            'no stable jointly-clipped highlight samples were found'
        )
        self.assertIn('bright daylight highlights', no_highlights)

        weak_samples = asi676mc_calibration._friendly_failure_message(
            'R has usable samples in only 5 pairs'
        )
        self.assertIn('Too few stable pixels', weak_samples)

        safety_failure = asi676mc_calibration._friendly_failure_message(
            'normal-frame validation mutated C:\\private\\normal.fit'
        )
        self.assertIn('final safety checks', safety_failure)
        self.assertNotIn('normal.fit', safety_failure)

        unexpected = asi676mc_calibration._friendly_failure_message(
            'cannot read C:\\private\\camera\\secret.fit'
        )
        self.assertIn('unexpected error', unexpected)
        self.assertNotIn('secret.fit', unexpected)

    def test_expired_abandoned_upload_is_removed_without_page_revisit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_id = asi676mc_calibration.create_session(
                'alice', root
            )['session_id']
            asi676mc_calibration.store_upload(
                session_id,
                'alice',
                self._fits_upload('received_before_disconnect.fit'),
                root,
            )
            session_dir = root.joinpath(session_id)
            expiry_time = (
                1700000000 - asi676mc_calibration.SESSION_RETENTION_SECONDS - 1
            )
            os.utime(session_dir, (expiry_time, expiry_time))

            removed = asi676mc_calibration.cleanup_expired_sessions(
                root,
                now=1700000000,
            )
            self.assertEqual(removed, 1)
            self.assertFalse(session_dir.exists())

    def test_unmatched_file_relaxation_is_explicit(self):
        """The integrated engine remains strict unless the caller opts in."""
        normal_records = []
        pairs = []
        for index in range(7):
            exposure = 0.001 if index < 4 else 0.002
            normal = calibration_engine.FrameRecord(
                path=Path(f'normal_{index}.fit'),
                timestamp=float(index * 10),
                exposure=exposure,
                gain=0.0,
                xbin=1,
                ybin=1,
                shape=(64, 64),
                bayer='RGGB',
                camera_name='ASI676MC',
                signature={'is_bad': False},
            )
            bad = calibration_engine.FrameRecord(
                path=Path(f'bad_{index}.fit'),
                timestamp=float(index * 10 + 1),
                exposure=exposure,
                gain=0.0,
                xbin=1,
                ybin=1,
                shape=(64, 64),
                bayer='RGGB',
                camera_name='ASI676MC',
                signature={'is_bad': True},
            )
            normal_records.append(normal)
            pairs.append(calibration_engine.MatchedPair(bad=bad, references=(normal,)))

        unmatched = [pairs[0].bad]
        records = normal_records + [pair.bad for pair in pairs] + unmatched
        with self.assertRaises(calibration_engine.CalibrationError):
            calibration_engine.validate_evidence(records, pairs, unmatched)

        evidence = calibration_engine.validate_evidence(
            records,
            pairs,
            unmatched,
            allow_unmatched=True,
        )
        self.assertEqual(evidence['pair_count'], 7)
        self.assertEqual(evidence['unmatched_bad_count'], 1)

    def test_every_web_endpoint_requires_a_real_login(self):
        project_root = Path(__file__).resolve().parents[2]
        views_path = project_root / 'indi_allsky' / 'flask' / 'views.py'
        views_source = views_path.read_text(encoding='utf-8')
        views_tree = ast.parse(views_source, filename=str(views_path))
        protected_classes = {
            'Asi676mcCalibrationView',
            'AjaxAsi676mcCalibrationSessionView',
            'AjaxAsi676mcCalibrationUploadView',
            'AjaxAsi676mcCalibrationDatabaseView',
            'AjaxAsi676mcCalibrationCancelView',
            'AjaxAsi676mcCalibrationStartView',
            'AjaxAsi676mcCalibrationStatusView',
            'Asi676mcCalibrationReportView',
            'AjaxAsi676mcCalibrationDiscardView',
            'AjaxAsi676mcCalibrationApplyView',
        }
        found = set()
        for node in views_tree.body:
            if not isinstance(node, ast.ClassDef) or node.name not in protected_classes:
                continue
            found.add(node.name)
            decorators_assignment = next(
                child
                for child in node.body
                if isinstance(child, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == 'decorators'
                    for target in child.targets
                )
            )
            decorator_names = {
                element.id
                for element in decorators_assignment.value.elts
                if isinstance(element, ast.Name)
            }
            self.assertEqual(
                decorator_names,
                {'strict_login_required', 'login_required'},
            )
        self.assertEqual(found, protected_classes)

    def test_page_uses_one_multi_file_selection(self):
        project_root = Path(__file__).resolve().parents[2]
        template = (
            project_root
            / 'indi_allsky'
            / 'flask'
            / 'templates'
            / 'asi676mc_calibration.html'
        ).read_text(encoding='utf-8')
        self.assertIn('id="calibration-files"', template)
        self.assertIn('multiple', template)
        self.assertIn('for (let index = 0; index < files.length; index++)', template)
        self.assertIn('Download text report', template)
        self.assertIn('Apply values and reload', template)
        self.assertIn('Current FITS capture settings', template)
        self.assertIn('Cancel upload', template)
        self.assertIn('Retry cancellation', template)
        self.assertIn('new AbortController()', template)
        self.assertIn('Reset / recalibrate', template)
        self.assertLess(
            template.index('id="calibration-reset"'),
            template.index('id="calibration-report-download"'),
        )
        self.assertIn('calibration-source-card bg-dark border-secondary', template)
        self.assertIn('Upload a FITS collection', template)
        self.assertIn('calibration-values-table table table-dark', template)
        self.assertIn('calibration-callout calibration-callout-info', template)
        self.assertIn('.calibration-callout-success', template)
        self.assertNotIn("? 'text-success' : 'text-info'", template)
        self.assertIn('id="calibration-browser-warning"', template)
        self.assertIn('window.asi676mcCalibrationBrowserSupported', template)
        self.assertIn('function calibrationPairSeparation()', template)
        self.assertIn('Number.isFinite(seconds)', template)
        self.assertIn('function validateSelectedFits(files)', template)
        self.assertIn('calibrationMaxSessionBytes', template)
        self.assertIn('Manual upload accepts uncompressed', template)
        self.assertIn('capture_guidance.guidance.level', template)
        self.assertIn('capture_guidance.guidance.title', template)
        self.assertNotIn('{% for message in capture_guidance.messages %}', template)
        self.assertIn('id="calibration-result-status"', template)
        self.assertIn('id="calibration-result-status-primary"', template)
        self.assertIn('id="calibration-result-status-detail"', template)
        self.assertIn('function setResultStatus(', template)
        self.assertIn('requestError.code = data.error_code', template)
        self.assertIn(
            'Only the seven calibration values shown below were',
            template,
        )
        self.assertNotIn(
            '<p class="calibration-help mt-3">\n'
            '            Only the seven calibration values',
            template,
        )
        self.assertNotIn('id="calibration-config-match"', template)
        self.assertNotIn('id="calibration-success-message"', template)
        self.assertNotIn('id="calibration-apply-result"', template)
        self.assertNotIn('id="calibration-source-summary"', template)
        self.assertIn('id="calibration-warning-list"', template)
        self.assertIn('Calibration notes', template)
        self.assertIn('new Set(result.warnings || [])', template)
        self.assertIn('configuration_comparison', template)
        self.assertIn('Current configured value', template)
        self.assertIn('configurationComparison.configured_values', template)
        self.assertIn('Find saved FITS and calibrate', template)
        self.assertIn('DATABASE_BAD_FRAME_LIMIT', template)
        self.assertIn('calibrationDatabaseUrl', template)
        self.assertIn(
            '#calibration-setup-panel, #calibration-progress-panel',
            template,
        )

        video_source = project_root.joinpath(
            'indi_allsky', 'video.py'
        ).read_text(encoding='utf-8')
        self.assertIn(
            'asi676mc_calibration.cleanup_expired_sessions()',
            video_source,
        )

        base_view_source = project_root.joinpath(
            'indi_allsky', 'flask', 'base_views.py'
        ).read_text(encoding='utf-8')
        base_template = project_root.joinpath(
            'indi_allsky', 'flask', 'templates', 'base.html'
        ).read_text(encoding='utf-8')
        views_source = project_root.joinpath(
            'indi_allsky', 'flask', 'views.py'
        ).read_text(encoding='utf-8')
        self.assertIn("context['asi676mc_repair_enabled']", base_view_source)
        self.assertIn(
            'current_user.is_authenticated and asi676mc_repair_enabled',
            base_template,
        )
        self.assertIn(
            'class AjaxAsi676mcCalibrationDatabaseView',
            views_source,
        )
        self.assertIn(
            'IndiAllSkyDbFitsImageTable.dayDate >= retention_cutoff',
            views_source,
        )
        self.assertIn("context['calibration_upload_limits']", views_source)
        self.assertIn("'error_code': 'configuration_changed'", views_source)
        self.assertIn("'error_code': 'result_unavailable'", views_source)
        self.assertIn('Reload on Save', views_source)
        self.assertIn(
            'The previous calibration expired, was cleared, or is no',
            views_source,
        )
        self.assertIn(
            'The browser could not confirm whether the result was cleared',
            template,
        )

    def test_capture_guidance_recommends_safe_low_disk_collection(self):
        guidance = asi676mc_calibration.capture_configuration_guidance({
            'IMAGE_ASI676MC_REPAIR': {
                'ENABLE': True,
                'EXCLUDE_ONLY': True,
                'SAVE_DIAGNOSTIC_FITS': True,
            },
            'IMAGE_SAVE_FITS': False,
            'IMAGE_FITS_EXPIRE_DAYS': 10,
        })
        self.assertTrue(guidance['exclude_only'])
        self.assertTrue(guidance['diagnostic_fits'])
        self.assertFalse(guidance['preceding_fits'])
        self.assertEqual(guidance['guidance']['level'], 'success')
        self.assertEqual(
            guidance['guidance']['title'],
            'Ready for low-disk FITS collection',
        )
        message = guidance['guidance']['text']
        self.assertIn('Exclude Only leaves purple frames unchanged', message)
        self.assertIn('immediately following frame', message)
        self.assertIn('standard FITS can remain off', message)

    def test_capture_guidance_explains_opt_in_preceding_cache(self):
        guidance = asi676mc_calibration.capture_configuration_guidance({
            'IMAGE_ASI676MC_REPAIR': {
                'ENABLE': True,
                'EXCLUDE_ONLY': True,
                'SAVE_DIAGNOSTIC_FITS': True,
                'SAVE_PRECEDING_FITS': True,
            },
            'IMAGE_SAVE_FITS': False,
            'IMAGE_FITS_EXPIRE_DAYS': 10,
        })
        facts = {item['label']: item['value'] for item in guidance['facts']}
        self.assertTrue(guidance['preceding_fits'])
        self.assertEqual(
            facts['Preceding RAW FITS'],
            'On (one-frame memory cache)',
        )
        message = guidance['guidance']['text']
        self.assertIn('one untouched normal frame is kept in memory', message)
        self.assertIn('good/purple/good triplet', message)
        self.assertIn('one full FITS frame of memory', message)
        self.assertIn('additional disk space', message)

    def test_capture_guidance_warns_about_unsafe_or_periodic_saving(self):
        guidance = asi676mc_calibration.capture_configuration_guidance({
            'IMAGE_ASI676MC_REPAIR': {
                'ENABLE': True,
                'EXCLUDE_ONLY': False,
                'SAVE_DIAGNOSTIC_FITS': False,
            },
            'IMAGE_SAVE_FITS': True,
            'IMAGE_SAVE_FITS_PERIOD': 600,
        })
        facts = {
            item['label']: item['value']
            for item in guidance['facts']
        }
        message = guidance['guidance']['text']
        self.assertEqual(facts['Repair mode'], 'Repair active')
        self.assertEqual(guidance['guidance']['level'], 'warning')
        self.assertEqual(
            guidance['guidance']['title'],
            'No untouched purple-frame FITS will be saved',
        )
        self.assertIn('periodic standard FITS is written after repair', message)
        self.assertIn('turn on Bad + following RAW FITS', message)
        self.assertIn('switch to Exclude Only', message)

    def test_capture_guidance_consolidates_every_switch_combination(self):
        periodic_modes = (
            (False, 7200),
            (False, 'invalid'),
            (True, 0),
            (True, 600),
            (True, 'invalid'),
            (True, -1),
        )
        for repair_enabled in (False, True):
            for exclude_only in (False, True):
                for diagnostic_fits in (False, True):
                    for preceding_fits, periodic_mode in product(
                        (False, True),
                        periodic_modes,
                    ):
                        standard_fits, fits_period = periodic_mode
                        if not standard_fits:
                            standard_mode = 'off'
                        elif fits_period == 0:
                            standard_mode = 'every'
                        elif isinstance(fits_period, int) and fits_period > 0:
                            standard_mode = 'periodic'
                        else:
                            standard_mode = 'invalid'
                        with self.subTest(
                            repair_enabled=repair_enabled,
                            exclude_only=exclude_only,
                            diagnostic_fits=diagnostic_fits,
                            preceding_fits=preceding_fits,
                            standard_fits=standard_fits,
                            fits_period=fits_period,
                        ):
                            result = (
                                asi676mc_calibration
                                .capture_configuration_guidance({
                                    'IMAGE_ASI676MC_REPAIR': {
                                        'ENABLE': repair_enabled,
                                        'EXCLUDE_ONLY': exclude_only,
                                        'SAVE_DIAGNOSTIC_FITS': diagnostic_fits,
                                        'SAVE_PRECEDING_FITS': preceding_fits,
                                    },
                                    'IMAGE_SAVE_FITS': standard_fits,
                                    'IMAGE_SAVE_FITS_PERIOD': fits_period,
                                    'IMAGE_FITS_EXPIRE_DAYS': 10,
                                })
                            )
                            self.assertIn(
                                result['guidance']['level'],
                                {'success', 'info', 'warning'},
                            )
                            if not repair_enabled:
                                expected = (
                                    'warning',
                                    'Purple-frame handling is off',
                                )
                            elif diagnostic_fits:
                                if standard_mode == 'every':
                                    expected = (
                                        'success',
                                        'Ready to collect complete FITS sequences',
                                    )
                                elif standard_mode in ('off', 'periodic'):
                                    expected = (
                                        'success',
                                        'Ready for low-disk FITS collection',
                                    )
                                else:
                                    expected = (
                                        'warning',
                                        'Standard FITS setting needs correction',
                                    )
                            elif not exclude_only:
                                expected = (
                                    'warning',
                                    'No untouched purple-frame FITS will be saved',
                                )
                            elif standard_mode == 'every':
                                expected = (
                                    'success',
                                    'Ready to collect complete FITS sequences',
                                )
                            elif standard_mode == 'periodic':
                                expected = (
                                    'warning',
                                    'Periodic FITS saving may miss purple frames',
                                )
                            elif standard_mode == 'invalid':
                                expected = (
                                    'warning',
                                    'No reliable calibration FITS will be saved',
                                )
                            else:
                                expected = (
                                    'warning',
                                    'No calibration FITS will be saved',
                                )
                            self.assertEqual(
                                (
                                    result['guidance']['level'],
                                    result['guidance']['title'],
                                ),
                                expected,
                            )
                            self.assertTrue(result['guidance']['title'])
                            self.assertTrue(result['guidance']['text'])
                            self.assertNotIn('messages', result)
                            self.assertNotIn('(s)', result['guidance']['text'])
                            self.assertNotIn(
                                'guarantees a usable pair',
                                result['guidance']['text'],
                            )
                            self.assertNotIn(
                                'next normal reference',
                                result['guidance']['text'],
                            )
                            facts = {
                                item['label']: item['value']
                                for item in result['facts']
                            }
                            if preceding_fits and repair_enabled and diagnostic_fits:
                                self.assertTrue(result['preceding_fits'])
                                self.assertEqual(
                                    facts['Preceding RAW FITS'],
                                    'On (one-frame memory cache)',
                                )
                                self.assertIn(
                                    'one untouched normal frame is kept in memory',
                                    result['guidance']['text'],
                                )
                            elif preceding_fits and not repair_enabled:
                                self.assertFalse(result['preceding_fits'])
                                self.assertEqual(
                                    facts['Preceding RAW FITS'],
                                    'Inactive (handling off)',
                                )
                            elif preceding_fits:
                                self.assertFalse(result['preceding_fits'])
                                self.assertEqual(
                                    facts['Preceding RAW FITS'],
                                    'Inactive (Bad + following off)',
                                )
                            else:
                                self.assertFalse(result['preceding_fits'])
                                self.assertEqual(
                                    facts['Preceding RAW FITS'],
                                    'Off',
                                )

    def test_capture_guidance_marks_invalid_retention_once(self):
        result = asi676mc_calibration.capture_configuration_guidance({
            'IMAGE_ASI676MC_REPAIR': {
                'ENABLE': True,
                'EXCLUDE_ONLY': True,
                'SAVE_DIAGNOSTIC_FITS': True,
            },
            'IMAGE_SAVE_FITS': False,
            'IMAGE_FITS_EXPIRE_DAYS': -1,
        })
        facts = {item['label']: item['value'] for item in result['facts']}
        self.assertEqual(facts['FITS retention'], 'Invalid value')
        self.assertEqual(result['guidance']['level'], 'warning')
        self.assertEqual(
            result['guidance']['text'].count(
                'Set FITS retention to at least 1 day'
            ),
            1,
        )

    def test_invalid_retention_overlay_covers_every_capture_mode(self):
        standard_modes = (
            (False, 7200),
            (True, 0),
            (True, 600),
            (True, 'invalid'),
        )
        repair_modes = (
            (False, True),
            (True, True),
            (True, False),
        )
        for repair_enabled, exclude_only in repair_modes:
            for diagnostic_fits in (False, True):
                for standard_enabled, standard_period in standard_modes:
                    for retention in (0, -1, 'invalid'):
                        with self.subTest(
                            repair_enabled=repair_enabled,
                            exclude_only=exclude_only,
                            diagnostic_fits=diagnostic_fits,
                            standard_enabled=standard_enabled,
                            standard_period=standard_period,
                            retention=retention,
                        ):
                            result = (
                                asi676mc_calibration
                                .capture_configuration_guidance({
                                    'IMAGE_ASI676MC_REPAIR': {
                                        'ENABLE': repair_enabled,
                                        'EXCLUDE_ONLY': exclude_only,
                                        'SAVE_DIAGNOSTIC_FITS': diagnostic_fits,
                                    },
                                    'IMAGE_SAVE_FITS': standard_enabled,
                                    'IMAGE_SAVE_FITS_PERIOD': standard_period,
                                    'IMAGE_FITS_EXPIRE_DAYS': retention,
                                })
                            )
                            facts = {
                                item['label']: item['value']
                                for item in result['facts']
                            }
                            self.assertEqual(
                                facts['FITS retention'],
                                'Invalid value',
                            )
                            self.assertEqual(
                                result['guidance']['level'],
                                'warning',
                            )
                            self.assertEqual(
                                result['guidance']['text'].count(
                                    'Set FITS retention to at least 1 day'
                                ),
                                1,
                            )
                            self.assertIn(
                                'manual upload remains available',
                                result['guidance']['text'],
                            )

    def test_capture_guidance_gives_both_safe_choices_when_repair_saves_no_fits(self):
        result = asi676mc_calibration.capture_configuration_guidance({
            'IMAGE_ASI676MC_REPAIR': {
                'ENABLE': True,
                'EXCLUDE_ONLY': False,
                'SAVE_DIAGNOSTIC_FITS': False,
            },
            'IMAGE_SAVE_FITS': False,
            'IMAGE_FITS_EXPIRE_DAYS': 7,
        })
        self.assertEqual(result['guidance']['level'], 'warning')
        self.assertEqual(
            result['guidance']['title'],
            'No untouched purple-frame FITS will be saved',
        )
        message = result['guidance']['text']
        self.assertIn('Repair is active, but no FITS saving is enabled', message)
        self.assertIn('turn on Bad + following RAW FITS', message)
        self.assertIn(
            'switch to Exclude Only and set standard FITS to Every Image',
            message,
        )

    def test_capture_guidance_marks_child_switches_inactive(self):
        handling_off = asi676mc_calibration.capture_configuration_guidance({
            'IMAGE_ASI676MC_REPAIR': {
                'ENABLE': False,
                'SAVE_DIAGNOSTIC_FITS': True,
            },
            'IMAGE_SAVE_FITS': False,
            'IMAGE_FITS_EXPIRE_DAYS': 7,
        })
        facts = {item['label']: item['value'] for item in handling_off['facts']}
        self.assertEqual(
            facts['Bad + following RAW FITS'],
            'Inactive (handling off)',
        )
        self.assertIn(
            'option is inactive until purple-frame handling is enabled',
            handling_off['guidance']['text'],
        )

        parent_off = asi676mc_calibration.capture_configuration_guidance({
            'IMAGE_ASI676MC_REPAIR': {
                'ENABLE': True,
                'SAVE_DIAGNOSTIC_FITS': False,
                'SAVE_PRECEDING_FITS': True,
            },
            'IMAGE_SAVE_FITS': False,
            'IMAGE_FITS_EXPIRE_DAYS': 7,
        })
        facts = {item['label']: item['value'] for item in parent_off['facts']}
        self.assertEqual(
            facts['Preceding RAW FITS'],
            'Inactive (Bad + following off)',
        )

        standard_off = asi676mc_calibration.capture_configuration_guidance({
            'IMAGE_ASI676MC_REPAIR': {'ENABLE': True},
            'IMAGE_SAVE_FITS': False,
            'IMAGE_SAVE_FITS_COMPRESSED': True,
            'IMAGE_FITS_EXPIRE_DAYS': 7,
        })
        facts = {item['label']: item['value'] for item in standard_off['facts']}
        self.assertEqual(
            facts['Standard FITS compression'],
            'Inactive (standard FITS off)',
        )

    def test_capture_guidance_explains_compressed_manual_upload_limit(self):
        result = asi676mc_calibration.capture_configuration_guidance({
            'IMAGE_ASI676MC_REPAIR': {
                'ENABLE': False,
                'SAVE_DIAGNOSTIC_FITS': False,
            },
            'IMAGE_SAVE_FITS': True,
            'IMAGE_SAVE_FITS_PERIOD': 0,
            'IMAGE_SAVE_FITS_COMPRESSED': True,
            'IMAGE_FITS_EXPIRE_DAYS': 7,
        })
        facts = {item['label']: item['value'] for item in result['facts']}
        self.assertEqual(facts['Standard FITS'], 'Every Image')
        self.assertEqual(facts['Standard FITS compression'], 'On')
        self.assertIn(
            'Manual upload accepts uncompressed FITS only',
            result['guidance']['text'],
        )
        self.assertIn('decompress the selected files first', result['guidance']['text'])
        self.assertIn('enable handling in Exclude Only mode', result['guidance']['text'])

    def test_safe_exclude_only_defaults_are_source_visible(self):
        project_root = Path(__file__).resolve().parents[2]
        config_source = project_root.joinpath(
            'indi_allsky', 'config.py'
        ).read_text(encoding='utf-8')
        processing_source = project_root.joinpath(
            'indi_allsky', 'processing.py'
        ).read_text(encoding='utf-8')
        views_source = project_root.joinpath(
            'indi_allsky', 'flask', 'views.py'
        ).read_text(encoding='utf-8')
        settings_template = project_root.joinpath(
            'indi_allsky', 'flask', 'templates', 'config.html'
        ).read_text(encoding='utf-8')

        self.assertIn('"EXCLUDE_ONLY"                : True', config_source)
        self.assertIn('"SAVE_PRECEDING_FITS"          : False', config_source)
        self.assertIn("get('EXCLUDE_ONLY', True)", processing_source)
        self.assertIn("get('EXCLUDE_ONLY', True)", views_source)
        self.assertIn('asi676mc_repair_was_enabled', settings_template)
        self.assertIn(
            'form_config.IMAGE_ASI676MC_REPAIR__SAVE_PRECEDING_FITS.label',
            settings_template,
        )
        self.assertIn(
            'update_asi676mc_preceding_fits_state',
            settings_template,
        )
        self.assertLess(
            settings_template.index(
                'form_config.IMAGE_ASI676MC_REPAIR__SAVE_DIAGNOSTIC_FITS.label'
            ),
            settings_template.index(
                'form_config.IMAGE_ASI676MC_REPAIR__SAVE_PRECEDING_FITS.label'
            ),
        )
        self.assertIn(
            'Purple-frame cameras only',
            settings_template,
        )
        self.assertIn(
            'Cameras without this failure should leave the feature disabled.',
            settings_template,
        )
        self.assertNotIn('Safe calibration workflow:', settings_template)
        enable_guidance_position = settings_template.index(
            'Purple-frame cameras only'
        )
        self.assertGreater(
            enable_guidance_position,
            settings_template.index(
                'form_config.IMAGE_ASI676MC_REPAIR__ENABLE.label'
            ),
        )
        self.assertLess(
            enable_guidance_position,
            settings_template.index(
                'form_config.IMAGE_ASI676MC_REPAIR__EXCLUDE_ONLY.label'
            ),
        )
        self.assertGreater(
            settings_template.index('For stronger good/purple/good triplets'),
            settings_template.index(
                'form_config.IMAGE_ASI676MC_REPAIR__EXCLUDE_ONLY.label'
            ),
        )
        highlight_start_position = settings_template.index(
            'form_config.IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_START_RATIO.label'
        )
        highlight_end_position = settings_template.index(
            'form_config.IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_END_RATIO.label'
        )
        sample_step_position = settings_template.index(
            'form_config.IMAGE_ASI676MC_REPAIR__SAMPLE_STEP.label'
        )
        chunk_rows_position = settings_template.index(
            'form_config.IMAGE_ASI676MC_REPAIR__CHUNK_ROWS.label'
        )
        self.assertLess(highlight_start_position, highlight_end_position)
        self.assertLess(highlight_end_position, sample_step_position)
        self.assertLess(sample_step_position, chunk_rows_position)


if __name__ == '__main__':
    unittest.main()
