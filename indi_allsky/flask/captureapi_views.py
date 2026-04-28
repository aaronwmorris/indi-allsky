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
    """Update the latest config row in-place, or insert if none exists."""
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    data_json = json.dumps(config_data)
    cur.execute(
        "UPDATE config SET data=? WHERE id=(SELECT id FROM config ORDER BY id DESC LIMIT 1)",
        (data_json,),
    )
    if cur.rowcount == 0:
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        cur.execute(
            "INSERT INTO config (createDate, level, encrypted, note, data) VALUES (?, '0', 0, ?, ?)",
            (now, note, data_json),
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
        """Poll shared memory for new JPEG frames from the daemon.

        Only updates when a genuinely new frame arrives (seq changes).
        Metadata is fetched once per new frame, not continuously.
        """
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
                        # Fetch metadata only when we have a new frame
                        try:
                            meta_resp = self._client.get_metadata()
                            if meta_resp.get('ok'):
                                self._metadata = meta_resp.get('metadata', {})
                        except Exception:
                            pass
            except Exception:
                pass
            time.sleep(0.1)  # poll rate — no need to be faster than frame rate

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
        """Generator yielding MJPEG parts — always the latest frame, never queued.

        Blocks until a new frame arrives, then sends it.  If multiple
        frames arrived while the previous send was in flight, only the
        latest is sent — intermediates are dropped.
        """
        self._client_count += 1
        try:
            while self._running:
                # Always grab whatever is latest RIGHT NOW
                frame = self._frame
                seq = self._last_seq
                if frame is not None:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n'
                           b'Content-Length: ' + str(len(frame)).encode() + b'\r\n'
                           b'\r\n' + frame + b'\r\n')
                # Wait for a NEW frame (seq must change)
                wait_for = seq
                while self._running and self._last_seq == wait_for:
                    self._frame_event.wait(timeout=1)
        finally:
            self._client_count -= 1

    def get_settings(self):
        return dict(self._settings)

    def get_metadata(self):
        """Return latest ISP metadata + stream stats."""
        meta = dict(self._metadata)
        elapsed = time.monotonic() - self._start_time if self._start_time else 0
        capture_time = meta.get("_capture_time", 0)
        frame_age = round(time.time() - capture_time, 1) if capture_time else None
        meta["_stream"] = {
            "frames": self._frame_count,
            "elapsed": round(elapsed, 1),
            "fps": round(self._frame_count / elapsed, 1) if elapsed > 1 else 0,
            "clients": self._client_count,
        }
        meta["frame_age"] = frame_age
        # Normalize common ISP keys — prefer requested values over ISP actual
        if "requested_exposure" in meta:
            meta["exposure"] = round(meta["requested_exposure"] / 1_000_000, 2)
        elif "ExposureTime" in meta:
            meta["exposure"] = round(meta["ExposureTime"] / 1_000_000, 2)
        if "requested_gain" in meta:
            meta["gain"] = round(meta["requested_gain"], 2)
        elif "AnalogueGain" in meta:
            meta["gain"] = round(meta["AnalogueGain"], 2)
        # Also include ISP actual values for OSD/debug
        if "ExposureTime" in meta:
            meta["actual_exposure"] = round(meta["ExposureTime"] / 1_000_000, 2)
        if "AnalogueGain" in meta:
            meta["actual_gain"] = round(meta["AnalogueGain"], 2)
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
    methods = ["GET"]

    def dispatch_request(self):
        """Update camera settings live via the picamera2 daemon AND config DB."""
        _ensure_stream()
        from ..camera.picamera2_client import Picamera2Client
        try:
            client = Picamera2Client()
            controls = {}
            shutter = request.args.get("shutter")
            if shutter and float(shutter) > 0:
                controls["exposure"] = float(shutter) / 1e6
            gain = request.args.get("gain")
            if gain and float(gain) > 0:
                controls["gain"] = float(gain)
            awb = request.args.get("awb")
            if awb:
                controls["awb"] = awb != "off"
            if controls:
                client.set_controls(**controls)

            # Stream settings → daemon
            stream_kwargs = {}
            quality = request.args.get("quality")
            if quality:
                stream_kwargs["quality"] = int(float(quality))
            sw = request.args.get("stream_width")
            sh = request.args.get("stream_height")
            if sw and sh:
                stream_kwargs["width"] = int(sw)
                stream_kwargs["height"] = int(sh)
            osd = request.args.get("osd")
            if osd is not None:
                stream_kwargs["osd"] = osd.lower() in ("1", "true", "on")
            if stream_kwargs:
                client.set_stream(**stream_kwargs)

            client.close()

            # Also update the indi-allsky config DB so capture worker uses these
            try:
                config = _get_config()
                if gain and float(gain) > 0:
                    gain_f = float(gain)
                    # Update gain for current mode
                    if config.get("CCD_CONFIG", {}).get("NIGHT", {}).get("GAIN") is not None:
                        config["CCD_CONFIG"]["NIGHT"]["GAIN"] = gain_f
                    if config.get("CCD_CONFIG", {}).get("MOONMODE", {}).get("GAIN") is not None:
                        config["CCD_CONFIG"]["MOONMODE"]["GAIN"] = gain_f
                    if config.get("CCD_CONFIG", {}).get("DAY", {}).get("GAIN") is not None:
                        config["CCD_CONFIG"]["DAY"]["GAIN"] = gain_f
                if shutter and float(shutter) > 0:
                    exp_s = float(shutter) / 1e6
                    config["CCD_EXPOSURE_MAX"] = exp_s
                    config["CCD_EXPOSURE_DEF"] = exp_s
                if "target_adu" in request.args:
                    config["TARGET_ADU"] = int(float(request.args["target_adu"]))
                if "autoexp" in request.args:
                    config["TARGET_ADU_DISABLE"] = request.args["autoexp"].lower() not in ("1", "true", "on")
                _save_config(config, note="live control update")
            except Exception:
                pass  # non-fatal: daemon controls still applied

            # Queue indi-allsky reload so capture worker picks up changes
            try:
                from ..flask.models import IndiAllSkyDbTaskQueueTable
                from ..flask import db
                from .. import constants
                task = IndiAllSkyDbTaskQueueTable(
                    queue=constants.TaskQueueQueue.MAIN,
                    state=constants.TaskQueueState.MANUAL,
                    priority=100,
                    data={'action': 'reload'},
                )
                db.session.add(task)
                db.session.commit()
            except Exception:
                pass  # non-fatal

            return jsonify({"message": "Settings applied"}), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500


