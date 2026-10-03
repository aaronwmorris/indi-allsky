import ast
import io
import json
import logging
import math
from functools import lru_cache
from multiprocessing import Array
from pathlib import Path
from types import SimpleNamespace

import pytest

from indi_allsky import constants, sensors_mapping
from indi_allsky.sensor import SensorWorker
from indi_allsky.devices.exceptions import SensorReadException


_SOURCE_ROOT = Path(__file__).resolve().parents[1] / 'indi_allsky'


@lru_cache(maxsize=None)
def _source_tree(relative_path):
    return ast.parse((_SOURCE_ROOT / relative_path).read_text(encoding='utf-8'))


def _source_member(relative_path, *names):
    node = _source_tree(relative_path)
    for name in names:
        node = next(child for child in node.body if getattr(child, 'name', None) == name)
    return node


def _source_assignment(nodes, target):
    return next(node for node in nodes if isinstance(node, ast.Assign)
                and any(ast.unparse(name) == target for name in node.targets))


def _exec_source(relative_path, body, namespace):
    exec(compile(ast.Module(body=body, type_ignores=[]), str(_SOURCE_ROOT / relative_path), 'exec'), namespace)


def _values(mapping):
    return lambda index: mapping.get(index)


def _config(**temp_sensor):
    settings = {
        'A_CLASSNAME': 'blinka_temp_sensor_mlx90614_i2c',
        'A_USER_VAR_SLOT': 'sensor_user_10',
        'B_CLASSNAME': 'blinka_temp_sensor_dht22',
        'B_USER_VAR_SLOT': 'sensor_user_12',
        'CLOUDINESS_INDEX_ENABLE': True,
        'CLOUDINESS_INDEX_TEMP_UNIT': 'c',
        'CLOUDINESS_INDEX_CLEAR_TEMP': -20.0,
        'CLOUDINESS_INDEX_CLOUDY_TEMP': 10.0,
        'CLOUDINESS_INDEX_CLEAR_GROUND_TEMP': 10.0,
        'CLOUDINESS_INDEX_CLOUDY_GROUND_TEMP': 10.0,
    }
    settings.update(temp_sensor)
    return {'TEMP_SENSOR': settings}


def _validate_cloudiness_form(form):
    validate = _source_member('flask/forms.py', 'IndiAllskyConfigForm', 'validate')
    namespace = {'self': form, 'math': math, 'sensors_mapping': sensors_mapping, 'result': True}
    _exec_source('flask/forms.py', [validate.body[1]], namespace)
    return namespace['result']


def _cloudiness_ground_form(config, ground_slot, enabled):
    from wtforms import BooleanField, Form, SelectField
    from wtforms.validators import ValidationError

    form_class = _source_member('flask/forms.py', 'IndiAllskyConfigForm')
    validator = _source_member('flask/forms.py', 'CLOUDINESS_INDEX_GROUND_SENSOR_validator')
    field = _source_assignment(form_class.body, 'TEMP_SENSOR__CLOUDINESS_INDEX_GROUND_SENSOR')
    namespace = {'SelectField': SelectField, 'ValidationError': ValidationError,
                 'constants': constants, 'sensors_mapping': sensors_mapping}
    _exec_source('flask/forms.py', [validator, field], namespace)
    form_type = type('CloudinessGroundForm', (Form,), {
        'TEMP_SENSOR__CLOUDINESS_INDEX_ENABLE': BooleanField(),
        'TEMP_SENSOR__CLOUDINESS_INDEX_GROUND_SENSOR': namespace['TEMP_SENSOR__CLOUDINESS_INDEX_GROUND_SENSOR'],
    })
    form = form_type(TEMP_SENSOR__CLOUDINESS_INDEX_ENABLE=enabled,
                     TEMP_SENSOR__CLOUDINESS_INDEX_GROUND_SENSOR=ground_slot)
    form.SENSOR_SLOT_choices = {'User Sensors': [(str(index), str(index)) for index in range(110)]}
    namespace['self'] = form
    for letter in ('A', 'B', 'C', 'D', 'E', 'F'):
        namespace['temp_sensor__' + letter.lower() + '_classname'] = config['TEMP_SENSOR'].get(letter + '_CLASSNAME', '')
        namespace['temp_sensor__' + letter.lower() + '_user_var_slot'] = config['TEMP_SENSOR'].get(letter + '_USER_VAR_SLOT', '')
    initialize = _source_member('flask/forms.py', 'IndiAllskyConfigForm', '__init__')
    temp_sensors = _source_assignment(initialize.body, 'temp_sensors')
    start = initialize.body.index(_source_assignment(initialize.body, 'ground_sensor_choices'))
    _exec_source('flask/forms.py', [temp_sensors] + initialize.body[start:start + 3], namespace)
    return form


