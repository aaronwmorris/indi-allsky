"""`/ws/focus`: the web relay between a focus page and the capture process's link.

App tier: builds the real app with `create_app()` from a temp flask.json (`INDI_ALLSKY_FLASK_CONFIG`). The link side
is a real `LinkServer`. `simple_websocket.Server.accept` is replaced by a fake websocket, `BaseView.__init__` (which
loads the indi-allsky config from the database) by a no-op, and the user by a request loader. The admin-network check
is the real `BaseView.verify_admin_network()`, fed by the request's remote address (with no local interfaces).
"""

from __future__ import annotations

import collections
import json
import logging
import queue
import socket
import threading
import time
import types

import pytest

from indi_allsky.focus.link import LinkServer


pytestmark = pytest.mark.app

SECRET = 'S3CRET-BODY-7f1e'
ADMIN_IP = '127.0.0.1'      # in ADMIN_NETWORKS below
OUTSIDE_IP = '203.0.113.9'  # TEST-NET-3: in no admin network and on no local interface
WAIT_S = 5.0

_CLOSE = object()


def _wait(pred, timeout=WAIT_S):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


class FakeWs(object):
    """Stands in for `simple_websocket.Server`: `receive`, `send`, `close`."""

    def __init__(self, closed_exc):
        self._closed_exc = closed_exc
        self.inbox = queue.Queue()
        self.sent = []
        self.closed = threading.Event()
        self.gate = None  # callable(data), run before a send is recorded
        self._lock = threading.Lock()

    def receive(self, timeout=None):
        if self.closed.is_set():
            raise self._closed_exc()
        try:
            item = self.inbox.get(timeout=timeout)
        except queue.Empty:
            return None
        if item is _CLOSE:
            self.closed.set()
            raise self._closed_exc()
        return item

    def send(self, data):
        if self.gate is not None:
            self.gate(data)
        if self.closed.is_set():
            raise self._closed_exc()
        with self._lock:
            self.sent.append(data)

    def close(self, reason=None, message=None):
        self.closed.set()

    def page_sends(self, data):
        self.inbox.put(data)

    def page_leaves(self):
        self.inbox.put(_CLOSE)

    def json_sent(self):
        with self._lock:
            return [json.loads(d) for d in self.sent if isinstance(d, str)]

    def frames_sent(self):
        with self._lock:
            return [d for d in self.sent if isinstance(d, bytes)]


@pytest.fixture
def web(flask_app, simple_websocket, monkeypatch):
    """The real app (see `flask_app`) with a fake websocket. Returns a namespace of helpers."""
    from indi_allsky.flask import focus_views

    app = flask_app.app
    set_user = flask_app.set_user

    sockets = []

    def accept(environ, **kwargs):
        ws = FakeWs(simple_websocket.ConnectionClosed)
        sockets.append(ws)
        return ws

    monkeypatch.setattr(simple_websocket.Server, 'accept', staticmethod(accept))

    class Web(object):
        pass

    w = Web()
    w.app = app
    w.focus_views = focus_views
    w.sockets = sockets
    w.threads = []

    def open_page(remote_addr=OUTSIDE_IP, headers=None):
        """Start a /ws/focus request on a thread; return (thread, fake ws, result dict)."""
        result = {}
        hdrs = {'Upgrade': 'websocket', 'Connection': 'Upgrade'}
        hdrs.update(headers or {})

        def run():
            with app.test_client() as client:
                resp = client.get('/indi-allsky/ws/focus', headers=hdrs, environ_base={'REMOTE_ADDR': remote_addr})
                result['status'] = resp.status_code

        n = len(sockets)
        t = threading.Thread(target=run, daemon=True)
        t.start()
        w.threads.append(t)
        assert _wait(lambda: len(sockets) > n or not t.is_alive()), 'the view never accepted'
        assert len(sockets) > n, 'the view returned without accepting: %r' % (result,)
        return t, sockets[n], result

    w.set_user = set_user
    w.open_page = open_page

    try:
        yield w
    finally:
        for ws in sockets:
            ws.page_leaves()
        for t in w.threads:
            t.join(WAIT_S)


