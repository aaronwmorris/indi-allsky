"""Stream overlay using indi-allsky's actual overlay modules.

Imports the real CardinalDirs, Orb, MoonOverlay classes and uses
Pillow for text rendering (matching the original processing.py exactly).
"""

from __future__ import annotations

import json
import math
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import ephem
except ImportError:
    ephem = None

try:
    from PIL import Image as PILImage, ImageFont, ImageDraw
    _has_pillow = True
except ImportError:
    _has_pillow = False

logger = logging.getLogger(__name__)

DB_PATH = "/var/lib/indi-allsky/indi-allsky.sqlite"


class _Constants:
    POSITION_LATITUDE = 0
    POSITION_LONGITUDE = 1
    POSITION_ELEVATION = 2


def _load_config() -> dict:
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT data FROM config ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
    except Exception as e:
        logger.warning("Could not load config from DB: %s", e)
    return {}


def _try_import_overlay(module_name: str, class_name: str):
    overlay_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "overlay"
    )
    module_path = os.path.join(overlay_dir, module_name + ".py")
    if not os.path.isfile(module_path):
        return None
    import importlib.util
    if "indi_allsky.constants" not in sys.modules:
        sys.modules["indi_allsky"] = type(sys)("indi_allsky")
        sys.modules["indi_allsky.constants"] = _Constants
        sys.modules["indi_allsky"].constants = _Constants
    spec = importlib.util.spec_from_file_location(
        f"indi_allsky.overlay.{module_name}", module_path,
        submodule_search_locations=[overlay_dir],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"indi_allsky.overlay.{module_name}"] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        logger.warning("Could not import overlay %s: %s", module_name, e)
        return None
    return getattr(mod, class_name, None)


# Font search paths (same as original)
FONT_PATHS = [
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
]


