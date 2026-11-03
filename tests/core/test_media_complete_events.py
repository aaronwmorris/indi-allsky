import ast
import sys
import types
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from indi_allsky import events


ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- payload and broadcast helper

def _entry(**kwargs):
    base = dict(id=7, filename='ccd_x/timelapse/20261010/allsky-timelapse_ccd1_20261010_night.mp4',
                camera_id=1, createDate=datetime(2026, 10, 11, 7, 2, 3), dayDate=date(2026, 10, 10),
                night=True, frames=1834)
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_payload_includes_final_values_and_skips_missing_fields():
    payload = events.media_complete_payload(_entry(framerate=25.0, fileSize=48123456, width=None))

    assert payload == {
        'id': 7,
        'filename': 'ccd_x/timelapse/20261010/allsky-timelapse_ccd1_20261010_night.mp4',
        'camera_id': 1,
        'createDate': '2026-10-11 07:02:03',
        'dayDate': '2026-10-10',
        'night': True,
        'frames': 1834,
        'framerate': 25.0,
        'fileSize': 48123456,
    }


def test_payload_for_keogram_has_dimensions_but_no_framerate():
    payload = events.media_complete_payload(_entry(frames=3552, width=3552, height=480, fileSize=901234))

    assert payload['width'] == 3552 and payload['height'] == 480
    assert 'framerate' not in payload


def test_broadcast_media_complete_sends_payload(monkeypatch):
    broadcast = Mock(return_value=0)
    monkeypatch.setattr(events.event_manager, 'broadcast', broadcast)

    events.broadcast_media_complete('timelapse_complete', _entry(framerate=25.0))

    broadcast.assert_called_once()
    event_type, payload = broadcast.call_args.args
    assert event_type == 'timelapse_complete'
    assert payload['frames'] == 1834 and payload['framerate'] == 25.0


def test_broadcast_media_complete_never_raises(monkeypatch):
    monkeypatch.setattr(events.event_manager, 'broadcast', Mock(side_effect=OSError('no socket')))
    events.broadcast_media_complete('keogram_complete', _entry())   # logged, not raised


# ---------------------------------------------------------------- miscDb.addKeogram / addStarTrail

def _misc_db_method(name, broadcast_mock, monkeypatch):
    """Run the real miscDb method without Flask or a database."""
    path = ROOT / 'indi_allsky/flask/miscDb.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'miscDb')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)

    # the method imports ..events; give it the real module with broadcast mocked
    monkeypatch.setitem(sys.modules, 'indi_allsky.flask', types.ModuleType('indi_allsky.flask'))
    monkeypatch.setattr(events.event_manager, 'broadcast', broadcast_mock)

    class Row(SimpleNamespace):
        def __init__(self, **kw):
            super().__init__(id=42, **kw)

    namespace = dict(
        __name__='indi_allsky.flask.miscDb', __package__='indi_allsky.flask',
        Path=Path, datetime=datetime, logger=Mock(),
        db=SimpleNamespace(session=SimpleNamespace(add=Mock(), commit=Mock())),
        IndiAllSkyDbKeogramTable=Row, IndiAllSkyDbStarTrailsTable=Row,
    )
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name]


METADATA = {'createDate': 1791700000, 'dayDate': '20261010', 'night': True}


@pytest.mark.parametrize('name,event', [('addKeogram', 'keogram_complete'), ('addStarTrail', 'startrail_complete')])
def test_add_broadcasts_by_default(monkeypatch, name, event):
    # callers that add a file that already exists (e.g. the sync API) still get the event,
    # now with the shared payload, so dimensions they supply are passed on
    broadcast = Mock(return_value=0)
    add = _misc_db_method(name, broadcast, monkeypatch)

    row = add(SimpleNamespace(), 'ccd_x/keogram.jpg', 1, dict(METADATA, frames=3552, width=3552, height=480))

    assert row.id == 42
    broadcast.assert_called_once()
    event_type, payload = broadcast.call_args.args
    assert event_type == event
    assert payload == events.media_complete_payload(row)
    assert payload['camera_id'] == 1 and payload['frames'] == 3552
    assert payload['width'] == 3552 and payload['height'] == 480


