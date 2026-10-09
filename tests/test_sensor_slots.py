import ast
import copy
import itertools
import logging
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from wtforms import Form, SelectField, StringField
from wtforms.validators import DataRequired, ValidationError

from indi_allsky import constants
from indi_allsky import sensor_slots
from indi_allsky.devices import sensors
from indi_allsky.devices.exceptions import SensorException


ROOT = Path(__file__).resolve().parents[1]


def tree(path):
    return ast.parse((ROOT / path).read_text(encoding='utf-8'))


def owner(path, name):
    return next(node for node in tree(path).body if isinstance(node, ast.ClassDef) and node.name == name)


def method(path, name, class_name):
    return copy.deepcopy(next(node for node in owner(path, class_name).body
                              if isinstance(node, ast.FunctionDef) and node.name == name))


def execute(nodes, namespace):
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    exec(compile(module, 'production-sensor-slots', 'exec'), namespace)
    return namespace


@pytest.fixture
def sensor_form():
    source = tree('indi_allsky/flask/forms.py')
    cls = owner('indi_allsky/flask/forms.py', 'IndiAllskyConfigForm')
    validators = {name for node in cls.body if isinstance(node, ast.For)
                  and isinstance(node.iter, ast.Name) and node.iter.id == 'SENSOR_LETTERS'
                  for name in (part.id for part in ast.walk(node) if isinstance(part, ast.Name))
                  if name.endswith('_validator')}
    definitions = [node for node in source.body if isinstance(node, ast.FunctionDef)
                   and (node.name in validators or node.name == '_sensor_reading_count')]
    choices = {'TEMP_SENSOR__CLASSNAME_choices', 'SENSOR_USER_VAR_SLOT_choices', 'SENSOR_SLOT_choices'}
    attrs = [copy.deepcopy(node) for node in cls.body if (
        isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in choices for target in node.targets)
    ) or (isinstance(node, ast.For) and isinstance(node.iter, ast.Name) and node.iter.id == 'SENSOR_LETTERS')]
    validate = method('indi_allsky/flask/forms.py', 'validate', 'IndiAllskyConfigForm')
    start = next(index for index, node in enumerate(validate.body) if isinstance(node, ast.For)
                 and isinstance(node.iter, ast.Name) and node.iter.id == 'SENSOR_LETTERS')
    stop = next(index for index, node in enumerate(validate.body) if isinstance(node, ast.If)
                and isinstance(node.test, ast.Attribute) and isinstance(node.test.value, ast.Attribute)
                and node.test.value.attr == 'DEW_HEATER__THOLD_ENABLE')
    validate.name = 'validate_sensors'
    validate.body = ast.parse('result = Form.validate(self)').body + validate.body[start:stop] + ast.parse('return result').body
    cls.bases = [ast.Name(id='Form', ctx=ast.Load())]
    cls.body = attrs + [validate]
    namespace = {'__package__': 'indi_allsky.flask', 'Form': Form, 'SelectField': SelectField,
                 'StringField': StringField, 'DataRequired': DataRequired, 'ValidationError': ValidationError,
                 'constants': constants, 're': re, 'itertools': itertools, 'SENSOR_LETTERS': sensor_slots.SENSOR_LETTERS}
    execute(definitions + [cls], namespace)
    return namespace['IndiAllskyConfigForm']


def form_data(**settings):
    return sensor_slots.sensor_form_data({'TEMP_SENSOR': settings})


