import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


import pytest


@pytest.fixture
def sync_env(tmp_path, monkeypatch, request):
    """Real models, SQLite and SyncAPI views without camera/D-Bus services."""
    import importlib.util
    import json
    import tempfile
    import types
    import uuid
    from copy import deepcopy
    from datetime import datetime, timedelta
    from urllib.parse import urlsplit

    from cryptography.fernet import Fernet
    from flask import Flask, current_app
    from flask.views import View
    from flask_sqlalchemy import SQLAlchemy
    import sqlalchemy as sa

    root = Path(__file__).resolve().parents[1]
    database = SQLAlchemy()

    def package(name, path):
        module = types.ModuleType(name)
        module.__path__ = [str(path)]
        monkeypatch.setitem(sys.modules, name, module)
        return module

    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, root / path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    flask_package = package('indi_allsky.flask', root / 'indi_allsky/flask')
    flask_package.db = database
    models = load('indi_allsky.flask.models', 'indi_allsky/flask/models.py')
    flask_package.models = models
    misc_db = load('indi_allsky.flask.miscDb', 'indi_allsky/flask/miscDb.py')
    config = {'SYNCAPI': {'ENABLE': True, 'MODE': 'archive', 'BASEURL': 'https://nas/indi-allsky',
                         'USERNAME': 'tester', 'APIKEY': 'test-api-key', 'CERT_BYPASS': False}, 'IMAGE_FOLDER': str(tmp_path / 'source')}
    config_module = types.ModuleType('indi_allsky.config')
    config_module.IndiAllSkyConfig = lambda: types.SimpleNamespace(config=deepcopy(models.IndiAllSkyDbConfigTable.query.order_by(models.IndiAllSkyDbConfigTable.id.desc()).first().data))
    monkeypatch.setitem(sys.modules, 'indi_allsky.config', config_module)
    transfers = package('indi_allsky.filetransfer', root / 'indi_allsky/filetransfer')
    exceptions = load('indi_allsky.filetransfer.exceptions', 'indi_allsky/filetransfer/exceptions.py')
    transfers.exceptions = exceptions
    for name in ('ConnectionFailure', 'TransferFailure', 'AuthenticationFailure', 'CertificateValidationFailure', 'PermissionFailure'):
        setattr(transfers, name, getattr(exceptions, name))
    load('indi_allsky.filetransfer.generic', 'indi_allsky/filetransfer/generic.py')
    transport = load('indi_allsky.filetransfer.requests_syncapi_v1', 'indi_allsky/filetransfer/requests_syncapi_v1.py')
    transfers.requests_syncapi_v1 = transport.requests_syncapi_v1
    worker_module = load('indi_allsky.syncapi_sync', 'indi_allsky/syncapi_sync.py')
    import indi_allsky
    monkeypatch.setattr(indi_allsky, 'syncapi_sync', worker_module, raising=False)
    load('indi_allsky.syncapi_schedule', 'indi_allsky/syncapi_schedule.py')

    def make_app(name):
        image_path = tmp_path / name
        image_path.mkdir()
        app = Flask(name)
        app.config.update(TESTING=True, SECRET_KEY='test-secret', PASSWORD_KEY=Fernet.generate_key().decode(),
                          SQLALCHEMY_DATABASE_URI='sqlite:///' + (tmp_path / (name + '.sqlite')).as_posix(),
                          INDI_ALLSKY_IMAGE_FOLDER=str(image_path), LOGIN_DISABLED=False)
        database.init_app(app)

        def close_database():
            with app.app_context():
                database.session.remove()
                database.engine.dispose()

        # Each app owns a connection pool; close both even if fixture setup fails.
        request.addfinalizer(close_database)
        with app.app_context():
            database.create_all()
        return app

    source_app, receiver_app = make_app('source'), make_app('receiver')
    flask_package.create_app = lambda: source_app
    base_package = types.ModuleType('indi_allsky.flask.base_views')

    class BaseView(View):
        def __init__(self, **kwargs):
            self.indi_allsky_config = {'IMAGE_FOLDER': current_app.config['INDI_ALLSKY_IMAGE_FOLDER']}
            self._miscDb = misc_db.miscDb(self.indi_allsky_config)

    base_package.BaseView = BaseView
    monkeypatch.setitem(sys.modules, base_package.__name__, base_package)
    receiver = load('indi_allsky.flask.syncapi_views', 'indi_allsky/flask/syncapi_views.py')
    receiver_app.register_blueprint(receiver.bp_syncapi_allsky)
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    events = types.ModuleType('indi_allsky.events')
    events.event_manager = types.SimpleNamespace(broadcast=lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, events.__name__, events)
    sensors = types.ModuleType('indi_allsky.sensors_mapping')
    sensors.get_latest_sensors_payload = lambda *a, **k: {}
    monkeypatch.setitem(sys.modules, sensors.__name__, sensors)
    with receiver_app.app_context():
        user = models.IndiAllSkyDbUserTable(username='tester', password='unused', email='test@example.invalid')
        user.setApiKey('test-api-key', receiver_app.config['PASSWORD_KEY'])
        database.session.add(user)
        database.session.commit()

    calls = []
    receiver_client = receiver_app.test_client()

    def send(method, url, **kwargs):
        stream = kwargs['data']
        encoder = getattr(stream, 'encoder', stream)
        metadata = json.loads(encoder.fields['metadata'][1].getvalue())
        calls.append((method, urlsplit(url).path, metadata))
        body = b''.join(iter(lambda: stream.read(8192), b''))
        response = receiver_client.open(urlsplit(url).path, method=method, headers=kwargs['headers'], data=body)
        return types.SimpleNamespace(status_code=response.status_code, text=response.get_data(as_text=True), json=response.get_json)

    monkeypatch.setattr(transport.requests, 'put', lambda url, **kwargs: send('PUT', url, **kwargs))
    monkeypatch.setattr(transport.requests, 'get', lambda url, **kwargs: send('GET', url, **kwargs))
    monkeypatch.setattr(transport.requests, 'post', lambda url, **kwargs: send('POST', url, **kwargs))
    with source_app.app_context():
        camera = models.IndiAllSkyDbCameraTable(name='Local camera', uuid=str(uuid.uuid4()), local=True, hidden=False)
        database.session.add(camera)
        database.session.add(models.IndiAllSkyDbConfigTable(level='test', note='test', data=deepcopy(config)))
        database.session.commit()
        worker_module.set_state('CONFIG_ID', 1)

        def asset(kind='image', age=2, camera_id=None, **overrides):
            model = worker_module.MEDIA[kind][0]
            created = (datetime.now() - timedelta(days=age)).replace(microsecond=0)
            filename = tmp_path / 'source' / (str(uuid.uuid4()) + ('.jpg' if kind in ('image', 'panoramaimage', 'keogram', 'startrail') else '.mp4'))
            filename.write_bytes(uuid.uuid4().bytes)
            values = {'camera_id': camera.id if camera_id is None else camera_id, 'filename': str(filename),
                      'createDate': created, 'dayDate': created.date(), 'thumbnail_uuid': None,
                      'data': {'custom_feature': 'preserved'}, 'fileSize': filename.stat().st_size}
            for column in model.__table__.columns:
                if column.name in values or column.primary_key or column.nullable or column.default or column.server_default:
                    continue
                if isinstance(column.type, sa.DateTime):
                    value = created
                elif isinstance(column.type, sa.Date):
                    value = created.date()
                elif isinstance(column.type, sa.String):
                    value = 'test'
                else:
                    value = 1
                values[column.name] = value
            if hasattr(model, 'success'):
                values['success'] = True
            values.update(overrides)
            entry = model(**values)
            database.session.add(entry)
            database.session.commit()
            return entry

        def thumbnail(entry, sync_id=None):
            path = tmp_path / 'source' / (str(uuid.uuid4()) + '.jpg')
            path.write_bytes(b'thumbnail')
            thumb = models.IndiAllSkyDbThumbnailTable(uuid=str(uuid.uuid4()), filename=str(path), camera_id=entry.camera_id,
                                                   createDate=entry.createDate, sync_id=sync_id, fileSize=9)
            database.session.add(thumb)
            entry.thumbnail_uuid = thumb.uuid
            database.session.commit()
            return thumb

        def run(types=None):
            task = worker_module.request_sync(config, types or ['image'])
            worker = worker_module.SyncApiSyncWorker(source_app, task.id)
            worker.execute()
            return worker_module.status()

        def save_schedule(payload, apply=True):
            from indi_allsky.syncapi_schedule import save_settings
            save_settings(config, payload)
            row = models.IndiAllSkyDbConfigTable(level='test', note='schedule', data=deepcopy(config))
            database.session.add(row)
            database.session.commit()
            if apply:
                worker_module.set_state('CONFIG_ID', row.id)
            return row.id

        yield types.SimpleNamespace(app=source_app, nas=receiver_app, db=database, models=models, sync=worker_module,
                                    config=config, camera=camera, asset=asset, thumbnail=thumbnail, run=run,
                                    transport=transport, errors=exceptions, calls=calls, send=send, load=load, receiver=receiver,
                                    save_schedule=save_schedule)
