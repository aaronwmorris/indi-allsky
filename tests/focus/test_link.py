from __future__ import annotations

import json
import os
import socket
import stat
import struct
import threading
import time

import pytest

from indi_allsky.focus import link
from indi_allsky.focus.link import LinkClient
from indi_allsky.focus.link import LinkError
from indi_allsky.focus.link import LinkInUse
from indi_allsky.focus.link import LinkServer
from indi_allsky.focus.link import LinkUnavailable
from indi_allsky.focus.link import NewestSlot
from indi_allsky.focus.link import SlotOverflow
from indi_allsky.focus.link import probe
from indi_allsky.focus.session import MAX_PAGES


REFUSAL = {'kind': 'refused', 'reason': 'Three pages are already watching this focus session.'}


def wait_for(cond, timeout=2.0):
    """Poll cond() until it is truthy or the timeout passes. Returns the last value."""
    deadline = time.monotonic() + timeout
    while True:
        value = cond()
        if value or time.monotonic() >= deadline:
            return value
        time.sleep(0.01)


def make_server(sock_path, closers, **kwargs):
    server = LinkServer(sock_path, **kwargs)
    closers.append(server)
    server.start()
    return server


def make_client(sock_path, closers):
    client = LinkClient(sock_path)
    closers.append(client)
    client.connect()
    return client


def raw_connect(path):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(2.0)
    s.connect(path)
    return s


def raw_message(obj):
    payload = json.dumps(obj).encode()
    return b'J' + struct.pack('>I', len(payload)) + payload


def peer_closed(s, timeout=3.0):
    """True once the server has closed s (reads until EOF)."""
    s.settimeout(timeout)
    try:
        while s.recv(65536):
            pass
    except socket.timeout:
        return False
    except OSError:
        pass
    return True


