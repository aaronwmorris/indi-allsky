"""Unit tests for system hardware profiling and performance calibration."""

import os
from pathlib import Path
import unittest
from unittest.mock import mock_open, patch

template_config = Path(__file__).resolve().parents[2] / 'flask.json_template'
os.environ.setdefault('INDI_ALLSKY_FLASK_CONFIG', str(template_config))

from indi_allsky.system_profile import (
    get_memory_total_bytes,
    get_swap_total_bytes,
    get_system_hardware_profile,
)


class TestSystemProfile(unittest.TestCase):
    def test_get_memory_total_bytes_from_proc(self):
        fake_meminfo = (
            "MemTotal:        2048000 kB\n"
            "MemFree:          512000 kB\n"
            "MemAvailable:    1024000 kB\n"
        )
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=fake_meminfo)):
                total = get_memory_total_bytes()
                self.assertEqual(total, 2048000 * 1024)

    def test_get_swap_total_bytes_from_proc(self):
        fake_meminfo = (
            "MemTotal:        2048000 kB\n"
            "SwapTotal:       1024000 kB\n"
            "SwapFree:        1024000 kB\n"
        )
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=fake_meminfo)):
                swap = get_swap_total_bytes()
                self.assertEqual(swap, 1024000 * 1024)

    def test_tier_1_severely_constrained(self):
        # 512 MB RAM, 1 CPU core (e.g. Pi Zero 2W / Pi 3A+)
        ram = int(0.5 * 1024**3)
        profile = get_system_hardware_profile(
            override_ram_bytes=ram,
            override_cpu_cores=1,
            override_swap_bytes=100 * 1024 * 1024,
        )
        self.assertEqual(profile.tier, 1)
        self.assertEqual(profile.tier_name, "Constrained")
        self.assertEqual(profile.config_overrides["FFMPEG_VFSCALE"], "-2:720")
        self.assertEqual(profile.config_overrides["FFMPEG_VFSCALE_DAY"], "-2:720")
        self.assertEqual(profile.config_overrides["FFMPEG_BITRATE"], "2500k")
        self.assertEqual(profile.config_overrides["IMAGE_QUEUE_MAX"], 3)
        self.assertEqual(profile.config_overrides["IMAGE_QUEUE_MIN"], 1)
        self.assertEqual(profile.config_overrides["UPLOAD_WORKERS"], 1)
        # On < 1.0 GB, libcamera defaults to jpg to avoid DNG OOM
        self.assertIn("LIBCAMERA", profile.config_overrides)
        self.assertEqual(profile.config_overrides["LIBCAMERA"]["IMAGE_FILE_TYPE"], "jpg")

    def test_tier_1_constrained_1gb(self):
        # 1.0 GB RAM (e.g. Pi 4 1GB or Pi 3B+)
        ram = int(1.0 * 1024**3)
        profile = get_system_hardware_profile(
            override_ram_bytes=ram,
            override_cpu_cores=4,
            override_swap_bytes=100 * 1024 * 1024,
        )
        self.assertEqual(profile.tier, 1)
        self.assertEqual(profile.tier_name, "Constrained")
        self.assertEqual(profile.config_overrides["FFMPEG_VFSCALE"], "-2:720")
        self.assertEqual(profile.config_overrides["UPLOAD_WORKERS"], 1)
        # At 1.0 GB, DNG is permitted (not forced to jpg)
        self.assertNotIn("LIBCAMERA", profile.config_overrides)

    def test_tier_2_moderate_2gb(self):
        # 2.0 GB RAM (e.g. Pi 4 2GB)
        ram = int(2.0 * 1024**3)
        profile = get_system_hardware_profile(
            override_ram_bytes=ram,
            override_cpu_cores=4,
            override_swap_bytes=512 * 1024 * 1024,
        )
        self.assertEqual(profile.tier, 2)
        self.assertEqual(profile.tier_name, "Moderate")
        self.assertEqual(profile.config_overrides["FFMPEG_VFSCALE"], "-2:1080")
        self.assertEqual(profile.config_overrides["FFMPEG_VFSCALE_DAY"], "-2:1080")
        self.assertEqual(profile.config_overrides["FFMPEG_BITRATE"], "4000k")
        self.assertEqual(profile.config_overrides["IMAGE_QUEUE_MAX"], 5)
        self.assertEqual(profile.config_overrides["IMAGE_QUEUE_MIN"], 2)
        self.assertEqual(profile.config_overrides["UPLOAD_WORKERS"], 1)

    def test_tier_3_standard_4gb(self):
        # 4.0 GB RAM (e.g. Pi 4/5 4GB)
        ram = int(4.0 * 1024**3)
        profile = get_system_hardware_profile(
            override_ram_bytes=ram,
            override_cpu_cores=4,
            override_swap_bytes=2 * 1024 * 1024 * 1024,
        )
        self.assertEqual(profile.tier, 3)
        self.assertEqual(profile.tier_name, "Standard")
        self.assertEqual(profile.config_overrides["FFMPEG_VFSCALE"], "-2:1440")
        self.assertEqual(profile.config_overrides["FFMPEG_BITRATE"], "5000k")
        self.assertEqual(profile.config_overrides["IMAGE_QUEUE_MAX"], 8)
        self.assertEqual(profile.config_overrides["IMAGE_QUEUE_MIN"], 4)
        self.assertEqual(profile.config_overrides["UPLOAD_WORKERS"], 2)

    def test_tier_4_high_performance_8gb(self):
        # 8.0 GB RAM (e.g. Pi 5 8GB / x86_64 server)
        ram = int(8.0 * 1024**3)
        profile = get_system_hardware_profile(
            override_ram_bytes=ram,
            override_cpu_cores=8,
            override_swap_bytes=4 * 1024 * 1024 * 1024,
        )
        self.assertEqual(profile.tier, 4)
        self.assertEqual(profile.tier_name, "High Performance")
        self.assertEqual(profile.config_overrides["FFMPEG_VFSCALE"], "")
        self.assertEqual(profile.config_overrides["FFMPEG_BITRATE"], "6000k")
        self.assertEqual(profile.config_overrides["IMAGE_QUEUE_MAX"], 10)
        self.assertEqual(profile.config_overrides["IMAGE_QUEUE_MIN"], 5)
        self.assertEqual(profile.config_overrides["UPLOAD_WORKERS"], 3)

    def test_apply_hardware_profile_to_config(self):
        from indi_allsky.config import IndiAllSkyConfigUtil

        util = IndiAllSkyConfigUtil.__new__(IndiAllSkyConfigUtil)
        util._config = {
            "FFMPEG_VFSCALE": "",
            "FFMPEG_VFSCALE_DAY": "",
            "FFMPEG_VFSCALE_STARTRAIL": "",
            "FFMPEG_BITRATE": "5000k",
            "IMAGE_QUEUE_MAX": 10,
            "UPLOAD_WORKERS": 1,
            "LIBCAMERA": {
                "IMAGE_FILE_TYPE": "dng",
                "IMAGE_FILE_TYPE_DAY": "dng",
            },
        }

        # Apply Tier 1 (< 1GB) profile
        profile = get_system_hardware_profile(override_ram_bytes=int(0.5 * 1024**3))
        util._apply_hardware_profile(profile)

        self.assertEqual(util.config["FFMPEG_VFSCALE"], "-2:720")
        self.assertEqual(util.config["FFMPEG_BITRATE"], "2500k")
        self.assertEqual(util.config["IMAGE_QUEUE_MAX"], 3)
        self.assertEqual(util.config["LIBCAMERA"]["IMAGE_FILE_TYPE"], "jpg")


if __name__ == "__main__":
    unittest.main()
