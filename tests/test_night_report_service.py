"""Publication, retries and archive lifecycle of Night Report attachments."""
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import json
import sys

from flask import Flask
from PIL import Image
import numpy as np
import pytest

from indi_allsky import night_report_service as reports
from indi_allsky.events import event_manager
from indi_allsky.flask import db
from indi_allsky.flask.models import (IndiAllSkyDbCameraTable as Camera,
                                     IndiAllSkyDbKeogramTable as Keogram)


@pytest.fixture(autouse=True)
def broadcast(monkeypatch):
    listener = Mock()
    monkeypatch.setattr(event_manager, 'broadcast', listener)
    return listener


@pytest.fixture
def station(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', INDI_ALLSKY_IMAGE_FOLDER=str(tmp_path))
    db.init_app(app)
    with app.app_context():
        db.create_all()
        camera = Camera(name='Station', uuid='night-report-test', latitude=52.7, longitude=12.4,
                        local=True, hidden=False)
        db.session.add(camera)
        db.session.commit()
        day = date.today() - timedelta(days=2)
        path = tmp_path / 'keogram.jpg'
        Image.new('RGB', (120, 120), 'gray').save(path)
        kg = Keogram(camera_id=camera.id, filename=path.name, dayDate=day, night=True,
                     success=True, data={'avg_stars': 150})
        db.session.add(kg)
        db.session.commit()
        worker = SimpleNamespace(config={'IMAGE_FOLDER': str(tmp_path), 'VARLIB_FOLDER': str(tmp_path)},
                                 image_dir=tmp_path, _shutdown=False, activity=None)
        prepared = {'title': 'Night Report', 'samples': [{'timestamp': 1000}],
                    'keogram_rgb': np.zeros((100, 1, 3), np.uint8), 'frame_times': [1000], 'events': []}
        prepare = Mock(return_value=prepared)
        def render(png, csv, **kwargs):
            Image.new('RGB', (240, 240), 'green').save(png)
            Path(csv).write_text('timestamp,sky,lux,air,dew\n1000,-30,0.01,2,1\n')
        renderer = Mock(side_effect=render)
        # Service contract tests are independent of the astronomical renderer.
        monkeypatch.setitem(sys.modules, 'indi_allsky.night_report_data', SimpleNamespace(prepare_report=prepare))
        monkeypatch.setitem(sys.modules, 'indi_allsky.night_report_render', SimpleNamespace(render_report=renderer))
        yield worker, camera, kg, prepare, renderer


def test_publishes_validated_pair_once_and_preserves_keogram(station, broadcast):
    w, camera, kg, prepare, render = station
    original = kg.getFilesystemPath().read_bytes()
    source = object()
    assert reports.build_report(w, camera, kg, keogram_source=source)
    assert prepare.call_args.kwargs['keogram_source'] is source
    assert reports.report_ready(kg)
    assert kg.data['avg_stars'] == 150
    assert kg.data['night_report']['status'] == 'ready'
    assert kg.getFilesystemPath().read_bytes() == original
    assert not reports.build_report(w, camera, kg)
    assert render.call_count == 1
    manifest = json.loads(reports.report_paths(kg)['manifest'].read_text())
    assert all(len(file['sha256']) == 64 for file in manifest['files'].values())
    broadcast.assert_called_once_with('night_report_complete', {
        'camera_id': camera.id, 'keogram_id': kg.id, 'dayDate': kg.dayDate.isoformat(),
        'created_at': manifest['created_at'],
    })


def test_failed_notification_keeps_report_ready(station, broadcast):
    w, camera, kg, _, _ = station
    broadcast.side_effect = OSError('relay unavailable')
    assert reports.build_report(w, camera, kg)
    assert reports.report_ready(kg)
    assert kg.data['night_report']['status'] == 'ready'
    assert not reports.build_report(w, camera, kg)
    broadcast.assert_called_once()


def test_uncommitted_publication_sends_no_event(station, broadcast, monkeypatch):
    w, camera, kg, _, _ = station
    commit = db.session.commit

    def fail_ready_commit():
        if (kg.data.get('night_report') or {}).get('status') == 'ready':
            raise RuntimeError('database write failed')
        commit()

    monkeypatch.setattr(db.session, 'commit', fail_ready_commit)
    assert not reports.build_report(w, camera, kg)
    assert kg.data['night_report']['status'] == 'waiting'
    broadcast.assert_not_called()


def test_changed_or_missing_csv_is_not_ready_and_can_be_rebuilt(station):
    w, camera, kg, _, render = station
    assert reports.build_report(w, camera, kg)
    csv = reports.report_paths(kg)['csv']
    csv.write_text('bad')
    assert not reports.report_ready(kg)
    assert reports.build_report(w, camera, kg)
    csv.unlink()
    assert not reports.report_ready(kg)
    assert reports.build_report(w, camera, kg)
    assert render.call_count == 3


def test_failed_renderer_never_publishes_half_a_pair_and_retries_with_backoff(station, broadcast):
    w, camera, kg, _, render = station
    original_render = render.side_effect
    def fail(png, csv, **kwargs):
        Image.new('RGB', (240, 240), 'red').save(png)
        raise OSError('write interrupted')
    render.side_effect = fail
    assert not reports.build_report(w, camera, kg)
    assert kg.success
    assert not reports.report_ready(kg)
    assert not any(path.exists() for path in reports.report_paths(kg).values())
    assert kg.data['night_report']['next_retry'] > reports.time.time()
    assert not reports.build_report(w, camera, kg)
    assert render.call_count == 1
    broadcast.assert_not_called()
    render.side_effect = original_render
    assert reports.build_report(w, camera, kg, force=True)
    assert reports.report_ready(kg)
    broadcast.assert_called_once()


def test_failed_forced_refresh_keeps_previous_valid_download(station):
    w, camera, kg, _, render = station
    assert reports.build_report(w, camera, kg)
    previous = {k: p.read_bytes() for k, p in reports.report_paths(kg).items()}
    render.side_effect = ValueError('invalid sources')
    assert not reports.build_report(w, camera, kg, force=True)
    assert reports.report_ready(kg)
    assert previous == {k: p.read_bytes() for k, p in reports.report_paths(kg).items()}


def test_archive_pause_daytime_and_remote_camera_are_skipped(station):
    w, camera, kg, prepare, _ = station
    w.config['CAPTURE_PAUSE'] = True
    assert not reports.build_report(w, camera, kg)
    w.config['CAPTURE_PAUSE'] = False
    kg.night = False
    assert not reports.build_report(w, camera, kg)
    kg.night = True
    camera.local = False
    assert not reports.build_report(w, camera, kg)
    assert not prepare.called


def test_deletion_during_render_does_not_publish_orphan_sidecars(station):
    w, camera, kg, _, render = station
    paths = reports.report_paths(kg)
    original = render.side_effect
    def removed(*args, **kwargs):
        original(*args, **kwargs)
        kg.deleteAsset()
        db.session.delete(kg)
        db.session.commit()
    render.side_effect = removed
    assert not reports.build_report(w, camera, kg)
    assert not any(p.exists() for p in paths.values())


def test_deleting_keogram_removes_its_report_but_preserves_other_files(station):
    w, camera, kg, _, _ = station
    assert reports.build_report(w, camera, kg)
    paths = reports.report_paths(kg)
    untouched = w.image_dir / 'keogram-other.night-report.png'
    untouched.write_bytes(b'other report')
    kg.deleteAsset()
    assert not kg.getFilesystemPath().exists()
    assert not any(p.exists() for p in paths.values())
    assert untouched.read_bytes() == b'other report'
    assert kg.data['night_report']['deleted']


def test_killed_worker_leaves_retry_deadline_and_recovers_after_it(station, monkeypatch):
    w, camera, kg, _, render = station
    original = render.side_effect
    render.side_effect = KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        reports.build_report(w, camera, kg)
    assert not reports.report_ready(kg)
    assert not reports.build_report(w, camera, kg)
    deadline = kg.data['night_report']['next_retry']
    monkeypatch.setattr(reports.time, 'time', lambda: deadline + 1)
    render.side_effect = original
    assert reports.build_report(w, camera, kg)


def test_archive_scan_backfills_existing_keogram_without_rebuilding_movies(station):
    w, camera, kg, prepare, render = station
    assert reports.backfill_reports(w, date.today())
    assert reports.report_ready(kg)
    assert not reports.backfill_reports(w, date.today())
    assert render.call_count == 1


def test_selection_redraw_reuses_cache_after_source_images_expire(station, broadcast):
    w, camera, kg, prepare, render = station
    assert reports.report_options(camera.id) is None
    reports.save_report_options(camera.id, ['lux'])
    assert reports.build_report(w, camera, kg)
    assert render.call_args.kwargs['selected_metrics'] == ['lux']
    prepare.side_effect = AssertionError('raw images have expired')
    reports.save_report_options(camera.id, ['air_temperature', 'dew_point'])
    assert reports.build_report(w, camera, kg, force=True)
    assert prepare.call_count == 1
    assert render.call_args.kwargs['selected_metrics'] == ['air_temperature', 'dew_point']
    assert reports.report_ready(kg)
    assert broadcast.call_count == 2


def test_corrupt_cache_falls_back_to_original_frames(station):
    w, camera, kg, prepare, _ = station
    assert reports.build_report(w, camera, kg)
    reports.report_paths(kg)['source_npz'].write_bytes(b'corrupt cache')
    assert reports.build_report(w, camera, kg, force=True)
    assert prepare.call_count == 2


def test_selection_changed_during_render_cannot_publish_stale_report(station):
    w, camera, kg, _, render = station
    reports.save_report_options(camera.id, ['lux'])
    original = render.side_effect
    def change_selection(*args, **kwargs):
        original(*args, **kwargs)
        reports.save_report_options(camera.id, ['sky_temperature'])
    render.side_effect = change_selection
    assert not reports.build_report(w, camera, kg)
    assert not reports.report_ready(kg)
    assert not any(path.exists() for path in reports.report_paths(kg).values())
    assert kg.data['night_report']['next_retry'] == 0


def test_options_follow_callers_transaction(station):
    _, camera, _, _, _ = station
    reports.save_report_options(camera.id, ['lux'], commit=False)
    db.session.rollback()
    assert reports.report_options(camera.id) is None
    reports.save_report_options(camera.id, ['lux', 'lux'])
    assert reports.report_options(camera.id) == ['lux']
    reports.save_report_options(camera.id, [])
    assert reports.report_options(camera.id) == []
    with pytest.raises(ValueError):
        reports.save_report_options(camera.id, [None])


def test_old_cached_report_recovers_without_querying_expired_source_images(station):
    from sqlalchemy import event
    w, camera, kg, prepare, _ = station
    kg.dayDate = date.today() - timedelta(days=20)
    db.session.commit()
    assert reports.build_report(w, camera, kg)
    reports.report_paths(kg)['png'].unlink()
    prepare.side_effect = AssertionError('raw source images have expired')
    statements = []
    def queries(connection, cursor, statement, parameters, context, many):
        statements.append(statement.lower())
    event.listen(db.engine, 'before_cursor_execute', queries)
    try:
        assert reports.backfill_reports(w, date.today())
    finally:
        event.remove(db.engine, 'before_cursor_execute', queries)
    assert reports.report_ready(kg)
    assert prepare.call_count == 1
    assert not any('from image ' in sql or 'from image\n' in sql for sql in statements)


def test_old_cache_scan_respects_retention_and_rotates_two_rows_per_pass(station):
    w, camera, kg, prepare, _ = station
    kg.dayDate = date.today() - timedelta(days=20)
    db.session.commit()
    assert reports.build_report(w, camera, kg)
    reports.report_paths(kg)['csv'].unlink()
    for age in (18, 19):
        db.session.add(Keogram(camera_id=camera.id, filename=f'uncached-{age}.jpg',
                               dayDate=date.today()-timedelta(days=age), night=True, success=True))
    db.session.commit()
    assert not reports.backfill_reports(w, date.today())
    assert reports.backfill_reports(w, date.today())
    assert reports.report_ready(kg)
    reports.report_paths(kg)['csv'].unlink()
    w.config['TIMELAPSE_EXPIRE_DAYS'] = 15
    assert not reports.backfill_reports(w, date.today())
    assert not reports.report_ready(kg)


def test_invalid_retained_cache_does_not_query_raw_sources_and_backs_off(station):
    w, camera, kg, prepare, render = station
    kg.dayDate = date.today() - timedelta(days=20)
    db.session.commit()
    assert reports.build_report(w, camera, kg)
    paths = reports.report_paths(kg)
    paths['png'].unlink()
    paths['source_npz'].write_bytes(b'invalid')
    assert reports.backfill_reports(w, date.today())
    assert not reports.report_ready(kg)
    assert prepare.call_count == render.call_count == 1
    assert not reports.backfill_reports(w, date.today())
