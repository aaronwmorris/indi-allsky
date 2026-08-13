"""
WebSocket Event Manager for indi-allsky.
Provides real-time event broadcasting to connected WebSocket clients (e.g. Home Assistant, Web Dashboards).
Supports multi-process UDP IPC event relay between background workers and Gunicorn web server processes.
"""
import json
import logging
import time
import socket
import threading
from typing import Dict, Any, Set, Optional

logger = logging.getLogger('indi_allsky')

UDP_IPC_HOST = "127.0.0.1"
UDP_IPC_PORT = 9876


class EventManager:
    """Singleton event manager tracking connected WS clients and broadcasting real-time events."""
    
    _instance: Optional['EventManager'] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(EventManager, cls).__new__(cls)
                cls._instance._clients: Set[Any] = set()
                cls._instance._client_lock = threading.Lock()
                cls._instance._ipc_started = False
        return cls._instance

    def start_ipc_server(self) -> None:
        """Starts a background UDP socket listener to receive events from background capture workers."""
        with self._client_lock:
            if self._ipc_started:
                return
            self._ipc_started = True

        def ipc_listener():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((UDP_IPC_HOST, UDP_IPC_PORT))
            except Exception as e:
                logger.warning("Failed binding UDP IPC event socket 127.0.0.1:%d: %s", UDP_IPC_PORT, e)
                return

            logger.info("UDP IPC event socket listener active on 127.0.0.1:%d", UDP_IPC_PORT)
            while True:
                try:
                    data, _ = sock.recvfrom(65536)
                    if data:
                        raw_payload = data.decode('utf-8')
                        self.broadcast_raw(raw_payload)
                except Exception as e:
                    logger.debug("Error in UDP IPC event listener: %s", e)

        t = threading.Thread(target=ipc_listener, daemon=True)
        t.start()

    def register(self, ws) -> None:
        """Register a new WebSocket connection."""
        self.start_ipc_server()
        with self._client_lock:
            self._clients.add(ws)
            logger.info("WebSocket event client connected. Active connections: %d", len(self._clients))

    def unregister(self, ws) -> None:
        """Unregister a WebSocket connection."""
        with self._client_lock:
            self._clients.discard(ws)
            logger.info("WebSocket event client disconnected. Active connections: %d", len(self._clients))

    @property
    def client_count(self) -> int:
        """Return count of active clients."""
        with self._client_lock:
            return len(self._clients)

    def broadcast_raw(self, raw_payload: str) -> int:
        """Sends raw JSON payload string to all registered WebSocket clients."""
        dead_clients = set()
        sent_count = 0

        with self._client_lock:
            clients_snapshot = list(self._clients)

        for ws in clients_snapshot:
            try:
                ws.send(raw_payload)
                sent_count += 1
            except Exception as e:
                logger.debug("Failed sending WS event to client: %s", e)
                dead_clients.add(ws)

        if dead_clients:
            with self._client_lock:
                for ws in dead_clients:
                    self._clients.discard(ws)

        return sent_count

    def broadcast(self, event_type: str, data: Dict[str, Any]) -> int:
        """
        Broadcast an event payload to all connected clients.
        If current process has no local WebSocket clients (e.g. background capture worker),
        relays the event via UDP IPC to Gunicorn web server process.
        """
        payload = json.dumps({
            "event": event_type,
            "timestamp": time.time(),
            "data": data
        }, default=str)

        sent_count = self.broadcast_raw(payload)

        # Relay to Gunicorn via UDP if local WS client count is 0
        if sent_count == 0:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.sendto(payload.encode('utf-8'), (UDP_IPC_HOST, UDP_IPC_PORT))
                sock.close()
            except Exception as e:
                logger.debug("Failed relaying IPC event over UDP: %s", e)

        return sent_count


# Global singleton instance
event_manager = EventManager()
