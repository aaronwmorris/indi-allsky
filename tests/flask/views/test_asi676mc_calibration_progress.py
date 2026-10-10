"""Run calibration progress regressions through the shared pytest suite."""

import shutil
import subprocess
from pathlib import Path


def test_asi676mc_calibration_progress():
    node = shutil.which('node')
    assert node is not None, 'Node.js is required for calibration progress tests'
    result = subprocess.run(
        [node, '--test', str(Path(__file__).with_name('asi676mc_calibration_progress.test.cjs'))],
        capture_output=True, text=True, encoding='utf-8', timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