@pytest.mark.parametrize('field_name', [
    'TEMP_SENSOR__CLOUDINESS_INDEX_ENABLE',
    'TEMP_SENSOR__CLOUDINESS_INDEX_USE_GROUND_SENSOR',
])
def test_cloudiness_toggles_use_checkbox_save_path(field_name):
    source = _SOURCE_ROOT / 'flask' / 'templates' / 'config.html'
    template = source.read_text(encoding='utf-8')
    save_lists = {}
    for list_name in ('field_names', 'checkbox_field_names'):
        array_source = template.split('const ' + list_name + ' = ', 1)[1].split(';', 1)[0]
        array_source = '\n'.join(line for line in array_source.splitlines()
                                 if not line.lstrip().startswith('//'))
        save_lists[list_name] = ast.literal_eval(array_source)

    assert field_name not in save_lists['field_names']
    assert save_lists['checkbox_field_names'].count(field_name) == 1


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('use_ground_sensor', [False, True])
@pytest.mark.parametrize('classname', [
    None, *constants.CLOUD_SENSOR_CLASSNAMES,
    'blinka_temp_sensor_dht22', 'temp_api_ecowitt',
])
def test_cloudiness_settings_initial_visibility_follows_enable_toggle(enabled, use_ground_sensor, classname):
    from jinja2 import Environment, nodes
    from wtforms import BooleanField, Form, StringField

    source = _SOURCE_ROOT / 'flask' / 'templates' / 'config' / 'sensors.html'
    card = source.read_text(encoding='utf-8').split('<!-- Cloudiness Index Card -->', 1)[1]
    environment = Environment(autoescape=True)
    field_names = {
        node.attr for node in environment.parse(card).find_all(nodes.Getattr)
        if isinstance(node.node, nodes.Name) and node.node.name == 'form_config'
        and node.attr.startswith('TEMP_SENSOR__')
    }
    enable_field = 'TEMP_SENSOR__CLOUDINESS_INDEX_ENABLE'
    external_field = 'TEMP_SENSOR__CLOUDINESS_INDEX_USE_GROUND_SENSOR'
    form_type = type('CloudinessVisibilityForm', (Form,), {
        name: BooleanField() if name in (enable_field, external_field) else StringField()
        for name in field_names
    })
    form = form_type(**{enable_field: enabled, external_field: use_ground_sensor})
    form.cloud_sensor_classnames = constants.CLOUD_SENSOR_CLASSNAMES
    has_cloud_sensor = classname in constants.CLOUD_SENSOR_CLASSNAMES
    form.TEMP_SENSOR__CLOUDINESS_INDEX_SENSOR.choices = {
        'MLX Cloudiness Sensors': [('sensor_user_10', classname)] if has_cloud_sensor else [],
    }
    rendered = environment.from_string(card).render(form_config=form)
    panel = rendered.split('<div id="cloudiness-index-panel"', 1)[1]
    assert ('style="display: none;"' in panel.split('>', 1)[0]) is not has_cloud_sensor
    before_settings, settings = rendered.split('<div id="cloudiness-index-settings"', 1)

    assert 'This is a local IR cloudiness indicator, not a percentage of sky covered by clouds.' in before_settings
    assert 'id="' + enable_field + '"' in before_settings
    assert ('style="display: none;"' in settings.split('>', 1)[0]) is not enabled
    for name in field_names - {enable_field}:
        assert 'id="' + name + '"' in settings

    ground_sensor = settings.split('<div id="cloudiness-index-ground-sensor"', 1)[1]
    assert ('style="display: none;"' in ground_sensor.split('>', 1)[0]) is not use_ground_sensor
    assert 'id="TEMP_SENSOR__CLOUDINESS_INDEX_GROUND_SENSOR"' in ground_sensor

    before_tuning, tuning = settings.split('<div id="cloudiness-index-tuning"', 1)
    assert 'id="cloudiness-index-tuning-toggle"' in before_tuning
    assert 'style="display: none;"' in tuning.split('>', 1)[0]
    for name in ('TEMP_SENSOR__CLOUDINESS_INDEX_COEFFICIENT', 'TEMP_SENSOR__CLOUDINESS_INDEX_OFFSET'):
        assert 'id="' + name + '"' not in before_tuning
        assert 'id="' + name + '"' in tuning


