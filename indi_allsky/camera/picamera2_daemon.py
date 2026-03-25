"""Picamera2 single-process daemon with IPC.

Owns the Picamera2 instance in a daemon thread, publishes frames via shared
memory, and accepts control commands over a Unix socket.  Both the
CaptureWorker (multiprocessing.Process) and gunicorn/Flask can connect as
clients without ever touching the camera directly.

Wire protocol (Unix stream socket, JSON-line):
  Client sends: {"cmd": "...", ...}\n
  Daemon replies: {"ok": true, ...}\n   or  {"ok": false, "error": "..."}\n

Shared memory layout (name = "indi_allsky_frame"):
  [0:8]       uint64  sequence counter
  [8:12]      uint32  width
  [12:16]     uint32  height
  [16:20]     uint32  channels
  [20:24]     uint32  jpeg_len
  [24:24+ML]  JPEG bytes for streaming (max 2MB)
  After JPEG region: raw frame path (UTF-8, null-terminated, 512 bytes)
"""

from __future__ import annotations

import json
import logging
import os
import select
import socket
import struct
import threading
import time
import traceback
from multiprocessing import shared_memory
from pathlib import Path
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

SOCK_PATH = "/run/indi-allsky/picamera2.sock"
SHM_NAME = "indi_allsky_frame"
SHM_HEADER = 24          # seq(8) + w(4) + h(4) + ch(4) + jpeg_len(4)
SHM_JPEG_MAX = 2 * 1024 * 1024  # 2 MB for stream JPEG
SHM_PATH_OFFSET = SHM_HEADER + SHM_JPEG_MAX
SHM_PATH_SIZE = 512
SHM_TOTAL = SHM_PATH_OFFSET + SHM_PATH_SIZE


