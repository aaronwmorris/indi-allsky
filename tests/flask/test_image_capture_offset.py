from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from pathlib import Path
import sys
from threading import Barrier
from types import ModuleType, SimpleNamespace
from zoneinfo import ZoneInfo

from flask import Flask, current_app
from flask.views import View
from flask_sqlalchemy import SQLAlchemy
import pytest


@pytest.fixture
def station(tmp_path, monkeypatch):
    """Run the actual writer, Sync view and ORM without starting camera services."""
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///' + str(tmp_path / 'test.sqlite'),
                      INDI_ALLSKY_IMAGE_FOLDER=str(tmp_path))
    pkg = ModuleType('indi_allsky._image_sync_test')
    pkg.__path__ = [str(Path(__file__).resolve().parents[2] / 'indi_allsky/flask')]
    pkg.db = SQLAlchemy(app)
    monkeypatch.setitem(sys.modules, pkg.__name__, pkg)
    monkeypatch.setitem(sys.modules, pkg.__name__ + '.base_views', SimpleNamespace(BaseView=View))
    monkeypatch.setitem(sys.modules, 'cv2', ModuleType('cv2'))
    with app.app_context():
        try:
            models = import_module(pkg.__name__ + '.models')
            writer = import_module(pkg.__name__ + '.miscDb').miscDb({})
            sync = import_module(pkg.__name__ + '.syncapi_views')
            from indi_allsky.events import event_manager
            from indi_allsky import sensors_mapping
            monkeypatch.setattr(event_manager, 'broadcast', lambda *args: None)
            monkeypatch.setattr(sensors_mapping, 'get_latest_sensors_payload', lambda config: {})
            pkg.db.create_all()
            camera = models.IndiAllSkyDbCameraTable(uuid='station', name='Station', local=False)
            pkg.db.session.add(camera)
            pkg.db.session.commit()
            view = object.__new__(sync.SyncApiImageView)
            view.image_dir, view._miscDb = tmp_path, writer
            yield camera, view, models
        finally:
            for name in list(sys.modules):
                if name.startswith(pkg.__name__ + '.'):
                    del sys.modules[name]


def metadata(stamp, offset, **extra):
    fields = dict(createDate=stamp, dayDate='20261024', utc_offset=offset, exposure=1,
                  exp_elapsed=1, gain=1, binmode=1, temp=0, adu=1, stable=True, moonmode=False,
                  moonphase=10, night=True, adu_roi=False, calibrated=False, stars=0,
                  sqm=10, detections=0, process_elapsed=1, height=100, width=100)
    fields.update(extra)
    return fields


@pytest.mark.parametrize(('original', 'wire', 'expected'), [
    (None, 0, 0), (None, 19800.0, 19800), (0, 7200, 0), (None, None, None),
])
def test_writer_preserves_known_capture_offset(station, tmp_path, original, wire, expected):
    camera, view, _ = station
    sensor = {'reading': 4}
    if original is not None:
        sensor['utc_offset'] = original
    row = view._miscDb.addImage(tmp_path / 'one.jpg', camera.id,
                                metadata(datetime(2026, 10, 24, 23), wire, data=sensor))
    assert row.data['reading'] == 4
    assert row.data.get('utc_offset') == expected
    assert ('utc_offset' in row.data) == (expected is not None)
    assert ('utc_offset' in sensor) == (original is not None)


def test_sync_keeps_both_occurrences_and_retries(station, tmp_path):
    camera, view, models = station
    wall = datetime(2026, 10, 25, 2, 15)
    pixels = [[2, 4, 8]] * 5

    def upload(offset, payload):
        upload_path = tmp_path / 'request.jpg'
        upload_path.write_bytes(payload)
        stamp = wall.replace(tzinfo=timezone(timedelta(seconds=offset))).timestamp()
        return view.processPost(camera, metadata(stamp, offset, keogram_pixels=pixels), upload_path)

    first = upload(7200, b'first capture')
    later = upload(3600, b'later capture')
    assert first.id != later.id and first.createDate == later.createDate == wall
    assert first.data['utc_offset'] == 7200 and later.data['utc_offset'] == 3600
    assert first.getFilesystemPath().name == f'ccd{camera.id}_20261025_021500.jpg'
    assert later.getFilesystemPath().name == f'ccd{camera.id}_20261025_021500_1792890900.jpg'
    assert upload(7200, b'first capture').id == first.id
    assert upload(3600, b'later capture').id == later.id
    assert first.getFilesystemPath().read_bytes() == b'first capture'
    assert later.getFilesystemPath().read_bytes() == b'later capture'
    assert models.IndiAllSkyDbImageTable.query.count() == 2
    assert models.IndiAllSkyDbLongTermKeogramTable.query.count() == 2


