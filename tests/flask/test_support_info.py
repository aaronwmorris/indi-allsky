"""Support Info Unicode output and browser error regressions, without camera services."""

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import unittest


class SupportInfoTests(unittest.TestCase):
    def test_python_output_uses_utf8_with_inherited_latin1(self):
        root = Path(__file__).resolve().parents[2]
        script = (root / 'misc/support_info.sh').read_text(encoding='utf-8')
        # Exercise the real script's environment setup without probing host hardware.
        prologue = script.split('function catch_error()', 1)[0]
        dump = "import json; print(json.dumps({'description': '\\U0001f30c Caf\\u00e9'}, ensure_ascii=False))"
        result = subprocess.run(
            ['bash', '-c', prologue + '\n' + shlex.join([sys.executable, '-c', dump])],
            env=dict(os.environ, PYTHONIOENCODING='latin-1', PYTHONUTF8='0', LC_ALL='C'),
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        self.assertEqual(json.loads(result.stdout.decode('utf-8')), {'description': '🌌 Café'})

    def test_browser_support_info(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node.js is required to run the Support Info browser tests')
        result = subprocess.run(
            [node, '--test', str(Path(__file__).with_name('support_info.test.cjs'))],
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
