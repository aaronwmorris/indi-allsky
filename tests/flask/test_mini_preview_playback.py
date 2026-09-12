"""Run the mini-timelapse preview JavaScript regressions through pytest."""

import shutil
import subprocess
from pathlib import Path


def test_mini_preview_playback():
    node = shutil.which("node")
    assert node is not None, "Node.js is required to run the mini preview tests"

    result = subprocess.run(
        [node, "--test", str(Path(__file__).with_name("mini_preview_playback.test.cjs"))],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
