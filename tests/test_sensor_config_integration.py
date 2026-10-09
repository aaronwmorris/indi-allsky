import ast
import copy
import ipaddress
import json
import logging
import socket
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import flask
from cryptography.fernet import Fernet
from flask_sqlalchemy import SQLAlchemy
import psutil
import pytest

from indi_allsky import asi676mc, constants, sensor_slots
from indi_allsky.devices import sensors
from indi_allsky.devices.exceptions import DeviceControlException, SensorException
from indi_allsky.exceptions import ConfigSaveException
from indi_allsky.sensors_mapping import build_slot_label_map
from indi_allsky.version import __config_level__
from tests.test_sensor_slots import execute, method, owner, tree


@pytest.fixture
def config_endpoint(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    app = flask.Flask(__name__)
    app.config.update(TESTING=True, LOGIN_DISABLED=True, WTF_CSRF_ENABLED=False,
                      SECRET_KEY='sensor-tests', SQLALCHEMY_DATABASE_URI='sqlite://',
                      PASSWORD_KEY=Fernet.generate_key().decode())
    db = SQLAlchemy(app)

    # Use the production schema, form, views and persistence classes, isolating
    # only application bootstrap and unrelated Linux/camera services.
    models = tree('indi_allsky/flask/models.py')
    models.body = [node for node in models.body if not (
        isinstance(node, ast.ImportFrom) and node.level == 1 and node.module is None)]
    namespace = execute(models.body, {'__name__': 'sensor_test_models', 'db': db})
    forms = tree('indi_allsky/flask/forms.py')
    forms.body = [node for node in forms.body if not (
        isinstance(node, ast.Import) and any(name.name == 'dbus' for name in node.names)
    ) and not (
        isinstance(node, ast.ImportFrom) and node.level == 1 and node.module in (None, 'models')
    )]
    namespace.update(__package__='indi_allsky.flask')
    execute(forms.body, namespace)
    namespace.update(
        SENSOR_DEFAULTS=sensor_slots.SENSOR_DEFAULTS, OrderedDict=OrderedDict,
        Path=Path, datetime=datetime, timezone=timezone, Fernet=Fernet,
        ConfigSaveException=ConfigSaveException, app=flask.current_app,
        logger=logging.getLogger('sensor-tests'), __config_level__=__config_level__,
    )
    config = tree('indi_allsky/config.py')
    execute([node for node in config.body if isinstance(node, ast.ClassDef)
             and node.name in ('IndiAllSkyConfigBase', 'IndiAllSkyConfig')],
            namespace)

    class FormView:
        def get_context(self):
            return {}

    namespace.update(
        FormView=FormView, BaseView=object, login_required=lambda func: func,
        request=flask.request, jsonify=flask.jsonify, asi676mc=asi676mc,
        socket=socket, ipaddress=ipaddress, json=json,
        _visible_asi676mc_cameras=lambda: [],
    )
    execute([owner('indi_allsky/flask/views.py', name)
             for name in ('ConfigView', 'AjaxConfigView')], namespace)
    monkeypatch.setattr(psutil, 'sensors_temperatures', lambda: {}, raising=False)
    monkeypatch.setattr(psutil, 'net_if_addrs', lambda: {})
    app.add_url_rule('/youtube-callback', 'indi_allsky.youtube_oauth2callback_view',
                     lambda: '')

    with app.app_context():
        db.create_all()
        User = namespace['IndiAllSkyDbUserTable']
        db.session.add(User(username='system', password='unused', name='System',
                            email='system@example.org', active=True, admin=True))
        Config = namespace['IndiAllSkyConfig']
        defaults = copy.deepcopy(Config._base_config)
        defaults.update(IMAGE_FOLDER='.', VARLIB_FOLDER='.')
        for letter in sensor_slots.SENSOR_LETTERS[6:]:
            for field in sensor_slots.SENSOR_FIELDS:
                del defaults['TEMP_SENSOR'][letter + '_' + field]
        db.session.add(namespace['IndiAllSkyDbConfigTable'](
            data=defaults, level='test', note='initial'))
        db.session.commit()

        def context():
            view = namespace['ConfigView']()
            view.indi_allsky_config = Config().config
            view.indi_allsky_config_id = 1
            view.camera = SimpleNamespace(minGain=0, maxGain=100, minBinning=1,
                                          maxBinning=4, minExposure=0.001, maxExposure=120)
            view.latest_image_entry = None
            view.validate_longitude_timezone = lambda: True
            view._miscDb = SimpleNamespace(getState=lambda name: None)
            return view.get_context()

        @app.get('/config')
        def get_config():
            form = context()['form_config']
            return flask.jsonify({field.name: field.data for field in form})

        @app.post('/config')
        def save_config():
            view = namespace['AjaxConfigView']()
            view._indi_allsky_config_obj = Config()
            view.indi_allsky_config = view._indi_allsky_config_obj.config
            return view.dispatch_request()

        yield app.test_client(), Config, namespace, context
        db.session.remove()
        db.drop_all()


@pytest.mark.parametrize('encrypted', [False, True])
def test_all_letters_survive_production_save_reload_and_remove(config_endpoint, encrypted):
    client, Config, _, _ = config_endpoint
    payload = client.get('/config').get_json()
    payload['ENCRYPT_PASSWORDS'] = encrypted
    for index, letter in enumerate(sensor_slots.SENSOR_LETTERS):
        payload.update({
            'TEMP_SENSOR__' + letter + '_CLASSNAME': 'kernel_temp_sensor_ds18x20_w1',
            'TEMP_SENSOR__' + letter + '_LABEL': 'Roof ' + letter,
            'TEMP_SENSOR__' + letter + '_USER_VAR_SLOT': 'sensor_user_' + str(10 + index),
        })
    response = client.post('/config', json=payload)
    assert response.status_code == 200, response.get_json()
    config = Config().config
    assert config['ENCRYPT_PASSWORDS'] is encrypted
    saved = config['TEMP_SENSOR']
    assert all(saved[letter + '_LABEL'] == 'Roof ' + letter for letter in sensor_slots.SENSOR_LETTERS)
    reloaded = client.get('/config').get_json()
    assert all(reloaded[key] == value for key, value in payload.items() if key.startswith('TEMP_SENSOR__'))
    reloaded['TEMP_SENSOR__G_CLASSNAME'] = ''
    response = client.post('/config', json=reloaded)
    assert response.status_code == 200, response.get_json()
    assert Config().config['TEMP_SENSOR']['G_CLASSNAME'] == ''
    assert client.get('/config').get_json()['TEMP_SENSOR__G_CLASSNAME'] == ''


def test_omitted_configured_sensor_is_still_validated(config_endpoint):
    client, Config, _, _ = config_endpoint
    payload = client.get('/config').get_json()
    payload.update(TEMP_SENSOR__Z_CLASSNAME='kernel_temp_sensor_ds18x20_w1',
                   TEMP_SENSOR__Z_USER_VAR_SLOT='sensor_user_10')
    response = client.post('/config', json=payload)
    assert response.status_code == 200, response.get_json()
    legacy_payload = {key: value for key, value in payload.items()
                      if not key.startswith('TEMP_SENSOR__Z_')}
    legacy_payload.update(TEMP_SENSOR__A_CLASSNAME='kernel_temp_sensor_ds18x20_w1',
                          TEMP_SENSOR__A_USER_VAR_SLOT='sensor_user_10')
    previous_id = Config().config_id
    response = client.post('/config', json=legacy_payload)
    assert response.status_code == 400, response.get_json()
    assert any('Overlapping' in error for error in response.get_json()['TEMP_SENSOR__Z_USER_VAR_SLOT'])
    assert Config().config_id == previous_id


def test_legacy_save_payload_preserves_new_sensor_fields(config_endpoint):
    client, Config, _, _ = config_endpoint
    payload = client.get('/config').get_json()
    payload.update(TEMP_SENSOR__Z_CLASSNAME='kernel_temp_sensor_ds18x20_w1',
                   TEMP_SENSOR__Z_USER_VAR_SLOT='sensor_user_59',
                   TEMP_SENSOR__Z_LABEL='Roof probe', TEMP_SENSOR__Z_PIN_1='28-0123456789ab',
                   TEMP_SENSOR__Z_TITLE_TEMPLATE='{label:s}: {probe:s}')
    response = client.post('/config', json=payload)
    assert response.status_code == 200, response.get_json()
    saved = copy.deepcopy(Config().config['TEMP_SENSOR'])
    omitted = {f'TEMP_SENSOR__{letter}_{field}' for letter in sensor_slots.SENSOR_LETTERS[6:]
               for field in sensor_slots.SENSOR_FIELDS}
    legacy_payload = {key: value for key, value in payload.items() if key not in omitted}
    response = client.post('/config', json=legacy_payload)
    assert response.status_code == 200, response.get_json()
    assert Config().config['TEMP_SENSOR'] == saved
    assert client.get('/config').get_json()['TEMP_SENSOR__Z_LABEL'] == 'Roof probe'


def test_invalid_new_driver_does_not_create_saved_configuration(config_endpoint):
    client, Config, _, _ = config_endpoint
    payload = client.get('/config').get_json()
    payload['TEMP_SENSOR__Z_CLASSNAME'] = 'unknown'
    previous_id = Config().config_id
    response = client.post('/config', json=payload)
    assert response.status_code == 400, response.get_json()
    assert response.get_json()['TEMP_SENSOR__Z_CLASSNAME']
    assert Config().config_id == previous_id


def test_removed_sensor_does_not_leak_labels_into_next_form(config_endpoint):
    client, _, _, context = config_endpoint
    payload = client.get('/config').get_json()
    payload.update(TEMP_SENSOR__Z_CLASSNAME='kernel_temp_sensor_ds18x20_w1',
                   TEMP_SENSOR__Z_LABEL='Roof probe', TEMP_SENSOR__Z_USER_VAR_SLOT='sensor_user_59')
    response = client.post('/config', json=payload)
    assert response.status_code == 200, response.get_json()
    with flask.current_app.test_request_context():
        configured_form = context()['form_config']
        assert 'Roof probe' in configured_form.SENSOR_SLOT_choices['User Sensors'][59][1]
    payload['TEMP_SENSOR__Z_CLASSNAME'] = ''
    response = client.post('/config', json=payload)
    assert response.status_code == 200, response.get_json()
    with flask.current_app.test_request_context():
        removed_form = context()['form_config']
        assert 'Roof probe' not in removed_form.SENSOR_SLOT_choices['User Sensors'][59][1]
        assert 'Roof probe' in configured_form.SENSOR_SLOT_choices['User Sensors'][59][1]
        assert 'Roof probe' not in removed_form.CHARTS__CUSTOM_SLOT_1.choices['User Sensors'][59][1]
        assert 'Roof probe' in configured_form.CHARTS__CUSTOM_SLOT_1.choices['User Sensors'][59][1]


@pytest.mark.parametrize('letter', sensor_slots.SENSOR_LETTERS)
def test_incomplete_sensor_defaults_match_runtime_capture_and_named_data(letter, monkeypatch):
    monkeypatch.setattr(psutil, 'sensors_temperatures', lambda: {}, raising=False)
    config = {'TEMP_SENSOR': {letter + '_CLASSNAME': 'kernel_temp_sensor_ds18x20_w1'}}
    class Probe(sensors.kernel_temp_sensor_ds18x20_w1):
        def __init__(self, config, label, night, astro, **kwargs):
            self.name = label
            self.kwargs = kwargs

    monkeypatch.setattr(sensors, 'kernel_temp_sensor_ds18x20_w1', Probe)
    devices = sensor_slots.initialize_sensors(config, [], [])
    capture = owner('indi_allsky/capture.py', 'CaptureWorker')
    slots = next(node.value for node in capture.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == 'SENSOR_SLOTS'
                         for target in node.targets))
    worker = SimpleNamespace(config=config, SENSOR_SLOTS=ast.literal_eval(slots))
    namespace = {'__package__': 'indi_allsky', 'constants': constants,
                 'logger': logging.getLogger('sensor-tests')}
    execute([method('indi_allsky/capture.py', 'update_sensor_slot_labels', 'CaptureWorker')], namespace)
    namespace['update_sensor_slot_labels'](worker)
    index = constants.SENSOR_INDEX_MAP[sensor_slots.SENSOR_DEFAULTS[letter]['USER_VAR_SLOT']]
    device = next(device for device in devices if isinstance(device, Probe))
    assert device.slot == index
    assert device.kwargs == {'pin_1_name': 'notdefined', 'pin_2_name': 'notdefined',
                             'i2c_address': sensor_slots.SENSOR_DEFAULTS[letter]['I2C_ADDRESS']}
    named = build_slot_label_map(config)
    assert index in named
    assert named[index]['name'] == worker.SENSOR_SLOTS[index][1]


