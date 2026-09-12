"""Image masking is a display boundary, separate from star detection and solving."""
import ast
from datetime import datetime, timedelta
import hashlib
import math
import os
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import flask
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
import pytest
from sqlalchemy import Column, DateTime


VIEWS = ast.parse((Path(__file__).resolve().parents[2] / 'indi_allsky/flask/views.py').read_text(encoding='utf-8'))


@pytest.fixture
def virtualsky_view():
    class TemplateView:
        def get_context(self):
            return {}

    cls = next(n for n in VIEWS.body if isinstance(n, ast.ClassDef) and n.name == 'VirtualSkyView')
    app = flask.Flask(__name__, static_folder=str(Path(__file__).resolve().parents[2] / 'indi_allsky/flask/static'))
    namespace = dict(TemplateView=TemplateView, math=math, datetime=datetime, hashlib=hashlib, Path=Path, app=app,
                     request=SimpleNamespace(args={}), IndiAllskyVirtualSkyHelperForm=lambda **kwargs: None)
    exec(compile(ast.Module(body=[cls], type_ignores=[]), 'views.py', 'exec'), namespace)
    view = namespace['VirtualSkyView']()
    view.camera = SimpleNamespace(local=True, az=0, alt=90, uuid='camera', utc_offset=0,
                                  data={'vs_image_circle_diameter': 2218})
    view.indi_allsky_config = {}
    view.getCameraPrivacyLatLong = lambda camera: (53, 11)
    return view, app


@pytest.mark.parametrize('local,enabled,opacity,outline,masked', [
    (True, True, 100, False, True), (False, True, 100, False, False),
    (True, False, 100, False, False), (True, True, 50, False, False),
    (True, True, 100, True, False),
])
@pytest.mark.parametrize('focus_mode', [False, True])
def test_only_the_local_cameras_opaque_image_mask_is_used(virtualsky_view, local, enabled, opacity, outline, masked, focus_mode):
    view, _ = virtualsky_view
    view.camera.local = local
    view.indi_allsky_config = {
        'IMAGE_CIRCLE_MASK': dict(ENABLE=enabled, DIAMETER=2200, OPACITY=opacity, OUTLINE=outline),
        'LENS_OFFSET_X': 36, 'LENS_OFFSET_Y': 3, 'IMAGE_SCALE': 50, 'FOCUS_MODE': focus_mode,
        'IMAGE_BORDER': {'TOP': 80, 'RIGHT': 70}, 'DETECT_MASK': '/not/a/display/mask.png',
    }
    expected = [2200, 36, 3, 100, 0, 0, 0, 0] if focus_mode else [2200, 36, 3, 50, 80, 70, 0, 0]
    assert view.get_context()['overlay_image_mask'] == (expected if masked else None)


@pytest.mark.parametrize('changed', ['virtualsky/virtualsky.min.js', 'js/virtualsky-calibration.js'])
def test_script_urls_change_with_contents_even_if_file_metadata_is_preserved(virtualsky_view, tmp_path, changed):
    view, app = virtualsky_view
    names = ('virtualsky/virtualsky.min.js', 'js/virtualsky-calibration.js')
    for name in names:
        file = tmp_path / name
        file.parent.mkdir(exist_ok=True)
        file.write_text('old script', encoding='utf-8')
    app.static_folder = str(tmp_path)
    templates = Environment(autoescape=True, loader=ChoiceLoader([
        DictLoader({'base.html': '{% block head %}{% endblock %}'}),
        FileSystemLoader(Path(__file__).resolve().parents[2] / 'indi_allsky/flask/templates'),
    ]))

    def script_urls():
        with app.test_request_context():
            html = templates.get_template('virtualsky.html').render(**view.get_context(),
                url_for=lambda endpoint, **kwargs: flask.url_for('static', **kwargs) if 'filename' in kwargs else '/unused')
        # Inspect actual rendered URLs, including the query used as the cache key.
        return re.findall(r'<script src="([^"]+)"', html)

    before = script_urls()
    assert script_urls() == before  # unchanged scripts can still use the cache
    for url in before[1:]:
        assert parse_qs(urlparse(url).query)['v'][0]
    file = tmp_path / changed
    stat = file.stat()
    file.write_text('new script', encoding='utf-8')
    os.utime(file, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    after = script_urls()
    assert before[0] == after[0]  # the unchanged loader is outside this fix
    for index, name in enumerate(names, 1):
        assert (before[index] != after[index]) == (name == changed)


@pytest.mark.parametrize('virtualsky,binmode', [(False, 2), (True, 2), (True, None)])
def test_virtualsky_gets_each_frames_binning_without_changing_other_loop_responses(virtualsky, binmode):
    cls = next(n for n in VIEWS.body if isinstance(n, ast.ClassDef) and n.name == 'JsonImageLoopView')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'getLoopImages')
    namespace = dict(timedelta=timedelta, request=flask.request, app=flask.Flask(__name__),
                     IndiAllSkyDbCameraTable=MagicMock(), and_=lambda *args: None, sa_false=lambda: False)
    exec(compile(ast.Module(body=[method], type_ignores=[]), 'views.py', 'exec'), namespace)
    entry = SimpleNamespace(width=800, height=600, createDate=datetime(2026, 9, 7),
                            getUrl=lambda **kwargs: '/image.jpg', sqm=0, stars=42, detections=0)
    if binmode is not None:  # the same loop view also serves assets without binning
        entry.binmode = binmode
    model = MagicMock()
    model.createDate = Column(DateTime)
    model.query.join.return_value.filter.return_value.order_by.return_value.limit.return_value = [entry]
    view = SimpleNamespace(model=model, web_nonlocal_images=False, s3_prefix='', include_id=False, limit=1)
    with namespace['app'].test_request_context(query_string={'virtualsky': '1'} if virtualsky else {}):
        result = namespace['getLoopImages'](view, 1, datetime(2026, 9, 7), 900)[0]
    assert ('binmode' in result) is virtualsky
    if virtualsky:
        assert result['binmode'] == binmode
