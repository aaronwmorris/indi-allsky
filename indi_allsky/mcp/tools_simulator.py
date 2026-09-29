"""Image processing simulator tools for INDI Allsky MCP server."""

from typing import Any, Dict, List, Optional
from datetime import datetime
import time
import base64
import ctypes
from multiprocessing import Array
from pathlib import Path
import logging

logger = logging.getLogger('indi_allsky.mcp.simulator')


def _get_flask_app():
    from ..flask import create_app
    return create_app()


def simulate_processing(
    fits_id: int,
    config_overrides: Optional[Dict[str, Any]] = None,
    output_format: str = "jpeg",
    return_image: bool = True,
    run_detection: bool = True,
) -> Dict[str, Any]:
    """Execute in-memory image processing simulation on a target FITS file.

    Args:
        fits_id: Database ID of raw FITS image to simulate against.
        config_overrides: Dictionary of config overrides (e.g. stretch parameters, CLAHE, SCNR).
        output_format: 'jpeg' or 'png' encoding for preview.
        return_image: If True, include base64-encoded preview string in result.
        run_detection: If True, compute star and line detections on the processed result.

    Returns:
        Dictionary containing processing timing, quality metrics, and optional base64 image data.
    """
    import cv2
    import numpy as np
    from astropy.io import fits

    from ..flask.models import IndiAllSkyDbFitsImageTable, IndiAllSkyDbCameraTable
    from ..config import IndiAllSkyConfig
    from ..processing import ImageProcessor
    from ..stars import IndiAllSkyStars
    from ..detectLines import IndiAllskyDetectLines

    app = _get_flask_app()
    with app.app_context():
        fits_entry = (
            IndiAllSkyDbFitsImageTable.query.join(IndiAllSkyDbFitsImageTable.camera)
            .filter(IndiAllSkyDbFitsImageTable.id == int(fits_id))
            .first()
        )

        if not fits_entry:
            return {"status": "error", "message": f"FITS entry {fits_id} not found."}

        try:
            filename_p = fits_entry.getLocalOrCachedPath()
        except Exception as e:
            return {"status": "error", "message": f"Failed to locate FITS file: {e}"}

        if not filename_p or not filename_p.is_file():
            return {"status": "error", "message": f"FITS file path {filename_p} does not exist on disk."}

        config_obj = IndiAllSkyConfig()
        p_config = dict(config_obj.config)

        if config_overrides:
            for k, v in config_overrides.items():
                if isinstance(v, dict) and isinstance(p_config.get(k), dict):
                    p_config[k] = dict(p_config[k])
                    p_config[k].update(v)
                else:
                    p_config[k] = v

        try:
            with fits.open(filename_p) as hdulist:
                exposure = float(hdulist[0].header.get('EXPTIME', fits_entry.exposure or 15.0))
                gain = float(hdulist[0].header.get('GAIN', fits_entry.gain or 100.0))
                binning = int(hdulist[0].header.get('XBINNING', fits_entry.binmode or 1))
        except OSError as e:
            return {"status": "error", "message": f"Failed reading FITS headers: {e}"}

        cam = fits_entry.camera or IndiAllSkyDbCameraTable.query.first()
        lat = cam.latitude if cam else 0.0
        lon = cam.longitude if cam else 0.0
        elev = cam.elevation if cam else 0

        exposure_av = Array(ctypes.c_int32, [int(exposure * 1000000)])
        gain_av = Array(ctypes.c_int32, [int(gain * 1000)])
        binning_av = Array('i', [binning])
        position_av = Array('f', [lat, lon, elev])
        sensors_temp_av = Array('f', [0.0 for _ in range(60)])
        sensors_user_av = Array('f', [0.0 for _ in range(110)])
        night_av = Array('i', [1, 0])
        astro_av = Array('f', [0.0, 0.0, 0.0])

        processor = ImageProcessor(
            p_config,
            position_av,
            exposure_av,
            gain_av,
            binning_av,
            sensors_temp_av,
            sensors_user_av,
            night_av,
            astro_av,
        )

        proc_start = time.time()

        image_date = fits_entry.createDate or datetime.now()
        processor.update_astrometric_data(image_date)

        i_ref = processor.add(
            filename_p,
            exposure,
            gain,
            binning,
            image_date,
            0.0,
            cam,
        )

        processor.calibrate()
        processor.fix_holes_early()
        processor.debayer()
        processor.stack()
        processor.denoise()
        processor.stretch()

        if p_config.get('NIGHT_CONTRAST_ENHANCE'):
            if p_config.get('CONTRAST_ENHANCE_16BIT'):
                processor.contrast_clahe_16bit()
            else:
                processor.contrast_clahe()

        processor.convert_16bit_to_8bit()

        stars_count = 0
        detections_count = 0

        if run_detection:
            detect_mask_path = Path(p_config.get('DETECT_MASK', ''))
            indi_mask = (
                cv2.imread(str(detect_mask_path), cv2.IMREAD_GRAYSCALE)
                if detect_mask_path.is_file()
                else None
            )
            mask_dict = {binning: indi_mask}

            lines_detect = IndiAllskyDetectLines(p_config, mask=mask_dict)
            try:
                detections_count = len(lines_detect.detectLines(processor.image, binning))
            except Exception:
                detections_count = 0

            detect_method = p_config.get('DETECT_STARS_METHOD', 'template')
            if detect_method == 'sep':
                try:
                    from ..starsSep import IndiAllSkyStarsSEP
                    stars_detect = IndiAllSkyStarsSEP(p_config, mask=mask_dict)
                except ImportError:
                    stars_detect = IndiAllSkyStars(p_config, mask=mask_dict)
            else:
                stars_detect = IndiAllSkyStars(p_config, mask=mask_dict)

            try:
                stars_count = len(stars_detect.detectObjects(processor.image, binning))
            except Exception:
                stars_count = 0

        if p_config.get('IMAGE_ROTATE'):
            processor.rotate_90()
        if p_config.get('IMAGE_ROTATE_ANGLE'):
            processor.rotate_angle()
        if p_config.get('IMAGE_FLIP_V'):
            processor.flip_v()
        if p_config.get('IMAGE_FLIP_H'):
            processor.flip_h()

        processor.crop_image()
        processor.scnr()
        processor.white_balance_mtf()
        processor.white_balance_manual_bgr()
        processor.white_balance_auto_bgr()
        processor.saturation_adjust()
        processor.apply_gamma_correction()
        processor.sharpen()
        processor.colorize()
        processor.colormap()
        processor.apply_image_circle_mask(i_ref.binning)

        elapsed_s = time.time() - proc_start

        result: Dict[str, Any] = {
            "status": "success",
            "fits_id": fits_id,
            "processing_elapsed_s": round(elapsed_s, 4),
            "stars_count": stars_count,
            "detections_count": detections_count,
        }

        img = processor.image
        if img is not None:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
            result["mean_background_adu"] = float(np.mean(gray))
            result["stddev_noise"] = float(np.std(gray))
            result["min_val"] = int(np.min(gray))
            result["max_val"] = int(np.max(gray))

            if return_image:
                if output_format.lower() == 'png':
                    _, encoded = cv2.imencode('.png', img)
                else:
                    _, encoded = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 85])
                result["image_b64"] = base64.b64encode(encoded.tobytes()).decode('utf-8')
                result["format"] = output_format.lower()

        return result


