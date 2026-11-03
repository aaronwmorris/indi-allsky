import ast
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from multiprocessing import Array
from pathlib import Path
from types import SimpleNamespace

import pytest
from wtforms import Form, SelectField, StringField
from wtforms.validators import ValidationError

from indi_allsky import constants, sensors_mapping
from indi_allsky.devices import sensors
from indi_allsky.devices.exceptions import SensorException, SensorReadException
from indi_allsky.devices.sensors import rainSensorWhSpRg
from indi_allsky.sensor import SensorWorker


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def gauge_factory(monkeypatch, tmp_path):
    clock = SimpleNamespace(now=200000.0)
    monkeypatch.setattr(rainSensorWhSpRg.time, 'time', lambda: clock.now)

    class Button:
        def __init__(self, pin, **kwargs):
            self.pin = pin
            self.options = kwargs
            self.when_pressed = None
            self.closed = False

        def close(self):
            self.closed = True
            self.when_pressed = None

    monkeypatch.setitem(sys.modules, 'board', SimpleNamespace(D25=SimpleNamespace(id=25), D26=SimpleNamespace(id=26)))
    monkeypatch.setitem(sys.modules, 'gpiozero', SimpleNamespace(Button=Button))
    monkeypatch.setitem(sys.modules, 'gpiozero.exc', SimpleNamespace(GPIOZeroError=RuntimeError))
    gauges = []

    def create(pin='D25', **config):
        gauge = rainSensorWhSpRg.RainSensorWhSpRg(
            {'VARLIB_FOLDER': str(tmp_path), **config}, 'test', [], [], pin_1_name=pin,
        )
        gauges.append(gauge)
        return gauge

    yield create, clock, tmp_path
    for gauge in gauges:
        gauge.deinit()


def tip(gauge, clock, timestamp):
    clock.now = timestamp
    gauge.input_device.when_pressed()


def test_registration_and_gpio(gauge_factory):
    create, _, _ = gauge_factory
    gauge = create()
    assert sensors.blinka_rain_sensor_wh_sp_rg is rainSensorWhSpRg.RainSensorWhSpRg
    assert gauge.input_device.pin == 25
    assert gauge.input_device.options == {'pull_up': True, 'bounce_time': 0.02}
    assert gauge.METADATA['count'] == 2
    assert gauge.METADATA['types'] == (constants.SENSOR_PRECIPITATION_RATE, constants.SENSOR_PRECIPITATION)


def test_dry_reading_has_exact_shape(gauge_factory):
    create, _, _ = gauge_factory
    assert create().update() == {'rain_rate': 0.0, 'rain_24h': 0.0, 'data': (0.0, 0.0)}


def test_factory_calibration_not_update_interval_extrapolation(gauge_factory):
    create, clock, _ = gauge_factory
    gauge = create()
    gauge.input_device.when_pressed()
    clock.now += 15
    assert gauge.update()['data'] == pytest.approx((0.3, 0.3))
    clock.now += 15
    assert gauge.update()['data'] == pytest.approx((0.3, 0.3))


@pytest.mark.parametrize('age, expected', [
    (0, (0.3, 0.3)),
    (3599.999, (0.3, 0.3)),
    (3600, (0.0, 0.3)),
    (3600.001, (0.0, 0.3)),
    (86399.999, (0.0, 0.3)),
    (86400, (0.0, 0.0)),
    (86400.001, (0.0, 0.0)),
])
def test_rolling_window_boundaries(gauge_factory, age, expected):
    create, clock, _ = gauge_factory
    gauge = create()
    gauge.input_device.when_pressed()
    clock.now += age
    assert gauge.update()['data'] == pytest.approx(expected)


def test_windows_count_different_tips_and_prune(gauge_factory):
    create, clock, _ = gauge_factory
    gauge = create()
    tip(gauge, clock, 100000)
    tip(gauge, clock, 180000)
    tip(gauge, clock, 199000)
    tip(gauge, clock, 200000)
    assert gauge.update()['data'] == pytest.approx((0.6, 0.9))
    assert gauge._history.execute('SELECT COUNT(*) FROM tips').fetchone()[0] == 3


def test_history_survives_restart_and_expires_during_downtime(gauge_factory):
    create, clock, _ = gauge_factory
    first = create()
    first.input_device.when_pressed()
    first.update()
    first.deinit()
    clock.now += 7200
    second = create()
    assert second.update()['data'] == pytest.approx((0.0, 0.3))
    second.deinit()
    clock.now += 86400
    assert create().update()['data'] == (0.0, 0.0)


def test_clean_shutdown_flushes_pending_tips(gauge_factory):
    create, _, _ = gauge_factory
    first = create()
    device = first.input_device
    device.when_pressed()
    first.deinit()
    assert device.closed
    first.deinit()
    assert create().update()['data'] == pytest.approx((0.3, 0.3))


