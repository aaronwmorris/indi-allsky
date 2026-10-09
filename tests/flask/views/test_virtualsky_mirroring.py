"""Run browser regressions through the shared pytest suite."""
import ast
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import flask
from flask_wtf import FlaskForm
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from wtforms import BooleanField, FloatField, IntegerField
from wtforms.widgets import NumberInput
from wtforms.validators import NumberRange


ROOT = Path(__file__).resolve().parents[3]


def test_virtualsky_mirroring():
    node = shutil.which('node')
    assert node is not None, 'Node.js is required to run the VirtualSky tests'
    result = subprocess.run(
        [node, '--test', str(Path(__file__).with_name('virtualsky_mirroring.test.cjs'))],
        capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('flip_h,flip_v', [(False, False), (True, False), (False, True), (True, True)])
def test_saved_orientation_flows_through_camera_metadata_to_page(flip_h, flip_v):
    # Execute the actual metadata assignments and page defaults without importing
    # camera drivers or starting the Flask application's database services.
    from indi_allsky.lens_solver import applySolvedValuesToConfig

    config = {}
    values = dict(AZIMUTH_ANGLE=37.5, LATITUDE_OFFSET=0, LONGITUDE_OFFSET=0,
                  IMAGE_CIRCLE_DIAMETER=1700, OFFSET_X=25, OFFSET_Y=-12,
                  FLIP_H=flip_h, FLIP_V=flip_v)
    applySolvedValuesToConfig(config, values)
    metadata = {'data': {}}
    tree = ast.parse((ROOT / 'indi_allsky/capture.py').read_text(encoding='utf-8'))
    assignments = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Subscript) and ast.unparse(t).startswith("camera_metadata['data']['vs_flip_")
                           for t in n.targets)]
    assert len(assignments) == 2
    exec(compile(ast.Module(body=assignments, type_ignores=[]), 'capture.py', 'exec'),
         {'self': SimpleNamespace(config=config), 'camera_metadata': metadata})
    tree = ast.parse((ROOT / 'indi_allsky/flask/views.py').read_text(encoding='utf-8'))
    view = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'VirtualSkyView')
    data = next(n.value for n in ast.walk(view) if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'data' for t in n.targets))
    for camera_data, expected in [(metadata['data'], (flip_h, flip_v)), ({}, (False, False))]:
        defaults = eval(compile(ast.Expression(data), 'views.py', 'eval'),
                        {'self': SimpleNamespace(camera=SimpleNamespace(az=37.5, data=camera_data))})
        assert (defaults['FLIP_H'], defaults['FLIP_V']) == expected
        form_tree = ast.parse((ROOT / 'indi_allsky/flask/forms.py').read_text(encoding='utf-8'))
        form = next(n for n in form_tree.body if isinstance(n, ast.ClassDef)
                    and n.name == 'IndiAllskyVirtualSkyHelperForm')
        namespace = dict(FlaskForm=FlaskForm, BooleanField=BooleanField, FloatField=FloatField,
                         IntegerField=IntegerField, NumberInput=NumberInput, NumberRange=NumberRange)
        exec(compile(ast.Module(body=[form], type_ignores=[]), 'forms.py', 'exec'), namespace)
        templates = Environment(autoescape=True, loader=ChoiceLoader([
            DictLoader({'base.html': '{% block content %}{% endblock %}'}),
            FileSystemLoader(ROOT / 'indi_allsky/flask/templates')]))
        app = flask.Flask(__name__)
        app.config['WTF_CSRF_ENABLED'] = False
        with app.test_request_context():
            html = templates.get_template('virtualsky.html').render(
                form_virtualsky=namespace['IndiAllskyVirtualSkyHelperForm'](data=defaults),
                login_disabled=True, current_user=SimpleNamespace(is_authenticated=False, is_admin=False),
                url_for=lambda *args, **kwargs: '/unused')
        for key, checked in zip(('FLIP_H', 'FLIP_V'), expected):
            tag = next(t for t in html.split('<input') if f'id="{key}"' in t).split('>')[0]
            assert ('checked' in tag) is checked


def test_mirrored_tilt_projection_agrees_with_browser():
    import json
    from itertools import product
    import numpy as np
    from indi_allsky.lens_solver.projection import projectToPixels, cameraAltAz
    from tests.flask.views.test_virtualsky import run_node

    cases = []
    alt, az = np.radians([15, 40, 75]), np.radians([30, 160, 310])
    for altitude, radial, h, v in product((20, 54, 90), (-0.5, 0.08, 0.5), (False, True), (False, True)):
        params = [200, 0, 0, 1000, 0, 0, radial]
        x, y = projectToPixels(alt, az, params, 1000, 1000,
            lens_altitude=altitude, pointing_azimuth=123, flip_h=h, flip_v=v)
        front = cameraAltAz(alt, az, altitude, 123)[0] >= 0
        cases.append(dict(altitude=altitude, radial=radial, flip_h=h, flip_v=v,
            points=[dict(alt=a, az=z, x=px, y=py, front=bool(f)) for a, z, px, py, f in zip(alt, az, x, y, front)]))
    run_node('-e', r"""
const assert = require('node:assert/strict');
const {makeSky} = require('./tests/flask/views/virtualsky_harness.cjs');
const cases = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
for (const asset of ['virtualsky.js', 'virtualsky.min.js']) for (const c of cases) {
    const sky = makeSky({fisheye_altitude: c.altitude, fisheye_azimuth: 123, az: 20,
        fisheye_radial: c.radial, flip_h: c.flip_h, flip_v: c.flip_v}, asset);
    for (const p of c.points) {
        const q = sky.azel2xy(p.az-sky.az_off*Math.PI/180, p.alt, 1000, 1000);
        if (p.front) assert.ok(Math.hypot(q.x-p.x, q.y-p.y) < 1e-7, JSON.stringify({c,p,q}));
        else assert.ok(Number.isNaN(q.x));
    }
}
""", input=json.dumps(cases))
