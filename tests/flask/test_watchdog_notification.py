import ast
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, sentinel

import pytest
from sqlalchemy.orm.exc import NoResultFound

from indi_allsky import constants


@pytest.fixture
def watchdog_status():
    # Execute the real status method without camera, D-Bus or database services.
    path = Path(__file__).resolve().parents[2] / 'indi_allsky/flask/base_views.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    base_view = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'BaseView')
    method = next(n for n in base_view.body if isinstance(n, ast.FunctionDef) and n.name == 'get_indi_allsky_status')
    namespace = dict(time=SimpleNamespace(time=lambda: 10000), timedelta=timedelta,
                     NoResultFound=NoResultFound, constants=constants,
                     NotificationCategory=SimpleNamespace(GENERAL=sentinel.general))
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    states = {'WATCHDOG': '10000', 'STATUS': str(constants.STATUS_RUNNING)}
    misc_db = Mock()
    misc_db.getState.side_effect = states.__getitem__
    view = SimpleNamespace(local_indi_allsky=True, indi_allsky_config={}, _miscDb=misc_db)
    return lambda: namespace['get_indi_allsky_status'](view), view, states


@pytest.mark.parametrize('age', [601, 2100])
@pytest.mark.parametrize('focus_mode', [False, True])
def test_expired_watchdog_notifies_before_returning_down(watchdog_status, age, focus_mode):
    get_status, view, states = watchdog_status
    states['WATCHDOG'] = str(10000 - age)
    view.indi_allsky_config['FOCUS_MODE'] = focus_mode

    assert get_status() == {'status': '<span class="tw:text-error">DOWN</span>'}
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

    expected = '<span class="tw:text-warning">FOCUS MODE</span>' if focus_mode else '<span class="tw:text-success">RUNNING</span>'
    assert get_status() == {'status': expected}
    view._miscDb.addNotification.assert_not_called()


@pytest.mark.parametrize('watchdog', [None, 'invalid'])
def test_unknown_watchdog_does_not_notify(watchdog_status, watchdog):
    get_status, view, states = watchdog_status
    if watchdog is None:
        view._miscDb.getState.side_effect = NoResultFound
    else:
        states['WATCHDOG'] = watchdog

    assert get_status() == {'status': '<span class="tw:text-warning">UNKNOWN</span>'}
    view._miscDb.addNotification.assert_not_called()


def test_remote_watchdog_does_not_notify(watchdog_status):
    get_status, view, _ = watchdog_status
    view.local_indi_allsky = False

    assert get_status() == {'status': '<span class="tw:text-base-content/60">REMOTE</span>'}
    view._miscDb.getState.assert_not_called()
    view._miscDb.addNotification.assert_not_called()
