from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import pytest
from sqlalchemy import event


@pytest.fixture
def station(monkeypatch):
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    db = SQLAlchemy(app)

    class Image(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        camera_id = db.Column(db.Integer, nullable=False)
        createDate = db.Column(db.DateTime, nullable=False)
        exclude = db.Column(db.Boolean, default=False)
        sqm = db.Column(db.Float)
        data = db.Column(db.JSON)
        remote_url = db.Column(db.String)
        s3_key = db.Column(db.String)

    # Import this helper in isolation from the full Flask UI and camera drivers.
    path = Path(__file__).resolve().parents[2] / 'indi_allsky/flask/companion_charts.py'
    spec = importlib.util.spec_from_file_location('indi_allsky.flask._test_companion_charts', path)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, 'indi_allsky.flask.models', SimpleNamespace(IndiAllSkyDbImageTable=Image))
    spec.loader.exec_module(mod)
    slot_keys = {0: 'camera_temp', 7: 'device_sqm', 8: 'camera_sqm', 10: 'sensor_a_temperature',
                 11: 'sensor_a_relative_humidity', 14: 'sensor_b_temperature', 15: 'sensor_b_sky_temperature',
                 35: 'sensor_c_lux', 36: 'sensor_c_visible', 39: 'sensor_c_sqm'}
    monkeypatch.setattr(mod, 'build_slot_label_map', lambda config: {i: {'key': k} for i, k in slot_keys.items()})
    tz = ZoneInfo('Europe/Berlin')
    now = datetime(2026, 11, 7, 18, tzinfo=tz)
    camera = SimpleNamespace(id=1, local=True, data={}, web_nonlocal_images=False)
    statements = []
    with app.app_context():
        db.create_all()
        event.listen(db.engine, 'before_cursor_execute',
                     lambda conn, cursor, statement, params, context, many: statements.append(statement))

        def add(minute, data, **kwargs):
            row = Image(camera_id=kwargs.pop('camera_id', 1), createDate=now.replace(tzinfo=None)+timedelta(minutes=minute),
                        data=data, **kwargs)
            db.session.add(row)

        def charts(requested=None, config=None):
            db.session.commit()
            statements.clear()
            return mod.companion_charts(camera, config or {}, now, tz, requested)

        yield camera, add, charts, statements


def test_defaults_and_scoped_window(station):
    _, add, charts, sql = station
    add(-121, {'sensor_user_15': -90})
    add(-120, {'sensor_user_15': 0.0, 'sensor_user_35': 0.0})
    add(-60, {'sensor_user_15': -20, 'private': 'never included'})
    add(-50, {'sensor_user_15': 100}, camera_id=2)
    add(-40, {'sensor_user_15': 100}, exclude=True)
    add(0, {'temp_display': 'f', 'sensor_user_15': 32, 'sensor_user_35': 2.5})
    add(1, {'sensor_user_15': 100})
    metrics, defaults, series = charts()
    assert defaults == ['sensor_user_15', 'sensor_user_35']
    assert {m['id'] for m in metrics} == {'sensor_user_10','sensor_user_11','sensor_user_15',
                                          'sensor_user_35','sensor_user_39','jsqm'}
    assert [p[1] for p in series[0]['points']] == [0.0, -20.0, 0.0]
    assert [p[1] for p in series[1]['points']] == [0.0, None, 2.5]
    assert series[0]['points'][0][0] == '2026-11-07T16:00:00+01:00'
    assert len(sql) == 1
    assert 'row_number()' in sql[0].lower() and 'json_extract' in sql[0].lower()


def test_off_unknown_duplicate_and_selection_limit(station):
    _, add, charts, sql = station
    add(0, {'sensor_user_10': 3.0, 'sensor_user_11': 64.0, 'secret': 55.0})
    for requested in [['none', 'none'], ['secret'], ['none','unknown','sensor_user_10']]:
        assert charts(requested)[2] == []
        assert sql == []
    series = charts(['none','sensor_user_11'])[2]
    assert [(s['label'],s['unit'],s['points'][0][1]) for s in series] == [('Relative Luftfeuchte','%',64.0)]
    series = charts(['sensor_user_10','sensor_user_10'])[2]
    assert len(series) == 1 and series[0]['label'] == 'Lufttemperatur'


def test_remote_uses_its_own_probe_names_and_units(station):
    camera, add, charts, _ = station
    camera.local = False
    camera.data = {'sensor_user_12':'MLX90614 (i2c) - remote - Sky Temperature',
                   'sensor_user_18':'TSL2591 (i2c) - remote - Lux', 'sensor_user_15':'User Slot 15'}
    add(-1, {'temp_display':'f', 'sensor_user_12':32, 'sensor_user_18':0})
    add(0, {'sensor_user_12':90, 'sensor_user_18':4})
    metrics, defaults, series = charts(config={'TEMP_DISPLAY':'f','CAMERA_SQM':{'ENABLE':True}})
    assert [m['id'] for m in metrics] == ['sensor_user_12','sensor_user_18','jsqm']
    assert defaults == ['sensor_user_12','sensor_user_18']
    assert series[0]['unit'] == '°C' and [p[1] for p in series[0]['points']] == [0.0,None]
    camera.data = {}
    metrics, defaults, _ = charts()
    assert defaults == ['jsqm'] and metrics[0]['unit'] == 'rel.'


def test_sqm_sentinels_and_remote_image_visibility(station):
    camera, add, charts, _ = station
    camera.web_nonlocal_images = True
    add(-45, {'sensor_user_39': 19.99})
    add(-30, {'sensor_user_39': 0, 'sensor_user_8': 0}, remote_url='https://example.invalid/image')
    add(-15, {'sensor_user_39': 20.4, 'sensor_user_8': 20.8}, s3_key='image.jpg')
    add(0, {'sensor_user_39':'nan','sensor_user_8':'broken'}, s3_key='image.jpg')
    metrics, _, series = charts(['sensor_user_39','sensor_user_8'], {'CAMERA_SQM': {'ENABLE':True}})
    assert any(m['id']=='sensor_user_8' for m in metrics)
    assert [p[1] for p in series[0]['points']] == [None,20.4,None]
    assert [p[1] for p in series[1]['points']] == [None,20.8,None]


def test_one_point_per_minute_preserves_entire_range(station):
    _, add, charts, _ = station
    for minute in range(-120,0):
        for seconds in (0,10,40):
            add(minute + seconds/60, {'sensor_user_35':seconds})
    points = charts(['sensor_user_35'])[2][0]['points']
    assert len(points) == 120
    assert all(value == 40 for _,value in points)
    assert datetime.fromisoformat(points[-1][0]).astimezone(timezone.utc).hour == 16
