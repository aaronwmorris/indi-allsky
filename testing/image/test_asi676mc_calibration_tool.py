import tempfile
from pathlib import Path
import unittest
from unittest import mock

import numpy
from astropy.io import fits

from indi_allsky import asi676mc
from misc import asi676mc_frame_repair as calibration_engine


class TestAsi676mcCalibrationTool(unittest.TestCase):

    def test_runtime_defaults_and_repair_are_equivalent(self):
        self.assertEqual(
            calibration_engine.DEFAULT_SETTINGS,
            asi676mc.DEFAULT_SETTINGS,
        )

        rng = numpy.random.default_rng(676)
        source = rng.integers(
            0,
            65535,
            size=(64, 80),
            dtype=numpy.uint16,
        )
        source[10:30:2, 11:31:2] = 65534
        source[11:31:2, 10:30:2] = 65534

        runtime_data = source.copy()
        tool_data = source.copy()
        asi676mc.repair_in_place(runtime_data)
        calibration_engine.repair_in_place(tool_data)
        numpy.testing.assert_array_equal(runtime_data, tool_data)

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
        self.assertFalse(calibration_engine.frame_signature(normal)['is_bad'])
        self.assertTrue(calibration_engine.frame_signature(bad)['is_bad'])

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
                payload, report = calibration_engine.calibrate_folder(folder)

        quality = payload['quality']
        settings = payload['IMAGE_ASI676MC_REPAIR']
        self.assertEqual(quality['pair_count'], 7)
        self.assertEqual(quality['two_sided_count'], 7)
        self.assertEqual(quality['good_bad_ratio'], 2.0)
        self.assertIn('ASI676MC calibration report', report)
        self.assertIn('TYPE THESE VALUES INTO YOUR CONFIG', report)
        self.assertIn('Purple Ratio Threshold: 1.5', report)
        self.assertIn('Bad-frame Gain R:', report)
        self.assertNotIn('IMAGE_ASI676MC_REPAIR values', report)
        for key in ('GAIN_R', 'GAIN_G1', 'GAIN_G2', 'GAIN_B'):
            self.assertAlmostEqual(
                settings[key],
                calibration_engine.DEFAULT_SETTINGS[key],
                delta=0.02,
            )


if __name__ == '__main__':
    unittest.main()
