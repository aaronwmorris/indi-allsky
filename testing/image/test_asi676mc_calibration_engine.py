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
        normal_crosses_blue['blue_side_ratio']['good_max'] = 1.600
        with self.assertRaisesRegex(
            calibration_engine.CalibrationError,
            'Configured Blue-side ratio threshold is 1.500.*midpoint 2.111',
        ):
            calibration_engine.validate_signature_separation(
                normal_crosses_blue,
                calibration_engine.DEFAULT_SETTINGS,
            )

        purple_misses_red = {
            metric: dict(values)
            for metric, values in ranges.items()
        }
        purple_misses_red['red_side_ratio']['bad_min'] = 1.200
        with self.assertRaisesRegex(
            calibration_engine.CalibrationError,
            'Configured Red-side ratio threshold is 1.250.*midpoint 0.954',
        ):
            calibration_engine.validate_signature_separation(
                purple_misses_red,
                calibration_engine.DEFAULT_SETTINGS,
            )

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

    def test_single_ratio_threshold_mismatch_uses_same_preliminary_result(self):
        records = self._threshold_population_records(purple_blue_ratio=2.5)
        for record in records:
            if record.path.name.startswith('likely_purple_'):
                record.signature['is_bad'] = True
            elif record.path.name.startswith('normal_before_'):
                record.signature['blue_side_ratio'] = 1.60
            else:
                record.signature['blue_side_ratio'] = 1.62

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
            2.06,
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

    def test_folder_scan_accepts_indi_allsky_compressed_fits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            header = fits.Header()
            header['DATE-OBS'] = '2026-07-01T00:00:00'
            header['EXPTIME'] = 0.001
            header['GAIN'] = 0.0
            header['BAYERPAT'] = 'RGGB'
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
                    header['INSTRUME'] = 'ZWO CCD ASI676MC'
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
                payload = calibration_engine.calibrate_folder(folder)

        quality = payload['quality']
        settings = payload['derived_settings']
        self.assertEqual(quality['pair_count'], 7)
        self.assertEqual(quality['two_sided_count'], 7)
        self.assertEqual(quality['good_bad_ratio'], 2.0)
        self.assertEqual(payload['rejected_files'], [])
        for key in ('GAIN_R', 'GAIN_G1', 'GAIN_G2', 'GAIN_B'):
            self.assertAlmostEqual(
                settings[key],
                calibration_engine.DEFAULT_SETTINGS[key],
                delta=0.02,
            )


if __name__ == '__main__':
    unittest.main()