@pytest.mark.parametrize('read_time, expected', [(100.0, 50.0), (40.0, None), (0.0, None), (None, None)])
def test_image_cloudiness_calculation_uses_snapshot_after_releasing_lock(monkeypatch, read_time, expected):
    import time
    from threading import Lock

    method = _source_member('image.py', 'ImageWorker', 'processImage')
    start = method.body.index(_source_assignment(method.body, 'i_ref.cloudiness_index')) - 2

    sensor_lock = Lock()

    class SensorArray(list):
        def get_lock(self):
            return sensor_lock

        def __getitem__(self, index):
            assert sensor_lock.locked()
            return super().__getitem__(index)

    values = SensorArray([0.0] * 110)
    values[10:12] = [10.0, -5.0]
    read_times = SensorArray([read_time] * 110)

    worker = SimpleNamespace(
        config=_config(), sensors_user_av=values,
        sensors_user_read_time_av=read_times if read_time is not None else None,
    )
    image_ref = SimpleNamespace()
    calculate = sensors_mapping.calculate_cloudiness_index

    def calculate_from_snapshot(config, get_sensor_value):
        assert not sensor_lock.locked()
        values[10:12] = [40.0, -20.0]
        read_times[:] = [0.0] * 110
        return calculate(config, get_sensor_value)

    monkeypatch.setattr(sensors_mapping, 'calculate_cloudiness_index', calculate_from_snapshot)
    monkeypatch.setattr(time, 'monotonic', lambda: 101.0)
    namespace = {'self': worker, 'i_ref': image_ref, 'sensors_mapping': sensors_mapping, 'time': time}
    _exec_source('image.py', method.body[start:start + 3], namespace)
    assert image_ref.cloudiness_index == expected


def test_returns_none_until_calibration_is_enabled():
    config = _config(CLOUDINESS_INDEX_ENABLE=False)

    assert sensors_mapping.calculate_cloudiness_index(config, _values({10: 10.0, 11: -20.0})) is None


def test_paired_ambient_calibration_interpolates_live_temperature_difference():
    # A live ground-to-sky difference of 15 C is halfway between 30 C clear
    # and 0 C cloudy reference differences.
    cloudiness_index = sensors_mapping.calculate_cloudiness_index(
        _config(),
        _values({10: 10.0, 11: -5.0}),
    )

    assert cloudiness_index == 50.0


def test_clamps_values_outside_calibrated_range():
    config = _config()

    assert sensors_mapping.calculate_cloudiness_index(config, _values({10: 10.0, 11: -25.0})) == 0.0
    assert sensors_mapping.calculate_cloudiness_index(config, _values({10: 10.0, 11: 15.0})) == 100.0


def test_rejects_equal_calibration_references():
    config = _config(CLOUDINESS_INDEX_CLOUDY_TEMP=-20.0)

    assert sensors_mapping.calculate_cloudiness_index(config, _values({10: 10.0, 11: -5.0})) is None


@pytest.mark.parametrize('slot', ['missing', None, '', 'invalid', 'sensor_user_999', 999])
def test_cloudiness_does_not_read_slot_ten_for_malformed_cloud_sensor_slot(slot):
    config = _config(A_USER_VAR_SLOT=slot)
    if slot == 'missing':
        del config['TEMP_SENSOR']['A_USER_VAR_SLOT']
    read_indices = []

    def get_sensor_value(index):
        read_indices.append(index)
        return {10: 10.0, 11: -5.0}.get(index)

    assert sensors_mapping.calculate_cloudiness_index(config, get_sensor_value) is None
    assert read_indices == []


def test_cloudiness_ignores_malformed_slot_when_another_mlx_is_valid():
    config = _config(
        A_USER_VAR_SLOT='invalid',
        B_CLASSNAME='blinka_temp_sensor_mlx90615_i2c',
        B_USER_VAR_SLOT='sensor_user_20',
    )
    assert sensors_mapping.calculate_cloudiness_index(
        config, _values({20: 10.0, 21: -5.0})) == 50.0


@pytest.mark.parametrize('unit', ['c', 'f', 'k'])
@pytest.mark.parametrize('clear_delta,cloudy_delta,valid', [
    (4.0, 3.9, False), (1.9, 0.0, False), (2.0, 0.0, False),
    (2.1, 0.0, True), (6.0, 3.9, True), (0.0, 4.0, False),
])
def test_calibration_span_must_exceed_two_celsius(clear_delta, cloudy_delta, valid, unit):
    def reference(temperature):
        if unit == 'f':
            return temperature * 9.0 / 5.0 + 32.0
        if unit == 'k':
            return temperature + 273.15
        return temperature

    config = _config(
        CLOUDINESS_INDEX_TEMP_UNIT=unit,
        CLOUDINESS_INDEX_CLEAR_TEMP=reference(10.0 - clear_delta),
        CLOUDINESS_INDEX_CLEAR_GROUND_TEMP=reference(10.0),
        CLOUDINESS_INDEX_CLOUDY_TEMP=reference(15.0 - cloudy_delta),
        CLOUDINESS_INDEX_CLOUDY_GROUND_TEMP=reference(15.0),
    )
    midpoint = (clear_delta + cloudy_delta) / 2.0
    result = sensors_mapping.calculate_cloudiness_index(
        config, _values({10: 10.0, 11: 10.0 - midpoint}))

    if valid:
        assert result == pytest.approx(50.0)
    else:
        assert result is None


