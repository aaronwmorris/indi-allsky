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

import copy
import json
import pytest
from flask import Flask
from cryptography.fernet import Fernet
from indi_allsky.flask.forms import IndiAllskyConfigForm
from indi_allsky.config import IndiAllSkyConfigBase, IndiAllSkyConfig
from indi_allsky import constants


@pytest.fixture
def flask_app():
    app = Flask('indi_allsky_test')
    app.config['SECRET_KEY'] = 'test-secret'
    app.config['PASSWORD_KEY'] = Fernet.generate_key().decode()
    app.config['WTF_CSRF_ENABLED'] = False
    return app


def _flatten_config(d, prefix=''):
    items = {}
    for k, v in d.items():
        if k.endswith('_comment'):
            continue
        key = f'{prefix}__{k}' if prefix else k
        if isinstance(v, dict):
            items.update(_flatten_config(v, key))
        elif isinstance(v, list):
            if key in ('ADU_ROI', 'SQM_ROI', 'IMAGE_CROP_ROI'):
                items[f'{key}_X1'] = v[0] if len(v) > 0 else 0
                items[f'{key}_Y1'] = v[1] if len(v) > 1 else 0
                items[f'{key}_X2'] = v[2] if len(v) > 2 else 0
                items[f'{key}_Y2'] = v[3] if len(v) > 3 else 0
            elif key == 'FITSHEADERS':
                for i in range(5):
                    items[f'FITSHEADERS__{i}__KEY'] = v[i][0] if i < len(v) else ''
                    items[f'FITSHEADERS__{i}__VAL'] = v[i][1] if i < len(v) else ''
            elif key.endswith('_COLOR') or key.endswith('_BORDER') or key == 'IMAGE_BORDER__COLOR':
                items[key] = ','.join(str(x) for x in v)
            elif key == 'YOUTUBE__TAGS':
                items['YOUTUBE__TAGS_STR'] = ', '.join(v)
            else:
                items[key] = json.dumps(v)
        else:
            items[key] = v
    return items


def _get_dummy_form_data():
    cfg = IndiAllSkyConfigBase._base_config
    data = _flatten_config(cfg)
    data['ADMIN_NETWORKS_FLASK'] = ''
    data['RELOAD_ON_SAVE'] = False
    data['CONFIG_NOTE'] = ''
    data['YOUTUBE__REDIRECT_URI'] = ''
    data['FILETRANSFER__LIBCURL_OPTIONS'] = '{}'
    data['INDI_CONFIG_DEFAULTS'] = '{}'
    data['INDI_CONFIG_DAY'] = '{}'

    # Cast string representations for select fields
    for k, v in list(data.items()):
        if k in (
            'CCD_BIT_DEPTH',
            'ADU_FOV_DIV',
            'SQM_FOV_DIV',
            'CCD_CONFIG__AUTO_GAIN_LEVELS',
            'TEMP_SENSOR__SI7021_HEATER_LEVEL_NIGHT',
            'TEMP_SENSOR__SI7021_HEATER_LEVEL_DAY',
            'TEMP_SENSOR__TSL2561_GAIN_NIGHT',
            'TEMP_SENSOR__TSL2561_GAIN_DAY',
        ):
            data[k] = str(v)

    return data


def test_i2c_sensor_validation_without_pin(flask_app):
    with flask_app.test_request_context():
        data = _get_dummy_form_data()
        data['TEMP_SENSOR__A_CLASSNAME'] = 'blinka_temp_sensor_bme280_i2c'
        data['TEMP_SENSOR__A_PIN_1'] = ''  # I2C sensors do not require PIN_1

        form = IndiAllskyConfigForm(data=data)
        form.validate()

        # Ensure validate() does not fail on PIN_1
        assert not form.TEMP_SENSOR__A_PIN_1.errors
        assert not form.TEMP_SENSOR__A_CLASSNAME.errors


def test_spi_and_dht_sensor_validation_requires_pin(flask_app):
    with flask_app.test_request_context():
        data = _get_dummy_form_data()
        data['TEMP_SENSOR__A_CLASSNAME'] = 'blinka_temp_sensor_bme280_spi'
        data['TEMP_SENSOR__A_PIN_1'] = ''

        form = IndiAllskyConfigForm(data=data)
        form.validate()
        assert 'PIN must be defined' in form.TEMP_SENSOR__A_PIN_1.errors