@pytest.mark.parametrize('exception', [DeviceControlException, SensorException])
def test_initialization_failure_keeps_configured_slot_and_reports_error(monkeypatch, caplog, exception):
    def fail(*args, **kwargs):
        raise exception('disconnected')

    monkeypatch.setattr(sensors, 'kernel_temp_sensor_ds18x20_w1', fail)
    with caplog.at_level(logging.ERROR, logger='indi_allsky'):
        devices = sensor_slots.initialize_sensors({'TEMP_SENSOR': {
            'Z_CLASSNAME': 'kernel_temp_sensor_ds18x20_w1', 'Z_LABEL': 'Roof',
            'Z_USER_VAR_SLOT': 'sensor_user_59'}}, [], [])
    assert isinstance(devices[-1], sensors.sensor_simulator)
    assert devices[-1].slot == 59
    assert devices[-1].name == 'Sensor Z'
    assert 'Error initializing sensor Z: disconnected' in caplog.text


def test_inactive_legacy_simulators_keep_original_constructor_arguments(monkeypatch):
    calls = []

    def simulator(config, name, night, astro, **kwargs):
        calls.append((name, kwargs))
        return SimpleNamespace()

    monkeypatch.setattr(sensors, 'sensor_simulator', simulator)
    devices = sensor_slots.initialize_sensors({'TEMP_SENSOR': {'A_LABEL': 'Unused label'}}, [], [])
    assert calls == [('Sensor ' + letter, {}) for letter in 'ABCDEF']
    assert [device.slot for device in devices] == [10, 20, 30, 40, 50, 55]


def test_sensor_test_utility_keeps_legacy_warnings_and_initializes_z(monkeypatch, caplog):
    monkeypatch.setattr(sensors, 'kernel_temp_sensor_ds18x20_w1',
                        lambda config, label, night, astro, **kwargs: SimpleNamespace(name=label))
    namespace = {'logger': logging.getLogger('sensor-utility-tests')}
    execute([method('misc/sensor_test.py', 'init_sensors', 'TestSensors')], namespace)
    worker = SimpleNamespace(config={'TEMP_SENSOR': {
        'Z_CLASSNAME': 'kernel_temp_sensor_ds18x20_w1', 'Z_USER_VAR_SLOT': 'sensor_user_59'}},
        night_av=[], astro_av=[])
    with caplog.at_level(logging.WARNING, logger='sensor-utility-tests'):
        namespace['init_sensors'](worker)
    assert len(worker.sensors) == 7
    assert worker.sensors[-1].name == 'Sensor Z'
    assert worker.sensors[-1].slot == 59
    assert [record.getMessage() for record in caplog.records] == [
        'No sensor ' + letter + ' - Initializing sensor simulator' for letter in 'ABCDEF']
