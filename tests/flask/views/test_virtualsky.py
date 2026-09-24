import json
import math
from pathlib import Path
import shutil
import subprocess

import numpy
import ephem
import pytest

from indi_allsky.lens_solver.projection import predictAltAz, projectToPixels, precessCatalog, cameraAltAz


ROOT = Path(__file__).resolve().parents[3]


def run_node(*args, input=None):
    node = shutil.which('node')
    assert node, 'Node.js is required for the VirtualSky JavaScript tests'
    result = subprocess.run([node, *args], cwd=ROOT, input=input,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_virtualsky_javascript():
    run_node('--test', 'tests/flask/views/virtualsky.test.cjs', 'tests/flask/views/virtualsky_refresh.test.cjs')


@pytest.mark.parametrize('date', ['2022-10-21T18:00:00Z', '2022-11-05T18:00:00Z',
                                  '2022-12-15T00:00:00Z', '2026-09-23T02:36:45Z'])
def test_planet_positions_against_independent_ephemeris(date):
    # Cover the original jumping-Jupiter dates and the observed 2026 offset.
    rows = json.loads(run_node('-e', '''
const {makeSky, loadPlanets} = require('./tests/flask/views/virtualsky_harness.cjs');
console.log(JSON.stringify(['virtualsky.js', 'virtualsky.min.js'].flatMap(asset => {
    const sky = loadPlanets(makeSky({clock: new Date(process.argv[1])}, asset));
    return sky.planets.map(p => ({asset, name: p[0], ...sky.interpolate(sky.times.JD, p[2])}));
})));
''', date))
    planets = dict(Me=ephem.Mercury, V=ephem.Venus, Ma=ephem.Mars, J=ephem.Jupiter,
                   S=ephem.Saturn, U=ephem.Uranus, N=ephem.Neptune)
    assert len(rows) == 2*len(planets)
    for row in rows:
        body = planets[row['name']]()
        body.compute(date.replace('T', ' ').replace('Z', ''))
        # VirtualSky renders these coordinates directly in the equinox of date.
        error = math.degrees(ephem.separation(
            (math.radians(row['ra']), math.radians(row['dec'])), (body.g_ra, body.g_dec)))
        # The bundled orbital model is approximate; catch offsets and wrap jumps
        # without claiming the precision of a modern numerical ephemeris.
        assert error < 0.25, (date, row, error)


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
const {makeSky} = require('./tests/flask/views/virtualsky_harness.cjs');
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