class StreamOverlay:
    """Render OSD onto stream frames using indi-allsky's overlay modules + Pillow text."""

    def __init__(
        self,
        latitude: float = 0.0,
        longitude: float = 0.0,
        elevation: float = 0.0,
    ) -> None:
        self._lat = latitude
        self._lon = longitude
        self._elev = elevation
        self._config = _load_config()

        # Text properties (from config, same as processing.py)
        tp = self._config.get("TEXT_PROPERTIES", {})
        self._text_color_rgb = list(tp.get("FONT_COLOR", [200, 200, 200]))
        self._text_xy = [int(tp.get("FONT_X", 30)), int(tp.get("FONT_Y", 30))]
        self._text_size_pillow = int(tp.get("PIL_FONT_SIZE", 30))
        self._text_font_height = int(tp.get("FONT_HEIGHT", 30))
        self._text_anchor = "la"
        self._font_outline = tp.get("FONT_OUTLINE", True)

        # Font file
        font_file = tp.get("PIL_FONT_FILE", "fonts-freefont-ttf/FreeMonoBold.ttf")
        self._font_path = self._find_font(font_file)

        # Label template
        self._label_template = self._config.get(
            "IMAGE_LABEL_TEMPLATE",
            "{timestamp:%Y%m%d %H:%M:%S}\nExposure {exposure:0.6f}\nGain {gain_f:0.2f}",
        )

        # Ephem observer
        self._observer: Any = None
        if ephem is not None and (latitude != 0 or longitude != 0):
            self._observer = ephem.Observer()
            self._observer.lat = str(latitude)
            self._observer.lon = str(longitude)
            self._observer.elevation = elevation
            self._observer.pressure = 0

        self._astro_cache: dict = {}
        self._astro_cache_time: float = 0

        # Position (simple list, no multiprocessing needed for stream)
        self._position_av = [latitude, longitude, elevation]

        # Import overlay modules
        self._cardinal_dirs = None
        self._orb = None
        self._moon_overlay = None

        CardinalCls = _try_import_overlay("cardinalDirsLabel", "IndiAllskyCardinalDirsLabel")
        if CardinalCls:
            try:
                self._cardinal_dirs = CardinalCls(self._config)
            except Exception as e:
                logger.warning("Cardinal dirs init failed: %s", e)

        OrbCls = _try_import_overlay("orb", "IndiAllskyOrbGenerator")
        if OrbCls:
            try:
                self._orb = OrbCls(self._config)
                self._orb.sun_alt_deg = self._config.get('NIGHT_SUN_ALT_DEG', -6.0)
                self._orb.azimuth_offset = self._config.get('ORB_PROPERTIES', {}).get('AZ_OFFSET', 0.0)
                self._orb.retrograde = self._config.get('ORB_PROPERTIES', {}).get('RETROGRADE', False)
                self._orb.sun_color_rgb = self._config.get('ORB_PROPERTIES', {}).get('SUN_COLOR', [200, 200, 0])
                self._orb.moon_color_rgb = self._config.get('ORB_PROPERTIES', {}).get('MOON_COLOR', [128, 128, 128])
            except Exception as e:
                logger.warning("Orb init failed: %s", e)

        MoonCls = _try_import_overlay("moonOverlay", "IndiAllSkyMoonOverlay")
        if MoonCls:
            try:
                self._moon_overlay = MoonCls(self._config)
            except Exception as e:
                logger.warning("Moon overlay init failed: %s", e)

        self._moon_scaled = False
        self._logo = None
        self._logo_alpha = None

    def _find_font(self, font_file: str) -> Optional[Path]:
        """Locate a font file in system font paths."""
        for base in FONT_PATHS:
            p = base / font_file
            if p.is_file():
                return p
        # Try truetype subdirs
        for base in FONT_PATHS:
            for sub in base.rglob(Path(font_file).name):
                if sub.is_file():
                    return sub
        return None

    # ------------------------------------------------------------------
    # Main apply
    # ------------------------------------------------------------------

    def apply(self, frame: np.ndarray, metadata: dict) -> np.ndarray:
        if cv2 is None:
            return frame

        h, w = frame.shape[:2]
        self._refresh_astro()
        full_w = 4056
        scale = max(0.15, w / full_w)

        # 1. Orb — scale radius
        if self._orb:
            orig_radius = self._config.get("ORB_PROPERTIES", {}).get("RADIUS", 9)
            self._orb.config["ORB_PROPERTIES"]["RADIUS"] = max(2, int(orig_radius * scale))
            self._apply_orb(frame)
            self._orb.config["ORB_PROPERTIES"]["RADIUS"] = orig_radius

        # 2. Cardinal dirs — draw at image edges with padding
        if self._config.get("CARDINAL_DIRS", {}).get("ENABLE"):
            self._draw_cardinals_edge(frame, w, h, scale)

        # 3. Moon overlay — scale position and size once
        if self._moon_overlay and self._config.get("MOON_OVERLAY", {}).get("ENABLE", True):
            try:
                if not self._moon_scaled:
                    self._moon_overlay.x = int(self._moon_overlay.x * scale)
                    self._moon_overlay.y = int(self._moon_overlay.y * scale)
                    self._moon_overlay.scale = self._moon_overlay.scale * scale
                    self._moon_overlay.moon_orig = None
                    self._moon_scaled = True
                moon_cycle = self._astro_cache.get("moon_cycle", 0)
                moon_phase = self._astro_cache.get("moon_phase", 0)
                self._moon_overlay.apply(frame, moon_cycle, moon_phase)
            except Exception as e:
                logger.debug("Moon overlay error: %s", e)

        # 4. Text label using Pillow (matches processing.py exactly)
        self._draw_label_pillow(frame, w, h, metadata, scale)

        return frame

    # ------------------------------------------------------------------
    # Pillow text rendering (extracted from processing.py)
    # ------------------------------------------------------------------

    def _draw_cardinals_edge(self, frame: np.ndarray, w: int, h: int, scale: float) -> None:
        """Draw N/S/E/W labels at image edges with equal padding."""
        if not _has_pillow:
            return
        cfg = self._config.get("CARDINAL_DIRS", {})
        color_rgb = tuple(cfg.get("FONT_COLOR", [255, 0, 0]))
        pad = max(5, int(15 * scale))
        font_size = max(12, int(cfg.get("PIL_FONT_SIZE", 20) * scale))

        try:
            font = ImageFont.truetype(str(self._font_path), font_size) if self._font_path else ImageFont.load_default()
        except Exception:
            font = ImageFont.load_default()

        chars = {
            "N": cfg.get("CHAR_NORTH", "N"),
            "S": cfg.get("CHAR_SOUTH", "S"),
            "E": cfg.get("CHAR_EAST", "E"),
            "W": cfg.get("CHAR_WEST", "W"),
        }
        if cfg.get("SWAP_NS"):
            chars["N"], chars["S"] = chars["S"], chars["N"]
        if cfg.get("SWAP_EW"):
            chars["E"], chars["W"] = chars["W"], chars["E"]

        # Frame is BGR; Pillow sees it as RGB, so swap R/B in colors
        color_bgr = (color_rgb[2], color_rgb[1], color_rgb[0])
        img = PILImage.fromarray(frame)
        draw = ImageDraw.Draw(img)

        stroke = max(1, int(4 * scale)) if self._font_outline else 0

        # Respect IMAGE_FLIP_V/H
        if self._config.get("IMAGE_FLIP_V"):
            chars["N"], chars["S"] = chars["S"], chars["N"]
        if self._config.get("IMAGE_FLIP_H"):
            chars["E"], chars["W"] = chars["W"], chars["E"]

        draw.text((w // 2, pad), chars["N"], fill=color_bgr, font=font,
                  anchor="mt", stroke_width=stroke, stroke_fill=(0, 0, 0))
        draw.text((w // 2, h - pad), chars["S"], fill=color_bgr, font=font,
                  anchor="mb", stroke_width=stroke, stroke_fill=(0, 0, 0))
        draw.text((w - pad, h // 2), chars["E"], fill=color_bgr, font=font,
                  anchor="rm", stroke_width=stroke, stroke_fill=(0, 0, 0))
        draw.text((pad, h // 2), chars["W"], fill=color_bgr, font=font,
                  anchor="lm", stroke_width=stroke, stroke_fill=(0, 0, 0))

        np.copyto(frame, np.array(img))

    def _draw_label_pillow(self, frame: np.ndarray, w: int, h: int,
                           metadata: dict, scale: float) -> None:
        """Render IMAGE_LABEL_TEMPLATE using Pillow — same as processing.py."""
        if not _has_pillow:
            return

        # Format the template
        text = self._format_label(metadata)
        if not text:
            return

        # Frame is BGR; Pillow sees it as RGB — swap R/B in color tuples
        img = PILImage.fromarray(frame)
        draw = ImageDraw.Draw(img)

        # Scale font size for stream resolution
        base_size = self._text_size_pillow
        font_size = max(10, int(base_size * scale))
        font_height = max(10, int(self._text_font_height * scale))

        # Reset state — config colors are RGB, swap to BGR for Pillow-on-BGR-frame
        default_rgb = self._text_color_rgb
        color_bgr = (int(default_rgb[2]), int(default_rgb[1]), int(default_rgb[0]))
        xy = [int(self._text_xy[0] * scale), int(self._text_xy[1] * scale)]
        anchor = "la"

        for line in text.split("\n"):
            if line.startswith("#"):
                # Process directive (same regex as processing.py)
                m_color = re.search(r'color:(\d{1,3}),(\d{1,3}),(\d{1,3})', line, re.IGNORECASE)
                if m_color:
                    # Template colors are RGB, swap to BGR for Pillow-on-BGR-frame
                    color_bgr = (int(m_color.group(3)), int(m_color.group(2)), int(m_color.group(1)))

                m_xy = re.search(r'xy:(-?\d+),(-?\d+)', line, re.IGNORECASE)
                if m_xy:
                    nx, ny = int(m_xy.group(1)), int(m_xy.group(2))
                    xy = [
                        int(nx * scale) if nx >= 0 else w + int(nx * scale),
                        int(ny * scale) if ny >= 0 else h + int(ny * scale),
                    ]

                m_anchor = re.search(r'anchor:([a-z]{2})', line, re.IGNORECASE)
                if m_anchor:
                    anchor = m_anchor.group(1).lower()

                m_size = re.search(r'size:(\d+)', line, re.IGNORECASE)
                if m_size:
                    sz = int(m_size.group(1))
                    font_size = max(8, int(sz * scale))
                    font_height = max(8, int(sz * scale))
                continue

            # Render text line
            try:
                font = ImageFont.truetype(str(self._font_path), font_size) if self._font_path else ImageFont.load_default()
            except Exception:
                font = ImageFont.load_default()

            stroke_width = max(1, int(4 * scale)) if self._font_outline else 0

            draw.text(
                tuple(xy),
                line,
                fill=color_bgr,
                font=font,
                stroke_width=stroke_width,
                stroke_fill=(0, 0, 0),
                anchor=anchor,
            )

            xy[1] += font_height

        np.copyto(frame, np.array(img))

    def _format_label(self, metadata: dict) -> str:
        """Format the IMAGE_LABEL_TEMPLATE with current values."""
        exp_us = metadata.get("ExposureTime", 0)
        exposure = exp_us / 1e6 if exp_us else 0
        gain = metadata.get("AnalogueGain", 0)
        temp_c = metadata.get("SensorTemperature")
        now = datetime.now(timezone.utc)

        # Temperature in configured unit
        temp_display = self._config.get("TEMP_DISPLAY", "c")
        if temp_c is not None:
            if temp_display == "f":
                temp_val = temp_c * 9 / 5 + 32
                temp_unit = "F"
            elif temp_display == "k":
                temp_val = temp_c + 273.15
                temp_unit = "K"
            else:
                temp_val = temp_c
                temp_unit = "C"
        else:
            temp_val = 0
            temp_unit = "C"

        # Rational exposure (e.g. "1/500" for short exposures)
        if exposure > 0 and exposure < 1:
            from fractions import Fraction
            rational_exp = str(Fraction(exposure).limit_denominator(10000))
        else:
            rational_exp = "{:.1f}".format(exposure)

        sun_alt = self._astro_cache.get("sun_alt", 0)
        moon_alt = self._astro_cache.get("moon_alt", 0)

        variables = {
            "timestamp": now,
            "ts": now, "ts_utc": now, "timestamp_utc": now,
            "exposure": exposure,
            "rational_exp": rational_exp,
            "gain": gain, "gain_f": gain,
            "temp": temp_val, "temp_unit": temp_unit,
            "temp_c": temp_c if temp_c is not None else 0,
            "stars": 0, "detections": 0,
            "latitude": self._lat, "longitude": self._lon,
            "elevation": self._elev,
            "sun_alt": sun_alt,
            "sun_up": "Up" if sun_alt > 0 else "Down",
            "moon_alt": moon_alt,
            "moon_phase": self._astro_cache.get("moon_phase", 0),
            "moon_cycle": self._astro_cache.get("moon_cycle", 0),
            "moon_up": "Up" if moon_alt > 0 else "Down",
            "lux": metadata.get("Lux", 0),
            "stretch": "", "stack_method": "", "stack_count": 0,
            "kpindex": 0, "ovation_max": 0, "smoke_rating": "Clear",
            "sqm": 0, "camera_sqm_raw_mag": 0,
            # Satellites (placeholders until live data available)
            "iss_up": "--", "iss_alt": 0, "iss_next_h": 0, "iss_next_alt": 0,
            "hst_up": "--", "hst_alt": 0, "hst_next_h": 0, "hst_next_alt": 0,
            "tiangong_up": "--", "tiangong_alt": 0, "tiangong_next_h": 0, "tiangong_next_alt": 0,
            # Planets
            "mercury_alt": self._astro_cache.get("mercury_alt", 0),
            "mercury_up": "Up" if self._astro_cache.get("mercury_alt", 0) > 0 else "Down",
            "venus_alt": self._astro_cache.get("venus_alt", 0),
            "venus_up": "Up" if self._astro_cache.get("venus_alt", 0) > 0 else "Down",
            "venus_phase": 0,
            "mars_alt": self._astro_cache.get("mars_alt", 0),
            "mars_up": "Up" if self._astro_cache.get("mars_alt", 0) > 0 else "Down",
            "jupiter_alt": self._astro_cache.get("jupiter_alt", 0),
            "jupiter_up": "Up" if self._astro_cache.get("jupiter_alt", 0) > 0 else "Down",
            "saturn_alt": self._astro_cache.get("saturn_alt", 0),
            "saturn_up": "Up" if self._astro_cache.get("saturn_alt", 0) > 0 else "Down",
            # Device status placeholders
            "dew_heater_status": "", "fan_status": "",
            "owner": "", "location": "",
        }

        # Process template: format text lines, pass directives through
        result_lines = []
        for raw_line in self._label_template.split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                result_lines.append(line)
                continue
            try:
                result_lines.append(line.format(**variables))
            except (KeyError, ValueError, IndexError, TypeError):
                result_lines.append(line)

        return "\n".join(result_lines)

    # ------------------------------------------------------------------
    # Orb
    # ------------------------------------------------------------------

    def _apply_orb(self, frame: np.ndarray) -> None:
        if self._orb is None or self._observer is None:
            return
        orb_mode = self._config.get("ORB_PROPERTIES", {}).get("MODE", "ha")
        if orb_mode == "off":
            return
        try:
            utcnow = datetime.now(tz=timezone.utc)
            obs = ephem.Observer()
            obs.lon = math.radians(self._lon)
            obs.lat = math.radians(self._lat)
            obs.elevation = self._elev
            obs.pressure = 0
            obs.date = utcnow
            sun = ephem.Sun()
            sun.compute(obs)
            moon = ephem.Moon()
            moon.compute(obs)
            self._orb.text_color_rgb = list(self._text_color_rgb)
            if orb_mode == "ha":
                self._orb.drawOrbsHourAngle_opencv(frame, utcnow, obs, sun, moon)
            elif orb_mode == "az":
                self._orb.drawOrbsAzimuth_opencv(frame, utcnow, obs, sun, moon)
            elif orb_mode == "alt":
                self._orb.drawOrbsAltitude_opencv(frame, utcnow, obs, sun, moon)
        except Exception as e:
            logger.debug("Orb error: %s", e)

    # ------------------------------------------------------------------
    # Celestial
    # ------------------------------------------------------------------

    def _refresh_astro(self) -> None:
        now = time.monotonic()
        if now - self._astro_cache_time < 10.0:
            return
        self._astro_cache_time = now
        if self._observer is None or ephem is None:
            return
        try:
            self._observer.date = ephem.now()
            sun = ephem.Sun(self._observer)
            moon = ephem.Moon(self._observer)
            sun_lon = ephem.Ecliptic(sun).lon
            moon_lon = ephem.Ecliptic(moon).lon
            sm_angle = (moon_lon - sun_lon) % math.tau
            moon_cycle_pct = (sm_angle / math.tau) * 100.0

            self._astro_cache = {
                "sun_alt": math.degrees(float(sun.alt)),
                "sun_az": math.degrees(float(sun.az)),
                "moon_alt": math.degrees(float(moon.alt)),
                "moon_az": math.degrees(float(moon.az)),
                "moon_phase": moon.phase,
                "moon_cycle": moon_cycle_pct,
            }
            for name, body in [
                ("mercury", ephem.Mercury), ("venus", ephem.Venus),
                ("mars", ephem.Mars), ("jupiter", ephem.Jupiter),
                ("saturn", ephem.Saturn),
            ]:
                try:
                    p = body(self._observer)
                    self._astro_cache[name + "_alt"] = math.degrees(float(p.alt))
                    self._astro_cache[name + "_az"] = math.degrees(float(p.az))
                except Exception:
                    pass
        except Exception:
            pass
