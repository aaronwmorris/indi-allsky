"""
WebSocket Event Manager for indi-allsky.
Provides real-time event broadcasting to connected WebSocket clients (e.g. Home Assistant, Web Dashboards).
"""
import json
import logging
import time
import threading
from typing import Dict, Any, Set, Optional

logger = logging.getLogger('indi_allsky')


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
        return cls._instance

    def register(self, ws) -> None:
        """Register a new WebSocket connection."""
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

    def broadcast(self, event_type: str, data: Dict[str, Any]) -> int:
        """
        Broadcast an event payload to all connected clients.
        
        Args:
            event_type: String event identifier (e.g. 'exposure_complete', 'sensor_update', 'status_update')
            data: Payload dictionary containing event attributes

        Returns:
            Number of clients successfully notified.
        """
        payload = json.dumps({
            "event": event_type,
            "timestamp": time.time(),
            "data": data
        }, default=str)

        dead_clients = set()
        sent_count = 0

        with self._client_lock:
            clients_snapshot = list(self._clients)

        for ws in clients_snapshot:
            try:
                ws.send(payload)
                sent_count += 1
            except Exception as e:
                logger.debug("Failed sending WS event to client: %s", e)
                dead_clients.add(ws)

        if dead_clients:
            with self._client_lock:
                for ws in dead_clients:
                    self._clients.discard(ws)

        return sent_count


# Global singleton instance
event_manager = EventManager()
