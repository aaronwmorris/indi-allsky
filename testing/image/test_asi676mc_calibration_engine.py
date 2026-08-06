import tempfile
from pathlib import Path
import unittest
from unittest import mock

import numpy
from astropy.io import fits

from indi_allsky import asi676mc
from indi_allsky import asi676mc_calibration_engine as calibration_engine


class TestAsi676mcCalibrationEngine(unittest.TestCase):

    @staticmethod
    def _threshold_record(name, timestamp, exposure, ratios):
        """Build a lightweight record for detector-threshold unit tests."""
        return calibration_engine.FrameRecord(
            path=Path(name),
            timestamp=float(timestamp),
            exposure=exposure,
            gain=0.0,
            xbin=1,
            ybin=1,
            shape=(64, 64),
            bayer='RGGB',
            camera_name='ZWO CCD ASI676MC',
            signature={
                'is_bad': False,
                'purple_ratio': ratios[0],
                'red_side_ratio': ratios[1],
                'blue_side_ratio': ratios[2],
            },
        )

    def _threshold_population_records(self, purple_blue_ratio=1.4):
        records = []
        for index in range(7):
            exposure = 0.001 if index < 4 else 0.002
            base_time = 1000 + (index * 300)
            records.extend((
                self._threshold_record(
                    'normal_before_{0}.fit'.format(index),
                    base_time,
                    exposure,
                    (0.90, 0.70, 1.10),
                ),
                self._threshold_record(
                    'likely_purple_{0}.fit'.format(index),
                    base_time + 20,
                    exposure,
                    (2.20, 1.70, purple_blue_ratio),
                ),
                self._threshold_record(
                    'normal_after_{0}.fit'.format(index),
                    base_time + 40,
                    exposure,
                    (0.92, 0.72, 1.12),
                ),
            ))
        return records

    def test_engine_uses_runtime_defaults(self):
        """Calibration and live repair must share one settings definition."""
        self.assertIs(
            calibration_engine.DEFAULT_SETTINGS,
            asi676mc.DEFAULT_SETTINGS,
        )
        self.assertEqual(
            calibration_engine.DEFAULT_SETTINGS['RED_SIDE_RATIO_THRESHOLD'],
            1.15,
        )
        self.assertEqual(
            calibration_engine.DEFAULT_SETTINGS['BLUE_SIDE_RATIO_THRESHOLD'],
            1.75,
        )

    def test_pairing_prefers_before_and_after(self):
        def record(name, timestamp, is_bad):
            return calibration_engine.FrameRecord(
                path=Path(name),
                timestamp=timestamp,
                exposure=0.001,
                gain=0.0,
                xbin=1,
                ybin=1,
                shape=(64, 64),
                bayer='RGGB',
                camera_name='ZWO CCD ASI676MC',
                signature={
                    'is_bad': is_bad,
                    'purple_ratio': 2.0 if is_bad else 0.9,
                    'red_side_ratio': 1.6 if is_bad else 0.7,
                    'blue_side_ratio': 2.5 if is_bad else 1.1,
                },
            )

        records = [
            record('before.fit', 80.0, False),
            record('bad.fit', 100.0, True),
            record('after.fit', 120.0, False),
            record('far.fit', 500.0, False),
        ]
        pairs, unmatched = calibration_engine.match_pairs(records, 90.0)

        self.assertFalse(unmatched)
        self.assertEqual(len(pairs), 1)
        self.assertTrue(pairs[0].two_sided)
        self.assertEqual(
            [item.path.name for item in pairs[0].references],
            ['before.fit', 'after.fit'],
        )

    def test_pairing_never_uses_same_timestamp_as_its_own_reference(self):
        def record(name, is_bad):
            return calibration_engine.FrameRecord(
                path=Path(name),
                timestamp=100.0,
                exposure=0.001,
                gain=0.0,
                xbin=1,
                ybin=1,
                shape=(64, 64),
                bayer='RGGB',
                camera_name='ZWO CCD ASI676MC',
                signature={'is_bad': is_bad},
            )

        pairs, unmatched = calibration_engine.match_pairs(
            [record('bad.fit', True), record('same_capture.fit', False)],
            max_pair_seconds=90.0,
        )
        self.assertFalse(pairs)
        self.assertEqual(len(unmatched), 1)

    def test_signature_threshold_validation_explains_safe_gap(self):
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
                'bad_min': 2.622,
                'bad_max': 3.136,
            },
        }
        calibration_engine.validate_signature_separation(
            ranges,
            calibration_engine.DEFAULT_SETTINGS,
        )

        normal_crosses_blue = {
            metric: dict(values)
            for metric, values in ranges.items()
        }
        normal_crosses_blue['blue_side_ratio']['good_max'] = 1.800
        with self.assertRaisesRegex(
            calibration_engine.CalibrationError,
            'Configured Blue-side ratio threshold is 1.750.*midpoint 2.211',
        ):
            calibration_engine.validate_signature_separation(
                normal_crosses_blue,
                calibration_engine.DEFAULT_SETTINGS,
            )

        purple_misses_red = {
            metric: dict(values)
            for metric, values in ranges.items()
        }
        purple_misses_red['red_side_ratio']['bad_min'] = 1.093
        with self.assertRaisesRegex(
            calibration_engine.CalibrationError,
            'Configured Red-side ratio threshold is 1.150.*midpoint 0.900',
        ):
            calibration_engine.validate_signature_separation(
                purple_misses_red,
                calibration_engine.DEFAULT_SETTINGS,
            )

    def test_threshold_margin_assessment_flags_only_narrow_gaps(self):
        ranges = {
            'purple_ratio': {
                'good_min': 0.85, 'good_max': 0.91,
                'bad_min': 2.19, 'bad_max': 2.27,
            },
            'red_side_ratio': {
                'good_min': 0.58, 'good_max': 0.71,
                'bad_min': 1.52, 'bad_max': 1.84,
            },
            'blue_side_ratio': {
                'good_min': 1.00, 'good_max': 1.71,
                'bad_min': 2.00, 'bad_max': 2.60,
            },
        }

        assessments = calibration_engine.assess_detection_threshold_margins(
            ranges,
            calibration_engine.DEFAULT_SETTINGS,
        )
        by_key = {item['key']: item for item in assessments}

        self.assertFalse(by_key['PURPLE_RATIO_THRESHOLD']['marginal'])
        self.assertFalse(by_key['RED_SIDE_RATIO_THRESHOLD']['marginal'])
        self.assertTrue(by_key['BLUE_SIDE_RATIO_THRESHOLD']['marginal'])
        self.assertEqual(
            by_key['BLUE_SIDE_RATIO_THRESHOLD']['suggested'],
            1.855,
        )

    def test_saved_signature_metadata_avoids_fits_decode(self):
        metadata = {
            'signature': {
                'purple_ratio': 2.2,
                'red_side_ratio': 1.7,
                'blue_side_ratio': 2.8,
            },
            'timestamp': 1000.0,
            'exposure': 0.001,
            'gain': 100.0,
            'binmode': 1,
            'width': 3552,
            'height': 3552,
            'camera_name': 'ZWO CCD ASI676MC',
        }

        record = calibration_engine.inspect_fits_metadata(
            Path('metadata_only.fit'),
            metadata,
            calibration_engine.DEFAULT_SETTINGS,
        )

        self.assertTrue(record.is_bad)
        self.assertEqual(record.shape, (3552, 3552))
        self.assertEqual(record.timestamp, 1000.0)

    def test_progressive_scan_stops_after_actionable_outliers(self):
        source_records = self._threshold_population_records()
        progress = []
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            metadata_by_name = {}
            for index, source in enumerate(source_records):
                name = '{0:03d}.fit'.format(index)
                folder.joinpath(name).touch()
                metadata_by_name[name] = {
                    'signature': {
                        metric: source.signature[metric]
                        for metric in calibration_engine.DETECTION_THRESHOLD_DETAILS
                    },
                    'timestamp': source.timestamp,
                    'exposure': source.exposure,
                    'gain': source.gain,
                    'binmode': 1,
                    'width': 64,
                    'height': 64,
                    'camera_name': source.camera_name,
                }

            records, rejected = calibration_engine.scan_folder(
                folder,
                calibration_engine.DEFAULT_SETTINGS,
                recursive=False,
                metadata_by_name=metadata_by_name,
                progress_callback=progress.append,
                progressive_check=lambda current: (
                    calibration_engine.dataset_has_actionable_result(
                        current,
                        calibration_engine.DEFAULT_SETTINGS,
                        90.0,
                    )
                ),
                initial_scan_count=14,
            )

        self.assertFalse(rejected)
        self.assertEqual(len(records), 20)
        self.assertEqual(progress[-1]['phase'], 'evidence_ready')
        self.assertEqual(progress[-1]['detected_bad_count'], 0)

    def test_detector_miss_returns_threshold_suggestions_without_fitting(self):
        records = self._threshold_population_records()
        with mock.patch.object(
            calibration_engine,
            'scan_folder',
            return_value=(records, []),
        ):
            payload = calibration_engine.calibrate_folder(Path('unused'))

        self.assertEqual(payload['outcome'], 'threshold_suggestion')
        self.assertNotIn('derived_settings', payload)
        self.assertEqual(payload['quality']['likely_purple_count'], 7)
        self.assertEqual(payload['quality']['likely_normal_count'], 14)
        self.assertEqual(len(payload['population_evidence']), 21)
        self.assertEqual(
            {item['population'] for item in payload['population_evidence']},
            {'higher ratio', 'lower ratio'},
        )
        self.assertTrue(all(
            item['timestamp_utc'].endswith('+00:00')
            for item in payload['population_evidence']
        ))
        suggestions = {
            item['key']: item
            for item in payload['threshold_suggestions']
        }
        self.assertFalse(
            suggestions['PURPLE_RATIO_THRESHOLD']['change_recommended']
        )
        self.assertFalse(
            suggestions['RED_SIDE_RATIO_THRESHOLD']['change_recommended']
        )
        self.assertTrue(
            suggestions['BLUE_SIDE_RATIO_THRESHOLD']['change_recommended']
        )
        self.assertEqual(
            suggestions['BLUE_SIDE_RATIO_THRESHOLD']['suggested'],
            1.26,
        )

    def test_all_rejected_failure_preserves_grouped_reasons_without_paths(self):
        rejected = [
            (Path('private_one.fit'), 'missing explicit BAYERPAT=RGGB metadata'),
            (Path('private_two.fit'), 'missing explicit BAYERPAT=RGGB metadata'),
            (
                Path('private_three.fit'),
                'calibration requires XBINNING=1 and YBINNING=1',
            ),
        ]
        with mock.patch.object(
            calibration_engine,
            'scan_folder',
            return_value=([], rejected),
        ):
            with self.assertRaises(calibration_engine.CalibrationError) as raised:
                calibration_engine.calibrate_folder(Path('private_folder'))

        message = str(raised.exception)
        self.assertIn('rejection summary:', message)
        self.assertIn('missing explicit BAYERPAT=RGGB metadata\":2', message)
        self.assertIn('XBINNING=1 and YBINNING=1\":1', message)
        self.assertNotIn('private_one.fit', message)
        self.assertNotIn('private_folder', message)

    def test_single_ratio_threshold_mismatch_uses_same_preliminary_result(self):
        records = self._threshold_population_records(purple_blue_ratio=2.5)
        for record in records:
            if record.path.name.startswith('likely_purple_'):
                record.signature['is_bad'] = True
            elif record.path.name.startswith('normal_before_'):
                record.signature['blue_side_ratio'] = 1.85
            else:
                record.signature['blue_side_ratio'] = 1.87

        with mock.patch.object(
            calibration_engine,
            'scan_folder',
            return_value=(records, []),
        ):
            payload = calibration_engine.calibrate_folder(Path('unused'))

        self.assertEqual(payload['outcome'], 'threshold_suggestion')
        suggestions = {
            item['key']: item
            for item in payload['threshold_suggestions']
        }
        self.assertTrue(
            suggestions['BLUE_SIDE_RATIO_THRESHOLD']['change_recommended']
        )
        self.assertEqual(
            suggestions['BLUE_SIDE_RATIO_THRESHOLD']['suggested'],
            2.185,
        )
        self.assertNotIn('derived_settings', payload)

    def test_threshold_analysis_rejects_inconsistently_ordered_populations(self):
        records = self._threshold_population_records(purple_blue_ratio=1.0)
        with self.assertRaisesRegex(
            calibration_engine.CalibrationError,
            'not higher in all three',
        ):
            calibration_engine.suggest_detection_thresholds(
                records,
                calibration_engine.DEFAULT_SETTINGS,
                max_pair_seconds=90.0,
            )

    def test_single_population_all_normal_or_all_bad_fails_safely(self):
        for is_bad in (False, True):
            records = [
                self._threshold_record(
                    'frame_{0}.fit'.format(index),
                    float(index),
                    0.001 if index < 10 else 0.002,
                    (0.9, 0.7, 1.1),
                )
                for index in range(20)
            ]
            for record in records:
                record.signature['is_bad'] = is_bad
            with self.subTest(is_bad=is_bad):
                with self.assertRaises(calibration_engine.CalibrationError):
                    calibration_engine.suggest_detection_thresholds(
                        records,
                        calibration_engine.DEFAULT_SETTINGS,
                        max_pair_seconds=90.0,
                    )

    def test_gain_fit_rejects_unstable_or_implausible_populations(self):
        reference = numpy.full((32, 32), 2000.0)
        stable = numpy.ones(reference.shape, dtype=numpy.bool_)

        def samples_for(ratios):
            return [
                calibration_engine.PairSamples(
                    pair=None,
                    bad_planes=tuple(
                        numpy.rint(reference * ratio).astype(numpy.uint16)
                        for _parity in range(4)
                    ),
                    reference_planes=tuple(
                        reference.copy() for _parity in range(4)
                    ),
                    stable_masks=tuple(
                        stable.copy() for _parity in range(4)
                    ),
                )
                for ratio in ratios
            ]

        with self.assertRaisesRegex(
            calibration_engine.CalibrationError,
            'varies too much',
        ):
            calibration_engine.estimate_gains(
                samples_for((0.5, 3.0, 0.5, 3.0, 0.5, 3.0, 1.75))
            )
        with self.assertRaisesRegex(
            calibration_engine.CalibrationError,
            'outside the plausible',
        ):
            calibration_engine.estimate_gains(samples_for((5.0,) * 7))

    def test_folder_scan_accepts_indi_allsky_compressed_fits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            header = fits.Header()
            header['DATE-OBS'] = '2026-07-01T00:00:00'
            header['EXPTIME'] = 0.001
            header['GAIN'] = 0.0
            header['BAYERPAT'] = 'RGGB'
            header['XBINNING'] = 1
            header['YBINNING'] = 1
            header['XBAYROFF'] = 0
            header['YBAYROFF'] = 0
            header['INSTRUME'] = 'ZWO CCD ASI676MC'
            fits.PrimaryHDU(
                data=self._normal_frame(64, 64),
                header=header,
            ).writeto(folder / 'saved_by_indi_allsky.fit.gz')

            records, rejected = calibration_engine.scan_folder(
                folder,
                calibration_engine.DEFAULT_SETTINGS,
                recursive=False,
            )

        self.assertFalse(rejected)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].path.name, 'saved_by_indi_allsky.fit.gz')

    def test_fits_inspection_merges_primary_and_image_extension_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir).joinpath('extension.fit')
            primary_header = fits.Header()
            primary_header['DATE-OBS'] = '2026-07-01T00:00:00'
            primary_header['EXPTIME'] = 0.001
            primary_header['GAIN'] = 0.0
            primary_header['BAYERPAT'] = 'RGGB'
            primary_header['XBINNING'] = 1
            primary_header['YBINNING'] = 1
            primary_header['XBAYROFF'] = 0
            primary_header['YBAYROFF'] = 0
            primary_header['CAMERA'] = 'indi-allsky'
            primary_header['INSTRUME'] = 'ZWO CCD ASI676MC'
            fits.HDUList([
                fits.PrimaryHDU(header=primary_header),
                fits.ImageHDU(data=self._normal_frame(64, 64)),
            ]).writeto(path)

            record = calibration_engine.inspect_fits(
                path,
                calibration_engine.DEFAULT_SETTINGS,
            )

        self.assertEqual(record.camera_name, 'ZWO CCD ASI676MC')
        self.assertEqual(record.xbin, 1)
        self.assertEqual(record.bayer, 'RGGB')

    def test_camera_bound_upload_accepts_only_generic_legacy_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)

            def write_fits(name, instrume=None):
                header = fits.Header()
                header['DATE-OBS'] = '2026-07-01T00:00:00'
                header['EXPTIME'] = 0.001
                header['GAIN'] = 0.0
                header['BAYERPAT'] = 'RGGB'
                header['XBINNING'] = 1
                header['YBINNING'] = 1
                header['XBAYROFF'] = 0
                header['YBAYROFF'] = 0
                if instrume is not None:
                    header['INSTRUME'] = instrume
                path = folder / name
                fits.PrimaryHDU(
                    data=self._normal_frame(64, 64),
                    header=header,
                ).writeto(path)
                return path

            generic_path = write_fits('generic.fit', 'indi-allsky')
            missing_path = write_fits('missing.fit')
            conflicting_path = write_fits('conflicting.fit', 'QHY268C')
            other_asi_path = write_fits(
                'other_asi.fit',
                'ZWO CCD ASI678MC',
            )

            with self.assertRaisesRegex(ValueError, 'explicitly identify'):
                calibration_engine.inspect_fits(
                    generic_path,
                    calibration_engine.DEFAULT_SETTINGS,
                )

            for path in (generic_path, missing_path):
                record = calibration_engine.inspect_fits(
                    path,
                    calibration_engine.DEFAULT_SETTINGS,
                    trusted_camera_name='ZWO CCD ASI676MC',
                )
                self.assertEqual(record.camera_name, 'ZWO CCD ASI676MC')
                self.assertEqual(record.camera_identity_source, 'bound_session')

            with self.assertRaisesRegex(ValueError, 'explicitly identify'):
                calibration_engine.inspect_fits(
                    conflicting_path,
                    calibration_engine.DEFAULT_SETTINGS,
                    trusted_camera_name='ZWO CCD ASI676MC',
                )
            with self.assertRaisesRegex(ValueError, 'ASI camera identity'):
                calibration_engine.inspect_fits(
                    other_asi_path,
                    calibration_engine.DEFAULT_SETTINGS,
                    trusted_camera_name='ZWO CCD ASI676MC',
                )

    def test_fits_inspection_rejects_runtime_incompatible_metadata(self):
        cases = (
            ({'BAYERPAT': None}, 'BAYERPAT'),
            ({'BAYERPAT': 'BGGR'}, 'expected RGGB'),
            ({'XBINNING': 2}, 'XBINNING=1'),
            ({'XBAYROFF': 1}, 'zero Bayer offsets'),
            ({'EXPTIME': 'Infinity'}, 'exposure'),
            ({'GAIN': 'NaN'}, 'gain'),
            ({'ASI676FX': True}, 'already repaired'),
            ({'INSTRUME': 'ZWO CCD ASI678MC'}, 'ASI camera identity'),
            ({'CAMERA': 'ZWO CCD ASI678MC'}, 'ASI camera identity'),
        )
        for changes, message in cases:
            with self.subTest(changes=changes):
                with tempfile.TemporaryDirectory() as temp_dir:
                    path = Path(temp_dir).joinpath('bad_metadata.fit')
                    header = fits.Header()
                    header['DATE-OBS'] = '2026-07-01T00:00:00'
                    header['EXPTIME'] = 0.001
                    header['GAIN'] = 0.0
                    header['BAYERPAT'] = 'RGGB'
                    header['XBINNING'] = 1
                    header['YBINNING'] = 1
                    header['XBAYROFF'] = 0
                    header['YBAYROFF'] = 0
                    # Exercise every compatibility rejection through the same
                    # camera-bound legacy path used by standard FITS uploads.
                    # The trusted name must relax only camera provenance.
                    header['INSTRUME'] = 'indi-allsky'
                    for key, value in changes.items():
                        if value is None:
                            del header[key]
                        else:
                            header[key] = value
                    fits.PrimaryHDU(
                        data=self._normal_frame(64, 64),
                        header=header,
                    ).writeto(path)
                    with self.assertRaisesRegex(ValueError, message):
                        calibration_engine.inspect_fits(
                            path,
                            calibration_engine.DEFAULT_SETTINGS,
                            trusted_camera_name='ZWO CCD ASI676MC',
                        )

    @staticmethod
    def _normal_frame(height=128, width=128):
        y, x = numpy.indices((height, width))
        data = (9000 + y * 35 + x * 20).astype(numpy.uint16)
        highlight = (y >= 48) & (y < 80) & (x >= 48) & (x < 80)
        data[highlight & ((y % 2) == 0) & ((x % 2) == 0)] = 50000
        data[highlight & ((y % 2) == 0) & ((x % 2) == 1)] = 60000
        data[highlight & ((y % 2) == 1) & ((x % 2) == 0)] = 60000
        data[highlight & ((y % 2) == 1) & ((x % 2) == 1)] = 45000
        return data

    @staticmethod
    def _bad_stream(normal):
        height, width = normal.shape
        bad = numpy.zeros_like(normal)
        gains = (
            calibration_engine.DEFAULT_SETTINGS['GAIN_R'],
            calibration_engine.DEFAULT_SETTINGS['GAIN_G1'],
            calibration_engine.DEFAULT_SETTINGS['GAIN_G2'],
            calibration_engine.DEFAULT_SETTINGS['GAIN_B'],
        )
        for row_parity in range(2):
            for column_parity in range(2):
                source = normal[
                    row_parity:height - 1:2,
                    column_parity::2,
                ].astype(numpy.float64)
                encoded = numpy.rint(
                    numpy.clip(
                        source * gains[row_parity * 2 + column_parity],
                        0,
                        65534,
                    )
                ).astype(numpy.uint16)
                bad[
                    1 + row_parity:height:2,
                    column_parity::2,
                ] = encoded
        bad[0] = bad[2]
        return bad

    def test_folder_calibration_accepts_seven_two_sided_pairs(self):
        normal = self._normal_frame()
        bad = self._bad_stream(normal)
        self.assertFalse(asi676mc.frame_signature(normal)['is_bad'])
        self.assertTrue(asi676mc.frame_signature(bad)['is_bad'])

        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            for index in range(7):
                exposure = 0.001 if index < 4 else 0.002
                base_second = index * 300
                for role, second, data in (
                    ('before', base_second, normal),
                    ('bad', base_second + 20, bad),
                    ('after', base_second + 40, normal),
                ):
                    timestamp = (
                        f'2026-07-01T00:'
                        f'{second // 60:02d}:{second % 60:02d}'
                    )
                    header = fits.Header()
                    header['DATE-OBS'] = timestamp
                    header['EXPTIME'] = exposure
                    header['GAIN'] = 0.0
                    header['XBINNING'] = 1
                    header['YBINNING'] = 1
                    header['BAYERPAT'] = 'RGGB'
                    # Reproduce indi-allsky's standard FITS default. The
                    # camera-bound manual upload supplies the missing model
                    # identity without altering these legacy files.
                    header['INSTRUME'] = 'indi-allsky'
                    fits.PrimaryHDU(data=data, header=header).writeto(
                        folder / f'{index:02d}_{role}.fit'
                    )

            overrides = {
                'MIN_GAIN_SAMPLES_PER_PARITY': 10,
                'MIN_HIGHLIGHT_SAMPLES_TOTAL': 10,
                'MIN_HIGHLIGHT_SAMPLES_PER_PAIR': 1,
                'BLEND_START_VALUES': (0.50, 0.55, 0.60),
                'BLEND_END_VALUES': (0.70, 0.75, 0.80),
            }
            with mock.patch.dict(
                calibration_engine.CALIBRATION_OPTIONS,
                overrides,
            ):
                payload = calibration_engine.calibrate_folder(
                    folder,
                    trusted_camera_name='ZWO CCD ASI676MC',
                )

        quality = payload['quality']
        settings = payload['derived_settings']
        self.assertEqual(quality['pair_count'], 7)
        self.assertEqual(quality['two_sided_count'], 7)
        self.assertEqual(quality['good_bad_ratio'], 2.0)
        self.assertEqual(quality['bound_session_camera_count'], 21)
        self.assertEqual(quality['explicit_camera_names'], [])
        self.assertEqual(payload['rejected_files'], [])
        self.assertEqual(len(payload['threshold_assessment']), 3)
        threshold_assessment = {
            item['key']: item
            for item in payload['threshold_assessment']
        }
        self.assertFalse(
            threshold_assessment['PURPLE_RATIO_THRESHOLD']['marginal']
        )
        self.assertFalse(
            threshold_assessment['RED_SIDE_RATIO_THRESHOLD']['marginal']
        )
        self.assertTrue(
            threshold_assessment['BLUE_SIDE_RATIO_THRESHOLD']['marginal']
        )
        for key in ('GAIN_R', 'GAIN_G1', 'GAIN_G2', 'GAIN_B'):
            self.assertAlmostEqual(
                settings[key],
                calibration_engine.DEFAULT_SETTINGS[key],
                delta=0.02,
            )

    def test_two_normal_colour_regimes_do_not_pass_as_phase_shift_failure(self):
        normal = self._normal_frame()
        higher_ratio = normal.copy()
        gains = (2.0, 0.7, 0.7, 2.0)
        for row_parity in range(2):
            for column_parity in range(2):
                plane = higher_ratio[row_parity::2, column_parity::2]
                plane[:] = numpy.rint(numpy.clip(
                    plane.astype(numpy.float64)
                    * gains[row_parity * 2 + column_parity],
                    0,
                    65534,
                )).astype(numpy.uint16)
        self.assertTrue(asi676mc.frame_signature(higher_ratio)['is_bad'])

        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            for index in range(7):
                exposure = 0.001 if index < 4 else 0.002
                base_second = index * 300
                for role, second, data in (
                    ('before', base_second, normal),
                    ('bad', base_second + 20, higher_ratio),
                    ('after', base_second + 40, normal),
                ):
                    header = fits.Header()
                    header['DATE-OBS'] = (
                        '2026-07-01T00:{0:02d}:{1:02d}'.format(
                            second // 60,
                            second % 60,
                        )
                    )
                    header['EXPTIME'] = exposure
                    header['GAIN'] = 0.0
                    header['XBINNING'] = 1
                    header['YBINNING'] = 1
                    header['BAYERPAT'] = 'RGGB'
                    header['INSTRUME'] = 'ZWO CCD ASI676MC'
                    fits.PrimaryHDU(data=data, header=header).writeto(
                        folder / '{0:02d}_{1}.fit'.format(index, role)
                    )

            overrides = {
                'MIN_GAIN_SAMPLES_PER_PARITY': 10,
                'MIN_HIGHLIGHT_SAMPLES_TOTAL': 10,
                'MIN_HIGHLIGHT_SAMPLES_PER_PAIR': 1,
            }
            with mock.patch.dict(
                calibration_engine.CALIBRATION_OPTIONS,
                overrides,
            ):
                with self.assertRaisesRegex(
                    calibration_engine.CalibrationError,
                    'one-row phase shift',
                ):
                    calibration_engine.calibrate_folder(folder)


if __name__ == '__main__':
    unittest.main()