def test_slot_choices_instance_isolation(flask_app):
    with flask_app.test_request_context():
        data1 = _get_dummy_form_data()
        data1['TEMP_SENSOR__A_CLASSNAME'] = 'blinka_temp_sensor_bme280_i2c'
        data1['TEMP_SENSOR__A_LABEL'] = 'Custom Label 1'
        data1['TEMP_SENSOR__A_USER_VAR_SLOT'] = 'sensor_user_10'

        form1 = IndiAllskyConfigForm(data=data1)

        data2 = _get_dummy_form_data()
        data2['TEMP_SENSOR__A_CLASSNAME'] = 'blinka_temp_sensor_sht3x_i2c'
        data2['TEMP_SENSOR__A_LABEL'] = 'Custom Label 2'
        data2['TEMP_SENSOR__A_USER_VAR_SLOT'] = 'sensor_user_20'

        form2 = IndiAllskyConfigForm(data=data2)

        # Form 1 should reflect BME280 in slot 10
        assert 'BME280' in form1.SENSOR_SLOT_choices['User Sensors'][10][1]
        assert 'Custom Label 1' in form1.SENSOR_SLOT_choices['User Sensors'][10][1]

        # Form 2 slot 10 should be clean default User Slot 10
        assert form2.SENSOR_SLOT_choices['User Sensors'][10][1] == 'User Slot 10'
        # Form 2 should reflect SHT3x in slot 20
        assert 'SHT3x' in form2.SENSOR_SLOT_choices['User Sensors'][20][1]

        # Class level SENSOR_SLOT_choices must remain unmutated
        assert IndiAllskyConfigForm.SENSOR_SLOT_choices['User Sensors'][10][1] == 'User Slot 10'
        assert IndiAllskyConfigForm.SENSOR_SLOT_choices['User Sensors'][20][1] == 'User Slot 20'


def test_slot_bounds_and_overlap_validation(flask_app):
    with flask_app.test_request_context():
        # Valid non-overlapping slots
        data = _get_dummy_form_data()
        data['TEMP_SENSOR__A_CLASSNAME'] = 'blinka_temp_sensor_bme280_i2c'  # count: 4
        data['TEMP_SENSOR__A_USER_VAR_SLOT'] = 'sensor_user_10'             # 10..13
        data['TEMP_SENSOR__B_CLASSNAME'] = 'blinka_temp_sensor_sht3x_i2c'   # count: 3
        data['TEMP_SENSOR__B_USER_VAR_SLOT'] = 'sensor_user_20'             # 20..22

        form = IndiAllskyConfigForm(data=data)
        form.validate()
        assert not form.TEMP_SENSOR__A_USER_VAR_SLOT.errors
        assert not form.TEMP_SENSOR__B_USER_VAR_SLOT.errors

        # Overlapping slots
        data_overlap = _get_dummy_form_data()
        data_overlap['TEMP_SENSOR__A_CLASSNAME'] = 'blinka_temp_sensor_bme280_i2c'  # 10..13
        data_overlap['TEMP_SENSOR__A_USER_VAR_SLOT'] = 'sensor_user_10'
        data_overlap['TEMP_SENSOR__B_CLASSNAME'] = 'blinka_temp_sensor_sht3x_i2c'   # 12..14 (overlaps 12, 13)
        data_overlap['TEMP_SENSOR__B_USER_VAR_SLOT'] = 'sensor_user_12'

        form_overlap = IndiAllskyConfigForm(data=data_overlap)
        form_overlap.validate()
        assert any('Overlapping slots' in err for err in form_overlap.TEMP_SENSOR__A_USER_VAR_SLOT.errors)
        assert any('Overlapping slots' in err for err in form_overlap.TEMP_SENSOR__B_USER_VAR_SLOT.errors)

        # Slot overflow (BME280 starting at slot 58 -> 58, 59, 60, 61 > 59)
        data_overflow = _get_dummy_form_data()
        data_overflow['TEMP_SENSOR__A_CLASSNAME'] = 'blinka_temp_sensor_bme280_i2c'
        data_overflow['TEMP_SENSOR__A_USER_VAR_SLOT'] = 'sensor_user_58'

        form_overflow = IndiAllskyConfigForm(data=data_overflow)
        form_overflow.validate()
        assert any('Not enough sensor slots' in err for err in form_overflow.TEMP_SENSOR__A_USER_VAR_SLOT.errors)


def test_gpio_hardware_error_resilience(flask_app, monkeypatch):
    """Ensure FileNotFoundError/OSError raised by lgpio/RPi.GPIO during validation is caught cleanly."""
    with flask_app.test_request_context():
        data = _get_dummy_form_data()
        data['DEW_HEATER__CLASSNAME'] = 'rpigpio_dew_heater_gpio'
        data['DEW_HEATER__PIN_1'] = '18'
        data['FAN__CLASSNAME'] = 'rpigpio_fan_gpio'
        data['FAN__PIN_1'] = '19'
        data['MANUAL_GPIO__A_CLASSNAME'] = 'rpigpio_manual_gpio'
        data['MANUAL_GPIO__A_PIN_1'] = '20'

        # Simulate lgpio FileNotFoundError on import RPi.GPIO
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == 'RPi.GPIO':
                raise FileNotFoundError(2, "No such file or directory: '.lgd-nfy-3'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, '__import__', mock_import)

        form = IndiAllskyConfigForm(data=data)
        # Should not raise FileNotFoundError
        form.validate()
        assert any('GPIO hardware error' in err for err in form.DEW_HEATER__CLASSNAME.errors)
        assert any('GPIO hardware error' in err for err in form.FAN__CLASSNAME.errors)
        assert any('GPIO hardware error' in err for err in form.MANUAL_GPIO__A_CLASSNAME.errors)
