import json
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from indi_allsky.archive_health import BLOCKED, LOW, OK
from indi_allsky.flask import base_views
from indi_allsky.sensor_health import ups_problem


@pytest.fixture
def sidebar(tmp_path, monkeypatch):
    user = SimpleNamespace(is_authenticated=True, is_admin=True)
    monkeypatch.setattr(base_views, 'current_user', user)
    monkeypatch.setattr(base_views, 'ups_problem', lambda _: ups_problem(tmp_path / 'ups.json'))
    view = SimpleNamespace(local_indi_allsky=True, login_disabled=False, verify_admin_network=lambda: True,
                           indi_allsky_config={'VARLIB_FOLDER': str(tmp_path), 'IMAGE_FOLDER': '/images'})
    render = lambda: base_views.BaseView.get_status_text(view, {'status': 'RUNNING'})
    return view, user, render


@pytest.mark.parametrize('level,reason,message', [
    (LOW, 'reserve', 'Video and export jobs are waiting'),
    (BLOCKED, 'mount', 'Archive mount unavailable. Capture paused'),
])
def test_local_admin_sees_only_active_warnings(sidebar, tmp_path, level, reason, message):
    _, _, render = sidebar
    assert render() == '<div>Status: RUNNING</div>'
    record = dict(path='/images', level=level, reason=reason, mount='/private/mount')
    (tmp_path / 'archive-health.json').write_text(json.dumps(record))
    (tmp_path / 'ups.json').write_text(json.dumps({'readable': True, 'last_good_mono': time.monotonic() - 60}))
    result = render()
    assert message in result and 'No recent valid UPS reading' in result
    assert '/private/mount' not in result
    record.update(level=OK, reason='ok')
    (tmp_path / 'archive-health.json').write_text(json.dumps(record))
    (tmp_path / 'ups.json').write_text(json.dumps({'readable': True, 'last_good_mono': time.monotonic()}))
    assert render() == '<div>Status: RUNNING</div>'


@pytest.mark.parametrize('local, authenticated, admin, login_disabled, admin_network, allowed', [
    (False, True, True, True, True, False),
    (True, False, False, False, True, False),
    (True, True, False, False, True, False),
    (True, False, False, True, False, False),
    (True, False, False, True, True, True),
    (True, True, True, False, False, True),
])
def test_host_state_is_scoped_before_reading(sidebar, monkeypatch, local, authenticated, admin, login_disabled,
                                            admin_network, allowed):
    view, user, render = sidebar
    view.local_indi_allsky, view.login_disabled = local, login_disabled
    view.verify_admin_network = lambda: admin_network
    user.is_authenticated, user.is_admin = authenticated, admin
    archive, ups = Mock(return_value={}), Mock(return_value=True)
    monkeypatch.setattr(base_views, 'archive_state', archive)
    monkeypatch.setattr(base_views, 'ups_problem', ups)
    result = render()
    assert archive.called == ups.called == allowed
    assert ('No recent valid UPS reading' in result) == allowed
