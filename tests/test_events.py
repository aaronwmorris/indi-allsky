import pytest
import json
from unittest.mock import Mock

from indi_allsky.events import EventManager, UDP_IPC_HOST, UDP_IPC_PORT


@pytest.fixture
def reset_singleton():
    """Reset the EventManager singleton state before and after each test."""
    EventManager._instance = None
    yield
    EventManager._instance = None


@pytest.fixture
def manager(reset_singleton):
    """Fixture providing a fresh EventManager instance."""
    return EventManager()


def test_singleton(reset_singleton):
    """Test that EventManager returns the same instance (singleton pattern)."""
    m1 = EventManager()
    m2 = EventManager()
    assert m1 is m2


def test_register_unregister_and_client_count(manager, mocker):
    """Test registering and unregistering clients and client_count property."""
    mocker.patch.object(manager, 'start_ipc_server')
    ws1 = Mock()
    ws2 = Mock()

    assert manager.client_count == 0

    manager.register(ws1)
    assert manager.client_count == 1
    assert ws1 in manager._clients

    manager.register(ws2)
    assert manager.client_count == 2
    assert ws2 in manager._clients

    assert manager.start_ipc_server.call_count == 2

    manager.unregister(ws1)
    assert manager.client_count == 1
    assert ws1 not in manager._clients

    manager.unregister(ws2)
    assert manager.client_count == 0

    # Unregistering a non-existent client shouldn't raise an error
    manager.unregister(ws2)


def test_broadcast_raw_no_clients(manager):
    """Test broadcast_raw with no active clients returns 0."""
    assert manager.broadcast_raw("test_payload") == 0


def test_broadcast_raw_sends_to_clients_and_returns_count(manager, mocker):
    """Test broadcast_raw sends the payload to all connected clients."""
    mocker.patch.object(manager, 'start_ipc_server')
    ws1 = Mock()
    ws2 = Mock()

    manager.register(ws1)
    manager.register(ws2)

    count = manager.broadcast_raw("hello_world")
    assert count == 2
    ws1.send.assert_called_once_with("hello_world")
    ws2.send.assert_called_once_with("hello_world")


def test_broadcast_raw_removes_dead_clients(manager, mocker):
    """Test broadcast_raw removes clients that raise exceptions on send."""
    mocker.patch.object(manager, 'start_ipc_server')
    ws_good = Mock()
    ws_bad = Mock()
    ws_bad.send.side_effect = Exception("Connection closed")

    manager.register(ws_good)
    manager.register(ws_bad)

    assert manager.client_count == 2
    count = manager.broadcast_raw("test_payload")

    assert count == 1  # Only one successful send
    ws_good.send.assert_called_once_with("test_payload")
    ws_bad.send.assert_called_once_with("test_payload")

    assert manager.client_count == 1
    assert ws_good in manager._clients
    assert ws_bad not in manager._clients


def test_broadcast_creates_json_payload(manager, mocker):
    """Test broadcast formats the JSON payload correctly with timestamp."""
    mocker.patch.object(manager, 'start_ipc_server')
    mocker.patch('time.time', return_value=12345.6)
    
    # Mock socket to avoid UDP network interaction
    mocker.patch('socket.socket')

    mock_broadcast_raw = mocker.patch.object(manager, 'broadcast_raw', return_value=0)

    manager.broadcast("test_event", {"key": "value"})

    mock_broadcast_raw.assert_called_once()
    payload = mock_broadcast_raw.call_args[0][0]

    parsed = json.loads(payload)
    assert parsed["event"] == "test_event"
    assert parsed["timestamp"] == 12345.6
    assert parsed["data"] == {"key": "value"}


def test_broadcast_local_clients_no_udp(manager, mocker):
    """Test broadcast does NOT relay via UDP if local clients received it."""
    mocker.patch.object(manager, 'broadcast_raw', return_value=1)
    mock_socket = mocker.patch('socket.socket')

    manager.broadcast("test_event", {})

    mock_socket.assert_not_called()


def test_broadcast_no_local_clients_sends_udp(manager, mocker):
    """Test broadcast relays via UDP if there are no local clients."""
    mocker.patch.object(manager, 'broadcast_raw', return_value=0)
    mock_socket_cls = mocker.patch('socket.socket')
    mock_sock = Mock()
    mock_socket_cls.return_value = mock_sock

    manager.broadcast("test_event", {"data": "test"})

    mock_socket_cls.assert_called_once()
    mock_sock.sendto.assert_called_once()
    mock_sock.close.assert_called_once()

    args = mock_sock.sendto.call_args[0]
    payload_bytes = args[0]
    address = args[1]

    payload_str = payload_bytes.decode('utf-8')
    parsed = json.loads(payload_str)
    assert parsed["event"] == "test_event"
    assert address == (UDP_IPC_HOST, UDP_IPC_PORT)


def test_start_ipc_server_idempotent(manager, mocker):
    """Test start_ipc_server only creates the background thread once."""
    mock_thread = mocker.patch('threading.Thread')
    
    manager.start_ipc_server()
    assert manager._ipc_started is True
    mock_thread.assert_called_once()
    
    # Second call should return early and not spawn another thread
    manager.start_ipc_server()
    assert mock_thread.call_count == 1