@pytest.mark.parametrize('name', ['addKeogram', 'addStarTrail'])
def test_add_uses_the_shared_helper(name):
    # one payload format: no inline event_manager.broadcast() left in these methods
    tree = ast.parse((ROOT / 'indi_allsky/flask/miscDb.py').read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'miscDb')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    assert _calls(method, 'broadcast_media_complete')
    assert not _calls(method, 'broadcast')


@pytest.mark.parametrize('name', ['addKeogram', 'addStarTrail'])
def test_add_can_defer_the_broadcast(monkeypatch, name):
    broadcast = Mock(return_value=0)
    add = _misc_db_method(name, broadcast, monkeypatch)

    row = add(SimpleNamespace(), 'ccd_x/keogram.jpg', 1, METADATA, broadcast=False)

    assert row.id == 42 and row.success is False
    broadcast.assert_not_called()


# ---------------------------------------------------------------- video.py: announced only once written

def _video_method(name):
    tree = ast.parse((ROOT / 'indi_allsky/video.py').read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'VideoWorker')
    return next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)


def _calls(node, attr):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)
            and (getattr(n.func, 'attr', None) == attr or getattr(n.func, 'id', None) == attr)]


def _broadcast_line(method, event):
    hits = [c.lineno for c in _calls(method, 'broadcast_media_complete') if c.args[0].value == event]
    assert len(hits) == 1, f'{event} should be broadcast exactly once'
    return hits[0]


def _success_true_lines(method, entry):
    return [n.lineno for n in ast.walk(method) if isinstance(n, ast.Assign)
            and isinstance(n.targets[0], ast.Attribute) and n.targets[0].attr == 'success'
            and getattr(n.targets[0].value, 'id', None) == entry
            and isinstance(n.value, ast.Constant) and n.value.value is True]


def test_timelapse_complete_follows_generation_and_success():
    method = _video_method('generateVideo')
    line = _broadcast_line(method, 'timelapse_complete')

    generate = [c.lineno for c in _calls(method, 'generate')]
    success = _success_true_lines(method, 'video_entry')
    assert generate and success
    assert line > max(generate) and line > max(success)

    # and it is not reachable from the failure branch, which returns first
    handler = next(n for n in ast.walk(method) if isinstance(n, ast.ExceptHandler)
                   and getattr(n.type, 'id', None) == 'TimelapseException')
    assert isinstance(handler.body[-1], ast.Return) and line > handler.end_lineno

    # only sent when the video is on disk, like the keogram and star trail events
    _exists_guard(method, 'video_file', line)


def _exists_guard(method, file_var, line):
    """The `if <file_var>.exists():` block that contains the broadcast on `line`."""
    guard = next((n for n in ast.walk(method) if isinstance(n, ast.If)
                  and isinstance(n.test, ast.Call) and getattr(n.test.func, 'attr', None) == 'exists'
                  and getattr(n.test.func.value, 'id', None) == file_var
                  and any(s.lineno == line for b in n.body for s in ast.walk(b) if hasattr(s, 'lineno'))),
                 None)
    assert guard is not None, f'broadcast on line {line} is not inside "if {file_var}.exists():"'
    return guard


@pytest.mark.parametrize('add,entry,event,finalize_obj,file_var', [
    ('addKeogram', 'keogram_entry', 'keogram_complete', 'kg', 'keogram_file'),
    ('addStarTrail', 'startrail_entry', 'startrail_complete', 'stg', 'startrail_file'),
])
def test_keogram_and_startrail_complete_follow_the_file(add, entry, event, finalize_obj, file_var):
    method = _video_method('generateKeogramStarTrails')

    # the DB row is created early, without an event
    (call,) = _calls(method, add)
    kw = {k.arg: k.value for k in call.keywords}
    assert isinstance(kw.get('broadcast'), ast.Constant) and kw['broadcast'].value is False

    line = _broadcast_line(method, event)
    finalize = [c.lineno for c in _calls(method, 'finalize') if getattr(c.func.value, 'id', None) == finalize_obj]
    assert finalize and line > max(finalize)
    assert line > max(_success_true_lines(method, entry))

    # sent from inside "if <file>.exists():", so only once the file is on disk
    _exists_guard(method, file_var, line)