@pytest.mark.parametrize('unit', ['c', 'f', 'k'])
@pytest.mark.parametrize('span,valid', [
    (0.0, False), (-3.0, False), (1.9, False), (2.0, False),
    (math.nextafter(2.0, math.inf), False), (2.000001, True), (30.0, True),
])
def test_shared_cloudiness_calibration_validation_normalizes_units(unit, span, valid):
    def reference(temperature):
        if unit == 'f':
            return temperature * 9.0 / 5.0 + 32.0
        if unit == 'k':
            return temperature + 273.15
        return temperature

    assert sensors_mapping.validate_cloudiness_calibration(
        reference(10.0 - span), reference(10.0), reference(10.0), reference(10.0),
        temp_unit=unit) is valid


@pytest.mark.parametrize('position', range(4))
@pytest.mark.parametrize('value', [None, 'invalid', math.nan, math.inf, -math.inf, 10 ** 1000])
def test_shared_cloudiness_calibration_validation_rejects_invalid_references(position, value):
    references = [-20.0, 10.0, 10.0, 10.0]
    references[position] = value
    assert sensors_mapping.validate_cloudiness_calibration(*references) is False


def test_shared_cloudiness_calibration_validation_rejects_overflowing_span():
    assert sensors_mapping.validate_cloudiness_calibration(-1e308, 0.0, 1e308, 0.0) is False


@pytest.mark.parametrize('unit', ['c', 'f', 'k'])
@pytest.mark.parametrize('clear_delta,cloudy_delta,valid', [
    (4.0, 3.9, False), (1.9, 0.0, False), (2.0, 0.0, False),
    (2.1, 0.0, True), (6.0, 3.9, True), (0.0, 4.0, False),
])
def test_form_rejects_weak_calibration_on_clear_sky_field(clear_delta, cloudy_delta, valid, unit):
    scale = 1.8 if unit == 'f' else 1.0
    base = 50.0 if unit == 'f' else 283.15 if unit == 'k' else 10.0
    settings = _config(
        CLOUDINESS_INDEX_TEMP_UNIT=unit,
        CLOUDINESS_INDEX_CLEAR_TEMP=base - clear_delta * scale,
        CLOUDINESS_INDEX_CLEAR_GROUND_TEMP=base,
        CLOUDINESS_INDEX_CLOUDY_TEMP=base - cloudy_delta * scale,
        CLOUDINESS_INDEX_CLOUDY_GROUND_TEMP=base,
        CLOUDINESS_INDEX_SENSOR='sensor_user_10',
        CLOUDINESS_INDEX_USE_GROUND_SENSOR=False,
        CLOUDINESS_INDEX_GROUND_SENSOR='',
    )['TEMP_SENSOR']
    form = SimpleNamespace(**{
        'TEMP_SENSOR__' + key: SimpleNamespace(data=value, errors=[])
        for key, value in settings.items()
    })
    form.TEMP_SENSOR__CLOUDINESS_INDEX_SENSOR.choices = {
        'MLX Cloudiness Sensors': [('sensor_user_10', 'MLX')],
    }
    form.cloud_sensor_auto_ground_slots = {'sensor_user_10'}

    assert _validate_cloudiness_form(form) is valid
    errors = form.TEMP_SENSOR__CLOUDINESS_INDEX_CLEAR_TEMP.errors
    if valid:
        assert errors == []
    else:
        assert 'more than 2.0 C (3.6 F)' in errors[0]
        assert 'greater than under cloudy skies' in errors[0]
        assert 'sensor may be having problems' in errors[0]
    assert form.TEMP_SENSOR__CLOUDINESS_INDEX_CLOUDY_GROUND_TEMP.errors == []


@pytest.mark.parametrize('enabled,sensor_count,selected,expected_error', [
    (True, 0, '', 'Configure an MLX sky-temperature sensor first.'),
    (True, 0, 'sensor_user_10', 'Configure an MLX sky-temperature sensor first.'),
    (False, 0, '', None),
    (True, 1, '', None),
    (True, 1, 'sensor_user_10', None),
    (True, 2, '', 'Select the MLX sensor used for this cloudiness index'),
    (True, 2, 'sensor_user_10', None),
])
def test_form_requires_configured_cloud_sensor_when_enabled(enabled, sensor_count, selected, expected_error):
    settings = _config(
        CLOUDINESS_INDEX_ENABLE=enabled,
        CLOUDINESS_INDEX_SENSOR=selected,
        CLOUDINESS_INDEX_USE_GROUND_SENSOR=False,
        CLOUDINESS_INDEX_GROUND_SENSOR='',
    )['TEMP_SENSOR']
    form = SimpleNamespace(**{
        'TEMP_SENSOR__' + key: SimpleNamespace(data=value, errors=[])
        for key, value in settings.items()
    })
    choices = [('sensor_user_10', 'MLX A'), ('sensor_user_20', 'MLX B')][:sensor_count]
    form.TEMP_SENSOR__CLOUDINESS_INDEX_SENSOR.choices = {'MLX Cloudiness Sensors': choices}
    form.cloud_sensor_auto_ground_slots = {slot for slot, label in choices}

    assert _validate_cloudiness_form(form) is (expected_error is None)
    assert form.TEMP_SENSOR__CLOUDINESS_INDEX_SENSOR.errors == (
        [] if expected_error is None else [expected_error])


