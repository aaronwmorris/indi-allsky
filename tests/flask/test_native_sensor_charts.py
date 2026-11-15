"""Exercise the native chart query on old, remote and recovering sensor data."""
from datetime import datetime, timedelta
from types import SimpleNamespace

from flask import Flask

from indi_allsky.flask import db
from indi_allsky.flask.models import IndiAllSkyDbCameraTable as Camera, IndiAllSkyDbImageTable as Frame
from indi_allsky.flask.views import JsonChartView


def test_external_sensor_recovers_from_a_gap_to_zero(tmp_path):
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', INDI_ALLSKY_IMAGE_FOLDER=str(tmp_path))
    db.init_app(app)
    with app.app_context():
        db.create_all()
        camera = Camera(name='remote', uuid='remote-camera', local=False,
                        data={'custom_chart_1_key': 'sensor_user_59', 'custom_chart_2_key': 'sensor_user_2'})
        db.session.add(camera)
        db.session.flush()
        start = datetime(2026, 1, 1, 20)
        for index, data in enumerate([
                {'sensor_user_59': 1.5},                       # A legacy frame has no validity mask.
                {'sensor_user_59': 1.5, 'sensor_valid_mask': 0},  # Last cached value while disconnected.
                {'sensor_user_59': 0.0, 'sensor_valid_mask': 1 << 49},
                None,                                         # A synced image without measurement data.
        ]):
            db.session.add(Frame(camera_id=camera.id, createDate=start + timedelta(seconds=index),
                                 dayDate=start.date(), filename=f'{index}.jpg', exposure=1, gain=1,
                                 adu=1, temp=5, night=True, stars=2, data=data))
        db.session.commit()
        view = SimpleNamespace(camera=camera, indi_allsky_config={})
        series = JsonChartView.getChartData(view, camera.id, start + timedelta(minutes=1), 120)
        assert [p['y'] for p in series['custom_1']] == [1.5, None, 0.0, None]
        assert [p['y'] for p in series['custom_2']] == [0, 0, 0, 0]
