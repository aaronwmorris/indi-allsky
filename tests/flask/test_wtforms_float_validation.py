import sys
import types
from unittest.mock import MagicMock
from importlib.machinery import ModuleSpec

class MockModule(types.ModuleType):
    def __init__(self, name):
        super().__init__(name)
        self.__path__ = []

    def __getattr__(self, name):
        val = MagicMock()
        setattr(self, name, val)
        return val

class MockImporter:
    mock_prefixes = (
        'astroalign',
        'astropy',
        'scipy',
        'skimage',
        'ccdproc',
        'ephem',
        'skyfield',
        'pyindi_client',
        'is_safe_url',
        'authlib',
        'pycurl',
    )

    def find_spec(self, fullname, path, target=None):
        if any(fullname == p or fullname.startswith(p + '.') for p in self.mock_prefixes):
            return ModuleSpec(fullname, self, is_package=True)
        return None

    def create_module(self, spec):
        mod = MockModule(spec.name)
        sys.modules[spec.name] = mod
        return mod

    def exec_module(self, module):
        pass

sys.meta_path.insert(0, MockImporter())

import os
from pathlib import Path

template_config = Path(__file__).resolve().parents[2] / 'flask.json_template'
os.environ['INDI_ALLSKY_FLASK_CONFIG'] = str(template_config)

import pytest
from flask import Flask
from wtforms.validators import ValidationError
from indi_allsky.flask.forms import (
    IndiAllskyConfigForm,
    NIGHT_SUN_ALT_DEG_validator,
    NIGHT_MOONMODE_ALT_DEG_validator,
    NIGHT_MOONMODE_PHASE_validator,
    STARTRAILS_SUN_ALT_THOLD_validator,
    STARTRAILS_MOON_ALT_THOLD_validator,
    STARTRAILS_MOON_PHASE_THOLD_validator,
)


@pytest.fixture
def test_app():
    app = Flask('test_app')
    app.config['SECRET_KEY'] = 'test-secret-key'
    app.config['WTF_CSRF_ENABLED'] = False
    return app


class DummyField:
    def __init__(self, data):
        self.data = data


class DummyForm:
    def __init__(self, moonmode_thold=True):
        self.STARTRAILS_MOONMODE_THOLD = DummyField(moonmode_thold)


def test_night_sun_alt_validator():
    form = DummyForm()
    # Valid values including zero and negatives
    for valid_val in [-90, -90.0, -6.0, 0, 0.0, 45.0, 90, 90.0]:
        NIGHT_SUN_ALT_DEG_validator(form, DummyField(valid_val))
        NIGHT_SUN_ALT_DEG_validator(form, DummyField(str(valid_val)))

    # Invalid range
    with pytest.raises(ValidationError, match='Sun altitude must be greater than -90'):
        NIGHT_SUN_ALT_DEG_validator(form, DummyField(-91))
    with pytest.raises(ValidationError, match='Sun altitude must be less than 90'):
        NIGHT_SUN_ALT_DEG_validator(form, DummyField(91))

    # Empty or non-numeric
    with pytest.raises(ValidationError, match='Please enter valid number'):
        NIGHT_SUN_ALT_DEG_validator(form, DummyField(None))
    with pytest.raises(ValidationError, match='Please enter valid number'):
        NIGHT_SUN_ALT_DEG_validator(form, DummyField(''))
    with pytest.raises(ValidationError, match='Please enter valid number'):
        NIGHT_SUN_ALT_DEG_validator(form, DummyField('invalid'))


def test_night_moonmode_alt_validator():
    form = DummyForm()
    for valid_val in [-90, -10.0, 0, 0.0, 5.0, 90.0, 91.0]:
        NIGHT_MOONMODE_ALT_DEG_validator(form, DummyField(valid_val))
        NIGHT_MOONMODE_ALT_DEG_validator(form, DummyField(str(valid_val)))

    with pytest.raises(ValidationError, match='Moon altitude must be greater than -90'):
        NIGHT_MOONMODE_ALT_DEG_validator(form, DummyField(-90.1))
    with pytest.raises(ValidationError, match='Moon altitude must be less than 91'):
        NIGHT_MOONMODE_ALT_DEG_validator(form, DummyField(91.5))

    with pytest.raises(ValidationError, match='Please enter valid number'):
        NIGHT_MOONMODE_ALT_DEG_validator(form, DummyField(''))


def test_startrails_sun_alt_validator():
    form = DummyForm()
    for valid_val in [-90, -15.0, 0, 0.0, 90.0]:
        STARTRAILS_SUN_ALT_THOLD_validator(form, DummyField(valid_val))
        STARTRAILS_SUN_ALT_THOLD_validator(form, DummyField(str(valid_val)))

    with pytest.raises(ValidationError, match='Sun altitude must be greater than -90'):
        STARTRAILS_SUN_ALT_THOLD_validator(form, DummyField(-95))
    with pytest.raises(ValidationError, match='Sun altitude must be less than 90'):
        STARTRAILS_SUN_ALT_THOLD_validator(form, DummyField(95))
    with pytest.raises(ValidationError, match='Please enter valid number'):
        STARTRAILS_SUN_ALT_THOLD_validator(form, DummyField(None))


def test_startrails_moon_alt_and_phase_when_camera_moonmode_enabled():
    # When STARTRAILS_MOONMODE_THOLD is True, custom moon thresholds are ignored and bypassed
    form = DummyForm(moonmode_thold=True)
    STARTRAILS_MOON_ALT_THOLD_validator(form, DummyField(None))
    STARTRAILS_MOON_ALT_THOLD_validator(form, DummyField(''))
    STARTRAILS_MOON_PHASE_THOLD_validator(form, DummyField(None))
    STARTRAILS_MOON_PHASE_THOLD_validator(form, DummyField(''))


def test_startrails_moon_alt_and_phase_when_camera_moonmode_disabled():
    # When STARTRAILS_MOONMODE_THOLD is False, custom moon thresholds must be valid
    form = DummyForm(moonmode_thold=False)

    for valid_val in [-90, 0, 0.0, 45.0, 91.0]:
        STARTRAILS_MOON_ALT_THOLD_validator(form, DummyField(valid_val))
    for valid_phase in [0, 0.0, 50.0, 100.0, 101.0]:
        STARTRAILS_MOON_PHASE_THOLD_validator(form, DummyField(valid_phase))

    with pytest.raises(ValidationError, match='Moon altitude must be less than 91'):
        STARTRAILS_MOON_ALT_THOLD_validator(form, DummyField(92))
    with pytest.raises(ValidationError, match='Moon phase must be less than 101'):
        STARTRAILS_MOON_PHASE_THOLD_validator(form, DummyField(105))
    with pytest.raises(ValidationError, match='Please enter valid number'):
        STARTRAILS_MOON_ALT_THOLD_validator(form, DummyField(''))


def test_float_formatting_no_leading_positive_sign():
    """Verify that formatting float fields without :+ conforms to HTML5 NumberInput requirements."""
    positive_val = 5.0
    zero_val = 0.0
    neg_val = -6.0

    # Format without +
    assert '{0:0.1f}'.format(positive_val) == '5.0'
    assert '{0:0.1f}'.format(zero_val) == '0.0'
    assert '{0:0.1f}'.format(neg_val) == '-6.0'

    assert '{0:0.3f}'.format(positive_val) == '5.000'
    assert '{0:0.3f}'.format(zero_val) == '0.000'
    assert '{0:0.3f}'.format(neg_val) == '-6.000'