def test_remote_retry_preserves_legacy_file_and_fills_missing_media(station, tmp_path):
    camera, view, _ = station
    wall = datetime(2026, 10, 25, 2, 15)
    folder = view.getImageFolder(wall, True, camera)
    path = folder / f'ccd{camera.id}_20261025_021500.jpg'
    path.write_bytes(b'archived camera frame')
    legacy = view._miscDb.addImage(path, camera.id, metadata(wall, None))
    stamp = wall.replace(tzinfo=timezone.utc).timestamp()
    info = metadata(stamp, 0)
    upload = tmp_path / 'request.jpg'
    upload.write_bytes(b'archived camera frame')
    assert view.processPost(camera, info, upload).id == legacy.id
    upload.write_bytes(b'')
    new = view.processPost(camera, info, upload)
    assert new.id != legacy.id and not new.getFilesystemPath().exists()
    upload.write_bytes(b'other exposure')
    assert view.processPost(camera, info, upload).id == new.id
    assert new.getFilesystemPath().read_bytes() == b'other exposure'
    assert path.read_bytes() == b'archived camera frame'


def test_delayed_upload_uses_capture_time_not_receiver_current_offset(station, tmp_path, monkeypatch):
    camera, view, _ = station
    receiver_zone = ZoneInfo('America/New_York')

    class ReceiverClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return SimpleNamespace(astimezone=lambda: datetime(2026, 7, 15, 12, tzinfo=receiver_zone))

        @classmethod
        def fromtimestamp(cls, stamp, tz=None):
            if tz is None:
                return datetime.fromtimestamp(stamp, receiver_zone).replace(tzinfo=None)
            return datetime.fromtimestamp(stamp, tz)

    monkeypatch.setattr(sys.modules[type(view).__module__], 'datetime', ReceiverClock)
    wall = datetime(2026, 1, 10, 2, 15)
    source_offset = 19800
    stamp = wall.replace(tzinfo=timezone(timedelta(seconds=source_offset))).timestamp()
    upload = tmp_path / 'received.jpg'
    upload.write_bytes(b'image')
    row = view.processPost(camera, metadata(stamp, source_offset), upload)
    assert row.createDate == wall and row.data['utc_offset'] == source_offset


def test_concurrent_sync_retries_reserve_one_file_per_instant(station, tmp_path):
    camera, view, models = station
    station_id = SimpleNamespace(id=camera.id, uuid=camera.uuid)
    app = current_app._get_current_object()
    barrier = Barrier(3)
    wall = datetime(2026, 10, 25, 2, 15)

    def send(index, offset):
        with app.app_context():
            upload = tmp_path / f'transfer_{index}.jpg'
            upload.write_bytes(str(offset).encode())
            stamp = wall.replace(tzinfo=timezone(timedelta(seconds=offset))).timestamp()
            barrier.wait(timeout=10)
            return view.processPost(station_id, metadata(stamp, offset), upload).id

    with ThreadPoolExecutor(max_workers=3) as pool:
        sent = [pool.submit(send, i, offset) for i, offset in enumerate((7200, 3600, 7200))]
        ids = [future.result(timeout=10) for future in sent]
    assert ids[0] == ids[2] and ids[0] != ids[1]
    for row in models.IndiAllSkyDbImageTable.query.all():
        assert row.getFilesystemPath().read_bytes() == str(row.data['utc_offset']).encode()
