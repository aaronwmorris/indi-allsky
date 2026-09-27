"""Run the system notification JavaScript regressions through pytest."""

import shutil
import subprocess
from pathlib import Path


def test_notification_polling():
    node = shutil.which("node")
    assert node is not None, "Node.js is required to run the notification polling tests"

    result = subprocess.run(
        [node, "--test", str(Path(__file__).with_name("notification_polling.test.cjs"))],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
