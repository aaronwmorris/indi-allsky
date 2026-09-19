import ast
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from flask_sqlalchemy import SQLAlchemy

from indi_allsky.exceptions import ConfigSaveException
from indi_allsky.lens_solver.calibration import displacement
from tests.flask.test_virtualsky import run_node
from tests.lens_solver.test_calibration import saved_model
from tests.flask.test_virtualsky_requests import endpoint, VALUES


@pytest.fixture(scope='module')
def camera_models():
    # Load the real schema with an isolated ORM registry. Importing the Flask
    # package normally also starts imports of camera/D-Bus infrastructure.
    path = Path(__file__).resolve().parents[2] / 'indi_allsky/flask/models.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.ImportFrom) and node.level == 1 and node.module is None)]
    namespace = {'__name__': 'virtualsky_test_models', 'db': SQLAlchemy()}
    exec(compile(tree, str(path), 'exec'), namespace)
    return namespace['IndiAllSkyDbCameraTable'], namespace['IndiAllSkyDbImageTable']


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('binmode', [None, 1, 2, 4])
@pytest.mark.parametrize('dimensions', [(3000, 2000), (None, None)])
def test_solve_endpoint_uses_real_image_binning(endpoint, camera_models, tmp_path,
                                              enabled, binmode, dimensions):
    app, view, namespace, saved = endpoint
    Camera, Image = camera_models
    camera = Camera(id=7, uuid='test-camera', alt=54, width=dimensions[0], height=dimensions[1],
                    data={'vs_pointing_azimuth': 123})
    image_file = tmp_path / 'sky.png'
    image_file.touch()
    image = Image(camera_id=7, binmode=binmode, filename=str(image_file))
    assert not hasattr(image, 'binning')  # the capture database calls this binmode
    image.getFilesystemPath = lambda: image_file

    class Query:
        def __init__(self, row):
            self.row = row

        def filter(self, *args):
            return self

        def first(self):
            return self.row

    namespace['IndiAllSkyDbCameraTable'] = SimpleNamespace(id=Camera.id, query=Query(camera))
    namespace['IndiAllSkyDbImageTable'] = SimpleNamespace(
        camera_id=Image.camera_id, createDate=Image.createDate, query=Query(image))
    view.cameraSetup = lambda **kwargs: None
    view.getCameraPrivacyLatLong = lambda selected: (53, 11)
    view.camera_time_offset = 30
    calls = []

    def solve(*args, **kwargs):
        calls.append((args, kwargs))
        return {'success': True, 'calibration': saved_model() if enabled else None}

    namespace['IndiAllSkyLensSolver'] = lambda config: SimpleNamespace(solve=solve)
    with app.test_request_context(json=dict(VALUES, action='solve', camera_id=7,
            timestamp=1770000000, LATITUDE_OFFSET=0, CALIBRATION_ENABLED=enabled)):
        response = app.make_response(view.dispatch_request())
    assert response.status_code == 200, response.get_json()
    result = response.get_json()
    assert result['success']
    assert calls[0][0][3] == 1770000000-30
    hints = {'lens_altitude': 54, 'pointing_azimuth': 123}
    if enabled:
        binning = binmode or 1
        hints['binning'] = binning
        if dimensions[0]:
            hints['sensor_shape'] = (dimensions[1]//binning, dimensions[0]//binning)
    assert calls[0][1] == hints
    if enabled:
        assert result['calibration']['camera_uuid'] == 'test-camera'
        assert result['calibration']['context'][2] == 30
    assert saved == []


def test_calibration_javascript():
    run_node('--test', 'tests/flask/virtualsky_calibration.test.cjs')


def test_python_and_browser_apply_identical_correction():
    model = saved_model()
    xy = np.random.default_rng(4).uniform(-1.4, 1.4, (1000, 2))
    actual = json.loads(run_node('-e', '''
const api = require('./indi_allsky/flask/static/js/virtualsky-calibration.js');
const input = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
console.log(JSON.stringify(input.xy.map(([u,v]) => api.delta(input.model,u,v))));
''', input=json.dumps(dict(model=model, xy=xy.tolist()))))
    np.testing.assert_allclose(actual, displacement(xy, model), atol=1e-14, rtol=0)


def test_endpoint_saves_validated_calibration_and_disabled_preference(endpoint):
    app, view, _, saved = endpoint
    model = saved_model()
    for enabled in (True, False):
        with app.test_request_context(json=dict(VALUES, action='save', LENS_ALTITUDE=90,
                CALIBRATION_ENABLED=enabled, CALIBRATION=model)):
            assert view.dispatch_request().get_json()['success']
        assert saved[-1]['VIRTUALSKY']['CALIBRATION_ENABLED'] is enabled
        assert saved[-1]['VIRTUALSKY']['CALIBRATION'] == model
    with app.test_request_context(json=dict(VALUES, action='save', LENS_ALTITUDE=90,
            CALIBRATION_ENABLED=True, CALIBRATION={'version': 1})):
        assert view.dispatch_request()[1] == 400
    assert len(saved) == 2


@pytest.fixture
def config_store(endpoint):
    app, view, namespace, saved = endpoint
    path = Path(__file__).resolve().parents[2] / 'indi_allsky/config.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    tree.body = [n for n in tree.body if isinstance(n, ast.ClassDef)
                 and n.name in ('IndiAllSkyConfigBase', 'IndiAllSkyConfig')]
    scope = dict(OrderedDict=OrderedDict, Path=Path, app=app, datetime=datetime,
                 timezone=timezone, ConfigSaveException=ConfigSaveException,
                 IndiAllSkyDbUserTable=MagicMock())
    exec(compile(tree, str(path), 'exec'), scope)
    cls = scope['IndiAllSkyConfig']
    # Keep the real save, validation, encryption and reload paths. Only replace
    # database access, preserving its JSON serialization boundary.
    cls._getConfigEntry = lambda self: SimpleNamespace(
        data=deepcopy(saved[-1]), id=len(saved), level='test', createDate=datetime.now())

    def store(self, config, user, note, encrypted):
        saved.append(json.loads(json.dumps(config)))
        return SimpleNamespace(id=len(saved))

    cls._setConfigEntry = store
    saved.append(deepcopy(cls._base_config))
    obj = cls()
    view._indi_allsky_config_obj = obj
    view.indi_allsky_config = obj.config
    namespace['ConfigSaveException'] = ConfigSaveException
    return app, view, cls, saved


