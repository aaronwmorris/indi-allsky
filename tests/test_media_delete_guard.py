import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from flask import Flask, current_app

from indi_allsky import night_movie
from indi_allsky.flask import db, views
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable as Camera, IndiAllSkyDbImageTable as Image, IndiAllSkyDbVideoTable as Movie,
    IndiAllSkyDbPanoramaImageTable as Panorama, IndiAllSkyDbPanoramaVideoTable as PanoramaMovie,
    IndiAllSkyDbStateTable as State,
)
from indi_allsky.flask.syncapi_views import SyncApiBaseView
from indi_allsky.media_delete import suppress_flushed_periods


@pytest.fixture
def station(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', INDI_ALLSKY_IMAGE_FOLDER=str(tmp_path))
    db.init_app(app)
    today = date(2026, 11, 7)
    monkeypatch.setattr('indi_allsky.utils.IndiAllSkyDateCalcs.getDayDate', lambda self: today)
    with app.app_context():
        db.create_all()
        camera = Camera(name='local', uuid='delete-guard-local', local=True, latitude=0., longitude=0.)
        remote = Camera(name='synced', uuid='delete-guard-synced', local=False, latitude=0., longitude=0.)
        db.session.add_all([camera, remote])
        db.session.commit()
        yield camera, remote, today, dict(NIGHT_SUN_ALT_DEG=-6, IMAGE_EXPIRE_DAYS=7, TIMELAPSE_EXPIRE_DAYS=10)


def frame(model, camera, day, night):
    metadata = dict(camera_id=camera.id, dayDate=day, night=night, exposure=1, gain=1,
                    filename=f'{camera.id}-{day}-{night}.jpg')
    if model is Image:
        metadata['adu'] = 0.
    return model(**metadata)


def test_bulk_flush_marks_each_recoverable_period_including_inflight_sources(station):
    camera, remote, today, config = station
    recent, older, expired = (today - timedelta(days=n) for n in (1, 6, 8))
    db.session.add_all([
        frame(Image, camera, recent, True), frame(Image, camera, recent, False),
        frame(Panorama, camera, recent, False), frame(Panorama, camera, older, True),
        frame(Image, camera, older, True), frame(Panorama, camera, expired, True),
        frame(Panorama, camera, today, True), frame(Panorama, remote, recent, False),
        PanoramaMovie(camera_id=camera.id, dayDate=older, night=False, filename='only-movie.mp4'),
    ])
    key = night_movie.attempt_key(camera.id, recent, False, True)
    token = json.dumps({'day': recent.isoformat(), 'source': 'encoding'})
    db.session.add(State(key=key, value=token))
    db.session.commit()
    suppress_flushed_periods(config, camera.id)
    assert {record.key for record in State.query.all()} == {
        night_movie.attempt_key(camera.id, recent), key,
        night_movie.attempt_key(camera.id, older, True, True), night_movie.attempt_key(camera.id, older, False, True),
    }
    assert all(json.loads(record.value)['deleted'] for record in State.query.all())
    assert not night_movie.lock_repair(camera.id, recent, token, False, True)


def test_daytime_flush_only_marks_local_day_panoramas(station):
    camera, remote, today, config = station
    day = today - timedelta(days=1)
    db.session.add_all([frame(Panorama, camera, day, False), frame(Panorama, camera, day, True),
                        frame(Image, camera, day, True), frame(Panorama, remote, day, False)])
    db.session.commit()
    suppress_flushed_periods(config, remote.id)
    suppress_flushed_periods(config, camera.id, daytime_only=True)
    assert State.query.one().key == night_movie.attempt_key(camera.id, day, False, True)


def test_sync_delete_marks_only_the_selected_local_recoverable_video(station, tmp_path):
    camera, remote, today, config = station
    day = today - timedelta(days=1)
    for model, cam, night in [(PanoramaMovie, remote, True), (Movie, camera, False), (PanoramaMovie, camera, False)]:
        path = tmp_path / f'{model.__tablename__}-{cam.id}-{night}.mp4'
        path.write_bytes(b'video')
        movie = model(camera_id=cam.id, dayDate=day, night=night, filename=str(path))
        db.session.add(movie)
        db.session.commit()
        SyncApiBaseView.deleteFile(SimpleNamespace(model=model), movie.id, cam.id)
        assert not path.exists()
    assert State.query.one().key == night_movie.attempt_key(camera.id, day, False, True)


@pytest.mark.parametrize('action,night,kinds', [
    ('delete_video_k_st_p', True, (False, True)), ('delete_panorama_video', False, (True,)),
    ('delete_video', False, ()), ('delete_video', True, (False,)),
])
def test_ui_delete_marks_only_requested_products_even_before_publication(station, monkeypatch, action, night, kinds):
    camera, _, today, _ = station
    day = today - timedelta(days=1)
    monkeypatch.setattr(views, 'current_user', SimpleNamespace(is_admin=True))
    monkeypatch.setattr(views, 'IndiAllskyTimelapseGeneratorForm', lambda **kw: SimpleNamespace(validate=lambda: True))
    request_data = dict(CAMERA_ID=camera.id, ACTION_SELECT=action, DAY_SELECT=f'{day}_{"night" if night else "day"}')
    with current_app.test_request_context(method='POST', json=request_data):
        result = views.AjaxTimelapseGeneratorView.dispatch_request(SimpleNamespace(verify_admin_network=lambda: True))
    assert result.status_code == 200
    assert {row.key for row in State.query.all()} == {night_movie.attempt_key(camera.id, day, night, p) for p in kinds}
