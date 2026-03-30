"""Camera backend abstraction for the picamera2 daemon.

Provides a common interface for both picamera2 (preferred on Pi)
and raw libcamera Python bindings (fallback / non-Pi).
"""

from __future__ import annotations

import logging
import mmap
import os
import selectors
import struct
import time
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)


class CameraBackend:
    """Abstract camera backend — subclass for each library."""

    def __init__(self, camera_num: int = 0) -> None:
        self._camera_num = camera_num
        self.sensor_info: dict[str, Any] = {}

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def grab_frame(self) -> tuple[np.ndarray, dict]:
        """Grab one frame. Returns (bgr_array, metadata_dict)."""
        raise NotImplementedError

    def set_controls(self, controls: dict[str, Any]) -> None:
        raise NotImplementedError

    def capture_dng(self, path: str) -> None:
        raise NotImplementedError


class Picamera2Backend(CameraBackend):
    """Uses the picamera2 library (preferred on Raspberry Pi)."""

    def __init__(self, camera_num: int = 0) -> None:
        super().__init__(camera_num)
        self._picam2: Any = None

    def start(self) -> None:
        from picamera2 import Picamera2

        self._picam2 = Picamera2(self._camera_num)

        props = self._picam2.camera_properties
        sensor_name = props.get("Model", "unknown")
        pixel_size = props.get("UnitCellSize", (0, 0))
        pixel_um = pixel_size[0] / 1000.0 if pixel_size[0] else 0

        config = self._picam2.create_still_configuration(
            main={"format": "RGB888"},  # actually BGR
            buffer_count=2,
        )
        self._picam2.configure(config)
        self._picam2.start()

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

        self.sensor_info = {
            "sensor_name": sensor_name,
            "width": w,
            "height": h,
            "pixel": pixel_um,
            "min_gain": float(gain_info[0]),
            "max_gain": float(gain_info[1]),
            "min_exposure": float(exp_info[0]) / 1e6,
            "max_exposure": float(exp_info[1]) / 1e6,
            "cfa": cfa,
            "bit_depth": 10,
            "backend": "picamera2",
        }

        logger.info(
            "Picamera2 backend: %s %dx%d gain=%.1f-%.1f exp=%.6f-%.1fs",
            sensor_name, w, h,
            self.sensor_info["min_gain"], self.sensor_info["max_gain"],
            self.sensor_info["min_exposure"], self.sensor_info["max_exposure"],
        )

    def stop(self) -> None:
        if self._picam2:
            try:
                self._picam2.stop()
                self._picam2.close()
            except Exception:
                pass
            self._picam2 = None

    def grab_frame(self) -> tuple[np.ndarray, dict]:
        array = self._picam2.capture_array("main")
        metadata = self._picam2.capture_metadata()
        return array, metadata

    def set_controls(self, controls: dict[str, Any]) -> None:
        self._picam2.set_controls(controls)

    def capture_dng(self, path: str) -> None:
        self._picam2.capture_file(path, format="dng")

    @property
    def sensor_modes(self) -> list:
        if self._picam2:
            return self._picam2.sensor_modes
        return []


