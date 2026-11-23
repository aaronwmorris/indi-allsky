import math
import logging

import numpy as np

from ..lens_solver.projection import projectToPixels
from ..lens_solver.calibration import displacement, pipelineSignature, validateCalibration


logger = logging.getLogger('indi_allsky')


def satellite_title_matches_filter(title, include_raw, exclude_raw):
    """Return True if a TLE title passes comma-separated include/exclude substring filters."""
    title_lower = str(title or '').strip().lower()
    include_tokens = [t.strip().lower() for t in str(include_raw or '').split(',') if t.strip()]
    exclude_tokens = [t.strip().lower() for t in str(exclude_raw or '').split(',') if t.strip()]

    if include_tokens and not any(tok in title_lower for tok in include_tokens):
        return False
    if any(tok in title_lower for tok in exclude_tokens):
        return False
    return True


def _parse_rgb_color(color_val, default=(163, 230, 53)):
    """Parse an RGB 3-tuple from a list/tuple or comma-separated string."""
    if isinstance(color_val, str):
        parts = [p.strip() for p in color_val.split(',')]
    elif isinstance(color_val, (list, tuple)):
        parts = list(color_val)
    else:
        return default

    if len(parts) != 3:
        return default

    try:
        r, g, b = (max(0, min(255, int(c))) for c in parts)
        return (r, g, b)
    except (TypeError, ValueError):
        return default


def project_sky_objects(items, config, image_width, image_height, binning=1):
    """Project sky objects (alt/az deg) into image pixel coordinates.

    Returns a list of dicts: {'item': dict, 'x': float, 'y': float}.
    """
    if not items or image_width <= 0 or image_height <= 0:
        return []

    vs_cfg = config.get('VIRTUALSKY', {})
    calibration = vs_cfg.get('CALIBRATION')
    calibration_enabled = bool(vs_cfg.get('CALIBRATION_ENABLED', False))
    use_calibration = (
        calibration_enabled
        and calibration
        and validateCalibration(calibration)
        and calibration.get('pipeline') == pipelineSignature(config)
    )

    if use_calibration:
        geom = calibration['geometry']
        azimuth_deg = float(geom[0])
        diameter_px = float(geom[3])
        offset_x_px = float(geom[4])
        offset_y_px = float(geom[5])
        lens_altitude = float(geom[6])
        pointing_azimuth = float(geom[7])
        radial_distortion = float(geom[8]) if len(geom) > 8 else 0.0
        mirror = bool(geom[9]) if len(geom) > 9 else False
        cal_w, cal_h = calibration['image_size']
        if cal_w > 0 and cal_h > 0 and (cal_w != image_width or cal_h != image_height):
            scale_x = float(image_width) / float(cal_w)
            scale_y = float(image_height) / float(cal_h)
            diameter_px *= scale_y
            offset_x_px *= scale_x
            offset_y_px *= scale_y
    else:
        bin_val = max(1, int(binning or 1))
        azimuth_deg = float(config.get('LENS_AZIMUTH', 0.0))
        diameter_px = float(config.get('LENS_IMAGE_CIRCLE', 3000)) / bin_val
        offset_x_px = float(config.get('LENS_OFFSET_X', 0)) / bin_val
        offset_y_px = float(config.get('LENS_OFFSET_Y', 0)) / bin_val
        lens_altitude = float(config.get('LENS_ALTITUDE', 90.0))
        pointing_azimuth = float(vs_cfg.get('POINTING_AZIMUTH', 0.0))
        radial_distortion = float(vs_cfg.get('RADIAL_DISTORTION', 0.0))
        mirror = bool(config.get('IMAGE_FLIP_H', False))

    params = [
        azimuth_deg,
        0.0,
        0.0,
        diameter_px,
        offset_x_px,
        offset_y_px,
        radial_distortion,
    ]

    projected = []
    r_ref = image_height / 2.0

    for item in items:
        try:
            alt_deg = float(item['alt'])
            az_deg = float(item['az'])
        except (KeyError, TypeError, ValueError):
            continue

        x, y = projectToPixels(
            math.radians(alt_deg),
            math.radians(az_deg),
            params,
            image_width,
            image_height,
            mirror=mirror,
            lens_altitude=lens_altitude,
            pointing_azimuth=pointing_azimuth,
        )

        x_f = float(x)
        y_f = float(y)

        if use_calibration and r_ref > 0:
            u = (x_f - image_width / 2.0) / r_ref
            v = (y_f - image_height / 2.0) / r_ref
            delta = displacement(np.array([[u, v]], dtype=float), calibration)[0]
            x_f += float(delta[0]) * r_ref
            y_f += float(delta[1]) * r_ref

        if not (math.isfinite(x_f) and math.isfinite(y_f)):
            continue

        if 0 <= x_f < image_width and 0 <= y_f < image_height:
            projected.append({
                'item': item,
                'x': x_f,
                'y': y_f,
            })

    return projected