@pytest.fixture
def server(sock_path, closers):
    s = LinkServer(sock_path)
    s.start()
    closers.append(s)
    return s


def _one_client(server):
    assert _wait(lambda: len(server.clients()) == 1), 'the page never registered on the link'
    return server.clients()[0]


def _commands(server, n):
    got = []

    def have():
        got.extend(server.poll_commands())
        return len(got) >= n

    _wait(have)
    return got


def test_route_is_a_websocket_route(web):
    rules = [r for r in web.app.url_map.iter_rules() if r.rule == '/indi-allsky/ws/focus']
    assert len(rules) == 1
    assert rules[0].websocket is True


def test_focus_address_default_when_key_missing(web):
    from indi_allsky.focus.link import DEFAULT_ADDRESS
    assert DEFAULT_ADDRESS == '/var/lib/indi-allsky/focus-session.sock'
    with web.app.app_context():
        web.app.config.pop('INDI_ALLSKY_FOCUS_ADDRESS')
        assert web.focus_views.focus_address() == DEFAULT_ADDRESS
        web.app.config['INDI_ALLSKY_FOCUS_ADDRESS'] = '/elsewhere.sock'
        assert web.focus_views.focus_address() == '/elsewhere.sock'


def test_admin_on_admin_network_gets_controls(web, server):
    web.set_user(is_admin=True)
    t, ws, _ = web.open_page(remote_addr=ADMIN_IP)
    cid = _one_client(server)
    assert server.client_hello(cid) == {'kind': 'hello', 'controls': True}


def test_watcher_flag_from_server_not_page(web, server):
    web.set_user(is_admin=False)
    t, ws, _ = web.open_page(remote_addr=ADMIN_IP)
    cid = _one_client(server)
    assert server.client_hello(cid)['controls'] is False

    ws.page_sends(json.dumps({'kind': 'start', 'controls': True}))
    ws.page_sends(json.dumps({'kind': 'hello', 'controls': True}))
    got = _commands(server, 2)
    assert got == [(cid, {'kind': 'start'}), (cid, {'kind': 'hello'})]
    assert server.client_hello(cid)['controls'] is False


def test_non_admin_network_gets_watch_only(web, server):
    web.set_user(is_admin=True)
    t, ws, _ = web.open_page(remote_addr=OUTSIDE_IP)
    cid = _one_client(server)
    assert server.client_hello(cid) == {'kind': 'hello', 'controls': False}


def test_link_down_sends_reason_and_closes(web, sock_path):
    # No server listens on sock_path.
    t, ws, result = web.open_page()
    t.join(WAIT_S)
    assert not t.is_alive()
    assert ws.json_sent() == [{'kind': 'ended', 'reason': web.focus_views.LINK_UNREACHABLE_REASON}]
    assert web.focus_views.LINK_UNREACHABLE_REASON == (
        'The live focus page cannot reach the capture program. It may be stopped, or running in another container '
        'or on another machine.')
    assert ws.closed.is_set()


def test_refusal_relayed_to_page(sock_path, closers, web):
    full = LinkServer(sock_path, max_clients=0)
    full.start()
    closers.append(full)

    t, ws, _ = web.open_page()
    t.join(WAIT_S)
    assert not t.is_alive()
    sent = ws.json_sent()
    assert sent == [{'kind': 'refused', 'reason': 'Three pages are already watching this focus session.'}]
    assert ws.closed.is_set()


def test_link_lost_mid_session_ends_page(web, server):
    t, ws, _ = web.open_page()
    _one_client(server)
    server.broadcast_json({'kind': 'state', 'session': 'active'})
    assert _wait(lambda: len(ws.json_sent()) == 1)
    server.close()
    t.join(WAIT_S)
    assert not t.is_alive()
    assert ws.json_sent() == [
        {'kind': 'state', 'session': 'active'},
        {'kind': 'ended', 'reason': web.focus_views.LINK_UNREACHABLE_REASON},
    ]
    assert ws.closed.is_set()


def test_capture_ended_is_not_followed_by_a_second_ended(web, server):
    t, ws, _ = web.open_page()
    cid = _one_client(server)
    server.send_json(cid, {'kind': 'ended', 'reason': 'done'})
    assert _wait(lambda: len(ws.json_sent()) == 1)
    server.close()
    t.join(WAIT_S)
    assert not t.is_alive()
    assert ws.json_sent() == [{'kind': 'ended', 'reason': 'done'}]


