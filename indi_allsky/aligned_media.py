"""Render a common geographic sky from a frame's own stellar calibration."""
from functools import partial
import logging
import math

import cv2
import numpy as np

from .exceptions import KeogramMismatchException
from .fisheye import SIN45, projectToPixels


logger = logging.getLogger('indi_allsky')


def projection_values(solution):
    v = solution['values']
    return (v['AZIMUTH_ANGLE'], 0, 0, v['IMAGE_CIRCLE_DIAMETER'], v['OFFSET_X'],
            v['OFFSET_Y'], v['RADIAL_DISTORTION'], v['LENS_ALTITUDE'], v['POINTING_AZIMUTH'])


def frame_geometry(metadata, size):
    """Only use well-formed geometry belonging to the archived image dimensions."""
    if not isinstance(metadata, dict):
        return None
    solution = metadata.get('star_alignment')
    if not isinstance(solution, dict) or solution.get('image_size') != list(size):
        return None
    try:
        params = projection_values(solution)
        if (not all(type(n) in (float, int) and math.isfinite(n) for n in params)
                or params[3] <= 0 or not -.5 <= params[6] <= 1 or not 0 <= params[7] <= 90):
            return None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    return solution


def _stack_coordinates(row):
    if not isinstance(row.data, dict) or 'star_alignment' not in row.data:
        return 'manual'
    if frame_geometry(row.data, (row.width, row.height)) is not None:
        return 'geographic'
    return None


def stack_entries(query, model):
    """Select one coordinate system before streaming a period into a single stack."""
    counts = {'manual': 0, 'geographic': 0}
    # Count using just the optional per-frame metadata, including legacy rows
    # with no key and pending rows with an explicit JSON null on any SQL backend.
    for row in query.with_entities(model.data, model.width, model.height).yield_per(100):
        coordinates = _stack_coordinates(row)
        if coordinates is not None:
            counts[coordinates] += 1
    selected = 'geographic' if counts['geographic'] else 'manual'
    rows = (row for row in query.yield_per(100) if _stack_coordinates(row) == selected)
    return rows, counts[selected]


def process_stack_frame(entry, path, pixels, remap, keogram, startrails, use_db_data):
    """Extract the geographic keogram strip, but apply trail masks in camera coordinates."""
    align = None
    metadata = entry.data
    if isinstance(metadata, dict) and 'star_alignment' in metadata:
        solution = frame_geometry(metadata, (pixels.shape[1], pixels.shape[0]))
        if solution is None:
            return
        align = partial(remap.image, solution=solution)

    if keogram is not None:
        if align:
            keogram.x_offset = keogram.y_offset = 0
        try:
            keogram.processImage(align(pixels) if align else pixels, path.stat().st_mtime)
        except KeogramMismatchException as exc:
            logger.error('Error processing keogram image: %s', exc)

    if startrails is not None:
        startrails.processImage(path, pixels, entry.binmode, adu=entry.adu if use_db_data else None,
                                star_count=entry.stars if use_db_data else None, align=align)


def horizon_edge(solution, azimuth, width, height):
    """Where a bearing meets the rectangular image border, seen from the zenith."""
    params = projection_values(solution)
    x, y = projectToPixels(np.array([math.pi / 2, 0.]), azimuth, params[:7], width, height,
                           lens_altitude=params[7], pointing_azimuth=params[8])
    dx, dy = x[1] - x[0], y[1] - y[0]
    # Clamp the origin inside the drawable image for very steep camera tilts.
    x0, y0 = np.clip(x[0], 0, width-1), np.clip(y[0], 0, height-1)
    edges = []
    if abs(dx) > 1e-8:
        edges.append(((width-1 if dx > 0 else 0) - x0) / dx)
    if abs(dy) > 1e-8:
        edges.append(((height-1 if dy > 0 else 0) - y0) / dy)
    t = min(edges, default=0)
    return int(round(x0 + t * dx)), int(round(y0 + t * dy))


class SkyRemap:
    """Cache one OpenCV lookup map. North is up, east left, zenith centered."""
    def __init__(self):
        self.key = None
        self.maps = None

    def image(self, image, solution, *, border=(0, 0, 0, 0)):
        h, w = image.shape[:2]
        final_w, final_h = solution['image_size']
        left, top, right, bottom = border
        params = projection_values(solution)
        args = (w, h, final_w, final_h, left, top, right, bottom, params)
        if args != self.key:
            self.maps = self._maps(*args)
            self.key = args
        return cv2.remap(image, *self.maps, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)

    @staticmethod
    def _maps(w, h, final_w, final_h, left, top, right, bottom, params):
        # Invert the output's centered equisolid model, then project that sky
        # direction into the actual lens. Work in strips on memory-limited Pis.
        map1 = np.empty((h, w, 2), np.int16)
        map2 = np.empty((h, w), np.uint16)
        x = (np.arange(w, dtype=np.float32) - w / 2) / (min(w, h) / 2)
        scale_x = w / (final_w - left - right)
        scale_y = h / (final_h - top - bottom)
        for start in range(0, h, 64):
            end = min(start + 64, h)
            y = (np.arange(start, end, dtype=np.float32)[:, None] - h / 2) / (min(w, h) / 2)
            radius = np.hypot(x, y)
            alt = np.pi / 2 - 2 * np.arcsin(np.minimum(1., radius) * SIN45)
            az = np.arctan2(-x, -y)
            sx, sy = projectToPixels(alt, az, params[:7], final_w, final_h,
                                     lens_altitude=params[7], pointing_azimuth=params[8])
            # cv2.resize samples at pixel centers. Undo scale and border when
            # working on the intermediate capture image before label rendering.
            sx = ((sx - left + .5) * scale_x - .5).astype(np.float32)
            sy = ((sy - top + .5) * scale_y - .5).astype(np.float32)
            sx[radius > 1.] = -2
            sy[radius > 1.] = -2
            map1[start:end], map2[start:end] = cv2.convertMaps(sx, sy, cv2.CV_16SC2)
        return map1, map2
