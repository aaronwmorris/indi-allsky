import subprocess
import struct
import threading
import time
import os
import json
import io

from flask import Blueprint, jsonify, request, Response, current_app as app
from flask.views import View
from flask_login import login_required

try:
    from flask_sock import Sock
    _has_flask_sock = True
except ImportError:
    _has_flask_sock = False

bp_captureapi_allsky = Blueprint(
    "captureapi_indi_allsky",
    __name__,
    url_prefix="/indi-allsky",
)

CAPTURE_CMD = "rpicam-still"
STREAM_CMD = "rpicam-vid"
CAMERA_ID = 0
HTDOCS = "/var/www/html/allsky/images"
DB_PATH = "/var/lib/indi-allsky/indi-allsky.sqlite"


# ---------------------------------------------------------------------------
# Allsky service helpers
# ---------------------------------------------------------------------------

LOCK_FILE = "/tmp/allsky-stream.lock"


def _systemctl(*args):
    """Run systemctl command, trying sudo (system) first, then --user."""
    cmd = ["sudo", "systemctl"] + list(args)
    r = subprocess.run(cmd, capture_output=True, timeout=10)
    if r.returncode != 0:
        cmd = ["systemctl", "--user"] + list(args)
        r = subprocess.run(cmd, capture_output=True, timeout=10)
    return r


def _stop_allsky():
    """No-op: picamera2 daemon owns the camera; no service contention."""
    pass


def _start_allsky():
    """No-op: picamera2 daemon owns the camera; no service contention."""
    pass


# ---------------------------------------------------------------------------
# Single-shot capture (Capture One button)
# ---------------------------------------------------------------------------