def test_coefficient_and_offset_tune_the_normalized_index():
    cloudiness_index = sensors_mapping.calculate_cloudiness_index(
        _config(CLOUDINESS_INDEX_COEFFICIENT=0.5, CLOUDINESS_INDEX_OFFSET=10.0),
        _values({10: 10.0, 11: -5.0}),
    )

    assert cloudiness_index == 35.0


def test_selected_ground_sensor_is_used_when_mlx_has_no_ambient_reference():
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'blinka_temp_sensor_mlx90640_i2c',
            'A_USER_VAR_SLOT': 'sensor_user_10',
            'B_CLASSNAME': 'blinka_temp_sensor_dht22',
            'B_USER_VAR_SLOT': 'sensor_user_11',
            'CLOUDINESS_INDEX_ENABLE': True,
            'CLOUDINESS_INDEX_CLEAR_TEMP': -20.0,
            'CLOUDINESS_INDEX_CLOUDY_TEMP': 10.0,
            'CLOUDINESS_INDEX_CLEAR_GROUND_TEMP': 10.0,
            'CLOUDINESS_INDEX_CLOUDY_GROUND_TEMP': 10.0,
            'CLOUDINESS_INDEX_GROUND_SENSOR': 'sensor_user_11',
        },
    }

    assert sensors_mapping.calculate_cloudiness_index(config, _values({10: -5.0, 11: 10.0})) == 50.0


def test_mlx_without_paired_ambient_requires_a_selected_ground_sensor():
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'blinka_temp_sensor_mlx90640_i2c',
            'A_USER_VAR_SLOT': 'sensor_user_10',
            'CLOUDINESS_INDEX_ENABLE': True,
            'CLOUDINESS_INDEX_CLEAR_TEMP': -20.0,
            'CLOUDINESS_INDEX_CLOUDY_TEMP': 10.0,
            'CLOUDINESS_INDEX_CLEAR_GROUND_TEMP': 10.0,
            'CLOUDINESS_INDEX_CLOUDY_GROUND_TEMP': 10.0,
        },
    }

    assert sensors_mapping.calculate_cloudiness_index(config, _values({10: -5.0})) is None


def test_selected_ground_sensor_overrides_paired_mlx_ambient():
    cloudiness_index = sensors_mapping.calculate_cloudiness_index(
        _config(
            CLOUDINESS_INDEX_USE_GROUND_SENSOR=True,
            CLOUDINESS_INDEX_GROUND_SENSOR='sensor_user_12',
        ),
        _values({10: 40.0, 11: -5.0, 12: 10.0}),
    )

    assert cloudiness_index == 50.0


@pytest.mark.parametrize('classname', [
    'temp_api_ecowitt', 'temp_api_ambientweather', 'temp_api_astrospheric',
    'temp_api_openweathermap', 'temp_api_weatherunderground', 'mqtt_broker_sensor',
])
def test_cloudiness_rejects_cached_external_ambient_sources(classname):
    config = _config(
        B_CLASSNAME=classname,
        CLOUDINESS_INDEX_USE_GROUND_SENSOR=True,
        CLOUDINESS_INDEX_GROUND_SENSOR='sensor_user_12',
    )
    assert sensors_mapping.calculate_cloudiness_index(
        config, _values({10: 10.0, 11: -5.0, 12: 10.0})) is None


@pytest.mark.parametrize('ground_slot', ['sensor_user_11', 'sensor_user_13', 'sensor_user_20'])
def test_cloudiness_rejects_sky_nontemperature_and_unconfigured_ambient_slots(ground_slot):
    config = _config(
        CLOUDINESS_INDEX_USE_GROUND_SENSOR=True,
        CLOUDINESS_INDEX_GROUND_SENSOR=ground_slot,
    )
    assert sensors_mapping.calculate_cloudiness_index(
        config, _values({10: 10.0, 11: -5.0, 12: 10.0, 13: 50.0, 20: 10.0})) is None


