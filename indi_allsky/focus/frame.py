"""Focus frames: decode the camera stream, stretch it for display, stamp the clock, encode, and add the header.

The packed frame is `HEADER` followed by the JPEG. The header layout is a contract with the page JavaScript.
"""

from __future__ import annotations

import datetime
import functools
import re
import struct
from dataclasses import dataclass
from typing import Any
from typing import Dict
from typing import Optional
from typing import Tuple

import cv2
import numpy as np

from .measure import glare_mask
from .measure import noise_sigma

try:
    import simplejpeg
except ImportError:
    simplejpeg = None


JPEG_QUALITY = 85

STRETCH_BLACK_PERCENTILE = 5.0
STRETCH_WHITE_PERCENTILE = 99.995
STRETCH_WHITE_SIGMA = 60.0
STRETCH_GAMMA = 0.8
STRETCH_MIN_KEPT = 0.01       # Auto's levels: fewer pixels than this share outside the glare mask, and it is ignored
STRETCH_NOISE_SAMPLES = 65536  # Auto's noise: from at most about this many of the kept pixels

HEADER_MAGIC = b'IAFF'
HEADER_VERSION = 1
# magic, version, frame_no, capture_time (epoch s, mid-exposure), exposure (s), gain, cmd_id
HEADER = struct.Struct('>4sBIdffI')


# --- decode -------------------------------------------------------------------------------------------------------

def decode_stream(data: bytes, w: int, h: int, fmt: str = '') -> Tuple[Optional[np.ndarray], Optional[float]]:
    """One INDI stream blob -> (gray or raw image, full scale), or (None, None) if it is not a frame we know.

    The second element is the value of a full-scale pixel (255.0 or 65535.0) for the stream's bit depth. Blobs are
    told apart by `fmt`, by the JPEG magic, and by their length against w x h.
    """
    if 'jpg' in (fmt or '').lower() or 'jpeg' in (fmt or '').lower() or data[:2] == b'\xff\xd8':
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
        return (img, 255.0) if img is not None else (None, None)

    if len(data) == w * h * 3:
        rgb = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 3)
        return rgb.mean(axis=2).astype(np.uint8), 255.0

    if len(data) == w * h * 2:
        return np.frombuffer(data, dtype='<u2').reshape(h, w), 65535.0

    if len(data) == w * h:
        return np.frombuffer(data, dtype=np.uint8).reshape(h, w), 255.0

    return None, None


