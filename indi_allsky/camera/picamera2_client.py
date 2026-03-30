"""Standalone picamera2 daemon client.

Zero dependencies on indi_allsky — safe to import from any context
(daemon, capture worker, Flask, standalone test scripts).
"""

from __future__ import annotations

import json
import socket
import struct
from multiprocessing import shared_memory
from typing import Any, Optional

SOCK_PATH = "/run/indi-allsky/picamera2.sock"
SHM_NAME = "indi_allsky_frame"
SHM_HEADER = 24
SHM_PATH_SIZE = 512
# JPEG max and path offset are derived from actual shm size at runtime


class Picamera2Client:
    """Connect to the picamera2 daemon via Unix socket + shared memory."""

    def __init__(self, sock_path: str = SOCK_PATH) -> None:
        self._sock_path = sock_path
        self._sock: Optional[socket.socket] = None
        self._shm: Optional[shared_memory.SharedMemory] = None

    def connect(self) -> None:
        if self._sock is not None:
            return
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.connect(self._sock_path)
        self._sock.settimeout(120.0)

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        if self._shm is not None:
            try:
                self._shm.close()
            except Exception:
                pass
            self._shm = None

    def _send(self, cmd: dict) -> dict:
        self.connect()
        msg = json.dumps(cmd).encode() + b"\n"
        self._sock.sendall(msg)
        buf = b""
        while b"\n" not in buf:
            data = self._sock.recv(4096)
            if not data:
                raise ConnectionError("Daemon closed connection")
            buf += data
        line = buf.split(b"\n", 1)[0]
        return json.loads(line)

    def ping(self) -> dict:
        return self._send({"cmd": "ping"})

    def get_sensor_info(self) -> dict:
        return self._send({"cmd": "get_sensor_info"})

    def get_metadata(self) -> dict:
        return self._send({"cmd": "get_metadata"})

    def get_modes(self) -> dict:
        return self._send({"cmd": "get_modes"})

    def set_controls(self, **kwargs) -> dict:
        return self._send({"cmd": "set_controls", **kwargs})

    def capture_still(self, exposure: float = None, gain: float = None,
                      timeout: float = 120) -> dict:
        cmd: dict[str, Any] = {"cmd": "capture_still", "timeout": timeout}
        if exposure is not None:
            cmd["exposure"] = exposure
        if gain is not None:
            cmd["gain"] = gain
        return self._send(cmd)

    def capture_dng(self, path: str, timeout: float = 120) -> dict:
        return self._send({"cmd": "capture_dng", "path": path, "timeout": timeout})

    def set_binning(self, level: int, width: int, height: int) -> dict:
        return self._send({"cmd": "set_binning", "level": level,
                           "width": width, "height": height})

    def set_stream(self, width: int = None, height: int = None,
                   quality: int = None, osd: bool = None) -> dict:
        cmd: dict[str, Any] = {"cmd": "set_stream"}
        if width is not None:
            cmd["width"] = width
        if height is not None:
            cmd["height"] = height
        if quality is not None:
            cmd["quality"] = quality
        if osd is not None:
            cmd["osd"] = osd
        return self._send(cmd)

    # ------------------------------------------------------------------
    # Shared memory frame reader
    # ------------------------------------------------------------------

    def _open_shm(self) -> None:
        if self._shm is None:
            self._shm = shared_memory.SharedMemory(name=SHM_NAME)
            # Prevent Python's resource tracker from unlinking shm we don't own.
            # The daemon creates and owns the shm; clients are read-only.
            try:
                from multiprocessing import resource_tracker
                resource_tracker.unregister(
                    "/" + SHM_NAME, "shared_memory",
                )
            except Exception:
                pass
            # Derive JPEG max and path offset from actual shm size
            self._shm_jpeg_max = self._shm.size - SHM_HEADER - SHM_PATH_SIZE
            self._shm_path_offset = SHM_HEADER + self._shm_jpeg_max

    def get_stream_jpeg(self) -> Optional[tuple[bytes, int]]:
        """Read the latest JPEG frame from shared memory.

        Returns (jpeg_bytes, sequence_counter) or None.
        """
        try:
            self._open_shm()
        except FileNotFoundError:
            return None

        buf = self._shm.buf
        seq, w, h, ch, jpeg_len = struct.unpack_from("<QIIiI", buf, 0)
        if jpeg_len <= 0 or jpeg_len > self._shm_jpeg_max:
            return None
        jpeg = bytes(buf[SHM_HEADER:SHM_HEADER + jpeg_len])
        return jpeg, seq

    def get_frame_path(self) -> Optional[str]:
        """Read the latest full-res frame path from shared memory."""
        try:
            self._open_shm()
        except FileNotFoundError:
            return None

        buf = self._shm.buf
        raw = bytes(buf[self._shm_path_offset:self._shm_path_offset + SHM_PATH_SIZE])
        path = raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
        return path if path else None