def test_page_leaving_closes_the_link(web, server):
    t, ws, _ = web.open_page()
    _one_client(server)
    ws.page_leaves()
    t.join(WAIT_S)
    assert not t.is_alive()
    assert _wait(lambda: server.clients() == [])


def test_a_failed_websocket_accept_closes_the_link(web, server, simple_websocket, monkeypatch):
    held = []

    def accept(environ, **kwargs):
        held.append(_wait(lambda: len(server.clients()) == 1))  # the link is open before the accept
        raise RuntimeError('handshake failed')

    monkeypatch.setattr(simple_websocket.Server, 'accept', staticmethod(accept))
    with web.app.test_client() as client:
        client.get('/indi-allsky/ws/focus', headers={'Upgrade': 'websocket', 'Connection': 'Upgrade'},
                   environ_base={'REMOTE_ADDR': OUTSIDE_IP})
    assert held == [True], 'the page never registered on the link'
    assert _wait(lambda: server.clients() == []), 'the link stayed open after the accept failed'


def test_frames_relayed_unchanged_as_binary(web, server):
    from indi_allsky.focus.frame import pack_frame
    frame = pack_frame(b'\xff\xd8jpeg\xff\xd9', 7, 1700000000.5, 0.1, 50.0, 3)

    t, ws, _ = web.open_page()
    _one_client(server)
    server.broadcast_frame(frame)
    assert _wait(lambda: ws.frames_sent() == [frame])


def test_ws_relay_drops_stale_frames(web, server, monkeypatch):
    marker_queued = threading.Event()
    real_slot = web.focus_views.NewestSlot

    class WatchedSlot(real_slot):
        def put_json(self, payload):
            super(WatchedSlot, self).put_json(payload)
            if b'marker' in payload:
                marker_queued.set()

    monkeypatch.setattr(web.focus_views, 'NewestSlot', WatchedSlot)

    t, ws, _ = web.open_page()
    _one_client(server)

    first_in_flight = threading.Event()
    release = threading.Event()

    def gate(data):
        if data == b'frame-1':
            first_in_flight.set()
            release.wait(WAIT_S)

    ws.gate = gate
    server.broadcast_frame(b'frame-1')
    assert first_in_flight.wait(WAIT_S)
    for n in (2, 3, 4, 5):
        server.broadcast_frame(b'frame-%d' % n)
    server.broadcast_json({'kind': 'marker'})
    assert marker_queued.wait(WAIT_S)
    release.set()

    assert _wait(lambda: len(ws.sent) == 3)
    time.sleep(0.2)
    assert ws.sent == [b'frame-1', b'frame-5', json.dumps({'kind': 'marker'}, separators=(',', ':'))]


def test_page_messages_filtered(web, server):
    t, ws, _ = web.open_page()
    cid = _one_client(server)

    ws.page_sends(b'\x00binary')
    ws.page_sends('not json')
    ws.page_sends(json.dumps([1, 2, 3]))
    ws.page_sends(json.dumps({'kind': 'ping', 'pad': 'x' * 4096}))  # over 4096 bytes
    ws.page_sends(json.dumps({'kind': 'ping', 'pad': 'é' * 2040}))  # under 4096 chars, over 4096 bytes
    ws.page_sends(json.dumps({'kind': 'ping', 'id': 1}))

    got = _commands(server, 1)
    time.sleep(0.2)
    got.extend(server.poll_commands())
    assert got == [(cid, {'kind': 'ping', 'id': 1})]
    assert t.is_alive()


