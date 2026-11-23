from pathlib import Path
import unittest

import numpy as np
from PIL import Image, ImageDraw

from indi_allsky.overlay.skyReticleOverlay import (
    draw_sky_reticles_opencv,
    draw_sky_reticles_pillow,
    project_sky_objects,
)


class TestSkyReticleOverlay(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.project_root = Path(__file__).resolve().parents[2]

    def _base_config(self):
        return {
            'LENS_AZIMUTH': 0.0,
            'LENS_IMAGE_CIRCLE': 400,
            'LENS_OFFSET_X': 10,
            'LENS_OFFSET_Y': -20,
            'LENS_ALTITUDE': 90.0,
            'IMAGE_FLIP_H': False,
            'VIRTUALSKY': {
                'POINTING_AZIMUTH': 0.0,
                'RADIAL_DISTORTION': 0.0,
                'CALIBRATION_ENABLED': False,
            },
        }

    def _overlay_cfg(self, **overrides):
        cfg = {
            'OVERLAY_ENABLE': True,
            'OVERLAY_STYLE': 'circle',
            'OVERLAY_RADIUS': 12,
            'OVERLAY_THICKNESS': 2,
            'OVERLAY_COLOR': [0, 255, 255],
            'OVERLAY_LABEL_ENABLE': True,
        }
        cfg.update(overrides)
        return cfg

    def test_zenith_projection_with_offsets_and_binning(self):
        cfg = self._base_config()
        items = [
            {'id': 'QFA1', 'alt': 90.0, 'az': 0.0},
            {'title': 'ISS (ZARYA)', 'alt': 90.0, 'az': 0.0},
            {'id': 'BAD', 'alt': 'nan', 'az': 10.0},
        ]

        pts_bin1 = project_sky_objects(items, cfg, 600, 400, binning=1)
        self.assertEqual(len(pts_bin1), 2)
        self.assertAlmostEqual(pts_bin1[0]['x'], 310.0, places=2)
        self.assertAlmostEqual(pts_bin1[0]['y'], 220.0, places=2)

        pts_bin2 = project_sky_objects(items, cfg, 300, 200, binning=2)
        self.assertEqual(len(pts_bin2), 2)
        self.assertAlmostEqual(pts_bin2[0]['x'], 155.0, places=2)
        self.assertAlmostEqual(pts_bin2[0]['y'], 110.0, places=2)

    def test_draw_sky_reticles_opencv_aircraft_and_satellites(self):
        cfg = self._base_config()
        aircraft = [{'id': 'UAL123', 'alt': 90.0, 'az': 0.0}]
        satellites = [{'title': 'ISS (ZARYA)', 'alt': 85.0, 'az': 45.0}]

        disabled = self._overlay_cfg(OVERLAY_ENABLE=False)
        img_disabled = np.zeros((400, 600, 3), dtype=np.uint8)
        self.assertEqual(draw_sky_reticles_opencv(img_disabled, aircraft, disabled, cfg), 0)
        self.assertEqual(int(img_disabled.sum()), 0)

        for style in ('circle', 'cross', 'both'):
            img_ac = np.zeros((400, 600, 3), dtype=np.uint8)
            self.assertEqual(
                draw_sky_reticles_opencv(
                    img_ac, aircraft, self._overlay_cfg(OVERLAY_STYLE=style), cfg, label_keys=('id',)
                ),
                1,
            )
            self.assertGreater(int(img_ac.sum()), 0)

            img_sat = np.zeros((400, 600, 3), dtype=np.uint8)
            self.assertEqual(
                draw_sky_reticles_opencv(
                    img_sat,
                    satellites,
                    self._overlay_cfg(OVERLAY_STYLE=style, OVERLAY_COLOR=[163, 230, 53]),
                    cfg,
                    label_keys=('title',),
                ),
                1,
            )
            self.assertGreater(int(img_sat.sum()), 0)

    def test_draw_sky_reticles_pillow_styles(self):
        cfg = self._base_config()
        satellites = [{'title': 'HST', 'alt': 90.0, 'az': 0.0}]

        for style in ('circle', 'cross', 'both'):
            img = Image.new('RGB', (600, 400), (0, 0, 0))
            draw = ImageDraw.Draw(img)
            count = draw_sky_reticles_pillow(
                draw,
                img.size,
                satellites,
                self._overlay_cfg(OVERLAY_STYLE=style, OVERLAY_COLOR=[163, 230, 53]),
                cfg,
                label_keys=('title',),
            )
            self.assertEqual(count, 1)
            self.assertGreater(int(np.asarray(img).sum()), 0)

    def test_ui_views_and_docs_wiring(self):
        adsb_html = (self.project_root / 'indi_allsky' / 'flask' / 'templates' / 'config' / 'adsb.html').read_text(encoding='utf-8')
        sat_html = (self.project_root / 'indi_allsky' / 'flask' / 'templates' / 'config' / 'sat_track.html').read_text(encoding='utf-8')
        virtualsky_html = (self.project_root / 'indi_allsky' / 'flask' / 'templates' / 'virtualsky.html').read_text(encoding='utf-8')
        views_py = (self.project_root / 'indi_allsky' / 'flask' / 'views.py').read_text(encoding='utf-8')
        sat_doc = (self.project_root / 'docs' / 'wiki' / 'Satellite-Tracking.md').read_text(encoding='utf-8')

        self.assertIn('ADSB__OVERLAY_ENABLE', adsb_html)
        self.assertIn('SATELLITE_TRACK__OVERLAY_ENABLE', sat_html)
        self.assertIn('SATELLITE_TRACK__TLE_INCLUDE', sat_html)
        self.assertIn('SATELLITE_TRACK__TLE_EXCLUDE', sat_html)
        self.assertIn('drawSkyReticleOverlay', virtualsky_html)
        self.assertIn('drawSkyReticleOverlays', virtualsky_html)
        self.assertIn('#SAT_OVERLAY', virtualsky_html)
        self.assertIn("data['aircraft']", views_py)
        self.assertIn("data['satellites']", views_py)
        self.assertIn('Satellite Reticle Overlay', sat_doc)

    def test_satellite_tle_filter(self):
        from indi_allsky.overlay.skyReticleOverlay import satellite_title_matches_filter

        fn = satellite_title_matches_filter
        self.assertTrue(fn('SL-4 R/B', '', ''))
        self.assertFalse(fn('SL-4 R/B', '', 'R/B, DEB'))
        self.assertTrue(fn('ISS (ZARYA)', '', 'R/B, DEB'))
        self.assertTrue(fn('ISS (ZARYA)', 'iss, hst', ''))
        self.assertFalse(fn('SL-4 R/B', 'iss, hst', ''))
        self.assertFalse(fn('ISS R/B', 'iss', 'r/b'))


if __name__ == '__main__':
    unittest.main()