class LibcameraBackend(CameraBackend):
    """Uses raw libcamera Python bindings (works on non-Pi Linux)."""

    def __init__(self, camera_num: int = 0) -> None:
        super().__init__(camera_num)
        self._cm: Any = None
        self._camera: Any = None
        self._allocator: Any = None
        self._stream = None
        self._buffers: list = []
        self._sel: Any = None
        self._pending_controls: dict = {}
        self._started = False

    def start(self) -> None:
        import libcamera

        self._cm = libcamera.CameraManager.singleton()
        cameras = self._cm.cameras
        if not cameras:
            raise RuntimeError("No libcamera cameras found")
        if self._camera_num >= len(cameras):
            raise RuntimeError(f"Camera {self._camera_num} not found (have {len(cameras)})")

        self._camera = cameras[self._camera_num]
        self._camera.acquire()

        # Configure for still capture (native resolution)
        config = self._camera.generate_configuration(
            [libcamera.StreamRole.StillCapture]
        )
        stream_cfg = config.at(0)

        # Get sensor properties
        props = self._camera.properties
        model = props.get(libcamera.properties.Model, "unknown")
        pixel_size = props.get(libcamera.properties.UnitCellSize, libcamera.Size(0, 0))
        pixel_um = pixel_size.width / 1000.0 if hasattr(pixel_size, 'width') else 0

        w = stream_cfg.size.width
        h = stream_cfg.size.height

        # Try to get control limits
        ctrl_info = self._camera.controls
        min_gain = 1.0
        max_gain = 16.0
        min_exp = 0.000001
        max_exp = 60.0

        for ctrl_id, ctrl_range in ctrl_info.items():
            name = ctrl_id.name if hasattr(ctrl_id, 'name') else str(ctrl_id)
            if name == "AnalogueGain":
                min_gain = float(ctrl_range.min)
                max_gain = float(ctrl_range.max)
            elif name == "ExposureTime":
                min_exp = float(ctrl_range.min) / 1e6
                max_exp = float(ctrl_range.max) / 1e6

        self.sensor_info = {
            "sensor_name": model,
            "width": w,
            "height": h,
            "pixel": pixel_um,
            "min_gain": min_gain,
            "max_gain": max_gain,
            "min_exposure": min_exp,
            "max_exposure": max_exp,
            "cfa": "RGGB",
            "bit_depth": 10,
            "backend": "libcamera",
        }

        # Set pixel format to BGR (matching picamera2's RGB888 = BGR)
        try:
            stream_cfg.pixel_format = libcamera.formats.BGR888
        except AttributeError:
            # Older libcamera may not have BGR888, try RGB888
            try:
                stream_cfg.pixel_format = libcamera.formats.RGB888
            except AttributeError:
                pass  # use default

        config.validate()
        self._camera.configure(config)

        # Allocate buffers
        self._stream = config.at(0).stream
        self._allocator = libcamera.FrameBufferAllocator(self._camera)
        num_bufs = self._allocator.allocate(self._stream)
        if num_bufs <= 0:
            raise RuntimeError("Failed to allocate libcamera buffers")
        self._buffers = self._allocator.buffers(self._stream)

        # Start camera
        self._camera.start()
        self._started = True

        # Queue all buffers
        for buf in self._buffers:
            req = self._camera.create_request()
            req.add_buffer(self._stream, buf)
            self._camera.queue_request(req)

        # Selector for event-driven frame readout
        self._sel = selectors.DefaultSelector()
        self._sel.register(self._cm.event_fd, selectors.EVENT_READ)

        logger.info(
            "libcamera backend: %s %dx%d gain=%.1f-%.1f exp=%.6f-%.1fs",
            model, w, h, min_gain, max_gain, min_exp, max_exp,
        )

    def stop(self) -> None:
        if self._camera and self._started:
            try:
                self._camera.stop()
            except Exception:
                pass
            self._started = False
        if self._sel:
            self._sel.close()
            self._sel = None
        if self._camera:
            try:
                self._camera.release()
            except Exception:
                pass
            self._camera = None

    def grab_frame(self) -> tuple[np.ndarray, dict]:
        """Block until next frame, return (bgr_array, metadata)."""
        import libcamera

        # Wait for frame
        events = self._sel.select(timeout=30)
        if not events:
            raise TimeoutError("libcamera frame timeout")

        completed = self._cm.get_ready_requests()
        if not completed:
            raise RuntimeError("No completed requests")

        req = completed[-1]  # latest

        # Extract metadata — raw libcamera uses ControlId objects as keys
        metadata = {}
        try:
            for key, value in req.metadata.items():
                if hasattr(key, 'name'):
                    metadata[key.name] = value
                else:
                    metadata[str(key)] = value
        except Exception as e:
            logger.debug("Metadata extraction error: %s", e)

        # Extract frame data from buffer
        fb = req.buffers[self._stream]
        planes = fb.planes
        if not planes:
            raise RuntimeError("No planes in frame buffer")

        plane = planes[0]
        w = self.sensor_info["width"]
        h = self.sensor_info["height"]

        # mmap the buffer fd to get pixel data
        with mmap.mmap(plane.fd, plane.length, mmap.MAP_SHARED, mmap.PROT_READ,
                       offset=plane.offset) as mm:
            array = np.frombuffer(mm[:w * h * 3], dtype=np.uint8).reshape(h, w, 3).copy()

        # Re-queue the request's buffer
        try:
            new_req = self._camera.create_request()
            new_req.add_buffer(self._stream, fb)
            # Apply pending controls
            if self._pending_controls:
                for ctrl_name, val in self._pending_controls.items():
                    try:
                        ctrl_id = libcamera.controls.controls[ctrl_name]
                        new_req.set_control(ctrl_id, val)
                    except (KeyError, AttributeError):
                        pass
                self._pending_controls.clear()
            self._camera.queue_request(new_req)
        except Exception:
            pass

        # Release other completed requests
        for r in completed[:-1]:
            try:
                buf = r.buffers[self._stream]
                nr = self._camera.create_request()
                nr.add_buffer(self._stream, buf)
                self._camera.queue_request(nr)
            except Exception:
                pass

        return array, metadata

    def set_controls(self, controls: dict[str, Any]) -> None:
        """Queue controls for next request."""
        self._pending_controls.update(controls)

    def capture_dng(self, path: str) -> None:
        logger.warning("DNG capture not supported with raw libcamera backend")


def create_backend(backend_type: str = "auto", camera_num: int = 0) -> CameraBackend:
    """Factory: create camera backend.

    backend_type: "auto" (prefer picamera2), "picamera2", "libcamera"
    """
    if backend_type == "picamera2":
        return Picamera2Backend(camera_num)

    if backend_type == "libcamera":
        return LibcameraBackend(camera_num)

    # Auto: prefer picamera2, fall back to libcamera
    try:
        import picamera2
        logger.info("Auto-detected picamera2")
        return Picamera2Backend(camera_num)
    except ImportError:
        pass

    try:
        import libcamera
        logger.info("Falling back to raw libcamera")
        return LibcameraBackend(camera_num)
    except ImportError:
        pass

    raise RuntimeError("Neither picamera2 nor libcamera Python bindings found")
