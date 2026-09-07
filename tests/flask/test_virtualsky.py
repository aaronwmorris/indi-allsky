import json
from pathlib import Path
import shutil
import subprocess

import numpy
import pytest

from indi_allsky.lens_solver.projection import predictAltAz, projectToPixels


ROOT = Path(__file__).resolve().parents[2]


def run_node(*args, input=None):
    node = shutil.which('node')
    assert node, 'Node.js is required for the VirtualSky JavaScript tests'
    result = subprocess.run([node, *args], cwd=ROOT, input=input,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_virtualsky_javascript():
    run_node('--test', 'tests/flask/virtualsky.test.cjs', 'tests/flask/virtualsky_refresh.test.cjs')


@pytest.mark.parametrize('altitude,heading', [(90, 215), (54, 0), (20, 120), (0, 350)])
def test_browser_and_solver_agree_across_timestamps(altitude, heading):
    catalog = numpy.array([[37.955, 89.26, 2], [79.172, 46, 0.1],
                           [213.915, 19.182, 0.0], [101.287, -16.72, -1.4]])
    params = [200, 2.0, -1.5, 1000, 0, 0]
    cases = []
    for timestamp in [1770000000, 1770014400, 1770043200]:
        alt, az = predictAltAz(catalog, 46.51+params[1], 8+params[2], timestamp)
        x, y = projectToPixels(alt, az, params, 1000, 1000,
                              lens_altitude=altitude, pointing_azimuth=heading)
        for star, expected_x, expected_y in zip(catalog, x, y):
            cases.append(dict(ra=float(star[0]), dec=float(star[1]),
                              timestamp=timestamp, x=expected_x, y=expected_y))
    payload = dict(cases=cases, altitude=altitude, heading=heading)
    run_node('-e', '''
const assert = require('node:assert/strict');
const {makeSky} = require('./tests/flask/virtualsky_harness.cjs');
const input = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
for (const asset of ['virtualsky.js', 'virtualsky.min.js']) {
  for (const c of input.cases) {
    const sky = makeSky({fisheye_altitude: input.altitude, fisheye_azimuth: input.heading,
      az: 20, latitude: 48.51, longitude: 6.5, clock: new Date(c.timestamp*1000)}, asset);
    const p = sky.radec2xy(c.ra*Math.PI/180, c.dec*Math.PI/180);
    if (Math.hypot(c.x-500, c.y-500) > 500 && input.altitude !== 90) {
      assert.ok(Number.isNaN(p.x));
    } else {
      // Existing JS/astropy sidereal-time approximations differ slightly.
      assert.ok(Math.hypot(p.x-c.x, p.y-c.y) < 0.1, JSON.stringify({c,p}));
    }
  }
}
''', input=json.dumps(payload))