@pytest.mark.parametrize('classname,expected', [
    ('blinka_temp_sensor_mlx90614_i2c', (0,)),
    ('blinka_temp_sensor_mlx90615_i2c', (0,)),
    ('blinka_temp_sensor_mlx90640_i2c', ()),
    ('blinka_temp_sensor_dht22', (0,)),
    ('kernel_temp_sensor_ds18x20_w1', (0,)),
    ('temp_api_ecowitt', ()), ('mqtt_broker_sensor', ()),
    ('unknown', ()), (None, ()),
])
def test_cloudiness_ambient_outputs_are_hardware_temperature_channels(classname, expected):
    assert sensors_mapping.get_cloudiness_ground_sensor_offsets(classname) == expected


@pytest.mark.parametrize('enabled', [True, False])
@pytest.mark.parametrize('ground_slot,supported', [
    ('', True), ('sensor_user_10', True), ('sensor_user_11', False),
    ('sensor_user_12', True), ('sensor_user_13', False),
    ('sensor_user_14', False), ('sensor_user_20', False),
])
def test_cloudiness_form_filters_and_validates_ambient_sources(enabled, ground_slot, supported):
    config = _config(C_CLASSNAME='temp_api_ecowitt', C_USER_VAR_SLOT='sensor_user_20')
    form = _cloudiness_ground_form(config, ground_slot, enabled)
    field = form.TEMP_SENSOR__CLOUDINESS_INDEX_GROUND_SENSOR
    assert [slot for slot, label in field.choices['Temperature Sensors']] == ['sensor_user_10', 'sensor_user_12']
    assert form.validate() is (supported or not enabled)
    if enabled and not supported:
        assert 'configured hardware ambient temperature sensor' in field.errors[0]


def test_paired_mlx_ambient_is_used_until_external_sensor_is_enabled():
    cloudiness_index = sensors_mapping.calculate_cloudiness_index(
        _config(CLOUDINESS_INDEX_GROUND_SENSOR='sensor_user_12'),
        _values({10: 10.0, 11: -5.0, 12: 40.0}),
    )

    assert cloudiness_index == 50.0


def test_multiple_cloud_sensors_require_an_explicit_selection():
    config = _config(
        B_CLASSNAME='blinka_temp_sensor_mlx90615_i2c',
        B_USER_VAR_SLOT='sensor_user_20',
    )

    assert sensors_mapping.calculate_cloudiness_index(config, _values({10: 10.0, 11: -5.0, 20: 10.0, 21: -5.0})) is None


def test_selected_cloud_sensor_is_used_when_multiple_are_configured():
    config = _config(
        B_CLASSNAME='blinka_temp_sensor_mlx90615_i2c',
        B_USER_VAR_SLOT='sensor_user_20',
        CLOUDINESS_INDEX_SENSOR='sensor_user_20',
    )

    cloudiness_index = sensors_mapping.calculate_cloudiness_index(
        config,
        _values({10: 10.0, 11: -20.0, 20: 10.0, 21: -5.0}),
    )

    assert cloudiness_index == 50.0


@pytest.mark.parametrize('unit,ambient,sky', [
    ('c', 10.0, -5.0), ('f', 50.0, 23.0), ('k', 283.15, 268.15),
])
def test_reference_units_are_independent_of_live_display_units(unit, ambient, sky):
    config = _config()
    config['TEMP_DISPLAY'] = unit

    cloudiness_index = sensors_mapping.calculate_cloudiness_index(config, _values({10: ambient, 11: sky}))

    assert cloudiness_index == 50.0


@pytest.mark.parametrize('index', [10, 11])
@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf'), None])
def test_invalid_live_readings_are_unavailable(index, value):
    values = {10: 10.0, 11: -5.0}
    values[index] = value
    assert sensors_mapping.calculate_cloudiness_index(_config(), _values(values)) is None


@pytest.mark.parametrize('key', [
    'CLOUDINESS_INDEX_CLEAR_TEMP', 'CLOUDINESS_INDEX_CLOUDY_TEMP',
    'CLOUDINESS_INDEX_CLEAR_GROUND_TEMP', 'CLOUDINESS_INDEX_CLOUDY_GROUND_TEMP',
    'CLOUDINESS_INDEX_COEFFICIENT', 'CLOUDINESS_INDEX_OFFSET',
])
@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_calibration_is_unavailable(key, value):
    assert sensors_mapping.calculate_cloudiness_index(
        _config(**{key: value}), _values({10: 10.0, 11: -5.0})) is None


@pytest.mark.parametrize('name', [
    'CLOUDINESS_INDEX_TEMP_validator', 'CLOUDINESS_INDEX_COEFFICIENT_validator',
    'CLOUDINESS_INDEX_OFFSET_validator',
])
@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf')])
def test_form_validators_reject_nonfinite_values(name, value):
    functions = [_source_member('flask/forms.py', validator)
                 for validator in {'CLOUDINESS_INDEX_TEMP_validator', name}]
    namespace = {'math': math, 'ValidationError': ValueError}
    _exec_source('flask/forms.py', functions, namespace)
    with pytest.raises(ValueError):
        namespace[name](None, SimpleNamespace(data=value))


