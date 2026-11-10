import ast
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, sentinel

import pytest

from indi_allsky import constants
from indi_allsky.live_status import CAPTURE_STATES, station_status


@pytest.fixture
def watchdog_status():
    # Execute the real status method without camera, D-Bus or database services.
    path = Path(__file__).resolve().parents[2] / 'indi_allsky/flask/base_views.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    base_view = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'BaseView')
    method = next(n for n in base_view.body if isinstance(n, ast.FunctionDef) and n.name == 'get_indi_allsky_status')
    namespace = dict(time=SimpleNamespace(time=lambda: 10000), timedelta=timedelta,
                     constants=constants, CAPTURE_STATES=CAPTURE_STATES, station_status=station_status,
                     NotificationCategory=SimpleNamespace(GENERAL=sentinel.general))
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    states = {'WATCHDOG': '10000', 'STATUS': str(constants.STATUS_RUNNING)}
    misc_db = Mock()
    view = SimpleNamespace(camera=SimpleNamespace(id=3), local_indi_allsky=True, indi_allsky_config={}, _miscDb=misc_db)
    def read(**kwargs):
        view.live_states = {key: SimpleNamespace(value=value) for key, value in states.items()}
        return namespace['get_indi_allsky_status'](view, **kwargs)
    return read, view, states


@pytest.mark.parametrize('age', [601, 2100])
@pytest.mark.parametrize('focus_mode', [False, True])
def test_expired_watchdog_notifies_before_returning_down(watchdog_status, age, focus_mode):
    get_status, view, states = watchdog_status
    states['WATCHDOG'] = str(10000 - age)
    view.indi_allsky_config['FOCUS_MODE'] = focus_mode

    assert get_status() == station_status('down', 'DOWN', 'tw:text-error')
    view._miscDb.addNotification.assert_called_once_with(
        sentinel.general,
        'watchdog',
        'Watchdog expired.  indi-allsky may be in a failed state.',
        expire=timedelta(minutes=60),
    )


@pytest.mark.parametrize('age', [0, 599, 600])
@pytest.mark.parametrize('focus_mode', [False, True])
def test_fresh_watchdog_does_not_notify(watchdog_status, age, focus_mode):
    get_status, view, states = watchdog_status
    states['WATCHDOG'] = str(10000 - age)
    view.indi_allsky_config['FOCUS_MODE'] = focus_mode

    expected = ('focus', 'FOCUS MODE', 'tw:text-warning') if focus_mode else ('running', 'RUNNING', 'tw:text-success')
    assert get_status() == station_status(*expected)
    view._miscDb.addNotification.assert_not_called()


@pytest.mark.parametrize('watchdog', [None, 'invalid'])
def test_unknown_watchdog_does_not_notify(watchdog_status, watchdog):
    get_status, view, states = watchdog_status
    if watchdog is None:
        states.pop('WATCHDOG')
    else:
        states['WATCHDOG'] = watchdog

    assert get_status() == station_status('unknown', 'UNKNOWN', 'tw:text-warning')
    view._miscDb.addNotification.assert_not_called()


def test_remote_watchdog_does_not_notify(watchdog_status):
    get_status, view, _ = watchdog_status
    view.local_indi_allsky = False

    assert get_status() == station_status('remote', 'REMOTE', 'tw:text-base-content/60')
    view._miscDb.getState.assert_not_called()
    view._miscDb.addNotification.assert_not_called()

@pytest.mark.parametrize(('published','code'), [
    (constants.STATUS_NOINDISERVER, 'no_indiserver'), (constants.STATUS_STOPPED, 'stopped'),
    (constants.STATUS_CAMERAERROR, 'camera_error'), (constants.STATUS_PAUSED, 'paused'),
])
def test_focus_setting_does_not_hide_a_published_problem(watchdog_status, published, code):
    get_status, view, states = watchdog_status
    view.indi_allsky_config['FOCUS_MODE'] = True
    states['STATUS'] = str(published)
    assert get_status()['code'] == code


def test_fast_status_poll_is_read_only_even_when_watchdog_expired(watchdog_status):
    get_status, view, states = watchdog_status
    states['WATCHDOG'] = '1'
    assert get_status(notify=False)['code'] == 'down'
    view._miscDb.addNotification.assert_not_called()


def test_a_different_local_camera_does_not_inherit_the_current_capture_status(watchdog_status):
    get_status, view, states = watchdog_status
    states['DB_CAMERA_ID'] = '18'
    assert get_status()['code'] == 'inactive'
    view.camera.id = -1
    assert get_status()['code'] == 'no_camera'
