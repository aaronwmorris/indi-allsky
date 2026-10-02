"""Astrometry and lens solving tools for INDI Allsky MCP server."""

from typing import Any, Dict
import logging

logger = logging.getLogger('indi_allsky.mcp.astrometry')


def _get_flask_app():
    from ..flask import create_app
    return create_app()


def solve_lens_geometry(image_id: int) -> Dict[str, Any]:
    """Execute astrometric plate solving on an image capture to solve optical geometry.

    Calculates focal length, field of view, center pixel offsets (X, Y), and rotation azimuth.

    Args:
        image_id: Database ID of processed image frame to solve.

    Returns:
        Dictionary containing solved optical parameters, fitting residual error, and matched stars.
    """
    from ..flask.models import IndiAllSkyDbImageTable
    from ..config import IndiAllSkyConfig
    from ..lens_solver.solver import IndiAllSkyLensSolver

    app = _get_flask_app()
    with app.app_context():
        image_entry = IndiAllSkyDbImageTable.query.filter(
            IndiAllSkyDbImageTable.id == int(image_id)
        ).first()

        if not image_entry:
            return {"status": "error", "message": f"Image entry {image_id} not found."}

        try:
            filename_p = image_entry.getLocalOrCachedPath()
        except Exception as e:
            return {"status": "error", "message": f"Failed to resolve image file: {e}"}

        if not filename_p or not filename_p.is_file():
            return {"status": "error", "message": f"Image file {filename_p} does not exist on disk."}

        config_obj = IndiAllSkyConfig()
        cfg = dict(config_obj.config)

        # Build initial_values from the VIRTUALSKY config sub-section, which uses
        # the VirtualSky form-field key names that IndiAllSkyLensSolver.solve() expects.
        virtualsky_cfg = cfg.get("VIRTUALSKY", {})
        initial_values = {
            "CALIBRATION_ENABLED": virtualsky_cfg.get("CALIBRATION_ENABLED", False),
            "PRECESSION": virtualsky_cfg.get("PRECESSION", False),
            "RADIAL_DISTORTION": virtualsky_cfg.get("RADIAL_DISTORTION", 0.0),
            "IMAGE_CIRCLE_DIAMETER": virtualsky_cfg.get("IMAGE_CIRCLE_DIAMETER", 3500),
            "LATITUDE_OFFSET": virtualsky_cfg.get("LATITUDE_OFFSET", 0.0),
            "LONGITUDE_OFFSET": virtualsky_cfg.get("LONGITUDE_OFFSET", 0.0),
            "OFFSET_X": virtualsky_cfg.get("OFFSET_X", cfg.get("LENS_OFFSET_X", 0)),
            "OFFSET_Y": virtualsky_cfg.get("OFFSET_Y", cfg.get("LENS_OFFSET_Y", 0)),
            "AZIMUTH_ANGLE": cfg.get("LENS_AZIMUTH", 0.0),
        }

        try:
            import time
            lat = cfg.get("LATITUDE", 0.0)
            lon = cfg.get("LONGITUDE", 0.0)
            lens_altitude = cfg.get("LENS_ALTITUDE", 90.0)
            obstime_unix = (
                image_entry.createDate.timestamp()
                if hasattr(image_entry, 'createDate') and image_entry.createDate
                else time.time()
            )

            cam = image_entry.camera
            sensor_shape = None
            binning = image_entry.binmode or 1
            if cam and cam.width and cam.height:
                sensor_shape = (cam.height // binning, cam.width // binning)

            solver = IndiAllSkyLensSolver(cfg)
            solve_result = solver.solve(
                str(filename_p),
                lat,
                lon,
                obstime_unix,
                initial_values,
                lens_altitude=lens_altitude,
                pointing_azimuth=virtualsky_cfg.get("POINTING_AZIMUTH", 0.0),
                sensor_shape=sensor_shape,
                binning=binning,
            )

            if not solve_result or not solve_result.get("success"):
                err_msg = (
                    solve_result.get("message")
                    if solve_result and solve_result.get("message")
                    else (solve_result.get("reason") if solve_result else "Solver returned no result.")
                )
                return {
                    "status": "error",
                    "image_id": image_id,
                    "message": err_msg,
                    "quality": solve_result.get("quality", {}) if solve_result else {},
                }

            values = solve_result.get("values", {})
            quality = solve_result.get("quality", {})
            geometry = solve_result.get("geometry", {})
            return {
                "status": "success",
                "image_id": image_id,
                "focal_length": cfg.get("LENS_FOCAL_LENGTH", 2.5),
                "fov_deg": solve_result.get("fov_deg", 180.0),
                "lens_offset_x": values.get("OFFSET_X", initial_values["OFFSET_X"]),
                "lens_offset_y": values.get("OFFSET_Y", initial_values["OFFSET_Y"]),
                "lens_azimuth": values.get("AZIMUTH_ANGLE", initial_values["AZIMUTH_ANGLE"]),
                "lens_altitude": values.get("LENS_ALTITUDE", lens_altitude),
                "matched_stars": quality.get("stars_matched", 0),
                "residual_error": quality.get("rms_px", 0.0),
                "geometry": geometry,
                "message": solve_result.get("message", ""),
                "timing": solve_result.get("timing", {}),
            }
        except Exception as e:
            return {"status": "error", "message": f"Lens solver encountered error: {e}"}


def align_cardinal_directions(image_id: int) -> Dict[str, Any]:
    """Calculate true astronomical North alignment angle from solved star field.

    Args:
        image_id: Database ID of image frame.

    Returns:
        Dictionary with cardinal direction azimuth angle and True North deviation.
    """
    solve_res = solve_lens_geometry(image_id)
    if solve_res.get("status") != "success":
        return solve_res

    azimuth = solve_res.get("lens_azimuth", 0.0)
    return {
        "status": "success",
        "image_id": image_id,
        "true_north_azimuth": azimuth,
        "recommended_cardinal_dirs_azimuth": azimuth,
    }


def register_astrometry_tools(mcp_server: Any) -> None:
    """Register astrometry tools with the MCPServer instance."""
    mcp_server.tool()(solve_lens_geometry)
    mcp_server.tool()(align_cardinal_directions)
