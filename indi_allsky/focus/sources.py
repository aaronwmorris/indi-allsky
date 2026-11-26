"""Picture sources for a focus session: the camera side of the controller.

A source gives raw frames on its `frames` queue. The controller (controller.py) measures them and sends previews to
the pages. Two sources implement `PictureSource`: `IndiStreamSource` (live video, indi_stream.py) and `StillsSource`
here, which turns any camera client's single exposures into frames.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from typing import NamedTuple
from typing import Optional
from typing import Tuple

import numpy as np

try:
    from typing import Protocol
except ImportError:  # pragma: no cover - Python < 3.8
    Protocol = object


logger = logging.getLogger('indi_allsky')


STATUS_POLL_S = 0.1
JOIN_TIMEOUT_S = 2.0
WHOLE_FRAME_TIMEOUT_S = 30.0

# (x, y, width, height) in sensor pixels
Roi = Tuple[int, int, int, int]


class RawFrame(NamedTuple):
    """One picture from a source.

    raw: the frame as read (a Bayer mosaic or mono), cropped to the region. full_scale: the value of a full-scale
    pixel. bayer: 'RGGB', ... or None for mono. t_end: epoch seconds when the exposure ended (for video, when the
    blob arrived). exposure (s) and gain: the settings this frame was taken with.
    """
    raw: np.ndarray
    full_scale: float
    bayer: Optional[str]
    t_end: float
    exposure: float
    gain: float


class PictureSource(Protocol):
    """What the controller needs from a camera during a session."""

    frames: 'queue.Queue[RawFrame]'
    bayer: Optional[str]  # optional: the pattern of the last picture, for a whole_frame taken before any frame

    def start(self, roi: Optional[Roi], exposure: float, gain: float) -> None:
        ...

    def set_camera(self, exposure: float, gain: float) -> None:
        """New exposure and gain. A video source restarts its stream."""

    def whole_frame(self) -> np.ndarray:
        """One full-sensor picture, for Move region. Called on its own thread while the session runs; it may wait
        for a picture, and must raise once `stop()` is called rather than keep waiting."""

    def stop(self) -> None:
        """Stop the pictures, and release a `whole_frame` that is waiting."""


def normalise_bayer(bayer) -> Optional[str]:
    """'' and None both mean mono (constants.CFA_STR_MAP treats '' as mono)."""
    if not bayer:
        return None
    return str(bayer).strip().upper() or None


def snap_roi(roi: Optional[Roi], shape: Tuple[int, int]) -> Optional[Roi]:
    """The region on the Bayer grid: x and y round down to even, sizes round down to even, clipped to the frame."""
    if roi is None:
        return None
    h, w = shape[:2]
    x, y, rw, rh = (int(v) for v in roi)
    x = max(0, min(x - x % 2, w - w % 2))
    y = max(0, min(y - y % 2, h - h % 2))
    rw = max(0, min(rw - rw % 2, w - x - (w - x) % 2))
    rh = max(0, min(rh - rh % 2, h - y - (h - y) % 2))
    return x, y, rw, rh


def crop(raw: np.ndarray, roi: Optional[Roi]) -> np.ndarray:
    snapped = snap_roi(roi, raw.shape)
    if snapped is None:
        return raw
    x, y, w, h = snapped
    return raw[y:y + h, x:x + w]


def _full_scale_for(dtype) -> float:
    return 255.0 if np.dtype(dtype) == np.uint8 else 65535.0


def load_still(filename: str) -> Tuple[np.ndarray, float, Optional[str]]:
    """(raw, full_scale, bayer) from a camera client's tempfile, read as processing.py reads that suffix."""
    name = filename.lower()

    if name.endswith(('.fit', '.fits', '.fit.gz', '.fits.gz')):
        from astropy.io import fits

        with fits.open(filename) as hdulist:
            header = hdulist[0].header
            data = np.array(hdulist[0].data)
            bitpix = int(header['BITPIX'])
            bayer = normalise_bayer(header.get('BAYERPAT'))
        if data.ndim == 3:  # a colour FITS holds planes; focus on their mean, which is no longer a mosaic
            data = data.mean(axis=0)
            bayer = None
        return data, 255.0 if bitpix == 8 else 65535.0, bayer

    if name.endswith('.dng'):
        import rawpy

        with rawpy.imread(filename) as raw:
            data = np.array(raw.raw_image, copy=True)
            bayer = None
            if raw.raw_pattern is not None:
                try:
                    bayer = ''.join(chr(raw.color_desc[i]) for i in np.asarray(raw.raw_pattern).flatten())
                except IndexError:  # monochrome sensors report patterns like GMYC
                    bayer = None
            if bayer not in ('RGGB', 'GRBG', 'BGGR', 'GBRG'):
                bayer = None
            full_scale = float(raw.white_level or 65535)
        return data, full_scale, bayer

    if name.endswith(('.jpg', '.jpeg', '.png')):
        import cv2

        data = cv2.imread(filename, cv2.IMREAD_UNCHANGED)
        if data is None:
            raise ValueError('unreadable image')
        if data.ndim == 3:
            code = cv2.COLOR_BGRA2GRAY if data.shape[2] == 4 else cv2.COLOR_BGR2GRAY
            data = cv2.cvtColor(data, code)
        return data, _full_scale_for(data.dtype), None

    raise ValueError('unsupported image format')


