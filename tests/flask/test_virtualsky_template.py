"""Render the real controls to check permissions without camera/database services."""
import ast
from pathlib import Path
from types import SimpleNamespace

import flask
from flask_wtf import FlaskForm
from jinja2 import DictLoader, Environment, FileSystemLoader, ChoiceLoader
import pytest
from wtforms import BooleanField, FloatField, IntegerField
from wtforms.validators import NumberRange
from wtforms.widgets import NumberInput


@pytest.mark.parametrize('login_disabled,authenticated,admin,allowed', [
    (False, False, False, False),
    (False, True, False, False),
    (False, True, True, True),
    (True, False, False, True),
    (True, True, False, True),
])
def test_calibration_actions_require_config_save_access(login_disabled, authenticated, admin, allowed):
    root = Path(__file__).resolve().parents[2] / 'indi_allsky/flask'
    tree = ast.parse((root / 'forms.py').read_text(encoding='utf-8'))
    form_node = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                     and n.name == 'IndiAllskyVirtualSkyHelperForm')
    namespace = dict(FlaskForm=FlaskForm, BooleanField=BooleanField, FloatField=FloatField,
                     IntegerField=IntegerField, NumberRange=NumberRange, NumberInput=NumberInput)
    exec(compile(ast.Module(body=[form_node], type_ignores=[]), 'forms.py', 'exec'), namespace)
    templates = Environment(autoescape=True, loader=ChoiceLoader([
        DictLoader({'base.html': '{% block content %}{% endblock %}'}),
        FileSystemLoader(root / 'templates'),
    ]))
    app = flask.Flask(__name__)
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_request_context():
        html = templates.get_template('virtualsky.html').render(
            form_virtualsky=namespace['IndiAllskyVirtualSkyHelperForm'](),
            camera_altitude=90, login_disabled=login_disabled,
            current_user=SimpleNamespace(is_authenticated=authenticated, is_admin=admin),
            url_for=lambda *args, **kwargs: '/unused')
    for control in ['lens_solve', 'lens_solve_spinner', 'lens_save', 'lens_reload_on_save']:
        assert (f'id="{control}"' in html) is allowed
    # Viewing, adjusting and downloading the overlay remain available to everyone.
    for control in ['lens_altitude', 'POINTING_AZIMUTH', 'AZIMUTH_ANGLE', 'LATITUDE_OFFSET',
                    'LONGITUDE_OFFSET', 'IMAGE_CIRCLE_DIAMETER', 'OFFSET_X', 'OFFSET_Y',
                    'MAGNITUDE', 'SHOWSTARS', 'download_overlay', 'download_map']:
        assert f'id="{control}"' in html
