import errno
import os
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from indi_allsky.archive_health import storage_errno
from indi_allsky.storage_startup import retry_storage_start


def test_readonly_sqlite_start_waits_and_resumes_once(tmp_path, monkeypatch):
    path = tmp_path / 'state.db'
    with sqlite3.connect(path) as db:
        db.execute('create table state (val text not null)')
    engines = [create_engine('sqlite:///file:' + str(path) + '?mode=ro&uri=true'),
               create_engine('sqlite:///' + str(path))]
    opened = []

    def prepare():
        engine = engines[min(len(opened), 1)]
        opened.append(engine)
        with engine.begin() as con:
            con.exec_driver_sql("insert into state values ('ready')")
        return 'started'

    monkeypatch.setattr('indi_allsky.storage_startup.time.sleep', lambda _: None)
    assert retry_storage_start(prepare) == 'started'
    assert len(opened) == 2
    with sqlite3.connect(path) as db:
        assert db.execute('select val from state').fetchall() == [('ready',)]


def test_interruptible_wait_and_other_errors(monkeypatch):
    failing = Mock(side_effect=OSError(errno.ENOSPC, 'full'))
    stopping = []
    monkeypatch.setattr('indi_allsky.storage_startup.time.sleep', lambda _: stopping.append(True))
    assert retry_storage_start(failing, lambda: bool(stopping)) is None
    assert failing.call_count == 1
    for error in (OSError(errno.EACCES, 'denied'), OperationalError('write', {}, sqlite3.Error('database is locked'))):
        with pytest.raises(type(error)):
            retry_storage_start(Mock(side_effect=error))


def test_sqlite_storage_error_without_numeric_code():
    assert storage_errno(OperationalError('write', {}, sqlite3.Error('database or disk is full'))) == errno.ENOSPC
    assert storage_errno(OperationalError('write', {}, sqlite3.Error('no such table: images'))) is None


def test_pid_retries_hold_lock_and_lock_contender_preserves_live_pid(tmp_path):
    from indi_allsky.allsky import IndiAllSky

    pidfile = tmp_path / 'live.pid'
    owner = SimpleNamespace(pid_lock=None, pid_file=pidfile, _miscDb=Mock())
    contender = SimpleNamespace(pid_lock=None, pid_file=pidfile, _miscDb=Mock())
    owner._miscDb.setState.side_effect = OperationalError('write', {}, sqlite3.Error('database or disk is full'))
    try:
        with pytest.raises(OperationalError):
            IndiAllSky.write_pid(owner)
        lock = owner.pid_lock
        with pytest.raises(SystemExit):
            IndiAllSky.write_pid(contender)
        assert pidfile.read_text() == str(os.getpid())
        owner._miscDb.setState.side_effect = None
        IndiAllSky.write_pid(owner)
        assert owner.pid_lock is lock
    finally:
        if owner.pid_lock:
            owner.pid_lock.close()


def test_maintenance_stop_during_cold_start_does_not_launch_workers(monkeypatch):
    from indi_allsky.allsky import IndiAllSky

    boss = SimpleNamespace(_shutdown=False, pid_lock=None,
                           _prepare_run=Mock(side_effect=OSError(errno.EROFS, 'readonly')),
                           _startCaptureWorker=Mock())
    monkeypatch.setattr('indi_allsky.storage_startup.time.sleep', lambda _: setattr(boss, '_shutdown', True))
    IndiAllSky.run(boss)
    boss._prepare_run.assert_called_once()
    boss._startCaptureWorker.assert_not_called()
