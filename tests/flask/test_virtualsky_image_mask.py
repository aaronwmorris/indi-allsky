"""Image masking is a display boundary, separate from star detection and solving."""
import ast
from datetime import datetime, timedelta
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import flask
import pytest
from sqlalchemy import Column, DateTime


VIEWS = ast.parse((Path(__file__).resolve().parents[2] / 'indi_allsky/flask/views.py').read_text(encoding='utf-8'))


@pytest.mark.parametrize('local,enabled,opacity,outline,masked', [
    (True, True, 100, False, True), (False, True, 100, False, False),
    (True, False, 100, False, False), (True, True, 50, False, False),
    (True, True, 100, True, False),
])
@pytest.mark.parametrize('focus_mode', [False, True])
def test_only_the_local_cameras_opaque_image_mask_is_used(local, enabled, opacity, outline, masked, focus_mode):
    class TemplateView:
        def get_context(self):
            return {}

    cls = next(n for n in VIEWS.body if isinstance(n, ast.ClassDef) and n.name == 'VirtualSkyView')
    namespace = dict(TemplateView=TemplateView, math=math, datetime=datetime,
                     request=SimpleNamespace(args={}), IndiAllskyVirtualSkyHelperForm=lambda **kwargs: None)
    exec(compile(ast.Module(body=[cls], type_ignores=[]), 'views.py', 'exec'), namespace)
    view = namespace['VirtualSkyView']()
    view.camera = SimpleNamespace(local=local, az=0, alt=90, uuid='camera', utc_offset=0,
                                  data={'vs_image_circle_diameter': 2218})
    view.indi_allsky_config = {
        'IMAGE_CIRCLE_MASK': dict(ENABLE=enabled, DIAMETER=2200, OPACITY=opacity, OUTLINE=outline),
        'LENS_OFFSET_X': 36, 'LENS_OFFSET_Y': 3, 'IMAGE_SCALE': 50, 'FOCUS_MODE': focus_mode,
        'IMAGE_BORDER': {'TOP': 80, 'RIGHT': 70}, 'DETECT_MASK': '/not/a/display/mask.png',
    }
    view.getCameraPrivacyLatLong = lambda camera: (53, 11)
    expected = [2200, 36, 3, 100, 0, 0, 0, 0] if focus_mode else [2200, 36, 3, 50, 80, 70, 0, 0]
    assert view.get_context()['overlay_image_mask'] == (expected if masked else None)


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