def test_disabled_calculation_does_not_access_sensor_values():
    def unavailable(index):
        raise AssertionError('Disabled cloudiness must not access live sensors')

    assert sensors_mapping.calculate_cloudiness_index(
        _config(CLOUDINESS_INDEX_ENABLE=False), unavailable) is None


@pytest.mark.parametrize('read_time', [
    0.0, 1.0, 102.0, float('nan'), float('inf'), -float('inf'), None, '100.0', 10 ** 400,
])
def test_uninitialized_expired_or_invalid_read_times_are_unavailable(read_time):
    assert sensors_mapping.get_fresh_sensor_value([0.0], [read_time], 0, now=101.0) is None


@pytest.mark.parametrize('index', [1, -2, None, '0', 0.5])
def test_fresh_sensor_value_rejects_invalid_indices(index):
    assert sensors_mapping.get_fresh_sensor_value([0.0], [100.0], index, now=101.0) is None


@pytest.mark.parametrize('values,read_times', [
    ([], [100.0]), ([0.0], []), (None, [100.0]), ([0.0], 100.0),
])
def test_fresh_sensor_value_rejects_missing_or_mismatched_arrays(values, read_times):
    assert sensors_mapping.get_fresh_sensor_value(values, read_times, 0, now=101.0) is None


@pytest.mark.parametrize('value', [
    None, '0.0', float('nan'), float('inf'), -float('inf'), 10 ** 400,
])
def test_fresh_sensor_value_rejects_invalid_readings(value):
    assert sensors_mapping.get_fresh_sensor_value([value], [100.0], 0, now=101.0) is None


def test_fresh_zero_temperature_is_valid():
    assert sensors_mapping.get_fresh_sensor_value([0.0], [100.0], 0, now=101.0) == 0.0
    assert sensors_mapping.get_fresh_sensor_value([0.0], None, 0, now=101.0) is None


@pytest.mark.parametrize('index', [10, 11, 12])
def test_cloudiness_requires_fresh_sky_and_selected_ambient(index):
    values = [0.0] * 110
    values[10:13] = [10.0, -5.0, 10.0]
    read_times = [100.0] * 110
    read_times[index] = 0.0
    config = _config(
        CLOUDINESS_INDEX_USE_GROUND_SENSOR=index == 12,
        CLOUDINESS_INDEX_GROUND_SENSOR='sensor_user_12',
    )
    assert sensors_mapping.calculate_cloudiness_index(
        config, lambda slot: sensors_mapping.get_fresh_sensor_value(
            values, read_times, slot, now=101.0)) is None


@pytest.mark.parametrize('data_factory', [tuple, iter])
def test_sensor_failure_invalidates_previous_readings_and_recovers(data_factory):
    class Sensor:
        slot = 10
        METADATA = {'count': 2}
        failed = False

        def update(self):
            if self.failed:
                raise SensorReadException('Disconnected')
            return {'data': data_factory((0.0, -5.0))}

    sensor = Sensor()
    worker = SimpleNamespace(
        sensors=[sensor], sensors_user_av=Array('f', [0.0] * 110),
        sensors_user_read_time_av=Array('d', [0.0] * 110),
    )
    SensorWorker.update_sensors(worker)
    assert worker.sensors_user_read_time_av[10] > 0.0
    assert worker.sensors_user_read_time_av[11] > 0.0

    sensor.failed = True
    SensorWorker.update_sensors(worker)
    assert worker.sensors_user_read_time_av[10:12] == [0.0, 0.0]
    assert worker.sensors_user_av[11] == -5.0

    sensor.failed = False
    SensorWorker.update_sensors(worker)
    assert worker.sensors_user_read_time_av[10] > 0.0


@pytest.mark.parametrize('error_type', [TypeError, ValueError, OverflowError])
@pytest.mark.parametrize('during_conversion', [False, True])
@pytest.mark.parametrize('with_timestamps', [False, True])
def test_unexpected_sensor_errors_propagate_and_invalidate_readings(error_type, during_conversion, with_timestamps):
    class InvalidReading:
        def __float__(self):
            raise error_type('Unexpected sensor error')

    class Sensor:
        slot = 10
        METADATA = {'count': 2}

        def update(self):
            if not during_conversion:
                raise error_type('Unexpected sensor error')
            return {'data': (0.0, InvalidReading())}

    read_times = Array('d', [100.0] * 110) if with_timestamps else None
    worker = SimpleNamespace(
        sensors=[Sensor()], sensors_user_av=Array('f', [0.0] * 110),
        sensors_user_read_time_av=read_times,
    )
    with pytest.raises(error_type, match='Unexpected sensor error'):
        SensorWorker.update_sensors(worker)
    if with_timestamps:
        assert read_times[10:12] == [0.0, 0.0]
        assert read_times[12] == 100.0