# --- stretch and preview ------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Stretch:
    """Display levels, fixed for a stream: black and white in the frame's own counts, and a gamma."""
    black: float
    white: float
    gamma: float = STRETCH_GAMMA

    @classmethod
    def from_frame(cls, gray: np.ndarray, clip: Optional[float] = None) -> Stretch:
        """Black just under the sky, white well above the stars' noise floor (levels tuned on a real sky).

        clip: the clipped level in the frame's counts. With it, the levels come from the pixels outside the glare
        mask (a clipped light such as the moon, and its halo), and white stays at or under `clip`. Without it, from
        every pixel."""
        if clip is None:
            black = float(np.percentile(gray, STRETCH_BLACK_PERCENTILE))
            white = max(
                float(np.percentile(gray, STRETCH_WHITE_PERCENTILE)),
                float(np.median(gray)) + STRETCH_WHITE_SIGMA * noise_sigma(gray),
            )
            return cls(black, white)

        keep = ~glare_mask(gray, clip) & (gray < clip)
        if np.count_nonzero(keep) < STRETCH_MIN_KEPT * gray.size:
            keep = gray < clip  # the glare covers (nearly) the whole frame: drop only the clipped pixels
        values = gray[keep] if np.any(keep) else gray.ravel()
        values = values.astype(np.float64)
        black = float(np.percentile(values, STRETCH_BLACK_PERCENTILE))
        median = float(np.median(values))
        # the noise from the kept pixels: over the whole frame the glare's slope would count as noise
        step = max(1, values.size // STRETCH_NOISE_SAMPLES)
        sigma = 1.4826 * float(np.median(np.abs(values[::step] - median))) + 1e-6
        white = max(float(np.percentile(values, STRETCH_WHITE_PERCENTILE)), median + STRETCH_WHITE_SIGMA * sigma)
        white = min(white, float(clip))
        return cls(black, max(white, black + 1.0))


def preview(gray: np.ndarray, stretch: Optional[Stretch]) -> np.ndarray:
    """2x2 max-pool (a 2 px star keeps its brightness at half size), then the stretch, to uint8.

    With no stretch the picture is linear: counts scaled by the dtype's full range (uint16 / 257, uint8 as is).
    """
    h, w = gray.shape[:2]
    # the kernel's anchor is its lower-right pixel, so [1::2] picks each pool's maximum
    pooled = cv2.dilate(gray, np.ones((2, 2), np.uint8))[1:h - h % 2:2, 1:w - w % 2:2]

    if stretch is None:
        if pooled.dtype == np.uint8:
            return pooled.copy()
        full = float(np.iinfo(pooled.dtype).max) if pooled.dtype.kind in 'ui' else 65535.0
        return np.clip(pooled.astype(np.float64) * (255.0 / full), 0, 255).astype(np.uint8)

    span = max(stretch.white - stretch.black, 1e-6)
    scaled = np.clip((pooled.astype(np.float32) - stretch.black) / span, 0.0, 1.0)
    return (scaled ** stretch.gamma * 255.0).astype(np.uint8)


# --- clock --------------------------------------------------------------------------------------------------------

_FONT = cv2.FONT_HERSHEY_SIMPLEX
CLOCK_FRACTION = 40      # the clock's glyphs are the picture's height over this ...
CLOCK_MIN_HEIGHT = 8     # ... and never fewer rows than this, so a small region's clock stays readable
_CLOCK_CHARS = '0123456789:.# '
ISO_CLOCK_FORMAT = '%Y-%m-%dT%H:%M:%S%:z'   # %:z is the offset as +HH:MM (clock_text fills it on any Python)
_TIMESTAMP_FIELD = re.compile(r'\{timestamp:([^{}]+)\}')


def clock_format(label_system: str, template: str) -> str:
    """The strftime format the overlay prints the sky pictures' timestamp with: the first `{timestamp:FORMAT}` field
    of IMAGE_LABEL_TEMPLATE, outside its `#` setting lines. ISO 8601 when the labels are off (IMAGE_LABEL_SYSTEM is
    neither pillow nor opencv) or the template has no such field."""
    if label_system not in ('pillow', 'opencv'):
        return ISO_CLOCK_FORMAT
    for line in (template or '').splitlines():
        if line.lstrip().startswith('#'):
            continue
        m = _TIMESTAMP_FIELD.search(line)
        if m:
            return m.group(1)
    return ISO_CLOCK_FORMAT


def clock_text(capture_time: float, fmt: str = ISO_CLOCK_FORMAT) -> str:
    """Local time, like the timestamp the overlay prints on the sky pictures (image.py: datetime.fromtimestamp), in
    `fmt`, with the local UTC offset for %z and %:z. Milliseconds follow the format's last %S, so the stamp shows
    the frames' pace."""
    t = datetime.datetime.fromtimestamp(capture_time).astimezone()  # aware: %z is empty on a naive time
    offset = t.strftime('%z')
    fmt = fmt.replace('%:z', offset[:3] + ':' + offset[3:])     # strftime knows %:z only from Python 3.12
    i = fmt.rfind('%S')
    if i < 0 or (i > 0 and fmt[i - 1] == '%'):
        return t.strftime(fmt)
    return '{0:s}.{1:03d}{2:s}'.format(t.strftime(fmt[:i + 2]), t.microsecond // 1000, t.strftime(fmt[i + 2:]))


@functools.lru_cache(maxsize=16)
def _scale_for_ink_height(height: int, thickness: int) -> float:
    """Font scale whose glyphs are `height` rows tall. getTextSize's height is only a nominal line height, so measure
    the ink of a sample drawn at scale 1.0."""
    sample = _CLOCK_CHARS.strip()
    (w, h), baseline = cv2.getTextSize(sample, _FONT, 1.0, thickness)
    canvas = np.zeros((h + baseline + 4 * thickness, w + 4 * thickness), np.uint8)
    cv2.putText(canvas, sample, (thickness, h + thickness), _FONT, 1.0, 255, thickness, cv2.LINE_AA)
    rows = np.where(canvas.any(axis=1))[0]
    return height / float(rows.max() - rows.min() + 1)


@functools.lru_cache(maxsize=32)
def _cell(scale: float, thickness: int, extra: str = '') -> Tuple[int, int, int]:
    """(width, height, baseline) of one character cell: the widest of the digits, the clock's punctuation and `extra`
    (the format's other characters), so every character gets the same room and the digits never shift."""
    chars = _CLOCK_CHARS + extra
    width = max(cv2.getTextSize(c, _FONT, scale, thickness)[0][0] for c in chars)
    (_, height), baseline = cv2.getTextSize(chars, _FONT, scale, thickness)
    return width, height, baseline


def draw_clock(img: np.ndarray, capture_time: float, frame_no: int, fmt: str = ISO_CLOCK_FORMAT) -> None:
    """Draw the capture time (local, in `fmt`; see clock_text) in the bottom-left corner and `#frame` in the
    bottom-right, each white on a black box, one fixed-width cell per character (OpenCV has no monospace font), both
    the same size. Glyphs are img height // CLOCK_FRACTION tall."""
    time_text = clock_text(capture_time, fmt)
    frame_text = '#{0:d}'.format(frame_no)
    height = max(img.shape[0] // CLOCK_FRACTION, CLOCK_MIN_HEIGHT)

    thickness = max(1, height // 12)
    scale = _scale_for_ink_height(height, thickness)
    cell_w, text_h, baseline = _cell(scale, thickness, ''.join(sorted(set(time_text) - set(_CLOCK_CHARS))))

    pad = max(2, height // 5)
    img_h, img_w = img.shape[:2]
    box_y0 = max(img_h - (text_h + baseline + 2 * pad), 0)
    white = 255 if img.ndim == 2 else (255,) * img.shape[2]
    y = img_h - pad - baseline

    def stamp(text: str, box_x0: int) -> None:
        box_x0 = max(box_x0, 0)
        img[box_y0:img_h, box_x0:min(box_x0 + len(text) * cell_w + 2 * pad, img_w)] = 0
        for i, c in enumerate(text):
            w = cv2.getTextSize(c, _FONT, scale, thickness)[0][0]
            cv2.putText(img, c, (box_x0 + pad + i * cell_w + (cell_w - w) // 2, y), _FONT, scale, white, thickness,
                        cv2.LINE_AA)

    stamp(time_text, 0)
    stamp(frame_text, img_w - (len(frame_text) * cell_w + 2 * pad))  # right-aligned in its corner


# --- encode and header --------------------------------------------------------------------------------------------

def encode_jpeg(img: np.ndarray) -> bytes:
    """JPEG at quality 85, with simplejpeg if it is installed, else cv2. `img` is uint8, gray or BGR."""
    if simplejpeg is not None:
        if img.ndim == 2:
            return bytes(simplejpeg.encode_jpeg(np.ascontiguousarray(img[:, :, None]), quality=JPEG_QUALITY, colorspace='GRAY'))
        return bytes(simplejpeg.encode_jpeg(np.ascontiguousarray(img), quality=JPEG_QUALITY, colorspace='BGR'))

    ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise ValueError('JPEG encode failed')
    return buf.tobytes()


def pack_frame(jpeg: bytes, frame_no: int, capture_time: float, exposure: float, gain: float, cmd_id: int) -> bytes:
    return HEADER.pack(HEADER_MAGIC, HEADER_VERSION, frame_no, capture_time, exposure, gain, cmd_id) + jpeg


def unpack_header(b: bytes) -> Dict[str, Any]:
    if len(b) < HEADER.size:
        raise ValueError('frame header needs {0:d} bytes, got {1:d}'.format(HEADER.size, len(b)))

    magic, version, frame_no, capture_time, exposure, gain, cmd_id = HEADER.unpack_from(b)

    if magic != HEADER_MAGIC:
        raise ValueError('bad frame magic {0!r}'.format(magic))
    if version != HEADER_VERSION:
        raise ValueError('unsupported frame version {0:d}'.format(version))

    return {
        'magic': magic,
        'version': version,
        'frame_no': frame_no,
        'capture_time': capture_time,
        'exposure': exposure,
        'gain': gain,
        'cmd_id': cmd_id,
    }
