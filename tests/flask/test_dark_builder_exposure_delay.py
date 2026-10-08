"""Run the builder cooldown controls through the shared pytest suite."""

import shutil
import subprocess
from pathlib import Path


def test_dark_builder_exposure_delay():
    node = shutil.which('node')
    assert node is not None, 'Node.js is required to run the dark builder tests'
    result = subprocess.run(
        [node, '--test', str(Path(__file__).with_name('dark_exposure_delay.test.cjs'))],
        capture_output=True, text=True, encoding='utf-8', timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