def test_defaults_preserve_legacy_keys_and_extend_alphabetically():
    assert list(sensor_slots.SENSOR_DEFAULTS) == list('ABCDEFGHIJKLMNOPQRSTUVWXYZ')
    legacy = [('D5', 10, '0x77'), ('D6', 20, '0x76'), ('D16', 30, '0x40'),
              ('D26', 40, '0x50'), ('D25', 50, '0x51'), ('D27', 55, '0x52')]
    for letter, (pin, index, address) in zip('ABCDEF', legacy):
        defaults = sensor_slots.SENSOR_DEFAULTS[letter]
        assert (defaults['PIN_1'], defaults['USER_VAR_SLOT'], defaults['I2C_ADDRESS']) == (pin, 'sensor_user_' + str(index), address)
    data = form_data(Z_LABEL='Roof sensor', Z_USER_VAR_SLOT='sensor_user_59')
    assert len(data) == 26 * 7
    assert data['TEMP_SENSOR__G_LABEL'] == 'Sensor G'
    assert data['TEMP_SENSOR__Z_LABEL'] == 'Roof sensor'
    assert data['TEMP_SENSOR__Z_USER_VAR_SLOT'] == 'sensor_user_59'
    cls = owner('indi_allsky/config.py', 'IndiAllSkyConfigBase')
    config = execute([cls], {'OrderedDict': dict, 'SENSOR_DEFAULTS': sensor_slots.SENSOR_DEFAULTS})['IndiAllSkyConfigBase']()
    assert all(config._base_config['TEMP_SENSOR'][letter + '_LABEL'] == 'Sensor ' + letter for letter in sensor_slots.SENSOR_LETTERS)


@pytest.mark.parametrize('letter', sensor_slots.SENSOR_LETTERS)
def test_each_letter_has_real_fields_and_identical_validation(sensor_form, letter):
    data = form_data(**{letter + '_CLASSNAME': 'kernel_temp_sensor_ds18x20_w1',
                       letter + '_USER_VAR_SLOT': 'sensor_user_10'})
    form = sensor_form(data=data)
    assert len(list(form)) == 26 * 7
    assert form.validate_sensors(), form.errors
    assert form['TEMP_SENSOR__' + letter + '_CLASSNAME'].label.text == 'Sensor ' + letter
    data['TEMP_SENSOR__' + letter + '_I2C_ADDRESS'] = 'not-an-address'
    assert not sensor_form(data=data).validate_sensors()


def test_all_26_devices_fit_existing_reading_slots(sensor_form):
    settings = {letter + '_CLASSNAME': 'kernel_temp_sensor_ds18x20_w1' for letter in sensor_slots.SENSOR_LETTERS}
    settings.update({letter + '_USER_VAR_SLOT': 'sensor_user_' + str(10 + index)
                     for index, letter in enumerate(sensor_slots.SENSOR_LETTERS)})
    form = sensor_form(data=form_data(**settings))
    assert form.validate_sensors(), form.errors


@pytest.mark.parametrize('slot, error', [('sensor_user_10', 'Overlapping'), ('sensor_user_55', 'Not enough')])
def test_overlap_and_capacity_checks_include_new_letters(sensor_form, slot, error):
    form = sensor_form(data=form_data(A_CLASSNAME='sensor_data_generator', A_USER_VAR_SLOT='sensor_user_10',
                                    Z_CLASSNAME='sensor_data_generator', Z_USER_VAR_SLOT=slot))
    assert not form.validate_sensors()
    assert any(error in message for message in form.TEMP_SENSOR__Z_USER_VAR_SLOT.errors)


@pytest.mark.parametrize('field, value', [('CLASSNAME', 'unknown'), ('USER_VAR_SLOT', 'sensor_user_60'),
                                        ('TITLE_TEMPLATE', '{unknown}'), ('LABEL', '')])
def test_invalid_new_fields_report_errors_instead_of_crashing(sensor_form, field, value):
    data = form_data(Z_CLASSNAME='kernel_temp_sensor_ds18x20_w1')
    data['TEMP_SENSOR__Z_' + field] = value
    form = sensor_form(data=data)
    assert not form.validate_sensors()
    assert form['TEMP_SENSOR__Z_' + field].errors


@pytest.mark.parametrize('topics', ['', 'a,a', 'a,b'])
def test_mqtt_hardware_validation_applies_to_z(sensor_form, topics):
    form = sensor_form(data=form_data(Z_CLASSNAME='mqtt_broker_sensor', Z_PIN_1=topics))
    assert form.validate_sensors() is (topics == 'a,b')


