import json
from pathlib import Path
import shutil
import subprocess

import numpy
import pytest

from indi_allsky.lens_solver.projection import predictAltAz, projectToPixels, precessCatalog, cameraAltAz


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
@pytest.mark.parametrize('precession', [False, True])
@pytest.mark.parametrize('radial', [0, -0.5, 0.08, 0.5, 1])
def test_browser_and_solver_agree_across_timestamps(altitude, heading, precession, radial):
    catalog = numpy.array([[37.955, 89.26, 2], [79.172, 46, 0.1],
                           [213.915, 19.182, 0.0], [101.287, -16.72, -1.4]])
    params = [200, 2.0, -1.5, 1000, 0, 0, radial]
    cases = []
    for timestamp in [1770000000, 1770014400, 1770043200]:
        stars = precessCatalog(catalog, timestamp) if precession else catalog
        alt, az = predictAltAz(stars, 46.51+params[1], 8+params[2], timestamp)
        x, y = projectToPixels(alt, az, params, 1000, 1000,
                              lens_altitude=altitude, pointing_azimuth=heading)
        front = cameraAltAz(alt, az, altitude, heading)[0] >= 0
        for star, expected_x, expected_y, in_front in zip(catalog, x, y, front):
            cases.append(dict(ra=float(star[0]), dec=float(star[1]),
                              timestamp=timestamp, x=expected_x, y=expected_y, front=bool(in_front)))
    payload = dict(cases=cases, altitude=altitude, heading=heading, precession=precession, radial=radial)
    run_node('-e', '''
const assert = require('node:assert/strict');
const {makeSky} = require('./tests/flask/virtualsky_harness.cjs');
const input = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
for (const asset of ['virtualsky.js', 'virtualsky.min.js']) {
  for (const c of input.cases) {
    const sky = makeSky({fisheye_altitude: input.altitude, fisheye_azimuth: input.heading,
      az: 20, latitude: 48.51, longitude: 6.5, precession: input.precession, fisheye_radial: input.radial,
      clock: new Date(c.timestamp*1000)}, asset);
    const p = sky.radec2xy(c.ra*Math.PI/180, c.dec*Math.PI/180);
    if (!c.front && input.altitude !== 90) {
      assert.ok(Number.isNaN(p.x));
    } else {
      // Existing JS/astropy sidereal-time approximations differ slightly.
      assert.ok(Math.hypot(p.x-c.x, p.y-c.y) < 0.1, JSON.stringify({c,p}));
      if (c.front && Math.hypot(p.x-500, p.y-500) < 500) {
        const recovered = sky.xy2radec(p.x,p.y);
        assert.ok(Math.abs(recovered.dec-c.dec*Math.PI/180) < 1e-8);
        assert.ok(Math.abs(Math.sin(recovered.ra-c.ra*Math.PI/180)) < 1e-8);
      }
    }
  }
}
''', input=json.dumps(payload))
