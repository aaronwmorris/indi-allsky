import json

import numpy as np
import pytest

from indi_allsky.lens_solver.projection import precessCatalog
from tests.flask.test_virtualsky import run_node
from tests.flask.test_virtualsky_requests import endpoint, VALUES


def test_browser_precession_and_inverse_match_solver():
    catalog = np.array([[0, 90, 1], [359.99, -90, 2], [0, 0, 3], [180, 45, 4.]])
    cases = []
    for timestamp in (0, 946728000, 1788731972, 4102444800):
        cases.append(dict(timestamp=timestamp, expected=precessCatalog(catalog, timestamp).tolist()))
    run_node('-e', '''
const assert = require('node:assert/strict');
const {makeSky} = require('./tests/flask/virtualsky_harness.cjs');
const input = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
function xyz(p) {return [Math.cos(p.dec)*Math.cos(p.ra), Math.cos(p.dec)*Math.sin(p.ra), Math.sin(p.dec)];}
for (const asset of ['virtualsky.js','virtualsky.min.js']) {
  const sky = makeSky({precession:true},asset);
  for (const c of input.cases) {
    sky.setClock(new Date(c.timestamp*1000));
    input.catalog.forEach((star,i) => {
      const original = {ra:star[0]*Math.PI/180,dec:star[1]*Math.PI/180};
      const actual = sky.precessEquatorial(original.ra,original.dec);
      const expected = {ra:c.expected[i][0]*Math.PI/180,dec:c.expected[i][1]*Math.PI/180};
      assert.ok(Math.hypot(...xyz(actual).map((v,j)=>v-xyz(expected)[j])) < 1e-12);
      const inverse = sky.precessEquatorial(actual.ra,actual.dec,true);
      assert.ok(Math.hypot(...xyz(inverse).map((v,j)=>v-xyz(original)[j])) < 1e-12);
    });
  }
}
''', input=json.dumps(dict(catalog=catalog.tolist(), cases=cases)))


@pytest.mark.parametrize('value', [True, False])
def test_save_preserves_coordinate_convention(endpoint, value):
    app, view, _, saved = endpoint
    with app.test_request_context(json=dict(VALUES, action='save', PRECESSION=value)):
        assert view.dispatch_request().get_json()['success']
    assert saved[-1]['VIRTUALSKY']['PRECESSION'] is value


@pytest.mark.parametrize('value', ['false', 1, None, []])
def test_invalid_coordinate_convention_is_rejected(endpoint, value):
    app, view, _, saved = endpoint
    with app.test_request_context(json=dict(VALUES, action='save', PRECESSION=value)):
        assert view.dispatch_request()[1] == 400
    assert not saved


def test_legacy_save_preserves_existing_coordinate_convention(endpoint):
    app, view, _, saved = endpoint
    view.indi_allsky_config['VIRTUALSKY']['PRECESSION'] = True
    with app.test_request_context(json=dict(VALUES, action='save')):
        assert view.dispatch_request().get_json()['success']
    assert saved[-1]['VIRTUALSKY']['PRECESSION'] is True