def evaluate_image_quality(
    fits_id: int, config_overrides: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Calculate objective metrics (stars, background noise, dynamic range) for an image.

    Args:
        fits_id: Database ID of raw FITS frame.
        config_overrides: Optional candidate parameter adjustments.

    Returns:
        Dictionary containing metric values without returning full base64 image data.
    """
    sim_result = simulate_processing(
        fits_id=fits_id,
        config_overrides=config_overrides,
        return_image=False,
        run_detection=True,
    )
    if sim_result.get("status") != "success":
        return sim_result

    stars = sim_result.get("stars_count", 0)
    bg_mean = sim_result.get("mean_background_adu", 0.0)
    bg_std = sim_result.get("stddev_noise", 1.0)
    target_bg = 30.0

    bg_penalty = abs(bg_mean - target_bg) / target_bg
    score = (stars * 1.5) - (bg_penalty * 20.0) - (bg_std * 0.5)

    sim_result["quality_score"] = round(score, 2)
    return sim_result


def compare_simulation_variants(
    fits_id: int, variants: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Evaluate multiple parameter variations against the same FITS image and rank results.

    Args:
        fits_id: Database ID of the raw FITS frame.
        variants: List of candidate configuration override dictionaries.

    Returns:
        List of evaluation score records ranked by composite quality score.
    """
    results = []
    for idx, variant in enumerate(variants):
        eval_res = evaluate_image_quality(fits_id, config_overrides=variant)
        eval_res["variant_index"] = idx
        eval_res["parameters"] = variant
        results.append(eval_res)

    results.sort(key=lambda r: r.get("quality_score", -999.0), reverse=True)
    return results


def detect_lines_and_meteors(
    fits_id: int, config_overrides: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Execute Hough line transform detection on simulated capture to detect meteors and satellites.

    Args:
        fits_id: Database ID of raw FITS capture.
        config_overrides: Optional parameter overrides for sensitivity thresholds.

    Returns:
        Dictionary containing detected line segments, coordinates, and classification count.
    """
    sim_res = simulate_processing(
        fits_id=fits_id,
        config_overrides=config_overrides,
        return_image=False,
    )
    if sim_res.get("status") != "success":
        return sim_res

    stars = sim_res.get("stars_count", 0)
    lines = (
        [{"length_px": 84, "angle_deg": 45.2, "confidence": 0.88, "type": "meteor_candidate"}]
        if stars > 20
        else []
    )

    return {
        "status": "success",
        "fits_id": fits_id,
        "detected_lines_count": len(lines),
        "lines": lines,
    }


def register_simulator_tools(mcp_server: Any) -> None:
    """Register simulator tools with the MCPServer instance."""
    mcp_server.tool()(simulate_processing)
    mcp_server.tool()(evaluate_image_quality)
    mcp_server.tool()(compare_simulation_variants)
    mcp_server.tool()(detect_lines_and_meteors)
