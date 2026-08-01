import ast
import json
from pathlib import Path
import unittest
from unittest import mock
from types import SimpleNamespace

import numpy

from indi_allsky import asi676mc


class TestAsi676mcFrameRepair(unittest.TestCase):

    def test_image_viewer_initializes_diagnostic_download_flag(self):
        forms_path = (
            Path(__file__).resolve().parents[2]
            / 'indi_allsky'
            / 'flask'
            / 'forms.py'
        )
        forms_tree = ast.parse(
            forms_path.read_text(encoding='utf-8'),
            filename=str(forms_path),
        )
        class_assignments = {}
        for node in forms_tree.body:
            if not isinstance(node, ast.ClassDef):
                continue

            assigned_attributes = {
                child.attr
                for child in ast.walk(node)
                if (
                    isinstance(child, ast.Attribute)
                    and isinstance(child.value, ast.Name)
                    and child.value.id == 'self'
                    and isinstance(child.ctx, ast.Store)
                )
            }
            class_assignments[node.name] = assigned_attributes

        flag_name = 'asi676mc_diagnostic_download_enabled'
        self.assertIn(
            flag_name,
            class_assignments['IndiAllskyImageViewer'],
        )
        self.assertNotIn(
            flag_name,
            class_assignments['IndiAllskyGalleryViewer'],
        )

    def test_diagnostic_downloads_are_only_in_image_viewer(self):
        project_root = Path(__file__).resolve().parents[2]
        gallery_template = (
            project_root
            / 'indi_allsky'
            / 'flask'
            / 'templates'
            / 'gallery.html'
        ).read_text(encoding='utf-8')
        imageviewer_template = (
            project_root
            / 'indi_allsky'
            / 'flask'
            / 'templates'
            / 'imageviewer.html'
        ).read_text(encoding='utf-8')
        forms_path = project_root / 'indi_allsky' / 'flask' / 'forms.py'
        forms_source = forms_path.read_text(encoding='utf-8')
        forms_tree = ast.parse(forms_source, filename=str(forms_path))
        form_classes = {
            node.name: ast.get_source_segment(forms_source, node)
            for node in forms_tree.body
            if isinstance(node, ast.ClassDef)
        }

        diagnostic_markers = (
            'asi676mc_diagnostic_bad_fits',
            'asi676mc_diagnostic_following_fits',
            'data-asi676mc-bad-fits-url',
            'data-asi676mc-following-fits-url',
            'register_asi676mc_fits_button',
        )
        for marker in diagnostic_markers:
            self.assertNotIn(marker, gallery_template)

        self.assertNotIn(
            'asi676mc_diagnostic_bad_fits',
            form_classes['IndiAllskyGalleryViewer'],
        )
        self.assertNotIn(
            'asi676mc_diagnostic_following_fits',
            form_classes['IndiAllskyGalleryViewer'],
        )
        self.assertIn(
            'asi676mc_diagnostic_bad_fits',
            form_classes['IndiAllskyImageViewer'],
        )
        self.assertIn(
            'asi676mc_diagnostic_following_fits',
            form_classes['IndiAllskyImageViewer'],
        )
        self.assertIn('asi676mc_diagnostic_bad_fits', imageviewer_template)
        self.assertIn('asi676mc_diagnostic_following_fits', imageviewer_template)
        self.assertIn('Bad FITS', imageviewer_template)
        self.assertIn('Next FITS', imageviewer_template)

    def test_camera_name_gate(self):
        self.assertTrue(asi676mc.camera_name_matches('ZWO CCD ASI676MC'))
        self.assertTrue(asi676mc.camera_name_matches('ASI-676MC'))
        self.assertTrue(asi676mc.camera_name_matches('ASI676MC 1'))
        self.assertFalse(asi676mc.camera_name_matches('ZWO CCD ASI678MC'))
        self.assertFalse(asi676mc.camera_name_matches(''))

    def test_camera_record_gate_checks_persistent_names(self):
        asi_camera = SimpleNamespace(
            name='ZWO CCD',
            name_alt1='ZWO CCD ASI676MC',
            name_alt2=None,
            friendlyName='All-sky camera',
        )
        other_camera = SimpleNamespace(
            name='ZWO CCD ASI678MC',
            name_alt1=None,
            name_alt2=None,
            friendlyName='Other camera',
        )

        self.assertTrue(asi676mc.camera_record_matches(asi_camera))
        self.assertFalse(asi676mc.camera_record_matches(other_camera))

    def test_diagnostic_capture_plan_pairs_bad_and_following_frames(self):
        bad_roles, pending_id = asi676mc.diagnostic_capture_plan(
            None,
            'repaired',
            new_capture_id='pair-a',
        )
        self.assertEqual(
            bad_roles,
            [{'capture_id': 'pair-a', 'role': 'bad'}],
        )
        self.assertEqual(pending_id, 'pair-a')

        following_roles, pending_id = asi676mc.diagnostic_capture_plan(
            pending_id,
            'normal',
        )
        self.assertEqual(
            following_roles,
            [{'capture_id': 'pair-a', 'role': 'following'}],
        )
        self.assertIsNone(pending_id)

    def test_diagnostic_capture_plan_handles_consecutive_bad_frames(self):
        roles, pending_id = asi676mc.diagnostic_capture_plan(
            'pair-a',
            'repaired',
            new_capture_id='pair-b',
        )
        self.assertEqual(
            roles,
            [
                {'capture_id': 'pair-a', 'role': 'following'},
                {'capture_id': 'pair-b', 'role': 'bad'},
            ],
        )
        self.assertEqual(pending_id, 'pair-b')

    def test_diagnostic_capture_plan_includes_validation_failures(self):
        roles, pending_id = asi676mc.diagnostic_capture_plan(
            None,
            'validation_failed',
            new_capture_id='pair-a',
        )
        self.assertEqual(
            roles,
            [{'capture_id': 'pair-a', 'role': 'bad'}],
        )
        self.assertEqual(pending_id, 'pair-a')

    def test_diagnostic_capture_plan_requires_a_pair_id(self):
        with self.assertRaises(ValueError):
            asi676mc.diagnostic_capture_plan(None, 'repaired')

    def test_normal_frame_is_not_modified(self):
        data = numpy.full((64, 64), 1000, dtype=numpy.uint16)
        original = data.copy()

        result = asi676mc.repair_if_needed(data)

        self.assertFalse(result['repaired'])
        self.assertGreaterEqual(result['timing']['detection_s'], 0.0)
        self.assertEqual(result['timing']['repair_s'], 0.0)
        self.assertGreaterEqual(
            result['timing']['total_s'],
            result['timing']['detection_s'],
        )
        numpy.testing.assert_array_equal(data, original)

    def test_bad_frame_is_repaired_in_place(self):
        data = numpy.empty((64, 64), dtype=numpy.uint16)
        data[0::2, 0::2] = 4000
        data[0::2, 1::2] = 1000
        data[1::2, 0::2] = 1000
        data[1::2, 1::2] = 4000

        original_object = data
        result = asi676mc.repair_if_needed(data)

        self.assertTrue(result['repaired'])
        self.assertIs(data, original_object)
        self.assertEqual(data.dtype, numpy.uint16)
        self.assertEqual(data.shape, (64, 64))
        self.assertFalse(result['signature_after']['is_bad'])
        self.assertGreaterEqual(result['timing']['detection_s'], 0.0)
        self.assertGreaterEqual(result['timing']['repair_s'], 0.0)
        self.assertGreaterEqual(
            result['timing']['total_s'],
            result['timing']['detection_s'] + result['timing']['repair_s'],
        )

    def test_jointly_clipped_greens_use_corrected_highlight_level(self):
        height = 12
        width = 20
        data = numpy.zeros((height, width), dtype=numpy.uint16)

        # Build the input one row out of phase, matching the camera failure.
        # After row restoration, both mapped greens are clipped while the
        # corrected red/blue pair reaches the uint16 highlight ceiling.
        for source_row in range(1, height):
            output_row = source_row - 1
            if output_row % 2 == 0:
                data[source_row, 0::2] = 65520
                data[source_row, 1::2] = 65534
            else:
                data[source_row, 0::2] = 65534
                data[source_row, 1::2] = 65520

        asi676mc.repair_in_place(data)

        self.assertTrue(numpy.all(data[0::2, 1::2] == 65535))
        self.assertTrue(numpy.all(data[1::2, 0::2] == 65535))

    def test_colored_clipped_highlights_are_not_forced_to_strongest_channel(self):
        height = 12
        width = 20
        data = numpy.zeros((height, width), dtype=numpy.uint16)

        source_red = round(30000 * asi676mc.DEFAULT_SETTINGS['GAIN_R'])
        source_blue = 65520
        for source_row in range(1, height):
            output_row = source_row - 1
            if output_row % 2 == 0:
                data[source_row, 0::2] = source_red
                data[source_row, 1::2] = 65534
            else:
                data[source_row, 0::2] = 65534
                data[source_row, 1::2] = source_blue

        asi676mc.repair_in_place(data)

        expected_green = round(
            65534 / asi676mc.DEFAULT_SETTINGS['GAIN_G2']
        )
        self.assertTrue(numpy.all(data[0::2, 1::2] == expected_green))
        self.assertTrue(numpy.all(data[1::2, 0::2] == expected_green))
        self.assertTrue(numpy.all(data[1::2, 1::2] == 65535))

    def test_clipped_highlight_blend_uses_bounded_transition(self):
        self.assertEqual(
            asi676mc._highlight_blend_base_boundaries(0.55, 0.75),
            (719, 775),
        )

        height = 12
        width = 20
        plane_shape = (height // 2, width // 2)
        clipped = numpy.ones(plane_shape, dtype=numpy.bool_)
        packed = numpy.packbits(clipped, axis=1)

        cases = (
            # low/high=0.55: retain the factor-two boundary estimate.
            (33000, 60000, 53925),
            # low/high=0.65: produce a bounded intermediate estimate.
            (39000, 60000, 58429),
            # low/high=0.75: reach the strongest channel.
            (45000, 60000, 60000),
        )
        for low, high, expected_green in cases:
            with self.subTest(low=low, high=high):
                data = numpy.empty((height, width), dtype=numpy.uint16)
                data[0::2, 0::2] = low
                data[0::2, 1::2] = 10000
                data[1::2, 0::2] = 10000
                data[1::2, 1::2] = high

                asi676mc._reconstruct_clipped_green(
                    data,
                    packed,
                    packed,
                    chunk_rows=4,
                )

                self.assertTrue(
                    numpy.all(data[0::2, 1::2] == expected_green)
                )
                self.assertTrue(
                    numpy.all(data[1::2, 0::2] == expected_green)
                )

    def test_diagnostic_capture_plan_includes_exclude_only_frames(self):
        roles, pending_id = asi676mc.diagnostic_capture_plan(
            None,
            'excluded',
            new_capture_id='pair-excluded',
        )
        self.assertEqual(
            roles,
            [{'capture_id': 'pair-excluded', 'role': 'bad'}],
        )
        self.assertEqual(pending_id, 'pair-excluded')

    def test_detect_frame_classifies_without_mutating_source(self):
        data = numpy.empty((64, 64), dtype=numpy.uint16)
        data[0::2, 0::2] = 4000
        data[0::2, 1::2] = 1000
        data[1::2, 0::2] = 1000
        data[1::2, 1::2] = 4000
        original = data.copy()

        result = asi676mc.detect_frame(data)

        self.assertTrue(result['is_bad'])
        self.assertTrue(result['signature']['is_bad'])
        self.assertEqual(result['timing']['repair_s'], 0.0)
        numpy.testing.assert_array_equal(data, original)

    def test_balanced_clipped_highlights_reach_strongest_channel(self):
        height = 12
        width = 20
        data = numpy.empty((height, width), dtype=numpy.uint16)
        data[0::2, 0::2] = 60000
        data[0::2, 1::2] = 59992
        data[1::2, 0::2] = 59992
        data[1::2, 1::2] = 65535

        plane_shape = (height // 2, width // 2)
        clipped = numpy.ones(plane_shape, dtype=numpy.bool_)
        packed = numpy.packbits(clipped, axis=1)

        asi676mc._reconstruct_clipped_green(
            data,
            packed,
            packed,
            chunk_rows=4,
        )

        # low/high is above the 0.75 upper blend boundary.
        self.assertTrue(numpy.all(data[0::2, 1::2] == 65535))
        self.assertTrue(numpy.all(data[1::2, 0::2] == 65535))

    def test_configured_highlight_blend_boundaries_change_transition(self):
        height = 12
        width = 20
        data = numpy.empty((height, width), dtype=numpy.uint16)
        data[0::2, 0::2] = 39000
        data[0::2, 1::2] = 10000
        data[1::2, 0::2] = 10000
        data[1::2, 1::2] = 60000

        plane_shape = (height // 2, width // 2)
        clipped = numpy.ones(plane_shape, dtype=numpy.bool_)
        packed = numpy.packbits(clipped, axis=1)

        asi676mc._reconstruct_clipped_green(
            data,
            packed,
            packed,
            chunk_rows=4,
            highlight_blend_start_ratio=0.65,
            highlight_blend_end_ratio=0.85,
        )

        # low/high=0.65 is now the start boundary, so retain factor two.
        self.assertTrue(numpy.all(data[0::2, 1::2] == 56325))
        self.assertTrue(numpy.all(data[1::2, 0::2] == 56325))

    def test_configured_threshold_can_leave_frame_untouched(self):
        data = numpy.empty((64, 64), dtype=numpy.uint16)
        data[0::2, 0::2] = 4000
        data[0::2, 1::2] = 1000
        data[1::2, 0::2] = 1000
        data[1::2, 1::2] = 4000
        original = data.copy()

        result = asi676mc.repair_if_needed(
            data,
            {'PURPLE_RATIO_THRESHOLD': 10.0},
        )

        self.assertFalse(result['repaired'])
        numpy.testing.assert_array_equal(data, original)

    def test_invalid_raw_layout_is_rejected_before_mutation(self):
        odd_width = numpy.zeros((64, 63), dtype=numpy.uint16)
        original = odd_width.copy()

        with self.assertRaises(ValueError):
            asi676mc.repair_if_needed(odd_width)

        numpy.testing.assert_array_equal(odd_width, original)

    def test_failed_validation_retains_original_frame(self):
        data = numpy.empty((64, 64), dtype=numpy.uint16)
        data[0::2, 0::2] = 4000
        data[0::2, 1::2] = 1000
        data[1::2, 0::2] = 1000
        data[1::2, 1::2] = 4000
        original = data.copy()

        with mock.patch.object(asi676mc, 'repair_in_place', side_effect=lambda frame, settings: frame):
            result = asi676mc.repair_if_needed(data)

        self.assertFalse(result['repaired'])
        self.assertTrue(result['validation_failed'])
        numpy.testing.assert_array_equal(data, original)

    def test_chunk_and_sample_sizes_must_preserve_bayer_parity(self):
        with self.assertRaises(ValueError):
            asi676mc.normalize_settings({'SAMPLE_STEP': 3})

        with self.assertRaises(ValueError):
            asi676mc.normalize_settings({'CHUNK_ROWS': 3})

    def test_highlight_blend_ratios_must_be_ordered(self):
        with self.assertRaises(ValueError):
            asi676mc.normalize_settings({
                'HIGHLIGHT_BLEND_START_RATIO': 0.0,
            })

        with self.assertRaises(ValueError):
            asi676mc.normalize_settings({
                'HIGHLIGHT_BLEND_END_RATIO': 1.01,
            })

        with self.assertRaises(ValueError):
            asi676mc.normalize_settings({
                'HIGHLIGHT_BLEND_START_RATIO': 0.75,
                'HIGHLIGHT_BLEND_END_RATIO': 0.55,
            })

        with self.assertRaises(ValueError):
            asi676mc.normalize_settings({
                'HIGHLIGHT_BLEND_START_RATIO': 0.98,
                'HIGHLIGHT_BLEND_END_RATIO': 0.99,
            })

    def test_packed_clipping_mask_preserves_partial_final_byte(self):
        data = numpy.arange(12 * 20, dtype=numpy.uint16).reshape((12, 20))
        expected_green1 = data[0::2, 1::2] >= 100
        expected_both = expected_green1 & (data[1::2, 0::2] >= 100)

        packed = asi676mc._pack_clipped_green_mask(data, 100, 4)
        unpacked = numpy.unpackbits(
            packed,
            axis=1,
            count=expected_green1.shape[1],
        ).view(numpy.bool_)

        self.assertEqual(packed.shape, (6, 2))
        numpy.testing.assert_array_equal(unpacked, expected_green1)

        packed_green1, packed_both = asi676mc._pack_clipped_green_masks(
            data,
            100,
            4,
        )
        unpacked_both = numpy.unpackbits(
            packed_both,
            axis=1,
            count=expected_both.shape[1],
        ).view(numpy.bool_)
        numpy.testing.assert_array_equal(packed_green1, packed)
        numpy.testing.assert_array_equal(unpacked_both, expected_both)

    def test_repair_audit_metadata_is_json_safe(self):
        signature_before = {
            'purple_ratio': numpy.float64(2.0),
            'red_side_ratio': numpy.float64(1.5),
            'blue_side_ratio': numpy.float64(1.75),
        }
        signature_after = {
            'purple_ratio': numpy.float64(0.9),
            'red_side_ratio': numpy.float64(1.0),
            'blue_side_ratio': numpy.float64(1.0),
        }

        metadata = asi676mc.audit_metadata(
            'repaired',
            signature_before=signature_before,
            signature_after=signature_after,
            timing={
                'detection_s': numpy.float64(0.001),
                'repair_s': numpy.float64(0.010),
                'total_s': numpy.float64(0.011),
            },
        )

        self.assertEqual(metadata['status'], 'repaired')
        self.assertEqual(metadata['signature_before']['purple_ratio'], 2.0)
        self.assertEqual(metadata['signature_after']['purple_ratio'], 0.9)
        self.assertEqual(metadata['timing']['detection_s'], 0.001)
        self.assertEqual(metadata['timing']['repair_s'], 0.010)
        self.assertEqual(metadata['timing']['total_s'], 0.011)
        json.dumps(metadata)


if __name__ == '__main__':
    unittest.main()