@pytest.mark.parametrize('pin, valid', [('D5', True), ('not-a-pin', False), ('', False)])
def test_gpio_hardware_validation_applies_to_z(sensor_form, monkeypatch, pin, valid):
    monkeypatch.setitem(sys.modules, 'board', SimpleNamespace(D5=5))
    form = sensor_form(data=form_data(Z_CLASSNAME='blinka_temp_sensor_dht22', Z_PIN_1=pin))
    assert form.validate_sensors() is valid
    if not valid:
        assert form.TEMP_SENSOR__Z_PIN_1.errors


def test_worker_initializes_reads_and_falls_back_for_new_devices(monkeypatch):
    class Probe:
        METADATA = {'count': 1}

        def __init__(self, config, label, night, astro, **kwargs):
            self.label, self.kwargs = label, kwargs

        def update(self):
            return {'data': (12.5,)}

    monkeypatch.setattr(sensors, 'kernel_temp_sensor_ds18x20_w1', Probe)
    namespace = {'__package__': 'indi_allsky', 'constants': constants,
                 'logger': logging.getLogger('sensor-test')}
    execute([method('indi_allsky/sensor.py', 'init_sensors', 'SensorWorker'),
             method('indi_allsky/sensor.py', 'update_sensors', 'SensorWorker')], namespace)
    from multiprocessing import Array
    worker = SimpleNamespace(config={'TEMP_SENSOR': {'G_CLASSNAME': 'kernel_temp_sensor_ds18x20_w1',
        'G_LABEL': 'G probe', 'G_PIN_1': 'D12', 'G_I2C_ADDRESS': '0x60', 'G_USER_VAR_SLOT': 'sensor_user_35',
        'Z_CLASSNAME': 'kernel_temp_sensor_ds18x20_w1', 'Z_USER_VAR_SLOT': 'sensor_user_59'}},
        night_av=[], astro_av=[], sensors_user_av=Array('d', [0] * 150))
    namespace['init_sensors'](worker)
    assert len(worker.sensors) == 8
    assert [sensor.slot for sensor in worker.sensors] == [10, 20, 30, 40, 50, 55, 35, 59]
    assert worker.sensors[6].label == 'G probe'
    assert worker.sensors[6].kwargs['i2c_address'] == '0x60'
    namespace['update_sensors'](worker)
    assert worker.sensors_user_av[35] == worker.sensors_user_av[59] == 12.5
    worker.config = {'TEMP_SENSOR': {
        letter + '_' + field: value
        for index, letter in enumerate(sensor_slots.SENSOR_LETTERS)
        for field, value in {'CLASSNAME': 'kernel_temp_sensor_ds18x20_w1',
                             'USER_VAR_SLOT': 'sensor_user_' + str(index + 10)}.items()
    }}
    namespace['init_sensors'](worker)
    assert len(worker.sensors) == 26
    assert [sensor.label for sensor in worker.sensors] == ['Sensor ' + letter for letter in sensor_slots.SENSOR_LETTERS]
    namespace['update_sensors'](worker)
    assert list(worker.sensors_user_av[10:36]) == [12.5] * 26
    class Failed(Probe):
        def __init__(self, *args, **kwargs):
            raise SensorException('unavailable')
    monkeypatch.setattr(sensors, 'kernel_temp_sensor_ds18x20_w1', Failed)
    namespace['init_sensors'](worker)
    assert isinstance(worker.sensors[-1], sensors.sensor_simulator)


def test_capture_and_named_labels_include_z(monkeypatch):
    import psutil
    from indi_allsky.sensors_mapping import build_slot_label_map

    monkeypatch.setattr(psutil, 'sensors_temperatures', lambda: {}, raising=False)
    config = {'TEMP_SENSOR': {'Z_CLASSNAME': 'kernel_temp_sensor_ds18x20_w1', 'Z_LABEL': 'Roof',
        'Z_PIN_1': 'test', 'Z_USER_VAR_SLOT': 'sensor_user_59', 'Z_TITLE_TEMPLATE': '{label:s}: {probe:s}'}}
    namespace = {'__package__': 'indi_allsky', 'constants': constants, 'logger': logging.getLogger('sensor-test')}
    execute([method('indi_allsky/capture.py', 'update_sensor_slot_labels', 'CaptureWorker')], namespace)
    cls = owner('indi_allsky/capture.py', 'CaptureWorker')
    slots = next(node.value for node in cls.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == 'SENSOR_SLOTS' for target in node.targets))
    worker = SimpleNamespace(config=config, SENSOR_SLOTS=ast.literal_eval(slots))
    namespace['update_sensor_slot_labels'](worker)
    label = worker.SENSOR_SLOTS[59][1]
    assert label.startswith('Roof:')
    assert build_slot_label_map(config)[59]['name'] == label
    assert build_slot_label_map(config)[59]['key'].startswith('sensor_z_')