class _ImageQueueAdapter(object):
    """Stands in for a camera client's `image_q` during a session: takes its jobdata, never the image worker."""

    def __init__(self, source):
        self._source = source

    def put(self, jobdata, *args, **kwargs):
        self._source._accept(jobdata)


class StillsSource(object):
    """Single exposures, back to back, from any camera client that puts jobdata on its `image_q`.

    `image_q_swap(new_q)` installs `new_q` as the camera client's image queue and returns the one it replaced.

    A thread loads each picture, queues a `RawFrame`, deletes the tempfile and starts the next exposure. While it
    waits it polls `getCcdExposureStatus()`, because libcamera queues its picture from that poll and the capture
    loop does not poll during a session.
    """

    def __init__(self, camera, image_q_swap):
        self.camera = camera
        self._swap = image_q_swap
        self.frames = queue.Queue()
        self._jobs = queue.Queue()
        self._lock = threading.Condition()
        self._running = False
        self._old_q = None
        self._thread = None
        self._roi = None
        self._exposure = 0.0
        self._gain = 0.0
        self._last_full = None
        self.bayer = None         # the Bayer pattern of the last picture (None before one, or mono)

    def start(self, roi, exposure, gain):
        if self._running:
            self.stop()
        with self._lock:
            self._roi = roi
            self._exposure = float(exposure)
            self._gain = float(gain)
            self._running = True
        self._jobs = queue.Queue()
        self._old_q = self._swap(_ImageQueueAdapter(self))
        self._thread = threading.Thread(target=self._run, args=(self._jobs,), name='focus-stills', daemon=True)
        self._thread.start()
        self._expose()

    def set_camera(self, exposure, gain):
        with self._lock:
            self._exposure = float(exposure)
            self._gain = float(gain)

    def whole_frame(self, timeout=WHOLE_FRAME_TIMEOUT_S):
        """The last full-sensor picture (stills are always taken whole and cropped here). Raises RuntimeError when
        the source stops before one arrives."""
        deadline = time.monotonic() + timeout
        with self._lock:
            while self._last_full is None:
                if not self._running:
                    raise RuntimeError('the picture source stopped')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('no picture yet')
                self._lock.wait(remaining)
            return self._last_full.copy()

    def stop(self):
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._lock.notify_all()
        # The stills thread may be between its running check and setCcdExposure. Wait for it to finish first, so
        # the abort below catches any exposure it starts, and that picture never reaches capture's own queue.
        self._jobs.put(None)
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(JOIN_TIMEOUT_S)
            if self._thread.is_alive():
                logger.error('Focus stills: the stills thread did not stop within %.0f s', JOIN_TIMEOUT_S)
        self._thread = None
        try:
            self.camera.abortCcdExposure()
        except Exception:
            logger.exception('Focus stills: abort failed')
        self._swap(self._old_q)
        self._old_q = None

    # -- internals ---------------------------------------------------------------------------------------------------

    def _accept(self, jobdata):
        with self._lock:
            running = self._running
            jobs = self._jobs
        if running:
            jobs.put(jobdata)
        else:
            _remove(jobdata)

    def _expose(self):
        with self._lock:
            if not self._running:
                return
            exposure, gain = self._exposure, self._gain
        try:
            self.camera.setCcdExposure(exposure, gain, binning=1, sync=False)
        except Exception:
            logger.exception('Focus stills: exposure failed to start')

    def _run(self, jobs):
        while True:
            try:
                jobdata = jobs.get(timeout=STATUS_POLL_S)
            except queue.Empty:
                with self._lock:
                    if not self._running:
                        return
                try:
                    self.camera.getCcdExposureStatus()
                except Exception:
                    logger.exception('Focus stills: exposure status failed')
                continue
            if jobdata is None:
                return
            with self._lock:
                running = self._running
            if not running:
                _remove(jobdata)
                continue
            self._load(jobdata)
            self._expose()

    def _load(self, jobdata):
        try:
            raw, full_scale, bayer = load_still(str(jobdata['filename']))
        except Exception as e:
            logger.error('Focus stills: could not read a picture: %s', e)
            return
        finally:
            _remove(jobdata)
        with self._lock:
            self._last_full = raw
            self.bayer = bayer
            roi = self._roi
            self._lock.notify_all()
        self.frames.put(RawFrame(
            raw=crop(raw, roi),
            full_scale=full_scale,
            bayer=bayer,
            t_end=float(jobdata.get('exp_time') or time.time()),
            exposure=float(jobdata.get('exposure', 0.0)),
            gain=float(jobdata.get('gain', 0.0)),
        ))


def _remove(jobdata):
    filename = jobdata.get('filename') if isinstance(jobdata, dict) else None
    if not filename:
        return
    try:
        os.unlink(filename)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning('Focus stills: could not delete a tempfile: %s', e)