def recv_until(client, want, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msg = client.recv(0.1)
        if msg is not None and want(msg):
            return msg
    return None


def test_round_trip_json_and_frame(sock_path, closers):
    server = make_server(sock_path, closers)
    client = make_client(sock_path, closers)
    assert wait_for(lambda: len(server.clients()) == 1)
    cid = server.clients()[0]

    client.send({'cmd': 'hello', 'n': 1})
    cmds = []
    wait_for(lambda: cmds.extend(server.poll_commands()) or cmds)
    assert cmds == [(cid, {'cmd': 'hello', 'n': 1})]
    assert server.poll_commands() == []

    server.broadcast_frame(b'\x00\x01frame-bytes')
    assert client.recv(2.0) == ('frame', b'\x00\x01frame-bytes')

    server.broadcast_json({'kind': 'status', 'v': 2})
    assert client.recv(2.0) == ('json', {'kind': 'status', 'v': 2})

    server.send_json(cid, {'kind': 'only-you'})
    assert client.recv(2.0) == ('json', {'kind': 'only-you'})

    assert client.recv(0.05) is None


def test_hello_carries_extra_fields(sock_path, closers):
    server = make_server(sock_path, closers)
    plain = make_client(sock_path, closers)
    assert wait_for(lambda: len(server.clients()) == 1)
    flagged = LinkClient(sock_path)
    closers.append(flagged)
    flagged.connect(hello={'controls': True, 'kind': 'not-hello'})
    assert wait_for(lambda: len(server.clients()) == 2)
    first, second = server.clients()

    assert server.client_hello(first) == {'kind': 'hello'}
    assert server.client_hello(second) == {'kind': 'hello', 'controls': True}
    # The hello registers the page; it is not a command.
    assert server.poll_commands() == []

    # A later 'hello' is an ordinary command and does not change the registration hello.
    plain.send({'kind': 'hello', 'controls': True})
    cmds = []
    wait_for(lambda: cmds.extend(server.poll_commands()) or cmds)
    assert cmds == [(first, {'kind': 'hello', 'controls': True})]
    assert server.client_hello(first) == {'kind': 'hello'}

    # The returned dict is a copy.
    server.client_hello(second)['controls'] = False
    assert server.client_hello(second)['controls'] is True

    plain.close()
    assert wait_for(lambda: server.clients() == [second])
    assert server.client_hello(first) is None


def test_recv_keeps_partial_message_across_timeout(sock_path, closers):
    # A raw server so the test controls the byte boundaries.
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    closers.append(listener)
    listener.bind(sock_path)
    listener.listen(1)
    client = make_client(sock_path, closers)
    conn, _ = listener.accept()
    closers.append(conn)

    payload = json.dumps({'kind': 'x'}).encode()
    data = b'J' + struct.pack('>I', len(payload)) + payload
    conn.sendall(data[:3])
    assert client.recv(0.1) is None
    conn.sendall(data[3:])
    assert client.recv(2.0) == ('json', {'kind': 'x'})


@pytest.mark.parametrize('header', [
    pytest.param(b'J' + struct.pack('>I', 64 * 1024 * 1024 + 1), id='oversize'),
    pytest.param(b'Q' + struct.pack('>I', 2), id='unknown-kind'),
])
def test_client_rejects_malformed_server_message(sock_path, closers, header):
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    closers.append(listener)
    listener.bind(sock_path)
    listener.listen(1)
    client = make_client(sock_path, closers)
    conn, _ = listener.accept()
    closers.append(conn)
    conn.sendall(header)
    with pytest.raises(LinkUnavailable) as exc:
        client.recv(2.0)
    assert exc.value.reason == 'protocol'


def test_socket_mode_is_0600(sock_path, closers):
    make_server(sock_path, closers)
    mode = os.stat(sock_path).st_mode
    assert stat.S_ISSOCK(mode)
    assert stat.S_IMODE(mode) == 0o600


@pytest.mark.parametrize('kind', ['file', 'symlink'])
def test_bind_refuses_a_path_that_is_not_a_socket_and_leaves_it(sock_path, closers, kind):
    # a mistyped INDI_ALLSKY_FOCUS_ADDRESS must never delete someone's file
    target = sock_path + '.data' if kind == 'symlink' else sock_path
    with open(target, 'w') as f:
        f.write('not mine to delete')
    if kind == 'symlink':
        os.symlink(target, sock_path)
    server = LinkServer(sock_path)
    closers.append(server)
    with pytest.raises(LinkError, match='not a socket'):
        server.start()
    assert os.path.lexists(sock_path)
    with open(target) as f:
        assert f.read() == 'not mine to delete'


def test_bind_replaces_dead_socket_file(sock_path, closers):
    dead = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    dead.bind(sock_path)
    dead.close()  # the file stays; nobody answers on it
    assert os.path.exists(sock_path)
    server = make_server(sock_path, closers)
    make_client(sock_path, closers)
    assert wait_for(lambda: len(server.clients()) == 1)


def test_bind_refuses_directory(sock_path, closers):
    os.mkdir(sock_path)
    server = LinkServer(sock_path)
    closers.append(server)
    with pytest.raises(LinkError, match='socket path is a directory'):
        server.start()
    assert os.path.isdir(sock_path)


@pytest.mark.skipif(os.geteuid() == 0, reason='root ignores socket file permissions')
def test_bind_refuses_unverifiable_socket(sock_path, closers):
    dead = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    dead.bind(sock_path)
    dead.close()
    os.chmod(sock_path, 0)  # connect now fails with EACCES, not ECONNREFUSED
    server = LinkServer(sock_path)
    closers.append(server)
    with pytest.raises(LinkInUse):
        server.start()
    assert os.path.exists(sock_path)


def test_bind_refuses_live_socket(sock_path, closers):
    first = make_server(sock_path, closers)
    second = LinkServer(sock_path)
    closers.append(second)
    with pytest.raises(LinkInUse):
        second.start()
    # A failed start owns nothing, so closing it must not remove the first server's socket.
    second.close()
    assert probe(sock_path)
    make_client(sock_path, closers)
    assert wait_for(lambda: len(first.clients()) == 1)


def test_newest_only_slot_drops_old_frames_keeps_json():
    slot = NewestSlot()
    slot.put_frame(b'frame1')
    slot.put_json(b'{"a":1}')
    slot.put_frame(b'frame2')
    slot.put_frame(b'frame3')
    assert slot.get(0.1) == ('json', b'{"a":1}')
    assert slot.get(0.1) == ('frame', b'frame3')
    assert slot.get(0.05) is None


def test_slot_keeps_json_after_frame_in_order():
    slot = NewestSlot()
    slot.put_json(b'A')
    slot.put_frame(b'f')
    slot.put_json(b'B')
    assert slot.get(0.1) == ('json', b'A')
    assert slot.get(0.1) == ('frame', b'f')
    assert slot.get(0.1) == ('json', b'B')


def test_slot_json_cap():
    slot = NewestSlot(json_cap=256)
    for i in range(256):
        slot.put_json(b'{}')
    slot.put_frame(b'frames do not count')
    with pytest.raises(SlotOverflow):
        slot.put_json(b'{}')


def test_fourth_client_refused(sock_path, closers):
    assert MAX_PAGES == 3
    server = make_server(sock_path, closers)
    for _ in range(MAX_PAGES):
        make_client(sock_path, closers)
    assert wait_for(lambda: len(server.clients()) == MAX_PAGES)
    ids = server.clients()

    fourth = make_client(sock_path, closers)
    assert fourth.recv(2.0) == ('json', REFUSAL)
    with pytest.raises(LinkUnavailable) as exc:
        fourth.recv(2.0)
    assert exc.value.reason == 'closed'
    assert server.clients() == ids


def test_probe_does_not_take_a_page_place(sock_path, closers):
    server = make_server(sock_path, closers)
    make_client(sock_path, closers)
    make_client(sock_path, closers)
    assert wait_for(lambda: len(server.clients()) == 2)

    # A probe-style connection that is still open and has not said hello.
    lurker = raw_connect(sock_path)
    closers.append(lurker)
    assert probe(sock_path) is True

    third = make_client(sock_path, closers)
    assert wait_for(lambda: len(server.clients()) == 3)
    server.broadcast_json({'kind': 'hi'})
    assert third.recv(2.0) == ('json', {'kind': 'hi'})
    assert len(server.clients()) == 3


def test_silent_connection_dropped_quietly(sock_path, closers, monkeypatch, caplog):
    monkeypatch.setattr(link, 'HELLO_TIMEOUT_S', 0.3)
    server = make_server(sock_path, closers)
    silent = raw_connect(sock_path)
    closers.append(silent)
    with caplog.at_level('DEBUG', logger='indi_allsky'):
        assert peer_closed(silent)
        assert wait_for(lambda: any('before hello' in r.getMessage() for r in caplog.records))
    assert server.clients() == []
    assert [r for r in caplog.records if 'before hello' in r.getMessage() and r.levelname != 'DEBUG'] == []


def test_first_message_must_be_hello(sock_path, closers):
    server = make_server(sock_path, closers)
    raw = raw_connect(sock_path)
    closers.append(raw)
    raw.sendall(raw_message({'cmd': 'not-hello'}))
    assert peer_closed(raw)
    assert server.clients() == []
    assert server.poll_commands() == []


def test_client_ids_increase_and_are_not_reused(sock_path, closers):
    server = make_server(sock_path, closers)
    a = make_client(sock_path, closers)
    assert wait_for(lambda: len(server.clients()) == 1)
    first_id = server.clients()[0]
    a.close()
    assert wait_for(lambda: server.clients() == [])
    make_client(sock_path, closers)
    assert wait_for(lambda: len(server.clients()) == 1)
    assert server.clients()[0] > first_id


def test_probe_false_when_no_server(sock_path):
    assert probe(sock_path) is False
    with open(sock_path, 'w') as f:
        f.write('not a socket')
    assert probe(sock_path) is False


def test_probe_true_when_server(sock_path, closers):
    make_server(sock_path, closers)
    assert probe(sock_path) is True


def test_connect_unavailable_when_no_server(sock_path):
    client = LinkClient(sock_path)
    with pytest.raises(LinkUnavailable):
        client.connect()


def test_client_disconnect_does_not_break_server(sock_path, closers):
    server = make_server(sock_path, closers)
    a = make_client(sock_path, closers)
    b = make_client(sock_path, closers)
    assert wait_for(lambda: len(server.clients()) == 2)

    a.close()
    assert wait_for(lambda: len(server.clients()) == 1)

    server.broadcast_json({'kind': 'still-here'})
    assert b.recv(2.0) == ('json', {'kind': 'still-here'})

    c = make_client(sock_path, closers)
    assert wait_for(lambda: len(server.clients()) == 2)
    server.broadcast_frame(b'f')
    assert b.recv(2.0) == ('frame', b'f')
    assert c.recv(2.0) == ('frame', b'f')


@pytest.mark.parametrize('bad', [
    pytest.param(b'J' + struct.pack('>I', 64 * 1024 + 1), id='oversize-json'),
    pytest.param(b'Q' + struct.pack('>I', 2) + b'{}', id='unknown-kind'),
    pytest.param(b'F' + struct.pack('>I', 2) + b'ab', id='frame-from-client'),
    pytest.param(b'J' + struct.pack('>I', 5) + b'nope!', id='bad-json'),
    pytest.param(b'J' + struct.pack('>I', 2) + b'[]', id='json-not-object'),
])
def test_malformed_client_is_dropped(sock_path, closers, bad):
    server = make_server(sock_path, closers)
    good = make_client(sock_path, closers)
    assert wait_for(lambda: len(server.clients()) == 1)

    raw = raw_connect(sock_path)
    closers.append(raw)
    raw.sendall(raw_message({'kind': 'hello'}))
    assert wait_for(lambda: len(server.clients()) == 2)
    raw.sendall(bad)
    assert wait_for(lambda: len(server.clients()) == 1)
    assert server.poll_commands() == []

    server.broadcast_json({'kind': 'ok'})
    assert good.recv(2.0) == ('json', {'kind': 'ok'})


def _drop_reasons(caplog, cid):
    return [r.args[1] for r in caplog.records
            if r.msg == 'Focus link client %d dropped: %s' and r.args and r.args[0] == cid]


def _connect_stalled(sock_path, closers):
    stalled = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    closers.append(stalled)
    stalled.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
    stalled.connect(sock_path)
    stalled.sendall(raw_message({'kind': 'hello'}))
    return stalled


def test_stalled_client_dropped_at_json_cap(sock_path, closers, monkeypatch, caplog):
    # A send timeout far beyond the test's length, so only the JSON cap can drop anyone.
    monkeypatch.setattr(link, 'SEND_TIMEOUT_S', 60.0)
    caplog.set_level('INFO', logger='indi_allsky')
    server = make_server(sock_path, closers)
    reader = make_client(sock_path, closers)
    assert wait_for(lambda: len(server.clients()) == 1)
    reader_id = server.clients()[0]

    _connect_stalled(sock_path, closers)
    assert wait_for(lambda: len(server.clients()) == 2)
    stalled_id = [c for c in server.clients() if c != reader_id][0]

    # Lockstep: the reading client drains each message before the next is sent, so only
    # the stalled client's slot fills. Kernel buffers absorb some messages first, so the
    # drop comes at 256 queued plus whatever the buffers held.
    pad = 'x' * 4096
    sent = 0
    for i in range(3000):
        server.broadcast_json({'kind': 'tick', 'i': i, 'pad': pad})
        sent += 1
        assert reader.recv(10.0) == ('json', {'kind': 'tick', 'i': i, 'pad': pad})
        if stalled_id not in server.clients():
            break

    assert server.clients() == [reader_id]
    assert sent > 256
    assert _drop_reasons(caplog, stalled_id) == ['json queue full']
    server.broadcast_json({'kind': 'after'})
    assert reader.recv(10.0) == ('json', {'kind': 'after'})


def test_stalled_client_dropped_at_send_timeout(sock_path, closers, monkeypatch, caplog):
    # Frames never overflow the slot, so the send timeout is a frame-only page's guard.
    # SEND_TIMEOUT_S is applied to each connection when it registers (at hello), so the
    # healthy reader keeps the real 5 s timeout and only the stalled page gets a short one.
    caplog.set_level('INFO', logger='indi_allsky')
    server = make_server(sock_path, closers)
    reader = make_client(sock_path, closers)
    assert wait_for(lambda: len(server.clients()) == 1)
    reader_id = server.clients()[0]

    monkeypatch.setattr(link, 'SEND_TIMEOUT_S', 1.0)
    _connect_stalled(sock_path, closers)
    assert wait_for(lambda: len(server.clients()) == 2)
    monkeypatch.undo()
    stalled_id = [c for c in server.clients() if c != reader_id][0]

    # 1 MiB is far more than the kernel buffers hold (about 200 KiB on Linux, 8 KiB on
    # macOS), so the stalled page's send must block; it is still small for the reader.
    frame = b'\x7f' * (1024 * 1024)
    server.broadcast_frame(frame)
    assert reader.recv(10.0) == ('frame', frame)
    assert wait_for(lambda: server.clients() == [reader_id], timeout=10.0)
    # _drop logs after it releases the lock, so the record can land just after clients() changes
    assert wait_for(lambda: _drop_reasons(caplog, stalled_id)) == ['send timed out']


def test_close_removes_socket_and_disconnects_clients(sock_path, closers):
    server = make_server(sock_path, closers)
    client = make_client(sock_path, closers)
    assert wait_for(lambda: len(server.clients()) == 1)
    t0 = time.monotonic()
    server.close()
    assert time.monotonic() - t0 < 3.0
    assert not os.path.exists(sock_path)
    with pytest.raises(LinkUnavailable) as exc:
        client.recv(2.0)
    assert exc.value.reason == 'closed'
    assert wait_for(lambda: not [t for t in threading.enumerate() if t.name.startswith('focus-link-')])
    server.close()  # idempotent


def test_close_leaves_socket_that_is_not_ours(sock_path, closers):
    server = make_server(sock_path, closers)
    os.unlink(sock_path)
    other = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    closers.append(other)
    other.bind(sock_path)
    server.close()
    assert os.path.exists(sock_path)


def test_close_without_start_is_safe(sock_path):
    LinkServer(sock_path).close()


class _SignalSelector(object):
    """Wraps a client's selector to report when recv is about to block in select."""

    def __init__(self, inner):
        self.inner = inner
        self.entered = threading.Event()

    def select(self, timeout=None):
        self.entered.set()
        return self.inner.select(timeout)

    def close(self):
        self.inner.close()


class _CloseOnEnter(object):
    """Stands in for the send lock and closes the client at the worst moment."""

    def __init__(self, client):
        self.client = client

    def __enter__(self):
        self.client.close()
        return self

    def __exit__(self, *exc):
        return False


def _recv_in_thread(client):
    result = {}

    def run():
        try:
            result['value'] = client.recv(None)
        except BaseException as e:  # record whatever escapes, for the assertion
            result['exc'] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, result


def test_send_racing_close_raises_link_unavailable(sock_path, closers):
    server = make_server(sock_path, closers)
    client = make_client(sock_path, closers)
    assert wait_for(lambda: len(server.clients()) == 1)
    # close() lands after send has taken the socket and before it writes.
    client._send_lock = _CloseOnEnter(client)
    with pytest.raises(LinkUnavailable) as exc:
        client.send({'cmd': 'x'})
    assert exc.value.reason == 'closed'
    with pytest.raises(LinkUnavailable):
        client.send({'cmd': 'y'})


def test_concurrent_send_and_close_only_raise_link_unavailable(sock_path, closers):
    server = make_server(sock_path, closers)
    client = make_client(sock_path, closers)
    assert wait_for(lambda: len(server.clients()) == 1)
    errors = []
    started = threading.Event()

    def spam():
        started.set()
        for i in range(100000):
            try:
                client.send({'i': i})
            except LinkUnavailable:
                return
            except BaseException as e:
                errors.append(e)
                return

    t = threading.Thread(target=spam, daemon=True)
    t.start()
    assert started.wait(2.0)
    client.close()
    t.join(2.0)
    assert not t.is_alive()
    assert errors == []


def test_close_from_another_thread_wakes_blocked_recv(sock_path, closers):
    server = make_server(sock_path, closers)
    client = make_client(sock_path, closers)
    assert wait_for(lambda: len(server.clients()) == 1)
    client._selector = _SignalSelector(client._selector)

    t, result = _recv_in_thread(client)
    assert client._selector.entered.wait(2.0)
    client.close()
    t.join(1.0)
    assert not t.is_alive()
    assert isinstance(result.get('exc'), LinkUnavailable), result
    assert result['exc'].reason == 'closed'


def test_server_close_wakes_blocked_recv(sock_path, closers):
    server = make_server(sock_path, closers)
    client = make_client(sock_path, closers)
    assert wait_for(lambda: len(server.clients()) == 1)
    client._selector = _SignalSelector(client._selector)

    t, result = _recv_in_thread(client)
    assert client._selector.entered.wait(2.0)
    server.close()
    t.join(2.0)
    assert not t.is_alive()
    assert isinstance(result.get('exc'), LinkUnavailable), result
    assert result['exc'].reason == 'closed'