@pytest.mark.parametrize('key,value', [
    ('CLOUDINESS_INDEX_COEFFICIENT', 0.0), ('CLOUDINESS_INDEX_COEFFICIENT', -1.0),
    ('CLOUDINESS_INDEX_COEFFICIENT', 10.1), ('CLOUDINESS_INDEX_OFFSET', -100.1),
    ('CLOUDINESS_INDEX_OFFSET', 100.1),
])
def test_runtime_enforces_form_calibration_limits(key, value):
    assert sensors_mapping.calculate_cloudiness_index(
        _config(**{key: value}), _values({10: 10.0, 11: -5.0})) is None


def test_overflow_from_finite_readings_is_unavailable():
    assert sensors_mapping.calculate_cloudiness_index(
        _config(), _values({10: -1e308, 11: 1e308})) is None


def test_sensor_restart_clears_read_validity_and_passes_shared_timestamps(monkeypatch):
    function = _source_member('allsky.py', 'IndiAllSky', '_startSensorWorker')
    namespace = {'__package__': 'indi_allsky', 'logger': logging.getLogger('test')}
    _exec_source('allsky.py', [function], namespace)
    worker = SimpleNamespace(
        sensor_worker=None, sensor_worker_idx=0, config=_config(), sensor_q=None,
        sensor_error_q=None, sensors_temp_av=Array('f', [0.0] * 60),
        sensors_user_av=Array('f', [0.0] * 110), night_av=[0], astro_av=[],
        sensors_user_read_time_av=Array('d', [100.0] * 110),
    )
    monkeypatch.setattr(SensorWorker, 'start', lambda self: None)
    namespace['_startSensorWorker'](worker)
    assert worker.sensors_user_read_time_av[:] == [0.0] * 110
    assert worker.sensor_worker.sensors_user_read_time_av is worker.sensors_user_read_time_av


def test_legacy_sensor_worker_call_does_not_require_timestamps():
    worker = SensorWorker(1, {}, None, None, None, None, None, None)
    assert worker.sensors_user_read_time_av is None


@pytest.mark.parametrize('value,expected', [(50.04, 50.0), (0.0, 0.0), (None, '')])
def test_mqtt_sends_empty_payload_to_clear_unavailable_retained_index(value, expected):
    assignment = _source_assignment(ast.walk(_source_tree('image.py')), "mqtt_data['cloudiness_index']")
    namespace = {'mqtt_data': {}, 'i_ref': SimpleNamespace(cloudiness_index=value)}
    _exec_source('image.py', [assignment], namespace)
    assert namespace['mqtt_data']['cloudiness_index'] == expected

    message_loop = next(
        node for node in _source_member('filetransfer/paho_mqtt.py', 'paho_mqtt', 'put').body
        if isinstance(node, ast.For) and ast.unparse(node.iter) == 'mq_data.items()'
    )
    messages = {'mq_data': namespace['mqtt_data'], 'message_list': [], 'base_topic': 'test', 'qos': 0}
    _exec_source('filetransfer/paho_mqtt.py', [message_loop], messages)
    assert messages['message_list'] == [{
        'topic': 'test/cloudiness_index', 'payload': expected, 'qos': 0, 'retain': True,
    }]


@pytest.mark.parametrize('value', [50.0, 0.0, None])
def test_status_json_includes_numeric_or_null_cloudiness(value, tmp_path):
    function = _source_member('image.py', 'ImageWorker', 'write_status_json')
    namespace = {'constants': constants, 'io': io, 'json': json}
    _exec_source('image.py', [function], namespace)
    attributes = {node.attr: 1 for node in ast.walk(function)
                  if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                  and node.value.id == 'i_ref'}
    attributes.update(
        cloudiness_index=value, stars=[], lines=[],
        exp_date=SimpleNamespace(strftime=lambda format_string: '1'),
        smoke_rating=next(iter(constants.SMOKE_RATING_MAP_STR)),
    )
    worker = SimpleNamespace(
        config={}, sensors_temp_av=[0.0] * 60, sensors_user_av=[0.0] * 110,
        night_av=[0] * 10, position_av=[0.0] * 10, varlib_folder_p=tmp_path,
        exposure_o=SimpleNamespace(target_adu_found=True, current_adu_target=100),
        image_processor=SimpleNamespace(camera_sqm_raw_mag=20.0), adsb_aircraft_list=[],
    )
    namespace['write_status_json'](worker, SimpleNamespace(**attributes), 100, 100)
    status = json.loads((tmp_path / 'indi_allsky_status.json').read_text(encoding='utf-8'))
    assert status['cloudiness_index'] == value
