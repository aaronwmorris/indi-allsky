import io
import ast
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from indi_allsky import asi676mc_calibration
from misc import asi676mc_frame_repair as calibration_engine


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
            'IMAGE_ASI676MC_REPAIR': settings,
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
            },
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

    def test_database_selection_uses_flagged_ordinary_fits_and_ignores_unmatched(self):
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
                    'allow_ordinary': False,
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

    def test_database_source_selection_is_text_report_auditable(self):
        report = asi676mc_calibration.format_database_source_report({
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
        })
        self.assertIn('DATABASE FITS SELECTION', report)
        self.assertIn('Requested bad-frame groups: 25', report)
        self.assertIn('Selected bad-frame groups: 9', report)
        self.assertIn('Missing local FITS rows ignored: 2', report)

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
                return_value=(payload, 'human-readable report\n'),
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
            self.assertIn('fewer than the requested 8', warnings)
            self.assertIn('no longer had a local file', warnings)
            self.assertIn('unsupported filename format', warnings)
            report = asi676mc_calibration.get_report_path(
                session_id,
                'alice',
                root,
            ).read_text(encoding='utf-8')
            self.assertTrue(report.startswith('human-readable report\n'))
            self.assertIn(
                'DATABASE FITS SELECTION',
                report,
            )

    def test_result_comparison_distinguishes_exact_negligible_and_different(self):
        payload = self._successful_payload()
        result = asi676mc_calibration._result_summary(payload)
        current = dict(calibration_engine.DEFAULT_SETTINGS)

        exact = asi676mc_calibration.compare_result_to_configuration(
            result,
            current,
        )
        self.assertEqual(exact['status'], 'exact')
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

        current['GAIN_B'] *= 1.02
        different = asi676mc_calibration.compare_result_to_configuration(
            result,
            current,
        )
        self.assertEqual(different['status'], 'different')
        self.assertIn('GAIN_B', different['differing_keys'])

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

    def test_command_line_strict_policy_remains_default(self):
        """The web relaxation must not change the command-line policy."""
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
        self.assertIn('Current calibration-evidence settings', template)
        self.assertIn('Cancel upload', template)
        self.assertIn('new AbortController()', template)
        self.assertIn('Reset / recalibrate', template)
        self.assertIn('id="calibration-browser-warning"', template)
        self.assertIn('window.asi676mcCalibrationBrowserSupported', template)
        self.assertIn('id="calibration-config-match"', template)
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
        messages = ' '.join(item['text'] for item in guidance['messages'])
        self.assertIn('Safe detection-only mode is active', messages)
        self.assertIn('Low-disk evidence collection is active', messages)

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
        messages = ' '.join(item['text'] for item in guidance['messages'])
        self.assertIn('may not retain the original bad mosaic', messages)
        self.assertIn('does not guarantee a FITS', messages)

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
        self.assertIn("get('EXCLUDE_ONLY', True)", processing_source)
        self.assertIn("get('EXCLUDE_ONLY', True)", views_source)
        self.assertIn('asi676mc_repair_was_enabled', settings_template)
        self.assertIn(
            'Only enable this feature if your ASI676MC produces purple frames.',
            settings_template,
        )


if __name__ == '__main__':
    unittest.main()