def test_ajax_save_uses_validated_values_and_preserves_omitted_slots(sensor_form):
    cls = owner('indi_allsky/flask/views.py', 'AjaxConfigView')
    loop = next(node for node in ast.walk(cls) if isinstance(node, ast.For)
                and isinstance(node.iter, ast.Name) and node.iter.id == 'SENSOR_LETTERS')
    config = {'TEMP_SENSOR': {'A_LABEL': 'Original', 'Z_LABEL': 'Keep me'}}
    payload = {'TEMP_SENSOR__G_CLASSNAME': 'kernel_temp_sensor_ds18x20_w1', 'TEMP_SENSOR__G_LABEL': 'Roof'}
    form = sensor_form(data=dict(form_data(), **payload))
    namespace = {'self': SimpleNamespace(indi_allsky_config=config), 'request': SimpleNamespace(json=payload),
                 'form_config': form, 'SENSOR_LETTERS': sensor_slots.SENSOR_LETTERS,
                 'SENSOR_FIELDS': sensor_slots.SENSOR_FIELDS}
    execute([copy.deepcopy(loop)], namespace)
    assert config['TEMP_SENSOR'] == {'A_LABEL': 'Original', 'Z_LABEL': 'Keep me',
                                    'G_CLASSNAME': 'kernel_temp_sensor_ds18x20_w1', 'G_LABEL': 'Roof'}


def render_sensor_editor(sensor_form, settings=None):
    from jinja2 import Environment

    form = sensor_form(data=form_data(**(settings or {})))
    form.sensor_letters = sensor_slots.SENSOR_LETTERS
    form.sensor_counts = {'kernel_temp_sensor_ds18x20_w1': 1, 'sensor_data_generator': 7}
    template = (ROOT / 'indi_allsky/flask/templates/config/sensors.html').read_text(encoding='utf-8')
    template = template.split('        <!-- Online Weather APIs Card -->')[0]
    rendered = Environment(autoescape=True).from_string(template).render(form_config=form)
    script = (ROOT / 'indi_allsky/flask/static/js/sensor-slots.js').read_text(encoding='utf-8')
    return '<html><body>' + rendered + '</div></div><script>' + script + '</script></body></html>'


def test_editor_renders_only_configured_cards_and_preserves_keys(sensor_form):
    html = render_sensor_editor(sensor_form, {'C_CLASSNAME': 'kernel_temp_sensor_ds18x20_w1'})
    assert html.count('data-sensor-slot=') == 26
    assert html.count('hidden>') == 25
    assert 'TEMP_SENSOR__Z_CLASSNAME' in html
    assert 'value="Sensor Z"' in html


def test_ui_serializes_all_26_slots_and_keeps_global_sensor_settings():
    from jinja2 import Environment

    current = (ROOT / 'indi_allsky/flask/templates/config.html').read_text(encoding='utf-8')
    block = current.split('const field_names = [', 1)[1].split('];', 1)[0]
    rendered = Environment().from_string(block).render(form_config=SimpleNamespace(sensor_letters=sensor_slots.SENSOR_LETTERS))
    keys = re.findall(r"'([A-Z][A-Z0-9_]+)'", rendered)
    assert set(form_data()) <= set(keys)
    assert 'TEMP_SENSOR__MQTT_HOST' in keys
    assert 'TEMP_SENSOR__OPENWEATHERMAP_APIKEY' in keys
    assert len(keys) == len(set(keys))