def test_history_is_per_gpio_not_label_or_user_slot(gauge_factory):
    create, _, _ = gauge_factory
    first = create()
    first.input_device.when_pressed()
    first.deinit()
    assert create('D26').update()['data'] == (0.0, 0.0)
    assert create('D25').update()['data'] == pytest.approx((0.3, 0.3))


@pytest.mark.parametrize('display', ['mm', 'in'])
def test_readings_remain_metric(gauge_factory, display):
    create, _, _ = gauge_factory
    gauge = create(PRECIPITATION_DISPLAY=display)
    gauge.input_device.when_pressed()
    assert gauge.update()['data'] == pytest.approx((0.3, 0.3))


def test_concurrent_callbacks_do_not_lose_tips(gauge_factory):
    create, _, _ = gauge_factory
    gauge = create()
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _: gauge._count_tip(), range(100)))
    assert gauge.update()['data'] == pytest.approx((30.0, 30.0))


def test_history_failure_is_error_and_pending_tips_are_retried(gauge_factory):
    create, _, _ = gauge_factory
    gauge = create()
    gauge.input_device.when_pressed()
    connection = gauge._history
    connection.execute('PRAGMA query_only = ON')
    with pytest.raises(SensorReadException, match='history failure'):
        gauge.update()
    assert len(gauge._pending_tips) == 1
    connection.execute('PRAGMA query_only = OFF')
    assert gauge.update()['data'] == pytest.approx((0.3, 0.3))
    assert gauge.update()['data'] == pytest.approx((0.3, 0.3))


def test_shutdown_history_failure_is_logged(gauge_factory, caplog):
    create, _, _ = gauge_factory
    gauge = create()
    gauge._history.execute('PRAGMA query_only = ON')
    gauge.input_device.when_pressed()
    gauge.deinit()
    assert 'Unable to save WH-SP-RG rainfall history on shutdown' in caplog.text


@pytest.mark.parametrize('pin', [None, '', 'INVALID'])
def test_invalid_pins_are_explicit_errors(gauge_factory, pin):
    create, _, _ = gauge_factory
    with pytest.raises(SensorException, match='pin'):
        create(pin)


def test_unwritable_state_directory_is_explicit_error(gauge_factory):
    create, _, tmp_path = gauge_factory
    invalid_dir = tmp_path.joinpath('file')
    invalid_dir.write_text('not a directory', encoding='ascii')
    with pytest.raises(SensorException, match='Unable to initialize'):
        create(VARLIB_FOLDER=str(invalid_dir))


def test_corrupt_history_is_not_silently_reset(gauge_factory):
    create, _, tmp_path = gauge_factory
    state_dir = tmp_path.joinpath('rain-gauges')
    state_dir.mkdir()
    state_dir.joinpath('wh-sp-rg-25.sqlite3').write_bytes(b'not a sqlite database')
    with pytest.raises(SensorException, match='Unable to initialize'):
        create()


def test_failed_gpio_initialization_is_explicit_error(gauge_factory, monkeypatch):
    create, _, _ = gauge_factory

    def fail(*args, **kwargs):
        raise RuntimeError('No GPIO backend')

    monkeypatch.setattr(sys.modules['gpiozero'], 'Button', fail)
    with pytest.raises(SensorException, match='No GPIO backend'):
        create()


def test_named_sensor_units_and_zero_values():
    config = {'TEMP_SENSOR': {
        'A_CLASSNAME': 'blinka_rain_sensor_wh_sp_rg',
        'A_USER_VAR_SLOT': 'sensor_user_20',
        'A_LABEL': 'Gauge',
    }}
    payload = sensors_mapping.format_named_sensors([0.0] * 60, [0.0] * 60, config)
    assert payload['sensor_a_rain_rate'] == {
        'name': 'Gauge (Rain Rate)', 'value': 0.0, 'unit': 'mm/h',
        'device_class': 'precipitation_intensity', 'slot': 20,
    }
    assert payload['sensor_a_rain_24h'] == {
        'name': 'Gauge (Rain 24h)', 'value': 0.0, 'unit': 'mm',
        'device_class': 'precipitation', 'slot': 21,
    }


def test_worker_populates_both_slots_and_aliases_without_changing_fc37(gauge_factory):
    create, _, _ = gauge_factory
    gauge = create()
    gauge.slot = 20
    gauge.input_device.when_pressed()
    worker = SensorWorker.__new__(SensorWorker)
    worker.sensors = [
        SimpleNamespace(slot=30, update=lambda: {'rain': 1, 'data': (1,)}),
        gauge,
    ]
    worker.sensors_user_av = Array('f', [0.0] * 110)
    worker.update_sensors()
    assert list(worker.sensors_user_av[20:22]) == pytest.approx([0.3, 0.3])
    assert worker.sensors_user_av[constants.SENSOR_USER_RAIN] == 1
    assert worker.sensors_user_av[constants.SENSOR_USER_RAIN_RATE] == pytest.approx(0.3)
    assert worker.sensors_user_av[constants.SENSOR_USER_RAIN_24H] == pytest.approx(0.3)


