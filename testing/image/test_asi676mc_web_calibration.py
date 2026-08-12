import io
import ast
from datetime import timedelta
from datetime import timezone
from itertools import product
import os
from pathlib import Path
import tempfile
import threading
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
                    'bad_min': 2.0,
                    'bad_max': 2.3,
                },
            },
            'rejected_files': [{
                'name': 'rejected.fit',
                'reason': 'already repaired by ASI676MC frame handling',
            }],
        }

    @staticmethod
    def _threshold_payload():
        ranges = {
            'purple_ratio': {
                'good_min': 0.852,
                'good_max': 0.905,
                'bad_min': 2.199,
                'bad_max': 2.261,
            },
            'red_side_ratio': {
                'good_min': 0.581,
                'good_max': 0.707,
                'bad_min': 1.519,
                'bad_max': 1.838,
            },
            'blue_side_ratio': {
                'good_min': 1.002,
                'good_max': 1.220,
                'bad_min': 1.420,
                'bad_max': 1.480,
            },
        }
        details = calibration_engine.DETECTION_THRESHOLD_DETAILS
        suggestions = []
        for metric, (key, label) in details.items():
            current = calibration_engine.DEFAULT_SETTINGS[key]
            values = ranges[metric]
            safe = values['good_max'] < current <= values['bad_min']
            suggestions.append({
                'metric': metric,
                'key': key,
                'label': label,
                'current': current,
                'suggested': (
                    current
                    if safe
                    else round(
                        (values['good_max'] + values['bad_min']) / 2.0,
                        3,
                    )
                ),
                'normal_max': values['good_max'],
                'purple_min': values['bad_min'],
                'change_recommended': not safe,
            })
        return {
            'outcome': 'threshold_suggestion',
            'generated_utc': '2026-08-02T12:34:56+00:00',
            'quality': {
                'detected_bad_count': 0,
                'likely_purple_count': 7,
                'likely_normal_count': 14,
                'pair_count': 7,
                'unmatched_bad_count': 0,
                'unique_good_count': 14,
                'good_bad_ratio': 2.0,
                'two_sided_count': 7,
                'exposure_levels': [0.001, 0.002],
                'explicit_camera_names': ['asi676mc'],
                'rejected_file_count': 0,
            },
            'signature_ranges': ranges,
            'threshold_suggestions': suggestions,
            'rejected_files': [],
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

            manifest = asi676mc_calibration.cancel_session(
                session_id,
                'alice',
                root,
            )
            self.assertEqual(manifest['status'], 'cancelled')
            self.assertFalse(root.joinpath(session_id, 'uploads').exists())
            self.assertTrue(manifest['sources_deleted_utc'])
            repeated = asi676mc_calibration.cancel_session(
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

    def test_database_search_checkpoint_rejects_cancelled_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_id = asi676mc_calibration.create_session(
                'alice', root
            )['session_id']

            manifest = asi676mc_calibration.database_search_checkpoint(
                session_id,
                'alice',
                root,
            )
            self.assertEqual(manifest['status'], 'uploading')
            asi676mc_calibration.cancel_session(
                session_id,
                'alice',
                root,
            )
            with self.assertRaisesRegex(
                asi676mc_calibration.CalibrationSessionError,
                'saved-FITS search was cancelled',
            ):
                asi676mc_calibration.database_search_checkpoint(
                    session_id,
                    'alice',
                    root,
                )

    @staticmethod
    def _database_record(record_id, timestamp, roles=()):
        return {
            'id': record_id,
            'path': Path('unused_{0}.fit'.format(record_id)),
            'size': 1024,
            'timestamp': float(timestamp),
            'exposure': 0.001,
            'gain': 100.0,
            'binmode': 1,
            'width': 3552,
            'height': 3552,
            'camera_name': 'ZWO CCD ASI676MC',
            'repair_status': 'normal',
            'roles': list(roles),
        }

    def test_database_group_target_maximum_is_thirty(self):
        self.assertEqual(asi676mc_calibration.DATABASE_GROUP_MAX, 30)
        with self.assertRaisesRegex(
            asi676mc_calibration.CalibrationSessionError,
            'between 7 and 30',
        ):
            asi676mc_calibration.discover_full_retention_database_evidence(
                [],
                bad_frames=[],
                target_groups=31,
                max_pair_seconds=30.0,
                settings=calibration_engine.DEFAULT_SETTINGS,
            )

    def test_full_retention_discovery_finds_unmarked_bad_frames_5000_files_back(self):
        records = []
        bad_ids = {50, 150, 250, 350, 450, 550, 650}
        for record_id in range(1, 5201):
            record = self._database_record(record_id, record_id * 20)
            if 649 <= record_id <= 651:
                record['exposure'] = 0.002
            ratio = 3.0 if record_id in bad_ids else 1.0
            record['signature'] = {
                'version': 1,
                'purple_ratio': ratio,
                'red_side_ratio': ratio,
                'blue_side_ratio': ratio,
            }
            records.append(record)

        settings = calibration_engine.asi676mc.normalize_settings({
            'PURPLE_RATIO_THRESHOLD': 10.0,
            'RED_SIDE_RATIO_THRESHOLD': 10.0,
            'BLUE_SIDE_RATIO_THRESHOLD': 10.0,
        })
        selected, summary = (
            asi676mc_calibration.discover_full_retention_database_evidence(
                records,
                bad_frames=[],
                target_groups=7,
                max_pair_seconds=30.0,
                settings=settings,
            )
        )

        selected_ids = {record['id'] for record in selected}
        self.assertTrue(bad_ids.issubset(selected_ids))
        self.assertEqual(summary['archive_scanned_file_count'], 5200)
        self.assertEqual(summary['metadata_signature_count'], 5200)
        self.assertEqual(summary['selected_group_count'], 7)
        self.assertEqual(
            summary['selection_mode'],
            'full_retention_population_groups',
        )
        self.assertTrue(summary['full_retention_exhaustive'])

    def test_full_retention_discovery_inspects_every_legacy_fits(self):
        records = [
            self._database_record(record_id, record_id * 20)
            for record_id in range(1, 31)
        ]
        records[0]['signature'] = {'version': 1}
        for record in records:
            if 20 <= record['id'] <= 22:
                record['exposure'] = 0.002
        bad_ids = {3, 6, 9, 12, 15, 18, 21}

        def inspect_legacy(path, _settings, trusted_camera_name=None):
            del trusted_camera_name
            record_id = int(path.stem.split('_')[-1])
            ratio = 3.0 if record_id in bad_ids else 1.0
            return calibration_engine.FrameRecord(
                path=path,
                timestamp=record_id * 20.0,
                exposure=0.002 if 20 <= record_id <= 22 else 0.001,
                gain=100.0,
                xbin=1,
                ybin=1,
                shape=(3552, 3552),
                bayer='RGGB',
                camera_name='ZWO CCD ASI676MC',
                signature={
                    'purple_ratio': ratio,
                    'red_side_ratio': ratio,
                    'blue_side_ratio': ratio,
                    'is_bad': record_id in bad_ids,
                },
            )

        with mock.patch.object(
            calibration_engine,
            'inspect_fits',
            side_effect=inspect_legacy,
        ) as inspect_mock:
            selected, summary = (
                asi676mc_calibration.discover_full_retention_database_evidence(
                    records,
                    bad_frames=[],
                    target_groups=7,
                    max_pair_seconds=30.0,
                    settings={},
                )
            )

        self.assertEqual(inspect_mock.call_count, 30)
        self.assertEqual(summary['legacy_fits_inspected_count'], 30)
        self.assertEqual(summary['archive_scanned_file_count'], 30)
        self.assertEqual(summary['selected_group_count'], 7)
        self.assertTrue(bad_ids.issubset({record['id'] for record in selected}))

    def test_unusable_all_purple_detector_falls_back_to_populations(self):
        records = []
        bad_ids = {2, 5, 8, 11, 14, 17, 20}
        for record_id in range(1, 22):
            record = self._database_record(record_id, record_id * 20)
            if 19 <= record_id <= 21:
                record['exposure'] = 0.002
            ratio = 3.0 if record_id in bad_ids else 1.0
            record['signature'] = {
                'purple_ratio': ratio,
                'red_side_ratio': ratio,
                'blue_side_ratio': ratio,
            }
            records.append(record)
        settings = calibration_engine.asi676mc.normalize_settings({
            'PURPLE_RATIO_THRESHOLD': 0.1,
            'RED_SIDE_RATIO_THRESHOLD': 0.1,
            'BLUE_SIDE_RATIO_THRESHOLD': 0.1,
        })

        selected, summary = (
            asi676mc_calibration.discover_full_retention_database_evidence(
                records,
                bad_frames=[],
                target_groups=7,
                max_pair_seconds=30.0,
                settings=settings,
            )
        )

        self.assertEqual(summary['detected_bad_count'], 21)
        self.assertEqual(
            summary['selection_mode'],
            'full_retention_population_groups',
        )
        self.assertTrue(bad_ids.issubset({record['id'] for record in selected}))

    def test_legacy_fits_header_overrides_stale_database_layout(self):
        records = [
            dict(
                self._database_record(record_id, record_id * 20),
                binmode=0,
                width=0,
                height=0,
                exposure=None,
                gain=None,
            )
            for record_id in range(1, 22)
        ]
        bad_ids = {2, 5, 8, 11, 14, 17, 20}

        def inspect_legacy(path, _settings, trusted_camera_name=None):
            del trusted_camera_name
            record_id = int(path.stem.split('_')[-1])
            exposure = 0.002 if 19 <= record_id <= 21 else 0.001
            ratio = 3.0 if record_id in bad_ids else 1.0
            return calibration_engine.FrameRecord(
                path=path,
                timestamp=record_id * 20.0,
                exposure=exposure,
                gain=100.0,
                xbin=1,
                ybin=1,
                shape=(3552, 3552),
                bayer='RGGB',
                camera_name='ZWO CCD ASI676MC',
                signature={
                    'purple_ratio': ratio,
                    'red_side_ratio': ratio,
                    'blue_side_ratio': ratio,
                    'is_bad': record_id in bad_ids,
                },
            )

        cached = {}
        with mock.patch.object(
            calibration_engine,
            'inspect_fits',
            side_effect=inspect_legacy,
        ) as inspect_mock:
            selected, summary = (
                asi676mc_calibration.discover_full_retention_database_evidence(
                    records,
                    bad_frames=[],
                    target_groups=7,
                    max_pair_seconds=30.0,
                    settings=calibration_engine.DEFAULT_SETTINGS,
                    signature_callback=(
                        lambda record_id, signature:
                        cached.__setitem__(record_id, signature)
                    ),
                )
            )

        self.assertEqual(inspect_mock.call_count, 21)
        self.assertEqual(len(cached), 21)
        self.assertEqual(summary['selected_group_count'], 7)
        self.assertTrue(bad_ids.issubset({record['id'] for record in selected}))

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
                    'camera_name': 'ZWO CCD ASI676MC',
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
            asi676mc_calibration.cancel_session(
                session_id,
                'alice',
                session_root,
            )
            self.assertTrue(all(record['path'].is_file() for record in records))

    def test_database_staging_skips_a_selected_file_that_disappeared(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_root = root.joinpath('sessions')
            available = root.joinpath('available.fit')
            available.write_bytes(b'database fits placeholder')
            missing = root.joinpath('missing.fit')
            records = [
                {
                    'id': 1,
                    'path': missing,
                    'camera_name': 'ZWO CCD ASI676MC',
                },
                {
                    'id': 2,
                    'path': available,
                    'camera_name': 'ZWO CCD ASI676MC',
                },
            ]
            session_id = asi676mc_calibration.create_session(
                'alice', session_root
            )['session_id']

            manifest = asi676mc_calibration.stage_database_files(
                session_id,
                'alice',
                records,
                session_root,
            )

        self.assertEqual(len(manifest['files']), 1)
        self.assertEqual(manifest['files'][0]['database_id'], 2)
        self.assertEqual(
            manifest['source']['staging_skipped_file_count'],
            1,
        )

    def test_staging_limit_failure_names_the_actual_limit(self):
        records = []
        bad_ids = {2, 5, 8, 11, 14, 17, 20}
        for record_id in range(1, 22):
            record = self._database_record(record_id, record_id * 20)
            record['size'] = 1024
            if 19 <= record_id <= 21:
                record['exposure'] = 0.002
            ratio = 3.0 if record_id in bad_ids else 1.0
            record['signature'] = {
                'purple_ratio': ratio,
                'red_side_ratio': ratio,
                'blue_side_ratio': ratio,
            }
            records.append(record)

        with mock.patch.object(
            asi676mc_calibration,
            'DATABASE_MAX_BYTES',
            6500,
        ):
            with self.assertRaisesRegex(
                calibration_engine.CalibrationError,
                'within the 200-file/2-GiB evidence staging limit',
            ):
                asi676mc_calibration.discover_full_retention_database_evidence(
                    records,
                    bad_frames=[],
                    target_groups=7,
                    max_pair_seconds=30.0,
                    settings=calibration_engine.DEFAULT_SETTINGS,
                )

    def test_database_staging_copies_when_hardlinks_are_unavailable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root.joinpath('source.fit')
            source.write_bytes(b'database fits placeholder')
            session_root = root.joinpath('sessions')
            session_id = asi676mc_calibration.create_session(
                'alice', session_root
            )['session_id']
            records = [{
                'id': 1,
                'path': source,
                'camera_name': 'ZWO CCD ASI676MC',
            }]
            with mock.patch.object(os, 'link', side_effect=OSError('cross-device')):
                manifest = asi676mc_calibration.stage_database_files(
                    session_id,
                    'alice',
                    records,
                    session_root,
                )

            staged = session_root.joinpath(
                session_id,
                'uploads',
                manifest['files'][0]['name'],
            )
            self.assertEqual(manifest['files'][0]['link_type'], 'copy')
            self.assertTrue(staged.is_file())
            self.assertFalse(staged.is_symlink())

    def test_database_copy_cancellation_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root.joinpath('source.fit')
            destination = root.joinpath('staged.fit')
            source.write_bytes(
                b'x' * (asi676mc_calibration.TRANSFER_CHUNK_BYTES + 1)
            )
            cancel_marker = mock.Mock()
            cancel_marker.exists.side_effect = [False, True]

            with self.assertRaisesRegex(
                asi676mc_calibration.CalibrationSessionError,
                'database search was cancelled',
            ):
                asi676mc_calibration._copy_database_file(
                    source,
                    destination,
                    cancel_marker,
                )

            self.assertTrue(source.is_file())
            self.assertFalse(destination.exists())
            self.assertFalse(root.joinpath('staged.fit.part').exists())

    def test_database_staging_rejects_a_mixed_upload_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_root = root.joinpath('sessions')
            session_id = asi676mc_calibration.create_session(
                'alice', session_root
            )['session_id']
            asi676mc_calibration.store_upload(
                session_id,
                'alice',
                self._fits_upload('browser.fit'),
                session_root,
            )
            source = root.joinpath('database.fit')
            source.write_bytes(b'database fits placeholder')
            with self.assertRaisesRegex(
                asi676mc_calibration.CalibrationSessionError,
                'already contains temporary files',
            ):
                asi676mc_calibration.stage_database_files(
                    session_id,
                    'alice',
                    [{
                        'id': 1,
                        'path': source,
                        'camera_name': 'ZWO CCD ASI676MC',
                    }],
                    session_root,
                )
            self.assertTrue(
                session_root.joinpath(
                    session_id,
                    'uploads',
                    'browser.fit',
                ).is_file()
            )

    def test_active_session_quota_is_per_owner_and_recoverable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sessions = [
                asi676mc_calibration.create_session('alice', root)
                for _index in range(
                    asi676mc_calibration.MAX_ACTIVE_SESSIONS_PER_OWNER
                )
            ]
            with self.assertRaisesRegex(
                asi676mc_calibration.CalibrationSessionError,
                'Finish or cancel',
            ):
                asi676mc_calibration.create_session('alice', root)

            asi676mc_calibration.cancel_session(
                sessions[0]['session_id'],
                'alice',
                root,
            )
            replacement = asi676mc_calibration.create_session('alice', root)
            self.assertEqual(replacement['status'], 'uploading')

    def test_parallel_uploads_serialize_manifest_updates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_id = asi676mc_calibration.create_session(
                'alice', root
            )['session_id']
            errors = []

            def upload(index):
                try:
                    asi676mc_calibration.store_upload(
                        session_id,
                        'alice',
                        self._fits_upload(
                            'parallel_{0}.fit'.format(index)
                        ),
                        root,
                    )
                except Exception as error:  # pragma: no cover - assertion aid
                    errors.append(error)

            threads = [
                threading.Thread(target=upload, args=(index,))
                for index in range(12)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(5)

            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertFalse(errors)
            manifest = asi676mc_calibration._read_manifest(
                root.joinpath(session_id)
            )
            self.assertEqual(len(manifest['files']), 12)
            self.assertEqual(manifest['total_bytes'], 12 * 2880)
            self.assertFalse(list(
                root.joinpath(session_id, 'uploads').glob('*.part')
            ))

    def test_parallel_session_creation_enforces_global_quota(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            created = []
            rejected = []

            def create(index):
                try:
                    created.append(asi676mc_calibration.create_session(
                        'owner-{0}'.format(index),
                        root,
                    ))
                except asi676mc_calibration.CalibrationSessionError as error:
                    rejected.append(str(error))

            threads = [
                threading.Thread(target=create, args=(index,))
                for index in range(10)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(5)

            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(
                len(created),
                asi676mc_calibration.MAX_ACTIVE_SESSIONS_GLOBAL,
            )
            self.assertEqual(
                len(rejected),
                10 - asi676mc_calibration.MAX_ACTIVE_SESSIONS_GLOBAL,
            )
            self.assertTrue(all(
                'currently busy' in message
                for message in rejected
            ))

    def test_stale_session_is_recovered_before_enforcing_quota(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sessions = [
                asi676mc_calibration.create_session('alice', root)
                for _index in range(
                    asi676mc_calibration.MAX_ACTIVE_SESSIONS_PER_OWNER
                )
            ]
            stale_dir = root.joinpath(sessions[0]['session_id'])
            stale_manifest = asi676mc_calibration._read_manifest(stale_dir)
            stale_manifest['status'] = 'queued'
            stale_manifest['updated_utc'] = '2000-01-01T00:00:00+00:00'
            asi676mc_calibration._atomic_write_json(
                stale_dir.joinpath('manifest.json'),
                stale_manifest,
            )

            replacement = asi676mc_calibration.create_session('alice', root)

            self.assertEqual(replacement['status'], 'uploading')
            recovered = asi676mc_calibration._read_manifest(stale_dir)
            self.assertEqual(recovered['status'], 'failed')
            self.assertIn('stopped responding', recovered['error'])
            self.assertFalse(stale_dir.joinpath('uploads').exists())

    def test_stale_uploading_session_is_recovered_before_quota(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sessions = [
                asi676mc_calibration.create_session('alice', root)
                for _index in range(
                    asi676mc_calibration.MAX_ACTIVE_SESSIONS_PER_OWNER
                )
            ]
            stale_dir = root.joinpath(sessions[0]['session_id'])
            stale_manifest = asi676mc_calibration._read_manifest(stale_dir)
            stale_manifest['updated_utc'] = '2000-01-01T00:00:00+00:00'
            asi676mc_calibration._atomic_write_json(
                stale_dir.joinpath('manifest.json'),
                stale_manifest,
            )

            replacement = asi676mc_calibration.create_session('alice', root)

            self.assertEqual(replacement['status'], 'uploading')
            recovered = asi676mc_calibration._read_manifest(stale_dir)
            self.assertEqual(recovered['status'], 'failed')
            self.assertIn('upload stopped responding', recovered['error'])
            self.assertFalse(stale_dir.joinpath('uploads').exists())

    def test_manifest_json_never_serializes_nan_or_infinity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir).joinpath('strict.json')
            with self.assertRaises(ValueError):
                asi676mc_calibration._atomic_write_json(
                    path,
                    {'unsafe': float('nan')},
                )
            self.assertFalse(path.exists())
            self.assertFalse(list(path.parent.glob('.manifest-*.tmp')))

    def test_worker_claim_is_single_use(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = asi676mc_calibration.create_session(
                'alice',
                root,
                camera_identity={
                    'id': 7,
                    'uuid': 'camera-uuid',
                    'name': 'ZWO CCD ASI676MC',
                },
            )
            session_id = manifest['session_id']
            for index in range(14):
                asi676mc_calibration.store_upload(
                    session_id,
                    'alice',
                    self._fits_upload('evidence_{0}.fit'.format(index)),
                    root,
                )
            asi676mc_calibration.mark_queued(
                session_id,
                'alice',
                task_id=1,
                max_pair_seconds=90.0,
                settings=calibration_engine.DEFAULT_SETTINGS,
                storage_root=root,
            )
            with mock.patch.object(
                calibration_engine,
                'calibrate_folder',
                return_value=self._successful_payload(),
            ) as calibrate_folder:
                asi676mc_calibration.run_calibration_session(
                    session_id,
                    storage_root=root,
                )
                with self.assertRaisesRegex(
                    asi676mc_calibration.CalibrationSessionError,
                    'not queued',
                ):
                    asi676mc_calibration.run_calibration_session(
                        session_id,
                        storage_root=root,
                    )
            self.assertEqual(
                calibrate_folder.call_args.kwargs['trusted_camera_name'],
                'ZWO CCD ASI676MC',
            )

    def test_background_database_session_discovers_then_stages_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root.joinpath('database')
            source_root.mkdir()
            manifest = asi676mc_calibration.create_session(
                'alice',
                root,
                camera_identity={
                    'id': 7,
                    'uuid': 'camera-uuid',
                    'name': 'ZWO CCD ASI676MC',
                },
            )
            records = []
            bad_ids = {2, 5, 8, 11, 14, 17, 20}
            for record_id in range(1, 22):
                path = source_root.joinpath('{0}.fit'.format(record_id))
                path.write_bytes(b'SIMPLE database evidence')
                ratio = 3.0 if record_id in bad_ids else 1.0
                record = self._database_record(record_id, record_id * 20)
                record.update({
                    'path': path,
                    'size': path.stat().st_size,
                    'signature': {
                        'version': 1,
                        'purple_ratio': ratio,
                        'red_side_ratio': ratio,
                        'blue_side_ratio': ratio,
                    },
                })
                if 19 <= record_id <= 21:
                    record['exposure'] = 0.002
                records.append(record)

            source_details = {
                'kind': 'database',
                'selection_mode': 'background_full_retention',
                'camera_id': 7,
                'camera_uuid': 'camera-uuid',
                'camera_name': 'ZWO CCD ASI676MC',
                'retention_days': 4,
                'retention_cutoff': '2026-08-06',
                'requested_group_count': 7,
            }
            asi676mc_calibration.mark_queued(
                manifest['session_id'],
                'alice',
                task_id=2,
                max_pair_seconds=30.0,
                settings=calibration_engine.DEFAULT_SETTINGS,
                source_details=source_details,
                storage_root=root,
            )
            loader = mock.Mock(return_value={
                'fits_records': records,
                'bad_frames': [],
                'source_details': {
                    'database_fits_count': len(records),
                    'local_fits_count': len(records),
                    'missing_local_count': 0,
                    'unsupported_count': 0,
                },
            })
            with mock.patch.object(
                calibration_engine,
                'calibrate_folder',
                return_value=self._successful_payload(),
            ) as calibrate_folder:
                result = asi676mc_calibration.run_calibration_session(
                    manifest['session_id'],
                    storage_root=root,
                    database_loader=loader,
                )

            loader.assert_called_once()
            self.assertEqual(result['source']['archive_scanned_file_count'], 21)
            self.assertEqual(result['source']['selected_group_count'], 7)
            self.assertEqual(
                result['source']['selection_mode'],
                'full_retention_detector_groups',
            )
            self.assertTrue(calibrate_folder.call_args.kwargs['metadata_by_name'])
            completed = asi676mc_calibration._read_manifest(
                root.joinpath(manifest['session_id'])
            )
            self.assertEqual(completed['status'], 'success')
            self.assertFalse(
                root.joinpath(manifest['session_id'], 'uploads').exists()
            )
            self.assertTrue(completed.get('sources_deleted_utc'))
            report = root.joinpath(
                manifest['session_id'],
                'asi676mc_calibration_report.txt',
            ).read_text(encoding='utf-8')
            self.assertIn(
                'Database search coverage: Complete retained archive',
                report,
            )
            self.assertIn('Retained FITS searched: 21', report)

    def test_empty_manual_session_still_cannot_be_queued(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = asi676mc_calibration.create_session('alice', root)
            with self.assertRaisesRegex(
                asi676mc_calibration.CalibrationSessionError,
                'Select at least 14 FITS',
            ):
                asi676mc_calibration.mark_queued(
                    manifest['session_id'],
                    'alice',
                    task_id=3,
                    max_pair_seconds=90.0,
                    settings=calibration_engine.DEFAULT_SETTINGS,
                    storage_root=root,
                )

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
                'requested_group_count': 25,
                'selection_mode': 'progressive_search',
                'selected_marked_group_count': 3,
                'selected_file_count': 19,
                'initial_scan_file_count': 19,
                'available_file_count': 19,
                'metadata_signature_count': 9,
                'excluded_repaired_standard_count': 2,
                'excluded_duplicate_standard_count': 1,
                'database_fits_count': 40,
                'missing_local_count': 2,
                'unsupported_count': 1,
            },
        })

        self.assertTrue(report.startswith(
            'indi-allsky ASI676MC purple-frame calibration report\n'
        ))
        self.assertIn('Status: Successful', report)
        self.assertIn('Final validation repaired all', report)
        self.assertIn('Recommended calibration values', report)
        self.assertIn('Configured when started', report)
        self.assertIn('Meaningful change', report)
        self.assertIn('Tools > ASI676MC Calibration', report)
        self.assertIn('can save settings on', report)
        self.assertIn('Config page', report)
        self.assertIn(
            'At the start of calibration, one or more derived values differed',
            report,
        )
        self.assertIn('Method: Saved FITS search', report)
        self.assertIn('Target purple-frame groups: 25', report)
        self.assertIn('Selection path: progressive ratio search', report)
        self.assertIn('Usable marked groups found: 3', report)
        self.assertIn('Initial fallback search target: 19 FITS files', report)
        self.assertIn('FITS inspected: 19 of 19', report)
        self.assertIn('Saved ratio metadata available: 9', report)
        self.assertIn('Post-repair standard FITS excluded: 2', report)
        self.assertIn('Duplicate standard FITS excluded: 1', report)
        self.assertIn('FITS retention cutoff: 2026-07-23 (10 days)', report)
        self.assertIn('Entries whose files were missing: 2', report)
        self.assertIn('configured threshold 1.500', report)
        self.assertIn('configured threshold 1.150', report)
        self.assertIn('configured threshold 1.750', report)
        self.assertIn('The ranges shown below do not overlap', report)
        self.assertIn('complete database-marked groups', report)
        self.assertIn('compact evidence set', report)
        self.assertIn('already_fixed.fit:', report)
        self.assertIn('already marked as repaired', report)
        self.assertIn('untouched', report)
        self.assertIn('diagnostic FITS captured before repair', report)
        self.assertNotIn(
            'already repaired by ASI676MC frame handling',
            report,
        )
        self.assertIn('Rejected-file details are', report)
        self.assertIn('listed later in this report.', report)
        self.assertNotIn('DATABASE FITS SELECTION', report)
        self.assertNotIn('REVIEW THESE CALIBRATION VALUES', report)
        self.assertNotIn('Source:', report)
        self.assertNotIn('/private/calibration/session/uploads', report)
        self.assertNotIn('operator', report.lower())
        self.assertNotIn('They repaired', report)

    def test_report_timestamp_uses_explicit_local_timezone(self):
        local_timezone = timezone(timedelta(hours=2), name='CEST')
        with mock.patch.object(
            asi676mc_calibration,
            '_local_timezone',
            return_value=local_timezone,
        ):
            formatted = asi676mc_calibration._format_report_timestamp(
                '2026-08-02T12:34:56+00:00'
            )

        self.assertEqual(
            formatted,
            '2026-08-02 14:34:56 CEST (UTC+02:00)',
        )

    def test_report_configuration_comparison_uses_historical_reference_time(
        self,
    ):
        payload = self._successful_payload()
        manifest = {
            'settings': dict(calibration_engine.DEFAULT_SETTINGS),
            'max_pair_seconds': 90.0,
            'files': [],
            'source': {'kind': 'upload', 'selected_file_count': 21},
        }
        exact_report = ' '.join(
            asi676mc_calibration.format_integrated_report(
                payload,
                manifest,
            ).split()
        )
        self.assertIn(
            'At the start of calibration, the derived values matched all '
            'seven configured values, so no update was necessary.',
            exact_report,
        )

        equivalent_settings = dict(calibration_engine.DEFAULT_SETTINGS)
        equivalent_settings['GAIN_R'] *= 1.004
        manifest['settings'] = equivalent_settings
        equivalent_report = ' '.join(
            asi676mc_calibration.format_integrated_report(
                payload,
                manifest,
            ).split()
        )
        self.assertIn(
            'At the start of calibration, the differences between the derived '
            'and configured values were too small to produce a visible change.',
            equivalent_report,
        )
        self.assertNotIn('Applying it was unlikely', equivalent_report)

    def test_report_download_name_uses_local_completion_time(self):
        local_timezone = timezone(timedelta(hours=2), name='CEST')
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = asi676mc_calibration.create_session('alice', root)
            session_dir = root.joinpath(manifest['session_id'])
            manifest['status'] = 'success'
            manifest['completed_utc'] = '2026-08-02T12:34:56+00:00'
            asi676mc_calibration._write_manifest(session_dir, manifest)
            expected_path = session_dir.joinpath(
                'asi676mc_calibration_report.txt'
            )
            expected_path.write_text('report\n', encoding='utf-8')

            with mock.patch.object(
                asi676mc_calibration,
                '_local_timezone',
                return_value=local_timezone,
            ):
                report_path, download_name = (
                    asi676mc_calibration.get_report_download(
                        manifest['session_id'],
                        'alice',
                        root,
                    )
                )

        self.assertEqual(report_path, expected_path)
        self.assertEqual(
            download_name,
            '2026-08-02_14-34-56_asi676mc_calibration_report.txt',
        )

    def test_threshold_suggestion_is_preliminary_and_applies_only_changes(self):
        payload = self._threshold_payload()
        report = asi676mc_calibration.format_integrated_report(payload, {
            'max_pair_seconds': 90.0,
            'files': [],
            'source': {
                'kind': 'database',
                'camera_name': 'ASI676MC',
                'requested_group_count': 30,
                'selection_mode': 'progressive_search',
                'selected_marked_group_count': 0,
                'selected_file_count': 21,
                'initial_scan_file_count': 21,
                'available_file_count': 21,
                'metadata_signature_count': 0,
                'excluded_repaired_standard_count': 2,
                'retention_cutoff': '2026-07-23',
                'retention_days': 10,
            },
        })
        self.assertIn('Status: Preliminary threshold suggestion', report)
        self.assertIn('No repair constants were derived', report)
        self.assertIn('each of the three measured ratios separated', report)
        self.assertIn('Each reported range has a clean gap', report)
        self.assertIn('can save settings on', report)
        self.assertIn('Config page', report)
        self.assertIn('Change recommended', report)
        self.assertIn('Current value is already safe', report)
        self.assertIn('Post-repair standard FITS excluded: 2', report)
        self.assertNotIn('Recommended calibration values', report)
        self.assertNotIn('operator', report.lower())

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_id = asi676mc_calibration.create_session(
                'alice', root
            )['session_id']
            for index in range(14):
                asi676mc_calibration.store_upload(
                    session_id,
                    'alice',
                    self._fits_upload('threshold_{0:02d}.fit'.format(index)),
                    root,
                )
            asi676mc_calibration.mark_queued(
                session_id,
                'alice',
                task_id=43,
                max_pair_seconds=90.0,
                settings=calibration_engine.DEFAULT_SETTINGS,
                source_details={
                    'kind': 'upload',
                    'selected_file_count': 14,
                },
                storage_root=root,
            )
            with mock.patch.object(
                calibration_engine,
                'calibrate_folder',
                return_value=payload,
            ):
                result = asi676mc_calibration.run_calibration_session(
                    session_id,
                    root,
                )

            self.assertEqual(result['outcome'], 'threshold_suggestion')
            self.assertNotIn('values', result)
            self.assertEqual(result['quality']['likely_purple_count'], 7)
            _manifest, completed, values = (
                asi676mc_calibration.get_completed_result(
                    session_id,
                    'alice',
                    root,
                )
            )
            self.assertEqual(completed['outcome'], 'threshold_suggestion')
            self.assertEqual(values, {'BLUE_SIDE_RATIO_THRESHOLD': 1.32})

    def test_integrated_upload_report_explains_cleanup_and_one_day_grammar(self):
        payload = self._successful_payload()
        payload['quality']['rejected_file_count'] = 0
        payload['quality']['unmatched_bad_count'] = 0
        payload['quality']['bound_session_camera_count'] = 21
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
        self.assertIn(
            '21 uploaded FITS files did not name the camera model',
            report,
        )

        payload['quality'].pop('bound_session_camera_count')
        payload['quality']['bound_database_camera_count'] = 21
        payload['quality']['database_metadata_camera_count'] = 0
        payload['quality']['explicit_camera_names'] = []

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
        self.assertIn(
            '21 saved FITS files did not name the camera model',
            database_report,
        )
        self.assertIn('saved database entries belonged to the selected', database_report)
        self.assertIn(
            'camera-bound database records for 21 saved files',
            database_report,
        )
        self.assertNotIn('21 uploaded FITS files', database_report)
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
                    'requested_group_count': 20,
                    'selection_mode': 'progressive_search',
                    'selected_marked_group_count': 4,
                    'selected_file_count': 14,
                    'initial_scan_file_count': 14,
                    'available_file_count': 14,
                    'metadata_signature_count': 7,
                    'excluded_repaired_standard_count': 1,
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
            self.assertIn('fewer than seven ready-to-use groups', warnings)
            self.assertIn('checked all 14 suitable saved FITS', warnings)
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
                'requested_group_count': 20,
                'selection_mode': 'marked_groups',
                'selected_marked_group_count': 14,
                'missing_local_count': 1,
                'unsupported_count': 1,
            },
        )
        self.assertEqual(len(warnings), 3)
        self.assertIn('14 usable purple-frame groups', warnings[0])
        self.assertIn('requested 20', warnings[0])
        self.assertIn('3 of 7 purple frames had normal references', warnings[1])
        self.assertIn('the other 4 purple frames had one nearby', warnings[1])
        self.assertIn('normal frames were used as a reference more than once', warnings[1])
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
        self.assertIn('normal frames were used as a reference more than once', reuse_only[0])
        self.assertIn('more different normal reference frames', reuse_only[0])

        fully_independent = asi676mc_calibration._result_warnings({
            'matched_bad_count': 7,
            'two_sided_count': 7,
            'matched_normal_count': 14,
            'unmatched_bad_count': 0,
            'rejected_file_count': 0,
        })
        self.assertEqual(fully_independent, [])

        nearly_complete = asi676mc_calibration._result_warnings({
            'matched_bad_count': 25,
            'two_sided_count': 24,
            'matched_normal_count': 49,
            'unmatched_bad_count': 0,
            'rejected_file_count': 0,
        })
        self.assertEqual(nearly_complete, [])

        nearly_complete_with_rejected_file = (
            asi676mc_calibration._result_warnings({
                'matched_bad_count': 25,
                'two_sided_count': 24,
                'matched_normal_count': 49,
                'unmatched_bad_count': 0,
                'rejected_file_count': 1,
            })
        )
        self.assertEqual(len(nearly_complete_with_rejected_file), 1)
        self.assertIn(
            '1 FITS file that could not be read or used',
            nearly_complete_with_rejected_file[0],
        )
        self.assertNotIn(
            '24 of 25 purple frames',
            nearly_complete_with_rejected_file[0],
        )

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

        rejection_summary = asi676mc_calibration._friendly_failure_message(
            'no compatible RAW16 RGGB FITS files found; rejection summary: '
            '{"missing explicit BAYERPAT=RGGB metadata":2,'
            '"calibration requires XBINNING=1 and YBINNING=1":1}'
        )
        self.assertIn('None of the 3 selected FITS', rejection_summary)
        self.assertIn('2 files:', rejection_summary)
        self.assertIn('does not state BAYERPAT=RGGB', rejection_summary)
        self.assertIn('1x1-binned', rejection_summary)
        self.assertNotIn('rejection summary', rejection_summary)

        cleanup_failure = asi676mc_calibration._friendly_failure_message(
            'no compatible RAW16 RGGB FITS files found; rejection summary: '
            '{"missing explicit BAYERPAT=RGGB metadata":3}; private '
            'calibration input cleanup also failed: access denied'
        )
        self.assertIn('Reason for all 3', cleanup_failure)
        self.assertIn('BAYERPAT=RGGB', cleanup_failure)
        self.assertNotIn('access denied', cleanup_failure)

        threshold_population = asi676mc_calibration._friendly_failure_message(
            'configured detection produced 0 purple and 9 normal FITS. '
            'Automatic threshold analysis could not make a safe suggestion: '
            'at least 14 compatible FITS are required for automatic threshold '
            'analysis'
        )
        self.assertIn('Fewer than 14 compatible files', threshold_population)
        self.assertIn('No settings were changed', threshold_population)

        unstable_gain = asi676mc_calibration._friendly_failure_message(
            'GAIN_R varies too much between pairs (relative MAD 0.300)'
        )
        self.assertIn('changes too much between frame groups', unstable_gain)

        wrong_failure_type = asi676mc_calibration._friendly_failure_message(
            'evidence does not confirm the ASI676MC one-row phase shift: '
            'C:\\private\\purple.fit'
        )
        self.assertIn('do not behave like', wrong_failure_type)
        self.assertNotIn('purple.fit', wrong_failure_type)

        safety_failure = asi676mc_calibration._friendly_failure_message(
            'normal-frame validation mutated C:\\private\\normal.fit'
        )
        self.assertIn('final safety checks', safety_failure)
        self.assertNotIn('normal.fit', safety_failure)

        no_detection = asi676mc_calibration._friendly_failure_message(
            'no FITS matched the configured purple-frame detector'
        )
        self.assertIn('No FITS matched', no_detection)
        self.assertIn('different detection thresholds', no_detection)

        threshold_failure = (
            'Configured Blue-side ratio threshold is 1.750, but a frame '
            'currently classified as normal reaches 1.800.'
        )
        self.assertEqual(
            asi676mc_calibration._friendly_failure_message(
                threshold_failure
            ),
            threshold_failure,
        )

        unexpected = asi676mc_calibration._friendly_failure_message(
            'cannot read C:\\private\\camera\\secret.fit'
        )
        self.assertIn('unexpected error', unexpected)
        self.assertNotIn('secret.fit', unexpected)

    def test_rejected_fits_reasons_are_plain_and_actionable(self):
        cases = (
            (
                'expected RGGB Bayer data, got BGGR',
                ('marked as BGGR', 'Use unmodified'),
            ),
            (
                'repair requires unsigned 16-bit RAW data',
                ('not unsigned 16-bit RAW data', 'RAW16'),
            ),
            (
                'FITS does not explicitly identify an ASI676MC camera',
                ('does not identify an ASI676MC', 'saved-FITS search'),
            ),
            (
                'missing usable DATE-OBS/DATE and filename timestamp',
                ('No usable capture time', 'original timestamped FITS'),
            ),
        )
        for internal_reason, expected_parts in cases:
            with self.subTest(reason=internal_reason):
                friendly = (
                    asi676mc_calibration._friendly_rejected_file_reason(
                        internal_reason
                    )
                )
                for expected in expected_parts:
                    self.assertIn(expected, friendly)

    def test_task_failure_text_is_actionable_and_bounded(self):
        short = asi676mc_calibration.task_failure_message(
            'matched failures cover only one exposure; collect more varied data'
        )
        self.assertIn('at least two exposure settings', short)

        long_failure = (
            'no compatible RAW16 RGGB FITS files found; rejection summary: '
            '{"missing explicit BAYERPAT=RGGB metadata":120,'
            '"calibration requires XBINNING=1 and YBINNING=1":80}'
        )
        bounded = asi676mc_calibration.task_failure_message(long_failure)
        self.assertLessEqual(len(bounded), 255)
        self.assertIn('Open Tools > ASI676MC Calibration', bounded)
        self.assertNotIn('rejection summary', bounded)

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
                {'asi676mc_calibration_required', 'login_required'},
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
        self.assertIn('Save values and reload configuration', template)
        self.assertIn('Current FITS capture settings', template)
        self.assertIn('original, unprocessed ASI676MC RAW16 FITS', template)
        self.assertIn('skip files', template)
        self.assertIn('message explains what to check', template)
        self.assertIn('id="calibration-capture-facts"', template)
        self.assertIn(
            'class="calibration-fact-grid tw:grid-cols-1 '
            'tw:sm:grid-cols-2 tw:lg:grid-cols-3 tw:mb-4"',
            template,
        )
        self.assertIn('id="calibration-settings"', template)
        self.assertIn('>Calibration settings</div>', template)
        self.assertIn('calibration-camera-control', template)
        self.assertIn('calibration-reference-control', template)
        self.assertIn('.calibration-setting-panel', template)
        self.assertIn(
            'tw:grid tw:grid-cols-1 tw:lg:grid-cols-2 '
            'tw:items-stretch tw:gap-4',
            template,
        )
        self.assertEqual(
            template.count('class="calibration-setting-panel"'),
            2,
        )
        self.assertIn(
            "CAMERA_ID.label(class='tw:label-text tw:font-semibold "
            "tw:block tw:mb-2')",
            template,
        )
        self.assertIn(
            "MAX_PAIR_SECONDS.label(class='tw:label-text tw:font-semibold "
            "tw:block tw:mb-2')",
            template,
        )
        self.assertNotIn('max-width: 14rem;', template)
        self.assertIn(
            'id="calibration-quality" class="calibration-fact-grid '
            'tw:grid-cols-1 tw:sm:grid-cols-2 tw:lg:grid-cols-4"',
            template,
        )
        self.assertIn('padding: 1rem;', template)
        self.assertNotIn(
            'grid-template-columns: repeat(auto-fit',
            template,
        )
        quality_card_body = template.split(
            'function qualityCard(label, value) {',
            1,
        )[1].split('function countedResultItem(', 1)[0]
        self.assertIn("{'class': 'calibration-fact'}", quality_card_body)
        self.assertNotIn('col-sm-6 col-lg-3', quality_card_body)
        self.assertNotIn('p-3', quality_card_body)
        self.assertNotIn(
            '<div class="card-header fw-semibold">Reference matching</div>',
            template,
        )
        shell_style = template.split('#calibration-shell {', 1)[1].split(
            '}',
            1,
        )[0]
        self.assertIn('width: 100%;', shell_style)
        self.assertNotIn('max-width:', shell_style)
        self.assertIn('Cancel upload', template)
        self.assertIn('Cancel saved-FITS search', template)
        self.assertIn('Retry cancellation', template)
        self.assertIn('new AbortController()', template)
        self.assertIn('session_id: activeCalibrationSessionId', template)
        self.assertIn('signal: activeRequestController.signal', template)
        self.assertIn(
            'Saved-FITS search cancelled. Database FITS were not changed.',
            template,
        )
        self.assertIn('Reset / recalibrate', template)
        self.assertIn('id="calibration-failure-reset"', template)
        self.assertIn('Reset / try again', template)
        self.assertIn('id="calibration-progress-error"', template)
        self.assertLess(
            template.index('id="calibration-reset"'),
            template.index('id="calibration-report-download"'),
        )
        self.assertIn(
            'calibration-source-card tw:bg-base-200 tw:border',
            template,
        )
        self.assertIn(
            'tw:grid tw:grid-cols-1 tw:lg:grid-cols-2 tw:gap-5',
            template,
        )
        self.assertIn('Upload a FITS collection', template)
        self.assertIn(
            'calibration-values-table tw:table tw:table-zebra',
            template,
        )
        self.assertIn('calibration-callout calibration-callout-info', template)
        self.assertIn('.calibration-callout-success', template)
        self.assertIn('.calibration-method-badge', template)
        self.assertIn('border-color: var(--color-info);', template)
        self.assertIn(
            'tw:badge tw:badge-outline calibration-method-badge',
            template,
        )
        self.assertNotIn("? 'text-success' : 'text-info'", template)
        self.assertIn('id="calibration-browser-warning"', template)
        self.assertIn('window.asi676mcCalibrationBrowserSupported', template)
        self.assertIn('function calibrationPairSeparation()', template)
        self.assertIn('Number.isFinite(seconds)', template)
        self.assertIn('function validateSelectedFits(files)', template)
        self.assertIn('calibrationMaxSessionBytes', template)
        self.assertIn('Manual upload accepts uncompressed', template)
        self.assertIn('Select 14 to 80 FITS', template)
        self.assertIn('each file may be up to 256 MiB', template)
        self.assertIn('frames do not need to have been marked as purple', template)
        self.assertIn('The tool first applies the current', template)
        self.assertIn('it looks for a separate', template)
        self.assertIn('groups across at least two exposure levels', template)
        self.assertIn('possible, two nearby normal frames', template)
        self.assertIn('default at 20; choose more only', template)
        automatic_card = template.split(
            '<span>Use saved FITS</span>',
            1,
        )[1].split('<span>Upload a FITS collection</span>', 1)[0]
        self.assertNotIn('200-FITS', automatic_card)
        self.assertNotIn('2-GiB', automatic_card)
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
        self.assertIn('Additional result information', template)
        self.assertIn('new Set(result.warnings || [])', template)
        self.assertIn('configuration_comparison', template)
        self.assertIn('Current configured value', template)
        self.assertIn('configurationComparison.configured_values', template)
        self.assertIn('Find saved FITS and calibrate', template)
        self.assertIn('DATABASE_GROUP_LIMIT', template)
        self.assertIn('target_groups: targetGroups', template)
        self.assertIn('Searching for missed purple frames', template)
        self.assertIn('function renderThresholdSuggestion(', template)
        self.assertIn("result.outcome === 'threshold_suggestion'", template)
        self.assertIn('id="calibration-threshold-values"', template)
        self.assertIn('Apply thresholds and reload', template)
        self.assertIn('id="confirm-higher-population"', template)
        self.assertIn('id="calibration-population-evidence"', template)
        self.assertIn('confirm_higher_population', template)
        self.assertIn('id="calibration-threshold-advisory"', template)
        self.assertIn(
            'any threshold change must be made manually in Image Settings',
            template,
        )
        self.assertIn('No repair values', template)
        self.assertIn('calibrationDatabaseUrl', template)
        self.assertIn(
            '#calibration-setup-panel, #calibration-progress-panel',
            template,
        )
        self.assertIn('function showCalibrationSetupView()', template)
        self.assertIn('function showCalibrationProgressView()', template)
        self.assertIn(
            'function showCalibrationFailure(sessionId, message)',
            template,
        )
        self.assertIn(
            "$('#calibration-setup-panel, #calibration-results').hide();",
            template,
        )
        self.assertIn('showCalibrationProgressView();', template)
        self.assertIn("'Preparing upload'", template)
        self.assertIn("'Restoring calibration'", template)
        self.assertIn(
            "progressPanel[0].scrollIntoView({behavior: 'smooth', block: 'nearest'});",
            template,
        )
        show_error_body = template.split(
            'function showCalibrationError(message) {',
            1,
        )[1].split('function showCalibrationNotice(message) {', 1)[0]
        reset_body = template.split(
            'function resetCalibrationInterface() {',
            1,
        )[1].split('function setCalibrationProgress(', 1)[0]
        progress_body = template.split(
            'function setCalibrationProgress(',
            1,
        )[1].split('function renderSelectedFiles()', 1)[0]
        upload_body = template.split(
            'async function submitCalibration() {',
            1,
        )[1].split('async function submitDatabaseCalibration()', 1)[0]
        self.assertIn('showCalibrationSetupView();', show_error_body)
        self.assertIn('showCalibrationSetupView();', reset_body)
        self.assertIn('showCalibrationProgressView();', progress_body)
        self.assertLess(
            upload_body.index("'Preparing upload'"),
            upload_body.index('const session = await createCalibrationSession();'),
        )
        self.assertIn('rememberCalibrationSession', template)
        self.assertIn('sessionStorage', template)
        self.assertIn('restoreRememberedCalibrationSession', template)
        self.assertIn('|| pollingCalibrationSessionId', template)
        self.assertIn('storedCalibrationSessions().length', template)
        self.assertIn('Reconnecting', template)
        self.assertIn("camera_id: $('#CAMERA_ID').val()", template)
        self.assertIn('Cancel calibration', template)
        self.assertIn(
            "$('#calibration-failure-reset').on('click', discardCalibrationResult);",
            template,
        )
        failed_status_body = template.split(
            "if (status.status === 'failed') {",
            1,
        )[1].split("if (status.status === 'cancelled') {", 1)[0]
        self.assertIn('showCalibrationFailure(', failed_status_body)
        self.assertNotIn('showCalibrationSetupView()', failed_status_body)

        docs = project_root.joinpath(
            'docs', 'asi676mc-frame-repair.md'
        ).read_text(encoding='utf-8')
        self.assertIn('camera-bound legacy', docs)
        self.assertIn('Reset / try', docs)

        video_source = project_root.joinpath(
            'indi_allsky', 'video.py'
        ).read_text(encoding='utf-8')
        self.assertIn(
            'asi676mc_calibration.cleanup_expired_sessions()',
            video_source,
        )
        self.assertIn(
            'asi676mc_calibration.task_failure_message(error)',
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
        forms_source = project_root.joinpath(
            'indi_allsky', 'flask', 'forms.py'
        ).read_text(encoding='utf-8')
        calibration_source = project_root.joinpath(
            'indi_allsky', 'asi676mc_calibration.py'
        ).read_text(encoding='utf-8')
        self.assertIn(
            "context['asi676mc_calibration_available']",
            base_view_source,
        )
        self.assertIn(
            'and asi676mc.feature_enabled(self.indi_allsky_config)',
            base_view_source,
        )
        self.assertIn('asi676mc_calibration_available', base_template)
        self.assertIn(
            'class AjaxAsi676mcCalibrationDatabaseView',
            views_source,
        )
        self.assertIn(
            'IndiAllSkyDbFitsImageTable.dayDate >= retention_cutoff',
            video_source,
        )
        self.assertIn(
            'def _loadAsi676mcCalibrationDatabase',
            video_source,
        )
        self.assertIn("'background_full_retention'", views_source)
        self.assertIn(
            "request_data.get('session_id')",
            views_source,
        )
        self.assertIn(
            'asi676mc_calibration.database_search_checkpoint(',
            views_source,
        )
        self.assertIn("context['calibration_upload_limits']", views_source)
        self.assertIn("context['calibration_database_limits']", views_source)
        self.assertIn("'DATABASE_GROUP_LIMIT': 20", views_source)
        self.assertIn("request_data.get('target_groups', 20)", views_source)
        group_field_source = forms_source.split(
            'DATABASE_GROUP_LIMIT = IntegerField(',
            1,
        )[1].split('\n\n', 1)[0]
        self.assertIn('default=20', group_field_source)
        self.assertIn(
            "source_details.get('requested_group_count', 20)",
            calibration_source,
        )
        self.assertEqual(asi676mc_calibration.MAX_FILE_COUNT, 80)
        self.assertEqual(asi676mc_calibration.DATABASE_MAX_FILES, 200)
        self.assertIn('def _can_save_standard_configuration()', views_source)
        self.assertIn('def _asi676mc_feature_enabled()', views_source)
        self.assertIn('if not _asi676mc_feature_enabled():', views_source)
        self.assertIn("app.config.get('LOGIN_DISABLED', False)", views_source)
        self.assertIn("'error_code': 'camera_changed'", views_source)
        self.assertIn('IndiAllSkyDbCameraTable.local == sa_true()', views_source)
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
        self.assertIn('Exclude Only keeps purple frames unchanged', message)
        self.assertIn('next matching normal frame', message)
        self.assertIn('standard FITS can remain off', message)
        self.assertIn('Diagnostic FITS are preferred', message)

    def test_capture_guidance_prefers_diagnostics_when_both_paths_are_enabled(
        self,
    ):
        periodic = asi676mc_calibration.capture_configuration_guidance({
            'IMAGE_ASI676MC_REPAIR': {
                'ENABLE': True,
                'EXCLUDE_ONLY': True,
                'SAVE_DIAGNOSTIC_FITS': True,
            },
            'IMAGE_SAVE_FITS': True,
            'IMAGE_SAVE_FITS_PERIOD': 1800,
            'IMAGE_FITS_EXPIRE_DAYS': 10,
        })
        periodic_message = periodic['guidance']['text']
        self.assertIn(
            'Diagnostic FITS are preferred',
            periodic_message,
        )
        self.assertIn(
            'only if you need them for another purpose',
            periodic_message,
        )
        self.assertIn(
            'temporarily set standard FITS saving to Every Image',
            periodic_message,
        )

        every_image = asi676mc_calibration.capture_configuration_guidance({
            'IMAGE_ASI676MC_REPAIR': {
                'ENABLE': True,
                'EXCLUDE_ONLY': False,
                'SAVE_DIAGNOSTIC_FITS': True,
            },
            'IMAGE_SAVE_FITS': True,
            'IMAGE_SAVE_FITS_PERIOD': 0,
            'IMAGE_FITS_EXPIRE_DAYS': 10,
        })
        every_image_message = every_image['guidance']['text']
        self.assertIn('original purple frame before repair', every_image_message)
        self.assertIn(
            'only if you also need standard FITS',
            every_image_message,
        )
        self.assertIn(
            'diagnostic saving misses purple frames',
            every_image_message,
        )
        self.assertIn('takes the most disk space', every_image_message)

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
            facts['Also Save Preceding RAW FITS'],
            'On (one-frame memory cache)',
        )
        message = guidance['guidance']['text']
        self.assertIn('keeps one normal frame in memory', message)
        self.assertIn('before/purple/after group', message)
        self.assertIn('one extra FITS frame of memory', message)
        self.assertIn('disk space', message)

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
        self.assertIn('Periodic standard FITS may miss purple frames', message)
        self.assertIn('Turn on diagnostic saving', message)
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
                                    facts['Also Save Preceding RAW FITS'],
                                    'On (one-frame memory cache)',
                                )
                                self.assertIn(
                                    'keeps one normal frame in memory',
                                    result['guidance']['text'],
                                )
                            elif preceding_fits and not repair_enabled:
                                self.assertFalse(result['preceding_fits'])
                                self.assertEqual(
                                    facts['Also Save Preceding RAW FITS'],
                                    'Inactive (handling off)',
                                )
                            elif preceding_fits:
                                self.assertFalse(result['preceding_fits'])
                                self.assertEqual(
                                    facts['Also Save Preceding RAW FITS'],
                                    'Inactive (Save Bad and Following RAW FITS off)',
                                )
                            else:
                                self.assertFalse(result['preceding_fits'])
                                self.assertEqual(
                                    facts['Also Save Preceding RAW FITS'],
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
        self.assertIn('Repair is active, but no FITS are being saved', message)
        self.assertIn('Turn on diagnostic saving', message)
        self.assertIn(
            'switch to Exclude Only and set',
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
            facts['Save Bad and Following RAW FITS'],
            'Inactive (handling off)',
        )
        self.assertIn(
            'configured diagnostic saving will then start',
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
            facts['Also Save Preceding RAW FITS'],
            'Inactive (Save Bad and Following RAW FITS off)',
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
            'Decompress selected files before manual upload',
            result['guidance']['text'],
        )
        self.assertIn('turn on handling in Exclude Only mode', result['guidance']['text'])

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
        settings_script = project_root.joinpath(
            'indi_allsky', 'flask', 'templates', 'config.html'
        ).read_text(encoding='utf-8')
        settings_template = project_root.joinpath(
            'indi_allsky', 'flask', 'templates', 'config', 'asi676mc.html'
        ).read_text(encoding='utf-8')

        self.assertIn(
            "{% include 'config/asi676mc.html' %}",
            project_root.joinpath(
                'indi_allsky', 'flask', 'templates', 'config', 'image.html'
            ).read_text(encoding='utf-8'),
        )

        self.assertIn('"EXCLUDE_ONLY"                : True', config_source)
        self.assertIn('"SAVE_PRECEDING_FITS"          : False', config_source)
        self.assertIn(
            '"RED_SIDE_RATIO_THRESHOLD"    : 1.15',
            config_source,
        )
        self.assertIn(
            '"BLUE_SIDE_RATIO_THRESHOLD"   : 1.75',
            config_source,
        )
        self.assertIn("get('EXCLUDE_ONLY', True)", processing_source)
        self.assertIn("get('EXCLUDE_ONLY', True)", views_source)
        self.assertIn(
            "asi676mc_repair_defaults['RED_SIDE_RATIO_THRESHOLD']",
            views_source,
        )
        self.assertIn(
            "asi676mc_repair_defaults['BLUE_SIDE_RATIO_THRESHOLD']",
            views_source,
        )
        self.assertIn('asi676mc_repair_was_enabled', settings_script)
        self.assertIn(
            'form_config.IMAGE_ASI676MC_REPAIR__SAVE_PRECEDING_FITS',
            settings_template,
        )
        self.assertIn(
            'update_asi676mc_preceding_fits_state',
            settings_script,
        )
        self.assertLess(
            settings_template.index(
                'form_config.IMAGE_ASI676MC_REPAIR__SAVE_DIAGNOSTIC_FITS'
            ),
            settings_template.index(
                'form_config.IMAGE_ASI676MC_REPAIR__SAVE_PRECEDING_FITS'
            ),
        )
        self.assertIn(
            'Purple-frame cameras only',
            settings_template,
        )
        self.assertIn(
            'Enable this only if the camera produces purple frames.',
            settings_template,
        )
        self.assertIn(
            'Leave standard FITS saving off unless you need those files',
            settings_template,
        )
        self.assertIn(
            'If this option misses purple frames',
            settings_template,
        )
        self.assertIn(
            "asi676mc_repair_defaults['RED_SIDE_RATIO_THRESHOLD']",
            settings_template,
        )
        self.assertIn(
            "asi676mc_repair_defaults['BLUE_SIDE_RATIO_THRESHOLD']",
            settings_template,
        )
        self.assertIn(
            "asi676mc_repair_defaults['SAMPLE_STEP']",
            settings_template,
        )
        self.assertIn(
            "asi676mc_repair_defaults['CHUNK_ROWS']",
            settings_template,
        )
        self.assertIn(
            'Brightness level used only when repairing clipped highlights.',
            settings_template,
        )
        self.assertNotIn('Safe calibration workflow:', settings_template)
        enable_guidance_position = settings_template.index(
            'Enable this only if the camera produces purple frames.'
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
                'form_config.IMAGE_ASI676MC_REPAIR__EXCLUDE_ONLY,'
            ),
        )
        self.assertGreater(
            settings_template.index('stronger before/purple/after groups'),
            settings_template.index(
                'form_config.IMAGE_ASI676MC_REPAIR__EXCLUDE_ONLY,'
            ),
        )
        sample_step_position = settings_template.index(
            'form_config.IMAGE_ASI676MC_REPAIR__SAMPLE_STEP'
        )
        highlight_start_position = settings_template.index(
            'form_config.IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_START_RATIO'
        )
        highlight_end_position = settings_template.index(
            'form_config.IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_END_RATIO'
        )
        chunk_rows_position = settings_template.index(
            'form_config.IMAGE_ASI676MC_REPAIR__CHUNK_ROWS'
        )
        highlight_section_position = settings_template.index(
            '>Clipping and highlight reconstruction<'
        )
        saturation_position = settings_template.index(
            'form_config.IMAGE_ASI676MC_REPAIR__SOURCE_SATURATION_THRESHOLD'
        )
        sampling_section_position = settings_template.index(
            '>Sampling and memory<'
        )
        self.assertLess(highlight_section_position, highlight_start_position)
        self.assertLess(highlight_section_position, saturation_position)
        self.assertLess(saturation_position, highlight_start_position)
        self.assertLess(highlight_start_position, highlight_end_position)
        self.assertLess(highlight_end_position, sampling_section_position)
        self.assertLess(sampling_section_position, sample_step_position)
        self.assertLess(sample_step_position, chunk_rows_position)

    def test_base_config_numerical_defaults_match_runtime_defaults(self):
        project_root = Path(__file__).resolve().parents[2]
        config_source = project_root.joinpath(
            'indi_allsky',
            'config.py',
        ).read_text(encoding='utf-8')
        config_tree = ast.parse(config_source)
        config_class = next(
            node for node in config_tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == 'IndiAllSkyConfigBase'
        )
        base_assignment = next(
            node for node in config_class.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == '_base_config'
                for target in node.targets
            )
        )
        base_config = ast.literal_eval(base_assignment.value.args[0])
        repair_config = base_config['IMAGE_ASI676MC_REPAIR']

        for key, value in calibration_engine.DEFAULT_SETTINGS.items():
            self.assertEqual(repair_config[key], value, key)

    def test_video_worker_cancellation_expires_task_without_dereference(self):
        video_path = (
            Path(__file__).resolve().parents[2]
            / 'indi_allsky'
            / 'video.py'
        )
        source = video_path.read_text(encoding='utf-8')
        tree = ast.parse(source, filename=str(video_path))
        worker = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == 'VideoWorker'
        )
        method = next(
            node for node in worker.body
            if isinstance(node, ast.FunctionDef)
            and node.name == '_runAsi676mcCalibration'
        )
        namespace = {
            'asi676mc_calibration': mock.Mock(
                run_calibration_session=mock.Mock(return_value=None),
            ),
            'logger': mock.Mock(),
        }
        exec(
            compile(
                ast.fix_missing_locations(
                    ast.Module(body=[method], type_ignores=[])
                ),
                str(video_path),
                'exec',
            ),
            namespace,
        )
        task = mock.Mock()
        processor = mock.Mock()

        namespace['_runAsi676mcCalibration'](
            processor,
            task,
            'cancelled-session',
        )

        task.setExpired.assert_called_once_with()
        task.setSuccess.assert_not_called()
        task.setFailed.assert_not_called()

    def test_video_task_only_enqueues_dedicated_calibration_work(self):
        project_root = Path(__file__).resolve().parents[2]
        video_source = project_root.joinpath(
            'indi_allsky', 'video.py'
        ).read_text(encoding='utf-8')
        self.assertIn('target=self._asi676mcCalibrationWorker', video_source)
        self.assertIn(
            'self._asi676mc_calibration_q.put((int(task.id), session_id))',
            video_source,
        )
        generate_body = video_source.split(
            'def generateAsi676mcCalibration',
            1,
        )[1].split('def _runAsi676mcCalibration', 1)[0]
        self.assertNotIn('run_calibration_session(', generate_body)

    def test_video_worker_backfills_legacy_signatures_in_batches(self):
        video_path = (
            Path(__file__).resolve().parents[2]
            / 'indi_allsky'
            / 'video.py'
        )
        source = video_path.read_text(encoding='utf-8')
        tree = ast.parse(source, filename=str(video_path))
        worker = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == 'VideoWorker'
        )
        method = next(
            node for node in worker.body
            if isinstance(node, ast.FunctionDef)
            and node.name == '_saveAsi676mcCalibrationSignatures'
        )
        entries = [
            mock.Mock(id=record_id, data={'preserved': True})
            for record_id in range(1, 502)
        ]
        query = mock.Mock()
        query.filter.return_value = query
        query.all.side_effect = (
            entries[:250],
            entries[250:500],
            entries[500:],
        )
        fits_model = mock.Mock()
        fits_model.query = query
        database = mock.Mock()
        namespace = {
            'IndiAllSkyDbFitsImageTable': fits_model,
            'asi676mc': mock.Mock(
                SIGNATURE_METADATA_KEY='asi676mc_signature'
            ),
            'db': database,
        }
        exec(
            compile(
                ast.fix_missing_locations(
                    ast.Module(body=[method], type_ignores=[])
                ),
                str(video_path),
                'exec',
            ),
            namespace,
        )
        updates = {
            record_id: {
                'purple_ratio': float(record_id),
                'red_side_ratio': 1.0,
                'blue_side_ratio': 1.0,
            }
            for record_id in range(1, 502)
        }

        namespace['_saveAsi676mcCalibrationSignatures'](
            mock.Mock(),
            {'camera_id': 7},
            updates,
        )

        self.assertEqual(database.session.commit.call_count, 3)
        self.assertTrue(entries[0].data['preserved'])
        self.assertEqual(
            entries[-1].data['asi676mc_signature']['purple_ratio'],
            501.0,
        )


if __name__ == '__main__':
    unittest.main()