class Picamera2Daemon:
    """Camera daemon that owns the Picamera2 instance.

    Start with :meth:`run` (blocking) or :meth:`start` (background thread).
    """

    def __init__(
        self,
        camera_num: int = 0,
        stream_width: int = 1920,
        stream_height: int = 1080,
        stream_quality: int = 75,
    ) -> None:
        self._camera_num = camera_num
        self._stream_width = stream_width
        self._stream_height = stream_height
        self._stream_quality = stream_quality

        self._picam2: Any = None
        self._sensor_info: dict = {}
        self._metadata: dict = {}
        self._frame_count: int = 0
        self._stop = threading.Event()

        self._controls_lock = threading.Lock()
        self._pending_controls: dict[str, Any] = {}

        # Shared memory for frame distribution
        self._shm: Optional[shared_memory.SharedMemory] = None

        # Latest full-res frame path (written to temp file for capture worker)
        self._latest_frame_path: str = ""
        self._frame_lock = threading.Lock()
        self._frame_event = threading.Event()

        # For DNG capture requests
        self._dng_request: Optional[dict] = None
        self._dng_result: Optional[dict] = None
        self._dng_event = threading.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> threading.Thread:
        """Start the daemon in a background thread."""
        t = threading.Thread(target=self.run, name="picamera2-daemon", daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        """Main entry point (blocking)."""
        try:
            self._init_camera()
            self._init_shm()
            self._start_socket_server()
        except Exception:
            logger.exception("Picamera2 daemon failed to start")
            raise
        finally:
            self._cleanup()

    # ------------------------------------------------------------------
    # Camera init
    # ------------------------------------------------------------------

    def _init_camera(self) -> None:
        from picamera2 import Picamera2

        self._picam2 = Picamera2(self._camera_num)

        # Detect sensor
        props = self._picam2.camera_properties
        sensor_name = props.get("Model", "unknown")
        pixel_size = props.get("UnitCellSize", (0, 0))
        pixel_um = pixel_size[0] / 1000.0 if pixel_size[0] else 0

        # Configure: main (RGB for processing) + raw (for DNG)
        config = self._picam2.create_still_configuration(
            main={"format": "RGB888"},
            buffer_count=2,
        )
        self._picam2.configure(config)
        self._picam2.start()

        # Read sensor limits from controls
        controls = self._picam2.camera_controls
        gain_info = controls.get("AnalogueGain", (1.0, 1.0, None))
        exp_info = controls.get("ExposureTime", (1, 1000000, None))

        sensor_config = self._picam2.camera_configuration()
        main_cfg = sensor_config.get("main", {})
        w = main_cfg.get("size", (0, 0))[0]
        h = main_cfg.get("size", (0, 0))[1]

        cfa_info = props.get("ColorFilterArrangement")
        cfa_map = {0: "RGGB", 1: "GRBG", 2: "GBRG", 3: "BGGR"}
        cfa = cfa_map.get(cfa_info, "RGGB")

        self._sensor_info = {
            "sensor_name": sensor_name,
            "width": w,
            "height": h,
            "pixel": pixel_um,
            "min_gain": float(gain_info[0]),
            "max_gain": float(gain_info[1]),
            "min_exposure": float(exp_info[0]) / 1e6,
            "max_exposure": float(exp_info[1]) / 1e6,
            "cfa": cfa,
            "bit_depth": 10,  # most libcamera sensors are 10-bit raw
        }

        logger.info(
            "Picamera2 daemon: sensor=%s %dx%d gain=%.1f-%.1f exp=%.6f-%.1fs",
            sensor_name, w, h,
            self._sensor_info["min_gain"], self._sensor_info["max_gain"],
            self._sensor_info["min_exposure"], self._sensor_info["max_exposure"],
        )

    # ------------------------------------------------------------------
    # Shared memory
    # ------------------------------------------------------------------

    def _init_shm(self) -> None:
        try:
            old = shared_memory.SharedMemory(name=SHM_NAME)
            old.close()
            old.unlink()
        except FileNotFoundError:
            pass

        self._shm = shared_memory.SharedMemory(
            name=SHM_NAME, create=True, size=SHM_TOTAL,
        )
        # Make shm world-readable so gunicorn/Flask workers can read frames
        shm_path = f"/dev/shm/{SHM_NAME}"
        try:
            os.chmod(shm_path, 0o666)
        except OSError:
            pass
        logger.info("Shared memory created: %s (%d bytes)", SHM_NAME, SHM_TOTAL)

    def _publish_frame(self, jpeg_bytes: bytes, frame_path: str) -> None:
        """Write a JPEG frame + metadata into shared memory."""
        if self._shm is None:
            return
        buf = self._shm.buf
        jpeg_len = min(len(jpeg_bytes), SHM_JPEG_MAX)
        w = self._sensor_info.get("width", 0)
        h = self._sensor_info.get("height", 0)

        # Header
        struct.pack_into("<QIIiI", buf, 0,
                         self._frame_count, w, h, 3, jpeg_len)
        # JPEG data
        buf[SHM_HEADER:SHM_HEADER + jpeg_len] = jpeg_bytes[:jpeg_len]
        # Frame path
        path_bytes = frame_path.encode("utf-8")[:SHM_PATH_SIZE - 1] + b"\x00"
        buf[SHM_PATH_OFFSET:SHM_PATH_OFFSET + len(path_bytes)] = path_bytes

    # ------------------------------------------------------------------
    # Grab loop
    # ------------------------------------------------------------------

    def _grab_loop(self) -> None:
        """Daemon thread: continuous frame grab from picamera2."""
        try:
            import cv2
        except ImportError:
            cv2 = None

        while not self._stop.is_set():
            try:
                # Apply pending controls
                with self._controls_lock:
                    if self._pending_controls:
                        self._picam2.set_controls(dict(self._pending_controls))
                        self._pending_controls.clear()

                # Handle DNG capture request
                if self._dng_request is not None:
                    self._handle_dng_capture()
                    continue

                # Grab frame
                array = self._picam2.capture_array("main")
                metadata = self._picam2.capture_metadata()

                self._metadata = metadata
                self._frame_count += 1

                # Save full-res frame to temp file for capture worker
                frame_path = f"/tmp/indi_allsky_frame_{self._frame_count}.npy"
                np.save(frame_path, array)

                # Clean up old frame file
                old_path = self._latest_frame_path
                with self._frame_lock:
                    self._latest_frame_path = frame_path
                    self._frame_event.set()
                if old_path and old_path != frame_path:
                    try:
                        os.unlink(old_path)
                    except OSError:
                        pass

                # Encode stream JPEG
                if cv2 is not None:
                    stream_frame = cv2.resize(
                        array,
                        (self._stream_width, self._stream_height),
                        interpolation=cv2.INTER_AREA,
                    )
                    # RGB → BGR for cv2
                    stream_bgr = cv2.cvtColor(stream_frame, cv2.COLOR_RGB2BGR)
                    ok, jpeg_buf = cv2.imencode(
                        ".jpg", stream_bgr,
                        [cv2.IMWRITE_JPEG_QUALITY, self._stream_quality],
                    )
                    if ok:
                        self._publish_frame(bytes(jpeg_buf), frame_path)

            except Exception:
                logger.exception("Grab loop error")
                time.sleep(1.0)

    def _handle_dng_capture(self) -> None:
        """Handle a DNG capture request from the control socket."""
        req = self._dng_request
        self._dng_request = None
        try:
            output_path = req.get("path", "/tmp/indi_allsky_capture.dng")
            self._picam2.capture_file(output_path, format="dng")
            self._dng_result = {"ok": True, "path": output_path}
        except Exception as e:
            self._dng_result = {"ok": False, "error": str(e)}
        self._dng_event.set()

    # ------------------------------------------------------------------
    # Control socket
    # ------------------------------------------------------------------

    def _start_socket_server(self) -> None:
        """Listen for control commands on a Unix socket."""
        sock_dir = os.path.dirname(SOCK_PATH)
        os.makedirs(sock_dir, exist_ok=True)
        if os.path.exists(SOCK_PATH):
            os.unlink(SOCK_PATH)

        # Start grab loop in background
        grab_thread = threading.Thread(
            target=self._grab_loop, name="picam2-grab", daemon=True,
        )
        grab_thread.start()

        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(SOCK_PATH)
        os.chmod(SOCK_PATH, 0o666)
        srv.listen(8)
        srv.settimeout(1.0)

        logger.info("Picamera2 daemon listening on %s", SOCK_PATH)

        while not self._stop.is_set():
            try:
                readable, _, _ = select.select([srv], [], [], 1.0)
            except (select.error, OSError):
                break
            if not readable:
                continue
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            threading.Thread(
                target=self._handle_client,
                args=(conn,),
                daemon=True,
            ).start()

        srv.close()
        if os.path.exists(SOCK_PATH):
            os.unlink(SOCK_PATH)

    def _handle_client(self, conn: socket.socket) -> None:
        """Handle one client connection (may send multiple commands)."""
        conn.settimeout(30.0)
        buf = b""
        try:
            while not self._stop.is_set():
                try:
                    data = conn.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        cmd = json.loads(line)
                        resp = self._dispatch(cmd)
                    except Exception as e:
                        resp = {"ok": False, "error": str(e)}
                    conn.sendall(json.dumps(resp).encode() + b"\n")
        except Exception:
            pass
        finally:
            conn.close()

    def _dispatch(self, cmd: dict) -> dict:
        """Route a command to the appropriate handler."""
        action = cmd.get("cmd", "")

        if action == "get_sensor_info":
            return {"ok": True, **self._sensor_info}

        elif action == "get_metadata":
            meta = dict(self._metadata)
            meta["frame_count"] = self._frame_count
            meta["latest_frame_path"] = self._latest_frame_path
            return {"ok": True, "metadata": meta}

        elif action == "set_controls":
            controls: dict[str, Any] = {}
            if "exposure" in cmd:
                controls["ExposureTime"] = int(float(cmd["exposure"]) * 1e6)
                controls["AeEnable"] = False
            if "gain" in cmd:
                controls["AnalogueGain"] = float(cmd["gain"])
                controls["AeEnable"] = False
            if "awb" in cmd:
                controls["AwbEnable"] = bool(cmd["awb"])
            if "ae_enable" in cmd:
                controls["AeEnable"] = bool(cmd["ae_enable"])
            if controls:
                with self._controls_lock:
                    self._pending_controls.update(controls)
            return {"ok": True}

        elif action == "capture_still":
            # Wait for next frame after applying controls
            if "exposure" in cmd or "gain" in cmd:
                controls = {}
                if "exposure" in cmd:
                    controls["ExposureTime"] = int(float(cmd["exposure"]) * 1e6)
                    controls["AeEnable"] = False
                if "gain" in cmd:
                    controls["AnalogueGain"] = float(cmd["gain"])
                with self._controls_lock:
                    self._pending_controls.update(controls)

            # Wait for a fresh frame
            self._frame_event.clear()
            if not self._frame_event.wait(timeout=cmd.get("timeout", 120)):
                return {"ok": False, "error": "Capture timeout"}

            with self._frame_lock:
                path = self._latest_frame_path

            meta = dict(self._metadata)
            return {
                "ok": True,
                "frame_path": path,
                "metadata": meta,
                "frame_count": self._frame_count,
            }

        elif action == "capture_dng":
            self._dng_event.clear()
            self._dng_request = cmd
            if not self._dng_event.wait(timeout=cmd.get("timeout", 120)):
                return {"ok": False, "error": "DNG capture timeout"}
            result = self._dng_result or {"ok": False, "error": "No result"}
            self._dng_result = None
            return result

        elif action == "set_binning":
            level = int(cmd.get("level", 1))
            width = int(cmd.get("width", 0))
            height = int(cmd.get("height", 0))
            if width and height:
                try:
                    self._stop_grab()
                    config = self._picam2.create_still_configuration(
                        main={"size": (width, height), "format": "RGB888"},
                        buffer_count=2,
                    )
                    self._picam2.configure(config)
                    self._picam2.start()
                    self._sensor_info["width"] = width
                    self._sensor_info["height"] = height
                    self._restart_grab()
                    return {"ok": True}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
            return {"ok": True}

        elif action == "set_stream":
            if "width" in cmd:
                self._stream_width = int(cmd["width"])
            if "height" in cmd:
                self._stream_height = int(cmd["height"])
            if "quality" in cmd:
                self._stream_quality = int(cmd["quality"])
            return {"ok": True}

        elif action == "ping":
            return {"ok": True, "frame_count": self._frame_count}

        else:
            return {"ok": False, "error": f"Unknown command: {action}"}

    def _stop_grab(self) -> None:
        """Temporarily stop camera for reconfiguration."""
        self._picam2.stop()

    def _restart_grab(self) -> None:
        """Restart camera after reconfiguration."""
        self._picam2.start()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup(self) -> None:
        self._stop.set()
        if self._picam2 is not None:
            try:
                self._picam2.stop()
                self._picam2.close()
            except Exception:
                pass
        if self._shm is not None:
            try:
                self._shm.close()
                self._shm.unlink()
            except Exception:
                pass
        if os.path.exists(SOCK_PATH):
            try:
                os.unlink(SOCK_PATH)
            except OSError:
                pass


# ------------------------------------------------------------------
# Client class (used by CaptureWorker and Flask)
# ------------------------------------------------------------------

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
        # Read response line
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
                   quality: int = None) -> dict:
        cmd: dict[str, Any] = {"cmd": "set_stream"}
        if width is not None:
            cmd["width"] = width
        if height is not None:
            cmd["height"] = height
        if quality is not None:
            cmd["quality"] = quality
        return self._send(cmd)

    # ------------------------------------------------------------------
    # Shared memory frame reader
    # ------------------------------------------------------------------

    def _open_shm(self) -> None:
        if self._shm is None:
            self._shm = shared_memory.SharedMemory(name=SHM_NAME)

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
        if jpeg_len <= 0 or jpeg_len > SHM_JPEG_MAX:
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
        raw = bytes(buf[SHM_PATH_OFFSET:SHM_PATH_OFFSET + SHM_PATH_SIZE])
        path = raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
        return path if path else None


# ------------------------------------------------------------------
# Standalone entry point
# ------------------------------------------------------------------

def main():
    """Run the daemon as a standalone process."""
    import sys
    # Remove this script's directory from sys.path to prevent
    # indi_allsky/camera/libcamera.py from shadowing the system libcamera package.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path = [p for p in sys.path if os.path.abspath(p) != script_dir]

    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Picamera2 daemon for indi-allsky")
    parser.add_argument("--camera", type=int, default=0, help="Camera number")
    parser.add_argument("--stream-width", type=int, default=1920)
    parser.add_argument("--stream-height", type=int, default=1080)
    parser.add_argument("--stream-quality", type=int, default=75)
    args = parser.parse_args()

    daemon = Picamera2Daemon(
        camera_num=args.camera,
        stream_width=args.stream_width,
        stream_height=args.stream_height,
        stream_quality=args.stream_quality,
    )
    try:
        daemon.run()
    except KeyboardInterrupt:
        daemon.stop()


if __name__ == "__main__":
    main()
