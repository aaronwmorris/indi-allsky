"""Image catalog and telemetry tools for INDI Allsky MCP server."""

from typing import Any, Dict, List, Optional
from datetime import datetime
import logging

logger = logging.getLogger('indi_allsky.mcp.images')


def _get_flask_app():
    from ..flask import create_app
    return create_app()


def get_latest_image(camera_id: int = 1, include_raw: bool = False) -> Dict[str, Any]:
    """Retrieve metadata and file path of the most recently captured image.

    Args:
        camera_id: Primary key ID of the camera (default: 1).
        include_raw: Whether to also resolve the corresponding raw FITS frame.

    Returns:
        Dictionary containing image capture timestamp, exposure, gain, ADU, and file paths.
    """
    from ..flask.models import IndiAllSkyDbImageTable, IndiAllSkyDbFitsImageTable

    app = _get_flask_app()
    with app.app_context():
        image_entry = (
            IndiAllSkyDbImageTable.query.filter(IndiAllSkyDbImageTable.camera_id == camera_id)
            .order_by(IndiAllSkyDbImageTable.createDate.desc())
            .first()
        )

        if not image_entry:
            return {"status": "error", "message": f"No images found for camera {camera_id}"}

        result: Dict[str, Any] = {
            "status": "success",
            "image_id": image_entry.id,
            "filename": image_entry.filename,
            "createDate": image_entry.createDate.isoformat() if image_entry.createDate else None,
            "dayDate": image_entry.dayDate.isoformat() if image_entry.dayDate else None,
            "exposure": image_entry.exposure,
            "gain": image_entry.gain,
            "binmode": image_entry.binmode,
            "temp": image_entry.temp,
            "night": image_entry.night,
            "adu": image_entry.adu,
            "sqm": image_entry.sqm,
            "stars": image_entry.stars,
            "detections": image_entry.detections,
            "moonphase": image_entry.moonphase,
        }

        if include_raw:
            fits_entry = (
                IndiAllSkyDbFitsImageTable.query.filter(
                    IndiAllSkyDbFitsImageTable.camera_id == camera_id
                )
                .order_by(IndiAllSkyDbFitsImageTable.createDate.desc())
                .first()
            )
            if fits_entry:
                result["latest_fits_id"] = fits_entry.id
                result["latest_fits_filename"] = fits_entry.filename

        return result


def query_image_history(
    camera_id: int = 1,
    limit: int = 20,
    night_only: bool = True,
    min_stars: Optional[int] = None,
    day_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query historical light frame captures filtered by observational criteria.

    Args:
        camera_id: Camera ID to filter on (default: 1).
        limit: Maximum records to return (default: 20).
        night_only: Filter strictly for night exposures.
        min_stars: Minimum detected stars threshold.
        day_date: Specific observation day in 'YYYY-MM-DD' format.

    Returns:
        List of image records matching criteria.
    """
    from ..flask.models import IndiAllSkyDbImageTable

    app = _get_flask_app()
    with app.app_context():
        query = IndiAllSkyDbImageTable.query.filter(
            IndiAllSkyDbImageTable.camera_id == camera_id
        )

        if night_only:
            query = query.filter(IndiAllSkyDbImageTable.night == True)  # noqa: E712

        if min_stars is not None:
            query = query.filter(IndiAllSkyDbImageTable.stars >= int(min_stars))

        if day_date:
            try:
                target_date = datetime.strptime(day_date, "%Y-%m-%d").date()
                query = query.filter(IndiAllSkyDbImageTable.dayDate == target_date)
            except ValueError:
                pass

        entries = query.order_by(IndiAllSkyDbImageTable.createDate.desc()).limit(limit).all()

        results = []
        for e in entries:
            results.append(
                {
                    "id": e.id,
                    "filename": e.filename,
                    "createDate": e.createDate.isoformat() if e.createDate else None,
                    "exposure": e.exposure,
                    "gain": e.gain,
                    "binmode": e.binmode,
                    "temp": e.temp,
                    "night": e.night,
                    "adu": e.adu,
                    "sqm": e.sqm,
                    "stars": e.stars,
                    "detections": e.detections,
                }
            )
        return results


def get_raw_fits_catalog(
    camera_id: int = 1, limit: int = 20, day_date: Optional[str] = None
) -> List[Dict[str, Any]]:
    """List available raw FITS frames for simulation and quality analysis.

    Args:
        camera_id: Camera ID (default: 1).
        limit: Max frames to list.
        day_date: Observation date in 'YYYY-MM-DD' format.

    Returns:
        List of raw FITS metadata records.
    """
    from ..flask.models import IndiAllSkyDbFitsImageTable

    app = _get_flask_app()
    with app.app_context():
        query = IndiAllSkyDbFitsImageTable.query.filter(
            IndiAllSkyDbFitsImageTable.camera_id == camera_id
        )

        if day_date:
            try:
                target_date = datetime.strptime(day_date, "%Y-%m-%d").date()
                query = query.filter(IndiAllSkyDbFitsImageTable.dayDate == target_date)
            except ValueError:
                pass

        entries = (
            query.order_by(IndiAllSkyDbFitsImageTable.createDate.desc()).limit(limit).all()
        )

        results = []
        for e in entries:
            results.append(
                {
                    "fits_id": e.id,
                    "filename": e.filename,
                    "createDate": e.createDate.isoformat() if e.createDate else None,
                    "dayDate": e.dayDate.isoformat() if e.dayDate else None,
                    "exposure": e.exposure,
                    "gain": e.gain,
                    "binmode": e.binmode,
                    "night": e.night,
                    "fileSize": e.fileSize,
                }
            )
        return results


def get_image_metadata(fits_id: int) -> Dict[str, Any]:
    """Retrieve full capture and astronomical metadata for a given FITS file.

    Args:
        fits_id: Primary key ID of the FITS frame.

    Returns:
        Dictionary containing FITS headers, astronomical calculations, and hardware conditions.
    """
    from ..flask.models import IndiAllSkyDbFitsImageTable

    app = _get_flask_app()
    with app.app_context():
        entry = IndiAllSkyDbFitsImageTable.query.filter(
            IndiAllSkyDbFitsImageTable.id == int(fits_id)
        ).first()

        if not entry:
            return {"status": "error", "message": f"FITS image with ID {fits_id} not found."}

        return {
            "status": "success",
            "fits_id": entry.id,
            "filename": entry.filename,
            "createDate": entry.createDate.isoformat() if entry.createDate else None,
            "dayDate": entry.dayDate.isoformat() if entry.dayDate else None,
            "exposure": entry.exposure,
            "gain": entry.gain,
            "binmode": entry.binmode,
            "night": entry.night,
            "fileSize": entry.fileSize,
            "width": entry.width,
            "height": entry.height,
            "data": entry.data or {},
        }


def register_image_tools(mcp_server: Any) -> None:
    """Register image tools with the MCPServer instance."""
    mcp_server.tool()(get_latest_image)
    mcp_server.tool()(query_image_history)
    mcp_server.tool()(get_raw_fits_catalog)
    mcp_server.tool()(get_image_metadata)