def _ensure_stream():
    """Auto-start the stream manager if not already running."""
    if not _stream.running:
        _stream.start()


class StreamMJPEGMethodView(View):
    decorators = [login_required]
    methods = ["GET"]

    def dispatch_request(self):
        """MJPEG multipart stream - connect <img src> directly to this."""
        _ensure_stream()
        # Wait up to 5s for first frame
        for _ in range(50):
            if _stream.running and _stream._frame is not None:
                break
            time.sleep(0.1)
        if not _stream.running:
            return jsonify({"error": "Stream failed to start."}), 500
        return Response(
            _stream.generate(),
            mimetype='multipart/x-mixed-replace; boundary=frame',
        )


class StreamFrameMethodView(View):
    """Single-frame endpoint: reads latest JPEG directly from shared memory.

    No login required — img.src fetches don't reliably send session cookies.
    """
    methods = ["GET"]

    def dispatch_request(self):
        from ..camera.picamera2_client import Picamera2Client
        try:
            client = Picamera2Client()
            result = client.get_stream_jpeg()
            client.close()
            if result is None:
                return Response(b'', status=204)
            jpeg, seq = result
            return Response(jpeg, mimetype='image/jpeg',
                            headers={'Cache-Control': 'no-cache, no-store, must-revalidate',
                                     'Pragma': 'no-cache',
                                     'Expires': '0',
                                     'X-Frame-Seq': str(seq)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


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
        """Return live ISP metadata directly from the picamera2 daemon."""
        from ..camera.picamera2_client import Picamera2Client
        try:
            client = Picamera2Client()
            meta_resp = client.get_metadata()
            client.close()
            if not meta_resp.get('ok'):
                return jsonify({"error": "No metadata"}), 503
            raw = meta_resp.get('metadata', {})
            # Normalize keys
            meta = {}
            req_exp = raw.get("requested_exposure")
            exp_us = req_exp if req_exp else raw.get("ExposureTime", 0)
            req_gain = raw.get("requested_gain")
            gain_val = req_gain if req_gain else raw.get("AnalogueGain", 0)
            meta["exposure"] = round(exp_us / 1_000_000, 2) if exp_us else 0
            meta["gain"] = round(gain_val, 2) if gain_val else 0
            meta["lux"] = round(raw.get("Lux", 0), 1)
            meta["colour_temp"] = raw.get("ColourTemperature", 0)
            meta["sensor_temp"] = raw.get("SensorTemperature")
            ct = raw.get("_capture_time", 0)
            meta["frame_age"] = round(time.time() - ct, 1) if ct > 1e9 else None
            meta["frame"] = raw.get("frame_count", 0)
            colour_gains = raw.get("ColourGains", (1.0, 1.0))
            if isinstance(colour_gains, (list, tuple)) and len(colour_gains) >= 2:
                meta["red_gain"] = round(float(colour_gains[0]), 3)
                meta["blue_gain"] = round(float(colour_gains[1]), 3)
            return jsonify(meta), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500


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


class StreamModesMethodView(View):
    methods = ["GET"]

    def dispatch_request(self):
        """Return available sensor modes and current stream resolution."""
        from ..camera.picamera2_client import Picamera2Client
        try:
            client = Picamera2Client()
            result = client.get_modes()
            client.close()
            if not result.get("ok"):
                return jsonify({"error": "Daemon not available"}), 500
            return jsonify(result), 200
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
bp_captureapi_allsky.add_url_rule("/api/stream/modes", view_func=StreamModesMethodView.as_view("captureapi_stream_modes"), methods=["GET"])


class StreamGetBackendMethodView(View):
    decorators = [login_required]
    methods = ["GET"]

    def dispatch_request(self):
        from ..camera.picamera2_client import Picamera2Client
        try:
            client = Picamera2Client()
            resp = client.get_backend()
            client.close()
            return jsonify(resp), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500


class StreamSetBackendMethodView(View):
    decorators = [login_required]
    methods = ["GET"]

    def dispatch_request(self):
        backend = request.args.get("backend", "auto")
        from ..camera.picamera2_client import Picamera2Client
        try:
            client = Picamera2Client()
            resp = client._send({"cmd": "set_backend", "backend": backend})
            client.close()
            if resp.get("ok"):
                # Persist to DB
                try:
                    config = _get_config()
                    config.setdefault("LIBCAMERA", {})["BACKEND"] = backend
                    _save_config(config, note="driver change from dashboard")
                except Exception:
                    pass
            return jsonify(resp), 200 if resp.get("ok") else 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500


bp_captureapi_allsky.add_url_rule("/api/stream/frame.jpg", view_func=StreamFrameMethodView.as_view("captureapi_stream_frame"), methods=["GET"])
bp_captureapi_allsky.add_url_rule("/api/stream/get_backend", view_func=StreamGetBackendMethodView.as_view("captureapi_stream_get_backend"), methods=["GET"])
bp_captureapi_allsky.add_url_rule("/api/stream/set_backend", view_func=StreamSetBackendMethodView.as_view("captureapi_stream_set_backend"), methods=["GET"])


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
        last_meta_time = 0
        cached_meta = {}
        sent_initial = False

        try:
            while True:
                # Always grab the most recent frame from shm
                result = client.get_stream_jpeg()
                if result is None:
                    time.sleep(0.1)
                    try:
                        ws.send(b"")
                    except Exception:
                        break
                    continue

                jpeg, seq = result

                # Always send the first frame immediately on connect,
                # even if it's the same seq (stale from a long exposure)
                if not sent_initial:
                    sent_initial = True
                    last_seq = seq
                    frame_count += 1
                elif seq == last_seq:
                    time.sleep(0.1)
                    continue
                else:
                    last_seq = seq
                    frame_count += 1

                # Refresh metadata ~1s
                now = time.monotonic()
                if now - last_meta_time > 1.0:
                    try:
                        meta_resp = client.get_metadata()
                        if meta_resp.get("ok"):
                            raw_meta = meta_resp.get("metadata", {})
                            # Prefer requested values over ISP actual
                            req_exp = raw_meta.get("requested_exposure")
                            exp_us = req_exp if req_exp else raw_meta.get("ExposureTime", 0)
                            req_gain = raw_meta.get("requested_gain")
                            gain_val = req_gain if req_gain else raw_meta.get("AnalogueGain", 0)
                            ct = raw_meta.get("_capture_time", 0)
                            cached_meta = {
                                "exposure": round(exp_us / 1_000_000, 2) if exp_us else 0,
                                "gain": round(gain_val, 2),
                                "lux": round(raw_meta.get("Lux", 0), 1),
                                "colour_temp": raw_meta.get("ColourTemperature", 0),
                                "sensor_temp": raw_meta.get("SensorTemperature"),
                                "ae_state": raw_meta.get("AeState", -1),
                                "frame_age": round(time.time() - ct, 1) if ct else None,
                            }
                            colour_gains = raw_meta.get("ColourGains", (1.0, 1.0))
                            if isinstance(colour_gains, (list, tuple)) and len(colour_gains) >= 2:
                                cached_meta["red_gain"] = round(float(colour_gains[0]), 3)
                                cached_meta["blue_gain"] = round(float(colour_gains[1]), 3)
                    except Exception:
                        pass
                    last_meta_time = now

                meta = dict(cached_meta)
                elapsed = now - start_time
                meta["frame"] = frame_count
                meta["fps"] = round(frame_count / elapsed, 1) if elapsed > 1 else 0

                # Pack and send — if send blocks, we'll skip to the latest
                # frame on the next iteration (shm always has the newest)
                try:
                    meta_bytes = json.dumps(meta, separators=(",", ":"), default=str).encode("utf-8")
                    header = struct.pack(">I", len(meta_bytes))
                    ws.send(header + meta_bytes + jpeg)
                except Exception:
                    break
        finally:
            client.close()