def _capture(output_path, quality=90, width=None, height=None,
             shutter=None, gain=None, awb=None, brightness=None,
             contrast=None, saturation=None, sharpness=None,
             denoise=None, ev=None, awbgains=None):
    """Capture a single frame via the picamera2 daemon."""
    from ..camera.picamera2_client import Picamera2Client
    try:
        client = Picamera2Client()
        exposure = shutter / 1e6 if shutter else None
        result = client.capture_still(exposure=exposure, gain=gain, timeout=30)
        client.close()
        if not result.get('ok'):
            return False, result.get('error', 'Capture failed')

        # Load the numpy frame and save as JPEG
        import numpy as np
        try:
            import cv2
        except ImportError:
            return False, "OpenCV not available"

        frame = np.load(result['frame_path'])
        bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        cv2.imwrite(output_path, bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return True, ""
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _get_config():
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT data FROM config ORDER BY createDate DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if row:
        return json.loads(row[0]) if isinstance(row[0], str) else row[0]
    return {}


def _save_config(config_data, note="slider update"):
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    cur.execute(
        "INSERT INTO config (createDate, level, encrypted, note, data) VALUES (?, 'user', 0, ?, ?)",
        (now, note, json.dumps(config_data)),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# MJPEG Stream Manager - single rpicam-vid process, multiple clients
# ---------------------------------------------------------------------------

class MJPEGStreamManager:
    """Reads JPEG frames from the picamera2 daemon's shared memory.

    No subprocess — the daemon owns the camera and both capture and
    streaming read from the same shared frame buffer.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._client = None
        self._frame = None
        self._frame_event = threading.Event()
        self._client_count = 0
        self._settings = {}
        self._running = False
        self._metadata = {}
        self._frame_count = 0
        self._start_time = 0
        self._reader_thread = None
        self._last_seq = -1

    @property
    def running(self):
        return self._running

    @property
    def client_count(self):
        return self._client_count

    def start(self, settings=None):
        """Connect to picamera2 daemon shared memory. Returns (ok, error_msg)."""
        from ..camera.picamera2_client import Picamera2Client
        with self._lock:
            if settings is None:
                settings = {}
            self._settings = settings
            self._running = True
            self._frame_count = 0
            self._start_time = time.monotonic()
            self._client = Picamera2Client()
            self._reader_thread = threading.Thread(
                target=self._read_frames, daemon=True)
            self._reader_thread.start()
        # Wait for first frame (up to 5s)
        for _ in range(50):
            if self._frame is not None:
                return True, ""
            time.sleep(0.1)
        if self._running:
            return True, ""  # daemon running but slow
        return False, "No frames from picamera2 daemon"

    def stop(self):
        with self._lock:
            self._running = False
            if self._client:
                self._client.close()
                self._client = None

    def update_settings(self, settings):
        """Send updated settings to the daemon. Returns (ok, error_msg)."""
        self._settings.update(settings)
        if self._client:
            try:
                s = settings
                if s.get("shutter") or s.get("gain"):
                    self._client.set_controls(
                        exposure=float(s["shutter"]) / 1e6 if s.get("shutter") else None,
                        gain=float(s["gain"]) if s.get("gain") else None,
                    )
                if s.get("width") or s.get("height") or s.get("quality"):
                    self._client.set_stream(
                        width=int(s["width"]) if s.get("width") else None,
                        height=int(s["height"]) if s.get("height") else None,
                        quality=int(s["quality"]) if s.get("quality") else None,
                    )
            except Exception:
                pass
        return True, ""

    def _read_frames(self):
        """Poll shared memory for new JPEG frames from the daemon."""
        while self._running:
            try:
                result = self._client.get_stream_jpeg()
                if result is not None:
                    jpeg, seq = result
                    if seq != self._last_seq:
                        self._last_seq = seq
                        self._frame = jpeg
                        self._frame_count += 1
                        self._frame_event.set()
                        self._frame_event.clear()
                # Also update metadata
                try:
                    meta_resp = self._client.get_metadata()
                    if meta_resp.get('ok'):
                        self._metadata = meta_resp.get('metadata', {})
                except Exception:
                    pass
            except Exception:
                pass
            time.sleep(0.03)  # ~30Hz poll

    def get_frame(self, timeout=5.0):
        if self._frame is not None:
            return self._frame
        self._frame_event.wait(timeout=timeout)
        return self._frame

    def wait_new_frame(self, last_count, timeout=5.0):
        deadline = time.monotonic() + timeout
        while self._running and time.monotonic() < deadline:
            if self._frame_count > last_count and self._frame is not None:
                return self._frame, self._frame_count
            time.sleep(0.02)
        return None, last_count

    def generate(self):
        """Generator yielding multipart MJPEG frames for a streaming response."""
        self._client_count += 1
        try:
            last_frame = None
            while self._running:
                frame = self._frame
                if frame is not None and frame is not last_frame:
                    last_frame = frame
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n'
                           b'Content-Length: ' + str(len(frame)).encode() + b'\r\n'
                           b'\r\n' + frame + b'\r\n')
                else:
                    time.sleep(0.03)
        finally:
            self._client_count -= 1

    def get_settings(self):
        return dict(self._settings)

    def get_metadata(self):
        """Return latest ISP metadata + stream stats."""
        meta = dict(self._metadata)
        elapsed = time.monotonic() - self._start_time if self._start_time else 0
        meta["_stream"] = {
            "frames": self._frame_count,
            "elapsed": round(elapsed, 1),
            "fps": round(self._frame_count / elapsed, 1) if elapsed > 1 else 0,
            "clients": self._client_count,
        }
        # Normalize common ISP keys
        if "ExposureTime" in meta:
            meta["exposure"] = round(meta["ExposureTime"] / 1_000_000, 6)
        if "AnalogueGain" in meta:
            meta["gain"] = round(meta["AnalogueGain"], 2)
        if "SensorTemperature" in meta:
            meta["sensor_temp"] = meta["SensorTemperature"]
        if "Lux" in meta:
            meta["lux"] = round(meta["Lux"], 1)
        if "ColourTemperature" in meta:
            meta["colour_temp"] = meta["ColourTemperature"]
        return meta


# Global stream manager instance
_stream = MJPEGStreamManager()


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

class ConfigGetMethodView(View):
    decorators = [login_required]
    methods = ["GET"]

    def dispatch_request(self):
        try:
            cfg = _get_config()
            ccd = cfg.get("CCD_CONFIG", {})
            result = {
                "NIGHT_GAIN": ccd.get("NIGHT", {}).get("GAIN", 0),
                "MOONMODE_GAIN": ccd.get("MOONMODE", {}).get("GAIN", 0),
                "DAY_GAIN": ccd.get("DAY", {}).get("GAIN", 0),
                "CCD_EXPOSURE_MAX": cfg.get("CCD_EXPOSURE_MAX", 30),
                "CCD_EXPOSURE_DEF": cfg.get("CCD_EXPOSURE_DEF", 5),
                "TARGET_ADU": cfg.get("TARGET_ADU", 75),
                "TARGET_ADU_DAY": cfg.get("TARGET_ADU_DAY", 100),
                "SATURATION_FACTOR": cfg.get("SATURATION_FACTOR", 1.0),
                "SATURATION_FACTOR_DAY": cfg.get("SATURATION_FACTOR_DAY", 1.0),
                "GAMMA_CORRECTION": cfg.get("GAMMA_CORRECTION", 1.0),
                "GAMMA_CORRECTION_DAY": cfg.get("GAMMA_CORRECTION_DAY", 1.0),
                "SHARPEN_AMOUNT": cfg.get("SHARPEN_AMOUNT", 0.0),
                "SHARPEN_AMOUNT_DAY": cfg.get("SHARPEN_AMOUNT_DAY", 0.0),
                "IMAGE_FLIP_V": cfg.get("IMAGE_FLIP_V", False),
                "IMAGE_FLIP_H": cfg.get("IMAGE_FLIP_H", False),
                "EXPOSURE_PERIOD": cfg.get("EXPOSURE_PERIOD", 35),
                "EXPOSURE_PERIOD_DAY": cfg.get("EXPOSURE_PERIOD_DAY", 15),
            }
            return jsonify(result), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500


class ConfigSetMethodView(View):
    decorators = [login_required]
    methods = ["POST"]

    def dispatch_request(self):
        try:
            updates = request.get_json(force=True)
            if not updates:
                return jsonify({"error": "No data"}), 400
            cfg = _get_config()
            ccd = cfg.setdefault("CCD_CONFIG", {})
            key_map = {
                "NIGHT_GAIN": lambda v: ccd.setdefault("NIGHT", {}).update({"GAIN": float(v)}),
                "MOONMODE_GAIN": lambda v: ccd.setdefault("MOONMODE", {}).update({"GAIN": float(v)}),
                "DAY_GAIN": lambda v: ccd.setdefault("DAY", {}).update({"GAIN": float(v)}),
            }
            flat_keys = [
                "CCD_EXPOSURE_MAX", "CCD_EXPOSURE_DEF", "EXPOSURE_PERIOD", "EXPOSURE_PERIOD_DAY",
                "SATURATION_FACTOR", "SATURATION_FACTOR_DAY",
                "GAMMA_CORRECTION", "GAMMA_CORRECTION_DAY",
                "SHARPEN_AMOUNT", "SHARPEN_AMOUNT_DAY",
            ]
            int_keys = ["TARGET_ADU", "TARGET_ADU_DAY"]
            bool_keys = ["IMAGE_FLIP_V", "IMAGE_FLIP_H"]
            changed = []
            for k, v in updates.items():
                if k in key_map:
                    key_map[k](v)
                    changed.append(k)
                elif k in flat_keys:
                    cfg[k] = float(v)
                    changed.append(k)
                elif k in int_keys:
                    cfg[k] = int(v)
                    changed.append(k)
                elif k in bool_keys:
                    cfg[k] = bool(v)
                    changed.append(k)
            if changed:
                _save_config(cfg, note="live slider: " + ", ".join(changed))
            return jsonify({"message": "Config updated", "changed": changed}), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500


class CaptureOneMethodView(View):
    decorators = [login_required]
    methods = ["GET"]

    def dispatch_request(self):
        try:
            dest = os.path.join(HTDOCS, "capture_one.jpg")

            # If stream is running, grab a frame from it (no rpicam-still needed)
            if _stream.running:
                frame = _stream.get_frame(timeout=5)
                if frame is None:
                    return jsonify({"error": "Stream active but no frame available"}), 500
                with open(dest, "wb") as f:
                    f.write(frame)
                return jsonify({
                    "url": "/indi-allsky/images/capture_one.jpg?t=" + str(int(time.time())),
                    "message": "Captured from stream",
                }), 200

            # No stream running - stop allsky, do a still capture, restart
            _stop_allsky()
            ok, err = _capture(dest, quality=90,
                               shutter=request.args.get("shutter", None, type=int),
                               gain=request.args.get("gain", None, type=float),
                               awb=request.args.get("awb", None),
                               brightness=request.args.get("brightness", None, type=float),
                               contrast=request.args.get("contrast", None, type=float),
                               saturation=request.args.get("saturation", None, type=float),
                               sharpness=request.args.get("sharpness", None, type=float),
                               awbgains=request.args.get("awbgains", None))
            _start_allsky()

            if not ok:
                return jsonify({"error": err}), 500
            return jsonify({
                "url": "/indi-allsky/images/capture_one.jpg?t=" + str(int(time.time())),
                "message": "Captured",
            }), 200
        except subprocess.TimeoutExpired:
            _start_allsky()
            return jsonify({"error": "Capture timed out"}), 500
        except Exception as e:
            _start_allsky()
            return jsonify({"error": str(e)}), 500


class StreamStartMethodView(View):
    decorators = [login_required]
    methods = ["GET"]

    def dispatch_request(self):
        settings = {}
        for key in ["shutter", "gain", "brightness", "contrast",
                     "saturation", "sharpness", "awb", "awbgains",
                     "denoise", "framerate"]:
            val = request.args.get(key, None)
            if val is not None:
                settings[key] = val
        ok, err = _stream.start(settings)
        if not ok:
            return jsonify({"error": err}), 500
        return jsonify({"message": "Stream started",
                        "clients": _stream.client_count}), 200


class StreamStopMethodView(View):
    decorators = [login_required]
    methods = ["GET"]

    def dispatch_request(self):
        _stream.stop()
        return jsonify({"message": "Stream stopped, allsky restarting"}), 200


class StreamUpdateMethodView(View):
    decorators = [login_required]
    methods = ["GET"]

    def dispatch_request(self):
        """Update stream settings on the fly - restarts rpicam-vid."""
        settings = {}
        for key in ["shutter", "gain", "brightness", "contrast",
                     "saturation", "sharpness", "awb", "awbgains",
                     "denoise", "framerate"]:
            val = request.args.get(key, None)
            if val is not None:
                settings[key] = val
        if not _stream.running:
            return jsonify({"error": "Stream not running"}), 400
        ok, err = _stream.update_settings(settings)
        if not ok:
            return jsonify({"error": err}), 500
        return jsonify({"message": "Settings updated",
                        "clients": _stream.client_count}), 200


class StreamMJPEGMethodView(View):
    decorators = [login_required]
    methods = ["GET"]

    def dispatch_request(self):
        """MJPEG multipart stream - connect <img src> directly to this."""
        # Wait up to 5s for stream to be ready
        for _ in range(50):
            if _stream.running and _stream._frame is not None:
                break
            time.sleep(0.1)
        if not _stream.running:
            return jsonify({"error": "Stream not running. Start it first."}), 400
        return Response(
            _stream.generate(),
            mimetype='multipart/x-mixed-replace; boundary=frame',
        )


class StreamStatusMethodView(View):
    decorators = [login_required]
    methods = ["GET"]

    def dispatch_request(self):
        elapsed = time.monotonic() - _stream._start_time if _stream._start_time else 0
        return jsonify({
            "running": _stream.running,
            "clients": _stream.client_count,
            "frames": _stream._frame_count,
            "fps": round(_stream._frame_count / elapsed, 1) if elapsed > 1 else 0,
            "settings": _stream.get_settings(),
        }), 200


# Keep old endpoints for backwards compat (they still work)
class LiveStartMethodView(View):
    decorators = [login_required]
    methods = ["GET"]

    def dispatch_request(self):
        settings = {}
        for key in ["shutter", "gain", "brightness", "contrast",
                     "saturation", "sharpness", "awb", "awbgains", "denoise"]:
            val = request.args.get(key, None)
            if val is not None:
                settings[key] = val
        ok, err = _stream.start(settings)
        if not ok:
            return jsonify({"error": err}), 500
        return jsonify({"message": "Live mode started (MJPEG stream)"}), 200


class LiveStopMethodView(View):
    decorators = [login_required]
    methods = ["GET"]

    def dispatch_request(self):
        _stream.stop()
        return jsonify({"message": "Live mode stopped"}), 200


class LiveFrameMethodView(View):
    decorators = [login_required]
    methods = ["GET"]

    def dispatch_request(self):
        """Legacy: return latest frame as a single JPEG URL."""
        if not _stream.running:
            return jsonify({"error": "Stream not active"}), 400
        frame = _stream.get_frame(timeout=5)
        if frame is None:
            return jsonify({"error": "No frame available"}), 500
        # Write frame to htdocs for URL access
        dest = os.path.join(HTDOCS, "live_frame.jpg")
        with open(dest, "wb") as f:
            f.write(frame)
        return jsonify({
            "url": "/indi-allsky/images/live_frame.jpg?t=" + str(int(time.time())),
            "message": "Live",
        }), 200


class StreamMetadataMethodView(View):
    decorators = [login_required]
    methods = ["GET"]

    def dispatch_request(self):
        """Return live ISP metadata from rpicam-vid (exposure, gain, temp, etc.)."""
        if not _stream.running:
            return jsonify({"error": "Stream not running"}), 400
        return jsonify(_stream.get_metadata()), 200


class SensorInfoMethodView(View):
    decorators = [login_required]
    methods = ["GET"]

    def dispatch_request(self):
        """Auto-detect camera sensor via picamera2 daemon."""
        from ..camera.picamera2_client import Picamera2Client
        try:
            client = Picamera2Client()
            info = client.get_sensor_info()
            client.close()
            if not info.get("ok"):
                return jsonify({"error": "Daemon not available"}), 500
            return jsonify({
                "sensor": info.get("sensor_name", "unknown"),
                "label": info.get("sensor_name", "unknown"),
                "gain_min": info.get("min_gain", 0),
                "gain_max": info.get("max_gain", 100),
                "exposure_min": info.get("min_exposure", 0),
                "exposure_max": info.get("max_exposure", 60),
                "width": info.get("width", 0),
                "height": info.get("height", 0),
                "cfa": info.get("cfa", ""),
            }), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# URL rules
# ---------------------------------------------------------------------------

bp_captureapi_allsky.add_url_rule("/api/capture_one", view_func=CaptureOneMethodView.as_view("captureapi_capture_one"), methods=["GET"])
bp_captureapi_allsky.add_url_rule("/api/live_start", view_func=LiveStartMethodView.as_view("captureapi_live_start"), methods=["GET"])
bp_captureapi_allsky.add_url_rule("/api/live_stop", view_func=LiveStopMethodView.as_view("captureapi_live_stop"), methods=["GET"])
bp_captureapi_allsky.add_url_rule("/api/live_frame", view_func=LiveFrameMethodView.as_view("captureapi_live_frame"), methods=["GET"])
bp_captureapi_allsky.add_url_rule("/api/stream/start", view_func=StreamStartMethodView.as_view("captureapi_stream_start"), methods=["GET"])
bp_captureapi_allsky.add_url_rule("/api/stream/stop", view_func=StreamStopMethodView.as_view("captureapi_stream_stop"), methods=["GET"])
bp_captureapi_allsky.add_url_rule("/api/stream/update", view_func=StreamUpdateMethodView.as_view("captureapi_stream_update"), methods=["GET"])
bp_captureapi_allsky.add_url_rule("/api/stream/feed.mjpeg", view_func=StreamMJPEGMethodView.as_view("captureapi_stream_feed"), methods=["GET"])
bp_captureapi_allsky.add_url_rule("/api/stream/status", view_func=StreamStatusMethodView.as_view("captureapi_stream_status"), methods=["GET"])
bp_captureapi_allsky.add_url_rule("/api/stream/metadata", view_func=StreamMetadataMethodView.as_view("captureapi_stream_metadata"), methods=["GET"])
bp_captureapi_allsky.add_url_rule("/api/config_get", view_func=ConfigGetMethodView.as_view("captureapi_config_get"), methods=["GET"])
bp_captureapi_allsky.add_url_rule("/api/config_set", view_func=ConfigSetMethodView.as_view("captureapi_config_set"), methods=["POST"])
bp_captureapi_allsky.add_url_rule("/api/sensor_info", view_func=SensorInfoMethodView.as_view("captureapi_sensor_info"), methods=["GET"])


# ---------------------------------------------------------------------------
# WebSocket stream (requires flask-sock)
# ---------------------------------------------------------------------------

def register_websocket(app):
    """Register the WebSocket stream endpoint if flask-sock is available.

    Call this from the Flask app factory after registering blueprints.
    Wire format per frame (binary message):
        [4 bytes]  uint32 big-endian — length of JSON header
        [N bytes]  UTF-8 JSON metadata (ISP values, WB gains, mode, etc.)
        [rest]     JPEG image data

    This reads directly from the picamera2 daemon's shared memory,
    so it works regardless of whether the MJPEG stream manager is running.
    Both capture and streaming share the same camera — no contention.
    """
    if not _has_flask_sock:
        return

    sock = Sock(app)

    @sock.route("/indi-allsky/api/stream/ws")
    def stream_ws(ws):
        """WebSocket endpoint: binary frames with per-frame metadata."""
        from ..camera.picamera2_client import Picamera2Client

        client = Picamera2Client()
        last_seq = -1
        frame_count = 0
        start_time = time.monotonic()

        try:
            while True:
                # Read JPEG frame from daemon shared memory
                result = client.get_stream_jpeg()
                if result is None:
                    time.sleep(0.1)
                    # Send keepalive every 5s
                    try:
                        ws.send(b"")
                    except Exception:
                        break
                    continue

                jpeg, seq = result
                if seq == last_seq:
                    time.sleep(0.02)  # ~50Hz poll
                    continue
                last_seq = seq
                frame_count += 1

                # Get metadata from daemon
                meta = {}
                try:
                    meta_resp = client.get_metadata()
                    if meta_resp.get("ok"):
                        raw_meta = meta_resp.get("metadata", {})

                        # Normalize ISP keys (same format as allsky-indie-ng)
                        exp_us = raw_meta.get("ExposureTime", 0)
                        meta["exposure"] = round(exp_us / 1_000_000, 6) if exp_us else 0
                        meta["gain"] = round(raw_meta.get("AnalogueGain", 0), 2)
                        meta["lux"] = round(raw_meta.get("Lux", 0), 1)
                        meta["colour_temp"] = raw_meta.get("ColourTemperature", 0)
                        meta["sensor_temp"] = raw_meta.get("SensorTemperature")
                        meta["ae_state"] = raw_meta.get("AeState", -1)

                        # White balance gains (red, blue relative to green)
                        colour_gains = raw_meta.get("ColourGains", (1.0, 1.0))
                        if isinstance(colour_gains, (list, tuple)) and len(colour_gains) >= 2:
                            meta["red_gain"] = round(float(colour_gains[0]), 3)
                            meta["blue_gain"] = round(float(colour_gains[1]), 3)

                        elapsed = time.monotonic() - start_time
                        meta["frame"] = frame_count
                        meta["fps"] = round(frame_count / elapsed, 1) if elapsed > 1 else 0
                except Exception:
                    pass

                # Pack: [4-byte JSON length][JSON bytes][JPEG bytes]
                try:
                    meta_bytes = json.dumps(meta, separators=(",", ":"), default=str).encode("utf-8")
                    header = struct.pack(">I", len(meta_bytes))
                    ws.send(header + meta_bytes + jpeg)
                except Exception:
                    break
        finally:
            client.close()
