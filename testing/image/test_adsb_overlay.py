from pathlib import Path
import unittest

import numpy as np
from PIL import Image, ImageDraw

from indi_allsky.overlay.adsbOverlay import (
    draw_adsb_overlay_opencv,
    draw_adsb_overlay_pillow,
    project_aircraft_positions,
)


class TestAdsbOverlay(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.project_root = Path(__file__).resolve().parents[2]

    def _base_config(self, **adsb_overrides):
        adsb_cfg = {
            'ENABLE': True,
            'OVERLAY_ENABLE': True,
            'OVERLAY_STYLE': 'circle',
            'OVERLAY_RADIUS': 12,
            'OVERLAY_THICKNESS': 2,
            'OVERLAY_COLOR': [0, 255, 255],
            'OVERLAY_LABEL_ENABLE': True,
        }
        adsb_cfg.update(adsb_overrides)
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
            'ADSB': adsb_cfg,
        }

    def test_zenith_projection_with_offsets_and_binning(self):
        cfg = self._base_config()
        aircraft = [
            {'id': 'QFA1', 'alt': 90.0, 'az': 0.0},
            {'id': 'BAD', 'alt': 'nan', 'az': 10.0},
        ]

        pts_bin1 = project_aircraft_positions(aircraft, cfg, 600, 400, binning=1)
        self.assertEqual(len(pts_bin1), 1)
        self.assertAlmostEqual(pts_bin1[0]['x'], 310.0, places=2)
        self.assertAlmostEqual(pts_bin1[0]['y'], 220.0, places=2)

        pts_bin2 = project_aircraft_positions(aircraft, cfg, 300, 200, binning=2)
        self.assertEqual(len(pts_bin2), 1)
        self.assertAlmostEqual(pts_bin2[0]['x'], 155.0, places=2)
        self.assertAlmostEqual(pts_bin2[0]['y'], 110.0, places=2)

    def test_draw_adsb_overlay_opencv_styles(self):
        aircraft = [{'id': 'UAL123', 'alt': 90.0, 'az': 0.0}]

        disabled_cfg = self._base_config(OVERLAY_ENABLE=False)
        img_disabled = np.zeros((400, 600, 3), dtype=np.uint8)
        self.assertEqual(draw_adsb_overlay_opencv(img_disabled, aircraft, disabled_cfg), 0)
        self.assertEqual(int(img_disabled.sum()), 0)

        for style in ('circle', 'cross', 'both'):
            cfg = self._base_config(OVERLAY_STYLE=style)
            img = np.zeros((400, 600, 3), dtype=np.uint8)
            count = draw_adsb_overlay_opencv(img, aircraft, cfg)
            self.assertEqual(count, 1)
            self.assertGreater(int(img.sum()), 0)

    def test_draw_adsb_overlay_pillow_styles(self):
        aircraft = [{'id': 'VOZ456', 'alt': 90.0, 'az': 0.0}]

        for style in ('circle', 'cross', 'both'):
            cfg = self._base_config(OVERLAY_STYLE=style)
            img = Image.new('RGB', (600, 400), (0, 0, 0))
            draw = ImageDraw.Draw(img)
            count = draw_adsb_overlay_pillow(draw, img.size, aircraft, cfg)
            self.assertEqual(count, 1)
            self.assertGreater(int(np.asarray(img).sum()), 0)

    def test_ui_and_views_wiring(self):
        adsb_html = (self.project_root / 'indi_allsky' / 'flask' / 'templates' / 'config' / 'adsb.html').read_text(encoding='utf-8')
        virtualsky_html = (self.project_root / 'indi_allsky' / 'flask' / 'templates' / 'virtualsky.html').read_text(encoding='utf-8')
        views_py = (self.project_root / 'indi_allsky' / 'flask' / 'views.py').read_text(encoding='utf-8')

        self.assertIn('ADSB__OVERLAY_ENABLE', adsb_html)
        self.assertIn('ADSB__OVERLAY_STYLE', adsb_html)
        self.assertIn('drawAdsbAircraftOverlay', virtualsky_html)
        self.assertIn("data['aircraft']", views_py)


if __name__ == '__main__':
    unittest.main()