def test_worker_logs_history_errors_instead_of_publishing_zero(gauge_factory, caplog):
    create, _, _ = gauge_factory
    gauge = create()
    gauge.slot = 20
    worker = SensorWorker.__new__(SensorWorker)
    worker.sensors = [gauge]
    worker.sensors_user_av = Array('f', [0.0] * 110)
    gauge.input_device.when_pressed()
    worker.update_sensors()
    gauge._history.execute('PRAGMA query_only = ON')
    worker.update_sensors()
    assert 'SensorReadException' in caplog.text
    assert worker.sensors_user_av[20] == pytest.approx(0.3)
    gauge._history.execute('PRAGMA query_only = OFF')


@pytest.mark.parametrize('name', ['IMAGE_LABEL_TEMPLATE_validator', 'WEB_STATUS_TEMPLATE_validator'])
def test_rain_aliases_pass_template_validation(name):
    source = ROOT.joinpath('indi_allsky', 'flask', 'forms.py')
    tree = ast.parse(source.read_text(encoding='utf-8'))
    validator = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = {'ValidationError': ValidationError, 'datetime': datetime, 'timezone': timezone, 're': re}
    exec(compile(ast.Module(body=[validator], type_ignores=[]), str(source), 'exec'), namespace)
    namespace[name](None, SimpleNamespace(data='Rain {rain_rate:0.1f} mm/hr / {rain_24h:0.1f} mm'))


@pytest.fixture
def sensor_form():
    source = ROOT.joinpath('indi_allsky', 'flask', 'forms.py')
    tree = ast.parse(source.read_text(encoding='utf-8'))
    names = {'I2C_ADDRESS_validator', 'TEMP_SENSOR_I2C_ADDRESS_validator'}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {'ValidationError': ValidationError}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), namespace)
    form_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'IndiAllskyConfigForm')
    fields = {}
    for letter in 'ABCDEF':
        name = 'TEMP_SENSOR__' + letter
        fields[name + '_CLASSNAME'] = SelectField(choices=[
            ('blinka_rain_sensor_wh_sp_rg', 'WH-SP-RG'),
            ('blinka_rain_sensor_fc37', 'FC-37'),
            ('blinka_temp_sensor_bme280_i2c', 'BME280'),
        ])
        assignment = next(node for node in form_class.body if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == name + '_I2C_ADDRESS' for target in node.targets))
        fields[name + '_I2C_ADDRESS'] = eval(
            compile(ast.Expression(body=assignment.value), str(source), 'eval'),
            {'StringField': StringField, **namespace},
        )
    return type('SensorAddressForm', (Form,), fields)


@pytest.mark.parametrize('letter', list('ABCDEF'))
@pytest.mark.parametrize('classname', ['blinka_rain_sensor_fc37', 'blinka_rain_sensor_wh_sp_rg'])
@pytest.mark.parametrize('address', ['', 'not-an-i2c-address'])
def test_gpio_sensors_skip_i2c_validation(sensor_form, letter, classname, address):
    form = sensor_form(data={
        'TEMP_SENSOR__' + letter + '_CLASSNAME': classname,
        'TEMP_SENSOR__' + letter + '_I2C_ADDRESS': address,
    })
    field = getattr(form, 'TEMP_SENSOR__' + letter + '_I2C_ADDRESS')
    assert field.validate(form), field.errors


@pytest.mark.parametrize('letter', list('ABCDEF'))
@pytest.mark.parametrize('address, valid', [('', False), (' ', False), ('invalid', False), ('0x80', False), ('-1', False), ('0x40', True)])
def test_other_sensors_keep_required_i2c_validation(sensor_form, letter, address, valid):
    form = sensor_form(data={
        'TEMP_SENSOR__' + letter + '_CLASSNAME': 'blinka_temp_sensor_bme280_i2c',
        'TEMP_SENSOR__' + letter + '_I2C_ADDRESS': address,
    })
    field = getattr(form, 'TEMP_SENSOR__' + letter + '_I2C_ADDRESS')
    assert field.validate(form) is valid


def test_dropdown_places_gauge_beside_fc37():
    tree = ast.parse(ROOT.joinpath('indi_allsky', 'flask', 'forms.py').read_text(encoding='utf-8'))
    form = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'IndiAllskyConfigForm')
    choices = next(node.value for node in form.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == 'TEMP_SENSOR__CLASSNAME_choices' for target in node.targets))
    rain = next(value for key, value in zip(choices.keys, choices.values)
                if isinstance(key, ast.Constant) and key.value == 'Rain Sensors')
    assert [entry[0] for entry in ast.literal_eval(rain)] == [
        'blinka_rain_sensor_fc37', 'blinka_rain_sensor_wh_sp_rg',
    ]
