import io
import ast
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from indi_allsky import asi676mc_calibration
from misc import asi676mc_frame_repair as standalone


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
        settings = dict(standalone.DEFAULT_SETTINGS)
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
                settings=standalone.DEFAULT_SETTINGS,
                storage_root=root,
            )

            payload = self._successful_payload()
            with mock.patch.object(
                standalone,
                'calibrate_folder',
                return_value=(payload, 'human-readable report\n'),
            ) as calibrate_folder:
                result = asi676mc_calibration.run_calibration_session(
                    session_id,
                    root,
                )

            call_kwargs = calibrate_folder.call_args.kwargs
            self.assertTrue(call_kwargs['allow_unmatched'])
            self.assertFalse(call_kwargs['recursive'])
            self.assertEqual(
                call_kwargs['report_title'],
                'ASI676MC web calibration report',
            )
            self.assertEqual(result['quality']['matched_bad_count'], 7)
            self.assertEqual(len(result['values']), 7)
            self.assertFalse(root.joinpath(session_id, 'uploads').exists())

            status = asi676mc_calibration.get_status(
                session_id,
                'alice',
                root,
            )
            self.assertEqual(status['status'], 'success')
            self.assertTrue(status['report_available'])
            self.assertEqual(status['result']['quality']['unmatched_bad_count'], 1)
            self.assertEqual(
                asi676mc_calibration.get_report_path(
                    session_id,
                    'alice',
                    root,
                ).read_text(encoding='utf-8'),
                'human-readable report\n',
            )

    def test_standalone_strict_policy_remains_default(self):
        """The web relaxation must not silently change the standalone CLI."""
        normal_records = []
        pairs = []
        for index in range(7):
            exposure = 0.001 if index < 4 else 0.002
            normal = standalone.FrameRecord(
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
            bad = standalone.FrameRecord(
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
            pairs.append(standalone.MatchedPair(bad=bad, references=(normal,)))

        unmatched = [pairs[0].bad]
        records = normal_records + [pair.bad for pair in pairs] + unmatched
        with self.assertRaises(standalone.CalibrationError):
            standalone.validate_evidence(records, pairs, unmatched)

        evidence = standalone.validate_evidence(
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
            'AjaxAsi676mcCalibrationStartView',
            'AjaxAsi676mcCalibrationStatusView',
            'Asi676mcCalibrationReportView',
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


if __name__ == '__main__':
    unittest.main()
