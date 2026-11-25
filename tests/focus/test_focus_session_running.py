"""`focus_session_running` keeps the old focus controller off the lens while capture runs a session."""

from __future__ import annotations

import threading
import time

import pytest

from indi_allsky.focus.link import LinkServer


pytestmark = pytest.mark.app


@pytest.fixture
def running(flask_app):
    # the views import dbus and systemd at module level; the flask_app fixture stands them in
    from indi_allsky.flask.focus_views import focus_session_running
    return focus_session_running


class _Answerer(object):
    """Sends each new page a `state`, as FocusService and FocusController do."""

    def __init__(self, server, session):
        self.server = server
        self.session = session
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        known = set()
        while not self.stop.is_set():
            now = set(self.server.clients())  # the hello registers a page; the service greets each new one
            for cid in sorted(now - known):
                self.server.send_json(cid, {'kind': 'state', 'session': self.session})
            known = now
            time.sleep(0.01)

    def close(self):
        self.stop.set()
        self.thread.join(1)


def _serve(sock_path, closers, session=None):
    server = LinkServer(sock_path)
    server.start()
    closers.append(server)
    if session is not None:
        closers.append(_Answerer(server, session))


def test_no_link_is_no_session(sock_path, running):
    assert running(sock_path, timeout=0.3) is False


def test_active_session(sock_path, closers, running):
    _serve(sock_path, closers, 'active')
    assert running(sock_path) is True


def test_idle_capture(sock_path, closers, running):
    _serve(sock_path, closers, 'idle')
    assert running(sock_path) is False


def test_silent_server_is_no_session(sock_path, closers, running):
    _serve(sock_path, closers)
    t0 = time.monotonic()
    assert running(sock_path, timeout=0.3) is False
    assert time.monotonic() - t0 < 1.0
