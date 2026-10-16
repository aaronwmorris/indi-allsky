"""Run the gallery panorama toolbar regression through pytest."""

import shutil
import subprocess
from pathlib import Path


def test_gallery_panorama_toolbar():
    node = shutil.which('node')
    assert node is not None, 'Node.js is required to run the gallery toolbar test'
    result = subprocess.run(
        [node, '--test', str(Path(__file__).with_name('gallery_panorama.test.cjs'))],
        capture_output=True, text=True, encoding='utf-8', timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
