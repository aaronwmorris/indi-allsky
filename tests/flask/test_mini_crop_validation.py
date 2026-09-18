"""Keep hidden panorama controls from blocking standard mini-timelapses (#3164)."""

from html.parser import HTMLParser
from pathlib import Path

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from wtforms import Form, HiddenField, SelectField, StringField


class MiniForm(Form):
    CAMERA_ID = HiddenField()
    IMAGE_ID = HiddenField()
    PRE_SECONDS_SELECT = SelectField()
    POST_SECONDS_SELECT = SelectField()
    FRAMERATE_SELECT = SelectField()
    BITRATE_SELECT = SelectField()
    NOTE = StringField()


class CropInputs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inputs = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input' and attrs.get('id') in ('CROP_WIDTH', 'CROP_HEIGHT'):
            self.inputs[attrs['id']] = attrs


@pytest.mark.parametrize(
    'enabled,width,height,expected',
    [
        pytest.param(False, 0, 0, (2, 2), id='panoramas-disabled'),
        pytest.param(True, 0, 0, (2, 2), id='panoramas-enabled-but-missing'),
        pytest.param(True, 1, 1, (2, 2), id='dimensions-below-minimum'),
        pytest.param(True, 2, 2, (2, 2), id='minimum-panorama'),
        pytest.param(True, 4096, 1024, (4096, 1024), id='existing-panorama'),
    ],
)
def test_rendered_crop_defaults_satisfy_browser_constraints(enabled, width, height, expected):
    templates = Path(__file__).resolve().parents[2] / 'indi_allsky/flask/templates'
    env = Environment(loader=ChoiceLoader([
        DictLoader({'base.html': '{% block content %}{% endblock %}'}),
        FileSystemLoader(templates),
    ]))
    html = env.get_template('mini_generate.html').render(
        panorama_enabled=enabled,
        panorama={'available': width >= 2 and height >= 2, 'width': width, 'height': height},
        panorama_suggestions=[],
        form_mini_timelapse=MiniForm(),
        url_for=lambda *args, **kwargs: '#',
    )
    parser = CropInputs()
    parser.feed(html)
    assert set(parser.inputs) == {'CROP_WIDTH', 'CROP_HEIGHT'}
    for field, expected_value in zip(('CROP_WIDTH', 'CROP_HEIGHT'), expected):
        attrs = parser.inputs[field]
        value = int(attrs['value'])
        assert attrs['type'] == 'number'
        assert int(attrs['min']) == 2
        assert int(attrs['step']) == 2
        assert value >= int(attrs['min']), f'{field} would block form submission'
        assert (value - int(attrs['min'])) % int(attrs['step']) == 0
        assert value == expected_value