@pytest.mark.parametrize('version', [1, 2])
def test_calibration_survives_real_config_save_and_reload(config_store, version):
    app, view, cls, saved = config_store
    model = saved_model(version)
    for enabled, calibration in [(True, model), (False, model), (False, None), (True, None), (True, model)]:
        with app.test_request_context(json=dict(VALUES, action='save', LENS_ALTITUDE=90,
                RADIAL_DISTORTION=0.08 if version == 2 else 0, PRECESSION=version == 2,
                CALIBRATION_ENABLED=enabled, CALIBRATION=calibration)):
            response = app.make_response(view.dispatch_request())
        assert response.status_code == 200, response.get_json()
        reloaded = cls()
        assert reloaded.config['VIRTUALSKY']['CALIBRATION'] == calibration
        assert reloaded.config['VIRTUALSKY']['CALIBRATION_ENABLED'] is enabled
        assert reloaded.config['VIRTUALSKY']['RADIAL_DISTORTION'] == (0.08 if version == 2 else 0)
        assert reloaded.config['VIRTUALSKY']['PRECESSION'] is (version == 2)
        view._indi_allsky_config_obj = reloaded
        view.indi_allsky_config = reloaded.config
    assert len(saved) == 6


@pytest.mark.parametrize('key,value', [('CALIBRATION', []), ('CALIBRATION', 'invalid'),
    ('CALIBRATION', 1), ('CALIBRATION', True), ('POINTING_AZIMUTH', 'invalid')])
def test_config_type_validation_remains_strict(config_store, key, value):
    _, view, _, _ = config_store
    view.indi_allsky_config['VIRTUALSKY'][key] = value
    with pytest.raises(ConfigSaveException, match='wrong type'):
        view._indi_allsky_config_obj._validateConfig()