def test_no_message_body_in_logs(web, server, caplog):
    caplog.set_level(logging.DEBUG)
    for name in ('indi_allsky', 'indi_allsky.flask', web.app.logger.name):
        logging.getLogger(name).addHandler(caplog.handler)
    try:
        t, ws, _ = web.open_page(headers={'X-Secret-Header': SECRET, 'Cookie': 'session=' + SECRET})
        cid = _one_client(server)
        ws.page_sends(json.dumps({'kind': 'ping', 'note': SECRET}))
        ws.page_sends('not json ' + SECRET)
        ws.page_sends(json.dumps({'kind': 'ping', 'note': SECRET * 400}))
        ws.page_sends(SECRET.encode())
        assert _commands(server, 1) == [(cid, {'kind': 'ping', 'note': SECRET})]
        server.send_json(cid, {'kind': 'pong', 'note': SECRET})
        assert _wait(lambda: len(ws.json_sent()) == 1)
        ws.page_leaves()
        t.join(WAIT_S)
    finally:
        for name in ('indi_allsky', 'indi_allsky.flask', web.app.logger.name):
            logging.getLogger(name).removeHandler(caplog.handler)

    assert any('Focus page' in r.getMessage() for r in caplog.records), 'the relay logged nothing; test is vacuous'
    assert SECRET not in caplog.text


def test_deeply_nested_page_message_is_dropped(web, server, monkeypatch):
    # Under 4096 bytes, but Python 3.9's json scanner raises RecursionError on it (3.13's parses it). The patched
    # loads does what 3.9 does, so this holds on every Python.
    nested = '[' * 2048 + ']' * 2048
    real_json = web.focus_views.json

    def loads(s, *args, **kwargs):
        if s == nested:
            raise RecursionError('maximum recursion depth exceeded while decoding a JSON array')
        return real_json.loads(s, *args, **kwargs)

    monkeypatch.setattr(web.focus_views, 'json', types.SimpleNamespace(loads=loads, dumps=real_json.dumps))

    t, ws, result = web.open_page()
    cid = _one_client(server)
    ws.page_sends(nested)
    ws.page_sends(json.dumps({'kind': 'ping', 'id': 2}))
    assert _commands(server, 1) == [(cid, {'kind': 'ping', 'id': 2})]
    assert t.is_alive()
    assert 'status' not in result


def test_slow_page_gets_ended_slow_then_closes(web, server, monkeypatch):
    overflowed = threading.Event()
    real_slot = web.focus_views.NewestSlot

    class SmallSlot(real_slot):
        def __init__(self):
            super(SmallSlot, self).__init__(json_cap=2)

        def put_json(self, payload):
            try:
                super(SmallSlot, self).put_json(payload)
            except web.focus_views.SlotOverflow:
                overflowed.set()
                raise

    monkeypatch.setattr(web.focus_views, 'NewestSlot', SmallSlot)

    t, ws, _ = web.open_page()
    _one_client(server)

    first_in_flight = threading.Event()
    release = threading.Event()

    def gate(data):
        if isinstance(data, str) and '"n":0' in data:
            first_in_flight.set()
            release.wait(WAIT_S)

    ws.gate = gate
    server.broadcast_json({'kind': 'reading', 'n': 0})
    assert first_in_flight.wait(WAIT_S)
    for n in range(1, 6):
        server.broadcast_json({'kind': 'reading', 'n': n})
    assert overflowed.wait(WAIT_S)
    release.set()

    t.join(WAIT_S)
    assert not t.is_alive()
    assert ws.json_sent() == [{'kind': 'reading', 'n': 0}, {'kind': 'ended', 'reason': 'slow'}]
    assert ws.closed.is_set()


def test_admin_network_check_skips_addresses_without_netmask(web, monkeypatch):
    # Pre-existing BaseView code: macOS utun (and some tunnel) addresses report netmask None.
    from indi_allsky.flask import base_views

    addr = collections.namedtuple('snicaddr', 'family address netmask broadcast ptp')
    monkeypatch.setattr(base_views.psutil, 'net_if_addrs', lambda: {
        'utun0': [addr(socket.AF_INET, '100.101.102.103', None, None, '100.101.102.103')],
        'en0': [addr(socket.AF_INET, '192.168.5.10', '255.255.255.0', None, None)],
    })
    view = base_views.BaseView()

    with web.app.test_request_context('/', environ_base={'REMOTE_ADDR': '192.168.5.20'}):
        assert view.verify_admin_network() is True
    with web.app.test_request_context('/', environ_base={'REMOTE_ADDR': OUTSIDE_IP}):
        assert view.verify_admin_network() is False