def _extract_label(item, label_keys):
    for key in label_keys:
        val = item.get(key)
        if val:
            return str(val)
    return ''


def draw_sky_reticles_opencv(
    image,
    items,
    overlay_cfg,
    config,
    binning=1,
    label_keys=('title', 'id'),
    default_color=(163, 230, 53),
):
    """Draw reticles for sky objects onto an OpenCV BGR image in place."""
    import cv2

    if not overlay_cfg.get('OVERLAY_ENABLE', False):
        return 0

    image_height, image_width = image.shape[:2]
    positions = project_sky_objects(items, config, image_width, image_height, binning=binning)
    if not positions:
        return 0

    style = str(overlay_cfg.get('OVERLAY_STYLE', 'circle')).lower()
    radius = max(4, int(overlay_cfg.get('OVERLAY_RADIUS', 15)))
    thickness = max(1, int(overlay_cfg.get('OVERLAY_THICKNESS', 2)))
    show_label = bool(overlay_cfg.get('OVERLAY_LABEL_ENABLE', True))
    r, g, b = _parse_rgb_color(overlay_cfg.get('OVERLAY_COLOR', default_color), default=default_color)
    color_bgr = (b, g, r)

    for entry in positions:
        cx = int(round(entry['x']))
        cy = int(round(entry['y']))

        if style in ('circle', 'both'):
            cv2.circle(image, (cx, cy), radius, color_bgr, thickness, cv2.LINE_AA)
        if style in ('cross', 'both'):
            cv2.drawMarker(
                image,
                (cx, cy),
                color_bgr,
                markerType=cv2.MARKER_CROSS,
                markerSize=radius * 2,
                thickness=thickness,
                line_type=cv2.LINE_AA,
            )

        if show_label:
            label = _extract_label(entry['item'], label_keys)
            if label:
                tx = min(image_width - 10, cx + radius + 4)
                ty = max(15, cy + 4)
                cv2.putText(
                    image,
                    label,
                    (tx, ty),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    color_bgr,
                    max(1, thickness - 1),
                    cv2.LINE_AA,
                )

    return len(positions)


def draw_sky_reticles_pillow(
    draw,
    image_size,
    items,
    overlay_cfg,
    config,
    font=None,
    binning=1,
    label_keys=('title', 'id'),
    default_color=(163, 230, 53),
):
    """Draw reticles for sky objects onto a Pillow ImageDraw surface."""
    if not overlay_cfg.get('OVERLAY_ENABLE', False):
        return 0

    image_width, image_height = image_size
    positions = project_sky_objects(items, config, image_width, image_height, binning=binning)
    if not positions:
        return 0

    style = str(overlay_cfg.get('OVERLAY_STYLE', 'circle')).lower()
    radius = max(4, int(overlay_cfg.get('OVERLAY_RADIUS', 15)))
    thickness = max(1, int(overlay_cfg.get('OVERLAY_THICKNESS', 2)))
    show_label = bool(overlay_cfg.get('OVERLAY_LABEL_ENABLE', True))
    color_rgb = _parse_rgb_color(overlay_cfg.get('OVERLAY_COLOR', default_color), default=default_color)

    for entry in positions:
        cx = int(round(entry['x']))
        cy = int(round(entry['y']))

        if style in ('circle', 'both'):
            draw.ellipse(
                (cx - radius, cy - radius, cx + radius, cy + radius),
                outline=color_rgb,
                width=thickness,
            )
        if style in ('cross', 'both'):
            draw.line((cx - radius, cy, cx + radius, cy), fill=color_rgb, width=thickness)
            draw.line((cx, cy - radius, cx, cy + radius), fill=color_rgb, width=thickness)

        if show_label:
            label = _extract_label(entry['item'], label_keys)
            if label:
                tx = min(image_width - 10, cx + radius + 4)
                ty = max(5, cy - 6)
                draw.text((tx, ty), label, fill=color_rgb, font=font)

    return len(positions)
